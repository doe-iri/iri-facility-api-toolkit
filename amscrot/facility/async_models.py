"""Async Resource and Job wrappers for the facility convenience API."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amsc_iri.models.job_spec_input import JobSpecInput as IriJobSpec
    from amscrot.client.job import JobSpec
    from amscrot.facility.async_client import AsyncFacilityClient
    from amscrot.facility.async_filesystem import AsyncFilesystemClient

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELED"})


class AsyncResource:
    """Async counterpart of :class:`~amscrot.facility.models.Resource`.

    In-memory property accessors remain synchronous; I/O-bound methods
    (:meth:`submit`, :meth:`jobs`) are ``async def``.

    Usage::

        polaris = await facility.resource("Polaris")
        job = await polaris.submit(executable="/bin/echo", nodes=1, queue="debug")
        task = await polaris.fs.ls("/home/user")
    """

    def __init__(self, data: dict, facility_client: "AsyncFacilityClient") -> None:
        self._data = data
        self._facility = facility_client
        self._fs: "AsyncFilesystemClient | None" = None

    # ── Metadata (in-memory — sync) ────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._data.get("id", "")

    @property
    def name(self) -> str:
        return self._data.get("name", "")

    @property
    def resource_type(self) -> str:
        return self._data.get("resource_type", "")

    @property
    def description(self) -> str:
        return self._data.get("description", "") or ""

    @property
    def group(self) -> str:
        return self._data.get("group", "") or ""

    @property
    def status(self) -> str:
        cs = self._data.get("current_status", "unknown")
        if cs is None:
            return "unknown"
        return cs.value if hasattr(cs, "value") else str(cs)

    # ── Filesystem (sync property, returns async client) ───────────────────

    @property
    def fs(self) -> "AsyncFilesystemClient":
        """Async filesystem client scoped to this resource."""
        if self._fs is None:
            from amscrot.facility.async_filesystem import AsyncFilesystemClient

            self._fs = AsyncFilesystemClient(
                resource_id=self.id,
                iri_filesystem=self._facility._service_client.filesystem,
                call_api=self._facility._async_call_api,
            )
        return self._fs

    # ── I/O operations (async) ─────────────────────────────────────────────

    async def jobs(self, *, historical: bool = False) -> list:
        """Return all jobs submitted to this resource (live API call)."""
        return await self._facility._async_get_jobs(self.id, historical=historical)

    def job(self, job_id: str) -> "AsyncJob":
        """Return a handle to an existing job by id (no API call)."""
        handle = SimpleNamespace(
            id=job_id,
            resource_id=self.id,
            name="",
            status=SimpleNamespace(value="UNKNOWN"),
        )
        return AsyncJob(amscrot_job=handle, resource_id=self.id, facility_client=self._facility)

    async def submit(
        self,
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
        job_spec: "JobSpec | IriJobSpec | None" = None,
        **custom_attributes: str,
    ) -> "AsyncJob":
        """Submit a job to this resource (async)."""
        return await self._facility._async_submit_job(
            resource_id=self.id,
            executable=executable,
            arguments=arguments,
            directory=directory,
            name=name,
            queue=queue,
            account=account,
            duration=duration,
            nodes=nodes,
            environment=environment,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            pre_launch=pre_launch,
            post_launch=post_launch,
            launcher=launcher,
            custom_attributes=custom_attributes or None,
            job_spec=job_spec,
        )

    def __repr__(self) -> str:
        return f"AsyncResource(name={self.name!r}, type={self.resource_type!r}, status={self.status!r})"


class AsyncJob:
    """Async counterpart of :class:`~amscrot.facility.models.Job`.

    In-memory property accessors (``id``, ``state``, ``is_terminal``,
    ``exit_code``, ``message``) remain synchronous.  I/O-bound methods
    (:meth:`refresh`, :meth:`wait`, :meth:`cancel`) are ``async def``.

    Usage::

        job = await polaris.submit(executable="/bin/echo", nodes=1)
        await job.wait(timeout=300)
        print(job.state, job.exit_code)
    """

    def __init__(
        self,
        amscrot_job: Any,
        resource_id: str,
        facility_client: "AsyncFacilityClient",
    ) -> None:
        self._job = amscrot_job
        self._resource_id = resource_id
        self._facility = facility_client
        self._last_status: Any = None

    # ── Properties (in-memory — sync) ──────────────────────────────────────

    @property
    def id(self) -> str:
        return self._job.id

    @property
    def state(self) -> str:
        """Last known state (cached from most recent refresh)."""
        if self._last_status is not None:
            return self._last_status.state
        s = self._job.status
        return s.value if hasattr(s, "value") else str(s)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def exit_code(self) -> int | None:
        return self._last_status.exit_code if self._last_status else None

    @property
    def message(self) -> str | None:
        return self._last_status.message if self._last_status else None

    # ── I/O operations (async) ─────────────────────────────────────────────

    async def refresh(self, *, historical: bool = False) -> str:
        """Poll the IRI API for current job status. Returns state string."""
        self._last_status = await self._facility._async_call_api(
            self._facility._service_client.status, self._job, historical=historical
        )
        return self.state

    async def wait(
        self,
        timeout: float = 300,
        poll_interval: float = 5,
        *,
        historical: bool = False,
    ) -> "AsyncJob":
        """Wait until the job reaches a terminal state.

        Uses ``asyncio.sleep()`` to keep the event loop responsive.

        Raises:
            TimeoutError: If the job doesn't finish within ``timeout`` seconds.
        """
        start = time.monotonic()
        while True:
            await self.refresh(historical=historical)
            if self.is_terminal:
                return self
            if time.monotonic() - start >= timeout:
                raise TimeoutError(
                    f"Job {self.id!r} did not complete within {timeout}s "
                    f"(last state: {self.state!r})"
                )
            await asyncio.sleep(poll_interval)

    async def cancel(self) -> bool:
        """Cancel this job."""
        await self._facility._async_call_api(
            self._facility._service_client.destroy, self._job
        )
        return True

    def __repr__(self) -> str:
        return f"AsyncJob(id={self.id!r}, state={self.state!r})"
