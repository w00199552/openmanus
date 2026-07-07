"""Agents API — list/get agent configurations from ~/.openmanus/agents/."""

from __future__ import annotations

from fastapi import APIRouter

from ..agent_loader import agent_loader

router = APIRouter(prefix="/agents", tags=["agents"])


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
            "strip_file_tools": cfg.get("strip_file_tools", False),
            "allowed_tools": sorted(cfg.get("allowed_tools", set())),
            "has_prompt": bool(cfg.get("prompt")),
        })
    return result


@router.get("/{name}")
async def get_agent(name: str) -> dict:
    """Get one agent's full config (including prompt text)."""
    cfg = agent_loader.get(name)
    if not cfg:
        from fastapi import HTTPException
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
