"""Offline smoke test for the AG-UI event bridge.

Drives AGUIBridge with a *fake* agent whose astream yields hand-crafted
LangGraph v2 chunks (assistant text tokens, a tool call, a tool result, an
update). This verifies the LangGraph -> AG-UI mapping without needing a real
LLM or API key.
"""

from __future__ import annotations

import asyncio
import json
from langchain_core.messages import AIMessageChunk, ToolMessage
from openmanus.agui_bridge import AGUIBridge
from typing import Any


class FakeAgent:
    """Mimics CompiledStateGraph.astream with a scripted chunk sequence."""

    def __init__(self, script: list[Any]) -> None:
        self._script = script

    async def astream(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        for chunk in self._script:
            yield chunk


def _ai_chunk(content: str = "", tool_call_chunks: list | None = None) -> tuple:
    msg = AIMessageChunk(content=content, tool_call_chunks=tool_call_chunks or [])
    return (msg, {"langgraph_node": "agent"})


def main() -> None:
    script = [
        # 1) assistant says "Hello"
        {"type": "messages", "ns": (), "data": _ai_chunk(content="Hello")},
        {"type": "messages", "ns": (), "data": _ai_chunk(content=", ")},
        {"type": "messages", "ns": (), "data": _ai_chunk(content="world!")},
        # 2) assistant emits a tool call (streamed: name then args)
        {
            "type": "messages", "ns": (),
            "data": _ai_chunk(tool_call_chunks=[{"name": "write_file", "id": "tc1"}]),
        },
        {
            "type": "messages", "ns": (),
            "data": _ai_chunk(tool_call_chunks=[{"args": '{"path": "a.txt"}'}]),
        },
        # 3) node step update
        {"type": "updates", "ns": (), "data": {"tools": {"messages": []}}},
        # 4) tool result comes back
        {
            "type": "messages", "ns": (),
            "data": (ToolMessage(content="wrote 5 bytes", tool_call_id="tc1"), {}),
        },
    ]

    bridge = AGUIBridge(FakeAgent(script))  # type: ignore[arg-type]
    frames = asyncio.run(
        bridge._collect(  # type: ignore[attr-defined]
            thread_id="t1", run_id="r1", user_text="hi"
        )
    )

    print(f"--- {len(frames)} AG-UI frames ---")
    skip = {"type", "timestamp"}
    for i, f in enumerate(frames, 1):
        # each frame is "data: {...}\n\n"
        payload = f.strip()[len("data: "):]
        try:
            obj = json.loads(payload)
            rest = json.dumps({k: v for k, v in obj.items() if k not in skip})
            print(f"{i:2d} {obj.get('type'):24s} {rest}")
        except Exception:
            print(f"{i:2d} RAW {payload}")

    # Assertions on the expected event sequence
    types = [json.loads(f.strip()[len("data: "):])["type"] for f in frames]
    assert types[0] == "RUN_STARTED", types
    assert "TEXT_MESSAGE_START" in types
    assert types.count("TEXT_MESSAGE_CONTENT") == 3, types
    assert "TEXT_MESSAGE_END" in types
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_ARGS" in types
    assert "TOOL_CALL_END" in types
    assert "TOOL_CALL_RESULT" in types
    assert "STEP_STARTED" in types
    assert types[-1] == "RUN_FINISHED", types
    print("\nALL ASSERTIONS PASSED ✓")


# helper added to bridge for testing convenience
async def _collect(self, **kw):
    out = []
    async for f in self.run(**kw):
        out.append(f)
    return out


AGUIBridge._collect = _collect  # type: ignore[attr-defined]

if __name__ == "__main__":
    main()
