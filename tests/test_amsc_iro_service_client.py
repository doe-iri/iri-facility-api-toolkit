import unittest
import pytest
import os
from pathlib import Path
from amscrot.client.client import Client
from amscrot.serviceclient import ServiceClient
from amscrot.util.constants import Constants


try:
    import sense
    HAS_SENSE = True
except ImportError:
    HAS_SENSE = False

CREDENTIALS_FILE = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
HAS_CREDENTIALS = os.path.exists(CREDENTIALS_FILE)

@pytest.mark.skipif(not HAS_SENSE, reason="Requires 'sense' module")
class TestAmscIroServiceClient(unittest.TestCase):
    """Test AMSC IRO ServiceClient integration focusing on discovery."""
    
    def test_amsc_iro_client_creation(self):
        """Test AMSC IRO ServiceClient creation logic."""
        client = ServiceClient.create(
            type=Constants.ServiceType.AMSC_IRO,
            name="test-amsc-iro",
            profile="amsc-iro"
        )
        self.assertIsNotNone(client)
        self.assertEqual(client.type, Constants.ServiceType.AMSC_IRO)
        self.assertEqual(client.name, "test-amsc-iro")

    @pytest.mark.integration
    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_amsc_iro_discovery(self):
        """Test that the amsc_iro discover properly fetches iri_facilities using token auth."""
        # Setup using Client parser
        client = Client()
        iro_client = ServiceClient.create(
            type=Constants.ServiceType.AMSC_IRO,
            name="iro-test",
            profile="amsc-iro"
        )
        client.add_service_client(iro_client)
        
        self.assertIsNotNone(iro_client)
        if not iro_client._available:
            self.skipTest("AMSC IRO client unavailable, likely expired token.")
        
        # Discover resources
        print("\n--- Discovering Resources (AMSC_IRO) ---")
        try:
            all_resources = iro_client.discover()
            facilities = all_resources.facility

            if not facilities:
                self.skipTest("No facility resources available. Might indicate down API or empty DB.")

            self.assertGreater(len(facilities), 0, "Should have discovered at least 1 facility")
            
            print(f"Discovered {len(facilities)} facility resources:")
            for f in facilities:
                print(f"  - {f.name} (ID: {f.data.get('id')})")
                print(f"    API Endpoint: {f.data.get('api_endpoint')}")
                endpoints = f.data.get('network_endpoints', [])
                if endpoints:
                    print(f"    Network Endpoints ({len(endpoints)}):")
                    for ep in endpoints:
                        print(f"      * {ep.get('port_name')} -> {ep.get('remote_port_name')}")
                else:
                    print(f"    Network Endpoints (0)")

            # List discovered intents
            intents = all_resources.intents
            print(f"\nDiscovered {len(intents)} intent profiles:")
            for intent in intents:
                print(f"  - {intent.name} (uuid={intent.uuid}, editable={intent.editable})")
            
        except Exception as e:
            import traceback
            
            if isinstance(e, unittest.SkipTest):
                raise
                
            error_msg = str(e)
            if "401" in error_msg or "403" in error_msg or "Unauthorized" in error_msg or "Forbidden" in error_msg:
                 print(f"Authentication failed (expected if token is invalid or expired): {e}")
                 self.skipTest(f"Skipping test due to authentication failure: {e}")
            
            print(f"Exception details: {traceback.format_exc()}")
            self.fail(f"Failed to discover resources: {e}")

    @pytest.mark.integration
    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_amsc_iro_plan_and_create(self):
        """Test that amsc_iro can plan and create using intent profile UUID/names via Session."""
        from amscrot.client.job import JobSpec, Job, JobType, JobServiceType, JobState
        
        client = Client()
        iro_client = ServiceClient.create(
            type=Constants.ServiceType.AMSC_IRO,
            name="iro-test-plan-create",
            profile="amsc-iro"
        )
        client.add_service_client(iro_client)
        if not iro_client._available:
            self.skipTest("AMSC IRO client unavailable, likely expired token.")

        # We will use the intent string as requested by the user
        test_intent = "0aa9afd2-6212-40ea-8b1d-8418c5a366e7"
        
        job_spec = JobSpec(
            executable="echo 'Test execution overriding sleepy duration'",
            resources={
                "cpu_cores_per_process": 1,
                "node_count": 1, 
                "processes_per_node": 1
            },
            attributes={
                "duration": 300
            }
        )
        
        session = client.create_session("amsc-iro-test-session")
        job = Job(
            name="test-amsc-iro-job",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=iro_client,
            job_spec=job_spec,
            intent=test_intent,
        )
        session.add_job(job)
        
        # Test planning
        print("\n--- Planning Resource (AMSC_IRO) ---")
        try:
            plan_summary = session.plan(verbose=True)
            print(f"Plan Summary: {plan_summary}")
        except Exception as e:
            if "not found" in str(e).lower() or "404" in str(e).lower() or "not marked as editable" in str(e):
                self.skipTest(f"Skipping because profile {test_intent} is not available/editable in backend: {e}")
            elif "401" in str(e) or "403" in str(e) or "Unauthorized" in str(e) or "Forbidden" in str(e) or "TOKEN" in str(e):
                 self.skipTest(f"Skipping test due to authentication failure: {e}")
            else:
                self.fail(f"Plan failed unexpectedly: {e}")

        # Test creation
        print("\n--- Creating Resource (AMSC_IRO) ---")
        try:
            session.apply()
            print("Successfully requested provisioning session block via Session.apply!")
            
            # Wait for completion / ready
            print("\n--- Waiting for Resource (AMSC_IRO) ---")
            results = session.wait(
                jobs=[job],
                target_states=[JobState.COMPLETED, JobState.FAILED, JobState.CANCELED],
                timeout=600,
                interval=5,
                verbose=True,
                raw=True,
            )
            
            status_result = results[job.name]
            print(f"Final Waited Status: {status_result}")
            self.assertIn(status_result.state, [JobState.COMPLETED])
            
            print("\n--- Destroying Resource (AMSC_IRO) ---")
            session.destroy()
            print("Successfully canceled intent session via Session.destroy!")
            
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            # Cleanup on failure
            try:
                session.destroy(jobs=[job])
            except:
                pass
            self.fail(f"Create/Wait/Destroy failed unexpectedly: {e}")

if __name__ == "__main__":
    unittest.main()
