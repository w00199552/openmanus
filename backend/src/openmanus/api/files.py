"""Files API — browse + read + write files in the workdir.

Endpoints:
  GET    /files/tree              — recursive file tree of workdir
  GET    /files/read?path=        — read a file
  PUT    /files/write             — write/save a file
  GET    /files/watch             — SSE stream of file change events (watchdog)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


def _workdir() -> Path:
    return Path(settings.workdir).resolve()


def _safe_resolve(path: str) -> Path:
    """Resolve a path relative to workdir, preventing traversal outside."""
    wd = _workdir()
    target = (wd / path).resolve()
    try:
        target.relative_to(wd)
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside workdir")
    return target


class FileNode(BaseModel):
    name: str
    path: str
    type: str  # "file" | "dir"
    size: int = 0
    children: list["FileNode"] = []
    has_children: bool = False  # whether a dir has loadable children (for lazy expansion)


FileNode.model_rebuild()

# Names hidden from the file tree.
_HIDE = frozenset({"__pycache__", "node_modules", ".git"})


def _skip(name: str) -> bool:
    return name.startswith(".") or name in _HIDE


def _build_node(path: Path, relative: str) -> FileNode:
    """Build a single FileNode with no children (children are lazy-loaded)."""
    is_dir = path.is_dir()
    has_children = False
    if is_dir:
        try:
            has_children = any(not _skip(c.name) for c in path.iterdir())
        except (PermissionError, OSError):
            pass
    return FileNode(
        name=path.name or str(path),
        path=relative,
        type="dir" if is_dir else "file",
        size=path.stat().st_size if not is_dir else 0,
        children=[],
        has_children=has_children,
    )


def _list_children(path: Path, relative: str) -> list[FileNode]:
    """Immediate children of a directory, sorted (dirs first, then by name)."""
    out: list[FileNode] = []
    try:
        for child in sorted(path.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
            if _skip(child.name):
                continue
            child_rel = f"{relative}/{child.name}" if relative else child.name
            out.append(_build_node(child, child_rel))
    except (PermissionError, OSError):
        pass
    return out


@router.get("/tree")
async def get_tree() -> FileNode:
    """Workdir root with first-level children (depth=1).

    Subdirectories are collapsed; their children are lazy-loaded via
    ``GET /files/children``.
    """
    wd = _workdir()
    root = _build_node(wd, "")
    root.children = _list_children(wd, "")
    return root


@router.get("/children")
async def get_children(path: str = Query("")) -> dict:
    """Immediate children of a directory (for lazy tree expansion)."""
    target = _safe_resolve(path) if path else _workdir()
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")
    children = _list_children(target, path)
    return {"path": path, "children": [c.model_dump() for c in children]}


@router.get("/read")
async def read_file(path: str = Query(...)) -> dict:
    """Read a file from the workdir."""
    target = _safe_resolve(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"path": path, "name": target.name, "content": "(binary file)", "file_type": "binary"}

    ext = target.suffix.lower()
    if ext == ".md":
        file_type = "markdown"
    elif ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".json", ".yaml", ".yml", ".css", ".html", ".xml", ".sql", ".toml", ".cfg", ".ini"):
        file_type = "code"
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico"):
        file_type = "image"
    else:
        file_type = "text"

    return {"path": path, "name": target.name, "content": content, "file_type": file_type}


class WriteFileBody(BaseModel):
    path: str
    content: str


@router.put("/write")
async def write_file(body: WriteFileBody) -> dict:
    """Write/save a file in the workdir."""
    target = _safe_resolve(body.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    return {"ok": True, "path": body.path}


# ── Watchdog: file change events via SSE ────────────────────────────────────

_watcher_started = False
_change_queue: asyncio.Queue | None = None


def _start_watcher():
    """Start a watchdog observer that pushes change events to the SSE queue."""
    global _watcher_started, _change_queue
    if _watcher_started:
        return
    _watcher_started = True

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        wd = _workdir()

        class Handler(FileSystemEventHandler):
            def _push(self, event_type: str, src_path: str):
                if _change_queue is None:
                    return
                rel = str(Path(src_path).resolve().relative_to(wd.resolve())).replace("\\", "/")
                # skip hidden + junk
                if any(part.startswith(".") or part == "__pycache__" or part == "node_modules"
                       for part in Path(rel).parts):
                    return
                try:
                    # watchdog runs in its own thread → use call_soon_threadsafe
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(
                        _change_queue.put_nowait,
                        {"type": event_type, "path": rel},
                    )
                except Exception:  # noqa: BLE001
                    pass

            def on_created(self, event):
                if not event.is_directory:
                    self._push("created", event.src_path)

            def on_modified(self, event):
                if not event.is_directory:
                    self._push("modified", event.src_path)

            def on_deleted(self, event):
                if not event.is_directory:
                    self._push("deleted", event.src_path)

            def on_moved(self, event):
                if not event.is_directory:
                    self._push("moved", event.src_path)

        observer = Observer()
        observer.schedule(Handler(), str(wd), recursive=True)
        observer.start()
        logger.info("file watcher started on %s", wd)
    except ImportError:
        logger.warning("watchdog not installed — file watch disabled (pip install watchdog)")
    except Exception:  # noqa: BLE001
        logger.exception("failed to start file watcher")


@router.get("/watch")
async def watch_files(request: Request) -> StreamingResponse:
    """SSE stream of file change events (created/modified/deleted/moved)."""
    global _change_queue
    _change_queue = asyncio.Queue()
    _start_watcher()

    import json

    async def event_stream():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(_change_queue.get(), timeout=15)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
