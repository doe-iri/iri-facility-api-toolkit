# High-Level Facility Convenience API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `amscrot/facility/` subpackage providing a Pythonic, minimal-boilerplate interface for IRI job submission that matches amsc-python-client's API surface for future re-export.

**Architecture:** A new `amscrot/facility/` subpackage wraps AmSCROT's existing `IriServiceClient`, `Session`, `JobSpec`, and `Job` internals behind five clean classes: `FacilityClient`, `Resource`, `Job`, `FilesystemClient`, and `Task`. The existing `amscrot.client.Client` gains one new `.facility()` method as its entry point. No existing files are modified except `amscrot/client/client.py`.

**Tech Stack:** Python 3.10+, pytest + unittest.mock (tests), AmSCROT internals (`IriServiceClient`, `ServiceClient`, `Session`, `JobSpec`, `Job` from `amscrot.client.job`), `amsc_iri` generated client (already a dependency).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `amscrot/facility/__init__.py` | Create | Public exports |
| `amscrot/facility/task.py` | Create | `Task` — wraps a completed IriFilesystem result as async-compatible object |
| `amscrot/facility/filesystem.py` | Create | `FilesystemClient` — resource-scoped filesystem ops returning `Task` |
| `amscrot/facility/models.py` | Create | `Resource`, `Job` — self-aware wrappers over discovered resources and submitted jobs |
| `amscrot/facility/client.py` | Create | `FacilityClient` — main convenience object, owns IriServiceClient + implicit Session |
| `amscrot/client/client.py` | Modify | Add `.facility()` method (one method, ~10 lines) |
| `tests/facility/test_task.py` | Create | Unit tests for `Task` |
| `tests/facility/test_filesystem.py` | Create | Unit tests for `FilesystemClient` |
| `tests/facility/test_models.py` | Create | Unit tests for `Resource` and `Job` |
| `tests/facility/test_facility_client.py` | Create | Unit tests for `FacilityClient` |
| `tests/facility/test_client_facility_method.py` | Create | Unit tests for `Client.facility()` |
| `tests/facility/__init__.py` | Create | Empty, marks directory as package |

---

## Task 1: Task class

**Files:**
- Create: `amscrot/facility/task.py`
- Create: `tests/facility/__init__.py`
- Create: `tests/facility/test_task.py`

- [ ] **Step 1: Create test directory and write failing tests**

Create `tests/facility/__init__.py` (empty file), then create `tests/facility/test_task.py`:

```python
"""Unit tests for amscrot.facility.task.Task."""
import pytest
from amscrot.facility.task import Task, TERMINAL_TASK_STATES


class TestTaskConstants:
    def test_terminal_states_are_frozenset(self):
        assert isinstance(TERMINAL_TASK_STATES, frozenset)

    def test_terminal_states_contents(self):
        assert TERMINAL_TASK_STATES == frozenset({"completed", "failed", "canceled"})


class TestTaskSuccess:
    def test_state_is_completed_on_success(self):
        task = Task(result={"output": "hello"})
        assert task.state == "completed"

    def test_is_terminal_true_on_success(self):
        task = Task(result={"output": "hello"})
        assert task.is_terminal is True

    def test_result_returns_value(self):
        task = Task(result={"output": "hello"})
        assert task.result == {"output": "hello"}

    def test_result_can_be_none(self):
        task = Task(result=None)
        assert task.result is None

    def test_wait_returns_self(self):
        task = Task(result="done")
        returned = task.wait()
        assert returned is task

    def test_wait_ignores_timeout(self):
        task = Task(result="done")
        # Should not raise even with tiny timeout since it's a no-op
        task.wait(timeout=0, poll_interval=0)

    def test_repr_shows_state(self):
        task = Task(result="done")
        assert "completed" in repr(task)


class TestTaskFailure:
    def test_state_is_failed_on_error(self):
        task = Task(error=ValueError("bad"))
        assert task.state == "failed"

    def test_is_terminal_true_on_error(self):
        task = Task(error=ValueError("bad"))
        assert task.is_terminal is True

    def test_result_raises_stored_exception(self):
        exc = RuntimeError("IRI API error")
        task = Task(error=exc)
        with pytest.raises(RuntimeError, match="IRI API error"):
            _ = task.result

    def test_wait_returns_self_on_failure(self):
        task = Task(error=ValueError("bad"))
        returned = task.wait()
        assert returned is task


class TestTaskDefaultState:
    def test_requires_result_or_error(self):
        # Task with neither result nor error defaults to completed with None result
        task = Task()
        assert task.state == "completed"
        assert task.result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_task.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'amscrot.facility'`

- [ ] **Step 3: Create `amscrot/facility/task.py`**

```python
"""Async-compatible wrapper for IRI filesystem operation results."""
from __future__ import annotations

TERMINAL_TASK_STATES = frozenset({"completed", "failed", "canceled"})


class Task:
    """Wraps a completed IriFilesystem operation as an async-compatible object.

    IriFilesystem operations are synchronous — they poll the IRI TaskApi
    internally and return the final result. This class wraps that result
    so callers can use the same ``task.wait(); task.result`` pattern as
    amsc-python-client, making a future switch to true async transparent.

    Args:
        result: The operation output (on success).
        error: The exception to raise on ``.result`` access (on failure).
    """

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    @property
    def state(self) -> str:
        """Operation state: 'completed' or 'failed'."""
        return "failed" if self._error else "completed"

    @property
    def is_terminal(self) -> bool:
        """Always True — Task objects are fully resolved at construction."""
        return True

    @property
    def result(self):
        """Operation output. Raises the stored exception if the operation failed."""
        if self._error is not None:
            raise self._error
        return self._result

    def wait(self, timeout: int = 300, poll_interval: int = 2) -> "Task":
        """No-op — the operation is already complete.

        Exists for API compatibility with amsc-python-client. If async
        execution is added later, callers need no changes.
        """
        return self

    def __repr__(self) -> str:
        return f"Task(state={self.state!r})"
```

- [ ] **Step 4: Create `amscrot/facility/__init__.py` (stub — full exports added in Task 5)**

```python
"""High-level facility convenience API for AmSCROT."""
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_task.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add amscrot/facility/__init__.py amscrot/facility/task.py tests/facility/__init__.py tests/facility/test_task.py
git commit -m "feat(facility): add Task class with async-compatible interface"
```

---

## Task 2: FilesystemClient

**Files:**
- Create: `amscrot/facility/filesystem.py`
- Create: `tests/facility/test_filesystem.py`

**Context:** `FilesystemClient` is scoped to a single `resource_id`. It delegates to `IriFilesystem` methods (which all require `resource_id` as first arg) and wraps each result in a `Task`. All delegation goes through `FacilityClient._call_api()` for token-refresh support — but since `FacilityClient` doesn't exist yet, we'll accept it as an injected callable in the constructor for testing.

- [ ] **Step 1: Write failing tests**

Create `tests/facility/test_filesystem.py`:

```python
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

    def test_cp_passes_dereference(self):
        fc, mock_fs = _make_client()
        fc.cp("/src", "/dst", dereference=True)
        mock_fs.cp.assert_called_once_with("res-123", "/src", "/dst", dereference=True)

    def test_mkdir_defaults_parents_true(self):
        fc, mock_fs = _make_client()
        fc.mkdir("/home/user/newdir")
        mock_fs.mkdir.assert_called_once_with("res-123", "/home/user/newdir", p=True)

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_filesystem.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'FilesystemClient' from 'amscrot.facility.filesystem'`

- [ ] **Step 3: Create `amscrot/facility/filesystem.py`**

```python
"""Resource-scoped filesystem client returning Task objects."""
from __future__ import annotations

from typing import Callable, Any

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

    def _run(self, method: str, *args, **kwargs) -> Task:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_filesystem.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add amscrot/facility/filesystem.py tests/facility/test_filesystem.py
git commit -m "feat(facility): add FilesystemClient returning Task objects"
```

---

## Task 3: Resource and Job models

**Files:**
- Create: `amscrot/facility/models.py`
- Create: `tests/facility/test_models.py`

**Context:** `Resource` wraps a `DiscoveredResource.data` dict (from `IriServiceClient.discover()`). `Job` wraps an `amscrot.client.job.Job` and is self-aware (can refresh/wait/cancel itself). Both delegate API calls through a `FacilityClient` reference — for testing we inject a mock. `Job.TERMINAL_STATES` uses uppercase strings matching AmSCROT's `JobState` enum values.

- [ ] **Step 1: Write failing tests**

Create `tests/facility/test_models.py`:

```python
"""Unit tests for amscrot.facility.models — Resource and Job."""
import time
import pytest
from unittest.mock import MagicMock, patch
from amscrot.facility.models import Resource, Job, TERMINAL_STATES
from amscrot.facility.filesystem import FilesystemClient


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_resource(resource_id="res-123", name="Polaris", resource_type="compute",
                   status="up"):
    data = {
        "id": resource_id,
        "name": name,
        "resource_type": resource_type,
        "current_status": status,
    }
    mock_facility = MagicMock()
    return Resource(data=data, facility_client=mock_facility), mock_facility


def _make_amscrot_job(job_id="job-456", state="QUEUED", exit_code=None, message=None):
    """Build a mock amscrot.client.job.Job."""
    job = MagicMock()
    job.id = job_id
    job.status = MagicMock()
    job.status.value = state
    job.status.state = state
    return job


def _make_job(job_id="job-456", initial_state="QUEUED"):
    amscrot_job = _make_amscrot_job(job_id=job_id, state=initial_state)
    mock_facility = MagicMock()

    # Default status return for refresh
    mock_status = MagicMock()
    mock_status.state = initial_state
    mock_status.exit_code = None
    mock_status.message = None
    mock_facility._call_api.return_value = mock_status

    job = Job(amscrot_job=amscrot_job, resource_id="res-123", facility_client=mock_facility)
    return job, mock_facility, mock_status


# ── Resource tests ─────────────────────────────────────────────────────────

class TestResource:
    def test_id_property(self):
        r, _ = _make_resource(resource_id="res-abc")
        assert r.id == "res-abc"

    def test_name_property(self):
        r, _ = _make_resource(name="Polaris")
        assert r.name == "Polaris"

    def test_resource_type_property(self):
        r, _ = _make_resource(resource_type="compute")
        assert r.resource_type == "compute"

    def test_status_property_string(self):
        r, _ = _make_resource(status="up")
        assert r.status == "up"

    def test_status_property_with_enum(self):
        data = {"id": "r1", "name": "R", "resource_type": "compute",
                "current_status": MagicMock(value="degraded")}
        r = Resource(data=data, facility_client=MagicMock())
        assert r.status == "degraded"

    def test_status_defaults_to_unknown_when_missing(self):
        data = {"id": "r1", "name": "R", "resource_type": "compute"}
        r = Resource(data=data, facility_client=MagicMock())
        assert r.status == "unknown"

    def test_fs_returns_filesystem_client(self):
        r, mock_facility = _make_resource()
        mock_facility._service_client.filesystem = MagicMock()
        mock_facility._call_api = lambda op, *a, **kw: op(*a, **kw)
        fs = r.fs
        assert isinstance(fs, FilesystemClient)

    def test_fs_is_cached(self):
        r, mock_facility = _make_resource()
        mock_facility._service_client.filesystem = MagicMock()
        mock_facility._call_api = lambda op, *a, **kw: op(*a, **kw)
        fs1 = r.fs
        fs2 = r.fs
        assert fs1 is fs2

    def test_submit_delegates_to_facility(self):
        r, mock_facility = _make_resource()
        r.submit(executable="/bin/echo", nodes=1, queue="debug")
        mock_facility._submit_job.assert_called_once()
        call_kwargs = mock_facility._submit_job.call_args[1]
        assert call_kwargs["resource_id"] == "res-123"
        assert call_kwargs["executable"] == "/bin/echo"
        assert call_kwargs["nodes"] == 1
        assert call_kwargs["queue"] == "debug"

    def test_submit_passes_custom_attributes(self):
        r, mock_facility = _make_resource()
        r.submit(executable="/bin/echo", filesystems="home", constraint="gpu")
        call_kwargs = mock_facility._submit_job.call_args[1]
        assert call_kwargs["custom_attributes"] == {"filesystems": "home", "constraint": "gpu"}

    def test_repr(self):
        r, _ = _make_resource(name="Polaris", resource_type="compute")
        assert "Polaris" in repr(r)
        assert "compute" in repr(r)


# ── Job tests ──────────────────────────────────────────────────────────────

class TestJobConstants:
    def test_terminal_states(self):
        assert TERMINAL_STATES == frozenset({"COMPLETED", "FAILED", "CANCELED"})


class TestJobProperties:
    def test_id_property(self):
        job, _, _ = _make_job(job_id="job-xyz")
        assert job.id == "job-xyz"

    def test_state_returns_cached_state(self):
        job, _, mock_status = _make_job(initial_state="QUEUED")
        # Before first refresh, state comes from amscrot_job
        assert job.state in ("QUEUED", "unknown")

    def test_is_terminal_false_for_queued(self):
        job, mock_facility, mock_status = _make_job(initial_state="QUEUED")
        mock_status.state = "QUEUED"
        job.refresh()
        assert job.is_terminal is False

    def test_is_terminal_true_for_completed(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.state = "COMPLETED"
        job.refresh()
        assert job.is_terminal is True

    def test_is_terminal_true_for_failed(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.state = "FAILED"
        job.refresh()
        assert job.is_terminal is True

    def test_is_terminal_true_for_canceled(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.state = "CANCELED"
        job.refresh()
        assert job.is_terminal is True

    def test_exit_code_after_refresh(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.exit_code = 0
        job.refresh()
        assert job.exit_code == 0

    def test_message_after_refresh(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.message = "Job completed successfully"
        job.refresh()
        assert job.message == "Job completed successfully"


class TestJobRefresh:
    def test_refresh_calls_service_client_status(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.state = "ACTIVE"
        state = job.refresh()
        assert state == "ACTIVE"
        mock_facility._call_api.assert_called_once()

    def test_status_property_calls_refresh(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.state = "COMPLETED"
        _ = job.status
        mock_facility._call_api.assert_called_once()


class TestJobWait:
    def test_wait_returns_self_when_terminal(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.state = "COMPLETED"
        result = job.wait(timeout=5, poll_interval=0)
        assert result is job

    def test_wait_polls_until_terminal(self):
        job, mock_facility, mock_status = _make_job()
        states = ["QUEUED", "ACTIVE", "COMPLETED"]
        call_count = [0]

        def side_effect(op, amscrot_job):
            s = MagicMock()
            s.state = states[min(call_count[0], len(states) - 1)]
            s.exit_code = None
            s.message = None
            call_count[0] += 1
            return s

        mock_facility._call_api.side_effect = side_effect
        result = job.wait(timeout=5, poll_interval=0)
        assert result is job
        assert call_count[0] == 3

    def test_wait_raises_timeout_error(self):
        job, mock_facility, mock_status = _make_job()
        mock_status.state = "QUEUED"  # never terminal
        with pytest.raises(TimeoutError, match="did not complete"):
            job.wait(timeout=0, poll_interval=0)


class TestJobCancel:
    def test_cancel_calls_service_client_destroy(self):
        job, mock_facility, _ = _make_job()
        job.cancel()
        mock_facility._call_api.assert_called_once()

    def test_cancel_returns_true(self):
        job, mock_facility, _ = _make_job()
        mock_facility._call_api.return_value = None
        result = job.cancel()
        assert result is True

    def test_repr(self):
        job, mock_facility, mock_status = _make_job(job_id="job-repr")
        mock_status.state = "QUEUED"
        job.refresh()
        assert "job-repr" in repr(job)
        assert "QUEUED" in repr(job)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_models.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'Resource' from 'amscrot.facility.models'`

- [ ] **Step 3: Create `amscrot/facility/models.py`**

```python
"""Resource and Job wrappers for the high-level facility convenience API."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amscrot.facility.client import FacilityClient
    from amscrot.facility.filesystem import FilesystemClient

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELED"})


class Resource:
    """A compute, storage, or network resource at an IRI facility.

    Provides direct job submission and resource-scoped filesystem access::

        polaris = facility.resource("Polaris")
        job = polaris.submit(executable="/bin/echo", nodes=1, queue="debug")

        task = polaris.fs.ls("/home/user")
        task.wait()
    """

    def __init__(self, data: dict, facility_client: "FacilityClient") -> None:
        self._data = data
        self._facility = facility_client
        self._fs: "FilesystemClient | None" = None

    # ── Metadata ───────────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._data.get("id", "")

    @property
    def name(self) -> str:
        return self._data.get("name", "")

    @property
    def resource_type(self) -> str:
        return self._data.get("resource_type", "")

    @property
    def status(self) -> str:
        cs = self._data.get("current_status", "unknown")
        if cs is None:
            return "unknown"
        return cs.value if hasattr(cs, "value") else str(cs)

    # ── Filesystem ─────────────────────────────────────────────────────────

    @property
    def fs(self) -> "FilesystemClient":
        """Filesystem client scoped to this resource."""
        if self._fs is None:
            from amscrot.facility.filesystem import FilesystemClient
            self._fs = FilesystemClient(
                resource_id=self.id,
                iri_filesystem=self._facility._service_client.filesystem,
                call_api=self._facility._call_api,
            )
        return self._fs

    # ── Compute ────────────────────────────────────────────────────────────

    def submit(
        self,
        executable: str = "",
        arguments: list[str] | None = None,
        directory: str | None = None,
        name: str | None = None,
        queue: str | None = None,
        account: str | None = None,
        duration: int | None = None,
        nodes: int | None = None,
        environment: dict[str, str] | None = None,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
        pre_launch: str | None = None,
        post_launch: str | None = None,
        launcher: str | None = None,
        **custom_attributes: str,
    ) -> "Job":
        """Submit a job to this resource.

        IRI-standard parameters map directly to JobSpec fields. Any additional
        keyword arguments become scheduler-specific ``custom_attributes``
        (e.g., ALCF's ``filesystems="home"``).
        """
        return self._facility._submit_job(
            resource_id=self.id,
            executable=executable,
            arguments=arguments,
            directory=directory,
            name=name,
            queue=queue,
            account=account,
            duration=duration,
            nodes=nodes,
            environment=environment,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            pre_launch=pre_launch,
            post_launch=post_launch,
            launcher=launcher,
            custom_attributes=custom_attributes or None,
        )

    def __repr__(self) -> str:
        return f"Resource(name={self.name!r}, type={self.resource_type!r}, status={self.status!r})"


class Job:
    """A submitted job on an IRI facility resource.

    Self-aware — retains a reference to its facility and can refresh
    its own status, wait for completion, or cancel itself::

        job = polaris.submit(executable="/bin/echo", ...)
        job.wait(timeout=120)
        print(job.state, job.exit_code)
    """

    def __init__(
        self,
        amscrot_job: Any,
        resource_id: str,
        facility_client: "FacilityClient",
    ) -> None:
        self._job = amscrot_job
        self._resource_id = resource_id
        self._facility = facility_client
        self._last_status: Any = None

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._job.id

    @property
    def state(self) -> str:
        """Last known state (cached from most recent refresh)."""
        if self._last_status is not None:
            return self._last_status.state
        s = self._job.status
        return s.value if hasattr(s, "value") else str(s)

    @property
    def status(self) -> str:
        """Live state — calls the API to refresh."""
        return self.refresh()

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def exit_code(self) -> int | None:
        return self._last_status.exit_code if self._last_status else None

    @property
    def message(self) -> str | None:
        return self._last_status.message if self._last_status else None

    # ── Actions ────────────────────────────────────────────────────────────

    def refresh(self) -> str:
        """Poll the IRI API for current job status. Returns state string."""
        self._last_status = self._facility._call_api(
            self._facility._service_client.status, self._job
        )
        return self.state

    def wait(self, timeout: int = 300, poll_interval: int = 5) -> "Job":
        """Block until the job reaches a terminal state.

        Raises:
            TimeoutError: If the job doesn't finish within ``timeout`` seconds.
        """
        start = time.time()
        while True:
            self.refresh()
            if self.is_terminal:
                return self
            if time.time() - start >= timeout:
                raise TimeoutError(
                    f"Job {self.id!r} did not complete within {timeout}s "
                    f"(last state: {self.state!r})"
                )
            time.sleep(poll_interval)

    def cancel(self) -> bool:
        """Cancel this job."""
        self._facility._call_api(
            self._facility._service_client.destroy, self._job
        )
        return True

    def __repr__(self) -> str:
        return f"Job(id={self.id!r}, state={self.state!r})"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_models.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add amscrot/facility/models.py tests/facility/test_models.py
git commit -m "feat(facility): add Resource and Job convenience wrappers"
```

---

## Task 4: FacilityClient

**Files:**
- Create: `amscrot/facility/client.py`
- Create: `tests/facility/test_facility_client.py`

**Context:** `FacilityClient` is the main object. It creates an `IriServiceClient` internally via `ServiceClient.create()`, creates an implicit `Session`, caches discovery results, and provides `_call_api()` with token-refresh retry. `_submit_job()` builds `JobSpec` + `AmscrotJob`, calls `plan()` then `create()` on the service client, and returns a `Job` wrapper.

- [ ] **Step 1: Write failing tests**

Create `tests/facility/test_facility_client.py`:

```python
"""Unit tests for amscrot.facility.client.FacilityClient."""
import pytest
from unittest.mock import MagicMock, patch, call
from amscrot.facility.client import FacilityClient
from amscrot.facility.models import Resource, Job


ENDPOINT = "https://iri-dev.ppg.es.net"
TOKEN = "test-token-abc"


def _make_facility(endpoint=ENDPOINT, token=TOKEN, mock_sc=None, mock_session=None):
    """Build FacilityClient with mocked IriServiceClient and Session."""
    if mock_sc is None:
        mock_sc = MagicMock()
        mock_sc.name = "test-facility"

    with patch("amscrot.facility.client.ServiceClient") as MockSC, \
         patch("amscrot.facility.client.Session") as MockSession:
        MockSC.create.return_value = mock_sc
        mock_sess = mock_session or MagicMock()
        MockSession.return_value = mock_sess

        fc = FacilityClient(endpoint=endpoint, token=token)
        fc._service_client = mock_sc
        fc._session = mock_sess
    return fc, mock_sc, mock_sess


# ── Constructor ────────────────────────────────────────────────────────────

class TestFacilityClientInit:
    def test_creates_with_static_token(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            fc = FacilityClient(endpoint=ENDPOINT, token=TOKEN)
        assert fc is not None

    def test_creates_with_token_provider(self):
        provider = lambda: "dynamic-token"
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            fc = FacilityClient(endpoint=ENDPOINT, token_provider=provider)
        assert fc is not None

    def test_service_client_created_with_correct_endpoint(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            FacilityClient(endpoint=ENDPOINT, token=TOKEN)
        call_kwargs = MockSC.create.call_args[1]
        assert call_kwargs["endpoint_uri"] == ENDPOINT

    def test_session_is_created(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session") as MockSession:
            MockSC.create.return_value = MagicMock()
            mock_sess = MagicMock()
            MockSession.return_value = mock_sess
            fc = FacilityClient(endpoint=ENDPOINT, token=TOKEN)
        assert fc._session is mock_sess


# ── Resource discovery ─────────────────────────────────────────────────────

class TestFacilityClientDiscovery:
    def test_resources_wraps_compute_resources(self):
        fc, mock_sc, _ = _make_facility()
        mock_discovery = MagicMock()
        mock_discovery.compute = [
            MagicMock(data={"id": "r1", "name": "Polaris", "resource_type": "compute",
                            "current_status": "up"}),
            MagicMock(data={"id": "r2", "name": "Aurora", "resource_type": "compute",
                            "current_status": "up"}),
        ]
        mock_sc.discover.return_value = mock_discovery

        resources = fc.resources()
        assert len(resources) == 2
        assert all(isinstance(r, Resource) for r in resources)
        assert resources[0].name == "Polaris"
        assert resources[1].name == "Aurora"

    def test_resources_caches_discovery(self):
        fc, mock_sc, _ = _make_facility()
        mock_discovery = MagicMock()
        mock_discovery.compute = []
        mock_sc.discover.return_value = mock_discovery

        fc.resources()
        fc.resources()
        mock_sc.discover.assert_called_once()

    def test_resource_by_name_case_insensitive(self):
        fc, mock_sc, _ = _make_facility()
        mock_discovery = MagicMock()
        mock_discovery.compute = [
            MagicMock(data={"id": "r1", "name": "Polaris", "resource_type": "compute",
                            "current_status": "up"}),
        ]
        mock_sc.discover.return_value = mock_discovery

        r = fc.resource("polaris")
        assert r.name == "Polaris"

        r2 = fc.resource("POLARIS")
        assert r2.name == "Polaris"

    def test_resource_raises_on_no_match(self):
        fc, mock_sc, _ = _make_facility()
        mock_discovery = MagicMock()
        mock_discovery.compute = [
            MagicMock(data={"id": "r1", "name": "Polaris", "resource_type": "compute",
                            "current_status": "up"}),
        ]
        mock_sc.discover.return_value = mock_discovery

        with pytest.raises(ValueError, match="No resource found"):
            fc.resource("NonExistent")

    def test_session_property_exposes_underlying_session(self):
        fc, _, mock_sess = _make_facility()
        assert fc.session is mock_sess


# ── _call_api ──────────────────────────────────────────────────────────────

class TestCallApi:
    def test_call_api_invokes_operation(self):
        fc, _, _ = _make_facility()
        mock_op = MagicMock(return_value="result")
        result = fc._call_api(mock_op, "arg1", key="val")
        mock_op.assert_called_once_with("arg1", key="val")
        assert result == "result"

    def test_call_api_reraises_non_auth_errors(self):
        fc, _, _ = _make_facility()
        mock_op = MagicMock(side_effect=RuntimeError("network error"))
        with pytest.raises(RuntimeError, match="network error"):
            fc._call_api(mock_op)

    def test_call_api_retries_on_401_with_token_provider(self):
        new_token = "refreshed-token"
        provider_calls = [0]

        def provider():
            provider_calls[0] += 1
            return new_token

        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            mock_sc = MagicMock()
            MockSC.create.return_value = mock_sc
            fc = FacilityClient(endpoint=ENDPOINT, token_provider=provider)
            fc._service_client = mock_sc
            fc._session = MagicMock()

        call_count = [0]

        def flaky_op():
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("401 Unauthorized")
            return "success"

        with patch("amscrot.facility.client.ServiceClient") as MockSC2:
            MockSC2.create.return_value = MagicMock()
            result = fc._call_api(flaky_op)

        assert result == "success"
        assert call_count[0] == 2
        assert provider_calls[0] == 1

    def test_call_api_does_not_retry_without_token_provider(self):
        fc, _, _ = _make_facility(token=TOKEN)  # static token, no provider

        def failing_op():
            raise Exception("401 Unauthorized")

        with pytest.raises(Exception, match="401"):
            fc._call_api(failing_op)


# ── _submit_job ────────────────────────────────────────────────────────────

class TestSubmitJob:
    def test_submit_job_returns_job_wrapper(self):
        fc, mock_sc, mock_sess = _make_facility()
        mock_sc.plan.return_value = {"status": "PLANNED", "warnings": []}
        mock_amscrot_job = MagicMock()
        mock_amscrot_job.id = "job-123"
        mock_amscrot_job.status = MagicMock(value="PENDING")

        with patch("amscrot.facility.client.AmscrotJob", return_value=mock_amscrot_job):
            job = fc._submit_job(
                resource_id="res-123",
                executable="/bin/echo",
                nodes=1,
                queue="debug",
                account="datascience",
                duration=300,
            )

        assert isinstance(job, Job)
        assert job.id == "job-123"

    def test_submit_job_calls_plan_then_create(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.plan.return_value = {"status": "PLANNED", "warnings": []}

        mock_amscrot_job = MagicMock()
        mock_amscrot_job.id = "job-456"
        mock_amscrot_job.status = MagicMock(value="PENDING")

        with patch("amscrot.facility.client.AmscrotJob", return_value=mock_amscrot_job):
            fc._submit_job(resource_id="res-123", executable="/bin/echo")

        mock_sc.plan.assert_called_once()
        mock_sc.create.assert_called_once()

    def test_submit_job_builds_resources_from_nodes(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.plan.return_value = {"status": "PLANNED", "warnings": []}
        captured_spec = {}

        def capture_plan(job, skip_checks=False):
            captured_spec["resources"] = job.job_spec.resources
            return {"status": "PLANNED", "warnings": []}

        mock_sc.plan.side_effect = capture_plan
        mock_amscrot_job = MagicMock()
        mock_amscrot_job.id = "j1"
        mock_amscrot_job.status = MagicMock(value="PENDING")

        with patch("amscrot.facility.client.AmscrotJob", return_value=mock_amscrot_job), \
             patch("amscrot.facility.client.JobSpec") as MockSpec:
            fc._submit_job(resource_id="res-123", executable="/bin/echo", nodes=4)
            call_kwargs = MockSpec.call_args[1]
            assert call_kwargs["resources"]["node_count"] == 4

    def test_submit_job_auto_generates_name_when_not_provided(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.plan.return_value = {"status": "PLANNED", "warnings": []}
        mock_amscrot_job = MagicMock()
        mock_amscrot_job.id = "j1"
        mock_amscrot_job.status = MagicMock(value="PENDING")

        with patch("amscrot.facility.client.AmscrotJob") as MockAmscrotJob:
            MockAmscrotJob.return_value = mock_amscrot_job
            fc._submit_job(resource_id="res-123", executable="/bin/echo")
            call_kwargs = MockAmscrotJob.call_args[1]
            assert call_kwargs["name"].startswith("job-")

    def test_submit_job_uses_provided_name(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.plan.return_value = {"status": "PLANNED", "warnings": []}
        mock_amscrot_job = MagicMock()
        mock_amscrot_job.id = "j1"
        mock_amscrot_job.status = MagicMock(value="PENDING")

        with patch("amscrot.facility.client.AmscrotJob") as MockAmscrotJob:
            MockAmscrotJob.return_value = mock_amscrot_job
            fc._submit_job(resource_id="res-123", executable="/bin/echo",
                           name="my-job")
            call_kwargs = MockAmscrotJob.call_args[1]
            assert call_kwargs["name"] == "my-job"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_facility_client.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'FacilityClient' from 'amscrot.facility.client'`

- [ ] **Step 3: Create `amscrot/facility/client.py`**

```python
"""High-level FacilityClient — wraps IriServiceClient + implicit Session."""
from __future__ import annotations

import time
from typing import Callable, Any

from amscrot.serviceclient import ServiceClient
from amscrot.client.models import Session
from amscrot.client.job import (
    Job as AmscrotJob,
    JobSpec,
    JobType,
    JobServiceType,
)
from amscrot.util import utils


class FacilityClient:
    """Pythonic interface to an IRI-compliant facility.

    Wraps AmSCROT's IriServiceClient and Session behind a minimal API::

        facility = client.facility("https://iri-dev.ppg.es.net", token="...")
        job = facility.resource("GPU Cluster").submit(
            executable="/bin/echo", nodes=1, queue="debug", account="myproj"
        )
        job.wait()

    Power users can access the underlying session::

        session = facility.session
        session.plan(verbose=True)
        session.destroy()

    Args:
        endpoint: Facility API base URL.
        token: Static bearer token (mutually exclusive with token_provider).
        token_provider: Callable returning current token (supports refresh).
        name: Optional display name for logging.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        token_provider: Callable[[], str] | None = None,
        name: str | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._name = name or self._endpoint
        self._logger = utils.get_logger()

        # Normalize to a callable that always returns the current token
        if token_provider is not None:
            self._token_provider: Callable[[], str] | None = token_provider
        elif token is not None:
            self._token_provider = lambda: token  # type: ignore[return-value]
        else:
            self._token_provider = None

        # Build internal IriServiceClient
        self._service_client = self._build_service_client()

        # Implicit session — hidden for simple use, exposed via .session
        self._session = Session(name=f"facility-{self._name}")
        self._session.add_service_client(self._service_client)

        # Cached discovery result
        self._discovery: Any = None

    # ── Public API ─────────────────────────────────────────────────────────

    def resources(self) -> list:
        """Return all available resources at this facility."""
        from amscrot.facility.models import Resource
        discovery = self._get_discovery()
        return [
            Resource(data=item.data, facility_client=self)
            for item in discovery.compute
        ]

    def resource(self, name: str):
        """Get a resource by name (case-insensitive).

        Raises:
            ValueError: If no resource with that name is found.
        """
        name_lower = name.lower()
        for r in self.resources():
            if r.name.lower() == name_lower:
                return r
        raise ValueError(
            f"No resource found with name {name!r} at {self._endpoint}. "
            f"Available: {[r.name for r in self.resources()]}"
        )

    @property
    def session(self) -> Session:
        """Access the underlying Session for advanced orchestration."""
        return self._session

    # ── Internal API (used by Resource and Job) ───────────────────────────

    def _call_api(self, operation: Callable, *args, **kwargs) -> Any:
        """Invoke an API operation with automatic token-refresh retry on 401/403."""
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            if self._is_auth_error(exc) and self._token_provider is not None:
                self._logger.warning(
                    f"[{self._name}] Auth error detected, refreshing token and retrying."
                )
                self._service_client = self._build_service_client()
                return operation(*args, **kwargs)
            raise

    def _submit_job(
        self,
        resource_id: str,
        executable: str = "",
        arguments: list[str] | None = None,
        directory: str | None = None,
        name: str | None = None,
        queue: str | None = None,
        account: str | None = None,
        duration: int | None = None,
        nodes: int | None = None,
        environment: dict[str, str] | None = None,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
        pre_launch: str | None = None,
        post_launch: str | None = None,
        launcher: str | None = None,
        custom_attributes: dict | None = None,
    ):
        """Build JobSpec + AmscrotJob from flat kwargs and submit."""
        from amscrot.facility.models import Job

        # Build resources dict
        resources: dict = {}
        if nodes is not None:
            resources["node_count"] = nodes

        # Build attributes dict
        attributes: dict = {"resource_id": resource_id}
        if directory:
            attributes["directory"] = directory
        if duration is not None:
            attributes["duration"] = duration
        if queue:
            attributes["queue_name"] = queue
        if account:
            attributes["account"] = account
        if stdout_path:
            attributes["stdout_path"] = stdout_path
        if stderr_path:
            attributes["stderr_path"] = stderr_path
        if environment:
            attributes["environment"] = environment
        if pre_launch:
            attributes["pre_launch"] = pre_launch
        if post_launch:
            attributes["post_launch"] = post_launch
        if launcher:
            attributes["launcher"] = launcher
        if custom_attributes:
            attributes["custom_attributes"] = custom_attributes

        spec = JobSpec(
            executable=executable,
            arguments=arguments or [],
            resources=resources,
            attributes=attributes,
        )

        job_name = name or f"job-{int(time.time())}"

        amscrot_job = AmscrotJob(
            name=job_name,
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=self._service_client,
            job_spec=spec,
        )

        self._session.add_job(amscrot_job)
        self._call_api(self._service_client.plan, amscrot_job)
        self._call_api(self._service_client.create, amscrot_job)

        return Job(
            amscrot_job=amscrot_job,
            resource_id=resource_id,
            facility_client=self,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _build_service_client(self) -> Any:
        """Create (or recreate) the IriServiceClient with the current token."""
        token = self._token_provider() if self._token_provider else ""
        return ServiceClient.create(
            type="amsc-iri",
            name=self._name,
            endpoint_uri=self._endpoint,
            credential={"api_key": token, "api_endpoint": self._endpoint},
        )

    def _get_discovery(self) -> Any:
        """Return cached discovery result, fetching on first call."""
        if self._discovery is None:
            self._discovery = self._call_api(self._service_client.discover)
        return self._discovery

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "401" in msg or "403" in msg or "unauthorized" in msg

    def __repr__(self) -> str:
        return f"FacilityClient(endpoint={self._endpoint!r}, name={self._name!r})"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_facility_client.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add amscrot/facility/client.py tests/facility/test_facility_client.py
git commit -m "feat(facility): add FacilityClient with discovery, submit, and token refresh"
```

---

## Task 5: Public exports and Client.facility()

**Files:**
- Modify: `amscrot/facility/__init__.py`
- Modify: `amscrot/client/client.py` (add one method)
- Create: `tests/facility/test_client_facility_method.py`

- [ ] **Step 1: Write failing tests**

Create `tests/facility/test_client_facility_method.py`:

```python
"""Unit tests for Client.facility() method."""
import pytest
from unittest.mock import MagicMock, patch
from amscrot.client import Client
from amscrot.facility.client import FacilityClient

ENDPOINT = "https://iri-dev.ppg.es.net"
TOKEN = "test-token"


class TestClientFacilityMethod:
    def test_facility_returns_facility_client(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            result = client.facility(ENDPOINT, token=TOKEN)
        assert isinstance(result, FacilityClient)

    def test_facility_passes_endpoint(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token=TOKEN)
        assert fc._endpoint == ENDPOINT

    def test_facility_passes_static_token(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token=TOKEN)
        assert fc._token_provider() == TOKEN

    def test_facility_passes_token_provider(self):
        provider = lambda: "dynamic-token"
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token_provider=provider)
        assert fc._token_provider is provider

    def test_facility_passes_name(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token=TOKEN, name="ESnet East")
        assert fc._name == "ESnet East"

    def test_facility_each_call_returns_new_instance(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc1 = client.facility(ENDPOINT, token=TOKEN)
            fc2 = client.facility(ENDPOINT, token=TOKEN)
        assert fc1 is not fc2


class TestFacilityPublicExports:
    def test_facility_client_importable_from_package(self):
        from amscrot.facility import FacilityClient
        assert FacilityClient is not None

    def test_resource_importable_from_package(self):
        from amscrot.facility import Resource
        assert Resource is not None

    def test_job_importable_from_package(self):
        from amscrot.facility import Job
        assert Job is not None

    def test_task_importable_from_package(self):
        from amscrot.facility import Task
        assert Task is not None

    def test_filesystem_client_importable_from_package(self):
        from amscrot.facility import FilesystemClient
        assert FilesystemClient is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_client_facility_method.py -v 2>&1 | head -20
```

Expected: `AttributeError: 'Client' object has no attribute 'facility'`

- [ ] **Step 3: Update `amscrot/facility/__init__.py`**

Replace the stub with full exports:

```python
"""High-level facility convenience API for AmSCROT.

Provides a Pythonic, minimal-boilerplate interface for IRI job submission::

    from amscrot.client import Client

    client = Client()
    facility = client.facility("https://api.alcf.anl.gov", token="...")
    job = facility.resource("Polaris").submit(
        executable="/bin/echo",
        nodes=1,
        queue="debug",
        account="datascience",
        duration=300,
    )
    job.wait()
"""

from amscrot.facility.client import FacilityClient
from amscrot.facility.models import Resource, Job
from amscrot.facility.filesystem import FilesystemClient
from amscrot.facility.task import Task

__all__ = [
    "FacilityClient",
    "Resource",
    "Job",
    "FilesystemClient",
    "Task",
]
```

- [ ] **Step 4: Add `facility()` method to `amscrot/client/client.py`**

Open `amscrot/client/client.py`. At the top of the file, after the existing imports, add:

```python
from amscrot.facility.client import FacilityClient
```

Then add this method to the `Client` class (after the last existing method):

```python
def facility(
    self,
    endpoint: str,
    *,
    token: Optional[str] = None,
    token_provider=None,
    name: Optional[str] = None,
) -> "FacilityClient":
    """Connect to an IRI-compliant facility.

    Args:
        endpoint: Facility API base URL (e.g., "https://iri-dev.ppg.es.net").
        token: Static bearer token (mutually exclusive with token_provider).
        token_provider: Callable returning the current token (supports refresh).
        name: Optional display name for logging.

    Returns:
        FacilityClient providing resource discovery and job submission.

    Example::

        facility = client.facility("https://api.alcf.anl.gov", token="my-key")
        job = facility.resource("Polaris").submit(
            executable="/bin/echo", nodes=1, queue="debug", account="proj"
        )
        job.wait()
    """
    return FacilityClient(
        endpoint=endpoint,
        token=token,
        token_provider=token_provider,
        name=name,
    )
```

- [ ] **Step 5: Run all facility tests**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Confirm existing tests still pass**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/ -v --ignore=tests/test_iri_integration.py
```

Expected: All non-integration tests PASS. No regressions.

- [ ] **Step 7: Commit**

```bash
git add amscrot/facility/__init__.py amscrot/client/client.py tests/facility/test_client_facility_method.py
git commit -m "feat(facility): wire facility() into Client and export public API"
```

---

## Task 6: End-to-end smoke test

**Files:**
- Create: `tests/facility/test_smoke.py`

This task writes a smoke test that exercises the full stack from `Client.facility()` down to `Job` and `FilesystemClient`, using mocks so no real network is needed.

- [ ] **Step 1: Write smoke test**

Create `tests/facility/test_smoke.py`:

```python
"""End-to-end smoke test for the facility convenience API.

Exercises the full call chain from Client.facility() through resource
discovery, job submission, wait, and filesystem operations — using mocks.
"""
import pytest
from unittest.mock import MagicMock, patch
from amscrot.client import Client
from amscrot.facility.models import Job
from amscrot.facility.task import Task

ENDPOINT = "https://iri-dev.ppg.es.net"
TOKEN = "smoke-test-token"


def _build_mock_service_client(job_state_sequence=None):
    """Build a fully mocked IriServiceClient."""
    job_states = job_state_sequence or ["QUEUED", "ACTIVE", "COMPLETED"]
    call_count = [0]

    mock_sc = MagicMock()
    mock_sc.name = "smoke-sc"

    # discover() returns compute resource
    mock_discovery = MagicMock()
    mock_discovery.compute = [
        MagicMock(data={
            "id": "res-polaris-001",
            "name": "Polaris",
            "resource_type": "compute",
            "current_status": "up",
        })
    ]
    mock_sc.discover.return_value = mock_discovery

    # plan() succeeds silently
    mock_sc.plan.return_value = {"status": "PLANNED", "warnings": []}

    # create() sets job.id
    def do_create(job, skip_checks=False):
        job.id = "job-smoke-001"

    mock_sc.create.side_effect = do_create

    # status() cycles through states
    def do_status(job):
        s = MagicMock()
        idx = min(call_count[0], len(job_states) - 1)
        s.state = job_states[idx]
        s.exit_code = 0 if job_states[idx] == "COMPLETED" else None
        s.message = None
        call_count[0] += 1
        return s

    mock_sc.status.side_effect = do_status

    # filesystem for fs operations
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [{"name": "stdout.log"}, {"name": "stderr.log"}]
    mock_fs.head.return_value = "Hello from the job!"
    mock_sc.filesystem = mock_fs

    return mock_sc


class TestFullWorkflowSmoke:
    def test_submit_wait_read_output(self):
        mock_sc = _build_mock_service_client()

        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session") as MockSession:
            MockSC.create.return_value = mock_sc
            mock_session = MagicMock()
            MockSession.return_value = mock_session

            # 1. Create client and connect to facility
            client = Client()
            facility = client.facility(ENDPOINT, token=TOKEN, name="ESnet East")

            # 2. Discover and select resource
            resources = facility.resources()
            assert len(resources) == 1
            assert resources[0].name == "Polaris"

            polaris = facility.resource("polaris")
            assert polaris.id == "res-polaris-001"

            # 3. Submit job
            job = polaris.submit(
                executable="/bin/echo",
                arguments=["Hello"],
                directory="/home/user/outputs",
                queue="debug",
                account="datascience",
                duration=300,
                nodes=1,
            )

            assert isinstance(job, Job)
            assert job.id == "job-smoke-001"

            # 4. Wait for completion (poll_interval=0 for speed in tests)
            result = job.wait(timeout=10, poll_interval=0)
            assert result is job
            assert job.state == "COMPLETED"
            assert job.exit_code == 0
            assert job.is_terminal is True

            # 5. Read output via filesystem
            task = polaris.fs.ls("/home/user/outputs")
            assert isinstance(task, Task)
            task.wait()
            listing = task.result
            assert any(f["name"] == "stdout.log" for f in listing)

            task2 = polaris.fs.head("/home/user/outputs/stdout.log", lines=10)
            task2.wait()
            assert "Hello" in task2.result

    def test_cancel_job(self):
        mock_sc = _build_mock_service_client()
        mock_sc.destroy.return_value = None

        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = mock_sc
            client = Client()
            facility = client.facility(ENDPOINT, token=TOKEN)
            polaris = facility.resource("Polaris")
            job = polaris.submit(executable="/bin/echo", nodes=1)
            result = job.cancel()

        assert result is True
        mock_sc.destroy.assert_called_once()

    def test_power_user_can_access_session(self):
        mock_sc = _build_mock_service_client()

        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session") as MockSession:
            MockSC.create.return_value = mock_sc
            mock_session = MagicMock()
            MockSession.return_value = mock_session
            client = Client()
            facility = client.facility(ENDPOINT, token=TOKEN)

        session = facility.session
        assert session is mock_session

    def test_token_refresh_on_auth_error(self):
        token_calls = [0]

        def provider():
            token_calls[0] += 1
            return f"token-{token_calls[0]}"

        mock_sc_initial = MagicMock()
        mock_sc_initial.name = "sc"
        mock_discovery = MagicMock()
        mock_discovery.compute = [
            MagicMock(data={"id": "r1", "name": "Polaris",
                            "resource_type": "compute", "current_status": "up"})
        ]
        mock_sc_initial.discover.return_value = mock_discovery

        mock_sc_refreshed = MagicMock()
        mock_sc_refreshed.name = "sc-refreshed"
        mock_sc_refreshed.discover.return_value = mock_discovery
        mock_sc_refreshed.plan.return_value = {"status": "PLANNED", "warnings": []}
        mock_sc_refreshed.create.side_effect = lambda job, **kw: setattr(job, "id", "j1")

        sc_instances = [mock_sc_initial, mock_sc_refreshed]
        sc_call_count = [0]

        def make_sc(**kwargs):
            idx = min(sc_call_count[0], len(sc_instances) - 1)
            sc_call_count[0] += 1
            return sc_instances[idx]

        # Patch discover on initial sc to raise 401 on first call
        discover_call = [0]

        def flaky_discover():
            discover_call[0] += 1
            if discover_call[0] == 1:
                raise Exception("401 Unauthorized")
            return mock_discovery

        mock_sc_initial.discover.side_effect = flaky_discover

        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.side_effect = make_sc
            client = Client()
            facility = client.facility(ENDPOINT, token_provider=provider)

            resources = facility.resources()
            assert len(resources) == 1
            assert token_calls[0] >= 1  # provider was called for refresh
```

- [ ] **Step 2: Run smoke tests**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/facility/test_smoke.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Run the full test suite**

```bash
cd /Users/jchilders/anl/amsc/iri-facility-api-toolkit
python -m pytest tests/ -v --ignore=tests/test_iri_integration.py
```

Expected: All tests PASS. No regressions in existing tests.

- [ ] **Step 4: Commit**

```bash
git add tests/facility/test_smoke.py
git commit -m "test(facility): add end-to-end smoke tests for convenience API"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| New `amscrot/facility/` subpackage with 5 files | Tasks 1-5 |
| `FacilityClient(endpoint, token/token_provider)` | Task 4 |
| `Client.facility()` entry point | Task 5 |
| `Resource.submit(flat kwargs)` → `Job` | Task 3, 4 |
| `Job.wait()`, `.cancel()`, `.refresh()`, `.state`, `.status` | Task 3 |
| `FilesystemClient` resource-scoped, all ops return `Task` | Task 2 |
| `Task` async-compatible wrapper | Task 1 |
| Token refresh retry via `_call_api()` | Task 4 |
| Discovery cached after first call | Task 4 |
| `resource(name)` case-insensitive with `ValueError` on miss | Task 4 |
| `facility.session` power-user escape hatch | Task 4, 5 |
| Unit tests for all new classes | Tasks 1-5 |
| Existing tests unbroken | Task 5, step 6 |
| Public exports from `amscrot.facility` | Task 5 |
| No modification to `IriServiceClient` or other existing code | All tasks |

All requirements covered. No gaps found.
