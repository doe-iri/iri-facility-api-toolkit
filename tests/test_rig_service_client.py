"""Tests for the AMSC_RIG gateway service client.

Covers ``/ready`` parsing and caching, API-version coercion, facility
filtering, child-client naming/collisions, and the job-lifecycle guards.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from amscrot.serviceclient.amsc_rig.ready_prober import (
    RigFacility,
    RigReadyDocument,
    RigReadyProber,
    parse_api_version,
)
from amscrot.serviceclient.amsc_rig.rig_service_client import RigServiceClient
from amscrot.util.constants import Constants


RIG_URL = "https://rig.staging.american-science-cloud.org"

# Trimmed copy of the real staging /ready payload.
READY_PAYLOAD = {
    "status": "ready",
    "active_roles": ["api"],
    "facilities": [
        {
            "name": "nersc", "tier": 3, "display_url": None,
            "health_monitored": True, "api_version": "v1",
            "probe_path": None, "metadata_path": "/api/v1/facility",
        },
        {
            "name": "pnnl", "tier": 1, "display_url": None,
            "health_monitored": True, "api_version": "v1",
            "probe_path": "/v1/account/projects", "metadata_path": "/v1/facility",
        },
        {
            "name": "esnet-east", "tier": 1, "display_url": None,
            "health_monitored": True, "api_version": "v2",
            "probe_path": None, "metadata_path": "/api/v2/facility",
        },
        {
            "name": "olcf-open", "tier": 3, "display_url": None,
            "health_monitored": True, "api_version": "v2",
            "probe_path": "/api/v2/account/whoami",
            "metadata_path": "/api/v2/facility",
        },
        {
            "name": "olcf-moderate", "tier": 3, "display_url": None,
            "health_monitored": True, "api_version": "v2",
            "probe_path": "/api/v2/account/whoami",
            "metadata_path": "/api/v2/facility",
        },
    ],
    "hub": {"status": "ok", "cache_populated": True},
}


@pytest.fixture
def cache_file(tmp_path):
    """Redirect the ready-cache to a temp file."""
    path = tmp_path / "rig_ready_cache.json"
    with patch(
        "amscrot.serviceclient.amsc_rig.ready_prober._cache_path",
        return_value=path,
    ):
        yield path


def _mock_response(status_code=200, payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if payload is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = payload
    return resp


def make_client(**overrides):
    """Build a RigServiceClient with credentials injected directly."""
    cred = {"api_key": "test-token", "api_endpoint": RIG_URL}
    cred.update(overrides)
    return RigServiceClient(name="amsc-rig", credential=cred)


# ---------------------------------------------------------------------------
# parse_api_version
# ---------------------------------------------------------------------------

class TestParseApiVersion:
    @pytest.mark.parametrize(
        "value,expected",
        [("v1", 1), ("v2", 2), ("V2", 2), ("2", 2), (2, 2), (" v3 ", 3)],
    )
    def test_valid(self, value, expected):
        assert parse_api_version(value) == expected

    @pytest.mark.parametrize("value", [None, "", "abc", "vX", True, {}])
    def test_invalid_uses_default(self, value):
        assert parse_api_version(value, default=1) == 1


# ---------------------------------------------------------------------------
# RigFacility
# ---------------------------------------------------------------------------

class TestRigFacility:
    def test_base_url_builds_proxy_path(self):
        fac = RigFacility(name="nersc", api_version=1)
        assert fac.base_url(RIG_URL) == f"{RIG_URL}/rig/external/nersc"

    def test_base_url_strips_trailing_slash(self):
        fac = RigFacility(name="nersc")
        assert fac.base_url(RIG_URL + "/") == f"{RIG_URL}/rig/external/nersc"

    def test_standard_path_style(self):
        fac = RigFacility.from_dict(READY_PAYLOAD["facilities"][0])
        assert fac.path_style == "standard"
        assert fac.is_standard_path

    def test_bare_path_style_detected(self):
        """pnnl advertises /v1/facility, incompatible with generated bindings."""
        fac = RigFacility.from_dict(READY_PAYLOAD["facilities"][1])
        assert fac.name == "pnnl"
        assert fac.path_style == "bare"
        assert not fac.is_standard_path

    def test_missing_metadata_path_assumed_standard(self):
        fac = RigFacility(name="x", api_version=2, metadata_path=None)
        assert fac.is_standard_path

    def test_from_dict_parses_all_fields(self):
        fac = RigFacility.from_dict(READY_PAYLOAD["facilities"][3])
        assert fac.name == "olcf-open"
        assert fac.api_version == 2
        assert fac.tier == 3
        assert fac.health_monitored is True
        assert fac.probe_path == "/api/v2/account/whoami"


# ---------------------------------------------------------------------------
# RigReadyDocument
# ---------------------------------------------------------------------------

class TestRigReadyDocument:
    def test_parses_payload(self):
        doc = RigReadyDocument.from_dict(RIG_URL, READY_PAYLOAD)
        assert doc.is_ready
        assert len(doc.facilities) == 5
        assert doc.facility("nersc").api_version == 1
        assert doc.facility("esnet-east").api_version == 2
        assert doc.facility("missing") is None

    def test_skips_entries_without_name(self):
        doc = RigReadyDocument.from_dict(
            RIG_URL, {"status": "ready", "facilities": [{"tier": 1}, "junk"]}
        )
        assert doc.facilities == []

    def test_empty_facilities(self):
        doc = RigReadyDocument.from_dict(RIG_URL, {"status": "ready"})
        assert doc.facilities == []
        assert doc.is_ready

    def test_not_ready_status(self):
        doc = RigReadyDocument.from_dict(RIG_URL, {"status": "degraded"})
        assert not doc.is_ready


# ---------------------------------------------------------------------------
# RigReadyProber
# ---------------------------------------------------------------------------

class TestRigReadyProber:
    def test_fetch_success_and_caches(self, cache_file):
        prober = RigReadyProber()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)) as g:
            doc = prober.fetch(RIG_URL, api_key="tok")

        assert doc is not None and len(doc.facilities) == 5
        url = g.call_args[0][0]
        assert url == f"{RIG_URL}/ready"
        assert g.call_args[1]["headers"]["Authorization"] == "Bearer tok"
        assert cache_file.exists()

    def test_second_fetch_uses_cache(self, cache_file):
        prober = RigReadyProber()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)) as g:
            prober.fetch(RIG_URL, api_key="tok")
            prober.fetch(RIG_URL, api_key="tok")
        assert g.call_count == 1

    def test_force_bypasses_cache(self, cache_file):
        prober = RigReadyProber()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)) as g:
            prober.fetch(RIG_URL, api_key="tok")
            prober.fetch(RIG_URL, api_key="tok", force=True)
        assert g.call_count == 2

    def test_expired_cache_refetches(self, cache_file):
        stale = datetime.now(timezone.utc) - timedelta(hours=5)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            RIG_URL: {
                "payload": READY_PAYLOAD,
                "fetched_at": stale.isoformat(),
                "ttl_seconds": 3600,
            }
        }))
        prober = RigReadyProber(ttl_seconds=3600)
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)) as g:
            prober.fetch(RIG_URL, api_key="tok")
        assert g.call_count == 1

    def test_unauthorized_returns_none(self, cache_file):
        prober = RigReadyProber()
        with patch("requests.get", return_value=_mock_response(401, text="denied")):
            assert prober.fetch(RIG_URL, api_key="bad") is None

    def test_non_json_returns_none(self, cache_file):
        prober = RigReadyProber()
        with patch("requests.get", return_value=_mock_response(200, None, "<html>")):
            assert prober.fetch(RIG_URL, api_key="tok") is None

    def test_network_error_returns_none(self, cache_file):
        prober = RigReadyProber()
        with patch("requests.get", side_effect=OSError("unreachable")):
            assert prober.fetch(RIG_URL, api_key="tok") is None

    def test_falls_back_to_stale_cache_on_failure(self, cache_file):
        """A stale entry beats nothing when the gateway is unreachable."""
        stale = datetime.now(timezone.utc) - timedelta(days=2)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            RIG_URL: {
                "payload": READY_PAYLOAD,
                "fetched_at": stale.isoformat(),
                "ttl_seconds": 3600,
            }
        }))
        prober = RigReadyProber(ttl_seconds=3600)
        with patch("requests.get", side_effect=OSError("unreachable")):
            doc = prober.fetch(RIG_URL, api_key="tok")
        assert doc is not None and len(doc.facilities) == 5

    def test_clear_cache(self, cache_file):
        prober = RigReadyProber()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)) as g:
            prober.fetch(RIG_URL, api_key="tok")
            prober.clear_cache(RIG_URL)
            prober.fetch(RIG_URL, api_key="tok")
        assert g.call_count == 2

    def test_empty_base_url(self, cache_file):
        assert RigReadyProber().fetch("", api_key="tok") is None


# ---------------------------------------------------------------------------
# RigServiceClient
# ---------------------------------------------------------------------------

class TestRigServiceClient:
    def test_registered_in_service_client_classes(self):
        assert Constants.ServiceType.AMSC_RIG == "amsc-rig"
        assert (
            Constants.SERVICE_CLIENT_CLASSES[Constants.ServiceType.AMSC_RIG]
            == "amscrot.serviceclient.amsc_rig.RigServiceClient"
        )

    def test_credentials_from_dict(self, cache_file):
        sc = make_client()
        assert sc.api_key == "test-token"
        assert sc.api_endpoint == RIG_URL
        assert sc._available

    def test_endpoint_trailing_slash_stripped(self, cache_file):
        sc = make_client(api_endpoint=RIG_URL + "/")
        assert sc.api_endpoint == RIG_URL

    def test_pat_file_resolved(self, cache_file, tmp_path):
        pat = tmp_path / "token.json"
        pat.write_text(json.dumps({"AMSC_PAT": "from-file"}))
        sc = RigServiceClient(
            name="amsc-rig",
            credential={"pat_file": str(pat), "api_endpoint": RIG_URL},
        )
        assert sc.api_key == "from-file"

    def test_unavailable_without_token(self, cache_file):
        sc = RigServiceClient(name="amsc-rig", credential={"api_endpoint": RIG_URL})
        assert not sc._available
        assert sc.get_ready() is None
        assert sc.discover().all == []

    def test_discover_lists_facilities(self, cache_file):
        sc = make_client()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            result = sc.discover()

        facilities = result.facility
        assert len(facilities) == 5
        by_name = {f.name: f.data for f in facilities}
        assert by_name["nersc"]["api_endpoint"] == f"{RIG_URL}/rig/external/nersc"
        assert by_name["nersc"]["api_version"] == 1
        assert by_name["esnet-east"]["api_version"] == 2
        # pnnl is surfaced but flagged unsupported rather than hidden.
        assert by_name["pnnl"]["supported"] is False
        assert by_name["pnnl"]["path_style"] == "bare"

    def test_discover_empty_when_unreachable(self, cache_file):
        sc = make_client()
        with patch("requests.get", side_effect=OSError("down")):
            assert sc.discover().all == []

    # -- child client expansion ----------------------------------------

    def test_create_facility_clients_skips_bare_path(self, cache_file):
        sc = make_client()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock(name=kw["name"])
                clients = sc.create_facility_clients()

        assert "pnnl-rig" not in clients
        assert set(clients) == {
            "nersc-rig", "esnet-east-rig", "olcf-open-rig", "olcf-moderate-rig",
        }

    def test_child_gets_explicit_api_version(self, cache_file):
        """Version comes from the RIG, so VersionProber is never needed."""
        sc = make_client()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock()
                sc.create_facility_clients()

        by_name = {c.kwargs["name"]: c.kwargs for c in create.call_args_list}

        assert by_name["nersc-rig"]["credential"]["api_version"] == 1
        assert by_name["esnet-east-rig"]["credential"]["api_version"] == 2
        for kwargs in by_name.values():
            assert kwargs["type"] == Constants.ServiceType.AMSC_IRI
            assert kwargs["credential"]["api_key"] == "test-token"
            assert "/rig/external/" in kwargs["endpoint_uri"]

    def test_version_prober_not_invoked(self, cache_file):
        """Expanding N facilities must cost one request, not N probes."""
        sc = make_client()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock()
                with patch(
                    "amscrot.serviceclient.amsc_iri.version_prober."
                    "VersionProber.detect_version"
                ) as probe:
                    sc.create_facility_clients()
        probe.assert_not_called()

    def test_colliding_shorthands_stay_distinct(self, cache_file):
        """olcf-open and olcf-moderate both shorthand to 'olcf'."""
        sc = make_client()
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock()
                clients = sc.create_facility_clients()

        assert "olcf-open-rig" in clients
        assert "olcf-moderate-rig" in clients
        assert "olcf-rig" not in clients

    def test_allowlist(self, cache_file):
        sc = make_client(facilities=["nersc"])
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock()
                clients = sc.create_facility_clients()
        assert set(clients) == {"nersc-rig"}

    def test_denylist(self, cache_file):
        sc = make_client(exclude_facilities=["nersc", "olcf-open", "olcf-moderate"])
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock()
                clients = sc.create_facility_clients()
        assert set(clients) == {"esnet-east-rig"}

    def test_child_prefix(self, cache_file):
        sc = make_client(facilities=["nersc"], child_prefix="amsc-")
        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock()
                clients = sc.create_facility_clients()
        assert set(clients) == {"amsc-nersc-rig"}

    def test_child_failure_does_not_abort_expansion(self, cache_file):
        sc = make_client()
        calls = {"n": 0}

        def flaky(**kw):
            calls["n"] += 1
            if kw["name"] == "nersc-rig":
                raise RuntimeError("boom")
            return MagicMock()

        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create",
                side_effect=flaky,
            ):
                clients = sc.create_facility_clients()

        assert "nersc-rig" not in clients
        assert "esnet-east-rig" in clients

    def test_no_clients_when_unreachable(self, cache_file):
        sc = make_client()
        with patch("requests.get", side_effect=OSError("down")):
            assert sc.create_facility_clients() == {}

    # -- job lifecycle guards -------------------------------------------

    @pytest.mark.parametrize("op", ["plan", "create", "destroy", "status"])
    def test_job_methods_raise(self, cache_file, op):
        sc = make_client()
        with pytest.raises(NotImplementedError, match="AMSC_RIG"):
            getattr(sc, op)(MagicMock())


# ---------------------------------------------------------------------------
# Client bootstrap integration
# ---------------------------------------------------------------------------

class TestClientExpansion:
    def test_expand_registers_children_without_clobbering(self, cache_file):
        from amscrot.client.client import Client

        client = Client()
        gateway = make_client()

        existing = MagicMock()
        existing.name = "nersc-rig"
        client._service_clients["amsc-rig"] = gateway
        client._service_clients["nersc-rig"] = existing

        with patch("requests.get", return_value=_mock_response(200, READY_PAYLOAD)):
            with patch(
                "amscrot.serviceclient.serviceclient.ServiceClient.create"
            ) as create:
                create.side_effect = lambda **kw: MagicMock()
                client._expand_rig_service_clients()

        # Pre-existing entry preserved.
        assert client._service_clients["nersc-rig"] is existing
        # New ones added.
        assert "esnet-east-rig" in client._service_clients
        assert "olcf-moderate-rig" in client._service_clients

    def test_expansion_survives_gateway_failure(self, cache_file):
        from amscrot.client.client import Client

        client = Client()
        client._service_clients["amsc-rig"] = make_client()

        with patch("requests.get", side_effect=OSError("down")):
            client._expand_rig_service_clients()

        assert set(client._service_clients) == {"amsc-rig"}
