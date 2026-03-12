"""Filesystem interface for IRI-based ServiceClients.

Provides ``FilesystemInterface`` (abstract base) and ``IriFilesystem``
(concrete implementation for both NERSC IRI and ESnet IRI), plus
``FilesystemError`` for operation failures.

Usage::

    fs = service_client.filesystem
    fs.mkdir(storage_resource_id, "/path/to/dir")
    fs.upload(storage_resource_id, "/local/file.sh", "/remote/file.sh")
    content = fs.head(storage_resource_id, "/remote/file.txt", lines=20)
    fs.download(storage_resource_id, "/remote/out.log", "/local/out.log")
    info = fs.stat(storage_resource_id, "/path/to/check")
    fs.rm(storage_resource_id, "/path/to/old")
    # Pretty-print a directory listing:
    print(fs.ls(storage_resource_id, "/path/to/dir", format=True))
"""

from __future__ import annotations

import ast
import base64
import datetime
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Union


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mode_to_str(mode: int, ftype: str) -> str:
    """Convert an integer mode + file-type string to a 10-char permission string.

    Example: mode=0o755, ftype='directory'  ->  'drwxr-xr-x'
    """
    type_char = {'directory': 'd', 'symlink': 'l'}.get(ftype, '-')
    chars = []
    for shift in (6, 3, 0):          # owner, group, other
        chars.append('r' if (mode >> (shift + 2)) & 1 else '-')
        chars.append('w' if (mode >> (shift + 1)) & 1 else '-')
        chars.append('x' if (mode >> shift) & 1 else '-')
    return type_char + ''.join(chars)


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

    All methods are synchronous from the caller's perspective — implementations
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


# ---------------------------------------------------------------------------
# IRI concrete implementation
# ---------------------------------------------------------------------------

class IriFilesystem(FilesystemInterface):
    """Filesystem interface backed by an IRI ``FilesystemApi`` + ``TaskApi``.

    Works with both NERSC IRI and ESnet IRI clients since they share an
    identical OpenAPI-generated surface.

    Args:
        filesystem_api:       The IRI ``FilesystemApi`` instance.
        task_api:             The IRI ``TaskApi`` instance used for polling.
        logger:               Standard Python logger.
        client_name:          Label used in log messages.
        default_task_timeout: Seconds to wait for a task to complete (default 120).
        default_task_interval: Polling interval in seconds (default 2).
    """

    def __init__(
        self,
        filesystem_api: Any,
        task_api: Any,
        logger: Any,
        client_name: str,
        default_task_timeout: float = 120.0,
        default_task_interval: float = 2.0,
    ):
        self._fs = filesystem_api
        self._tasks = task_api
        self._logger = logger
        self._client_name = client_name
        self._timeout = default_task_timeout
        self._interval = default_task_interval

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_ls_entries(result: Dict[str, Any]) -> list:
        """Extract the list of entry dicts from an ls result.

        The IRI API can return the listing in several ways:
        - ``{'output': "{'output': [...]}"}``  (double-nested Python repr)
        - ``{'output': '[...]'}``               (JSON or Python repr list)
        - ``{'output': [...]}``                 (already a list)
        - A bare list
        """
        raw = result.get('output', result)

        # If raw is already a list, we're done.
        if isinstance(raw, list):
            return raw

        # If it's a string, try to parse it (Python repr or JSON).
        if isinstance(raw, str):
            try:
                parsed = ast.literal_eval(raw)
            except Exception:
                return []
            # Parsed may be {'output': [...]} or directly a list.
            if isinstance(parsed, dict):
                inner = parsed.get('output', [])
                return inner if isinstance(inner, list) else []
            if isinstance(parsed, list):
                return parsed

        # If raw is a dict with an 'output' key, recurse one level.
        if isinstance(raw, dict) and 'output' in raw:
            return IriFilesystem._parse_ls_entries({'output': raw['output']})

        return []

    @staticmethod
    def _format_ls_long(result: Dict[str, Any]) -> str:
        """Render an ls result as ``ls -al`` style text.

        Each line has the form::

            drwxr-xr-x     50001    50001         6144  Mar 04 15:53  dirname
            -rw-r--r--     50001    50001           11  Mar 12 20:11  file.txt -> target
        """
        entries = IriFilesystem._parse_ls_entries(result)
        if not entries:
            return '(empty or unrecognised ls response)'

        lines = []
        for entry in entries:
            ftype = entry.get('type', 'file')
            perms_raw = entry.get('permissions', '0o644')
            try:
                mode = int(perms_raw, 8) if isinstance(perms_raw, str) else int(perms_raw)
            except (ValueError, TypeError):
                mode = 0o644
            perm_str = _mode_to_str(mode, ftype)

            user  = str(entry.get('user', '-'))
            group = str(entry.get('group', '-'))
            try:
                size = int(entry.get('size', 0))
            except (ValueError, TypeError):
                size = 0

            try:
                mtime = int(entry.get('last_modified', 0))
                dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
                date_str = dt.strftime('%b %d %H:%M')
            except Exception:
                date_str = '?          '

            name = entry.get('name', '?')
            link_target = entry.get('link_target')
            name_str = f"{name} -> {link_target}" if link_target else name

            lines.append(
                f"{perm_str}  {user:>8} {group:>8}  {size:>12}  {date_str}  {name_str}"
            )
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tag(self) -> str:
        return f"[{self._client_name}][filesystem]"

    def _run_task(
        self,
        task_response: Any,
        *,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        op: str = "task",
    ) -> Any:
        """Poll TaskApi until the task reaches a terminal state.

        Args:
            task_response: ``TaskSubmitResponse`` from a filesystem API call.
            timeout:       Override default timeout (seconds).
            interval:      Override default polling interval (seconds).
            op:            Short operation name for log messages.

        Returns:
            The completed ``Task`` object (task.result contains the payload).

        Raises:
            FilesystemError: On task failure, cancellation, or timeout.
        """
        timeout = timeout if timeout is not None else self._timeout
        interval = interval if interval is not None else self._interval
        task_id = getattr(task_response, 'task_id', None) or str(task_response)

        self._logger.debug(f"{self._tag()} {op}: submitted task_id={task_id}")

        start = time.monotonic()
        while (time.monotonic() - start) < timeout:
            task = self._tasks.get_task(task_id)
            if hasattr(task, 'status') and task.status:
                status_val = (
                    task.status.value
                    if hasattr(task.status, 'value')
                    else str(task.status)
                )
                if status_val in ('completed', 'failed', 'canceled'):
                    if status_val != 'completed':
                        raise FilesystemError(
                            f"{self._tag()} {op} task ended with status "
                            f"'{status_val}' (task_id={task_id})",
                            task_id=task_id,
                            status=status_val,
                        )
                    self._logger.debug(
                        f"{self._tag()} {op}: task_id={task_id} completed"
                    )
                    return task
            time.sleep(interval)

        raise FilesystemError(
            f"{self._tag()} {op} timed out after {timeout}s "
            f"(task_id={task_id})",
            task_id=task_id,
            status="timeout",
        )

    @staticmethod
    def _decode_result(task: Any) -> Any:
        """Return decoded task.result, base64-decoding if the API wrapped it.

        Some IRI deployments (e.g. ESnet) base64-encode the output field;
        others (e.g. NERSC) return plain text directly.  ``validate=True``
        makes the base64 attempt strict so plain-text strings are correctly
        rejected and returned as-is rather than decoded as garbage.
        """
        raw = task.result if task.result is not None else ''
        if isinstance(raw, dict) and 'output' in raw:
            output_val = raw['output']
            if isinstance(output_val, str):
                try:
                    return base64.b64decode(output_val, validate=True).decode('utf-8', errors='replace')
                except Exception:
                    # Not base64-encoded — return the plain string as-is.
                    return output_val
            return str(output_val)
        return raw

    @staticmethod
    def _result_dict(task: Any) -> Dict[str, Any]:
        """Return task.result as a dict, handling text/dict/None cases."""
        raw = IriFilesystem._decode_result(task)
        if isinstance(raw, dict):
            return raw
        return {'output': raw}

    # ------------------------------------------------------------------
    # FilesystemInterface implementation
    # ------------------------------------------------------------------

    def mkdir(self, resource_id: str, path: str, p: bool = True) -> Dict[str, Any]:
        # Dynamically import the request model so this module works with
        # either nersc_iri or esnet_iri (both expose identically named models).
        try:
            from nersc_iri.models.post_make_dir_request import PostMakeDirRequest
        except ImportError:
            from esnet_iri.models.post_make_dir_request import PostMakeDirRequest  # type: ignore

        self._logger.debug(f"{self._tag()} mkdir path={path!r}")
        req = PostMakeDirRequest(path=path, p=p)
        resp = self._fs.mkdir(resource_id, req)
        task = self._run_task(resp, op="mkdir")
        return self._result_dict(task)

    def ls(
        self,
        resource_id: str,
        path: str,
        *,
        show_hidden: bool = False,
        recursive: bool = False,
        format: bool = False,
    ) -> Union[Dict[str, Any], str]:
        self._logger.debug(f"{self._tag()} ls path={path!r}")
        resp = self._fs.ls(
            resource_id,
            path,
            show_hidden=show_hidden or None,
            recursive=recursive or None,
        )
        task = self._run_task(resp, op="ls")
        result = self._result_dict(task)
        if format:
            return self._format_ls_long(result)
        return result

    def stat(
        self,
        resource_id: str,
        path: str,
        *,
        dereference: bool = False,
    ) -> Dict[str, Any]:
        self._logger.debug(f"{self._tag()} stat path={path!r}")
        resp = self._fs.stat(
            resource_id,
            path,
            dereference=dereference or None,
        )
        task = self._run_task(resp, op="stat")
        return self._result_dict(task)

    def upload(
        self,
        resource_id: str,
        local_path: str,
        remote_path: str,
    ) -> Dict[str, Any]:
        local = Path(local_path).expanduser()
        self._logger.debug(
            f"{self._tag()} upload local={str(local)!r} -> remote={remote_path!r}"
        )
        file_bytes = local.read_bytes()
        resp = self._fs.upload(resource_id, path=remote_path, file=file_bytes)
        task = self._run_task(resp, op="upload")
        return self._result_dict(task)

    def download(
        self,
        resource_id: str,
        remote_path: str,
        local_path: str,
    ) -> str:
        self._logger.debug(
            f"{self._tag()} download remote={remote_path!r} -> local={local_path!r}"
        )
        resp = self._fs.download(resource_id, path=remote_path)
        task = self._run_task(resp, op="download")
        content = self._decode_result(task)
        if not isinstance(content, str):
            content = str(content)
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding='utf-8')
        self._logger.debug(f"{self._tag()} download saved -> {str(local)!r}")
        return str(local)

    def rm(self, resource_id: str, path: str) -> Dict[str, Any]:
        self._logger.debug(f"{self._tag()} rm path={path!r}")
        resp = self._fs.rm(resource_id, path=path)
        task = self._run_task(resp, op="rm")
        return self._result_dict(task)

    def mv(self, resource_id: str, src: str, dst: str) -> Dict[str, Any]:
        try:
            from nersc_iri.models.post_move_request import PostMoveRequest
        except ImportError:
            from esnet_iri.models.post_move_request import PostMoveRequest  # type: ignore

        self._logger.debug(f"{self._tag()} mv {src!r} -> {dst!r}")
        req = PostMoveRequest(source_path=src, target_path=dst)
        resp = self._fs.mv(resource_id, req)
        task = self._run_task(resp, op="mv")
        return self._result_dict(task)

    def cp(self, resource_id: str, src: str, dst: str) -> Dict[str, Any]:
        try:
            from nersc_iri.models.post_copy_request import PostCopyRequest
        except ImportError:
            from esnet_iri.models.post_copy_request import PostCopyRequest  # type: ignore

        self._logger.debug(f"{self._tag()} cp {src!r} -> {dst!r}")
        req = PostCopyRequest(source_path=src, target_path=dst)
        resp = self._fs.cp(resource_id, req)
        task = self._run_task(resp, op="cp")
        return self._result_dict(task)

    def chmod(self, resource_id: str, path: str, mode: str) -> Dict[str, Any]:
        try:
            from nersc_iri.models.put_file_chmod_request import PutFileChmodRequest
        except ImportError:
            from esnet_iri.models.put_file_chmod_request import PutFileChmodRequest  # type: ignore

        self._logger.debug(f"{self._tag()} chmod path={path!r} mode={mode!r}")
        req = PutFileChmodRequest(path=path, mode=mode)
        resp = self._fs.chmod(resource_id, req)
        task = self._run_task(resp, op="chmod")
        return self._result_dict(task)

    def head(
        self,
        resource_id: str,
        path: str,
        *,
        lines: Optional[int] = None,
        bytes: Optional[int] = None,
    ) -> str:
        self._logger.debug(f"{self._tag()} head path={path!r} lines={lines} bytes={bytes}")
        resp = self._fs.head(resource_id, path=path, lines=lines, bytes=bytes)
        task = self._run_task(resp, op="head")
        content = self._decode_result(task)
        return content if isinstance(content, str) else str(content)

    def tail(
        self,
        resource_id: str,
        path: str,
        *,
        lines: Optional[int] = None,
        bytes: Optional[int] = None,
    ) -> str:
        self._logger.debug(f"{self._tag()} tail path={path!r} lines={lines} bytes={bytes}")
        resp = self._fs.tail(resource_id, path=path, lines=lines, bytes=bytes)
        task = self._run_task(resp, op="tail")
        content = self._decode_result(task)
        return content if isinstance(content, str) else str(content)

    def checksum(self, resource_id: str, path: str) -> str:
        self._logger.debug(f"{self._tag()} checksum path={path!r}")
        resp = self._fs.checksum(resource_id, path=path)
        task = self._run_task(resp, op="checksum")
        return self._decode_result(task) or ''

    def compress(
        self,
        resource_id: str,
        path: str,
        target_path: str,
        *,
        dereference: bool = False,
    ) -> Dict[str, Any]:
        try:
            from nersc_iri.models.post_compress_request import PostCompressRequest
        except ImportError:
            from esnet_iri.models.post_compress_request import PostCompressRequest  # type: ignore

        self._logger.debug(
            f"{self._tag()} compress path={path!r} -> {target_path!r}"
        )
        req = PostCompressRequest(
            source_path=path,
            target_path=target_path,
            dereference=dereference or None,
        )
        resp = self._fs.compress(resource_id, req)
        task = self._run_task(resp, op="compress")
        return self._result_dict(task)

    def extract(
        self,
        resource_id: str,
        path: str,
        target_path: str,
    ) -> Dict[str, Any]:
        try:
            from nersc_iri.models.post_extract_request import PostExtractRequest
        except ImportError:
            from esnet_iri.models.post_extract_request import PostExtractRequest  # type: ignore

        self._logger.debug(
            f"{self._tag()} extract path={path!r} -> {target_path!r}"
        )
        req = PostExtractRequest(source_path=path, target_path=target_path)
        resp = self._fs.extract(resource_id, req)
        task = self._run_task(resp, op="extract")
        return self._result_dict(task)

    def symlink(
        self,
        resource_id: str,
        link_path: str,
        target_path: str,
    ) -> Dict[str, Any]:
        try:
            from nersc_iri.models.post_file_symlink_request import PostFileSymlinkRequest
        except ImportError:
            from esnet_iri.models.post_file_symlink_request import PostFileSymlinkRequest  # type: ignore

        self._logger.debug(
            f"{self._tag()} symlink {link_path!r} -> {target_path!r}"
        )
        req = PostFileSymlinkRequest(link_path=link_path, target_path=target_path)
        resp = self._fs.symlink(resource_id, req)
        task = self._run_task(resp, op="symlink")
        return self._result_dict(task)
