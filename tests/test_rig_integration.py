"""Live integration tests for the AMSC_RIG gateway service client.

These hit the real AmSC Resource Interface Gateway and require an
``AMSC_RIG`` section in ``~/.amscrot/credentials.yml`` with a valid PAT::

    amsc-rig:
      client_type: AMSC_RIG
      api_endpoint: https://rig.staging.american-science-cloud.org
      pat_file: ~/.amsc_token.json

Run with::

    pytest tests/test_rig_integration.py -m integration -v

They are skipped automatically when no RIG profile is configured, and are
excluded from the default run via ``-m "not integration"``.
"""

import os
from pathlib import Path

import pytest
import yaml

from amscrot.util.constants import Constants


CRED_FILE = Path.home() / ".amscrot" / "credentials.yml"
HAS_CREDENTIALS = CRED_FILE.exists()


def _rig_profiles():
    """Return credential profile names declaring ``client_type: AMSC_RIG``."""
    if not HAS_CREDENTIALS:
        return []
    try:
        with CRED_FILE.open() as fh:
            creds = yaml.safe_load(fh) or {}
    except Exception:
        return []

    profiles = [
        name for name, section in creds.items()
        if isinstance(section, dict) and section.get("client_type") == "AMSC_RIG"
    ]

    env_filter = os.environ.get("RIG_TEST_PROFILES", "").strip()
    if env_filter:
        wanted = {p.strip() for p in env_filter.split(",") if p.strip()}
        profiles = [p for p in profiles if p in wanted]
    return profiles


RIG_PROFILES = _rig_profiles()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml"
    ),
    pytest.mark.skipif(
        not RIG_PROFILES, reason="No AMSC_RIG profiles found in credentials"
    ),
]


@pytest.fixture(scope="module", params=RIG_PROFILES)
def rig(request):
    """A live RigServiceClient for each configured AMSC_RIG profile."""
    from amscrot.serviceclient import ServiceClient

    client = ServiceClient.create(
        type=Constants.ServiceType.AMSC_RIG,
        name=request.param,
        profile=request.param,
    )
    if not client._available:
        pytest.skip(f"RIG profile '{request.param}' has no usable credentials")
    return client


class TestRigLive:
    def test_ready(self, rig):
        """The gateway responds to /ready with a facility listing."""
        doc = rig.get_ready()
        assert doc is not None, "RIG /ready returned nothing"
        assert doc.is_ready, f"gateway status={doc.status}"
        assert doc.facilities, "no facilities advertised"

    def test_facilities_well_formed(self, rig):
        """Every advertised facility has a name and a sane API version."""
        for fac in rig.get_facilities():
            assert fac.name
            assert fac.api_version >= 1
            assert fac.base_url(rig.api_endpoint).endswith(f"/{fac.name}")

    def test_discover_reports_facilities(self, rig):
        """discover() surfaces each facility with its proxied endpoint."""
        facilities = rig.discover().facility
        assert facilities

        for item in facilities:
            data = item.data
            assert data["api_endpoint"].startswith(rig.api_endpoint)
            assert Constants.RIG_EXTERNAL_PATH in data["api_endpoint"]
            assert data["path_style"] in ("standard", "bare")

    def test_expands_into_usable_iri_clients(self, rig):
        """Children are real IRI clients at the version the RIG reported."""
        from amscrot.serviceclient.amsc_iri import IriServiceClientBase

        clients = rig.create_facility_clients()
        assert clients, "RIG produced no facility clients"

        doc = rig.get_ready()
        for name, child in clients.items():
            assert isinstance(child, IriServiceClientBase)
            assert name.endswith("-rig")
            assert Constants.RIG_EXTERNAL_PATH in child.api_endpoint

            facility_name = child.api_endpoint.rstrip("/").rsplit("/", 1)[-1]
            expected = doc.facility(facility_name)
            assert expected is not None
            assert child.api_version == expected.api_version

    def test_child_names_are_unique(self, rig):
        """Facilities sharing a shorthand (olcf-*) must not collide."""
        doc = rig.get_ready()
        selected = rig._selected_facilities(doc)
        names = [rig.child_client_name(f, peers=selected) for f in selected]
        assert len(names) == len(set(names)), f"duplicate client names: {names}"

    def test_unsupported_facilities_excluded(self, rig):
        """Facilities with non-standard path prefixes are not expanded."""
        clients = rig.create_facility_clients()
        for fac in rig.get_facilities():
            if not fac.is_standard_path:
                endpoints = [c.api_endpoint for c in clients.values()]
                assert fac.base_url(rig.api_endpoint) not in endpoints

    def test_discovery_through_proxy(self, rig):
        """At least one proxied facility answers a real IRI API call."""
        clients = rig.create_facility_clients()
        reachable = {}

        for name, child in clients.items():
            try:
                result = child.discover(native=True)
            except Exception as exc:  # facility-side outage, not our bug
                print(f"  {name}: unreachable ({type(exc).__name__}: {exc})")
                continue
            total = len(result.compute) + len(result.storage) + len(result.network)
            reachable[name] = total
            print(f"  {name}: {total} resource(s)")

        assert reachable, "no facility behind the RIG answered a discovery call"

    def test_job_methods_rejected(self, rig):
        """The gateway itself cannot run jobs."""
        with pytest.raises(NotImplementedError):
            rig.create(object())


class TestRigClientBootstrap:
    def test_client_registers_facility_clients(self):
        """Client(create_service_clients=True) expands the gateway."""
        from amscrot.client.client import Client
        from amscrot.serviceclient.amsc_rig import RigServiceClient

        client = Client(create_service_clients=True)
        gateways = [
            sc for sc in client.get_service_client()
            if isinstance(sc, RigServiceClient)
        ]
        if not gateways:
            pytest.skip("No AMSC_RIG client registered")

        rig_children = [
            sc for sc in client.get_service_client()
            if sc.name.endswith("-rig") and not isinstance(sc, RigServiceClient)
        ]
        assert rig_children, "gateway contributed no facility clients"

        for child in rig_children:
            assert client.get_service_client(child.name) is child
