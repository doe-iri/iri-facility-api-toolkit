import json

from fabfed.model import Network
from fabfed.util.constants import Constants
from fabfed.util.utils import get_logger
from .cloudlab_constants import *
from .cloudlab_exceptions import CloudlabException
from .cloudlab_provider import CloudlabProvider

logger = get_logger()


class CloudNetwork(Network):
    def __init__(self, *, label, name: str, provider: CloudlabProvider,
                 stitch_info=None, profile: str, interfaces, layer3, cluster):
        super().__init__(label=label, name=name, site="")
        self.profile = profile
        self._provider = provider
        self.stitch_info = stitch_info
        self.interface = interfaces or []
        self.layer3 = layer3
        self.cluster = cluster
        self.stich_node_ip = None
        self.stich_site = None

    @property
    def provider(self):
        return self._provider

    @property
    def project(self):
        return self.provider.config[CLOUDLAB_PROJECT]

    def params(self):
        params = {
            "profile": f"{self.project},{self.profile}",
            "proj": self.project,
            "name": self.name,
            "asjson": True,
        }

        return params

    def create(self):
        import emulab_sslxmlrpc.client.api as api
        import emulab_sslxmlrpc.xmlrpc as xmlrpc

        server = self.provider.rpc_server()
        exp_params = self.provider.experiment_params(self.name)
        exitval, response = api.experimentStatus(server, exp_params).apply()

        if exitval == xmlrpc.RESPONSE_SEARCHFAILED:
            logger.debug(f"Network {self.name} not found, creating...")
            params = self.params()
            bindings = {}

            if self.interface:
                vlan = self.interface[0]['vlan']
                bindings['vlan'] = str(vlan)

            bindings['cluster'] = self.cluster
            # noinspection PyUnresolvedReferences
            nodes = [n for n in self.provider.nodes if n.net == self]
            bindings['node_count'] = str(len(nodes))
            subnet = self.layer3.attributes[Constants.RES_SUBNET]
            bindings['ip_subnet'] = str(subnet)
            ip_start = self.layer3.attributes[Constants.RES_LAYER3_DHCP_START]
            bindings['ip_start'] = str(ip_start)
            params['bindings'] = json.dumps(bindings)
            logger.info(f"Network {self.name} not found, creating... {params}")
            exitval, response = api.startExperiment(server, params).apply()

            if exitval:
                raise CloudlabException(exitval=exitval, response=response)

        elif exitval == xmlrpc.RESPONSE_SUCCESS or exitval == xmlrpc.RESPONSE_ALREADYEXISTS:
            logger.info("Network already exists, checking status")
        else:
            raise CloudlabException(exitval=exitval, response=response)

    def wait_for_create(self):
        import time
        import emulab_sslxmlrpc.client.api as api

        server = self.provider.rpc_server()
        exp_params = self.provider.experiment_params(self.name)
        attempt = -1

        for attempt in range(CLOUDLAB_RETRY):
            exitval, response = api.experimentStatus(server, exp_params).apply()

            # sometimes the response is not what we expect (network glitch). We keep checking status ...
            if response and hasattr(response, "value"):
                if exitval:
                    code = response.value

                    if code == api.GENIRESPONSE_REFUSED or code == api.GENIRESPONSE_NETWORK_ERROR:
                        logger.debug("Server is offline, waiting for a bit")
                    elif code == api.GENIRESPONSE_BUSY:
                        logger.debug("Experiment is busy, waiting for a bit")
                    elif code == api.GENIRESPONSE_SEARCHFAILED:
                        raise CloudlabException(message="Experiment is gone", exitval=exitval, response=response)
                    else:
                        raise CloudlabException(exitval=exitval, response=response)
                else:
                    status = json.loads(response.value)
                    logger.info(json.dumps(status, indent=2))

                    if status["status"] == "failed":
                        raise CloudlabException(exitval=exitval, response=response,
                                                message="Experiment failed to instantiate")
                    elif status["status"] == "ready":
                        if "execute_status" not in status:
                            logger.info("No execute service to wait for!")
                            break

                        total = status["execute_status"]["total"]
                        finished = status["execute_status"]["finished"]

                        if total != finished:
                            logger.info("Still waiting for execute service to finish")
                            continue

                        logger.info("Execute services have finished")
                        break

            if response and hasattr(response, "value"):
                logger.info(f"Still waiting for experiment to be ready exitval={exitval}:{response.value}")
            else:
                logger.warning(f"Still waiting for experiment to be ready exitval={exitval}:{response}")

            time.sleep(CLOUDLAB_SLEEP_TIME)

        if attempt == CLOUDLAB_RETRY:
            raise CloudlabException(message="Please Apply Again. Giving up on waiting for experiment ...")

        exitval, response = api.experimentManifests(server, exp_params).apply()

        if exitval:
            raise CloudlabException(exitval=exitval, response=response)

        status = json.loads(response.value)
        logger.debug(json.dumps(status, indent=2))
        logger.info(f"STATUS_KEYS={status.keys()}")

        import xmltodict

        data_dict = xmltodict.parse(next(iter(status.values())))
        logger.info(f"RSPEC: {json.dumps(data_dict['rspec'], indent=2)}")
        link = data_dict['rspec']['link']

        temp = dict(id=self.label, vlan=link['@vlantag'])
        temp.update(self.stitch_info.stitch_port['peer'])
        temp['provider'] = self.stitch_info.stitch_port['provider']
        self.interface = [temp]

        # noinspection PyUnresolvedReferences
        if not [n for n in self.provider.nodes if n.net == self]:
            return

        all_nodes = data_dict['rspec']['node']
        nodes = [n for n in all_nodes if 'stitch' not in ['@component_manager_id']]
        n = nodes[0]
        self.stich_node_ip = n['interface']['ip']['@address']
        self.stich_site = n['jacks:site']['@id']
        nodes = [n for n in all_nodes if 'stitch' not in n['@component_manager_id']]
        self.site = nodes[0]['jacks:site']['@id']

    def delete(self):
        import emulab_sslxmlrpc.client.api as api
        import emulab_sslxmlrpc.xmlrpc as xmlrpc
        import time

        server = self.provider.rpc_server()
        exp_params = self.provider.experiment_params(self.name)
        exitval, response = api.experimentStatus(server, exp_params).apply()

        if exitval == xmlrpc.RESPONSE_SEARCHFAILED:
            return

        exitval, response = api.terminateExperiment(server, exp_params).apply()

        if exitval == xmlrpc.RESPONSE_SUCCESS:
            while True:
                exitval, response = api.experimentStatus(server, exp_params).apply()

                if exitval == xmlrpc.RESPONSE_SEARCHFAILED:
                    break

                logger.info("Still waiting for experiment to be terminated")
                time.sleep(CLOUDLAB_SLEEP_TIME)

        if exitval != xmlrpc.RESPONSE_SEARCHFAILED:
            raise CloudlabException(exitval=exitval, response=response)
