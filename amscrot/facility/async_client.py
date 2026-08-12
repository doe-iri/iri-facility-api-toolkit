"""Async counterpart of :class:`FacilityClient` for use with ``asyncio``.

Only I/O-bound methods are ``async def``; in-memory property accessors
and the constructor remain synchronous.

Usage::

    from amscrot.client import AsyncClient

    async def main():
        async with AsyncClient(discover_endpoints=True) as client:
            facility = client.facility("https://iri.nersc.gov", token="...")
            resources = await facility.resources()
            job = await resources[0].submit(executable="/bin/echo", nodes=1)
            await job.wait(timeout=300)
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from amscrot.serviceclient import ServiceClient
from amscrot.client.models import Session
from amscrot.client.job import (
    Job as AmscrotJob,
    JobSpec,
    JobType,
    JobServiceType,
)
from amscrot.util import utils

if TYPE_CHECKING:
    from amsc_iri.models.job_spec_input import JobSpecInput as IriJobSpec


class AsyncFacilityClient:
    """Async interface to an IRI-compliant facility.

    Mirrors :class:`FacilityClient` with I/O methods as ``async def``.
    In-memory property accessors (``name``, ``display_name``, ``base_url``,
    ``session``) remain synchronous.

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

        self._static_token = token

        if token_provider is not None:
            self._token_provider: Callable[[], str] | None = token_provider
        else:
            self._token_provider = None

        self._service_client = self._build_service_client(initial=True)

        self._session = Session(name=f"facility-{self._name}")
        self._session.add_service_client(self._service_client)

        self._discovery: Any = None

    # ── Properties (in-memory — sync) ──────────────────────────────────────

    @property
    def name(self) -> str:
        """Short name of the facility (defaults to the endpoint URL)."""
        return self._name

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        return self._name

    @property
    def base_url(self) -> str:
        """Base URL of the facility API."""
        return self._endpoint

    @property
    def session(self) -> Session:
        """Access the underlying Session for advanced orchestration."""
        return self._session

    # ── I/O operations (async) ─────────────────────────────────────────────

    async def info(self) -> Any:
        """Return facility metadata (live API call)."""
        return await self._async_call_api(self._service_client.get_facility_info)

    async def resources(self) -> list:
        """Return compute, storage, and network resources at this facility."""
        from amscrot.facility.async_models import AsyncResource

        _INCLUDED_TYPES = {"compute", "storage", "network"}
        discovery = await self._async_get_discovery()
        return [
            AsyncResource(data=item.data, facility_client=self)
            for item in discovery.all
            if item.type in _INCLUDED_TYPES
        ]

    async def resource(self, name: str):
        """Get a resource by name (case-insensitive).

        Raises:
            ValueError: If no resource with that name is found.
        """
        name_lower = name.lower()
        available = await self.resources()
        for r in available:
            if r.name.lower() == name_lower:
                return r
        raise ValueError(
            f"No resource found with name {name!r} at {self._endpoint}. "
            f"Available: {[r.name for r in available]}"
        )

    async def incidents(self) -> List[Any]:
        """Return all incidents at this facility (live API call)."""
        return await self._async_call_api(self._service_client.get_incidents) or []

    async def incident(self, incident_id: str) -> Optional[Any]:
        """Return a single incident by ID (live API call)."""
        return await self._async_call_api(self._service_client.get_incident, incident_id)

    async def events(self, incident_id: str) -> List[Any]:
        """Return events for a specific incident (live API call)."""
        return await self._async_call_api(self._service_client.get_events, incident_id) or []

    async def resource_by_id(self, resource_id: str) -> Optional[Any]:
        """Return a single resource by UUID (live API call, not cached)."""
        from amscrot.facility.async_models import AsyncResource

        data = await self._async_call_api(self._service_client.get_resource_by_id, resource_id)
        if data is None:
            return None
        return AsyncResource(data=data, facility_client=self)

    async def _async_get_jobs(self, resource_id: str, *, historical: bool = False) -> list:
        """Return AsyncJob wrappers for all jobs on a resource (live API call)."""
        from amscrot.facility.async_models import AsyncJob

        raw_jobs = await self._async_call_api(
            self._service_client.get_jobs, resource_id, historical=historical
        ) or []
        jobs = []
        for raw in raw_jobs:
            handle = SimpleNamespace(
                id=raw.get("id", ""),
                resource_id=resource_id,
                name=raw.get("name", ""),
                status=SimpleNamespace(value=raw.get("status", "UNKNOWN")),
            )
            jobs.append(AsyncJob(amscrot_job=handle, resource_id=resource_id, facility_client=self))
        return jobs

    async def _async_submit_job(
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
        job_spec: JobSpec | "IriJobSpec" | None = None,
    ) -> Any:
        """Build JobSpec + AmscrotJob from flat kwargs and submit (async)."""
        from amscrot.facility.async_models import AsyncJob

        if job_spec is not None:
            amscrot_job = AmscrotJob(
                name=name or "",
                type=JobType.COMPUTE,
                service_type=JobServiceType.BATCH,
                service_client=self._service_client,
                job_spec=job_spec,
            )
            amscrot_job.resource_id = resource_id
            await self._async_call_api(self._service_client.create, amscrot_job)
            return AsyncJob(
                amscrot_job=amscrot_job,
                resource_id=resource_id,
                facility_client=self,
            )

        # Build resources dict
        resources: dict = {}
        if nodes is not None:
            resources["node_count"] = nodes

        # Build attributes dict
        attributes: dict = {}
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
            resource_id=resource_id,
            service_type=JobServiceType.BATCH,
            service_client=self._service_client,
            job_spec=spec,
        )

        self._session.add_job(amscrot_job)
        await self._async_call_api(self._service_client.plan, amscrot_job)
        await self._async_call_api(self._service_client.create, amscrot_job)

        return AsyncJob(
            amscrot_job=amscrot_job,
            resource_id=resource_id,
            facility_client=self,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    async def _async_call_api(self, operation: Callable, *args: Any, **kwargs: Any) -> Any:
        """Invoke an API operation asynchronously with token-refresh retry."""
        try:
            return await asyncio.to_thread(operation, *args, **kwargs)
        except Exception as exc:
            if self._is_auth_error(exc) and self._token_provider is not None:
                self._logger.warning(
                    f"[{self._name}] Auth error detected, refreshing token and retrying."
                )
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
                refreshed_op = (
                    getattr(self._service_client, sc_method_name)
                    if sc_method_name is not None
                    else operation
                )
                return await asyncio.to_thread(refreshed_op, *args, **kwargs)
            raise

    def _build_service_client(self, initial: bool = False) -> Any:
        """Create (or recreate) the IriServiceClient with the current token."""
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

    async def _async_get_discovery(self, refresh: bool = False) -> Any:
        """Return cached discovery result, fetching on first call."""
        if refresh:
            self._discovery = None
        if self._discovery is None:
            self._discovery = await self._async_call_api(
                self._session.metadata, self._name, refresh=refresh, native=True
            )
        return self._discovery

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "401" in msg or "403" in msg or "unauthorized" in msg

    def __repr__(self) -> str:
        return f"AsyncFacilityClient(endpoint={self._endpoint!r}, name={self._name!r})"
