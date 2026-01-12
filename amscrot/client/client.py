
from typing import Dict, List, Any, Union
from amscrot.amscrot_manager import AmSCROTManager
from amscrot.util.constants import Constants
from .models import Session, Provider

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
        self._providers: List[Provider] = []
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
                # Don't overwrite existing credentials if default file is missing
                if not self._credentials:
                    self._credentials = {}
                return

        creds = load_yaml_from_file(file_path) or {}
        # Merge dicts to ProviderCredential objects
        for k, v in creds.items():
            if k in self._credentials:
                self._credentials[k].update(**v)
            else:
                self._credentials[k] = ProviderCredential(**v)

    def add_credential(self, *, profile: str, **kwargs):
        """
        Add or update a credential profile programmatically.
        """
        if profile in self._credentials:
            self._credentials[profile].update(**kwargs)
        else:
            self._credentials[profile] = ProviderCredential(**kwargs)

    def update_credential(self, *, profile: str, **kwargs):
        """
        Update an existing credential profile.
        """
        if profile not in self._credentials:
            raise ValueError(f"Profile '{profile}' not found.")
        self._credentials[profile].update(**kwargs)

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

    def add_provider(self, *, label: str, type: str, profile: str = None, **kwargs) -> Provider:
        """
        Add a provider configuration.
        """
        # Load credentials if a file is specified
        if "credential_file" in kwargs:
            self.load_credentials(file_path=kwargs["credential_file"])

        attributes = {}

        if profile:
            if profile not in self._credentials:
                raise ValueError(f"Profile '{profile}' not found in loaded credentials.")
            attributes.update(self._credentials[profile].to_dict())
            attributes['profile'] = profile

        attributes.update(kwargs)

        provider = Provider(label, type, **attributes)
        self._providers.append(provider)
        return provider

    def create_session(self, name: str) -> Session:
        return Session(client=self, name=name)
