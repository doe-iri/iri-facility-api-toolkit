from amscrot.util.constants import Constants
import enum

AUTH_ENDPOINT = "auth_endpoint"
API_ENDPOINT = "api_endpoint"
CLIENT_ID = "client_id"
USERNAME = "username"
PASSWORD = "password"
SECRET = "secret"
SENSE_SLICE_PRIVATE_KEY_LOCATION = "slice-private-key-location"

SENSE_CONF_ATTRS = [AUTH_ENDPOINT, API_ENDPOINT, CLIENT_ID, USERNAME, PASSWORD, SECRET, SENSE_SLICE_PRIVATE_KEY_LOCATION]

SENSE_PROFILE_UID = "service_profile_uuid"
SENSE_ALIAS = "alias"
SENSE_EDIT = "options"
SENSE_URI = 'uri'
# SENSE_ID = 'id'
SENSE_PATH = 'path'
SENSE_VLAN_TAG = 'vlan_tag'

SENSE_DTN = 'With Host'
SENSE_DTN_IP = 'IP Address'

SERVICE_INSTANCE_KEYS = ['intents', 'alias', 'referenceUUID', 'state', 'owner', 'lastState', 'timestamp', 'archived']

SENSE_CUSTOMER_ASN = "customer_asn"
SENSE_AMAZON_ASN = "amazon_asn"
SENSE_GOOGLE_ASN = "google_asn"
SENSE_CUSTOMER_IP = "customer_ip"
SENSE_AMAZON_IP = "amazon_ip"
SENSE_GOOGLE_IP = "google_ip"
SENSE_AUTHKEY = "authkey"
SENSE_TO_HOSTED_CONN = "to_hosted_conn"

SENSE_AWS_PEERING_MAPPING = {
    Constants.RES_LOCAL_ASN: SENSE_CUSTOMER_ASN,
    Constants.RES_LOCAL_ADDRESS: SENSE_CUSTOMER_IP,

    Constants.RES_REMOTE_ASN: SENSE_AMAZON_ASN,
    Constants.RES_REMOTE_ADDRESS: SENSE_AMAZON_IP,

    Constants.RES_SECURITY: SENSE_AUTHKEY,

    Constants.RES_ID: SENSE_TO_HOSTED_CONN,
}

SENSE_GCP_PEERING_MAPPING = {
    Constants.RES_LOCAL_ASN: SENSE_CUSTOMER_ASN,
    Constants.RES_LOCAL_ADDRESS: SENSE_CUSTOMER_IP,

    Constants.RES_REMOTE_ASN: SENSE_GOOGLE_ASN,
    Constants.RES_REMOTE_ADDRESS: SENSE_GOOGLE_IP,

    Constants.RES_SECURITY: SENSE_AUTHKEY
}

# This is what we get from node_details from manifest for AWS ...
# 'Public IP': '18.215.246.8', 'Node Name': 'VM-1',
# 'Key Pair': 'keypair+kp-sense', 'Image': 'image+ami-052efd3df9dad4825'}

# ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-20220609
# ami-052efd3df9dad4825
# ami-052efd3df9dad4825
# Canonical, Ubuntu, 22.04 LTS, amd64 jammy image build on 2022-06-09

SENSE_KEYPAIR = 'Key Pair'
SENSE_PUBLIC_IP = 'Public IP'
SENSE_PRIVATE_IP = 'Private IP'
SENSE_NODE_NAME = 'Node Name'
SENSE_IMAGE = 'Image'

SENSE_RETRY = 50

class SupportedCloud(str, enum.Enum):
    """
    The Cloud supported by SENSE.
    """
    GCP = "GOOGLE"
    AWS = "AMAZON"
    DTN = "DTNL2"
