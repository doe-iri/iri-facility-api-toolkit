import pytest
import unittest
import json
import logging
try:
    from amscrot.serviceclient.kube.kube_service_client import KubeServiceClient
    HAS_KUBE = True
except ImportError:
    KubeServiceClient = None
    HAS_KUBE = False
from amscrot.serviceclient.amsc_iri.iri_service_client import IriServiceClient
from amscrot.model.discovery import DiscoveryResult
from amscrot.util.constants import Constants

# Configure logging to show output during tests (if -s is used)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.integration
class TestServiceClientDiscovery(unittest.TestCase):
    """Test the discover method of ServiceClient implementations."""

    def test_kube_discover(self):
        """Test KubeServiceClient.discover().
        
        Skips if Kubernetes client is not available or connection fails.
        Dumps discovery JSON to stdout on success.
        """
        if not HAS_KUBE:
             self.skipTest("KubeServiceClient unavailable (kubernetes package not installed).")
        print("\n--- Testing KubeServiceClient.discover ---")
        client = KubeServiceClient(name="test-kube")
        
        if not client._available:
             self.skipTest("KubeServiceClient unavailable (no kubeconfig found or load failed).")

        try:
            discovery = client.discover()
            
            # Basic assertions
            self.assertIsInstance(discovery, DiscoveryResult)
            
            nodes = discovery.by_type('node')
            crds = discovery.by_type('crd')
            
            print(f"Discovery Summary:")
            print(f"  Total items: {len(discovery)}")
            print(f"  Nodes found: {len(nodes)}")
            print(f"  CRDs found: {len(crds)}")
            print(f"  Types: {discovery.summary()}")
            
            if not discovery:
                 self.skipTest("KubeServiceClient likely connected but returned no resources (empty cluster?).")

            # Dump complete JSON
            print("\n--- Discovery JSON Dump ---")
            print(json.dumps(discovery.to_list(), indent=2, default=str))
            print("--- End JSON Dump ---")
            
        except Exception as e:
            # Re-raise SkipTest so it's not treated as a failure
            if isinstance(e, unittest.SkipTest):
                raise

            # Check for connection errors and skip if appropriate
            error_msg = str(e)
            if "Max retries exceeded" in error_msg or "Connection refused" in error_msg: 
                 self.skipTest(f"Connection to Kubernetes cluster failed: {e}")
            else:
                 self.fail(f"KubeServiceClient discovery failed with unexpected error: {e}")

    def test_iri_discover(self):
        """Test IriServiceClient.discover()."""
        print("\n--- Testing IriServiceClient.discover ---")
        # Use a name that matches an entry in credentials.yml
        client = IriServiceClient(name="iri-west", profile="esnet-iri-west")
        try:
            discovery = client.discover()
            
            if not discovery:
                 print("IriServiceClient returned empty discovery. Check credentials if this is unexpected.")
                 return

            # Basic assertions for extended discovery
            self.assertIsInstance(discovery, DiscoveryResult)
            
            print(f"IRI Discovery Summary:")
            print(f"  Total items: {len(discovery)}")
            print(f"  Compute resources: {len(discovery.compute)}")
            print(f"  Facilities: {len(discovery.facility)}")
            print(f"  Capabilities: {len(discovery.capability)}")
            print(f"  Allocations: {len(discovery.allocation)}")
            print(f"  Types: {discovery.summary()}")

            if not (discovery.compute or discovery.facility or discovery.capability or discovery.allocation):
                 self.skipTest("IriServiceClient connected but found no resources of any type.")

            # Dump JSON for manual inspection
            print("\n--- IRI Discovery JSON Dump ---")
            print(json.dumps(discovery.to_list(), indent=2, default=str))
            print("--- End JSON Dump ---")

        except Exception as e:
             self.fail(f"IriServiceClient discovery failed: {e}")

if __name__ == '__main__':
    unittest.main()
