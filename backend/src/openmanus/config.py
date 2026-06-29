"""Application configuration loaded from environment / .env.

Two provider modes are supported via the MODEL_PROVIDER setting:

* ``anthropic`` (default for GLM) — uses an Anthropic-protocol-compatible
  endpoint. BigModel's GLM-5.2 exposes
  ``https://open.bigmodel.cn/api/anthropic`` and a standard API key.
* ``openai`` — any OpenAI-compatible endpoint (OpenAI, OpenRouter, Ollama, …).

The agent operates on the real local project files under WORKDIR.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Provider / model ------------------------------------------------
    # "anthropic" or "openai". GLM-5.2 via BigModel is Anthropic-protocol.
    model_provider: str = "anthropic"
    model: str = "GLM-5.2"

    # Anthropic-protocol credentials (BigModel GLM, Anthropic itself, Z.ai, …)
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://open.bigmodel.cn/api/anthropic"

    # OpenAI-protocol credentials (kept for OpenAI/OpenRouter/Ollama use)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # Skip TLS certificate verification (set False for self-signed / 公司内网
    # 自建模型证书). Affects BOTH providers' httpx clients.
    ssl_verify: bool = True

    # --- Filesystem the agent works on -----------------------------------
    # Defaults to the current working directory so the agent edits real files.
    workdir: str = str(Path.cwd())

    # --- History persistence (checkpointer) ------------------------------
    # sqlite:///./data/checkpoints.db  or  postgresql+psycopg://user:pass@host/db
    database_url: str = "sqlite:///./data/checkpoints.db"

    # --- Server ----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8999
    cors_origins: str = "*"

    # --- Agent behaviour -------------------------------------------------
    system_prompt: str = (
        "You are manus, an AI coding agent operating in the user's project "
        "directory. Use the file system tools to read, edit, and run code. "
        "Be concise. Explain what you are about to do, then do it."
    )

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
