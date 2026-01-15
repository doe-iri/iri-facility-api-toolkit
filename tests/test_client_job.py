
import unittest
from amscrot.client import Job, JobSpec, JobType, JobServiceType, JobStatus
from amscrot.serviceclient import ServiceClient

class TestClientJob(unittest.TestCase):
    def test_service_client_creation(self):
        sc = ServiceClient.create(type="iri", name="sc1", endpoint_uri="http://localhost:8000")
        self.assertEqual(sc.name, "sc1")
        self.assertEqual(sc.endpoint_uri, "http://localhost:8000")
        self.assertEqual(sc.status, "ACTIVE")
        self.assertEqual(sc.capabilities, [])
        
    def test_job_creation(self):
        sc = ServiceClient.create(type="iri", name="sc1", endpoint_uri="http://localhost:8000")
        
        spec = JobSpec(
            resources={"node_count": 10},
            image="my-image",
            executable=["run.sh"],
            attributes={"duration": 60}
        )
        
        job = Job(
            name="job1",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=sc,
            job_spec=spec,
            preferences={"site": "nersc"}
        )
        
        self.assertEqual(job.name, "job1")
        self.assertEqual(job.type, JobType.COMPUTE)
        self.assertEqual(job.service_type, JobServiceType.BATCH)
        self.assertEqual(job.status, JobStatus.INIT)
        self.assertEqual(job.service_client, sc)
        self.assertEqual(job.job_spec, spec)
        self.assertEqual(job.preferences['site'], 'nersc')
        
    def test_job_enum_conversion(self):
        # Test passing strings instead of Enums
        job = Job(
            name="job_str",
            type="DATA",
            service_type="REALTIME"
        )
        self.assertEqual(job.type, JobType.DATA)
        self.assertEqual(job.service_type, JobServiceType.REALTIME)
        
    def test_job_dependency(self):
        job1 = Job(name="j1", type="COMPUTE", service_type="BATCH")
        job2 = Job(name="j2", type="DATA", service_type="REALTIME", dependency=job1)
        
        self.assertEqual(job2.dependency, job1)

    def test_job_spec_defaults(self):
        spec = JobSpec()
        self.assertEqual(spec.resources, {})
        self.assertEqual(spec.executable, [])

    def test_add_job_to_session(self):
        from amscrot.client import Client
        
        client = Client()
        session = client.create_session("job_session")
        
        job = Job(name="j1", type="COMPUTE", service_type="BATCH")
        session.add_job(job)
        
        config = session._build_config()
        self.assertEqual(len(config['job']), 1)
        
        # config['job'] is a list of dicts returned by Job.to_config()
        # e.g. [{'j1': ...}]
        job_config = config['job'][0]['j1']
        self.assertEqual(job_config['name'], "j1")
        self.assertEqual(job_config['type'], "COMPUTE")
