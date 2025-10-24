from amscrot.exceptions import AmSCROTException


class CloudlabException(AmSCROTException):
    """Cloudlab exception"""
    def __init__(self, *, message=None, exitval=None, response=None):
        self.message = ''

        if exitval:
            self.message = f"exitval={exitval}"

        if message:
            self.message = f"message={message},{self.message}"

        if response:
            self.message = f"{self.message},code={response.code},output={response.output}"

        self.message = f"[{self.message}]"
        super().__init__(self.message)
