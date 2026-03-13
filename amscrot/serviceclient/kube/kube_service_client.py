from typing import Dict, Optional, TYPE_CHECKING, List, Any
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from ..serviceclient import ServiceClient
from ...util.constants import Constants
from ...model.discovery import DiscoveryResult, DiscoveredResource

if TYPE_CHECKING:
    from amscrot.client.job import JobSpec

from amscrot.client.job import JobStatus, JobState
from amscrot.serviceclient.serviceclient import PlanError, CreateError, DestroyError

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
                self.logger.warning(f"[{self.name}] Warning: Could not load kubernetes config.") 

        self.batch_v1 = client.BatchV1Api() if self._available else None
        self.core_v1 = client.CoreV1Api() if self._available else None
        self.scheduling_v1 = client.SchedulingV1Api() if self._available else None
        self.custom_objects = client.CustomObjectsApi() if self._available else None
        self.apiextensions_v1 = client.ApiextensionsV1Api() if self._available else None
        # self.job_name = None # Removed stateful job_name
        self.namespace = "default" # Could be configurable

    def discover(self, native: bool = True) -> DiscoveryResult:
        # Check connectivity if client is available
        if self._available:
            try:
                self.core_v1.list_namespace(limit=1, _request_timeout=2)
            except Exception as e:
                # Raise exception so tests can catch it and skip
                raise Exception(f"Kubernetes cluster unreachable during discover: {e}")
        if native:
            return self._discover_native()
        return self._discover_normalized()

    def _discover_native(self) -> DiscoveryResult:
        """Return raw Kubernetes resources (nodes, CRDs) as DiscoveredResource items."""
        if not self._available:
            return DiscoveryResult()

        items = []

        try:
            # 1. Discover Nodes
            self.logger.info(f"[{self.name}] Discovering nodes...")
            nodes = self.core_v1.list_node()
            for node in nodes.items:
                node_data = {
                    "name": node.metadata.name,
                    "addresses": [
                        {"type": addr.type, "address": addr.address}
                        for addr in node.status.addresses
                    ],
                    "allocatable": node.status.allocatable,
                    "capacity": node.status.capacity,
                    "node_info": node.status.node_info.to_dict(),
                    "labels": node.metadata.labels,
                    "annotations": node.metadata.annotations
                }
                items.append(DiscoveredResource(type="node", data=node_data))

            # 2. Discover CRDs
            if self.apiextensions_v1:
                self.logger.info(f"[{self.name}] Discovering CRDs...")
                crds = self.apiextensions_v1.list_custom_resource_definition()
                for crd in crds.items:
                    crd_data = {
                        "name": crd.metadata.name,
                        "group": crd.spec.group,
                        "versions": [v.name for v in crd.spec.versions],
                        "scope": crd.spec.scope
                    }
                    items.append(DiscoveredResource(type="crd", data=crd_data))

        except ApiException as e:
            self.logger.error(f"[{self.name}] Error during discovery: {e}")
        except Exception as e:
             self.logger.error(f"[{self.name}] Error during discovery: {e}")

        return DiscoveryResult(items=items)

    def _discover_normalized(self) -> DiscoveryResult:
        """Return a normalized Facility object aggregating all Kube nodes as Compute resources."""
        from ...model.metadata import Compute, Facility

        if not self._available:
            return DiscoveryResult()

        compute_list = []

        try:
            self.logger.info(f"[{self.name}] Discovering nodes for normalization...")
            nodes = self.core_v1.list_node()
            for node in nodes.items:
                allocatable = node.status.allocatable or {}
                node_info = node.status.node_info
                labels = node.metadata.labels or {}

                # Parse CPU (e.g. "4" or "4000m")
                cpu_raw = allocatable.get("cpu", "0")
                try:
                    if cpu_raw.endswith("m"):
                        cores = int(round(int(cpu_raw[:-1]) / 1000))
                    else:
                        cores = int(cpu_raw)
                except (ValueError, AttributeError):
                    cores = None

                # Parse GPU count
                gpu_raw = allocatable.get("nvidia.com/gpu")
                gpus = int(gpu_raw) if gpu_raw else None

                compute_list.append(Compute(
                    cores=cores,
                    memory=allocatable.get("memory"),
                    architecture=node_info.architecture if node_info else None,
                    gpus_per_node=gpus,
                    gpu_type=labels.get("nvidia.com/gpu.product"),
                    container_runtime=node_info.container_runtime_version if node_info else None,
                    node_selector=labels,
                ))

        except ApiException as e:
            self.logger.error(f"[{self.name}] Error during normalized discovery: {e}")
        except Exception as e:
            self.logger.error(f"[{self.name}] Error during normalized discovery: {e}")

        facility = Facility(name=self.name, compute=compute_list)
        item = DiscoveredResource(
            type="facility",
            data={"name": self.name},
            name=self.name,
            metadata=facility,
        )
        return DiscoveryResult(items=[item])

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
        
        # Build container command from executable + arguments
        command = [job_spec.executable] if job_spec.executable else ["echo"]
        if job_spec.arguments:
            command.extend(job_spec.arguments)
        container = client.V1Container(
            name=job_name,
            image=job_spec.image or "busybox",
            command=command,
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

        self.logger.info(f"[{self.name}] Validating resources for '{job_name}'...")
        
        # 1. Validate PriorityClass
        priority_class = job.spec.template.spec.priority_class_name
        if priority_class:
            try:
                self.scheduling_v1.read_priority_class(name=priority_class)
                self.logger.info(f"[{self.name}] PriorityClass '{priority_class}' found.")
            except ApiException as e:
                msg = f"PriorityClass '{priority_class}' validation failed: ({e.status}) {e.reason}"
                self.logger.warning(f"[{self.name}] Warning: {msg}")
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
                self.logger.info(f"[{self.name}] LocalQueue '{queue_name}' found in namespace '{job.metadata.namespace}'.")
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
        
        # Check connectivity if client is available
        if self._available:
            try:
                self.core_v1.list_namespace(limit=1, _request_timeout=2)
            except Exception as e:
                raise PlanError(errors=[f"Kubernetes cluster unreachable: {e}"])

        self.logger.info(f"[{self.name}] Planning Kube service for '{name}'...")
        job = self._create_job_object(job_spec, name)
        
        errors, warnings = self._validate_resources(job, name)
        
        if errors:
            raise PlanError(errors=errors, warnings=warnings)

        return {
            "status": JobState.PLANNED.value,
            "warnings": warnings,
            "job_object": job
        }

    def create(self, job_spec: "JobSpec", job_name: str = None):
        name = job_name or self.name
        self.logger.info(f"[{self.name}] Creating Kube service for '{name}'...")
        if not self._available:
            raise CreateError(errors=["Kubernetes client not available - check config"])

        job = self._create_job_object(job_spec, name)
        try: 
            # Use namespace from job object if set, otherwise default
            namespace = job.metadata.namespace or self.namespace
            api_response = self.batch_v1.create_namespaced_job(
                body=job,
                namespace=namespace
            )
            self._status = JobState.ACTIVE.value
            self.logger.info(f"[{self.name}] Job '{name}' submitted. Status='{api_response.status}'")
        except CreateError:
            raise
        except Exception as e:
            raise CreateError(errors=[f"Error submitting job '{name}': {e}"]) from e

    def destroy(self, job_name: str = None):
        name = job_name or self.name
        self.logger.info(f"[{self.name}] Destroying Kube service for '{name}'...")
        if not self._available:
            raise DestroyError(errors=["Kubernetes client not available - check config"])

        try:
            api_response = self.batch_v1.delete_namespaced_job(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions(
                    propagation_policy='Foreground',
                    grace_period_seconds=5
                )
            )
            self.logger.info(f"[{self.name}] Job '{name}' deleted. Status='{api_response.status}'")
            self._status = JobState.CANCELED.value
        except DestroyError:
            raise
        except Exception as e:
            raise DestroyError(errors=[f"Error deleting job '{name}': {e}"]) from e

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

    def status(self, job_name: str = None) -> JobStatus:
        name = job_name or self.name

        if not self._available:
            return JobStatus(state=self._status)

        try:
            api_response = self.batch_v1.read_namespaced_job_status(
                name=name,
                namespace=self.namespace
            )
            k8s_status = api_response.status

            # Map Kubernetes job status -> aligned JobState
            if k8s_status.succeeded:
                state = JobState.COMPLETED
            elif k8s_status.failed:
                state = JobState.FAILED
            elif k8s_status.active:
                state = JobState.ACTIVE
            else:
                state = JobState.UNKNOWN

            logs = self._get_job_logs(name)

            return JobStatus(
                state=state.value,
                provider_status={
                    "succeeded": k8s_status.succeeded,
                    "failed": k8s_status.failed,
                    "active": k8s_status.active,
                    "logs": logs,
                }
            )
        except ApiException as e:
            if e.status == 404:
                # Job not found -- either destroyed or never created
                state = JobState.CANCELED if self._status == JobState.CANCELED.value else JobState.UNKNOWN
                return JobStatus(state=state.value)
            self.logger.error(f"[{self.name}] Error reading status for '{name}': {e}")
            return JobStatus(state=JobState.UNKNOWN.value, message=str(e))
        except Exception as e:
            self.logger.error(f"[{self.name}] Error reading status for '{name}': {e}")
            return JobStatus(state=JobState.UNKNOWN.value, message=str(e))
