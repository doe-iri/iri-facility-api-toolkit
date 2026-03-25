from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING
from ..serviceclient import ServiceClient, PlanError, CreateError, DestroyError
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult, DiscoveredResource
from ...client.job import JobStatus, JobState
if TYPE_CHECKING:
    from amscrot.client.job import Job
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
            'AUTH_ENDPOINT': self.auth_endpoint,
            'FOREIGN_TOKEN': self.api_key,
            'FOREIGN_TOKEN_ISSUER': self.token_issuer,
            'CLIENT_ID': self.client_id,
            'SECRET': self.secret
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
        self.auth_endpoint = None
        self.client_id = 'dummy'
        self.secret = 'dummy'
        self.token_issuer = 'https://auth.globus.org'

        if self.credential:
            try:
                creds = self.credential if isinstance(self.credential, dict) else self.credential.to_dict()
                if creds.get('api_key'): self.api_key = creds.get('api_key')
                if creds.get('api_endpoint'): self.endpoint_uri = creds.get('api_endpoint')
                if creds.get('auth_endpoint'): self.auth_endpoint = creds.get('auth_endpoint')
                if creds.get('client_id'): self.client_id = creds.get('client_id')
                if creds.get('secret'): self.secret = creds.get('secret')
                if creds.get('token_issuer'): self.token_issuer = creds.get('token_issuer')
                return
            except Exception as e:
                self.logger.error(f"[{self.name}] Error loading from credential object: {e}")

        # Load from file if profile exists
        if getattr(self, 'profile', None):
            default_file = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
            cred_file = getattr(self, 'credential_file', None) or default_file
            cred_file = os.path.expanduser(cred_file)
            
            if os.path.exists(cred_file):
                try:
                    with open(cred_file, 'r') as f:
                        config = yaml.safe_load(f)
                        if config and self.profile in config:
                            creds = config[self.profile]
                            if creds.get('api_key'): self.api_key = creds.get('api_key')
                            if creds.get('api_endpoint'): self.endpoint_uri = creds.get('api_endpoint')
                            if creds.get('auth_endpoint'): self.auth_endpoint = creds.get('auth_endpoint')
                            if creds.get('client_id'): self.client_id = creds.get('client_id')
                            if creds.get('secret'): self.secret = creds.get('secret')
                            if creds.get('token_issuer'): self.token_issuer = creds.get('token_issuer')
                except Exception as e:
                    self.logger.error(f"[{self.name}] Failed to parse credentials file: {e}")

    def discover(self, native: bool = True) -> DiscoveryResult:
        self.logger.info(f"[{self.name}] Discovering resources")
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

        # Discover intent profiles
        try:
            from amscrot.model.intent import Intent
            profile_api = ProfileApi(req_wrapper=self._api_client)
            profiles = profile_api.profile_list()
            if profiles:
                profile_list = profiles if isinstance(profiles, list) else [profiles]
                for p in profile_list:
                    intent = Intent(data=p)
                    items.append(DiscoveredResource(
                        type="intent",
                        name=intent.name,
                        data=p,
                        metadata=intent,
                    ))
        except Exception as e:
            self.logger.error(f"[{self.name}] Failed to discover intent profiles: {e}")

        return DiscoveryResult(items=items)

    def _escape_multiline(self, text: str) -> str:
        # Order matters: escape backslashes first, then quotes, then newlines
        text = text.replace("\\", "\\\\")
        text = text.replace('"', '\\"')
        text = text.replace("\n", "\\n")
        return text

    def _unescape_multiline(self, text: str) -> str:
        # Order matters: unescape newlines, then quotes, then backslashes
        text = text.replace("\\n", "\n")
        text = text.replace('\\"', '"')
        text = text.replace("\\\\", "\\")
        return text

    def _prepare_intent(self, jobs: List["Job"], intent: str) -> Tuple[Dict, Dict, str]:
        if not self._api_client:
            raise Exception("AMSC_IRO client not properly initialized")

        profile_api = ProfileApi(req_wrapper=self._api_client)
        try:
            profile = profile_api.profile_describe(desc=intent)
        except Exception as e:
            raise Exception(f"Failed to lookup intent profile '{intent}': {e}")
            
        if not profile:
            raise Exception(f"No intent profile found for '{intent}'")
            
        if not profile.get("editable"):
            raise Exception(f"Profile '{intent}' is not marked as editable")

        intent_uuid = profile.get("uuid")
        profile_intent = profile.get("intent", {})
        profile_jobs = profile_intent.get("data", {}).get("jobs", [])

        edit_paths = None
        if "edit" in profile:
            edit_paths = set()
            for e in profile["edit"]:
                if isinstance(e, dict):
                    edit_paths.add(e.get("path"))
                elif hasattr(e, "path"):
                    edit_paths.add(e.path)

        def is_editable(path):
            if edit_paths is None:
                return True
            return path in edit_paths

        name_map = {}
        options = {}

        for i, job in enumerate(jobs):
            spec = job.job_spec
            
            if i < len(profile_jobs):
                pjob = profile_jobs[i]
                orig_name = pjob.get("name")
                if orig_name and job.name:
                    name_map[orig_name] = job.name
                
                # Apply defaults
                if "image" in pjob:
                    container = spec.attributes.setdefault("container", {})
                    if not container.get("image"):
                        container["image"] = pjob["image"]

                if not spec.executable and "executable" in pjob:
                    if isinstance(pjob["executable"], list) and len(pjob["executable"]) > 2:
                        spec.executable = self._unescape_multiline(pjob["executable"][2])
                    elif isinstance(pjob["executable"], str):
                        spec.executable = self._unescape_multiline(pjob["executable"])

                rspec = pjob.get("resource_spec", {})
                for k, v in rspec.items():
                    if k not in spec.resources:
                        spec.resources[k] = v

                attr = pjob.get("attributes", {})
                for k, v in attr.items():
                    if k not in spec.attributes:
                        spec.attributes[k] = v

            # Build options based on the possibly updated spec
            name = job.name
            if name:
                path = f"data.jobs[{i}].name"
                if is_editable(path):
                    options[path] = name
                
            if spec.executable:
                path = f"data.jobs[{i}].executable[2]"
                if is_editable(path):
                    options[path] = self._escape_multiline(spec.executable)

            container = spec.attributes.get("container", {})
            image_override = container.get("image")
            if image_override:
                path = f"data.jobs[{i}].image"
                if is_editable(path):
                    options[path] = image_override

            res = spec.resources
            if res.get("cpu_cores_per_process"):
                path = f"data.jobs[{i}].resource_spec.cpu_cores_per_process"
                if is_editable(path):
                    options[path] = str(res.get("cpu_cores_per_process"))
            if res.get("node_count"):
                path = f"data.jobs[{i}].resource_spec.node_count"
                if is_editable(path):
                    options[path] = str(res.get("node_count"))
            if res.get("processes_per_node"):
                path = f"data.jobs[{i}].resource_spec.processes_per_node"
                if is_editable(path):
                    options[path] = str(res.get("processes_per_node"))

            if spec.attributes.get("duration"):
                path = f"data.jobs[{i}].attributes.duration"
                if is_editable(path):
                    options[path] = str(spec.attributes.get("duration"))
            
        profile_networks = profile_intent.get("data", {}).get("networks", [])
        for net_idx, network in enumerate(profile_networks):
            connects = network.get("connects", [])
            for conn_idx, connector in enumerate(connects):
                orig_conn_name = connector.get("name")
                if orig_conn_name in name_map:
                    path = f"data.networks[{net_idx}].connects[{conn_idx}].name"
                    if is_editable(path):
                        options[path] = name_map[orig_conn_name]

        return profile, options, intent_uuid

    def plan(self, job: "Job") -> Dict:
        name = job.name or self.name
        self.logger.info(f"[{self.name}] Planning '{name}'")
        
        intent = getattr(job, 'intent', None) or job.job_spec.attributes.get("intent")
        if not intent:
            raise PlanError(["Missing 'intent' attribute for AMSC_IRO planning"])

        try:
            profile, _, _ = self._prepare_intent([job], intent)
        except Exception as e:
            raise PlanError([str(e)])

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

    def plan_intent(self, jobs: List["Job"], intent: str) -> Dict:
        self.logger.info(f"[{self.name}] Planning intent '{intent}' for {len(jobs)} job(s)")
        
        try:
            profile, _, _ = self._prepare_intent(jobs, intent)
        except Exception as e:
            raise PlanError([str(e)])

        return {
            "resource": {
                "profile_name": profile.get("name"),
                "profile_uuid": profile.get("uuid"),
                "editable": True,
                "status": "Ready for intent edits"
            },
            "status": "planned"
        }

    def create_intent(self, jobs: List["Job"], intent: str):
        self.logger.info(f"[{self.name}] Creating intent '{intent}' for {len(jobs)} job(s)")
        
        try:
            _, options, intent_uuid = self._prepare_intent(jobs, intent)
        except Exception as e:
             raise CreateError([str(e)])
             
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
            
            # Provide job ID back to the job object
            for job in jobs:
                if job.name:
                    job.id = si_uuid
                
        except Exception as e:
            # Try to clean up state if provisioning failed midway
            if getattr(workflow_api, 'si_uuid', None):
                workflow_api.instance_delete()
            job_names = ", ".join([j.name for j in jobs if j.name])
            raise CreateError([f"Failed to create and provision intent for jobs {job_names}: {e}"])

        self.logger.info(f"[{self.name}] Successfully created job intent with SI UUID {si_uuid}")

    def create(self, job: "Job"):
        name = job.name or self.name
        
        intent = getattr(job, 'intent', None) or job.job_spec.attributes.get("intent")
        if not intent:
            raise CreateError(["Missing 'intent' attribute for AMSC_IRO creation"])

        self.create_intent([job], intent)

    def destroy(self, job: "Job"):
        name = job.name or self.name
        si_uuid = job.id
        if not si_uuid:
            self.logger.warning(f"No tracked SI UUID for job '{name}', cannot destroy/cancel.")
            return
            
        workflow_api = WorkflowCombinedApi(req_wrapper=self._api_client)
        workflow_api.si_uuid = si_uuid
        try:
            status = workflow_api.instance_get_status()
            if 'FAILED' in status:
                workflow_api.instance_operate('cancel', force='true', sync='true')
            if 'READY' in status and 'CANCEL' not in status:
                workflow_api.instance_operate('cancel', sync='true')
            
            self.logger.info(f"[{self.name}] Successfully canceled instance {si_uuid}")
        except Exception as e:
            raise DestroyError([f"Failed to cancel instance {si_uuid}: {e}"])

    def status(self, job: "Job") -> JobStatus:
        name = job.name or self.name
        si_uuid = job.id
        if not si_uuid:
            return JobStatus(state=JobState.UNKNOWN, message="No known SI UUID in memory for AMSC_IRO")
            
        workflow_api = WorkflowCombinedApi(req_wrapper=self._api_client)
        workflow_api.si_uuid = si_uuid
        try:
            orch_status = workflow_api.instance_get_status()
            conf_status = workflow_api.instance_get_status(status='configstate')
            message = f"IRO Orch Status: {orch_status}, Conf Status: {conf_status}"

            # Basic mapping
            state = JobState.PENDING
            if 'READY' in orch_status:
                state = JobState.ACTIVE
            if 'CANCEL' in orch_status:
                state = JobState.CANCELED
            if 'FAILED' in orch_status:
                state = JobState.FAILED
            if 'FINISHED' in orch_status or 'UNSTABLE' in conf_status:
                state = JobState.COMPLETED
                
            provider_status = None
            try:
                from sense.client.facility_space_api import FacilitySpaceApi
                fs_api = FacilitySpaceApi(req_wrapper=self._api_client)
                fs_jobs = fs_api.facility_space_jobs_get(si_uuid)
                if isinstance(fs_jobs, list):
                    for fs_j in fs_jobs:
                        if fs_j.get("name") == job.name:
                            provider_status = fs_j
                            # Sync state if possible
                            fs_job_status = fs_j.get("jobStatus", {})
                            fs_state = fs_job_status.get("state")
                            if fs_state == "RUNNING":
                                state = JobState.ACTIVE
                            elif fs_state == "COMPLETED":
                                state = JobState.COMPLETED
                            elif fs_state == "FAILED":
                                state = JobState.FAILED
                            elif fs_state == "QUEUED":
                                state = JobState.QUEUED
                                
                            exit_code = fs_job_status.get("exit_code")
                            if exit_code is not None:
                                message = f"{message}, Exit Code: {exit_code}"
                                if fs_job_status.get("message"):
                                    message = f"{message}, Detail: {fs_job_status.get('message')}"
                            break
            except Exception as e:
                self.logger.debug(f"Could not fetch detailed FS job status: {e}")

            return JobStatus(
                state=state,
                job_id=si_uuid,
                message=message,
                provider_status=provider_status
            )
        except Exception as e:
            return JobStatus(state=JobState.UNKNOWN, message=str(e))
