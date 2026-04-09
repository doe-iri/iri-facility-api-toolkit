"""
esnet_iri_example -- Demo Airflow DAG that submits an echo job on ESnet IRI east,
fetches stdout, and logs its contents.

Task graph:
  discover_resource >> submit_job >> read_output

- discover_resource (AmscrotDiscoverOperator):
    Calls the IRI discovery API, finds the first available compute resource,
    and pushes its resource_id to XCom.

- submit_job (IriJobSubmitOperator):
    Uses amscrot Client + Session to plan, submit, wait, and fetch output files
    all within a single Airflow task. Pulls resource_id from discover_resource
    XCom. XCom carries job_id and local file paths to downstream tasks.

- read_output (IriReadOutputOperator):
    Reads the local stdout/stderr files from XCom and logs their contents.
    Requires no API calls -- just file I/O.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG

from amscrot_airflow import (
    AmscrotDiscoverOperator,
    IriJobSubmitOperator,
    IriReadOutputOperator,
)

# ---------------------------------------------------------------------------
# Configuration -- edit these to match your site
# ---------------------------------------------------------------------------
PROFILE = "esnet-iri-east"           # credentials.yml profile
OUTPUT_DIR = "/tmp/airflow_amscrot"  # local directory for downloaded output files

# ---------------------------------------------------------------------------
# Default args
# ---------------------------------------------------------------------------
default_args = {
    "owner": "amscrot",
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
}

# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id="esnet_iri_example",
    description="Discover resource, submit an echo job on ESnet IRI, and read stdout",
    schedule=None,          # trigger manually
    start_date=datetime(2026, 3, 3),
    catchup=False,
    default_args=default_args,
    tags=["amscrot", "iri", "esnet"],
) as dag:

    # Common operator kwargs for all three tasks
    base_kwargs = dict(
        session_name="airflow-esnet-iri",
        service_type="amsc-iri",
        service_name="iri-east",
        profile=PROFILE,
    )

    # Task 1: discover the first available compute resource on the IRI site
    # and push resource_id to XCom for submit_job to consume.
    discover_resource = AmscrotDiscoverOperator(
        task_id="discover_resource",
        resource_index=0,
        **base_kwargs,
    )

    # Task 2: submit job, wait for completion, and fetch output files.
    # Pulls resource_id from discover_resource XCom -- no hardcoded UUIDs needed.
    submit_job = IriJobSubmitOperator(
        task_id="submit_job",
        **base_kwargs,
        # IriJobSubmitOperator args
        job_name="airflow-echo-job",
        executable="/bin/echo",
        arguments=["Hello from Airflow"],
        iri_resources={
            "node_count": 1,
            "process_count": 1,
            "processes_per_node": 1,
            "cpu_cores_per_process": 1,
            "gpu_cores_per_process": None,
            "exclusive_node_use": False,
            "memory": 268435456,
        },
        attributes={
            "directory": "/data/home/kissel",
            "duration": 120,
            "queue_name": "debug",
            "account": "interactive",
            "stdout_path": "/data/home/kissel/airflow_amscrot_stdout.log",
            "stderr_path": "/data/home/kissel/airflow_amscrot_stderr.log",
        },
        resource_id_task_id="discover_resource",   # pull resource_id from XCom
        fetch_output=True,
        output_path=OUTPUT_DIR,
        wait_timeout=300.0,
        wait_interval=5.0,
    )

    # Task 3: read the local output files left by submit_job and log them.
    # No API calls needed -- just reads files from the path in XCom.
    read_output = IriReadOutputOperator(
        task_id="read_output",
        target_task_id="submit_job",
        log_output=True,
    )

    # DAG dependency chain
    discover_resource >> submit_job >> read_output
