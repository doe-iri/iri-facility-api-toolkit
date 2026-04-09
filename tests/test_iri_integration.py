"""Integration tests for the unified IriServiceClient.

Tests any AMSC_IRI profile defined in ``~/.amscrot/credentials.yml``.

Profile selection
-----------------
By default the test discovers **all** credential sections whose
``client_type`` is ``AMSC_IRI`` and parameterises on each one.

To run against specific profiles only, set the ``IRI_TEST_PROFILES``
environment variable to a comma-separated list::

    IRI_TEST_PROFILES=esnet-iri-east,nersc-iri pytest tests/test_iri_integration.py -v

To run ALL discovered profiles::

    pytest tests/test_iri_integration.py -v -m integration
"""

import os
import shutil
import unittest
import yaml
import pytest
from pathlib import Path

from amscrot.client.client import Client
from amscrot.client.job import Job, JobSpec, JobType, JobServiceType, JobState
from amscrot.serviceclient import ServiceClient, PlanError, CreateError
from amscrot.util.constants import Constants


# ---------------------------------------------------------------------------
# Profile discovery
# ---------------------------------------------------------------------------

CREDENTIALS_FILE = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
HAS_CREDENTIALS = os.path.exists(CREDENTIALS_FILE)


def _discover_iri_profiles():
    """Return a list of profile names whose ``client_type`` is ``AMSC_IRI``."""
    if not HAS_CREDENTIALS:
        return []
    with open(CREDENTIALS_FILE) as f:
        creds = yaml.safe_load(f) or {}

    profiles = [
        key for key, val in creds.items()
        if isinstance(val, dict) and val.get('client_type') == 'AMSC_IRI'
    ]

    # Allow narrowing via env var
    env_filter = os.environ.get('IRI_TEST_PROFILES', '').strip()
    if env_filter:
        allowed = {p.strip() for p in env_filter.split(',')}
        profiles = [p for p in profiles if p in allowed]

    return profiles


IRI_PROFILES = _discover_iri_profiles()


# ---------------------------------------------------------------------------
# Per-profile job configuration
# ---------------------------------------------------------------------------

# Each entry defines how job specs and resource selection differ per facility.
# Keys:
#   account           – scheduler account/project name
#   directory         – remote working directory
#   stdout_path       – remote stdout log path
#   stderr_path       – remote stderr log path
#   exclusive_node_use – whether to request exclusive node access
#   resource_filter   – optional callable(resource_data) -> bool to pick
#                       a specific compute resource from discovery results

PROFILE_CONFIGS = {
    "esnet-iri-east": {
        "account": "interactive",
        "directory": "/data/home/kissel",
        "stdout_path": "/data/home/kissel/iri_test_stdout.log",
        "stderr_path": "/data/home/kissel/iri_test_stderr.log",
        "exclusive_node_use": True,
        "resource_filter": None,  # use first available compute resource
    },
    "esnet-iri-west": {
        "account": "interactive",
        "directory": "/data/home/kissel",
        "stdout_path": "/data/home/kissel/iri_test_stdout.log",
        "stderr_path": "/data/home/kissel/iri_test_stderr.log",
        "exclusive_node_use": True,
        "resource_filter": None,
    },
    "nersc-iri": {
        "account": "amsc013",
        "directory": "/global/homes/k/kissel",
        "stdout_path": "iri_test_stdout.log",
        "stderr_path": "iri_test_stderr.log",
        "exclusive_node_use": False,
        "resource_filter": lambda d: d.get("group") == "perlmutter" and d.get("name") == "compute",
    },
}

# Fallback for unknown profiles
_DEFAULT_PROFILE_CONFIG = {
    "account": "interactive",
    "directory": "/tmp",
    "stdout_path": "iri_test_stdout.log",
    "stderr_path": "iri_test_stderr.log",
    "exclusive_node_use": False,
    "resource_filter": None,
}


def _get_profile_config(profile: str) -> dict:
    """Return the job configuration for a profile, falling back to defaults."""
    return PROFILE_CONFIGS.get(profile, _DEFAULT_PROFILE_CONFIG)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(not HAS_CREDENTIALS, reason="Requires ~/.amscrot/credentials.yml")
@pytest.mark.skipif(not IRI_PROFILES, reason="No AMSC_IRI profiles found in credentials")
class TestIriIntegration:
    """Integration tests parameterised on each AMSC_IRI credential profile."""

    @pytest.fixture(params=IRI_PROFILES)
    def profile(self, request):
        """Yield each discovered IRI profile name."""
        return request.param

    @pytest.fixture
    def iri_client(self, profile):
        """Create an IriServiceClient from the given profile."""
        client = ServiceClient.create(
            type=Constants.ServiceType.IRI,
            name=f"test-{profile}",
            profile=profile,
        )
        assert client._available, (
            f"IriServiceClient for profile '{profile}' is not available — "
            "check api_key / api_endpoint in credentials.yml"
        )
        return client

    # -- Discovery ----------------------------------------------------------

    def test_discover(self, iri_client, profile):
        """Native discovery returns compute resources."""
        print(f"\n--- [{profile}] Discovering resources ---")
        result = iri_client.discover()

        print(f"  Total items: {len(result)}")
        print(f"  Compute:      {len(result.compute)}")
        print(f"  Storage:      {len(result.storage)}")
        print(f"  Facilities:   {len(result.facility)}")
        print(f"  Capabilities: {len(result.capability)}")
        print(f"  Allocations:  {len(result.allocation)}")

        assert len(result) > 0, f"[{profile}] Discovery returned no resources"

    # -- Full job lifecycle -------------------------------------------------

    def test_job_lifecycle(self, iri_client, profile):
        """plan → create → wait → fetch_output_files → destroy."""
        print(f"\n--- [{profile}] Job lifecycle ---")
        pcfg = _get_profile_config(profile)

        # --- Setup ---
        client = Client()
        client.add_service_client(iri_client)
        session_name = f"test-{profile}"
        session = client.create_session(session_name)

        # --- Discover a compute + storage resource ---
        all_resources = iri_client.discover()
        compute_resources = all_resources.compute

        if not compute_resources:
            pytest.skip(f"[{profile}] No compute resources available")

        # Select compute resource (apply profile-specific filter if present)
        resource_filter = pcfg.get("resource_filter")
        target_resource = None
        if resource_filter:
            for res in compute_resources:
                if resource_filter(res.data):
                    target_resource = res
                    break
            if not target_resource:
                pytest.skip(
                    f"[{profile}] No compute resource matching profile filter"
                )
        else:
            target_resource = compute_resources[0]

        resource_id = target_resource.data.get("id")
        if not resource_id:
            pytest.skip(f"[{profile}] Compute resource found but ID is missing")

        print(f"  Using compute resource: {resource_id}")

        # Resolve storage
        storage_resources = all_resources.storage or []
        storage_resource_id = None
        for res in storage_resources:
            if 'home' in (res.data.get('name') or '').lower():
                storage_resource_id = res.data.get('id')
                break
        if not storage_resource_id and storage_resources:
            storage_resource_id = storage_resources[0].data.get('id')
        print(f"  Storage resource: {storage_resource_id}")

        # --- Build job with profile-specific attributes ---
        spec = JobSpec(
            executable="/bin/echo",
            arguments=["Hello AmSC"],
            resources={
                "node_count": 1,
                "process_count": 1,
                "processes_per_node": 1,
                "cpu_cores_per_process": 1,
                "gpu_cores_per_process": None,
                "exclusive_node_use": pcfg["exclusive_node_use"],
                "memory": 268435456,
            },
            attributes={
                "resource_id": resource_id,
                "directory": pcfg["directory"],
                "duration": 600,
                "queue_name": "debug",
                "account": pcfg["account"],
                "stdout_path": pcfg["stdout_path"],
                "stderr_path": pcfg["stderr_path"],
            },
        )

        job = Job(
            name=f"{profile}-test-job",
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=iri_client,
            job_spec=spec,
        )
        session.add_job(job)

        try:
            # 1. Plan
            print("  Plan...")
            plan_result = iri_client.plan(job)
            print(f"    result: {plan_result}")
            assert plan_result["status"] == "PLANNED"

            # 2. Create
            print("  Create...")
            iri_client.create(job)
            if not job.id:
                pytest.skip(f"[{profile}] Job not submitted")
            assert job.resource_id == resource_id
            print(f"    Job ID: {job.id}")

            # 3. Wait
            print("  Wait...")
            results = session.wait(
                jobs=[job],
                target_states=[JobState.COMPLETED, JobState.FAILED, JobState.CANCELED],
                timeout=600,
                interval=2,
                verbose=True,
            )
            status_result = results[job.name]
            assert status_result.state == JobState.COMPLETED, (
                f"[{profile}] Job ended with state {status_result.state}"
            )
            print(f"    Completed. State: {status_result.state}")

            # 4. Fetch output files
            print("  Fetch output files...")
            if storage_resource_id and iri_client.filesystem:
                working_dir = pcfg["directory"]
                try:
                    ls_result = iri_client.filesystem.ls(
                        storage_resource_id, working_dir, format=True
                    )
                    print(f"    ls: {ls_result}")
                except Exception as ls_err:
                    print(f"    ls failed: {ls_err}")

            fetched = session.fetch_output_files(jobs=[job])
            print(f"    Fetched: {fetched}")

            if fetched.get(job.name):
                for stream, local_path in fetched[job.name].items():
                    assert os.path.exists(local_path), f"Missing {local_path}"
                    with open(local_path) as f:
                        print(f"    {stream}: {f.read().strip() or '(empty)'}")

            assert job.local_files == fetched.get(job.name, {})

        except (PlanError, CreateError) as e:
            if any(
                kw in err for err in e.errors
                for kw in ("not available", "credentials", "401", "403")
            ):
                pytest.skip(f"[{profile}] Auth issue: {e}")
            raise

        finally:
            # 5. Destroy
            print("  Destroy...")
            try:
                if job.id:
                    iri_client.destroy(job)
                    print("    Done")
            except Exception as cleanup_error:
                print(f"    Warning: {cleanup_error}")

            try:
                session_dir = session.session_path
                if os.path.exists(session_dir):
                    shutil.rmtree(session_dir)
            except Exception:
                pass

