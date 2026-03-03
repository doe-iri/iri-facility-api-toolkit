"""
AmscrotDiscoverOperator -- run discovery on an IRI site and push the
first available compute resource_id to XCom.

This is typically used as the first task in a DAG so downstream
IriJobSubmitOperator tasks can pull a verified resource_id rather
than relying on hardcoded UUIDs or per-service-client auto-discovery.

XCom output:
    key "resource_id"  -> str UUID of the first compute resource
    key "resources"    -> list of all discovered compute resource dicts
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from airflow.exceptions import AirflowException

from amscrot_airflow.operators.base import AmscrotBaseOperator


class AmscrotDiscoverOperator(AmscrotBaseOperator):
    """Airflow Operator that runs IRI discovery and pushes resource_id to XCom.

    Parameters
    ----------
    resource_index:
        Index into the list of discovered compute resources to use.
        Defaults to 0 (first available resource).
    session_name, service_type, service_name, profile, credential_file:
        Forwarded to AmscrotBaseOperator.
    """

    def __init__(
        self,
        *,
        resource_index: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.resource_index = resource_index

    def execute(self, context) -> Dict[str, Any]:
        _session, sc = self._build_session()

        self.log.info("[amscrot] Running discovery on '%s'...", self.service_name)
        try:
            discovery = sc.discover()
        except Exception as exc:
            raise AirflowException(
                f"Discovery failed for service '{self.service_name}': {exc}"
            ) from exc

        compute = getattr(discovery, "compute", None) or []
        if not compute:
            raise AirflowException(
                f"No compute resources found during discovery on '{self.service_name}'."
            )

        if self.resource_index >= len(compute):
            raise AirflowException(
                f"resource_index={self.resource_index} is out of range "
                f"(found {len(compute)} compute resource(s))."
            )

        resource = compute[self.resource_index]
        resource_id = resource.data.get("id") if hasattr(resource, "data") else resource.get("id")

        if not resource_id:
            raise AirflowException(
                f"Could not extract 'id' from compute resource at index {self.resource_index}."
            )

        self.log.info(
            "[amscrot] Discovered resource_id='%s' (index %d of %d).",
            resource_id, self.resource_index, len(compute),
        )

        all_resources = []
        for r in compute:
            all_resources.append(r.data if hasattr(r, "data") else r)

        context["ti"].xcom_push(key="resource_id", value=resource_id)
        context["ti"].xcom_push(key="resources", value=all_resources)
        return {"resource_id": resource_id, "resources": all_resources}
