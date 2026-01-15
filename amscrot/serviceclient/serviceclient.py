from abc import ABC, abstractmethod
from typing import List, Any

class ServiceClient(ABC):
    def __init__(self, name: str, endpoint_uri: str, type: str, status: str = "ACTIVE", capabilities: List[Any] = None, allocated: List[Any] = None):
        self.name = name
        self.endpoint_uri = endpoint_uri
        self.type = type
        self.status = status
        self.capabilities = capabilities or []
        self.allocated = allocated or []

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def status(self) -> str:
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

    def __repr__(self):
        return f"<ServiceClient name={self.name} type={self.type} uri={self.endpoint_uri}>"