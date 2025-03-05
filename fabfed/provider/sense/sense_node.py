from fabfed.model import Node
from fabfed.util.utils import get_logger
from fabfed.util.constants import Constants
from . import sense_utils
from .sense_exceptions import SenseException
from . import sense_constants as SenseConstants

logger = get_logger()


class SenseNode(Node):
    def __init__(self, *, label, name: str, network: str, spec: dict, provider):
        super().__init__(label=label, name=name, image="", site="", flavor="")
        assert network
        self.network = network
        self._spec = spec
        self.spec_name = spec['name']
        self.node_details: dict = {}
        self.dataplane_ipv4 = None
        self.dataplane_ipv6 = None
        self._provider = provider

    def create(self):
        si_uuid = sense_utils.find_instance_by_alias(alias=self.network)

        if not si_uuid:
            raise SenseException(f"Instance not found by alias={self.network}")

        statuses = ('CREATE - READY', 'REINSTATE - READY')
        status = sense_utils.wait_for_instance_operate(si_uuid=si_uuid, statuses=statuses)

        if status not in statuses:
            raise SenseException(f"Instance is not in ready state:status={status}")

        """ retrieve the gateway type from intents """
        instance_dict = sense_utils.service_instance_details(si_uuid=si_uuid, alias=self.network)
        gateway_type = instance_dict.get("intents")[0]['json']['data']['gateways'][0]['type'].upper()
        if "GCP" in gateway_type:
            template_file = 'gcp-template.json'
        elif "AWS" in gateway_type:
            template_file = 'aws-template.json'
        else:
            raise SenseException(f"Was not able to get node template file {self.name}")

        details = sense_utils.manifest_create(alias=self.network, template_file=template_file)

        for node_details in details.get("Nodes", []):
            if node_details[SenseConstants.SENSE_NODE_NAME].lower() == self.spec_name.lower():
                self.node_details = node_details
                break

        if not self.node_details:
            raise SenseException(f"Was not able to get node details {self.name}:spec_name={self.spec_name}")

        self.dataplane_ipv4 = self.node_details[SenseConstants.SENSE_PRIVATE_IP]
        self.mgmt_ip = self.node_details[SenseConstants.SENSE_PUBLIC_IP]
        self.host = self.node_details[SenseConstants.SENSE_PUBLIC_IP]
        self.image = self.node_details[SenseConstants.SENSE_IMAGE]
        self.image = self.image[self.image.find("+") + 1:]
        self.keypair = self.node_details[SenseConstants.SENSE_KEYPAIR]

        self.user = sense_utils.get_image_info(self.image, 'user')

        if not self.user and "GCP" in gateway_type:
            if "+" in self.keypair:
                idx = self.keypair.index('+')
                self.user = self.keypair[idx + 1:]

        logger.info(f"node has user {self.user}")

        if self._provider:
            self.keyfile = self._provider.private_key_file_location

    def delete(self):
        si_uuid = sense_utils.find_instance_by_alias(alias=self.network)
        assert si_uuid is None

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
