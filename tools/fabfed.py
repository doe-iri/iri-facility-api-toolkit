import sys

from fabfed.controller.controller import Controller
from fabfed.controller.provider_factory import default_provider_factory
from fabfed.exceptions import ControllerException
from fabfed.util import utils
from fabfed.util import state as sutil
from fabfed.util.config import WorkflowConfig
from fabfed.util.stats import FabfedStats, Duration
from fabfed.util.constants import Constants


def delete_session_if_empty(*, session):
    provider_states = sutil.load_states(session)

    if not provider_states:
        sutil.destroy_session(session)


def manage_workflow(args):
    logger = utils.init_logger()
    config_dir = utils.absolute_path(args.config_dir)
    sessions = sutil.load_sessions()
    config_dir_from_meta = sutil.load_meta_data(args.session, 'config_dir') if args.session in sessions else None

    if config_dir_from_meta and config_dir_from_meta != config_dir:
        logger.error(f"attempt to use fabfed session {args.session} from the wrong config dir {config_dir} ...")
        logger.warning(f"ATTN: The CORRECT config dir for session {args.session} is {config_dir_from_meta}!!!!!!!")
        sys.exit(1)

    var_dict = utils.load_vars(args.var_file) if args.var_file else {}

    from fabfed.policy.policy_helper import load_policy

    policy = load_policy(policy_file=args.policy_file, load_details=False) if args.policy_file else {}

    if args.validate:
        try:
            WorkflowConfig.parse(dir_path=config_dir, var_dict=var_dict)
            logger.info("config looks ok")
        except Exception as e:
            logger.error(f"Validation failed .... {type(e)} {e}")
            logger.error(e, exc_info=True)
            sys.exit(1)

    if args.apply:
        sutil.save_meta_data(dict(config_dir=config_dir), args.session)
        sutil.delete_stats(args.session)
        import time

        start = time.time()
        config = WorkflowConfig.parse(dir_path=config_dir, var_dict=var_dict)
        parse_and_validate_config_duration = time.time() - start
        controller_duration_start = time.time()

        try:
            controller = Controller(config=config,
                                    policy=policy,
                                    use_local_policy=not args.use_remote_policy)
        except Exception as e:
            logger.error(f"Exceptions while initializing controller .... {e}", exc_info=True)
            sys.exit(1)

        states = sutil.load_states(args.session)
        # have_created_resources = next(filter(lambda s: s.number_of_created_resources() > 0, states), None)

        try:
            controller.init(session=args.session, provider_factory=default_provider_factory, provider_states=states)
        except Exception as e:
            logger.error(f"Exceptions while initializing providers  .... {e}", exc_info=True)
            sys.exit(1)

        try:
            controller.plan(provider_states=states)
        except Exception as e:
            logger.error(f"Exception while planning ... {e}")
            sys.exit(1)
        except KeyboardInterrupt as kie:
            logger.error(f"Keyboard Interrupt while planning ... {kie}")
            sys.exit(1)

        try:
            controller.add(provider_states=states)
        except Exception as e:
            logger.error(f"Exception while adding ... {e}")
            sys.exit(1)
        except KeyboardInterrupt as kie:
            logger.error(f"Keyboard Interrupt while adding  resources ... {kie}")
            sys.exit(1)

        workflow_failed = False
        workflow_failed_message = ''

        try:
            controller.apply(provider_states=states)
        except KeyboardInterrupt as kie:
            logger.error(f"Keyboard Interrupt while creating resources ... {kie}")
            workflow_failed_message = f'{kie}'
            workflow_failed = True
        except ControllerException as ce:
            logger.error(f"Exceptions while creating resources ... {ce}")
            workflow_failed_message = f'{ce}'
            workflow_failed = True
        except Exception as e:
            logger.error(f"Unknown error while creating resources ... {e}")
            workflow_failed_message = f'{e}'
            workflow_failed = True

        controller_duration = time.time() - controller_duration_start
        providers_duration = 0

        for stats in controller.get_stats():
            logger.debug(f"STATS:provider={stats.provider}, provider_duration={stats.provider_duration}")
            controller_duration -= stats.provider_duration.duration
            providers_duration += stats.provider_duration.duration

        states = controller.get_states()
        nodes, networks, services, pending, failed = utils.get_counters(states=states)
        workflow_failed = workflow_failed or pending or failed

        if workflow_failed and Constants.RECONCILE_STATES:
            states = sutil.reconcile_states(states, args.session)

        sutil.save_states(states, args.session)
        provider_stats = controller.get_stats()
        workflow_duration = time.time() - start
        workflow_duration = Duration(duration=workflow_duration,
                                     comment="total time spent in creating workflow")
        controller_duration = Duration(duration=controller_duration,
                                       comment="time spent in controller. It does not include time spent in providers")
        providers_duration = Duration(duration=providers_duration,
                                      comment="time spent in all providers")
        validate_config_duration = Duration(duration=parse_and_validate_config_duration,
                                            comment="time spent in parsing and validating config")

        fabfed_stats = FabfedStats(action="apply",
                                   has_failures=workflow_failed,
                                   workflow_duration=workflow_duration,
                                   workflow_config=validate_config_duration,
                                   controller=controller_duration,
                                   providers=providers_duration,
                                   provider_stats=provider_stats)
        logger.info(f"STATS:duration_in_seconds={workflow_duration}")
        logger.info(f"nodes={nodes}, networks={networks}, services={services}, pending={pending}, failed={failed}")
        counts = dict(nodes=nodes, networks=networks, services=services, pending=pending, failed=failed)
        display_info = dict(workflow_status="FAILED" if workflow_failed else "OK",
                            error_message=workflow_failed_message,
                            resources=counts)
        sutil.dump_objects(objects=display_info, to_json=args.json)
        sutil.save_stats(dict(comment="all durations are in seconds", stats=fabfed_stats), args.session)
        sys.exit(1 if workflow_failed else 0)

    if args.init:
        config = WorkflowConfig.parse(dir_path=config_dir, var_dict=var_dict)
        controller = Controller(config=config,
                                policy=policy,
                                use_local_policy=not args.use_remote_policy)
        states = sutil.load_states(args.session)
        controller.init(session=args.session, provider_factory=default_provider_factory, provider_states=states)
        sutil.dump_resources(resources=controller.resources, to_json=args.json, summary=args.summary)
        delete_session_if_empty(session=args.session)
        return

    if args.stitch_info:
        config = WorkflowConfig.parse(dir_path=config_dir, var_dict=var_dict)
        controller = Controller(config=config,
                                policy=policy,
                                use_local_policy=not args.use_remote_policy)
        states = sutil.load_states(args.session)
        controller.init(session=args.session, provider_factory=default_provider_factory, provider_states=states)
        resources = controller.resources

        from collections import namedtuple

        if not args.summary:
            stitch_info_details = []

            StitchInfoDetails = namedtuple("StitchInfoDetails", "label provider_label stitch_info")

            for network in filter(lambda n: n.is_network, resources):
                details = StitchInfoDetails(label=network.label,
                                            provider_label=network.provider.label,
                                            stitch_info=network.attributes.get(Constants.RES_STITCH_INFO))
                stitch_info_details.append(details)

            stitch_info_details = dict(StitchNetworkDetails=stitch_info_details)
            sutil.dump_objects(objects=stitch_info_details, to_json=args.json)

        NetworkInfo = namedtuple("NetworkInfo", "label provider_label")
        StitchInfoSummary = namedtuple("StitchInfoSummary", "network_infos stitch_info")

        stitch_info_summaries = []
        stitch_info_map = {}
        stitch_info_network_info_map = {}

        for network in filter(lambda n: n.is_network and n.attributes.get(Constants.RES_STITCH_INFO), resources):
            stitch_infos = network.attributes.get(Constants.RES_STITCH_INFO)

            for stitch_info in stitch_infos:
                network_info = NetworkInfo(label=network.label, provider_label=network.provider.label)
                if 'name' in stitch_info.stitch_port:
                    stitch_port_name = stitch_info.stitch_port['name']
                else:
                    stitch_port_name = stitch_info.stitch_port['peer']['name']

                stitch_info_map[stitch_port_name] = stitch_info

                if stitch_port_name not in stitch_info_network_info_map:
                    stitch_info_network_info_map[stitch_port_name] = []

                stitch_info_network_info_map[stitch_port_name].append(network_info)

        for k, v in stitch_info_network_info_map.items():
            stitch_info_summary = StitchInfoSummary(network_infos=v, stitch_info=stitch_info_map[k])
            stitch_info_summaries.append(stitch_info_summary)

        stitch_info_summaries = dict(StitchInfoSummary=stitch_info_summaries)
        sutil.dump_objects(objects=stitch_info_summaries, to_json=args.json)
        delete_session_if_empty(session=args.session)
        return

    if args.plan:
        config = WorkflowConfig.parse(dir_path=config_dir, var_dict=var_dict)
        controller = Controller(config=config,
                                policy=policy,
                                use_local_policy=not args.use_remote_policy)
        states = sutil.load_states(args.session)
        controller.init(session=args.session, provider_factory=default_provider_factory, provider_states=states)
        controller.plan(provider_states=states)
        cr, dl = sutil.dump_plan(resources=controller.resources, to_json=args.json, summary=args.summary)

        logger.warning(f"Applying this plan would create {cr} resource(s) and destroy {dl} resource(s)")
        delete_session_if_empty(session=args.session)
        return

    if args.show:
        states = sutil.load_states(args.session) if args.session in sessions else []
        sutil.dump_states(states, args.json, args.summary)
        return

    if args.stats:
        stats = sutil.load_stats(args.session)
        sutil.dump_stats(stats, args.json)
        delete_session_if_empty(session=args.session)
        return

    if args.destroy:
        sutil.delete_stats(args.session)

        if args.session not in sessions:
            return

        states = sutil.load_states(args.session)

        if not states:
            sutil.destroy_session(args.session)
            return

        import time

        start = time.time()
        config = WorkflowConfig.parse(dir_path=config_dir, var_dict=var_dict)
        parse_and_validate_config_duration = time.time() - start
        controller_duration_start = time.time()

        try:
            controller = Controller(config=config,
                                    policy=policy,
                                    use_local_policy=not args.use_remote_policy)
            controller.init(session=args.session, provider_factory=default_provider_factory, provider_states=states)
        except Exception as e:
            logger.error(f"Exceptions while initializing controller .... {e}")
            sys.exit(1)

        destroy_failed = False

        try:
            controller.destroy(provider_states=states)
        except ControllerException as e:
            logger.error(f"Exceptions while deleting resources ...{e}")
            destroy_failed = True
        except KeyboardInterrupt as kie:
            logger.error(f"Keyboard Interrupt while deleting resources ... {kie}")
            sys.exit(1)

        controller_duration = time.time() - controller_duration_start
        providers_duration = 0

        for stats in controller.get_stats():
            logger.info(f"STATS:provider={stats.provider}, provider_duration={stats.provider_duration}")
            controller_duration -= stats.provider_duration.duration
            providers_duration += stats.provider_duration.duration

        if not states:
            logger.info(f"Destroying session {args.session} ...")
            sutil.destroy_session(args.session)
        else:
            sutil.save_states(states, args.session)

        end = time.time()
        workflow_duration = end - start
        workflow_duration = Duration(duration=workflow_duration,
                                     comment="total time spent in destroying workflow")
        controller_duration = Duration(duration=controller_duration,
                                       comment="time spent in controller. It does not include time spent in providers")
        providers_duration = Duration(duration=providers_duration, comment="time spent in all providers")
        validate_config_duration = Duration(duration=parse_and_validate_config_duration,
                                            comment="time spent in parsing and validating config")

        provider_stats = controller.get_stats()
        fabfed_stats = FabfedStats(action="destroy",
                                   has_failures=len(states) > 0,
                                   workflow_duration=workflow_duration,
                                   workflow_config=validate_config_duration,
                                   controller=controller_duration,
                                   providers=providers_duration,
                                   provider_stats=provider_stats)
        logger.info(f"STATS:duration_in_seconds={workflow_duration}")
        sutil.save_stats(dict(comment="all durations are in seconds", stats=fabfed_stats), args.session)
        sys.exit(1 if destroy_failed else 0)


def manage_sessions(args):
    if args.show:
        utils.dump_sessions(args.json)
        return


def display_stitch_info(args):
    logger = utils.init_logger()

    if not args.use_remote_policy or args.policy_file:
        from fabfed.policy.policy_helper import load_policy

        policy = load_policy(policy_file=args.policy_file, load_details=args.policy_file is not None)
        logger.info(f"loaded local stitching policy.")
    else:
        from fabfed.policy.policy_helper import load_remote_policy

        attrs = {'credential_file': args.credential_file, 'profile': args.profile}
        default_provider_factory.init_provider(type='fabric',
                                               label='no_label',
                                               name='no_name',
                                               attributes=attrs,
                                               logger=logger)
        policy = load_remote_policy()
        logger.info(f"loaded remote stitching policy.")

    providers = args.providers.split(",")

    if len(providers) != 2:
        logger.error("please input two providers")
        sys.exit(1)

    for provider in providers:
        if provider not in policy:
            logger.error(f"Did not find provider {provider} in policy file")
            sys.exit(1)

    from fabfed.policy.policy_helper import find_stitch_port_for_providers, peer_stitch_ports

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
    from fabfed.util.constants import Constants

    for i, stitch_info in enumerate(stitch_infos):
        producer = stitch_info.producer
        consumer = stitch_info.consumer
        stitch_port = stitch_info.stitch_port
        c = {"config": [{Constants.NETWORK_STITCH_CONFIG: [{f"si_from_{names[i]}": {"producer": producer,
                                                                                    "consumer": consumer,
                                                                                    "stitch_port": stitch_port}}]}]}
        rep = yaml.dump(c, default_flow_style=False, sort_keys=False)
        rep = rep.replace('\n', '\n  ')
        print(rep)


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = utils.build_parser(manage_workflow=manage_workflow,
                                manage_sessions=manage_sessions,
                                display_stitch_info=display_stitch_info)
    args = parser.parse_args(argv)

    if len(args.__dict__) == 0:
        parser.print_usage()
        sys.exit(1)

    args.dispatch_func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
