import os
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, TYPE_CHECKING
from ..serviceclient import ServiceClient, PlanError, CreateError, DestroyError
from ..filesystem import IriFilesystem, FilesystemError
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult, DiscoveredResource
from ...client.job import JobStatus, JobState as AmscrotJobState

from amsc_iri.configuration import Configuration as IriConfiguration
from amsc_iri.api_client import ApiClient as IriApiClient
from amsc_iri.api.compute_api import ComputeApi
from amsc_iri.api.status_api import StatusApi
from amsc_iri.api.facility_api import FacilityApi
from amsc_iri.api.account_api import AccountApi
from amsc_iri.api.filesystem_api import FilesystemApi
from amsc_iri.api.task_api import TaskApi
from amsc_iri.models.job_spec_input import JobSpecInput as IriJobSpec
from amsc_iri.models.resource_type import ResourceType
from amsc_iri.models.job_state import JobState as IriJobState
from amsc_iri.models.job import Job as IriJob
from amsc_iri.models.status import Status
from amsc_iri.exceptions import NotFoundException, BadRequestException

if TYPE_CHECKING:
    from amscrot.client.job import Job, JobSpec

class IriServiceClient(ServiceClient):
    """Unified ServiceClient implementation for IRI compute jobs.

    Works with any IRI-compliant facility (ESnet, NERSC, etc.).  The target
    facility is determined by the ``profile`` parameter, which selects the
    appropriate credentials section in ``~/.amscrot/credentials.yml``.
    """

    # Map IRI JobState enum -> AmSCROT JobState (direct 1:1 alignment)
    _IRI_TO_AMSCROT = {
        IriJobState.NEW:       AmscrotJobState.NEW,
        IriJobState.QUEUED:    AmscrotJobState.QUEUED,
        IriJobState.ACTIVE:    AmscrotJobState.ACTIVE,
        IriJobState.COMPLETED: AmscrotJobState.COMPLETED,
        IriJobState.FAILED:    AmscrotJobState.FAILED,
        IriJobState.CANCELED:  AmscrotJobState.CANCELED,
    }

    def __init__(self, **kwargs):
        super().__init__(type=Constants.ServiceType.IRI, **kwargs)
        
        # Load credentials
        self.api_key = None
        self.api_endpoint = None
        self._load_credentials()
        
        # Override endpoint if provided via ServiceClient init
        if self.endpoint_uri:
            self.api_endpoint = self.endpoint_uri
        else:
            self.endpoint_uri = self.api_endpoint
        
        # Normalize endpoint: strip trailing slashes to avoid double-slash URLs
        if self.api_endpoint:
            self.api_endpoint = self.api_endpoint.rstrip('/')
            self.endpoint_uri = self.api_endpoint

        # Initialize the API client
        self._api_client = None
        if self.api_key and self.api_endpoint:
            configuration = IriConfiguration(
                host=self.api_endpoint,
                api_key={'APIKeyHeader': self.api_key},
                api_key_prefix={'APIKeyHeader': 'Bearer'},
                access_token=self.api_key
            )
            self._api_client = IriApiClient(configuration)
            self._compute_api = ComputeApi(self._api_client)
            self._status_api = StatusApi(self._api_client)
            self._facility_api = FacilityApi(self._api_client)
            self._account_api = AccountApi(self._api_client)
            self._filesystem_api = FilesystemApi(self._api_client)
            self._task_api = TaskApi(self._api_client)
            self._available = True
        else:
            self._available = False
            self.logger.warning(f"[{self.name}] Warning: Could not load IRI credentials.")
        
        self._default_resource_id = None
        # Lazily-created filesystem interface
        self._filesystem: Optional[IriFilesystem] = None
    
    def discover(self, native: bool = True) -> DiscoveryResult:
        """Discover resources. native=True returns raw DiscoveredResource items;
        native=False returns normalized Facility objects."""
        if native:
            return self._discover_native()
        return self._discover_normalized()

    def _discover_native(self) -> DiscoveryResult:
        """Return raw API resources (compute, storage, network, facilities, capabilities, allocations)."""
        if not self._api_client:
            self.logger.warning(f"[{self.name}] Warning: Client not initialized, returning empty discovery.")
            return DiscoveryResult()

        items = []
        try:
            # 1. Discover typed resources (compute, storage, network)
            for res_type, item_type in [
                (ResourceType.COMPUTE,  "compute"),
                (ResourceType.STORAGE,  "storage"),
                (ResourceType.NETWORK,  "network"),
            ]:
                self.logger.debug(f"[{self.name}] Discovering {item_type} resources...")
                resources = self._status_api.get_resources(resource_type=res_type)
                if resources:
                    for res in resources:
                        items.append(DiscoveredResource(type=item_type, data=res.to_dict()))

            # 2. Discover Facilities (Sites)
            self.logger.debug(f"[{self.name}] Discovering facilities...")
            sites = self._facility_api.get_sites()
            if sites:
                for site in sites:
                    items.append(DiscoveredResource(type="facility", data=site.to_dict()))

            # 3. Discover Capabilities
            self.logger.debug(f"[{self.name}] Discovering capabilities...")
            capabilities = self._account_api.get_capabilities()
            if capabilities:
                for cap in capabilities:
                    items.append(DiscoveredResource(type="capability", data=cap.to_dict()))

            # 4. Discover Allocations (via Projects)
            self.logger.debug(f"[{self.name}] Discovering allocations...")
            projects = self._account_api.get_projects()
            if projects:
                for project in projects:
                    allocations = self._account_api.get_project_allocations_by_project(
                        project_id=project.id
                    )
                    if allocations:
                        for alloc in allocations:
                            alloc_data = alloc.to_dict()
                            alloc_data['_project_name'] = project.name
                            items.append(DiscoveredResource(type="allocation", data=alloc_data))

            # 5. Discover Incidents
            self.logger.debug(f"[{self.name}] Discovering incidents...")
            try:
                incidents = self._status_api.get_incidents()
                if incidents:
                    for inc in incidents:
                        items.append(DiscoveredResource(type="incident", data=inc.to_dict()))
            except Exception as inc_exc:
                self.logger.warning(f"[{self.name}] Could not fetch incidents: {inc_exc}")

        except Exception as e:
            self.logger.error(f"[{self.name}] Error during discovery: {e}")

        self.logger.debug(f"[{self.name}] Discovery complete. Found {len(items)} items.")
        return DiscoveryResult(items=items)

    def _discover_normalized(self) -> DiscoveryResult:
        """Aggregate raw API resources into a single typed Facility object.

        Any resources found (compute, storage, network, allocations) can be assumed 
        to belong to the single facility found in the resources query.  There is no
        longer a 'default' catch-all facility.
        """
        from ...model.metadata import Compute, Storage, Network, Allocation, Facility

        if not self._api_client:
            self.logger.warning(f"[{self.name}] Warning: Client not initialized, returning empty discovery.")
            return DiscoveryResult()

        native_result = self._discover_native()

        def _build_compute(d: dict) -> Compute:
            return Compute(
                id=d.get("id"),
                name=d.get("name") or d.get("node_name"),
                description=d.get("description"),
                architecture=d.get("architecture"),
                cores=d.get("cores") or d.get("cpu_cores"),
                memory=d.get("memory"),
                nodes=d.get("node_count"),
                gpus_per_node=d.get("gpus_per_node") or d.get("gpu_count"),
                gpu_type=d.get("gpu_type"),
            )

        def _build_storage(d: dict) -> Storage:
            return Storage(
                id=d.get("id"),
                name=d.get("name"),
                description=d.get("description"),
                type=d.get("storage_type") or d.get("type"),
                quota=str(d.get("capacity_bytes")) if d.get("capacity_bytes") else d.get("quota"),
                performance_tier=d.get("performance_tier"),
            )

        def _build_network(d: dict) -> Network:
            return Network(
                id=d.get("id"),
                name=d.get("name"),
                description=d.get("description"),
                fabric=d.get("fabric") or d.get("network_type"),
                bandwidth_limit=d.get("bandwidth_limit"),
                external_connectivity=d.get("external_connectivity"),
            )

        compute_resources = []
        for item in native_result.by_type("compute"):
            d = item.data
            if d.get("id"):
                res_obj = _build_compute(d)
                compute_resources.append(res_obj)

                # Cache the first one as default
                if not hasattr(self, '_default_resource_id') or not self._default_resource_id:
                    self._default_resource_id = res_obj.id

        storage_resources = []
        for item in native_result.by_type("storage"):
            d = item.data
            if d.get("id"):
                storage_resources.append(_build_storage(d))

        network_resources = []
        for item in native_result.by_type("network"):
            d = item.data
            if d.get("id"):
                network_resources.append(_build_network(d))

        allocations = []
        for item in native_result.by_type("allocation"):
            d = item.data
            project_name = d.get("_project_name", "default")
            allocations.append(Allocation(
                id=d.get("id"),
                name=d.get("name"),
                description=d.get("description"),
                account=project_name,
                qos=d.get("qos"),
                walltime_limit=d.get("walltime_limit") or d.get("max_walltime"),
                exclusive=d.get("exclusive"),
            ))

        # -- 3. Find the single facility ---------------------------------------
        facilities = list(native_result.by_type("facility"))
        if not facilities:
            self.logger.warning(f"[{self.name}] No facilities found, returning empty discovery.")
            return DiscoveryResult()

        # We assume all resources belong to the FIRST facility returned
        facility_item = facilities[0]
        raw = facility_item.data
        site_key = raw.get("id") or raw.get("name") or "unknown"

        facility = Facility(
            id=raw.get("id"),
            name=raw.get("name") or site_key,
            description=raw.get("description"),
            compute=compute_resources if compute_resources else None,
            storage=storage_resources if storage_resources else None,
            networks=network_resources if network_resources else None,
            allocations=allocations if allocations else None,
        )

        result_items = [
            DiscoveredResource(
                type="facility",
                data=raw,
                name=facility.name,
                metadata=facility,
            )
        ]

        self.logger.info(
            f"[{self.name}] Normalized discovery complete. "
            f"1 facility created with {len(compute_resources)} compute, "
            f"{len(storage_resources)} storage, {len(network_resources)} network resources, "
            f"and {len(allocations)} allocations."
        )
        return DiscoveryResult(items=result_items)

    def _load_credentials(self):
        """Load IRI credentials."""
        # 1. Use provided ProviderCredential object if available
        # self.credential is populated by ServiceClient.__init__
        if self.credential:
            try:
                # Handle ProviderCredential object (duck typing or to_dict)
                if hasattr(self.credential, 'to_dict'):
                    creds = self.credential.to_dict()
                elif isinstance(self.credential, dict):
                    creds = self.credential
                else:
                    creds = {}

                self.api_key = creds.get('api_key')
                self.api_endpoint = creds.get('api_endpoint')
                return
            except Exception as e:
                print(f"[{self.name}] Error loading from credential object: {e}")

        # 2. Load from file
        default_file = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
        # self.credential_file is populated by ServiceClient.__init__
        cred_file = self.credential_file or default_file
        cred_file = os.path.expanduser(cred_file)
        
        if not os.path.exists(cred_file):
            if self.credential_file:
                 self.logger.warning(f"[{self.name}] Warning: Custom credentials file not found at {cred_file}")
            # If default file is missing and no explicit file given, just return silent warning if desired
            if not self.credential_file and cred_file == default_file:
                 self.logger.warning(f"[{self.name}] Warning: Credentials file not found at {cred_file}")
            return

        try:
            with open(cred_file, 'r') as f:
                credentials = yaml.safe_load(f) or {}

            # 3. Look up profile or default type
            lookups = []
            if self.profile:
                lookups.append(self.profile)
            lookups.append(Constants.ServiceType.IRI)

            section_creds = None
            used_key = None

            for key in lookups:
                if key in credentials:
                    section_creds = credentials[key]
                    used_key = key
                    break

            if section_creds:
                self.api_key = section_creds.get('api_key')
                self.api_endpoint = section_creds.get('api_endpoint')

                if not self.api_key or not self.api_endpoint:
                    self.logger.warning(f"[{self.name}] Warning: Missing api_key or api_endpoint in credentials (section: {used_key})")
            else:
                 searched = f"'{self.profile}' or " if self.profile else ""
                 self.logger.warning(f"[{self.name}] Warning: Section {searched}'{Constants.ServiceType.IRI}' not found in credentials")

        except Exception as e:
            self.logger.error(f"[{self.name}] Error loading credentials: {e}")
    
    def _convert_to_iri_job_spec(self, job_spec: Union["JobSpec", IriJobSpec], name: str = None) -> IriJobSpec:
        """Convert AmSCROT JobSpec to IRI JobSpecInput format.

        Constructs IriJobSpec using direct keyword arguments rather than from_dict()
        to avoid pydantic setting None for absent fields in model_fields_set, which
        would cause those fields to be serialized as null and rejected by the API's
        min_length=1 constraints.

        Callers that already hold a typed ``IriJobSpec`` may pass it straight through.
        """
        from amsc_iri.models.resource_spec import ResourceSpec as IriResourceSpec
        from amsc_iri.models.job_attributes import JobAttributes as IriJobAttributes
        from amsc_iri.models.container import Container as IriContainer

        if isinstance(job_spec, IriJobSpec):
            if name and not job_spec.name:
                job_spec.name = name
            return job_spec

        # --- Executable / arguments ---
        executable = job_spec.executable or None
        arguments = job_spec.arguments or None

        # --- Keyword args for IriJobSpec (only set what we have) ---
        kwargs: dict = {"executable": executable}

        if arguments:
            kwargs["arguments"] = arguments

        # Job name
        job_name = name or (job_spec.name if hasattr(job_spec, "name") and job_spec.name else None)
        if job_name:
            kwargs["name"] = job_name

        # --- ResourceSpec ---
        if job_spec.resources:
            res_kwargs = {k: v for k, v in job_spec.resources.items() if v is not None}
            if res_kwargs:
                kwargs["resources"] = IriResourceSpec(**res_kwargs)

        # --- Attributes and top-level IriJobSpec fields ---
        # Fields that live directly on JobSpecInput (not in JobAttributes)
        JOBSPEC_DIRECT_FIELDS = {
            "directory", "stdout_path", "stderr_path", "stdin_path",
            "inherit_environment", "environment", "pre_launch", "post_launch", "launcher",
        }
        # Fields that belong in JobAttributes
        JOB_ATTRIBUTES_FIELDS = {
            "duration", "queue_name", "account", "reservation_id", "custom_attributes",
        }

        if job_spec.attributes:
            attrs = {k: v for k, v in job_spec.attributes.items() if v is not None}

            # Lift container dict -> IriContainer object
            container_data = attrs.pop("container", None)
            if container_data and isinstance(container_data, dict):
                kwargs["container"] = IriContainer.from_dict(container_data)
            elif container_data:
                kwargs["container"] = container_data

            # Lift all other direct JobSpecInput fields
            for field in JOBSPEC_DIRECT_FIELDS:
                val = attrs.pop(field, None)
                if val is not None:
                    kwargs[field] = val

            # Whatever remains goes into JobAttributes
            attrs_kwargs = {k: v for k, v in attrs.items() if k in JOB_ATTRIBUTES_FIELDS}
            unknown = {k: v for k, v in attrs.items() if k not in JOB_ATTRIBUTES_FIELDS}
            if unknown:
                self.logger.debug(
                    f"[{self.name}] Unmapped job attributes passed to JobAttributes: {list(unknown.keys())}"
                )
                attrs_kwargs.update(unknown)

            if attrs_kwargs:
                kwargs["attributes"] = IriJobAttributes(**attrs_kwargs)

        return IriJobSpec(**kwargs)
    
    def plan(self, job: "Job", skip_checks: bool = False) -> Dict:
        """Validate the job specification.

        Args:
            job: The Job object to validate.
            skip_checks: If True, all validation errors are downgraded
                to warnings and PlanError is never raised.
        """
        name = job.name or self.name
        self.logger.debug(f"[{self.name}] Planning IRI job for '{name}'...")
        
        errors = []
        warnings = []
        
        # Check if client is available
        if not self._available:
            msg = "IRI client not available - check credentials"
            if skip_checks:
                warnings.append(msg)
            else:
                raise PlanError(errors=[msg])
        
        resource_id = job.resource_id
        if not resource_id:
            errors.append("Job must have a resource_id")

        # Validate executable is present
        if not job.job_spec.executable:
            errors.append("Job spec must have an executable")
        
        # Try to convert to IRI format
        try:
            iri_spec = self._convert_to_iri_job_spec(job.job_spec)
        except Exception as e:
            errors.append(f"Failed to convert job spec: {e}")

        if resource_id and not errors:
            try:
                iri_resource = self._status_api.get_resource(resource_id=resource_id)
                if iri_resource and iri_resource.current_status:
                    if iri_resource.current_status != Status.UP:
                        # Fallback check if it was serialized as a bare string
                        if not (isinstance(iri_resource.current_status, str) and iri_resource.current_status == Status.UP.value):
                            status_val = iri_resource.current_status.value if hasattr(iri_resource.current_status, 'value') else str(iri_resource.current_status)
                            msg = f"Resource '{resource_id}' is not UP (current status: {status_val})"
                            errors.append(msg)
                elif iri_resource is None:
                    warnings.append(f"Resource '{resource_id}' not found.")
            except Exception as e:
                warnings.append(f"Could not verify status for resource '{resource_id}': {e}")

        if errors:
            if skip_checks:
                for err in errors:
                    self.logger.warning(f"[{self.name}] {err}")
                warnings.extend(errors)
                errors = []
            else:
                raise PlanError(errors=errors, warnings=warnings)

        self.logger.debug(f"[{self.name}] IRI Job Validated: {name}")
        if resource_id:
            self.logger.debug(f"[{self.name}]   Resource ID: {resource_id}")

        return {
            "status": AmscrotJobState.PLANNED.value,
            "warnings": warnings,
        }
    
    def create(self, job: "Job"):
        """Submit a job to the IRI facility."""
        name = job.name or self.name
        self.logger.debug(f"[{self.name}] Creating IRI job for '{name}'...")
        
        if not self._available:
            raise CreateError(errors=["IRI client not available - check credentials"])
        
        try:
            resource_id = job.resource_id
            if not resource_id:
                raise CreateError(errors=[f"Job '{name}' has no resource_id"])
            
            iri_spec = self._convert_to_iri_job_spec(job.job_spec, name=name)
            
            # Submit the job via the typed API (returns an IriJob model)
            iri_job: IriJob = self._compute_api.launch_job(
                resource_id=resource_id,
                job_spec_input=iri_spec
            )
            
            # Set job ID
            job.id = iri_job.id
            self._status = AmscrotJobState.PENDING.value
            self.logger.debug(f"[{self.name}] Job '{name}' submitted successfully. Job ID: {iri_job.id}")
                
        except CreateError:
            raise
        except Exception as e:
            raise CreateError(errors=[f"Error submitting job '{name}': {e}"]) from e
    
    def destroy(self, job: "Job"):
        """Cancel a job on the IRI facility."""
        name = job.name or self.name
        self.logger.debug(f"[{self.name}] Destroying IRI job for '{name}'...")
        
        if not self._available:
            raise DestroyError(errors=["IRI client not available - check credentials"])
        
        # Check if we have a job ID for this job
        if not job.id or not job.resource_id:
            raise DestroyError(errors=[f"Job ID or Resource ID missing for '{name}'. Cannot cancel."])
        
        try:
            # Cancel the job
            self._compute_api.cancel_job(
                resource_id=job.resource_id,
                job_id=job.id
            )
            
            self.logger.debug(f"[{self.name}] Job '{name}' (ID: {job.id}) cancelled.")
            self._status = AmscrotJobState.CANCELED.value
            
        except DestroyError:
            raise
        except Exception as e:
            raise DestroyError(errors=[f"Error cancelling job '{name}': {e}"]) from e
    
    def status(self, job: "Job") -> JobStatus:
        """Get the status of a job on the IRI facility."""
        name = job.name or self.name
        
        if not self._available:
            return JobStatus(state=self._status)
        
        # Check if we have a job ID for this job
        if not job.id or not job.resource_id:
            return JobStatus(
                state="UNKNOWN",
                message="Job ID or Resource ID missing, job likely not submitted"
            )
        
        try:
            # Get job via the typed API (returns an IriJob model)
            iri_job: IriJob = self._compute_api.get_job(
                resource_id=job.resource_id,
                job_id=job.id,
                historical=False,
                include_spec=False
            )

            # PBS removes completed jobs from the active queue; a None response
            # means the job is no longer tracked — treat as COMPLETED.
            if iri_job is None:
                self.logger.info(
                    f"[{self.name}] Job {job.id!r} not found in PBS queue; "
                    "assumed completed."
                )
                return JobStatus(
                    state=AmscrotJobState.COMPLETED.value,
                    message="Job no longer in PBS queue; assumed completed.",
                    job_id=job.id,
                    resource_id=job.resource_id,
                )

            # Map IRI JobState enum -> AmSCROT JobState
            amscrot_state = AmscrotJobState.UNKNOWN
            if iri_job.status and iri_job.status.state:
                amscrot_state = self._IRI_TO_AMSCROT.get(iri_job.status.state, AmscrotJobState.UNKNOWN)
            state_str = amscrot_state.value

            return JobStatus(
                state=state_str,
                message=iri_job.status.message if iri_job.status else None,
                exit_code=iri_job.status.exit_code if iri_job.status else None,
                job_id=job.id,
                resource_id=job.resource_id,
                provider_status=iri_job.status.to_dict() if iri_job.status else None,
            )

        except NotFoundException:
            # PBS removes completed jobs from the active queue — 404 means done.
            self.logger.info(
                f"[{self.name}] Job {job.id!r} not found in PBS queue (404); "
                "assumed completed."
            )
            return JobStatus(
                state=AmscrotJobState.COMPLETED.value,
                message="Job no longer in PBS queue; assumed completed.",
                job_id=job.id,
                resource_id=job.resource_id,
            )
        except BadRequestException as e:
            # ALCF returns 400 (not 404) when a finished job has left the PBS
            # queue. Detect by "not found" in the detail; treat as COMPLETED.
            body = getattr(e, "body", "") or ""
            if "not found" in body.lower():
                self.logger.info(
                    f"[{self.name}] Job {job.id!r} not found in PBS queue (400); "
                    "assumed completed."
                )
                return JobStatus(
                    state=AmscrotJobState.COMPLETED.value,
                    message="Job no longer in PBS queue; assumed completed.",
                    job_id=job.id,
                    resource_id=job.resource_id,
                )
            self.logger.error(f"[{self.name}] Error reading status for '{name}': {e}")
            return JobStatus(state="UNKNOWN", message=str(e))
        except Exception as e:
            self.logger.error(f"[{self.name}] Error reading status for '{name}': {e}")
            return JobStatus(
                state="UNKNOWN",
                message=str(e)
            )

    def get_incidents(self, **filters) -> List[Any]:
        """Fetch all incidents from the IRI API.

        Args:
            **filters: Optional filter kwargs forwarded to ``get_incidents()``
                (e.g. ``status``, ``resource_id``, ``var_from``, ``to``).

        Returns:
            List of ``amsc_iri.models.Incident`` objects.
        """
        if not self._available:
            return []
        try:
            incidents = self._status_api.get_incidents(**filters)
            return list(incidents) if incidents else []
        except Exception as exc:
            self.logger.warning(f"[{self.name}] Could not fetch incidents: {exc}")
            return []

    def get_incident(self, incident_id: str) -> Optional[Any]:
        """Fetch a single incident by ID from the IRI API.

        Args:
            incident_id: UUID of the incident to retrieve.

        Returns:
            ``amsc_iri.models.Incident``, or ``None`` if not found / unavailable.
        """
        if not self._available:
            return None
        try:
            return self._status_api.get_incident(incident_id=incident_id)
        except Exception as exc:
            self.logger.warning(
                f"[{self.name}] Could not fetch incident {incident_id!r}: {exc}"
            )
            return None

    def get_events(self, incident_id: str) -> List[Any]:
        """Fetch events for a given incident ID from the IRI API.

        Args:
            incident_id: The UUID of the incident to fetch events for.

        Returns:
            List of ``amsc_iri.models.Event`` objects.
        """
        if not self._available:
            return []
        try:
            events = self._status_api.get_events_by_incident(incident_id=incident_id)
            return list(events) if events else []
        except Exception as exc:
            self.logger.warning(
                f"[{self.name}] Could not fetch events for incident {incident_id!r}: {exc}"
            )
            return []

    def get_facility_info(self) -> Any:
        """Fetch facility-level metadata from the IRI API.

        Returns:
            Native ``amsc_iri`` facility object, or ``None`` if unavailable.
        """
        if not self._available:
            return None
        try:
            return self._facility_api.get_facility()
        except Exception as exc:
            self.logger.warning(f"[{self.name}] Could not fetch facility info: {exc}")
            return None

    def get_resource_by_id(self, resource_id: str) -> Optional[Any]:
        """Fetch a single resource by UUID from the IRI API.

        Args:
            resource_id: UUID of the resource to retrieve.

        Returns:
            Resource data dict, or ``None`` if not found / unavailable.
        """
        if not self._available:
            return None
        try:
            resource = self._status_api.get_resource(resource_id=resource_id)
            return resource.to_dict() if resource else None
        except Exception as exc:
            self.logger.warning(
                f"[{self.name}] Could not fetch resource {resource_id!r}: {exc}"
            )
            return None

    def get_jobs(self, resource_id: str) -> List[Any]:
        """Fetch all jobs for a resource from the IRI API.

        Args:
            resource_id: UUID of the resource to list jobs for.

        Returns:
            List of job data dicts.
        """
        if not self._available:
            return []
        try:
            jobs = self._compute_api.get_jobs(resource_id=resource_id)
            return [j.to_dict() for j in jobs] if jobs else []
        except Exception as exc:
            self.logger.warning(
                f"[{self.name}] Could not fetch jobs for resource {resource_id!r}: {exc}"
            )
            return []

    # -- Filesystem interface -------------------------------------------------

    @property
    def filesystem(self) -> Optional[IriFilesystem]:
        """Return the IRI filesystem interface for this client.

        Returns ``None`` if the client is not available (e.g. missing credentials).
        The interface is created lazily on first access and reused thereafter.
        """
        if not self._available:
            return None
        if self._filesystem is None:
            self._filesystem = IriFilesystem(
                filesystem_api=self._filesystem_api,
                task_api=self._task_api,
                logger=self.logger,
                client_name=self.name,
            )
        return self._filesystem

    # -- Output file retrieval -------------------------------------------------

    def _get_storage_resource_id(self, compute_resource_id: str) -> str:
        """Resolve an available storage resource ID for filesystem operations.

        Strategy:
          1. Get all available storage resources.
          2. Prefer one with ``home`` in its name.
          3. Fall back to any available storage resource.

        A resource is considered available when its ``current_status`` is ``up``.
        Returns ``None`` if no suitable storage resource is found.
        """
        try:
            storage_resources = self._status_api.get_resources(
                resource_type=ResourceType.STORAGE
            ) or []

            def _is_available(res) -> bool:
                if res.current_status is None:
                    return True  # assume available if status unknown
                status_val = (
                    res.current_status.value
                    if hasattr(res.current_status, 'value')
                    else str(res.current_status)
                )
                return status_val == 'up'

            available = [res for res in storage_resources if _is_available(res)]

            # Prefer a storage resource with "home" in the name
            for res in available:
                name = (res.name or '').lower()
                if 'home' in name:
                    self.logger.info(
                        f"[{self.name}] Using home storage resource "
                        f"'{res.id}' (name='{res.name}')."
                    )
                    return res.id

            # Fall back to any available storage resource
            if available:
                res = available[0]
                self.logger.info(
                    f"[{self.name}] Using fallback storage resource "
                    f"'{res.id}' (name='{res.name}')."
                )
                return res.id

            self.logger.warning(
                f"[{self.name}] No available storage resource found."
            )
        except Exception as e:
            self.logger.error(
                f"[{self.name}] Error resolving storage resource: {e}"
            )
        return None

    def fetch_output_files(self, job: "Job", session_dir: str,
                           storage_resource_id: str = None) -> Dict[str, str]:
        """Download remote stdout/stderr files for a Job to a local directory.

        Reads ``stdout_path`` and ``stderr_path`` from ``job.job_spec.attributes``,
        downloads them via the IRI FilesystemApi, saves them under *session_dir*,
        and populates ``job.local_files`` with the resulting local paths.

        Args:
            job:                  The Job whose output files to fetch.
            session_dir:          Local directory to write files into.
            storage_resource_id:  Storage resource to use for filesystem ops.
                                  If ``None``, auto-resolved from available
                                  storage resources.

        Returns:
            Dict mapping stream name -> local file path.
        """
        if not self._available:
            self.logger.warning(f"[{self.name}] Client unavailable -- cannot fetch output files.")
            return {}

        compute_resource_id = job.resource_id
        if not compute_resource_id:
            self.logger.warning(f"[{self.name}] Job '{job.name}' has no resource_id. Cannot fetch output.")
            return {}

        # Use explicit storage_resource_id or resolve from compute resource group
        if not storage_resource_id:
            storage_resource_id = self._get_storage_resource_id(compute_resource_id)
        if not storage_resource_id:
            self.logger.error(
                f"[{self.name}] Cannot fetch output files -- no storage resource "
                f"found for compute resource '{compute_resource_id}'."
            )
            return {}

        fs = self.filesystem
        attrs = job.job_spec.attributes or {}
        results: Dict[str, str] = {}

        for stream, attr_key in [('stdout', 'stdout_path'), ('stderr', 'stderr_path')]:
            remote_path = attrs.get(attr_key)
            if not remote_path:
                continue

            local_path = os.path.join(session_dir, f"{stream}.log")

            try:
                self.logger.debug(
                    f"[{self.name}] Downloading {stream} from '{remote_path}' "
                    f"for job '{job.name}'..."
                )
                fs.download(
                    storage_resource_id,
                    remote_path=remote_path,
                    local_path=local_path,
                )
                results[stream] = local_path
                self.logger.debug(
                    f"[{self.name}] Saved {stream} for '{job.name}' -> {local_path}"
                )
            except FilesystemError as e:
                self.logger.warning(
                    f"[{self.name}] Could not fetch {stream} for '{job.name}': {e}"
                )
            except Exception as e:
                self.logger.error(
                    f"[{self.name}] Error fetching {stream} for '{job.name}': {e}"
                )

        # Store results back on the Job object
        job.local_files.update(results)
        return results
