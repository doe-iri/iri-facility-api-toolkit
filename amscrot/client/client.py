
from typing import Dict, List, Any, Union
from amscrot.amscrot_manager import AmSCROTManager
from amscrot.util.constants import Constants


class Client:
    def __init__(self):
        self._provider_configs = []
        self._resource_configs = []
        self._manager = None
        
    def add_provider(self, *, label: str, type: str, **kwargs):
        """
        Add a provider configuration.
        """
        config = {
            type: [
                {label: kwargs}
            ]
        }
        self._provider_configs.append(config)
        
    def add_resource(self, *, label: str, type: str, provider: str, **kwargs):
        """
        Add a resource configuration.
        """
        # Resource needs 'provider' in kwargs usually, but here it's passed explicitly.
        # Ensure it's in the attributes.
        attrs = kwargs.copy()
        attrs['provider'] = provider
        
        config = {
            type: [
                {label: attrs}
            ]
        }
        self._resource_configs.append(config)

    def _build_config(self) -> Dict:
        return {
            'provider': self._provider_configs,
            'resource': self._resource_configs
        }

    def set_credentials(self, *, file_path: str = None, profile: str = 'default', **kwargs):
        """
        Helper to set credentials. In a real scenario, this might load from a file
        or accept direct keys and merge them into the relevant provider configs.
        For now, this is a placeholder or can be used to set environment variables.
        """
        # This implementation depends on how specific providers expect credentials.
        # Often they are part of the provider attributes.
        pass

    def _get_manager(self, session: str) -> AmSCROTManager:
        import yaml
        config_list = self._build_config()
        config_content = yaml.dump(config_list)
        return AmSCROTManager(config_content=config_content)
        
    def plan(self, *, session: str) -> Any:
        manager = self._get_manager(session)
        return manager.plan(session=session)

    def apply(self, *, session: str) -> Any:
        manager = self._get_manager(session)
        return manager.apply(session=session)

    def destroy(self, *, session: str) -> Any:
        # For destroy, we might need to load existing state which AmSCROTManager does.
        # But we still need the config to know what to destroy or how to connect.
        manager = self._get_manager(session)
        return manager.destroy(session=session)

    def show(self, *, session: str) -> Any:
        manager = self._get_manager(session)
        return manager.show(session=session)
