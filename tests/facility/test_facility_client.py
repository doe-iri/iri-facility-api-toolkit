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

def _make_discovery(*items):
    """Build a mock DiscoveryResult where .all returns the given items."""
    mock_discovery = MagicMock()
    mock_discovery.all = list(items)
    return mock_discovery


def _res(resource_id, name, resource_type, status="up"):
    return MagicMock(
        type=resource_type,
        data={"id": resource_id, "name": name, "resource_type": resource_type,
              "current_status": status},
    )


class TestFacilityClientDiscovery:
    def test_resources_wraps_compute_resources(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.discover.return_value = _make_discovery(
            _res("r1", "Polaris", "compute"),
            _res("r2", "Aurora", "compute"),
        )

        resources = fc.resources()
        assert len(resources) == 2
        assert all(isinstance(r, Resource) for r in resources)
        assert resources[0].name == "Polaris"
        assert resources[1].name == "Aurora"

    def test_resources_includes_storage_and_network(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.discover.return_value = _make_discovery(
            _res("r1", "Polaris", "compute"),
            _res("r2", "Home", "storage"),
            _res("r3", "ESnet", "network"),
            _res("r4", "proj-alloc", "allocation"),  # should be excluded
        )

        resources = fc.resources()
        names = [r.name for r in resources]
        assert "Polaris" in names
        assert "Home" in names
        assert "ESnet" in names
        assert "proj-alloc" not in names

    def test_resources_caches_discovery(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.discover.return_value = _make_discovery()

        fc.resources()
        fc.resources()
        mock_sc.discover.assert_called_once()

    def test_resource_by_name_case_insensitive(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.discover.return_value = _make_discovery(
            _res("r1", "Polaris", "compute"),
        )

        r = fc.resource("polaris")
        assert r.name == "Polaris"

        r2 = fc.resource("POLARIS")
        assert r2.name == "Polaris"

    def test_resource_raises_on_no_match(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.discover.return_value = _make_discovery(
            _res("r1", "Polaris", "compute"),
        )

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

    def test_call_api_retry_uses_refreshed_service_client(self):
        """After a 401, retry must use the new service client's method, not the old one."""
        provider_token = ["token-v1"]

        def provider():
            provider_token[0] = "token-v2"
            return provider_token[0]

        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            old_sc = MagicMock()
            new_sc = MagicMock()
            MockSC.create.side_effect = [old_sc, new_sc]
            fc = FacilityClient(endpoint=ENDPOINT, token_provider=provider)
            fc._session = MagicMock()

        # Simulate: old_sc.discover raises 401; new_sc.discover succeeds
        old_sc.discover.side_effect = Exception("401 Unauthorized")
        new_sc.discover.return_value = MagicMock(compute=[])

        with patch("amscrot.facility.client.ServiceClient") as MockSC2:
            MockSC2.create.return_value = new_sc
            result = fc._call_api(old_sc.discover)

        # The retry must have used new_sc.discover, not old_sc.discover
        new_sc.discover.assert_called_once()
        assert result.compute == []


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


# ── Incidents & Events ─────────────────────────────────────────────────────

class TestIncidentsAndEvents:
    def test_incidents_makes_live_api_call(self):
        fc, mock_sc, _ = _make_facility()
        mock_incidents = [MagicMock(id="inc-001"), MagicMock(id="inc-002")]
        mock_sc.get_incidents.return_value = mock_incidents

        result = fc.incidents()
        mock_sc.get_incidents.assert_called_once()
        assert result is mock_incidents

    def test_incidents_empty_when_none_returned(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_incidents.return_value = []

        assert fc.incidents() == []

    def test_incidents_does_not_cache(self):
        """incidents() is a live call — calling it twice hits the API twice."""
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_incidents.return_value = []

        fc.incidents()
        fc.incidents()
        assert mock_sc.get_incidents.call_count == 2

    def test_incident_passes_through_native_object(self):
        fc, mock_sc, _ = _make_facility()
        mock_inc = MagicMock(id="inc-001", status="active")
        mock_sc.get_incident.return_value = mock_inc

        result = fc.incident("inc-001")
        mock_sc.get_incident.assert_called_once_with("inc-001")
        assert result is mock_inc

    def test_incident_returns_none_when_not_found(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_incident.return_value = None

        assert fc.incident("inc-missing") is None

    def test_events_calls_service_client_get_events(self):
        fc, mock_sc, _ = _make_facility()
        mock_events = [MagicMock(id="evt-001"), MagicMock(id="evt-002")]
        mock_sc.get_events.return_value = mock_events

        result = fc.events("inc-001")
        mock_sc.get_events.assert_called_once_with("inc-001")
        assert result is mock_events

    def test_events_returns_empty_list_when_none(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_events.return_value = []

        assert fc.events("inc-001") == []


# ── Properties ─────────────────────────────────────────────────────────────

class TestFacilityClientProperties:
    def test_name_defaults_to_endpoint(self):
        fc, _, _ = _make_facility(endpoint=ENDPOINT)
        assert fc.name == ENDPOINT

    def test_name_returns_custom_name(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            fc = FacilityClient(endpoint=ENDPOINT, token=TOKEN, name="my-facility")
        assert fc.name == "my-facility"

    def test_display_name_equals_name(self):
        fc, _, _ = _make_facility()
        assert fc.display_name == fc.name

    def test_base_url_returns_endpoint(self):
        fc, _, _ = _make_facility(endpoint=ENDPOINT)
        assert fc.base_url == ENDPOINT


# ── info() ─────────────────────────────────────────────────────────────────

class TestFacilityClientInfo:
    def test_info_makes_live_api_call(self):
        fc, mock_sc, _ = _make_facility()
        mock_info = MagicMock()
        mock_sc.get_facility_info.return_value = mock_info

        result = fc.info()
        mock_sc.get_facility_info.assert_called_once()
        assert result is mock_info

    def test_info_does_not_cache(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_facility_info.return_value = MagicMock()

        fc.info()
        fc.info()
        assert mock_sc.get_facility_info.call_count == 2


# ── resource_by_id() ───────────────────────────────────────────────────────

class TestResourceById:
    def test_resource_by_id_makes_live_api_call(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_resource_by_id.return_value = {
            "id": "res-001", "name": "Polaris",
            "resource_type": "compute", "current_status": "up",
        }

        r = fc.resource_by_id("res-001")
        mock_sc.get_resource_by_id.assert_called_once_with("res-001")
        assert isinstance(r, Resource)
        assert r.id == "res-001"

    def test_resource_by_id_returns_none_when_not_found(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_resource_by_id.return_value = None

        result = fc.resource_by_id("nonexistent")
        assert result is None

    def test_resource_by_id_does_not_use_discovery_cache(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_resource_by_id.return_value = {
            "id": "res-001", "name": "Polaris",
            "resource_type": "compute", "current_status": "up",
        }

        fc.resource_by_id("res-001")
        fc.resource_by_id("res-001")
        assert mock_sc.get_resource_by_id.call_count == 2


# ── _get_jobs() ────────────────────────────────────────────────────────────

class TestGetJobs:
    def test_get_jobs_returns_job_wrappers(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_jobs.return_value = [
            {"id": "job-001", "name": "job-a", "status": "RUNNING"},
        ]

        jobs = fc._get_jobs("res-001")
        mock_sc.get_jobs.assert_called_once_with("res-001", historical=False)
        assert len(jobs) == 1
        assert isinstance(jobs[0], Job)
        assert jobs[0].id == "job-001"

    def test_get_jobs_returns_empty_list_when_none(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_jobs.return_value = []

        assert fc._get_jobs("res-001") == []

    def test_get_jobs_forwards_historical(self):
        fc, mock_sc, _ = _make_facility()
        mock_sc.get_jobs.return_value = []

        fc._get_jobs("res-001", historical=True)
        mock_sc.get_jobs.assert_called_once_with("res-001", historical=True)
