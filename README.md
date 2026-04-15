# Table of contents

 - [Description](#descr)
 - [Installation](#install)
 - [Operating Instructions](#operate)
 - [Jupyter Notebook Examples](#jupyter)
 - [Apache Airflow Support](#airflow)

# <a name="descr"></a>Description
The American Science Cloud Infrastructure Services Resource Orchestration Toolkit (AmSC-ISRO-Toolkit [AmSCROT]) provides _infrastructure_ orchestration for AmSC use.

# <a name="install"></a>Installation

```
pip install amscrot-py
```

# <a name="operate"></a>Operation Instructions

## Credentials

AmSCROT reads provider credentials from `~/.amscrot/credentials.yml`. Each section key corresponds to a service type or profile name:

```yaml
esnet-iri-east:
  client_type: AMSC_IRI
  api_key: <token>
  api_endpoint: https://iri-dev.ppg.es.net

nersc-iri:
  client_type: AMSC_IRI
  api_key: <token>
  api_endpoint: https://api.iri.nersc.gov

amsc-iro:
  client_type: AMSC_IRO
  api_key: <token>
  api_endpoint: https://...
```

An example credentials file is provided in [credentials-template.yml](examples/client/credentials-template.yml).


## Core Concepts

| Class | Role |
|---|---|
| `Client` | Top-level entry point; owns sessions and service clients |
| `ServiceClient` | Provider-specific driver (Kube/Kueue, ESnet IRI, NERSC IRI, AMSC-IRO) |
| `Session` | Named unit of work; groups jobs and persists state to disk |
| `Job` | A single compute task bound to a `ServiceClient` |
| `JobSpec` | Declares executable, arguments, resources, and provider attributes |
| `DiscoveryResult` | Typed result from `service_client.discover()` |

## Basic Usage

AmSCROT offers three ways to set up service clients: **automatic discovery**, **automatic generation**, and **manual definition**. Each require credentials in `~/.amscrot/credentials.yml`.

### Option A: Automatic Endpoint Discovery (recommended)

```python
from amscrot.client.client import Client

client = Client(discover_endpoints=True)
```

With `discover_endpoints=True`, the `Client` queries the AmSC IRO facility registry and automatically creates an `IriServiceClient` for each discovered facility. Credentials are matched by comparing each facility's `api_endpoint` against your `credentials.yml` profiles that have `client_type: AMSC_IRI`:

```yaml
# ~/.amscrot/credentials.yml
nersc-iri:
  client_type: AMSC_IRI
  api_key: <token>
  api_endpoint: https://api.iri.nersc.gov

alcf-iri:
  client_type: AMSC_IRI
  api_key: <token>
  api_endpoint: https://api.alcf.anl.gov
```

**Token resolution order** per discovered facility:
1. **Credential profile match** — if a profile with `client_type: AMSC_IRI` has a matching `api_endpoint`, that profile is used.
2. **`AMSC_TOKEN` env var** — if no profile matches, the `AMSC_TOKEN` environment variable is used as a fallback.
3. **Skip** — if neither is available, the facility is skipped with a warning.

Service clients are named using a slugified version of the facility name (e.g., `"Argonne Leadership Computing Facility"` → `"argonne-leadership-computing-facility"`):

```python
# Access auto-discovered clients by name
nersc = client.get_service_client("national-energy-research-scientific-computing-center")
alcf  = client.get_service_client("argonne-leadership-computing-facility")

# List all discovered clients
print("Discovered:", [sc.name for sc in client.service_clients])
```

### Option B: Auto-Create from Credentials File

```python
from amscrot.client.client import Client

client = Client(create_service_clients=True)
```

With `create_service_clients=True`, the `Client` reads `~/.amscrot/credentials.yml` and creates a `ServiceClient` for every entry that has a `client_type` field. Each credential profile becomes a service client named after its YAML key:

```yaml
# Creates two service clients: "nersc-iri" and "esnet-iri-east"
nersc-iri:
  client_type: AMSC_IRI
  api_key: <token>
  api_endpoint: https://api.iri.nersc.gov

esnet-iri-east:
  client_type: AMSC_IRI
  api_key: <token>
  api_endpoint: https://iri-dev.ppg.es.net
```

```python
nersc = client.get_service_client("nersc-iri")
east  = client.get_service_client("esnet-iri-east")
```

This mode does **not** contact any external registry — it works entirely from your local credentials file. Entries without `client_type` are skipped with a warning.

### Option C: Manual ServiceClient Definition

Use a credential profile from `credentials.yml`:

```python
from amscrot.client.client import Client
from amscrot.serviceclient import ServiceClient
from amscrot.util.constants import Constants

client = Client()

svc = ServiceClient.create(
    type=Constants.ServiceType.AMSC_IRI,
    name="nersc-compute",
    profile="nersc-iri"           # matches credentials.yml section
)
client.add_service_client(svc)
```

Or define credentials entirely in code — no `credentials.yml` needed:

```python
client = Client()

# Add credentials programmatically
client.add_credential(
    profile="my-nersc",
    client_type="AMSC_IRI",
    api_key="<token>",
    api_endpoint="https://api.iri.nersc.gov"
)

svc = ServiceClient.create(
    type=Constants.ServiceType.AMSC_IRI,
    name="nersc-compute",
    profile="my-nersc"
)
client.add_service_client(svc)
```

With manual setup, you control exactly which service clients exist, their names, and which credential profiles they use. This is useful for testing, notebooks, or when credentials come from environment variables or a secrets manager.

### When to Use Each

| | `discover_endpoints` | `create_service_clients` | Manual `ServiceClient.create()` |
|---|---|---|---|
| **Setup** | One line | One line | Explicit per-client |
| **Source** | IRO facility registry (remote) | `credentials.yml` (local) | Code |
| **Naming** | Auto-slugified from registry | YAML key names | You choose |
| **Credentials** | Matched by `api_endpoint` | Direct from each entry | Explicit `profile=` |
| **Best for** | Multi-site, dynamic environments | Stable multi-facility setups | Testing, custom configs |
| **Requires** | IRO registry reachable | `client_type` in credentials | Only the credential profile |

### 2. Discover Available Resources

```python
result = svc.discover()      # returns DiscoveryResult

# Iterate typed resources
for item in result.by_type("compute"):
    print(item.data["id"], item.data["name"])

# Normalized Facility objects (provider-agnostic)
for facility in result.facilities:
    print(facility.name, [c.cores for c in (facility.compute or [])])
```

### 3. Define a Job

```python
from amscrot.client.job import Job, JobSpec, JobType, JobServiceType

spec = JobSpec(
    executable="python",
    arguments=["-c", "print('hello')"],
    resources={
            "node_count": 1,
            "process_count": 1,
            "processes_per_node": 1,
            "cpu_cores_per_process": 1,
            "exclusive_node_use": False,
            "memory": 268435456
    },
    attributes={
        "container": {"image": "python:3.12-slim"},  # provider image
        "resource_id": "<compute-resource-id>"       # from discovery
    }
)

job = Job(
    name="my-job",
    type=JobType.COMPUTE,
    service_type=JobServiceType.BATCH,
    service_client=svc,
    job_spec=spec
)
```

### 4. Create a Session and Submit

```python
session = client.create_session("my-session")
session.add_job(job)

# Validate (raises PlanError on failure)
session.plan(verbose=True)

# Submit all jobs
session.apply()
```

### 5. Wait for Completion

```python
from amscrot.client.job import JobState

results = session.wait(
    timeout=300,
    interval=5,
    verbose=True,
)

for job_name, status in results.items():
    print(f"{job_name}: {status.state}  message={status.message}")
```

`session.wait()` polls until all jobs reach a terminal state (`COMPLETED`, `FAILED`, or `CANCELED`). Pass `jobs=[job1, job2]` to wait on a subset.

### 6. Clean Up

```python
session.destroy()   # cancels running jobs and removes session state
```

Sessions are persisted to `~/.amscrot/sessions/<session-name>/` so they survive process restarts. An existing session is restored automatically on `client.create_session(name)`.

### 7. Fetch Output Files (IRI providers)

After a job completes, stdout/stderr can be downloaded from the remote filesystem:

```python
# Include stdout/stderr paths in the job spec attributes
spec = JobSpec(
    executable="python",
    arguments=["-c", "print('done')"],
    attributes={
        "resource_id": "<compute-resource-id>",
        "directory": "/path/to/workdir",        # remote working directory
        "stdout_path": "/path/to/workdir/out.log",
        "stderr_path": "/path/to/workdir/err.log",
    }
)

# After session.wait() returns COMPLETED:
fetched = session.fetch_output_files(jobs=[job])
# fetched == {"my-job": {"stdout": "/local/.amscrot/sessions/my-session/files/my-job/stdout.log",
#                        "stderr": "/local/.amscrot/sessions/my-session/files/my-job/stderr.log"}}
```

Files are written to `~/.amscrot/sessions/<session-name>/files/<job-name>/` by default. Pass `output_path=` to override.

### 8. Direct Filesystem Access (IRI providers)

ESnet IRI and NERSC IRI service clients expose an `IriFilesystem` interface for direct file operations independent of job submission:

```python
fs = svc.filesystem          # IriFilesystem instance (None if client unavailable)

# Upload a local file to remote storage
fs.upload(storage_resource_id, local_path="/tmp/input.txt", remote_path="/scratch/input.txt")

# Download a remote file
fs.download(storage_resource_id, remote_path="/scratch/out.log", local_path="/tmp/out.log")

# List a remote directory
entries = fs.list(storage_resource_id, remote_path="/scratch/")

# Compute checksum of a remote file
checksum = fs.checksum(storage_resource_id, remote_path="/scratch/data.tar")

# Create a tar archive of a remote directory
fs.compress(storage_resource_id, remote_path="/scratch/results/", archive_path="/scratch/results.tar.gz")
```

`storage_resource_id` is the UUID of a storage resource from `svc.discover()`. For most IRI deployments, the home storage resource is auto-resolved when calling `session.fetch_output_files()`.

## Kubernetes / Kueue Jobs

```python
spec = JobSpec(
    executable="sleep",
    arguments=["30"],
    resources={"requests": {"cpu": "1", "memory": "1Gi"}},
    attributes={
        "container": {"image": "busybox"},
        "namespace": "default",
        "labels": {"kueue.x-k8s.io/queue-name": "compute-queue"},
        "completions": 1,
        "restartPolicy": "Never"
    }
)
```

See [`scripts/kube/setup-kueue.sh`](scripts/kube/setup-kueue.sh) to install Kueue and create the required `ResourceFlavor`, `ClusterQueue`, `LocalQueue`, and `PriorityClass` resources on your cluster.


# <a name="jupyter"></a>Jupyter Notebook Examples

Interactive notebooks are provided under [`examples/notebooks/client/`](examples/notebooks/client/).

| Notebook | Description |
|---|---|
| [amsc_hello_world](examples/notebooks/client/amsc_hello_world.ipynb) | **Start here.** Walks through installation, credential setup, creating a `Client`/`Session`, submitting a job, monitoring with `session.wait()`, and cleanup with `session.destroy()`. |
| [amsc_gpt2_training_job](examples/notebooks/client/amsc_gpt2_training_job.ipynb) | Submits a GPT-2 training job to a remote IRI compute resource, polls for completion, and fetches log output. |
| [amsc_iri_multisite](examples/notebooks/client/amsc_iri_multisite.ipynb) | Demonstrates multi-site job submission across ESnet IRI East and West endpoints using a single session. |
| [amsc_iro_net_xfer](examples/notebooks/client/amsc_iro_net_xfer.ipynb) | Uses the AMSC-IRO backend to orchestrate networked data-transfer jobs with L2 network metadata. |

# <a name="airflow"></a>Apache Airflow Support

The [`airflow/`](airflow/) subdirectory provides custom Airflow operators for submitting and monitoring IRI compute jobs as part of larger data pipelines.

## Operators

- **`IriJobSubmitOperator`** — Plans, submits, and waits for an IRI job. Accepts `service_type`, `profile`, `executable`, `resources`, and `attributes`. Pushes `job_id` to XCom on completion.
- **`IriFetchOutputOperator`** — Downloads stdout/stderr from a completed job to a local directory.

## Quick Start

```bash
cd airflow/
bash setup_airflow.sh --start   # installs deps, initialises DB, launches standalone Airflow
```

Open [http://localhost:8080](http://localhost:8080), configure credentials in `~/.amscrot/credentials.yml`, then trigger the demo DAG (`esnet_iri_example` or `gpt2_training_job`) from the UI or via the REST API:

```bash
curl -X POST http://localhost:8080/api/v2/dags/esnet_iri_example/dagRuns \
     -H "Content-Type: application/json" \
     -u "admin:<password>" -d '{}'
```

See [`airflow/README.md`](airflow/README.md) for the full operator reference and configuration options.
