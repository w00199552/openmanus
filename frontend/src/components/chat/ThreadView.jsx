import { useState, useRef, useEffect } from "react";
import { observer } from "mobx-react-lite";
import { ChevronRight, ChevronDown, Wrench, Loader2, Brain } from "lucide-react";

import { Avatar } from "@/components/Avatar";

/**
 * ThreadView — a PURE presentational chat surface (no assistant-ui runtime).
 *
 * Receives a `messages` array (Message[] from the runtime's eventReducer) and
 * renders it with our cinematic dark theme + DiceBear avatars + collapsible
 * reasoning + tool fences. It has no data dependency: whoever owns the messages
 * (agentRuntime.activeMessages) just hands them in.
 *
 * Message shape (see runtime/eventReducer.js):
 *   { id, role:'user'|'assistant', speaker, thinking?, content: Part[], status }
 *   Part: { type:'text', text } | { type:'tool-call', toolCallId, toolName, args, result, _streaming }
 *
 * @param {{ messages: import("@/runtime/eventReducer").Message[], session?: object }} props
 */
export const ThreadView = observer(function ThreadView({ messages = [], session }) {
  const scrollRef = useRef(null);
  const stickToBottom = useRef(true);

  // Auto-scroll: stick to bottom as new content streams in, unless the user
  // scrolled up to read history. Resumes stick-to-bottom near the bottom.
  const last = messages[messages.length - 1];
  const fingerprint = `${messages.length}:${last?.content?.length || 0}:${(last?.thinking || "").length}`;
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [fingerprint]);

  if (!messages.length) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <p className="text-sm text-muted-foreground">
          What would you like to build or change today?
        </p>
      </div>
    );
  }
  return (
    <div
      ref={scrollRef}
      className="h-full overflow-y-auto"
      onScroll={(e) => {
        const el = e.currentTarget;
        stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }}
    >
      <div className="content-narrow px-2 py-4">
        {messages.map((m) => (
          <MessageRow key={m.id} message={m} session={session} />
        ))}
      </div>
    </div>
  );
});

/** Dispatch a message to its renderer by role. */
function MessageRow({ message, session }) {
  if (message.role === "user") return <UserMessage message={message} session={session} />;
  return <AssistantMessage message={message} session={session} />;
}

/**
 * A user-authored message bubble — right-aligned (chat-bubble style).
 *
 * For a sub-agent session, the "user" message isn't from the human — it's the
 * TASK the parent agent (e.g. Manus) delegated. So we label it with the
 * delegator's identity (default "Manus") instead of "you", to reflect who
 * actually sent the task to this agent.
 */
function UserMessage({ message, session }) {
  const text = extractText(message);
  const isDelegated = session?.kind === "subagent";
  const label = isDelegated ? "Manus" : "you";
  const avatarSeed = isDelegated ? "manus-open" : "user-face";
  return (
    <div className="anim-rise mb-5 flex justify-end gap-3">
      <div className="min-w-0 max-w-[80%]">
        <p className="mb-1 text-right text-[11px] font-medium text-muted-foreground">{label}</p>
        <div className="rounded-2xl rounded-tr-sm bg-accent/15 px-3.5 py-2">
          <p className="whitespace-pre-wrap break-words text-[14px] leading-relaxed text-foreground">
            {text}
          </p>
        </div>
      </div>
      <div className="mt-0.5 shrink-0">
        <Avatar seed={avatarSeed} size={28} />
      </div>
    </div>
  );
}

/** An assistant message: avatar + thinking + interleaved text/tool parts.
 *
 * deepagents emits text→tool→text→tool within ONE turn (shared message_id),
 * so we render the content parts IN ORDER (not "all text then all tools") to
 * preserve the real working sequence: think, act, think, act.
 */
const AssistantMessage = observer(function AssistantMessage({ message, session }) {
  const speaker = message.speaker || "assistant";
  const seed = speakerSeed(speaker, session);
  const label = speakerLabel(speaker, session);
  const thinking = message.thinking || "";
  const parts = message.content || [];
  const streaming = message.status === "streaming";
  const hasContent = parts.some((p) => (p.type === "text" && p.text) || p.type === "tool-call");
  const onlyThinking = streaming && !hasContent;
  return (
    <div className="anim-rise mb-5 flex gap-3">
      <div className="mt-0.5 shrink-0">
        <Avatar seed={seed} size={28} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-[11px] font-medium text-muted-foreground">
          {label}
          {streaming && (
            <span className="ml-1.5 inline-flex items-center gap-1 text-accent">
              <Loader2 className="size-3 animate-spin" />
            </span>
          )}
        </p>
        {thinking && <ThinkingBlock text={thinking} live={onlyThinking || (!hasContent && streaming)} />}
        {onlyThinking && !thinking && (
          <p className="text-[13px] text-muted-foreground">thinking…</p>
        )}
        {/* render parts IN ORDER: text + tool-call interleaved */}
        {parts.map((part, i) => {
          if (part.type === "text" && part.text) {
            return (
              <p key={`t-${i}`} className="whitespace-pre-wrap break-words text-[14px] leading-relaxed text-foreground">
                {part.text}
              </p>
            );
          }
          if (part.type === "tool-call") {
            return <ToolFence key={part.toolCallId || `f-${i}`} tool={part} />;
          }
          return null;
        })}
      </div>
    </div>
  );
});

/**
 * A collapsible reasoning/thinking region shown above the answer.
 * Live (streaming) → expanded by default with a spinner; finished → collapsible,
 * collapsed by default so past reasoning stays reviewable but out of the way.
 */
const ThinkingBlock = observer(function ThinkingBlock({ text, live }) {
  const [open, setOpen] = useState(live);
  const thinkRef = useRef(null);
  if (live && !open) setOpen(true);
  // auto-scroll the thinking content to bottom while streaming
  useEffect(() => {
    const el = thinkRef.current;
    if (el && open) el.scrollTop = el.scrollHeight;
  }, [text, open]);
  return (
    <div className="mb-2 rounded-md border border-border/40 bg-sidebar/30">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-[12px] text-muted-foreground/80 transition hover:text-foreground"
      >
        {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
        <Brain className="size-3 text-muted-foreground/60" />
        <span>{live ? "思考中" : "思考过程"}</span>
        {live && <Loader2 className="ml-1 size-3 animate-spin text-muted-foreground/50" />}
      </button>
      {open && (
        <p
          ref={thinkRef}
          className="max-h-72 overflow-y-auto whitespace-pre-wrap border-t border-border/40 px-2.5 py-2 font-mono text-[11.5px] leading-relaxed text-muted-foreground/70"
        >
          {text}
        </p>
      )}
    </div>
  );
});

/** A tool-call rendered as a collapsible fence (name + args + result). */
const ToolFence = observer(function ToolFence({ tool }) {
  const [open, setOpen] = useState(false);
  const running = tool && tool.result == null && !tool.isError && tool._streaming;
  return (
    <div className="my-1.5">
      <div className="rounded-md border border-border/60 bg-card/60">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:text-foreground"
        >
          {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
          <Wrench className="size-3 text-accent" />
          <span className="font-mono">{tool?.toolName || "tool"}</span>
          {running ? (
            <Loader2 className="ml-auto size-3 animate-spin text-accent" />
          ) : tool?.result != null ? (
            <span className="ml-auto size-1.5 rounded-full bg-accent ring-2 ring-accent/20" />
          ) : null}
        </button>
        {open && (
          <pre className="max-h-60 overflow-auto border-t border-border/60 px-2.5 py-2 font-mono text-[11px] text-muted-foreground">
            {tool?.args || "(no args)"}
            {tool?.result != null && (
              <span className="mt-1 block border-t border-border/40 pt-1 text-foreground/70">
                {String(tool.result)}
              </span>
            )}
          </pre>
        )}
      </div>
    </div>
  );
});

// ─── pure helpers ───────────────────────────────────────────────────────────

/** Concatenated text from a message's text parts. */
function extractText(message) {
  if (!message) return "";
  const c = message.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c.filter((p) => p?.type === "text").map((p) => p.text || "").join("");
  }
  return "";
}

/**
 * DiceBear seed for the speaker.
 *
 * Two cases:
 *  - Single-agent view (1:1 with a session): use the SESSION ID as seed, so the
 *    face EXACTLY matches SessionList's SessionAvatar for that session.
 *  - Team group-chat view: the active session is the team itself, but each
 *    message comes from a different participant (teamleader/researcher/coder).
 *    Use the speaker name as seed so each participant gets a distinct face.
 *    (Team-internal participants don't appear in SessionList, so there's no
 *    list to stay consistent with.)
 */
function speakerSeed(speaker, session) {
  if (!session) return speaker || "manus-open";
  if (session.kind === "team") return speaker || "team";
  if (session.id === "manus") return "manus-open";
  return session.id;
}

/** Display label for the speaker. */
function speakerLabel(speaker, session) {
  if (speaker && speaker.startsWith("agent:")) return speaker.slice(6);
  if (session?.kind === "subagent") return session.name || "agent";
  if (session?.kind === "team") return speaker || "team";
  return speaker || "Manus";
}
