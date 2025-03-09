import logging
import os
from typing import List

import fabfed.provider.api.dependency_util as util
from fabfed.exceptions import ResourceTypeNotSupported, ProviderException
from fabfed.model import Resource
from fabfed.provider.api.provider import Provider
from fabfed.util.constants import Constants
from fabfed.util.utils import get_logger
from .chi_constants import *

logger: logging.Logger = get_logger()


class ChiProvider(Provider):
    def __init__(self, *, type, label, name, config: dict[str, str]):
        super().__init__(type=type, label=label, name=name, logger=logger, config=config)
        self.helper = None

    def setup_environment(self):
        site = "CHI@UC"
        config = self.config

        for attr in CHI_CONF_ATTRS:
            if config.get(attr) is None:
                raise ProviderException(f"{self.name}: Expecting a value for {attr}")

        if not isinstance(config[CHI_PROJECT_ID], dict):
            raise ProviderException(f"{self.name}: Expecting a dictionary for {CHI_PROJECT_ID}")

        temp = {}

        for k, v in config[CHI_PROJECT_ID].items():
            temp[k.lower()] = config[CHI_PROJECT_ID][k]

        if "uc" not in temp or "tacc" not in temp:
            raise ProviderException(f"{self.name}: Expecting a dictionary for {CHI_PROJECT_ID} for uc and tacc")

        config[CHI_PROJECT_ID] = temp

        from fabfed.util.utils import can_read, is_private_key, absolute_path

        pkey = config[CHI_SLICE_PRIVATE_KEY_LOCATION]
        pkey = absolute_path(pkey)

        if not can_read(pkey) or not is_private_key(pkey):
            raise ProviderException(f"{self.name}: unable to read/parse ssh key in {pkey}")

        self.config[CHI_SLICE_PRIVATE_KEY_LOCATION] = pkey

        pub_key = self.config[CHI_SLICE_PUBLIC_KEY_LOCATION]
        pubkey = absolute_path(pub_key)

        if not can_read(pubkey):
            raise ProviderException(f"{self.name}: unable to read/parse ssh key in {pubkey}")

        self.config[CHI_SLICE_PUBLIC_KEY_LOCATION] = pub_key

        site_id = self.__get_site_identifier(site=site)
        os.environ['OS_AUTH_URL'] = config.get(CHI_AUTH_URL, DEFAULT_AUTH_URLS)[site_id]
        os.environ['OS_IDENTITY_API_VERSION'] = "3"
        os.environ['OS_INTERFACE'] = "public"
        os.environ['OS_PROJECT_ID'] = config.get(CHI_PROJECT_ID)[site_id]
        os.environ['OS_USERNAME'] = config.get(CHI_USER)
        os.environ['OS_PROTOCOL'] = "openid"
        os.environ['OS_AUTH_TYPE'] = "v3oidcpassword"
        os.environ['OS_PASSWORD'] = config.get(CHI_PASSWORD)
        os.environ['OS_IDENTITY_PROVIDER'] = "chameleon"
        os.environ['OS_DISCOVERY_ENDPOINT'] = DEFAULT_DISCOVERY_URL
        os.environ['OS_CLIENT_ID'] = config.get(CHI_CLIENT_ID, DEFAULT_CLIENT_IDS)[site_id]
        os.environ['OS_ACCESS_TOKEN_TYPE'] = "access_token"
        os.environ['OS_CLIENT_SECRET'] = "none"
        os.environ['OS_REGION_NAME'] = site
        os.environ['OS_SLICE_PRIVATE_KEY_FILE'] = config.get(CHI_SLICE_PRIVATE_KEY_LOCATION)
        os.environ['OS_SLICE_PUBLIC_KEY_FILE'] = config.get(CHI_SLICE_PUBLIC_KEY_LOCATION)

    def do_validate_resource(self, *, resource: dict):
        label = resource[Constants.LABEL]
        rtype = resource.get(Constants.RES_TYPE)

        if rtype not in [Constants.RES_TYPE_NETWORK, Constants.RES_TYPE_NODE]:
            raise ResourceTypeNotSupported(f"resource {rtype} not supported")

        site = resource.get(Constants.RES_SITE)

        if site is None and Constants.CONFIG in resource:
            site = resource[Constants.CONFIG].get(Constants.RES_SITE)

            if site is None:
                raise ProviderException(f"{self.label} expecting a site in {rtype} resource {label}")

        resource[Constants.RES_SITE] = site

    def supports_modify(self):
        return True

    def _setup_environment(self, *, site: str):
        site_id = self.__get_site_identifier(site=site)
        os.environ['OS_AUTH_URL'] = self.config.get(CHI_AUTH_URL, DEFAULT_AUTH_URLS)[site_id]
        os.environ['OS_PROJECT_ID'] = self.config.get(CHI_PROJECT_ID)[site_id]
        os.environ['OS_CLIENT_ID'] = self.config.get(CHI_CLIENT_ID, DEFAULT_CLIENT_IDS)[site_id]

    @staticmethod
    def __get_site_identifier(*, site: str):
        if site == "CHI@UC":
            return "uc"
        elif site == "CHI@TACC":
            return "tacc"
        elif site == "CHI@NU":
            return "nu"
        elif site == "KVM@TACC":
            return "kvm"
        elif site == "CHI@Edge":
            return "edge"
        else:
            return "uc"

    def do_add_resource(self, *, resource: dict):
        label = resource[Constants.LABEL]
        rtype = resource[Constants.RES_TYPE]
        site = resource[Constants.RES_SITE]
        creation_details = resource[Constants.RES_CREATION_DETAILS]

        if not creation_details['in_config_file']:
            return

        self._setup_environment(site=site)
        key_pair = self.config[CHI_KEY_PAIR]
        project_name = self.config[CHI_PROJECT_NAME]

        if rtype == Constants.RES_TYPE_NODE:
            network = resource.get(Constants.RES_NETWORK, DEFAULT_NETWORK)

            if util.has_resolved_internal_dependencies(resource=resource, attribute='network'):
                net = util.get_single_value_for_dependency(resource=resource, attribute='network')
                network = net.name

            node_count = resource[Constants.RES_COUNT]
            image = resource.get(Constants.RES_IMAGE, DEFAULT_IMAGE)
            flavor = resource.get(Constants.RES_FLAVOR, DEFAULT_FLAVOR)

            for n in range(0, node_count):
                node_name = self.resource_name(resource, n)
                self.existing_map[label].append(node_name)

                from fabfed.provider.chi.chi_node import ChiNode

                node = ChiNode(label=label, name=node_name, image=image, site=site, flavor=flavor,
                               key_pair=key_pair, network=network, project_name=project_name)
                self.nodes.append(node)

                if self.resource_listener:
                    self.resource_listener.on_added(source=self, provider=self, resource=node)
            return

        layer3 = resource.get(Constants.RES_LAYER3)
        from fabfed.policy.policy_helper import StitchInfo
        stitch_infos: List[StitchInfo] = resource.get(Constants.RES_STITCH_INFO)
        assert stitch_infos, f"resource {label} missing stitch info"
        assert isinstance(stitch_infos, list), f"resource {label} expecting a list for stitch info"
        assert len(stitch_infos) == 1, f"resource {label} expect a list of size for stitch info "

        peer_stitch_port = stitch_infos[0].stitch_port['peer']
        assert peer_stitch_port['provider'] != self.type, f"resource {label} stitch provider has wrong type"

        vlan_saved = False

        if self.retrieve_attribute_from_saved_state(resource, self.resource_name(resource), attribute='interface'):
            net_name = self.resource_name(resource)
            interface = self.retrieve_attribute_from_saved_state(resource, net_name, attribute='interface')

            vlan = interface['vlan']

            if isinstance(vlan, str):
                vlan = int(vlan)

            interfaces = resource.get(Constants.RES_INTERFACES, list())

            if interfaces and interfaces[0]['vlan'] != vlan:
                self.logger.warning(
                    f"{self.label} ignoring: {label}'s interface {interfaces} does not match provisioned vlan {vlan}")

            resource[Constants.RES_INTERFACES] = [{'vlan': vlan}]
            vlan_saved = True

        discovered_interface = None

        if util.has_resolved_external_dependencies(resource=resource, attribute=Constants.RES_STITCH_INTERFACE):
            stitching_nets = util.get_values_for_dependency(resource=resource,
                                                            attribute=Constants.RES_STITCH_INTERFACE)

            for interface in stitching_nets[0].interface:
                if peer_stitch_port['device_name'] in interface['id']:
                    discovered_interface = interface
                    break

        if not discovered_interface:
            raise Exception(f"Did not find peer interface for {peer_stitch_port['device_name']}")

        if discovered_interface:
            vlan = discovered_interface['vlan']
        elif resource.get(Constants.RES_INTERFACES, list()):
            interfaces = resource.get(Constants.RES_INTERFACES) 
            if 'vlan' not in interfaces[0]:
               raise ProviderException(f"{self.label} expecting {label}'s interface to have a vlan")

            vlan = interfaces[0]['vlan']

            if not vlan_saved:
                from fabfed.policy.facility_port_handler import load_facility_info
                from fabfed.exceptions import ResourceNotAvailable

                load_facility_info(stitch_infos)

                if vlan in peer_stitch_port['allocated_vlans']:
                    raise ResourceNotAvailable(
                        f"vlan {vlan} is already used. allocated_vlans={peer_stitch_port['allocated_vlans']}")

        else:
            from fabfed.policy.facility_port_handler import load_facility_info
            from fabfed.policy.tag_handler import get_available_vlan

            load_facility_info(stitch_infos)
            vlan = get_available_vlan(stitch_port=peer_stitch_port)

        net_name = self.resource_name(resource)
        from fabfed.provider.chi.chi_network import ChiNetwork

        net = ChiNetwork(label=label, name=net_name, site=site,
                         layer3=layer3, stitch_info=stitch_infos[0],
                         project_name=project_name, vlan=int(vlan))
        self._networks.append(net)

        if self.resource_listener:
            self.resource_listener.on_added(source=self, provider=self, resource=net)

    def do_create_resource(self, *, resource: dict):
        site = resource.get(Constants.RES_SITE)
        self._setup_environment(site=site)
        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)

        if rtype == Constants.RES_TYPE_NETWORK:
            if self.modified:
                net_name = self.resource_name(resource)

                if net_name in self.existing_map[label] and net_name not in self.added_map.get(label, list()):
                    from fabfed.provider.chi.chi_network import ChiNetwork
                    from ...util.config_models import Config

                    layer3 = Config("", "", {})
                    project_name = self.config[CHI_PROJECT_NAME]

                    net = ChiNetwork(label=label, name=net_name, site=site,
                                     layer3=layer3, stitch_info=None, project_name=project_name, vlan=-1)
                    net.delete()

                    self.logger.info(f"Deleted network: {net_name} at site {site}")

                    if self.resource_listener:
                        self.resource_listener.on_deleted(source=self, provider=self, resource=net)

                    return

            net = next(filter(lambda n: n.label == label, self.networks))
            net.create()

            if self.resource_listener:
                self.resource_listener.on_created(source=self, provider=self, resource=net)

        else:
            from fabfed.provider.chi.chi_node import ChiNode

            temp: List[ChiNode] = [node for node in self._nodes if node.label == label]

            if self.modified:
                for node_name in self.existing_map[label]:
                    key_pair = self.config[CHI_KEY_PAIR]
                    project_name = self.config[CHI_PROJECT_NAME]

                    if node_name not in self.added_map.get(label, list()):
                        from fabfed.provider.chi.chi_node import ChiNode

                        node = ChiNode(label=label, name=node_name, image='', site=site, flavor='',
                                       key_pair=key_pair, network='', project_name=project_name)
                        node.delete()

                        self.logger.info(f"Deleted node: {node_name} at site {site}")

                        if self.resource_listener:
                            self.resource_listener.on_deleted(source=self, provider=self, resource=node)

            for node in temp:
                node.create()

    def do_wait_for_create_resource(self, *, resource: dict):
        site = resource.get(Constants.RES_SITE)
        self._setup_environment(site=site)
        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)

        if rtype == Constants.RES_TYPE_NETWORK:
            pass
        else:
            from fabfed.provider.chi.chi_node import ChiNode

            temp: List[ChiNode] = [node for node in self._nodes if node.label == label]

            for node in temp:
                node.wait_for_active()

            for node in temp:
                node.wait_for_ssh()

                if self.resource_listener:
                    self.resource_listener.on_created(source=self, provider=self, resource=node)

    def do_handle_externally_depends_on(self, *, resource: Resource, dependee: Resource):
        # post process can be done here ....
        pass

    # noinspection PyTypeChecker
    def do_delete_resource(self, *, resource: dict):
        site = resource.get(Constants.RES_SITE)
        self._setup_environment(site=site)
        key_pair = self.config[CHI_KEY_PAIR]
        project_name = self.config[CHI_PROJECT_NAME]
        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)

        if rtype == Constants.RES_TYPE_NETWORK.lower():
            net_name = self.resource_name(resource)
            self.logger.debug(f"Deleting network: {net_name} at site {site}")
            from fabfed.provider.chi.chi_network import ChiNetwork
            from ...util.config_models import Config

            layer3 = Config("", "", {})

            net = ChiNetwork(label=label, name=net_name, site=site,
                             layer3=layer3, stitch_info=None, project_name=project_name, vlan=-1)
            net.delete()
            self.logger.info(f"Deleted network: {net_name} at site {site}")

            if self.resource_listener:
                self.resource_listener.on_deleted(source=self, provider=self, resource=net)
        else:
            node_count = resource.get(Constants.RES_COUNT, 1)

            for n in range(0, node_count):
                node_name = self.resource_name(resource, n)
                self.logger.debug(f"Deleting node: {node_name} at site {site}")

                from fabfed.provider.chi.chi_node import ChiNode

                node = ChiNode(label=label, name=node_name, image=None, site=site, flavor=None,
                               key_pair=key_pair, network=None, project_name=project_name)
                node.delete()
                self.logger.info(f"Deleted node: {node_name} at site {site}")

                if self.resource_listener:
                    self.resource_listener.on_deleted(source=self, provider=self, resource=node)
