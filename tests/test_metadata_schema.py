
import pytest
from amscrot.model.metadata import MetadataDump
from amscrot.serviceclient.serviceclient import ServiceClient

def test_load_metadata_schema():
    import os
    
    # Path to the example file
    json_path = os.path.join(os.path.dirname(__file__), '../examples/metadata/service_client_metadata.json')
    
    with open(json_path, 'r') as f:
        json_content = f.read()
        
    # Validation logic
    metadata = MetadataDump.model_validate_json(json_content)
    
    assert len(metadata.services) == 3
    assert len(metadata.service_clients) == 3
    assert len(metadata.groups) == 3
    assert len(metadata.policies) == 3
    
    # Verify HPC Client
    hpc = next(c for c in metadata.service_clients if c.name == 'hpc-simulation-service')
    assert hpc.serviceRef == 'weather-sim-v2'
    assert len(hpc.facilities) == 2
    
    # Verify Policy
    policy = metadata.policies['hpc-simulation-service']
    assert policy.preference == 900
    assert policy.group == 'research-team-a'
    
    # Verify Facility content
    facility = hpc.facilities[0]
    assert facility.name == 'supercomputer-alpha'
    assert len(facility.compute) == 1
    assert facility.compute[0].nodes == 4
    
    # Verify L3 Network
    assert facility.networks[0].layer3.ipv4_subnets[0] == '10.100.0.0/16'
    assert facility.networks[0].layer3.bgp_peers[0].asn == 65001
    
    assert len(facility.storage) == 1
    assert facility.storage[0].type == 'lustre'
    
    # Verify K8s Client
    k8s = next(c for c in metadata.service_clients if c.name == 'web-api-backend')
    assert k8s.facilities[0].compute[0].resources['requests']['cpu'] == '2000m'
    # Verify L2 Network
    assert k8s.facilities[0].networks[0].layer2.vlan_id == 105

    # Verify Service Reference Integrity (manual check in test)
    service_names = {s.name for s in metadata.services}
    for client in metadata.service_clients:
        assert client.serviceRef in service_names
