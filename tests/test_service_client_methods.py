import unittest
import pytest
from amscrot.serviceclient import ServiceClient, PlanError
from amscrot.util.constants import Constants
from amscrot.client.job import Job, JobSpec, JobState, JobType, JobServiceType

class TestServiceClientMethods(unittest.TestCase):
    def test_dummy_methods(self):
        client = ServiceClient.create(type=Constants.ServiceType.DUMMY, name="dummy1", endpoint_uri="http://dummy")
        spec = JobSpec(attributes={"container": {"image": "test-image"}})
        job = Job(name="test-dummy", type=JobType.COMPUTE, service_type=JobServiceType.BATCH, job_spec=spec, service_client=client)
        
        # Test Plan
        plan_result = client.plan(job)
        self.assertIsInstance(plan_result, dict)
        self.assertEqual(plan_result["status"], JobState.PLANNED)
        
        # Test Create
        client.create(job)
        self.assertEqual(client.status(job).state, JobState.ACTIVE)
        
        # Test Destroy
        client.destroy(job)
        self.assertEqual(client.status(job).state, JobState.CANCELED)
        
    @pytest.mark.integration
    def test_kube_methods(self):
        client = ServiceClient.create(type=Constants.ServiceType.KUBE, name="kube1", endpoint_uri="http://kube")
        if not client._available:
            self.skipTest("Skipping test - no kubeconfig found")
        spec = JobSpec(executable="echo", arguments=["hello"], attributes={"container": {"image": "busybox"}})
        job = Job(name="test-kube", type=JobType.COMPUTE, service_type=JobServiceType.BATCH, job_spec=spec, service_client=client)

        try:
            plan_result = client.plan(job)
        except PlanError as e:
            if any("unreachable" in err or "not found" in err.lower() for err in e.errors):
                self.skipTest(f"Skipping test - K8s cluster unavailable: {e}")
            self.fail(f"Plan raised PlanError unexpectedly: {e}")
        self.assertIsInstance(plan_result, dict)
        self.assertEqual(plan_result["status"], JobState.PLANNED)

        client.create(job)
        client.destroy(job)
        client.status(job)

    @pytest.mark.integration
    def test_kube_log_capture(self):
        # Test with a job that sleeps and prints
        client = ServiceClient.create(type=Constants.ServiceType.KUBE, name="logtest", endpoint_uri="http://kube")
        spec = JobSpec(
            executable="python",
            arguments=["-c", "import time; print('Hello K8s Logs'); time.sleep(5); print('Done Sleep')"],
            attributes={"container": {"image": "python:3.9-slim"}}
        )
        job = Job(name="test-kube-log", type=JobType.COMPUTE, service_type=JobServiceType.BATCH, job_spec=spec, service_client=client)
        
        try:
            plan_result = client.plan(job)
        except PlanError as e:
            if any("unreachable" in err for err in e.errors):
                self.skipTest(f"Skipping test - K8s connectivity failed: {e}")
            self.fail(f"Plan raised PlanError unexpectedly: {e}")
        self.assertEqual(plan_result["status"], JobState.PLANNED)
        
        client.create(job)
        
        # Poll for logs (simulated simple polling loop)
        import time
        max_retries = 30
        found_log = False
        
        try:
            for _ in range(max_retries):
                job_status = client.status(job)
                logs = (job_status.provider_status or {}).get("logs", "")
                if "Hello K8s Logs" in logs:
                    found_log = True
                    print(logs)
                    break
                time.sleep(1)
        finally:
            client.destroy(job)

        if client._available:
             self.assertTrue(found_log, "Did not find expected log message")
        
if __name__ == "__main__":
    unittest.main()
