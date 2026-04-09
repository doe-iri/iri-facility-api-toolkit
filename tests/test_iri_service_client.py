import unittest
import pytest
import os
from pathlib import Path
from amscrot.serviceclient import ServiceClient, PlanError, CreateError
from amscrot.client.job import Job, JobSpec, JobType, JobServiceType
from amscrot.util.constants import Constants


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


if __name__ == "__main__":
    unittest.main()
