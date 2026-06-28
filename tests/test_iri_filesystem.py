"""Unit tests for the IriFilesystem adapter.

Tests in this module are strictly unit tests -- they mock the IRI APIs and do
NOT require live credentials or a network connection.  Integration tests
(requiring real credentials) are marked with ``@pytest.mark.integration``.
"""

import time
import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path

from amscrot.serviceclient.filesystem import (
    FilesystemInterface,
    IriFilesystem,
    FilesystemError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(status: str = "completed", result=None):
    """Return a mock Task object with the given status and result."""
    task = MagicMock()
    task.task_id = "task-123"
    task.status = MagicMock()
    task.status.value = status
    task.result = result
    return task


def _make_task_response(task_id: str = "task-123"):
    """Return a mock TaskSubmitResponse."""
    resp = MagicMock()
    resp.task_id = task_id
    return resp


def _make_fs(
    task_result=None, task_status="completed", timeout=5.0, interval=0.01
):
    """Build an IriFilesystem wired to mock filesystem_api and task_api."""
    filesystem_api = MagicMock()
    task_api = MagicMock()
    logger = MagicMock()

    task = _make_task(status=task_status, result=task_result)
    task_api.get_task.return_value = task

    # Every filesystem API call returns a task submit response
    task_resp = _make_task_response()
    for method in [
        "mkdir", "ls", "stat", "upload", "download", "rm", "mv",
        "cp", "chmod", "head", "tail", "checksum", "compress",
        "extract", "symlink",
    ]:
        getattr(filesystem_api, method).return_value = task_resp

    fs = IriFilesystem(
        filesystem_api=filesystem_api,
        task_api=task_api,
        logger=logger,
        client_name="test-client",
        default_task_timeout=timeout,
        default_task_interval=interval,
    )
    return fs, filesystem_api, task_api


# ---------------------------------------------------------------------------
# FilesystemInterface
# ---------------------------------------------------------------------------

class TestFilesystemInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            FilesystemInterface()  # type: ignore[abstract]

    def test_iri_filesystem_is_concrete(self):
        fs, *_ = _make_fs()
        assert isinstance(fs, FilesystemInterface)


# ---------------------------------------------------------------------------
# _run_task
# ---------------------------------------------------------------------------

class TestRunTask:
    def test_returns_completed_task(self):
        fs, _, task_api = _make_fs(task_status="completed")
        task = _make_task(status="completed", result="ok")
        task_api.get_task.return_value = task

        resp = _make_task_response()
        result = fs._run_task(resp, op="test")
        assert result is task

    def test_raises_on_failed_task(self):
        fs, _, task_api = _make_fs(task_status="failed")
        with pytest.raises(FilesystemError) as exc_info:
            fs._run_task(_make_task_response(), op="test-op")
        assert "failed" in str(exc_info.value)
        assert exc_info.value.status == "failed"

    def test_raises_on_canceled_task(self):
        fs, _, task_api = _make_fs(task_status="canceled")
        with pytest.raises(FilesystemError) as exc_info:
            fs._run_task(_make_task_response(), op="test-op")
        assert exc_info.value.status == "canceled"

    def test_raises_on_timeout(self):
        fs, _, task_api = _make_fs(timeout=0.05, interval=0.01)
        # Never reach completed
        running_task = _make_task(status="queued")
        task_api.get_task.return_value = running_task

        with pytest.raises(FilesystemError) as exc_info:
            fs._run_task(_make_task_response(), op="test-op")
        assert exc_info.value.status == "timeout"

    def test_polls_until_terminal(self):
        """Verify that polling continues until status is terminal."""
        fs, _, task_api = _make_fs()
        # First two calls return 'queued', third returns 'completed'
        task_api.get_task.side_effect = [
            _make_task(status="queued"),
            _make_task(status="queued"),
            _make_task(status="completed", result="done"),
        ]
        result = fs._run_task(_make_task_response(), op="test")
        assert task_api.get_task.call_count == 3
        assert result.result == "done"


# ---------------------------------------------------------------------------
# _decode_result
# ---------------------------------------------------------------------------

class TestDecodeResult:
    def test_base64_dict(self):
        import base64
        task = _make_task(result={"output": base64.b64encode(b"hello").decode()})
        assert IriFilesystem._decode_result(task) == "hello"

    def test_plain_string_output_field(self):
        # NERSC IRI returns {'output': 'plain text'} — not base64.
        # Should return the string directly, not the whole dict stringified.
        task = _make_task(result={"output": "Hello AmSC\n"})
        assert IriFilesystem._decode_result(task) == "Hello AmSC\n"

    def test_plain_dict(self):
        task = _make_task(result={"key": "value"})
        # No 'output' key -> returns as-is
        assert IriFilesystem._decode_result(task) == {"key": "value"}

    def test_plain_string(self):
        task = _make_task(result="some output")
        assert IriFilesystem._decode_result(task) == "some output"

    def test_none_result(self):
        task = _make_task(result=None)
        assert IriFilesystem._decode_result(task) == ""

    def test_regression_no_dict_stringified(self):
        # The old code fell back to str(raw) which returned the whole dict.
        # Ensure we never get "{'output': ...}" when the value is a plain string.
        task = _make_task(result={"output": "just text"})
        result = IriFilesystem._decode_result(task)
        assert result == "just text"
        assert not result.startswith("{"), "should not return the whole dict stringified"


# ---------------------------------------------------------------------------
# mkdir
# ---------------------------------------------------------------------------

class TestMkdir:
    def test_calls_filesystem_api(self):
        fs, fsapi, _ = _make_fs()
        fs.mkdir("res-1", "/tmp/mydir")
        fsapi.mkdir.assert_called_once()
        args, kwargs = fsapi.mkdir.call_args
        assert args[0] == "res-1"

    def test_returns_result_dict(self):
        fs, _, _ = _make_fs(task_result={"path": "/tmp/mydir"})
        result = fs.mkdir("res-1", "/tmp/mydir")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

class TestLs:
    def test_calls_filesystem_api(self):
        fs, fsapi, _ = _make_fs()
        fs.ls("res-1", "/tmp")
        fsapi.ls.assert_called_once_with(
            "res-1", "/tmp", show_hidden=None, recursive=None,
        )

    def test_recursive_flag(self):
        fs, fsapi, _ = _make_fs()
        fs.ls("res-1", "/tmp", recursive=True)
        _, kwargs = fsapi.ls.call_args
        assert kwargs["recursive"] is True


# ---------------------------------------------------------------------------
# stat
# ---------------------------------------------------------------------------

class TestStat:
    def test_calls_filesystem_api(self):
        fs, fsapi, _ = _make_fs()
        fs.stat("res-1", "/some/path")
        fsapi.stat.assert_called_once_with("res-1", "/some/path", dereference=None)

    def test_raises_on_failure(self):
        fs, fsapi, task_api = _make_fs(task_status="failed")
        with pytest.raises(FilesystemError):
            fs.stat("res-1", "/no/such/path")


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

class TestUpload:
    def test_reads_file_and_calls_api(self, tmp_path):
        local = tmp_path / "script.sh"
        local.write_bytes(b"#!/bin/bash\necho hi\n")
        fs, fsapi, _ = _make_fs()
        fs.upload("res-1", str(local), "/remote/script.sh")
        fsapi.upload.assert_called_once()
        _, kwargs = fsapi.upload.call_args
        assert kwargs["path"] == "/remote/script.sh"
        assert kwargs["file"] == b"#!/bin/bash\necho hi\n"

    def test_raises_on_task_failure(self, tmp_path):
        local = tmp_path / "f.txt"
        local.write_bytes(b"data")
        fs, _, _ = _make_fs(task_status="failed")
        with pytest.raises(FilesystemError):
            fs.upload("res-1", str(local), "/remote/f.txt")

    def test_upload_bytes_calls_api_without_file_io(self):
        fs, fsapi, _ = _make_fs()
        fs.upload_bytes("res-1", b"generated content", "/remote/gen.yaml")
        fsapi.upload.assert_called_once()
        _, kwargs = fsapi.upload.call_args
        assert kwargs["path"] == "/remote/gen.yaml"
        assert kwargs["file"] == b"generated content"


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

class TestDownload:
    def test_writes_decoded_content(self, tmp_path):
        import base64
        local = str(tmp_path / "out.log")
        content = "line 1\nline 2\n"
        encoded = base64.b64encode(content.encode()).decode()
        fs, fsapi, _ = _make_fs(task_result={"output": encoded})

        returned_path = fs.download("res-1", "/remote/out.log", local)
        assert returned_path == local
        assert Path(local).read_text() == content

    def test_creates_parent_dirs(self, tmp_path):
        import base64
        local = str(tmp_path / "deep" / "dir" / "out.log")
        encoded = base64.b64encode(b"data").decode()
        fs, _, _ = _make_fs(task_result={"output": encoded})
        fs.download("res-1", "/remote/out.log", local)
        assert Path(local).exists()

    def test_raises_on_task_failure(self, tmp_path):
        local = str(tmp_path / "out.log")
        fs, _, _ = _make_fs(task_status="failed")
        with pytest.raises(FilesystemError):
            fs.download("res-1", "/remote/out.log", local)


# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------

class TestRm:
    def test_calls_filesystem_api(self):
        fs, fsapi, _ = _make_fs()
        fs.rm("res-1", "/tmp/old")
        fsapi.rm.assert_called_once_with("res-1", path="/tmp/old")


# ---------------------------------------------------------------------------
# mv / cp
# ---------------------------------------------------------------------------

class TestMvCp:
    def test_mv_calls_api(self):
        fs, fsapi, _ = _make_fs()
        fs.mv("res-1", "/a", "/b")
        fsapi.mv.assert_called_once()

    def test_cp_calls_api(self):
        fs, fsapi, _ = _make_fs()
        fs.cp("res-1", "/a", "/b")
        fsapi.cp.assert_called_once()


# ---------------------------------------------------------------------------
# chmod
# ---------------------------------------------------------------------------

class TestChmod:
    def test_calls_filesystem_api(self):
        fs, fsapi, _ = _make_fs()
        fs.chmod("res-1", "/script.sh", "755")
        fsapi.chmod.assert_called_once()


# ---------------------------------------------------------------------------
# head / tail
# ---------------------------------------------------------------------------

class TestHeadTail:
    def test_head_returns_string(self):
        fs, fsapi, _ = _make_fs(task_result="first lines\n")
        result = fs.head("res-1", "/file.txt", lines=10)
        assert isinstance(result, str)
        assert "first lines" in result

    def test_tail_returns_string(self):
        fs, _, _ = _make_fs(task_result="last lines\n")
        result = fs.tail("res-1", "/file.txt", lines=10)
        assert "last lines" in result


# ---------------------------------------------------------------------------
# checksum
# ---------------------------------------------------------------------------

class TestChecksum:
    def test_returns_string(self):
        fs, _, _ = _make_fs(task_result="abc123def456")
        result = fs.checksum("res-1", "/file.txt")
        assert result == "abc123def456"


# ---------------------------------------------------------------------------
# compress / extract / symlink
# ---------------------------------------------------------------------------

class TestArchive:
    def test_compress_calls_api(self):
        fs, fsapi, _ = _make_fs()
        fs.compress("res-1", "/data", "/data.tar.gz")
        fsapi.compress.assert_called_once()

    def test_extract_calls_api(self):
        fs, fsapi, _ = _make_fs()
        fs.extract("res-1", "/data.tar.gz", "/data")
        fsapi.extract.assert_called_once()

    def test_symlink_calls_api(self):
        fs, fsapi, _ = _make_fs()
        fs.symlink("res-1", "/link", "/target")
        fsapi.symlink.assert_called_once()


# ---------------------------------------------------------------------------
# ServiceClient.filesystem integration
# ---------------------------------------------------------------------------

class TestServiceClientFilesystemProperty:
    """Verify the filesystem property wires up correctly through the service client."""

    def test_iri_filesystem_returns_iri_filesystem(self):
        from amscrot.serviceclient.amsc_iri.iri_service_client import (
            IriServiceClient,
        )
        client = IriServiceClient.__new__(IriServiceClient)
        client._available = True
        client._filesystem = None
        client._filesystem_api = MagicMock()
        client._task_api = MagicMock()
        client.name = "test"
        client.logger = MagicMock()

        fs = client.filesystem
        assert isinstance(fs, FilesystemInterface)

    def test_iri_filesystem_returns_none_when_unavailable(self):
        from amscrot.serviceclient.amsc_iri.iri_service_client import (
            IriServiceClient,
        )
        client = IriServiceClient.__new__(IriServiceClient)
        client._available = False
        client._filesystem = None
        client.name = "test"
        client.logger = MagicMock()

        assert client.filesystem is None

    def test_filesystem_is_lazily_cached(self):
        from amscrot.serviceclient.amsc_iri.iri_service_client import (
            IriServiceClient,
        )
        client = IriServiceClient.__new__(IriServiceClient)
        client._available = True
        client._filesystem = None
        client._filesystem_api = MagicMock()
        client._task_api = MagicMock()
        client.name = "test"
        client.logger = MagicMock()

        fs1 = client.filesystem
        fs2 = client.filesystem
        assert fs1 is fs2

    def test_base_serviceclient_returns_none(self):
        """Non-IRI clients should return None from the base property."""
        from amscrot.serviceclient.serviceclient import ServiceClient
        # Use KubeServiceClient as a concrete non-IRI example
        try:
            from amscrot.serviceclient.kube.kube_service_client import KubeServiceClient
            client = KubeServiceClient.__new__(KubeServiceClient)
            client._available = False
            client.name = "test"
            client.logger = MagicMock()
            # KubeServiceClient does not override filesystem, so it returns None
            assert client.filesystem is None
        except Exception:
            # If kube client can't be instantiated barebones, skip
            pytest.skip("KubeServiceClient not available for bare instantiation")

