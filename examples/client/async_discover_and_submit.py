"""
Async: Auto-Discover and Submit Jobs to Discovered Facilities via Session
=========================================================================

Async counterpart of ``discover_and_submit_iri.py``.

Demonstrates:
  1. Initializing the AsyncClient with discover_endpoints=True to query the IRO
     discovery endpoint and automatically register ServiceClient instances.
  2. Selecting available IRI service clients for both NERSC and ESnet.
  3. Session persistence -- if a prior session exists on disk, skips straight to monitoring.
  4. Querying normalized discovery results to inspect project allocations.
  5. Using resources_for_project() to map projects to actual accessible compute resources.
  6. Defining JobSpec and Job objects, adding them to an AsyncSession.
  7. Using AsyncSession plan(), apply(), wait(), and destroy() to manage the job lifecycle.

Usage::

    pip install amscrot-py[async]

    python async_discover_and_submit.py
    python async_discover_and_submit.py --directory /my/working/dir --account my-project

Requires ~/.amscrot/credentials.yml with valid client profiles.
"""

import argparse
import asyncio
import sys

from amscrot.client import AsyncClient
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import PlanError, CreateError


async def setup_and_submit(client, session, args):
    """Fresh session setup: discover resources, plan, and submit jobs."""
    service_clients = client.get_service_client()
    print(f"Discovered {len(service_clients)} service client(s) total.")

    nersc_client = client.get_service_client("nersc")
    esnet_client = client.get_service_client("esnet-east")

    target_clients = [c for c in [nersc_client, esnet_client] if c and c._available]

    if not target_clients:
        print("ERROR: Neither NERSC nor ESnet-East service clients are available. Check credentials.yml.")
        sys.exit(1)

    print(f"Selected Service Client(s): {[sc.name for sc in target_clients]}")

    selected_resources = []

    for target_client in target_clients:
        print(f"\n======================================================================")
        print(f"Processing Facility Client: {target_client.name} ({target_client.api_endpoint})")
        print(f"======================================================================")

        # Discover normalized facility details including projects and resources
        # metadata() is async — makes API calls
        discovery_result = await session.metadata(target_client.name, native=False)
        if not discovery_result.facilities:
            print(f"WARNING: No facilities discovered for {target_client.name}, skipping.")
            continue

        fac = discovery_result.facilities[0]
        print(f"Facility Name: {fac.name}")

        # Use resources_for_project to help the user find the correct resource for submission
        print("\n--- Mapping Project Allocations to Resources ---")
        selected_project = None
        selected_resource_name = None
        selected_resource_id = None

        for project in (fac.projects or []):
            print(f"\nProject: {project.name}")
            proj_resources = fac.resources_for_project(project.name)
            cap_map = proj_resources.get(project.name, {})

            for cap, res_map in cap_map.items():
                print(f"  Capability: {cap}")
                for cat, resources in res_map.items():
                    res_names = [r.name for r in resources]
                    print(f"    {cat.capitalize()}: {', '.join(res_names)}")
                    # Pick the first compute resource we find for submission
                    if cat == "compute" and not selected_resource_name:
                        selected_project = project.name
                        selected_resource_name = resources[0].name
                        selected_resource_id = resources[0].id

        if not selected_resource_name:
            print(f"\nWARNING: No compute resources found for any project allocation at {fac.name}, skipping.")
            continue

        # Set up default directory
        default_dir = "/tmp"
        if "nersc" in target_client.name.lower():
            default_dir = "/global/homes/k/kissel"
        elif "esnet" in target_client.name.lower():
            default_dir = "/data/home/kissel"

        res_name = selected_resource_name
        account_name = args.account or selected_project
        dir_path = args.directory or default_dir
        res_id = selected_resource_id

        print(f"\nAdding Job for {fac.name} to Session:")
        print(f"  Resource:  {res_name} (ID: {res_id})")
        print(f"  Account:   {account_name}")
        print(f"  Directory: {dir_path}")
        print(f"  Queue:     {args.queue}")

        selected_resources.append((fac.name, res_name, res_id))

        # Standard resources block
        resources = {
            "node_count": 1,
            "process_count": 1,
            "processes_per_node": 1,
            "cpu_cores_per_process": 1,
            "gpu_cores_per_process": None,
            "exclusive_node_use": False,
            "memory": 268435456,
        }

        # Build JobSpec
        spec = JobSpec(
            executable="/bin/echo",
            arguments=[f"Hello from {fac.name}"],
            resources=resources,
            attributes={
                "directory": dir_path,
                "duration": 300,
                "queue_name": args.queue,
                "account": account_name,
                "stdout_path": "stdout.log",
                "stderr_path": "stderr.log",
            }
        )

        # Build Job object and add it to the Session (sync — no I/O)
        job = Job(
            name=f"job-{target_client.name}",
            type=JobType.COMPUTE,
            resource_id=res_id,
            service_type=JobServiceType.BATCH,
            service_client=target_client,
            job_spec=spec
        )
        session.add_job(job)

    if not session.jobs:
        print("\nERROR: No jobs were added to the session.")
        sys.exit(1)

    # Print selected resources summary
    print("\n======================================================================")
    print("Selected Resources Summary")
    print("======================================================================")
    for fac_name, res_name, res_id in selected_resources:
        print(f"  Facility: {fac_name}")
        print(f"    Resource Name: {res_name}")
        print(f"    Resource ID:   {res_id}")

    # 1. Plan Phase (async — makes API calls)
    print("\n======================================================================")
    print("Session Plan Phase")
    print("======================================================================")
    try:
        plan_result = await session.plan(verbose=True)
        print("Plan succeeded.")
    except PlanError as e:
        print("Plan failed:")
        for err in e.errors:
            print(f"  - {err}")
        sys.exit(1)

    # 2. Apply Phase (async — makes API calls)
    print("\n======================================================================")
    print("Session Apply Phase (Submitting Jobs)")
    print("======================================================================")
    try:
        await session.apply()
        print("All jobs successfully submitted.")
    except CreateError as e:
        print("Apply failed:")
        for err in e.errors:
            print(f"  - {err}")
        sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(description="Async: Submit jobs to discovered IRI facilities via Session.")
    parser.add_argument("--directory", help="Remote working directory for the jobs")
    parser.add_argument("--account", help="Project account to charge")
    parser.add_argument("--queue", default="debug", help="Queue to submit to (default: debug)")
    args = parser.parse_args()

    print("--- Initializing AsyncClient and Discovering Endpoints ---")

    # Setting discover_endpoints=True queries the IRO registry to auto-generate ServiceClient instances.
    # The context manager calls await client.initialize() which performs the async I/O.
    async with AsyncClient(discover_endpoints=True) as client:

        # Create or restore session from disk (async — file I/O)
        session = await client.create_session("discover-and-submit-session")

        if session.jobs:
            # Session restored from disk — skip straight to monitoring
            print(f"\n--- Restored existing session 'discover-and-submit-session' from disk ---")
            for job in session.jobs:
                print(f"  Job {job.name}: ID={job.id}, Status={job.status}")
        else:
            # Fresh session — discover, plan, submit
            await setup_and_submit(client, session, args)

        # 3. Wait Phase — uses native asyncio.sleep() polling instead of time.sleep()
        print("\n======================================================================")
        print("Session Wait Phase (Monitoring Jobs)")
        print("======================================================================")
        try:
            results = await session.wait(
                timeout=300.0,
                interval=5.0,
                verbose=True,
            )
        except Exception as e:
            print(f"Error waiting for jobs: {e}")
            sys.exit(1)

        print("\n--- Final Job States ---")
        for job_name, status in results.items():
            print(f"  {job_name}: state={status.state}, exit_code={status.exit_code}")

        # 4. Destroy Phase (async — cleanup API calls)
        print("\n======================================================================")
        print("Session Destroy Phase (Cleanup)")
        print("======================================================================")
        try:
            await session.destroy()
            print("Session destroyed successfully.")
        except Exception as e:
            print(f"Warning: Cleanup failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
