"""Async counterpart of :class:`FilesystemClient` for use with ``asyncio``.

All filesystem methods are ``async def`` because each one performs a remote
IRI API call via ``asyncio.to_thread()``.

Usage::

    polaris = await facility.resource("Polaris")
    task = await polaris.fs.ls("/home/user")
    print(task.result)
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable

from amscrot.facility.task import Task


class AsyncFilesystemClient:
    """Async filesystem operations scoped to a single IRI resource.

    All methods are ``async def`` and return a :class:`Task` that is
    already resolved (the underlying IRI SDK is synchronous and is
    offloaded to a thread).

    Args:
        resource_id: The IRI resource ID for all operations.
        iri_filesystem: An ``IriFilesystem`` instance.
        call_api: Async callable used to invoke operations (handles
            token-refresh retry).
    """

    def __init__(
        self,
        resource_id: str,
        iri_filesystem: Any,
        call_api: Callable[..., Awaitable[Any]],
    ) -> None:
        self._resource_id = resource_id
        self._fs = iri_filesystem
        self._call_api = call_api

    async def _run(self, method: str, *args: Any, **kwargs: Any) -> Task:
        """Execute a filesystem method asynchronously and wrap as a Task."""
        try:
            result = await self._call_api(
                getattr(self._fs, method), self._resource_id, *args, **kwargs
            )
            return Task(result=result)
        except Exception as exc:
            return Task(error=exc)

    # ── Read operations ────────────────────────────────────────────────────

    async def ls(self, path: str, *, recursive: bool = False) -> Task:
        """List directory contents."""
        return await self._run("ls", path, recursive=recursive)

    async def stat(self, path: str) -> Task:
        """Get file/directory metadata."""
        return await self._run("stat", path)

    async def head(self, path: str, *, lines: int | None = None, bytes_: int | None = None) -> Task:
        """Read the beginning of a file."""
        return await self._run("head", path, lines=lines, bytes=bytes_)

    async def tail(self, path: str, *, lines: int | None = None, bytes_: int | None = None) -> Task:
        """Read the end of a file."""
        return await self._run("tail", path, lines=lines, bytes=bytes_)

    async def checksum(self, path: str) -> Task:
        """Compute file checksum."""
        return await self._run("checksum", path)

    async def download(self, remote_path: str, local_path: str) -> Task:
        """Download a file from the resource to local disk."""
        return await self._run("download", remote_path=remote_path, local_path=local_path)

    # ── Write operations ───────────────────────────────────────────────────

    async def mkdir(self, path: str, *, parents: bool = True) -> Task:
        """Create a directory."""
        return await self._run("mkdir", path, p=parents)

    async def rm(self, path: str) -> Task:
        """Remove a file or directory."""
        return await self._run("rm", path)

    async def cp(self, source: str, destination: str, *, dereference: bool = False) -> Task:
        """Copy a file or directory."""
        return await self._run("cp", source, destination)

    async def mv(self, source: str, destination: str) -> Task:
        """Move (rename) a file or directory."""
        return await self._run("mv", source, destination)

    async def symlink(self, target: str, link_path: str) -> Task:
        """Create a symbolic link."""
        return await self._run("symlink", link_path, target)

    async def upload(self, local_path: str, remote_path: str) -> Task:
        """Upload a file from local disk to the resource."""
        return await self._run("upload", local_path=local_path, remote_path=remote_path)

    async def upload_bytes(self, data: bytes, remote_path: str) -> Task:
        """Upload in-memory bytes to the resource (max 5 MB)."""
        return await self._run("upload_bytes", data, remote_path=remote_path)

    # ── Permission operations ──────────────────────────────────────────────

    async def chmod(self, path: str, mode: str) -> Task:
        """Change file permissions."""
        return await self._run("chmod", path, mode)

    # ── Archive operations ─────────────────────────────────────────────────

    async def compress(
        self,
        source: str,
        destination: str,
        *,
        pattern: str | None = None,
        dereference: bool = False,
        compression: str | None = None,
    ) -> Task:
        """Compress files into an archive."""
        return await self._run("compress", source, destination, dereference=dereference)

    async def extract(self, source: str, destination: str, *, compression: str | None = None) -> Task:
        """Extract an archive."""
        return await self._run("extract", source, destination)

    def __repr__(self) -> str:
        return f"AsyncFilesystemClient(resource_id={self._resource_id!r})"
