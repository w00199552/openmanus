"""StreamEngine — runs an agent and turns its output into a unified SSE event flow.

This is the execution layer between an agent (a deepagents/LangGraph graph) and
the live SSE channel the frontend drains. It does NOT decide who gets delegated
to (that's the dispatch tool's job) — it only knows how to RUN a given agent and
translate its langgraph stream chunks into the unified event schema.

Two entry points:
  * ``run``    — run an agent the user is directly talking to (manus / TeamLeader
                 on a team session). Streams to the session's channel.
  * ``start``  — run a DISPATCHED agent (a Coder/Researcher kicked off by the
                 dispatch tool). Same streaming, PLUS records the outcome to the
                 whiteboard + notifies the caller via mailbox when done.

The chunk→event conversion (``convert_chunk``) carries the ``_StreamState``
de-dup logic ported from the old AGUIBridge — this is what keeps
``subgraphs=True`` safe (the team-stream fix).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from langchain_core.messages import HumanMessage
from typing import Any

from . import event_schema as E
from .channels import channels
from .db import session_store
from .mailbox import mailbox_store
from .whiteboard import whiteboard_store

logger = logging.getLogger(__name__)


def _new_id() -> str:
    return uuid.uuid4().hex


def _extract_text(content: Any) -> list[str]:
    if content is None:
        return []
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if t:
                    out.append(t)
            elif isinstance(block, str):
                out.append(block)
        return out
    return []


def _extract_reasoning(msg: Any) -> list[str]:
    """Pull thinking/reasoning deltas out of a streamed AIMessageChunk."""
    ak = getattr(msg, "additional_kwargs", None) or {}
    rc = ak.get("reasoning_content")
    if isinstance(rc, str) and rc:
        return [rc]
    if isinstance(rc, list):
        out = [p.get("text", "") if isinstance(p, dict) else str(p) for p in rc]
        return [s for s in out if s]
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("thinking", "reasoning"):
                t = block.get("thinking") or block.get("text")
                if t:
                    out.append(t)
        return out
    return []


class _StreamState:
    def __init__(self) -> None:
        self.assistant_message_id: str | None = None
        self.message_open: bool = False
        self.open_tool_calls: set[str] = set()
        self.open_steps: set[str] = set()

    def close_turn(self, *, session_id: str, speaker: str) -> list[str]:
        """Close the current model-turn message (if any) and reset for the next.

        A LangGraph agent run loops: AIMessage (model output) → ToolMessage
        (tool result) → AIMessage (next model output) → ... Each AIMessage is a
        DISTINCT model call with its own thinking/text. Without closing the
        current turn at the ToolMessage boundary, the next model call's events
        reuse the same assistant_message_id — which makes the frontend append
        the second thinking to the first (they should be separate bubbles).

        Called when a ToolMessage arrives: emit message_end for the open
        message, then clear assistant_message_id + message_open so the next
        AIMessageChunk allocates a fresh id.
        """
        from . import event_schema as E
        frames: list[str] = []
        if self.message_open and self.assistant_message_id:
            frames.append(E.frame(E.ev_message_end(
                session_id=session_id,
                message_id=self.assistant_message_id,
                speaker=speaker,
            )))
        self.assistant_message_id = None
        self.message_open = False
        return frames


def convert_chunk(chunk, st, *, session_id, speaker):
    from langchain_core.messages import AIMessageChunk, ToolMessage

    ctype = chunk.get("type")
    frames: list[str] = []

    if ctype == "updates":
        for node_name in (chunk.get("data") or {}).keys():
            if not node_name:
                continue
            if node_name not in st.open_steps:
                st.open_steps.add(node_name)
                frames.append(E.frame(E.ev_step_start(session_id=session_id, node=node_name)))
            frames.append(E.frame(E.ev_step_end(session_id=session_id, node=node_name)))
        return frames

    if ctype != "messages":
        return []

    data = chunk.get("data")
    if not isinstance(data, tuple) or len(data) != 2:
        return []
    msg, _meta = data

    if isinstance(msg, AIMessageChunk):
        # Use the LangChain AIMessageChunk's own id as message_id (not _new_id).
        # This keeps the live stream's message_id consistent with the
        # checkpoint-stored AIMessage.id, so history replay (GET /sessions/:id)
        # produces the same bubble ids as the live stream.
        chunk_msg_id = getattr(msg, "id", None) or None

        for tc in msg.tool_call_chunks or []:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
            tcid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
            if name:
                tcid = tcid or _new_id()
                st.open_tool_calls.add(tcid)
                if st.assistant_message_id is None:
                    st.assistant_message_id = chunk_msg_id or _new_id()
                frames.append(E.frame(E.ev_tool_call_start(
                    session_id=session_id, message_id=st.assistant_message_id,
                    speaker=speaker, call_id=tcid, tool=name,
                )))
            if args:
                if not tcid:
                    tcid = next(iter(st.open_tool_calls), None) or _new_id()
                frames.append(E.frame(E.ev_tool_call_args(
                    session_id=session_id, call_id=tcid, args_json=str(args),
                )))

        for thought in _extract_reasoning(msg):
            if not thought:
                continue
            if st.assistant_message_id is None:
                st.assistant_message_id = chunk_msg_id or _new_id()
            frames.append(E.frame(E.ev_thinking_delta(
                session_id=session_id, message_id=st.assistant_message_id,
                speaker=speaker, delta=thought,
            )))

        for text in _extract_text(msg.content):
            if not text:
                continue
            if not st.message_open:
                if st.assistant_message_id is None:
                    st.assistant_message_id = chunk_msg_id or _new_id()
                frames.append(E.frame(E.ev_message_start(
                    session_id=session_id, message_id=st.assistant_message_id, speaker=speaker,
                )))
                st.message_open = True
            frames.append(E.frame(E.ev_text_delta(
                session_id=session_id, message_id=st.assistant_message_id,
                speaker=speaker, delta=text,
            )))
        return frames

    if isinstance(msg, ToolMessage):
        tcid = getattr(msg, "tool_call_id", None) or _new_id()
        try:
            content = str(msg.content)
        except Exception:  # noqa: BLE001
            content = "<tool result>"
        st.open_tool_calls.discard(tcid)
        frames.append(E.frame(E.ev_tool_call_result(
            session_id=session_id, call_id=tcid, result=content,
        )))
        frames.append(E.frame(E.ev_tool_call_end(
            session_id=session_id, call_id=tcid,
        )))
        # This ToolMessage completes one model turn; the next AIMessageChunk is
        # a fresh model call. Close the current message (emit message_end) and
        # reset assistant_message_id so the next thinking/text opens a NEW
        # bubble instead of appending to the previous one.
        frames.extend(st.close_turn(session_id=session_id, speaker=speaker))
        return frames

    return []


def _close_open(st, *, session_id, speaker):
    frames: list[str] = []
    if st.message_open:
        frames.append(E.frame(E.ev_message_end(
            session_id=session_id, message_id=st.assistant_message_id or _new_id(),
            speaker=speaker,
        )))
        st.message_open = False
    for tcid in list(st.open_tool_calls):
        frames.append(E.frame(E.ev_tool_call_end(session_id=session_id, call_id=tcid)))
        st.open_tool_calls.discard(tcid)
    return frames


async def _final_text(agent, config):
    try:
        snapshot = await agent.aget_state(config)
        for msg in reversed(getattr(snapshot, "values", {}).get("messages", [])):
            if getattr(msg, "type", "") == "ai":
                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in content
                    )
                return str(content) or "(no output)"
    except Exception:  # noqa: BLE001
        logger.exception("failed reading final state")
    return "(no output)"


class StreamEngine:
    """Run agents and stream their output as unified events."""

    def __init__(self) -> None:
        # Pending dispatched-agent starts, deferred until the current top-level
        # stream finishes. This prevents concurrent astreams on the same event
        # loop (which cross-contaminate each other's chunks). Keyed by the
        # CALLER's session id — when that caller's _stream ends, we launch its
        # pending dispatched agents.
        self._pending: dict[str, list] = {}
        # Strong references to background tasks (asyncio may GC unreferenced ones).
        self._tasks: set = set()

    async def run(
        self,
        *,
        session_id: str,
        prompt: str,
        speaker: str,
        mode: str = "async",
    ) -> str | None:
        """Run an agent the user is directly talking to.

        The agent is built fresh from the session's DB record inside _stream.

        ``mode="async"`` schedules a background task and returns immediately.
        ``mode="sync"`` awaits completion and returns the final text.
        """
        if mode == "async":
            task = asyncio.create_task(
                self._stream(
                    session_id=session_id, prompt=prompt,
                    speaker=speaker,
                )
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return None
        return await self._stream(
            session_id=session_id, prompt=prompt,
            speaker=speaker,
        )

    async def start(
        self,
        *,
        caller_session_id: str,
        target_agent: str,
        task: str,
        topic_id: str,
        target_session_id: str,
    ) -> str:
        """Run a DISPATCHED agent: stream it + record outcome for the caller.

        ALWAYS deferred — the dispatched agent runs AFTER the caller's own
        astream finishes (no concurrent astreams → no cross-talk). When done,
        it writes the result to the whiteboard + sends the caller a mailbox
        "result" message. The caller picks that up on its NEXT turn.
        """
        prompt = task

        # DEFER until the caller's own stream finishes. We store only the
        # session_id — the agent is built fresh when _stream actually runs.
        self._pending.setdefault(caller_session_id, []).append({
            "target_session_id": target_session_id,
            "prompt": prompt, "speaker": target_agent,
            "topic_id": topic_id, "caller_session_id": caller_session_id,
        })
        return target_session_id

    async def _stream(
        self, *, session_id: str, prompt: str, speaker: str,
    ) -> str:
        from .agent_factory import build_agent, close_agent

        agent, ctx = await build_agent(session_id)
        queue = channels.get_queue(session_id)
        st = _StreamState()
        config = ctx.to_config()
        await session_store.update(session_id, status="running", touch=True)
        final = "(no output)"
        try:
            async for chunk in agent.astream(
                {"messages": [HumanMessage(content=prompt)]},
                config=config,
                stream_mode=["messages", "updates"],
                subgraphs=False,
                version="v2",
            ):
                for f in convert_chunk(chunk, st, session_id=session_id, speaker=speaker):
                    await queue.put(f)
            for f in _close_open(st, session_id=session_id, speaker=speaker):
                await queue.put(f)
            await session_store.update(session_id, status="active", touch=True)
            await queue.put(E.frame(E.ev_done(session_id=session_id)))
            # Extract final text BEFORE closing the agent (avoids rebuild).
            final = await _final_text(agent, config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("engine failed for session %s", session_id)
            for f in _close_open(st, session_id=session_id, speaker=speaker):
                await queue.put(f)
            await queue.put(E.frame(E.ev_error(session_id=session_id, message=str(exc))))
            await session_store.update(session_id, status="error", touch=True)
            await queue.put(E.frame(E.ev_done(session_id=session_id)))
        finally:
            await close_agent(agent)
            await queue.put(E.done_sentinel(session_id))
            channels.mark_finished(session_id)
            # Launch any dispatched agents that were deferred during this stream.
            pending = self._pending.pop(session_id, [])
            for p in pending:
                task = asyncio.create_task(self._start_and_record(
                    target_session_id=p["target_session_id"],
                    prompt=p["prompt"], speaker=p["speaker"],
                    topic_id=p["topic_id"], caller_session_id=p["caller_session_id"],
                ))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            # After this session ends, check mailbox for pending messages.
            # If any arrived while we were running, start a new session to
            # process them (pull path — complements the push path in _wakeup).
            await self._drain_and_start_session(ctx.topic_id, ctx.agent_name)
        return final

    async def _start_and_record(
        self, *, target_session_id, prompt, speaker, topic_id, caller_session_id,
    ):
        answer = await self._stream(
            session_id=target_session_id, prompt=prompt, speaker=speaker,
        )
        await self._record_result(
            topic_id=topic_id, target_session_id=target_session_id,
            caller_session_id=caller_session_id, target_agent=speaker, answer=answer or "",
        )

    async def _record_result(
        self, *, topic_id, target_session_id, caller_session_id, target_agent, answer,
    ):
        """Record a dispatched agent's result: write whiteboard note + mail caller."""
        caller = await session_store.get(caller_session_id)
        if caller and caller.get("kind") == "root":
            return  # entry agent (Manus) is a pure router, doesn't receive results
        if not topic_id:
            return
        caller_name = (caller or {}).get("name") or "unknown"
        try:
            art = await whiteboard_store.create(
                topic_id=topic_id, author=target_agent,
                kind="result", status="finished",
                title=f"{target_agent} result",
                content=answer[:2000] or "(no output)",
            )
            await mailbox_store.send(
                topic_id=topic_id,
                from_agent=target_agent, to_agent=caller_name,
                kind="result",
                content=f"{target_agent} finished",
                whiteboard_ref=art["id"],
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed recording result for %s", target_session_id)

    # ── message-driven wake-up ──────────────────────────────────────────────

    async def _wakeup(self, topic_id: str, agent_name: str) -> None:
        """Wake up an idle agent when a mailbox message arrives (push path).

        Called by mailbox.send via the wakeup callback. If the agent is idle
        (not running), drain its inbox and start a new session. If busy, the
        message queues and will be picked up by _drain_and_start_session when
        the current session ends (_stream finally).
        """
        sessions = await session_store.list_in_topic(topic_id)
        agent_sessions = [s for s in sessions if s.get("name") == agent_name]
        if not agent_sessions:
            return  # agent has no session yet
        latest = agent_sessions[0]  # list_in_topic returns newest first
        if latest.get("status") == "running":
            return  # busy; mail will be drained when session ends
        await self._drain_and_start_session(topic_id, agent_name)

    async def _drain_and_start_session(self, topic_id: str, agent_name: str) -> None:
        """Check mailbox for unread messages; if any, start a new session.

        Uses mailbox.check_and_drain which atomically reads + marks read under
        a lock (prevents the wakeup/check race). The on_messages callback
        builds the inbox prompt and launches a fresh session.
        """
        async def on_messages(msgs):
            lines = []
            for m in msgs:
                sender = m.get("from_agent", "?")
                lines.append(f"- from {sender}: {m.get('content', '')}")
            prompt = ("你收到了以下新消息:\n" + "\n".join(lines)
                      + "\n\n请读取并处理。")
            session = await session_store.create(
                topic_id=topic_id, kind="subagent", name=agent_name,
                title=f"{agent_name} mailbox",
            )
            await session_store.update(session["id"], status="running")
            task = asyncio.create_task(self._stream(
                session_id=session["id"], prompt=prompt, speaker=agent_name,
            ))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        await mailbox_store.check_and_drain(topic_id, agent_name, on_messages)


# Module-level singleton.
engine = StreamEngine()

# Register the wake-up callback so mailbox.send can trigger agent activation.
from .mailbox import set_wakeup_callback  # noqa: E402
set_wakeup_callback(engine._wakeup)
