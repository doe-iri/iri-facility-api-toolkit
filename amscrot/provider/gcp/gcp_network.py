from amscrot.model import Network
from amscrot.util.utils import get_logger, Constants
from . import gcp_utils
from .gcp_exceptions import GcpException
from .gcp_provider import GcpProvider

logger = get_logger()


class GcpNetwork(Network):
    def __init__(self, *, label, name: str, provider: GcpProvider, layer3, peering, stitch_port):
        super().__init__(label=label, name=name, site="")
        self._provider = provider
        self.layer3 = layer3
        self.peering = peering
        self.stitch_port = stitch_port
        self.interface = []

    def create(self):
        project = self._provider.project
        service_key_path = self._provider.service_key_path
        vpc = self.peering.attributes.get(Constants.RES_CLOUD_VPC)

        if not vpc:
            raise GcpException(f"Must supply Vpc using peering config and {Constants.RES_CLOUD_VPC}")

        vpc_details = gcp_utils.find_vpc(service_key_path=service_key_path,
                                         project=project,
                                         vpc=vpc)

        if not vpc_details:
            raise GcpException(f"Vpc {vpc} not found")

        logger.info(f"vpc_details={vpc_details}")

        region = self.peering.attributes.get(Constants.RES_CLOUD_REGION)

        if not region:
            region = self.stitch_port['peer'].get(Constants.STITCH_PORT_REGION)

        if not region:
            raise GcpException(f"Missing cloud region")

        router_name = f'{self.name}-router'
        router = gcp_utils.find_router(service_key_path=service_key_path,
                                       project=project,
                                       region=region,
                                       router_name=router_name)

        if not router:
            google_asn = self.peering.attributes.get(Constants.RES_REMOTE_ASN)

            if isinstance(google_asn, str):
                google_asn = int(google_asn)

            vpc = self.peering.attributes.get(Constants.RES_CLOUD_VPC)
            gcp_utils.create_router(service_key_path=service_key_path,
                                    project=project,
                                    region=region,
                                    router_name=router_name,
                                    vpc=vpc,
                                    bgp_asn=google_asn)

        attachment_name = f'{self.name}-vlan-attachment'
        attachment = gcp_utils.find_interconnect_attachment(service_key_path=service_key_path,
                                                            project=project,
                                                            region=region,
                                                            attachment_name=attachment_name)

        if not attachment:
            mtu = self.peering.attributes.get(Constants.RES_CLOUD_MTU, 1460)
            gcp_utils.create_interconnect_attachment(service_key_path=service_key_path,
                                                     project=project,
                                                     region=region,
                                                     mtu=int(mtu),
                                                     router_name=router_name,
                                                     attachment_name=attachment_name)
            attachment = gcp_utils.find_interconnect_attachment(service_key_path=service_key_path,
                                                                project=project,
                                                                region=region,
                                                                attachment_name=attachment_name)

        # set the MD5 authentication
        assert Constants.RES_SECURITY in self.peering.attributes
        bgp_key = self.peering.attributes[Constants.RES_SECURITY]

        gcp_utils.patch_router(service_key_path=service_key_path,
                               project=project,
                               region=region,
                               router_name=router_name,
                               bgp_key=bgp_key)

        logger.info(f"attachment_details={attachment}")
        self.interface.append(dict(id=attachment.pairing_key, provider=self._provider.type))

    def delete(self):
        project = self._provider.project
        service_key_path = self._provider.service_key_path
        region = self.peering.attributes.get(Constants.RES_CLOUD_REGION)

        if not region:
            region = self.stitch_port['peer'].get(Constants.STITCH_PORT_REGION)

        if not region:
            raise GcpException(f"Missing cloud region")

        attachment_name = f'{self.name}-vlan-attachment'
        attachment = gcp_utils.find_interconnect_attachment(service_key_path=service_key_path,
                                                            project=project,
                                                            region=region,
                                                            attachment_name=attachment_name)

        if attachment:
            gcp_utils.delete_interconnect_vlan_attachment(service_key_path=service_key_path,
                                                          project=project,
                                                          region=region,
                                                          attachment_name=attachment_name)

        router_name = f'{self.name}-router'
        router = gcp_utils.find_router(service_key_path=service_key_path,
                                       project=project,
                                       region=region,
                                       router_name=router_name)

        if router:
            gcp_utils.delete_router(service_key_path=service_key_path,
                                    project=project,
                                    region=region,
                                    router_name=router_name)
