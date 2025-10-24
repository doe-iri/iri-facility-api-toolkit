from amscrot.util.parser import Parser
from amscrot.util.config_models import DependencyInfo
from amscrot.exceptions import ParseConfigException
from amscrot.exceptions import ResourceTypeNotSupported
import pytest


def test_malformed_node():
    yaml_str = '''
resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
            count: 2
          - extra:
            count: 2
provider:
  - fabric:
    - my_provider:
       - user: user1
    '''

    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)

def test_resources():
    yaml_str = '''
resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
            count: 2
      - my_node2:
          - provider: '{{ fabric.my_provider }}'
            count: 2
  - node:
      - my_node3:
          - provider: '{{ fabric.my_provider }}'
            count: 2
      - my_node4:
          - provider: '{{ fabric.my_provider }}'
            count: 2
provider:
  - fabric:
    - my_provider:
       - user: user1
    - my_other_provider:
       - user: user1
    '''

    providers, ordered_resources = Parser.parse(content=yaml_str)
    assert len(providers) == 2
    assert len(ordered_resources) == 4


def test_no_nodes_and_no_networks():
    yaml_str = '''
resource:
  - no_type:
      - my_no_type:
          - provider: '{{ fabric.my_provider }}'
provider:
  - fabric:
    - my_provider:
       - user: user1
    '''

    with pytest.raises(ResourceTypeNotSupported):
        Parser.parse(content=yaml_str)


def test_not_pointing_to_provider():
    yaml_str = '''
resource:
  - node:
      - my_node:
            - count: 2
provider:
  - fabric:
    - my_provider:
       - user: user1
    '''

    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_no_provider_node():
    yaml_str = '''
resource:
  - node:
      - my_node:
            - no_provider: '{{ fabric.my_provider }}'
            
provider:
  - fabric:
    - my_provider:
       - user: user1
    '''

    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_duplicate_providers():
    yaml_str = '''
provider:
  - fabric:
    - my_provider:
       - user: user1
  - fabric:
    - my_provider:
       - user: user2
    '''

    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_duplicate_nodes():
    yaml_str = '''
resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
            count: 2
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
            count: 5
provider:
  - fabric:
    - my_provider:
       - user: user1
    '''

    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_duplicate_node_across_providers():
    yaml_str = '''
resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider1 }}'
            count: 2
  - node:
      - my_node:
          - provider: '{{ chi.my_provider2 }}' 
          
provider:
  - fabric:
    - my_provider1:
       - user: user1
  - chi:
    - my_provider2:
       - user: user1
    '''

    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_duplicate_networks_across_providers():
    yaml_str = '''
resource:
  - network:
      - my_net:
          - provider: '{{ fabric.my_provider }}'
            count: 2
  - network:
      - my_net:
          - provider: '{{ chi.my_provider2 }}'

provider:
  - fabric:
    - my_provider:
       - user: user1
  - chi:
    - my_provider2:
       - user: user2
    '''

    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_duplicate_across_types():
    yaml_str = '''
resource:
  - node:
      - my_var:
          - provider: '{{ fabric.my_var }}'
            count: 2
  - network:
      - my_var:
          - provider: '{{ chi.my_provider2 }}'
provider:
  - fabric:
    - my_var:
       - user: user1
  - chi:
    - my_provider2:
       - user: user1
    '''

    Parser.parse(content=yaml_str)


def test_different_types():
    yaml_str = '''
resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
            count: 1
            up: True
            vlans: [1, 2]
            network:
              type: ipv4
              ip:
                - interface: eth0
provider:
  - fabric:
    - my_provider:
       - user: user1
        '''
    _, resources = Parser.parse(content=yaml_str)
    assert len(resources) == 1
    assert len(resources[0].dependencies) == 0


def test_missing_variable():
    yaml_str = '''
provider:
  - fabric:
    - my_provider:
       - user: '{{ var.user_name }}'
resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
    '''
    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_duplicate_variables():
    yaml_str = '''
variable:
  - slice_name:
      - default: "test_slice"
  - slice_name:
      - default: "user10"
provider:
  - fabric:
    - my_provider:
       - user: "some_user"
resource:
  - node:
      - my_node:
          - slice:  '{{ slice.my_slice }}'
  - slice:
      - my_slice:
          - provider: '{{ fabric.my_provider }}'
    '''
    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)


def test_variables():
    yaml_str = '''
variable:
  - provider_name:
      - default: "test_provider"
  - user_name:
      - default: "user10"
  - open_ports:
      - default: [22, 443]
  - groups:
      - default:
  - vlan:

provider:
  - fabric:
    - my_provider:
       - user: '{{ var.user_name }}'
         name: '{{ var.provider_name }}'

resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
            ports:  '{{ var.open_ports }}'
            vlan:   '{{ var.vlan }}'
            groups: '{{ var.groups }}'
    '''
    with pytest.raises(ParseConfigException):
        Parser.parse(content=yaml_str)

    # now let's inject some values for groups and vlan
    var_dict = dict(groups=['g1'], vlan=5)

    providers, resources = Parser.parse(content=yaml_str, var_dict=var_dict)
    assert providers[0].name == "test_provider"
    assert providers[0].attributes['user'] == 'user10'
    assert resources[0].attributes['ports'] == [22, 443]
    assert resources[0].attributes['vlan'] == 5
    assert resources[0].attributes['groups'] == ['g1']


def test_dependencies():
    yaml_str = '''
resource:
  - node:
      - my_node:
          - provider: '{{ fabric.my_provider }}'
            simple_attr: '{{ network.my_network.vlan }}'
            list_attr:  [ '{{ network.my_network.ip }}', '{{ network.my_network.port }}']
            complex_attr:
              type: '{{ network.my_network.subnet }}'
              ip:
                - interface: '{{ network.my_network.os_interface.mask }}'
  - network:
      - my_network:
          - provider: '{{ fabric.my_provider }}'
provider:
  - fabric:
    - my_provider:
       - user: user1
    '''
    providers, resources = Parser.parse(content=yaml_str)
    assert len(providers) == 1
    assert len(resources) == 2

    for resource in resources:
        if resource.is_node:
            assert len(resource.attributes) == 3
            assert list(resource.attributes.keys()) == ['simple_attr', 'list_attr', 'complex_attr']
            assert isinstance(resource.attributes['simple_attr'], DependencyInfo)
            assert len(resource.attributes['list_attr']) == 2
            assert len(resource.attributes['complex_attr']) == 2
            assert len(resource.dependencies) == 5
            keys = set()
            attributes = set()

            for dep in resource.dependencies:
                keys.add(dep.key)
                attributes.add(dep.attribute)

            assert keys == {'complex_attr.ip.interface', 'list_attr', 'simple_attr', 'complex_attr.type'}
            assert attributes == {'ip', 'port', 'vlan', 'os_interface.mask', 'subnet'}

            temp = list()
            temp.append(resource.attributes['simple_attr'])
            temp.extend(resource.attributes['list_attr'])
            adict = resource.attributes['complex_attr']
            temp.append(adict['type'])
            ip_dep = adict['ip'][0]
            temp.append(ip_dep['interface'])
            assert len(resource.dependencies) == len(temp)
            temp = [d for d in temp if not isinstance(d, DependencyInfo)]
            assert not temp
