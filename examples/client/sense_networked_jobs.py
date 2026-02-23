import argparse
import unittest
import time
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import ServiceClient
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
            "directory": "/tmp",
            "duration": 60,
            "queue_name": "debug",
            "account": "interactive"
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
        session.plan()
        
        # 9. Apply
        print("\n--- Session Apply ---")
        rc = session.apply()
        if rc:
            self.fail("Session apply failed")
            sys.exit(-1)

        # 10. Show Status (Poll)
        print("\n--- Session Status (Poll) ---")
        for i in range(30):
            #session.show()

            # Check individual job statuses via client
            s1 = east_client.status(job_name="job-1")
            s2 = west_client.status(job_name="job-2")

            print(f"Poll {i}: Job1={s1.state} Job2={s2.state}")

            if (s1.state in ["DONE", "ERROR", "DESTROYED"] and 
                s2.state in ["DONE", "ERROR", "DESTROYED"]):
                break

            time.sleep(2)

        self.assertEqual(s1.state, "DONE", f"Job failed or timed out. Details: {s1}")
        self.assertEqual(s2.state, "DONE", f"Job failed or timed out. Details: {s2}")
        print(f"Jobs completed successfully. Status: {s1.state} {s2.state}")

        # 11. Destroy
        print("\n--- Session Destroy ---")
        #session.destroy()
        return

        # Verify cleanup with polling
        for i in range(30):
            s1 = east_client.status(job_name="job-1")
            s2 = west_client.status(job_name="job-2")
            if (s1.state in ["DESTROYED", "UNKNOWN", "KILLED"] and 
                s2.state in ["DESTROYED", "UNKNOWN", "KILLED"]):
                break
            time.sleep(1)
        
        self.assertIn(s1.state, ["DESTROYED", "UNKNOWN", "KILLED"])
        self.assertIn(s2.state, ["DESTROYED", "UNKNOWN", "KILLED"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESnet IRI networked jobs example")
    parser.add_argument("--network", action="store_true",
                        help="Include SENSE network provisioning")
    args = parser.parse_args()
    SENSENetworkedJobs().main(use_network=args.network)
