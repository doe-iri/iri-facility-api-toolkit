"""
gpt2_training_job -- Airflow DAG that trains a small GPT-2 style language model
on ESnet IRI east using Docker image ``quay.io/amscesnet/minigpt:dev``.

This DAG mirrors the job definition in Section 5 of the
``amsc_gpt2_training_job`` Jupyter notebook.

Task graph:
  discover_resource >> submit_job >> read_output

- discover_resource (AmscrotDiscoverOperator):
    Calls the IRI discovery API, locates the first available compute resource,
    and pushes its resource_id to XCom.

- submit_job (IriJobSubmitOperator):
    Builds and submits the GPT-2 training job using the bash payload defined
    below.  Pulls resource_id from discover_resource via XCom, then plans,
    submits, waits for completion, and fetches stdout/stderr into OUTPUT_DIR.

- read_output (IriReadOutputOperator):
    Reads the local stdout/stderr log files pushed to XCom by submit_job and
    logs their contents.  No additional API calls are made.
"""
from __future__ import annotations

import textwrap
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
PROFILE = "esnet-iri-east"              # credentials.yml profile
JOB_DIR = "/data/home/kissel"          # remote working directory
OUTPUT_DIR = "/tmp/airflow_amscrot"    # local directory for downloaded logs

IMAGE = "quay.io/amscesnet/minigpt:dev"

# Training parameters
NUM_STEPS = 1000
NUM_LINES = 1000000

# ---------------------------------------------------------------------------
# Bash payload executed inside the container on the compute node.
# Using textwrap.dedent so there is no leading indentation in the script.
# ---------------------------------------------------------------------------
BASH_PAYLOAD = textwrap.dedent(f"""\
    set -euo pipefail

    INPUT_FILE="{JOB_DIR}/synthetic_training_data_1g.txt"
    OUTPUT_DIR_REMOTE="{JOB_DIR}/amsc-iri-demo-results-$(date -u +%Y%m%d-%H%M%S)"

    echo "=== MiniGPT training job ==="
    echo "UTC now: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "Hostname: $(hostname)"
    echo "Input file: ${{INPUT_FILE}}"
    echo "Output dir: ${{OUTPUT_DIR_REMOTE}}"

    mkdir -p "${{OUTPUT_DIR_REMOTE}}"

    echo "Starting training..."

    python3 /root/tiny_gpt2_cpu_1k.py \\
        "${{INPUT_FILE}}" \\
        "${{OUTPUT_DIR_REMOTE}}" \\
        {NUM_STEPS} \\
        {NUM_LINES}

    echo "Training finished."
    echo "Output directory contents:"
    ls -lah "${{OUTPUT_DIR_REMOTE}}"
""")

# ---------------------------------------------------------------------------
# Default args
# ---------------------------------------------------------------------------
default_args = {
    "owner": "amscrot",
    "retries": 0,
    "retry_delay": timedelta(minutes=5),
}

# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id="gpt2_training_job",
    description="Discover resource, train a GPT-2 model on ESnet IRI east, and read logs",
    schedule=None,          # trigger manually
    start_date=datetime(2026, 3, 3),
    catchup=False,
    default_args=default_args,
    tags=["amscrot", "iri", "esnet", "gpt2", "ml"],
) as dag:

    # Shared kwargs for all amscrot operators
    base_kwargs = dict(
        session_name="airflow-gpt2-training",
        service_type="esnet-iri",
        service_name="iri-east",
        profile=PROFILE,
    )

    # ------------------------------------------------------------------
    # Task 1: Discover the first available compute resource at the IRI
    # site and push its resource_id to XCom.
    # ------------------------------------------------------------------
    discover_resource = AmscrotDiscoverOperator(
        task_id="discover_resource",
        resource_index=0,
        **base_kwargs,
    )

    # ------------------------------------------------------------------
    # Task 2: Build and submit the GPT-2 training job.
    # The bash payload is passed as the sole argument to `bash -lc`.
    # resource_id is pulled automatically from the discover task XCom.
    # ------------------------------------------------------------------
    submit_job = IriJobSubmitOperator(
        task_id="submit_job",
        **base_kwargs,
        # Job identity
        job_name="gpt2-training-job",
        # Executable + bash payload (mirrors notebook Section 5)
        executable="bash",
        arguments=["-lc", BASH_PAYLOAD],
        # Compute resources (mirrors common_resources in the notebook)
        iri_resources={
            "node_count": 1,
            "process_count": 1,
            "processes_per_node": 1,
            "cpu_cores_per_process": 4,
            "gpu_cores_per_process": None,
            "exclusive_node_use": False,
            "memory": 4000000000,
        },
        # Job attributes (mirrors esnet_attributes in the notebook)
        attributes={
            "container": {"image": IMAGE},
            "inherit_environment": True,
            "directory": JOB_DIR,
            "duration": 7200,
            "queue_name": "debug",
            "account": "interactive",
            "stdout_path": f"{JOB_DIR}/minigpt_stdout.log",
            "stderr_path": f"{JOB_DIR}/minigpt_stderr.log",
        },
        # Pull resource_id from the discover task XCom
        resource_id_task_id="discover_resource",
        # Fetch stdout/stderr after completion
        fetch_output=True,
        output_path=OUTPUT_DIR,
        wait_timeout=7200.0,    # 2 hours, matching job duration
        wait_interval=15.0,
    )

    # ------------------------------------------------------------------
    # Task 3: Read the downloaded log files and print their contents.
    # ------------------------------------------------------------------
    read_output = IriReadOutputOperator(
        task_id="read_output",
        target_task_id="submit_job",
        log_output=True,
    )

    # DAG dependency chain
    discover_resource >> submit_job >> read_output
