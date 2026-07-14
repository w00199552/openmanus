"""ReadOnlyFilesystemBackend — a FilesystemBackend that rejects all writes.

Used with CompositeBackend to mount /skills/ as read-only: the agent can
read_file / ls / glob / grep skill files, but cannot write_file / edit_file /
delete them. This prevents an agent from modifying shared skill definitions.
"""

from __future__ import annotations

from deepagents.backends.filesystem import FilesystemBackend


class ReadOnlyFilesystemBackend(FilesystemBackend):
    """FilesystemBackend that allows reads but blocks all modifications.

    virtual_mode=True is required when used inside CompositeBackend: the
    composite backend strips the route prefix (e.g. /skills/) and passes
    the remaining virtual path, which virtual_mode resolves relative to
    root_dir.
    """

    def __init__(self, root_dir, **kwargs):
        # Force virtual_mode=True for correct CompositeBackend path routing
        kwargs["virtual_mode"] = True
        super().__init__(root_dir=root_dir, **kwargs)

    def write(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("skills directory is read-only")

    def edit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("skills directory is read-only")

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("skills directory is read-only")
