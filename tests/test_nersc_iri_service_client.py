import unittest
import pytest
import os
import shutil
from pathlib import Path
from amscrot.client.client import Client
from amscrot.client.job import Job, JobSpec, JobType, JobServiceType, JobState
from amscrot.serviceclient import ServiceClient, PlanError
from amscrot.util.constants import Constants


# Check if credentials file exists
CREDENTIALS_FILE = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
HAS_CREDENTIALS = os.path.exists(CREDENTIALS_FILE)

SESSION_NAME = "test-nersc-iri"


class TestNerscIriServiceClient(unittest.TestCase):
    """Test NERSC IRI ServiceClient integration using Session and Job objects."""
    
    @pytest.mark.integration
    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_nersc_iri_job_lifecycle(self):
        """Test the full lifecycle of a NERSC IRI job using Session/Job:
        plan -> create -> wait -> (fetch output files) -> destroy.
        """
        
        # --- Setup: Client, ServiceClient, Session ---
        client = Client()
        iri_client = ServiceClient.create(
            type=Constants.ServiceType.NERSC_IRI,
            name="nersc-iri-compute",
            profile="nersc-iri"
        )
        client.add_service_client(iri_client)
        
        self.assertIsNotNone(iri_client)
        self.assertTrue(iri_client._available, "NERSC IRI client should be available with valid credentials")
        
        session = client.create_session(SESSION_NAME)
        
        # --- Discover resources ---
        print("\n--- Discovering Resources ---")
        try:
            all_resources = iri_client.discover()
            compute_resources = all_resources.compute

            if not compute_resources:
                self.skipTest("No compute resources available.")

            target_resource = None
            for resource in compute_resources:
                data = resource.data
                if data.get('group') == 'perlmutter' and data.get('name') == 'compute':
                    target_resource = resource
                    break

            if not target_resource:
                self.skipTest("Target compute resource (perlmutter/compute) not found.")

            resource_data = target_resource.data
            resource_id = resource_data.get('id')

            if resource_id:
                print(f"Found target compute resource: {resource_data}")
                print(f"Using resource ID: {resource_id}")
            else:
                self.skipTest("Target compute resource found but ID is missing.")

            # Resolve a storage resource for filesystem operations
            # (prefer a resource with 'home' in its name, fall back to any available)
            storage_resources = all_resources.storage or []
            storage_resource_id = None
            for res in storage_resources:
                if 'home' in (res.data.get('name') or '').lower():
                    storage_resource_id = res.data.get('id')
                    break
            if not storage_resource_id and storage_resources:
                storage_resource_id = storage_resources[0].data.get('id')
            print(f"Storage resource ID: {storage_resource_id}")

        except Exception as e:
            import traceback
            error_msg = str(e)
            if "401" in error_msg or "403" in error_msg or "Unauthorized" in error_msg or "Forbidden" in error_msg:
                 print(f"Authentication failed (expected if token is invalid): {e}")
                 self.skipTest(f"Skipping test due to authentication failure: {e}")
            
            print(f"Exception details: {traceback.format_exc()}")
            self.skipTest(f"Failed to discover resources: {e}")

        # --- Create Job with stdout/stderr paths ---
        spec = JobSpec(
            executable="/bin/echo",
            arguments=["Hello AmSC"],
            resources={
                "node_count": 1,
                "process_count": 1,
                "processes_per_node": 1,
                "cpu_cores_per_process": 1,
                "gpu_cores_per_process": None,
                "exclusive_node_use": False,
                "memory": 268435456
            },
            attributes={
                "resource_id": resource_id,
                "directory": "/global/homes/k/kissel",
                "duration": 600,
                "queue_name": "debug",
                "account": "amsc013",
                "stdout_path": "nersc_iri_test_stdout.log",
                "stderr_path": "nersc_iri_test_stderr.log"
            }
        )
        
        job = Job(
            name="nersc-iri-test-job",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=iri_client,
            job_spec=spec,
        )
        session.add_job(job)
        
        try:
            # 1. Plan
            print("\n--- Test Plan ---")
            plan_result = iri_client.plan(spec, job.name)
            print(f"Plan result: {plan_result}")
            self.assertEqual(plan_result["status"], "PLANNED")

            # 2. Create
            print("\n--- Test Create ---")
            iri_client.create(spec, job.name)
            
            if job.name not in iri_client._submitted_jobs:
                self.skipTest(f"Job '{job.name}' was not submitted. Skipping remaining assertions.")
            
            self.assertIn(job.name, iri_client._submitted_jobs)
            tracked_resource_id, job_id = iri_client._submitted_jobs[job.name]
            self.assertIsNotNone(job_id, "Job ID should be returned from API")
            self.assertEqual(tracked_resource_id, resource_id)
            print(f"Job submitted with ID: {job_id}")
            
            # 3. Wait for completion
            print("\n--- Test Wait ---")
            results = session.wait(
                jobs=[job],
                target_states=[JobState.COMPLETED, JobState.FAILED, JobState.CANCELED],
                timeout=600,
                interval=2,
                verbose=True,
            )
            
            status_result = results[job.name]
            self.assertEqual(status_result.state, JobState.COMPLETED,
                             f"Job failed or timed out. State: {status_result.state}")
            print(f"Job completed successfully. Status: {status_result.state}")
            
            if status_result.provider_status:
                print(f"Raw IRI response: {status_result.provider_status}")
            self.assertEqual(status_result.job_id, job_id)
            
            # 4. Fetch output files
            print("\n--- Test Fetch Output Files ---")

            # List the remote working directory via the filesystem interface
            working_dir = spec.attributes.get("directory", "/")
            if storage_resource_id and iri_client.filesystem:
                try:
                    print(f"\n  [ls] {working_dir} on storage resource {storage_resource_id}:")
                    ls_result = iri_client.filesystem.ls(storage_resource_id, working_dir, format=True)
                    print(f"  {ls_result}")
                except Exception as ls_err:
                    print(f"  [ls] failed: {ls_err}")

            fetched = session.fetch_output_files(jobs=[job])
            print(f"Fetched files: {fetched}")
            print(f"Job local_files: {job.local_files}")
            
            # Verify files were fetched (if stdout/stderr paths existed on remote)
            if fetched.get(job.name):
                for stream, local_path in fetched[job.name].items():
                    self.assertTrue(os.path.exists(local_path),
                                    f"Expected local file at {local_path}")
                    print(f"  {stream}: {local_path} (exists={os.path.exists(local_path)})")
                    with open(local_path) as f:
                        contents = f.read()
                    print(f"  --- {stream} contents ---")
                    print(contents or "  (empty)")
                    print(f"  --- end {stream} ---")
            
            # Verify local_files was populated on the Job
            self.assertEqual(job.local_files, fetched.get(job.name, {}))

        except PlanError as e:
            if any("not available" in err or "credentials" in err.lower() for err in e.errors):
                self.skipTest(f"Skipping test - NERSC IRI client not available: {e}")
            raise

        except Exception as e:
            print(f"\n!!! Test failed with error: {e}")
            raise
            
        finally:
            # 5. Destroy
            print("\n--- Test Destroy ---")
            try:
                if job.name in iri_client._submitted_jobs:
                    iri_client.destroy(job.name)
                    self.assertNotIn(job.name, iri_client._submitted_jobs)
                    print("Job destroyed successfully")
            except Exception as cleanup_error:
                print(f"Warning: Failed to clean up job: {cleanup_error}")
            
            # Clean up session files
            try:
                session_dir = session.session_path
                if os.path.exists(session_dir):
                    shutil.rmtree(session_dir)
                    print(f"Cleaned up session dir: {session_dir}")
            except Exception:
                pass

    
    def test_nersc_iri_client_creation(self):
        """Test NERSC IRI ServiceClient creation."""
        iri_client = ServiceClient.create(
            type=Constants.ServiceType.NERSC_IRI,
            name="test-nersc-iri"
        )
        
        self.assertIsNotNone(iri_client)
        self.assertEqual(iri_client.type, Constants.ServiceType.NERSC_IRI)
        self.assertEqual(iri_client.name, "test-nersc-iri")
    
    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_resource_id_extraction(self):
        """Test that resource_id is correctly extracted from JobSpec attributes."""
        iri_client = ServiceClient.create(
            type="nersc-iri",
            name="test-nersc-iri",
            profile="nersc-iri"
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
        
        # Starts empty
        self.assertEqual(job.local_files, {})
        
        # Paths are in the spec attributes
        self.assertEqual(job.job_spec.attributes["stdout_path"], "/remote/stdout.log")
        self.assertEqual(job.job_spec.attributes["stderr_path"], "/remote/stderr.log")
        
        # Can be written to
        job.local_files["stdout"] = "/local/stdout.log"
        self.assertEqual(job.local_files["stdout"], "/local/stdout.log")

    def test_session_paths(self):
        """Test Session.session_path and Session.files_path align with AmSCROTManager."""
        from amscrot.client.models import Session
        
        session = Session(name="test-paths-session")
        expected_base = os.path.join(str(Path.home()), '.amscrot', 'sessions', 'test-paths-session')
        
        self.assertEqual(session.session_path, expected_base)
        self.assertTrue(os.path.isdir(expected_base))
        
        files_dir = session.files_path("my-job")
        expected_files = os.path.join(expected_base, 'files', 'my-job')
        self.assertEqual(files_dir, expected_files)
        self.assertTrue(os.path.isdir(expected_files))
        
        # Cleanup
        shutil.rmtree(expected_base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
