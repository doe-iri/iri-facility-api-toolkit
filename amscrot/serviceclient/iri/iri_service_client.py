from typing import Dict
from ..serviceclient import ServiceClient

class IriServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type="iri", **kwargs)

    def plan(self, job_spec: "JobSpec") -> Dict:
        print(f"[{self.name}] Planning IRI service with spec: {job_spec}")
        return {"status": "PLANNED", "errors": [], "warnings": []}

    def create(self, job_spec):
        print(f"[{self.name}] Creating IRI service with spec: {job_spec}")
        self._status = "RUNNING"

    def destroy(self):
        print(f"[{self.name}] Destroying IRI service...")
        self._status = "STOPPED"

    def status(self) -> Dict:
        return {"status": self._status}
