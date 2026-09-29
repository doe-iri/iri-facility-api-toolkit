"""
Auto-Discover and Submit Jobs to Discovered or Configured Facilities via Session
================================================================================

Demonstrates:
  1. Initializing the Client with discover_endpoints=True to query the IRO
     discovery endpoint and automatically register ServiceClient instances.
  2. Specifying site entries from credentials.yml on the command line (--site / -s).
  3. Resolving site profiles (direct or RIG) or discovered shorthands to ServiceClient instances.
  4. Session persistence -- if a prior session exists on disk, skips straight to monitoring,
     or use --new-session to force a fresh run.
  5. Querying normalized discovery results to inspect project allocations.
  6. Using resources_for_project() to map projects to actual accessible compute resources.
  7. Defining JobSpec and Job objects, adding them to a Session.
  8. Using Session plan(), apply(), wait(), and destroy() to manage the job lifecycle.
  9. Fetching and displaying job stdout/stderr after completion via fetch_output_files().

Usage:
  python discover_and_submit_iri.py
  python discover_and_submit_iri.py --site nersc-iri
  python discover_and_submit_iri.py --site nersc-iri -s esnet-iri-east
  python discover_and_submit_iri.py --sites nersc-iri,esnet-iri-east
  python discover_and_submit_iri.py --site nersc-iri-rig --new-session
  python discover_and_submit_iri.py --list-sites
  python discover_and_submit_iri.py --directory /my/working/dir --account my-project
  python discover_and_submit_iri.py --refresh-discovery

Requires ~/.amscrot/credentials.yml with valid client profiles.
"""

import argparse
import getpass
import os
import sys
from typing import List, Optional

from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec
from amscrot.serviceclient import PlanError, CreateError, ServiceClient
from amscrot.util.constants import Constants
from amscrot.util import state as sutil


def resolve_sites(client: Client, requested_sites: List[str]) -> List[ServiceClient]:
    """Resolve requested site names to ServiceClient instances using client.get_service_client()."""
    target_clients = []
    for site_name in requested_sites:
        sc = client.get_service_client(site_name)
        if sc and getattr(sc, "_available", True):
            if sc not in target_clients:
                target_clients.append(sc)
        else:
            available_clients = [c.name for c in client.get_service_client()]
            print(f"ERROR: Service client '{site_name}' not found.")
            print(f"  Available service clients: {available_clients}")
            sys.exit(1)

    return target_clients


def setup_and_submit(client: Client, session, target_clients: List[ServiceClient], args):
    """Fresh session setup: discover resources, plan, and submit jobs."""
    selected_resources = []

    for target_client in target_clients:
        print(f"\n======================================================================")
        print(f"Processing Facility Client: {target_client.name} ({target_client.api_endpoint})")
        print(f"======================================================================")

        # Ensure the client is attached to the session
        if target_client.name not in session._service_clients:
            session.add_service_client(target_client)

        # Discover normalized facility details including projects and resources
        discovery_result = session.metadata(target_client.name, refresh=args.refresh_discovery, native=False)
        if not discovery_result.facilities:
            print(f"WARNING: No facilities discovered for {target_client.name}, skipping.")
            continue

        fac = discovery_result.facilities[0]
        print(f"Facility Name: {fac.name}")

        # Use resources_for_project to help find the correct compute resource
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
                    # Pick the first compute resource found for submission
                    if cat == "compute" and not selected_resource_name:
                        selected_project = project.name
                        selected_resource_name = resources[0].name
                        selected_resource_id = resources[0].id

        if not selected_resource_name:
            print(f"\nWARNING: No compute resources found for any project allocation at {fac.name}, skipping.")
            continue

        # Set up default directory
        username = args.user or os.environ.get("USER")
        if not username:
            try:
                username = getpass.getuser()
            except Exception:
                username = None

        ident = f"{target_client.name} {fac.name}".lower()
        is_esnet = "esnet" in ident

        if username:
            if "nersc" in ident:
                default_dir = f"/global/homes/{username[0].lower()}/{username}"
            elif is_esnet:
                default_dir = f"/data/home/{username}"

        res_name = selected_resource_name
        dir_path = args.directory or default_dir
        res_id = selected_resource_id

        # Site-specific customizations (ESnet uses 'interactive' account, exclusive node use, etc.)
        account_name = args.account or ("interactive" if is_esnet else selected_project)
        job_duration = args.duration if args.duration is not None else (600 if is_esnet else 300)
        exclusive_node_use = True if is_esnet else False
        stdout_path = f"{dir_path}/stdout.log" if is_esnet else "stdout.log"
        stderr_path = f"{dir_path}/stderr.log" if is_esnet else "stderr.log"
        container_image = args.image or ("debian:latest" if is_esnet else None)

        print(f"\nAdding Job for {fac.name} to Session:")
        print(f"  Resource:  {res_name} (ID: {res_id})")
        print(f"  Account:   {account_name}")
        print(f"  Directory: {dir_path}")
        print(f"  Queue:     {args.queue}")
        print(f"  Duration:  {job_duration}s")
        print(f"  Exclusive: {exclusive_node_use}")
        if container_image:
            print(f"  Container: {container_image}")

        selected_resources.append((fac.name, res_name, res_id))

        # Standard resources block
        resources = {
            "node_count": 1,
            "process_count": 1,
            "processes_per_node": 1,
            "cpu_cores_per_process": 1,
            "exclusive_node_use": exclusive_node_use,
            "memory": 268435456,
        }

        # Build Job attributes
        attributes = {
            "directory": dir_path,
            "duration": job_duration,
            "queue_name": args.queue,
            "account": account_name,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
        }
        if container_image:
            attributes["container"] = {"image": container_image}

        # Build JobSpec
        exec_args = args.arguments if args.arguments is not None else [f"Hello from {fac.name}"]
        spec = JobSpec(
            executable=args.executable,
            arguments=exec_args,
            resources=resources,
            attributes=attributes,
        )

        # Build Job object and add it to the Session
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

    # 1. Plan Phase
    print("\n======================================================================")
    print("Session Plan Phase")
    print("======================================================================")
    try:
        plan_result = session.plan(verbose=True)
        print("Plan succeeded.")
    except PlanError as e:
        print("Plan failed:")
        for err in e.errors:
            print(f"  - {err}")
        sys.exit(1)

    # 2. Apply Phase
    print("\n======================================================================")
    print("Session Apply Phase (Submitting Jobs)")
    print("======================================================================")
    try:
        session.apply()
        print("All jobs successfully submitted.")
    except CreateError as e:
        print("Apply failed:")
        for err in e.errors:
            print(f"  - {err}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Submit jobs to discovered or configured IRI facilities via Session."
    )
    parser.add_argument(
        "-s", "--site", "--sites",
        action="append",
        dest="sites",
        help="Site entry/profile name(s) from credentials.yml (e.g. nersc-iri, esnet-iri-east, nersc-iri-rig) "
             "or shorthand names (nersc, esnet-east). Default: esnet-east. Can be specified multiple times or comma-separated."
    )
    parser.add_argument(
        "--list-sites",
        action="store_true",
        default=False,
        help="List available credential profiles from credentials.yml and discovered facilities, then exit."
    )
    parser.add_argument(
        "--new-session",
        action="store_true",
        default=False,
        help="Start a fresh session, clearing any existing saved session state from disk."
    )
    parser.add_argument(
        "--session-name",
        default="discover-and-submit-session",
        help="Session name to use (default: discover-and-submit-session)."
    )
    parser.add_argument(
        "--credential-file",
        default=None,
        help="Path to credentials file (default: ~/.amscrot/credentials.yml)."
    )
    parser.add_argument("--directory", help="Remote working directory for the jobs (overrides default derived from --user)")
    parser.add_argument(
        "-u", "--user",
        default=None,
        help="Remote username for deriving default home directories. Defaults to local user."
    )
    parser.add_argument("--account", help="Project account to charge")
    parser.add_argument("--queue", default="debug", help="Queue to submit to (default: debug)")
    parser.add_argument("--executable", default="/bin/echo", help="Executable to run (default: /bin/echo)")
    parser.add_argument("--arguments", nargs="*", default=None, help="Arguments for executable (default: Hello from <facility>)")
    parser.add_argument("--image", default=None, help="Container image to use (default: debian:latest for ESnet)")
    parser.add_argument("--duration", type=int, default=None, help="Job duration limit in seconds (default: 600 for ESnet, 300 for others)")
    parser.add_argument("--timeout", type=float, default=300.0, help="Wait timeout in seconds (default: 300.0)")
    parser.add_argument("--interval", type=float, default=5.0, help="Wait polling interval in seconds (default: 5.0)")
    parser.add_argument("--refresh-discovery", action="store_true", default=False,
                        help="Force a refresh of the discovery cache instead of using cached results")
    parser.add_argument("--no-wait", action="store_true", default=False,
                        help="Submit jobs and exit without waiting for completion")
    parser.add_argument("--no-destroy", action="store_true", default=False,
                        help="Keep the session on disk after completion without destroying")
    args = parser.parse_args()

    # Parse requested sites list (default: esnet-east)
    requested_sites = []
    if args.sites:
        for s in args.sites:
            for part in s.split(","):
                part = part.strip()
                if part and part not in requested_sites:
                    requested_sites.append(part)
    if not requested_sites:
        requested_sites = ["esnet-east"]

    print("--- Initializing Client and Discovering Endpoints ---")
    client = Client(
        credential_file=args.credential_file,
        create_service_clients=True,
        discover_endpoints=True,
    )
    # Ensure credentials are fully loaded
    client.load_credentials(file_path=args.credential_file)

    # If --list-sites is requested, display and exit
    if args.list_sites:
        print("\nAvailable Credential Profiles (from credentials.yml):")
        for p in client.list_credentials():
            cred = client.get_credential(p)
            ctype = getattr(cred, "client_type", "unknown")
            endpoint = getattr(cred, "api_endpoint", "n/a")
            ver = getattr(cred, "api_version", "auto")
            print(f"  - {p} (type={ctype}, endpoint={endpoint}, api_version={ver})")
        print("\nDiscovered Service Clients:")
        for sc in client.get_service_client():
            print(f"  - {sc.name} ({getattr(sc, 'api_endpoint', 'n/a')})")
        return

    # Handle --new-session by removing existing state file
    if args.new_session:
        sutil.delete_jobs(args.session_name)

    # Create or restore session from disk
    session = client.create_session(args.session_name)

    if session.jobs and not args.new_session:
        # Session restored from disk -- skip straight to monitoring
        print(f"\n--- Restored existing session '{args.session_name}' from disk ---")
        for job in session.jobs:
            print(f"  Job {job.name}: ID={job.id}, Status={job.status}")
    else:
        # Fresh session -- resolve sites, discover, plan, submit
        target_clients = resolve_sites(client, requested_sites)
        print(f"Selected Service Client(s): {[sc.name for sc in target_clients]}")
        setup_and_submit(client, session, target_clients, args)

    if args.no_wait:
        print("\n--no-wait specified; exiting after job submission.")
        return

    # 3. Wait Phase (Monitoring)
    print("\n======================================================================")
    print("Session Wait Phase (Monitoring Jobs)")
    print("======================================================================")
    try:
        results = session.wait(
            timeout=args.timeout,
            interval=args.interval,
            verbose=True,
        )
    except Exception as e:
        print(f"Error waiting for jobs: {e}")
        sys.exit(1)

    print("\n--- Final Job States ---")
    for job_name, status in results.items():
        print(f"  {job_name}: state={status.state}, exit_code={status.exit_code}")

    # 4. Fetch Job Output (stdout/stderr)
    print("\n======================================================================")
    print("Fetching Job Output (stdout/stderr)")
    print("======================================================================")
    try:
        fetched = session.fetch_output_files()
        if fetched:
            for job_name, file_map in fetched.items():
                print(f"\n--- Output for {job_name} ---")
                for stream, local_path in file_map.items():
                    print(f"\n  [{stream}] ({local_path}):")
                    try:
                        with open(local_path, "r") as f:
                            content = f.read()
                        if content.strip():
                            for line in content.splitlines():
                                print(f"    {line}")
                        else:
                            print("    (empty)")
                    except OSError as read_err:
                        print(f"    (could not read file: {read_err})")
        else:
            print("No output files were fetched (jobs may lack stdout/stderr paths).")
    except Exception as e:
        print(f"Warning: Failed to fetch job output: {e}")

    # 5. Destroy Phase (Cleanup)
    if not args.no_destroy:
        print("\n======================================================================")
        print("Session Destroy Phase (Cleanup)")
        print("======================================================================")
        try:
            session.destroy()
            print("Session destroyed successfully.")
        except Exception as e:
            print(f"Warning: Cleanup failed: {e}")


if __name__ == "__main__":
    main()
