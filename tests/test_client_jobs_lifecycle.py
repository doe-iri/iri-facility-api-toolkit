
import unittest
import pytest
from amscrot.client import Client, Session, Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import ServiceClient

class TestClientJobsLifecycle(unittest.TestCase):
    def test_jobs_lifecycle(self):
        client = Client()
        # Add a dummy provider to satisfy Parser validation
        client.add_provider(label="dummy_prov", type="dummy", config={})
        
        session = client.create_session("test_jobs_lifecycle")
        
        # Create ServiceClients
        sc1 = ServiceClient.create(type="iri",
                                   name="nersc_perlmutter",
                                   endpoint_uri="https://nersc.gov/api")
        sc2 = ServiceClient.create(type="kube",
                                   name="anl_theta",
                                   endpoint_uri="https://anl.gov/api")
        
        # Job 1 on SC1
        job1 = Job(
            name="job1", 
            type=JobType.COMPUTE, 
            service_type=JobServiceType.BATCH,
            service_client=sc1,
            job_spec=JobSpec(
                resources={"node_count": 1},
                image="alpine:latest",
                executable=["/bin/sh", "-c", "echo hello job1"],
                attributes={"walltime": "10m"}
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
                image="data-mover:latest",
                executable=["/bin/transfer"],
                attributes={"bandwidth": "10Gbps"}
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
                image="tensorflow:latest",
                executable=["python", "train.py"],
                attributes={"priority": "high"}
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
                image="instrument-ctrl:v1",
                executable=["/bin/capture"],
                attributes={"duration": "1h"}
            )
        )
        
        session.add_job(job1)
        session.add_job(job2)
        session.add_job(job3)
        session.add_job(job4)
    
        
        print("\n--- PLAN ---")
        session.plan()
        
        print("\n--- APPLY ---")
        session.apply()
        
        print("\n--- SHOW ---")
        session.show()
        
        print("\n--- DESTROY ---")
        session.destroy()
        
