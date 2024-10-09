from fabrictestbed_extensions.fablib.node import Node as Delegate
from fabrictestbed_extensions.fablib.slice import Slice

from fabfed.model import Node
from fabfed.util.constants import Constants
from fabfed.util.utils import get_logger
from .fabric_constants import *

logger = get_logger()


class FabricNode(Node):
    def __init__(self, *, label, delegate: Delegate, nic_model: str, network_label: str):
        flavor = {'cores': delegate.get_cores(), 'ram': delegate.get_ram(), 'disk': delegate.get_disk()}
        super().__init__(label=label, name=delegate.get_name(), image=delegate.get_image(), site=delegate.get_site(),
                         flavor=str(flavor))
        logger.info(f" Node {self.name} construtor called ... ")
        self._delegate = delegate
        self.nic_model = nic_model
        self._slice_object = delegate.get_slice()
        self.slice_name = self._slice_object.get_name()
        self.mgmt_ip = delegate.get_management_ip()
        self.mgmt_ip = str(self.mgmt_ip) if self.mgmt_ip else None
        self.network_label = network_label
        self.username = delegate.get_username()
        self.user = self.username
        self.state = delegate.get_reservation_state()
        self.state = self.state.lower() if self.state else None
        self.host = self.mgmt_ip
        self.keyfile = self._delegate.get_private_key_file()
        self.jump_user = self._delegate.get_fablib_manager().get_bastion_username()
        self.jump_host = self._delegate.get_fablib_manager().get_bastion_host()
        self.jump_keyfile = self._delegate.get_fablib_manager().get_bastion_key_location()
        self._used_dataplane_ipv4 = None
        self.dataplane_ipv4 = None
        self.dataplane_ipv6 = None
        self.id = delegate.get_reservation_id()
        self.components = [dict(name=c.get_name(), model=c.get_model()) for c in delegate.get_components()]
        self.addr_list = {}

    def handle_networking(self):
        if not self.mgmt_ip:
            logger.warning(f" Node {self.name} has no management ip ")
            return

        itfs = [itf for itf in self.delegate.get_interfaces() if itf.get_ip_addr()]

        for itf in itfs:
            if FABRIC_STITCH_NET_IFACE_NAME in itf.get_name():
                self.dataplane_ipv4 = str(itf.get_ip_addr())
                break
            elif f'FABNET_IPv4_{self.site}' in itf.get_name():
                self.dataplane_ipv4 = str(itf.get_ip_addr())
                break

        for itf in itfs:
            if f'FABNET_IPv6_{self.site}' in itf.get_name():
                node_addr = itf.get_ip_addr()
                self.dataplane_ipv6 = str(node_addr)
                break

    @property
    def delegate(self) -> Delegate:
        return self._delegate

    def set_network_label(self, network_label):
        self.network_label = network_label

    def used_dataplane_ipv4(self):
        return self._used_dataplane_ipv4

    def set_used_dataplane_ipv4(self, used_dataplane_ipv4):
        self._used_dataplane_ipv4 = used_dataplane_ipv4

    def get_interfaces(self):
        return self._delegate.get_interfaces()

    def get_interface(self, *, network_name):
        assert network_name
        return self._delegate.get_interface(network_name=network_name)

    def upload_file(self, local_file_path, remote_file_path, retry=3, retry_interval=10):
        self._delegate.upload_file(local_file_path, remote_file_path, retry, retry_interval)

    def download_file(self, local_file_path, remote_file_path, retry=3, retry_interval=10):
        self._delegate.download_file(local_file_path, remote_file_path, retry, retry_interval)

    def upload_directory(self, local_directory_path, remote_directory_path, retry=3, retry_interval=10):
        self._delegate.upload_directory(local_directory_path, remote_directory_path, retry, retry_interval)

    def download_directory(self, local_directory_path, remote_directory_path, retry=3, retry_interval=10):
        self._delegate.download_directory(local_directory_path, remote_directory_path, retry, retry_interval)

    def execute(self, command, retry=3, retry_interval=10):
        self._delegate.execute(command, retry, retry_interval)

    def add_route(self, subnet, gateway):
        self._delegate.ip_route_add(subnet=subnet, gateway=gateway)

    def get_management_ip(self) -> str:
        return self._delegate.get_management_ip()

    def get_dataplane_address(self, network=None, interface=None, af=Constants.IPv4):
        if af == Constants.IPv4:
            return self.dataplane_ipv4
        elif af == Constants.IPv6:
            return self.dataplane_ipv6
        else:
            return None

    def get_reservation_id(self) -> str:
        return self._delegate.get_reservation_id()

    def get_reservation_state(self) -> str:
        return self._delegate.get_reservation_state()


class NodeBuilder:
    def __init__(self, label, slice_object: Slice, name: str,  resource: dict):
        from .fabric_constants import FABRIC_RANDOM
        site = resource.get(Constants.RES_SITE, FABRIC_RANDOM)

        if site == FABRIC_RANDOM:
            from fabrictestbed_extensions.fablib.fablib import fablib

            site = fablib.get_random_site()

        image = resource.get(Constants.RES_IMAGE, Delegate.default_image)
        flavor = resource.get(Constants.RES_FLAVOR, {'cores': 2, 'ram': 8, 'disk': 10})
        cores = flavor.get(Constants.RES_FLAVOR_CORES, Delegate.default_cores)
        ram = flavor.get(Constants.RES_FLAVOR_RAM, Delegate.default_ram)
        disk = flavor.get(Constants.RES_FLAVOR_DISK, Delegate.default_disk)
        self.label = label
        self.nic_model = resource.get(Constants.RES_NIC_MODEL, 'NIC_Basic')
        self.node: Delegate = slice_object.add_node(name=name, image=image, site=site, cores=cores, ram=ram, disk=disk)

        # Use fully automated ip v4
        if resource.get(Constants.RES_TYPE_NETWORK) is None:
            self.node.add_fabnet(net_type="IPv4", nic_type=self.nic_model)

        # Use fully automated ip v6
        if INCLUDE_FABNET_V6 and resource.get(Constants.RES_TYPE_NETWORK) is None:
            self.node.add_fabnet(net_type="IPv6", nic_type=self.nic_model)

    def add_component(self, model=None, name=None):
        self.node.add_component(model=model, name=name)

    def build(self) -> FabricNode:
        return FabricNode(label=self.label, delegate=self.node, nic_model=self.nic_model, network_label="")
