import os
import yaml
from pathlib import Path
from typing import Dict, List, Any, TYPE_CHECKING
from ..serviceclient import ServiceClient, PlanError
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult, DiscoveredResource
from ...client.job import JobStatus, JobState as AmscrotJobState

from esnet_iri.configuration import Configuration as IriConfiguration
from esnet_iri.api_client import ApiClient as IriApiClient
from esnet_iri.api.compute_api import ComputeApi
from esnet_iri.api.status_api import StatusApi
from esnet_iri.api.facility_api import FacilityApi
from esnet_iri.api.account_api import AccountApi
from esnet_iri.models.job_spec_input import JobSpecInput as IriJobSpec
from esnet_iri.models.resource_type import ResourceType
from esnet_iri.models.job_state import JobState as IriJobState
from esnet_iri.models.job import Job as IriJob

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec

class EsnetIriServiceClient(ServiceClient):
    """ServiceClient implementation for ESnet IRI compute jobs."""

    # Map IRI JobState enum → AmSCROT JobState (direct 1:1 alignment)
    _IRI_TO_AMSCROT = {
        IriJobState.NEW:       AmscrotJobState.NEW,
        IriJobState.QUEUED:    AmscrotJobState.QUEUED,
        IriJobState.ACTIVE:    AmscrotJobState.ACTIVE,
        IriJobState.COMPLETED: AmscrotJobState.COMPLETED,
        IriJobState.FAILED:    AmscrotJobState.FAILED,
        IriJobState.CANCELED:  AmscrotJobState.CANCELED,
    }

    def __init__(self, **kwargs):
        super().__init__(type=Constants.ServiceType.ESNET_IRI, **kwargs)
        
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
                api_key_prefix={'APIKeyHeader': 'Bearer'}
            )
            self._api_client = IriApiClient(configuration)
            self._compute_api = ComputeApi(self._api_client)
            self._status_api = StatusApi(self._api_client)
            self._facility_api = FacilityApi(self._api_client)
            self._account_api = AccountApi(self._api_client)
            self._available = True
        else:
            self._available = False
            self.logger.warning(f"[{self.name}] Warning: Could not load ESnet IRI credentials.")
        
        # Track submitted jobs: {job_name: (resource_id, job_id)}
        self._submitted_jobs = {}
    
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

        # ── 3. Find the single facility ───────────────────────────────────────
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
        """Load ESnet IRI credentials."""
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
                 pass # Silent warning as per previous behavior, or just print warning
                 self.logger.warning(f"[{self.name}] Warning: Credentials file not found at {cred_file}")
            return

        try:
            with open(cred_file, 'r') as f:
                credentials = yaml.safe_load(f) or {}

            # 3. Look up profile or default type
            lookups = []
            if self.profile:
                lookups.append(self.profile)
            lookups.append(Constants.ServiceType.ESNET_IRI)

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
                 self.logger.warning(f"[{self.name}] Warning: Section {searched}'{Constants.ServiceType.ESNET_IRI}' not found in credentials")

        except Exception as e:
            self.logger.error(f"[{self.name}] Error loading credentials: {e}")
    
    def _convert_to_iri_job_spec(self, job_spec: "JobSpec", name: str = None) -> IriJobSpec:
        """Convert AmSCROT JobSpec to ESnet IRI JobSpecInput format.

        Constructs IriJobSpec using direct keyword arguments rather than from_dict()
        to avoid pydantic setting None for absent fields in model_fields_set, which
        would cause those fields to be serialized as null and rejected by the API's
        min_length=1 constraints.
        """
        from esnet_iri.models.resource_spec import ResourceSpec as IriResourceSpec
        from esnet_iri.models.job_attributes import JobAttributes as IriJobAttributes

        # --- Executable / arguments ---
        executable = job_spec.executable
        arguments = None
        if isinstance(executable, list) and len(executable) > 0:
            if len(executable) > 1:
                arguments = executable[1:]
            executable = executable[0]
        elif not executable:
            executable = "echo"

        # --- Keyword args for IriJobSpec (only set what we have) ---
        kwargs: dict = {"executable": executable}

        if arguments:
            kwargs["arguments"] = arguments

        # Job name
        job_name = name or (job_spec.name if hasattr(job_spec, "name") and job_spec.name else None)
        if job_name:
            kwargs["name"] = job_name

        # --- ResourceSpec (typed model, no from_dict) ---
        if job_spec.resources:
            res = job_spec.resources
            res_kwargs: dict = {}
            if res.get("node_count") is not None:
                res_kwargs["node_count"] = res["node_count"]
            if res.get("process_count") is not None:
                res_kwargs["process_count"] = res["process_count"]
            if res.get("processes_per_node") is not None:
                res_kwargs["processes_per_node"] = res["processes_per_node"]
            if res.get("cpu_cores_per_process") is not None:
                res_kwargs["cpu_cores_per_process"] = res["cpu_cores_per_process"]
            if res.get("gpu_cores_per_process") is not None:
                res_kwargs["gpu_cores_per_process"] = res["gpu_cores_per_process"]
            if res.get("exclusive_node_use") is not None:
                res_kwargs["exclusive_node_use"] = res["exclusive_node_use"]
            if res.get("memory") is not None:
                res_kwargs["memory"] = res["memory"]
            kwargs["resources"] = IriResourceSpec(**res_kwargs)

        # --- Attributes and I/O paths ---
        if job_spec.attributes:
            attrs = job_spec.attributes.copy()

            # Remove resource_id — handled separately via _get_resource_id
            attrs.pop("resource_id", None)

            # I/O path fields live directly on IriJobSpec (min_length=1, only set if present)
            for field in ("directory", "stdout_path", "stderr_path", "stdin_path"):
                val = attrs.pop(field, None)
                if val:
                    kwargs[field] = val

            # Remaining attrs → JobAttributes typed model (no from_dict)
            if attrs:
                attr_kwargs: dict = {}
                if attrs.get("duration") is not None:
                    attr_kwargs["duration"] = attrs.pop("duration")
                if attrs.get("queue_name"):
                    attr_kwargs["queue_name"] = attrs.pop("queue_name")
                if attrs.get("account"):
                    attr_kwargs["account"] = attrs.pop("account")
                if attrs.get("reservation_id"):
                    attr_kwargs["reservation_id"] = attrs.pop("reservation_id")
                # Remaining unknown attrs go into custom_attributes
                if attrs:
                    attr_kwargs["custom_attributes"] = {k: str(v) for k, v in attrs.items()}
                kwargs["attributes"] = IriJobAttributes(**attr_kwargs)

        return IriJobSpec(**kwargs)
    
    def _get_resource_id(self, job_spec: "JobSpec") -> str:
        """Extract resource_id from JobSpec attributes."""
        if job_spec.attributes and 'resource_id' in job_spec.attributes:
            return job_spec.attributes['resource_id']
        
        # Fallback: if we've run discovery, use the first compute resource
        if hasattr(self, '_default_resource_id') and self._default_resource_id:
            return self._default_resource_id
            
        return None
    
    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        """Validate the job specification."""
        name = job_name or self.name
        self.logger.debug(f"[{self.name}] Planning ESnet IRI job for '{name}'...")
        
        errors = []
        warnings = []
        
        # Check if client is available
        if not self._available:
            raise PlanError(errors=["ESnet IRI client not available - check credentials"])
        
        # Validate resource_id is present
        resource_id = None
        try:
            resource_id = self._get_resource_id(job_spec)
        except Exception as e:
            errors.append(f"Failed to get resource_id: {e}")
        
        # Validate executable is present
        if not job_spec.executable:
            errors.append("Job spec must have an executable")
        
        # Try to convert to IRI format
        try:
            iri_spec = self._convert_to_iri_job_spec(job_spec)
        except Exception as e:
            errors.append(f"Failed to convert job spec: {e}")
        
        if errors:
            raise PlanError(errors=errors, warnings=warnings)

        self.logger.debug(f"[{self.name}] ESnet IRI Job Validated: {name}")
        if resource_id:
            self.logger.debug(f"[{self.name}]   Resource ID: {resource_id}")

        return {
            "status": AmscrotJobState.PLANNED.value,
            "warnings": warnings,
        }
    
    def create(self, job_spec: "JobSpec", job_name: str = None):
        """Submit a job to ESnet IRI."""
        name = job_name or self.name
        self.logger.debug(f"[{self.name}] Creating ESnet IRI job for '{name}'...")
        
        if not self._available:
            self.logger.warning(f"[{self.name}] ESnet IRI client unavailable. Skipping submission.")
            self._status = "ERROR"
            return
        
        try:
            # Get resource_id and convert job spec
            resource_id = self._get_resource_id(job_spec)
            iri_spec = self._convert_to_iri_job_spec(job_spec, name=name)
            
            # Submit the job via the typed API (returns an IriJob model)
            iri_job: IriJob = self._compute_api.launch_job(
                resource_id=resource_id,
                job_spec_input=iri_spec
            )
            
            self._submitted_jobs[name] = (resource_id, iri_job.id)
            self._status = AmscrotJobState.PENDING.value
            self.logger.debug(f"[{self.name}] Job '{name}' submitted successfully. Job ID: {iri_job.id}")
                
        except Exception as e:
            self.logger.error(f"[{self.name}] Error submitting job '{name}': {e}")
            self._status = "ERROR"
    
    def destroy(self, job_name: str = None):
        """Cancel a job on ESnet IRI."""
        name = job_name or self.name
        self.logger.debug(f"[{self.name}] Destroying ESnet IRI job for '{name}'...")
        
        if not self._available:
            self.logger.warning(f"[{self.name}] ESnet IRI client unavailable.")
            return
        
        # Check if we have a job ID for this job
        if name not in self._submitted_jobs:
            self.logger.warning(f"[{self.name}] No job ID found for '{name}'. Cannot cancel.")
            return
        
        try:
            resource_id, job_id = self._submitted_jobs[name]
            
            # Cancel the job
            self._compute_api.cancel_job(
                resource_id=resource_id,
                job_id=job_id
            )
            
            self.logger.debug(f"[{self.name}] Job '{name}' (ID: {job_id}) cancelled.")
            self._status = AmscrotJobState.CANCELED.value
            
            # Remove from tracking
            del self._submitted_jobs[name]
            
        except Exception as e:
            self.logger.error(f"[{self.name}] Error cancelling job '{name}': {e}")
    
    def status(self, job_name: str = None) -> JobStatus:
        """Get the status of a job on ESnet IRI."""
        name = job_name or self.name
        
        if not self._available:
            return JobStatus(state=self._status)
        
        # Check if we have a job ID for this job
        if name not in self._submitted_jobs:
            return JobStatus(
                state="UNKNOWN",
                message="Job not found or not yet submitted"
            )
        
        try:
            resource_id, job_id = self._submitted_jobs[name]
            
            # Get job via the typed API (returns an IriJob model)
            iri_job: IriJob = self._compute_api.get_job(
                resource_id=resource_id,
                job_id=job_id,
                historical=False,
                include_spec=False
            )
            
            # Map IRI JobState enum → AmSCROT JobState
            amscrot_state = AmscrotJobState.UNKNOWN
            if iri_job.status and iri_job.status.state:
                amscrot_state = self._IRI_TO_AMSCROT.get(iri_job.status.state, AmscrotJobState.UNKNOWN)
            state_str = amscrot_state.value
            
            return JobStatus(
                state=state_str,
                message=iri_job.status.message if iri_job.status else None,
                exit_code=iri_job.status.exit_code if iri_job.status else None,
                job_id=job_id,
                resource_id=resource_id,
                provider_status=iri_job.status.to_dict() if iri_job.status else None,
            )
                
        except Exception as e:
            self.logger.error(f"[{self.name}] Error reading status for '{name}': {e}")
            return JobStatus(
                state="UNKNOWN",
                message=str(e)
            )
