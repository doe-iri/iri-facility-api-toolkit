from fabfed.policy.policy_helper import get_stitch_port_for_provider
from fabfed.exceptions import ResourceTypeNotSupported, ProviderException
from fabfed.provider.api.provider import Provider
from fabfed.util.utils import get_logger
from .sense_exceptions import SenseException
from .sense_constants import *

logger = get_logger()


class SenseProvider(Provider):
    def __init__(self, *, type, label, name, config: dict):
        super().__init__(type=type, label=label, name=name, logger=logger, config=config)
        self.supported_resources = [Constants.RES_TYPE_NETWORK,  Constants.RES_TYPE_NODE]
        self.initialized = False
        self._handled_modify = False

    def setup_environment(self):
        for attr in SENSE_CONF_ATTRS:
            if self.config.get(attr.lower()) is None and self.config.get(attr.upper()) is None:
                raise ProviderException(f"{self.name}: Expecting a value for {attr}")

        pkey = self.config[SENSE_SLICE_PRIVATE_KEY_LOCATION]

        from fabfed.util.utils import can_read, is_private_key, absolute_path

        pkey = absolute_path(pkey)

        if not can_read(pkey) or not is_private_key(pkey):
            raise ProviderException(f"{self.name}: unable to read/parse ssh key in {pkey}")

        self.config[SENSE_SLICE_PRIVATE_KEY_LOCATION] = pkey

    @property
    def private_key_file_location(self):
        from .sense_constants import SENSE_SLICE_PRIVATE_KEY_LOCATION

        return self.config.get(SENSE_SLICE_PRIVATE_KEY_LOCATION)

    def _handle_peering_config(self, resource):
        import fabfed.provider.api.dependency_util as util
        from fabfed.model import Network

        peering = resource.get(Constants.RES_PEERING)
        prop = 'stitch_interface'
        assert Constants.RES_SECURITY in peering.attributes

        if peering and util.has_resolved_external_dependencies(resource=resource, attribute=prop):
            net = util.get_single_value_for_dependency(resource=resource, attribute=prop)

            if isinstance(net, Network):
                iface = net.interface

                if isinstance(iface, list):
                    iface = iface[0]

                if isinstance(iface, dict) and iface.get("provider") == "fabric":
                    peering.attributes[Constants.RES_ID] = iface[Constants.RES_ID]
                    self.logger.info(f"Added id to peering config:id={iface[Constants.RES_ID]}")

        return peering

    def _init_client(self):
        if not self.initialized:
            self.logger.info(f"{self.name}: Initializing sense client")
            from .sense_client import init_client

            init_client(self.config)
            self.logger.info(f"{self.name}: Initialized sense client")
            self.initialized = True

    def do_add_resource(self, *, resource: dict):
        self._init_client()

        creation_details = resource[Constants.RES_CREATION_DETAILS]

        if not creation_details['in_config_file']:
            return

        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)

        if rtype not in self.supported_resources:
            raise ResourceTypeNotSupported(f"{rtype} for {label}")

        if rtype == Constants.RES_TYPE_NODE:
            from .sense_node import SenseNode
            import fabfed.provider.api.dependency_util as util
            from . import sense_utils

            assert util.has_resolved_internal_dependencies(resource=resource, attribute='network')
            net = util.get_single_value_for_dependency(resource=resource, attribute='network')
            profile_uuid = sense_utils.get_profile_uuid(profile=net.profile)
            vms = sense_utils.get_vms_specs_from_profile(profile_uuid=profile_uuid)

            count = resource[Constants.RES_COUNT]

            if count != len(vms):
                from fabfed.exceptions import ProviderException

                raise ProviderException(f'count {count} != sense_vm_specs: {len(vms)}')

            for idx, vm in enumerate(vms):
                node_name = self.resource_name(resource, idx)
                node = SenseNode(label=label, name=f'{node_name}', network=net.name, spec=vm, provider=self)
                self._nodes.append(node)

                if self.resource_listener:
                    self.resource_listener.on_added(source=self, provider=self, resource=node)

            return

        sense_stitch_port = get_stitch_port_for_provider(resource=resource, provider=self.type)
        interfaces = resource.get(Constants.RES_INTERFACES)

        if not interfaces and 'option' in sense_stitch_port:
            interfaces = sense_stitch_port['option'].get('interface')

        if interfaces:
            for interface in interfaces:
                if not interface.get(Constants.RES_BANDWIDTH):
                    interface[Constants.RES_BANDWIDTH] = resource.get(Constants.RES_BANDWIDTH)

        net_name = self.resource_name(resource)
        profile = resource.get(Constants.RES_PROFILE)

        if not profile and sense_stitch_port:
            profile = sense_stitch_port.get(Constants.RES_PROFILE)

        if not profile:
            raise SenseException(f"Must have a profile for {net_name}")

        layer3 = resource.get(Constants.RES_LAYER3)
        peering = self._handle_peering_config(resource)
        bandwidth = resource.get(Constants.RES_BANDWIDTH)

        from .sense_network import SenseNetwork

        saved_interfaces = self.retrieve_attribute_from_saved_state(resource, net_name, attribute='interface')
        if not isinstance(saved_interfaces, list):
            saved_interfaces = [saved_interfaces]

        net = SenseNetwork(label=label, name=net_name, profile=profile,
                           bandwidth=bandwidth, layer3=layer3, peering=peering, interfaces=interfaces,
                           saved_interfaces=saved_interfaces)

        self._networks.append(net)

        if self.resource_listener:
            self.resource_listener.on_added(source=self, provider=self, resource=net)

    def do_create_resource(self, *, resource: dict):
        assert self.initialized
        rtype = resource.get(Constants.RES_TYPE)
        assert rtype in self.supported_resources
        label = resource.get(Constants.LABEL)
        self.logger.info(f"{self.name}: Creating resource {label} ....")

        if not self._handled_modify and self.modified:
            assert rtype == Constants.RES_TYPE_NETWORK, "sense expects network to be created first"
            self._handled_modify = True

            self.logger.warning(f"{self.name}:Modified state: Deleting sense resources ...")

            from .sense_network import SenseNetwork

            net_name = self.resource_name(resource)
            net = SenseNetwork(label=label, name=net_name, bandwidth=None, profile=None, layer3=None, interfaces=None,
                               peering=None)

            try:
                net.delete()
                self.logger.warning(f"Deleted sense resources ....")
            except Exception as e:
                self.logger.error(f"Exception deleting cloudlab resources ....", e)

        label = resource.get(Constants.LABEL)

        if rtype == Constants.RES_TYPE_NODE:
            for node in [node for node in self._nodes if node.label == label]:
                self.logger.debug(f"Creating node: {vars(node)}")
                node.create()

                if self.resource_listener:
                    self.resource_listener.on_created(source=self, provider=self, resource=node)

                self.logger.debug(f"Created node: {vars(node)}")

            return

        for net in [net for net in self._networks if net.label == label]:
            self.logger.debug(f"Creating network: {vars(net)}")
            net.create()

            if self.resource_listener:
                self.resource_listener.on_created(source=self, provider=self, resource=net)

            self.logger.debug(f"Created network: {vars(net)}")

    def do_delete_resource(self, *, resource: dict):
        self._init_client()
        rtype = resource.get(Constants.RES_TYPE)
        assert rtype in self.supported_resources
        label = resource.get(Constants.LABEL)

        if rtype == Constants.RES_TYPE_NODE:
            # DO NOTHING
            return

        net_name = self.resource_name(resource)

        logger.debug(f"Deleting network: {net_name}")

        from .sense_network import SenseNetwork

        net = SenseNetwork(label=label, name=net_name, bandwidth=None, profile=None, layer3=None, interfaces=None,
                           peering=None)

        net.delete()
        logger.debug(f"Done Deleting network: {net_name}")

        if self.resource_listener:
            self.resource_listener.on_deleted(source=self, provider=self, resource=net)
