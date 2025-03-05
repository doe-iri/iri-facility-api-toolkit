from fabfed.model import Network
from fabfed.util.utils import get_logger
from . import sense_utils
from .sense_constants import SERVICE_INSTANCE_KEYS
from .sense_exceptions import SenseException
import json

logger = get_logger()


class SenseNetwork(Network):
    def __init__(self, *, label, name: str, bandwidth, profile, layer3, peering, interfaces, saved_interfaces=None):
        super().__init__(label=label, name=name, site="")
        self.profile = profile
        self.layer3 = layer3
        self.peering = peering
        self.interface = interfaces or list()
        self.bandwidth = bandwidth
        self.dtn = []
        self.id = ''
        self.referenceUUID = self.id
        self.intents = []
        self._saved_interfaces = saved_interfaces or list()

    # CREATE - COMPILED, CREATE - COMMITTING, CREATE - COMMITTED, CREATE - READY
    def create(self):
        si_uuid = sense_utils.find_instance_by_alias(alias=self.name)

        if not si_uuid:
            logger.debug(f"Creating {self.name}")
            self._saved_interfaces = list()
            si_uuid, status = sense_utils.create_instance(profile=self.profile, bandwidth=self.bandwidth,
                                                          alias=self.name,
                                                          layer3=self.layer3, peering=self.peering,
                                                          interfaces=self.interface)
        else:
            logger.debug(f"Found {self.name} {si_uuid}")
            assert si_uuid
            status = sense_utils.instance_get_status(si_uuid=si_uuid)
            logger.info(f"Found existing {self.name} {si_uuid} with status={status}")

        if 'FAILED' in status:
            raise SenseException(f"Found instance {si_uuid} with status={status}")

        if 'CREATE - READY' not in status:
            logger.debug(f"Provisioning {self.name}")
            sense_utils.instance_operate(si_uuid=si_uuid)

        statuses = ('CREATE - READY', 'REINSTATE - READY', 'CREATE - COMMITTED', 'REINSTATE - COMMITTED')
        status = sense_utils.wait_for_instance_operate(si_uuid=si_uuid, statuses=statuses)

        if status not in statuses:
            raise SenseException(f"Creation failed for {si_uuid} {status}")

        logger.debug(f"Retrieving details {self.name} {status}")
        instance_dict = sense_utils.service_instance_details(si_uuid=si_uuid, alias=self.name)
        logger.info(f"Retrieved details {self.name} {status}: \n{json.dumps(instance_dict, indent=2)}")

        for key in SERVICE_INSTANCE_KEYS:
            self.__setattr__(key, instance_dict.get(key))

        self.id = self.referenceUUID

        if (self.intents[0]['json']['service'] != 'vcn' or
                "GCP" not in self.intents[0]['json']['data']['gateways'][0]['type'].upper()):
            return

        for saved_interface in self._saved_interfaces:
            if saved_interface.get('kind') == 'gcp_pairing_key':
                self.interface.append(saved_interface)
                return

        from .sense_constants import SENSE_RETRY

        for attempt in range(SENSE_RETRY):
            try:
                template_file = 'gcp-pairing-key-template.json'
                details = sense_utils.manifest_create(si_uuid=si_uuid, template_file=template_file)
                pairing_key = details.get('Pairing Key', "?pairing_key?")

                if '?pairing_key?' not in pairing_key:
                    self.interface.append(dict(id=pairing_key, provider="sense", info=status, kind='gcp_pairing_key'))
                    break

            except Exception as e:
                if status in ('CREATE - READY', 'REINSTATE - READY'):
                    raise SenseException(f"not able to get pairing key ...status={status}:{e}")

            logger.warning(f"Waiting on pairing key: going to sleep attempt={attempt}:status={status}")
            import time

            time.sleep(2)
            status = sense_utils.instance_get_status(si_uuid=si_uuid)

    def delete(self):
        from . import sense_utils

        si_uuid = sense_utils.find_instance_by_alias(alias=self.name)

        logger.debug(f"Deleting {self.name} {si_uuid}")

        if si_uuid:
            sense_utils.delete_instance(si_uuid=si_uuid)
            logger.debug(f"Deleted {self.name} {si_uuid}")
