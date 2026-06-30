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

    # discover() returns compute resource via .all (as consumed by FacilityClient.resources())
    mock_resource = MagicMock()
    mock_resource.type = "compute"
    mock_resource.data = {
        "id": "res-polaris-001",
        "name": "Polaris",
        "resource_type": "compute",
        "current_status": "up",
    }
    mock_discovery = MagicMock()
    mock_discovery.all = [mock_resource]
    mock_sc.discover.return_value = mock_discovery

    # plan() succeeds silently
    mock_sc.plan.return_value = {"status": "PLANNED", "warnings": []}

    # create() sets job.id
    def do_create(job, skip_checks=False):
        job.id = "job-smoke-001"

    mock_sc.create.side_effect = do_create

    # status() cycles through states
    def do_status(job, **kwargs):
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
        # Scenario: token_provider is given; first discover() raises 401;
        # _call_api should call provider() once, rebuild the service client,
        # and retry using the new client's discover() — which succeeds.

        token_calls = [0]

        def provider():
            token_calls[0] += 1
            return f"token-{token_calls[0]}"

        # 1. Two service-client instances: initial (raises 401) and refreshed (succeeds)
        mock_sc_initial = MagicMock()
        mock_sc_initial.name = "sc"
        mock_resource = MagicMock()
        mock_resource.type = "compute"
        mock_resource.data = {"id": "r1", "name": "Polaris",
                              "resource_type": "compute", "current_status": "up"}
        mock_discovery = MagicMock()
        mock_discovery.all = [mock_resource]

        mock_sc_refreshed = MagicMock()
        mock_sc_refreshed.name = "sc-refreshed"
        mock_sc_refreshed.discover.return_value = mock_discovery

        sc_instances = [mock_sc_initial, mock_sc_refreshed]
        sc_call_count = [0]

        def make_sc(**kwargs):
            idx = min(sc_call_count[0], len(sc_instances) - 1)
            sc_call_count[0] += 1
            return sc_instances[idx]

        # 2. First call to discover raises 401; subsequent calls succeed
        discover_call = [0]

        def flaky_discover():
            discover_call[0] += 1
            if discover_call[0] == 1:
                raise Exception("401 Unauthorized")
            return mock_discovery

        mock_sc_initial.discover.side_effect = flaky_discover

        # 3. Build FacilityClient with token_provider, then trigger the 401 path
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.side_effect = make_sc
            client = Client()
            facility = client.facility(ENDPOINT, token_provider=provider)

            resources = facility.resources()

        # 4. Verify: discovery succeeded, provider was called exactly once for refresh
        assert len(resources) == 1
        assert token_calls[0] == 1  # provider called exactly once (for the retry)
