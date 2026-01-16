from typing import Dict, Optional, TYPE_CHECKING
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from ..serviceclient import ServiceClient

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec

class KubeServiceClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(type="kube", **kwargs)
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
        self.job_name = None
        self.namespace = "default" # Could be configurable

    def _create_job_object(self, job_spec: "JobSpec"):
        # Extract attributes
        attributes = job_spec.attributes or {}
        
        # Determine namespace (override if in attributes)
        namespace = attributes.get("namespace", self.namespace)
        self.namespace = namespace # Update instance namespace if provided? Or just use for this job? 
        # Better to keep it consistent for the create call:
        # But create() uses self.namespace. Let's update it or return it.
        # For now, let's assume if custom namespace is needed, client should be init with it or updated.
        # But attributes might specify it per job.
        
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
            name=self.name,
            image=job_spec.image or "busybox",
            command=job_spec.executable or ["echo", "Hello World"],
            resources=container_resources 
        )
        
        # Labels
        labels = {"app": self.name}
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
            metadata=client.V1ObjectMeta(name=self.name, namespace=namespace, labels=labels), 
            spec=spec
        )
        return job

    def _validate_resources(self, job) -> tuple[list[str], list[str]]:
        errors = []
        warnings = []
        
        if not self._available:
             # If client is not available, we might assume validation can't run fully 
             # OR we warn that validation is skipped.
             # Given 'plan' often runs locally without cluster, we might just warn?
             # But here we are using the client to check cluster state.
             warnings.append("Kubernetes client unavailable, skipping cluster-side validation.")
             return errors, warnings

        print(f"[{self.name}] Validating resources...")
        
        # 1. Validate PriorityClass
        priority_class = job.spec.template.spec.priority_class_name
        if priority_class:
            try:
                self.scheduling_v1.read_priority_class(name=priority_class)
                print(f"[{self.name}] PriorityClass '{priority_class}' found.")
            except ApiException as e:
                msg = f"PriorityClass '{priority_class}' validation failed: ({e.status}) {e.reason}"
                print(f"[{self.name}] Warning: {msg}")
                # Treat missing priority class as error or warning? 
                # K8s will block pod scheduling if missing, so it's critical.
                if e.status == 404:
                    errors.append(f"PriorityClass '{priority_class}' not found.")
                else:
                    warnings.append(msg)
        
        # 2. Validate Kueue LocalQueue (if configured via labels)
        queue_name = job.metadata.labels.get("kueue.x-k8s.io/queue-name")
        if queue_name and self.custom_objects:
            try:
                # Check for Kueue CRD/API availability first? Or just try getting the object.
                # Assuming group kueue.x-k8s.io and version v1beta1
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

    def plan(self, job_spec: "JobSpec") -> Dict:
        print(f"[{self.name}] Planning Kube service...")
        job = self._create_job_object(job_spec)
        
        errors, warnings = self._validate_resources(job)
        
        status = "PLANNED"
        if errors:
            status = "FAILED"
            print(f"[{self.name}] Plan FAILED with {len(errors)} errors.")
        else:
            print(f"[{self.name}] Kubernetes Job Validated: {job.metadata.name}")
            
        return {
            "status": status,
            "errors": errors,
            "warnings": warnings,
            "job_object": job # Optional: return the constructed object for inspection?
             # Probably not serializable easily if it's a complex object, but callers might want it.
             # For now keep it simple.
        }

    def create(self, job_spec: "JobSpec"):
        print(f"[{self.name}] Creating Kube service...")
        if not self._available:
             print(f"[{self.name}] Kubernetes client unavailable. Skipping submission.")
             return

        job = self._create_job_object(job_spec)
        try: 
            # Use namespace from job object if set, otherwise default
            namespace = job.metadata.namespace or self.namespace
            api_response = self.batch_v1.create_namespaced_job(
                body=job,
                namespace=namespace
            )
            self.job_name = api_response.metadata.name
            self._status = "SUBMITTED"
            print(f"[{self.name}] Job submitted. Status='{api_response.status}'")
        except Exception as e:
            print(f"[{self.name}] Error submitting job: {e}")
            self._status = "ERROR"

    def destroy(self):
        print(f"[{self.name}] Destroying Kube service...")
        if not self._available or not self.job_name:
            return

        try:
            api_response = self.batch_v1.delete_namespaced_job(
                name=self.job_name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    propagation_policy='Foreground',
                    grace_period_seconds=5
                )
            )
            print(f"[{self.name}] Job deleted. Status='{api_response.status}'")
            self._status = "DESTROYED"
        except Exception as e:
             print(f"[{self.name}] Error deleting job: {e}")

    def _get_job_logs(self) -> str:
        if not self.core_v1 or not self.job_name:
            return ""
        
        try:
            # Find pods owned by the job (label selector job-name=<job_name>)
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"job-name={self.job_name}"
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

    def status(self) -> Dict:
        if not self._available or not self.job_name:
             return {"status": self._status}
        
        try:
            api_response = self.batch_v1.read_namespaced_job_status(
                name=self.job_name,
                namespace=self.namespace
            )
            # Map k8s status to amscrot status
            k8s_status = api_response.status
            if k8s_status.succeeded:
                self._status = "DONE"
            elif k8s_status.failed:
                self._status = "ERROR"
            elif k8s_status.active:
                self._status = "RUNNING"
                
            logs = self._get_job_logs()
            
            return {
                "status": self._status,
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
            print(f"[{self.name}] Error reading status: {e}")
            return {"status": "UNKNOWN", "error": str(e)}
        except Exception as e:
            print(f"[{self.name}] Error reading status: {e}")
            return {"status": "UNKNOWN", "error": str(e)}
