from typing import Dict, List, Any
from ..serviceclient import ServiceClient
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult, DiscoveredResource
from ...client.job import JobStatus, JobState


class DummyServiceClient(ServiceClient):
    """In-memory ServiceClient for lifecycle testing.

    Simulates state transitions without any real backend:
      plan()   -> PLANNED
      create() -> transitions internal state ACTIVE
      status() -> returns current internal state as JobStatus
      destroy()-> transitions internal state to CANCELED
    """

    def __init__(self, **kwargs):
        super().__init__(type=Constants.ServiceType.DUMMY, **kwargs)
        # Track per-job state: {job_name: JobState}
        self._job_states: Dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Discovery                                                             #
    # ------------------------------------------------------------------ #

    def discover(self, native: bool = True) -> DiscoveryResult:
        resource = DiscoveredResource(
            type="compute",
            data={"id": "dummy-resource-1", "name": "Dummy Compute"},
            name="dummy-compute",
        )
        return DiscoveryResult(items=[resource])

    # ------------------------------------------------------------------ #
    # Job lifecycle                                                         #
    # ------------------------------------------------------------------ #

    def plan(self, job_spec, job_name: str = None) -> Dict:
        name = job_name or self.name
        self.logger.info(f"[{self.name}] [DUMMY] Planning '{name}'")
        return {"status": JobState.PLANNED.value, "errors": [], "warnings": []}

    def create(self, job_spec, job_name: str = None):
        name = job_name or self.name
        self.logger.info(f"[{self.name}] [DUMMY] Creating '{name}'")
        self._job_states[name] = JobState.ACTIVE.value

    def destroy(self, job_name: str = None):
        name = job_name or self.name
        self.logger.info(f"[{self.name}] [DUMMY] Destroying '{name}'")
        self._job_states[name] = JobState.CANCELED.value

    def status(self, job_name: str = None) -> JobStatus:
        name = job_name or self.name
        state = self._job_states.get(name, self._status)
        return JobStatus(state=state)

    def complete(self, job_name: str = None):
        """Test helper: manually advance a job to COMPLETED."""
        name = job_name or self.name
        self._job_states[name] = JobState.COMPLETED.value

    def fail(self, job_name: str = None):
        """Test helper: manually advance a job to FAILED."""
        name = job_name or self.name
        self._job_states[name] = JobState.FAILED.value
