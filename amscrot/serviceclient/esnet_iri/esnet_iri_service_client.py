import os
import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, TYPE_CHECKING
from ..serviceclient import ServiceClient
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult, DiscoveredResource

# Import the generated ESnet IRI client (installed via pip from generated/)
from esnet_iri.configuration import Configuration as IriConfiguration
from esnet_iri.api_client import ApiClient as IriApiClient
from esnet_iri.api.compute_api import ComputeApi
from esnet_iri.api.status_api import StatusApi
from esnet_iri.api.facility_api import FacilityApi
from esnet_iri.api.account_api import AccountApi
from esnet_iri.models.job_spec_input import JobSpecInput as IriJobSpec
from esnet_iri.models.resource_type import ResourceType
from esnet_iri.models.resource_spec import ResourceSpec
from esnet_iri.models.job_attributes import JobAttributes

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec

class EsnetIriServiceClient(ServiceClient):
    """ServiceClient implementation for ESnet IRI compute jobs."""
    
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
                self.logger.info(f"[{self.name}] Discovering {item_type} resources...")
                resources = self._status_api.get_resources(resource_type=res_type)
                if resources:
                    for res in resources:
                        items.append(DiscoveredResource(type=item_type, data=res.to_dict()))

            # 2. Discover Facilities (Sites)
            self.logger.info(f"[{self.name}] Discovering facilities...")
            sites = self._facility_api.get_sites()
            if sites:
                for site in sites:
                    items.append(DiscoveredResource(type="facility", data=site.to_dict()))

            # 3. Discover Capabilities
            self.logger.info(f"[{self.name}] Discovering capabilities...")
            capabilities = self._account_api.get_capabilities()
            if capabilities:
                for cap in capabilities:
                    items.append(DiscoveredResource(type="capability", data=cap.to_dict()))

            # 4. Discover Allocations (via Projects)
            self.logger.info(f"[{self.name}] Discovering allocations...")
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

        self.logger.info(f"[{self.name}] Discovery complete. Found {len(items)} items.")
        return DiscoveryResult(items=items)

    def _discover_normalized(self) -> DiscoveryResult:
        """Aggregate raw API resources into typed Facility objects.

        Relationships between facilities and resources are resolved by inspecting
        each facility's ``resource_uris``, extracting the UUID tail of each URI,
        and matching it against the ``id`` of native resource items — no extra
        HTTP calls required.  Covers compute, storage, and network resource types.
        """
        from ...model.metadata import Compute, Storage, Network, Allocation, Facility

        if not self._api_client:
            self.logger.warning(f"[{self.name}] Warning: Client not initialized, returning empty discovery.")
            return DiscoveryResult()

        # ── 1. Collect raw items ──────────────────────────────────────────────
        native_result = self._discover_native()

        # ── 2. Build resource_id → typed object maps ──────────────────────────
        def _build_compute(d: dict) -> Compute:
            return Compute(
                id=d.get("id"),
                name=d.get("name") or d.get("node_name"),
                description=d.get("description"),
                architecture=d.get("architecture"),
                cores=d.get("cores") or d.get("cpu_cores"),
                memory=str(d.get("memory_gb")) + "GiB" if d.get("memory_gb") else d.get("memory"),
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
                bandwidth_limit=str(d.get("bandwidth_mbps")) + "Mbps" if d.get("bandwidth_mbps") else d.get("bandwidth_limit"),
                external_connectivity=d.get("external_connectivity"),
            )

        # resource_id -> typed metadata object (Compute | Storage | Network)
        resource_map: dict = {}
        for item in native_result.by_type("compute"):
            d = item.data
            if d.get("id"):
                resource_map[d["id"]] = ("compute", _build_compute(d))
        for item in native_result.by_type("storage"):
            d = item.data
            if d.get("id"):
                resource_map[d["id"]] = ("storage", _build_storage(d))
        for item in native_result.by_type("network"):
            d = item.data
            if d.get("id"):
                resource_map[d["id"]] = ("network", _build_network(d))

        claimed_ids: set = set()

        # ── 3. Build per-facility resource lists via resource_uris ────────────
        site_meta: dict    = {}   # site_key -> raw site dict
        site_compute: dict = {}   # site_key -> List[Compute]
        site_storage: dict = {}   # site_key -> List[Storage]
        site_network: dict = {}   # site_key -> List[Network]
        site_alloc: dict   = {}   # site_key -> List[Allocation]

        for item in native_result.by_type("facility"):
            d = item.data
            site_key = d.get("id") or d.get("name") or "unknown"
            site_meta[site_key]    = d
            site_compute[site_key] = []
            site_storage[site_key] = []
            site_network[site_key] = []
            site_alloc[site_key]   = []

            for uri in d.get("resource_uris") or []:
                resource_id = uri.rstrip("/").rsplit("/", 1)[-1]
                if resource_id in resource_map:
                    rtype, robj = resource_map[resource_id]
                    if rtype == "compute":
                        site_compute[site_key].append(robj)
                    elif rtype == "storage":
                        site_storage[site_key].append(robj)
                    elif rtype == "network":
                        site_network[site_key].append(robj)
                    claimed_ids.add(resource_id)
                    self.logger.debug(
                        f"[{self.name}] Linked {rtype} {resource_id} → facility {site_key}"
                    )
                else:
                    self.logger.debug(
                        f"[{self.name}] URI tail {resource_id!r} has no matching native resource."
                    )

        # ── 4. Unclaimed resources → 'default' fallback bucket ─────────────── 
        unclaimed_compute = [obj for rid, (t, obj) in resource_map.items() if rid not in claimed_ids and t == "compute"]
        unclaimed_storage = [obj for rid, (t, obj) in resource_map.items() if rid not in claimed_ids and t == "storage"]
        unclaimed_network = [obj for rid, (t, obj) in resource_map.items() if rid not in claimed_ids and t == "network"]
        if unclaimed_compute or unclaimed_storage or unclaimed_network:
            site_meta.setdefault("default", {"id": "default", "name": "default"})
            site_compute.setdefault("default", []).extend(unclaimed_compute)
            site_storage.setdefault("default", []).extend(unclaimed_storage)
            site_network.setdefault("default", []).extend(unclaimed_network)
            site_alloc.setdefault("default", [])

        # ── 5. Map allocations to their project ───────────────────────────────
        for item in native_result.by_type("allocation"):
            d = item.data
            project_name = d.get("_project_name", "default")
            site_alloc.setdefault(project_name, [])
            site_compute.setdefault(project_name, [])
            site_storage.setdefault(project_name, [])
            site_network.setdefault(project_name, [])
            site_meta.setdefault(project_name, {"id": project_name, "name": project_name})
            site_alloc[project_name].append(Allocation(
                id=d.get("id"),
                name=d.get("name"),
                description=d.get("description"),
                account=project_name,
                qos=d.get("qos"),
                walltime_limit=d.get("walltime_limit") or d.get("max_walltime"),
                exclusive=d.get("exclusive"),
            ))

        # ── 6. Build one Facility per site ────────────────────────────────────
        result_items = []
        for site_key, raw in site_meta.items():
            facility = Facility(
                id=raw.get("id"),
                name=raw.get("name") or site_key,
                description=raw.get("description"),
                compute=site_compute.get(site_key) or None,
                storage=site_storage.get(site_key) or None,
                networks=site_network.get(site_key) or None,
                allocations=site_alloc.get(site_key) or None,
            )
            result_items.append(DiscoveredResource(
                type="facility",
                data=raw,
                name=facility.name,
                metadata=facility,
            ))

        self.logger.info(
            f"[{self.name}] Normalized discovery complete. "
            f"{len(result_items)} facilities, {len(claimed_ids)} resource(s) linked via URI."
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
        """Convert AmSCROT JobSpec to ESnet IRI JobSpecInput format."""
        # Extract the executable - use the first element if it's a list
        executable = job_spec.executable
        arguments = None
        if isinstance(executable, list) and len(executable) > 0:
            if len(executable) > 1:
                arguments = executable[1:]
            executable = executable[0]
        elif not executable:
            executable = "echo"  # Default fallback

        # Build a plain dict to avoid pydantic cross-import validation issues
        spec_dict = {"executable": executable}

        if arguments:
            spec_dict["arguments"] = arguments

        # Add name if present (prioritize argument, then check JobSpec attribute if exists)
        if name:
            spec_dict["name"] = name
        elif hasattr(job_spec, 'name') and job_spec.name:
            spec_dict["name"] = job_spec.name

        # Add resources if present
        if job_spec.resources:
            spec_dict["resources"] = job_spec.resources

        # Add attributes if present (excluding resource_id which is handled separately)
        if job_spec.attributes:
            attrs = job_spec.attributes.copy()

            # Extract resource_id
            if 'resource_id' in attrs:
                del attrs['resource_id']

            # Extract directory if present
            if 'directory' in attrs:
                spec_dict["directory"] = attrs.pop('directory')

            # Extract standard I/O paths
            if 'stdout_path' in attrs:
                spec_dict["stdout_path"] = attrs.pop('stdout_path')
            if 'stderr_path' in attrs:
                spec_dict["stderr_path"] = attrs.pop('stderr_path')
            if 'stdin_path' in attrs:
                spec_dict["stdin_path"] = attrs.pop('stdin_path')
                
            # Remaining attributes go to JobAttributes
            if attrs:
                spec_dict["attributes"] = attrs
        
        return IriJobSpec.from_dict(spec_dict)
    
    def _get_resource_id(self, job_spec: "JobSpec") -> str:
        """Extract resource_id from JobSpec attributes."""
        if job_spec.attributes and 'resource_id' in job_spec.attributes:
            return job_spec.attributes['resource_id']
        
        # Fallback to a default if not specified (for testing)
        self.logger.warning(f"[{self.name}] Warning: No resource_id in job attributes! Using default.")
        return "fb0aafe1-c780-55c0-b635-a7121f1b0ce5"
    
    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        """Validate the job specification."""
        name = job_name or self.name
        self.logger.info(f"[{self.name}] Planning ESnet IRI job for '{name}'...")
        
        errors = []
        warnings = []
        
        # Check if client is available
        if not self._available:
            errors.append("ESnet IRI client not available - check credentials")
            return {
                "status": "FAILED",
                "errors": errors,
                "warnings": warnings
            }
        
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
        
        status = "PLANNED" if not errors else "FAILED"
        
        if errors:
            self.logger.error(f"[{self.name}] Plan FAILED for '{name}' with {len(errors)} errors.")
        else:
            self.logger.info(f"[{self.name}] ESnet IRI Job Validated: {name}")
            if resource_id:
                self.logger.debug(f"[{self.name}]   Resource ID: {resource_id}")
        
        return {
            "status": status,
            "errors": errors,
            "warnings": warnings
        }
    
    def create(self, job_spec: "JobSpec", job_name: str = None):
        """Submit a job to ESnet IRI."""
        name = job_name or self.name
        self.logger.info(f"[{self.name}] Creating ESnet IRI job for '{name}'...")
        
        if not self._available:
            self.logger.warning(f"[{self.name}] ESnet IRI client unavailable. Skipping submission.")
            self._status = "ERROR"
            return
        
        try:
            # Get resource_id and convert job spec
            resource_id = self._get_resource_id(job_spec)
            iri_spec = self._convert_to_iri_job_spec(job_spec, name=name)
            
            # Submit the job using raw response to avoid JobState deserialization issues
            raw_response = self._compute_api.launch_job_without_preload_content(
                resource_id=resource_id,
                job_spec_input=iri_spec
            )
            
            # Parse the raw JSON response
            response_data = json.loads(raw_response.data.decode('utf-8'))
            
            if raw_response.status == 200 and 'id' in response_data:
                job_id = response_data['id']
                self._submitted_jobs[name] = (resource_id, job_id)
                self._status = "SUBMITTED"
                self.logger.info(f"[{self.name}] Job '{name}' submitted successfully. Job ID: {job_id}")
            else:
                # Error response
                self.logger.error(f"[{self.name}] Error submitting job '{name}': {response_data}")
                self._status = "ERROR"
                
        except Exception as e:
            self.logger.error(f"[{self.name}] Error submitting job '{name}': {e}")
            self._status = "ERROR"
    
    def destroy(self, job_name: str = None):
        """Cancel a job on ESnet IRI."""
        name = job_name or self.name
        self.logger.info(f"[{self.name}] Destroying ESnet IRI job for '{name}'...")
        
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
            
            self.logger.info(f"[{self.name}] Job '{name}' (ID: {job_id}) cancelled.")
            self._status = "DESTROYED"
            
            # Remove from tracking
            del self._submitted_jobs[name]
            
        except Exception as e:
            self.logger.error(f"[{self.name}] Error cancelling job '{name}': {e}")
    
    def status(self, job_name: str = None) -> Dict:
        """Get the status of a job on ESnet IRI."""
        name = job_name or self.name
        
        if not self._available:
            return {"status": self._status}
        
        # Check if we have a job ID for this job
        if name not in self._submitted_jobs:
            return {
                "status": "UNKNOWN",
                "error": "Job not found or not yet submitted"
            }
        
        try:
            resource_id, job_id = self._submitted_jobs[name]
            
            # Get job status using raw response to avoid JobState deserialization issues
            raw_response = self._compute_api.get_job_without_preload_content(
                resource_id=resource_id,
                job_id=job_id,
                historical=False,
                include_spec=False
            )
            
            if raw_response.status == 200:
                response_data = json.loads(raw_response.data.decode('utf-8'))
                
                # Map IRI job state to AmSCROT status
                status_str = "UNKNOWN"
                job_status = response_data.get('status', {})
                if isinstance(job_status, dict):
                    job_state = job_status.get('state')
                elif isinstance(job_status, str):
                    job_state = job_status
                else:
                    job_state = None
                    
                if job_state is not None:
                    # Map job states (API returns string names)
                    state_map = {
                        0: "NEW",           # NEW
                        1: "QUEUED",      # QUEUED
                        2: "RUNNING",     # ACTIVE
                        3: "DONE",        # COMPLETED
                        4: "ERROR",       # FAILED
                        5: "DESTROYED",   # CANCELED
                        "NEW": "NEW",
                        "QUEUED": "QUEUED",
                        "ACTIVE": "RUNNING",
                        "COMPLETED": "DONE",
                        "FAILED": "ERROR",
                        "CANCELED": "DESTROYED"
                    }
                    status_str = state_map.get(job_state, "UNKNOWN")
                
                return {
                    "status": status_str,
                    "job_id": job_id,
                    "resource_id": resource_id,
                    "iri_response": job_status
                }
            else:
                # Non-200 response
                error_body = raw_response.data.decode('utf-8') if raw_response.data else 'No response body'
                self.logger.error(f"[{self.name}] Status check returned HTTP {raw_response.status}: {error_body}")
                return {
                    "status": "UNKNOWN",
                    "error": f"HTTP {raw_response.status}: {error_body}"
                }
                
        except Exception as e:
            self.logger.error(f"[{self.name}] Error reading status for '{name}': {e}")
            return {
                "status": "UNKNOWN",
                "error": str(e)
            }
