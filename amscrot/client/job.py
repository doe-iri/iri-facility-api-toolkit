from enum import Enum
from typing import List, Dict, Any, Optional, Union, TYPE_CHECKING
from amscrot.serviceclient import ServiceClient

if TYPE_CHECKING:
    from amsc_iri.models.job_spec_input import JobSpecInput as IriJobSpec

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

class JobState(str, Enum):
    # amscrot lifecycle states (not from esnet-iri)
    INIT      = "INIT"       # Job object created, not yet planned
    PLANNED   = "PLANNED"    # Job validated/planned successfully
    PENDING   = "PENDING"    # Submitted, awaiting provider scheduling
    UNKNOWN   = "UNKNOWN"    # State cannot be determined

    # States aligned with esnet-iri JobState
    NEW       = "NEW"        # Job created at the provider
    QUEUED    = "QUEUED"     # Job queued at the provider
    ACTIVE    = "ACTIVE"     # Job is actively running
    COMPLETED = "COMPLETED"  # Job completed successfully
    FAILED    = "FAILED"     # Job failed
    CANCELED  = "CANCELED"   # Job was canceled/destroyed

class JobStatus:
    """Result of a ServiceClient.status() call.

    Wraps a normalized status with the serialized provider-specific response.
    """
    def __init__(
        self,
        state: str = "UNKNOWN",
        message: Optional[str] = None,
        exit_code: Optional[int] = None,
        job_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        provider_status: Optional[Dict[str, Any]] = None,
    ):
        self.state = state
        self.message = message
        self.exit_code = exit_code
        self.job_id = job_id
        self.resource_id = resource_id
        self.provider_status = provider_status

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"state": self.state}
        if self.message is not None:
            d["message"] = self.message
        if self.exit_code is not None:
            d["exit_code"] = self.exit_code
        if self.job_id is not None:
            d["job_id"] = self.job_id
        if self.resource_id is not None:
            d["resource_id"] = self.resource_id
        if self.provider_status is not None:
            d["provider_status"] = self.provider_status
        return d

    def __repr__(self):
        parts = [f"state={self.state!r}"]
        if self.message:
            parts.append(f"message={self.message!r}")
        if self.exit_code is not None:
            parts.append(f"exit_code={self.exit_code}")
        if self.job_id:
            parts.append(f"job_id={self.job_id!r}")
        return f"<JobStatus {' '.join(parts)}>"

class JobSpec:
    def __init__(self, resources: Dict = None, executable: str = None,
                 arguments: List[str] = None, attributes: Dict = None):
        self.resources = resources or {}
        self.executable = executable or ""
        self.arguments = arguments or []
        self.attributes = attributes or {}

    def to_dict(self) -> Dict:
        return {
            'resources': self.resources,
            'executable': self.executable,
            'arguments': self.arguments,
            'attributes': self.attributes
        }

class Job:
    def __init__(
        self,
        name: str,
        type: Union[JobType, str],
        service_type: Union[JobServiceType, str],
        service_client: Optional[ServiceClient] = None,
        job_spec: Optional[Union[JobSpec, "IriJobSpec"]] = None,
        dependency: Optional['Job'] = None,
        intent: Optional[str] = None,
        network: Optional[Any] = None,
        preferences: Dict = None,
        inputs: Dict = None,
        outputs: Dict = None
    ):
        self.name = name
        self.type = JobType(type) if isinstance(type, str) else type
        self.service_type = JobServiceType(service_type) if isinstance(service_type, str) else service_type
        
        self.id = None
        self.resource_id = None
        self.status = JobState.INIT
        self.service_client = service_client
        self.job_spec = job_spec or JobSpec()
        self.dependency = dependency
        self.intent = intent
        self.network = network
        self.preferences = preferences or {}
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.local_files: Dict[str, str] = {}  # populated by fetch_output_files

    def to_config(self) -> Dict:
        config = {
            'name': self.name,
            'id': self.id,
            'resource_id': self.resource_id,
            'type': self.type.value if hasattr(self.type, 'value') else self.type,
            'service_type': self.service_type.value if hasattr(self.service_type, 'value') else self.service_type,
            'status': self.status.value if hasattr(self.status, 'value') else self.status,
            'intent': self.intent,
            'network': self.network.model_dump(exclude_none=True) if hasattr(self.network, 'model_dump') else self.network,
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

    def set_status(self, status: Union[JobState, str]):
        self.status = JobState(status) if isinstance(status, str) else status

    def __repr__(self):
        return f"<Job name={self.name} type={self.type} status={self.status}>"
