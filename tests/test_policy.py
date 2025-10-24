from amscrot.policy.policy_helper import *


def test_policy_with_site_and_no_site():
    yaml_str = '''
fabric:
  stitch-port:
      - name: AAA
        member-of:
          - UTAH
        profile: prof1
        preference: 10
        site: sitea
      - name: BBB
        member-of:
          - UTAH
        profile: prof2
        preference: 100
        site: siteb
  group:
      - name: UTAH
        consumer-for:
          - cloudlab        
cloudlab:
  stitch-port:
      - name: AAA
        member-of:
          - UTAH
        device_name: dev1
      - name: BBB
        member-of:
          - UTAH
        device_name: dev2
  group:
    - name: UTAH
      producer-for:
        - fabric
    '''

    policy = load_policy(content=yaml_str)
    stitch_info = find_stitch_port(policy=policy,
                                   providers=['cloudlab', 'fabric'])

    stitch_port = stitch_info.stitch_port
    assert stitch_port['name'] == 'BBB'
    assert stitch_port.get('device_name') == 'dev2' or stitch_port['peer']['device_name'] == 'dev2'
    assert stitch_info.producer == 'cloudlab'
    assert stitch_info.consumer == 'fabric'

    policy = load_policy(content=yaml_str)
    stitch_info = find_stitch_port(policy=policy,
                                   providers=['cloudlab', 'fabric'], site='sitea')

    stitch_port = stitch_info.stitch_port
    assert stitch_port['name'] == 'AAA'
    assert stitch_port.get('device_name') == 'dev1' or stitch_port['peer']['device_name'] == 'dev1'
    assert stitch_info.producer == 'cloudlab'
    assert stitch_info.consumer == 'fabric'


def test_peering_and_duplicates():
    yaml_str = '''
fabric:
  stitch-port:
      - name: AAA
        member-of:
          - AWS
        device_name: dev1
      - name: AAA
        member-of:
            - AWS
        device_name: dev1
  group:
      - name: AWS
        producer-for:
          - sense
sense:
  stitch-port:
      - name: AAA
        member-of:
          - AWS
        region:
        device_name: dev3
        local_name: TenGigE0/0/0/11/3
  group:
      - name: AWS 
        profile: FABRIC-AWS-DX-VGW
        consumer-for:
          - fabric
        producer-for:
          - fabric
    '''

    policy = load_policy(content=yaml_str)
    stitch_infos = find_stitch_port_for_providers(policy, ['sense', 'fabric'])
    assert len(stitch_infos) == 2
    stitch_infos = peer_stitch_ports(stitch_infos)
    assert len(stitch_infos) == 1


def load_local_policy_using(providers):
    from amscrot.policy.policy_helper import load_policy

    policy = load_policy()

    from amscrot.policy.policy_helper import find_stitch_port_for_providers, peer_stitch_ports

    stitch_infos = find_stitch_port_for_providers(policy, providers)
    stitch_infos = peer_stitch_ports(stitch_infos)
    attrs = ["preference", "member-of", 'name']
    names = []

    for stitch_info in stitch_infos:
        names.append(stitch_info.stitch_port.get("name"))

        for attr in attrs:
            stitch_info.stitch_port.pop(attr, None)

        peer = stitch_info.stitch_port.get('peer', {})

        for attr in attrs:
            peer.pop(attr, None)

    import yaml
    from amscrot.util.constants import Constants

    for i, stitch_info in enumerate(stitch_infos):
        producer = stitch_info.producer
        consumer = stitch_info.consumer
        stitch_port = stitch_info.stitch_port
        c = {"config": [{Constants.NETWORK_STITCH_CONFIG: [{f"si_from_{names[i]}": {"producer": producer,
                                                                                    "consumer": consumer,
                                                                                    "stitch_port": stitch_port}}]}]}
        rep = yaml.dump(c, default_flow_style=False, sort_keys=False)
        rep = rep.replace('\n', '\n  ')
        print(rep)
    return stitch_infos


def test_load_local_policy_using_sense():
    providers = ['sense', 'fabric']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 2 
    providers = ['fabric', 'sense']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 2 


def test_load_local_policy_using_chi():
    providers = ['chi', 'fabric']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 3
    providers = ['fabric', 'chi']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 3


def test_load_local_policy_using_clab():
    providers = ['cloudlab', 'fabric']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 2
    providers = ['cloudlab', 'fabric']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 2


def test_load_local_policy_using_aws():
    providers = ['aws', 'fabric']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 1 
    providers = ['fabric', 'aws']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 1 


def test_load_local_policy_using_gcp():
    providers = ['gcp', 'fabric']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 1
    providers = ['fabric', 'gcp']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 1


def test_load_local_policy_zero():
    providers = ['gcp', 'aws']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 0
    providers = ['sense', 'chi']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 0
    providers = ['cloudlab', 'sense']
    stitch_infos = load_local_policy_using(providers)
    assert len(stitch_infos) == 0
