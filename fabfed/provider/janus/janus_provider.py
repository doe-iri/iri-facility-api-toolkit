import os
import json
import logging

from fabfed.model import Service, Resource, Node
from fabfed.provider.api.provider import Provider
from fabfed.util.constants import Constants
from fabfed.util.utils import get_inventory_dir
from fabfed.util import state
from fabfed.provider.janus.util.ansible_helper import AnsibleRunnerHelper


JANUS_CTRL_PORT=5000

class JanusService(Service):
    def __init__(self, *, label, name: str, image, nodes, controller_url, controller_host,
                 controller_web, ssh_tunnel_cmd, provider, logger: logging.Logger):
        super().__init__(label=label, name=name)
        self.logger = logger
        self.image = image
        self.created = False
        self._nodes = nodes
        self._provider = provider

        if controller_url and controller_host:
            self.controller_url = controller_url
            self.controller_host = controller_host
            self._internal_controller = True
        else:
            self.controller_url = provider.config.get("url")
            self._internal_controller = False
        self.controller_web = controller_web
        self.controller_ssh_tunnel_cmd = ssh_tunnel_cmd

    def _do_ansible(self, delete=False):
        def _helper(host_file, tags, extra_vars = dict(), limit = ""):
            script_dir = os.path.dirname(__file__)
            helper = AnsibleRunnerHelper(host_file, self.logger)
            helper.set_extra_vars(extra_vars)
            helper.run_playbook(os.path.join(script_dir, "ansible/janus.yml"), tags=tags, limit=limit)

        friendly_name = self._provider.name
        host_file = get_inventory_dir(friendly_name)
        janus_vars = self._provider.config
        janus_vars['url'] = self.controller_url
        if delete:
            _helper(host_file, ["janus-del"], janus_vars)
        else:
            _helper(host_file, ["docker", "janus"], janus_vars)
            if self._internal_controller:
                _helper(host_file, ["controller"], janus_vars, limit=self.controller_host)
            _helper(host_file, ["janus-add"], janus_vars)
            self.created = True

    def create(self):
        self._do_ansible()
        self.logger.info(f" Service {self.name} created. service_nodes={self._nodes}")

    def delete(self):
        self._do_ansible(delete=True)
        self.logger.info(f" Service {self.name} deleted. service_nodes={self._nodes}")

from fabfed.util.utils import get_logger

logger: logging.Logger = get_logger()


class JanusProvider(Provider):
    def setup_environment(self):
        pass

    def __init__(self, *, type, label, name,  config: dict):
        super().__init__(type=type, label=label, name=name, logger=logger, config=config)
        credential_file = self.config.get(Constants.CREDENTIAL_FILE)

        if credential_file:
            from fabfed.util import utils

            profile = self.config.get(Constants.PROFILE)
            config = utils.load_yaml_from_file(credential_file)
            self.config = config[profile]

    def _validate_resource(self, resource: dict):
        assert resource.get(Constants.LABEL)
        assert resource.get(Constants.RES_TYPE) in Constants.RES_SUPPORTED_TYPES
        assert resource.get(Constants.RES_NAME_PREFIX)
        creation_details = resource[Constants.RES_CREATION_DETAILS]

        # count was set to zero 
        if not creation_details['in_config_file']:
            return

        assert resource.get(Constants.RES_COUNT, 1)
        self.logger.info(f"Validated:OK Resource={self.name} using {self.label}")

    def do_add_resource(self, *, resource: dict):
        """
        Called by add_resource(self, *, resource: dict) if resource has no external dependencies.
        The add_resource(self, *, resource: dict) puts resources in the pending dictionary when
        they have external dependencies.

        When the external dependencies are satisfied following a resource creation event, this method
        would be called automatically. See on_created(self, *, source, provider, resource: object)

        Note that external dependencies are respurce dependencies across different providers.
        @param resource: resource attributes
        """
        creation_details = resource[Constants.RES_CREATION_DETAILS]

        if not creation_details['in_config_file']:
            return

        self.logger.info(f"Adding resource={self.name} using {self.label}")
        self._validate_resource(resource)

        label = resource.get(Constants.LABEL)
        image = resource.get(Constants.RES_IMAGE, "dtnaas/tools")
        controller = resource.get("controller", None)
        controller_url = None
        controller_host = None
        controller_web = None
        ssh_tunnel_cmd = None
        if controller and len(controller) == 1:
            if isinstance(controller, list):
                controller = controller[0]
            if isinstance(controller, tuple):
                controller = controller[0]
            dplane_addr = controller.get_dataplane_address()
            if not dplane_addr:
                dplane_addr = "localhost"
            controller_url = f"https://{dplane_addr}:{JANUS_CTRL_PORT}"
            controller_host = controller.mgmt_ip
            controller_web = "http://localhost:8000"
            ssh_tunnel_cmd = f"{controller.sshcmd_str} -L 8000:localhost:8000"
        elif controller:
            self.logger.error(f"Invalid controller configuration for {label}")

        nodes = [rd for rd in resource[Constants.RESOLVED_EXTERNAL_DEPENDENCIES]
                 if rd.attr == 'node']
        service_name_prefix = resource.get(Constants.RES_NAME_PREFIX)
        service_nodes = [n for i in nodes for n in i.value]
        service_name = f"{self.name}-{service_name_prefix}"
        service = JanusService(label=label, name=service_name, image=image, nodes=service_nodes,
                               controller_url=controller_url,
                               controller_host=controller_host,
                               controller_web=controller_web,
                               ssh_tunnel_cmd=ssh_tunnel_cmd,
                               provider=self, logger=self.logger)
        self._services.append(service)
        self.resource_listener.on_added(source=self, provider=self, resource=service)

    def do_create_resource(self, *, resource: dict):
        """
        Called by add_resource(self, *, resource: dict) if resource has no external dependencies
        @param resource: resource attributes
        """
        creation_details = resource[Constants.RES_CREATION_DETAILS]

        if not creation_details['in_config_file']:
            return

        label = resource.get(Constants.LABEL)
        states = resource.get(Constants.SAVED_STATES)
        force = resource.get("force", True)
        created = False
        for s in states:
            created =  s.attributes.get('created', True)

        self.logger.info(f"Creating resource={self.name} using {self.label}")

        temp = [service for service in self.services if service.label == label]

        for service in temp:
            if not force and created:
                self.logger.info(f"Service {label} is already in created state, skipping create task")
                service.created = True
            else:
                service.create()
            self.resource_listener.on_created(source=self, provider=self, resource=service)

    def do_delete_resource(self, *, resource: dict):
        self.logger.info(f"Deleting resource={resource} using {self.label}")
        image = resource.get(Constants.RES_IMAGE, "dtnaas/tools")
        nodes = [rd for rd in resource[Constants.EXTERNAL_DEPENDENCY_STATES]]
        service_nodes = [n.attributes.get('name') for n in nodes]
        label = resource.get(Constants.LABEL)
        states = resource.get(Constants.SAVED_STATES)
        states = [s for s in states if s.label == label]

        if not states:
            return

        s = states[0]
        controller_url = s.attributes.get('controller_url')
        controller_host = s.attributes.get('controller_host')
        controller_web = s.attributes.get('controller_web')
        ssh_tunnel_cmd = s.attributes.get('controller_ssh_tunnel_cmd')

        service_name_prefix = resource.get(Constants.RES_NAME_PREFIX)
        service_name = f"{self.name}-{service_name_prefix}"
        service = JanusService(label=label, name=service_name, image=image, nodes=service_nodes,
                               controller_url=controller_url,
                               controller_host=controller_host,
                               controller_web=controller_web,
                               ssh_tunnel_cmd=ssh_tunnel_cmd,
                               provider=self, logger=self.logger)

        service.delete()
        self.resource_listener.on_deleted(source=self, provider=self, resource=service)
