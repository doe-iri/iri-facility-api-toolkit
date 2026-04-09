import unittest
import json
import logging
from amscrot.serviceclient.kube.kube_service_client import KubeServiceClient
from amscrot.serviceclient.amsc_iri.iri_service_client import IriServiceClient
from amscrot.model.discovery import DiscoveryResult
from amscrot.model.metadata import Facility, ResourceBase

# Configure logging to show output during tests (if -s is used)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestServiceClientDiscoverNormalized(unittest.TestCase):
    """Test discover(native=False) for all ServiceClient implementations.

    Verifies that normalized discovery returns typed Facility objects with
    id, name, description and properly nested resource metadata.
    """

    def test_kube_discover_normalized(self):
        """KubeServiceClient.discover(native=False) returns a Facility with Compute list."""
        print("\n--- Testing KubeServiceClient.discover(native=False) ---")
        client = KubeServiceClient(name="test-kube")

        if not client._available:
            self.skipTest("Skipping test - no kubeconfig found")

        try:
            result = client.discover(native=False)

            self.assertIsInstance(result, DiscoveryResult)

            # Always returns exactly one facility item keyed to the client name
            facility_items = result.by_type("facility")
            self.assertEqual(len(facility_items), 1, "Expected exactly one facility item")

            item = facility_items[0]
            self.assertEqual(item.name, "test-kube")

            # .metadata must be a Facility
            self.assertIsNotNone(item.metadata)
            self.assertIsInstance(item.metadata, Facility)

            fac = item.metadata
            self.assertEqual(fac.name, "test-kube")

            # .facilities convenience accessor
            facilities = result.facilities
            self.assertEqual(len(facilities), 1)
            self.assertIsInstance(facilities[0], Facility)

            print(f"Facility name: {fac.name}")
            print(f"Compute nodes: {len(fac.compute or [])}")

            if fac.compute:
                for c in fac.compute:
                    self.assertIsInstance(c, ResourceBase)
                    print(f"  Node: name={c.name} cores={c.cores} "
                          f"memory={c.memory} arch={c.architecture}")
            else:
                print("  (no nodes reachable -- cluster unavailable)")

        except unittest.SkipTest:
            raise
        except Exception as e:
            error_msg = str(e)
            if "Max retries exceeded" in error_msg or "Connection refused" in error_msg or "unreachable" in error_msg.lower():
                self.skipTest(f"Kubernetes cluster unreachable: {e}")
            self.fail(f"KubeServiceClient normalized discovery failed: {e}")

    def test_iri_discover_normalized(self):
        """IriServiceClient.discover(native=False) returns typed Facility objects."""
        print("\n--- Testing IriServiceClient.discover(native=False) ---")
        client = IriServiceClient(name="iri-east", profile="esnet-iri-east")

        try:
            result = client.discover(native=False)

            self.assertIsInstance(result, DiscoveryResult)

            if not result:
                print("Empty result -- check credentials.")
                return

            print(f"Normalized Discovery Summary:")
            print(f"  Total facility items: {len(result.by_type('facility'))}")

            facilities = result.facilities
            print(f"  Typed Facility objects: {len(facilities)}")

            # Every item must be type=facility and carry a typed Facility in .metadata
            for item in result.by_type("facility"):
                self.assertEqual(item.type, "facility")
                self.assertIsNotNone(item.metadata,
                    f"Item '{item.name}' missing .metadata")
                self.assertIsInstance(item.metadata, Facility,
                    f"Item '{item.name}' .metadata is not a Facility")

            for fac in facilities:
                self.assertIsInstance(fac, Facility)
                self.assertIsInstance(fac, ResourceBase)
                self.assertIsNotNone(fac.name, "Facility.name must not be None")

                print(f"\n  Facility: id={fac.id!r} name={fac.name!r}")

                # Compute entries
                for c in fac.compute or []:
                    self.assertIsInstance(c, ResourceBase)
                    print(f"    Compute: id={c.id!r} name={c.name!r} "
                          f"cores={c.cores} memory={c.memory}")

                # Allocation entries
                for a in fac.allocations or []:
                    self.assertIsInstance(a, ResourceBase)
                    print(f"    Allocation: id={a.id!r} account={a.account!r}")

            # Hierarchical dump: named facilities first, "default" bucket last
            print("\n--- Hierarchical Facility Dump ---")
            print(json.dumps(result.to_hierarchical(), indent=2, default=str))
            print("--- End Dump ---")

        except unittest.SkipTest:
            raise
        except Exception as e:
            self.fail(f"IriServiceClient normalized discovery failed: {e}")


if __name__ == '__main__':
    unittest.main()
