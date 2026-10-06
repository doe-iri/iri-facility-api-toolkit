"""AmSC Resource Interface Gateway (RIG) service client.

The RIG is a transparent authenticating reverse proxy in front of many IRI
facilities.  Each facility is reachable at::

    <rig-base-url>/rig/external/<facility-name>

and the standard IRI paths (``/api/vN/...``) hang directly off that prefix.
Because the proxy is transparent, a plain
:class:`~amscrot.serviceclient.amsc_iri.IriServiceClient` pointed at that URL
works without modification -- no new API bindings or path rewriting required.

This client therefore does **not** implement a new transport.  It is a
*discovery and factory* client that:

1. Probes the gateway's ``/ready`` endpoint (once, cached) to enumerate the
   available IRI facilities and their API versions.
2. Exposes that listing through the standard :meth:`discover` contract.
3. Expands into real ``IriServiceClient`` children via
   :meth:`create_facility_clients`, each pre-seeded with the authoritative
   API version so no child ever needs to run ``VersionProber``.

Credential layout in ``~/.amscrot/credentials.yml``::

    amsc-rig:
      client_type: AMSC_RIG
      api_endpoint: https://rig.staging.american-science-cloud.org
      pat_file: ~/.amsc_token.json
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import yaml

from amscrot.model.discovery import DiscoveredResource, DiscoveryResult
from amscrot.serviceclient.serviceclient import ServiceClient
from amscrot.util import utils
from amscrot.util.constants import Constants

from .ready_prober import RigFacility, RigReadyDocument, RigReadyProber

if TYPE_CHECKING:
    from amscrot.client.job import Job, JobStatus


class RigServiceClient(ServiceClient):
    """Discovery/factory client for an AmSC Resource Interface Gateway.

    This client fronts no compute of its own; the job lifecycle methods
    (:meth:`plan`, :meth:`create`, :meth:`destroy`, :meth:`status`) raise
    :class:`NotImplementedError` and direct the caller to a facility client
    produced by :meth:`create_facility_clients`.
    """

    #: Credential keys recognized for tuning facility expansion.
    _OPTION_KEYS = (
        "facilities",
        "exclude_facilities",
        "skip_unhealthy",
        "child_prefix",
        "verify",
    )

    def __init__(self, **kwargs):
        kwargs.pop("api_version", None)
        if not kwargs.get("name"):
            kwargs["name"] = kwargs.get("profile") or "amsc-rig"
        super().__init__(type=Constants.ServiceType.AMSC_RIG, **kwargs)

        self.api_key: Optional[str] = None
        self.api_endpoint: Optional[str] = None

        # Expansion options (populated by _load_credentials)
        self.facility_allowlist: List[str] = []
        self.facility_denylist: List[str] = []
        self.skip_unhealthy: bool = False
        self.child_prefix: str = ""
        self.verify: bool = True

        self._load_credentials()

        # An explicitly supplied endpoint_uri wins over the credential file.
        if self.endpoint_uri:
            self.api_endpoint = self.endpoint_uri

        if self.api_endpoint:
            self.api_endpoint = self.api_endpoint.rstrip("/")
            self.endpoint_uri = self.api_endpoint

        self._prober = RigReadyProber(verify=self.verify)
        self._ready: Optional[RigReadyDocument] = None

        self._available = bool(self.api_key and self.api_endpoint)
        if not self._available:
            missing = []
            if not self.api_key:
                missing.append("api_key/pat_file")
            if not self.api_endpoint:
                missing.append("api_endpoint")
            self.logger.warning(
                f"[{self.name}] Warning: Could not load RIG credentials "
                f"(missing: {', '.join(missing)})."
            )

    # ------------------------------------------------------------------
    # Credential loading
    # ------------------------------------------------------------------

    def _load_credentials(self) -> None:
        """Load RIG credentials from a credential object or credentials.yml."""
        # 1. Explicit credential object / dict
        if self.credential:
            try:
                if hasattr(self.credential, "to_dict"):
                    creds = self.credential.to_dict()
                elif isinstance(self.credential, dict):
                    creds = self.credential
                else:
                    creds = {}
                if creds:
                    self._apply_credentials(creds)
                    return
            except Exception as exc:
                self.logger.error(
                    f"[{self.name}] Error loading from credential object: {exc}"
                )

        # 2. credentials.yml
        default_file = os.path.join(str(Path.home()), ".amscrot", "credentials.yml")
        cred_file = os.path.expanduser(self.credential_file or default_file)

        if not os.path.exists(cred_file):
            self.logger.warning(
                f"[{self.name}] Warning: Credentials file not found at {cred_file}"
            )
            return

        try:
            with open(cred_file, "r") as fh:
                credentials = yaml.safe_load(fh) or {}
        except Exception as exc:
            self.logger.error(f"[{self.name}] Error loading credentials: {exc}")
            return

        lookups = []
        if self.profile:
            lookups.append(self.profile)
        if self.name and self.name not in lookups:
            lookups.append(self.name)
        lookups.append(Constants.ServiceType.AMSC_RIG)

        for key in lookups:
            if key in credentials and isinstance(credentials[key], dict):
                self._apply_credentials(credentials[key])
                return

        searched = f"'{self.profile}' or " if self.profile else ""
        self.logger.warning(
            f"[{self.name}] Warning: Section {searched}"
            f"'{Constants.ServiceType.AMSC_RIG}' not found in credentials"
        )

    def _apply_credentials(self, creds: Dict[str, Any]) -> None:
        """Apply a credentials mapping to this client's configuration."""
        self.api_key = creds.get("api_key")
        if not self.api_key and creds.get("pat_file"):
            self.api_key = utils.load_pat_from_file(creds.get("pat_file"))

        endpoint = creds.get("api_endpoint")
        if endpoint:
            self.api_endpoint = endpoint

        allow = creds.get("facilities")
        if allow:
            self.facility_allowlist = [str(f) for f in allow]

        deny = creds.get("exclude_facilities")
        if deny:
            self.facility_denylist = [str(f) for f in deny]

        if "skip_unhealthy" in creds:
            self.skip_unhealthy = bool(creds.get("skip_unhealthy"))
        if creds.get("child_prefix"):
            self.child_prefix = str(creds.get("child_prefix"))
        if "verify" in creds:
            self.verify = bool(creds.get("verify"))

    # ------------------------------------------------------------------
    # Ready document
    # ------------------------------------------------------------------

    def get_ready(self, *, refresh: bool = False) -> Optional[RigReadyDocument]:
        """Return the gateway's parsed ``/ready`` document.

        Args:
            refresh: Bypass both the in-memory and on-disk caches.

        Returns:
            A :class:`RigReadyDocument`, or ``None`` if unavailable.
        """
        if self._ready is not None and not refresh:
            return self._ready

        if not self._available:
            self.logger.warning(
                f"[{self.name}] RIG client not initialized; cannot query /ready."
            )
            return None

        self._ready = self._prober.fetch(
            self.api_endpoint, api_key=self.api_key, force=refresh
        )
        return self._ready

    def get_facilities(self, *, refresh: bool = False) -> List[RigFacility]:
        """Return every facility advertised by the gateway."""
        doc = self.get_ready(refresh=refresh)
        return list(doc.facilities) if doc else []

    def is_ready(self, *, refresh: bool = False) -> bool:
        """True when the gateway reports ``status: ready``."""
        doc = self.get_ready(refresh=refresh)
        return bool(doc and doc.is_ready)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, native: bool = True) -> DiscoveryResult:
        """Enumerate the IRI facilities fronted by this gateway.

        Each facility becomes a ``facility``-typed
        :class:`~amscrot.model.discovery.DiscoveredResource` carrying its
        resolved proxy ``api_endpoint``, API version, and path style.
        """
        doc = self.get_ready()
        if doc is None:
            self.logger.warning(
                f"[{self.name}] /ready unavailable; returning empty discovery."
            )
            return DiscoveryResult()

        items: List[DiscoveredResource] = []
        for fac in doc.facilities:
            data = fac.to_dict()
            data["id"] = fac.name
            data["api_endpoint"] = fac.base_url(doc.base_url)
            data["supported"] = True
            data["path_prefix"] = fac.api_prefix
            items.append(
                DiscoveredResource(
                    type=Constants.RES_FACILITY,
                    name=fac.name,
                    data=data,
                )
            )

        self.logger.debug(
            f"[{self.name}] Discovered {len(items)} facility(ies) from RIG."
        )
        return DiscoveryResult(items=items)

    # ------------------------------------------------------------------
    # Facility client factory
    # ------------------------------------------------------------------

    def _selected_facilities(self, doc: RigReadyDocument) -> List[RigFacility]:
        """Apply allow/deny/health filters to the advertised facility list."""
        selected: List[RigFacility] = []
        for fac in doc.facilities:
            if self.facility_allowlist and fac.name not in self.facility_allowlist:
                self.logger.debug(
                    f"[{self.name}] Skipping '{fac.name}' (not in allow-list)."
                )
                continue
            if fac.name in self.facility_denylist:
                self.logger.debug(
                    f"[{self.name}] Skipping '{fac.name}' (in exclude list)."
                )
                continue
            if self.skip_unhealthy and not fac.health_monitored:
                self.logger.debug(
                    f"[{self.name}] Skipping '{fac.name}' (not health-monitored)."
                )
                continue
            if not fac.is_standard_path:
                self.logger.info(
                    f"[{self.name}] Facility '{fac.name}' advertises "
                    f"non-standard metadata_path '{fac.metadata_path}'; "
                    f"will use path_prefix={fac.api_prefix!r} for its "
                    f"IRI client."
                )
            selected.append(fac)
        return selected

    def child_client_name(
        self,
        facility: RigFacility,
        peers: Optional[List[RigFacility]] = None,
    ) -> str:
        """Return the service-client name to register for *facility*.

        Uses the toolkit's facility shorthand resolution and appends a
        ``-rig`` suffix so gateway-discovered clients never collide with a
        directly-configured client for the same facility.

        Several distinct RIG facilities can collapse to the same shorthand --
        ``olcf-open`` and ``olcf-moderate`` both resolve to ``olcf``.  When
        *peers* is supplied and a collision exists within it, the facility's
        own name is used as the base instead so each enclave keeps a distinct
        client (``olcf-open-rig`` / ``olcf-moderate-rig``).

        Args:
            facility: The facility to name.
            peers: The full set of facilities being expanded alongside it.
        """
        from amscrot.client.client import Client

        base = Client.get_shorthand(facility.name)

        if peers:
            collides = any(
                other.name != facility.name
                and Client.get_shorthand(other.name) == base
                for other in peers
            )
            if collides:
                base = Client._slugify(facility.name)

        if not base.endswith("-rig"):
            base = f"{base}-rig"
        return f"{self.child_prefix}{base}"

    def create_facility_clients(
        self, *, refresh: bool = False
    ) -> Dict[str, ServiceClient]:
        """Build an ``IriServiceClient`` for each advertised facility.

        Every child is constructed with an explicit ``api_version`` taken from
        the gateway, which short-circuits ``VersionProber`` entirely -- so
        expanding N facilities costs exactly one HTTP request (the ``/ready``
        call) rather than N version probes.

        Args:
            refresh: Re-query ``/ready`` instead of using the cache.

        Returns:
            Mapping of client name to constructed ``ServiceClient``.  Empty if
            the gateway is unreachable.
        """
        doc = self.get_ready(refresh=refresh)
        if doc is None:
            return {}

        if not doc.is_ready:
            self.logger.warning(
                f"[{self.name}] Gateway reports status='{doc.status}'; "
                "continuing with the advertised facility list anyway."
            )

        clients: Dict[str, ServiceClient] = {}
        selected = self._selected_facilities(doc)
        for fac in selected:
            child_name = self.child_client_name(fac, peers=selected)
            endpoint = fac.base_url(doc.base_url)
            try:
                client = ServiceClient.create(
                    type=Constants.ServiceType.AMSC_IRI,
                    name=child_name,
                    endpoint_uri=endpoint,
                    credential={
                        "api_key": self.api_key,
                        "api_endpoint": endpoint,
                        "api_version": fac.api_version,
                        "path_prefix": fac.api_prefix,
                    },
                )
            except Exception as exc:
                self.logger.warning(
                    f"[{self.name}] Failed to create IRI client "
                    f"'{child_name}' for facility '{fac.name}': {exc}"
                )
                continue

            clients[child_name] = client
            self.logger.info(
                f"[{self.name}] Created IRI client '{child_name}' "
                f"(facility={fac.name}, v{fac.api_version}) -> {endpoint}"
            )

        return clients

    # ------------------------------------------------------------------
    # Job lifecycle -- not applicable to the gateway itself
    # ------------------------------------------------------------------

    def _no_jobs(self, operation: str):
        raise NotImplementedError(
            f"[{self.name}] '{operation}' is not supported on an AMSC_RIG "
            "gateway client. The RIG only brokers access to IRI facilities; "
            "use a facility client from create_facility_clients() "
            "(e.g. 'nersc-rig', 'esnet-east-rig') to submit or manage jobs."
        )

    def plan(self, job: "Job", skip_checks: bool = False) -> Dict:
        self._no_jobs("plan")

    def create(self, job: "Job"):
        self._no_jobs("create")

    def destroy(self, job: "Job"):
        self._no_jobs("destroy")

    def status(self, job: "Job") -> "JobStatus":
        self._no_jobs("status")

    def __repr__(self):
        return (
            f"<RigServiceClient name={self.name} uri={self.endpoint_uri} "
            f"available={self._available}>"
        )
