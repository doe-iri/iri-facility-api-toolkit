import json
import logging
import time

import chi
import chi.network
import chi.server

from amscrot.model import Network
from .chi_util import LeaseHelper
from ...util.config_models import Config
from ...util.constants import Constants
from .chi_constants import INCLUDE_ROUTER


from amscrot.util.utils import get_logger

logger: logging.Logger = get_logger()


class ChiNetwork(Network):
    def __init__(self, *, label, name: str, site: str, project_name: str, layer3: Config,
                 stitch_info, vlan: int):
        super().__init__(label=label, name=name, site=site)
        self.project_name = project_name
        self.layer3 = layer3
        self.subnet = layer3.attributes.get(Constants.RES_SUBNET)
        self.ip_start = layer3.attributes.get(Constants.RES_LAYER3_DHCP_START)
        self.ip_end = layer3.attributes.get(Constants.RES_LAYER3_DHCP_END)
        self.gateway = layer3.attributes.get(Constants.RES_NET_GATEWAY, None)
        self.stitch_info = stitch_info
        self.stitch_provider = None

        if stitch_info is not None:
            self.stitch_provider = stitch_info.stitch_port['peer']['provider']

        self._retry = 10 
        self.lease_name = f'{name}-lease'
        self.subnet_name = f'{name}-subnet'
        self.router_name = f'{name}-router'

        if vlan > 0:
            resource_properties = json.dumps(
                ["and", ["==", "$stitch_provider", self.stitch_provider], ["==", "$segment_id", str(vlan)]], indent=3
            )
        else:
            resource_properties = json.dumps(
                ["==", "$stitch_provider", self.stitch_provider], indent=3
            )

        logger.info(f"Using resource_properties:{resource_properties}")

        self.reservations = [{
            "resource_type": "network",
            "network_name": self.name,
            "network_properties": "",
            "resource_properties": resource_properties
        }]

        self.vlans = list()
        self.interface = list()
        self.logger = logger
        self._lease_helper = LeaseHelper(lease_name=self.lease_name, logger=self.logger)

    def get_reservation_id(self):
        return self._lease_helper.get_reservation_id()

    def get_vlans(self) -> list:
        return self.vlans

    def create(self):
        import json

        chi.set('project_name', self.project_name)
        chi.set('project_domain_name', 'default')
        chi.use_site(self.site)
        self._lease_helper.create_lease_if_needed(reservations=self.reservations, retry=self._retry)
        self.logger.debug(f"Using active lease {self.lease_name}:lease={json.dumps(self._lease_helper.lease, indent=3)}")

        self.vlans = []
        self.interface = []
        network_vlan = None
        chameleon_network_id = None
        chameleon_network = dict()

        for attempt in range(self._retry):
            try:
                chameleon_network = chi.network.get_network(self.name)
                chameleon_network_id = chameleon_network['id']

                if 'provider:segmentation_id' in chameleon_network:
                    network_vlan = chameleon_network['provider:segmentation_id']
                    break
            except Exception as e:
                self.logger.error(f'Error while retrieving vlan:{self.name}:{e}')

            self.logger.warning(f'Network is not ready {self.name}. Trying again! attempt={attempt}:network_details=={chameleon_network}')
            time.sleep(12)

        if network_vlan is None:
             temp = dict()

             if chameleon_network:
                 temp = json.dumps(chameleon_network, indent=3)

             self.logger.error(f"Network {self.name} did not get vlan using 'provider:segmentation_id':network_details=={temp}")
             raise Exception(f"Network {self.name} did not get vlan using 'provider:segmentation_id':network_details=={chameleon_network}")

        self.logger.info(f'Got network. network_name: {self.name}, network_vlan: {network_vlan}')
        self.vlans.append(network_vlan)

        for vlan in self.vlans:
            temp = dict(id=self.label, vlan=vlan)
            temp.update(self.stitch_info.stitch_port['peer'])
            temp['provider'] = self.stitch_info.stitch_port['provider']
            self.interface.append(temp)

        try:
            chameleon_subnet = chi.network.get_subnet(self.subnet_name)
            self.logger.info(f'Subnet already created: {self.subnet_name}')
        except Exception as e:
            self.logger.warning(f'Error while creating subnet: {self.subnet_name} {e}')
            chameleon_subnet = None

        if not chameleon_subnet:
            chameleon_subnet = chi.network.create_subnet(self.subnet_name, chameleon_network_id,
                                                         cidr=self.subnet,
                                                         allocation_pool_start=self.ip_start,
                                                         allocation_pool_end=self.ip_end,
                                                         gateway_ip=self.gateway)
            self.logger.info(f'Created subnet {self.subnet_name}')

        self.logger.debug(f'Subnet: {chameleon_subnet}')
        chameleon_router = None

        # we do not use get as it throws an exception if not found. So we list them
        for router in chi.network.list_routers():
            if router['name'] == self.router_name:
                chameleon_router = router
                break

        if not INCLUDE_ROUTER:
            return

        if chameleon_router:
            self.logger.info(f'Router already created: {self.router_name}')
            self.logger.debug(f'Router: {chameleon_router}')
        else:
            chameleon_router = chi.network.create_router(self.router_name, gw_network_name='public')
            self.logger.info(f'Router created: {self.router_name}')
            chi.network.add_subnet_to_router_by_name(self.router_name, self.subnet_name)
            self.logger.info(f'Attached subnet {self.subnet_name} to router  {self.router_name}')
            self.logger.debug(f'Router: {chameleon_router}')

    def update_route(self, *, subnet: str, gateway_ip: str):
        chameleon_subnet = chi.network.get_subnet(self.subnet_name)
        body = {
            "subnet": {
                "host_routes": [
                    {
                        "destination": f"{subnet}",
                        "nexthop": f"{gateway_ip}"
                    }
                ]
            }
        }

        chi.neutron().update_subnet(subnet=chameleon_subnet['id'], body=body)

    def _delete(self):
        chi.set('project_name', self.project_name)
        chi.set('project_domain_name', 'default')
        chi.use_site(self.site)

        from neutronclient.common.exceptions import NotFound

        try:
            self.logger.debug(f"Removing subnet {self.subnet_name} from router {self.router_name}")
            subnet_id = chi.network.get_subnet_id(self.subnet_name)
            router_id = chi.network.get_router_id(self.router_name)
            chi.network.remove_subnet_from_router(router_id, subnet_id)
            self.logger.info(f"Removed subnet {self.subnet_name} from router {self.router_name}")
        except NotFound:
            pass
        except RuntimeError as re:
            if "No subnets found with" not in str(re) and "No routers found with" not in str(re):
                raise re

        if INCLUDE_ROUTER:
            try:
                router_id = chi.network.get_router_id(self.router_name)
                chi.network.delete_router(router_id)
                self.logger.info(f"Deleted router  {self.router_name} net_id={router_id}")
            except NotFound:
                pass
            except RuntimeError as re:
                if "No routers found with" not in str(re):
                    raise re

        try:
            subnet_id = chi.network.get_subnet_id(self.subnet_name)
            chi.network.delete_subnet(subnet_id)
            self.logger.info(f"Deleted subnet  {self.subnet_name} net_id={subnet_id}")
        except NotFound:
            pass
        except RuntimeError as re:
            if "No subnets found with" not in str(re):
                raise re

        try:
            net_id = chi.server.get_network_id(self.name)
            chi.network.delete_network(net_id)
            self.logger.info(f"Deleted network {self.name} net_id={net_id}")
        except NotFound:
            pass
        except RuntimeError as re:
            if "No networks found with" not in str(re):
                raise re

        self._lease_helper.delete_lease()

    def delete(self):
        import time

        ex = None

        for attempt in range(self._retry):
            try:
                self._delete()
                return
            except Exception as e:
                self.logger.warning(f"Error deleting network {self.name} {e}")
                ex = e

            time.sleep(12)

        raise Exception(f"Error while deleting network {self.name}:{ex}")
