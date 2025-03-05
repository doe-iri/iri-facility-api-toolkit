import logging
from typing import List, Union

import fabfed.provider.api.dependency_util as util
from fabfed.model import Node, Network
from .fabric_network import NetworkBuilder, FabricNetwork
from .fabric_node import FabricNode, NodeBuilder
from .fabric_provider import FabricProvider
from ...util.constants import Constants
from .fabric_constants import *


# noinspection PyUnresolvedReferences
class FabricSlice:
    def __init__(self, *, provider: FabricProvider, logger: logging.Logger):
        self.provider = provider
        self.logger = logger
        self.notified_create = False
        self.slice_created = False
        self.slice_modified = False
        self.submitted = False
        self.network_to_sites_mapping = dict()

        from fabrictestbed_extensions.fablib.slice import Slice

        self.slice_object: Union[Slice, None] = None
        self.retry = 10
        self.existing_nodes = []
        self.existing_networks = []
        self._resource_state_map = {}

    def init(self, destroy_phase):
        from . import fabric_slice_helper

        self.slice_object = fabric_slice_helper.init_slice(self.provider.name, destroy_phase)

        if self.slice_object and self.slice_object.get_state() == "StableOK":
            self.slice_created = self.slice_object.get_state() == "StableOK"
            self.existing_nodes = [node.get_name() for node in self.slice_object.get_nodes()]
            self.existing_networks = []

            for net in self.slice_object.get_networks():
                net_name = net.get_name()

                if "_aux" in net_name or FABRIC_IPV4_NET_NAME in net_name or FABRIC_IPV6_NET_NAME in net_name:
                    continue

                if FABNET_IPV4_PREFIX in net_name or FABNET_IPV6_PREFIX in net_name:
                    continue

                self.existing_networks.append(net_name)

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def failed(self):
        return self.provider.failed

    @property
    def resource_listener(self):
        return self.provider.resource_listener

    @property
    def nodes(self) -> List[Node]:
        return self.provider.nodes

    @property
    def networks(self) -> List[Network]:
        return self.provider.networks

    @property
    def pending(self):
        return self.provider.pending

    def validate_resource(self, *, resource: dict):
        rtype = resource.get(Constants.RES_TYPE)

        if rtype == Constants.RES_TYPE_NETWORK.lower():
            label = resource[Constants.LABEL]
            if label not in self.network_to_sites_mapping:
                self.network_to_sites_mapping[label] = set()

            if Constants.RES_SITE in resource:
                self.network_to_sites_mapping[label].add(resource[Constants.RES_SITE])

            dependencies = resource[Constants.INTERNAL_DEPENDENCIES]

            for dependency in dependencies:
                if Constants.RES_SITE in dependency.resource.attributes:
                    self.network_to_sites_mapping[label].add(dependency.resource.attributes[Constants.RES_SITE])

        elif rtype == Constants.RES_TYPE_NODE.lower():
            dependencies = resource[Constants.INTERNAL_DEPENDENCIES]

            for dependency in dependencies:
                label = dependency.resource.label

                if label not in self.network_to_sites_mapping:
                    self.network_to_sites_mapping[label] = set()

                if Constants.RES_SITE in resource:
                    self.network_to_sites_mapping[label].add(resource[Constants.RES_SITE])
        else:
            raise Exception("Unknown resource ....")

    def _add_network(self, resource: dict):
        label = resource[Constants.LABEL]
        net_name = self.provider.resource_name(resource)

        if net_name in self.existing_networks:
            delegate = self.slice_object.get_network(net_name)
            assert delegate is not None, "expected to find network {net_name} in slice {self.name}"
            layer3 = resource.get(Constants.RES_LAYER3)
            peer_layer3 = resource.get(Constants.RES_PEER_LAYER3)
            peering = resource.get(Constants.RES_PEERING)
            net = FabricNetwork(label=label, delegate=delegate, layer3=layer3,
                                peering=peering, peer_layer3=peer_layer3)

            self.provider.networks.append(net)
            self.resource_listener.on_added(source=self, provider=self.provider, resource=net)
            return

        network_builder = NetworkBuilder(label, self.provider, self.slice_object, net_name, resource)
        network_builder.handle_facility_port(sites=self.network_to_sites_mapping[label])
        network_builder.handle_network()
        net = network_builder.build()
        self.provider.networks.append(net)
        self.slice_modified = self.slice_created
        self.resource_listener.on_added(source=self, provider=self.provider, resource=net)

    def _add_node(self, resource: dict):
        node_count = resource[Constants.RES_COUNT]
        label = resource[Constants.LABEL]

        for i in range(node_count):
            name = self.provider.resource_name(resource, i)

            if name in self.existing_nodes:
                from fabrictestbed_extensions.fablib.node import Node as NodeDelegate

                delegate: NodeDelegate = self.slice_object.get_node(name)
                assert delegate is not None, "expected to find node {name} in slice {self.name}"
                network_label = self.provider.retrieve_attribute_from_saved_state(resource, name, 'network_label')
                dataplane_ipv4 = self.provider.retrieve_attribute_from_saved_state(resource, name, 'dataplane_ipv4')
                nic_model = self.provider.retrieve_attribute_from_saved_state(resource, name, 'nic_model', "NIC_Basic")
                node = FabricNode(label=label, delegate=delegate, nic_model=nic_model, network_label=network_label)

                if not network_label:
                    if util.has_resolved_internal_dependencies(resource=resource, attribute='network'):
                        network = util.get_single_value_for_dependency(resource=resource, attribute='network')

                        if network:
                            # TODO: Need to talk to fablib team and make sure an existing node's interface
                            # TODO: can be added to a network after it has been created.

                            from fabrictestbed_extensions.fablib.network_service import NetworkService

                            itf = None

                            try:
                                comp = node.delegate.get_component(name=FABRIC_STITCH_NET_IFACE_NAME)
                                itf = comp.get_interfaces()[0]
                                self.logger.info(f"Found interface {itf.get_name()} to node {node.get_name()}")
                            except Exception as e:
                                self.logger.warning(
                                    f"Exception while looking for {FABRIC_STITCH_NET_IFACE_NAME} in node {node.get_name()}: {e}")

                            if itf is None:
                                itf = node.delegate.add_component(model=nic_model,
                                                                  name=FABRIC_STITCH_NET_IFACE_NAME).get_interfaces()[0]
                                self.logger.info(f"Added interface {itf.get_name()} to node {node.get_name()}")

                                delegate: NetworkService = network.delegate

                                if network.peering:
                                   from fim.slivers.capacities_labels import Labels, Capacities

                                   aux_name = delegate.get_name() + "_aux"
                                   aux_net = self.slice_object.get_network(delegate.get_name() + "_aux")

                                   if aux_net is None:
                                      aux_net = self.slice_object.add_l3network(name=aux_name, interfaces=[], type='L3VPN')
                                      delegate.fim_network_service.peer(aux_net.fim_network_service,
                                         labels=Labels(bgp_key='secret', ipv4_subnet='192.168.50.1/24'),
                                         capacities=Capacities(mtu=9000), peer_labels=Labels(local_name="FABRIC"))

                                   fim_iface1 = itf.get_fim_interface()
                                   ipv4_gateway = network.layer3.attributes.get(Constants.RES_NET_GATEWAY)

                                   if ipv4_gateway:
                                      ipv4_subnet = network.layer3.attributes.get(Constants.RES_SUBNET)

                                      if ipv4_subnet and '/' in ipv4_subnet:
                                         ipv4_netmask = ipv4_subnet.split('/')[1]
                                         ipv4_subnet = f'{ipv4_gateway}/{ipv4_netmask}'
                                   else:
                                      ipv4_subnet = network.layer3.attributes.get(Constants.RES_SUBNET)

                                   fim_iface1.labels = Labels.update(fim_iface1.labels, ipv4_subnet=f'{ipv4_subnet}')
                                   aux_net.add_interface(itf)
                                   self.logger.info(f"Added interface {itf.get_name()} to network {aux_name}")
                                else:
                                   delegate.add_interface(itf)
                                self.logger.info(f"Added interface {itf.get_name()} to network {delegate.get_name()}")
                                self.slice_modified = True
                                dataplane_ipv4 = None

                            node.set_network_label(network.label)

                if dataplane_ipv4:
                    from ipaddress import IPv4Address

                    node.set_used_dataplane_ipv4(IPv4Address(dataplane_ipv4))
            else:
                node_builder = NodeBuilder(label, self.slice_object, name, resource)
                node = node_builder.build()
                self.slice_modified = True
                network: Union[Network, None] = None

                if util.has_resolved_internal_dependencies(resource=resource, attribute='network'):
                    network = util.get_single_value_for_dependency(resource=resource, attribute='network')

                if network:
                    from fabrictestbed_extensions.fablib.network_service import NetworkService

                    itf = node.delegate.add_component(model=node.nic_model,
                                                      name=FABRIC_STITCH_NET_IFACE_NAME).get_interfaces()[0]
                    self.logger.info(
                        f"Added interface {itf.get_name()} to node {node.get_name()} with nic_model={node.nic_model}")

                    delegate: NetworkService = network.delegate

                    if network.peering:
                       from fim.slivers.capacities_labels import Labels, Capacities

                       aux_name = delegate.get_name() + "_aux"
                       aux_net = self.slice_object.get_network(delegate.get_name() + "_aux")

                       if aux_net is None:
                          aux_net = self.slice_object.add_l3network(name=aux_name, interfaces=[], type='L3VPN')
                          delegate.fim_network_service.peer(aux_net.fim_network_service,
                                  labels=Labels(bgp_key='secret', ipv4_subnet='192.168.50.1/24'),
                                  capacities=Capacities(mtu=9000), peer_labels=Labels(local_name="FABRIC"))

                       fim_iface1 = itf.get_fim_interface()

                       ipv4_gateway = network.layer3.attributes.get(Constants.RES_NET_GATEWAY)

                       if ipv4_gateway:
                             ipv4_subnet = network.layer3.attributes.get(Constants.RES_SUBNET)

                             if ipv4_subnet and '/' in ipv4_subnet:
                                ipv4_netmask = ipv4_subnet.split('/')[1]
                                ipv4_subnet = f'{ipv4_gateway}/{ipv4_netmask}'
                       else:
                          ipv4_subnet = network.layer3.attributes.get(Constants.RES_SUBNET)

                       fim_iface1.labels = Labels.update(fim_iface1.labels, ipv4_subnet=f'{ipv4_subnet}')
                       aux_net.add_interface(itf)
                       self.logger.info(f"Added interface {itf.get_name()} to network {aux_name}")
                    else:
                       delegate.add_interface(itf)
                       self.logger.info(f"Added interface {itf.get_name()} to network {delegate.get_name()}")

                    node.set_network_label(network.label)

            self.nodes.append(node)
            self.resource_listener.on_added(source=self, provider=self.provider, resource=node)

    def add_resource(self, *, resource: dict):
        rtype = resource.get(Constants.RES_TYPE)

        for state in resource[Constants.SAVED_STATES]:
            self._resource_state_map[state.attributes['name']] = state

        creation_details = resource[Constants.RES_CREATION_DETAILS]

        if not creation_details['in_config_file']:
            return

        if rtype == Constants.RES_TYPE_NETWORK.lower():
            self._add_network(resource)
        elif rtype == Constants.RES_TYPE_NODE.lower():
            self._add_node(resource)
        else:
            raise Exception("Unknown resource ....")

    def _reload_nodes(self):
        from fabrictestbed_extensions.fablib.fablib import fablib

        temp = []
        self.slice_object = fablib.get_slice(name=self.provider.name)

        for node in self.nodes:
            delegate = self.slice_object.get_node(node.name)
            n = FabricNode(label=node.label, delegate=delegate,
                           nic_model=node.nic_model, network_label=node.network_label)
            n.set_network_label(node.network_label)
            n.set_used_dataplane_ipv4(node.used_dataplane_ipv4())
            temp.append(n)
            n.handle_networking()

        self.provider._nodes = temp

    def _reload_networks(self):
        from fabrictestbed_extensions.fablib.fablib import fablib

        self.slice_object = fablib.get_slice(name=self.provider.name)

        temp = []

        for net in self.provider.networks:
            delegate = self.slice_object.get_network(net.name)
            fabric_network = FabricNetwork(label=net.label,
                                           delegate=delegate,
                                           layer3=net.layer3,
                                           peering=net.peering,
                                           peer_layer3=net.peer_layer3)

            temp.append(fabric_network)

        self.provider._networks = temp

    def _ensure_management_ips(self):
        if len(self.nodes) == 0:
            return

        for attempt in range(self.retry):
            mngmt_ips = []
            from fabrictestbed_extensions.fablib.fablib import fablib

            self.slice_object = fablib.get_slice(name=self.provider.name)

            for node in self.nodes:
                delegate = self.slice_object.get_node(node.name)
                mgmt_ip = delegate.get_management_ip()

                if mgmt_ip:
                    mngmt_ips.append(mgmt_ip)

            if len(self.nodes) == len(mngmt_ips):
                self.logger.info(f"Got All management ips for slice {self.provider.label}:{mngmt_ips}")
                break

            if attempt == self.retry:
                self.logger.warning(f"Giving up on checking node management ips ...slice "
                                    f"{self.provider.label} {self.nodes}:{mngmt_ips}:")
                break

            import time

            self.logger.info(
                f"Going to sleep. Will try checking node management ips ... slice {self.provider.label}")

            time.sleep(2)

    def _do_handle_node_networking(self):
        from fabrictestbed_extensions.fablib.fablib import fablib
        from . import fabric_slice_helper

        self._ensure_management_ips()

        for network in self.networks:
            from ipaddress import IPv4Network

            available_ips: list = network.available_ips()

            if available_ips and network.subnet:
                net_name = network.name
                subnet = IPv4Network(network.subnet)
                temp = [n for n in self.nodes if n.network_label == network.label]

                for node in temp:
                    if node.used_dataplane_ipv4() and node.used_dataplane_ipv4() in available_ips:
                        available_ips.remove(node.used_dataplane_ipv4())

                for node in temp:
                    node_addr = node.used_dataplane_ipv4() if node.used_dataplane_ipv4() else available_ips.pop(0)
                    fabric_slice_helper.add_ip_address_to_network(self.slice_object,
                                                                  node, net_name, node_addr, subnet, self.retry)
                    node.set_used_dataplane_ipv4(node_addr)

            if network.gateway and network.peer_layer3:
                for peer_layer3 in network.peer_layer3:
                    subnet = peer_layer3.attributes.get(Constants.RES_SUBNET)

                    if subnet:
                        self.logger.info(f"Slice {self.name}:Handling subnet {subnet} for peer {peer_layer3}")
                        vpc_subnet = fabric_slice_helper.to_vpc_subnet(subnet)

                        for node in self.nodes:
                            fabric_slice_helper.add_route(self.slice_object, node, vpc_subnet, network.gateway,
                                                          self.retry)

        self._reload_nodes()
        self._reload_networks()

    def _handle_node_networking(self):
        try:
            self._do_handle_node_networking()
        except Exception as e:
            raise Exception(
                f"Please Apply again. Fabric slice {self.name} has exception during post networking setup: {e}")

    def create_resource(self, *, resource: dict):
        label = resource.get(Constants.LABEL)

        if self.failed:
            raise Exception(f"fabric slice {self.name} has some failures. Refusing to create {label}")

        if self.pending:
            self.logger.warning(f"still have pending {len(self.pending)} resources")
            return

        if self.submitted:
            return

        if self.slice_created:
            aset = set(self.existing_nodes)
            bset = {n.name for n in self.nodes}
            diff = aset - bset

            if diff:
                network_labels = {}
                for name, state in self._resource_state_map.items():
                    if state.type == Constants.RES_NODES:
                        network_labels[name] = state.attributes['network_label']

                for n in diff:
                    self.logger.info(f"removing node {n} from slice {self.name}")

                    if INCLUDE_FABNETS:
                        self.logger.info(f"removing node's fabnets: {n} from slice {self.name}")
                        self.slice_object.get_fim_topology().remove_network_service(f"{n}-{FABRIC_IPV4_NET_NAME}")
                        self.slice_object.get_fim_topology().remove_network_service(f"{n}-{FABRIC_IPV6_NET_NAME}")

                    node = self.slice_object.get_node(name=n)
                    temp = [net for net in self.networks if net.label == network_labels[n]]

                    for network in temp:
                        self.logger.info(f"removing node's interface: {n} from network {network.name}")
                        from fabrictestbed_extensions.fablib.network_service import NetworkService

                        delegate: NetworkService = network.delegate
                        node_interfaces = [i for i in node.get_interfaces()]
                        itf = node_interfaces[0]
                        delegate.remove_interface(itf)

                    self.slice_object.get_fim_topology().remove_node(name=n)
                    self.slice_modified = True
                    self.logger.info(f"Done removing node {n} from slice {self.name}")

            aset = set(self.existing_networks)
            bset = {n.name for n in self.networks}
            diff = aset - bset

            if diff:
                for n in diff:
                    self.slice_object.get_fim_topology().remove_network_service(name=n)
                    self.slice_modified = True
                    self.logger.info(f"Done removing network {n} from slice {self.name}")

            for network in [net for net in self.networks if net.name in self.existing_networks]:
                temp = (bset - aset)
                node_map = {}

                for node in self.nodes:
                    node_map[node.name] = node

                temp = [n for n in temp if node_map[n].network_label == network.label]

                for n in temp:
                    node = self.slice_object.get_node(name=n)
                    itf = node.add_component(model="NIC_Basic", name=FABRIC_STITCH_NET_IFACE_NAME).get_interfaces()[0]
                    self.logger.info(f"Added interface {itf.get_name()} to node {node.get_name()}")

                    from fabrictestbed_extensions.fablib.network_service import NetworkService

                    delegate: NetworkService = network.delegate
                    self.logger.info(f"adding interface {itf.get_name()} to {delegate.get_name()}")
                    delegate.add_interface(itf)
                    self.slice_modified = True

        if self.slice_created and not self.slice_modified:
            return

        self.logger.info(f"Submitting request for slice {self.name}")
        # self.slice_object.validate()
        slice_id = self.slice_object.submit(wait=False)
        self.logger.info(f"Done Submitting request for slice {self.name}:{slice_id}")
        self.submitted = True

    def wait_for_create_resource(self, *, resource: dict):
        if self.slice_created and not self.slice_modified and not self.notified_create:
            self._handle_node_networking()

            for node in self.nodes:
                self.resource_listener.on_created(source=self, provider=self.provider, resource=node)

            for net in self.networks:
                self.resource_listener.on_created(source=self, provider=self.provider, resource=net)

            self.notified_create = True
            return

        if self.slice_created and not self.slice_modified:
            return

        assert self.submitted, "expecting slice to have been submitted"

        self.logger.info(f"Waiting for slice {self.name} to be stable")

        rtype = resource.get(Constants.RES_TYPE)

        if self.nodes and rtype == Constants.RES_TYPE_NETWORK.lower():
            from fabrictestbed_extensions.fablib.fablib import fablib
            import functools

            net_name = self.provider.resource_name(resource)
            net = next(filter(lambda n: n.name == net_name, self.networks))

            if net.peering is None:  # TODO SENSE_AWS RUNS INTO AN ISSUE
                for attempt in range(15):
                    self.slice_object = fablib.get_slice(name=self.provider.name)
                    slivers = self.slice_object.get_slivers()
                    slivers = list(filter(lambda s: s.sliver_type == 'NetworkServiceSliver', slivers))
                    slivers = list(filter(lambda s: s.sliver['Name'] == net_name, slivers))
                    states = ['active'] if net.peering else ['active', 'ticketed']
                    count = map(lambda s: 1 if s.state.lower() in states else 0, slivers)
                    count = functools.reduce(lambda a, b: a + b, count)

                    if len(slivers) == count:
                        self.logger.info(f"Network sliver is ready:{net_name}.")

                        if net.peering is None:
                            interfaces = list()
                            for s in slivers:
                                for interface in s.sliver['interfaces']:
                                    import json

                                    labels = json.loads(interface['Labels'])
                                    interfaces.append(dict(id=interface['Name'], vlan=labels['vlan']))

                            net.interface = interfaces

                        self.resource_listener.on_created(source=self, provider=self.provider, resource=net)
                        return

                    self.logger.warning(
                        f"Waiting on ready network sliver: {net_name}:attempt={attempt}:{count}:{len(slivers)}")

                    import time

                    time.sleep(10)

        try:
            self.slice_object.wait(timeout=24 * 60, progress=True)
        except Exception as e:
            state = self.slice_object.get_state()
            self.logger.warning(f"Exception occurred while waiting state={state}:{e}")
            raise e

        try:
            self.slice_object.wait_ssh()
        except Exception as e:
            self.logger.warning(f"Exception occurred while waiting on ssh: {e}")

        try:
            self.slice_object.post_boot_config()
        except Exception as e:
            self.logger.warning(f"Exception occurred while update/post_boot_config: {e}")

        self.logger.info(f"Slice provisioning successful {self.slice_object.get_state()}")

        # days = DEFAULT_RENEWAL_IN_DAYS
        # try:
        #     import datetime
        #     end_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S %z")
        #     self.slice_object.renew(end_date)
        # except Exception as e:
        #     self.logger.warning(f"Exception occurred while renewing for {days}: {e}")

        self.slice_created = True
        self.slice_modified = False
        self.existing_nodes = [n.name for n in self.nodes]
        self.existing_networks = []

        for net in self.slice_object.get_networks():
            net_name = net.get_name()

            if "_aux" in net_name or FABRIC_IPV4_NET_NAME in net_name or FABRIC_IPV6_NET_NAME in net_name:
                continue

            if FABNET_IPV4_PREFIX in net_name or FABNET_IPV6_PREFIX in net_name:
                continue

            self.existing_networks.append(net_name)

        if self.nodes:
            self._handle_node_networking()
        else:
            self._reload_networks()

        for node in self.nodes:
            self.resource_listener.on_created(source=self, provider=self.provider, resource=node)

        for net in self.networks:
            self.resource_listener.on_created(source=self, provider=self.provider, resource=net)

        self.notified_create = True

    def delete_resource(self, *, resource: dict):
        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)

        if rtype == Constants.RES_TYPE_NODE.lower() and self.existing_networks:
            return

        self.logger.debug(f"Destroying resource {self.name}: {label}")

        if self.slice_object:
            self.slice_object.delete()
            self.slice_object = None
            self.slice_created = False
            self.logger.info(f"Destroyed slice {self.name}")  # TODO EMIT DELETE EVENT
