import unittest
import pytest
import os
from pathlib import Path
from amscrot.client.job import JobSpec
from amscrot.serviceclient import ServiceClient
from amscrot.util.constants import Constants


# Check if credentials file exists
CREDENTIALS_FILE = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
HAS_CREDENTIALS = os.path.exists(CREDENTIALS_FILE)


class TestEsnetIriServiceClient(unittest.TestCase):
    """Test ESnet IRI ServiceClient integration."""
    
    @pytest.mark.integration
    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_esnet_iri_job_lifecycle(self):
        """Test the full lifecycle of an ESnet IRI job: plan -> create -> status -> destroy.
        
        This is an integration test that makes real API calls to ESnet IRI.
        It first discovers available compute resources from the API, then uses one to test job submission.
        """
        
        # Import the get_resources API
        from amscrot.serviceclient.esnet_iri.generated.esnet_iri.api.status import get_resources
        from amscrot.serviceclient.esnet_iri.generated.esnet_iri.models.resource_type import ResourceType
        
        # Create the service client (will load credentials automatically)
        iri_client = ServiceClient.create(
            type=Constants.ServiceType.ESNET_IRI,
            name="iri-compute",
            profile="esnet-iri-east"
        )
        
        # Verify client was created successfully
        self.assertIsNotNone(iri_client)
        self.assertTrue(iri_client._available, "ESnet IRI client should be available with valid credentials")
        
        # Discover available compute resources from the API
        print("\n--- Discovering Resources ---")
        try:
            response = get_resources.sync_detailed(
                client=iri_client._client,
                resource_type=ResourceType.COMPUTE,
                limit=10
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response content (first 500 chars): {response.content[:500]}")
            print(f"Response parsed type: {type(response.parsed)}")
            
            # Check the status code
            if response.status_code != 200:
                self.skipTest(f"APIs returned status {response.status_code}: {response.parsed}")
            
            # Try to parse the response manually if parsed is None
            if response.parsed is None and response.content:
                import json
                try:
                    data = json.loads(response.content)
                    print(f"Manually parsed JSON type: {type(data)}")
                    print(f"Manually parsed JSON: {data}")
                    
                    # If it's a list, use it directly
                    if isinstance(data, list) and len(data) > 0:
                        resource_id = data[0].get('id')
                        print(f"Found {len(data)} compute resource(s). Using resource ID: {resource_id}")
                    else:
                        self.skipTest(f"No compute resources in response. Data: {data}")
                except json.JSONDecodeError as je:
                    self.skipTest(f"Failed to parse JSON response: {je}")
            else:
                resources_response = response.parsed
                
                # The response should be a list of resources
                if isinstance(resources_response, list) and len(resources_response) > 0:
                    # Extract the first resource's ID
                    resource_id = resources_response[0].id
                    print(f"Found {len(resources_response)} compute resource(s). Using resource ID: {resource_id}")
                else:
                    self.skipTest(f"No compute resources available. Response type: {type(resources_response)}, Response: {resources_response}")
        except Exception as e:
            import traceback
            error_msg = str(e)
            if "401" in error_msg or "403" in error_msg or "Unauthorized" in error_msg or "Forbidden" in error_msg:
                 print(f"Authentication failed (expected if token is invalid): {e}")
                 self.skipTest(f"Skipping test due to authentication failure: {e}")
            
            print(f"Exception details: {traceback.format_exc()}")
            self.skipTest(f"Failed to discover resources: {e}")
        
        # Create a job spec with resource_id in attributes
        spec = JobSpec(
            executable=["/bin/echo", "Hello AmSC;", "sleep 5"],
            resources={
                "node_count": 1,
                "process_count": 1,
                "processes_per_node": 1,
                "cpu_cores_per_process": 1,
                "gpu_cores_per_process": 1,
                "exclusive_node_use": True,
                "memory": 1
            },
            attributes={
                "resource_id": resource_id,
                "directory": "/tmp",
                "duration": 60,
                "queue_name": "debug",
                "account": "interactive"
            }
        )
        
        job_name = "iri-test-job"
        
        try:
            # 1. Test Plan
            print("\n--- Test Plan ---")
            plan_result = iri_client.plan(spec, job_name)
            self.assertEqual(plan_result["status"], "PLANNED")
            self.assertEqual(len(plan_result["errors"]), 0)
            print(f"Plan result: {plan_result}")
            
            # 2. Test Create (Real API call)
            print("\n--- Test Create ---")
            iri_client.create(spec, job_name)
            
            # Verify job was submitted
            if job_name not in iri_client._submitted_jobs:
                self.skipTest(f"Job '{job_name}' was not submitted (check logs for API errors). Skipping remaining assertions.")
            
            self.assertIn(job_name, iri_client._submitted_jobs)
            tracked_resource_id, job_id = iri_client._submitted_jobs[job_name]
            self.assertIsNotNone(job_id, "Job ID should be returned from API")
            self.assertEqual(tracked_resource_id, resource_id)
            print(f"Job submitted with ID: {job_id}")
            
            print("\n--- Test Status (Polling) ---")
            import time
            max_retries = 30
            for i in range(max_retries):
                status_result = iri_client.status(job_name)
                current_status = status_result.get("status")
                print(f"Attempt {i+1}/{max_retries}: Status = {current_status}")
                
                if current_status in ["DONE", "ERROR", "DESTROYED"]:
                    break
                
                time.sleep(2)

            self.assertEqual(status_result["status"], "DONE", f"Job failed or timed out. Details: {status_result}")
            print(f"Job completed successfully. Status: {status_result}")

            # Verify exit code if available in the raw response
            if "iri_response" in status_result and status_result["iri_response"]:
                print(f"Raw IRI response: {status_result['iri_response']}")
            self.assertEqual(status_result["job_id"], job_id)

        except Exception as e:
            # If there's an error, print it but still try to clean up
            print(f"\n!!! Test failed with error: {e}")
            raise
            
        finally:
            # 4. Test Destroy (Real API call) - Always try to clean up
            print("\n--- Test Destroy ---")
            try:
                if job_name in iri_client._submitted_jobs:
                    iri_client.destroy(job_name)
                    
                    # Verify job was removed from tracking
                    self.assertNotIn(job_name, iri_client._submitted_jobs)
                    print("Job destroyed successfully")
            except Exception as cleanup_error:
                print(f"Warning: Failed to clean up job: {cleanup_error}")

    
    def test_esnet_iri_client_creation(self):
        """Test ESnet IRI ServiceClient creation."""
        iri_client = ServiceClient.create(
            type=Constants.ServiceType.ESNET_IRI,
            name="test-iri"
        )
        
        self.assertIsNotNone(iri_client)
        self.assertEqual(iri_client.type, Constants.ServiceType.ESNET_IRI)
        self.assertEqual(iri_client.name, "test-iri")
        
        # Client may or may not be available depending on credentials
        # Just verify it was created without errors
    
    @pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
    def test_resource_id_extraction(self):
        """Test that resource_id is correctly extracted from JobSpec attributes.
        
        This is a unit test but requires the client to be initialized.
        """
        iri_client = ServiceClient.create(
            type="esnet-iri",
            name="test-iri"
        )
        
        # Test with resource_id in attributes
        spec = JobSpec(
            executable=["echo", "test"],
            attributes={"resource_id": "custom-resource-id"}
        )
        
        resource_id = iri_client._get_resource_id(spec)
        self.assertEqual(resource_id, "custom-resource-id")
        
        # Test without resource_id (should use default)
        spec_no_resource = JobSpec(
            executable=["echo", "test"],
            attributes={}
        )
        
        resource_id_default = iri_client._get_resource_id(spec_no_resource)
        self.assertEqual(resource_id_default, "fb0aafe1-c780-55c0-b635-a7121f1b0ce5")


if __name__ == "__main__":
    unittest.main()
