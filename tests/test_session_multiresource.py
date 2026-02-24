import unittest
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.serviceclient import ServiceClient, PlanError
from amscrot.util.constants import Constants

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
            type=Constants.ServiceType.KUBE, 
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
        
        print("\n--- Session Plan ---")
        try:
            session.plan()
        except PlanError as e:
            if any("unreachable" in err for err in e.errors):
                self.skipTest(f"Skipping test - K8s connectivity failed: {e}")
            self.fail(f"Plan failed with validation errors: {e}")
        
        # 8. Apply
        print("\n--- Session Apply ---")
        session.apply()
        
        # 9. Wait for Jobs (ACTIVE means submitted, COMPLETED means done)
        print("\n--- Session Status (Wait) ---")
        results = session.wait(
            jobs=[job1, job2],
            target_states=[JobState.COMPLETED, JobState.ACTIVE, JobState.FAILED, JobState.CANCELED],
            timeout=20.0,
            interval=1.0,
            verbose=True,
        )
        s1 = results["job-1"]
        s2 = results["job-2"]
        print(f"Settled: job-1={s1.state} job-2={s2.state}")
            
        # 10. Destroy
        print("\n--- Session Destroy ---")
        session.destroy()
        
        # Verify cleanup with wait
        cleanup = session.wait(
            jobs=[job1, job2],
            target_states=[JobState.CANCELED, JobState.UNKNOWN],
            timeout=20.0,
            interval=1.0,
            verbose=True,
        )
        s1 = cleanup["job-1"]
        s2 = cleanup["job-2"]
        self.assertIn(s1.state, [JobState.CANCELED, JobState.UNKNOWN])
        self.assertIn(s2.state, [JobState.CANCELED, JobState.UNKNOWN])

if __name__ == "__main__":
    unittest.main()
