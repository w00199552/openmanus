"""LLM trace callback — logs every model call's full output (text + tool calls).

Mounted on the ChatGLM model via ``callbacks``. Unlike AgentTrace middleware
(which struggles to extract the message from the model-response wrapper), this
hooks directly into langchain's callback system where the AIMessage is cleanly
available at ``on_chat_model_end``.

Because the SAME model instance is shared across all agents, we tag each call
with the agent name by peeking at the runnable config's "metadata.agent_name"
(deepagents sets this). Falls back to "?" if unavailable.

Usage: pass ``callbacks=[LLMTraceCallback()]`` to the model, or set it globally.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger("openmanus.llm_trace")


def _short(text: Any, n: int = 200) -> str:
    s = str(text).replace("\n", " ").strip()
    return s[:n] + ("…" if len(s) > n else "")


class LLMTraceCallback(BaseCallbackHandler):
    """Logs the model's full output (text + tool_calls) after each call."""

    def on_chat_model_end(self, response, *, run_id, parent_run_id, **kwargs: Any) -> None:
        """Fires after the model returns. response.generations has the output."""
        try:
            # extract agent name from the serialized run info if available
            agent_name = "?"
            inv = kwargs.get("invocation_kwargs") or {}
            tags = inv.get("tags") or []
            for t in tags:
                if isinstance(t, str) and t.startswith("openmanus-"):
                    agent_name = t.replace("openmanus-", "")

            gens = response.generations or []
            if gens and gens[0]:
                gen = gens[0][0]  # GenerationChunk or ChatGeneration
                msg = getattr(gen, "message", None)
                if msg is None:
                    # plain Generation: text in .text
                    text = getattr(gen, "text", "")
                    logger.warning("[LLM_TRACE] %s → %s", agent_name, _short(text))
                    return
                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    text = " ".join(
                        p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in content
                    )
                else:
                    text = str(content or "")
                tcs = getattr(msg, "tool_calls", None) or []
                tc_info = []
                for tc in tcs:
                    if isinstance(tc, dict):
                        tc_info.append(f"{tc.get('name','?')}({ _short(tc.get('args',{}), 60) })")
                    else:
                        tc_info.append(f"{getattr(tc,'name','?')}")
                logger.warning(
                    "[LLM_TRACE] %s → text=%r tools=%s",
                    agent_name, _short(text),
                    tc_info if tc_info else "(none)",
                )
        except Exception:  # noqa: BLE001 — never break the model for a log
            pass

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """For non-chat models (we use chat, so this is a no-op fallback)."""
        pass
