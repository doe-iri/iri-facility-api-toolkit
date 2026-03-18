from typing import Dict, List, Any, Optional
from ..serviceclient import ServiceClient, PlanError, CreateError, DestroyError
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult, DiscoveredResource
from ...client.job import JobStatus, JobState
from sense.client.requestwrapper import RequestWrapper
from sense.client.discover_api import DiscoverApi
from sense.client.profile_api import ProfileApi
from sense.client.workflow_combined_api import WorkflowCombinedApi
import json
import os
from pathlib import Path
import yaml


class AmscIroServiceClient(ServiceClient):
    """ServiceClient for AMSC-IRO using sense-o-py API."""

    def __init__(self, **kwargs):
        if 'type' not in kwargs:
            kwargs['type'] = Constants.ServiceType.AMSC_IRO
        super().__init__(**kwargs)
        
        # Track per-job state locally for now
        self._job_states: Dict[str, str] = {}
        
        # Load credentials natively if not yet provided
        self.api_key = kwargs.get('api_key')
        self._load_credentials()
            
        if not self.api_key:
            self.logger.warning(f"[{self.name}] No api_key provided for AMSC_IRO service client, ApiClient initialization may fail.")
            
        sense_config = {
            'API_ENDPOINT': self.endpoint_uri,
            'ACCESS_TOKEN': self.api_key,
            # Dummy params required by ApiClient validation
            'AUTH_ENDPOINT': 'dummy',
            'CLIENT_ID': 'dummy',
            'SECRET': 'dummy'
        }
        
        # Sense-O-Py ApiClient will throw an exception if config fails validation
        try:
            self._api_client = RequestWrapper(sense_config)
            self._available = True
        except Exception as e:
            self.logger.error(f"Failed to initialize AMSC_IRO ApiClient: {e}")
            self._api_client = None
            self._available = False

    def _load_credentials(self):
        """Load AMSC IRO credentials from self.credential or file."""
        if self.credential:
            try:
                creds = self.credential if isinstance(self.credential, dict) else self.credential.to_dict()
                if creds.get('api_key'): self.api_key = creds.get('api_key')
                if creds.get('api_endpoint'): self.endpoint_uri = creds.get('api_endpoint')
                return
            except Exception as e:
                self.logger.error(f"[{self.name}] Error loading from credential object: {e}")

        # Load from file if profile exists
        if self.profile:
            default_file = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
            cred_file = self.credential_file or default_file
            cred_file = os.path.expanduser(cred_file)
            
            if os.path.exists(cred_file):
                try:
                    with open(cred_file, 'r') as f:
                        config = yaml.safe_load(f)
                        if config and self.profile in config:
                            creds = config[self.profile]
                            if creds.get('api_key'): self.api_key = creds.get('api_key')
                            if creds.get('api_endpoint'): self.endpoint_uri = creds.get('api_endpoint')
                except Exception as e:
                    self.logger.error(f"[{self.name}] Failed to parse credentials file: {e}")

    def discover(self, native: bool = True) -> DiscoveryResult:
        self.logger.info(f"[{self.name}] [AMSC_IRO] Discovering resources")
        if not self._api_client:
            self.logger.warning(f"[{self.name}] Client not initialized, returning empty discovery.")
            return DiscoveryResult(items=[])

        discover_api = DiscoverApi(req_wrapper=self._api_client)
        
        items = []
        try:
            response = discover_api.discover_iri_facility_get()
            facilities = response.get('facilities', []) if isinstance(response, dict) else []
            for f in facilities:
                # Map sense-o-py fields to typical amscrot resource fields
                f_data = {
                    'id': f.get('facility_uri'),
                    'name': f.get('facility_name', 'Unknown'),
                    **f
                }
                items.append(DiscoveredResource(
                    type=Constants.RES_FACILITY,
                    name=f_data['name'],
                    data=f_data
                ))
        except Exception as e:
            self.logger.error(f"[{self.name}] Failed to discover iri_facilities: {e}")
            
        return DiscoveryResult(items=items)

    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        name = job_name or self.name
        self.logger.info(f"[{self.name}] [AMSC_IRO] Planning '{name}'")
        
        intent = job_spec.attributes.get("intent")
        if not intent:
            raise PlanError(["Missing 'intent' attribute in JobSpec for AMSC_IRO planning"])

        if not self._api_client:
            raise PlanError(["AMSC_IRO client not properly initialized"])

        profile_api = ProfileApi(req_wrapper=self._api_client)
        try:
            # profile_describe implicitly uses profile_search_get which searches by name or UUID
            profile = profile_api.profile_describe(desc=intent)
        except Exception as e:
            raise PlanError([f"Failed to lookup intent profile '{intent}': {e}"])
            
        if not profile:
            raise PlanError([f"No intent profile found for '{intent}'"])
            
        if not profile.get("editable"):
            raise PlanError([f"Profile '{intent}' is not marked as editable"])

        return {
            "resource": {
                "profile_name": profile.get("name"),
                "profile_uuid": profile.get("uuid"),
                "editable": True,
                "status": "Ready for intent edits"
            },
            "job": {
                "name": name,
                "status": "planned"
            }
        }

    def create(self, job_spec: "JobSpec", job_name: str = None):
        name = job_name or self.name
        self.logger.info(f"[{self.name}] [AMSC_IRO] Creating '{name}'")
        
        intent = job_spec.attributes.get("intent")
        if not intent:
            raise CreateError(["Missing 'intent' attribute in JobSpec for AMSC_IRO creation"])

        profile_api = ProfileApi(req_wrapper=self._api_client)
        try:
            profile = profile_api.profile_describe(desc=intent)
            intent_uuid = profile.get("uuid")
        except Exception as e:
             raise CreateError([f"Failed to lookup intent profile '{intent}': {e}"])
            
        options = {}
        if name:
            options["data.jobs[0].name"] = name
            
        if job_spec.executable:
            # The executable array in the profile uses index 2 for the script
            # In JobSpec, executable is a string representing the script 
            options["data.jobs[0].executable[2]"] = job_spec.executable

        # Resources mapping
        if job_spec.resources.get("cpu_cores_per_process"):
            options["data.jobs[0].resource_spec.cpu_cores_per_process"] = str(job_spec.resources.get("cpu_cores_per_process"))
        if job_spec.resources.get("node_count"):
            options["data.jobs[0].resource_spec.node_count"] = str(job_spec.resources.get("node_count"))
        if job_spec.resources.get("processes_per_node"):
            options["data.jobs[0].resource_spec.processes_per_node"] = str(job_spec.resources.get("processes_per_node"))

        # Custom attribute duration mapping
        if job_spec.attributes.get("duration"):
            options["data.jobs[0].attributes.duration"] = str(job_spec.attributes.get("duration"))
            
        req_intent = {
            "service_profile_uuid": intent_uuid,
            "queries": [
                {
                    "ask": "edit",
                    "options": [options]
                }
            ]
        }
        
        workflow_api = WorkflowCombinedApi(req_wrapper=self._api_client)
        try:
            # Creates an intent session/instance
            si_uuid = workflow_api.instance_new()
            # Computes orchestration via intent
            workflow_api.instance_create(json.dumps(req_intent))
            # Actually commits and provisions the workflow
            workflow_api.instance_operate('provision', sync='true')
            
            # Save mapping locally
            if name:
                self._job_states[name] = si_uuid
                
        except Exception as e:
            # Try to clean up state if provisioning failed midway
            if workflow_api.si_uuid:
                workflow_api.instance_delete()
            raise CreateError([f"Failed to create and provision intent for {name}: {e}"])

        self.logger.info(f"[{self.name}] Successfully created job intent {name} with SI UUID {si_uuid}")

    def destroy(self, job_name: str = None):
        name = job_name or self.name
        self.logger.info(f"[{self.name}] [AMSC_IRO] Destroying '{name}'")
        si_uuid = self._job_states.get(name)
        if not si_uuid:
            self.logger.warning(f"No tracked SI UUID for job '{name}', cannot destroy/cancel.")
            return
            
        workflow_api = WorkflowCombinedApi(req_wrapper=self._api_client)
        workflow_api.si_uuid = si_uuid
        try:
            status = workflow_api.instance_get_status()
            if 'FAILED' in status:
                workflow_api.instance_operate('cancel', force='true', sync='true')
            elif 'READY' in status and 'CANCEL' not in status:
                workflow_api.instance_operate('cancel', sync='true')
            
            self._job_states.pop(name, None)
            self.logger.info(f"[{self.name}] Successfully canceled instance {si_uuid}")
        except Exception as e:
            raise DestroyError([f"Failed to cancel instance {si_uuid}: {e}"])

    def status(self, job_name: str = None) -> JobStatus:
        name = job_name or self.name
        si_uuid = self._job_states.get(name)
        if not si_uuid:
            return JobStatus(state=JobState.UNKNOWN, message="No known SI UUID in memory for AMSC_IRO")
            
        workflow_api = WorkflowCombinedApi(req_wrapper=self._api_client)
        workflow_api.si_uuid = si_uuid
        try:
            orch_status = workflow_api.instance_get_status()
            conf_status = workflow_api.instance_get_status(status='configstate')
            
            # Basic mapping
            state = JobState.PENDING
            if 'READY' in orch_status:
                state = JobState.ACTIVE
            if 'CANCEL' in orch_status:
                state = JobState.CANCELED
            if 'FAILED' in orch_status:
                state = JobState.FAILED
            if 'FINISHED' in orch_status:
                state = JobState.COMPLETED
                
            return JobStatus(
                state=state,
                job_id=si_uuid,
                message=f"Orchestration: {orch_status}, Configuration: {conf_status}"
            )
        except Exception as e:
            return JobStatus(state=JobState.UNKNOWN, message=str(e))
