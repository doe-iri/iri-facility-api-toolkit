class Constants:
    IPv4 = "ipv4"
    IPv6 = "ipv6"
    FAB_EXTENSION = '.fab'
    CREDENTIAL_FILE = 'credential_file'
    PROFILE = 'profile'

    LABEL = 'label'
    RESOURCES = "resources"
    RESOURCE = "resource"
    RES_TYPE = "type"
    RES_SITE = "site"
    RES_COUNT = "count"
    RES_CREATION_DETAILS = "creation_details"
    RES_IMAGE = "image"
    RES_NIC_MODEL = "nic_model"
    RES_NAME_PREFIX = "name_prefix"
    
    # Named resources
    RES_NETWORK = "network"
    RES_COMPUTE = "compute"
    RES_STORAGE = "storage"
    RES_ALLOCATION = "allocation"
    RES_PROJECT = "project"
    RES_FACILITY = "facility"
    RES_CAPABILITY = "capability"
    RES_INTENT = "intent"

    RES_TYPE_NODE = "node"
    RES_TYPE_NETWORK = "network"
    RES_TYPE_SERVICE = "service"
    RES_SUPPORTED_TYPES = [RES_TYPE_NODE, RES_TYPE_NETWORK, RES_TYPE_SERVICE]
    RES_RESTRICTED_TYPES = [RES_TYPE_NETWORK]

    RES_TYPE_VM = "VM"
    RES_TYPE_BM = "Baremetal"
    RES_FLAVOR = "flavor"
    RES_FLAVOR_CORES = "cores"
    RES_FLAVOR_RAM = "ram"
    RES_FLAVOR_DISK = "disk"
    RES_FLAVOR_NAME = "name"
    RES_NET_POOL_START = "pool_start"
    RES_NET_POOL_END = "pool_end"
    RES_NET_GATEWAY = "gateway"
    RES_SUBNET = 'subnet'
    RES_LAYER3 = 'layer3'
    RES_PEER_LAYER3 = 'peer_layer3'
    RES_LAYER3_DHCP_START = 'ip_start'
    RES_LAYER3_DHCP_END = 'ip_end'

    RES_INTERFACES = 'interface'
    RES_NODES = 'node'
    RES_BANDWIDTH = "bandwidth"
    RES_INDEX = 'index'

    RES_PROFILE = "profile"
    RES_CLUSTER = "cluster"

    RES_PEERING = 'peering'
    RES_ID = "id"
    RES_LOCAL_ASN = "local_asn"
    RES_LOCAL_ADDRESS = "local_address"
    RES_REMOTE_ASN = "remote_asn"
    RES_REMOTE_ADDRESS = "remote_address"
    RES_SECURITY = "password"

    RES_CLOUD_FACILITY = "cloud_facility"
    RES_CLOUD_ACCOUNT = "cloud_account"
    RES_CLOUD_REGION = "cloud_region"
    RES_CLOUD_VPC = "cloud_vpc"
    RES_CLOUD_MTU = "cloud_mtu"
    RES_CLOUD_BW = "cloud_bw"
    RES_BW = "bw"
    RES_CLOUD_VLAN = "cloud_vlan"
    RES_BGP_KEY = "bgp_key"

    RES_LOCAL_DEVICE = "local_device"
    RES_LOCAL_PORT = "local_port"

    STITCH_PORT_DEVICE_NAME = 'device_name'
    STITCH_PORT_LOCAL_NAME = 'local_name'
    STITCH_PORT_REGION = 'region'
    STITCH_PORT_SITE = 'site'
    STITCH_VLAN_RANGE = 'vlan_range'
    STITCH_PORT_VLAN = 'vlan'

    RES_STITCH_INFO = "stitch_info"
    RES_STITCH_INTERFACE = "stitch_interface"

    LOGGING = "logging"
    PROPERTY_CONF_LOG_FILE = 'log-file'
    PROPERTY_CONF_LOG_LEVEL = 'log-level'
    PROPERTY_CONF_LOG_RETAIN = 'log-retain'
    PROPERTY_CONF_LOG_SIZE = 'log-size'
    PROPERTY_CONF_LOGGER = "logger"

    EXTERNAL_DEPENDENCIES = "external_dependencies"
    RESOLVED_EXTERNAL_DEPENDENCIES = "resolved_external_dependencies"

    INTERNAL_DEPENDENCIES = "internal_dependencies"
    RESOLVED_INTERNAL_DEPENDENCIES = "resolved_internal_dependencies"

    SAVED_STATES = "saved_states"
    CONFIG = "config"
    EXTERNAL_DEPENDENCY_STATES = "external_dependency_states"

    NETWORK_STITCH_WITH = "stitch_with"
    NETWORK_STITCH_OPTION = "stitch_option"
    NETWORK_STITCH_CONFIG = "policy"
    PROVIDER = 'provider'
    DEFAULT_IRO_ENDPOINT = "https://sense-o-east.es.net:8443/StackV-web/restapi"
    CONFIG_SUPPORTED_TYPES = [NETWORK_STITCH_CONFIG, "layer3", "peering"]
    
    class ServiceType:
        IRI = "iri"
        AMSC_IRI = "amsc-iri"
        KUBE = "kube"
        AMSC_IRO = "amsc-iro"
        DUMMY = "dummy-sc"

    PROVIDER_CLASSES = {
        "fabric": "amscrot.provider.fabric.fabric_provider.FabricProvider",
        "chi": "amscrot.provider.chi.chi_provider.ChiProvider",
        "sense": "amscrot.provider.sense.sense_provider.SenseProvider",
        "janus": "amscrot.provider.janus.janus_provider.JanusProvider",
        ServiceType.KUBE: "amscrot.provider.kube.kube_provider.KubeProvider",
        "cloudlab": "amscrot.provider.cloudlab.cloudlab_provider.CloudlabProvider",
        "gcp": "amscrot.provider.gcp.gcp_provider.GcpProvider",
        "aws": "amscrot.provider.aws.aws_provider.AwsProvider",
        "dummy": "amscrot.provider.dummy.dummy_provider.DummyProvider"
    }

    SERVICE_CLIENT_CLASSES = {
        ServiceType.IRI: "amscrot.serviceclient.amsc_iri.iri_service_client.IriServiceClient",
        ServiceType.AMSC_IRI: "amscrot.serviceclient.amsc_iri.iri_service_client.IriServiceClient",
        ServiceType.KUBE: "amscrot.serviceclient.kube.kube_service_client.KubeServiceClient",
        ServiceType.AMSC_IRO: "amscrot.serviceclient.amsc_iro.amsc_iro_service_client.AmscIroServiceClient",
        ServiceType.DUMMY: "amscrot.serviceclient.dummy.dummy_service_client.DummyServiceClient",
    }

    RECONCILE_STATES = True
    RUN_SSH_TESTER = True
    COPY_TOKENS = False
    PROVIDER_STATE = 'provider_state'
    LABELS = "labels"
