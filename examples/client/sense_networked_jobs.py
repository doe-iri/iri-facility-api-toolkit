import argparse
import unittest
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.serviceclient import PlanError

class SENSENetworkedJobs(unittest.TestCase):
    def _setup_and_submit(self, client, session):
        """Fresh session: discover resources, define jobs, plan, and apply."""

        # Lookup discovered IRI Service Clients
        east_client = client.get_service_client("esnet-facility-east")
        west_client = client.get_service_client("esnet-facility-west")

        if not east_client:
            self.fail("IRI client 'esnet-facility-east' not found. Check credentials or AMSC_TOKEN.")
        if not west_client:
            self.fail("IRI client 'esnet-facility-west' not found. Check credentials or AMSC_TOKEN.")

        # Discover compute resources from each site
        print("\n--- Discovering Compute Resources ---")
        east_discovery = east_client.discover()
        west_discovery = west_client.discover()

        if not east_discovery.compute:
            self.fail("No compute resources found on east site.")
        if not west_discovery.compute:
            self.fail("No compute resources found on west site.")

        east_resource_id = east_discovery.compute[0].data.get("id")
        west_resource_id = west_discovery.compute[0].data.get("id")
        print(f"  East resource_id: {east_resource_id}")
        print(f"  West resource_id: {west_resource_id}")
        print(f"  East discovery: {east_discovery.summary()}")
        print(f"  West discovery: {west_discovery.summary()}")

        # Create Job specs with discovered resource IDs
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
            "container": {
                "image": "debian:latest"
            },
            "directory": "/data/home/kissel",
            "duration": 600,
            "queue_name": "debug",
            "account": "interactive",
            "stdout_path": "/data/home/kissel/amscrot_stdout.log",
            "stderr_path": "/data/home/kissel/amscrot_stderr.log",
        }

        session.add_job(Job(
            name="job-1",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=east_client,
            job_spec=JobSpec(
                executable="/bin/echo",
                arguments=["Hello AmSC East"],
                resources=common_resources,
                attributes={"resource_id": east_resource_id, **common_attributes}
            )
        ))

        session.add_job(Job(
            name="job-2",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=west_client,
            job_spec=JobSpec(
                executable="/bin/echo",
                arguments=["Hello AmSC West"],
                resources=common_resources,
                attributes={"resource_id": west_resource_id, **common_attributes}
            )
        ))

        # Plan
        print("\n--- Session Plan ---")
        try:
            session.plan()
        except PlanError as e:
            self.fail(f"Plan failed:\n" + "\n".join(f"  - {err}" for err in e.errors))
        except Exception as e:
            self.fail(f"Plan failed with unknown error: {e}")

        # Show the session config
        print("\n--- Session Config ---")
        session.show()

        # Apply
        print("\n--- Session Apply ---")
        try:
            session.apply()
        except Exception as e:
            self.fail(f"Session apply failed: {e}")

        print("Jobs Created Successfully:")
        for job in session.jobs:
            print(f"  {job.name} API ID: {job.id}")

    def main(self, use_network=False):
        client = Client(discover_endpoints=True)

        # Show discovered service clients
        print("\n--- Discovered Service Clients ---")
        for sc in client.get_service_client():
            print(f"  {sc.name} ({sc.type}) -> {getattr(sc, 'endpoint_uri', 'N/A')}")

        session = client.create_session("sense-networked-jobs")

        # Infrastructure resources are always added to the session
        if use_network:
            print("\n--- Adding SENSE Network ---")
            sense_provider = client.add_provider(
                label="sense",
                type="sense",
                name="sense-provider",
                profile="sense",
                credential_file="~/.amscrot/credentials.yml"
            )
            session.add_network(
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

        if session.jobs:
            print(f"\n--- Restored {len(session.jobs)} job(s) from session state ---")
            for job in session.jobs:
                print(f"  {job.name}: id={job.id} status={job.status}")
        else:
            self._setup_and_submit(client, session)

        # Wait for Jobs to Complete
        print("\n--- Session Wait ---")
        try:
            results = session.wait(
                timeout=600.0,
                interval=2.0,
                verbose=True,
            )
        except Exception as e:
            self.fail(f"Jobs did not complete within timeout: {e}")

        for job_name, status in results.items():
            self.assertEqual(status.state, JobState.COMPLETED, f"{job_name} failed or timed out: {status}")
        print(f"All jobs completed: {', '.join(f'{n}={s.state}' for n, s in results.items())}")

        # Fetch Output Files
        print("\n--- Fetch Output Files ---")
        fetched = session.fetch_output_files()
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

        # Destroy
        print("\n--- Session Destroy ---")
        session.destroy()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESnet IRI networked jobs example")
    parser.add_argument("--network", action="store_true",
                        help="Include SENSE network provisioning")
    args = parser.parse_args()
    SENSENetworkedJobs().main(use_network=args.network)
