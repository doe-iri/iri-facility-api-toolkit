import unittest
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.serviceclient import ServiceClient, PlanError
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
            executable="sleep",
            arguments=["5"],
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
        
        print("\n--- Session Plan ---")
        try:
            session.plan()
        except PlanError as e:
            if any("unreachable" in err for err in e.errors):
                self.skipTest(f"Skipping test - K8s connectivity failed: {e}")
            self.fail(f"Plan failed with validation errors: {e}")
        
        # 6. Apply
        print("\n--- Session Apply ---")
        session.apply()

        # 7. Wait for Completion
        print("\n--- Session Wait ---")
        try:
            results = session.wait(
                jobs=[job],
                target_states=[JobState.COMPLETED, JobState.FAILED, JobState.CANCELED],
                timeout=180.0,
                interval=2.0,
                verbose=True,
            )
            final = results["sess-job-1"]
            print(f"Final Status: {final.state}")
            if final.provider_status:
                succeeded = final.provider_status.get("succeeded", 0)
                print(f"Succeeded count: {succeeded}")
            self.assertEqual(final.state, JobState.COMPLETED, f"Job did not complete: {final}")

        finally:
            # 8. Destroy
            print("\n--- Session Destroy ---")
            session.destroy()

            # Verify cleanup
            final_status = k_client.status(job_name="sess-job-1")
            print(f"Final Status: {final_status.state}")


if __name__ == "__main__":
    unittest.main()
