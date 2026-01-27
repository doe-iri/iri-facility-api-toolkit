import os
import yaml
from pathlib import Path
from typing import Dict, TYPE_CHECKING
from ..serviceclient import ServiceClient
from ...util.constants import Constants

# Import the generated ESnet IRI client
from .generated.esnet_iri.client import AuthenticatedClient
from .generated.esnet_iri.api.compute import launch_job, get_jobs, cancel_job
from .generated.esnet_iri.models.job_spec import JobSpec as IriJobSpec
from .generated.esnet_iri.models.job import Job as IriJob
from .generated.esnet_iri.models.resource_spec import ResourceSpec
from .generated.esnet_iri.models.job_attributes import JobAttributes

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec

class EsnetIriServiceClient(ServiceClient):
    """ServiceClient implementation for ESnet IRI compute jobs."""
    
    def __init__(self, **kwargs):
        super().__init__(type=Constants.ServiceType.ESNET_IRI, **kwargs)
        
        # Load credentials from ~/.amscrot/credentials.yml
        self.api_key = None
        self.endpoint = None
        self._load_credentials()
        
        # Initialize the authenticated client
        self._client = None
        if self.api_key and self.endpoint:
            self._client = AuthenticatedClient(
                base_url=self.endpoint,
                token=self.api_key,
                verify_ssl=True
            )
            self._available = True
        else:
            self._available = False
            print(f"[{self.name}] Warning: Could not load ESnet IRI credentials.")
        
        # Track submitted jobs: {job_name: (resource_id, job_id)}
        self._submitted_jobs = {}
    
    def _load_credentials(self):
        """Load ESnet IRI credentials from ~/.amscrot/credentials.yml"""
        cred_file = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
        
        if not os.path.exists(cred_file):
            print(f"[{self.name}] Warning: Credentials file not found at {cred_file}")
            return
        
        try:
            with open(cred_file, 'r') as f:
                credentials = yaml.safe_load(f)
            
            if Constants.ServiceType.ESNET_IRI in credentials:
                iri_creds = credentials[Constants.ServiceType.ESNET_IRI]
                self.api_key = iri_creds.get('api_key')
                self.endpoint = iri_creds.get('endpoint')
                
                if not self.api_key or not self.endpoint:
                    print(f"[{self.name}] Warning: Missing api_key or endpoint in credentials")
            else:
                print(f"[{self.name}] Warning: 'esnet-iri' section not found in credentials")
        except Exception as e:
            print(f"[{self.name}] Error loading credentials: {e}")
    
    def _convert_to_iri_job_spec(self, job_spec: "JobSpec", name: str = None) -> IriJobSpec:
        """Convert AmSCROT JobSpec to ESnet IRI JobSpec format."""
        # Extract the executable - use the first element if it's a list
        executable = job_spec.executable
        if isinstance(executable, list) and len(executable) > 0:
            executable = executable[0]
        elif not executable:
            executable = "echo"  # Default fallback
        
        # Create the IRI JobSpec
        iri_spec = IriJobSpec(
            executable=executable,
        )
        
        # Add arguments if present
        if job_spec.executable and isinstance(job_spec.executable, list) and len(job_spec.executable) > 1:
            iri_spec.arguments = job_spec.executable[1:]
        
        # Add name if present (prioritize argument, then check JobSpec attribute if exists)
        if name:
            iri_spec.name = name
        elif hasattr(job_spec, 'name') and job_spec.name:
            iri_spec.name = job_spec.name
            
        # Add resources if present
        if job_spec.resources:
            iri_spec.resources = ResourceSpec.from_dict(job_spec.resources)
            
        # Add attributes if present (excluding resource_id which is handled separately)
        if job_spec.attributes:
            attrs = job_spec.attributes.copy()
            
            # Extract resource_id
            if 'resource_id' in attrs:
                del attrs['resource_id']
                
            # Extract directory if present
            if 'directory' in attrs:
                iri_spec.directory = attrs.pop('directory')
                
            # Extract standard I/O paths
            if 'stdout_path' in attrs:
                iri_spec.stdout_path = attrs.pop('stdout_path')
            if 'stderr_path' in attrs:
                iri_spec.stderr_path = attrs.pop('stderr_path')
            if 'stdin_path' in attrs:
                iri_spec.stdin_path = attrs.pop('stdin_path')
                
            # Remaining attributes go to JobAttributes
            if attrs:
                iri_spec.attributes = JobAttributes.from_dict(attrs)
        
        return iri_spec
    
    def _get_resource_id(self, job_spec: "JobSpec") -> str:
        """Extract resource_id from JobSpec attributes."""
        if job_spec.attributes and 'resource_id' in job_spec.attributes:
            return job_spec.attributes['resource_id']
        
        # Fallback to a default if not specified (for testing)
        print(f"[{self.name}] Warning: No resource_id in job attributes, using default")
        return "fb0aafe1-c780-55c0-b635-a7121f1b0ce5"
    
    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        """Validate the job specification."""
        name = job_name or self.name
        print(f"[{self.name}] Planning ESnet IRI job for '{name}'...")
        
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
            print(f"[{self.name}] Plan FAILED for '{name}' with {len(errors)} errors.")
        else:
            print(f"[{self.name}] ESnet IRI Job Validated: {name}")
            if resource_id:
                print(f"[{self.name}]   Resource ID: {resource_id}")
        
        return {
            "status": status,
            "errors": errors,
            "warnings": warnings
        }
    
    def create(self, job_spec: "JobSpec", job_name: str = None):
        """Submit a job to ESnet IRI."""
        name = job_name or self.name
        print(f"[{self.name}] Creating ESnet IRI job for '{name}'...")
        
        if not self._available:
            print(f"[{self.name}] ESnet IRI client unavailable. Skipping submission.")
            self._status = "ERROR"
            return
        
        try:
            # Get resource_id and convert job spec
            resource_id = self._get_resource_id(job_spec)
            iri_spec = self._convert_to_iri_job_spec(job_spec, name=name)
            
            # Submit the job
            response = launch_job.sync(
                resource_id=resource_id,
                client=self._client,
                body=iri_spec
            )
            
            # Handle response
            if isinstance(response, IriJob):
                job_id = response.id
                self._submitted_jobs[name] = (resource_id, job_id)
                self._status = "SUBMITTED"
                print(f"[{self.name}] Job '{name}' submitted successfully. Job ID: {job_id}")
            else:
                # Error response
                print(f"[{self.name}] Error submitting job '{name}': {response}")
                self._status = "ERROR"
                
        except Exception as e:
            print(f"[{self.name}] Error submitting job '{name}': {e}")
            self._status = "ERROR"
    
    def destroy(self, job_name: str = None):
        """Cancel a job on ESnet IRI."""
        name = job_name or self.name
        print(f"[{self.name}] Destroying ESnet IRI job for '{name}'...")
        
        if not self._available:
            print(f"[{self.name}] ESnet IRI client unavailable.")
            return
        
        # Check if we have a job ID for this job
        if name not in self._submitted_jobs:
            print(f"[{self.name}] No job ID found for '{name}'. Cannot cancel.")
            return
        
        try:
            resource_id, job_id = self._submitted_jobs[name]
            
            # Cancel the job
            response = cancel_job.sync(
                resource_id=resource_id,
                job_id=job_id,
                client=self._client
            )
            
            print(f"[{self.name}] Job '{name}' (ID: {job_id}) cancelled.")
            self._status = "DESTROYED"
            
            # Remove from tracking
            del self._submitted_jobs[name]
            
        except Exception as e:
            print(f"[{self.name}] Error cancelling job '{name}': {e}")
    
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
            
            # Get job status
            response = get_jobs.sync(
                resource_id=resource_id,
                job_id=job_id,
                client=self._client,
                historical=False,
                include_spec=False
            )
            
            if isinstance(response, IriJob):
                # Map IRI job state to AmSCROT status
                status_str = "UNKNOWN"
                if response.status:
                    # The JobStatus object has a state field
                    job_state = getattr(response.status, 'state', None)
                    
                    # If it's a dict, try getting the key
                    if job_state is None and isinstance(response.status, dict):
                        job_state = response.status.get('state')
                        
                    if job_state is not None:
                        # Map job states (these are from JobState enum or string values from API)
                        # Typical states: NEW=0, QUEUED=1, ACTIVE=2, COMPLETED=3, FAILED=4, CANCELED=5
                        state_map = {
                            0: "QUEUED",      # NEW
                            1: "QUEUED",      # QUEUED
                            2: "RUNNING",     # ACTIVE
                            3: "DONE",        # COMPLETED
                            4: "ERROR",       # FAILED
                            5: "DESTROYED",   # CANCELED
                            "NEW": "QUEUED",
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
                    "iri_response": str(response.status) if response.status else None
                }
            else:
                # Error response
                return {
                    "status": "UNKNOWN",
                    "error": f"Unexpected response: {response}"
                }
                
        except Exception as e:
            print(f"[{self.name}] Error reading status for '{name}': {e}")
            return {
                "status": "UNKNOWN",
                "error": str(e)
            }
