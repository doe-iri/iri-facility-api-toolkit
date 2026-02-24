import time
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
        self._providers = providers or []
        self._service_clients = service_clients or []
        self._nodes: List[Node] = []
        self._networks: List[Network] = []
        self._services: List[Service] = []
        self._jobs: List[Job] = []

    def add_node(self, *, label: str, provider: Provider, **kwargs) -> Node:
        node = Node(label, provider, **kwargs)
        self._nodes.append(node)
        return node

    def add_network(self, *, label: str, provider: Provider, **kwargs) -> Network:
        network = Network(label, provider, **kwargs)
        self._networks.append(network)
        return network

    def add_service(self, *, label: str, provider: Provider, **kwargs) -> Service:
        service = Service(label, provider, **kwargs)
        self._services.append(service)
        return service

    def add_job(self, job: "Job"):
        self._jobs.append(job)

    def add_provider(self, provider: Provider):
        self._providers.append(provider)
        
    def add_service_client(self, service_client: "ServiceClient"):
        self._service_clients.append(service_client)

    def _build_config(self) -> Dict:
        resources = []
        for n in self._nodes:
            resources.append(n.to_config('node'))
        for Net in self._networks:
            resources.append(Net.to_config('network'))
        for s in self._services:
            resources.append(s.to_config('service'))
            
        job_configs = []
        for j in self._jobs:
            job_configs.append(j.to_config())
            
        # Build provider config
        provider_configs = [p.to_config() for p in self._providers]
        
        # Build service client config
        service_client_configs = [sc.to_config() for sc in self._service_clients]
            
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
        
        print(yaml.dump(sanitized_config))
        
        # Use the original config content for the manager
        config_content = yaml.dump(config_list)
        return AmSCROTManager(config_content=config_content, jobs=self._jobs)
        
    def plan(self) -> Any:
        manager = self._get_manager()
        return manager.plan(session=self._name)

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

        Returns:
            Dict of {job_name: JobStatus} for all jobs once settled.

        Raises:
            WaitTimeoutError: If timeout is reached before all jobs settle,
                              carrying the last known status for unsettled jobs.
        """
        from amscrot.client.job import JobState

        watch_jobs: List["Job"] = jobs if jobs is not None else list(self._jobs)

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
                            results[job_name] = sc.status(job_name=job_name)
                        except Exception:
                            pass
                raise WaitTimeoutError(results, target_states)

            # Group pending jobs by service_client
            by_client: Dict[Any, List[str]] = {}
            for job_name, job in pending.items():
                sc = job.service_client
                if sc is None:
                    raise ValueError(
                        f"Job '{job_name}' has no bound service_client — cannot poll status."
                    )
                by_client.setdefault(sc, []).append(job_name)

            # Poll each client for its jobs
            settled_this_round: List[str] = []
            for sc, job_names in by_client.items():
                for job_name in job_names:
                    status = sc.status(job_name=job_name)
                    results[job_name] = status
                    if status.state in target_set:
                        settled_this_round.append(job_name)

            if verbose:
                summary = ", ".join(
                    f"{n}={results[n].state}" for n in sorted(results)
                )
                elapsed = time.monotonic() - start
                print(f"[wait] {elapsed:.1f}s — {summary}")

            for name in settled_this_round:
                del pending[name]

            if pending:
                time.sleep(interval)

        return results

    def show(self) -> Any:
        manager = self._get_manager()
        return manager.show(session=self._name)
