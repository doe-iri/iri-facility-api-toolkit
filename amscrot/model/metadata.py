from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field



# -- Common base -------------------------------------------------------------

class ResourceBase(BaseModel):
    """Common fields shared by all first-class resource metadata objects."""
    id: Optional[str] = None
    name: Optional[str] = None
    group: Optional[str] = None
    description: Optional[str] = None
    capabilities: Optional[List[str]] = None


# -- Resource Models ----------------------------------------------------------

class Compute(ResourceBase):
    # Common / Shared
    architecture: Optional[str] = None
    cores: Optional[int] = None
    memory: Optional[str] = None
    
    # HPC Specific
    partition: Optional[str] = None
    nodes: Optional[int] = None
    tasks_per_node: Optional[int] = None
    gpus_per_node: Optional[int] = None
    gpu_type: Optional[str] = None
    memory_per_node: Optional[str] = None
    cpu_arch: Optional[str] = None

    # K8s Specific
    resources: Optional[Dict[str, Dict[str, str]]] = None # requests/limits
    replicas: Optional[int] = None
    node_selector: Optional[Dict[str, str]] = None
    container_runtime: Optional[str] = None


class Storage(ResourceBase):
    # Common
    type: Optional[str] = None # lustre, nfs, ebs
    mount_point: Optional[str] = None
    quota: Optional[str] = None
    
    # HPC Specific
    performance_tier: Optional[str] = None
    
    # K8s Specific
    kind: Optional[str] = None # PersistentVolumeClaim
    storage_class: Optional[str] = None
    size: Optional[str] = None
    access_modes: Optional[List[str]] = None


class BGPPeer(BaseModel):
    asn: int
    peer_ip: str
    local_ip: Optional[str] = None
    md5_auth: Optional[str] = None


class Layer2(BaseModel):
    vlan_ranges: Optional[List[str]] = None
    vlan_id: Optional[int] = None
    mtu: Optional[int] = None
    port_name: Optional[str] = None


class Layer3(BaseModel):
    ipv4_subnets: Optional[List[str]] = None
    ipv6_subnets: Optional[List[str]] = None
    bgp_peers: Optional[List[BGPPeer]] = None
    gateway: Optional[str] = None


class Network(ResourceBase):
    # HPC
    fabric: Optional[str] = None
    rdma_enabled: Optional[bool] = None
    external_connectivity: Optional[str] = None
    
    # K8s
    service: Optional[Dict[str, Any]] = None
    ingress: Optional[Dict[str, Any]] = None
    
    # Edge
    interface: Optional[str] = None
    bandwidth_limit: Optional[str] = None
    latency_tolerance: Optional[str] = None
    offline_support: Optional[bool] = None

    # Advanced L2/L3
    layer2: Optional[List[Layer2]] = None
    layer3: Optional[List[Layer3]] = None


class Allocation(ResourceBase):
    account: Optional[str] = None
    qos: Optional[str] = None
    walltime_limit: Optional[str] = None
    exclusive: Optional[bool] = None


class Data(ResourceBase):
    caching_policy: Optional[str] = None
    sync_interval: Optional[str] = None
    retention_policy: Optional[str] = None


class Operation(ResourceBase):
    strategy: Optional[str] = None
    max_unavailable: Optional[str] = None
    max_surge: Optional[str] = None


# -- Project / Allocation Hierarchy -------------------------------------------

class AllocationEntry(BaseModel):
    """A single allocation/usage entry (e.g. node_hours, bytes)."""
    allocation: Optional[float] = None
    usage: Optional[float] = None
    unit: Optional[str] = None


class UserAllocation(BaseModel):
    """A per-user slice of a project allocation."""
    id: Optional[str] = None
    user_id: Optional[str] = None
    entries: Optional[List[AllocationEntry]] = None


class ProjectAllocation(BaseModel):
    """A project-level allocation linked to a capability (cpu, gpu, storage)."""
    id: Optional[str] = None
    capability: Optional[str] = None
    entries: Optional[List[AllocationEntry]] = None
    user_allocations: Optional[List[UserAllocation]] = None


class Project(BaseModel):
    """A project with its allocations and user-level breakdowns."""
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    user_ids: Optional[List[str]] = None
    allocations: Optional[List[ProjectAllocation]] = None

    def get_allocations_by_capability(self, capability: str) -> List["ProjectAllocation"]:
        """Filter project allocations by capability type (e.g. 'cpu', 'gpu')."""
        return [a for a in (self.allocations or []) if a.capability == capability]

    def get_user_allocations(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get user-level allocation summaries.

        When *user_id* is ``None`` every user allocation is returned.
        Each item is a dict with ``capability``, ``user_id``, and ``entries``.
        """
        results: List[Dict[str, Any]] = []
        for pa in (self.allocations or []):
            for ua in (pa.user_allocations or []):
                if user_id is None or ua.user_id == user_id:
                    results.append({
                        'capability': pa.capability,
                        'user_id': ua.user_id,
                        'entries': [
                            e.model_dump(exclude_none=True)
                            for e in (ua.entries or [])
                        ],
                    })
        return results


class Facility(ResourceBase):
    name: str  # required -- overrides the optional base field
    compute: Optional[List[Compute]] = None
    storage: Optional[List[Storage]] = None
    networks: Optional[List[Network]] = None
    allocations: Optional[List[Allocation]] = None
    projects: Optional[List[Project]] = None
    operations: Optional[List[Operation]] = None
    data: Optional[List[Data]] = None

    def get_project(self, name: str) -> Optional["Project"]:
        """Look up a project by name (case-insensitive)."""
        for p in (self.projects or []):
            if p.name and p.name.lower() == name.lower():
                return p
        return None

    def get_resources_by_group(
        self, group: str,
    ) -> Dict[str, List["ResourceBase"]]:
        """Return compute, storage, and network resources in a group.

        Args:
            group: Group name such as 'perlmutter' or 'retired' (case-insensitive).

        Returns:
            Dict keyed by resource category ('compute', 'storage', 'networks')
            containing matching resources. Categories with no matches are
            omitted.
        """
        result: Dict[str, List[ResourceBase]] = {}
        target = group.lower()

        compute = [c for c in (self.compute or [])
                   if c.group and c.group.lower() == target]
        if compute:
            result["compute"] = compute

        storage = [s for s in (self.storage or [])
                   if s.group and s.group.lower() == target]
        if storage:
            result["storage"] = storage

        networks = [n for n in (self.networks or [])
                    if n.group and n.group.lower() == target]
        if networks:
            result["networks"] = networks

        return result

    def resources_for_project(
        self,
        project_name: Optional[str] = None,
    ) -> Dict[str, Dict[str, List["ResourceBase"]]]:
        """Return the compute/storage resources accessible per capability for a project.

        Combines project allocation capabilities with the resource capability
        mapping to answer: *"which actual resources can this project use?"*

        Args:
            project_name: Filter to a specific project (case-insensitive).
                If ``None``, returns resources for **all** projects.

        Returns:
            Dict keyed by project name -> capability -> resource category -> resource list.
            Only resource categories with matches are included.

        Example::

            fac.resources_for_project('mpesnet')
            # -> {'mpesnet': {
            #       'cpu': {'compute': [Compute(name='compute', ...)]},
            #       'gpfs_storage': {'storage': [Storage(name='homes', ...), ...]},
            #   }}
        """
        projects = self.projects or []
        if project_name is not None:
            proj = self.get_project(project_name)
            projects = [proj] if proj else []

        output: Dict[str, Dict[str, List[ResourceBase]]] = {}
        for proj in projects:
            proj_key = proj.name or proj.id or "unknown"
            cap_map: Dict[str, List[ResourceBase]] = {}
            for pa in (proj.allocations or []):
                cap = pa.capability
                if cap and cap not in cap_map:
                    res_map: Dict[str, List[ResourceBase]] = {}
                    compute = [c for c in (self.compute or [])
                               if c.capabilities and cap in c.capabilities]
                    if compute:
                        res_map['compute'] = compute
                    storage = [s for s in (self.storage or [])
                               if s.capabilities and cap in s.capabilities]
                    if storage:
                        res_map['storage'] = storage

                    if res_map:
                        cap_map[cap] = res_map
            if cap_map:
                output[proj_key] = cap_map

        return output


# Service Models

class Service(BaseModel):
    name: str
    endpoint_uri: str
    status: str
    capabilities: Optional[List[str]] = None
    allocated: Optional[bool] = None


class Group(BaseModel):
    name: str


class Policy(BaseModel):
    profile: str
    group: str
    preference: int = Field(ge=0, le=1000)


class ServiceClient(BaseModel):
    name: str
    serviceRef: str # Reference to Service.name
    facilities: List[Facility]


class MetadataDump(BaseModel):
    groups: List[Group]
    policies: Dict[str, Policy]
    services: List[Service]
    service_clients: List[ServiceClient]
