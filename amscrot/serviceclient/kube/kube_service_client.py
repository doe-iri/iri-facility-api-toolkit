from ..serviceclient import ServiceClient

class KubeServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type="kube", **kwargs)

    def run(self):
        print(f"[{self.name}] Running Kube service...")

    def stop(self):
        print(f"[{self.name}] Stopping Kube service...")

    def status(self) -> str:
        return self.status
