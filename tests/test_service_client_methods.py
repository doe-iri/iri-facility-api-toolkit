import unittest
from amscrot.serviceclient import ServiceClient, PlanError
from amscrot.util.constants import Constants
from amscrot.client.job import JobSpec, JobState

class TestServiceClientMethods(unittest.TestCase):
    def test_iri_methods(self):
        client = ServiceClient.create(type=Constants.ServiceType.IRI, name="iri1", endpoint_uri="http://iri")
        spec = JobSpec(image="test-image")
        
        # Test Plan
        plan_result = client.plan(spec)
        self.assertIsInstance(plan_result, dict)
        self.assertEqual(plan_result["status"], JobState.PLANNED)
        
        # Test Create
        client.create(spec)
        self.assertEqual(client.status().state, JobState.ACTIVE)
        
        # Test Destroy
        client.destroy()
        self.assertEqual(client.status().state, JobState.CANCELED)
        
    def test_kube_methods(self):
        client = ServiceClient.create(type=Constants.ServiceType.KUBE, name="kube1", endpoint_uri="http://kube")
        spec = JobSpec(image="busybox", executable=["echo", "hello"])

        try:
            plan_result = client.plan(spec)
        except PlanError as e:
            if any("unreachable" in err for err in e.errors):
                self.skipTest(f"Skipping test - K8s connectivity failed: {e}")
            self.fail(f"Plan raised PlanError unexpectedly: {e}")
        self.assertIsInstance(plan_result, dict)
        self.assertEqual(plan_result["status"], JobState.PLANNED)

        client.create(spec)
        client.destroy()
        client.status()

    def test_kube_log_capture(self):
        # Test with a job that sleeps and prints
        client = ServiceClient.create(type=Constants.ServiceType.KUBE, name="logtest", endpoint_uri="http://kube")
        spec = JobSpec(
            image="python:3.9-slim", 
            executable=["python", "-c", "import time; print('Hello K8s Logs'); time.sleep(5); print('Done Sleep')"]
        )
        
        try:
            plan_result = client.plan(spec)
        except PlanError as e:
            if any("unreachable" in err for err in e.errors):
                self.skipTest(f"Skipping test - K8s connectivity failed: {e}")
            self.fail(f"Plan raised PlanError unexpectedly: {e}")
        self.assertEqual(plan_result["status"], JobState.PLANNED)
        
        client.create(spec)
        
        # Poll for logs (simulated simple polling loop)
        import time
        max_retries = 30
        found_log = False
        
        try:
            for _ in range(max_retries):
                job_status = client.status()
                logs = (job_status.provider_status or {}).get("logs", "")
                if "Hello K8s Logs" in logs:
                    found_log = True
                    print(logs)
                    break
                time.sleep(1)
        finally:
            client.destroy()

        if client._available:
             self.assertTrue(found_log, "Did not find expected log message")
        
if __name__ == "__main__":
    unittest.main()
