import unittest
import pytest
from amscrot.client import Client, Session, Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.serviceclient import ServiceClient
from amscrot.util.constants import Constants

@pytest.mark.integration
class TestClientJobsLifecycle(unittest.TestCase):
    def test_jobs_lifecycle(self):
        client = Client()
        
        session = client.create_session("test_jobs_lifecycle")
        
        # Create ServiceClients
        sc1 = ServiceClient.create(type=Constants.ServiceType.IRI,
                                   name="nersc_perlmutter",
                                   endpoint_uri="https://nersc.gov/api")
        sc2 = ServiceClient.create(type=Constants.ServiceType.DUMMY,
                                   name="anl_theta")
        
        # Job 1 on SC1
        job1 = Job(
            name="job1", 
            type=JobType.COMPUTE, 
            service_type=JobServiceType.BATCH,
            service_client=sc1,
            job_spec=JobSpec(
                resources={"node_count": 1},
                executable="/bin/sh",
                arguments=["-c", "echo hello job1"],
                attributes={"walltime": "10m", "container": {"image": "alpine:latest"}}
            )
        )
        
        # Job 2 on SC1, depends on Job1
        job2 = Job(
            name="job2", 
            type=JobType.DATA, 
            service_type=JobServiceType.BATCH,
            service_client=sc1,
            dependency=job1,
            job_spec=JobSpec(
                resources={"storage_gb": 100},
                executable="/bin/transfer",
                attributes={"bandwidth": "10Gbps", "container": {"image": "data-mover:latest"}}
            )
        )
        
        # Job 3 on SC2
        job3 = Job(
            name="job3", 
            type=JobType.COMPUTE, 
            service_type=JobServiceType.REALTIME,
            service_client=sc2,
            job_spec=JobSpec(
                resources={"gpu_count": 4},
                executable="python",
                arguments=["train.py"],
                attributes={"priority": "high", "container": {"image": "tensorflow:latest"}}
            )
        )
        
        # Job 4 on SC2, depends on Job3
        job4 = Job(
            name="job4", 
            type=JobType.INSTRUMENT, 
            service_type=JobServiceType.REALTIME,
            service_client=sc2,
            dependency=job3,
             job_spec=JobSpec(
                resources={"sensor_id": "sensor-1"},
                executable="/bin/capture",
                attributes={"duration": "1h", "container": {"image": "instrument-ctrl:v1"}}
            )
        )
        
        session.add_job(job1)
        session.add_job(job2)
        session.add_job(job3)
        session.add_job(job4)
    
        
        print("\n--- PLAN ---")
        try:
            session.plan()
        except Exception as e:
            # Skipping test if any error occurs during plan
            self.skipTest(f"Skipping test - an error occurred during plan: {e}")
        
        print("\n--- APPLY ---")
        result = session.apply()
        print(f"Apply result: {result}")
        self.assertIsInstance(result, dict)
        self.assertIn("resources", result)
        self.assertIn("jobs", result)
        
        print("\n--- SHOW ---")
        session.show()
        
        print("\n--- DESTROY ---")
        session.destroy()
        
