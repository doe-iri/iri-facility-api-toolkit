class FabfedException(Exception):
    """Base class for other exceptions"""
    pass

class AnsibleException(FabfedException):
    pass

class ParseConfigException(FabfedException):
    pass


class ResourceTypeNotSupported(FabfedException):
    pass


class ResourceNotAvailable(FabfedException):
    pass


class ConfigTypeNotSupported(FabfedException):
    pass


class StateException(FabfedException):
    pass


class ProviderTypeNotSupported(FabfedException):
    pass


class StitchPortNotFound(FabfedException):
    pass


class ProviderException(FabfedException):
    pass


class ControllerException(FabfedException):
    def __init__(self, exceptions):
        self.exceptions = exceptions

        self.message = f"Number Of Exceptions={len(exceptions)}:["

        for ex in exceptions:
            self.message += "\nmsg=" + ''.join(str(ex).splitlines())

        self.message += "\n]"
        super().__init__(self.message)
