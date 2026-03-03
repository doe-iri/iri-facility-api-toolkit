import argparse
import unittest
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.serviceclient import ServiceClient, PlanError
from amscrot.util.constants import Constants

class SENSENetworkedJobs(unittest.TestCase):
    def main(self, use_network=False):
        # 1. Initialize Client
        client = Client()
        
        # 2. Create Session
        session = client.create_session("sense-networked-jobs")

        # 3. Optionally add SENSE provider and network
        if use_network:
            print("\n--- Adding SENSE Network ---")
            sense_provider = client.add_provider(
                label="sense",
                type="sense",
                name="sense-provider",
                profile="sense",
                credential_file="~/.amscrot/credentials.yml"
            )
            net1 = session.add_network(
                label="net1",
                provider=sense_provider,
                name_prefix="test-net",
                site="ESnet",
                profile='AmSC-WFC-L2VPN',
                count=1
            )
            print("SENSE network added to session.")
        else:
            print("\n--- Skipping SENSE network (use --network to enable) ---")
        
        # 5. Setup ESnet IRI Service Clients for Jobs
        east_client = ServiceClient.create(
            type=Constants.ServiceType.ESNET_IRI, 
            name="iri-east",
            profile="esnet-iri-east"
        )
        session.add_service_client(east_client)

        west_client = ServiceClient.create(
            type=Constants.ServiceType.ESNET_IRI, 
            name="iri-west",
            profile="esnet-iri-west"
        )
        session.add_service_client(west_client)
        
        # 6. Discover compute resources from each site
        print("\n--- Discovering Compute Resources ---")
        east_discovery = east_client.discover()
        west_discovery = west_client.discover()

        if not east_discovery.compute:
            print("ERROR: No compute resources found on east site.")
            return
        if not west_discovery.compute:
            print("ERROR: No compute resources found on west site.")
            return

        east_resource_id = east_discovery.compute[0].data.get("id")
        west_resource_id = west_discovery.compute[0].data.get("id")
        print(f"  East resource_id: {east_resource_id}")
        print(f"  West resource_id: {west_resource_id}")
        print(f"  East discovery: {east_discovery.summary()}")
        print(f"  West discovery: {west_discovery.summary()}")

        # 7. Create Job specs with discovered resource IDs
        common_resources = {
            "node_count": 1,
            "process_count": 1,
            "processes_per_node": 1,
            "cpu_cores_per_process": 1,
            "gpu_cores_per_process": 1,
            "exclusive_node_use": True,
            "memory": 268435456
        }
        common_attributes = {
            "directory": "/data/home/kissel",
            "duration": 600,
            "queue_name": "debug",
            "account": "interactive",
            "stdout_path": "/data/home/kissel/amscrot_stdout.log",
            "stderr_path": "/data/home/kissel/amscrot_stderr.log",
        }

        spec1 = JobSpec(
            executable=["/bin/echo", "Hello AmSC East"],
            resources=common_resources,
            attributes={"resource_id": east_resource_id, **common_attributes}
        )
        spec2 = JobSpec(
            executable=["/bin/echo", "Hello AmSC West"],
            resources=common_resources,
            attributes={"resource_id": west_resource_id, **common_attributes}
        )

        # 8. Define Jobs
        job1 = Job(
            name="job-1",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=east_client,
            job_spec=spec1
        )
        
        job2 = Job(
            name="job-2",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=west_client,
            job_spec=spec2
        )

        # Add Jobs to Session
        session.add_job(job1)
        session.add_job(job2)
        
        # 8. Plan
        print("\n--- Session Plan ---")
        try:
            session.plan()
        except PlanError as e:
            self.fail(f"Plan failed:\n" + "\n".join(f"  - {err}" for err in e.errors))
        
        # 9. Apply
        print("\n--- Session Apply ---")
        rc = session.apply()
        if rc:
            self.fail("Session apply failed")
            sys.exit(-1)

        # 10. Wait for Jobs to Complete
        print("\n--- Session Wait ---")
        try:
            results = session.wait(
                jobs=[job1, job2],
                timeout=600.0,
                interval=2.0,
                verbose=True,
            )
        except Exception as e:
            self.fail(f"Jobs did not complete within timeout: {e}")

        s1 = results["job-1"]
        s2 = results["job-2"]

        self.assertEqual(s1.state, JobState.COMPLETED, f"Job-1 failed or timed out: {s1}")
        self.assertEqual(s2.state, JobState.COMPLETED, f"Job-2 failed or timed out: {s2}")
        print(f"Jobs completed. Status: job-1={s1.state} job-2={s2.state}")

        # 12. Fetch Output Files
        print("\n--- Fetch Output Files ---")
        fetched = session.fetch_output_files(jobs=[job1, job2])
        print(f"Fetched files: {fetched}")

        for job_name, paths in fetched.items():
            stdout_path = paths.get("stdout")
            if stdout_path:
                print(f"\n--- stdout for {job_name} ---")
                try:
                    with open(stdout_path) as f:
                        print(f.read())
                except Exception as e:
                    print(f"  (could not read stdout: {e})")

        # 13. Destroy
        print("\n--- Session Destroy ---")
        #session.destroy()
        return

        # Verify cleanup with polling
        cleanup = session.wait(
            jobs=[job1, job2],
            target_states=[JobState.CANCELED, JobState.UNKNOWN],
            timeout=60.0,
            interval=1.0,
            verbose=True,
        )

        s1 = cleanup["job-1"]
        s2 = cleanup["job-2"]
        self.assertIn(s1.state, [JobState.CANCELED, JobState.UNKNOWN])
        self.assertIn(s2.state, [JobState.CANCELED, JobState.UNKNOWN])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESnet IRI networked jobs example")
    parser.add_argument("--network", action="store_true",
                        help="Include SENSE network provisioning")
    args = parser.parse_args()
    SENSENetworkedJobs().main(use_network=args.network)
