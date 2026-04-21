"""Resource-scoped filesystem client returning Task objects."""
from __future__ import annotations

from typing import Any, Callable

from amscrot.facility.task import Task


class FilesystemClient:
    """Filesystem operations scoped to a single IRI resource.

    All methods return a :class:`Task` immediately. Since IriFilesystem
    operations are synchronous, the Task is already resolved::

        task = fs.ls("/home/user")
        task.wait()           # no-op but keeps API compatible
        print(task.result)    # directory listing

    Args:
        resource_id: The IRI resource ID for all operations.
        iri_filesystem: An ``IriFilesystem`` instance (from IriServiceClient.filesystem).
        call_api: Callable used to invoke operations; handles token-refresh retry.
    """

    def __init__(
        self,
        resource_id: str,
        iri_filesystem: Any,
        call_api: Callable,
    ) -> None:
        self._resource_id = resource_id
        self._fs = iri_filesystem
        self._call_api = call_api

    def _run(self, method: str, *args: Any, **kwargs: Any) -> Task:
        """Execute a filesystem method and wrap the result as a Task."""
        try:
            result = self._call_api(
                getattr(self._fs, method), self._resource_id, *args, **kwargs
            )
            return Task(result=result)
        except Exception as exc:
            return Task(error=exc)

    # ── Read operations ────────────────────────────────────────────────────

    def ls(self, path: str, *, recursive: bool = False) -> Task:
        """List directory contents."""
        return self._run("ls", path, recursive=recursive)

    def stat(self, path: str) -> Task:
        """Get file/directory metadata."""
        return self._run("stat", path)

    def head(self, path: str, *, lines: int | None = None, bytes_: int | None = None) -> Task:
        """Read the beginning of a file."""
        return self._run("head", path, lines=lines, bytes=bytes_)

    def tail(self, path: str, *, lines: int | None = None, bytes_: int | None = None) -> Task:
        """Read the end of a file."""
        return self._run("tail", path, lines=lines, bytes=bytes_)

    def checksum(self, path: str) -> Task:
        """Compute file checksum."""
        return self._run("checksum", path)

    def download(self, remote_path: str, local_path: str) -> Task:
        """Download a file from the resource to local disk."""
        return self._run("download", remote_path=remote_path, local_path=local_path)

    # ── Write operations ───────────────────────────────────────────────────

    def mkdir(self, path: str, *, parents: bool = True) -> Task:
        """Create a directory."""
        return self._run("mkdir", path, p=parents)

    def rm(self, path: str) -> Task:
        """Remove a file or directory."""
        return self._run("rm", path)

    def cp(self, source: str, destination: str, *, dereference: bool = False) -> Task:
        """Copy a file or directory."""
        return self._run("cp", source, destination, dereference=dereference)

    def mv(self, source: str, destination: str) -> Task:
        """Move (rename) a file or directory."""
        return self._run("mv", source, destination)

    def symlink(self, target: str, link_path: str) -> Task:
        """Create a symbolic link."""
        return self._run("symlink", link_path, target)

    def upload(self, local_path: str, remote_path: str) -> Task:
        """Upload a file from local disk to the resource."""
        return self._run("upload", local_path=local_path, remote_path=remote_path)

    # ── Permission operations ──────────────────────────────────────────────

    def chmod(self, path: str, mode: str) -> Task:
        """Change file permissions."""
        return self._run("chmod", path, mode)

    def chown(self, path: str, *, owner: str | None = None, group: str | None = None) -> Task:
        """Change file ownership."""
        return self._run("chown", path, owner=owner, group=group)

    # ── Archive operations ─────────────────────────────────────────────────

    def compress(
        self,
        source: str,
        destination: str,
        *,
        pattern: str | None = None,
        dereference: bool = False,
        compression: str | None = None,
    ) -> Task:
        """Compress files into an archive."""
        return self._run("compress", source, destination, dereference=dereference)

    def extract(self, source: str, destination: str, *, compression: str | None = None) -> Task:
        """Extract an archive."""
        return self._run("extract", source, destination)

    def __repr__(self) -> str:
        return f"FilesystemClient(resource_id={self._resource_id!r})"
