"""Tools API — list tools + browse tool files (yaml + source)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pathlib import Path

from ..tool_loader import tool_loader, TOOLS_DIR

router = APIRouter(prefix="/tools-api", tags=["tools"])

# Built-in tool definitions (always available)
_BUILTIN_TOOLS = [
    {"name": "dispatch", "description": "Delegate a task to another agent", "source": "builtin"},
    {"name": "send_message", "description": "Send a message to another agent", "source": "builtin"},
    {"name": "read_mailbox", "description": "Read your inbox messages", "source": "builtin"},
    {"name": "whiteboard_write", "description": "Write an artefact to the whiteboard", "source": "builtin"},
    {"name": "whiteboard_read", "description": "Read whiteboard artefacts", "source": "builtin"},
]


class FileNode(BaseModel):
    name: str
    path: str
    type: str
    children: list["FileNode"] = []


FileNode.model_rebuild()


@router.get("")
@router.get("/", include_in_schema=False)
async def list_tools() -> list[dict]:
    """List all tools (built-in + user-defined)."""
    tools = list(_BUILTIN_TOOLS)
    for name, instance in tool_loader.tools.items():
        tools.append({
            "name": name,
            "description": getattr(instance, "description", "")[:200],
            "source": "user",
        })
    return tools


@router.get("/{name}/tree")
async def get_tool_tree(name: str) -> FileNode:
    """Return the file tree of a user tool directory."""
    tool_dir = TOOLS_DIR / name
    if not tool_dir.exists():
        raise HTTPException(status_code=404, detail="tool not found (built-in tools have no files)")

    def build_tree(path: Path, relative: str) -> FileNode:
        node = FileNode(
            name=path.name,
            path=relative,
            type="dir" if path.is_dir() else "file",
        )
        if path.is_dir():
            for child in sorted(path.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
                child_rel = f"{relative}/{child.name}" if relative else child.name
                node.children.append(build_tree(child, child_rel))
        return node

    return build_tree(tool_dir, "")


@router.get("/{name}/file")
async def get_tool_file(name: str, path: str = Query(...)) -> dict:
    """Read a single file from a tool directory."""
    tool_dir = TOOLS_DIR / name
    if not tool_dir.exists():
        raise HTTPException(status_code=404, detail="tool not found")

    target = (tool_dir / path).resolve()
    try:
        target.relative_to(tool_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside tool directory")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = "(binary file)"

    ext = target.suffix.lower()
    if ext == ".md":
        file_type = "markdown"
    elif ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".json", ".yaml", ".yml", ".css"):
        file_type = "code"
    else:
        file_type = "text"

    return {"path": path, "name": target.name, "content": content, "file_type": file_type}
