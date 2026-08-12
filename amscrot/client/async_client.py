"""Async counterpart of :class:`Client` for use with ``asyncio``.

Only methods that perform I/O are ``async def``; pure in-memory helpers
remain synchronous to avoid unnecessary overhead and the anti-pattern of
``await``-ing CPU-only operations.

Usage::

    from amscrot.client import AsyncClient

    async def main():
        async with AsyncClient(discover_endpoints=True) as client:
            client.add_credential(profile="nersc", api_key="...")
            session = await client.create_session("my-session")
            await session.plan(verbose=True)
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from amscrot.util.constants import Constants
from amscrot.util import utils
from .client import ProviderCredential
from .models import Provider

if TYPE_CHECKING:
    from amscrot.serviceclient import ServiceClient


class AsyncClient:
    """Async-compatible client for the AmSCROT toolkit.

    Only I/O-bound methods (credential loading, endpoint discovery, session
    hydration) are ``async def``.  In-memory helpers like
    :meth:`add_credential`, :meth:`add_provider`, and
    :meth:`get_service_client` are regular synchronous methods.

    The constructor does **not** perform any I/O — call :meth:`initialize`
    (or use the ``async with`` context manager) to load credentials and
    discover endpoints::

        async with AsyncClient(discover_endpoints=True) as client:
            facility = client.facility("https://iri.nersc.gov", token="...")

    Args:
        create_service_clients: Auto-create ServiceClient instances from
            credential entries.
        discover_endpoints: Query the IRO facility discovery endpoint and
            auto-register IRI service clients.
        iro_endpoint: Override the default IRO endpoint URL.
        credential_file: Path to the credentials YAML file.
    """

    def __init__(
        self,
        *,
        create_service_clients: bool = False,
        discover_endpoints: bool = False,
        iro_endpoint: str | None = None,
        credential_file: str | None = None,
    ) -> None:
        self._providers: List[Provider] = []
        self._sessions: list = []
        self._service_clients: Dict[str, "ServiceClient"] = {}
        self._credentials: Dict[str, ProviderCredential] = {}
        self._logger = utils.get_logger()
        self._iro_endpoint = iro_endpoint or Constants.DEFAULT_IRO_ENDPOINT
        self._credential_file = credential_file

        # Deferred flags — acted on by initialize()
        self._deferred_create_service_clients = create_service_clients
        self._deferred_discover_endpoints = discover_endpoints

    # ── Async lifecycle ────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Perform deferred I/O: load credentials and discover endpoints.

        Safe to call multiple times — subsequent calls are no-ops if the
        deferred flags have already been consumed.
        """
        if self._deferred_create_service_clients or self._deferred_discover_endpoints:
            await self.load_credentials(file_path=self._credential_file)

        if self._deferred_create_service_clients:
            await asyncio.to_thread(self._sync_create_service_clients_from_credentials)
            self._deferred_create_service_clients = False

        if self._deferred_discover_endpoints:
            await self._discover_and_create_iri_clients()
            self._deferred_discover_endpoints = False

    async def __aenter__(self) -> "AsyncClient":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass  # No resources to release currently

    # ── Credential management (I/O: load_credentials) ─────────────────────

    async def load_credentials(self, *, file_path: str | None = None) -> None:
        """Load credentials from a YAML file asynchronously.

        If *file_path* is not provided, defaults to ``~/.amscrot/credentials.yml``.
        """
        from amscrot.util.utils import load_yaml_from_file

        if file_path is None:
            file_path = "~/.amscrot/credentials.yml"
            path_expanded = os.path.expanduser(file_path)
            exists = await asyncio.to_thread(os.path.exists, path_expanded)
            if not exists:
                if not self._credentials:
                    self._credentials = {}
                return

        creds = await asyncio.to_thread(load_yaml_from_file, file_path)
        creds = creds or {}
        for k, v in creds.items():
            if k in self._credentials:
                self._credentials[k].update(**v)
            else:
                self._credentials[k] = ProviderCredential(**v)

    def add_credential(self, *, profile: str, **kwargs) -> None:
        """Add or update a credential profile programmatically."""
        if profile in self._credentials:
            self._credentials[profile].update(**kwargs)
        else:
            self._credentials[profile] = ProviderCredential(**kwargs)

    def update_credential(self, *, profile: str, **kwargs) -> None:
        """Update an existing credential profile."""
        if profile not in self._credentials:
            raise ValueError(f"Profile '{profile}' not found.")
        self._credentials[profile].update(**kwargs)

    def get_credential(self, profile: str) -> ProviderCredential | None:
        """Get a specific credential object."""
        return self._credentials.get(profile)

    def list_credentials(self) -> List[str]:
        """List available credential profiles."""
        return list(self._credentials.keys())

    # ── Provider management (in-memory — sync) ────────────────────────────

    def add_provider(
        self,
        *,
        label: str,
        type: str,
        profile: str | None = None,
        **kwargs,
    ) -> Provider:
        """Add a provider configuration.

        .. note::

            If a ``credential_file`` keyword is present, you should call
            :meth:`load_credentials` separately before calling this method,
            since ``add_provider`` is synchronous.
        """
        attributes: dict = {}
        if profile:
            if profile not in self._credentials:
                raise ValueError(f"Profile '{profile}' not found in loaded credentials.")
            attributes.update(self._credentials[profile].to_dict())
            attributes["profile"] = profile

        attributes.update(kwargs)
        provider = Provider(label, type, **attributes)
        self._providers.append(provider)

        for session in self._sessions:
            session.add_provider(provider)

        return provider

    # ── Service client management (in-memory — sync) ──────────────────────

    def add_service_client(self, service_client: "ServiceClient") -> "ServiceClient":
        """Register a pre-built ServiceClient instance."""
        self._service_clients[service_client.name] = service_client
        return service_client

    def get_service_client(
        self, name: str | None = None
    ) -> Union[Optional["ServiceClient"], List["ServiceClient"]]:
        """Retrieve a service client by name, shorthand, or list all."""
        if name is None:
            return list(self._service_clients.values())

        # 1. Direct match
        if name in self._service_clients:
            return self._service_clients[name]

        # 2. Shorthand match
        shorthand = self.get_shorthand(name)
        for sc in self._service_clients.values():
            if self.get_shorthand(sc.name) == shorthand:
                return sc

        # 3. Case-insensitive substring match fallback
        name_lower = name.lower()
        for k, sc in self._service_clients.items():
            if name_lower in k.lower():
                return sc

        return None

    # ── Session factory (I/O: disk state hydration) ───────────────────────

    async def create_session(self, name: str) -> "AsyncSession":
        """Create a new :class:`AsyncSession` and hydrate from disk state.

        Returns an :class:`AsyncSession` whose I/O methods are ``async def``.
        """
        from .async_session import AsyncSession
        from .models import Session

        sync_session = Session(
            name=name,
            providers=list(self._providers),
            service_clients=list(self._service_clients.values()),
        )

        # Hydrate cached state from disk
        await asyncio.to_thread(self._hydrate_session, sync_session, name)

        async_session = AsyncSession(sync_session)
        self._sessions.append(async_session)
        return async_session

    # ── Facility client factory (no I/O — sync) ───────────────────────────

    def facility(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        token_provider=None,
        name: str | None = None,
    ) -> "AsyncFacilityClient":
        """Connect to an IRI-compliant facility (async version).

        Returns an :class:`AsyncFacilityClient` whose I/O methods are
        ``async def``.

        Args:
            endpoint: Facility API base URL.
            token: Static bearer token.
            token_provider: Callable returning the current token.
            name: Optional display name.
        """
        from amscrot.facility.async_client import AsyncFacilityClient

        return AsyncFacilityClient(
            endpoint=endpoint,
            token=token,
            token_provider=token_provider,
            name=name,
        )

    # ── Static / class helpers (shared logic with sync Client) ─────────────

    @staticmethod
    def _normalize_endpoint(url: str) -> str:
        """Normalize an IRI endpoint URL for identity comparison."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    @staticmethod
    def _slugify(name: str) -> str:
        """Turn a facility name into a kebab-case identifier."""
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-")

    @classmethod
    def get_shorthand(cls, name: str) -> str:
        """Resolve a facility name or slug to a user-friendly shorthand."""
        slug = cls._slugify(name)
        if slug in Constants.FACILITY_SHORTHANDS:
            return Constants.FACILITY_SHORTHANDS[slug]

        if "nersc" in slug:
            return "nersc"
        if "esnet" in slug:
            if "east" in slug:
                return "esnet-east"
            if "west" in slug:
                return "esnet-west"
            return "esnet"
        if "alcf" in slug or "argonne" in slug:
            return "alcf"
        if "olcf" in slug or "oak-ridge" in slug:
            return "olcf"
        if "amsc-iro" in slug:
            return "amsc-iro"

        return slug

    # ── Private helpers ────────────────────────────────────────────────────

    def _sync_create_service_clients_from_credentials(self) -> None:
        """Auto-create ServiceClient instances from credential entries.

        Called via ``asyncio.to_thread()`` from :meth:`initialize`.
        """
        from amscrot.serviceclient import ServiceClient as SC

        for entry_name, cred in self._credentials.items():
            client_type_attr = getattr(cred, "client_type", None)
            if not client_type_attr:
                self._logger.warning(
                    f"Missing 'client_type' in credential entry '{entry_name}', skipping."
                )
                continue

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
                    f"Created service client '{entry_name}' (type={service_type})"
                )
            except Exception as e:
                self._logger.warning(
                    f"Failed to create service client '{entry_name}' "
                    f"(type={service_type}): {e}"
                )

    async def _discover_and_create_iri_clients(self) -> None:
        """Query the IRO facility discovery endpoint asynchronously.

        Uses ``httpx.AsyncClient`` for the HTTP call when available,
        falling back to ``asyncio.to_thread(requests.get, ...)`` otherwise.
        """
        from amscrot.serviceclient import ServiceClient as SC

        url = f"{self._iro_endpoint.rstrip('/')}/amsc-iro/resource/facility"
        self._logger.debug(f"Discovering IRI facilities from {url}")

        try:
            data = await self._async_get_json(url)
        except Exception as e:
            self._logger.warning(f"Failed to discover IRI facilities: {e}")
            return

        facilities = data.get("facilities", [])
        if not facilities:
            self._logger.info("No IRI facilities returned from discovery.")
            return

        cred_by_endpoint: Dict[str, tuple] = {}
        for profile_name, cred in self._credentials.items():
            ctype = getattr(cred, "client_type", None)
            ep = getattr(cred, "api_endpoint", None)
            if ctype == "AMSC_IRI" and ep:
                cred_by_endpoint[self._normalize_endpoint(ep)] = (profile_name, cred)

        env_token = os.environ.get("AMSC_TOKEN")

        for fac in facilities:
            fac_name = fac.get("facility_name", "unknown")
            fac_endpoint = fac.get("api_endpoint", "")
            norm_ep = self._normalize_endpoint(fac_endpoint)
            shorthand = self.get_shorthand(fac_name)

            if shorthand in self._service_clients:
                self._logger.debug(f"Service client '{shorthand}' already exists, skipping.")
                continue

            match = cred_by_endpoint.get(norm_ep)
            if match:
                profile_name, cred = match
                self._logger.info(
                    f"Matched facility '{fac_name}' to credential profile '{profile_name}'"
                )
                try:
                    sc = await asyncio.to_thread(
                        SC.create,
                        type=Constants.ServiceType.IRI,
                        name=shorthand,
                        profile=profile_name,
                        credential=cred,
                    )
                    self._service_clients[shorthand] = sc
                    self._logger.debug(
                        f"Created IRI client '{shorthand}' from profile '{profile_name}'"
                    )
                except Exception as e:
                    self._logger.warning(
                        f"Failed to create IRI client '{shorthand}' "
                        f"from profile '{profile_name}': {e}"
                    )
                continue

            if env_token:
                try:
                    sc = await asyncio.to_thread(
                        SC.create,
                        type=Constants.ServiceType.IRI,
                        name=shorthand,
                        endpoint_uri=norm_ep,
                        credential={"api_key": env_token, "api_endpoint": norm_ep},
                    )
                    self._service_clients[shorthand] = sc
                    self._logger.info(
                        f"Created IRI client '{shorthand}' for '{fac_name}' using AMSC_TOKEN"
                    )
                except Exception as e:
                    self._logger.warning(
                        f"Failed to create IRI client '{shorthand}' with AMSC_TOKEN: {e}"
                    )
                continue

            self._logger.warning(
                f"Skipping facility '{fac_name}' — no matching credential profile "
                f"and AMSC_TOKEN not set."
            )

    async def _async_get_json(self, url: str) -> dict:
        """Fetch JSON from *url* asynchronously.

        Tries ``httpx`` first; falls back to ``requests`` via ``to_thread``.
        """
        try:
            import httpx

            async with httpx.AsyncClient(verify=True, timeout=10) as http:
                resp = await http.get(url)
                resp.raise_for_status()
                return resp.json()
        except ImportError:
            import requests as _requests

            resp = await asyncio.to_thread(
                _requests.get, url, timeout=10, verify=True
            )
            resp.raise_for_status()
            return resp.json()

    def _hydrate_session(self, session, name: str) -> None:
        """Hydrate a Session with cached service clients and jobs from disk."""
        from amscrot.util import state as sutil
        from amscrot.client.job import Job, JobType, JobServiceType, JobState, JobSpec
        from amscrot.serviceclient import ServiceClient

        cached_scs, cached_jobs = sutil.load_jobs(name)

        if cached_scs:
            self._logger.info(
                f"Restoring {len(cached_scs)} service client(s) from session '{name}' state file."
            )
            for sc_dict in cached_scs:
                for sc_name, sc_cfg in sc_dict.items():
                    try:
                        sc = ServiceClient.create(
                            type=sc_cfg.get("type"),
                            name=sc_name,
                            endpoint_uri=sc_cfg.get("endpoint_uri"),
                            status=sc_cfg.get("status", "ACTIVE"),
                            profile=sc_cfg.get("profile"),
                        )
                        if sc_name not in session._service_clients:
                            session.add_service_client(sc)
                    except Exception as e:
                        self._logger.warning(
                            f"Skipping hydration of cached ServiceClient '{sc_name}': {e}"
                        )

        if cached_jobs:
            self._logger.info(
                f"Restoring {len(cached_jobs)} job(s) from session '{name}' state file."
            )
            for j_dict in cached_jobs:
                try:
                    sc_name = j_dict.get("service_client")
                    sc = session.get_service_client(sc_name) if sc_name else None
                    if sc is None and sc_name:
                        result = self._service_clients.get(sc_name)
                        sc = result

                    job_spec_dict = j_dict.get("spec", {})
                    spec = None
                    if job_spec_dict:
                        spec = JobSpec(
                            resources=job_spec_dict.get("resources"),
                            executable=job_spec_dict.get("executable"),
                            arguments=job_spec_dict.get("arguments"),
                            attributes=job_spec_dict.get("attributes"),
                        )

                    job = Job(
                        name=j_dict.get("name"),
                        type=JobType(j_dict.get("type", "COMPUTE")),
                        service_type=JobServiceType(j_dict.get("service_type", "BATCH")),
                        service_client=sc,
                        job_spec=spec,
                    )
                    job.id = j_dict.get("id")
                    job.resource_id = j_dict.get("resource_id")
                    try:
                        job.status = JobState(j_dict.get("status", "INIT"))
                    except ValueError:
                        job.status = JobState.INIT
                    session.add_job(job)
                except Exception as e:
                    self._logger.warning(
                        f"Skipping hydration of cached job '{j_dict.get('name')}': {e}"
                    )

    def __repr__(self) -> str:
        return (
            f"AsyncClient(providers={len(self._providers)}, "
            f"service_clients={len(self._service_clients)})"
        )
