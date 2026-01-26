import unittest
import time
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import ServiceClient


class TestSessionLifecycle(unittest.TestCase):
    def test_session_job_orchestration(self):
        # 1. Setup Client and Session
        client = Client()

        session = client.create_session("test-session-k8s-v2")
        
        # 2. Setup KubeServiceClient and Job
        k_client = ServiceClient.create(type="kube", name="sess-k8s", endpoint_uri="http://kube")
        
        # Use simple spec for quicker test (using busybox)
        # Note: we assume kueue is setup from previous steps if we used the advanced config that requires it.
        # Let's use the advanced spec to verify full integration, but reduce times/counts.
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
        
        job = Job(
            name="sess-job-1",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=k_client,
            job_spec=spec
        )
        
        session.add_job(job)
        
        # 3. Plan
        print("\n--- Session Plan ---")
        session.plan()
        
        # 4. Apply
        print("\n--- Session Apply ---")
        session.apply()
        
        # 5. Show (Poll Status)
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
            # 6. Destroy
            print("\n--- Session Destroy ---")
            session.destroy()
            
            # Verify cleanup
            final_status = k_client.status(job_name="sess-job-1")
            print(f"Final Status: {final_status}")


if __name__ == "__main__":
    unittest.main()
