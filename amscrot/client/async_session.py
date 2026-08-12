"""Async counterpart of :class:`Session` for use with ``asyncio``.

Wraps the synchronous :class:`Session` and exposes only I/O-bound methods
as ``async def``.  In-memory operations (add_node, add_job, getters, show)
remain synchronous — no ``await`` needed.

Usage::

    from amscrot.client import AsyncClient

    async def main():
        client = AsyncClient()
        session = await client.create_session("my-session")
        session.add_node(label="n1", provider=provider)
        await session.plan(verbose=True)
        await session.apply()
        results = await session.wait(verbose=True, timeout=600)
        await session.destroy()
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .models import Session, Provider, Node, Network, Service, WaitTimeoutError

if TYPE_CHECKING:
    from .job import Job, JobState
    from amscrot.serviceclient import ServiceClient


class AsyncSession:
    """Async wrapper around :class:`Session`.

    I/O-bound operations (plan, apply, destroy, wait, metadata,
    fetch_output_files) are ``async def`` and use ``asyncio.to_thread()``
    or native async polling loops.

    In-memory helpers (add_node, add_job, getters, show) are regular
    synchronous methods — they only manipulate local state and do not
    perform any network or filesystem I/O.

    Args:
        sync_session: The underlying synchronous :class:`Session` instance.
    """

    def __init__(self, sync_session: Session) -> None:
        self._sync = sync_session

    # ── Properties (forwarded from sync session) ───────────────────────────

    @property
    def name(self) -> str:
        """Session name."""
        return self._sync.name

    @property
    def session_path(self) -> str:
        """Base directory for this session."""
        return self._sync.session_path

    @property
    def jobs(self) -> List["Job"]:
        """Return the list of jobs attached to this session."""
        return self._sync.jobs

    # ── Resource builders (in-memory — sync) ──────────────────────────────

    def add_node(self, *, label: str, provider: Provider, **kwargs) -> Node:
        """Add a node resource to the session."""
        return self._sync.add_node(label=label, provider=provider, **kwargs)

    def add_network(self, *, label: str, provider: Provider, **kwargs) -> Network:
        """Add a network resource to the session."""
        return self._sync.add_network(label=label, provider=provider, **kwargs)

    def add_service(self, *, label: str, provider: Provider, **kwargs) -> Service:
        """Add a service resource to the session."""
        return self._sync.add_service(label=label, provider=provider, **kwargs)

    def add_job(self, job: "Job") -> None:
        """Add a job to the session."""
        self._sync.add_job(job)

    def add_provider(self, provider: Provider) -> None:
        """Add a provider to the session."""
        self._sync.add_provider(provider)

    def add_service_client(self, service_client: "ServiceClient") -> None:
        """Add a service client to the session."""
        self._sync.add_service_client(service_client)

    # ── Getters (in-memory — sync) ────────────────────────────────────────

    def get_provider(self, label: str) -> Optional[Provider]:
        """Look up a provider by label."""
        return self._sync.get_provider(label)

    def get_node(self, label: str) -> Optional[Node]:
        """Look up a node by label."""
        return self._sync.get_node(label)

    def get_network(self, label: str) -> Optional[Network]:
        """Look up a network by label."""
        return self._sync.get_network(label)

    def get_service(self, label: str) -> Optional[Service]:
        """Look up a service by label."""
        return self._sync.get_service(label)

    def get_service_client(self, name: str) -> Optional["ServiceClient"]:
        """Look up a service client by name."""
        return self._sync.get_service_client(name)

    def get_job(self, name: str) -> Optional["Job"]:
        """Look up a job by name."""
        return self._sync.get_job(name)

    # ── I/O operations (truly async) ───────────────────────────────────────

    async def metadata(
        self, client_name: str, refresh: bool = False, native: bool = True
    ) -> Any:
        """Retrieve discovery metadata for a service client.

        Args:
            client_name: Name of the service client to query.
            refresh: If True, bypass cache and perform live discovery.
            native: If True, return raw native items.
        """
        return await asyncio.to_thread(
            self._sync.metadata, client_name, refresh=refresh, native=native
        )

    async def plan(self, verbose: bool = False, skip_checks: bool = False) -> Any:
        """Validate the session configuration.

        Offloads the synchronous plan operation to a thread.
        """
        return await asyncio.to_thread(
            self._sync.plan, verbose=verbose, skip_checks=skip_checks
        )

    async def apply(self) -> Any:
        """Apply the session configuration (submit jobs, create resources).

        Offloads the synchronous apply operation to a thread.
        """
        return await asyncio.to_thread(self._sync.apply)

    async def destroy(self) -> Any:
        """Destroy the session (cancel jobs, tear down resources).

        Offloads the synchronous destroy operation to a thread.
        """
        return await asyncio.to_thread(self._sync.destroy)

    async def wait(
        self,
        jobs: Optional[List["Job"]] = None,
        target_states: Optional[List] = None,
        *,
        timeout: Optional[float] = 300.0,
        interval: float = 2.0,
        verbose: bool = False,
        raw: bool = False,
    ) -> Dict[str, Any]:
        """Poll jobs until all reach one of the target states.

        This is a native async implementation that uses ``asyncio.sleep()``
        instead of ``time.sleep()``, keeping the event loop responsive
        during polling.

        Args:
            jobs:          Jobs to monitor. Defaults to all session jobs.
            target_states: Terminal states to wait for. Defaults to
                           [COMPLETED, FAILED, CANCELED].
            timeout:       Max seconds to wait. None = wait forever.
            interval:      Seconds between poll rounds.
            verbose:       Print poll status to stdout each round.
            raw:           If True and verbose, also print raw provider status.

        Returns:
            Dict of ``{job_name: JobStatus}`` for all jobs once settled.

        Raises:
            WaitTimeoutError: If timeout is reached before all jobs settle.
        """
        from amscrot.client.job import JobState

        watch_jobs: List["Job"] = jobs if jobs is not None else list(self._sync._jobs.values())

        if target_states is None:
            target_states = [JobState.COMPLETED, JobState.FAILED, JobState.CANCELED]

        target_set: Set[str] = {
            s.value if hasattr(s, "value") else s for s in target_states
        }

        pending: Dict[str, "Job"] = {j.name: j for j in watch_jobs}
        results: Dict[str, Any] = {}

        start = time.monotonic()

        while pending:
            if timeout is not None and (time.monotonic() - start) >= timeout:
                for job_name, job in pending.items():
                    sc = job.service_client
                    if sc:
                        try:
                            results[job_name] = await asyncio.to_thread(sc.status, job)
                        except Exception:
                            pass
                raise WaitTimeoutError(results, target_states)

            # Group pending jobs by service_client
            by_client: Dict[Any, list] = {}
            for job_name, job in pending.items():
                sc = job.service_client
                if sc is None:
                    raise ValueError(
                        f"Job '{job_name}' has no bound service_client — cannot poll status."
                    )
                by_client.setdefault(sc, []).append((job_name, job))

            # Poll each client for its jobs (offloaded to thread)
            settled_this_round: List[str] = []
            for sc, jobs_list in by_client.items():
                for job_name, job in jobs_list:
                    status = await asyncio.to_thread(sc.status, job)
                    results[job_name] = status
                    try:
                        job.set_status(status.state)
                    except (ValueError, KeyError):
                        pass
                    if status.state in target_set:
                        settled_this_round.append(job_name)

            if verbose:
                summary_parts = []
                for n in sorted(results):
                    st = results[n]
                    state_str = st.state.value if hasattr(st.state, "value") else str(st.state)
                    part = f"{n}={state_str}"
                    if getattr(st, "message", None):
                        part += f" ({st.message})"
                    if raw:
                        raw_parts = []
                        if getattr(st, "provider_status", None):
                            raw_parts.append(f"provider_status={st.provider_status}")
                        if raw_parts:
                            part += f" ({', '.join(raw_parts)})"
                    summary_parts.append(part)

                summary = "\n        ".join(summary_parts)
                elapsed = time.monotonic() - start
                print(f"[wait] {elapsed:.1f}s --\n        {summary}")

            for name in settled_this_round:
                del pending[name]

            if pending:
                await asyncio.sleep(interval)

        return results

    async def fetch_output_files(
        self,
        jobs: Optional[List["Job"]] = None,
        storage_resource_id: str | None = None,
        output_path: str | None = None,
    ) -> Dict[str, Dict[str, str]]:
        """Fetch remote stdout/stderr for completed jobs.

        Offloads the synchronous fetch operation to a thread.

        Args:
            jobs:                 Jobs to fetch for. Defaults to all session jobs.
            storage_resource_id:  Storage resource for filesystem ops.
            output_path:          Override base directory for output files.

        Returns:
            ``{job_name: {"stdout": "<local_path>", ...}}``.
        """
        return await asyncio.to_thread(
            self._sync.fetch_output_files,
            jobs=jobs,
            storage_resource_id=storage_resource_id,
            output_path=output_path,
        )

    # ── Display (sync — stdout only) ───────────────────────────────────────

    def show(self, summary: bool = False) -> None:
        """Display session state (no remote API calls)."""
        self._sync.show(summary=summary)

    def files_path(self, job_name: str) -> str:
        """Local directory for a job's fetched output files."""
        return self._sync.files_path(job_name)

    def __repr__(self) -> str:
        return f"AsyncSession(name={self.name!r})"
