import logging

from amscrot.model import Service, Node, SSHNode
from amscrot.provider.api.provider import Provider
from amscrot.util.constants import Constants

'''

To add a provider, all you should need is to add its classpath to fabfed.util.constants.Constants.PROVIDER_CLASSES


see tests/examples/dummy-service for a simple example.
see tests/examples/dummy-service-dependency for en example with an external dependency. (Dependency across providers)

This example also show how to hide attributes by using underscores and how to expose interesting attributes
to other resources by extracting it and using yaml python supported types.

Useful Commands:
see tests/examples/dummy-service  # for a simple example
see tests/examples/dummy-service/config.fab 

>fabfed workflow --session <session> -validate
>fabfed workflow --session <session> -plan
>fabfed workflow --session <session> -apply
>fabfed workflow --session <session> -show
>fabfed workflow --session <session> -destroy
'''


class HideAttribute:
    def __init__(self, *, x=10, y=20):
        self.x = x
        self.y = y

class DummyNode(Node, SSHNode):
    def __init__(self, *, label, name: str, image, site, flavor, logger: logging.Logger):
        super().__init__(label=label, name=name, image=image, site=site, flavor=flavor)
        self.logger = logger

    def create(self):
        import random
        self.logger.info(f" Dummy Node {self.name} created.")
        self.user = "dummy_user"
        self.host = f"localhost_{self.name}"
        self.keyfile = "~/.ssh/dummy_key"
        #self.jump_user = "dummy_jump_user"
        self.jump_host = "dummy.jumphost.net"
        self.jump_keyfile = "~/.ssh/dummy_jump_key"

    def delete(self):
        self.logger.info(f" Dummy Node {self.name} deleted")

    def get_reservation_id(self):
        pass

    def get_reservation_state(self):
        pass

    def add_route(self, subnet, gateway):
        pass

    def get_dataplane_address(self, network=None, interface=None, af=None):
        return "192.168.1.10"

class DummyService(Service):
    def __init__(self, *, label, name: str, image, x=None, logger: logging.Logger):
        super().__init__(label=label, name=name)
        self.logger = logger
        self.image = image
        # We hide a complex attribute by using underscores otherwise marshalling the state will fail
        # as we do not have yaml representer for it.
        self._hidden_attribute = HideAttribute(x=x)
        self.exposed_attribute_x = self._hidden_attribute.x  # Here we expose x which can be marshalled

    def create(self):
        import random

        if not self.exposed_attribute_x:
            self._hidden_attribute = HideAttribute(x=random.randint(1, 5), y=random.random())
            self.exposed_attribute_x = self._hidden_attribute.x

        self.logger.info(f" Dummy Service {self.name} created. X={self.exposed_attribute_x}")

    def delete(self):
        self.logger.info(f" Dummy Service {self.name} deleted")

from amscrot.util.utils import get_logger

logger: logging.Logger = get_logger()


class DummyProvider(Provider):

    def setup_environment(self):
        pass

    def __init__(self, *, type, label, name, config: dict):
        super().__init__(type=type, label=label, name=name, logger=logger, config=config)

    def _validate_resource(self, resource: dict):
        assert resource.get(Constants.LABEL)
        assert resource.get(Constants.RES_TYPE) in Constants.RES_SUPPORTED_TYPES
        assert resource.get(Constants.RES_NAME_PREFIX)
        assert resource.get(Constants.RES_COUNT, 1)

        label = resource.get(Constants.LABEL)
        self.logger.info(f"Validated:OK Resource={label} using {self.label}")

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
        label = resource.get(Constants.LABEL)
        self.logger.info(f"Adding resource={label} using {self.label}")
        self._validate_resource(resource)
        image = resource.get(Constants.RES_IMAGE)
        exposed_attribute_x = resource.get("exposed_attribute_x")

        # In the dependency example, exposed_attribute_x is an external dependency
        import amscrot.provider.api.dependency_util as util

        if util.has_resolved_external_dependencies(resource=resource, attribute='exposed_attribute_x'):
            # Service dtn1 depends on service dtn2. dtn1 and dtn2 have different providers.
            # Extract all values. There can be more than one if count of service.dtn2 is greater than 1.

            values = util.get_values_for_dependency(resource=resource, attribute='exposed_attribute_x')
            assert values

            # The next line handles both dependencies:
            #          exposed_attribute_x: "{{ service.dtn2 }}"
            #          exposed_attribute_x: "{{ service.dtn2.exposed_attribute_x }}"
            values = [value.exposed_attribute_x if isinstance(value, DummyService) else value for value in values]
            exposed_attribute_x = sum(values)

        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)

        if rtype == Constants.RES_TYPE_NODE.lower():
            node_count = resource.get(Constants.RES_COUNT, 1)
            name_prefix = resource.get(Constants.RES_NAME_PREFIX)
            site = resource.get(Constants.RES_SITE)
            flavor = resource.get(Constants.RES_FLAVOR, "dummy_flavor")

            for i in range(node_count):
                name = f"{name_prefix}{i}"
                node = DummyNode(label=label, name=name, site=site, image=image, flavor=flavor, logger=self.logger)
                self.nodes.append(node)
                self.resource_listener.on_added(source=self, provider=self, resource=node)

        elif rtype == Constants.RES_TYPE_SERVICE.lower():
            service_count = resource.get(Constants.RES_COUNT, 1)
            service_name_prefix = resource.get(Constants.RES_NAME_PREFIX)

            for n in range(0, service_count):
                service_name = f"{self.name}-{service_name_prefix}-{n}"
                service = DummyService(label=label, name=service_name, image=image,
                                       x=exposed_attribute_x, logger=self.logger)

                self._services.append(service)
                self.resource_listener.on_added(source=self, provider=self, resource=service)

    def do_create_resource(self, *, resource: dict):
        """
        Called by create_resource(self, *, resource: dict) if resource has no external dependencies
        @param resource: resource attributes
        """
        label = resource.get(Constants.LABEL)
        self.logger.info(f"Creating resource={resource} using {self.label}")

        rtype = resource.get(Constants.RES_TYPE)

        if rtype == Constants.RES_TYPE_NODE.lower():
            for node in self.nodes:
                node.create()
                self.resource_listener.on_created(source=self, provider=self, resource=node)
        elif rtype == Constants.RES_TYPE_NETWORK.lower():
            for net in self.networks:
                net.create()
                self.resource_listener.on_created(source=self, provider=self, resource=net)
        elif rtype == Constants.RES_TYPE_SERVICE.lower():
            temp = [service for service in self.services if service.label == label]
            for service in temp:
                service.create()
                self.resource_listener.on_created(source=self, provider=self, resource=service)

    def do_delete_resource(self, *, resource: dict):
        self.logger.info(f"Deleting resource={resource} using {self.label}")

        label = resource.get(Constants.LABEL)
        rtype = resource.get(Constants.RES_TYPE)
        name_prefix = resource.get(Constants.RES_NAME_PREFIX)

        if rtype == Constants.RES_TYPE_NODE.lower():
            node_count = resource.get(Constants.RES_COUNT, 1)
            for i in range(node_count):
                name = f"{name_prefix}{i}"
                node = DummyNode(label=label, name=name, site=None, image=None, flavor=None, logger=self.logger)
                node.delete()
                self.resource_listener.on_deleted(source=self, provider=self, resource=node)
        elif rtype == Constants.RES_TYPE_NETWORK.lower():
            pass
        elif rtype == Constants.RES_TYPE_SERVICE.lower():
            service_count = resource.get(Constants.RES_COUNT, 1)
            image = resource.get(Constants.RES_IMAGE)
            for n in range(0, service_count):
                service_name = f"{self.name}-{name_prefix}-{n}"
                service = DummyService(label=label, name=service_name, image=image, logger=self.logger)
                service.delete()
                self.resource_listener.on_deleted(source=self, provider=self, resource=service)
