import unittest
import time
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import ServiceClient
from amscrot.util.constants import Constants


class TestSessionLifecycle(unittest.TestCase):
    def test_session_job_orchestration(self):
        # 1. Setup Client and Session
        client = Client()

        session = client.create_session("test-session-k8s-v2")
        
        # 2. Setup KubeServiceClient and Job
        k_client = ServiceClient.create(type=Constants.ServiceType.KUBE,
                                        name="sess-k8s")
        
        # 3. Provide Job specification
        spec = JobSpec(
            image="busybox",
            executable=["sleep", "5"],
            resources={"requests": {"cpu": "1", "memory": "1Gi"}},
            attributes={
                "namespace": "default",
                "labels": {"kueue.x-k8s.io/queue-name": "compute-queue"},
                "completions": 5,
                "parallelism": 5,
                "ttlSecondsAfterFinished": 60,
                "priorityClassName": "batch-low",
                "restartPolicy": "Never"
            }
        )
        
        # 4. Add Job with bound spec
        job = Job(
            name="sess-job-1",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=k_client,
            job_spec=spec
        )
        
        session.add_job(job)
        
        # 5. Plan
        print("\n--- Session Plan ---")
        try:
            session.plan()
        except Exception as e:
            if "Kubernetes cluster unreachable" in str(e):
                self.skipTest(f"Skipping test - K8s connectivity failed: {e}")
            else:
                raise
        
        # 6. Apply
        print("\n--- Session Apply ---")
        session.apply()
        
        # 7. Show (Poll Status)
        print("\n--- Session Show (Polling) ---")
        try:
            # Poll for completion
            for i in range(10):
                session.show()
                
                status = k_client.status(job_name="sess-job-1")
                print(f"Poll {i}: {status.get('status')} - Succeeded: {status.get('succeeded')}")
                
                if status.get("succeeded") == 5:
                    print("Job completed successfully via Session orchestration.")
                    break
                
                if status.get("status") == "ERROR":
                    print(f"FAILED STATUS: {status}")
                    self.fail(f"Job failed during session execution: {status}")
                    
                time.sleep(2)
            else:
                 self.fail("Timed out waiting for session job completion")

        finally:
            # 8. Destroy
            print("\n--- Session Destroy ---")
            session.destroy()
            
            # Verify cleanup
            final_status = k_client.status(job_name="sess-job-1")
            print(f"Final Status: {final_status}")


if __name__ == "__main__":
    unittest.main()
