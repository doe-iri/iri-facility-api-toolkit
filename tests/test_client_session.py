
import pytest
from amscrot.client import Client, Session

def test_client_create_session():
    client = Client()
    session = client.create_session("test_session")
    assert isinstance(session, Session)
    assert session._client == client
    assert session._name == "test_session"

def test_session_config_inheritance():
    client = Client()
    client.add_provider(label="my_aws", type="aws", region="us-east-1")
    
    session = client.create_session("test_session")
    session.add_node(label="my_vm", provider="my_aws", image="ami-123")
    
    config = session._build_config()
    
    # Check provider from client is in config
    assert len(config['provider']) == 1
    # provider config structure is [{type: [{label: attrs}]}]
    assert config['provider'][0]['aws'][0]['my_aws']['region'] == 'us-east-1'
    
    # Check resource from session is in config
    assert len(config['resource']) == 1
    assert config['resource'][0]['node'][0]['my_vm']['image'] == 'ami-123'
    assert config['resource'][0]['node'][0]['my_vm']['provider'] == 'my_aws'

def test_create_session_isolation():
    client = Client()
    s1 = client.create_session("s1")
    s2 = client.create_session("s2")
    
    s1.add_node(label="vm1", provider="p", image="v1")
    s2.add_node(label="vm2", provider="p", image="v2")
    
    c1 = s1._build_config()
    c2 = s2._build_config()
    
    assert len(c1['resource']) == 1
    assert c1['resource'][0]['node'][0]['vm1']['image'] == 'v1'
    
    assert len(c2['resource']) == 1
    assert c2['resource'][0]['node'][0]['vm2']['image'] == 'v2'

def test_add_network_and_service():
    client = Client()
    session = client.create_session("s_net")
    
    session.add_network(label="net1", provider="aws", cidr="10.0.0.0/16")
    session.add_service(label="svc1", provider="k8s", replicas=3)
    
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
