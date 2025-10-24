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
to_be_created_count, to_be_deleted_count = manager.plan(session=session)
status_code = manager.apply(session=session)
manager.show(session=session)
manager.show_sessions()
status_code = manager.destroy(session=session)
manager.show(session=session)
manager.show_sessions()

'''


class AmSCROTManager:
    def __init__(self, *, config_dir: str, var_dict: Union[Dict[str, str], None] = None):
        self.config_dir = config_dir
        self.var_dict = var_dict or dict()
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

        if not self.provider_states:
            sutil.destroy_session(session)

        self._load_sessions()

    def _init_controller(self, *, session: str):
        self.provider_states = sutil.load_states(session)
        config = WorkflowConfig.parse(dir_path=self.config_dir, var_dict=self.var_dict)
        controller: Controller = Controller(config=config)

        from amscrot.controller.provider_factory import default_provider_factory
        controller.init(session=session,
                        provider_factory=default_provider_factory,
                        provider_states=self.provider_states)
        self.controller = controller

    def validate(self):
        config = WorkflowConfig.parse(dir_path=self.config_dir, var_dict=self.var_dict)
        return config

    def plan(self, *, session: str, to_json: bool = False, summary: bool = True):
        self._init_controller(session=session)
        self.controller.plan(provider_states=self.provider_states)
        resources = self.controller.resources
        cr, dl = sutil.dump_plan(resources=resources, to_json=to_json, summary=summary)

        logger.warning(f"Applying this plan would create {cr} resource(s) and destroy {dl} resource(s)")
        self._delete_session_if_empty(session=session)
        return cr, dl

    def apply(self, *, session: str):
        self._init_controller(session=session)
        self.controller.plan(provider_states=self.provider_states)
        self.controller.add(provider_states=self.provider_states)
        workflow_failed = False

        sutil.save_meta_data(dict(config_dir=self.config_dir), session)

        try:
            self.controller.apply(provider_states=self.provider_states)
        except KeyboardInterrupt as kie:
            logger.error(f"Keyboard Interrupt while creating resources ... {kie}")
            workflow_failed = True
        except ControllerException as ce:
            logger.error(f"Exceptions while creating resources ... {ce}")
            workflow_failed = True
        except Exception as e:
            logger.error(f"Unknown error while creating resources ... {e}")
            workflow_failed = True

        self.provider_states = self.controller.get_states()
        nodes, networks, services, pending, failed = utils.get_counters(states=self.provider_states)
        workflow_failed = workflow_failed or pending or failed
        self.provider_states = sutil.reconcile_states(self.provider_states, session)
        sutil.save_states(self.provider_states, session)
        logger.info(f"nodes={nodes}, networks={networks}, services={services}, pending={pending}, failed={failed}")
        return 1 if workflow_failed else 0

    def show(self, *, session: str, to_json: bool = False, summary: bool = True):
        self._load_sessions()
        session_names = [session_meta['session'] for session_meta in self.sessions]
        self.provider_states = sutil.load_states(session) if session in session_names else []
        sutil.dump_states(self.provider_states, to_json, summary)
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
        self._load_sessions()
        session_names = [session_meta['session'] for session_meta in self.sessions]

        if session not in session_names:
            return

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
