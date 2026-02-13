from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from amscrot.controller.metadata_manager import MetadataManager
from amscrot.util import utils

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec


class ServiceClient(ABC):
    def __init__(
        self,
        name: str,
        type: str,
        endpoint_uri: Optional[str] = None,
        status: str = "ACTIVE",
        capabilities: List[Any] = None,
        allocated: List[Any] = None,
        credential: Any = None,
        profile: str = None,
        credential_file: str = None,
    ):
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

    #################################################
    # Global Metadata Discovery (local/remote metadata records)
    #################################################

    @classmethod
    def discover(cls, **kwargs) -> Dict:
        """
        Discover (retrieve) global metadata using MetadataManager.

        Keyword Args:
            metadata_preference: 'local', 'remote', 'local|remote', 'remote|local'. Defaults to 'local'.
            metadata_id: Local cache file stem. Defaults to 'gmetadata'.
            config_metadata: Optional config forwarded to MetadataManager (e.g., remote_domain/remote_name).

        Returns:
            Metadata dict if found; otherwise an empty dict.
        """
        metadata_preference = str(kwargs.get("metadata_preference", "local"))
        metadata_id = str(kwargs.get("metadata_id", "gmetadata"))
        config_metadata = kwargs.get("config_metadata")

        metadata = MetadataManager.fetch(
            metadata_preference=metadata_preference,
            metadata_id=metadata_id,
            config_metadata=config_metadata,
        )

        return metadata or {}

    #################################################
    # ServiceClient API (subclasses implement these)
    #################################################

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
    def status(self, job_name: str = None) -> Dict:
        pass

    @classmethod
    def create(cls, type: str, **kwargs) -> "ServiceClient":
        from amscrot.util.constants import Constants
        import importlib

        class_path = Constants.SERVICE_CLIENT_CLASSES.get(type)
        if not class_path:
            raise ValueError(f"Unknown ServiceClient type: {type}")

        try:
            module_name, class_name = class_path.rsplit(".", 1)
            module = importlib.import_module(module_name)
            client_class = getattr(module, class_name)
            return client_class(**kwargs)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to load ServiceClient class for type '{type}' from '{class_path}': {e}")

    def to_config(self) -> Dict:
        return {
            "service_client": [
                {
                    self.name: {
                        "type": self.type,
                        "endpoint_uri": self.endpoint_uri,
                        "status": self._status,
                    }
                }
            ]
        }

    def __repr__(self):
        return f"<ServiceClient name={self.name} type={self.type} uri={self.endpoint_uri}>"


def _main() -> int:
    """
    Module entrypoint for:
        python -m amscrot.serviceclient.serviceclient

    Defaults are:
        metadata_preference="local"
        metadata_id="gmetadata"
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="ServiceClient metadata discovery helper")
    parser.add_argument("--metadata-preference", default="local", help="local | remote | local|remote | remote|local")
    parser.add_argument("--metadata-id", default="gmetadata", help="Local metadata cache file stem")
    args = parser.parse_args()

    metadata = ServiceClient.discover(metadata_preference=args.metadata_preference, metadata_id=args.metadata_id)
    print(json.dumps(metadata, indent=2, default=str))
    return 0



if __name__ == "__main__":
    raise SystemExit(_main())


# Test:
# (amsc-isro-toolkit) PS C:\Users\4ua\Projects\amsc-isro-toolkit> python -m amscrot.serviceclient.serviceclient --metadata-preference local --metadata-id service_client_metadata
# Test:
#(amsc-isro-toolkit) PS C:\Users\4ua\Projects\amsc-isro-toolkit> python -m amscrot.serviceclient.serviceclient --metadata-preference remote --metadata-id anees-test
