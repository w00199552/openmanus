"""Skills API — list skills + browse skill files (tree + content)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pathlib import Path

from ..skill_loader import skill_loader, SKILLS_DIR

router = APIRouter(prefix="/skills", tags=["skills"])


class FileNode(BaseModel):
    name: str
    path: str
    type: str  # "file" | "dir"
    children: list["FileNode"] = []


FileNode.model_rebuild()


@router.get("")
@router.get("/", include_in_schema=False)
async def list_skills() -> list[dict]:
    """List all installed skills."""
    return [
        {
            "name": s["name"],
            "description": s.get("description", ""),
            "has_scripts": s.get("has_scripts", False),
            "has_references": s.get("has_references", False),
        }
        for s in skill_loader.skills.values()
    ]


@router.get("/{name}/tree")
async def get_skill_tree(name: str) -> FileNode:
    """Return the file tree of a skill directory."""
    sdir = skill_loader.skill_dir(name)
    if not sdir or not sdir.exists():
        raise HTTPException(status_code=404, detail="skill not found")

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

    return build_tree(sdir, "")


@router.get("/{name}/file")
async def get_skill_file(name: str, path: str = Query(...)) -> dict:
    """Read a single file from a skill directory (read-only)."""
    sdir = skill_loader.skill_dir(name)
    if not sdir or not sdir.exists():
        raise HTTPException(status_code=404, detail="skill not found")

    # Resolve and prevent path traversal
    target = (sdir / path).resolve()
    try:
        target.relative_to(sdir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside skill directory")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = "(binary file, cannot display)"

    # Determine file type for frontend rendering
    ext = target.suffix.lower()
    if ext in (".md",):
        file_type = "markdown"
    elif ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".json", ".yaml", ".yml", ".css", ".html", ".xml", ".sql"):
        file_type = "code"
    else:
        file_type = "text"

    return {
        "path": path,
        "name": target.name,
        "content": content,
        "file_type": file_type,
    }
