
import unittest
import logging
from amscrot.client import Client
from amscrot.util import utils

class TestClientModule(unittest.TestCase):
    def setUp(self):
        logging.basicConfig(level=logging.INFO)
        self.session_name = "test_client_module_session"

    def test_client_lifecycle_dummy_provider(self):
        client = Client()

        # Add a dummy provider
        provider = client.add_provider(
            label="my_dummy_provider",
            type="dummy",
            config={} 
        )

        # Create Session
        session = client.create_session(self.session_name)

        # Add a dummy resource
        session.add_node(
            label="my_dummy_node",
            provider=provider,
            count=1,
            image="default_image",
            flavor="default_flavor"
        )

        # 1. Plan
        print("\n--- Running Plan ---")
        plan_result = session.plan()
        self.assertEqual(plan_result["resources"]["to_be_created"], 1)
        self.assertEqual(plan_result["resources"]["to_be_deleted"], 0)

        # 2. Apply
        print("\n--- Running Apply ---")
        result = session.apply()
        self.assertIsInstance(result, dict)
        self.assertIn("resources", result)
        self.assertIn("jobs", result)
        self.assertEqual(result["resources"]["pending"], 0)
        self.assertEqual(result["resources"]["failed"], 0)

        # 3. Show
        print("\n--- Running Show ---")
        session.show()

        # 4. Destroy
        print("\n--- Running Destroy ---")
        status = session.destroy()
        self.assertEqual(status, 0) # 0 means success in amscrot destroy

if __name__ == "__main__":
    unittest.main()
