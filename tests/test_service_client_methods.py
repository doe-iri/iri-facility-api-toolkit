import unittest
from amscrot.serviceclient import ServiceClient
from amscrot.client.job import JobSpec

class TestServiceClientMethods(unittest.TestCase):
    def test_iri_methods(self):
        client = ServiceClient.create(type="iri", name="iri1", endpoint_uri="http://iri")
        spec = JobSpec(image="test-image")
        
        # Test Plan
        plan_result = client.plan(spec)
        self.assertIsInstance(plan_result, dict)
        self.assertEqual(plan_result["status"], "PLANNED")
        
        # Test Create
        client.create(spec)
        self.assertEqual(client.status()["status"], "RUNNING")
        
        # Test Destroy
        client.destroy()
        self.assertEqual(client.status()["status"], "STOPPED")
        
    def test_kube_methods(self):
        client = ServiceClient.create(type="kube", name="kube1", endpoint_uri="http://kube")
        spec = JobSpec(image="busybox", executable=["echo", "hello"])
        
        plan_result = client.plan(spec)
        self.assertIsInstance(plan_result, dict)
        # It might be PLANNED or FAILED depending on env, but for simple busybox it should be PLANNED 
        # unless Kube client is missing completely, in which case it is PLANNED with warnings.
        self.assertEqual(plan_result["status"], "PLANNED")
        
        client.create(spec)
        client.destroy()
        client.status()

    def test_kube_log_capture(self):
        # Test with a job that sleeps and prints
        client = ServiceClient.create(type="kube", name="logtest", endpoint_uri="http://kube")
        spec = JobSpec(
            image="python:3.9-slim", 
            executable=["python", "-c", "import time; print('Hello K8s Logs'); time.sleep(5); print('Done Sleep')"]
        )
        
        plan_result = client.plan(spec)
        self.assertEqual(plan_result["status"], "PLANNED")
        
        client.create(spec)
        
        # Poll for logs (simulated simple polling loop)
        import time
        max_retries = 30
        found_log = False
        
        try:
            for _ in range(max_retries):
                status_dict = client.status()
                logs = status_dict.get("logs", "")
                if "Hello K8s Logs" in logs:
                    found_log = True
                    print (logs)
                    break
                time.sleep(1)
        finally:
            client.destroy()

        if client._available:
             self.assertTrue(found_log, "Did not find expected log message")
        
if __name__ == "__main__":
    unittest.main()
