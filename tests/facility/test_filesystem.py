"""Unit tests for amscrot.facility.filesystem.FilesystemClient."""
import pytest
from unittest.mock import MagicMock, patch
from amscrot.facility.filesystem import FilesystemClient
from amscrot.facility.task import Task


def _make_client(resource_id="res-123"):
    """Build a FilesystemClient with a mock IriFilesystem and call_api."""
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [{"name": "file.txt"}]
    mock_fs.stat.return_value = {"size": 1024}
    mock_fs.head.return_value = "line1\nline2"
    mock_fs.tail.return_value = "lastline"
    mock_fs.mkdir.return_value = {}
    mock_fs.rm.return_value = {}
    mock_fs.cp.return_value = {}
    mock_fs.mv.return_value = {}
    mock_fs.chmod.return_value = {}
    mock_fs.checksum.return_value = "abc123"
    mock_fs.symlink.return_value = {}
    mock_fs.compress.return_value = {}
    mock_fs.extract.return_value = {}
    mock_fs.download.return_value = "/local/file.txt"
    mock_fs.upload.return_value = {}

    # call_api just calls the operation directly (no retry in tests)
    def call_api(operation, *args, **kwargs):
        return operation(*args, **kwargs)

    fc = FilesystemClient(
        resource_id=resource_id,
        iri_filesystem=mock_fs,
        call_api=call_api,
    )
    return fc, mock_fs


class TestFilesystemClientReturnsTask:
    def test_ls_returns_task(self):
        fc, _ = _make_client()
        result = fc.ls("/home/user")
        assert isinstance(result, Task)

    def test_stat_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.stat("/home/user/file.txt"), Task)

    def test_head_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.head("/home/user/file.txt", lines=10), Task)

    def test_tail_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.tail("/home/user/file.txt", lines=5), Task)

    def test_mkdir_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.mkdir("/home/user/newdir"), Task)

    def test_rm_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.rm("/home/user/file.txt"), Task)

    def test_cp_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.cp("/src", "/dst"), Task)

    def test_mv_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.mv("/src", "/dst"), Task)

    def test_chmod_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.chmod("/home/user/file.txt", "755"), Task)

    def test_checksum_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.checksum("/home/user/file.txt"), Task)

    def test_symlink_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.symlink("/target", "/link"), Task)

    def test_compress_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.compress("/src", "/dst.tar.gz"), Task)

    def test_extract_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.extract("/src.tar.gz", "/dst"), Task)

    def test_download_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.download("/remote/file.txt", "/local/file.txt"), Task)

    def test_upload_returns_task(self):
        fc, _ = _make_client()
        assert isinstance(fc.upload("/local/file.txt", "/remote/file.txt"), Task)


class TestFilesystemClientDelegation:
    def test_ls_passes_resource_id_and_path(self):
        fc, mock_fs = _make_client(resource_id="res-abc")
        fc.ls("/home/user")
        mock_fs.ls.assert_called_once_with("res-abc", "/home/user", recursive=False)

    def test_ls_recursive_flag(self):
        fc, mock_fs = _make_client()
        fc.ls("/home/user", recursive=True)
        mock_fs.ls.assert_called_once_with("res-123", "/home/user", recursive=True)

    def test_head_passes_lines(self):
        fc, mock_fs = _make_client()
        fc.head("/home/user/file.txt", lines=50)
        mock_fs.head.assert_called_once_with("res-123", "/home/user/file.txt", lines=50, bytes=None)

    def test_cp_does_not_forward_dereference(self):
        fc, mock_fs = _make_client()
        fc.cp("/src", "/dst", dereference=True)
        mock_fs.cp.assert_called_once_with("res-123", "/src", "/dst")

    def test_mkdir_defaults_parents_true(self):
        fc, mock_fs = _make_client()
        fc.mkdir("/home/user/newdir")
        mock_fs.mkdir.assert_called_once_with("res-123", "/home/user/newdir", p=True)

    def test_compress_passes_dereference_only(self):
        fc, mock_fs = _make_client()
        fc.compress("/src", "/dst.tar.gz", pattern="*.log", dereference=True, compression="gzip")
        mock_fs.compress.assert_called_once_with(
            "res-123", "/src", "/dst.tar.gz",
            dereference=True
        )

    def test_extract_no_kwargs_forwarded(self):
        fc, mock_fs = _make_client()
        fc.extract("/src.tar.gz", "/dst", compression="gzip")
        mock_fs.extract.assert_called_once_with("res-123", "/src.tar.gz", "/dst")

    def test_result_accessible_after_wait(self):
        fc, _ = _make_client()
        task = fc.ls("/home/user")
        task.wait()
        assert task.result == [{"name": "file.txt"}]


class TestFilesystemClientErrorHandling:
    def test_failed_operation_returns_failed_task(self):
        mock_fs = MagicMock()
        mock_fs.ls.side_effect = RuntimeError("IRI API error")

        def call_api(operation, *args, **kwargs):
            return operation(*args, **kwargs)

        fc = FilesystemClient(resource_id="res-123", iri_filesystem=mock_fs, call_api=call_api)
        task = fc.ls("/home/user")
        assert task.state == "failed"
        with pytest.raises(RuntimeError, match="IRI API error"):
            _ = task.result

    def test_repr(self):
        fc, _ = _make_client(resource_id="res-xyz")
        assert "res-xyz" in repr(fc)
