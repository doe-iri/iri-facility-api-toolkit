
from typing import Dict, List, Any, Union
from amscrot.amscrot_manager import AmSCROTManager
from amscrot.util.constants import Constants


class ProviderCredential:
    def __init__(self, **kwargs):
        self._attributes = kwargs

    def __getattr__(self, item):
        return self._attributes.get(item)

    def __setattr__(self, key, value):
        if key == "_attributes":
            super().__setattr__(key, value)
        else:
            self._attributes[key] = value

    def to_dict(self) -> Dict:
        return self._attributes.copy()

    def update(self, **kwargs):
        self._attributes.update(kwargs)


class Client:
    def __init__(self):
        self._provider_configs = []
        self._resource_configs = []
        self._manager = None
        self._credentials = {}

    def load_credentials(self, *, file_path: str = None):
        """
        Load credentials from a YAML file.
        If file_path is not provided, defaults to ~/.amscrot/credentials.yml.
        """
        from amscrot.util.utils import load_yaml_from_file
        import os

        if file_path is None:
            file_path = "~/.amscrot/credentials.yml"
            path_expanded = os.path.expanduser(file_path)
            if not os.path.exists(path_expanded):
                self._credentials = {}
                return

        creds = load_yaml_from_file(file_path) or {}
        # Convert dicts to ProviderCredential objects
        self._credentials = {k: ProviderCredential(**v) for k, v in creds.items()}

    def add_credential(self, *, profile: str, **kwargs):
        """
        Add or update a credential profile programmatically.
        """
        if profile in self._credentials:
            self._credentials[profile].update(**kwargs)
        else:
            self._credentials[profile] = ProviderCredential(**kwargs)

    def get_credential(self, profile: str) -> "ProviderCredential":
        """
        Get a specific credential object.
        """
        return self._credentials.get(profile)

    def list_credentials(self) -> List[str]:
        """
        List available credential profiles.
        """
        return list(self._credentials.keys())

    def add_provider(self, *, label: str, type: str, profile: str = None, **kwargs):
        """
        Add a provider configuration.
        """
        attributes = {}

        if profile:
            if profile not in self._credentials:
                raise ValueError(f"Profile '{profile}' not found in loaded credentials.")
            attributes.update(self._credentials[profile].to_dict())

        attributes.update(kwargs)

        config = {
            type: [
                {label: attributes}
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
