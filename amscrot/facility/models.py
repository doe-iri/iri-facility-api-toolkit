"""Resource and Job wrappers for the high-level facility convenience API."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amscrot.facility.client import FacilityClient
    from amscrot.facility.filesystem import FilesystemClient

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELED"})


class Resource:
    """A compute, storage, or network resource at an IRI facility.

    Provides direct job submission and resource-scoped filesystem access::

        polaris = facility.resource("Polaris")
        job = polaris.submit(executable="/bin/echo", nodes=1, queue="debug")

        task = polaris.fs.ls("/home/user")
        task.wait()
    """

    def __init__(self, data: dict, facility_client: "FacilityClient") -> None:
        self._data = data
        self._facility = facility_client
        self._fs: "FilesystemClient | None" = None

    # ── Metadata ───────────────────────────────────────────────────────────

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

    # ── Filesystem ─────────────────────────────────────────────────────────

    @property
    def fs(self) -> "FilesystemClient":
        """Filesystem client scoped to this resource."""
        if self._fs is None:
            from amscrot.facility.filesystem import FilesystemClient
            self._fs = FilesystemClient(
                resource_id=self.id,
                iri_filesystem=self._facility._service_client.filesystem,
                call_api=self._facility._call_api,
            )
        return self._fs

    # ── Compute ────────────────────────────────────────────────────────────

    def jobs(self, *, historical: bool = False) -> list:
        """Return all jobs submitted to this resource (live API call)."""
        return self._facility._get_jobs(self.id, historical=historical)

    def submit(
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
        **custom_attributes: str,
    ) -> "Job":
        """Submit a job to this resource.

        IRI-standard parameters map directly to JobSpec fields. Any additional
        keyword arguments become scheduler-specific ``custom_attributes``
        (e.g., ALCF's ``filesystems="home"``).
        """
        return self._facility._submit_job(
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
        )

    def __repr__(self) -> str:
        return f"Resource(name={self.name!r}, type={self.resource_type!r}, status={self.status!r})"


class Job:
    """A submitted job on an IRI facility resource.

    Self-aware — retains a reference to its facility and can refresh
    its own status, wait for completion, or cancel itself::

        job = polaris.submit(executable="/bin/echo", ...)
        job.wait(timeout=120)
        print(job.state, job.exit_code)
    """

    def __init__(
        self,
        amscrot_job: Any,
        resource_id: str,
        facility_client: "FacilityClient",
    ) -> None:
        self._job = amscrot_job
        self._resource_id = resource_id
        self._facility = facility_client
        self._last_status: Any = None

    # ── Properties ─────────────────────────────────────────────────────────

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
    def status(self) -> str:
        """Live state — calls the IRI API on every access to refresh."""
        return self.refresh()

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def exit_code(self) -> int | None:
        return self._last_status.exit_code if self._last_status else None

    @property
    def message(self) -> str | None:
        return self._last_status.message if self._last_status else None

    # ── Actions ────────────────────────────────────────────────────────────

    def refresh(self, *, historical: bool = False) -> str:
        """Poll the IRI API for current job status. Returns state string."""
        self._last_status = self._facility._call_api(
            self._facility._service_client.status, self._job, historical=historical
        )
        return self.state

    def wait(self, timeout: float = 300, poll_interval: float = 5, *, historical: bool = False) -> "Job":
        """Block until the job reaches a terminal state.

        Raises:
            TimeoutError: If the job doesn't finish within ``timeout`` seconds.
        """
        start = time.time()
        while True:
            self.refresh(historical=historical)
            if self.is_terminal:
                return self
            if time.time() - start >= timeout:
                raise TimeoutError(
                    f"Job {self.id!r} did not complete within {timeout}s "
                    f"(last state: {self.state!r})"
                )
            time.sleep(poll_interval)

    def cancel(self) -> bool:
        """Cancel this job."""
        self._facility._call_api(
            self._facility._service_client.destroy, self._job
        )
        return True

    def __repr__(self) -> str:
        return f"Job(id={self.id!r}, state={self.state!r})"
