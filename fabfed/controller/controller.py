import logging
from typing import List, Union, Dict

from fabfed.exceptions import ControllerException
from fabfed.model.state import ResourceState, ProviderState
from fabfed.util.config import WorkflowConfig
from .helper import ControllerResourceListener, partition_layer3_config
from fabfed.policy.policy_helper import ProviderPolicy
from .provider_factory import ProviderFactory
from ..util.constants import Constants
from ..util.config_models import ResourceConfig
from ..util.stats import ProviderStats, Duration, Stages
from fabfed.util.utils import get_logger


class Controller:
    def __init__(self, *, config: WorkflowConfig, logger: Union[logging.Logger, None] = None,
                 policy: Union[Dict[str, ProviderPolicy], None] = None,
                 use_local_policy=True):
        import copy

        self.config = copy.deepcopy(config)
        self.logger = logger or get_logger()
        self.provider_factory: Union[ProviderFactory, None] = None
        self.resources: List[ResourceConfig] = []
        self.policy = policy
        self.use_local_policy = use_local_policy
        self.resource_listener = ControllerResourceListener()
        self.current_session = None

    def init(self, *, session: str, provider_factory: ProviderFactory, provider_states: List[ProviderState]):
        self.current_session = session

        init_provider_map: Dict[str, bool] = dict()

        for provider_config in self.config.get_provider_configs():
            init_provider_map[provider_config.label] = False

        for resource in self.config.get_resource_configs():
            count = resource.attributes.get(Constants.RES_COUNT, 1)
            init_provider_map[resource.provider.label] = init_provider_map[resource.provider.label] or count > 0

        for provider_state in provider_states:
            init_provider_map[provider_state.label] = init_provider_map[provider_state.label] \
                                                      or len(provider_state.states()) > 0

        for provider_config in self.config.get_provider_configs():
            if not init_provider_map[provider_config.label]:
                self.logger.warning(f"Skipping initialization of {provider_config.label}: no resources")
                continue

            name = provider_config.attributes.get('name')
            name = f"{session}-{name}" if name else session
            provider = provider_factory.init_provider(type=provider_config.type,
                                                      label=provider_config.label,
                                                      name=name,
                                                      attributes=provider_config.attributes,
                                                      logger=self.logger)
            saved_state = next(filter(lambda s: s.label == provider.label, provider_states), None)
            provider.set_saved_state(saved_state)

        self.resources = self.config.get_resource_configs()
        networks = [resource for resource in self.resources if resource.is_network]

        if networks and not self.policy:
            if self.use_local_policy:
                from fabfed.policy.policy_helper import load_policy

                self.policy = load_policy()
                self.logger.info(f"loaded local stitching policy.")
            else:
                from fabfed.policy.policy_helper import load_remote_policy

                self.policy = load_remote_policy()
                self.logger.info(f"loaded remote stitching policy.")

        self.provider_factory = provider_factory
        providers = self.provider_factory.providers
        self.resource_listener.set_providers(providers)

        for provider in providers:
            provider.set_resource_listener(self.resource_listener)

        if networks:
            from fabfed.policy.policy_helper import handle_stitch_info

            self.resources = handle_stitch_info(self.config, self.policy, self.resources)

            from fabfed.policy.policy_helper import fix_node_site, fix_network_site

            for resource in self.resources:
                from fabfed.policy.policy_helper import fix_node_site, fix_network_site

                if resource.is_node:
                    fix_node_site(resource, self.resources)
                elif resource.is_network:
                    fix_network_site(resource)

        for resource in self.resources:
            resource_dict = resource.attributes
            resource_dict[Constants.RES_COUNT] = resource_dict.get(Constants.RES_COUNT, 1)
            resource_dict[Constants.RES_NAME_PREFIX] = resource.name
            resource_dict[Constants.CONFIG] = resource_dict.copy()
            resource_dict[Constants.RES_TYPE] = resource.type
            resource_dict[Constants.LABEL] = resource.label
            resource_dict[Constants.EXTERNAL_DEPENDENCIES] = list()
            resource_dict[Constants.RESOLVED_EXTERNAL_DEPENDENCIES] = list()
            resource_dict[Constants.INTERNAL_DEPENDENCIES] = list()
            resource_dict[Constants.RESOLVED_INTERNAL_DEPENDENCIES] = list()
            resource_dict[Constants.SAVED_STATES] = list()

            for dependency in resource.dependencies:
                if dependency.is_external:
                    resource_dict[Constants.EXTERNAL_DEPENDENCIES].append(dependency)
                else:
                    resource_dict[Constants.INTERNAL_DEPENDENCIES].append(dependency)

        layer3_to_network_mapping = {}
        networks = [resource for resource in self.resources if resource.is_network]

        from .helper import populate_layer3_config

        populate_layer3_config(networks=networks)

        for network in networks:
            layer3 = network.attributes.get(Constants.RES_LAYER3)

            if layer3:
                if layer3.label in layer3_to_network_mapping:
                    layer3_to_network_mapping.get(layer3.label).append(network)
                else:
                    layer3_to_network_mapping[layer3.label] = [network]

        for networks_with_same_layer3 in layer3_to_network_mapping.values():
            partition_layer3_config(networks=networks_with_same_layer3)

        # Handle peering labels. The labels are inserted here to match it to a stitch port
        for network in networks:
            peering_list = network.attributes.get(Constants.RES_PEERING)

            if not peering_list:
                continue

            if not isinstance(peering_list, list):
                peering_list = [peering_list]

            for peering in peering_list:
                if Constants.LABELS not in peering.attributes:
                    peering.attributes[Constants.LABELS] = []

                peering.attributes[Constants.LABELS].append(network.label)
                peering.attributes[Constants.LABELS] = sorted(peering.attributes["labels"])

                if Constants.RES_SECURITY not in peering.attributes:
                    from fabfed.util.utils import generate_bgp_key_if_needed

                    provider = self.provider_factory.get_provider(label=network.provider.label)
                    peering.attributes[Constants.RES_SECURITY] = generate_bgp_key_if_needed(provider.name)

        peering_to_network_mapping = {}

        for network in networks:
            if Constants.RES_PEER_LAYER3 in network.attributes: # This is for testing
                continue

            network.attributes[Constants.RES_PEER_LAYER3] = []

            peering_list = network.attributes.get(Constants.RES_PEERING)

            if not peering_list:
                continue

            if not isinstance(peering_list, list):
                peering_list = [peering_list]

            for peering in peering_list:
                if peering.label in peering_to_network_mapping:
                    peering_to_network_mapping.get(peering.label).append(network)
                else:
                    peering_to_network_mapping[peering.label] = [network]

        for peers in peering_to_network_mapping.values():
            for network in peers:
                for other in [peer for peer in peers if peer.label != network.label]:
                    if Constants.RES_LAYER3 in other.attributes:
                        network.attributes[Constants.RES_PEER_LAYER3].append(other.attributes[Constants.RES_LAYER3])

        for network in [net for net in networks if net.attributes.get(Constants.RES_STITCH_INFO)]:
            stitch_info = network.attributes.get(Constants.RES_STITCH_INFO)
            self.logger.info(f"{network}: stitch_info={stitch_info}")

    def plan(self, provider_states: List[ProviderState]):
        resources = self.resources
        resource_state_map = Controller._build_state_map(provider_states)
        self.logger.info(f"Starting PLAN_PHASE for {len(resources)} resource(s)")
        pf = self.provider_factory
        resources_labels = [r.label for r in resources]
        planned_resources = []

        for resource in resources:
            resource_dict = resource.attributes
            label = resource.provider.label
            provider = pf.get_provider(label=label)
            creation_details = resource_dict[Constants.RES_CREATION_DETAILS] = {}
            creation_details['resources'] = {}
            creation_details['resources'][resource.label] = []
            creation_details['total_count'] = resource_dict[Constants.RES_COUNT]
            creation_details['failed_count'] = 0
            creation_details['created_count'] = 0
            creation_details['in_config_file'] = True
            creation_details['provider_supports_modifiable'] = provider.supports_modify()

            if resource.label in resource_state_map:
                resource_dict = resource.attributes
                resource_dict[Constants.RES_CREATION_DETAILS].update(
                    provider.saved_state.creation_details[resource.label])
                resource_dict[Constants.RES_CREATION_DETAILS]['total_count'] = resource_dict[Constants.RES_COUNT]

            planned_resources.append(resource)

        for state_label, states in resource_state_map.items():
            if state_label not in resources_labels:
                state = states[0]
                resource_dict = state.attributes.copy()
                provider_state = resource_dict.pop(Constants.PROVIDER_STATE)
                provider = pf.get_provider(label=provider_state.label)

                import copy

                creation_details: Dict = copy.deepcopy(provider_state.creation_details[state_label])
                creation_details['in_config_file'] = False
                creation_details['provider_supports_modifiable'] = provider.supports_modify()

                from ..util.config_models import ProviderConfig

                var_name, _ = tuple(provider_state.label.split('@'))
                provider_config = ProviderConfig(type=provider.type, name=var_name, attrs=provider.config)

                resource_dict = {}
                var_name, _ = tuple(state.label.split('@'))

                if var_name != creation_details['name_prefix']:
                    resource_dict['name'] = creation_details['name_prefix']

                resource_config = ResourceConfig(type=state.type, name=var_name, provider=provider_config,
                                                 attrs=resource_dict)
                resource_dict[Constants.RES_TYPE] = state.type
                resource_dict[Constants.RES_NAME_PREFIX] = creation_details['name_prefix']
                resource_dict[Constants.LABEL] = resource_config.label
                resource_dict[Constants.EXTERNAL_DEPENDENCIES] = list()
                resource_dict[Constants.RESOLVED_EXTERNAL_DEPENDENCIES] = list()
                resource_dict[Constants.INTERNAL_DEPENDENCIES] = list()
                resource_dict[Constants.RESOLVED_INTERNAL_DEPENDENCIES] = list()
                resource_dict[Constants.SAVED_STATES] = list()
                resource_dict[Constants.RES_COUNT] = creation_details['total_count']
                resource_dict[Constants.RES_CREATION_DETAILS] = creation_details
                resource_dict[Constants.CONFIG] = creation_details.pop(Constants.CONFIG)
                planned_resources.append(resource_config)

        self.resources = planned_resources

    def add(self, provider_states: List[ProviderState]):
        resources = self.resources
        self.logger.info(f"Starting ADD_PHASE: Calling ADD ... for {len(resources)} resource(s)")

        exceptions = []
        for resource in resources:
            label = resource.provider.label
            provider = self.provider_factory.get_provider(label=label)

            try:
                provider.validate_resource(resource=resource.attributes)
            except Exception as e:
                exceptions.append(e)
                self.logger.error(e, exc_info=True)

        if exceptions:
            raise ControllerException(exceptions)

        exceptions = []
        resource_state_map = Controller._build_state_map(provider_states)
        for resource in resources:
            label = resource.provider.label
            provider = self.provider_factory.get_provider(label=label)

            if resource.label in resource_state_map:
                resource.attributes[Constants.SAVED_STATES] = resource_state_map[resource.label]

            try:
                provider.add_resource(resource=resource.attributes)
            except Exception as e:
                exceptions.append(e)
                self.logger.error(e, exc_info=True)

        if exceptions:
            raise ControllerException(exceptions)

    def apply(self, provider_states: List[ProviderState]):
        from fabfed.util import state as sutil

        sutil.delete_inventory(self.current_session)
        sutil.delete_ssh(self.current_session)
        resources = self.resources
        self.logger.info(f"Starting APPLY_PHASE for {len(resources)} resource(s)")
        resource_state_map = Controller._build_state_map(provider_states)
        exceptions = []

        create_and_wait_resource_labels = set()

        for resource in filter(lambda r: not r.is_service, resources):
            resource_dict = resource.attributes

            for dependency in resource_dict[Constants.EXTERNAL_DEPENDENCIES]:
                create_and_wait_resource_labels.add(dependency.resource.label)

            if resource.label in resource_state_map:
                resource.attributes[Constants.SAVED_STATES] = resource_state_map[resource.label]

        for resource in filter(lambda r: not r.is_service, resources):
            if resource.label in create_and_wait_resource_labels:
                provider = self.provider_factory.get_provider(label=resource.provider.label)

                try:
                    provider.create_resource(resource=resource.attributes)
                    provider.wait_for_create_resource(resource=resource.attributes)
                except Exception as e:
                    exceptions.append(e)
                    self.logger.error(e, exc_info=True)

        if exceptions:
            raise ControllerException(exceptions)

        exceptions = []

        for resource in filter(lambda r: not r.is_service, resources):
            if resource.label not in create_and_wait_resource_labels:
                provider = self.provider_factory.get_provider(label=resource.provider.label)

                try:
                    provider.create_resource(resource=resource.attributes)
                except Exception as e:
                    exceptions.append(e)
                    self.logger.error(e, exc_info=True)

        if exceptions:
            raise ControllerException(exceptions)

        exceptions = []

        for resource in filter(lambda r: not r.is_service, resources):
            if resource.label not in create_and_wait_resource_labels:
                provider = self.provider_factory.get_provider(label=resource.provider.label)

                try:
                    provider.wait_for_create_resource(resource=resource.attributes)
                except Exception as e:
                    exceptions.append(e)
                    self.logger.error(e, exc_info=True)

        if exceptions:
            raise ControllerException(exceptions)

        if not Constants.RUN_SSH_TESTER:
            return

        from fabfed.util.node_tester import SshNodeTester

        nodes = [n for prov in self.provider_factory.providers if prov.type != "dummy" for n in prov.nodes]

        if nodes:
            for n in nodes:
                if n.get_dataplane_address(af=Constants.IPv4) is None:
                    raise ControllerException(
                        [Exception(f"Node {n.label} has no dataplane ip. Try apply again!")])

            clusters = [nodes]  # find_node_clusters(resources=resources)

            for cluster in clusters:
                tester = SshNodeTester(nodes=[n for n in nodes if n.label in [n.label for n in cluster]])
                tester.run_tests()

                from fabfed.model.state import get_dumper
                import yaml

                rep = yaml.dump(tester.summary, default_flow_style=False, sort_keys=False, Dumper=get_dumper())
                self.logger.info(f"{rep}")

                if tester.has_failures():
                    raise ControllerException([Exception("Node testing over ssh failed see node test summary ...")])

                self.logger.info(f"Node testing over ssh passed for {[n.name for n in nodes]}")

        exceptions = []

        for resource in filter(lambda r: r.is_service, resources):
            label = resource.provider.label
            provider = self.provider_factory.get_provider(label=label)

            if resource.label in resource_state_map:
                resource.attributes[Constants.SAVED_STATES] = resource_state_map[resource.label]

            try:
                provider.create_resource(resource=resource.attributes)
            except Exception as e:
                exceptions.append(e)
                self.logger.error(e, exc_info=True)

        if exceptions:
            raise ControllerException(exceptions)

    @staticmethod
    def _build_state_map(provider_states: List[ProviderState]) -> Dict[str, List[ResourceState]]:
        resource_state_map = dict()

        for provider_state in provider_states:
            temp_list = provider_state.states()

            for state in temp_list:
                state.attributes[Constants.PROVIDER_STATE] = provider_state

                if state.label in resource_state_map:
                    resource_state_map[state.label].append(state)
                else:
                    resource_state_map[state.label] = [state]

        return resource_state_map

    def destroy(self, *, provider_states: List[ProviderState]):
        exceptions = []
        resource_state_map = Controller._build_state_map(provider_states)
        provider_resource_map = dict()
        failed_resources = []

        for provider_state in provider_states:
            for k in provider_state.failed:
                failed_resources.append(k)

        for provider_state in provider_states:
            key = provider_state.label
            provider_resource_map[key] = list()

        temp = self.resources
        temp.reverse()

        for resource in temp:
            if resource.label in resource_state_map:
                key = resource.provider.label
                external_dependencies = resource.attributes.get(Constants.EXTERNAL_DEPENDENCIES, [])
                external_states = [resource_state_map[ed.resource.label] for ed in external_dependencies]
                resource.attributes[Constants.EXTERNAL_DEPENDENCY_STATES] = sum(external_states, [])
                provider_resource_map[key].append(resource)
                resource.attributes[Constants.SAVED_STATES] = resource_state_map[resource.label]

        remaining_resources = list()
        skip_resources = set()

        for resource in temp:
            if resource.label not in resource_state_map and resource.label not in failed_resources:
                continue

            provider_label = resource.provider.label
            provider = self.provider_factory.get_provider(label=provider_label)
            external_states = resource.attributes.get(Constants.EXTERNAL_DEPENDENCY_STATES, list())

            if resource.label in skip_resources:
                self.logger.warning(f"Skipping deleting resource: {resource} with {provider_label}")
                remaining_resources.append(resource)
                skip_resources.update([external_state.label for external_state in external_states])
                continue

            try:
                provider.delete_resource(resource=resource.attributes)
            except Exception as e:
                self.logger.warning(f"Exception occurred while deleting resource: {e} using {provider_label}", exc_info=True)
                remaining_resources.append(resource)
                skip_resources.update([external_state.label for external_state in external_states])
                exceptions.append(e)

        if not remaining_resources:
            provider_states.clear()
            return

        provider_states_copy = provider_states.copy()
        provider_states.clear()

        for provider_state in provider_states_copy:
            provider_state.node_states.clear()
            provider_state.network_states.clear()
            provider_state.service_states.clear()

            if self.provider_factory.has_provider(label=provider_state.label):
                provider = self.provider_factory.get_provider(label=provider_state.label)
                provider_state.failed = provider.failed

                for remaining_resource in [r for r in remaining_resources if r.provider.label == provider_state.label]:
                    if remaining_resource.label in resource_state_map:
                        resource_states = resource_state_map[remaining_resource.label]
                        provider_state.add_all(resource_states)

                if provider_state.states() or provider_state.failed:
                    provider_states.append(provider_state)

        if exceptions:
            raise ControllerException(exceptions)

    def get_states(self) -> List[ProviderState]:
        provider_states = []

        for provider in self.provider_factory.providers:
            provider_state = provider.get_state()
            provider_states.append(provider_state)

        return provider_states

    def get_stats(self) -> List[ProviderStats]:
        provider_stats = []

        for provider in self.provider_factory.providers:
            total_duration = provider.init_duration \
                             + provider.add_duration + provider.create_duration + provider.delete_duration
            total_duration = Duration(duration=total_duration,
                                      comment="Total time spent in provider")
            stages = Stages(setup_duration=provider.init_duration,
                            plan_duration=provider.add_duration,
                            create_duration=provider.create_duration,
                            delete_duration=provider.delete_duration)
            temp = ProviderStats(provider=provider.label,
                                 provider_duration=total_duration,
                                 has_failures=len(provider.failed) > 0,
                                 has_pending=len(provider.pending) > 0,
                                 stages=stages)
            provider_stats.append(temp)

        return provider_stats
