
import os
import re
from typing import Dict, List, Any, Optional, Union, TYPE_CHECKING
if TYPE_CHECKING:
    from amscrot.serviceclient import ServiceClient
from amscrot.amscrot_manager import AmSCROTManager
from amscrot.util.constants import Constants
from amscrot.util import utils
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
    def __init__(self, *, create_service_clients: bool = False,
                 discover_endpoints: bool = False,
                 iro_endpoint: str = None,
                 credential_file: str = None):
        self._providers: List[Provider] = []
        self._sessions: List[Session] = []
        self._service_clients: Dict[str, "ServiceClient"] = {}
        self._credentials = {}
        self._logger = utils.get_logger()
        self._iro_endpoint = iro_endpoint or Constants.DEFAULT_IRO_ENDPOINT

        if create_service_clients or discover_endpoints:
            self.load_credentials(file_path=credential_file)

        if create_service_clients:
            self._create_service_clients_from_credentials()

        if discover_endpoints:
            self._discover_and_create_iri_clients()

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

        # Forward to any existing sessions so providers can be added after create_session
        for session in self._sessions:
            session.add_provider(provider)

        return provider

    def add_service_client(self, service_client: "ServiceClient"):
        self._service_clients[service_client.name] = service_client
        return service_client

    def get_service_client(self, name: str = None) -> Union[Optional["ServiceClient"], List["ServiceClient"]]:
        """Retrieve a service client by name, or list all if no name given."""
        if name is None:
            return list(self._service_clients.values())
        return self._service_clients.get(name)

    def _create_service_clients_from_credentials(self):
        """Auto-create ServiceClient instances from credential entries that
        contain a ``client_type`` attribute mapping to a valid
        ``Constants.ServiceType`` name (e.g. ``ESNET_IRI``, ``NERSC_IRI``).
        """
        from amscrot.serviceclient import ServiceClient as SC

        for entry_name, cred in self._credentials.items():
            client_type_attr = getattr(cred, 'client_type', None)
            if not client_type_attr:
                self._logger.warning(
                    f"Missing 'client_type' in credential entry '{entry_name}', skipping."
                )
                continue

            # Resolve e.g. "ESNET_IRI" -> Constants.ServiceType.ESNET_IRI -> "esnet-iri"
            service_type = getattr(Constants.ServiceType, client_type_attr, None)
            if service_type is None:
                self._logger.warning(
                    f"Unknown client_type '{client_type_attr}' "
                    f"in credential entry '{entry_name}', skipping."
                )
                continue

            try:
                sc = SC.create(
                    type=service_type,
                    name=entry_name,
                    profile=entry_name,
                    credential=cred,
                )
                self._service_clients[entry_name] = sc
                self._logger.debug(
                    f"Created service client '{entry_name}' "
                    f"(type={service_type})"
                )
            except Exception as e:
                self._logger.warning(
                    f"Failed to create service client '{entry_name}' "
                    f"(type={service_type}): {e}"
                )

    # -- Endpoint discovery ---------------------------------------------------

    @staticmethod
    def _normalize_endpoint(url: str) -> str:
        """Strip trailing ``/api`` and slashes so endpoints can be compared."""
        url = url.rstrip('/')
        if url.endswith('/api'):
            url = url[:-4]
        return url.rstrip('/')

    @staticmethod
    def _slugify(name: str) -> str:
        """Turn a facility name into a kebab-case identifier."""
        slug = name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        return slug.strip('-')

    def _discover_and_create_iri_clients(self):
        """Query the IRO facility discovery endpoint and auto-create
        ``IriServiceClient`` instances for each discovered facility.

        Token resolution order per facility:
          1. If a credential profile matches (``client_type: AMSC_IRI`` and
             ``api_endpoint`` match), use that profile (full override).
          2. Else use the ``AMSC_TOKEN`` environment variable.
          3. If neither is available, skip with a warning.
        """
        import requests as _requests
        from amscrot.serviceclient import ServiceClient as SC

        url = f"{self._iro_endpoint.rstrip('/')}/amsc-iro/resource/facility"
        self._logger.debug(f"Discovering IRI facilities from {url}")

        try:
            resp = _requests.get(url, timeout=10, verify=False)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self._logger.warning(f"Failed to discover IRI facilities: {e}")
            return

        facilities = data.get('facilities', [])
        if not facilities:
            self._logger.info("No IRI facilities returned from discovery.")
            return

        # Build index of AMSC_IRI credential profiles keyed by normalized api_endpoint
        cred_by_endpoint: Dict[str, tuple] = {}  # norm_url -> (profile_name, cred)
        for profile_name, cred in self._credentials.items():
            ctype = getattr(cred, 'client_type', None)
            ep = getattr(cred, 'api_endpoint', None)
            if ctype == 'AMSC_IRI' and ep:
                cred_by_endpoint[self._normalize_endpoint(ep)] = (profile_name, cred)

        env_token = os.environ.get('AMSC_TOKEN')

        for fac in facilities:
            fac_name = fac.get('facility_name', 'unknown')
            fac_endpoint = fac.get('api_endpoint', '')
            norm_ep = self._normalize_endpoint(fac_endpoint)
            slug = self._slugify(fac_name)

            # Skip if already registered
            if slug in self._service_clients:
                self._logger.debug(f"Service client '{slug}' already exists, skipping.")
                continue

            # 1. Check for matching credential profile
            match = cred_by_endpoint.get(norm_ep)
            if match:
                profile_name, cred = match
                api_key = getattr(cred, 'api_key', None)
                endpoint = getattr(cred, 'api_endpoint', fac_endpoint)
                self._logger.info(
                    f"Matched facility '{fac_name}' to credential profile '{profile_name}'"
                )
                try:
                    sc = SC.create(
                        type=Constants.ServiceType.IRI,
                        name=slug,
                        profile=profile_name,
                        credential=cred,
                    )
                    self._service_clients[slug] = sc
                    self._logger.debug(f"Created IRI client '{slug}' from profile '{profile_name}'")
                except Exception as e:
                    self._logger.warning(
                        f"Failed to create IRI client '{slug}' from profile '{profile_name}': {e}"
                    )
                continue

            # 2. Fall back to AMSC_TOKEN env var
            if env_token:
                try:
                    sc = SC.create(
                        type=Constants.ServiceType.IRI,
                        name=slug,
                        endpoint_uri=norm_ep,
                        credential={'api_key': env_token, 'api_endpoint': norm_ep},
                    )
                    self._service_clients[slug] = sc
                    self._logger.info(
                        f"Created IRI client '{slug}' for '{fac_name}' using AMSC_TOKEN"
                    )
                except Exception as e:
                    self._logger.warning(
                        f"Failed to create IRI client '{slug}' with AMSC_TOKEN: {e}"
                    )
                continue

            # 3. No token available
            self._logger.warning(
                f"Skipping facility '{fac_name}' — no matching credential profile "
                f"and AMSC_TOKEN not set."
            )

    def create_session(self, name: str) -> Session:
        session = Session(name=name, providers=list(self._providers), service_clients=list(self._service_clients.values()))
        self._sessions.append(session)

        # Hydrate service clients and jobs from disk if available
        from amscrot.util import state as sutil
        from amscrot.client.job import Job, JobType, JobServiceType, JobState, JobSpec
        from amscrot.serviceclient import ServiceClient

        cached_scs, cached_jobs = sutil.load_jobs(name)

        if cached_scs:
            self._logger.info(f"Restoring {len(cached_scs)} service client(s) from session '{name}' state file.")
            for sc_dict in cached_scs:
                # Top level dictionary keys are names
                for sc_name, sc_cfg in sc_dict.items():
                    try:
                        sc = ServiceClient.create(
                            type=sc_cfg.get('type'),
                            name=sc_name,
                            endpoint_uri=sc_cfg.get('endpoint_uri'),
                            status=sc_cfg.get('status', 'ACTIVE'),
                            profile=sc_cfg.get('profile')
                        )
                        # Prevents duplicates if the client is already attached
                        if sc_name not in session._service_clients:
                            session.add_service_client(sc)
                    except Exception as e:
                        self._logger.warning(f"Skipping hydration of cached ServiceClient '{sc_name}': {e}")

        if cached_jobs:
            self._logger.info(f"Restoring {len(cached_jobs)} job(s) from session '{name}' state file.")
            for j_dict in cached_jobs:
                try:
                    sc_name = j_dict.get('service_client')
                    sc = session.get_service_client(sc_name) if sc_name else None
                    if sc is None and sc_name:
                        sc = self.get_service_client(sc_name)
                    
                    job_spec_dict = j_dict.get('spec', {})
                    spec = None
                    if job_spec_dict:
                        spec = JobSpec(
                            resources=job_spec_dict.get('resources'),
                            image=job_spec_dict.get('image'),
                            executable=job_spec_dict.get('executable'),
                            arguments=job_spec_dict.get('arguments'),
                            attributes=job_spec_dict.get('attributes')
                        )
                    
                    job = Job(
                        name=j_dict.get('name'),
                        type=JobType(j_dict.get('type', 'COMPUTE')),
                        service_type=JobServiceType(j_dict.get('service_type', 'BATCH')),
                        service_client=sc,
                        job_spec=spec
                    )
                    job.id = j_dict.get('id')
                    job.resource_id = j_dict.get('resource_id')
                    try:
                        job.status = JobState(j_dict.get('status', 'INIT'))
                    except ValueError:
                        job.status = JobState.INIT
                    session.add_job(job)
                except Exception as e:
                    self._logger.warning(f"Skipping hydration of cached job '{j_dict.get('name')}': {e}")

        return session
