from collections import namedtuple
from typing import Dict, List

from amscrot.exceptions import StitchPortNotFound, AmSCROTException
from amscrot.util.constants import Constants

MEMBER_OF = 'member-of'
STITCH_PORT = 'stitch-port'
GROUP = 'group'
PRODUCER_FOR = 'producer-for'
CONSUMER_FOR = 'consumer-for'
PEER = 'peer'


class BadStitchPortException(AmSCROTException):
    """Base class for other exceptions"""
    pass


class ProviderPolicy:
    def __init__(self, *, type, stitch_ports, groups):
        self.type = type
        self.stitch_ports = stitch_ports

        for group in groups:
            if CONSUMER_FOR not in group:
                group[CONSUMER_FOR] = []
            if PRODUCER_FOR not in group:
                group[PRODUCER_FOR] = []

        self.groups = groups

    def __str__(self) -> str:
        lst = ["stitch_ports=" + str(self.stitch_ports), "groups=" + str(self.groups)]
        return str(lst)

    def __repr__(self) -> str:
        return self.__str__()


DetailedStitchInfo = namedtuple("DetailedStitchInfo", "stitch_port producer consumer producer_group consumer_group")
StitchInfo = namedtuple("StitchInfo", "stitch_port producer consumer")


def parse_policy(policy, policy_details, fp_dict=None) -> Dict[str, ProviderPolicy]:
    for k, v in policy.items():
        stitch_ports = v[STITCH_PORT] if STITCH_PORT in v else []
        effective_stitch_ports = []

        for stitch_port in stitch_ports:
            if not stitch_port.get('name'):
                raise BadStitchPortException(f"stitch port must have a name", stitch_port)

            stitch_port[Constants.PROVIDER] = k

            if 'preference' not in stitch_port:
                stitch_port['preference'] = 0

            handled_by_remote = False

            if fp_dict and stitch_port.get('profile') in fp_dict and fp_dict[stitch_port['profile']]:
                handled_by_remote = True
                fp_list = fp_dict[stitch_port['profile']]

                for detail in fp_list:
                    effective_stitch_port = stitch_port.copy()
                    effective_stitch_port.update(vars(detail))
                    effective_stitch_ports.append(effective_stitch_port)

            if handled_by_remote:
                continue

            if stitch_port.get('profile') and k in policy_details and policy_details[k] and stitch_port['profile'] in \
                    policy_details[k]:
                port_detail = policy_details[k][stitch_port['profile']]
                if isinstance(port_detail, list):
                    for detail in port_detail:
                        if not detail.get('name') or detail.get('name') == stitch_port['name']:
                            effective_stitch_port = stitch_port.copy()
                            effective_stitch_port.update(detail)
                            effective_stitch_ports.append(effective_stitch_port)
                else:
                    if not port_detail.get('name') or port_detail.get('name') == stitch_port['name']:
                        effective_stitch_port = stitch_port  # TODO
                        effective_stitch_port.update(port_detail)
                        effective_stitch_ports.append(effective_stitch_port)
            else:
                effective_stitch_port = stitch_port  # TODO
                effective_stitch_ports.append(effective_stitch_port)

        groups = v[GROUP] if GROUP in v else []

        for g in groups:
            g[Constants.PROVIDER] = k

        policy[k] = ProviderPolicy(type=k, stitch_ports=effective_stitch_ports, groups=groups)

    return policy


def load_remote_policy() -> Dict[str, ProviderPolicy]:
    from fabrictestbed_extensions.fablib.fablib import fablib
    from types import SimpleNamespace

    facility_ports = fablib.get_facility_ports()
    fp_dict = {}

    for fp in facility_ports.topology.facilities.values():
        for iface in fp.interface_list:
            local_name = iface.labels.local_name if iface.labels and iface.labels.local_name else None
            device_name = iface.labels.device_name if iface.labels and iface.labels.device_name else None
            region = iface.labels.region if iface.labels and iface.labels.region else None
            vlan_range = iface.labels.vlan_range if iface.labels else []
            fp_ns = SimpleNamespace(site=fp.site, local_name=local_name, device_name=device_name,
                                    region=region, vlan_range=vlan_range)

            fp_list = fp_dict.get(fp.name)

            if not fp_list:
                fp_list = []
                fp_dict[fp.name] = fp_list

            fp_list.append(fp_ns)

    policy = fablib.get_stitching_policy()
    policy_details = get_facility_ports()
    return parse_policy(policy, policy_details, fp_dict)


def load_policy(*, policy_file=None, content=None, load_details=True) -> Dict[str, ProviderPolicy]:
    import os
    import yaml
    import json

    if content:
        policy = yaml.safe_load(content)
        return parse_policy(policy, dict())

    if not policy_file:
        policy_file = os.path.join(os.path.dirname(__file__), 'stitching_policy.json')

    with open(policy_file, 'r') as fp:
        if policy_file.endswith(".json"):
            policy = json.load(fp)
        else:
            policy = yaml.load(fp, Loader=yaml.FullLoader)

    if load_details:
        policy_details = get_facility_ports()
        return parse_policy(policy, policy_details)
    else:
        return parse_policy(policy, dict())


def get_facility_ports():
    import os
    import json

    port_file = os.path.join(os.path.dirname(__file__), "stitching_policy_details.json")
    with open(port_file, 'r') as fp:
        ports = json.load(fp)
    return ports


def find_stitch_port_for_providers(policy: Dict[str, ProviderPolicy], providers: List[str]) -> List[DetailedStitchInfo]:
    provider1 = providers[0]
    provider2 = providers[1]
    stitch_infos = []

    for g in policy[provider1].groups:
        if provider2 in g[CONSUMER_FOR]:  # provider1's group is a consumer, find provider2's groups that are producers
            for producer_group in policy[provider2].groups:
                if provider1 in producer_group[PRODUCER_FOR]:
                    if g['name'] != producer_group['name']:
                        continue

                    for stitch_port in policy[g['provider']].stitch_ports:
                        if g['name'] in stitch_port[MEMBER_OF]:
                            stitch_info = DetailedStitchInfo(stitch_port=stitch_port,
                                                             producer=producer_group[Constants.PROVIDER],
                                                             consumer=g[Constants.PROVIDER],
                                                             producer_group=producer_group,
                                                             consumer_group=g)

                            stitch_infos.append(stitch_info)

                    for stitch_port in policy[producer_group['provider']].stitch_ports:
                        if producer_group['name'] in stitch_port[MEMBER_OF]:
                            stitch_info = DetailedStitchInfo(stitch_port=stitch_port,
                                                             producer=producer_group[Constants.PROVIDER],
                                                             consumer=g[Constants.PROVIDER],
                                                             producer_group=producer_group,
                                                             consumer_group=g)

                            stitch_infos.append(stitch_info)

        if provider2 in g[PRODUCER_FOR]:   # provider2's group is a producer find provider2's groups that are consumers
            for consumer_group in policy[provider2].groups:
                if provider1 in consumer_group[CONSUMER_FOR]:
                    if g['name'] != consumer_group['name']:
                        continue

                    for stitch_port in policy[g['provider']].stitch_ports:
                        if g['name'] in stitch_port[MEMBER_OF]:
                            stitch_info = DetailedStitchInfo(stitch_port=stitch_port,
                                                             producer=g[Constants.PROVIDER],
                                                             consumer=consumer_group[Constants.PROVIDER],
                                                             producer_group=g,
                                                             consumer_group=consumer_group)
                            stitch_infos.append(stitch_info)

                    for stitch_port in policy[consumer_group['provider']].stitch_ports:
                        if consumer_group['name'] in stitch_port[MEMBER_OF]:
                            stitch_info = DetailedStitchInfo(stitch_port=stitch_port,
                                                             producer=g[Constants.PROVIDER],
                                                             consumer=consumer_group[Constants.PROVIDER],
                                                             producer_group=g,
                                                             consumer_group=consumer_group)
                            stitch_infos.append(stitch_info)

    stitch_infos.sort(key=lambda sinfo: sinfo.stitch_port['preference'], reverse=True)
    removed_duplicates_stitch_infos = []

    for si in stitch_infos:
        found = False
        for csi in removed_duplicates_stitch_infos:
            if si.consumer == csi.consumer and si.producer == csi.producer and si.stitch_port == csi.stitch_port:
                found = True
                break

        if not found:
            removed_duplicates_stitch_infos.append(si)

    return removed_duplicates_stitch_infos


def check_options(k, v, adict):
    temp = adict.get('option')

    if temp:
        assert isinstance(temp, dict), "option must be a dictionary"

        if temp.get(k):
            if isinstance(v, str) and v == temp.get(k):
                return True, {(k, v)}

            if isinstance(v, list):
                for v_pair in v:
                    aset = set(v_pair.items())

                    if isinstance(temp.get(k), list):
                        for t_pair in temp.get(k):
                            bset = set(t_pair.items())

                            if aset.issubset(bset):
                                return True, aset

    return False, None


def peer_stitch_ports(stitch_infos: List[DetailedStitchInfo]):
    stitch_ports = []

    for si in stitch_infos:
        stitch_ports.append(si.stitch_port)

    effective_stitch_infos = []
    for si in stitch_infos:
        stitch_port = si.stitch_port
        stitch_port_provider = stitch_port['provider']
        stitch_port_providers = list(sorted([si.producer, si.consumer]))

        for sp in stitch_ports:
            if sp['provider'] == stitch_port_provider \
                    or sp['provider'] not in stitch_port_providers:
                continue

            if sp['provider'] != stitch_port_providers[0]:
                continue

            if stitch_port['name'] != sp['name']:
                continue

            acopy = stitch_port.copy()
            acopy['peer'] = sp.copy()
            effective_stitch_info = DetailedStitchInfo(stitch_port=acopy,
                                                       producer=si.producer,
                                                       consumer=si.consumer,
                                                       producer_group=si.producer_group,
                                                       consumer_group=si.consumer_group)
            effective_stitch_infos.append(effective_stitch_info)

    return effective_stitch_infos


def find_stitch_port(*, policy: Dict[str, ProviderPolicy], providers: List[str], site=None,
                     profile=None, options=None) -> DetailedStitchInfo or None:
    from amscrot.util.utils import get_logger

    logger = get_logger()
    stitch_infos = find_stitch_port_for_providers(policy, providers)
    stitch_infos = peer_stitch_ports(stitch_infos)

    logger.info(f"Found {len(stitch_infos)} stitch ports")

    if options:
        logger.info(f"Got options {options}")

        for k, v in options.items():
            for stitch_info in stitch_infos:
                if k == 'port_name':
                    k = 'name'

                stitch_ports = [stitch_info.stitch_port]

                if stitch_info.stitch_port.get('peer'):
                    stitch_ports.append(stitch_info.stitch_port.get('peer'))

                for stitch_port in stitch_ports:
                    if stitch_port.get(k) == v:
                        logger.info(f"Using stitch port based on port: {k}={v} and providers={providers}:{stitch_info}")
                        return stitch_info

                    ret, aset = check_options(k, v, stitch_port)

                    if ret:
                        logger.info(
                            f"Using stitch port based on port: {aset} and providers={providers}:{stitch_info}")
                        return stitch_info

                for g in [stitch_info.consumer_group, stitch_info.producer_group]:
                    if k == 'group_name':
                        k = 'name'

                    if g.get(k) == v:
                        logger.info(
                            f"Using stitch port based on group: {k}={v} and providers={providers}:{stitch_info}")

                        return stitch_info

                    ret, aset = check_options(k, v, g)

                    if ret:
                        logger.info(
                            f"Using stitch port based on group: {aset} and providers={providers}:{stitch_info}")
                        return stitch_info

            logger.warning(f"No stitch port based on {k}={v}")

        logger.info(f"Done with options {options}")

    if profile:
        for stitch_info in stitch_infos:
            if profile == stitch_info.stitch_port.get(Constants.RES_PROFILE):
                logger.info(f"Using stitch port based on profile={profile} and providers={providers}:{stitch_info}")
                return stitch_info

    if site:
        for stitch_info in stitch_infos:
            if site == stitch_info.stitch_port.get('site'):
                logger.info(f"Using stitch port based on site={site} and providers={providers}:{stitch_info}")
                return stitch_info

        logger.warning(f"did not find a stitch port for site={site} and providers={providers}")

    stitch_info = stitch_infos[0] if stitch_infos else None

    if not stitch_info:
        raise StitchPortNotFound(f"did not find a stitch port for providers={providers}")

    if len(stitch_infos) > 1:
        logger.info(f"Using stitch port based on preference for providers={providers}:{stitch_info}")
    else:
        logger.info(f"Using stitch port for providers={providers}:{stitch_info}")

    return stitch_info


def find_profile(network, resources):
    profile = network.attributes.get(Constants.RES_PROFILE)

    # if not profile:
    #     for dep in [dep for dep in network.dependencies if dep.resource.is_network]:
    #         profile = dep.resource.attributes.get(Constants.RES_PROFILE)
    #
    #         if profile:
    #             break

    if not profile:
        for net in [resource for resource in resources if resource.is_network]:
            if [dep for dep in network.dependencies if dep.resource == net]:
                profile = net.attributes.get(Constants.RES_PROFILE)

                if profile:
                    break
    return profile


def find_site(network, resources):
    site = network.attributes.get(Constants.RES_SITE)

    if not site:
        for dep in network.dependencies:
            if dep.resource.is_node:
                site = dep.resource.attributes.get(Constants.RES_SITE)

                if site:
                    break

    if not site:
        for node in [resource for resource in resources if resource.is_node]:
            if [dep for dep in node.dependencies if dep.resource == network]:
                site = node.attributes.get(Constants.RES_SITE)

                if site:
                    break
    return site


def clean_up_port(stitch_port):
    attrs = ["preference", "member-of"]

    for attr in attrs:
        stitch_port.pop(attr, None)

    peer = stitch_port.get('peer', {})
    attrs = ["preference", "member-of", "name"]

    for attr in attrs:
        peer.pop(attr, None)


def handle_stitch_info(config, policy, resources):
    from amscrot.util.utils import get_logger

    logger = get_logger()
    has_stitch_with = False

    for network in [resource for resource in resources if resource.is_network]:
        if Constants.RES_STITCH_INFO not in network.attributes:
            network.attributes[Constants.RES_STITCH_INFO] = []

        if Constants.RES_STITCH_INTERFACE not in network.attributes:
            network.attributes[Constants.RES_STITCH_INTERFACE] = []

    for network in [resource for resource in resources if resource.is_network]:
        if Constants.NETWORK_STITCH_WITH in network.attributes:
            from amscrot.util.config_models import DependencyInfo

            has_stitch_with = True
            dependency_info_dicts = network.attributes[Constants.NETWORK_STITCH_WITH]

            if not isinstance(dependency_info_dicts, list):
                option = network.attributes.get(Constants.NETWORK_STITCH_OPTION)
                dependency_info_dicts = [dict(network=dependency_info_dicts, stitch_option=option)]

            from amscrot.util.config_models import DependencyInfo

            for dependency_info_dict in dependency_info_dicts:
                assert("network" in dependency_info_dict)
                assert(isinstance(dependency_info_dict["network"], DependencyInfo))

            temp = set()

            for dep in network.dependencies:
                if dep.key == 'stitch_with.network':
                    # Dependency(key='stitch_with.network', resource=cnet@network, attribute='', is_external=True
                    from amscrot.util.config_models import Dependency
                    new_dep = Dependency(key=Constants.NETWORK_STITCH_WITH,
                                         resource=dep.resource, attribute=dep.attribute, is_external=True)
                    temp.add(new_dep)
                else:
                    temp.add(dep)

            network._resource_dependencies = temp

            for dependency_info_dict in dependency_info_dicts:
                dependency_info: DependencyInfo = dependency_info_dict['network']
                network_dependency = None

                for ed in network.dependencies:
                    if ed.key == Constants.NETWORK_STITCH_WITH and ed.resource.label == dependency_info.resource.label:
                        network_dependency = ed
                        break

                assert network_dependency is not None, "should never happen"
                assert network_dependency.is_external, "only network stitching across providers is supported"
                other_network = network_dependency.resource
                assert other_network.is_network, "only network stitching is supported"

                stitch_config = None
                option = dependency_info_dict.get(Constants.NETWORK_STITCH_OPTION)

                if option:
                    stitch_config = option.get(Constants.NETWORK_STITCH_CONFIG)

                if not stitch_config:
                    site = find_site(network, resources)
                    profile = find_profile(network, resources)
                    stitch_info = find_stitch_port(policy=policy,
                                                   providers=[network.provider.type, other_network.provider.type],
                                                   site=site,
                                                   profile=profile,
                                                   options=option)

                    clean_up_port(stitch_info.stitch_port)
                    stitch_info = StitchInfo(consumer=stitch_info.consumer,
                                             producer=stitch_info.producer,
                                             stitch_port=stitch_info.stitch_port)
                else:
                    logger.info(f"using supplied {Constants.NETWORK_STITCH_CONFIG}:{stitch_config.attributes}")
                    stitch_info = StitchInfo(consumer=stitch_config.attributes['consumer'],
                                             producer=stitch_config.attributes['producer'],
                                             stitch_port=stitch_config.attributes['stitch_port'])
                from amscrot.util.config_models import DependencyInfo

                if network.provider.type == stitch_info.consumer:
                    network.attributes[Constants.RES_STITCH_INTERFACE].append(DependencyInfo(resource=other_network,
                                                                                             attribute=''))
                else:
                    other_network.attributes[Constants.RES_STITCH_INTERFACE].append(DependencyInfo(resource=network,
                                                                                                   attribute=''))

                peer1 = {}
                peer2 = {}

                peer1.update(stitch_info.stitch_port['peer'])
                peer2.update(stitch_info.stitch_port)
                peer2.pop('peer')

                if network.provider.type != peer1['provider']:
                    pass

                stitch_info = StitchInfo(stitch_port=dict(),
                                         producer=stitch_info.producer, consumer=stitch_info.consumer)

                if network.provider.type == peer1['provider']:
                    stitch_info.stitch_port.update(peer1)
                    stitch_info.stitch_port['peer'] = dict()
                    stitch_info.stitch_port['peer'].update(peer2)
                else:
                    stitch_info.stitch_port.update(peer2)
                    stitch_info.stitch_port['peer'] = dict()
                    stitch_info.stitch_port['peer'].update(peer1)

                # Handle stitch port labels. The labels are inserted here to match it to a peering config
                stitch_info.stitch_port[Constants.LABELS] = sorted([network.label, other_network.label])
                network.attributes[Constants.RES_STITCH_INFO].append(stitch_info)
                stitch_info = StitchInfo(stitch_port=dict(),
                                         producer=stitch_info.producer, consumer=stitch_info.consumer)

                if other_network.provider.type == peer1['provider']:
                    stitch_info.stitch_port.update(peer1)
                    stitch_info.stitch_port['peer'] = dict()
                    stitch_info.stitch_port['peer'].update(peer2)
                else:
                    stitch_info.stitch_port.update(peer2)
                    stitch_info.stitch_port['peer'] = dict()
                    stitch_info.stitch_port['peer'].update(peer1)
                # Handle stitch port labels. The labels are inserted here to match it to a peering config
                stitch_info.stitch_port[Constants.LABELS] = sorted([network.label, other_network.label])
                other_network.attributes[Constants.RES_STITCH_INFO].append(stitch_info)

    for network in [resource for resource in resources if resource.is_network]:
        network.attributes.pop(Constants.NETWORK_STITCH_WITH, None)
        network.attributes.pop(Constants.NETWORK_STITCH_OPTION, None)

    if has_stitch_with:
        for resource in resources:
            resource.dependencies.clear()

        from amscrot.util.resource_dependency_helper import ResourceDependencyEvaluator, order_resources

        dependency_evaluator = ResourceDependencyEvaluator(resources, config.get_provider_configs())
        dependency_map = dependency_evaluator.evaluate()
        resources = order_resources(dependency_map)

    return resources


def fix_node_site(resource, resources):
    site = resource.attributes.get(Constants.RES_SITE)

    if site:
        return

    for dep in resource.dependencies:
        if dep.resource.is_network and dep.resource.provider == resource.provider:
            net = dep.resource
            site = net.attributes.get(Constants.RES_SITE)

            if site:
                resource.attributes[Constants.RES_SITE] = site
                return

            stitch_port = get_stitch_port_for_provider(resource=net.attributes, provider=net.provider.type)

            if isinstance(stitch_port, list) and len(stitch_port) > 1:
                return

            if isinstance(stitch_port, list) and len(stitch_port) == 1:
                stitch_port = stitch_port[0]

            if stitch_port:
                site = stitch_port.get(Constants.RES_SITE)  # TODO FIX PYCHARM WARNING
                resource.attributes[Constants.RES_SITE] = site
                return

    for net in [r for r in resources if r.is_network]:
        if [dep for dep in net.dependencies if net.provider == resource.provider and dep.resource == resource]:
            site = net.attributes.get(Constants.RES_SITE)

            if site:
                resource.attributes[Constants.RES_SITE] = site
                return

            stitch_port = get_stitch_port_for_provider(resource=net.attributes, provider=net.provider.type)

            if isinstance(stitch_port, list) and len(stitch_port) > 1:
                return

            if isinstance(stitch_port, list) and len(stitch_port) == 1:
                stitch_port = stitch_port[0]

            if stitch_port:
                site = stitch_port.get(Constants.RES_SITE)  # TODO FIX PYCHARM WARNING
                resource.attributes[Constants.RES_SITE] = site
                return


def fix_network_site(resource):
    site = resource.attributes.get(Constants.RES_SITE)

    if site:
        return

    stitch_ports = get_stitch_port_for_provider(resource=resource.attributes, provider=resource.provider.type)

    if stitch_ports is None:
        return

    if isinstance(stitch_ports, list) and len(stitch_ports) > 1:
        return

    if isinstance(stitch_ports, list) and len(stitch_ports) == 1:
        stitch_port = stitch_ports[0]
        site = stitch_port.get(Constants.RES_SITE)
        resource.attributes[Constants.RES_SITE] = site

    if isinstance(stitch_ports, dict):
        stitch_port = stitch_ports
        site = stitch_port.get(Constants.RES_SITE)
        resource.attributes[Constants.RES_SITE] = site


def get_vlan_from_range(*, resource: dict):
    vlan_range = get_vlan_range(resource=resource)

    if not vlan_range:
        return -1

    vlan_range = vlan_range[0]
    x = vlan_range.split("-")

    import random

    vlan = random.randrange(int(x[0]), int(x[1]) + 1)
    return vlan


def get_vlan_range(*, resource: dict):
    stitch_infos = resource.get(Constants.RES_STITCH_INFO)

    if not stitch_infos:
        return None

    if isinstance(stitch_infos, dict):  # This is for testing purposes.
        producer = stitch_infos['producer']
        consumer = stitch_infos['consumer']
        stitch_info = StitchInfo(stitch_port=stitch_infos['stitch_port'], producer=producer, consumer=consumer)
        stitch_infos = resource[Constants.RES_STITCH_INFO] = [stitch_info]

    stitch_ports = [stitch_infos[0].stitch_port]

    if PEER in stitch_infos[0].stitch_port:
        stitch_ports.append(stitch_infos[0].stitch_port[PEER])

    for stitch_port in stitch_ports:
        if Constants.STITCH_VLAN_RANGE in stitch_port:
            return stitch_port[Constants.STITCH_VLAN_RANGE]

    return None


def get_stitch_port_for_provider(*, resource: dict, provider: str):
    stitch_infos = resource.get(Constants.RES_STITCH_INFO)

    if not stitch_infos:
        return None

    if isinstance(stitch_infos, dict):  # This is for testing purposes.
        producer = stitch_infos['producer']
        consumer = stitch_infos['consumer']
        stitch_info = StitchInfo(stitch_port=stitch_infos['stitch_port'], producer=producer, consumer=consumer)
        stitch_infos = resource[Constants.RES_STITCH_INFO] = [stitch_info]

    stitch_ports = []

    for stitch_info in stitch_infos:
        temp_stitch_ports = [stitch_info.stitch_port]

        if PEER in stitch_info.stitch_port:
            temp_stitch_ports.append(stitch_info.stitch_port[PEER])

        stitch_port = next(filter(lambda sp: sp['provider'] == provider, temp_stitch_ports), None)

        if stitch_port is not None:
            stitch_ports.append(stitch_port)

    if len(stitch_ports) == 0:
        return None

    if len(stitch_ports) == 1:
        return stitch_ports[0]

    return stitch_ports

