"""Filesystem interface for IRI API v2 (amsc-iri-v2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from amscrot.serviceclient.amsc_iri.filesystem import IriFilesystemBase


class IriFilesystemV2(IriFilesystemBase):
    """Filesystem interface for IRI API v2 endpoints (amsc-iri-v2)."""

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
        req = {
            "path": path,
            "show_hidden": show_hidden or None,
            "recursive": recursive or None,
        }
        resp = self._fs.ls(resource_id, req)
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
        req = {
            "path": path,
            "dereference": dereference or None,
        }
        resp = self._fs.stat(resource_id, req)
        task = self._run_task(resp, op="stat")
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
        resp = self._fs.download(resource_id, {"path": remote_path})
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
        resp = self._fs.rm(resource_id, {"path": path})
        task = self._run_task(resp, op="rm")
        return self._result_dict(task)

    def mv(self, resource_id: str, src: str, dst: str) -> Dict[str, Any]:
        self._logger.debug(f"{self._tag()} mv {src!r} -> {dst!r}")
        req = {"path": src, "target_path": dst}
        resp = self._fs.mv(resource_id, req)
        task = self._run_task(resp, op="mv")
        return self._result_dict(task)

    def cp(self, resource_id: str, src: str, dst: str) -> Dict[str, Any]:
        self._logger.debug(f"{self._tag()} cp {src!r} -> {dst!r}")
        req = {"path": src, "target_path": dst}
        resp = self._fs.cp(resource_id, req)
        task = self._run_task(resp, op="cp")
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
        req = {"path": path, "lines": lines, "bytes": bytes}
        resp = self._fs.head(resource_id, req)
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
        req = {"path": path, "lines": lines, "bytes": bytes}
        resp = self._fs.tail(resource_id, req)
        task = self._run_task(resp, op="tail")
        content = self._decode_result(task)
        return content if isinstance(content, str) else str(content)

    def checksum(self, resource_id: str, path: str) -> str:
        self._logger.debug(f"{self._tag()} checksum path={path!r}")
        resp = self._fs.checksum(resource_id, {"path": path})
        task = self._run_task(resp, op="checksum")
        return self._decode_result(task) or ''

    def symlink(
        self,
        resource_id: str,
        link_path: str,
        target_path: str,
    ) -> Dict[str, Any]:
        self._logger.debug(
            f"{self._tag()} symlink {link_path!r} -> {target_path!r}"
        )
        req = {"path": target_path, "link_path": link_path}
        resp = self._fs.symlink(resource_id, req)
        task = self._run_task(resp, op="symlink")
        return self._result_dict(task)
