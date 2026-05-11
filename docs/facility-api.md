# Facility Convenience API

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [Resource Discovery](#resource-discovery)
- [Submitting Jobs](#submitting-jobs)
- [Waiting and Polling](#waiting-and-polling)
- [Filesystem Operations](#filesystem-operations)
- [Cancelling Jobs](#cancelling-jobs)
- [Power User: Accessing the Session](#power-user-accessing-the-session)
- [API Reference](#api-reference)

---

## Overview

AmSCROT's standard workflow — explicit `ServiceClient`, `Session`, `JobSpec`, `plan()`, `apply()` — is the right tool for multi-site orchestration and complex pipeline automation. For the common case of submitting a job to a single facility and waiting for it, that workflow is about 45 lines of boilerplate.

The facility convenience API reduces this to ~8 lines. It is an optional layer built on top of the same AmSCROT internals and is accessed via a single new method on `Client`.

**Before:**
```python
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.serviceclient import ServiceClient

client = Client()
session = client.create_session("my-session")
sc = ServiceClient.create(type="amsc-iri", name="alcf",
                           credential={"api_key": "<token>",
                                       "api_endpoint": "https://api.alcf.anl.gov"})
session.add_service_client(sc)
discovery = sc.discover()
resource_id = discovery.compute[0].data["id"]
spec = JobSpec(executable="/bin/echo", arguments=["hello"],
               resources={"node_count": 1},
               attributes={"resource_id": resource_id, "queue_name": "debug",
                           "account": "datascience", "duration": 300,
                           "directory": "/home/user/outputs"})
job = Job(name="hello", type=JobType.COMPUTE, service_type=JobServiceType.BATCH,
          service_client=sc, job_spec=spec)
session.add_job(job)
session.plan()
session.apply()
session.wait(jobs=[job], target_states=[JobState.COMPLETED, JobState.FAILED],
             timeout=300, interval=5)
```

**After:**
```python
from amscrot.client import Client

client = Client()
alcf = client.facility("https://api.alcf.anl.gov", token="<token>")
job = alcf.resource("Polaris").submit(
    executable="/bin/echo",
    arguments=["hello"],
    directory="/home/user/outputs",
    queue="debug",
    account="datascience",
    duration=300,
    nodes=1,
)
job.wait(timeout=300)
```

---

## Quick Start

```python
from amscrot.client import Client

client = Client()

# Connect to a facility
facility = client.facility("https://api.alcf.anl.gov", token="<your-api-token>")

# Discover available resources
for r in facility.resources():
    print(r.name, r.resource_type, r.status)

# Submit a job
job = facility.resource("Polaris").submit(
    executable="/path/to/script.sh",
    nodes=4,
    queue="debug",
    account="my-allocation",
    duration=3600,          # wall time in seconds
    directory="/home/user/scratch",
)
print(f"Submitted: {job.id}")

# Wait for completion
job.wait(timeout=3600, poll_interval=30)
print(f"Done: {job.state}, exit code: {job.exit_code}")
```

---

## Authentication

`client.facility()` accepts either a static token or a callable that returns the current token. The callable form supports transparent token refresh: when the API returns 401 or 403, the facility client calls your provider to get a fresh token, rebuilds its internal service client, and retries once automatically.

```python
# Static token — no refresh
facility = client.facility("https://api.alcf.anl.gov", token="<token>")

# Token provider — refresh on 401
def get_token():
    return my_auth_system.current_token()

facility = client.facility("https://api.alcf.anl.gov", token_provider=get_token)
```

The `name` parameter is optional and used in log messages:

```python
facility = client.facility(
    "https://api.alcf.anl.gov",
    token="<token>",
    name="ALCF Polaris",
)
```

---

## Resource Discovery

`facility.resources()` returns all compute, storage, and network resources at the facility. Allocation and other resource types are excluded. Discovery results are cached after the first call.

```python
resources = facility.resources()
for r in resources:
    print(r.id, r.name, r.resource_type, r.status)
```

`facility.resource(name)` does a case-insensitive lookup and raises `ValueError` if no match is found:

```python
polaris = facility.resource("Polaris")   # or "polaris", "POLARIS"
```

### Resource properties

| Property | Type | Description |
|---|---|---|
| `id` | `str` | IRI resource identifier |
| `name` | `str` | Human-readable name |
| `resource_type` | `str` | e.g. `"compute"`, `"storage"` |
| `status` | `str` | `"up"`, `"down"`, `"degraded"`, `"unknown"` |

---

## Submitting Jobs

`resource.submit()` takes IRI-standard parameters plus any scheduler-specific custom attributes as keyword arguments.

```python
job = polaris.submit(
    executable="/path/to/script.sh",
    arguments=["--input", "data.h5"],   # list of strings
    directory="/home/user/scratch",      # working directory on the resource
    name="my-job",                       # optional; auto-generated if omitted
    queue="debug",
    account="my-allocation",
    duration=3600,                       # wall time in seconds
    nodes=4,
    stdout_path="/home/user/scratch/job.stdout",
    stderr_path="/home/user/scratch/job.stderr",
    environment={"OMP_NUM_THREADS": "4"},
    # Any extra kwargs become scheduler-specific custom_attributes:
    filesystems="home",                  # ALCF-specific
)
```

### Submit parameters

| Parameter | Type | Description |
|---|---|---|
| `executable` | `str` | Path to the executable |
| `arguments` | `list[str]` | Command-line arguments |
| `directory` | `str` | Working directory on the resource |
| `name` | `str` | Job name (auto-generated if omitted) |
| `queue` | `str` | Queue or partition name |
| `account` | `str` | Project / allocation account |
| `duration` | `int` | Wall time in seconds |
| `nodes` | `int` | Number of nodes |
| `environment` | `dict[str, str]` | Environment variables |
| `stdout_path` | `str` | Path for stdout |
| `stderr_path` | `str` | Path for stderr |
| `pre_launch` | `str` | Commands to run before the job |
| `post_launch` | `str` | Commands to run after the job |
| `launcher` | `str` | Job launcher (e.g. `"mpiexec"`) |
| `**custom_attributes` | `str` | Scheduler-specific key-value pairs |

---

## Waiting and Polling

`job.wait()` blocks until the job reaches a terminal state (`COMPLETED`, `FAILED`, or `CANCELED`).

```python
job.wait(timeout=3600, poll_interval=30)

if job.state == "COMPLETED":
    print("Success, exit code:", job.exit_code)
elif job.state == "FAILED":
    print("Failed:", job.message)
```

`wait()` raises `TimeoutError` if the job does not finish within `timeout` seconds.

For non-blocking status checks:

```python
print(job.state)    # cached from last refresh — no API call
print(job.status)   # calls the API to refresh — always current
job.refresh()       # updates cached state, returns state string
```

### Job properties

| Property | Type | Description |
|---|---|---|
| `id` | `str` | IRI job identifier |
| `state` | `str` | Last known state (cached) |
| `status` | `str` | Live state (calls API on every access) |
| `is_terminal` | `bool` | `True` if `COMPLETED`, `FAILED`, or `CANCELED` |
| `exit_code` | `int \| None` | Exit code when terminal, else `None` |
| `message` | `str \| None` | Scheduler status message |

---

## Filesystem Operations

Each resource provides a `FilesystemClient` via its `.fs` property, scoped to that resource's ID. All operations return a `Task` object immediately — call `.wait()` then `.result` to get the output.

```python
home = facility.resource("Home")   # storage resource

# List a directory
task = home.fs.ls("/home/user/scratch")
task.wait()
for entry in task.result:
    print(entry)

# Read the beginning of a file
task = home.fs.head("/home/user/scratch/job.stdout", lines=50)
task.wait()
print(task.result)

# Read the end of a file
task = home.fs.tail("/home/user/scratch/job.stdout", lines=20)
task.wait()
print(task.result)

# File metadata
task = home.fs.stat("/home/user/scratch")
task.wait()
print(task.result)

# Create a directory
home.fs.mkdir("/home/user/new-dir").wait()

# Copy, move, delete
home.fs.cp("/home/user/src.dat", "/home/user/dst.dat").wait()
home.fs.mv("/home/user/old.dat", "/home/user/new.dat").wait()
home.fs.rm("/home/user/tmp.dat").wait()

# Upload / download
home.fs.upload("/local/input.h5", "/home/user/scratch/input.h5").wait()
home.fs.download("/home/user/scratch/output.h5", "/local/output.h5").wait()

# Checksum
task = home.fs.checksum("/home/user/scratch/output.h5")
task.wait()
print(task.result)

# Permissions
home.fs.chmod("/home/user/scratch/script.sh", "755").wait()

# Archives
home.fs.compress("/home/user/scratch", "/home/user/scratch.tar.gz").wait()
home.fs.extract("/home/user/scratch.tar.gz", "/home/user/restored").wait()

# Symbolic link
home.fs.symlink("/home/user/data", "/home/user/scratch/data-link").wait()
```

### Task interface

All filesystem methods return a `Task`:

| Property/Method | Description |
|---|---|
| `.state` | `"completed"` or `"failed"` |
| `.is_terminal` | Always `True` (operations complete synchronously) |
| `.result` | Operation output; raises the stored exception if the operation failed |
| `.wait(timeout, poll_interval)` | No-op — exists for API compatibility; returns `self` |

---

## Cancelling Jobs

```python
job.cancel()   # returns True if accepted
```

---

## Power User: Accessing the Session

The facility client manages an implicit AmSCROT `Session` internally. You can access it directly for multi-job orchestration, manual plan/apply/destroy workflows, or session persistence:

```python
facility = client.facility("https://api.alcf.anl.gov", token="<token>")

# Submit jobs via the convenience API...
job1 = polaris.submit(executable="/bin/script1.sh", nodes=2)
job2 = polaris.submit(executable="/bin/script2.sh", nodes=4)

# ...then use the underlying session for bulk operations
session = facility.session
session.wait(timeout=600, verbose=True)
session.destroy()
```

This gives full access to AmSCROT's session-based workflow without requiring you to set up the session, service client, or discovery manually.
