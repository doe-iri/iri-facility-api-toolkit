from ..serviceclient import ServiceClient

class IriServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type="iri", **kwargs)

    def run(self):
        print(f"[{self.name}] Running IRI service...")

    def stop(self):
        print(f"[{self.name}] Stopping IRI service...")

    def status(self) -> str:
        return self.status
