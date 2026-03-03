"""
IriReadOutputOperator -- read and log stdout/stderr from a completed IRI job.

This operator requires NO API calls and carries no service-client state.
It simply reads the local file paths returned by IriJobSubmitOperator via
XCom and makes the contents available to downstream tasks.

Because IriJobSubmitOperator already fetches the output files within its own
execute() call (while the Session is still alive), this operator is purely
a file-reading utility for downstream use.

XCom output:
    key "output_contents" -> {
        "<job_name>": {
            "stdout": "<text content or None>",
            "stderr": "<text content or None>",
        }
    }
"""
from __future__ import annotations

from typing import Dict, Optional

from airflow.exceptions import AirflowException
from airflow.models import BaseOperator


class IriReadOutputOperator(BaseOperator):
    """Airflow Operator to read stdout/stderr files fetched by IriJobSubmitOperator.

    Pulls the ``job_result`` XCom from an upstream IriJobSubmitOperator,
    reads the local stdout/stderr files, logs their contents, and pushes
    them as ``output_contents`` for further downstream use.

    Parameters
    ----------
    target_task_id:
        task_id of the upstream IriJobSubmitOperator.
    log_output:
        Whether to log file contents to the Airflow task log. Default: True.
    """

    def __init__(
        self,
        *,
        target_task_id: str,
        log_output: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_task_id = target_task_id
        self.log_output = log_output

    def execute(self, context) -> Dict[str, Dict[str, Optional[str]]]:
        ti = context["ti"]
        job_result = ti.xcom_pull(key="job_result", task_ids=self.target_task_id)

        if not job_result:
            raise AirflowException(
                f"No 'job_result' XCom found from task '{self.target_task_id}'. "
                "Ensure IriJobSubmitOperator ran successfully upstream."
            )

        local_files: dict = job_result.get("local_files", {})
        output_contents: Dict[str, Dict[str, Optional[str]]] = {}

        for job_name, paths in local_files.items():
            job_output: Dict[str, Optional[str]] = {}
            for stream in ("stdout", "stderr"):
                path = paths.get(stream)
                content = None
                if path:
                    try:
                        with open(path) as f:
                            content = f.read()
                        if self.log_output:
                            self.log.info(
                                "\n--- %s for %s ---\n%s",
                                stream, job_name, content,
                            )
                    except Exception as exc:
                        self.log.warning(
                            "Could not read %s file '%s': %s", stream, path, exc
                        )
                job_output[stream] = content
            output_contents[job_name] = job_output

        context["ti"].xcom_push(key="output_contents", value=output_contents)
        return output_contents
