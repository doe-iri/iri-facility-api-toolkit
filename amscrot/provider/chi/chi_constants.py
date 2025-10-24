CHI_USER = "user"
CHI_PASSWORD = "password"
CHI_AUTH_URL = "auth_url"
CHI_TACC = "tacc"
CHI_UC = "uc"
CHI_KVM = "kvm"
CHI_EDGE = "edge"
CHI_CLIENT_ID = "client_id"
CHI_PROJECT_NAME = "project_name"
CHI_PROJECT_ID = "project_id"
CHI_RANDOM = "CHI.RANDOM"
CHI_KEY_PAIR = "key_pair"
CHI_SLICE_PRIVATE_KEY_LOCATION = "slice-private-key-location"
CHI_SLICE_PUBLIC_KEY_LOCATION = "slice-public-key-location"

CHI_CONF_ATTRS = [CHI_USER,
                  CHI_PASSWORD,
                  CHI_KEY_PAIR,
                  CHI_PROJECT_NAME,
                  CHI_PROJECT_ID,
                  CHI_SLICE_PRIVATE_KEY_LOCATION,
                  CHI_SLICE_PUBLIC_KEY_LOCATION]

DEFAULT_NETWORK = "sharednet1"
DEFAULT_NETWORKS = [DEFAULT_NETWORK, "sharedwan1", "containernet1"]
DEFAULT_IMAGE = "CC-Ubuntu20.04"
DEFAULT_FLAVOR = "m1.medium"

DEFAULT_AUTH_URLS = dict(
    tacc='https://chi.tacc.chameleoncloud.org:5000/v3',
    uc='https://chi.uc.chameleoncloud.org:5000/v3',
    kvm='https://kvm.tacc.chameleoncloud.org:5000/v3',
    edge='https://chi.edge.chameleoncloud.org:5000/v3'
)

DEFAULT_CLIENT_IDS = dict(
    tacc='keystone-tacc-prod',
    uc='keystone-uc-prod',
    kvm='keystone-kvm-prod',
    edge='keystone-edge-prod'
)

DEFAULT_PROJECT_IDS = dict(
    tacc='a400724e818d40cbba1a5c6b5e714462',
    uc='ae76673270164b048b59d3bd30676721',
    kvm='a400724e818d40cbba1a5c6b5e714462',
    edge=None
)

DEFAULT_DISCOVERY_URL = "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration"

INCLUDE_ROUTER = True 
