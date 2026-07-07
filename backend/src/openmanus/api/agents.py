"""Agents API — list/get/update agent configurations + available tools."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent_loader import agent_loader
from ..tool_loader import tool_loader

router = APIRouter(prefix="/agents", tags=["agents"])

# Built-in tool names (always available, not in ~/.openmanus/tools/)
_BUILTIN_TOOLS = [
    {"name": "dispatch", "description": "Delegate a task to another agent", "source": "builtin"},
    {"name": "send_message", "description": "Send a message to another agent", "source": "builtin"},
    {"name": "read_mailbox", "description": "Read your inbox messages", "source": "builtin"},
    {"name": "whiteboard_write", "description": "Write an artefact to the whiteboard", "source": "builtin"},
    {"name": "whiteboard_read", "description": "Read whiteboard artefacts", "source": "builtin"},
]


@router.get("")
@router.get("/", include_in_schema=False)
async def list_agents() -> list[dict]:
    """List all loaded agent configurations."""
    result = []
    for name, cfg in agent_loader.configs.items():
        result.append({
            "name": name,
            "display_name": cfg.get("display_name", name),
            "tools": cfg.get("tools", []),
            "skills": cfg.get("skills", []),
            "sub_agents": cfg.get("sub_agents", []),
            "is_entry": cfg.get("is_entry", False),
            "is_builtin": cfg.get("is_entry", False) or name in ("manus", "teamleader"),
            "strip_file_tools": cfg.get("strip_file_tools", False),
            "allowed_tools": sorted(cfg.get("allowed_tools", set())),
            "has_prompt": bool(cfg.get("prompt")),
        })
    # sort: builtin first (manus, teamleader), then by name
    result.sort(key=lambda a: (not a["is_builtin"], a["name"] != "manus", a["name"] != "teamleader", a["name"]))
    return result


@router.get("/meta/tools")
async def list_all_tools() -> list[dict]:
    """List all available tools (built-in + user-defined)."""
    tools = list(_BUILTIN_TOOLS)
    for name, instance in tool_loader.tools.items():
        tools.append({
            "name": name,
            "description": getattr(instance, "description", "")[:200],
            "source": "user",
        })
    return tools


@router.get("/{name}")
async def get_agent(name: str) -> dict:
    """Get one agent's full config (including prompt text)."""
    cfg = agent_loader.get(name)
    if not cfg:
        raise HTTPException(status_code=404, detail="agent not found")
    return {
        "name": name,
        "display_name": cfg.get("display_name", name),
        "prompt": cfg.get("prompt", ""),
        "tools": cfg.get("tools", []),
        "skills": cfg.get("skills", []),
        "sub_agents": cfg.get("sub_agents", []),
        "is_entry": cfg.get("is_entry", False),
        "strip_file_tools": cfg.get("strip_file_tools", False),
        "allowed_tools": sorted(cfg.get("allowed_tools", set())),
    }


class UpdateAgentBody(BaseModel):
    prompt: str | None = None
    tools: list[str] | None = None


@router.put("/{name}")
async def update_agent(name: str, body: UpdateAgentBody) -> dict:
    """Update an agent's prompt and/or tools (writes to disk)."""
    if not agent_loader.get(name):
        raise HTTPException(status_code=404, detail="agent not found")
    # Built-in agents (manus, teamleader) cannot be modified.
    if name in ("manus", "teamleader"):
        raise HTTPException(status_code=403, detail="built-in agents cannot be modified")
    if body.prompt is not None:
        agent_loader.save_prompt(name, body.prompt)
    if body.tools is not None:
        agent_loader.save_tools(name, body.tools)
    return {"ok": True, "name": name}
