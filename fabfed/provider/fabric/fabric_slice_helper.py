import time

from fabfed.util.utils import get_logger
from .fabric_constants import *

logger = get_logger()


# def has_ip_address(slice_delegate, node, addr):
#     addrs = []
#     delegate = slice_delegate.get_node(node.name)
#     ip_addr_list = delegate.ip_addr_list(output='json', update=False)
#
#     if ip_addr_list:
#         for ip_addr in ip_addr_list:
#             for addr_info in ip_addr['addr_info']:
#                 addrs.append(addr_info['local'])
#
#     return str(addr) in addrs


def has_ip_route(slice_delegate, node, subnet, gateway):
    delegate = slice_delegate.get_node(node.name)
    routes = delegate.get_ip_routes()

    if routes:
        for route in routes:
            if str(subnet) == route.get('dst') and str(gateway) == route.get('gateway'):
                return True

    return False


def to_vpc_subnet(subnet: str):
    from ipaddress import IPv4Network

    subnet = IPv4Network(subnet)
    vpc_subnet = subnet

    for i in [8, 4, 2]:
        if subnet.prefixlen - i > 0:
            vpc_subnet = subnet.supernet(i)
            break

    return vpc_subnet


# def setup_fabric_networks(slice_delegate, node, v4net_name, v6net_name):
#     logger.info(f'setting up ipv4 and ipv6 fabric networks:{node.name}')
#     delegate = slice_delegate.get_node(node.name)
#     v4_net = slice_delegate.get_network(name=v4net_name)
#     v4_net_available_ips = v4_net.get_available_ips()
#     v6_net = slice_delegate.get_network(name=v6net_name)
#     v6_net_available_ips = v6_net.get_available_ips()
#     iface_v4 = delegate.get_interface(network_name=v4net_name)
#     iface_v6 = delegate.get_interface(network_name=v6net_name)
#
#     if v4_net_available_ips:
#         addr_v4 = v4_net_available_ips.pop(0)
#         iface_v4.ip_addr_add(addr=addr_v4, subnet=v4_net.get_subnet())
#
#     if v6_net_available_ips:
#         addr_v6 = v6_net_available_ips.pop(0)
#         iface_v6.ip_addr_add(addr=addr_v6, subnet=v6_net.get_subnet())
#
#     delegate.ip_route_add(subnet=FABRIC_PRIVATE_IPV4_SUBNET, gateway=v4_net.get_gateway())
#     delegate.ip_route_add(subnet=FABRIC_PUBLIC_IPV6_SUBNET, gateway=v6_net.get_gateway())


def add_ip_address_to_network(slice_delegate, node, net_name, node_addr, subnet, retry):
    delegate = slice_delegate.get_node(node.name)

    itfs = [itf for itf in delegate.get_interfaces() if FABRIC_STITCH_NET_IFACE_NAME in itf.get_name()]
    assert len(itfs) == 1, f"expecting one stitch interface ....{[itf.get_name() for itf in itfs]}"
    itf = itfs[0]

    if itf.get_ip_addr() and str(node_addr) == str(itf.get_ip_addr()):
        return

    for attempt in range(retry):
        logger.info(f'adding ip addr {node_addr}:{subnet}: {net_name}:{node.name}:attempt={attempt + 1}')
        itf.ip_addr_add(addr=node_addr, subnet=subnet)
        delegate = slice_delegate.get_node(node.name)
        itfs = [itf for itf in delegate.get_interfaces() if FABRIC_STITCH_NET_IFACE_NAME in itf.get_name()]
        assert len(itfs) == 1, f"expecting one stitch interface ....{[itf.get_name() for itf in itfs]}"
        itf = itfs[0]

        if itf.get_ip_addr() and str(node_addr) == str(itf.get_ip_addr()):
            return

        if attempt == retry:
            break

        time.sleep(2)

    logger.warning(f'Giving up: adding ip addr: {node_addr} after {retry} attempts')


def add_route(slice_delegate, node, vpc_subnet, gateway, retry):
    if has_ip_route(slice_delegate, node, vpc_subnet, gateway):
        logger.info(f"already exists when adding route: {vpc_subnet}:gateway={gateway}")
        return

    for attempt in range(retry):
        logger.info(f"adding route: {vpc_subnet}:gateway={gateway}:attempt={attempt + 1}")
        delegate = slice_delegate.get_node(node.name)
        delegate.ip_route_add(subnet=vpc_subnet, gateway=gateway)

        if has_ip_route(slice_delegate, node, vpc_subnet, gateway):
            logger.info(f"added: {vpc_subnet}:gateway={gateway}:attempt={attempt + 1}")
            return

        if attempt == retry:
            break

        time.sleep(2)

    logger.warning(f"Giving up:adding route: {vpc_subnet}:gateway={gateway} after {retry} attempts")


def init_slice(name: str, destroy_phase):
    from fabrictestbed_extensions.fablib.fablib import fablib

    # noinspection PyBroadException
    slice_object = None

    # noinspection PyBroadException
    try:
        slice_object = fablib.get_slice(name=name)
        logger.info(f"Found slice {name}:state={slice_object.get_state()}")
    except Exception:
        if not destroy_phase:
            slice_object = fablib.new_slice(name=name)
            logger.info(f"Created fresh slice {name}:state={slice_object.get_state()}")
            return slice_object

    if destroy_phase:
        return slice_object

    assert slice_object.get_state() not in ["Closing", "Dead"]

    if slice_object.get_state() in ["StableError", "ModifyError"]:
        logger.warning(f"Destroying slice {name}:state={slice_object.get_state()}")
        slice_object.delete()

        import time

        time.sleep(5)
        return fablib.new_slice(name=name)

    if slice_object.get_state() in ["Nascent", "Configuring", "Modifying", "ModifyOK"]:
        logger.warning(f"slice {name}:state={slice_object.get_state()}. Waiting for StableOK")

        try:
            slice_object.wait(timeout=24 * 60, progress=True)
        except Exception as e:
            state = slice_object.get_state()
            logger.warning(f"Exception occurred while waiting for StableOK: state={state}:{e}")
            raise e

    assert slice_object.get_state() == "StableOK"
    return slice_object


def patch_for_token():
    if not PATCH_FOR_TOKENS:
        return

    def load_tokens(self, refresh: bool = True):
        """
        Load Fabric Tokens from the tokens.json if it exists
        Otherwise, this is the first attempt, create the tokens and save them
        @note this function is invoked when reloading the tokens to ensure tokens
        from the token file are read instead of the local variables
        """
        import os
        import json

        # Load the tokens from the JSON
        if os.path.exists(self.token_location):
            with open(self.token_location, 'r') as stream:
                self.tokens = json.loads(stream.read())
            refresh_token = self.get_refresh_token()
        else:
            # First time login, use environment variable to load the tokens
            from fabrictestbed.util.constants import Constants

            refresh_token = os.environ.get(Constants.CILOGON_REFRESH_TOKEN)
        if refresh_token is None:
            return
        # Renew the tokens to ensure any project_id changes are taken into account
        if refresh and self.auto_refresh:
            self.refresh_tokens(refresh_token=refresh_token)

    from fabrictestbed.slice_manager.slice_manager import SliceManager

    mngr = SliceManager
    mngr._SliceManager__load_tokens = load_tokens
