"""Tests for the IRI ApiClient path-rewriting shim.

Validates that ``make_path_rewriting_client`` correctly rewrites (or
passes through) the ``/api`` prefix in generated resource paths.
"""

from unittest.mock import MagicMock, call

import pytest

from amscrot.serviceclient.amsc_iri._path_rewriting import (
    GENERATED_PREFIX,
    make_path_rewriting_client,
)


# ---------------------------------------------------------------------------
# Fake ApiClient for unit tests
# ---------------------------------------------------------------------------

class _FakeApiClient:
    """Minimal stand-in for a generated ``ApiClient``."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.default_headers = {}
        self._calls = []

    def param_serialize(
        self,
        method,
        resource_path,
        path_params=None,
        query_params=None,
        header_params=None,
        body=None,
        post_params=None,
        files=None,
        auth_settings=None,
        collection_formats=None,
        _host=None,
        _request_auth=None,
    ):
        """Record the call so tests can inspect the final resource_path."""
        self._calls.append({
            "method": method,
            "resource_path": resource_path,
        })
        return (method, resource_path, {}, None, None)


class TestPathRewritingShim:
    """Tests for ``make_path_rewriting_client``."""

    def test_standard_prefix_returns_plain_client(self):
        """Default path_prefix='/api' should skip the shim entirely."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix=GENERATED_PREFIX,
        )
        assert type(client) is _FakeApiClient

    def test_bare_prefix_returns_subclass(self):
        """Empty path_prefix should create a rewriting subclass."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="",
        )
        assert type(client) is not _FakeApiClient
        assert isinstance(client, _FakeApiClient)

    def test_bare_prefix_rewrites_api_path(self):
        """resource_path='/api/v1/facility' -> '/v1/facility' with prefix=''."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="",
        )
        client.param_serialize("GET", "/api/v1/facility")
        assert len(client._calls) == 1
        assert client._calls[0]["resource_path"] == "/v1/facility"

    def test_bare_prefix_rewrites_v2_path(self):
        """resource_path='/api/v2/compute/resources' -> '/v2/compute/resources'."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="",
        )
        client.param_serialize("GET", "/api/v2/compute/resources")
        assert client._calls[0]["resource_path"] == "/v2/compute/resources"

    def test_bare_prefix_preserves_non_api_paths(self):
        """Paths not starting with /api should pass through unchanged."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="",
        )
        client.param_serialize("GET", "/health")
        assert client._calls[0]["resource_path"] == "/health"

    def test_standard_prefix_does_not_rewrite(self):
        """Default prefix should pass resource_path through unchanged."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="/api",
        )
        client.param_serialize("GET", "/api/v1/facility")
        assert client._calls[0]["resource_path"] == "/api/v1/facility"

    def test_custom_prefix_rewrites(self):
        """A custom prefix like '/custom' should replace '/api'."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="/custom",
        )
        client.param_serialize("GET", "/api/v1/facility")
        assert client._calls[0]["resource_path"] == "/custom/v1/facility"

    def test_configuration_is_stored(self):
        """The shim should pass configuration to the parent __init__."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="",
        )
        assert client.configuration is config

    def test_default_headers_accessible(self):
        """The shim instance should have default_headers dict."""
        config = MagicMock()
        client = make_path_rewriting_client(
            _FakeApiClient, config, path_prefix="",
        )
        client.default_headers["Authorization"] = "Bearer test"
        assert client.default_headers["Authorization"] == "Bearer test"


class TestIriServiceClientPathPrefix:
    """Test that IriServiceClientBase picks up path_prefix from credentials."""

    def test_path_prefix_from_credential_dict(self):
        """path_prefix in credential dict should be stored on the client."""
        from amscrot.serviceclient.amsc_iri.iri_service_client import (
            IriServiceClientBase,
        )

        # We cannot instantiate the abstract base directly, so test the
        # property contract via a mock that has _path_prefix set.
        class _TestClient(IriServiceClientBase):
            API_VERSION = 1

            def _init_api_client(self):
                pass

            def _resource_type(self, kind):
                return kind

            def _create_filesystem(self):
                return None

        client = _TestClient(
            name="test-bare",
            credential={
                "api_key": "tok",
                "api_endpoint": "https://example.com",
                "path_prefix": "",
            },
        )
        assert client.path_prefix == ""

    def test_path_prefix_defaults_to_api(self):
        """Without path_prefix in credentials, default to '/api'."""
        from amscrot.serviceclient.amsc_iri.iri_service_client import (
            IriServiceClientBase,
        )

        class _TestClient(IriServiceClientBase):
            API_VERSION = 1

            def _init_api_client(self):
                pass

            def _resource_type(self, kind):
                return kind

            def _create_filesystem(self):
                return None

        client = _TestClient(
            name="test-standard",
            credential={
                "api_key": "tok",
                "api_endpoint": "https://example.com",
            },
        )
        assert client.path_prefix == "/api"
