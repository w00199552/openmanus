/**
 * eventReducer — pure functions: an SSE event + current messages → new messages.
 *
 * This is the SINGLE authoritative definition of "how an event becomes a
 * message". It is:
 *   - pure (no side effects, no mutation of inputs — every reducer returns a
 *     fresh array with fresh message/part references)
 *   - dependency-free (no mobx, no React, no network)
 *   - unit-testable in isolation
 *
 * All immutable replacement lives HERE. This centralisation is deliberate:
 * the previous design scattered `last.text += delta` style in-place writes
 * across several store methods, which mobx/React-19 did not observe reliably
 * (streaming appeared to arrive all-at-once). Funneling every mutation
 * through these pure builders guarantees a new reference per delta, which
 * every reactive layer observes correctly.
 *
 * @module runtime/eventReducer
 */

// ─── types (JSDoc) ─────────────────────────────────────────────────────────
/**
 * @typedef {Object} Event — one SSE frame from the backend (see event_schema.py)
 * @property {string} kind
 * @property {string} [session_id]
 * @property {string} [message_id]
 * @property {string} [speaker]
 * @property {string} [delta]          — text/thinking delta
 * @property {string} [call_id]        — tool call id
 * @property {string} [tool]           — tool name
 * @property {string} [args_json]      — streamed tool args fragment
 * @property {string} [result]         — tool result content
 * @property {Object} [mailbox]        — inter-agent message payload
 * @property {string} [message]        — error text
 */

/**
 * @typedef {Object} Message
 * @property {string} id
 * @property {"user"|"assistant"} role
 * @property {string} speaker          — who produced it (user / agent name)
 * @property {string} [thinking]       — reasoning trace (GLM reasoning_content)
 * @property {Part[]} content
 * @property {"streaming"|"complete"|"error"} status
 * @property {number} [createdAt]
 */

/**
 * @typedef {Object} Part
 * @property {"text"|"tool-call"} type
 * @property {string} [text]                  — for text parts
 * @property {string} [toolCallId]            — for tool-call parts
 * @property {string} [toolName]
 * @property {string} [args]
 * @property {string} [result]
 * @property {boolean} [_streaming]           — tool call still in progress
 */

// ─── the dispatch table ────────────────────────────────────────────────────

/**
 * Apply one event to a message array, returning a NEW array (immutable).
 *
 * Unknown event kinds are returned unchanged. Reducers never mutate `messages`.
 *
 * @param {Message[]} messages
 * @param {Event} event
 * @returns {Message[]}
 */
export function reduceEvent(messages, event) {
  switch (event.kind) {
    case "message_start":
      return ensureMessage(messages, event.message_id, event.speaker || "assistant");
    case "text_delta":
      return reduceTextDelta(messages, event);
    case "thinking_delta":
      return reduceThinkingDelta(messages, event);
    case "message_end":
      return reduceMessageEnd(messages, event);
    case "tool_call_start":
      return reduceToolCallStart(messages, event);
    case "tool_call_args":
      return reduceToolCallArgs(messages, event);
    case "tool_call_result":
      return reduceToolCallResult(messages, event);
    case "tool_call_end":
      return reduceToolCallEnd(messages, event);
    case "mailbox":
      return reduceMailbox(messages, event);
    case "done":
    case "step_start":
    case "step_end":
      return messages; // no message mutation; lifecycle handled by the runtime
    default:
      return messages;
  }
}

// ─── text / thinking ───────────────────────────────────────────────────────

/** Append a text delta to the message's last open text part (or open one). */
function reduceTextDelta(messages, event) {
  const ms = ensureMessage(messages, event.message_id, event.speaker || "assistant");
  return replaceMessage(ms, event.message_id, (m) => {
    const parts = m.content;
    const last = parts[parts.length - 1];
    if (last && last.type === "text") {
      // extend the open text part with a fresh ref
      const newParts = parts.slice(0, -1);
      newParts.push({ ...last, text: last.text + (event.delta || "") });
      return { ...m, content: newParts };
    }
    return { ...m, content: [...parts, { type: "text", text: event.delta || "" }] };
  });
}

/** Append a reasoning/thinking delta to the message's thinking field. */
function reduceThinkingDelta(messages, event) {
  const ms = ensureMessage(messages, event.message_id, event.speaker || "assistant");
  return replaceMessage(ms, event.message_id, (m) => ({
    ...m,
    thinking: (m.thinking || "") + (event.delta || ""),
  }));
}

/** Mark a message complete (status streaming → complete). */
function reduceMessageEnd(messages, event) {
  return replaceMessage(messages, event.message_id, (m) => ({ ...m, status: "complete" }));
}

// ─── tool calls ────────────────────────────────────────────────────────────

/** Open a new tool-call part on the message. */
function reduceToolCallStart(messages, event) {
  const ms = ensureMessage(messages, event.message_id, event.speaker || "assistant");
  return replaceMessage(ms, event.message_id, (m) => ({
    ...m,
    content: [
      ...m.content,
      {
        type: "tool-call",
        toolCallId: event.call_id,
        toolName: event.tool || "tool",
        args: "",
        result: null,
        _streaming: true,
      },
    ],
  }));
}

/** Append a streamed args fragment to the matching tool-call part. */
function reduceToolCallArgs(messages, event) {
  return replaceToolPart(messages, event.call_id, (p) => ({
    ...p,
    args: (p.args || "") + (event.args_json || ""),
  }));
}

/** Set the result of a tool-call part. */
function reduceToolCallResult(messages, event) {
  return replaceToolPart(messages, event.call_id, (p) => ({
    ...p,
    result: event.result,
  }));
}

/** Mark a tool-call part as no longer streaming. */
function reduceToolCallEnd(messages, event) {
  return replaceToolPart(messages, event.call_id, (p) => ({ ...p, _streaming: false }));
}

// ─── mailbox (inter-agent messages rendered as a bubble) ───────────────────

/** An inter-agent message arriving live → a distinct assistant bubble. */
function reduceMailbox(messages, event) {
  const mb = event.mailbox || {};
  // Prefer the sender's role name (e.g. "Coder"); fall back to session id
  // prefix only if the backend couldn't resolve it.
  const from = mb.from_name || String(mb.from_session_id || "").slice(0, 8);
  const text =
    mb.kind === "result"
      ? `✅ ${(mb.content || "").slice(0, 160)}`
      : mb.kind === "dispatch"
        ? `📋 ${(mb.content || "").slice(0, 120)}`
        : `💬 ${(mb.content || "").slice(0, 200)}`;
  const msg = {
    id: `mb-${mb.id}`,
    role: "assistant",
    speaker: `agent:${from}`,
    content: [{ type: "text", text }],
    status: "complete",
    createdAt: Date.now(),
  };
  // dedupe by id (a mailbox frame could be re-delivered)
  if (messages.some((m) => m.id === msg.id)) return messages;
  return [...messages, msg];
}

// ─── immutable helpers (the heart of the streaming fix) ────────────────────

/**
 * Ensure a message with `messageId` exists (idempotent). Returns a NEW array
 * if a message was added, otherwise the same array reference.
 *
 * @param {Message[]} messages
 * @param {string} messageId
 * @param {string} speaker
 * @returns {Message[]}
 */
export function ensureMessage(messages, messageId, speaker) {
  if (messageId && messages.some((m) => m.id === messageId)) return messages;
  const msg = {
    id: messageId || `a-${Date.now()}`,
    role: "assistant",
    speaker,
    thinking: "",
    content: [],
    status: "streaming",
    createdAt: Date.now(),
  };
  return [...messages, msg];
}

/**
 * Immutably replace one message (matched by id) with the result of `updater`.
 * If not found, returns the array unchanged.
 *
 * @param {Message[]} messages
 * @param {string} messageId
 * @param {(m: Message) => Message} updater
 * @returns {Message[]}
 */
export function replaceMessage(messages, messageId, updater) {
  const i = messages.findIndex((m) => m.id === messageId);
  if (i < 0) return messages;
  const next = messages.slice();
  next[i] = updater(messages[i]);
  return next;
}

/**
 * Immutably replace one tool-call part (matched by toolCallId) within whatever
 * message holds it. If not found, returns the array unchanged.
 *
 * @param {Message[]} messages
 * @param {string} callId
 * @param {(p: Part) => Part} updater
 * @returns {Message[]}
 */
export function replaceToolPart(messages, callId, updater) {
  for (let mi = messages.length - 1; mi >= 0; mi--) {
    const parts = messages[mi].content || [];
    for (let pi = parts.length - 1; pi >= 0; pi--) {
      if (parts[pi].type === "tool-call" && parts[pi].toolCallId === callId) {
        const newParts = parts.slice();
        newParts[pi] = updater(parts[pi]);
        const next = messages.slice();
        next[mi] = { ...messages[mi], content: newParts };
        return next;
      }
    }
  }
  return messages;
}
