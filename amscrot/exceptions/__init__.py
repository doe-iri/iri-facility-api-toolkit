class AmSCROTException(Exception):
    """Base class for other exceptions"""
    pass

class AnsibleException(AmSCROTException):
    pass

class ParseConfigException(AmSCROTException):
    pass


class ResourceTypeNotSupported(AmSCROTException):
    pass


class ResourceNotAvailable(AmSCROTException):
    pass


class ConfigTypeNotSupported(AmSCROTException):
    pass


class StateException(AmSCROTException):
    pass


class ProviderTypeNotSupported(AmSCROTException):
    pass


class StitchPortNotFound(AmSCROTException):
    pass


class ProviderException(AmSCROTException):
    pass


class ControllerException(AmSCROTException):
    def __init__(self, exceptions):
        self.exceptions = exceptions

        self.message = f"Number Of Exceptions={len(exceptions)}:["

        for ex in exceptions:
            self.message += "\nmsg=" + ''.join(str(ex).splitlines())

        self.message += "\n]"
        super().__init__(self.message)
