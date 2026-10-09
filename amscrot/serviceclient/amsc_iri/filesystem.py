"""Base filesystem interface for IRI-based ServiceClients.

Provides ``IriFilesystemBase`` which implements common task polling,
result decoding, ls output formatting, and operations with identical
calling conventions across API versions (mkdir, upload, chmod, compress, extract).

Version-specific implementations are in:
- ``amscrot.serviceclient.amsc_iri._v1.filesystem.IriFilesystemV1``
- ``amscrot.serviceclient.amsc_iri._v2.filesystem.IriFilesystemV2``
"""

from __future__ import annotations

import ast
import base64
import datetime
import os
import time
from abc import ABC
from pathlib import Path
from typing import Any, Dict, Optional, Union

from amscrot.serviceclient.filesystem import FilesystemInterface, FilesystemError

__all__ = ["IriFilesystemBase"]


def _mode_to_str(mode: int, ftype: str) -> str:
    """Convert an integer mode + file-type string to a 10-char permission string.

    Example: mode=0o755, ftype='directory' -> 'drwxr-xr-x'
    """
    type_char = {'directory': 'd', 'symlink': 'l'}.get(ftype, '-')
    chars = []
    for shift in (6, 3, 0):          # owner, group, other
        chars.append('r' if (mode >> (shift + 2)) & 1 else '-')
        chars.append('w' if (mode >> (shift + 1)) & 1 else '-')
        chars.append('x' if (mode >> shift) & 1 else '-')
    return type_char + ''.join(chars)


class IriFilesystemBase(FilesystemInterface, ABC):
    """Base class for IRI filesystem interfaces backed by FilesystemApi + TaskApi.

    Provides common task polling, base64 decoding, ls formatting, and shared
    operations (mkdir, upload, chmod, compress, extract).

    Version-specific differences (API v1 vs v2) are implemented in subclasses
    (:class:`IriFilesystemV1` and :class:`IriFilesystemV2`).

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

        if isinstance(raw, list):
            return raw

        if isinstance(raw, str):
            try:
                parsed = ast.literal_eval(raw)
            except Exception:
                return []
            if isinstance(parsed, dict):
                inner = parsed.get('output', [])
                return inner if isinstance(inner, list) else []
            if isinstance(parsed, list):
                return parsed

        if isinstance(raw, dict) and 'output' in raw:
            return IriFilesystemBase._parse_ls_entries({'output': raw['output']})

        return []

    @staticmethod
    def _format_ls_long(result: Dict[str, Any]) -> str:
        """Render an ls result as ``ls -al`` style text."""
        entries = IriFilesystemBase._parse_ls_entries(result)
        if not entries:
            return 'total 0'

        lines = []
        for entry in entries:
            ftype = entry.get('type', 'file')
            perms_raw = entry.get('permissions', '0o644')
            try:
                mode = int(perms_raw, 8) if isinstance(perms_raw, str) else int(perms_raw)
            except (ValueError, TypeError):
                mode = 0o644
            perm_str = _mode_to_str(mode, ftype)

            user = str(entry.get('user', '-'))
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
        """Poll TaskApi until the task reaches a terminal state."""
        timeout = timeout if timeout is not None else self._timeout
        interval = interval if interval is not None else self._interval
        task_id = getattr(task_response, 'task_id', None) or str(task_response)

        self._logger.debug(f"{self._tag()} {op}: submitted task_id={task_id}")

        start = time.monotonic()
        while time.monotonic() - start < timeout:
            task = self._tasks.get_task(task_id)
            if task and task.status:
                status_val = (
                    task.status.value
                    if hasattr(task.status, 'value')
                    else str(task.status)
                ).lower()
                if status_val in ("completed", "failed", "canceled", "cancelled"):
                    if status_val in ("failed", "canceled", "cancelled"):
                        detail = f": {task.error}" if getattr(task, 'error', None) else ""
                        raise FilesystemError(
                            f"{self._tag()} {op} ended with status "
                            f"'{status_val}' (task_id={task_id}){detail}",
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
        """Return decoded task.result, base64-decoding if the API wrapped it."""
        raw = task.result if task.result is not None else ''
        if isinstance(raw, dict) and 'output' in raw:
            output_val = raw['output']
            if isinstance(output_val, str):
                try:
                    return base64.b64decode(output_val, validate=True).decode('utf-8', errors='replace')
                except Exception:
                    return output_val
            return str(output_val)
        return raw

    @staticmethod
    def _result_dict(task: Any) -> Dict[str, Any]:
        """Return task.result as a dict, handling text/dict/None cases."""
        raw = IriFilesystemBase._decode_result(task)
        if isinstance(raw, dict):
            return raw
        return {'output': raw}

    # ------------------------------------------------------------------
    # Common filesystem operations
    # ------------------------------------------------------------------

    def mkdir(self, resource_id: str, path: str, p: bool = True) -> Dict[str, Any]:
        self._logger.debug(f"{self._tag()} mkdir path={path!r}")
        req = {"path": path, "parent": p}
        resp = self._fs.mkdir(resource_id, req)
        task = self._run_task(resp, op="mkdir")
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
        return self.upload_bytes(resource_id, local.read_bytes(), remote_path)

    def upload_bytes(
        self,
        resource_id: str,
        data: bytes,
        remote_path: str,
    ) -> Dict[str, Any]:
        self._logger.debug(
            f"{self._tag()} upload_bytes ({len(data)} bytes) -> remote={remote_path!r}"
        )
        resp = self._fs.upload(resource_id, path=remote_path, file=data)
        task = self._run_task(resp, op="upload")
        return self._result_dict(task)

    def chmod(self, resource_id: str, path: str, mode: str) -> Dict[str, Any]:
        self._logger.debug(f"{self._tag()} chmod path={path!r} mode={mode!r}")
        req = {"path": path, "mode": mode}
        resp = self._fs.chmod(resource_id, req)
        task = self._run_task(resp, op="chmod")
        return self._result_dict(task)

    def compress(
        self,
        resource_id: str,
        path: str,
        target_path: str,
        *,
        dereference: bool = False,
    ) -> Dict[str, Any]:
        self._logger.debug(
            f"{self._tag()} compress path={path!r} -> {target_path!r}"
        )
        req = {
            "source_path": path,
            "target_path": target_path,
            "dereference": dereference or None,
        }
        resp = self._fs.compress(resource_id, req)
        task = self._run_task(resp, op="compress")
        return self._result_dict(task)

    def extract(
        self,
        resource_id: str,
        path: str,
        target_path: str,
    ) -> Dict[str, Any]:
        self._logger.debug(
            f"{self._tag()} extract path={path!r} -> {target_path!r}"
        )
        req = {"source_path": path, "target_path": target_path}
        resp = self._fs.extract(resource_id, req)
        task = self._run_task(resp, op="extract")
        return self._result_dict(task)
