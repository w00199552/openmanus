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


def _workdir(workdir: str | None = None) -> Path:
    """Resolve the workdir to use. If ``workdir`` is given (per-session),
    use it; otherwise fall back to the global setting."""
    base = workdir or settings.workdir
    return Path(base).resolve()


def _safe_resolve(path: str, workdir: str | None = None) -> Path:
    """Resolve a path relative to workdir, preventing traversal outside."""
    wd = _workdir(workdir)
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


def _build_node(path: Path, relative: str, workdir: str | None = None) -> FileNode:
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


def _list_children(path: Path, relative: str, workdir: str | None = None) -> list[FileNode]:
    """Immediate children of a directory, sorted (dirs first, then by name)."""
    out: list[FileNode] = []
    try:
        for child in sorted(path.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
            if _skip(child.name):
                continue
            child_rel = f"{relative}/{child.name}" if relative else child.name
            out.append(_build_node(child, child_rel, workdir))
    except (PermissionError, OSError):
        pass
    return out


@router.get("/tree")
async def get_tree(workdir: str | None = Query(None)) -> FileNode:
    """Workdir root with first-level children (depth=1).

    Pass ``?workdir=`` to target a specific session's workdir (per-session
    sandbox). Subdirectories are collapsed; their children are lazy-loaded via
    ``GET /files/children``.
    """
    wd = _workdir(workdir)
    root = _build_node(wd, "", workdir)
    root.children = _list_children(wd, "", workdir)
    return root


@router.get("/children")
async def get_children(
    path: str = Query(""),
    workdir: str | None = Query(None),
) -> dict:
    """Immediate children of a directory (for lazy tree expansion)."""
    target = _safe_resolve(path, workdir) if path else _workdir(workdir)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")
    children = _list_children(target, path, workdir)
    return {"path": path, "children": [c.model_dump() for c in children]}


@router.get("/read")
async def read_file(
    path: str = Query(...),
    workdir: str | None = Query(None),
) -> dict:
    """Read a file from the workdir."""
    target = _safe_resolve(path, workdir)
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
    workdir: str | None = None


@router.put("/write")
async def write_file(body: WriteFileBody) -> dict:
    """Write/save a file in the workdir."""
    target = _safe_resolve(body.path, body.workdir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    return {"ok": True, "path": body.path}


# ── Watchdog: file change events via SSE ────────────────────────────────────

import threading


class _FileWatcher:
    """Single-directory watchdog.

    Only the **currently active** workdir is watched — matching the one
    session the user is looking at.  When the frontend switches session it
    closes the SSE connection (``useEffect`` cleanup) and opens a new one
    with a different ``?workdir=``, which triggers ``set_target`` to
    re-point the observer.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._observer = None
        self._watch = None          # active ObservedWatch (or None)
        self._wd_resolved: Path | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None  # current subscriber's queue

    # ── lifecycle ──────────────────────────────────────────────────────────

    def _ensure_observer(self):
        if self._observer is not None:
            return
        try:
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("watchdog not installed — file watch disabled (pip install watchdog)")
            return
        self._observer = Observer()
        self._observer.daemon = True
        self._observer.start()
        logger.info("watchdog observer started")

    def _make_handler(self):
        from watchdog.events import FileSystemEventHandler

        wd = self._wd_resolved
        hub = self

        class Handler(FileSystemEventHandler):
            def _push(self, event_type: str, src_path: str):
                if hub._queue is None or hub._loop is None or wd is None:
                    return
                try:
                    rel = str(Path(src_path).resolve().relative_to(wd)).replace("\\", "/")
                except (ValueError, OSError):
                    return
                if any(part.startswith(".") or part == "__pycache__" or part == "node_modules"
                       for part in Path(rel).parts):
                    return
                hub._loop.call_soon_threadsafe(
                    hub._queue.put_nowait, {"type": event_type, "path": rel},
                )

            def on_created(self, event):
                self._push("created", event.src_path)

            def on_modified(self, event):
                self._push("modified", event.src_path)

            def on_deleted(self, event):
                self._push("deleted", event.src_path)

            def on_moved(self, event):
                self._push("moved", event.src_path)

        return Handler()

    # ── public API ─────────────────────────────────────────────────────────

    def start(self, wd_str: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        """Begin watching *wd_str*. Returns the SSE queue for this subscriber.

        Only one subscriber (the active session) is supported at a time.
        If called with the same workdir (e.g. React reconnect), the queue is
        replaced without re-scheduling the observer.  If the workdir changed,
        the observer is re-pointed.
        """
        wd_resolved = Path(wd_str).resolve()
        q: asyncio.Queue = asyncio.Queue()

        with self._lock:
            self._ensure_observer()
            self._loop = loop

            if wd_resolved != self._wd_resolved:
                # target changed → re-point
                self._stop_watch()
                self._wd_resolved = wd_resolved
                self._queue = q
                if self._observer is not None:
                    try:
                        self._watch = self._observer.schedule(
                            self._make_handler(), str(wd_resolved), recursive=True,
                        )
                        logger.info("file watcher → %s", wd_resolved)
                    except Exception:  # noqa: BLE001
                        logger.exception("failed to start watcher on %s", wd_resolved)
                        self._watch = None
            else:
                # same target → just swap the queue (reconnect)
                self._queue = q

        return q

    def _stop_watch(self):
        if self._watch is not None and self._observer is not None:
            try:
                self._observer.unschedule(self._watch)
            except Exception:  # noqa: BLE001
                pass
        self._watch = None

    def stop(self, q: asyncio.Queue):
        """Called on SSE disconnect.

        Only tears down the watch if *q* is still the active queue — avoids
        a stale/reconnecting connection from killing the current one.
        """
        with self._lock:
            if self._queue is not q:
                return  # we've been superseded by a newer subscriber
            self._queue = None
            self._stop_watch()
            self._wd_resolved = None


_watcher = _FileWatcher()


@router.get("/watch")
async def watch_files(
    request: Request,
    workdir: str | None = Query(None),
) -> StreamingResponse:
    """SSE stream of file change events (created/modified/deleted/moved).

    Watches only the active workdir (``?workdir=``).  The frontend opens a
    fresh connection when the user switches session, which re-points the
    observer to the new workdir.
    """
    wd_str = workdir or settings.workdir
    loop = asyncio.get_running_loop()
    q = _watcher.start(wd_str, loop)

    import json

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        finally:
            _watcher.stop(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
