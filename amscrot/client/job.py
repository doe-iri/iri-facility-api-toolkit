from enum import Enum
from typing import List, Dict, Any, Optional, Union
from amscrot.serviceclient import ServiceClient

class JobServiceType(str, Enum):
    REALTIME = "REALTIME"
    BATCH = "BATCH"
    INTERACTIVE = "INTERACTIVE"

class JobType(str, Enum):
    COMPUTE = "COMPUTE"
    NETWORK = "NETWORK"
    STORAGE = "STORAGE"
    DATA = "DATA"
    INSTRUMENT = "INSTRUMENT"

class JobStatus(str, Enum):
    INIT = "INIT"
    PLAN = "PLAN"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    ERROR = "ERROR"
    DONE = "DONE"

class JobSpec:
    def __init__(self, resources: Dict = None, image: str = None, executable: List[str] = None, attributes: Dict = None):
        self.resources = resources or {}
        self.image = image
        self.executable = executable or []
        self.attributes = attributes or {}

    def to_dict(self) -> Dict:
        return {
            'resources': self.resources,
            'image': self.image,
            'executable': self.executable,
            'attributes': self.attributes
        }

class Job:
    def __init__(
        self,
        name: str,
        type: Union[JobType, str],
        service_type: Union[JobServiceType, str],
        service_client: Optional[ServiceClient] = None,
        job_spec: Optional[JobSpec] = None,
        dependency: Optional['Job'] = None,
        preferences: Dict = None,
        inputs: Dict = None,
        outputs: Dict = None
    ):
        self.name = name
        # Allow string or Enum, convert to Enum if possible or keep as is? 
        # Plan implies strict typing where specified but flexibility is often good.
        # Let's enforce Enum for known types but cast from string if passed.
        self.type = JobType(type) if isinstance(type, str) else type
        self.service_type = JobServiceType(service_type) if isinstance(service_type, str) else service_type
        
        self.status = JobStatus.INIT
        self.service_client = service_client
        self.job_spec = job_spec or JobSpec()
        self.dependency = dependency
        self.preferences = preferences or {}
        self.inputs = inputs or {}
        self.outputs = outputs or {}

    def to_config(self) -> Dict:
        config = {
            'name': self.name,
            'type': self.type.value if hasattr(self.type, 'value') else self.type,
            'service_type': self.service_type.value if hasattr(self.service_type, 'value') else self.service_type,
            'status': self.status.value if hasattr(self.status, 'value') else self.status,
            'spec': self.job_spec.to_dict(),
            'preferences': self.preferences,
            'inputs': self.inputs,
            'outputs': self.outputs
        }
        if self.service_client:
            config['service_client'] = self.service_client.name # Reference by name
        if self.dependency:
            config['dependency'] = self.dependency.name # Reference by name
            
        return {self.name: config}

    def set_status(self, status: Union[JobStatus, str]):
        self.status = JobStatus(status) if isinstance(status, str) else status

    def __repr__(self):
        return f"<Job name={self.name} type={self.type} status={self.status}>"
