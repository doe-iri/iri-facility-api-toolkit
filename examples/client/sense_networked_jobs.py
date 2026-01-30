import unittest
import time
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import ServiceClient
from amscrot.util.constants import Constants

class SENSENetworkedJobs(unittest.TestCase):
    def main(self):
        # 1. Initialize Client
        client = Client()
        
        # 2. Add Dummy Provider for Network resource
        sense_provider = client.add_provider(
            label="sense",
            type="sense",
            name="sense-provider",
            profile="sense",
            credential_file="~/.amscrot/credentials.yml"
        )

        # 3. Create Session
        session = client.create_session("sense-networked-jobs")
        
        # 4. Add Resources
        # Network Resource (managed by DummyProvider)
        net1 = session.add_network(
            label="net1",
            provider=sense_provider,
            name_prefix="test-net",
            site="site1",
            profile='AmSC-WFC-L2VPN',
            # profile='4258df2c-7853-497a-9307-009d8c7b9cf3',
            count=1
        )
        
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
        
        # 6. Create Jobs
        # Job 1
        spec1 = spec2 = JobSpec(
            executable=["/bin/echo", "Hello AmSC"],
            resources={
                "node_count": 1,
                "process_count": 1,
                "processes_per_node": 1,
                "cpu_cores_per_process": 1,
                "gpu_cores_per_process": 1,
                "exclusive_node_use": True,
                "memory": 1
            },
            attributes={
                "resource_id": "fb0aafe1-c780-55c0-b635-a7121f1b0ce5",
                "directory": "/tmp",
                "duration": 60,
                "queue_name": "debug",
                "account": "interactive"
            }
        )

        job1 = Job(
            name="job-1",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=east_client,
            job_spec=spec1
        )
        
        # Job 2
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
        
        # 7. Plan
        print("\n--- Session Plan ---")
        session.plan()
        
        # 8. Apply
        print("\n--- Session Apply ---")
        rc = session.apply()
        if rc:
            self.fail("Session apply failed")
            sys.exit(-1)

        # 9. Show Status (Poll)
        print("\n--- Session Status (Poll) ---")
        for i in range(20):
            #session.show()

            # Check individual job statuses via client
            s1 = east_client.status(job_name="job-1")
            s2 = west_client.status(job_name="job-2")

            print(f"Poll {i}: Job1={s1.get('status')} Job2={s2.get('status')}")

            if (s1.get('status') in ["DONE", "ERROR", "DESTROYED"] and 
                s2.get('status') in ["DONE", "ERROR", "DESTROYED"]):
                break

            time.sleep(2)

        self.assertEqual(s1.get('status'), "DONE", f"Job failed or timed out. Details: {s1}")
        self.assertEqual(s2.get('status'), "DONE", f"Job failed or timed out. Details: {s2}")
        print(f"Jobs completed successfully. Status: {s1.get('status')} {s2.get('status')}")

        # 10. Destroy
        print("\n--- Session Destroy ---")
        #session.destroy()
        return

        # Verify cleanup with pulling
        for i in range(10):
            s1 = east_client.status(job_name="job-1")
            s2 = west_client.status(job_name="job-2")
            if (s1.get('status') in ["DESTROYED", "UNKNOWN", "KILLED"] and 
                s2.get('status') in ["DESTROYED", "UNKNOWN", "KILLED"]):
                break
            time.sleep(1)
        
        self.assertIn(s1.get('status'), ["DESTROYED", "UNKNOWN", "KILLED"])
        self.assertIn(s2.get('status'), ["DESTROYED", "UNKNOWN", "KILLED"])

if __name__ == "__main__":
    SENSENetworkedJobs().main()
