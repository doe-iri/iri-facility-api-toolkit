"""Tests for IRI multi-version API support.

Tests version probing, caching, factory dispatch, and versioned client
behavior.
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# VersionProber tests
# ---------------------------------------------------------------------------

class TestVersionProber:
    """Tests for the VersionProber class."""

    def test_probe_returns_highest_version(self):
        """Probing should return the highest version that responds HTTP 200."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        prober = VersionProber()

        # Mock urllib3 to simulate v2: 200, v1: 200
        mock_response_200 = MagicMock()
        mock_response_200.status = 200

        mock_http = MagicMock()
        mock_http.request.return_value = mock_response_200

        with patch("urllib3.PoolManager", return_value=mock_http):
            with patch("urllib3.disable_warnings"):
                version = prober._probe("https://example.com")

        assert version == 2  # highest first
        # Should have been called for v2 first (and stopped there)
        assert mock_http.request.call_count == 1
        call_url = mock_http.request.call_args[0][1]
        assert "/api/v2/" in call_url

    def test_probe_falls_back_to_v1(self):
        """If v2 returns 404, probing should fall back to v1."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        prober = VersionProber()

        mock_404 = MagicMock()
        mock_404.status = 404
        mock_200 = MagicMock()
        mock_200.status = 200

        mock_http = MagicMock()
        mock_http.request.side_effect = [mock_404, mock_200]

        with patch("urllib3.PoolManager", return_value=mock_http):
            with patch("urllib3.disable_warnings"):
                version = prober._probe("https://example.com")

        assert version == 1
        assert mock_http.request.call_count == 2

    def test_probe_all_fail_returns_lowest(self):
        """If all probes fail, should return the lowest version."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        prober = VersionProber()

        mock_http = MagicMock()
        mock_http.request.side_effect = Exception("connection refused")

        with patch("urllib3.PoolManager", return_value=mock_http):
            with patch("urllib3.disable_warnings"):
                version = prober._probe("https://example.com")

        assert version == 1  # lowest fallback

    def test_probe_with_api_key(self):
        """Probing should include Authorization header when api_key is given."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        prober = VersionProber()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_http = MagicMock()
        mock_http.request.return_value = mock_response

        with patch("urllib3.PoolManager", return_value=mock_http):
            with patch("urllib3.disable_warnings"):
                prober._probe("https://example.com", api_key="test-token")

        call_kwargs = mock_http.request.call_args
        headers = call_kwargs[1].get("headers") or call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer test-token"

    def test_cache_write_and_read(self):
        """Cache should persist and be readable on next access."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_cache.json"

            with patch(
                "amscrot.serviceclient.amsc_iri.version_prober._cache_path",
                return_value=cache_file,
            ):
                prober = VersionProber(ttl_seconds=3600)

                # Write to cache
                prober._set_cached("https://example.com", 2)
                assert cache_file.exists()

                # Read from cache (fresh instance to clear in-memory state)
                prober2 = VersionProber(ttl_seconds=3600)
                cached = prober2._get_cached("https://example.com")
                assert cached == 2

    def test_cache_expiry(self):
        """Expired cache entries should return None."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_cache.json"

            with patch(
                "amscrot.serviceclient.amsc_iri.version_prober._cache_path",
                return_value=cache_file,
            ):
                # Use a very short TTL
                prober = VersionProber(ttl_seconds=1)
                prober._set_cached("https://example.com", 2)

                # Wait for expiry
                time.sleep(1.5)

                prober2 = VersionProber(ttl_seconds=1)
                cached = prober2._get_cached("https://example.com")
                assert cached is None

    def test_clear_cache_single(self):
        """clear_cache(url) should remove only that entry."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_cache.json"

            with patch(
                "amscrot.serviceclient.amsc_iri.version_prober._cache_path",
                return_value=cache_file,
            ):
                prober = VersionProber()
                prober._set_cached("https://a.com", 1)
                prober._set_cached("https://b.com", 2)

                prober.clear_cache("https://a.com")

                assert prober._get_cached("https://a.com") is None
                assert prober._get_cached("https://b.com") == 2

    def test_clear_cache_all(self):
        """clear_cache() with no args should remove all entries."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_cache.json"

            with patch(
                "amscrot.serviceclient.amsc_iri.version_prober._cache_path",
                return_value=cache_file,
            ):
                prober = VersionProber()
                prober._set_cached("https://a.com", 1)
                prober._set_cached("https://b.com", 2)

                prober.clear_cache()

                assert prober._get_cached("https://a.com") is None
                assert prober._get_cached("https://b.com") is None

    def test_detect_version_uses_cache(self):
        """detect_version should use cached value when available."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_cache.json"

            with patch(
                "amscrot.serviceclient.amsc_iri.version_prober._cache_path",
                return_value=cache_file,
            ):
                prober = VersionProber()
                prober._set_cached("https://example.com", 1)

                # Should use cache, not probe
                with patch.object(prober, "_probe") as mock_probe:
                    version = prober.detect_version("https://example.com")

                assert version == 1
                mock_probe.assert_not_called()

    def test_detect_version_force_skips_cache(self):
        """detect_version(force=True) should always probe live."""
        from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_cache.json"

            with patch(
                "amscrot.serviceclient.amsc_iri.version_prober._cache_path",
                return_value=cache_file,
            ):
                prober = VersionProber()
                prober._set_cached("https://example.com", 1)

                with patch.object(prober, "_probe", return_value=2) as mock_probe:
                    version = prober.detect_version(
                        "https://example.com", force=True
                    )

                assert version == 2
                mock_probe.assert_called_once()


# ---------------------------------------------------------------------------
# Factory dispatch tests
# ---------------------------------------------------------------------------

class TestIriServiceClientFactory:
    """Tests for the IriServiceClient factory dispatch."""

    def test_factory_returns_v1_for_api_version_1(self):
        """Factory should return IriServiceClientV1 when api_version=1."""
        from amscrot.serviceclient.amsc_iri import IriServiceClient
        from amscrot.serviceclient.amsc_iri._v1 import IriServiceClientV1

        client = IriServiceClient(
            name="test",
            credential={
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
                "api_version": 1,
            },
        )

        assert isinstance(client, IriServiceClientV1)
        assert client.API_VERSION == 1

    def test_factory_returns_v2_for_api_version_2(self):
        """Factory should return IriServiceClientV2 when api_version=2."""
        from amscrot.serviceclient.amsc_iri import IriServiceClient
        from amscrot.serviceclient.amsc_iri._v2 import IriServiceClientV2

        client = IriServiceClient(
            name="test",
            credential={
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
                "api_version": 2,
            },
        )

        assert isinstance(client, IriServiceClientV2)
        assert client.API_VERSION == 2

    def test_factory_uses_probing_when_no_override(self):
        """Without api_version, factory should probe the endpoint."""
        from amscrot.serviceclient.amsc_iri import IriServiceClient
        from amscrot.serviceclient.amsc_iri._v2 import IriServiceClientV2
        import amscrot.serviceclient.amsc_iri as iri_module

        with patch.object(
            iri_module, "_probe_version", return_value=2
        ):
            client = IriServiceClient(
                name="test",
                credential={
                    "api_key": "test-key",
                    "api_endpoint": "https://example.com",
                },
            )

        assert isinstance(client, IriServiceClientV2)

    def test_factory_uses_probing_falls_back_to_v1(self):
        """Without api_version, when probe returns 1, factory returns v1."""
        from amscrot.serviceclient.amsc_iri import IriServiceClient
        from amscrot.serviceclient.amsc_iri._v1 import IriServiceClientV1
        import amscrot.serviceclient.amsc_iri as iri_module

        with patch.object(
            iri_module, "_probe_version", return_value=1
        ):
            client = IriServiceClient(
                name="test",
                credential={
                    "api_key": "test-key",
                    "api_endpoint": "https://example.com",
                },
            )

        assert isinstance(client, IriServiceClientV1)

    def test_factory_reads_api_version_from_yaml(self):
        """Factory should read api_version from credentials.yml."""
        from amscrot.serviceclient.amsc_iri import IriServiceClient
        from amscrot.serviceclient.amsc_iri._v1 import IriServiceClientV1
        from amscrot.serviceclient.amsc_iri._v2 import IriServiceClientV2
        import yaml

        cred_data = {
            "test-v1-profile": {
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
                "api_version": 1,
            },
            "test-v2-profile": {
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
                "api_version": 2,
            },
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            yaml.dump(cred_data, f)
            cred_file = f.name

        try:
            client1 = IriServiceClient(
                name="test",
                profile="test-v1-profile",
                credential_file=cred_file,
            )
            assert isinstance(client1, IriServiceClientV1)
            assert client1.api_version == 1

            client2 = IriServiceClient(
                name="test",
                profile="test-v2-profile",
                credential_file=cred_file,
            )
            assert isinstance(client2, IriServiceClientV2)
            assert client2.api_version == 2

            # Lookup by name when profile is omitted
            client_by_name = IriServiceClient(
                name="test-v2-profile",
                credential_file=cred_file,
            )
            assert isinstance(client_by_name, IriServiceClientV2)
            assert client_by_name.api_version == 2
        finally:
            os.unlink(cred_file)

    def test_factory_accepts_direct_api_version_kwarg(self):
        """Factory should accept direct api_version kwarg."""
        from amscrot.serviceclient.amsc_iri import IriServiceClient
        from amscrot.serviceclient.amsc_iri._v1 import IriServiceClientV1
        from amscrot.serviceclient.amsc_iri._v2 import IriServiceClientV2

        c1 = IriServiceClient(name="test", api_version=1)
        assert isinstance(c1, IriServiceClientV1)
        assert c1.api_version == 1

        c2 = IriServiceClient(name="test", api_version=2)
        assert isinstance(c2, IriServiceClientV2)
        assert c2.api_version == 2

    def test_v1_client_does_not_have_v2_methods(self):
        """V1 client should not have whoami, get_storage_locations, etc."""
        from amscrot.serviceclient.amsc_iri._v1 import IriServiceClientV1

        client = IriServiceClientV1(
            name="test",
            credential={
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
            },
        )

        assert not hasattr(client, "whoami")
        assert not hasattr(client, "get_storage_locations")
        assert not hasattr(client, "get_storage_access_endpoints")

    def test_v2_client_has_v2_methods(self):
        """V2 client should have whoami, get_storage_locations, etc."""
        from amscrot.serviceclient.amsc_iri._v2 import IriServiceClientV2

        client = IriServiceClientV2(
            name="test",
            credential={
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
            },
        )

        assert hasattr(client, "whoami")
        assert hasattr(client, "get_storage_locations")
        assert hasattr(client, "get_storage_access_endpoints")


# ---------------------------------------------------------------------------
# V1 client tests
# ---------------------------------------------------------------------------

class TestIriServiceClientV1:
    """Tests for IriServiceClientV1-specific behavior."""

    def _make_client(self):
        from amscrot.serviceclient.amsc_iri._v1 import IriServiceClientV1

        client = IriServiceClientV1(
            name="test-v1",
            credential={
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
            },
        )
        client._compute_api = MagicMock()
        client._status_api = MagicMock()
        client._account_api = MagicMock()
        client._facility_api = MagicMock()
        return client

    def test_resource_type_returns_simple_strings(self):
        """V1 resource types should be simple strings."""
        client = self._make_client()

        assert client._resource_type("compute") == "compute"
        assert client._resource_type("storage") == "storage"
        assert client._resource_type("network") == "network"

    def test_v1_uses_amsc_iri_models(self):
        """V1 client should use models from amsc_iri package."""
        from amsc_iri.models.job_spec import JobSpec as V1JobSpec

        client = self._make_client()
        assert client._iri_models['JobSpec'] is V1JobSpec


# ---------------------------------------------------------------------------
# V2 client tests
# ---------------------------------------------------------------------------

class TestIriServiceClientV2:
    """Tests for IriServiceClientV2-specific behavior."""

    def _make_client(self):
        from amscrot.serviceclient.amsc_iri._v2 import IriServiceClientV2

        client = IriServiceClientV2(
            name="test-v2",
            credential={
                "api_key": "test-key",
                "api_endpoint": "https://example.com",
            },
        )
        client._compute_api = MagicMock()
        client._status_api = MagicMock()
        client._account_api = MagicMock()
        client._facility_api = MagicMock()
        client._storage_api = MagicMock()
        return client

    def test_resource_type_returns_urns(self):
        """V2 resource types should be DOE IRI URN strings."""
        client = self._make_client()

        assert client._resource_type("compute") == "urn:doe-iri:resource:compute"
        assert client._resource_type("storage") == "urn:doe-iri:resource:storage"
        assert client._resource_type("network") == "urn:doe-iri:resource:network"

    def test_v2_uses_amsc_iri_v2_models(self):
        """V2 client should use models from amsc_iri_v2 package."""
        from amsc_iri_v2.models.job_spec import JobSpec as V2JobSpec

        client = self._make_client()
        assert client._iri_models['JobSpec'] is V2JobSpec

    def test_whoami_returns_username(self):
        """whoami() should return the username from the v2 API."""
        mock_result = MagicMock()
        mock_result.username = "ezra"

        client = self._make_client()
        client._account_api.whoami.return_value = mock_result

        result = client.whoami()

        assert result == "ezra"
        client._account_api.whoami.assert_called_once()

    def test_whoami_returns_none_when_unavailable(self):
        """whoami() should return None when client is unavailable."""
        client = self._make_client()
        client._available = False

        result = client.whoami()

        assert result is None

    def test_whoami_returns_none_on_exception(self):
        """whoami() should return None when the API call fails."""
        client = self._make_client()
        client._account_api.whoami.side_effect = Exception("API error")

        result = client.whoami()

        assert result is None

    def test_get_storage_locations_returns_list(self):
        """get_storage_locations() should return list of dicts on v2."""
        mock_loc1 = MagicMock()
        mock_loc1.to_dict.return_value = {
            "logical_name": "home",
            "path": "/global/homes/e/ezra",
            "filesystem": "ceph",
            "performance_tier": "ssd",
            "purge_policy_days": 30,
            "shared": False,
            "access": {"read": True, "write": True},
        }
        mock_loc2 = MagicMock()
        mock_loc2.to_dict.return_value = {
            "logical_name": "scratch",
            "path": "/tmp/e/ezra",
            "filesystem": "lustre",
            "performance_tier": "hdd",
            "purge_policy_days": 7,
            "shared": True,
            "access": {"read": True, "write": True},
        }

        client = self._make_client()
        client._storage_api.get_storage_locations.return_value = [mock_loc1, mock_loc2]

        result = client.get_storage_locations("storage-uuid")

        assert len(result) == 2
        assert result[0]["logical_name"] == "home"
        assert result[0]["path"] == "/global/homes/e/ezra"
        assert result[1]["logical_name"] == "scratch"
        client._storage_api.get_storage_locations.assert_called_once_with(
            resource_id="storage-uuid"
        )

    def test_get_storage_locations_filters(self):
        """get_storage_locations() should pass filter parameters."""
        client = self._make_client()
        client._storage_api.get_storage_locations.return_value = []

        result = client.get_storage_locations(
            "storage-uuid",
            logical_name="home",
            project="myproject",
            intent="staging",
        )

        assert result == []
        client._storage_api.get_storage_locations.assert_called_once_with(
            resource_id="storage-uuid",
            logicalpath="home",
            project="myproject",
            intent="staging",
        )

    def test_get_storage_access_endpoints_returns_list(self):
        """get_storage_access_endpoints() should return list of dicts on v2."""
        mock_ep1 = MagicMock()
        mock_ep1.to_dict.return_value = {
            "id": "globus-endpoint-1",
            "resource_id": "storage-uuid",
            "protocol": "globus",
            "display_name": "Globus Endpoint",
            "auth_type": "oauth2",
            "capabilities": {"read": True, "write": True},
            "endpoint_id": "abcd-1234",
        }

        client = self._make_client()
        client._storage_api.get_storage_access_endpoints.return_value = [mock_ep1]

        result = client.get_storage_access_endpoints("storage-uuid")

        assert len(result) == 1
        assert result[0]["protocol"] == "globus"
        assert result[0]["endpoint_id"] == "abcd-1234"
        client._storage_api.get_storage_access_endpoints.assert_called_once_with(
            resource_id="storage-uuid"
        )

    def test_get_storage_access_endpoints_filters(self):
        """get_storage_access_endpoints() should pass filter parameters."""
        client = self._make_client()
        client._storage_api.get_storage_access_endpoints.return_value = []

        result = client.get_storage_access_endpoints(
            "storage-uuid",
            protocol="s3",
            endpoint_id="my-endpoint",
        )

        assert result == []
        client._storage_api.get_storage_access_endpoints.assert_called_once_with(
            resource_id="storage-uuid",
            protocol="s3",
            endpoint_id="my-endpoint",
        )
