"""ReadOnlyFilesystemBackend — a FilesystemBackend that rejects all writes.

Used with CompositeBackend to mount /skills/ as read-only: the agent can
read_file / ls / glob / grep skill files, but cannot write_file / edit_file /
delete them. This prevents an agent from modifying shared skill definitions.
"""

from __future__ import annotations

from deepagents.backends.filesystem import FilesystemBackend


class ReadOnlyFilesystemBackend(FilesystemBackend):
    """FilesystemBackend that allows reads but blocks all modifications."""

    def write(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("skills directory is read-only")

    def edit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("skills directory is read-only")

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("skills directory is read-only")
