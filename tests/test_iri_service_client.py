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

    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_resource_id_extraction(self):
        """Test that resource_id is correctly extracted from JobSpec attributes."""
        iri_client = ServiceClient.create(
            type="iri",
            name="test-iri",
            profile="esnet-iri-east"
        )

        spec = JobSpec(
            executable="echo",
            arguments=["test"],
            attributes={"resource_id": "custom-resource-id"}
        )

        resource_id = iri_client._get_resource_id(spec)
        self.assertEqual(resource_id, "custom-resource-id")

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
        expected = "amscrot.serviceclient.amsc_iri.iri_service_client.IriServiceClient"
        self.assertEqual(Constants.SERVICE_CLIENT_CLASSES[Constants.ServiceType.IRI], expected)
        # Old entries should no longer exist
        self.assertNotIn("esnet-iri", Constants.SERVICE_CLIENT_CLASSES)
        self.assertNotIn("nersc-iri", Constants.SERVICE_CLIENT_CLASSES)


# ── IriServiceClient.status() — PBS queue-exit behaviour ──────────────────

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
        """PBS removes completed jobs from the active queue — NotFoundException → COMPLETED."""
        sc = _make_iri_sc()
        sc._compute_api.get_job.side_effect = NotFoundException()

        result = sc.status(_make_job_handle())

        assert result.state == "COMPLETED"

    def test_none_response_returns_completed(self):
        """A None return from get_job (job left queue silently) → COMPLETED."""
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

        assert result.state not in ("UNKNOWN", "COMPLETED")


if __name__ == "__main__":
    unittest.main()
