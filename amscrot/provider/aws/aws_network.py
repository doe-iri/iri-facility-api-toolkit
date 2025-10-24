from amscrot.model import Network
from amscrot.util.utils import get_logger, Constants
from . import aws_utils
from .aws_provider import AwsProvider
from .aws_exceptions import AwsException

logger = get_logger()


class AwsNetwork(Network):
    def __init__(self, *, label, name: str, provider: AwsProvider, layer3, peering, stitch_port, state=None):
        super().__init__(label=label, name=name, site="")
        self._provider = provider
        self.layer3 = layer3
        self.peering = peering
        self.stitch_port = stitch_port
        self.vpc_id = None
        self.vpn_id = None
        self.vif_details = {}
        self.route_table_details = {}
        self._state = state

    @property
    def vpn_gateway_name(self):
        return f'{self._provider.name}-fab-vpn-gateway'

    @property
    def vif_name(self):
        return f'{self._provider.name}-fab-vif'

    @property
    def connection_name(self):
        return self.peering.attributes.get(Constants.RES_ID)

    def create(self):
        region = self.peering.attributes.get(Constants.RES_CLOUD_REGION)

        if not region:
           region = self.stitch_port['peer'].get(Constants.STITCH_PORT_REGION)

        if not region:
           raise AwsException(f"Missing cloud region")

        logger.info(f'{self.name} using region {region}')

        ec2_client = aws_utils.create_ec2_client(region=region,
                                                 access_key=self._provider.access_key,
                                                 secret_key=self._provider.secret_key)
        self.vpc_id = self.peering.attributes.get(Constants.RES_CLOUD_VPC)

        if not self.vpc_id:
            raise AwsException(f"must supply vpc id using peering attribute: {Constants.RES_CLOUD_VPC}")

        if not aws_utils.is_vpc_available(ec2_client=ec2_client, vpc_id=self.vpc_id):
            raise AwsException(f"Vpc is not available:{self.vpc_id}")

        logger.info(f'Vpc {self.vpc_id} is available')

        direct_connect_client = aws_utils.create_direct_connect_client(
            region=region,
            access_key=self._provider.access_key,
            secret_key=self._provider.secret_key)

        connection_id, vlan = aws_utils.find_available_dx_connection(
            direct_connect_client=direct_connect_client,
            name=self.connection_name)

        logger.info(f'connection {self.connection_name} is available:connection_id={connection_id}')

        amazon_asn = self.peering.attributes.get(Constants.RES_REMOTE_ASN)

        if isinstance(amazon_asn, str):
           amazon_asn = int(amazon_asn)

        self.vpn_id = aws_utils.find_vpn_gateway(ec2_client=ec2_client, name=self.vpn_gateway_name)

        if not self.vpn_id:
            logger.info(f'Creating vpn gateway: name={self.vpn_gateway_name}:vpc={self.vpc_id}')
            self.vpn_id = aws_utils.create_vpn_gateway(
                ec2_client=ec2_client,
                name=self.vpn_gateway_name,
                amazon_asn=amazon_asn)
            logger.info(f'Created vpn gateway: name={self.vpn_gateway_name}')
        else:
            logger.info(f'Found vpn gateway: name={self.vpn_gateway_name}')

        aws_utils.attach_vpn_gateway_if_needed(ec2_client=ec2_client, vpn_id=self.vpn_id, vpc_id=self.vpc_id)

        self.route_table_details = aws_utils.create_route_table_if_needed(ec2_client=ec2_client,
                                                                    cidr=self.layer3.attributes['subnet'],
                                                                    vpc_id=self.vpc_id,
                                                                    vpn_id=self.vpn_id)

        self.vif_details = aws_utils.create_private_virtual_interface(
            direct_connect_client=direct_connect_client,
            vpn_gateway_id=self.vpn_id,
            connection_id=connection_id,
            vlan=vlan,
            peering=self.peering,
            vif_name=f"{self.vif_name}")

    def delete(self):
        region = self.peering.attributes.get(Constants.RES_CLOUD_REGION)

        if not region:
           region = self.stitch_port['peer'].get(Constants.STITCH_PORT_REGION)

        if not region:
           raise AwsException(f"Missing cloud region")

        ec2_client = aws_utils.create_ec2_client(region=region,
                                                 access_key=self._provider.access_key,
                                                 secret_key=self._provider.secret_key)

        vpc_id = self.peering.attributes.get(Constants.RES_CLOUD_VPC)
        if not vpc_id:
            return

        if not aws_utils.is_vpc_available(ec2_client=ec2_client, vpc_id=vpc_id):
            return

        vpn_id = aws_utils.find_vpn_gateway(ec2_client=ec2_client, name=self.vpn_gateway_name)

        if not vpn_id:
            return

        route_table_details = {}

        if self._state:
            route_table_details = self._state.attributes.get('route_table_details', {})

        route_table_id = route_table_details.get('RouteTableId')
        aws_utils.delete_route_table_if_needed(ec2_client=ec2_client, vpc_id=vpc_id, route_table_id=route_table_id)

        direct_connect_client = aws_utils.create_direct_connect_client(
            region=region,
            access_key=self._provider.access_key,
            secret_key=self._provider.secret_key)

        aws_utils.delete_private_virtual_interface(direct_connect_client=direct_connect_client,
                                                   vif_name=f"{self.vif_name}")

        aws_utils.detach_vpn_gateway_if_needed(ec2_client=ec2_client, vpn_id=vpn_id, vpc_id=vpc_id)
        aws_utils.delete_vpn_gateway(ec2_client=ec2_client, name=self.vpn_gateway_name)
