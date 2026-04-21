"""Unit tests for Client.facility() method."""
import pytest
from unittest.mock import MagicMock, patch
from amscrot.client import Client
from amscrot.facility.client import FacilityClient

ENDPOINT = "https://iri-dev.ppg.es.net"
TOKEN = "test-token"


class TestClientFacilityMethod:
    def test_facility_returns_facility_client(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            result = client.facility(ENDPOINT, token=TOKEN)
        assert isinstance(result, FacilityClient)

    def test_facility_passes_endpoint(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token=TOKEN)
        assert fc._endpoint == ENDPOINT

    def test_facility_passes_static_token(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token=TOKEN)
        assert fc._static_token == TOKEN

    def test_facility_passes_token_provider(self):
        provider = lambda: "dynamic-token"
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token_provider=provider)
        assert fc._token_provider is provider

    def test_facility_passes_name(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc = client.facility(ENDPOINT, token=TOKEN, name="ESnet East")
        assert fc._name == "ESnet East"

    def test_facility_each_call_returns_new_instance(self):
        with patch("amscrot.facility.client.ServiceClient") as MockSC, \
             patch("amscrot.facility.client.Session"):
            MockSC.create.return_value = MagicMock()
            client = Client()
            fc1 = client.facility(ENDPOINT, token=TOKEN)
            fc2 = client.facility(ENDPOINT, token=TOKEN)
        assert fc1 is not fc2


class TestFacilityPublicExports:
    def test_facility_client_importable_from_package(self):
        from amscrot.facility import FacilityClient
        assert FacilityClient is not None

    def test_resource_importable_from_package(self):
        from amscrot.facility import Resource
        assert Resource is not None

    def test_job_importable_from_package(self):
        from amscrot.facility import Job
        assert Job is not None

    def test_task_importable_from_package(self):
        from amscrot.facility import Task
        assert Task is not None

    def test_filesystem_client_importable_from_package(self):
        from amscrot.facility import FilesystemClient
        assert FilesystemClient is not None
