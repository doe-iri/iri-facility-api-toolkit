from abc import ABC, abstractmethod
from typing import List, Any, Dict, Optional, TYPE_CHECKING
from amscrot.util import utils

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec
    from amscrot.model.discovery import DiscoveryResult


class PlanError(Exception):
    """Raised by ServiceClient.plan() when validation errors prevent job submission.

    Attributes:
        errors:   List of error messages that caused the failure.
        warnings: List of non-fatal warning messages (may be empty).
    """

    def __init__(self, errors: List[str], warnings: List[str] = None):
        self.errors = errors
        self.warnings = warnings or []
        error_summary = "; ".join(errors)
        super().__init__(f"Plan failed with {len(errors)} error(s): {error_summary}")


class ServiceClient(ABC):
    def __init__(self, name: str, type: str, endpoint_uri: Optional[str] = None, 
                 status: str = "ACTIVE", capabilities: List[Any] = None, 
                 allocated: List[Any] = None,
                 credential: Any = None, profile: str = None, credential_file: str = None):
        self.name = name
        self.endpoint_uri = endpoint_uri
        self.type = type
        self._status = status
        self.capabilities = capabilities or []
        self.allocated = allocated or []
        self.credential = credential
        self.profile = profile
        self.credential_file = credential_file
        self.logger = utils.get_logger()

    @abstractmethod
    def discover(self, native: bool = True) -> "DiscoveryResult":
        pass

    @abstractmethod
    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        pass

    @abstractmethod
    def create(self, job_spec: "JobSpec", job_name: str = None):
        pass

    @abstractmethod
    def destroy(self, job_name: str = None):
        pass

    @abstractmethod
    def status(self, job_name: str = None) -> "JobStatus":
        pass

    @classmethod
    def create(cls, type: str, **kwargs) -> "ServiceClient":
        from amscrot.util.constants import Constants
        import importlib

        class_path = Constants.SERVICE_CLIENT_CLASSES.get(type)
        if not class_path:
             raise ValueError(f"Unknown ServiceClient type: {type}")

        try:
            module_name, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_name)
            client_class = getattr(module, class_name)
            return client_class(**kwargs)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to load ServiceClient class for type '{type}' from '{class_path}': {e}")

    def to_config(self) -> Dict:
        return {
            'service_client': [
                {
                    self.name: {
                        'type': self.type,
                        'endpoint_uri': self.endpoint_uri,
                        'status': self._status
                    }
                }
            ]
        }

    def __repr__(self):
        return f"<ServiceClient name={self.name} type={self.type} uri={self.endpoint_uri}>"