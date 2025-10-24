import json

from amscrot.model import Node
from amscrot.util.utils import get_logger
from amscrot.util.constants import Constants
from .cloudlab_constants import *
from .cloudlab_exceptions import CloudlabException
from .cloudlab_provider import CloudlabProvider

logger = get_logger()


class CloudlabNode(Node):
    def __init__(self, *, label, name: str, provider: CloudlabProvider, network):
        super().__init__(label=label, name=name, image="", site="", flavor="")
        self._provider = provider
        self._net = network
        self.dataplane_ipv4 = None
        self.dataplane_ipv6 = None
        self.keyfile = provider.private_key_file_location
        self.user = provider.user

    @property
    def provider(self):
        return self._provider

    @property
    def net(self):
        return self._net

    def create(self):
        import emulab_sslxmlrpc.client.api as api

        server = self.provider.rpc_server()
        exp_params = self.provider.experiment_params(self.net.name)
        exitval, response = api.experimentStatus(server, exp_params).apply()

        if exitval:
            raise CloudlabException(exitval=exitval, response=response)

        status = json.loads(response.value)
        logger.info(f"STATUS: {json.dumps(status, indent=2)}")

        if status['status'] != 'ready':
            raise CloudlabException(message=f"Found experiment with status={status['status']}")

        node_uris = list(status[AGGREGATE_STATUS].keys())
        node_uri = [uri for uri in  node_uris if 'stitch' not in uri][0]
        idx = int(self.name[self.name.rindex('-') + 1:])
        node_info = status[AGGREGATE_STATUS][node_uri][NODES]["node" + str(idx)]
        logger.info(f"NODE_INFO {self.name}: {node_info}")

        self.mgmt_ip = node_info[IPV4]
        self.host = node_info[IPV4]
        exitval, response = api.experimentManifests(server, exp_params).apply()

        if exitval:
            raise CloudlabException(exitval=exitval, response=response)

        status = json.loads(response.value)

        logger.debug(json.dumps(status, indent=2))

        import xmltodict

        data_dict = xmltodict.parse(list(status.values())[0])
        logger.debug(f"RSPEC: {json.dumps(data_dict['rspec'], indent=2)}")
        nodes = data_dict['rspec']['node']
        nodes = [n for n in nodes if self._net.cluster == n['@component_manager_id']]
        n = nodes[idx]

        if n['interface']['ip']['@type'] == 'ipv4':
            self.dataplane_ipv4 = n['interface']['ip']['@address']
        else:
            self.dataplane_ipv6 = n['interface']['ip']['@address']

        self.site = n['jacks:site']['@id']

    def delete(self):
        pass

    def get_reservation_state(self) -> str:
        pass

    def get_reservation_id(self) -> str:
        pass

    def add_route(self, subnet, gateway):
        pass

    def get_dataplane_address(self, network=None, interface=None, af=Constants.IPv4):
        if af == Constants.IPv4:
            return self.dataplane_ipv4
        elif af == Constants.IPv6:
            return self.dataplane_ipv6
        else:
            return None
