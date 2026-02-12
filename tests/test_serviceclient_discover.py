import unittest
import json
import logging
from amscrot.serviceclient.kube.kube_service_client import KubeServiceClient
from amscrot.serviceclient.esnet_iri.esnet_iri_service_client import EsnetIriServiceClient
from amscrot.serviceclient.iri.iri_service_client import IriServiceClient
from amscrot.util.constants import Constants

# Configure logging to show output during tests (if -s is used)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestServiceClientDiscovery(unittest.TestCase):
    """Test the discover method of ServiceClient implementations."""

    def test_kube_discover(self):
        """Test KubeServiceClient.discover().
        
        Skips if Kubernetes client is not available or connection fails.
        Dumps discovery JSON to stdout on success.
        """
        print("\n--- Testing KubeServiceClient.discover ---")
        client = KubeServiceClient(name="test-kube")
        
        if not client._available:
             self.skipTest("KubeServiceClient unavailable (no kubeconfig found or load failed).")

        try:
            discovery = client.discover()
            
            # Basic assertions
            self.assertIsInstance(discovery, list)
            
            nodes = [item for item in discovery if item.get('type') == 'node']
            crds = [item for item in discovery if item.get('type') == 'crd']
            
            print(f"Discovery Summary:")
            print(f"  Total items: {len(discovery)}")
            print(f"  Nodes found: {len(nodes)}")
            print(f"  CRDs found: {len(crds)}")
            
            if not discovery:
                 self.skipTest("KubeServiceClient likely connected but returned no resources (empty cluster?).")

            # Dump complete JSON
            print("\n--- Discovery JSON Dump ---")
            print(json.dumps(discovery, indent=2, default=str)) # default=str handles non-serializable objects if any
            print("--- End JSON Dump ---")
            
        except Exception as e:
            # Check for connection errors and skip if appropriate
            error_msg = str(e)
            if "Max retries exceeded" in error_msg or "Connection refused" in error_msg: 
                 self.skipTest(f"Connection to Kubernetes cluster failed: {e}")
            else:
                 self.fail(f"KubeServiceClient discovery failed with unexpected error: {e}")

    def test_esnet_iri_discover(self):
        """Test EsnetIriServiceClient.discover()."""
        print("\n--- Testing EsnetIriServiceClient.discover ---")
        # Use a name that matches an entry in credentials.yml
        client = EsnetIriServiceClient(name="esnet-iri-west", profile="esnet-iri-west")
        # Discovery is a stub, so it should always succeed returned empty list
        try:
            discovery = client.discover()
            
            # If no credentials, it returns empty list (which is valid behavior for client itself, 
            # though locally we expect credentials to be present now).
            if not discovery:
                 print("EsnetIriServiceClient returned empty discovery. Check credentials if this is unexpected.")
                 return

            # Basic assertions for extended discovery
            self.assertIsInstance(discovery, list)
            
            compute = [item for item in discovery if item.get('type') == 'compute']
            facilities = [item for item in discovery if item.get('type') == 'facility']
            capabilities = [item for item in discovery if item.get('type') == 'capability']
            allocations = [item for item in discovery if item.get('type') == 'allocation']
            
            print(f"Esnet IRI Discovery Summary:")
            print(f"  Total items: {len(discovery)}")
            print(f"  Compute resources: {len(compute)}")
            print(f"  Facilities: {len(facilities)}")
            print(f"  Capabilities: {len(capabilities)}")
            print(f"  Allocations: {len(allocations)}")

            # We expect at least some of these if connected to a real environment
            if not (compute or facilities or capabilities or allocations):
                 self.skipTest("EsnetIriServiceClient connected but found no resources of any type.")

            # Dump JSON for manual inspection
            print("\n--- Esnet IRI Discovery JSON Dump ---")
            print(json.dumps(discovery, indent=2, default=str))
            print("--- End JSON Dump ---")

        except Exception as e:
            # Handle potential credential load errors if they propagate
             self.fail(f"EsnetIriServiceClient discovery failed: {e}")

    def test_iri_discover(self):
        """Test IriServiceClient.discover()."""
        print("\n--- Testing IriServiceClient.discover ---")
        client = IriServiceClient(name="test-iri")
        # Discovery is a stub
        discovery = client.discover()
        self.assertEqual(discovery, [], "IriServiceClient.discover should return empty list")

if __name__ == '__main__':
    unittest.main()
