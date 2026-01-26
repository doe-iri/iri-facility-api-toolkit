from typing import Dict
from ..serviceclient import ServiceClient

class IriServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type="iri", **kwargs)

    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        print(f"[{self.name}] Planning IRI service for '{job_name or self.name}' with spec: {job_spec}")
        return {"status": "PLANNED", "errors": [], "warnings": []}

    def create(self, job_spec, job_name: str = None):
        print(f"[{self.name}] Creating IRI service for '{job_name or self.name}' with spec: {job_spec}")
        self._status = "RUNNING"

    def destroy(self, job_name: str = None):
        print(f"[{self.name}] Destroying IRI service for '{job_name or self.name}'...")
        self._status = "STOPPED"

    def status(self, job_name: str = None) -> Dict:
        return {"status": self._status}
