"""
IriJobSubmitOperator -- submit an amscrot Job via a Session and wait for completion,
then immediately fetch output files, all within a single execute() call.

Because Airflow runs each task in a fresh Python process, the service-client's
in-memory _submitted_jobs state would be lost between tasks. By doing
submit + wait + fetch in one execute(), the Session and ServiceClient remain
alive throughout and no cross-process state passing is needed.

XCom output:
    key "job_result" -> {
        "job_name": str,
        "job_id": str,
        "status": str,         # e.g. "COMPLETED"
        "local_files": {       # keyed by job name
            "<job_name>": {
                "stdout": "/path/to/stdout.log",
                "stderr": "/path/to/stderr.log",
            }
        }
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from airflow.exceptions import AirflowException

from amscrot.client.job import Job, JobSpec, JobType, JobServiceType, JobState
from amscrot.serviceclient import PlanError

from amscrot_airflow.operators.base import AmscrotBaseOperator


class IriJobSubmitOperator(AmscrotBaseOperator):
    """Airflow Operator to plan, submit, wait for, and fetch output of an IRI job.

    All of plan -> submit -> wait -> fetch_output_files happens within a single
    execute() call so the Session's in-memory state is never lost across tasks.

    The XCom result dict can be consumed by downstream PythonOperators or by
    an IriReadOutputOperator for logging purposes.

    Parameters
    ----------
    job_name:
        Name for the job (also used as the XCom key).
    executable:
        Path to the program to run, e.g. ``"/bin/echo"``.
    arguments:
        Arguments list for the executable, e.g. ``["Hello from Airflow"]``.
    resources:
        Dict of IRI ResourceSpec fields (node_count, memory, etc.).
    attributes:
        Dict of job attributes placed in amscrot JobSpec.attributes
        (resource_id, directory, duration, queue_name, account, stdout_path, etc.).
    fetch_output:
        Whether to fetch stdout/stderr after the job completes. Default: True.
    output_path:
        Local base directory for downloaded output files.
        Defaults to ``~/.amscrot/sessions/<session_name>/files/<job_name>/``.
    wait_timeout:
        Max seconds to wait for completion. Default: 600.
    wait_interval:
        Polling interval in seconds. Default: 5.
    session_name, service_type, service_name, profile, credential_file:
        Forwarded to AmscrotBaseOperator.
    """

    template_fields = AmscrotBaseOperator.template_fields + ("job_name",)

    def __init__(
        self,
        *,
        job_name: str,
        executable: str,
        arguments: Optional[List[str]] = None,
        iri_resources: Optional[Dict[str, Any]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        resource_id_task_id: Optional[str] = None,
        fetch_output: bool = True,
        output_path: Optional[str] = None,
        wait_timeout: float = 600.0,
        wait_interval: float = 5.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.job_name = job_name
        self.executable = executable
        self.arguments = arguments or []
        self.iri_resources = iri_resources or {}
        self.attributes = attributes or {}
        self.resource_id_task_id = resource_id_task_id
        self.fetch_output = fetch_output
        self.output_path = output_path
        self.wait_timeout = wait_timeout
        self.wait_interval = wait_interval

    def execute(self, context) -> Dict[str, Any]:
        session, sc = self._build_session()

        # -- Pull resource_id from upstream discover task if configured --
        attrs = dict(self.attributes)
        if self.resource_id_task_id:
            resource_id = context["ti"].xcom_pull(
                key="resource_id",
                task_ids=self.resource_id_task_id,
            )
            if not resource_id:
                raise AirflowException(
                    f"No 'resource_id' XCom found from task '{self.resource_id_task_id}'. "
                    "Ensure AmscrotDiscoverOperator ran successfully upstream."
                )
            self.log.info(
                "[amscrot] Using discovered resource_id='%s' from task '%s'.",
                resource_id, self.resource_id_task_id,
            )
            attrs["resource_id"] = resource_id

        spec = JobSpec(
            executable=self.executable,
            arguments=self.arguments if self.arguments else None,
            resources=self.iri_resources if self.iri_resources else None,
            attributes=attrs if attrs else None,
        )

        job = Job(
            name=self.job_name,
            type=JobType.COMPUTE,
            service_type=JobServiceType.BATCH,
            service_client=sc,
            job_spec=spec,
        )
        session.add_job(job)

        # -- Plan --
        self.log.info("[amscrot] Planning job '%s'...", self.job_name)
        try:
            session.plan()
        except PlanError as exc:
            raise AirflowException(
                f"Job '{self.job_name}' plan failed: {exc.errors}"
            ) from exc

        # -- Submit --
        self.log.info("[amscrot] Submitting job '%s'...", self.job_name)
        rc = session.apply()
        if rc:
            raise AirflowException(f"Session apply failed for job '{self.job_name}'")
        self.log.info("[amscrot] Job submitted.")

        # -- Wait --
        self.log.info(
            "[amscrot] Waiting for job '%s' (timeout=%ss)...",
            self.job_name, self.wait_timeout,
        )
        try:
            results = session.wait(
                jobs=[job],
                timeout=self.wait_timeout,
                interval=self.wait_interval,
                verbose=False,
            )
        except Exception as exc:
            raise AirflowException(
                f"Job '{self.job_name}' wait failed: {exc}"
            ) from exc

        status = results.get(self.job_name)
        if status is None or status.state != JobState.COMPLETED:
            state = status.state if status else "UNKNOWN"
            msg = status.message if status else ""
            raise AirflowException(
                f"Job '{self.job_name}' did not complete successfully "
                f"(state={state}, message={msg})"
            )

        self.log.info(
            "[amscrot] Job '%s' COMPLETED (job_id=%s).",
            self.job_name, status.job_id,
        )

        # -- Fetch output files (while Session + ServiceClient are still alive) --
        local_files: Dict[str, Dict[str, str]] = {}
        if self.fetch_output:
            self.log.info("[amscrot] Fetching output files for '%s'...", self.job_name)
            try:
                local_files = session.fetch_output_files(
                    jobs=[job],
                    output_path=self.output_path,
                )
                self.log.info("[amscrot] Fetched files: %s", local_files)
            except Exception as exc:
                self.log.warning(
                    "[amscrot] fetch_output_files failed for '%s': %s",
                    self.job_name, exc,
                )

        result = {
            "job_name": self.job_name,
            "job_id": status.job_id,
            "status": str(status.state),
            "local_files": local_files,
        }
        context["ti"].xcom_push(key="job_result", value=result)
        return result
