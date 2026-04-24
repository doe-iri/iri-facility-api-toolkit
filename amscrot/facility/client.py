"""High-level FacilityClient — wraps IriServiceClient + implicit Session."""
from __future__ import annotations

import time
from typing import Any, Callable

from amscrot.serviceclient import ServiceClient
from amscrot.client.models import Session
from amscrot.client.job import (
    Job as AmscrotJob,
    JobSpec,
    JobType,
    JobServiceType,
)
from amscrot.model.metadata import Incident, StatusEvent
from amscrot.util import utils


class FacilityClient:
    """Pythonic interface to an IRI-compliant facility.

    Wraps AmSCROT's IriServiceClient and Session behind a minimal API::

        facility = client.facility("https://iri-dev.ppg.es.net", token="...")
        job = facility.resource("GPU Cluster").submit(
            executable="/bin/echo", nodes=1, queue="debug", account="myproj"
        )
        job.wait()

    Power users can access the underlying session::

        session = facility.session
        session.plan(verbose=True)
        session.destroy()

    Args:
        endpoint: Facility API base URL.
        token: Static bearer token (mutually exclusive with token_provider).
        token_provider: Callable returning current token (supports refresh).
        name: Optional display name for logging.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        token_provider: Callable[[], str] | None = None,
        name: str | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._name = name or self._endpoint
        self._logger = utils.get_logger()

        # Store static token separately so we can distinguish from a real provider.
        # When a token_provider is given, we do NOT call it during __init__ — the
        # initial service client is built with the static token (or empty string).
        # The provider is only invoked on a 401/403 refresh retry.
        self._static_token = token

        # Only set _token_provider when a real callable is passed; static tokens
        # never refresh — retry on 401 is not triggered for static tokens.
        if token_provider is not None:
            self._token_provider: Callable[[], str] | None = token_provider
        else:
            self._token_provider = None

        # Build internal IriServiceClient using static token (provider not called yet)
        self._service_client = self._build_service_client(initial=True)

        # Implicit session — hidden for simple use, exposed via .session
        self._session = Session(name=f"facility-{self._name}")
        self._session.add_service_client(self._service_client)

        # Cached discovery result
        self._discovery: Any = None

    # ── Public API ─────────────────────────────────────────────────────────

    def resources(self) -> list:
        """Return compute, storage, and network resources at this facility."""
        from amscrot.facility.models import Resource
        _INCLUDED_TYPES = {"compute", "storage", "network"}
        discovery = self._get_discovery()
        return [
            Resource(data=item.data, facility_client=self)
            for item in discovery.all
            if item.type in _INCLUDED_TYPES
        ]

    def resource(self, name: str):
        """Get a resource by name (case-insensitive).

        Raises:
            ValueError: If no resource with that name is found.
        """
        name_lower = name.lower()
        available = self.resources()
        for r in available:
            if r.name.lower() == name_lower:
                return r
        raise ValueError(
            f"No resource found with name {name!r} at {self._endpoint}. "
            f"Available: {[r.name for r in available]}"
        )

    def incidents(self) -> list[Incident]:
        """Return all incidents at this facility (live API call).

        Mirrors ``amsc_client.facility.FacilityClient.incidents()``.
        Each raw incident dict is wrapped in
        an :class:`~amscrot.model.metadata.Incident` model.
        """
        raw = self._call_api(self._service_client.get_incidents)
        return [Incident.from_dict(d) for d in (raw or [])]

    def incident(self, incident_id: str) -> Incident | None:
        """Return a single incident by ID (live API call).

        Mirrors ``amsc_client.facility.FacilityClient.incident()``.

        Args:
            incident_id: UUID of the incident to retrieve.

        Returns:
            :class:`~amscrot.model.metadata.Incident`, or ``None`` if not found.
        """
        raw = self._call_api(self._service_client.get_incident, incident_id)
        return Incident.from_dict(raw) if raw else None

    def events(self, incident_id: str) -> list[StatusEvent]:
        """Return events for a specific incident (live API call).

        Args:
            incident_id: UUID of the incident to retrieve events for.

        Returns:
            List of :class:`~amscrot.model.metadata.StatusEvent` objects.
        """
        raw_events = self._call_api(self._service_client.get_events, incident_id)
        return [StatusEvent.from_dict(d) for d in (raw_events or [])]

    @property
    def session(self) -> Session:
        """Access the underlying Session for advanced orchestration."""
        return self._session

    # ── Internal API (used by Resource and Job) ───────────────────────────

    def _call_api(self, operation: Callable, *args: Any, **kwargs: Any) -> Any:
        """Invoke an API operation with automatic token-refresh retry on 401/403.

        Retry only occurs when a real token_provider callable was supplied at
        construction time (not when a static token= was used).
        """
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            if self._is_auth_error(exc) and self._token_provider is not None:
                self._logger.warning(
                    f"[{self._name}] Auth error detected, refreshing token and retrying."
                )
                # Before rebuilding, detect whether `operation` is a bound method of
                # the current service client so we can re-resolve it on the new one.
                # We scan the old client's attributes by identity because __name__ is
                # not reliable for all callable types (e.g. MagicMock children).
                old_client = self._service_client
                sc_method_name = next(
                    (
                        attr
                        for attr in dir(old_client)
                        if not attr.startswith("_")
                        and getattr(old_client, attr, None) is operation
                    ),
                    None,
                )
                self._service_client = self._build_service_client()
                # Re-resolve the method on the refreshed client when possible.
                # For operations that were bound to the old service client, look up
                # the same name on the new client. For plain callables (lambdas,
                # test fakes), fall back to the original operation.
                refreshed_op = (
                    getattr(self._service_client, sc_method_name)
                    if sc_method_name is not None
                    else operation
                )
                return refreshed_op(*args, **kwargs)
            raise

    def _submit_job(
        self,
        resource_id: str,
        executable: str = "",
        arguments: list[str] | None = None,
        directory: str | None = None,
        name: str | None = None,
        queue: str | None = None,
        account: str | None = None,
        duration: int | None = None,
        nodes: int | None = None,
        environment: dict[str, str] | None = None,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
        pre_launch: str | None = None,
        post_launch: str | None = None,
        launcher: str | None = None,
        custom_attributes: dict | None = None,
    ) -> Any:
        """Build JobSpec + AmscrotJob from flat kwargs and submit."""
        from amscrot.facility.models import Job

        # Build resources dict
        resources: dict = {}
        if nodes is not None:
            resources["node_count"] = nodes

        # Build attributes dict
        attributes: dict = {"resource_id": resource_id}
        if directory:
            attributes["directory"] = directory
        if duration is not None:
            attributes["duration"] = duration
        if queue:
            attributes["queue_name"] = queue
        if account:
            attributes["account"] = account
        if stdout_path:
            attributes["stdout_path"] = stdout_path
        if stderr_path:
            attributes["stderr_path"] = stderr_path
        if environment:
            attributes["environment"] = environment
        if pre_launch:
            attributes["pre_launch"] = pre_launch
        if post_launch:
            attributes["post_launch"] = post_launch
        if launcher:
            attributes["launcher"] = launcher
        if custom_attributes:
            attributes["custom_attributes"] = custom_attributes

        spec = JobSpec(
            executable=executable,
            arguments=arguments or [],
            resources=resources,
            attributes=attributes,
        )

        job_name = name or f"job-{int(time.time())}"

        amscrot_job = AmscrotJob(
            name=job_name,
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=self._service_client,
            job_spec=spec,
        )

        self._session.add_job(amscrot_job)
        self._call_api(self._service_client.plan, amscrot_job)
        self._call_api(self._service_client.create, amscrot_job)

        return Job(
            amscrot_job=amscrot_job,
            resource_id=resource_id,
            facility_client=self,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _build_service_client(self, initial: bool = False) -> Any:
        """Create (or recreate) the IriServiceClient with the current token.

        Args:
            initial: When True (called from __init__), use the static token only —
                     do NOT invoke token_provider. This ensures the provider is only
                     called during explicit refresh retries (on 401/403), not at
                     construction time.
        """
        if not initial and self._token_provider is not None:
            token = self._token_provider()
        else:
            token = self._static_token or ""
        return ServiceClient.create(
            type="amsc-iri",
            name=self._name,
            endpoint_uri=self._endpoint,
            credential={"api_key": token, "api_endpoint": self._endpoint},
        )

    def _get_discovery(self) -> Any:
        """Return cached discovery result, fetching on first call."""
        if self._discovery is None:
            self._discovery = self._call_api(self._service_client.discover)
        return self._discovery

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "401" in msg or "403" in msg or "unauthorized" in msg

    def __repr__(self) -> str:
        return f"FacilityClient(endpoint={self._endpoint!r}, name={self._name!r})"
