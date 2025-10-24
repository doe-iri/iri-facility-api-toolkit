from amscrot.provider.api.provider import Provider
from amscrot.provider.api.resource_event_listener import ResourceListener
from amscrot.util.constants import Constants


class ControllerResourceListener(ResourceListener):
    def __init__(self):
        self.providers = list()

    def set_providers(self, providers: list):
        self.providers = providers

    def on_added(self, *, source, provider: Provider, resource: object):
        for temp_provider in self.providers:
            temp_provider.on_added(source=self, provider=provider, resource=resource)

    def on_created(self, *, source, provider: Provider, resource: object):
        for temp_provider in self.providers:
            if temp_provider == provider:
                temp_provider.on_created(source=self, provider=provider, resource=resource)
                break

        for temp_provider in self.providers:
            if temp_provider != provider:
                temp_provider.on_created(source=self, provider=provider, resource=resource)

    def on_deleted(self, *, source, provider: Provider, resource: object):
        for temp_provider in self.providers:
            temp_provider.on_deleted(source=self, provider=provider, resource=resource)


def populate_layer3_config(*, networks: list):
    from amscrot.exceptions import ControllerException

    for network in networks:
        layer3 = network.attributes.get(Constants.RES_LAYER3)

        if not layer3:
            continue

        if Constants.RES_SUBNET not in layer3.attributes:
            raise ControllerException(f"network {network.label} must have a subnet in its layer3 config")

        subnet = layer3.attributes[Constants.RES_SUBNET]

        try:
            addr = subnet[:subnet.rindex("/")]
            prefix = addr[:addr.rindex(".")]

            if Constants.RES_NET_GATEWAY not in layer3.attributes:
                layer3.attributes[Constants.RES_NET_GATEWAY] = prefix + ".1"

            if Constants.RES_LAYER3_DHCP_START not in layer3.attributes:
                layer3.attributes[Constants.RES_LAYER3_DHCP_START] = prefix + ".2"

            if Constants.RES_LAYER3_DHCP_END not in layer3.attributes:
                layer3.attributes[Constants.RES_LAYER3_DHCP_END] = prefix + ".254"
        except:
            raise ControllerException(f"Error parsing {subnet} for layer3 config in network {network.label}")


def partition_layer3_config(*, networks: list):
    from ipaddress import IPv4Address
    from ..util.constants import Constants
    from amscrot.util.config_models import Config

    if len(networks) <= 1:
        return

    layer3 = networks[0].attributes.get(Constants.RES_LAYER3)

    if not layer3.attributes.get(Constants.RES_LAYER3_DHCP_START):
        return

    if "/" in layer3.attributes.get(Constants.RES_LAYER3_DHCP_START):
        return

    if "/" in layer3.attributes.get(Constants.RES_LAYER3_DHCP_END):
        return

    layer3 = networks[0].attributes.get(Constants.RES_LAYER3)
    dhcp_start = int(IPv4Address(layer3.attributes.get(Constants.RES_LAYER3_DHCP_START)))
    last = dhcp_end = int(IPv4Address(layer3.attributes.get(Constants.RES_LAYER3_DHCP_END)))
    interval = int((dhcp_end - dhcp_start) / len(networks))

    for index, network in enumerate(networks):
        layer3_config = Config(layer3.type, f"{layer3.name}-{index}", layer3.attributes.copy())
        dhcp_end = dhcp_start + interval

        if dhcp_end > last:
            dhcp_end = last

        layer3_config.attributes[Constants.RES_LAYER3_DHCP_START] = str(IPv4Address(dhcp_start))
        layer3_config.attributes[Constants.RES_LAYER3_DHCP_END] = str(IPv4Address(dhcp_end))
        network.attributes[Constants.RES_LAYER3] = layer3_config
        dhcp_start = dhcp_end + 1


def find_peer_networks(*, network):
    dependencies = network.dependencies
    peer_networks = []

    for ed in dependencies:
        if ed.key == Constants.RES_STITCH_INTERFACE:
            peer_networks.append(ed.resource)

    return peer_networks


def find_nodes_related_to_network(*, network, resources):
    nodes = []
    assert network.is_network

    for dep in network.dependencies:
        if dep.resource.is_node:
            nodes.append(dep.resource)

    for node in filter(lambda r: r.is_node, resources):
        if next(filter(lambda d: d.resource.label == network.label, node.dependencies), None):
            nodes.append(node)

    return nodes


def find_node_clusters(*, resources):
    networks = [r for r in resources if r.is_network]
    net_clusters = []
    node_clusters = []

    for net in networks:
        net_cluster = None

        for temp_net_cluster in net_clusters:
            if net.label in temp_net_cluster:
                net_cluster = temp_net_cluster
                break

        if net_cluster is None:
            peers = find_peer_networks(network=net)

            for peer in peers:
                for temp_net_cluster in net_clusters:
                    if peer.label in temp_net_cluster:
                        net_cluster = temp_net_cluster
                        break

            if net_cluster is None:
                net_cluster = set()
                net_clusters.append(net_cluster)

            net_cluster.add(net.label)

            for peer in peers:
                net_cluster.add(peer.label)

    added_nodes = []
    for net_cluster in net_clusters:
        node_cluster = []

        for net in networks:
            if net.label in net_cluster:
                nodes = find_nodes_related_to_network(network=net, resources=resources)
                node_cluster.extend(nodes)
                added_nodes.extend([n.label for n in nodes])
        node_clusters.append(node_cluster)

    nodes = [r for r in resources if r.is_node]
    for n in nodes:
        if n.label not in added_nodes:
            node_clusters.append([n])

    return node_clusters
