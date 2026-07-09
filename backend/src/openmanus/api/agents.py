"""Agents API — list/get/update agent configurations + available tools."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent_loader import agent_loader
from ..skill_loader import skill_loader
from ..tool_loader import tool_loader

router = APIRouter(prefix="/agents", tags=["agents"])

# Built-in agent check: is_builtin is read from agent.yaml (seed agents have
# is_builtin: true). No hardcoded names.


# ─── Pydantic models ────────────────────────────────────────────────────────

class ToolInfo(BaseModel):
    name: str
    description: str = ""
    source: str = "builtin"  # "builtin" | "user"


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    has_scripts: bool = False
    has_references: bool = False


class AgentSummary(BaseModel):
    """Agent metadata for the list view (no prompt body)."""
    name: str
    description: str = ""
    tools: list[str] = []
    skills: list[str] = []
    sub_agents: list[str] = []
    strip_file_tools: bool = False
    allowed_tools: list[str] = []
    has_prompt: bool = False
    is_builtin: bool = False


class AgentDetail(BaseModel):
    """Full agent config (including prompt text)."""
    name: str
    description: str = ""
    prompt: str = ""
    tools: list[str] = []
    skills: list[str] = []
    sub_agents: list[str] = []
    strip_file_tools: bool = False
    allowed_tools: list[str] = []


class UpdateAgentBody(BaseModel):
    prompt: str | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None
    description: str | None = None


class CreateAgentBody(BaseModel):
    name: str
    description: str = ""
    prompt: str = ""
    tools: list[str] = []
    skills: list[str] = []


# Built-in tool names (always available, not in ~/.openmanus/tools/)
_BUILTIN_TOOLS = [
    ToolInfo(name="dispatch", description="Delegate a task to another agent", source="builtin"),
    ToolInfo(name="send_message", description="Send a message to another agent", source="builtin"),
    ToolInfo(name="read_mailbox", description="Read your inbox messages", source="builtin"),
    ToolInfo(name="whiteboard_write", description="Write an artefact to the whiteboard", source="builtin"),
    ToolInfo(name="whiteboard_read", description="Read whiteboard artefacts", source="builtin"),
]


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("")
@router.get("/", include_in_schema=False)
async def list_agents() -> list[AgentSummary]:
    """List all loaded agent configurations."""
    result = []
    for name, cfg in agent_loader.configs.items():
        result.append(AgentSummary(
            name=name,
            description=cfg.get("description", ""),
            tools=cfg.get("tools", []),
            skills=cfg.get("skills", []),
            sub_agents=cfg.get("sub_agents", []),
            strip_file_tools=cfg.get("strip_file_tools", False),
            allowed_tools=sorted(cfg.get("allowed_tools", set())),
            has_prompt=bool(cfg.get("prompt")),
            is_builtin=cfg.get("is_builtin", False),
        ))
    # sort: builtin first, then by name
    result.sort(key=lambda a: (not a.is_builtin, a.name))
    return result


@router.get("/meta/tools")
async def list_all_tools() -> list[ToolInfo]:
    """List all available tools (built-in + user-defined)."""
    tools = list(_BUILTIN_TOOLS)
    for name, instance in tool_loader.tools.items():
        tools.append(ToolInfo(
            name=name,
            description=getattr(instance, "description", "")[:200],
            source="user",
        ))
    return tools


@router.get("/meta/skills")
async def list_all_skills() -> list[SkillInfo]:
    """List all available skills from ~/.openmanus/skills/."""
    return [
        SkillInfo(
            name=s["name"],
            description=s.get("description", ""),
            has_scripts=s.get("has_scripts", False),
            has_references=s.get("has_references", False),
        )
        for s in skill_loader.skills.values()
    ]


@router.get("/{name}")
async def get_agent(name: str) -> AgentDetail:
    """Get one agent's full config (including prompt text)."""
    cfg = agent_loader.get(name)
    if not cfg:
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentDetail(
        name=name,
        description=cfg.get("description", ""),
        prompt=cfg.get("prompt", ""),
        tools=cfg.get("tools", []),
        skills=cfg.get("skills", []),
        sub_agents=cfg.get("sub_agents", []),
        strip_file_tools=cfg.get("strip_file_tools", False),
        allowed_tools=sorted(cfg.get("allowed_tools", set())),
    )


@router.post("")
@router.post("/", include_in_schema=False)
async def create_agent(body: CreateAgentBody) -> dict:
    """Create a new agent on disk."""
    try:
        agent_loader.create(body.name, body.prompt, body.tools, body.description)
        if body.skills:
            agent_loader.save_skills(body.name.strip(), body.skills)
        return {"ok": True, "name": body.name.strip()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{name}")
async def update_agent(name: str, body: UpdateAgentBody) -> dict:
    """Update an agent's prompt and/or tools and/or skills (writes to disk)."""
    if not agent_loader.get(name):
        raise HTTPException(status_code=404, detail="agent not found")
    if agent_loader.get(name, ).get("is_builtin", False):
        raise HTTPException(status_code=403, detail="built-in agents cannot be modified")
    if body.prompt is not None:
        agent_loader.save_prompt(name, body.prompt)
    if body.tools is not None:
        agent_loader.save_tools(name, body.tools)
    if body.skills is not None:
        agent_loader.save_skills(name, body.skills)
    if body.description is not None:
        agent_loader.save_description(name, body.description)
    return {"ok": True, "name": name}


@router.delete("/{name}")
async def delete_agent(name: str) -> dict:
    """Delete a custom agent (built-in agents cannot be deleted)."""
    try:
        agent_loader.delete(name)
        return {"ok": True, "name": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
