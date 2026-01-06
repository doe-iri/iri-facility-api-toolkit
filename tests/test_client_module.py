
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
        client.add_provider(
            label="my_dummy_provider",
            type="dummy",
            config={} 
        )

        # Add a dummy resource
        client.add_resource(
            label="my_dummy_node",
            type="node",
            provider="{{ dummy.my_dummy_provider }}",
            count=1,
            image="default_image",
            flavor="default_flavor"
        )

        # 1. Plan
        print("\n--- Running Plan ---")
        created, deleted = client.plan(session=self.session_name)
        self.assertEqual(created, 1)
        self.assertEqual(deleted, 0)

        # 2. Apply
        print("\n--- Running Apply ---")
        status = client.apply(session=self.session_name)
        self.assertEqual(status, 0) # 0 means success in amscrot apply

        # 3. Show
        print("\n--- Running Show ---")
        client.show(session=self.session_name)

        # 4. Destroy
        print("\n--- Running Destroy ---")
        status = client.destroy(session=self.session_name)
        self.assertEqual(status, 0) # 0 means success in amscrot destroy

if __name__ == "__main__":
    unittest.main()
