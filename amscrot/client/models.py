import os
import time
from pathlib import Path
from typing import Dict, List, Any, TYPE_CHECKING, Union, Optional, Set
from amscrot.amscrot_manager import AmSCROTManager

if TYPE_CHECKING:
    from .job import Job
    from amscrot.serviceclient import ServiceClient

class Provider:
    def __init__(self, label: str, type: str, **kwargs):
        self.label = label
        self.type = type
        self.attributes = kwargs

    def to_config(self) -> Dict:
        return {
            self.type: [
                {self.label: self.attributes}
            ]
        }

    def __str__(self):
        return f"{{{{ {self.type}.{self.label} }}}}"

class Resource:
    def __init__(self, label: str, provider: Provider, **kwargs):
        self.label = label
        self.provider = provider

        # Resolve attributes
        self.attributes = {}
        for k, v in kwargs.items():
            self.attributes[k] = self._resolve_attribute(v)

    def _resolve_attribute(self, value: Any) -> Any:
        if isinstance(value, (Resource, Provider)):
            # When resolving references for YAML output, we want the template string reference
            return str(value)
        elif isinstance(value, list):
            return [self._resolve_attribute(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._resolve_attribute(v) for k, v in value.items()}
        return value

    def to_config(self, resource_type: str) -> Dict:
        attrs = self.attributes.copy()
        if self.provider:
            attrs['provider'] = str(self.provider)

        return {
            resource_type: [
                {self.label: attrs}
            ]
        }


class Node(Resource):
    def __str__(self):
        return f"{{{{ node.{self.label} }}}}"

class Network(Resource):
    def __str__(self):
        return f"{{{{ network.{self.label} }}}}"

class Service(Resource):
    def __init__(self, label: str, provider: Provider, controller: Union[str, Node] = None, **kwargs):
        if controller:
            kwargs['controller'] = controller
        super().__init__(label, provider, **kwargs)

    def __str__(self):
        return f"{{{{ service.{self.label} }}}}"


class WaitTimeoutError(TimeoutError):
    """Raised by Session.wait() when the timeout expires before all jobs settle."""
    def __init__(self, pending: Dict[str, Any], target_states):
        self.pending = pending  # {job_name: last JobStatus}
        names = list(pending.keys())
        labels = [s.value if hasattr(s, 'value') else s for s in target_states]
        super().__init__(
            f"{len(names)} job(s) did not reach {labels} within the timeout: {names}"
        )


class Session:
    def __init__(self, name: str, providers: List[Provider] = None, service_clients: List["ServiceClient"] = None):
        self._name = name
        self._providers: Dict[str, Provider] = {p.label: p for p in providers} if providers else {}
        self._service_clients: Dict[str, "ServiceClient"] = {sc.name: sc for sc in service_clients} if service_clients else {}
        self._nodes: Dict[str, Node] = {}
        self._networks: Dict[str, Network] = {}
        self._services: Dict[str, Service] = {}
        self._jobs: Dict[str, "Job"] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def session_path(self) -> str:
        """Base directory for this session (aligned with AmSCROTManager)."""
        p = os.path.join(str(Path.home()), '.amscrot', 'sessions', self._name)
        os.makedirs(p, exist_ok=True)
        return p

    @property
    def jobs(self) -> List["Job"]:
        """Return the list of jobs attached to this session."""
        return list(self._jobs.values())

    def files_path(self, job_name: str) -> str:
        """Local directory for a job's fetched output files."""
        p = os.path.join(self.session_path, 'files', job_name)
        os.makedirs(p, exist_ok=True)
        return p

    def _warn_overwrite(self, collection: Dict, key: str, kind: str):
        """Log a warning if *key* already exists in *collection*."""
        if key in collection:
            from amscrot.util import utils
            logger = utils.get_logger()
            logger.warning(
                f"{kind} '{key}' already exists in session "
                f"'{self._name}'. Overwriting previous entry."
            )

    def add_node(self, *, label: str, provider: Provider, **kwargs) -> Node:
        node = Node(label, provider, **kwargs)
        self._warn_overwrite(self._nodes, label, "Node")
        self._nodes[label] = node
        return node

    def add_network(self, *, label: str, provider: Provider, **kwargs) -> Network:
        network = Network(label, provider, **kwargs)
        self._warn_overwrite(self._networks, label, "Network")
        self._networks[label] = network
        return network

    def add_service(self, *, label: str, provider: Provider, **kwargs) -> Service:
        service = Service(label, provider, **kwargs)
        self._warn_overwrite(self._services, label, "Service")
        self._services[label] = service
        return service

    def add_job(self, job: "Job"):
        self._warn_overwrite(self._jobs, job.name, "Job")
        self._jobs[job.name] = job

    def add_provider(self, provider: Provider):
        self._warn_overwrite(self._providers, provider.label, "Provider")
        self._providers[provider.label] = provider

    def add_service_client(self, service_client: "ServiceClient"):
        self._warn_overwrite(self._service_clients, service_client.name, "ServiceClient")
        self._service_clients[service_client.name] = service_client

    # -- Getters ---------------------------------------------------------------

    def get_provider(self, label: str) -> Optional[Provider]:
        """Look up a provider by label."""
        return self._providers.get(label)

    def get_node(self, label: str) -> Optional[Node]:
        """Look up a node by label."""
        return self._nodes.get(label)

    def get_network(self, label: str) -> Optional[Network]:
        """Look up a network by label."""
        return self._networks.get(label)

    def get_service(self, label: str) -> Optional[Service]:
        """Look up a service by label."""
        return self._services.get(label)

    def get_service_client(self, name: str) -> Optional["ServiceClient"]:
        """Look up a service client by name."""
        return self._service_clients.get(name)

    def get_job(self, name: str) -> Optional["Job"]:
        """Look up a job by name."""
        return self._jobs.get(name)

    def _build_config(self) -> Dict:
        resources = []
        for n in self._nodes.values():
            resources.append(n.to_config('node'))
        for net in self._networks.values():
            resources.append(net.to_config('network'))
        for s in self._services.values():
            resources.append(s.to_config('service'))

        job_configs = []
        for j in self._jobs.values():
            job_configs.append(j.to_config())

        # Build provider config
        provider_configs = [p.to_config() for p in self._providers.values()]

        # Build service client config
        service_client_configs = [sc.to_config() for sc in self._service_clients.values()]

        return {
            'provider': provider_configs,
            'service_client': service_client_configs,
            'resource': resources,
            'job': job_configs
        }

    def _get_manager(self) -> AmSCROTManager:
        import yaml
        import copy

        config_list = self._build_config()

        # Create a deep copy for sanitization to avoid modifying the actual config
        sanitized_config = copy.deepcopy(config_list)

        def sanitize(data):
            if isinstance(data, dict):
                return {k: sanitize(v) if k.lower() not in ['password', 'secret'] else '******' for k, v in data.items()}
            elif isinstance(data, list):
                return [sanitize(v) for v in data]
            else:
                return data

        sanitized_config = sanitize(sanitized_config)

        # print(yaml.dump(sanitized_config))

        # Use the original config content for the manager
        config_content = yaml.dump(config_list)
        return AmSCROTManager(config_content=config_content, jobs=list(self._jobs.values()))

    def plan(self, verbose: bool = False, skip_checks: bool = False) -> Any:
        manager = self._get_manager()
        result = manager.plan(session=self._name, skip_checks=skip_checks)

        if verbose:
            cr = result["resources"]["to_be_created"]
            dl = result["resources"]["to_be_deleted"]
            print(f"Resources: {cr} to create, {dl} to destroy")
            if result["jobs"]:
                print(f"Jobs: {len(result['jobs'])} planned")
                for j in result["jobs"]:
                    status = j.get("plan_status", "UNKNOWN")
                    warnings = j.get("warnings") or []
                    line = f"  {j['name']}: {status}"
                    if warnings:
                        line += f"  warnings={warnings}"
                    print(line)

        return result

    def apply(self) -> Any:
        manager = self._get_manager()
        return manager.apply(session=self._name)

    def destroy(self) -> Any:
        manager = self._get_manager()
        return manager.destroy(session=self._name)

    def wait(
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

        Resolves each job's bound service_client automatically, grouping polls
        per client to avoid redundant API calls.

        Args:
            jobs:          Jobs to monitor. Defaults to all jobs in the session.
            target_states: Terminal states to wait for. Defaults to
                           [JobState.COMPLETED, JobState.FAILED, JobState.CANCELED].
            timeout:       Max seconds to wait total. None = wait forever.
            interval:      Seconds between poll rounds.
            verbose:       Print poll status to stdout each round.
            raw:           If True and verbose is True, also print raw status/messages from the provider.

        Returns:
            Dict of {job_name: JobStatus} for all jobs once settled.

        Raises:
            WaitTimeoutError: If timeout is reached before all jobs settle,
                              carrying the last known status for unsettled jobs.
        """
        from amscrot.client.job import JobState

        watch_jobs: List["Job"] = jobs if jobs is not None else list(self._jobs.values())

        if target_states is None:
            target_states = [JobState.COMPLETED, JobState.FAILED, JobState.CANCELED]

        # Normalise target_states to a set of string values for comparison
        target_set: Set[str] = {
            s.value if hasattr(s, "value") else s for s in target_states
        }

        # pending: {job_name -> job}, results: {job_name -> JobStatus}
        pending: Dict[str, "Job"] = {j.name: j for j in watch_jobs}
        results: Dict[str, Any] = {}

        start = time.monotonic()

        while pending:
            if timeout is not None and (time.monotonic() - start) >= timeout:
                # Capture last status for unsettled jobs before raising
                for job_name, job in pending.items():
                    sc = job.service_client
                    if sc:
                        try:
                            results[job_name] = sc.status(job)
                        except Exception:
                            pass
                raise WaitTimeoutError(results, target_states)

            # Group pending jobs by service_client
            by_client: Dict[Any, List[str]] = {}
            for job_name, job in pending.items():
                sc = job.service_client
                if sc is None:
                    raise ValueError(
                        f"Job '{job_name}' has no bound service_client -- cannot poll status."
                    )
                by_client.setdefault(sc, []).append((job_name, job))

            # Poll each client for its jobs
            settled_this_round: List[str] = []
            for sc, jobs_list in by_client.items():
                for job_name, job in jobs_list:
                    status = sc.status(job)
                    results[job_name] = status
                    # Update job.status to stay in sync with provider state
                    try:
                        job.set_status(status.state)
                    except (ValueError, KeyError):
                        pass  # state string may not map to JobState enum
                    if status.state in target_set:
                        settled_this_round.append(job_name)

            if verbose:
                summary_parts = []
                for n in sorted(results):
                    st = results[n]
                    state_str = st.state.value if hasattr(st.state, "value") else str(st.state)
                    part = f"{n}={state_str}"
                    if getattr(st, 'message', None):
                        part += f" ({st.message})"
                    if raw:
                        raw_parts = []
                        if getattr(st, 'provider_status', None):
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
                time.sleep(interval)

        return results

    def show(self, summary: bool = False) -> None:
        """Display session state from internal objects (no remote API calls).

        Args:
            summary: If True, print a concise overview. If False (default),
                     print the full session config YAML.
        """
        import yaml
        from amscrot.model.state import get_dumper

        if summary:
            print(f"Session: {self._name}")
            print(f"  Providers:       {len(self._providers)}")
            print(f"  Service Clients: {len(self._service_clients)}")
            print(f"  Nodes:           {len(self._nodes)}")
            print(f"  Networks:        {len(self._networks)}")
            print(f"  Services:        {len(self._services)}")
            print(f"  Jobs:            {len(self._jobs)}")

            if self._jobs:
                print("\n  Jobs:")
                for job in self._jobs.values():
                    sc_name = job.service_client.name if job.service_client else "none"
                    print(f"    {job.name}: status={job.status} id={job.id} service_client={sc_name}")
        else:
            config = self._build_config()
            print(yaml.dump(config, Dumper=get_dumper(), default_flow_style=False, sort_keys=False))

    def fetch_output_files(
        self,
        jobs: Optional[List["Job"]] = None,
        storage_resource_id: str = None,
        output_path: str = None,
    ) -> Dict[str, Dict[str, str]]:
        """Fetch remote stdout/stderr for completed jobs into the session directory.

        Args:
            jobs:                 Jobs to fetch files for. Defaults to all session jobs.
            storage_resource_id:  Storage resource to use for filesystem ops.
                                  If ``None``, auto-resolved per service client.
            output_path:          Override the base directory to write files into.
                                  Each job's files are written to ``<output_path>/<job_name>/``.
                                  Defaults to ``~/.amscrot/sessions/<name>/files/<job>/``.

        Returns ``{job_name: {"stdout": "<local_path>", ...}}``.
        """
        import os
        target_jobs: List["Job"] = jobs if jobs is not None else list(self._jobs.values())
        results: Dict[str, Dict[str, str]] = {}

        for job in target_jobs:
            sc = job.service_client
            if sc is None or not hasattr(sc, 'fetch_output_files'):
                continue

            if output_path is not None:
                dest = os.path.join(output_path, job.name)
            else:
                dest = self.files_path(job.name)
            fetched = sc.fetch_output_files(
                job=job,
                session_dir=dest,
                storage_resource_id=storage_resource_id,
            )
            if fetched:
                results[job.name] = fetched

        return results
