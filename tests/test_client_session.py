
import pytest
from amscrot.client import Client, Session

def test_client_create_session():
    client = Client()
    session = client.create_session("test_session")
    assert isinstance(session, Session)
    assert session._name == "test_session"

def test_session_config_inheritance():
    client = Client()
    p = client.add_provider(label="my_aws", type="aws", region="us-east-1")
    
    session = client.create_session("test_session")
    session.add_node(label="my_vm", provider=p, image="ami-123")
    
    config = session._build_config()
    
    # Check provider from client is in config
    assert len(config['provider']) == 1
    # provider config structure is [{type: [{label: attrs}]}]
    assert config['provider'][0]['aws'][0]['my_aws']['region'] == 'us-east-1'
    
    # Check resource from session is in config
    assert len(config['resource']) == 1
    assert config['resource'][0]['node'][0]['my_vm']['image'] == 'ami-123'
    # Check resource from session is in config
    assert len(config['resource']) == 1
    assert config['resource'][0]['node'][0]['my_vm']['image'] == 'ami-123'
    assert config['resource'][0]['node'][0]['my_vm']['provider'] == '{{ aws.my_aws }}'

def test_session_service_client_config():
    client = Client()
    
    # Mock a ServiceClient
    class MockServiceClient:
        def __init__(self, name, type):
            self.name = name
            self.type = type
        def to_config(self):
            return {'service_client': [{self.name: {'type': self.type}}]}
            
    sc = MockServiceClient("sc1", "mock")
    client.add_service_client(sc)
            
    session = client.create_session("test_session")
    
    config = session._build_config()
    assert len(config['service_client']) == 1
    assert config['service_client'][0]['service_client'][0]['sc1']['type'] == 'mock'

def test_create_session_isolation():
    client = Client()
    p = client.add_provider(label="p", type="test", region="us-east-1")

    s1 = client.create_session("s1")
    s2 = client.create_session("s2")
    
    s1.add_node(label="vm1", provider=p, image="v1")
    s2.add_node(label="vm2", provider=p, image="v2")
    
    c1 = s1._build_config()
    c2 = s2._build_config()
    
    assert len(c1['resource']) == 1
    assert c1['resource'][0]['node'][0]['vm1']['image'] == 'v1'
    
    assert len(c2['resource']) == 1
    assert c2['resource'][0]['node'][0]['vm2']['image'] == 'v2'

def test_add_network_and_service():
    client = Client()
    p_aws = client.add_provider(label="aws", type="aws")
    p_k8s = client.add_provider(label="k8s", type="k8s")
    session = client.create_session("s_net")
    
    session.add_network(label="net1", provider=p_aws, cidr="10.0.0.0/16")
    session.add_service(label="svc1", provider=p_k8s, replicas=3)
    
    config = session._build_config()
    
    assert len(config['resource']) == 2
    
    # Verify Network
    # implementation appends Node then Network then Service
    
    net_res = config['resource'][0]
    assert 'network' in net_res
    assert net_res['network'][0]['net1']['cidr'] == "10.0.0.0/16"
    
    svc_res = config['resource'][1]
    assert 'service' in svc_res
    assert svc_res['service'][0]['svc1']['replicas'] == 3
