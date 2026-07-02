"""ChatGLM — a ChatOpenAI subclass that preserves GLM's reasoning_content.

Why this exists: ``langchain-openai`` (1.3.x) explicitly does NOT extract
non-standard response fields like ``reasoning_content`` (it targets the
official OpenAI spec only; see the ChatOpenAI docstring). Zhipu GLM-5.x
exposes its chain-of-thought as ``reasoning_content`` on the streaming delta
(gated behind ``thinking.type=enabled``), so a plain ChatOpenAI silently drops
the thinking trace AND, because the deltas arrive as reasoning-only chunks,
collapses the token stream.

This subclass overrides ``_convert_chunk_to_generation_chunk`` to fish
``reasoning_content`` out of the raw delta and attach it to the message chunk's
``additional_kwargs``. Everything else (tools, checkpointer, agent middleware,
streaming) is inherited unchanged from ChatOpenAI, so deepagents orchestration
keeps working.

The downstream ``runner._extract_reasoning`` then reads
``additional_kwargs.reasoning_content`` and emits ``thinking_delta`` events.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI


class ChatGLM(ChatOpenAI):
    """ChatOpenAI tuned for Zhipu GLM — preserves reasoning_content in stream.

    Use exactly like ChatOpenAI (same kwargs: model, api_key, base_url,
    streaming, extra_body for ``thinking``, http_client for ssl_verify, ...).
    The only addition is that GLM's ``reasoning_content`` delta field is
    forwarded into ``additional_kwargs`` instead of being discarded.
    """

    def _convert_chunk_to_generation_chunk(  # type: ignore[override]
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ):
        gen_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen_chunk is None:
            return None
        msg = gen_chunk.message
        if not isinstance(msg, AIMessageChunk):
            return gen_chunk

        choices = (
            chunk.get("choices", [])
            or chunk.get("chunk", {}).get("choices", [])
        )
        if not choices:
            return gen_chunk
        delta = choices[0].get("delta") or {}
        # GLM/智谱官方用 reasoning_content；公司 ascendvllm 部署可能用 reasoning。
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if reasoning:
            # GLM streams reasoning token-by-token; accumulate into
            # additional_kwargs so _extract_reasoning can read it per-chunk.
            existing = msg.additional_kwargs.get("reasoning_content", "")
            msg.additional_kwargs["reasoning_content"] = existing + reasoning
        return gen_chunk
