from typing import Dict, Optional, TYPE_CHECKING
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from ..serviceclient import ServiceClient
from ...util.constants import Constants

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec

class KubeServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type=Constants.ServiceType.KUBE, **kwargs)
        # Try to load kube config, fall back to in-cluster or None if failing (will be handled in methods)
        try:
            config.load_kube_config()
            self._available = True
        except Exception:
             # Fallback for in-cluster config or just mark as unavailable (or mock in tests)
            try:
                config.load_incluster_config()
                self._available = True
            except Exception:
                self._available = False
                print(f"[{self.name}] Warning: Could not load kubernetes config.") 

        self.batch_v1 = client.BatchV1Api() if self._available else None
        self.core_v1 = client.CoreV1Api() if self._available else None
        self.scheduling_v1 = client.SchedulingV1Api() if self._available else None
        self.custom_objects = client.CustomObjectsApi() if self._available else None
        # self.job_name = None # Removed stateful job_name
        self.namespace = "default" # Could be configurable

    def _create_job_object(self, job_spec: "JobSpec", job_name: str) -> client.V1Job:
        # Extract attributes
        attributes = job_spec.attributes or {}
        
        # Determine namespace (override if in attributes)
        # Use job-specific namespace if provided, else client default
        namespace = attributes.get("namespace", self.namespace)
        
        # Configure Pod resources
        resources = job_spec.resources or {}
        container_resources = None
        if resources:
            # Map simplified dict to V1ResourceRequirements
            # Assuming resources dict has 'requests' and 'limits' keys matching k8s
            container_resources = client.V1ResourceRequirements(
                requests=resources.get("requests"),
                limits=resources.get("limits")
            )
        
        container = client.V1Container(
            name=job_name,
            image=job_spec.image or "busybox",
            command=job_spec.executable or ["echo", "Hello World"],
            resources=container_resources 
        )
        
        # Labels
        labels = {"app": job_name}
        if "labels" in attributes:
            labels.update(attributes["labels"])
            
        # Create and configurate a spec section
        pod_spec_args = {
            "restart_policy": attributes.get("restartPolicy", "Never"),
            "containers": [container]
        }
        if "priorityClassName" in attributes:
            pod_spec_args["priority_class_name"] = attributes["priorityClassName"]
            
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=labels),
            spec=client.V1PodSpec(**pod_spec_args)
        )
        
        # Job Spec Args
        job_spec_args = {
             "template": template,
             "backoff_limit": 4
        }
        if "completions" in attributes:
            job_spec_args["completions"] = int(attributes["completions"])
        if "parallelism" in attributes:
            job_spec_args["parallelism"] = int(attributes["parallelism"])
        if "ttlSecondsAfterFinished" in attributes:
            job_spec_args["ttl_seconds_after_finished"] = int(attributes["ttlSecondsAfterFinished"])
        
        # Create the specification of deployment
        spec = client.V1JobSpec(**job_spec_args)
        
        # Instantiate the job object
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name, namespace=namespace, labels=labels), 
            spec=spec
        )
        return job

    def _validate_resources(self, job, job_name: str) -> tuple[list[str], list[str]]:
        errors = []
        warnings = []
        
        if not self._available:
             warnings.append("Kubernetes client unavailable, skipping cluster-side validation.")
             return errors, warnings

        print(f"[{self.name}] Validating resources for '{job_name}'...")
        
        # 1. Validate PriorityClass
        priority_class = job.spec.template.spec.priority_class_name
        if priority_class:
            try:
                self.scheduling_v1.read_priority_class(name=priority_class)
                print(f"[{self.name}] PriorityClass '{priority_class}' found.")
            except ApiException as e:
                msg = f"PriorityClass '{priority_class}' validation failed: ({e.status}) {e.reason}"
                print(f"[{self.name}] Warning: {msg}")
                if e.status == 404:
                    errors.append(f"PriorityClass '{priority_class}' not found.")
                else:
                    warnings.append(msg)
        
        # 2. Validate Kueue LocalQueue (if configured via labels)
        queue_name = job.metadata.labels.get("kueue.x-k8s.io/queue-name")
        if queue_name and self.custom_objects:
            try:
                self.custom_objects.get_namespaced_custom_object(
                    group="kueue.x-k8s.io",
                    version="v1beta1",
                    namespace=job.metadata.namespace,
                    plural="localqueues",
                    name=queue_name
                )
                print(f"[{self.name}] LocalQueue '{queue_name}' found in namespace '{job.metadata.namespace}'.")
            except ApiException as e:
                 msg = f"LocalQueue '{queue_name}' validation failed: ({e.status}) {e.reason}"
                 if e.status == 404:
                     # Warn that job might not be scheduled
                     warnings.append(f"LocalQueue '{queue_name}' not found in namespace '{job.metadata.namespace}'. Job may not be scheduled.")
                 else:
                     warnings.append(msg)
        
        return errors, warnings

    def plan(self, job_spec: "JobSpec", job_name: str = None) -> Dict:
        name = job_name or self.name 
        print(f"[{self.name}] Planning Kube service for '{name}'...")
        job = self._create_job_object(job_spec, name)
        
        errors, warnings = self._validate_resources(job, name)
        
        status = "PLANNED"
        if errors:
            status = "FAILED"
            print(f"[{self.name}] Plan FAILED for '{name}' with {len(errors)} errors.")
        else:
            print(f"[{self.name}] Kubernetes Job Validated: {job.metadata.name}")
            
        return {
            "status": status,
            "errors": errors,
            "warnings": warnings,
            "job_object": job 
        }

    def create(self, job_spec: "JobSpec", job_name: str = None):
        name = job_name or self.name
        print(f"[{self.name}] Creating Kube service for '{name}'...")
        if not self._available:
             print(f"[{self.name}] Kubernetes client unavailable. Skipping submission.")
             return

        job = self._create_job_object(job_spec, name)
        try: 
            # Use namespace from job object if set, otherwise default
            namespace = job.metadata.namespace or self.namespace
            api_response = self.batch_v1.create_namespaced_job(
                body=job,
                namespace=namespace
            )
            self._status = "SUBMITTED"
            print(f"[{self.name}] Job '{name}' submitted. Status='{api_response.status}'")
        except Exception as e:
            print(f"[{self.name}] Error submitting job '{name}': {e}")
            self._status = "ERROR"

    def destroy(self, job_name: str = None):
        name = job_name or self.name
        print(f"[{self.name}] Destroying Kube service for '{name}'...")
        if not self._available:
            return

        try:
            api_response = self.batch_v1.delete_namespaced_job(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    propagation_policy='Foreground',
                    grace_period_seconds=5
                )
            )
            print(f"[{self.name}] Job '{name}' deleted. Status='{api_response.status}'")
            self._status = "DESTROYED"
        except Exception as e:
             print(f"[{self.name}] Error deleting job '{name}': {e}")

    def _get_job_logs(self, job_name: str) -> str:
        if not self.core_v1:
            return ""
        
        try:
            # Find pods owned by the job (label selector job-name=<job_name>)
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"job-name={job_name}"
            )
            
            if not pods.items:
                return "No pods found"
                
            # Get logs from the first pod
            pod_name = pods.items[0].metadata.name
            logs = self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace
            )
            return logs
        except ApiException as e:
            if e.status == 400 and "ContainerCreating" in e.body:
                 return "Waiting for container to start..."
            return f"Error fetching logs: ({e.status}) {e.reason}"
        except Exception as e:
            return f"Error fetching logs: {str(e)}"

    def status(self, job_name: str = None) -> Dict:
        name = job_name or self.name
        
        if not self._available:
             return {"status": self._status}
        
        try:
            api_response = self.batch_v1.read_namespaced_job_status(
                name=name,
                namespace=self.namespace
            )
            # Map k8s status to amscrot status
            k8s_status = api_response.status
            status_str = "UNKNOWN"
            if k8s_status.succeeded:
                status_str = "DONE"
            elif k8s_status.failed:
                status_str = "ERROR"
            elif k8s_status.active:
                status_str = "RUNNING"
                
            logs = self._get_job_logs(name)
            
            return {
                "status": status_str,
                "succeeded": k8s_status.succeeded,
                "failed": k8s_status.failed,
                "active": k8s_status.active,
                "logs": logs
            }
        except ApiException as e:
            if e.status == 404:
                # Job not found implies it was destroyed or never created
                if self._status == "DESTROYED":
                    return {"status": "DESTROYED"}
                return {"status": "UNKNOWN", "error": "Job not found"}
            print(f"[{self.name}] Error reading status for '{name}': {e}")
            return {"status": "UNKNOWN", "error": str(e)}
        except Exception as e:
            print(f"[{self.name}] Error reading status for '{name}': {e}")
            return {"status": "UNKNOWN", "error": str(e)}
