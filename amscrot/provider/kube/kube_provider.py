from amscrot.util.utils import get_logger
import os
import logging
import yaml

from amscrot.model import Service
from amscrot.provider.api.provider import Provider
from amscrot.util.constants import Constants
from amscrot.util.utils import get_inventory_dir, get_base_dir
from amscrot.provider.janus.util.ansible_helper import AnsibleRunnerHelper
from amscrot.provider.kube.kube_constants import KUBE_VERSION


logger: logging.Logger = get_logger()


class K3sService(Service):
    """K3s Kubernetes cluster service."""

    def __init__(self, *, label, name: str, controller_node, agent_nodes,
                 kube_version: str, flannel_iface: str, flannel_ipv6_masq: bool,
                 provider, logger: logging.Logger):
        super().__init__(label=label, name=name)
        self.logger = logger
        self.created = False

        self.kube_version = kube_version
        self.flannel_iface = flannel_iface
        self.flannel_ipv6_masq = flannel_ipv6_masq
        self.controller_host = None

        self._controller_node = controller_node
        self._agent_nodes = agent_nodes
        self._provider = provider

        # Get controller (server) dataplane IPv6
        self.controller_host = self._controller_node.get_dataplane_address(af=Constants.IPv6)
        if not self.controller_host:
            raise Exception(
                f"Controller node {self._controller_node.name} has no IPv6 dataplane address"
            )

    def _generate_inventory(self) -> str:
        """
        Generate K3s inventory in YAML format with per-node SSH configuration.

        Returns:
            YAML string with k3s_cluster structure
        """

        # Build server host with SSH config
        server_host = {
            f"{self.controller_host}": {
                'ansible_user': self._controller_node.user,
                'ansible_ssh_private_key_file': self._controller_node.keyfile,
                'ansible_ssh_common_args': '-o StrictHostKeyChecking=no'
            }
        }

        # Validate controller SSH details
        if not self._controller_node.user or not self._controller_node.keyfile:
            raise Exception(
                f"Controller node {self._controller_node.name} missing SSH credentials"
            )

        # Build agent hosts with per-node SSH config
        agent_hosts = {}
        for agent in self._agent_nodes:
            agent_ipv6 = agent.get_dataplane_address(af=Constants.IPv6)
            if not agent_ipv6:
                raise Exception(f"Agent node {agent.name} has no IPv6 dataplane address")

            if not agent.user or not agent.keyfile:
                raise Exception(f"Agent node {agent.name} missing SSH credentials")

            agent_hosts[f"{agent_ipv6}"] = {
                'ansible_user': agent.user,
                'ansible_ssh_private_key_file': agent.keyfile,
                'ansible_ssh_common_args': '-o StrictHostKeyChecking=no'
            }

        # Build group-level vars (K3s-specific only)
        group_vars = {
            'k3s_version': self.kube_version,
            'api_endpoint': f"[{self.controller_host}]",
            'extra_server_args': "--node-ip {{ inventory_hostname }}",
            'extra_agent_args': "--disable-apiserver-lb --node-ip {{ inventory_hostname }}"
        }

        if self.flannel_iface:
            group_vars['extra_server_args'] += f" --flannel-iface {self.flannel_iface}"
            group_vars['extra_agent_args'] += f" --flannel-iface {self.flannel_iface}"

        if self.flannel_ipv6_masq:
            group_vars['extra_server_args'] += " --flannel-ipv6-masq"

        # Build inventory structure
        inventory = {
            'k3s_cluster': {
                'children': {
                    'server': {
                        'hosts': server_host
                    },
                    'agent': {
                        'hosts': agent_hosts
                    }
                },
                'vars': group_vars
            }
        }

        # Convert to YAML string
        return yaml.dump(inventory, default_flow_style=False, sort_keys=False, width=256)

    def _write_inventory(self, friendly_name):
        """Write inventory to file in the inventory directory."""
        inventory_dir = get_inventory_dir(friendly_name)
        inventory_file = os.path.join(inventory_dir, f"{self.name}_inventory.yml")

        inventory_content = self._generate_inventory()

        with open(inventory_file, 'w') as f:
            f.write(inventory_content)

        self.logger.info(f"K3s inventory written to: {inventory_file}")
        return inventory_file

    def _do_ansible(self, delete=False):
        """Execute ansible playbook for K3s installation/removal."""
        friendly_name = self._provider.name

        # Generate and write inventory
        inventory_file = self._write_inventory(friendly_name)

        # Run ansible playbook
        script_dir = os.path.dirname(__file__)
        playbook = os.path.join(script_dir, "ansible/k3s.yml")

        helper = AnsibleRunnerHelper(inventory_file, self.logger)

        if delete:
            # For deletion, we might need specific tags or playbook
            # k3s-ansible may have a reset/uninstall playbook
            helper.run_playbook(playbook, tags=["reset"])
        else:
            # Install k3s cluster
            helper.run_playbook(playbook)
            friendly_name = self._provider.name
            session_dir = get_base_dir(friendly_name)
            helper.set_extra_vars({'kconfig_dest_path': session_dir})
            helper.run_playbook(playbook, tags=["fetch"], limit=self.controller_host)

    def create(self):
        """Create K3s cluster."""
        self._do_ansible()
        self.created = True
        node_names = [self._controller_node.name] + [n.name for n in self._agent_nodes]
        self.logger.info(f"Service {self.name} created. service_nodes={node_names}")

    def delete(self):
        """Delete K3s cluster."""
        self._do_ansible(delete=True)
        node_names = [self._controller_node.name] + [n.name for n in self._agent_nodes]
        self.logger.info(f"Service {self.name} deleted. service_nodes={node_names}")


class KubeProvider(Provider):
    """K3s Kubernetes provider."""

    def setup_environment(self):
        pass

    def __init__(self, *, type, label, name, config: dict):
        super().__init__(type=type, label=label, name=name, logger=logger, config=config)
        credential_file = self.config.get(Constants.CREDENTIAL_FILE)

        if credential_file:
            from amscrot.util import utils
            profile = self.config.get(Constants.PROFILE)
            config = utils.load_yaml_from_file(credential_file)
            self.config = config[profile]

    def _validate_resource(self, resource: dict):
        """Validate resource configuration."""
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
        Add K3s service resource.

        Extracts controller and agent nodes from resolved dependencies,
        parses k3s configuration, and creates K3sService instance.
        """
        creation_details = resource[Constants.RES_CREATION_DETAILS]

        if not creation_details['in_config_file']:
            return

        self.logger.info(f"Adding resource={self.name} using {self.label}")
        self._validate_resource(resource)

        label = resource.get(Constants.LABEL)

        # Extract controller node (single server)
        controller = resource.get("controller", None)
        if controller and len(controller) == 1:
            if isinstance(controller, list):
                controller = controller[0]
            if isinstance(controller, tuple):
                controller = controller[0]
        elif controller:
            self.logger.error(f"Invalid controller configuration for {label} - must be single node")
            raise Exception(f"K3s requires exactly one controller node")
        else:
            self.logger.error(f"No controller specified for {label}")
            raise Exception(f"K3s requires a controller node")

        # Extract agent nodes
        nodes = [rd for rd in resource[Constants.RESOLVED_EXTERNAL_DEPENDENCIES]
                 if rd.attr == 'node']
        agent_nodes = [n for i in nodes for n in i.value if n != controller]

        if not agent_nodes:
            self.logger.warning(f"No agent nodes specified for {label} - creating single-node cluster")
            agent_nodes = []

        # Get Kube configuration
        kube_version = resource.get('k3s_version', KUBE_VERSION)
        flannel_iface = resource.get('flannel_iface', None)
        flannel_ipv6_masq = resource.get('flannel_ipv6_masq', False)

        # Create service
        service_name_prefix = resource.get(Constants.RES_NAME_PREFIX)
        service_name = f"{self.name}-{service_name_prefix}"

        service = K3sService(
            label=label,
            name=service_name,
            controller_node=controller,
            agent_nodes=agent_nodes,
            kube_version=kube_version,
            flannel_iface=flannel_iface,
            flannel_ipv6_masq=flannel_ipv6_masq,
            provider=self,
            logger=self.logger
        )

        self._services.append(service)
        self.resource_listener.on_added(source=self, provider=self, resource=service)

    def do_create_resource(self, *, resource: dict):
        creation_details = resource[Constants.RES_CREATION_DETAILS]

        if not creation_details['in_config_file']:
            return

        label = resource.get(Constants.LABEL)
        states = resource.get(Constants.SAVED_STATES)
        force = resource.get("force", False)
        delete = resource.get("delete", False)
        created = False
        for s in states:
            created = s.attributes.get('created', True)

        self.logger.info(f"Creating resource={self.name} using {self.label}")

        temp = [service for service in self.services if service.label == label]

        for service in temp:
            if not force and not delete and created:
                self.logger.info(
                    f"Service {label} is already in created state, skipping create task"
                )
                service.created = True
            elif delete:
                service.delete()
            else:
                service.create()
            self.resource_listener.on_created(source=self, provider=self, resource=service)

    def do_delete_resource(self, *, resource: dict):
        """Delete K3s cluster resources."""
        self.logger.info(f"Deleting resource={resource} using {self.label}")

        label = resource.get(Constants.LABEL)
        states = resource.get(Constants.SAVED_STATES)
        states = [s for s in states if s.label == label]

        if not states:
            return

        s = states[0]

        # Reconstruct service from saved state
        controller_node = None
        agent_nodes = []

        # Extract nodes from external dependency states
        if resource.get(Constants.EXTERNAL_DEPENDENCY_STATES):
            nodes = [rd for rd in resource.get(Constants.EXTERNAL_DEPENDENCY_STATES)]
            # First node should be controller based on original config
            # This is a simplification - in production might need better tracking
            if nodes:
                controller_node = nodes[0]
                agent_nodes = nodes[1:] if len(nodes) > 1 else []

        if not controller_node:
            self.logger.warning(f"Cannot delete {label} - no controller node found")
            return

        kube_version = resource.get('k3s_version', KUBE_VERSION)
        flannel_iface = resource.get('flannel_iface', None)
        flannel_ipv6_masq = resource.get('flannel_ipv6_masq', False)

        service_name_prefix = resource.get(Constants.RES_NAME_PREFIX)
        service_name = f"{self.name}-{service_name_prefix}"

        service = K3sService(
            label=label,
            name=service_name,
            controller_node=controller_node,
            agent_nodes=agent_nodes,
            k3s_version=kube_version,
            flannel_iface=flannel_iface,
            flannel_ipv6_masq=flannel_ipv6_masq,
            provider=self,
            logger=self.logger
        )

        service.delete()
        self.resource_listener.on_deleted(source=self, provider=self, resource=service)
