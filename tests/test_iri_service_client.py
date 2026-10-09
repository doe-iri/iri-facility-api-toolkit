import unittest
import pytest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from amscrot.serviceclient import ServiceClient, PlanError, CreateError
from amscrot.client.job import Job, JobSpec, JobType, JobServiceType
from amscrot.util.constants import Constants
from amsc_iri.exceptions import NotFoundException, BadRequestException


# Check if credentials file exists
CREDENTIALS_FILE = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
HAS_CREDENTIALS = os.path.exists(CREDENTIALS_FILE)


class TestIriServiceClient(unittest.TestCase):
    """Unit tests for the unified IriServiceClient."""

    def test_iri_client_creation_via_factory(self):
        """Test IriServiceClient creation through the ServiceClient.create factory."""
        iri_client = ServiceClient.create(
            type=Constants.ServiceType.IRI,
            name="test-iri",
            profile="esnet-iri-east"
        )

        self.assertIsNotNone(iri_client)
        self.assertEqual(iri_client.type, Constants.ServiceType.IRI)
        self.assertEqual(iri_client.name, "test-iri")

    def test_iri_client_creation_with_string_type(self):
        """Test IriServiceClient creation using the raw string type."""
        iri_client = ServiceClient.create(
            type="iri",
            name="test-iri-string",
            profile="esnet-iri-east"
        )

        self.assertIsNotNone(iri_client)
        self.assertEqual(iri_client.type, "iri")


    def test_job_local_files_attribute(self):
        """Test that Job.local_files is initialized correctly and mutable."""
        job = Job(
            name="test-job",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            job_spec=JobSpec(
                executable="echo",
                arguments=["test"],
                attributes={
                    "stdout_path": "/remote/stdout.log",
                    "stderr_path": "/remote/stderr.log",
                }
            ),
        )

        self.assertEqual(job.local_files, {})
        self.assertEqual(job.job_spec.attributes["stdout_path"], "/remote/stdout.log")
        self.assertEqual(job.job_spec.attributes["stderr_path"], "/remote/stderr.log")

        job.local_files["stdout"] = "/local/stdout.log"
        self.assertEqual(job.local_files["stdout"], "/local/stdout.log")

    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_iri_client_with_different_profiles(self):
        """Test that different profiles resolve to different endpoints."""
        client_east = ServiceClient.create(
            type="iri",
            name="iri-east",
            profile="esnet-iri-east"
        )
        client_nersc = ServiceClient.create(
            type="iri",
            name="iri-nersc",
            profile="nersc-iri"
        )

        self.assertIsNotNone(client_east)
        self.assertIsNotNone(client_nersc)
        # Different profiles should yield different endpoints
        self.assertNotEqual(client_east.api_endpoint, client_nersc.api_endpoint)

    def test_service_type_constant(self):
        """Test that the IRI service type constant is correct."""
        self.assertEqual(Constants.ServiceType.IRI, "iri")
        # Old types should no longer exist
        self.assertFalse(hasattr(Constants.ServiceType, 'ESNET_IRI'))
        self.assertFalse(hasattr(Constants.ServiceType, 'NERSC_IRI'))

    def test_service_client_classes_registration(self):
        """Test that the SERVICE_CLIENT_CLASSES registry points to the unified class."""
        expected = "amscrot.serviceclient.amsc_iri.IriServiceClient"
        self.assertEqual(Constants.SERVICE_CLIENT_CLASSES[Constants.ServiceType.IRI], expected)
        # Old entries should no longer exist
        self.assertNotIn("esnet-iri", Constants.SERVICE_CLIENT_CLASSES)
        self.assertNotIn("nersc-iri", Constants.SERVICE_CLIENT_CLASSES)


# -- IriServiceClient.status() - PBS queue-exit behaviour ------------------

def _make_iri_sc():
    """Build an IriServiceClient with mocked API clients."""
    sc = ServiceClient.create(
        type="amsc-iri",
        name="test-alcf",
        endpoint_uri="https://api.alcf.anl.gov",
        credential={"api_key": "test-token",
                    "api_endpoint": "https://api.alcf.anl.gov"},
    )
    sc._compute_api = MagicMock()
    sc._available = True
    return sc


def _make_job_handle(job_id="job-001", resource_id="res-001"):
    return SimpleNamespace(
        id=job_id,
        resource_id=resource_id,
        name="test-job",
    )


class TestIriServiceClientStatus:
    def test_not_found_exception_returns_completed(self):
        """PBS removes completed jobs from the active queue -- NotFoundException -> COMPLETED."""
        sc = _make_iri_sc()
        sc._compute_api.get_job.side_effect = NotFoundException()

        result = sc.status(_make_job_handle())

        assert result.state == "COMPLETED"

    def test_none_response_returns_completed(self):
        """A None return from get_job (job left queue silently) -> COMPLETED."""
        sc = _make_iri_sc()
        sc._compute_api.get_job.return_value = None

        result = sc.status(_make_job_handle())

        assert result.state == "COMPLETED"

    def test_bad_request_not_found_returns_completed(self):
        """ALCF returns 400 with 'not found' detail when job left the PBS queue."""
        sc = _make_iri_sc()
        exc = BadRequestException(status=400, reason="Bad Request")
        exc.body = '{"detail": "Job 7101273.polaris-pbs-01 not found."}'
        sc._compute_api.get_job.side_effect = exc

        result = sc.status(_make_job_handle())

        assert result.state == "COMPLETED"

    def test_bad_request_other_reason_returns_unknown(self):
        """400 errors unrelated to job-not-found still return UNKNOWN."""
        sc = _make_iri_sc()
        exc = BadRequestException(status=400, reason="Bad Request")
        exc.body = '{"detail": "Invalid resource_id format."}'
        sc._compute_api.get_job.side_effect = exc

        result = sc.status(_make_job_handle())

        assert result.state == "UNKNOWN"

    def test_other_exception_still_returns_unknown(self):
        """Non-404 errors (network failure, etc.) still return UNKNOWN."""
        sc = _make_iri_sc()
        sc._compute_api.get_job.side_effect = RuntimeError("timeout")

        result = sc.status(_make_job_handle())

        assert result.state == "UNKNOWN"

    def test_active_job_state_returned_normally(self):
        """Normal in-queue job returns mapped state."""
        from amsc_iri.models import JobState
        sc = _make_iri_sc()
        mock_job = MagicMock()
        mock_job.status.state = JobState.ACTIVE
        mock_job.status.message = None
        mock_job.status.exit_code = None
        sc._compute_api.get_job.return_value = mock_job

        result = sc.status(_make_job_handle())

    def test_format_api_exception_pretty_prints_json(self):
        """format_api_exception should pretty print JSON response body."""
        from amscrot.util.utils import format_api_exception

        raw_json = '{"type":"https://example.com/problems/unauthorized","status":401,"title":"Unauthorized","detail":"Auth failed"}'
        exc = BadRequestException(status=401, reason="Unauthorized")
        exc.body = raw_json

        formatted = format_api_exception(exc)
        assert "  \"status\": 401" in formatted
        assert "  \"detail\": \"Auth failed\"" in formatted

    def test_format_api_exception_with_string_marker(self):
        """format_api_exception should parse HTTP response body marker in exception string."""
        from amscrot.util.utils import format_api_exception

        msg = '(401)\nReason: Unauthorized\nHTTP response body: {"detail": "token invalid"}\nHTTP response data: ...'
        exc = Exception(msg)

        formatted = format_api_exception(exc)
        assert "  \"detail\": \"token invalid\"" in formatted


# -- _get_storage_resource_id() - availability filtering -------------------

def _storage_res(name, status, rid=None):
    """Build a mock storage resource. ``status`` mirrors the IRI Status enum values."""
    res = MagicMock()
    res.name = name
    res.id = rid or f"id-{name}"
    res.current_status = status
    return res


def _sc_with_storage(resources):
    sc = _make_iri_sc()
    sc._status_api = MagicMock()
    sc._status_api.get_resources.return_value = resources
    return sc


class TestIriStorageResolution:
    def test_unknown_status_is_usable(self):
        """ALCF reports every filesystem as 'unknown'; those must still resolve.

        Regression test: requiring status == 'up' made fetch_output_files fail
        at ALCF with "No available storage resource found".
        """
        sc = _sc_with_storage([
            _storage_res("Home", "unknown"),
            _storage_res("Eagle", "unknown"),
        ])
        assert sc._get_storage_resource_id("compute-1") == "id-Home"

    def test_degraded_status_is_usable(self):
        """A degraded filesystem is still better than no download at all."""
        sc = _sc_with_storage([_storage_res("archive", "degraded")])
        assert sc._get_storage_resource_id("compute-1") == "id-archive"

    def test_down_resources_are_excluded(self):
        sc = _sc_with_storage([
            _storage_res("broken-home", "down"),
            _storage_res("scratch", "up"),
        ])
        assert sc._get_storage_resource_id("compute-1") == "id-scratch"

    def test_all_down_returns_none(self):
        sc = _sc_with_storage([_storage_res("a", "down"), _storage_res("b", "down")])
        assert sc._get_storage_resource_id("compute-1") is None

    def test_no_storage_advertised_returns_none(self):
        sc = _sc_with_storage([])
        assert sc._get_storage_resource_id("compute-1") is None

    def test_up_preferred_over_unknown_home(self):
        """Among 'home' candidates, a confirmed-up one wins."""
        sc = _sc_with_storage([
            _storage_res("home-unknown", "unknown"),
            _storage_res("home-up", "up"),
        ])
        assert sc._get_storage_resource_id("compute-1") == "id-home-up"

    def test_home_preferred_over_other_names(self):
        sc = _sc_with_storage([
            _storage_res("scratch", "up"),
            _storage_res("homes", "up"),
        ])
        assert sc._get_storage_resource_id("compute-1") == "id-homes"

    def test_enum_valued_status_is_handled(self):
        """Status may arrive as an enum with .value rather than a bare string."""
        sc = _sc_with_storage([_storage_res("Home", SimpleNamespace(value="unknown"))])
        assert sc._get_storage_resource_id("compute-1") == "id-Home"

    def test_none_status_is_usable(self):
        sc = _sc_with_storage([_storage_res("Home", None)])
        assert sc._get_storage_resource_id("compute-1") == "id-Home"

    def test_api_error_returns_none(self):
        sc = _make_iri_sc()
        sc._status_api = MagicMock()
        sc._status_api.get_resources.side_effect = RuntimeError("boom")
        assert sc._get_storage_resource_id("compute-1") is None


if __name__ == "__main__":
    unittest.main()
