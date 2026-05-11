# High-Level Facility Convenience API

**Date:** 2026-04-20
**Branch:** `feature/high-level-api`
**Status:** Design approved, pending implementation

## Problem

AmSCROT's current API requires ~45 lines of boilerplate to submit a single job: explicit ServiceClient creation, session management, discovery, JobSpec construction with nested dicts, enum wiring, and two-phase plan/apply. This is appropriate for multi-site orchestration workflows but excessive for the 80% use case of submitting a single job to a single facility.

The amsc-python-client project provides a Pythonic, minimal-boilerplate interface for the same IRI operations. The goal is to bring that ease of use into AmSCROT itself, so that amsc-python-client can re-export the facility layer directly rather than maintaining its own parallel implementation.

## Goals

1. Provide a convenience API that reduces single-job submission to ~5 lines.
2. Preserve full access to AmSCROT's session/plan/apply/destroy machinery for power users.
3. Match amsc-python-client's public API surface (method signatures, class names) so the facility layer can be re-exported without users noticing the switch.
4. Keep the existing AmSCROT codebase unchanged except for one new method on `Client`.

## Non-Goals

- Replacing AmSCROT's existing session-based workflow.
- Supporting non-IRI providers (Kubernetes, IRO) in this iteration.
- Shipping built-in facility configs (endpoint URLs). AmSCROT stays generic; amsc-python-client owns the facility registry.
- Modifying `IriServiceClient` internals.

## Architecture

### Package Structure

```
amscrot/
├── facility/                    # NEW — convenience layer
│   ├── __init__.py              # exports FacilityClient, Resource, Job, Task, FilesystemClient
│   ├── client.py                # FacilityClient
│   ├── models.py                # Resource, Job
│   ├── filesystem.py            # FilesystemClient (resource-scoped)
│   └── task.py                  # Task (async-compatible wrapper)
├── client/
│   └── client.py                # Existing Client — gains one .facility() method
├── serviceclient/               # Existing — unchanged
└── ...                          # Everything else — unchanged
```

### Class Diagram

```
Client
  └── .facility(endpoint, token/token_provider) → FacilityClient

FacilityClient
  ├── .resource(name) → Resource
  ├── .resources() → list[Resource]
  ├── .session → Session (implicit, for power users)
  ├── _service_client: IriServiceClient (internal)
  ├── _session: Session (internal, auto-created)
  └── _call_api() (internal, handles token refresh retry)

Resource
  ├── .submit(executable, nodes, queue, ...) → Job
  ├── .fs → FilesystemClient
  ├── .id, .name, .status, .resource_type
  └── _facility: FacilityClient (internal ref)

Job
  ├── .wait(timeout, poll_interval) → Job
  ├── .cancel() → bool
  ├── .refresh() → str
  ├── .state, .status, .is_terminal
  ├── .id, .exit_code, .message
  └── _facility: FacilityClient (internal ref)

FilesystemClient
  ├── .ls(), .head(), .tail(), .stat(), .mkdir(), .rm(), ...
  ├── .upload(), .download()
  ├── All methods return → Task
  └── _resource_id: str (scoped, no per-call resource_id)

Task
  ├── .wait(timeout) → Task
  ├── .result → Any
  ├── .state, .is_terminal
  └── Wraps synchronous IriFilesystem call
```

## Detailed Design

### 1. Client.facility()

A single new method on the existing `amscrot.client.Client`:

```python
def facility(self, endpoint, *, token=None, token_provider=None, name=None):
    """Connect to an IRI-compliant facility.

    Args:
        endpoint: Facility API base URL (e.g., "https://iri-dev.ppg.es.net").
        token: Static bearer token (mutually exclusive with token_provider).
        token_provider: Callable returning current token (supports refresh).
        name: Optional display name for the facility.

    Returns:
        FacilityClient with resource discovery and job submission.
    """
```

This is the only change to existing code.

### 2. FacilityClient

The main convenience object. Wraps an `IriServiceClient` and an implicit `Session`.

**Constructor:**
- Accepts `endpoint` (required), `token` or `token_provider` (one required), `name` (optional).
- Creates an `IriServiceClient` internally using `ServiceClient.create()` with a credential dict.
- Creates an implicit `Session` (named from endpoint) for job tracking.
- Lazily caches discovery results on first `.resource()` call.

**Token refresh via `_call_api()`:**
All API operations route through `_call_api()`, which catches auth errors (401/403) and retries once after calling `token_provider()` and rebuilding the `IriServiceClient`. This avoids modifying `IriServiceClient`, which bakes the token into its `IriConfiguration` at construction time.

```python
def _call_api(self, operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except Exception as e:
        if self._is_auth_error(e) and self._token_provider:
            self._rebuild_service_client()
            return operation(*args, **kwargs)
        raise

def _is_auth_error(self, exc):
    msg = str(exc).lower()
    return "401" in msg or "403" in msg or "unauthorized" in msg

def _rebuild_service_client(self):
    new_token = self._token_provider()
    self._service_client = ServiceClient.create(
        type="amsc-iri",
        name=self._name,
        endpoint_uri=self._endpoint,
        credential={"api_key": new_token, "api_endpoint": self._endpoint},
    )
```

**Resource discovery:**
- `.resources()` calls `_service_client.discover()` (cached after first call), wraps each `DiscoveredResource` as a `Resource` object.
- `.resource(name)` does case-insensitive name matching against discovered resources. Raises `ValueError` if no resource matches. If multiple resources match (unlikely given IRI facility structure), returns the first match.

**Power user escape hatch:**
- `.session` property exposes the underlying `Session` for plan/apply/destroy workflows.

### 3. Resource

Wraps a discovered resource. Provides flat `submit()` and resource-scoped filesystem access.

**`submit()` signature** (matches amsc-python-client exactly):

```python
def submit(
    self,
    executable="",
    arguments=None,
    directory=None,
    name=None,
    queue=None,
    account=None,
    duration=None,
    nodes=None,
    environment=None,
    stdout_path=None,
    stderr_path=None,
    pre_launch=None,
    post_launch=None,
    launcher=None,
    **custom_attributes,
) -> Job:
```

**Internal wiring of `_submit_job()`:**
1. Builds `resources` dict from `nodes` kwarg.
2. Builds `attributes` dict from `queue`, `account`, `duration`, `directory`, `resource_id`, stdout/stderr paths, and `custom_attributes`.
3. Constructs `JobSpec(executable, arguments, resources, attributes)`.
4. Constructs `AmscrotJob(name, type=COMPUTE, service_type=BATCH, service_client, job_spec)`.
5. Adds job to implicit session.
6. Calls `service_client.plan(job)` then `service_client.create(job)` via `_call_api()`.
7. Returns a convenience `Job` wrapper.

Auto-generates a timestamp-based job name if none provided.

**`.fs` property:**
Returns a `FilesystemClient` scoped to this resource's ID.

### 4. Job

Self-aware job object. Holds references to its `FacilityClient` and resource.

**Properties:**
- `.id` — job ID from IRI.
- `.state` — last known state (cached from last refresh).
- `.status` — live state (calls API via `refresh()`).
- `.is_terminal` — True if state in `{COMPLETED, FAILED, CANCELED}`.
- `.exit_code` — integer exit code if terminal, else None.
- `.message` — scheduler status message.

**Methods:**
- `.wait(timeout=300, poll_interval=5)` — polls until terminal state. Raises `TimeoutError` on timeout. Returns self.
- `.cancel()` — cancels the job. Returns True.
- `.refresh()` — calls API, updates cached state, returns state string.

All API calls route through `FacilityClient._call_api()` for automatic token refresh.

### 5. FilesystemClient

Scoped to a resource ID. All operations return `Task` objects.

**Read operations:** `ls`, `stat`, `head`, `tail`, `view`, `checksum`, `file`, `download`.
**Write operations:** `mkdir`, `rm`, `cp`, `mv`, `symlink`, `upload`.
**Permission operations:** `chmod`, `chown`.
**Archive operations:** `compress`, `extract`.

Each method delegates to the corresponding `IriFilesystem` method (via `_call_api()`), passing `self._resource_id` automatically so the user only provides paths.

### 6. Task

Wraps a synchronous `IriFilesystem` operation result as an async-compatible object.

**Design decision:** Since `IriFilesystem` operations are synchronous (they internally poll the IRI TaskApi to completion before returning), `Task` objects are immediately resolved at creation time. The `wait()` method is a no-op that exists for API compatibility with amsc-python-client.

This means users write the same code (`task.wait(); print(task.result)`) and if we later add true async execution (e.g., background threads), their code doesn't change.

**Interface:**
- `.state` — "completed" or "failed".
- `.is_terminal` — always True.
- `.result` — operation output (raises stored exception if failed).
- `.wait(timeout=300, poll_interval=2)` — returns self (no-op).

## Authentication Flow

### AmSCROT standalone (static token):

```python
client = Client()
facility = client.facility("https://iri-dev.ppg.es.net", token="my-api-key")
```

Token is wrapped internally as `lambda: "my-api-key"`. No refresh capability. Auth failures raise the underlying exception.

### amsc-python-client re-export (Globus refresh):

```python
# Inside amsc_client/core/client.py
def facility(self, name):
    config = BUILTIN_FACILITIES[name]
    return FacilityClient(
        endpoint=config.api_base_url,
        token_provider=lambda: self._authenticator.get_token(config),
        name=config.display_name,
    )
```

On 401, `FacilityClient._call_api()` calls `token_provider()`, which triggers Globus token refresh inside amsc-python-client's authenticator, then rebuilds the `IriServiceClient` with the fresh token and retries.

## Re-Export Strategy

amsc-python-client re-exports all facility-layer classes directly:

```python
# amsc_client/facility/__init__.py
from amscrot.facility import FacilityClient, Resource, Job, Task, FilesystemClient
```

amsc-python-client's `Client.facility("alcf")` method does name-to-config resolution and token acquisition, then constructs `amscrot.facility.FacilityClient`. Everything below that point is AmSCROT code.

**Dependency changes for amsc-python-client:**
- Add: `amscrot` (brings in `amsc-iri`).
- Remove: `iri-api-autogen` (no longer needed; facility operations come from AmSCROT).
- Keep: `amsc-api-autogen` (still used for catalog, workflow, account APIs).

**User impact:** None, besides needing to reinstall. The public API surface is identical.

## API Compatibility Matrix

| amsc-python-client | AmSCROT facility layer | Match |
|---|---|---|
| `Resource.submit(executable, nodes, queue, **custom_attributes)` | Same signature | Exact |
| `Job.wait(timeout, poll_interval)` | Same signature | Exact |
| `Job.state`, `.status`, `.is_terminal`, `.cancel()` | Same properties/methods | Exact |
| `Job.exit_code`, `.message`, `.id` | Same properties | Exact |
| `resource.fs.ls(path)` returns `Task` | Same pattern | Exact |
| `Task.wait()`, `.result`, `.state`, `.is_terminal` | Same interface | Exact |
| `FilesystemClient.{ls,head,tail,stat,mkdir,rm,cp,mv,...}` | Same methods | Exact |
| `FacilityClient(endpoint, token_provider)` | Constructor takes explicit params | Compatible (different from amsc-python-client's internal construction, but public methods match) |

## What Changes in Existing Code

Only one addition to `amscrot/client/client.py`: the `facility()` method. Everything else in the existing codebase is untouched.

## Scope

**In scope:**
- `amscrot/facility/` subpackage (5 files).
- One method addition to `amscrot/client/client.py`.
- IRI provider only.
- Unit tests for all new classes.

**Out of scope:**
- Kubernetes, IRO, or Dummy provider support via the convenience layer.
- Built-in facility configs (stays in amsc-python-client).
- Modifications to `IriServiceClient` or other existing classes.
- Changes to amsc-python-client (separate repo, separate PR).

## End-to-End Usage

### Before (current AmSCROT — ~45 lines):

```python
from amscrot.client.client import Client
from amscrot.client.job import Job, JobType, JobServiceType, JobSpec, JobState
from amscrot.serviceclient import ServiceClient
from amscrot.util.constants import Constants

client = Client()
session = client.create_session("my-session")
sc = ServiceClient.create(type=Constants.ServiceType.AMSC_IRI, name="alcf",
                           profile="alcf", credential_file="~/.amscrot/credentials.yml")
session.add_service_client(sc)
discovery = sc.discover()
resource_id = discovery.compute[0].data["id"]
spec = JobSpec(executable="/bin/echo", arguments=["hello"],
               resources={"node_count": 1},
               attributes={"resource_id": resource_id, "queue_name": "debug",
                           "account": "datascience", "duration": 300,
                           "directory": "/home/user/outputs",
                           "stdout_path": "/home/user/outputs/stdout.log",
                           "stderr_path": "/home/user/outputs/stderr.log"})
job = Job(name="hello", type=JobType.COMPUTE, service_type=JobServiceType.BATCH,
          service_client=sc, job_spec=spec)
session.add_job(job)
session.plan(verbose=True)
session.apply()
results = session.wait(jobs=[job], target_states=[JobState.COMPLETED, JobState.FAILED],
                       timeout=300, interval=5)
```

### After (convenience layer — ~8 lines):

```python
from amscrot.client import Client

client = Client()
alcf = client.facility("https://api.alcf.anl.gov", token="my-token")
job = alcf.resource("Polaris").submit(
    executable="/bin/echo",
    arguments=["hello"],
    directory="/home/user/outputs",
    queue="debug",
    account="datascience",
    duration=300,
    nodes=1,
)
job.wait(timeout=300, poll_interval=5)
```

### Power user (access underlying session):

```python
client = Client()
facility = client.facility("https://iri-dev.ppg.es.net", token="my-token")

# Use convenience API for setup
polaris = facility.resource("Polaris")

# Drop into session for multi-job orchestration
session = facility.session
session.plan(verbose=True)
session.apply()
session.wait(timeout=600, verbose=True)
session.destroy()
```

### Filesystem operations:

```python
alcf = client.facility("https://api.alcf.anl.gov", token="my-token")
home = alcf.resource("Home")

task = home.fs.ls("/home/user/outputs")
task.wait()
print(task.result)

task = home.fs.head("/home/user/outputs/job.stdout", lines=50)
task.wait()
print(task.result)
```
