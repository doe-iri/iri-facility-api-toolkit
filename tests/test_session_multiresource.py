import unittest
import time
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import ServiceClient

class TestSessionMultiResource(unittest.TestCase):
    def test_multiresource_session_lifecycle(self):
        # 1. Initialize Client
        client = Client()
        
        # 2. Add Dummy Provider for Network resource
        dummy_provider = client.add_provider(
            label="dummy_site",
            type="dummy",
            name="dummy-provider"
        )

        # 3. Create Session
        session = client.create_session("sess-multiresource-v2")
        
        # 4. Add Resources
        # Network Resource (managed by DummyProvider)
        net1 = session.add_network(
            label="net1",
            provider=dummy_provider,
            name_prefix="test-net",
            site="site1",
            count=1
        )
        
        # 5. Setup Kube Service Client for Jobs
        k_client = ServiceClient.create(
            type="kube", 
            name="k8s-client", 
            endpoint_uri="http://localhost:8080"
        )
        session.add_service_client(k_client)
        
        # 6. Create Jobs
        # Job 1
        spec1 = JobSpec(
            image="busybox",
            executable=["echo", "Running Job 1"],
            attributes={"namespace": "default", "restartPolicy": "Never"}
        )
        job1 = Job(
            name="job-1",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=k_client,
            job_spec=spec1
        )
        
        # Job 2
        spec2 = JobSpec(
            image="busybox",
            executable=["echo", "Running Job 2"],
            attributes={"namespace": "default", "restartPolicy": "Never"}
        )
        job2 = Job(
            name="job-2",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=k_client,
            job_spec=spec2
        )

        # Add Jobs to Session
        session.add_job(job1)
        session.add_job(job2)
        
        # 7. Plan
        print("\n--- Session Plan ---")
        session.plan()
        
        # 8. Apply
        print("\n--- Session Apply ---")
        session.apply()
        
        # 9. Show Status (Poll)
        print("\n--- Session Status (Poll) ---")
        for i in range(10):
            session.show()
            
            # Check individual job statuses via client
            s1 = k_client.status(job_name="job-1")
            s2 = k_client.status(job_name="job-2")
            
            print(f"Poll {i}: Job1={s1.get('status')} Job2={s2.get('status')}")
            
            if (s1.get('status') in ["DONE", "RUNNING"] and 
                s2.get('status') in ["DONE", "RUNNING"]):
                # Success if both are at least running or done
                # Since busybox jobs might finish instantly, "DONE" is good.
                break
                
            time.sleep(1)
            
        # 10. Destroy
        print("\n--- Session Destroy ---")
        session.destroy()
        
        # Verify cleanup with pulling
        for i in range(10):
            s1 = k_client.status(job_name="job-1")
            s2 = k_client.status(job_name="job-2")
            if (s1.get('status') in ["DESTROYED", "UNKNOWN", "KILLED"] and 
                s2.get('status') in ["DESTROYED", "UNKNOWN", "KILLED"]):
                break
            time.sleep(1)
        
        self.assertIn(s1.get('status'), ["DESTROYED", "UNKNOWN", "KILLED"])
        self.assertIn(s2.get('status'), ["DESTROYED", "UNKNOWN", "KILLED"])

if __name__ == "__main__":
    unittest.main()
