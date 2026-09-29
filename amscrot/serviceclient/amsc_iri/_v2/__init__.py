"""IRI v2 service client.

Uses the ``amsc_iri_v2`` package (generated from the v2 OpenAPI spec) to
communicate with IRI facilities that expose ``/api/v2/`` endpoints.

v2 uses DOE IRI URN strings for resource types and adds several new
capabilities beyond v1:

* ``whoami()`` -- identity verification
* ``get_storage_locations()`` -- resolved storage paths
* ``get_storage_access_endpoints()`` -- data access protocol endpoints
* ``StorageApi`` -- dedicated storage resource queries
"""

from __future__ import annotations

from typing import Dict, List, Optional

from amsc_iri_v2.configuration import Configuration as IriConfiguration
from amsc_iri_v2.api_client import ApiClient as IriApiClient
from amsc_iri_v2.api.compute_api import ComputeApi
from amsc_iri_v2.api.status_api import StatusApi
from amsc_iri_v2.api.facility_api import FacilityApi
from amsc_iri_v2.api.account_api import AccountApi
from amsc_iri_v2.api.filesystem_api import FilesystemApi
from amsc_iri_v2.api.storage_api import StorageApi
from amsc_iri_v2.api.task_api import TaskApi
from amsc_iri_v2.models.job_spec import JobSpec as IriJobSpec
from amsc_iri_v2.models.job_state import JobState as IriJobState
from amsc_iri_v2.models.job import Job as IriJob
from amsc_iri_v2.models.status import Status
from amsc_iri_v2.models.resource_spec import ResourceSpec as IriResourceSpec
from amsc_iri_v2.models.job_attributes import JobAttributes as IriJobAttributes
from amsc_iri_v2.models.container import Container as IriContainer
from amsc_iri_v2.exceptions import NotFoundException, BadRequestException

from amscrot.serviceclient.amsc_iri.iri_service_client import IriServiceClientBase
from amscrot.serviceclient.amsc_iri._v2.filesystem import IriFilesystemV2

__all__ = ["IriServiceClientV2", "IriFilesystemV2"]


# v2 uses DOE IRI URN strings for resource type filters.
_RESOURCE_TYPE_V2 = {
    "compute": "urn:doe-iri:resource:compute",
    "storage": "urn:doe-iri:resource:storage",
    "network": "urn:doe-iri:resource:network",
}


class IriServiceClientV2(IriServiceClientBase):
    """IRI service client for v2 API endpoints.

    Uses the ``amsc_iri_v2`` package (generated from the v2 OpenAPI spec).
    Adds v2-only features: ``whoami()``, ``get_storage_locations()``,
    and ``get_storage_access_endpoints()``.
    """

    API_VERSION = 2

    def _init_api_client(self) -> None:
        """Create the v2 API client and typed helpers."""
        configuration = IriConfiguration(
            host=self.api_endpoint,
            api_key={'APIKeyHeader': self.api_key},
            api_key_prefix={'APIKeyHeader': 'Bearer'},
            access_token=self.api_key,
        )
        self._api_client = IriApiClient(configuration)
        if self.api_key:
            self._api_client.default_headers['Authorization'] = f'Bearer {self.api_key}'
        self._compute_api = ComputeApi(self._api_client)
        self._status_api = StatusApi(self._api_client)
        self._facility_api = FacilityApi(self._api_client)
        self._account_api = AccountApi(self._api_client)
        self._filesystem_api = FilesystemApi(self._api_client)
        self._storage_api = StorageApi(self._api_client)
        self._task_api = TaskApi(self._api_client)

        # Register version-specific model types for base class methods
        self._iri_models = {
            'JobSpec': IriJobSpec,
            'ResourceSpec': IriResourceSpec,
            'JobAttributes': IriJobAttributes,
            'Container': IriContainer,
            'JobState': IriJobState,
            'Job': IriJob,
            'Status': Status,
            'NotFoundException': NotFoundException,
            'BadRequestException': BadRequestException,
        }

    def _resource_type(self, kind: str) -> str:
        """Return v2 resource type filter (DOE IRI URN strings)."""
        return _RESOURCE_TYPE_V2[kind]

    def _create_filesystem(self):
        """Create v2-specific filesystem interface."""
        return IriFilesystemV2(
            filesystem_api=self._filesystem_api,
            task_api=self._task_api,
            logger=self.logger,
            client_name=self.name,
        )

    # ------------------------------------------------------------------
    # v2-only features
    # ------------------------------------------------------------------

    def whoami(self) -> Optional[str]:
        """Return the authenticated user's username.

        Calls ``GET /api/v2/account/whoami`` to verify credentials and
        retrieve the current user identity.

        Returns:
            The username string, or ``None`` if the client is unavailable
            or the call fails.
        """
        if not self._available:
            return None
        try:
            result = self._account_api.whoami()
            return result.username if result else None
        except Exception as exc:
            self.logger.warning(f"[{self.name}] whoami() failed: {exc}")
            return None

    def get_storage_locations(
        self,
        resource_id: str,
        *,
        logical_name: str = None,
        project: str = None,
        intent: str = None,
    ) -> List[Dict]:
        """Return resolved storage paths for the authenticated user.

        Each returned dict describes a concrete storage location with fields
        like ``logical_name``, ``path``, ``filesystem``, ``performance_tier``,
        ``purge_policy_days``, ``shared``, and ``access`` (permissions).

        This is useful for auto-resolving user home directories, scratch
        space, or project storage without hardcoding per-facility paths.

        Args:
            resource_id:   Storage resource UUID.
            logical_name:  Filter to a specific filesystem tier
                           (e.g. ``"home"``, ``"scratch"``).
            project:       Filter by project/allocation identifier.
            intent:        Usage hint -- ``"staging"``, ``"write"``,
                           ``"read"``, or ``"long-term-storage"``.

        Returns:
            List of storage location dicts, or empty list if unavailable.
        """
        if not self._available:
            return []
        try:
            kwargs = {}
            if logical_name is not None:
                kwargs["logicalpath"] = logical_name
            if project is not None:
                kwargs["project"] = project
            if intent is not None:
                kwargs["intent"] = intent
            locations = self._storage_api.get_storage_locations(
                resource_id=resource_id, **kwargs
            )
            return [loc.to_dict() for loc in locations] if locations else []
        except Exception as exc:
            self.logger.warning(
                f"[{self.name}] get_storage_locations() failed for "
                f"resource {resource_id!r}: {exc}"
            )
            return []

    def get_storage_access_endpoints(
        self,
        resource_id: str,
        *,
        protocol: str = None,
        endpoint_id: str = None,
    ) -> List[Dict]:
        """Return data access endpoints for a storage resource.

        Each returned dict describes a data access protocol (Globus, XRootD,
        S3, etc.) and the connection details needed to use it.  Useful for
        programmatic data transfer setup between facilities.

        Args:
            resource_id:  Storage resource UUID.
            protocol:     Filter by protocol (e.g. ``"globus"``, ``"s3"``).
            endpoint_id:  Filter by specific endpoint ID.

        Returns:
            List of access endpoint dicts, or empty list if unavailable.
        """
        if not self._available:
            return []
        try:
            kwargs = {}
            if protocol is not None:
                kwargs["protocol"] = protocol
            if endpoint_id is not None:
                kwargs["endpoint_id"] = endpoint_id
            endpoints = self._storage_api.get_storage_access_endpoints(
                resource_id=resource_id, **kwargs
            )
            return [ep.to_dict() for ep in endpoints] if endpoints else []
        except Exception as exc:
            self.logger.warning(
                f"[{self.name}] get_storage_access_endpoints() failed for "
                f"resource {resource_id!r}: {exc}"
            )
            return []
