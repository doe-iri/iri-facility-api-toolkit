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
from amscrot.model.metadata import (
    Facility, ResourceBase, Project, ProjectAllocation, UserAllocation, AllocationEntry,
)

# Configure logging to show output during tests (if -s is used)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.mark.integration
class TestServiceClientDiscoverNormalized(unittest.TestCase):
    """Test discover(native=False) for all ServiceClient implementations.

    Verifies that normalized discovery returns typed Facility objects with
    id, name, description and properly nested resource metadata.
    """

    def test_kube_discover_normalized(self):
        """KubeServiceClient.discover(native=False) returns a Facility with Compute list."""
        if not HAS_KUBE:
             self.skipTest("KubeServiceClient unavailable (kubernetes package not installed).")
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
        client = IriServiceClient(name="alcf", profile="alcf-iri")

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

                # Allocation entries (backward compat flat list)
                for a in fac.allocations or []:
                    self.assertIsInstance(a, ResourceBase)
                    print(f"    Allocation: id={a.id!r} account={a.account!r}")

                # ---- Project hierarchy ----
                print(f"\n  --- Projects ({len(fac.projects or [])}) ---")
                self.assertIsNotNone(fac.projects, "Facility.projects should be populated")
                self.assertGreater(len(fac.projects), 0, "Expected at least one project")

                for proj in fac.projects:
                    self.assertIsInstance(proj, Project)
                    self.assertIsNotNone(proj.id, "Project.id must not be None")
                    self.assertIsNotNone(proj.name, "Project.name must not be None")

                    print(f"    Project: id={proj.id!r} name={proj.name!r} "
                          f"desc={proj.description!r} users={proj.user_ids}")

                    self.assertIsNotNone(proj.allocations,
                        f"Project '{proj.name}' should have allocations")

                    for pa in proj.allocations:
                        self.assertIsInstance(pa, ProjectAllocation)
                        self.assertIsNotNone(pa.capability,
                            f"ProjectAllocation {pa.id} should have a capability")
                        self.assertIsNotNone(pa.entries,
                            f"ProjectAllocation {pa.id} should have entries")

                        print(f"      ProjectAllocation: id={pa.id!r} "
                              f"capability={pa.capability!r}")
                        for e in (pa.entries or []):
                            self.assertIsInstance(e, AllocationEntry)
                            print(f"        Entry: alloc={e.allocation} "
                                  f"usage={e.usage} unit={e.unit}")

                        # User allocations
                        for ua in (pa.user_allocations or []):
                            self.assertIsInstance(ua, UserAllocation)
                            print(f"        UserAlloc: id={ua.id!r} "
                                  f"user={ua.user_id!r}")
                            for ue in (ua.entries or []):
                                self.assertIsInstance(ue, AllocationEntry)
                                print(f"          Entry: alloc={ue.allocation} "
                                      f"usage={ue.usage} unit={ue.unit}")

                # ---- Convenience method: get_project ----
                first_proj_name = fac.projects[0].name
                looked_up = fac.get_project(first_proj_name)
                self.assertIsNotNone(looked_up,
                    f"get_project('{first_proj_name}') should find the project")
                self.assertEqual(looked_up.name, first_proj_name)
                print(f"\n  get_project('{first_proj_name}'): found [OK]")

                # Case-insensitive lookup
                looked_up_ci = fac.get_project(first_proj_name.upper())
                self.assertIsNotNone(looked_up_ci,
                    "get_project should be case-insensitive")
                print(f"  get_project('{first_proj_name.upper()}'): found (case-insensitive) [OK]")

                # ---- Convenience method: get_user_allocations ----
                proj = fac.projects[0]
                all_user_allocs = proj.get_user_allocations()
                print(f"\n  {proj.name}.get_user_allocations() -> {len(all_user_allocs)} items")
                for ua_summary in all_user_allocs:
                    print(f"    cap={ua_summary['capability']} "
                          f"user={ua_summary['user_id']} "
                          f"entries={ua_summary['entries']}")

            # ---- Convenience method: resources_for_project (all projects) ----
            print("\n--- resources_for_project() (all projects, project-level) ---")
            all_resources = result.resources_for_project()
            self.assertIsInstance(all_resources, dict)
            self.assertGreater(len(all_resources), 0,
                "resources_for_project() should return at least one project")
            print(json.dumps(all_resources, indent=2, default=str))

            # ---- resources_for_project with specific project ----
            first_proj_name = list(all_resources.keys())[0]
            print(f"\n--- resources_for_project('{first_proj_name}') ---")
            single_project = result.resources_for_project(first_proj_name)
            self.assertIn(first_proj_name, single_project)
            print(json.dumps(single_project, indent=2, default=str))

            # ---- projects_typed accessor ----
            typed_projects = result.projects_typed
            self.assertGreater(len(typed_projects), 0,
                "projects_typed should return Project objects")
            for p in typed_projects:
                self.assertIsInstance(p, Project)
            print(f"\n  result.projects_typed: {len(typed_projects)} projects [OK]")

            # ---- Capability linkage: resources have capabilities populated ----
            fac = facilities[0]
            print("\n--- Resource Capabilities ---")
            for c in fac.compute or []:
                print(f"  Compute '{c.name}' (group={c.group}): "
                      f"capabilities={c.capabilities}")
            for s in fac.storage or []:
                print(f"  Storage '{s.name}': capabilities={s.capabilities}")

            # At least one compute resource should have capabilities
            compute_with_caps = [c for c in (fac.compute or [])
                                 if c.capabilities]
            self.assertGreater(len(compute_with_caps), 0,
                "At least one compute resource should have capabilities")

            # ---- Facility.resources_for_project ----
            print("\n--- Facility.resources_for_project() (all projects) ---")
            proj_resources = fac.resources_for_project()
            for proj_name, cap_map in proj_resources.items():
                print(f"  Project '{proj_name}':")
                for cap, res_map in cap_map.items():
                    parts = [f"{cat}={[r.name for r in rs]}"
                             for cat, rs in res_map.items()]
                    print(f"    {cap}: {', '.join(parts)}")
            self.assertGreater(len(proj_resources), 0,
                "resources_for_project() should return at least one project")

            first_proj_name = list(proj_resources.keys())[0]
            print(f"\n--- Facility.resources_for_project('{first_proj_name}') ---")
            single = fac.resources_for_project(first_proj_name)
            for proj_name, cap_map in single.items():
                print(f"  Project '{proj_name}':")
                for cap, res_map in cap_map.items():
                    parts = [f"{cat}={[r.name for r in rs]}"
                             for cat, rs in res_map.items()]
                    print(f"    {cap}: {', '.join(parts)}")
            self.assertIn(first_proj_name, single)

            # Hierarchical dump
            print("\n--- Hierarchical Facility Dump ---")
            print(json.dumps(result.to_hierarchical(), indent=2, default=str))
            print("--- End Dump ---")

        except unittest.SkipTest:
            raise
        except Exception as e:
            self.fail(f"IriServiceClient normalized discovery failed: {e}")


    def test_client_shorthand_lookup(self):
        """Client.get_shorthand resolves facility names to user-friendly shorthands."""
        from amscrot.client.client import Client
        from unittest.mock import MagicMock

        self.assertEqual(Client.get_shorthand("National Energy Research Scientific Computing Center"), "nersc")
        self.assertEqual(Client.get_shorthand("ESnet Facility East"), "esnet-east")
        self.assertEqual(Client.get_shorthand("ESnet Facility West"), "esnet-west")
        self.assertEqual(Client.get_shorthand("Argonne Leadership Computing Facility"), "alcf")
        self.assertEqual(Client.get_shorthand("Oak Ridge Leadership Computing Facility"), "olcf")
        self.assertEqual(Client.get_shorthand("AmSC IRO Orchestrator"), "amsc-iro")

        # Test fallback/heuristics
        self.assertEqual(Client.get_shorthand("random-nersc-endpoint"), "nersc")
        self.assertEqual(Client.get_shorthand("some-unmatched-facility"), "some-unmatched-facility")

        # Test get_service_client with shorthand
        c = Client()
        dummy_sc = MagicMock()
        dummy_sc.name = "national-energy-research-scientific-computing-center"
        dummy_sc.type = "iri"
        c.add_service_client(dummy_sc)

        # Retrieve via direct match
        self.assertEqual(c.get_service_client("national-energy-research-scientific-computing-center"), dummy_sc)
        # Retrieve via shorthand
        self.assertEqual(c.get_service_client("nersc"), dummy_sc)
        # Retrieve via substring
        self.assertEqual(c.get_service_client("scientific"), dummy_sc)


if __name__ == '__main__':
    unittest.main()

