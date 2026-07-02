"""SessionRunner: the ONE way to run any agent participant.

Replaces single_runner + team_runner + dispatch_task's inline streaming. Every
agent — the default router, a single specialist, the teamleader, a team-internal
sub-agent — runs through here, producing the SAME unified event schema on its
OWN channel. There is no longer a parallel hand-written delta path (which was
the root cause of the team-stream bug: ``subgraphs=True`` double-emits tokens
that the hand path didn't de-dup, and a separate ``aget_state`` final-text read
diverged from the streamed deltas).

KEY INVARIANT — one converter, with de-dup: ``convert_chunk`` carries over
``_StreamState`` from the old AGUIBridge. It tracks the currently-open
assistant message id, the open tool-call ids, and the open step names, so:
  * a token is emitted once even when ``subgraphs=True`` mirrors it across
    graph layers;
  * message/step boundaries close exactly once;
  * the streamed output IS the final output (no second ``aget_state`` read).

MODES:
  * ``async``  — fire-and-forget (asyncio.create_task); the caller returns
                 immediately. Used by the entry default agent.
  * ``sync``   — block until the run completes, return the final assistant
                 text. Used by the teamleader for serial orchestration where
                 the next decision needs this sub-agent's result.

dispatch() is the single delegation primitive. Synchronous vs asynchronous is
just "do we await the run or not" — same code path, same channel, same events.
The sub-agent writes its outcome to the whiteboard and sends the parent a
short ``result`` mailbox message carrying the whiteboard ref (no content copy).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage

from . import event_schema as E
from .channels import channels
from .db import session_store
from .mailbox import mailbox_store
from .whiteboard import whiteboard_store

logger = logging.getLogger(__name__)


def _new_id() -> str:
    return uuid.uuid4().hex


def _extract_text(content: Any) -> list[str]:
    """Pull text deltas out of a streamed message ``content`` field.

    Handles both shapes produced by different providers:
      * ``str``  — OpenAI-style streaming (single-element list)
      * ``list`` — content blocks, e.g. ``[{"text": "Hi", "type": "text"}]``
        (Anthropic / GLM); collect each text block's text in order.
    """
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
    """Pull thinking/reasoning deltas out of a streamed AIMessageChunk.

    GLM-5.x exposes its chain-of-thought as ``reasoning_content`` on the native
    OpenAI endpoint (gated behind ``thinking.type=enabled``). LangChain's
    OpenAI client surfaces non-standard delta fields in
    ``additional_kwargs``, so we read it there. We also tolerate the Anthropic
    shape (a ``{"type":"thinking", "thinking": ...}`` content block) in case
    someone swaps providers. Returns the delta strings in order.
    """
    # 1. GLM native (OpenAI protocol): reasoning_content lives in additional_kwargs
    ak = getattr(msg, "additional_kwargs", None) or {}
    rc = ak.get("reasoning_content")
    if isinstance(rc, str) and rc:
        return [rc]
    if isinstance(rc, list):
        out = [p.get("text", "") if isinstance(p, dict) else str(p) for p in rc]
        return [s for s in out if s]

    # 2. Anthropic shape: thinking-type content blocks
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
    """Tracks ids emitted so far so boundaries close exactly once.

    Ported from the old AGUIBridge — this de-dup is what makes
    ``subgraphs=True`` safe (the team-stream bug fix).
    """

    def __init__(self) -> None:
        self.assistant_message_id: str | None = None
        self.message_open: bool = False
        self.open_tool_calls: set[str] = set()
        self.open_steps: set[str] = set()

    def reset(self) -> None:
        self.assistant_message_id = None
        self.message_open = False
        self.open_tool_calls.clear()
        self.open_steps.clear()


def convert_chunk(
    chunk: dict[str, Any],
    st: _StreamState,
    *,
    session_id: str,
    speaker: str,
) -> list[str]:
    """Return the unified-event SSE frames for one LangGraph stream chunk.

    Pure/synchronous: constructs frame strings only, never awaits. ``session_id``
    and ``speaker`` are injected into every event so a fanned-in stream stays
    attributable.
    """
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
        # streaming tool-call fragments
        for tc in msg.tool_call_chunks or []:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
            tcid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
            if name:  # first fragment carries the tool name → start
                tcid = tcid or _new_id()
                st.open_tool_calls.add(tcid)
                if st.assistant_message_id is None:
                    st.assistant_message_id = _new_id()
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

        # reasoning / thinking trace (GLM reasoning_content, before the answer).
        # Ensure a message id exists; thinking and answer share one message id
        # but render as separate regions in the frontend.
        for thought in _extract_reasoning(msg):
            if not thought:
                continue
            if st.assistant_message_id is None:
                st.assistant_message_id = _new_id()
            frames.append(E.frame(E.ev_thinking_delta(
                session_id=session_id, message_id=st.assistant_message_id,
                speaker=speaker, delta=thought,
            )))

        # plain assistant text
        for text in _extract_text(msg.content):
            if not text:
                continue
            if not st.message_open:
                if st.assistant_message_id is None:
                    st.assistant_message_id = _new_id()
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
        return frames

    return []


def _close_open(st: _StreamState, *, session_id: str, speaker: str) -> list[str]:
    """Close any still-open message / tool-call boundaries on run end."""
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


async def _final_text(agent: Any, config: dict) -> str:
    """Best-effort final assistant text from the populated checkpointer state.

    Used by sync dispatch so the teamleader receives a concrete answer string
    (mirrors the old dispatch_task behaviour). This is a RESULT read for the
    caller only — it is NOT re-streamed; the live stream already showed
    everything.
    """
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


class SessionRunner:
    """The single entry point for running any agent on its session."""

    async def run(
        self,
        *,
        agent: Any,
        session_id: str,
        prompt: str,
        speaker: str,
        mode: str = "async",
    ) -> str | None:
        """Run an agent turn on its session, streaming events to its channel.

        ``mode="async"`` schedules the run as a background task and returns
        immediately (returns None). ``mode="sync"`` awaits completion and
        returns the final assistant text (for serial orchestration).
        """
        if mode == "async":
            asyncio.create_task(
                self._run_to_completion(
                    agent=agent, session_id=session_id, prompt=prompt, speaker=speaker,
                )
            )
            return None
        # sync
        return await self._run_to_completion(
            agent=agent, session_id=session_id, prompt=prompt, speaker=speaker,
        )

    async def _run_to_completion(
        self, *, agent: Any, session_id: str, prompt: str, speaker: str
    ) -> str:
        queue = channels.get_queue(session_id)
        st = _StreamState()
        config = {"configurable": {"thread_id": session_id}}
        await session_store.update(session_id, status="running", touch=True)
        try:
            async for chunk in agent.astream(
                {"messages": [HumanMessage(content=prompt)]},
                config=config,
                stream_mode=["messages", "updates"],
                subgraphs=True,
                version="v2",
            ):
                for f in convert_chunk(chunk, st, session_id=session_id, speaker=speaker):
                    await queue.put(f)
            for f in _close_open(st, session_id=session_id, speaker=speaker):
                await queue.put(f)
            await session_store.update(session_id, status="active", touch=True)
            await queue.put(E.frame(E.ev_done(session_id=session_id)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("runner failed for session %s", session_id)
            for f in _close_open(st, session_id=session_id, speaker=speaker):
                await queue.put(f)
            await queue.put(E.frame(E.ev_error(session_id=session_id, message=str(exc))))
            await session_store.update(session_id, status="error", touch=True)
            await queue.put(E.frame(E.ev_done(session_id=session_id)))
        finally:
            await queue.put(E.done_sentinel(session_id))
            channels.mark_finished(session_id)
        return await _final_text(agent, config)

    async def dispatch(
        self,
        *,
        agent: Any,
        from_session_id: str,
        target_agent: str,
        task: str,
        scope_id: str | None,
        child_session_id: str,
        mode: str = "async",
    ) -> str | None:
        """The single delegation primitive.

        Creates (or reuses) the child session, records a dispatch mailbox
        message, runs the sub-agent under its role prompt, then on completion
        writes its outcome to the whiteboard and notifies the parent with a
        short result mailbox message (whiteboard ref only — no content copy).

        ``mode="sync"`` awaits the run and returns the sub-agent's final text
        (for serial teamleader orchestration). ``mode="async"`` returns the
        child session id immediately.
        """
        from .tools.roles import role_prompt  # lazy: avoid import cycle

        # Record the delegation as a mailbox message (durable + live).
        await mailbox_store.send(
            to_session_id=child_session_id,
            from_session_id=from_session_id,
            kind="dispatch",
            content=task,
        )

        prompt = f"{role_prompt(target_agent)}\n\nTask:\n{task}"

        if mode == "sync":
            answer = await self._run_to_completion(
                agent=agent, session_id=child_session_id, prompt=prompt, speaker=target_agent,
            )
            await self._record_result(
                scope_id=scope_id, child_session_id=child_session_id,
                from_session_id=from_session_id, target_agent=target_agent, answer=answer or "",
            )
            return answer

        # async: fire and forget, record result when it lands.
        asyncio.create_task(self._run_and_record(
            agent=agent, child_session_id=child_session_id, prompt=prompt,
            speaker=target_agent, scope_id=scope_id, from_session_id=from_session_id,
        ))
        return child_session_id

    async def _run_and_record(
        self, *, agent: Any, child_session_id: str, prompt: str, speaker: str,
        scope_id: str | None, from_session_id: str,
    ) -> None:
        answer = await self._run_to_completion(
            agent=agent, session_id=child_session_id, prompt=prompt, speaker=speaker,
        )
        await self._record_result(
            scope_id=scope_id, child_session_id=child_session_id,
            from_session_id=from_session_id, target_agent=speaker, answer=answer or "",
        )

    async def _record_result(
        self, *, scope_id: str | None, child_session_id: str,
        from_session_id: str, target_agent: str, answer: str,
    ) -> None:
        """Persist the outcome to the whiteboard + notify the parent by mailbox."""
        if not scope_id:
            return  # top-level single dispatch has no shared space to write to
        try:
            art = await whiteboard_store.create(
                scope_id=scope_id, session_id=child_session_id,
                kind="result", title=f"{target_agent} result",
                content=answer[:2000] or "(no output)",
            )
            await mailbox_store.send(
                to_session_id=from_session_id,
                from_session_id=child_session_id,
                kind="result",
                content=f"{target_agent} finished",
                whiteboard_ref=art["id"],
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed recording result for %s", child_session_id)


# Module-level singleton.
runner = SessionRunner()
