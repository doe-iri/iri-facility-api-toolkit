from typing import Dict, List, Any
from ..serviceclient import ServiceClient
from ...util.constants import Constants

class IriServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type=Constants.ServiceType.IRI, **kwargs)

    def discover(self) -> List[Any]:
        return []

    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        self.logger.info(f"[{self.name}] Planning IRI service for '{job_name or self.name}' with spec: {job_spec}")
        return {"status": "PLANNED", "errors": [], "warnings": []}

    def create(self, job_spec, job_name: str = None):
        self.logger.info(f"[{self.name}] Creating IRI service for '{job_name or self.name}' with spec: {job_spec}")
        self._status = "RUNNING"

    def destroy(self, job_name: str = None):
        self.logger.info(f"[{self.name}] Destroying IRI service for '{job_name or self.name}'...")
        self._status = "STOPPED"

    def status(self, job_name: str = None) -> Dict:
        return {"status": self._status}
