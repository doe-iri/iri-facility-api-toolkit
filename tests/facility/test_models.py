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
