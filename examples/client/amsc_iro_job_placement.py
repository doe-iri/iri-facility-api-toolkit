"""
AmSC IRO Job Placement Example
================================

Demonstrates:
  1. Discovering facilities and intent profiles from the AMSC-IRO backend
  2. Selecting the "Job Placement" intent by name
  3. Creating and submitting a compute job via Session
  4. Session persistence — if a prior session exists on disk, skips straight to monitoring

Usage:
  python amsc_iro_job_placement.py
  python amsc_iro_job_placement.py --intent "AmSC Demo - IRI Job Placement"
  python amsc_iro_job_placement.py --session-name my-session

Requires ~/.amscrot/credentials.yml with an 'amsc-iro' profile section.
"""

import argparse
import sys
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.model.metadata import Network, Layer2
from amscrot.serviceclient import ServiceClient, PlanError
from amscrot.util.constants import Constants

DEFAULT_SESSION = "amsc-iro-job-placement"
DEFAULT_INTENT_MATCH = "AmSC Demo - Networked IRI Jobs - Transfer"


def setup_and_submit(client, session, iro_client, intent_name_match):
    """Fresh session: discover resources, find the intent, define a job, plan, and apply."""

    # Discover resources and intents
    print("\n--- Discovering Resources & Intents ---")
    discovery = iro_client.discover()

    facilities = discovery.facility
    intents = discovery.intents
    print(f"  Facilities: {len(facilities)}")
    for f in facilities:
        print(f"    - {f.name} ({f.data.get('id')})")

    amsc_intents = [i for i in intents if i.name and "amsc" in i.name.lower()]
    print(f"  Intents (AmSC): {len(amsc_intents)}")
    for intent in amsc_intents:
        print(f"    - {intent.name} (uuid={intent.uuid}, editable={intent.editable})")

    # Find the Job Placement intent
    matching = [i for i in intents if intent_name_match.lower() in (i.name or "").lower()]
    if not matching:
        print(f"\nERROR: No intent matching '{intent_name_match}' found.")
        print("Available intents:")
        for i in intents:
            print(f"  - {i.name}")
        sys.exit(1)

    selected_intent = matching[0]
    print(f"\n--- Selected Intent ---")
    print(f"  Name: {selected_intent.name}")
    print(f"  UUID: {selected_intent.uuid}")

    print (f"\n--- Intent Details --- ")
    print (f"{selected_intent.data}")
    sys.exit(0)

    # Discover remote_port_names for specific facilities
    target_facilities = ["ESnet Facility East", "ESnet Facility West"]
    remote_ports = []
    for f in facilities:
        if f.name in target_facilities:
            endpoints = f.data.get("network_endpoints", [])
            for ep in endpoints:
                rp = ep.get("remote_port_name")
                if rp and rp != "n/a":
                    remote_ports.append(rp)

    if len(remote_ports) < 2:
        print(f"\nWARNING: Could not find at least 2 remote ports for {target_facilities}")
        network_metadata = None
    else:
        print(f"\n--- Created Network Metadata ---")
        l2_configs = [Layer2(port_name=rp) for rp in remote_ports]
        network_metadata = Network(
            name="iro-network-metadata",
            layer2=l2_configs
        )
        print(f"  Network '{network_metadata.name}' created with {len(l2_configs)} ports.")

    job1 = Job(
        name="gpt2-compute",
        type=JobType.COMPUTE,
        service_type=JobServiceType.BATCH,
        service_client=iro_client,
        job_spec=JobSpec(),
        intent=selected_intent.uuid
    )
    session.add_job(job1)

    job2 = Job(
        name="transfer-src",
        type=JobType.COMPUTE,
        service_type=JobServiceType.BATCH,
        service_client=iro_client,
        job_spec=JobSpec(),
        intent=selected_intent.uuid,
        network=network_metadata
    )
    session.add_job(job2)

    job3 = Job(
        name="transfer-dst",
        type=JobType.COMPUTE,
        service_type=JobServiceType.BATCH,
        service_client=iro_client,
        job_spec=JobSpec(),
        intent=selected_intent.uuid,
        network=network_metadata
    )
    session.add_job(job3)

    # Plan
    print("\n--- Session Plan ---")
    try:
        plan_result = session.plan(verbose=True)
    except PlanError as e:
        print("Plan failed:")
        for err in e.errors:
            print(f"  - {err}")
        sys.exit(1)

    # Show session state
    print("\n--- Session Config ---")
    session.show()
    # sys.exit(0)
    # Apply
    print("\n--- Session Apply ---")
    session.apply()
    print("Job submitted successfully.")


def main():
    parser = argparse.ArgumentParser(description="AmSC IRO Job Placement example")
    parser.add_argument(
        "--intent",
        default=DEFAULT_INTENT_MATCH,
        help=f"Substring to match intent name (default: '{DEFAULT_INTENT_MATCH}')",
    )
    parser.add_argument(
        "--session-name",
        default=DEFAULT_SESSION,
        help=f"Session name for persistence (default: '{DEFAULT_SESSION}')",
    )
    args = parser.parse_args()

    client = Client()

    # Create AMSC IRO service client
    iro_client = ServiceClient.create(
        type=Constants.ServiceType.AMSC_IRO,
        name="amsc-iro",
        profile="amsc-iro",
    )
    client.add_service_client(iro_client)

    if not iro_client._available:
        print("ERROR: AMSC IRO client failed to initialize. Check credentials.")
        sys.exit(1)

    # Create or restore session
    session = client.create_session(args.session_name)

    if session.jobs:
        # Session restored from disk — skip to monitoring
        print(f"\n--- Restored {len(session.jobs)} job(s) from session '{args.session_name}' ---")
        for job in session.jobs:
            print(f"  {job.name}: id={job.id} status={job.status}")
    else:
        # Fresh session — discover, plan, submit
        setup_and_submit(client, session, iro_client, args.intent)

    # Wait for completion
    print("\n--- Session Wait ---")
    try:
        results = session.wait(
            timeout=600.0,
            interval=5.0,
            verbose=True,
            # raw=True
        )
    except Exception as e:
        print(f"Error waiting for jobs: {e}")
        sys.exit(1)

    for job_name, status in results.items():
        state = status.state
        print(f"  {job_name}: {state}")
        if state != JobState.COMPLETED:
            print(f"  WARNING: {job_name} ended in state {state}")

    # Destroy
    print("\n--- Session Destroy ---")
    session.destroy()
    print("Done.")


if __name__ == "__main__":
    main()
