"""IRI v1 service client.

Uses the ``amsc_iri`` package (generated from the v1 OpenAPI spec) to
communicate with IRI facilities that expose ``/api/v1/`` endpoints.

v1 uses simple string resource types (``"compute"``, ``"storage"``,
``"network"``) and does not support v2-only features like ``whoami()``,
``get_storage_locations()``, or ``get_storage_access_endpoints()``.
"""

from __future__ import annotations

from amsc_iri.configuration import Configuration as IriConfiguration
from amsc_iri.api_client import ApiClient as IriApiClient
from amsc_iri.api.compute_api import ComputeApi
from amsc_iri.api.status_api import StatusApi
from amsc_iri.api.facility_api import FacilityApi
from amsc_iri.api.account_api import AccountApi
from amsc_iri.api.filesystem_api import FilesystemApi
from amsc_iri.api.task_api import TaskApi
from amsc_iri.models.job_spec import JobSpec as IriJobSpec
from amsc_iri.models.job_state import JobState as IriJobState
from amsc_iri.models.job import Job as IriJob
from amsc_iri.models.status import Status
from amsc_iri.models.resource_spec import ResourceSpec as IriResourceSpec
from amsc_iri.models.job_attributes import JobAttributes as IriJobAttributes
from amsc_iri.models.container import Container as IriContainer
from amsc_iri.exceptions import NotFoundException, BadRequestException

from amscrot.serviceclient.amsc_iri.iri_service_client import IriServiceClientBase
from amscrot.serviceclient.amsc_iri._v1.filesystem import IriFilesystemV1

__all__ = ["IriServiceClientV1", "IriFilesystemV1"]


# v1 uses simple enum-style strings for resource type filters.
_RESOURCE_TYPE_V1 = {
    "compute": "compute",
    "storage": "storage",
    "network": "network",
}


class IriServiceClientV1(IriServiceClientBase):
    """IRI service client for v1 API endpoints.

    Uses the ``amsc_iri`` package (generated from the v1 OpenAPI spec).
    """

    API_VERSION = 1

    def _init_api_client(self) -> None:
        """Create the v1 API client and typed helpers."""
        from amscrot.serviceclient.amsc_iri._path_rewriting import (
            make_path_rewriting_client,
        )

        configuration = IriConfiguration(
            host=self.api_endpoint,
            api_key={'APIKeyHeader': self.api_key},
            api_key_prefix={'APIKeyHeader': 'Bearer'},
            access_token=self.api_key,
        )
        self._api_client = make_path_rewriting_client(
            IriApiClient, configuration, path_prefix=self.path_prefix,
        )
        if self.api_key:
            self._api_client.default_headers['Authorization'] = f'Bearer {self.api_key}'
        self._compute_api = ComputeApi(self._api_client)
        self._status_api = StatusApi(self._api_client)
        self._facility_api = FacilityApi(self._api_client)
        self._account_api = AccountApi(self._api_client)
        self._filesystem_api = FilesystemApi(self._api_client)
        self._task_api = TaskApi(self._api_client)
        # v1 does not have StorageApi
        self._storage_api = None

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
        """Return v1 resource type filter (simple strings)."""
        return _RESOURCE_TYPE_V1[kind]

    def _create_filesystem(self):
        """Create v1-specific filesystem interface."""
        return IriFilesystemV1(
            filesystem_api=self._filesystem_api,
            task_api=self._task_api,
            logger=self.logger,
            client_name=self.name,
        )

