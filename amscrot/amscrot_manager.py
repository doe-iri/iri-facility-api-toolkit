from amscrot.util import utils
from amscrot.util.config import WorkflowConfig
from typing import Union, Dict, List, Any
from amscrot.controller.controller import Controller
from amscrot.util import state as sutil
from amscrot.model.state import ProviderState
from amscrot.exceptions import ControllerException
from amscrot.util.constants import Constants

logger = utils.init_logger()

'''
from amscrot.amscrot_manager import AmSCROTManager

config_dir = "examples/fabric"
session="some_session"
manager = AmSCROTManager(config_dir=config_dir)
manager.validate()
manager.show_available_stitch_ports(from_provider='chi', to_provider="fabric")
manager.stitch_info(session=session)
plan_result = manager.plan(session=session)
status_code = manager.apply(session=session)
manager.show(session=session)
manager.show_sessions()
status_code = manager.destroy(session=session)
manager.show(session=session)
manager.show_sessions()

'''


class AmSCROTManager:
    def __init__(self, *, config_dir: str = '.', var_dict: Union[Dict[str, str], None] = None,
                 config_content: Union[str, Dict, None] = None, jobs: List[Any] = None):
        self.config_dir = config_dir
        self.config_content = config_content
        self.var_dict = var_dict or dict()
        self.jobs = jobs or []
        self.controller: Union[Controller, None] = None
        self.provider_states: List[ProviderState] = list()
        self.sessions: List[Any] = list()

    def _load_sessions(self):
        import os
        from pathlib import Path

        base_dir = os.path.join(str(Path.home()), '.amscrot', 'sessions')
        os.makedirs(base_dir, exist_ok=True)
        sessions = os.listdir(base_dir)
        self.sessions = [dict(session=s, config_dir=sutil.load_meta_data(s, 'config_dir')) for s in sessions]

    def _delete_session_if_empty(self, *, session):
        self.provider_states = sutil.load_states(session)
        jobs = self._get_jobs()

        if not self.provider_states and not jobs:
            sutil.destroy_session(session)

        self._load_sessions()

    def _init_controller(self, *, session: str):
        self.provider_states = sutil.load_states(session)
        dir_path = self.config_dir if not self.config_content else None
        config = WorkflowConfig.parse(dir_path=dir_path,
                                      content=self.config_content,
                                      var_dict=self.var_dict)
        controller: Controller = Controller(config=config)

        from amscrot.controller.provider_factory import default_provider_factory
        controller.init(session=session,
                        provider_factory=default_provider_factory,
                        provider_states=self.provider_states)
        self.controller = controller

    def validate(self):
        dir_path = self.config_dir if not self.config_content else None
        config = WorkflowConfig.parse(dir_path=dir_path,
                                      content=self.config_content,
                                      var_dict=self.var_dict)
        return config

    def _get_jobs(self) -> List[Any]:
        if self.jobs:
            return self.jobs

        import yaml
        content = self.config_content
        if not content:
            if self.config_dir:
                 pass
            return []

        if isinstance(content, str):
            try:
                content = yaml.safe_load(content)
            except yaml.YAMLError:
                return []

        if not isinstance(content, dict):
            return []

        jobs = []

        # content['job'] is a list of dicts like [{name1: config1}, {name2: config2}]
        if 'job' in content:
             for item in content['job']:
                 # item is {job_name: job_config}
                 jobs.extend(item.values())

        return jobs

    def plan(self, *, session: str, to_json: bool = False, summary: bool = True, skip_checks: bool = False):
        # Phase 1: Plan resources (nodes, networks, services)
        logger.info("Phase 1: Planning resources (nodes, networks, services)...")
        self._init_controller(session=session)
        self.controller.plan(provider_states=self.provider_states)
        resources = self.controller.resources

        import io, sys
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            cr, dl = sutil.dump_plan(resources=resources, to_json=to_json, summary=summary)
        finally:
            sys.stdout = old_stdout

        # Phase 2: Plan jobs
        job_summaries = []
        jobs = self._get_jobs()
        if jobs:
            logger.info("Phase 2: Planning jobs...")
            intent_groups = {}
            standalone_jobs = []

            for job in jobs:
                if hasattr(job, 'intent') and job.intent:
                    sc = getattr(job, 'service_client', None)
                    if not sc:
                        raise ValueError(f"Job {job.name} has intent but no service_client bound")
                    intent_groups.setdefault((job.intent, sc), []).append(job)
                else:
                    standalone_jobs.append(job)

            # Process intent groups
            for (intent_uuid, sc), group_jobs in intent_groups.items():
                plan_intent_func = getattr(sc, "plan_intent", None)
                if plan_intent_func:
                    result = plan_intent_func(group_jobs, intent_uuid)
                    for job in group_jobs:
                        job_summaries.append({
                            "name": job.name,
                            "type": str(job.type),
                            "service_client": getattr(sc, "name", "Unknown"),
                            "plan_status": result.get("status"),
                            "errors": result.get("errors"),
                            "warnings": result.get("warnings")
                        })
                else:
                    name = getattr(sc, "name", "Unknown")
                    raise AttributeError(f"Service client {name} does not support plan_intent but jobs specify an intent.")

            # Process standalone jobs
            for job in standalone_jobs:
                if hasattr(job, 'service_client') and job.service_client:
                    result = job.service_client.plan(job, skip_checks=skip_checks)
                    job_summaries.append({
                        "name": job.name,
                        "type": str(job.type),
                        "service_client": job.service_client.name,
                        "plan_status": result.get("status"),
                        "errors": result.get("errors"),
                        "warnings": result.get("warnings")
                    })
                else:
                    job_summaries.append({
                        "name": job.get("name") if isinstance(job, dict) else job.name,
                        "type": job.get("type") if isinstance(job, dict) else str(job.type),
                        "service_type": job.get("service_type") if isinstance(job, dict) else str(job.service_type),
                        "service_client": job.get("service_client") if isinstance(job, dict) else (job.service_client.name if job.service_client else None),
                        "action": "CREATE"
                    })
            logger.info(f"Jobs planned: {len(job_summaries)} job(s)")

        self._delete_session_if_empty(session=session)
        return {
            "resources": {
                "to_be_created": cr,
                "to_be_deleted": dl,
            },
            "jobs": job_summaries,
        }

    def apply(self, *, session: str):
        self._init_controller(session=session)

        # Phase 1: Plan and create resources (nodes, networks, services)
        logger.info("Phase 1: Planning and creating resources (nodes, networks, services)...")
        self.controller.plan(provider_states=self.provider_states)
        self.controller.add(provider_states=self.provider_states)

        sutil.save_meta_data(dict(config_dir=self.config_dir), session)

        try:
            self.controller.apply(provider_states=self.provider_states)
        finally:
            # Always persist state regardless of success or failure
            self.provider_states = self.controller.get_states()
            nodes, networks, services, pending, failed = utils.get_counters(states=self.provider_states)
            self.provider_states = sutil.reconcile_states(self.provider_states, session)
            sutil.save_states(self.provider_states, session)
            logger.info(f"Resources: nodes={nodes}, networks={networks}, services={services}, pending={pending}, failed={failed}")

        # Re-read counters from reconciled state
        nodes, networks, services, pending, failed = utils.get_counters(states=self.provider_states)
        if pending or failed:
            raise ControllerException(
                [Exception(f"Resource failures after apply: pending={pending}, failed={failed}")]
            )

        # Phase 2: Create jobs (only after resources are successfully created)
        job_summaries = []
        jobs = self._get_jobs()
        if jobs:
            logger.info("Phase 2: Creating jobs...")
            
            intent_groups = {}
            standalone_jobs = []

            for job in jobs:
                if hasattr(job, 'intent') and job.intent:
                    sc = getattr(job, 'service_client', None)
                    if not sc:
                        raise ValueError(f"Job {job.name} has intent but no service_client bound")
                    intent_groups.setdefault((job.intent, sc), []).append(job)
                else:
                    standalone_jobs.append(job)
            
            # Process intent groups
            for (intent_uuid, sc), group_jobs in intent_groups.items():
                create_intent_func = getattr(sc, "create_intent", None)
                if create_intent_func:
                    create_intent_func(group_jobs, intent_uuid)
                else:
                    name = getattr(sc, "name", "Unknown")
                    raise AttributeError(f"Service client {name} does not support create_intent but jobs specify an intent.")
                
                for job in group_jobs:
                    config_dict = list(job.to_config().values())[0]
                    config_dict["status"] = "SUBMITTED"
                    if not config_dict.get("resource_id"):
                        config_dict["resource_id"] = (job.job_spec.attributes or {}).get("resource_id")
                    job_summaries.append(config_dict)

            # Process standalone jobs
            for job in standalone_jobs:
                if hasattr(job, 'service_client') and job.service_client:
                    # Execute real create (client populates job.id implicitly)
                    job.service_client.create(job)
                    config_dict = list(job.to_config().values())[0]
                    config_dict["status"] = "SUBMITTED"
                    if not config_dict.get("resource_id"):
                        config_dict["resource_id"] = (job.job_spec.attributes or {}).get("resource_id")
                    job_summaries.append(config_dict)
                else:
                    # Fallback
                    job_summaries.append({
                        "name": job.get("name") if isinstance(job, dict) else job.name,
                        "service_client": job.get("service_client") if isinstance(job, dict) else (job.service_client.name if job.service_client else None),
                        "status": "SUBMITTED",
                        "id": f"mock-id-{job.get('name') if isinstance(job, dict) else job.name}"
                    })

            # Collect unique ServiceClients from the Job objects
            seen_sc_names = set()
            sc_list = []
            for job in jobs:
                sc = getattr(job, 'service_client', None)
                if sc and sc.name not in seen_sc_names:
                    sc_list.append(sc)
                    seen_sc_names.add(sc.name)
            sutil.save_jobs(sc_list, job_summaries, session)  # Persist job state

            logger.info(f"Jobs created: {len(job_summaries)} job(s) submitted")

        return {
            "resources": {
                "nodes": nodes, "networks": networks, "services": services,
                "pending": pending, "failed": failed,
            },
            "jobs": job_summaries,
        }


    def show(self, *, session: str, to_json: bool = False, summary: bool = True):
        self._load_sessions()
        session_names = [session_meta['session'] for session_meta in self.sessions]
        self.provider_states = sutil.load_states(session) if session in session_names else []
        sutil.dump_states(self.provider_states, to_json, summary)

        # Handle Jobs        
        jobs = self._get_jobs()
        if jobs:
             job_summaries = []
             for job in jobs:
                 if hasattr(job, 'service_client') and job.service_client:
                     status = job.service_client.status(job)
                     logs_raw = (status.provider_status or {}).get("logs", "") if status.provider_status else ""
                     job_summaries.append({
                        "name": job.name,
                        "status": status.state,
                        "logs": logs_raw[:200] + "..." if logs_raw else "",
                        "service_client": job.service_client.name,
                    })
                 else:
                     job_summaries.append({
                        "name": job.get("name"),
                        "status": "UNKNOWN", # No interaction with real backend yet
                        "service_client": job.get("service_client"),
                        "dependency": job.get("dependency")
                    })
             sutil.dump_objects(objects={"job_status": job_summaries}, to_json=to_json)

        # Fallback to loading jobs from disk if no jobs are attached dynamically
        elif session in session_names:
            _, loaded_jobs = sutil.load_jobs(session)
            if loaded_jobs:
                 # Check remote status for cached jobs if service_client can be resolved globally
                 job_summaries = []
                 for j_dict in loaded_jobs:
                     sc_name = j_dict.get('service_client')
                     # Note: we skip live checking here unless we build client-hydrating structure, just print last known state
                     job_summaries.append({
                         "name": j_dict.get('name'),
                         "id": j_dict.get('id'),
                         "status": j_dict.get('status', 'CACHED'),
                         "service_client": sc_name,
                         "logs": "(Cached state, run from client to retrieve live logs)"
                     })
                 sutil.dump_objects(objects={"job_status_cached": job_summaries}, to_json=to_json)

        self._delete_session_if_empty(session=session)

    def stitch_info(self, session: str, to_json: bool = False, summary: bool = True):
        self._init_controller(session=session)

        resources = self.controller.resources

        from collections import namedtuple

        if not summary:
            stitch_info_details = []

            StitchInfoDetails = namedtuple("StitchInfoDetails", "label provider_label stitch_info")

            for network in filter(lambda n: n.is_network, resources):
                details = StitchInfoDetails(label=network.label,
                                            provider_label=network.provider.label,
                                            stitch_info=network.attributes.get(Constants.RES_STITCH_INFO))
                stitch_info_details.append(details)

            stitch_info_details = dict(StitchNetworkDetails=stitch_info_details)
            sutil.dump_objects(objects=stitch_info_details, to_json=to_json)

        NetworkInfo = namedtuple("NetworkInfo", "label provider_label")
        StitchInfoSummary = namedtuple("StitchInfoSummary", "network_infos stitch_info")

        stitch_info_summaries = []
        stitch_info_map = {}
        stitch_info_network_info_map = {}

        for network in filter(lambda n: n.is_network and n.attributes.get(Constants.RES_STITCH_INFO), resources):
            stitch_info = network.attributes.get(Constants.RES_STITCH_INFO)

            if stitch_info:
                network_info = NetworkInfo(label=network.label, provider_label=network.provider.label)
                stitch_port_name = stitch_info.stitch_port['name']
                stitch_info_map[stitch_port_name] = stitch_info

                if stitch_port_name not in stitch_info_network_info_map:
                    stitch_info_network_info_map[stitch_port_name] = []

                stitch_info_network_info_map[stitch_port_name].append(network_info)

        for k, v in stitch_info_network_info_map.items():
            stitch_info_summary = StitchInfoSummary(network_infos=v, stitch_info=stitch_info_map[k])
            stitch_info_summaries.append(stitch_info_summary)

        stitch_info_summaries = dict(StitchInfoSummary=stitch_info_summaries)
        sutil.dump_objects(objects=stitch_info_summaries, to_json=to_json)

    def destroy(self, *, session: str):
        self._init_controller(session=session)
        self._load_sessions()
        session_names = [session_meta['session'] for session_meta in self.sessions]

        if session not in session_names:
            return

        # Phase 1: Destroy jobs first (before resources)
        jobs = self._get_jobs()
        if jobs:
            logger.info("Phase 1: Destroying jobs...")
            job_summaries = []
            for job in jobs:
                if hasattr(job, 'service_client') and job.service_client:
                    job.service_client.destroy(job)
                    job_summaries.append({
                        "name": job.name,
                        "service_client": job.service_client.name,
                        "action": "DELETE"
                    })
                else:
                    job_summaries.append({
                        "name": job.get("name"),
                        "service_client": job.get("service_client"),
                        "action": "DELETE"
                    })
            # sutil.dump_objects(objects={"job_destroy": job_summaries}, to_json=False)
            logger.info(f"Jobs destroyed: {len(job_summaries)} job(s) deleted")

        # Clean up persisted job state file
        sutil.delete_jobs(session)

        # Phase 2: Destroy resources (nodes, networks, services)
        logger.info("Phase 2: Destroying resources (nodes, networks, services)...")
        self.provider_states = sutil.load_states(session)

        if not self.provider_states:
            sutil.destroy_session(session)
            self.provider_states = []
            self._load_sessions()
            return

        self._init_controller(session=session)

        destroy_failed = False

        try:
            self.controller.destroy(provider_states=self.provider_states)
        except ControllerException as e:
            logger.error(f"Exceptions while deleting resources ...{e}")
            destroy_failed = True
        except KeyboardInterrupt as kie:
            logger.error(f"Keyboard Interrupt while deleting resources ... {kie}")
            return 1

        if not self.provider_states:
            logger.info(f"Destroying session {session} ...")
            sutil.destroy_session(session)
            self.controller = None
        else:
            sutil.save_states(self.provider_states, session)

        return 1 if destroy_failed else 0

    def show_sessions(self, *, to_json: bool = False):
        self.sessions = utils.dump_sessions(to_json)

    def show_available_stitch_ports(self, *, from_provider, to_provider):
        from amscrot.policy.policy_helper import load_policy

        policy = load_policy()

        from amscrot.policy.policy_helper import find_stitch_port_for_providers, peer_stitch_ports

        providers = [from_provider, to_provider]
        stitch_infos = find_stitch_port_for_providers(policy, providers)
        stitch_infos = peer_stitch_ports(stitch_infos)
        attrs = ["preference", "member-of", 'name']
        names = []

        for stitch_info in stitch_infos:
            names.append(stitch_info.stitch_port.get("name"))

            for attr in attrs:
                stitch_info.stitch_port.pop(attr, None)

            peer = stitch_info.stitch_port.get('peer', {})

            for attr in attrs:
                peer.pop(attr, None)

        import yaml
        from amscrot.util.constants import Constants

        stitch_port_configs = []

        for i, stitch_info in enumerate(stitch_infos):
            producer = stitch_info.producer
            consumer = stitch_info.consumer
            stitch_port = stitch_info.stitch_port
            c = {"config": [{Constants.NETWORK_STITCH_CONFIG: [{f"si_from_{names[i]}": {"producer": producer,
                                                                                        "consumer": consumer,
                                                                                        "stitch_port": stitch_port}}]}]}
            stitch_port_configs.append(c)

        rep = yaml.dump(stitch_port_configs, default_flow_style=False, sort_keys=False)
        print(rep)
