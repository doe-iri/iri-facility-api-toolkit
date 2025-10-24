from abc import ABC, abstractmethod
from .provider import Provider


class ResourceListener(ABC):
    @abstractmethod
    def on_added(self, *, source, provider: Provider, resource: object):
        pass

    @abstractmethod
    def on_created(self, *, source, provider: Provider, resource: object):
        pass

    @abstractmethod
    def on_deleted(self, *, source, provider: Provider, resource: object):
        pass
