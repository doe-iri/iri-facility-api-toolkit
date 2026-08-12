"""Unit tests for amscrot.facility.async_client, async_models, async_filesystem."""

import asyncio
import time
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

from amscrot.facility.async_client import AsyncFacilityClient
from amscrot.facility.async_models import AsyncResource, AsyncJob, TERMINAL_STATES
from amscrot.facility.async_filesystem import AsyncFilesystemClient
from amscrot.facility.task import Task

# ── Test constants ─────────────────────────────────────────────────────────

ENDPOINT = "https://iri-test.example.com"
TOKEN = "test-token"


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_facility(endpoint=ENDPOINT, token=TOKEN, mock_sc=None, mock_session=None):
    """Build AsyncFacilityClient with mocked ServiceClient and Session."""
    with patch("amscrot.facility.async_client.ServiceClient") as MockSC, \
         patch("amscrot.facility.async_client.Session") as MockSession:
        if mock_sc:
            MockSC.create.return_value = mock_sc
        else:
            MockSC.create.return_value = MagicMock()
        if mock_session:
            MockSession.return_value = mock_session
        else:
            MockSession.return_value = MagicMock()

        fc = AsyncFacilityClient(endpoint=endpoint, token=token)
    return fc, MockSC.create.return_value, MockSession.return_value


# ── AsyncFacilityClient tests ──────────────────────────────────────────────


class TestAsyncFacilityClientInit:

    def test_creates_with_static_token(self):
        fc, mock_sc, _ = _make_facility()
        assert fc.name == ENDPOINT
        assert fc.base_url == ENDPOINT
        assert fc._static_token == TOKEN

    def test_creates_with_custom_name(self):
        fc, _, _ = _make_facility()
        fc._name = "My Facility"
        assert fc.display_name == "My Facility"

    def test_properties_are_sync(self):
        fc, _, mock_sess = _make_facility()
        # These should not be coroutines
        assert not asyncio.iscoroutine(fc.name)
        assert not asyncio.iscoroutine(fc.base_url)
        assert fc.session is mock_sess


class TestAsyncFacilityClientIO:

    @pytest.mark.asyncio
    async def test_info_is_async(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_facility_info.return_value = {"name": "TestFacility"}
        result = await fc.info()
        assert result == {"name": "TestFacility"}

    @pytest.mark.asyncio
    async def test_incidents_is_async(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_incidents.return_value = [{"id": "inc-1"}]
        result = await fc.incidents()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_incidents_returns_empty_on_none(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_incidents.return_value = None
        result = await fc.incidents()
        assert result == []

    @pytest.mark.asyncio
    async def test_incident_is_async(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_incident.return_value = {"id": "inc-1"}
        result = await fc.incident("inc-1")
        assert result["id"] == "inc-1"

    @pytest.mark.asyncio
    async def test_events_is_async(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_events.return_value = [{"id": "evt-1"}]
        result = await fc.events("inc-1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_resources_returns_async_resources(self):
        fc, mock_sc, mock_sess = _make_facility()
        mock_disc = MagicMock()
        mock_item = MagicMock()
        mock_item.type = "compute"
        mock_item.data = {"id": "r1", "name": "GPU", "resource_type": "compute"}
        mock_disc.all = [mock_item]
        mock_sess.metadata.return_value = mock_disc

        resources = await fc.resources()
        assert len(resources) == 1
        assert isinstance(resources[0], AsyncResource)
        assert resources[0].name == "GPU"

    @pytest.mark.asyncio
    async def test_resource_by_name(self):
        fc, mock_sc, mock_sess = _make_facility()
        mock_disc = MagicMock()
        mock_item = MagicMock()
        mock_item.type = "compute"
        mock_item.data = {"id": "r1", "name": "Polaris", "resource_type": "compute"}
        mock_disc.all = [mock_item]
        mock_sess.metadata.return_value = mock_disc

        resource = await fc.resource("polaris")
        assert resource.name == "Polaris"

    @pytest.mark.asyncio
    async def test_resource_raises_on_no_match(self):
        fc, mock_sc, mock_sess = _make_facility()
        mock_disc = MagicMock()
        mock_disc.all = []
        mock_sess.metadata.return_value = mock_disc

        with pytest.raises(ValueError, match="No resource found"):
            await fc.resource("nonexistent")

    @pytest.mark.asyncio
    async def test_resource_by_id_returns_async_resource(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_resource_by_id.return_value = {"id": "r-uuid", "name": "TestRes"}
        result = await fc.resource_by_id("r-uuid")
        assert isinstance(result, AsyncResource)
        assert result.id == "r-uuid"

    @pytest.mark.asyncio
    async def test_resource_by_id_returns_none(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_resource_by_id.return_value = None
        result = await fc.resource_by_id("missing")
        assert result is None


class TestAsyncCallApiRetry:

    @pytest.mark.asyncio
    async def test_retries_on_401(self):
        fc, mock_sc, _ = _make_facility(token=TOKEN)
        fc._token_provider = lambda: "new-token"

        call_count = 0

        def flaky_op():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("401 Unauthorized")
            return "success"

        with patch.object(fc, "_build_service_client", return_value=mock_sc):
            result = await fc._async_call_api(flaky_op)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_no_retry_without_token_provider(self):
        fc, mock_sc, _ = _make_facility(token=TOKEN)
        fc._token_provider = None

        def failing_op():
            raise Exception("401 Unauthorized")

        with pytest.raises(Exception, match="401"):
            await fc._async_call_api(failing_op)


# ── AsyncResource tests ───────────────────────────────────────────────────


class TestAsyncResource:

    def _make_resource(self):
        fc, mock_sc, _ = _make_facility()
        data = {
            "id": "res-1",
            "name": "TestResource",
            "resource_type": "compute",
            "description": "A test resource",
            "current_status": "up",
        }
        return AsyncResource(data=data, facility_client=fc), fc

    def test_properties_are_sync(self):
        r, _ = self._make_resource()
        assert r.id == "res-1"
        assert r.name == "TestResource"
        assert r.resource_type == "compute"
        assert r.description == "A test resource"
        assert r.status == "up"
        assert not asyncio.iscoroutine(r.id)

    def test_job_returns_async_job_sync(self):
        r, _ = self._make_resource()
        j = r.job("job-123")
        assert isinstance(j, AsyncJob)
        assert j.id == "job-123"

    def test_fs_returns_async_filesystem_client(self):
        r, fc = self._make_resource()
        fc._service_client.filesystem = MagicMock()
        fs = r.fs
        assert isinstance(fs, AsyncFilesystemClient)

    @pytest.mark.asyncio
    async def test_jobs_is_async(self):
        r, fc = self._make_resource()
        fc._service_client.get_jobs.return_value = [
            {"id": "j1", "name": "job1", "status": "RUNNING"}
        ]
        jobs = await r.jobs()
        assert len(jobs) == 1
        assert isinstance(jobs[0], AsyncJob)

    @pytest.mark.asyncio
    async def test_submit_is_async(self):
        r, fc = self._make_resource()
        with patch.object(fc, "_async_submit_job", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = AsyncJob(
                amscrot_job=SimpleNamespace(id="j1", status=SimpleNamespace(value="INIT")),
                resource_id="res-1",
                facility_client=fc,
            )
            job = await r.submit(executable="/bin/echo", nodes=1)
        assert isinstance(job, AsyncJob)
        mock_submit.assert_called_once()


# ── AsyncJob tests ─────────────────────────────────────────────────────────


class TestAsyncJob:

    def _make_job(self, state="RUNNING"):
        fc, mock_sc, _ = _make_facility()
        handle = SimpleNamespace(
            id="job-42",
            resource_id="res-1",
            name="test-job",
            status=SimpleNamespace(value=state),
        )
        return AsyncJob(amscrot_job=handle, resource_id="res-1", facility_client=fc), fc

    def test_properties_are_sync(self):
        j, _ = self._make_job()
        assert j.id == "job-42"
        assert j.state == "RUNNING"
        assert j.is_terminal is False
        assert j.exit_code is None
        assert j.message is None

    def test_is_terminal_for_completed(self):
        j, _ = self._make_job(state="COMPLETED")
        assert j.is_terminal is True

    @pytest.mark.asyncio
    async def test_refresh_is_async(self):
        j, fc = self._make_job()
        mock_status = MagicMock()
        mock_status.state = "COMPLETED"
        mock_status.exit_code = 0
        mock_status.message = "done"
        fc._service_client.status.return_value = mock_status

        state = await j.refresh()
        assert state == "COMPLETED"
        assert j.exit_code == 0

    @pytest.mark.asyncio
    async def test_wait_resolves_on_terminal(self):
        j, fc = self._make_job()
        mock_status = MagicMock()
        mock_status.state = "COMPLETED"
        mock_status.exit_code = 0
        mock_status.message = "done"
        fc._service_client.status.return_value = mock_status

        result = await j.wait(timeout=5, poll_interval=0.01)
        assert result is j
        assert j.state == "COMPLETED"

    @pytest.mark.asyncio
    async def test_wait_timeout_raises(self):
        j, fc = self._make_job()
        mock_status = MagicMock()
        mock_status.state = "RUNNING"
        fc._service_client.status.return_value = mock_status

        with pytest.raises(TimeoutError, match="did not complete"):
            await j.wait(timeout=0.05, poll_interval=0.01)

    @pytest.mark.asyncio
    async def test_cancel_is_async(self):
        j, fc = self._make_job()
        fc._service_client.destroy.return_value = None
        result = await j.cancel()
        assert result is True

    def test_repr(self):
        j, _ = self._make_job()
        assert "AsyncJob" in repr(j)
        assert "job-42" in repr(j)


# ── AsyncFilesystemClient tests ───────────────────────────────────────────


class TestAsyncFilesystemClient:

    def _make_fs(self):
        mock_iri_fs = MagicMock()

        async def fake_call_api(operation, *args, **kwargs):
            return operation(*args, **kwargs)

        fs = AsyncFilesystemClient(
            resource_id="res-1",
            iri_filesystem=mock_iri_fs,
            call_api=fake_call_api,
        )
        return fs, mock_iri_fs

    @pytest.mark.asyncio
    async def test_ls_is_async(self):
        fs, mock_iri = self._make_fs()
        mock_iri.ls.return_value = ["/home/user/file.txt"]
        task = await fs.ls("/home/user")
        assert isinstance(task, Task)
        assert task.state == "completed"
        mock_iri.ls.assert_called_once_with("res-1", "/home/user", recursive=False)

    @pytest.mark.asyncio
    async def test_stat_is_async(self):
        fs, mock_iri = self._make_fs()
        mock_iri.stat.return_value = {"size": 1024}
        task = await fs.stat("/home/user/file.txt")
        assert task.result == {"size": 1024}

    @pytest.mark.asyncio
    async def test_mkdir_is_async(self):
        fs, mock_iri = self._make_fs()
        mock_iri.mkdir.return_value = {"status": "ok"}
        task = await fs.mkdir("/home/user/newdir")
        assert task.state == "completed"

    @pytest.mark.asyncio
    async def test_rm_is_async(self):
        fs, mock_iri = self._make_fs()
        mock_iri.rm.return_value = {"status": "ok"}
        task = await fs.rm("/home/user/file.txt")
        assert task.state == "completed"

    @pytest.mark.asyncio
    async def test_error_wraps_as_failed_task(self):
        fs, mock_iri = self._make_fs()
        mock_iri.ls.side_effect = RuntimeError("boom")
        task = await fs.ls("/fail")
        assert task.state == "failed"
        with pytest.raises(RuntimeError, match="boom"):
            _ = task.result

    @pytest.mark.asyncio
    async def test_upload_is_async(self):
        fs, mock_iri = self._make_fs()
        mock_iri.upload.return_value = {"bytes": 1024}
        task = await fs.upload("/local/file", "/remote/file")
        assert task.state == "completed"

    @pytest.mark.asyncio
    async def test_download_is_async(self):
        fs, mock_iri = self._make_fs()
        mock_iri.download.return_value = {"bytes": 2048}
        task = await fs.download("/remote/file", "/local/file")
        assert task.state == "completed"

    def test_repr(self):
        fs, _ = self._make_fs()
        assert "AsyncFilesystemClient" in repr(fs)
        assert "res-1" in repr(fs)


# ── Task async_wait / __await__ tests ──────────────────────────────────────


class TestTaskAsync:

    @pytest.mark.asyncio
    async def test_async_wait_returns_self(self):
        t = Task(result="data")
        result = await t.async_wait()
        assert result is t

    @pytest.mark.asyncio
    async def test_await_task(self):
        t = Task(result="data")
        result = await t
        assert result is t
        assert result.result == "data"

    @pytest.mark.asyncio
    async def test_await_failed_task(self):
        t = Task(error=ValueError("oops"))
        result = await t
        assert result.state == "failed"
        with pytest.raises(ValueError, match="oops"):
            _ = result.result
