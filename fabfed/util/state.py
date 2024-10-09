from fabfed.model.state import ProviderState
from fabfed.util.utils import get_base_dir, get_stats_base_dir, get_inventory_dir, get_ssh_dir
from typing import List, Dict

import json


class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        else:
            return obj.__dict__


def dump_plan(*, resources, to_json: bool, summary: bool = False):
    from collections import namedtuple
    from fabfed.util.constants import Constants
    import sys

    plan = {}
    ResourceSummary = namedtuple("ResourceSummary", "label attributes")

    if not summary:
        summaries = []

        ResourceDetails = namedtuple("ResourceDetails", "label attributes")

        for resource in resources:
            resource_dict = resource.attributes.copy()
            del_attrs = [Constants.EXTERNAL_DEPENDENCIES,
                         Constants.RESOLVED_EXTERNAL_DEPENDENCIES,
                         Constants.INTERNAL_DEPENDENCIES,
                         Constants.RESOLVED_INTERNAL_DEPENDENCIES,
                         Constants.SAVED_STATES]

            for attr in del_attrs:
                del resource_dict[attr]

            stringify_attrs = [Constants.PROVIDER,
                               Constants.RES_INTERFACES,
                               Constants.RES_NODES,
                               Constants.RES_NETWORK,
                               Constants.RES_STITCH_INTERFACE,
                               Constants.NETWORK_STITCH_WITH,
                               Constants.RES_LAYER3,
                               Constants.RES_PEER_LAYER3,
                               Constants.RES_PEERING
                               ]

            for attr in stringify_attrs:
                if attr in resource_dict:
                    resource_dict[attr] = str(resource_dict[attr])

            label = resource_dict.pop(Constants.LABEL)
            summaries.append(ResourceDetails(label=label, attributes=resource_dict))
            plan['resource_details'] = summaries

        summaries = []

        for resource in resources:
            resource_dict = {}

            label = resource.attributes[Constants.LABEL]

            import copy

            details = copy.deepcopy(resource.attributes[Constants.RES_CREATION_DETAILS])
            resource_dict[Constants.RES_CREATION_DETAILS] = details
            summaries.append(ResourceSummary(label=label, attributes=resource_dict))

        plan['resource_creation_details'] = summaries

    summaries = []
    to_be_created = 0
    to_be_deleted = 0
    provider_resource_map = {}

    for resource in resources:
        details = resource.attributes[Constants.RES_CREATION_DETAILS]
        provider_supports_modifiable = details['provider_supports_modifiable']

        if not provider_supports_modifiable:
            provider_resource_map[resource.provider.label] = False

    for resource in resources:
        details = resource.attributes[Constants.RES_CREATION_DETAILS]
        provider_supports_modifiable = details['provider_supports_modifiable']

        if not provider_supports_modifiable:
            in_config_file = details['in_config_file']
            changed = not in_config_file or details['total_count'] != details['created_count']
            provider_resource_map[resource.provider.label] = provider_resource_map[resource.provider.label] or changed

    for resource in resources:
        resource_dict = {}
        label = resource.attributes[Constants.LABEL]
        details = resource.attributes[Constants.RES_CREATION_DETAILS]
        provider_supports_modifiable = details['provider_supports_modifiable']
        in_config_file = details['in_config_file']

        if provider_supports_modifiable:
            if in_config_file:
                if details['total_count'] > details['created_count']:
                    resource_dict['to_be_created'] = details['total_count'] - details['created_count']
                    resource_dict['to_be_deleted'] = 0
                else:
                    resource_dict['to_be_created'] = 0
                    resource_dict['to_be_deleted'] = details['created_count'] - details['total_count']
            else:
                resource_dict['to_be_created'] = 0
                resource_dict['to_be_deleted'] = details['created_count']
        elif provider_resource_map[resource.provider.label]:
            if in_config_file:
                resource_dict['to_be_created'] = details['total_count']
                resource_dict['to_be_deleted'] = details['created_count']
            else:
                resource_dict['to_be_created'] = 0
                resource_dict['to_be_deleted'] = details['created_count']
        else:
            resource_dict['to_be_created'] = 0
            resource_dict['to_be_deleted'] = 0

        to_be_created += resource_dict['to_be_created']
        to_be_deleted += resource_dict['to_be_deleted']
        summaries.append(ResourceSummary(label=label, attributes=resource_dict))

    plan['summaries'] = summaries

    if to_json:
        import json

        sys.stdout.write(json.dumps(plan, cls=SetEncoder, indent=3))
    else:
        import yaml
        from fabfed.model.state import get_dumper

        sys.stdout.write(yaml.dump(plan, Dumper=get_dumper(), default_flow_style=False, sort_keys=False))

    return to_be_created, to_be_deleted


def dump_resources(*, resources, to_json: bool, summary: bool = False):
    import sys

    if summary:
        summaries = []
        from collections import namedtuple
        from fabfed.util.constants import Constants

        ResourceSummary = namedtuple("ResourceSummary", "label attributes")

        for resource in resources:
            resource_dict = resource.attributes.copy()
            del_attrs = [Constants.EXTERNAL_DEPENDENCIES,
                         Constants.RESOLVED_EXTERNAL_DEPENDENCIES,
                         Constants.INTERNAL_DEPENDENCIES,
                         Constants.RESOLVED_INTERNAL_DEPENDENCIES,
                         Constants.SAVED_STATES]

            for attr in del_attrs:
                del resource_dict[attr]

            stringify_attrs = [Constants.PROVIDER,
                               Constants.RES_INTERFACES,
                               Constants.RES_NODES,
                               Constants.RES_NETWORK,
                               Constants.RES_STITCH_INTERFACE,
                               Constants.NETWORK_STITCH_WITH,
                               Constants.RES_LAYER3,
                               Constants.RES_PEER_LAYER3,
                               Constants.RES_PEERING
                               ]

            for attr in stringify_attrs:
                if attr in resource_dict:
                    resource_dict[attr] = str(resource_dict[attr])

            label = resource_dict.pop(Constants.LABEL)
            summaries.append(ResourceSummary(label=label, attributes=resource_dict))

        resources = summaries

    if to_json:
        import json

        sys.stdout.write(json.dumps(resources, cls=SetEncoder, indent=3))
    else:
        import yaml
        from fabfed.model.state import get_dumper

        sys.stdout.write(yaml.dump(resources, Dumper=get_dumper(), default_flow_style=False, sort_keys=False))


def dump_objects(objects, to_json: bool):
    import sys

    if to_json:
        import json

        sys.stdout.write(json.dumps(objects, cls=SetEncoder, indent=3))
    else:
        import yaml
        from fabfed.model.state import get_dumper

        sys.stdout.write(yaml.dump(objects, Dumper=get_dumper(), default_flow_style=False, sort_keys=False))


def dump_states(states, to_json: bool, summary: bool = False):
    import sys
    from fabfed.model.state import get_dumper

    temp = []

    if not summary:
        for provider_state in states:
            for resource_state in provider_state.states():
                temp.append(resource_state)

    if summary:
        for provider_state in states:
            for node_state in provider_state.node_states:
                attributes = {}
                props = ['mgmt_ip', 'user', 'site', 'state', "name",
                         "dataplane_ipv4", "dataplane_ipv6", 'keyfile', 'jump_keyfile']

                for prop in props:
                    if prop in node_state.attributes:
                        attributes[prop] = node_state.attributes[prop]

                node_state.attributes = attributes
                temp.append(node_state)

            for network_state in provider_state.network_states:
                attributes = dict()
                props = ['name', 'site', 'state', 'profile']

                for prop in props:
                    if prop in network_state.attributes:
                        attributes[prop] = network_state.attributes[prop]

                network_state.attributes = attributes
                temp.append(network_state)

            for service_state in provider_state.service_states:
                attributes = dict()
                props = ['name', 'image', 'controller_host', 'controller_web', 'controller_ssh_tunnel_cmd']

                for prop in props:
                    if prop in service_state.attributes:
                        attributes[prop] = service_state.attributes[prop]

                service_state.attributes = attributes
                temp.append(service_state)

    states = temp

    output = dict()
    nodes = []
    networks = []
    services = []

    for state in states:
        if state.is_node_state:
            nodes.append(state)
            pass
        elif state.is_network_state:
            networks.append(state)
        else:
            services.append(state)

    output['networks'] = networks
    output['nodes'] = nodes
    output['services'] = services

    if to_json:
        import json

        sys.stdout.write(json.dumps(output, cls=SetEncoder, indent=3))
    else:
        import yaml

        sys.stdout.write(
            yaml.dump(output, Dumper=get_dumper(), width=float("inf"), default_flow_style=False, sort_keys=False))


def dump_stats(stats, to_json: bool):
    import sys

    if to_json:
        import json

        sys.stdout.write(json.dumps(stats, cls=SetEncoder, indent=3))
    else:
        import yaml
        from fabfed.model.state import get_dumper

        sys.stdout.write(
            yaml.dump(stats,
                      Dumper=get_dumper(), width=float("inf"), default_flow_style=False, sort_keys=False))


def load_meta_data(friendly_name: str, attr=None):
    import yaml
    import os
    from fabfed.model.state import get_loader

    file_path = os.path.join(get_base_dir(friendly_name), friendly_name + '_meta.yml')

    if os.path.exists(file_path):
        with open(file_path, 'r') as stream:
            try:
                ret = yaml.load(stream, Loader=get_loader())

                if ret is not None:
                    return ret.get(attr) if attr else ret
            except Exception as e:
                from fabfed.exceptions import StateException

                raise StateException(f'Exception while loading state at {file_path}:{e}')

    return None if attr else dict()


def load_states(friendly_name) -> List[ProviderState]:
    import yaml
    import os
    from fabfed.model.state import get_loader

    file_path = os.path.join(get_base_dir(friendly_name), friendly_name + '.yml')

    if os.path.exists(file_path):
        with open(file_path, 'r') as stream:
            try:
                ret = yaml.load(stream, Loader=get_loader())

                if ret is not None:
                    return ret
            except Exception as e:
                from fabfed.exceptions import StateException

                raise StateException(f'Exception while loading state at {file_path}:{e}')

    return []


def load_states_as_dict(friendly_name) -> Dict[str, ProviderState]:
    states = load_states(friendly_name)
    state_map = {}

    for state in states:
        state_map[state.label] = state

    return state_map


def load_stats(friendly_name):
    import yaml
    import os
    from fabfed.model.state import get_loader

    file_path = os.path.join(get_stats_base_dir(friendly_name), friendly_name + '-stats.yml')

    if os.path.exists(file_path):
        with open(file_path, 'r') as stream:
            try:
                ret = yaml.load(stream, Loader=get_loader())

                if ret is not None:
                    return ret
            except Exception as e:
                from fabfed.exceptions import StateException

                raise StateException(f'Exception while loading state at {file_path}:{e}')

    return []


def save_meta_data(meta_data: dict, friendly_name: str):
    import yaml
    import os
    from fabfed.model.state import get_dumper

    file_path = os.path.join(get_base_dir(friendly_name), friendly_name + '_meta.yml')

    with open(file_path, "w") as stream:
        try:
            stream.write(yaml.dump(meta_data, Dumper=get_dumper()))
        except Exception as e:
            from fabfed.exceptions import StateException

            raise StateException(f'Exception while saving state at temp file {file_path}:{e}')


def save_states(states: List[ProviderState], friendly_name: str):
    import yaml
    import os
    from fabfed.model.state import get_dumper

    file_path = os.path.join(get_base_dir(friendly_name), friendly_name + '.yml')
    temp_file_path = file_path + ".temp"

    with open(temp_file_path, "w") as stream:
        try:
            stream.write(yaml.dump(states, Dumper=get_dumper(), default_flow_style=False, sort_keys=False))
        except Exception as e:
            from fabfed.exceptions import StateException

            raise StateException(f'Exception while saving state at temp file {temp_file_path}:{e}')

    import shutil

    shutil.move(temp_file_path, file_path)


def reconcile_state(provider_state: ProviderState, saved_provider_state: ProviderState):
    assert provider_state.number_of_created_resources() != provider_state.number_of_total_resources()

    creation_details = provider_state.creation_details

    for resource_state in saved_provider_state.states():
        resource_label = resource_state.label

        if resource_label in creation_details:
            resource_details = creation_details[resource_label]

            if resource_details['total_count'] == resource_details['created_count']:
                continue

        provider_state.add_if_not_found(resource_state)


def reconcile_states(provider_states: List[ProviderState], friendly_name: str) -> List[ProviderState]:
    saved_states_map = load_states_as_dict(friendly_name)
    if next(filter(lambda s: s.number_of_created_resources() > 0, saved_states_map.values()), None) is None:
        return provider_states

    reconciled_states = []

    for provider_state in provider_states:
        if provider_state.label not in saved_states_map:
            reconciled_states.append(provider_state)
        elif provider_state.number_of_created_resources() == provider_state.number_of_total_resources():
            reconciled_states.append(provider_state)
        else:
            saved_provider_state = saved_states_map.get(provider_state.label)
            reconcile_state(provider_state=provider_state, saved_provider_state=saved_provider_state)
            reconciled_states.append(provider_state)

    return reconciled_states


def save_stats(stats, friendly_name):
    import yaml
    import os
    from fabfed.model.state import get_dumper

    file_path = os.path.join(get_stats_base_dir(friendly_name), friendly_name + '-stats.yml')
    temp_file_path = file_path + ".temp"

    with open(temp_file_path, "w") as stream:
        try:
            stream.write(yaml.dump(stats, Dumper=get_dumper(), default_flow_style=False, sort_keys=False))
        except Exception as e:
            from fabfed.exceptions import FabfedException

            raise FabfedException(f'Exception while saving stats at temp file {temp_file_path}:{e}')

    import shutil

    shutil.move(temp_file_path, file_path)


def load_sessions():
    from pathlib import Path
    import os

    base_dir = os.path.join(str(Path.home()), '.fabfed', 'sessions')
    os.makedirs(base_dir, exist_ok=True)
    sessions = os.listdir(base_dir)
    return sessions


def delete_stats(friendly_name: str):
    import shutil

    dir_path = get_stats_base_dir(friendly_name)
    shutil.rmtree(dir_path)


def delete_inventory(friendly_name: str):
    import shutil

    dir_path = get_inventory_dir(friendly_name)
    shutil.rmtree(dir_path)


def delete_ssh(friendly_name: str):
    import shutil

    dir_path = get_ssh_dir(friendly_name)
    shutil.rmtree(dir_path)


def destroy_session(friendly_name: str):
    import shutil

    dir_path = get_base_dir(friendly_name)
    shutil.rmtree(dir_path)
