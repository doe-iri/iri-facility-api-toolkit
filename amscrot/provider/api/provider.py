import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Union

from amscrot.model import Resource, Node, Network, Service
from amscrot.model.state import ProviderState
from amscrot.util.constants import Constants
from amscrot.util.utils import normalize_alias


class Provider(ABC):
    def __init__(self, *, type, label, name, logger: logging.Logger, config: dict):
        self.label = label
        self.type = type
        self.name = name
        self.logger = logger
        self.config = config
        self.resource_listener = None

        self._nodes = list()
        self._networks = list()
        self._services = list()

        self._pending = []
        self._externally_depends_on_map: Dict[str, List[str]] = {}

        self._no_longer_pending = []
        self._failed = {}
        self.creation_details = {}
        self._added = []
        self.pending_internal = []

        self.add_duration = self.create_duration = self.delete_duration = self.init_duration = 0
        self._saved_state: ProviderState = Union[ProviderState, None]
        self._existing_map: Dict[str, List[str]] = {}
        self._added_map: Union[Dict[str, List[str]], None] = None

    @property
    def existing_map(self) -> Dict[str, List[str]]:
        return self._existing_map

    @property
    def added_map(self) -> Dict[str, List[str]]:
        return self._added_map

    @property
    def resources(self) -> List[Resource]:
        resources = [n for n in self._nodes]
        resources.extend([n for n in self._networks])
        resources.extend([n for n in self._services])
        return resources

    @property
    def nodes(self) -> List[Node]:
        return self._nodes

    @property
    def saved_state(self) -> Union[ProviderState, None]:
        return self._saved_state

    def set_saved_state(self, state: Union[ProviderState, None]):
        self._saved_state = state

    @property
    def networks(self) -> List[Network]:
        return self._networks

    @property
    def services(self) -> List[Service]:
        return self._services

    @property
    def no_longer_pending(self) -> List:
        return self._no_longer_pending

    @property
    def pending(self) -> List:
        return self._pending

    @property
    def failed(self) -> Dict:
        return self._failed

    def set_resource_listener(self, resource_listener):
        self.resource_listener = resource_listener

    def on_added(self, *, source, provider, resource: object):
        assert self != source
        assert provider
        assert resource
        pass

    def on_deleted(self, *, source, provider, resource: object):
        assert self != source
        assert provider
        assert resource
        resource.write_ansible(provider.name, delete=True)

    def get_dependency_resolver(self, *, external=True):
        from .dependency_reslover import DependencyResolver

        return DependencyResolver(label=self.label, external=external, logger=self.logger)

    def on_created(self, *, source, provider, resource: Resource):
        assert self != source
        assert provider


        if self == provider:
            self.creation_details[resource.label]["resources"].append(resource.name)
            resource.set_externally_depends_on(self._externally_depends_on_map[resource.label])

            try:
                resource.write_ansible(provider.name)
            except Exception as e:
                self.logger.warning(
                    f"exception occurred while writing ansible for resource={resource.name}/{provider.name}:{e}")
        else:
            for pending_resource in self.pending.copy():
                resolver = self.get_dependency_resolver()
                label = pending_resource[Constants.LABEL]
                resolver.resolve_dependency(resource=pending_resource, from_resource=resource)
                ok = resolver.check_if_external_dependencies_are_resolved(resource=pending_resource)

                if ok:
                    resolver.extract_values(resource=pending_resource)
                    self.pending.remove(pending_resource)
                    self.no_longer_pending.append(pending_resource)
                    self.logger.info(f"Removing {label} from pending using {self.label}")

            for r in self.resources:
                if r.label in resource.get_externally_depends_on():
                    self.do_handle_externally_depends_on(resource=r, dependee=resource)

    def init(self):
        import time

        start = time.time()
        credential_file = self.config.get(Constants.CREDENTIAL_FILE, None)

        if credential_file:
            from amscrot.util import utils
            from amscrot.exceptions import ProviderException

            if Constants.PROFILE not in self.config:
                raise ProviderException(
                    f"{self.label}: must name a section in the credential file using keyword {Constants.PROFILE}")

            profile = self.config[Constants.PROFILE]
            config = utils.load_yaml_from_file(credential_file)

            if profile not in config:
                raise ProviderException(
                    f"{self.label}: credential file {credential_file} does not have a section for keyword {profile}")
            self.config.update(config[profile])

        self.setup_environment()
        end = time.time()
        self.init_duration = (end - start)

    def supports_modify(self):
        return False

    def resource_name(self, resource: dict, idx: int = -1):
        if idx < 0:
           name = f"{self.name}-{resource[Constants.RES_NAME_PREFIX]}"
        else:
           name = f"{self.name}-{resource[Constants.RES_NAME_PREFIX]}-{idx}"

        return normalize_alias(name)

    def add_to_existing_map(self, resource: dict):
        label = resource.get(Constants.LABEL)
        self.existing_map[label] = []

        if self.saved_state and resource.get(Constants.LABEL) in self.saved_state.creation_details:
            provider_saved_creation_details = self.saved_state.creation_details[label]

            for n in range(0, provider_saved_creation_details['total_count']):
                resource_name = self.resource_name(resource, n)
                self.existing_map[label].append(resource_name)

    def _compute_added_map(self):
        if self.added_map is None:
            self._added_map = {}

            for net in self.networks:
                if net.label not in self.added_map:
                    self.added_map[net.label] = []

                self.added_map[net.label].append(net.name)

            for node in self.nodes:
                if node.label not in self.added_map:
                    self.added_map[node.label] = []

                self.added_map[node.label].append(node.name)

            for service in self.services:
                if service.label not in self.added_map:
                    self.added_map[service.label] = []

                self.added_map[service.label].append(service.name)

    @property
    def modified(self):
        if self.saved_state:
            self._compute_added_map()
            return self._existing_map and self.added_map != self._existing_map

        return False

    def retrieve_attribute_from_saved_state(self, resource, resource_name, attribute, defaultValue=None):
        if self.saved_state:
            for state in resource[Constants.SAVED_STATES]:
                if state.attributes['name'] == resource_name:
                    ret = state.attributes.get(attribute)

                    if isinstance(ret, list) and len(ret) == 1:
                        return ret[0]

                    return ret
        return defaultValue

    def validate_resource(self, *, resource: dict):
        label = resource.get(Constants.LABEL)

        self.creation_details[label] = dict()
        self.creation_details[label]['resources'] = list()
        self.creation_details[label]['config'] = resource[Constants.CONFIG]
        self.creation_details[label]['total_count'] = resource[Constants.RES_COUNT]
        self.creation_details[label]['failed_count'] = 0
        self.creation_details[label]['created_count'] = 0
        self.creation_details[label]['name_prefix'] = resource[Constants.RES_NAME_PREFIX]
        self.add_to_existing_map(resource)

        import time

        start = time.time()

        try:
            self.do_validate_resource(resource=resource)
        except Exception as e:
            self.failed[label] = 'VALIDATE'
            raise e
        finally:
            end = time.time()
            self.add_duration += (end - start)

    def add_resource(self, *, resource: dict):
        import time

        start = time.time()
        count = resource.get(Constants.RES_COUNT, 1)
        label = resource.get(Constants.LABEL)
        assert count > 0
        assert label not in self._added, f"{label} already in {self._added}"

        if label not in self._externally_depends_on_map:
            depends_on = self._externally_depends_on_map[label] = list()

            for dependency in resource[Constants.EXTERNAL_DEPENDENCIES]:
                depends_on.append(dependency.resource.label)

        if len(resource[Constants.EXTERNAL_DEPENDENCIES]) > len(resource[Constants.RESOLVED_EXTERNAL_DEPENDENCIES]):
            self.logger.info(f"Adding {label} to pending using {self.label}")
            assert resource not in self.pending, f"Did not expect {label} to be in pending list using {self.label}"
            self.pending.append(resource)
            return
        elif len(resource[Constants.INTERNAL_DEPENDENCIES]) > len(resource[Constants.RESOLVED_INTERNAL_DEPENDENCIES]):
            self.logger.info(f"Handling internal dependencies {label} using provider {self.label}")
            resolver = self.get_dependency_resolver(external=False)

            for temp in self.resources:
                resolver.resolve_dependency(resource=resource, from_resource=temp)

            ok = resolver.check_if_external_dependencies_are_resolved(resource=resource)

            if ok:
                resolver.extract_values(resource=resource)
            else:
                self.logger.info(f"Adding to internal_dependencies {label}")

                assert resource not in self.pending_internal, f"internal pending resource {label} already added"
                self.pending_internal.append(resource)
                return

        try:
            self.do_add_resource(resource=resource)
            self._added.append(label)
        except Exception as e:
            label = resource.get(Constants.LABEL)

            self.failed[label] = 'ADD'
            failed_count = resource[Constants.RES_COUNT] - len(self.creation_details[label]['resources'])
            self.creation_details[label]['failed_count'] = failed_count
            raise e
        finally:
            end = time.time()
            self.add_duration += (end - start)

    def create_resource(self, *, resource: dict):
        import time

        start = time.time()
        label = resource.get(Constants.LABEL)

        if self.no_longer_pending:
            self.logger.info(f"Checking internal dependencies using {self.label}")
            temp_no_longer_pending = self._no_longer_pending
            self._no_longer_pending = []

            for no_longer_pending_resource in temp_no_longer_pending:
                external_dependency_label = no_longer_pending_resource[Constants.LABEL]

                try:
                    self.logger.info(f"Adding no longer pending external_dependency {external_dependency_label}")
                    self.add_resource(resource=no_longer_pending_resource)
                    added = True
                except Exception as e:
                    self.no_longer_pending.append(no_longer_pending_resource)
                    # Propagate the error only if the resourcce being created is not add successfully
                    if label == external_dependency_label:
                        raise e

                    self.logger.warning(f"Adding no longer pending externally {external_dependency_label} failed: {e}",
                                        exc_info=True)
                    added = False

                if added:
                    temp = self.pending_internal
                    self.pending_internal = []

                    for internal_dependency in temp:
                        internal_dependency_label = internal_dependency[Constants.LABEL]
                        self.logger.info(f"Adding internal_dependency {internal_dependency_label}")

                        try:
                            self.add_resource(resource=internal_dependency)
                        except Exception as e2:
                            self.logger.warning(
                                f"Adding no longer pending internally {internal_dependency_label} failed using {e2}",
                                        exc_info=True)

        if label in self._added:
            self.logger.info(f"Create: {label} using {self.label}: {self._added}")

            try:
                self.do_create_resource(resource=resource)
            except (Exception, KeyboardInterrupt) as e:
                self.failed[label] = 'CREATE'
                failed_count = resource[Constants.RES_COUNT] - len(self.creation_details[label]['resources'])
                self.creation_details[label]['failed_count'] = failed_count
                raise e
            finally:
                self.creation_details[label]['created_count'] = len(self.creation_details[label]['resources'])
                end = time.time()
                self.create_duration += (end - start)

    def wait_for_create_resource(self, *, resource: dict):
        import time
        start = time.time()
        label = resource.get(Constants.LABEL)

        if label in self._added:
            self.logger.info(f"Waiting on Create: {label} using {self.label}: {self._added}")

            try:
                self.do_wait_for_create_resource(resource=resource)
            except (Exception, KeyboardInterrupt) as e:
                self.failed[label] = 'CREATE'
                failed_count = resource[Constants.RES_COUNT] - len(self.creation_details[label]['resources'])
                self.creation_details[label]['failed_count'] = failed_count
                raise e
            finally:
                self.creation_details[label]['created_count'] = len(self.creation_details[label]['resources'])
                end = time.time()
                self.create_duration += (end - start)

    def delete_resource(self, *, resource: dict):
        import time

        start = time.time()

        try:
            self.do_delete_resource(resource=resource)
        except Exception as e:
            label = resource.get(Constants.LABEL)

            self.failed[label] = 'DELETE'
            raise e
        finally:
            end = time.time()
            self.delete_duration += (end - start)

    def get_state(self) -> ProviderState:
        from amscrot.model.state import NetworkState, NodeState, ServiceState

        def cleanup_attrs(attrs):
            attributes = attrs.copy()
            attributes.pop('logger', None)
            attributes.pop('label')
            attributes = {k: v for k, v in attributes.items() if not k.startswith('_')}
            return attributes

        networks = [n for n in self.networks if n.name in self.creation_details[n.label]["resources"]]
        net_states = [NetworkState(label=n.label, attributes=cleanup_attrs(vars(n))) for n in networks]
        nodes = [n for n in self.nodes if n.name in self.creation_details[n.label]["resources"]]
        node_states = [NodeState(label=n.label, attributes=cleanup_attrs(vars(n))) for n in nodes]
        services = [s for s in self.services if s.name in self.creation_details[s.label]["resources"]]
        service_states = [ServiceState(label=s.label, attributes=cleanup_attrs(vars(s))) for s in services]
        pending = [res['label'] for res in self.pending]
        pending_internal = [res['label'] for res in self.pending_internal]
        return ProviderState(self.label, dict(name=self.name), net_states, node_states, service_states,
                             pending, pending_internal, self.failed, self.creation_details)

    def list_networks(self) -> list:
        from tabulate import tabulate

        table = []
        for network in self.networks:
            table.append([network.get_reservation_id(),
                          network.get_name(),
                          network.get_site()
                          ])

        return tabulate(table, headers=["ID", "Name", "Site"])

    def list_nodes(self) -> list:
        from tabulate import tabulate

        table = []
        for node in self._nodes:
            table.append([node.get_reservation_id(),
                          node.get_name(),
                          node.get_site(),
                          node.get_flavor(),
                          node.get_image(),
                          node.get_management_ip(),
                          node.get_reservation_state()
                          ])

        return tabulate(table, headers=["ID", "Name", "Site", "Flavor", "Image",
                                        "Management IP", "State"])

    @abstractmethod
    def setup_environment(self):
        pass

    def do_validate_resource(self, *, resource: dict):
        pass

    @abstractmethod
    def do_add_resource(self, *, resource: dict):
        pass

    @abstractmethod
    def do_create_resource(self, *, resource: dict):
        pass

    def do_wait_for_create_resource(self, *, resource: dict):
        pass

    def do_handle_externally_depends_on(self, *, resource: Resource, dependee: Resource):
        pass

    @abstractmethod
    def do_delete_resource(self, *, resource: dict):
        pass
