# amscrot Airflow Operators

Custom Apache Airflow operators for submitting and monitoring HPC compute jobs
via the amscrot IRI service clients. Modeled on the
[FireCREST Airflow integration](https://eth-cscs.github.io/firecrest-v2/use_cases/workflow-orchestrator/).

## Folder layout

```
airflow/
  amscrot_airflow/
    operators/
      base.py          # AmscrotBaseOperator
      iri_job.py       # IriJobSubmitOperator
      fetch_files.py   # IriFetchOutputOperator
  dags/
    esnet_iri_example.py   # Demo DAG
  pyproject.toml
  setup_airflow.sh         # One-shot setup + launch script
  README.md
  airflow_home/            # Created by setup_airflow.sh (gitignored)
```

## Quick start

### 1. Set up and launch Airflow

Run the setup script from inside the `airflow/` directory.
It installs `apache-airflow[celery]` and `amscrot-airflow`, initialises the
SQLite database, and launches Airflow in standalone mode.

```bash
cd airflow/
bash setup_airflow.sh --start
```

**Airflow 3 note**: standalone generates a random admin password on first launch.
Look for a line in the output like:

```
Login with username: admin  password: <random-string>
```

Open [http://localhost:8080](http://localhost:8080) and use those credentials.

To restart Airflow in a new shell (AIRFLOW_HOME must be set):

```bash
export AIRFLOW_HOME="$(pwd)/airflow_home"
airflow standalone
```

### 2. Configure credentials

Make sure `~/.amscrot/credentials.yml` contains a profile matching
the `PROFILE` constant in the DAG file (default: `esnet-iri-east`):

```yaml
- profile: esnet-iri-east
  type: esnet-iri
  endpoint: https://iri-dev.ppg.es.net
  token: <your-token>
```

### 3. Edit the demo DAG

Open `dags/esnet_iri_example.py` and adjust:

| Variable | What to set |
|---|---|
| `PROFILE` | credentials.yml profile name |
| `RESOURCE_ID` | Specific compute resource UUID, or `None` to auto-discover |
| `OUTPUT_DIR` | Local path for downloaded stdout/stderr |
| `job_attributes["directory"]` | Working directory on the remote system |
| `job_attributes["account"]` | Account/project to charge |

### 4. Trigger the DAG

**Wait ~30 seconds** after `airflow standalone` starts for the scheduler to
parse and register the DAG. Then use the web UI **Play** button, or the REST API:

```bash
# Replace <password> with the password printed by standalone
curl -X POST http://localhost:8080/api/v2/dags/esnet_iri_example/dagRuns \
     -H "Content-Type: application/json" \
     -u "admin:<password>" \
     -d '{}'
```

> [!NOTE]
> `airflow dags trigger` from a separate shell requires `AIRFLOW_HOME` to
> be exported **and** the scheduler to have already parsed the DAG.
> The REST API + web UI are the recommended ways to trigger in Airflow 3.

Watch task progress in the UI under **Grid** or **Graph** view.


## Operators reference

### `IriJobSubmitOperator`

Plans, submits, and waits for an IRI compute job.

| Parameter | Type | Description |
|---|---|---|
| `service_type` | str | `"esnet-iri"` or `"nersc-iri"` |
| `name` | str | Label for the service client |
| `profile` | str | credentials.yml profile |
| `job_name` | str | Name for the job |
| `executable` | list[str] | Command + args, e.g. `["/bin/echo", "hi"]` |
| `resources` | dict | IRI ResourceSpec fields |
| `attributes` | dict | Job attributes (directory, duration, etc.) |
| `wait_timeout` | float | Max seconds to wait (default 600) |
| `wait_interval` | float | Poll interval in seconds (default 5) |

Pushes `{"job_name": ..., "job_id": ...}` to XCom key `job_submission`.

### `IriFetchOutputOperator`

Downloads stdout/stderr from a completed IRI job.

| Parameter | Type | Description |
|---|---|---|
| `target_task_id` | str | task_id of the upstream IriJobSubmitOperator |
| `output_path` | str | Local base directory for downloaded files |
| `attributes` | dict | Same attributes used at submit time (needs `resource_id`) |

Returns `{job_name: {"stdout": "/path/...", "stderr": "/path/..."}}`.

## Notes

- Airflow `LocalExecutor` is used for local testing with SQLite.
  For production, use `CeleryExecutor` or `KubernetesExecutor` with Postgres.
- The `airflow_home/` directory is gitignored. It contains the SQLite DB and logs.
- Each Airflow task runs in a fresh Python process, so the ServiceClient is
  re-created in every `execute()` call (credentials are re-read from disk).
