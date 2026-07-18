/**
 * eventReducer unit tests — pure-function checks, no React/mobx/network.
 *
 * Run with: `node --test src/runtim./event-reducer.test.js` (Node 18+ test runner)
 * or any runner that understands `node:test` + `node:assert`.
 *
 * These tests lock down the streaming contract: every event produces a fresh
 * immutable array, deltas accumulate correctly, tool calls match by id, and
 * nothing mutates the input.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { ensureMessage, reduceEvent, replaceMessage } from "./event-reducer.js";

/** helper: text length of the last message's concatenated text parts */
function lastText(messages) {
    const m = messages[messages.length - 1];
    if (!m) return "";
    return (m.content || [])
        .filter((p) => p.type === "text")
        .map((p) => p.text)
        .join("");
}

test("message_start creates a streaming assistant message", () => {
    const out = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "Coder",
    });
    assert.equal(out.length, 1);
    assert.equal(out[0].id, "m1");
    assert.equal(out[0].role, "assistant");
    assert.equal(out[0].speaker, "Coder");
    assert.equal(out[0].status, "streaming");
});

test("message_start is idempotent for the same message_id", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    const before = s;
    s = reduceEvent(s, {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    assert.equal(s.length, 1);
    assert.equal(s, before); // same reference — no duplicate added
});

test("text_delta accumulates into one text part", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    s = reduceEvent(s, { kind: "text_delta", message_id: "m1", delta: "hel" });
    s = reduceEvent(s, { kind: "text_delta", message_id: "m1", delta: "lo" });
    assert.equal(lastText(s), "hello");
    assert.equal(s[s.length - 1].content.length, 1); // single text part
});

test("text_delta after a tool call opens a NEW text part (preserves order)", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    s = reduceEvent(s, {
        kind: "text_delta",
        message_id: "m1",
        delta: "before",
    });
    s = reduceEvent(s, {
        kind: "tool_call_start",
        message_id: "m1",
        call_id: "t1",
        tool: "ls",
    });
    s = reduceEvent(s, {
        kind: "tool_call_end",
        message_id: "m1",
        call_id: "t1",
    });
    s = reduceEvent(s, {
        kind: "text_delta",
        message_id: "m1",
        delta: "after",
    });
    const m = s[s.length - 1];
    // content: [text:before, tool-call, text:after] — order preserved
    assert.equal(m.content.length, 3);
    assert.equal(m.content[0].type, "text");
    assert.equal(m.content[0].text, "before");
    assert.equal(m.content[1].type, "tool-call");
    assert.equal(m.content[1].toolName, "ls");
    assert.equal(m.content[2].type, "text");
    assert.equal(m.content[2].text, "after");
});

test("thinking_delta accumulates separately from text", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    s = reduceEvent(s, {
        kind: "thinking_delta",
        message_id: "m1",
        delta: "let me think",
    });
    s = reduceEvent(s, {
        kind: "thinking_delta",
        message_id: "m1",
        delta: "...",
    });
    s = reduceEvent(s, {
        kind: "text_delta",
        message_id: "m1",
        delta: "answer",
    });
    const m = s[s.length - 1];
    assert.equal(m.thinking, "let me think...");
    assert.equal(lastText(s), "answer");
});

test("message_end marks status complete", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    s = reduceEvent(s, { kind: "message_end", message_id: "m1" });
    assert.equal(s[s.length - 1].status, "complete");
});

test("tool_call lifecycle: start → args → result → end", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    s = reduceEvent(s, {
        kind: "tool_call_start",
        message_id: "m1",
        call_id: "t1",
        tool: "read_file",
    });
    s = reduceEvent(s, {
        kind: "tool_call_args",
        call_id: "t1",
        args_json: '{"path":"a',
    });
    s = reduceEvent(s, {
        kind: "tool_call_args",
        call_id: "t1",
        args_json: '.py"}',
    });
    s = reduceEvent(s, {
        kind: "tool_call_result",
        call_id: "t1",
        result: "file contents",
    });
    s = reduceEvent(s, { kind: "tool_call_end", call_id: "t1" });
    const part = s[s.length - 1].content.find((p) => p.toolCallId === "t1");
    assert.equal(part.toolName, "read_file");
    assert.equal(part.args, '{"path":"a.py"}');
    assert.equal(part.result, "file contents");
    assert.equal(part._streaming, false);
});

test("multiple concurrent tool calls match by their own call_id", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    s = reduceEvent(s, {
        kind: "tool_call_start",
        message_id: "m1",
        call_id: "t1",
        tool: "ls",
    });
    s = reduceEvent(s, {
        kind: "tool_call_start",
        message_id: "m1",
        call_id: "t2",
        tool: "grep",
    });
    s = reduceEvent(s, {
        kind: "tool_call_args",
        call_id: "t2",
        args_json: "x",
    });
    s = reduceEvent(s, {
        kind: "tool_call_result",
        call_id: "t1",
        result: "r1",
    });
    const m = s[s.length - 1];
    const p1 = m.content.find((p) => p.toolCallId === "t1");
    const p2 = m.content.find((p) => p.toolCallId === "t2");
    assert.equal(p1.result, "r1");
    assert.equal(p1.args, "");
    assert.equal(p2.args, "x");
    assert.equal(p2.result, null);
});

test("mailbox adds a distinct assistant bubble, deduped by id", () => {
    let s = reduceEvent([], {
        kind: "mailbox",
        session_id: "x",
        mailbox: {
            id: 5,
            kind: "result",
            content: "done",
            from_session_id: "abc12345",
        },
    });
    assert.equal(s.length, 1);
    assert.equal(s[0].id, "mb-5");
    // duplicate mailbox frame → ignored
    s = reduceEvent(s, {
        kind: "mailbox",
        session_id: "x",
        mailbox: {
            id: 5,
            kind: "result",
            content: "done",
            from_session_id: "abc12345",
        },
    });
    assert.equal(s.length, 1);
});

test("every reduceEvent returns a fresh array reference (immutability)", () => {
    let s = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    const r1 = s;
    s = reduceEvent(s, { kind: "text_delta", message_id: "m1", delta: "x" });
    assert.notEqual(s, r1); // new top-level array
    const r2 = s;
    s = reduceEvent(s, { kind: "text_delta", message_id: "m1", delta: "y" });
    assert.notEqual(s, r2);
});

test("reduceEvent does not mutate the input array", () => {
    const base = reduceEvent([], {
        kind: "message_start",
        message_id: "m1",
        speaker: "a",
    });
    const frozen = [...base];
    reduceEvent(base, { kind: "text_delta", message_id: "m1", delta: "x" });
    assert.deepEqual(base, frozen); // base untouched
});

test("unknown event kinds are a no-op (return same ref)", () => {
    const s = [
        {
            id: "m1",
            role: "assistant",
            speaker: "a",
            thinking: "",
            content: [],
            status: "streaming",
        },
    ];
    const out = reduceEvent(s, { kind: "some_future_event" });
    assert.equal(out, s); // same reference
});

test("done / step events are a no-op on messages", () => {
    const s = [
        {
            id: "m1",
            role: "assistant",
            speaker: "a",
            thinking: "",
            content: [],
            status: "streaming",
        },
    ];
    assert.equal(reduceEvent(s, { kind: "done", session_id: "x" }), s);
    assert.equal(reduceEvent(s, { kind: "step_start", node: "model" }), s);
});

// helper export checks
test("ensureMessage / replaceMessage / replaceToolPart are pure", () => {
    const s = ensureMessage([], "m1", "a");
    assert.equal(s.length, 1);
    const s2 = replaceMessage(s, "m1", (m) => ({ ...m, status: "complete" }));
    assert.notEqual(s, s2);
    assert.equal(s[0].status, "streaming"); // original unchanged
    assert.equal(s2[0].status, "complete");
});
