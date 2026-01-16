from typing import Dict, List, Any, TYPE_CHECKING, Union
from amscrot.amscrot_manager import AmSCROTManager

if TYPE_CHECKING:
    from .client import Client
    from .job import Job

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
    def __init__(self, label: str, provider: Union[str, Provider], **kwargs):
        self.label = label
        if isinstance(provider, Provider):
            self.provider = str(provider)
        else:
            self.provider = provider
        
        # Resolve attributes
        self.attributes = {}
        for k, v in kwargs.items():
            self.attributes[k] = self._resolve_attribute(v)

    def _resolve_attribute(self, value: Any) -> Any:
        if isinstance(value, (Resource, Provider)):
            return str(value)
        elif isinstance(value, list):
            return [self._resolve_attribute(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._resolve_attribute(v) for k, v in value.items()}
        return value

    def to_config(self, resource_type: str) -> Dict:
        attrs = self.attributes.copy()
        attrs['provider'] = self.provider
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
    def __init__(self, label: str, provider: Union[str, Provider], controller: Union[str, Node] = None, **kwargs):
        if controller:
            kwargs['controller'] = controller
        super().__init__(label, provider, **kwargs)

    def __str__(self):
        return f"{{{{ service.{self.label} }}}}"


class Session:
    def __init__(self, client: "Client", name: str):
        if not client:
             raise ValueError("client argument is required")
        self._client = client
        self._name = name
        self._nodes: List[Node] = []
        self._networks: List[Network] = []
        self._services: List[Service] = []
        self._jobs: List[Job] = []

    def add_node(self, *, label: str, provider: Union[str, Provider], **kwargs) -> Node:
        node = Node(label, provider, **kwargs)
        self._nodes.append(node)
        return node

    def add_network(self, *, label: str, provider: Union[str, Provider], **kwargs) -> Network:
        network = Network(label, provider, **kwargs)
        self._networks.append(network)
        return network

    def add_service(self, *, label: str, provider: Union[str, Provider], **kwargs) -> Service:
        service = Service(label, provider, **kwargs)
        self._services.append(service)
        return service

    def add_job(self, job: "Job"):
        self._jobs.append(job)

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
            
        # Build provider config from client's Provider objects
        provider_configs = [p.to_config() for p in self._client._providers]
            
        return {
            'provider': provider_configs,
            'resource': resources,
            'job': job_configs
        }

    def _get_manager(self) -> AmSCROTManager:
        import yaml
        config_list = self._build_config()
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

    def show(self) -> Any:
        manager = self._get_manager()
        return manager.show(session=self._name)
