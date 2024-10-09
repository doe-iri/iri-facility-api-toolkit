import json
from types import SimpleNamespace

from sense.client.discover_api import DiscoverApi
from sense.client.profile_api import ProfileApi
from sense.client.workflow_combined_api import WorkflowCombinedApi

from .sense_client import get_client

from .sense_constants import *
from .sense_exceptions import SenseException

from fabfed.util.utils import get_logger

logger = get_logger()


def get_image_info(image_spec, attr=None):
    import os

    path_file = os.path.join(os.path.dirname(__file__), 'inventory', 'sense_image_info.json')

    with open(path_file, 'r') as fp:
        infos = json.load(fp)

    if not attr:
        return infos.get(image_spec)

    return infos.get(image_spec, dict()).get(attr)


def describe_profile(*, client=None, uuid: str):
    client = client or get_client()
    profile_api = ProfileApi(req_wrapper=client)
    profile_details = profile_api.profile_describe(uuid)
    profile_details = json.loads(profile_details, object_hook=lambda dct: SimpleNamespace(**dct))

    if hasattr(profile_details, "edit"):
        from requests import utils

        for ns in profile_details.edit:
            ns.path = utils.unquote(ns.path)
            ns.valid = utils.unquote(ns.valid)

    return profile_details


def populate_options_using_interfaces(options, interfaces, edit_uri_entries):
    if len(interfaces) > len(edit_uri_entries):
        raise SenseException("invalid number of interfaces")

    index_used = False

    for interface in interfaces:
        if interface.get(Constants.RES_INDEX):
            index_used = True
            break

    if not index_used:
        for idx, interface in enumerate(interfaces):
            interface[Constants.RES_INDEX] = idx
    else:
        for interface in interfaces:
            if not interface.get(Constants.RES_INDEX):
                raise SenseException(f"index missing {interface}")

    for interface in interfaces:
        idx = interface.get(Constants.RES_INDEX)

        if idx < 0 or idx >= len(edit_uri_entries):
            raise SenseException("bad interface index")

        name = interface.get(Constants.RES_ID)
        path_prefix = f"data.connections[0].terminals[{idx}]."

        if name:
            path = path_prefix + SENSE_URI
            options.append({path: name})

        vlan_range = interface.get("vlan_range", None)

        if vlan_range:
            vlan_path = path_prefix + SENSE_VLAN_TAG
            vlan_range_str = str(vlan_range).replace(" ", "").replace(",", "-")
            options.append({vlan_path: vlan_range_str[1:-1]})


def get_profile_uuid(*, client=None, profile):
    client = client or get_client()
    profile_api = ProfileApi(req_wrapper=client)

    try:
        profile = profile_api.profile_search_get_with_http_info(search=profile)
        profile = json.loads(profile, object_hook=lambda dct: SimpleNamespace(**dct))
        profile_uuid = profile.uuid
        return profile_uuid
    except Exception as e:
        raise SenseException(f"Exception searching for profile:{e}")


def create_instance(*, client=None, bandwidth, profile, alias, layer3, peering, interfaces):
    client = client or get_client()
    profile_uuid = get_profile_uuid(client=client, profile=profile)
    workflow_api = WorkflowCombinedApi(req_wrapper=client)
    workflow_api.instance_new()
    intent = {SENSE_PROFILE_UID: profile_uuid, "alias": alias}
    edit_entries = []
    profile_details = describe_profile(client=client, uuid=profile_uuid)

    logger.debug(f'Profile Details: {profile_details}')

    if hasattr(profile_details, "edit"):
        edit_entries = profile_details.edit
        temp_entries = [e.__dict__ for e in edit_entries]
        logger.info(f'Edit Entries: {json.dumps(temp_entries, indent=2)}')

    edit_uri_entries = [e for e in edit_entries if e.path.endswith(SENSE_URI)]
    options = []

    if interfaces:
        populate_options_using_interfaces(options, interfaces, edit_uri_entries)

    if bandwidth:
        options.append({f"data.connections[{0}].bandwidth.capacity": bandwidth})

    if peering:
        try:
            gateway_type = profile_details.intent.data.gateways[0].type.upper()
            if "GCP" in gateway_type:
                peering_mapping = SENSE_GCP_PEERING_MAPPING
            elif "AWS" in gateway_type:
                peering_mapping = SENSE_AWS_PEERING_MAPPING
            else:
                raise SenseException(f"Was not able to figure out peering mapping for {gateway_type}")
        except Exception as e:
            raise SenseException(f"Was not able to figure out peering mapping:{str(e)}")

        for k, v in peering_mapping.items():
            if k in peering.attributes:
                path = "data.gateways[0].connects[0]." + v
                options.append({path: peering.attributes[k]})

    if layer3:
        edit_entry_paths = [e.path for e in edit_entries]
        subnet = layer3.attributes[Constants.RES_SUBNET]

        from ipaddress import IPv4Network

        subnet = IPv4Network(subnet)

        if "data.subnets[0].cidr" in edit_entry_paths:
            options.append({f"data.subnets[0].cidr": str(subnet)})
            vpc_subnet = subnet

            for i in [8, 4, 2]:
                if subnet.prefixlen - i > 0:
                    vpc_subnet = subnet.supernet(i)
                    break

            options.append({"data.cidr": str(vpc_subnet)})

    if options:
        query = dict([("ask", "edit"), ("options", options)])
        intent["queries"] = [query]

    logger.info(f'Intent: {json.dumps(intent, indent=2)}')
    intent = json.dumps(intent)

    import time
    from random import randint

    for attempt in range(SENSE_RETRY):
        try:
            logger.info(f"creating instance: {alias}:attempt={attempt + 1}")
            response = workflow_api.instance_create(intent)  # service_uuid, intent_uuid, queries, model
            temp = json.loads(response)
            status = workflow_api.instance_get_status()
            return temp['service_uuid'], status
        except Exception as e:
            logger.warning(f"exception while creating instance {e}")

        time.sleep(randint(30, 35))

    raise SenseException(f"could not create instance {alias}")


def instance_operate(*, client=None, si_uuid, action='provision'):
    import time
    from random import randint

    client = client or get_client()
    workflow_api = WorkflowCombinedApi(req_wrapper=client)
    status = workflow_api.instance_get_status(si_uuid=si_uuid)

    if "CREATE - COMMITTING" not in status or 'CANCEL - READY' == status:
        try:
            time.sleep(randint(5, 10))
            workflow_api.instance_operate(action, si_uuid=si_uuid, async_req=True)
        except Exception as e:
            logger.warning(f"exception from instance_operate {e}")


def wait_for_instance_operate(*, client=None, si_uuid,
                              statuses=('CREATE - READY', 'REINSTATE - READY')):
    import time
    from random import randint

    client = client or get_client()
    workflow_api = WorkflowCombinedApi(req_wrapper=client)

    for attempt in range(SENSE_RETRY):
        try:
            status = workflow_api.instance_get_status(si_uuid=si_uuid)
            logger.info(f"Waiting on {statuses}: status={status}:attempt={attempt} out of {SENSE_RETRY}")

            if status in statuses:
                return status

            if 'FAILED' in status:
                return status
        except Exception as e:
            logger.warning(f"exception from  instance_get_status {e}")
            pass

        logger.info(f"Waiting on {statuses}: going to sleep attempt={attempt}")
        time.sleep(randint(30, 35))

    return workflow_api.instance_get_status(si_uuid=si_uuid)


def delete_instance(*, client=None, si_uuid):
    import time
    import random

    client = client or get_client()
    workflow_api = WorkflowCombinedApi(req_wrapper=client)

    status = workflow_api.instance_get_status(si_uuid=si_uuid)

    if 'error' in status:
        raise SenseException("error deleting got " + status)

    if 'FAILED' in status:
        raise SenseException(f'cannot delete instance - contact admin. {status}')

    if "CREATE - COMPILED" in status:
        time.sleep(random.randint(5, 30))

        workflow_api.instance_delete(si_uuid=si_uuid)
        return

    if "CANCEL" not in status:
        if 'CREATE' not in status and 'REINSTATE' not in status and 'MODIFY' not in status:
            raise ValueError(f"cannot cancel an instance in '{status}' status...")

        time.sleep(random.randint(5, 30))

        if 'READY' not in status:
            workflow_api.instance_operate('cancel', si_uuid=si_uuid, sync='false', force='true')
        else:
            workflow_api.instance_operate('cancel', si_uuid=si_uuid, sync='false')

    for attempt in range(SENSE_RETRY):
        # This sleep is here to workaround issue where CANCEL-READY shows up prematurely.
        time.sleep(random.randint(30, 35))

        status = workflow_api.instance_get_status(si_uuid=si_uuid)
        # print("LOOPING:DELETE:Status=", status, "attempt=", attempt)
        logger.info(f"Waiting on CANCEL-READY: status={status}:attempt={attempt} out of {SENSE_RETRY}")

        if 'CANCEL - READY' in status:  # This got triggered very quickly ...
            break

        if 'FAILED' in status:
            break

    if 'CANCEL - READY' in status:
        logger.info(f"Deleting instance: {si_uuid}")
        time.sleep(random.randint(5, 30))
        ret = workflow_api.instance_delete(si_uuid=si_uuid)
        logger.info(f"Deleted instance: {si_uuid}: ret={ret}")
    else:
        raise SenseException(f'cancel operation disrupted - instance not deleted - contact admin. {status}')


def instance_get_status(*, client=None, si_uuid):
    client = client or get_client()
    workflow_api = WorkflowCombinedApi(req_wrapper=client)
    return workflow_api.instance_get_status(si_uuid=si_uuid)


def service_instance_details(*, client=None, si_uuid, alias):
    client = client or get_client()
    discover_api = DiscoverApi(req_wrapper=client)
    response = discover_api.discover_service_instances_get(search=alias)
    # print(json.dumps(json.loads(response), indent=2))
    response = json.loads(response)
    instances = response['instances']

    for instance in instances:
        temp = SimpleNamespace(**instance)

        if temp.referenceUUID == si_uuid:
            instance['intents'] = []

            for intent in temp.intents:
                intent['json'] = json.loads(intent['json'])
                instance['intents'].append(intent)

            return instance

    raise SenseException('no details found')


def discover_service_instances(*, client=None):
    client = client or get_client()
    discover_api = DiscoverApi(req_wrapper=client)
    response = discover_api.discover_service_instances_get()
    # print(json.dumps(json.loads(response), indent=2))
    response = json.loads(response)
    instances = response['instances']

    for instance in instances:
        temp = SimpleNamespace(**instance)
        instance['intents'] = []

        for intent in temp.intents:
            intent['json'] = json.loads(intent['json'])
            instance['intents'].append(intent)

    return instances


def find_instance_by_alias(*, client=None, alias):
    client = client or get_client()
    instances = discover_service_instances(client=client)

    for instance in instances:
        if instance['alias'] == alias:
            return instance['referenceUUID']

    return None


def get_vms_specs_from_profile(*, client=None, profile_uuid):
    client = client or get_client()
    profile_details = describe_profile(client=client, uuid=profile_uuid)
    all_vms = []

    if hasattr(profile_details, "intent"):
        for subnet in profile_details.intent.data.subnets:
            vms = [vars(vm) for vm in subnet.vms]
            all_vms.extend(vms)

    return all_vms


def manifest_create(*, client=None, template_file=None, alias=None, si_uuid=None):
    import os
    import time
    from json.decoder import JSONDecodeError

    client = client or get_client()
    si_uuid = si_uuid or find_instance_by_alias(alias=alias)
    workflow_api = WorkflowCombinedApi(req_wrapper=client)
    template_file = os.path.join(os.path.dirname(__file__), 'manifests', template_file)

    with open(template_file, 'r') as fp:
        template = json.load(fp)

    template = json.dumps(template)

    for attempt in range(SENSE_RETRY):
        response = workflow_api.manifest_create(template, si_uuid=si_uuid)

        try:
            response = json.loads(response, object_hook=lambda dct: SimpleNamespace(**dct))
            details = json.loads(response.jsonTemplate)
            return details
        except JSONDecodeError:
            logger.warning(f"Could not decode sense manifest from response={response}")

        time.sleep(10)

    raise SenseException(f"Unable to retrieve manifest using {template_file}")
