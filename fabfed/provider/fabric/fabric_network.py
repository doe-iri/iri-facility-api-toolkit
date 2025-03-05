from ipaddress import IPv4Address
from typing import List, Dict, Union

from fabrictestbed_extensions.fablib.network_service import NetworkService
from fabrictestbed_extensions.fablib.slice import Slice

from fabfed.model import Network
from fabfed.policy.policy_helper import get_stitch_port_for_provider
from fabfed.util.constants import Constants
from fabfed.util.utils import get_logger
from .fabric_provider import FabricProvider
from ...util.config_models import Config

logger = get_logger()


class FabricNetwork(Network):
    def __init__(self, *, label, delegate: NetworkService, layer3: Config,
                 peering: Union[List[Config], Config], peer_layer3: Config):
        self.name = delegate.get_name()
        self.site = delegate.get_site()
        super().__init__(label=label, name=self.name, site=self.site)
        self._delegate = delegate
        self.site = delegate.get_site()
        self.slice_name = self._delegate.get_slice().get_name()
        self.type = str(delegate.get_type())

        self.layer3 = layer3
        self.peering = peering
        self.peer_layer3 = peer_layer3
        ns = self._delegate.get_fim_network_service()
        self.interface = []

        if self.peering and isinstance(self.peering, list):
            for peering in self.peering:
                if Constants.RES_CLOUD_ACCOUNT in peering.attributes:
                    self.interface.append(dict(id=self.slice_name, provider="fabric"))
        elif self.peering and Constants.RES_CLOUD_ACCOUNT in self.peering.attributes:
            self.interface.append(dict(id=self.slice_name, provider="fabric"))

        for key, iface in ns.interfaces.items():
            if hasattr(iface.labels, "vlan") and iface.labels.vlan:
                self.interface.append(dict(id=key, vlan=iface.labels.vlan))

        self.id = self._delegate.get_reservation_id()
        self.state = self._delegate.get_reservation_state()

    @property
    def subnet(self):
        return self.layer3.attributes.get(Constants.RES_SUBNET) if self.layer3 else None

    @property
    def gateway(self):
        return self.layer3.attributes.get(Constants.RES_NET_GATEWAY) if self.layer3 else None

    @property
    def delegate(self):
        return self._delegate

    def available_ips(self) -> list:
        available_ips = []

        if self.layer3:
            ip_start = self.layer3.attributes.get(Constants.RES_LAYER3_DHCP_START)
            ip_end = self.layer3.attributes.get(Constants.RES_LAYER3_DHCP_END)

            if ip_start and ip_end:
                pool_start = int(IPv4Address(ip_start))
                pool_end = int(IPv4Address(ip_end))

                for ip_int in range(pool_start + 1, pool_end + 1):
                    available_ips.append(IPv4Address(ip_int))

        return available_ips

    def get_reservation_id(self):
        self._delegate.get_reservation_id()

    def get_site(self):
        return self._delegate.get_site()


class NetworkBuilder:
    def __init__(self, label, provider: FabricProvider, slice_object: Slice, name, resource: dict):
        from fabfed.policy.policy_helper import StitchInfo

        self.provider = provider
        self.slice_object = slice_object
        self.stitch_infos: List[StitchInfo] = resource.get(Constants.RES_STITCH_INFO)
        self.stitch_port = get_stitch_port_for_provider(resource=resource, provider=provider.type)
        self.site = resource.get(Constants.RES_SITE)
        self.facility_cloud_port_interfaces = []
        self.facility_non_cloud_port_interfaces = []
        self.net_name = name
        self.layer3 = resource.get(Constants.RES_LAYER3)
        self.peering: Union[List[Config], Config] = resource.get(Constants.RES_PEERING)
        self.peer_layer3 = resource.get(Constants.RES_PEER_LAYER3)
        self.stitching_nets = []
        self.label = label
        self.net: Union[NetworkService, None] = None
        self.bw = resource.get(Constants.RES_BW)
        self.discovered_stitch_infos: List[Dict] = []
        self.sites = set()

        import fabfed.provider.api.dependency_util as util

        if util.has_resolved_external_dependencies(resource=resource, attribute=Constants.RES_STITCH_INTERFACE):
            self.stitching_nets = util.get_values_for_dependency(resource=resource,
                                                                 attribute=Constants.RES_STITCH_INTERFACE)

            for stitching_net in self.stitching_nets:
                interface = stitching_net.interface
                assert isinstance(interface, list)
                interface = next(iter([i for i in interface if isinstance(i, dict) and 'provider' in i]))
                logger.info(f'Network {self.net_name} got stitching interface {interface} from {stitching_net.label}')
                discovered_stitch_info = dict()
                discovered_stitch_info.update(interface)
                self.discovered_stitch_infos.append(discovered_stitch_info)

        if self.peering and not isinstance(self.peering, list):
            self.peering = [self.peering]

        if self.stitch_port and not isinstance(self.stitch_port, list):
            self.stitch_port = [self.stitch_port]

        if self.peering:
            from .plugins import Plugins

            Plugins.load()

    @staticmethod
    def _get_stitch_info_index(peering, stitch_ports):
        for idx, stitch_port in enumerate(stitch_ports):
            if peering.attributes[Constants.LABELS] == stitch_port[Constants.LABELS]:
                return idx

        raise Exception(f"Did not expect peering {peering} with no stitch port")

    def handle_facility_port(self, *, sites):
        from fim.slivers.capacities_labels import Labels, Capacities

        self.sites.update(sites)

        if self.peering:
            for peering in self.peering:
                idx = self._get_stitch_info_index(peering, self.stitch_port)
                cloud = peering.attributes.get(Constants.RES_CLOUD_FACILITY)

                if not cloud:
                    cloud = self.stitch_port[idx].get(Constants.STITCH_PORT_SITE)
                    peering.attributes[Constants.RES_CLOUD_FACILITY] = cloud

            for peering in self.peering:
                idx = self._get_stitch_info_index(peering, self.stitch_port)
                cloud = peering.attributes.get(Constants.RES_CLOUD_FACILITY)
                asn = peering.attributes.get(Constants.RES_REMOTE_ASN)
                account_id = peering.attributes.get(Constants.RES_CLOUD_ACCOUNT)

                if account_id is None:
                    for discovered_stitch_info in self.discovered_stitch_infos:
                        if self.stitch_port[idx]['peer']['provider'] == discovered_stitch_info['provider']:
                            account_id = discovered_stitch_info.get("id")  # GCP's Pairing Key
                            break

                if account_id is None:
                    raise Exception(f"Missing {Constants.RES_CLOUD_ACCOUNT}:{peering}")

                subnet = peering.attributes.get(Constants.RES_LOCAL_ADDRESS)
                peer_subnet = peering.attributes.get(Constants.RES_REMOTE_ADDRESS)
                region = peering.attributes.get(Constants.RES_CLOUD_REGION)
                device = peering.attributes.get(Constants.RES_LOCAL_DEVICE)
                port = peering.attributes.get(Constants.RES_LOCAL_PORT)
                vlan = peering.attributes.get(Constants.RES_CLOUD_VLAN)
                bw = peering.attributes.get(Constants.RES_CLOUD_BW, 50)
                mtu = peering.attributes.get(Constants.RES_CLOUD_MTU)
                bgp_key = peering.attributes[Constants.RES_SECURITY]

                if not device:
                    device = self.stitch_port[idx].get(Constants.STITCH_PORT_DEVICE_NAME)

                if not port:
                    port = self.stitch_port[idx].get(Constants.STITCH_PORT_LOCAL_NAME)

                if not region:
                    region = self.stitch_port[idx].get(Constants.STITCH_PORT_REGION)

                if not cloud:
                    cloud = self.stitch_port[idx].get(Constants.STITCH_PORT_SITE)

                labels = Labels(ipv4_subnet=subnet)

                if vlan:
                    labels = Labels.update(labels, vlan=str(vlan))

                if device:
                    labels = Labels.update(labels, device_name=device)
                if port:
                    labels = Labels.update(labels, local_name=port)

                if cloud == "GCP":
                    peer_labels = Labels(ipv4_subnet=peer_subnet,
                                         asn=str(asn),
                                         bgp_key=bgp_key,
                                         account_id=account_id,
                                         # region=region,
                                         local_name='Google Cloud Platform')
                else:
                    peer_labels = Labels(ipv4_subnet=peer_subnet,
                                         asn=str(asn),
                                         bgp_key=bgp_key,
                                         account_id=account_id,
                                         region=region,
                                         local_name=cloud)

                logger.info(f"Creating_Facility_Port:Labels: {labels}")
                logger.info(f"Creating_Facility_Port:PeerLabels: {peer_labels}")

                if not mtu:
                    if cloud == "GCP":
                        mtu = 1460
                    else:
                        mtu = 9001

                capacities = Capacities(bw=int(bw), mtu=int(mtu))
                logger.info(f"Creating_Facility_Port:Capacities: {capacities}")

                facility_port = self.slice_object.add_facility_port(
                    name='Cloud-Facility-' + cloud,
                    site=cloud,
                    labels=labels,
                    peer_labels=peer_labels,
                    capacities=capacities)

                facility_port_interface = facility_port.get_interfaces()[0]
                self.facility_cloud_port_interfaces.append(facility_port_interface)
                logger.info("Done_Creating_Facility_Port:" + facility_port.toJson())
                return

        devices = set()

        for discovered_stitch_info in self.discovered_stitch_infos:
            if 'site' not in discovered_stitch_info:
                continue

            site = discovered_stitch_info[Constants.STITCH_PORT_SITE]
            assert site not in ['AWS', 'GCP']

            logger.info(
                f'{self.net_name} will use stitch info: {discovered_stitch_info}')

            device = discovered_stitch_info[Constants.STITCH_PORT_DEVICE_NAME]
            devices.add(device)
            site = discovered_stitch_info[Constants.STITCH_PORT_SITE]
            vlan = discovered_stitch_info[Constants.STITCH_PORT_VLAN]
            self.sites.add(site)
            logger.info(f"Adding Facility Port to slice: name={device}:site={site}:vlan={vlan}")

            from fabrictestbed_extensions.fablib.facility_port import FacilityPort

            fim_facility_port = self.slice_object.get_fim_topology().add_facility(
                name=device,
                site=site,
                capacities=Capacities(bw=self.bw),
                labels=Labels(vlan=str(vlan)),
            )

            facility_port = FacilityPort(self.slice_object, fim_facility_port)

            # facility_port = self.slice_object.add_facility_port(name=device,
            #                                                     site=site,
            #                                                     vlan=str(vlan))
            facility_port_interface = facility_port.get_interfaces()[0]
            self.facility_non_cloud_port_interfaces.append(facility_port_interface)

        if len(devices) != len(self.stitch_infos):
            from fabfed.policy.facility_port_handler import load_facility_info_using_stich_port
            from fabfed.policy.tag_handler import get_available_vlan

            for stitch_port in self.stitch_port:
                device = stitch_port[Constants.STITCH_PORT_DEVICE_NAME]

                if device in devices:
                    continue

                load_facility_info_using_stich_port(stitch_port)
                site = stitch_port[Constants.STITCH_PORT_SITE]
                vlan = get_available_vlan(stitch_port=stitch_port)
                self.sites.add(site)
                logger.info(f"Adding Facility Port to slice: name={device}:site={site}:vlan={vlan}")

                from fabrictestbed_extensions.fablib.facility_port import FacilityPort

                fim_facility_port = self.slice_object.get_fim_topology().add_facility(
                    name=device,
                    site=site,
                    capacities=Capacities(bw=self.bw),
                    labels=Labels(vlan=str(vlan)),
                )
                facility_port = FacilityPort(self.slice_object, fim_facility_port)

                # facility_port = self.slice_object.add_facility_port(name=device,
                #                                                     site=site,
                #                                                     vlan=str(vlan))
                facility_port_interface = facility_port.get_interfaces()[0]
                self.facility_non_cloud_port_interfaces.append(facility_port_interface)

    def handle_network(self):
        if self.facility_cloud_port_interfaces:
            tech = 'AL2S'
            port_names = [n.get_name() for n in self.facility_cloud_port_interfaces]

            logger.info(f"Creating L3VPN Network:{self.net_name}:FacilityPorts:{port_names}:techonolgy={tech}")

            self.net = self.slice_object.add_l3network(name=self.net_name,
                                                       interfaces=self.facility_cloud_port_interfaces,
                                                       type='L3VPN',
                                                       technology=tech)

        if self.facility_non_cloud_port_interfaces:
            if len(self.sites) == 2:
                net_type = 'L2STS'
            elif len(self.sites) == 1:
                net_type = 'L2Bridge'
            else:
                raise Exception(f"The number of sites in {self.sites} is not supported")

            port_names = [i.get_name() for i in self.facility_non_cloud_port_interfaces]
            logger.info(f"Creating {net_type} Network:{self.net_name}:FacilityPorts:{port_names}")
            # self.net = self.slice_object.add_l2network(name=self.net_name, type=net_type)
            self.net = self.slice_object.add_l2network(name=self.net_name)

            # We loop for now. Maybe we can remove in a later release post 1.7.3.
            for itf in self.facility_non_cloud_port_interfaces:
                self.net.add_interface(itf)

    def build(self) -> FabricNetwork:
        assert self.net
        return FabricNetwork(label=self.label, delegate=self.net, layer3=self.layer3,
                             peering=self.peering, peer_layer3=self.peer_layer3)
