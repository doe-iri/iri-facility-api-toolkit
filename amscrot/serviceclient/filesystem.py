"""Filesystem interface for ServiceClients.

Provides ``FilesystemInterface`` (abstract base) and ``FilesystemError``
for operation failures.

IRI filesystem implementations are in:
- ``amscrot.serviceclient.amsc_iri.filesystem.IriFilesystemBase``
- ``amscrot.serviceclient.amsc_iri._v1.filesystem.IriFilesystemV1``
- ``amscrot.serviceclient.amsc_iri._v2.filesystem.IriFilesystemV2``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union

__all__ = [
    "FilesystemInterface",
    "FilesystemError",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FilesystemError(Exception):
    """Raised when an IRI filesystem task fails or times out.

    Attributes:
        message:   Human-readable description.
        task_id:   IRI task ID, if available.
        status:    Terminal status value reported by the task, if available.
    """

    def __init__(
        self,
        message: str,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
    ):
        self.task_id = task_id
        self.status = status
        super().__init__(message)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class FilesystemInterface(ABC):
    """Abstract interface for remote filesystem operations.

    All methods are synchronous from the caller's perspective -- implementations
    handle async task submission and polling internally.

    Every method accepts ``resource_id`` as its first argument, identifying the
    remote storage resource to operate on.
    """

    @abstractmethod
    def mkdir(self, resource_id: str, path: str, p: bool = True) -> Dict[str, Any]:
        """Create a remote directory (``mkdir``).

        Args:
            resource_id: Storage resource identifier.
            path:        Remote path to create.
            p:           If True, create all missing parent directories
                         (equivalent to ``-p``).

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def ls(
        self,
        resource_id: str,
        path: str,
        *,
        show_hidden: bool = False,
        recursive: bool = False,
        format: bool = False,
    ) -> Union[Dict[str, Any], str]:
        """List the contents of a remote directory (``ls``).

        Args:
            format: If ``True``, return a human-readable ``ls -al`` style
                    string instead of the raw result dict.

        Returns:
            Formatted string when ``format=True``, otherwise the raw task
            result dict.
        """

    @abstractmethod
    def stat(
        self,
        resource_id: str,
        path: str,
        *,
        dereference: bool = False,
    ) -> Dict[str, Any]:
        """Return metadata for a remote path (``stat``).

        Raises:
            FilesystemError: If the path does not exist or stat fails.

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def upload(
        self,
        resource_id: str,
        local_path: str,
        remote_path: str,
    ) -> Dict[str, Any]:
        """Upload a local file to a remote path (max 5 MB).

        Args:
            resource_id:  Storage resource identifier.
            local_path:   Path to the local file to upload.
            remote_path:  Destination path on the remote filesystem.

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def upload_bytes(
        self,
        resource_id: str,
        data: bytes,
        remote_path: str,
    ) -> Dict[str, Any]:
        """Upload in-memory bytes to a remote path (max 5 MB).

        Args:
            resource_id:  Storage resource identifier.
            data:         Raw file contents to upload.
            remote_path:  Destination path on the remote filesystem.

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def download(
        self,
        resource_id: str,
        remote_path: str,
        local_path: str,
    ) -> str:
        """Download a remote file to a local path (max 5 MB).

        Args:
            resource_id:  Storage resource identifier.
            remote_path:  Remote file to download.
            local_path:   Local destination path. Parent directories are
                          created automatically.

        Returns:
            The absolute local path that was written.

        Raises:
            FilesystemError: If the download task fails or times out.
        """

    @abstractmethod
    def rm(self, resource_id: str, path: str) -> Dict[str, Any]:
        """Delete a remote file or directory (``rm``).

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def mv(self, resource_id: str, src: str, dst: str) -> Dict[str, Any]:
        """Move or rename a remote file or directory (``mv``).

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def cp(self, resource_id: str, src: str, dst: str) -> Dict[str, Any]:
        """Copy a remote file or directory (``cp``).

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def chmod(self, resource_id: str, path: str, mode: str) -> Dict[str, Any]:
        """Change permissions of a remote path (``chmod``).

        Args:
            mode: Octal mode string, e.g. ``"755"``.

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def head(
        self,
        resource_id: str,
        path: str,
        *,
        lines: Optional[int] = None,
        bytes: Optional[int] = None,
    ) -> str:
        """Return the first N lines/bytes of a remote file (``head``).

        Returns:
            Decoded text content.
        """

    @abstractmethod
    def tail(
        self,
        resource_id: str,
        path: str,
        *,
        lines: Optional[int] = None,
        bytes: Optional[int] = None,
    ) -> str:
        """Return the last N lines/bytes of a remote file (``tail``).

        Returns:
            Decoded text content.
        """

    @abstractmethod
    def checksum(self, resource_id: str, path: str) -> str:
        """Return the SHA-256 checksum of a remote file.

        Returns:
            Checksum string from the task result.
        """

    @abstractmethod
    def compress(
        self,
        resource_id: str,
        path: str,
        target_path: str,
        *,
        dereference: bool = False,
    ) -> Dict[str, Any]:
        """Compress a remote path using ``tar`` (``compress``).

        Args:
            path:        Source path to compress.
            target_path: Destination archive path.

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def extract(
        self,
        resource_id: str,
        path: str,
        target_path: str,
    ) -> Dict[str, Any]:
        """Extract a remote archive (``extract``).

        Args:
            path:        Archive to extract.
            target_path: Destination directory.

        Returns:
            Task result dict from the IRI API.
        """

    @abstractmethod
    def symlink(
        self,
        resource_id: str,
        link_path: str,
        target_path: str,
    ) -> Dict[str, Any]:
        """Create a symbolic link on the remote filesystem (``ln -s``).

        Args:
            link_path:   Path of the new symlink.
            target_path: Target the symlink points to.

        Returns:
            Task result dict from the IRI API.
        """
