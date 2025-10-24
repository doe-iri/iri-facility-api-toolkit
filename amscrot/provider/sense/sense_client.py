from sense.client.requestwrapper import RequestWrapper

SENSE_CLIENT = None


def init_client(config):
    global SENSE_CLIENT

    if not SENSE_CLIENT:
        SENSE_CLIENT = SenseClient(config)


def get_client():
    return SENSE_CLIENT


# TODO Fix this and make sure the config is coming from fabfed credentials
class SenseClient(RequestWrapper):
    def __init__(self, config=None):
        self.temp_config = config
        super().__init__()

    def getConfig(self, config_file=None):
        if not self.temp_config:
            super().getConfig()
            return

        normalized_config = {}
        for k, v in self.temp_config.items():
            if k == 'verify':
                normalized_config['verify'] = v
            else:
                normalized_config[k.upper()] = v
        self.config = normalized_config
        self._validateConfig()
        self._setDefaults()
