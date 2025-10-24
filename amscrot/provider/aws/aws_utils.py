import time

import boto3

from amscrot.util.utils import get_logger
from amscrot.util.constants import Constants
from .aws_constants import *
from .aws_exceptions import AwsException

logger = get_logger()


def create_ec2_client(*, region: str, access_key: str, secret_key: str):
    ec2_client = boto3.client(
        'ec2',
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )

    return ec2_client


def is_vpc_available(*, ec2_client, vpc_id: str):
    response = ec2_client.describe_vpcs(VpcIds=[vpc_id])

    if response and isinstance(response, dict) and 'Vpcs' in response:
        vpc = next(iter(response['Vpcs']), None)

        if vpc:
            state = vpc['State']

            if state == 'available':
                return True

            logger.warning(f'found vpc {vpc_id} with state={state}')
        else:
            raise AwsException(f"Vpc not found {vpc_id}")

    return False


def find_route_tables(*, ec2_client, vpc_id):
    response = ec2_client.describe_route_tables()
    route_tables = []

    if response and isinstance(response, dict) and 'RouteTables' in response:
        for route_table in response['RouteTables']:
            if route_table['VpcId'] == vpc_id:
                route_tables.append(route_table)

    return route_tables


def create_subnet_if_needed(*, ec2_client, cidr, vpc_id):
    response = ec2_client.describe_subnets()
    subnet = next(
        filter(lambda sub: sub['CidrBlock'] == cidr and sub['VpcId'] == vpc_id, response['Subnets']),
        None
    )

    if not subnet:
        logger.info(f'Creating subnet {cidr}')

        response = ec2_client.create_subnet(
            CidrBlock=cidr,
            VpcId=vpc_id
        )

        subnet = response['Subnet']

    logger.info(f'Got Subnet {subnet}')

    state = subnet['State']
    subnet_id = subnet['SubnetId']

    if state == 'available':
        return subnet_id

    for i in range(RETRY):
        response = ec2_client.describe_subnets(SubnetIds=[subnet_id])
        subnet = next(filter(lambda sub: sub['CidrBlock'] == cidr and sub['VpcId'] == vpc_id, response['Subnets']))
        state = subnet['State']
        logger.info(f'Waiting on subnet {subnet_id}: state={state}')

        if state == 'available':
            return subnet_id

        time.sleep(20)

    raise AwsException(f'Timed out. subnet {subnet_id}:state={state}')


# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/enable_vgw_route_propagation.html
# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_route_tables.html

def print_route_tables(ec2_client, vpc_id):
    route_tables = find_route_tables(ec2_client=ec2_client, vpc_id=vpc_id)
    print()
    print("Number of route tables", len(route_tables))

    for route in route_tables:
        print()
        print("Begin Routetable")
        print(route)

        print("PropagatingVgws", route['PropagatingVgws'])

        for asso in route['Associations']:
            print('ASSOCIATION=', asso, "::::")
        print("END Routetable")

    print()


def create_route_table_if_needed(*, ec2_client, cidr, vpc_id, vpn_id):
    subnet_id = create_subnet_if_needed(ec2_client=ec2_client, cidr=cidr, vpc_id=vpc_id)
    route_tables = find_route_tables(ec2_client=ec2_client, vpc_id=vpc_id)

    for route_table in route_tables:
        if {'GatewayId': vpn_id} in route_table['PropagatingVgws']:
            logger.info(f'Already associated to vpn {vpn_id}')
            print_route_tables(ec2_client=ec2_client, vpc_id=vpc_id)
            return route_table

    for route_table in route_tables:
        for asso in route_table['Associations']:
            if asso.get('SubnetId') == subnet_id:
                response = ec2_client.disassociate_route_table(
                    AssociationId=asso['RouteTableAssociationId']
                )

                logger.info(f'disassociated_route_table from subnet={subnet_id}:response={response}')
                break

    logger.info(f'Creating route_table vpc={vpc_id}')
    response = ec2_client.create_route_table(VpcId=vpc_id)
    route_table = response['RouteTable']
    route_table_id = route_table['RouteTableId']
    response = ec2_client.associate_route_table(RouteTableId=route_table_id, SubnetId=subnet_id)
    logger.info(f'associate_created_route_table:response={response}')
    response = ec2_client.enable_vgw_route_propagation(GatewayId=vpn_id, RouteTableId=route_table_id)
    logger.info(f'enable_vgw_route_propagation_to_created_table:response={response}')
    print_route_tables(ec2_client=ec2_client, vpc_id=vpc_id)
    return route_table


def delete_route_table_if_needed(*, ec2_client, vpc_id, route_table_id):
    logger.info(f'deleting route_table:{route_table_id}')
    route_tables = find_route_tables(ec2_client=ec2_client, vpc_id=vpc_id)
    route_table = next(filter(lambda rt: rt['RouteTableId'] == route_table_id, route_tables), None)

    if not route_table:
        logger.info(f'route_table not found:{route_table_id}')
        return

    for route_table in route_tables:
        for asso in route_table['Associations']:
            if asso.get('SubnetId'):
                subnet_id = asso.get('SubnetId')
                response = ec2_client.disassociate_route_table(
                    AssociationId=asso['RouteTableAssociationId']
                )

                logger.info(f'disassociated_route_table from subnet={subnet_id}: response={response}')

    response = ec2_client.delete_route_table(RouteTableId=route_table_id)
    logger.info(f'deleted route_table:{route_table_id}:response={response}')

    for i in range(RETRY):
        route_tables = find_route_tables(ec2_client=ec2_client, vpc_id=vpc_id)
        route_table = next(filter(lambda rt: rt['RouteTableId'] == route_table_id, route_tables), None)

        if not route_table:
            break
        logger.info(f'waiting on deleting route_table:{route_table_id}:response={response}')
        time.sleep(20)

    logger.info(f'done deleting route_table:{route_table_id}:response={response}')
    print_route_tables(ec2_client=ec2_client, vpc_id=vpc_id)


def find_available_dx_connection(*, direct_connect_client, name: str):
    response = direct_connect_client.describe_connections()

    if not isinstance(response, dict) and 'connections' not in response:
        raise AwsException(f'did not find dx connection {name}')

    # connection = next(filter(lambda con: con['connectionName'] == name, response['connections']), None)
    connections = list(filter(lambda con: con['connectionName'] == name, response['connections']))

    if not connections:
        raise AwsException(f'did not find dx connection {name}')

    for connection in connections:
        logger.info(f'Found dx connection {connection}')
    
        state = connection['connectionState']
        vlan = connection['vlan']
        connection_id = connection['connectionId']
        
        if state in ['down', 'deleting', 'deleted', 'rejected', 'unknown']:
            continue
    
        if state == 'available':
            return connection_id, vlan
    
        if state == 'ordering':
            response = direct_connect_client.confirm_connection(connectionId=connection_id)
            logger.info(f'response from confirm dx connection {response}')
    
        for i in range(RETRY):
            response = direct_connect_client.describe_connections(connectionId=connection_id)
            connection = next(filter(lambda con: con['connectionName'] == name, response['connections']))
            state = connection['connectionState']
            logger.info(f'state={state}. dx connection {connection}')
    
            if state == 'available':
                return connection_id, vlan
    
            time.sleep(20)

    raise AwsException(f'Timed out. dx connection {name}:state={state}')


def find_vpn_gateway(*, ec2_client, name: str):
    response = ec2_client.describe_vpn_gateways()

    if isinstance(response, dict) and 'VpnGateways' in response:
        for gw in response['VpnGateways']:
            if 'Tags' in gw and gw['Tags']:
                name_tag = next(filter(lambda t: t['Key'] == 'Name' and t['Value'] == name, gw['Tags']), None)

                if name_tag:
                    return gw['VpnGatewayId']

    return None


def _find_vpn_gateway_by_id(*, ec2_client, vpn_id: str):
    response = ec2_client.describe_vpn_gateways()

    if response and isinstance(response, dict) and 'VpnGateways' in response:
        for gw in response['VpnGateways']:
            if gw['VpnGatewayId'] == vpn_id:
                return gw

    return None


def attach_vpn_gateway_if_needed(*, ec2_client, vpn_id: str, vpc_id: str):
    vpn_gateway = _find_vpn_gateway_by_id(ec2_client=ec2_client, vpn_id=vpn_id)
    attachments = vpn_gateway['VpcAttachments']
    attachment = next(filter(lambda at: at['VpcId'] == vpc_id, attachments), None)

    if not attachment or attachment['State'] in ['detaching', 'detached']:
        response = ec2_client.attach_vpn_gateway(
            VpcId=vpc_id,
            VpnGatewayId=vpn_id
        )

        attachment = response['VpcAttachment']

    state = attachment['State']

    if state == 'attached':
        logger.info(f"VPN {vpn_id}:state={state}")
        return

    for i in range(RETRY):
        vpn_gateway = _find_vpn_gateway_by_id(ec2_client=ec2_client, vpn_id=vpn_id)
        attachments = vpn_gateway['VpcAttachments']
        attachment = next(filter(lambda at: at['VpcId'] == vpc_id, attachments))
        state = attachment['State']

        if state == 'attached':
            logger.info(f"VPN {vpn_id}:state={state}")
            return

        logger.info(f"Waiting on attaching VPN {vpn_id}:state={state}")
        time.sleep(20)

    raise AwsException(f"Timed out on attaching vpn_gateway: state={state}")


def detach_vpn_gateway_if_needed(*, ec2_client, vpn_id: str, vpc_id: str):
    vpn_gateway = _find_vpn_gateway_by_id(ec2_client=ec2_client, vpn_id=vpn_id)
    attachments = vpn_gateway['VpcAttachments']
    attachment = None

    for a in attachments:
        if a['VpcId'] == vpc_id:
            attachment = a

    if not attachment:
        return

    try:
        logger.info(f"Detaching vpn:id={vpn_id}")
        ec2_client.detach_vpn_gateway(
            VpcId=vpc_id,
            VpnGatewayId=vpn_id
        )
    except Exception as e:
        logger.warning(f"failed to detach vpn: {e}")

    state = None

    for i in range(RETRY):
        vpn_gateway = _find_vpn_gateway_by_id(ec2_client=ec2_client, vpn_id=vpn_id)
        attachments = vpn_gateway['VpcAttachments']
        state = None

        for attachment in attachments:
            if attachment['VpcId'] == vpc_id:
                state = attachment['State']
                break

        if not state or state == 'detached':
            return

        logger.info(f"Waiting on detached vpn state={state}")
        time.sleep(20)

    raise AwsException(f"Timed out on detaching vpn_gateway: state={state}")


def create_vpn_gateway(*, ec2_client, name: str, amazon_asn: int):
    response = ec2_client.create_vpn_gateway(
        Type='ipsec.1',
        TagSpecifications=[
            {
                'ResourceType': 'vpn-gateway',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': name
                    },
                ]
            },
        ],
        AmazonSideAsn=amazon_asn
    )

    vpn_gateway = response['VpnGateway']
    vpn_id = vpn_gateway['VpnGatewayId']
    state = vpn_gateway['State']

    if state == 'available':
        logger.info(f"Returning VPN {name}:state={state}")
        return vpn_id

    for i in range(RETRY):
        vpn_gateway = _find_vpn_gateway_by_id(ec2_client=ec2_client, vpn_id=vpn_id)

        if vpn_gateway:
            state = vpn_gateway['State']

            if state == 'available':
                return vpn_id

        logger.info(f"Waiting on VPN {name}:state={state}")
        time.sleep(20)

    raise AwsException(f"Timed out on creating vpn_gateway: state={state}")


def delete_vpn_gateway(*, ec2_client, name: str):
    vpn_id = find_vpn_gateway(ec2_client=ec2_client, name=name)

    if not vpn_id:
        return

    ec2_client.delete_vpn_gateway(VpnGatewayId=vpn_id)
    state = None

    for i in range(RETRY):
        vpn_gateway = _find_vpn_gateway_by_id(ec2_client=ec2_client, vpn_id=vpn_id)

        if vpn_gateway:
            state = vpn_gateway['State']

        if not state or state == 'deleted':
            return vpn_id

        time.sleep(20)

    raise AwsException(f"Timed out on creating vpn_gateway: state={state}")


def create_direct_connect_client(*, region: str, access_key: str, secret_key: str):
    direct_connect_client = boto3.client(
        'directconnect',
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )

    return direct_connect_client


def find_direct_connect_gateway_by_name(*, direct_connect_client, gateway_name: str):
    response = direct_connect_client.describe_direct_connect_gateways()

    if response and isinstance(response, dict) and 'directConnectGateways' in response:
        for gw in response['directConnectGateways']:
            if gw['directConnectGatewayName'] == gateway_name:
                return gw['directConnectGatewayId']

    return None


def create_direct_connect_gateway(*, direct_connect_client, gateway_name: str, amazon_asn: int):
    direct_connect_gateway_id = find_direct_connect_gateway_by_name(
        direct_connect_client=direct_connect_client,
        gateway_name=gateway_name)

    if not direct_connect_gateway_id:
        response = direct_connect_client.create_direct_connect_gateway(
            directConnectGatewayName=gateway_name,
            amazonSideAsn=amazon_asn
        )

        logger.info(f"Created directConnectGateway {response}")
        direct_connect_gateway_id = response['directConnectGateway']['directConnectGatewayId']

    return direct_connect_gateway_id


def delete_direct_connect_gateway(*, direct_connect_client, gateway_name: str):
    direct_connect_gateway_id = find_direct_connect_gateway_by_name(
        direct_connect_client=direct_connect_client,
        gateway_name=gateway_name)

    if direct_connect_gateway_id:
        response = direct_connect_client.delete_direct_connect_gateway(
            directConnectGatewayId=direct_connect_gateway_id
        )

        logger.info(f"Deleted directConnectGateway {response}")

    return direct_connect_gateway_id


# 'virtualInterfaceState':
# 'confirming'|'verifying'|'pending'|'available'|'down'|'deleting'|'deleted'|'rejected'|'unknown',
def create_private_virtual_interface(*,
                                     direct_connect_client,
                                     vpn_gateway_id: str,
                                     connection_id,
                                     vlan,
                                     peering,
                                     vif_name: str):
    response = direct_connect_client.describe_virtual_interfaces()
    details = {}

    if isinstance(response, dict) and 'virtualInterfaces' in response:
        for vif in response['virtualInterfaces']:
            if vif['virtualGatewayId'] == vpn_gateway_id and vif['virtualInterfaceName'] == vif_name:
                logger.info(f"Found existing private virtual interface {vif_name}")

                for k in VIF_DETAILS:
                    details[k] = vif[k]

                break

    if not details:
        logger.info(f"Creating private virtual interface {vif_name}:connection_id={connection_id}:vlan={vlan}")

        bgp_asn = peering.attributes.get(Constants.RES_LOCAL_ASN)
        local_address = peering.attributes.get(Constants.RES_LOCAL_ADDRESS)
        remote_address = peering.attributes.get(Constants.RES_REMOTE_ADDRESS)
        bgp_key = peering.attributes.get(Constants.RES_SECURITY)

        vif = direct_connect_client.create_private_virtual_interface(
            connectionId=connection_id,
            newPrivateVirtualInterface={
                'virtualInterfaceName': vif_name,
                'vlan': vlan,
                'asn': bgp_asn,  # remote oess asn
                'mtu': 9001,
                'authKey': bgp_key,
                'amazonAddress': remote_address,   # local_address,
                'customerAddress': local_address,  # remote_address,
                'addressFamily': 'ipv4',
                'virtualGatewayId': vpn_gateway_id,
                'enableSiteLink': False
            }
        )

        for k in VIF_DETAILS:
            details[k] = vif[k]

    if details[VIF_STATE] == 'available':
        logger.info(f"Private virtual interface {vif_name} is {details[VIF_STATE]}")
        return details

    for i in range(RETRY):
        logger.warning(f"Waiting on private virtual interface {vif_name}:state={details[VIF_STATE]}:attempt={i + 1}")
        time.sleep(20)

        response = direct_connect_client.describe_virtual_interfaces()
        vif = next(filter(lambda v: v[VIF_ID] == details[VIF_ID], response['virtualInterfaces']))

        for k in VIF_DETAILS:
            details[k] = vif[k]

        state = details[VIF_STATE]

        if state == 'available':
            break

    if details[VIF_STATE] != 'available':
        raise AwsException(f"Virtual interface {vif_name}:state={details[VIF_STATE]}")

    logger.info(f"Private virtual interface {vif_name} is {details[VIF_STATE]}")
    return details


def delete_private_virtual_interface(*,
                                     direct_connect_client,
                                     vif_name: str):
    response = direct_connect_client.describe_virtual_interfaces()
    details = {}

    if isinstance(response, dict) and 'virtualInterfaces' in response:
        for vif in response['virtualInterfaces']:
            if vif['virtualInterfaceName'] == vif_name:
                logger.info(f"Found existing private virtual interface {vif_name}")

                for k in VIF_DETAILS:
                    details[k] = vif[k]

                break

    if not details:
        return

    if details[VIF_STATE] == 'deleted':
        logger.info(f"Private virtual interface {vif_name} is {details[VIF_STATE]}")
        return details

    logger.info(f"Deleting private virtual interface {vif_name}:{details}")
    direct_connect_client.delete_virtual_interface(
        virtualInterfaceId=details[VIF_ID]
    )

    for i in range(RETRY):
        logger.warning(f"Waiting on private virtual interface {vif_name}:state={details[VIF_STATE]}:attempt={i + 1}")
        time.sleep(20)

        response = direct_connect_client.describe_virtual_interfaces()
        vif = next(filter(lambda v: v[VIF_ID] == details[VIF_ID], response['virtualInterfaces']))

        for k in VIF_DETAILS:
            details[k] = vif[k]

        state = details[VIF_STATE]

        if state == 'deleted':
            break

    if details[VIF_STATE] != 'deleted':
        raise AwsException(f"Virtual interface {vif_name}:state={details[VIF_STATE]}")

    logger.info(f"Private virtual interface {vif_name} is {details[VIF_STATE]}")
    return details


def find_association_dxgw_vpn(*, direct_connect_client, direct_connect_gateway_id: str, vpn_id: str):
    response = direct_connect_client.describe_direct_connect_gateway_associations(
        virtualGatewayId=vpn_id,
        directConnectGatewayId=direct_connect_gateway_id,
    )

    if response and isinstance(response, dict) and 'directConnectGatewayAssociations' in response:
        associations = response['directConnectGatewayAssociations']

        if associations:
            return associations[0]

    return None


def find_association_dxgw_vpn_id(*, direct_connect_client, direct_connect_gateway_id: str, vpn_id: str):
    association = find_association_dxgw_vpn(
        direct_connect_client=direct_connect_client,
        direct_connect_gateway_id=direct_connect_gateway_id,
        vpn_id=vpn_id
    )

    if association:
        return association['associationId']

    return None


def associate_dxgw_vpn(direct_connect_client, direct_connect_gateway_id, vpn_id: str):
    association = find_association_dxgw_vpn(
        direct_connect_client=direct_connect_client,
        direct_connect_gateway_id=direct_connect_gateway_id,
        vpn_id=vpn_id
    )

    if association and association['associationState'] == 'associated':
        logger.info(f'association is associated:{association}')
        return association['associationId']

    if not association:
        response = direct_connect_client.create_direct_connect_gateway_association(
            directConnectGatewayId=direct_connect_gateway_id,
            virtualGatewayId=vpn_id
        )
        association = response['directConnectGatewayAssociation']

    state = association['associationState']

    if state == 'associated':
        logger.info(f'association is associated:{association}')
        return association['associationId']

    for i in range(RETRY):
        logger.warning(f'Waiting on association. state={state}: association:{association}')
        time.sleep(20)

        association = find_association_dxgw_vpn(
            direct_connect_client=direct_connect_client,
            direct_connect_gateway_id=direct_connect_gateway_id,
            vpn_id=vpn_id
        )

        state = association['associationState']

        if state == 'associated':
            logger.info(f'association is associated:{association}')
            return association['associationId']

    raise AwsException(f"Timed out on creating direct_connect_gateway_association: state={state}")


def dissociate_dxgw_vpn(*, direct_connect_client, association_id: str):
    response = direct_connect_client.delete_direct_connect_gateway_association(
        associationId=association_id
    )

    association = response['directConnectGatewayAssociation']

    if not association or not isinstance(association, dict) or 'associationState' not in association:
        return

    state = association['associationState']

    if state == 'disassociated':
        return

    direct_connect_gateway_id = association['directConnectGatewayId']
    vpn_id = association['virtualGatewayId']

    for i in range(RETRY):
        association = find_association_dxgw_vpn(
            direct_connect_client=direct_connect_client,
            direct_connect_gateway_id=direct_connect_gateway_id,
            vpn_id=vpn_id
        )

        if not association or not isinstance(association, dict) or 'associationState' not in association:
            return

        logger.info(f'checking if association state is disassociated: {association}')
        state = association['associationState']

        if state == 'disassociated':
            return

        time.sleep(20)

    raise AwsException(f"Timed out on deleting direct_connect_gateway_association:id={association_id}:state={state}")
