from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field

# Resource Models
class Compute(BaseModel):
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


class Storage(BaseModel):
    # Common
    name: Optional[str] = None
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


class Layer3(BaseModel):
    ipv4_subnets: Optional[List[str]] = None
    ipv6_subnets: Optional[List[str]] = None
    bgp_peers: Optional[List[BGPPeer]] = None
    gateway: Optional[str] = None


class Network(BaseModel):
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
    layer2: Optional[Layer2] = None
    layer3: Optional[Layer3] = None


class Allocation(BaseModel):
    account: Optional[str] = None
    qos: Optional[str] = None
    walltime_limit: Optional[str] = None
    exclusive: Optional[bool] = None


class Data(BaseModel):
    caching_policy: Optional[str] = None
    sync_interval: Optional[str] = None
    retention_policy: Optional[str] = None


class Operation(BaseModel):
    strategy: Optional[str] = None
    max_unavailable: Optional[str] = None
    max_surge: Optional[str] = None


class Facility(BaseModel):
    name: str
    description: Optional[str] = None
    compute: Optional[List[Compute]] = None
    storage: Optional[List[Storage]] = None
    networks: Optional[List[Network]] = None
    allocations: Optional[List[Allocation]] = None
    operations: Optional[List[Operation]] = None
    data: Optional[List[Data]] = None


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
