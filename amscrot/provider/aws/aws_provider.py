from amscrot.exceptions import ResourceTypeNotSupported
from amscrot.provider.api.provider import Provider
from amscrot.util.constants import Constants
from amscrot.util.utils import get_logger
from . import aws_constants

logger = get_logger()


class AwsProvider(Provider):
    def __init__(self, *, type, label, name, config: dict):
        super().__init__(type=type, label=label, name=name, logger=logger, config=config)
        self.supported_resources = [Constants.RES_TYPE_NETWORK.lower()]

    @property
    def access_key(self):
        return self.config.get(aws_constants.ACCESS_KEY)

    @property
    def secret_key(self):
        return self.config.get(aws_constants.SECRET_KEY)

    def setup_environment(self):
        from amscrot.util import utils

        credential_file = self.config.get(Constants.CREDENTIAL_FILE)
        profile = self.config.get(Constants.PROFILE)
        config = utils.load_yaml_from_file(credential_file)

        if profile not in config:
            from amscrot.exceptions import ProviderException

            raise ProviderException(
                f"credential file {credential_file} does not have a section for keyword {profile}"
            )

        self.config = config[profile]
        normalized_config = {}

        for k, v in self.config.items():
            normalized_config[k.upper()] = v

        self.config = normalized_config
        assert self.access_key
        assert self.secret_key

    def _handle_peering_config(self, resource):
        import fabfed.provider.api.dependency_util as util
        from amscrot.model import Network

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

    def do_add_resource(self, *, resource: dict):
        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)

        if rtype not in self.supported_resources:
            raise ResourceTypeNotSupported(f"{rtype} for {label}")

        name_prefix = resource.get(Constants.RES_NAME_PREFIX)
        net_name = f'{self.name}-{name_prefix}'
        layer3 = resource.get(Constants.RES_LAYER3)
        peering = self._handle_peering_config(resource)

        from .aws_network import AwsNetwork
        from amscrot.policy.policy_helper import get_stitch_port_for_provider

        stitch_port = get_stitch_port_for_provider(resource=resource, provider=self.type)
        net = AwsNetwork(label=label, name=net_name, provider=self,
                         layer3=layer3, peering=peering, stitch_port=stitch_port)
        self._networks.append(net)

        if self.resource_listener:
            self.resource_listener.on_added(source=self, provider=self, resource=net)

    def do_create_resource(self, *, resource: dict):
        rtype = resource.get(Constants.RES_TYPE)
        assert rtype in self.supported_resources
        label = resource.get(Constants.LABEL)

        for net in [net for net in self._networks if net.label == label]:
            self.logger.debug(f"Creating network: {vars(net)}")
            net.create()

            if self.resource_listener:
                self.resource_listener.on_created(source=self, provider=self, resource=net)

            self.logger.debug(f"Created network: {vars(net)}")

    def do_delete_resource(self, *, resource: dict):
        rtype = resource.get(Constants.RES_TYPE)
        assert rtype in self.supported_resources
        label = resource.get(Constants.LABEL)

        if rtype == Constants.RES_TYPE_NODE.lower():
            # DO NOTHING
            return

        states = resource.get(Constants.SAVED_STATES, [])
        state = next(filter(lambda s: s.label == label, states), None)
        net_name = f'{self.name}-{resource.get(Constants.RES_NAME_PREFIX)}'
        logger.debug(f"Deleting network: {net_name}")

        from .aws_network import AwsNetwork
        from amscrot.policy.policy_helper import get_stitch_port_for_provider

        stitch_port = get_stitch_port_for_provider(resource=resource, provider=self.type)
        layer3 = resource.get(Constants.RES_LAYER3)
        peering = resource.get(Constants.RES_PEERING)
        net = AwsNetwork(label=label, name=net_name, provider=self, layer3=layer3, peering=peering, stitch_port=stitch_port, state=state)
        net.delete()
        logger.debug(f"Done Deleting network: {net_name}")

        if self.resource_listener:
            self.resource_listener.on_deleted(source=self, provider=self, resource=net)
