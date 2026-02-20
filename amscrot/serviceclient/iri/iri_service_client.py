from typing import Dict, List, Any
from ..serviceclient import ServiceClient
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult

class IriServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type=Constants.ServiceType.IRI, **kwargs)

    def discover(self, native: bool = True) -> DiscoveryResult:
        if native:
            return self._discover_native()
        return self._discover_normalized()

    def _discover_native(self) -> DiscoveryResult:
        """Return raw IRI resources (currently empty — IRI API not yet integrated)."""
        return DiscoveryResult()

    def _discover_normalized(self) -> DiscoveryResult:
        """Return normalized Facility objects (stub until IRI API is integrated)."""
        return DiscoveryResult()

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
