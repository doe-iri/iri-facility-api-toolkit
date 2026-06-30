import unittest
import pytest
import os
import shutil
from pathlib import Path
from amscrot.client.client import Client
from amscrot.client.job import Job, JobSpec, JobType, JobServiceType, JobState
from amscrot.serviceclient import ServiceClient, PlanError, CreateError
from amscrot.util.constants import Constants


SESSION_NAME = "test-kube-kueue"

try:
    import kubernetes
    HAS_KUBE = True
except ImportError:
    HAS_KUBE = False


@pytest.mark.skipif(not HAS_KUBE, reason="Requires 'kubernetes' module")
class TestKubeKueueServiceClient(unittest.TestCase):
    """Test Kubernetes/Kueue ServiceClient integration using Session and Job objects."""

    def test_kube_kueue_client_creation(self):
        """Test Kube ServiceClient creation."""
        k_client = ServiceClient.create(
            type=Constants.ServiceType.KUBE,
            name="test-kube"
        )
        self.assertIsNotNone(k_client)
        self.assertEqual(k_client.type, Constants.ServiceType.KUBE)
        self.assertEqual(k_client.name, "test-kube")

    @pytest.mark.integration
    def test_kube_kueue_job_lifecycle(self):
        """Test the full lifecycle of a Kubernetes/Kueue batch job using Session/Job:
        plan -> apply -> wait -> destroy.
        """

        # --- Setup: Client, ServiceClient, Session ---
        client = Client()
        k_client = ServiceClient.create(
            type=Constants.ServiceType.KUBE,
            name="kube-kueue-compute"
        )
        client.add_service_client(k_client)

        self.assertIsNotNone(k_client)

        session = client.create_session(SESSION_NAME)

        # --- Build JobSpec ---
        spec = JobSpec(
            executable="sleep",
            arguments=["5"],
            resources={"requests": {"cpu": "1", "memory": "1Gi"}},
            attributes={
                "container": {"image": "busybox"},
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
            name="kube-kueue-test-job",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=k_client,
            job_spec=spec
        )
        session.add_job(job)

        try:
            # 1. Plan
            print("\n--- Test Plan ---")
            try:
                plan_result = session.plan(verbose=True)
                print(f"Plan result: {plan_result}")
            except PlanError as e:
                skip_keywords = ("unreachable", "not available", "not found", "connection refused", "connection timed out")
                if any(kw in err.lower() for err in e.errors for kw in skip_keywords):
                    self.skipTest(f"Skipping test - K8s cluster setup incomplete or unreachable: {e}")
                self.fail(f"Plan failed with validation errors: {e}")

            # 2. Apply (Create)
            print("\n--- Test Apply ---")
            result = session.apply()
            print(f"Apply result: {result}")
            self.assertIsInstance(result, dict)
            self.assertIn("resources", result)
            self.assertIn("jobs", result)

            if not job.id:
                self.skipTest(f"Job '{job.name}' was not submitted. Skipping remaining assertions.")

            print(f"Job submitted with ID: {job.id}")

            # 3. Wait for completion
            print("\n--- Test Wait ---")
            results = session.wait(
                jobs=[job],
                target_states=[JobState.COMPLETED, JobState.FAILED, JobState.CANCELED],
                timeout=180,
                interval=2,
                verbose=True,
            )

            status_result = results[job.name]
            self.assertEqual(status_result.state, JobState.COMPLETED,
                             f"Job failed or timed out. State: {status_result.state}")
            print(f"Job completed successfully. Status: {status_result.state}")

            if status_result.provider_status:
                succeeded = status_result.provider_status.get("succeeded", 0)
                print(f"Succeeded count: {succeeded}")

        except (PlanError, CreateError) as e:
            if any("not available" in err or "500" in err or "unreachable" in err or "connection" in err.lower() for err in e.errors):
                self.skipTest(f"Skipping test - Kube/Kueue client API issue: {e}")
            raise

        except Exception as e:
            print(f"\n!!! Test failed with error: {e}")
            raise

        finally:
            # 4. Destroy
            print("\n--- Test Destroy ---")
            try:
                session.destroy()
                print("Session destroyed successfully")
            except Exception as cleanup_error:
                print(f"Warning: Failed to clean up session: {cleanup_error}")

            # Clean up session files
            try:
                session_dir = session.session_path
                if os.path.exists(session_dir):
                    shutil.rmtree(session_dir)
                    print(f"Cleaned up session dir: {session_dir}")
            except Exception:
                pass

    def test_job_spec_attributes(self):
        """Test that JobSpec attributes are initialized correctly for Kube/Kueue."""
        spec = JobSpec(
            executable="sleep",
            arguments=["5"],
            resources={"requests": {"cpu": "1", "memory": "1Gi"}},
            attributes={
                "container": {"image": "busybox"},
                "namespace": "default",
                "restartPolicy": "Never",
            }
        )

        job = Job(
            name="test-kube-spec",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            job_spec=spec,
        )

        self.assertEqual(job.job_spec.attributes["container"]["image"], "busybox")
        self.assertEqual(job.job_spec.attributes["namespace"], "default")
        self.assertEqual(job.job_spec.attributes["restartPolicy"], "Never")
        self.assertEqual(job.job_spec.executable, "sleep")
        self.assertEqual(job.local_files, {})


if __name__ == "__main__":
    unittest.main()
