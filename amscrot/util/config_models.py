from collections import namedtuple
from typing import Dict, Set, Any

from amscrot.exceptions import ParseConfigException
from amscrot.util.constants import Constants


class BaseConfig:
    def __init__(self, type: str, name: str, attrs: Dict):
        self.type = type.lower()
        self._var_name = name.lower()
        self.attributes = attrs

    @property
    def label(self) -> str:
        return self._var_name + '@' + self.type

    @property
    def var_name(self) -> str:
        return self._var_name

    @property
    def name(self) -> str:
        return self.attributes['name'] if 'name' in self.attributes else self._var_name

    def attribute(self, key: str):
        return self.attributes.get(key)

    def __str__(self) -> str:
        return self.var_name + '@' + self.type

    def __repr__(self) -> str:
        return self.__str__()

    def __eq__(self, other):
        return (self.var_name, self.type) == (other.var_name, other.type)

    def __hash__(self):
        return hash(str(self))


class Config(BaseConfig):
    def __init__(self, type: str, name: str, attrs: Dict):
        super().__init__(type, name, attrs)


class ProviderConfig(BaseConfig):
    def __init__(self, type: str, name: str, attrs: Dict):
        super().__init__(type, name, attrs)


Dependency = namedtuple("Dependency", "key resource attribute is_external")


class ResourceConfig(BaseConfig):
    def __init__(self, type: str, name: str, attrs:  Dict, provider: ProviderConfig):
        super().__init__(type, name, attrs)
        assert provider, f"provider is required for {name}"
        assert isinstance(provider, ProviderConfig), f"expected ProviderConfig for {name}"
        self._provider = provider
        self._resource_dependencies = set()

    @property
    def provider(self) -> ProviderConfig:
        return self._provider

    @property
    def dependencies(self) -> Set[Dependency]:
        return self._resource_dependencies

    def add_dependency(self, dependency):
        self._resource_dependencies.add(dependency)

    def has_dependencies(self):
        return len(self._resource_dependencies) > 0

    @property
    def is_node(self):
        return self.type == Constants.RES_TYPE_NODE

    @property
    def is_network(self):
        return self.type == Constants.RES_TYPE_NETWORK

    @property
    def is_service(self):
        return self.type == Constants.RES_TYPE_SERVICE


def resource_from_basic_config(basic_config, providers) -> ResourceConfig:
    if isinstance(basic_config, ResourceConfig):
        return basic_config

    attrs = basic_config.attributes.copy()

    if 'provider' not in attrs:
        raise ParseConfigException(f"resource {basic_config.var_name} missing provider")

    provider = attrs.pop('provider')

    if not provider:
        raise ParseConfigException(f"missing provider while parsing {basic_config}")

    index = providers.index(ProviderConfig(provider.type, provider.var_name, {}))

    if index < 0:
        raise ParseConfigException(f"did not find provider {provider.var_name} for {basic_config}")

    return ResourceConfig(basic_config.type, basic_config.var_name, attrs, provider)


DependencyInfo = namedtuple("DependencyInfo", "resource  attribute")


class Variable:
    def __init__(self, name: str, value: Any):
        self._name = name.lower()
        self._value = value

    @property
    def name(self) -> str:
        return self._name

    @property
    def value(self) -> str:
        return self._value

    def __str__(self) -> str:
        return 'Variable[' + self.name + '=' + str(self.value) + ']'

    def __repr__(self) -> str:
        return self.__str__()

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)
