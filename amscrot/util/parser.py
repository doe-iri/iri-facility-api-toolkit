from types import SimpleNamespace
from typing import List, Tuple, Union

from .config_models import *
from .constants import Constants
from .resource_dependency_helper import order_resources
from .variable_evaluator import VariableEvaluator, Evaluator


def normalize(objs):  # TODO looks like we need this  for chameleon provider
    for obj in objs:
        attrs = {}

        for key, value in obj.attributes.items():
            if isinstance(value, SimpleNamespace):
                attrs[key] = vars(value)
            else:
                attrs[key] = value

        obj.attributes = attrs


def parse_pair(obj: SimpleNamespace) -> Tuple[str, Dict]:
    def extract_label(lst):
        return next(label for label in lst if not label.startswith("__"))

    if not isinstance(obj, SimpleNamespace):
        raise ParseConfigException(f"expecting a pair {obj}")

    try:
        name = extract_label(dir(obj))

        if not obj.__getattribute__(name):
            return name, {}

        if isinstance(obj.__getattribute__(name), list):
            attrs = obj.__getattribute__(name)[0].__dict__

            if len(obj.__getattribute__(name)) > 1:
                raise ParseConfigException(f"did not expect a block after {attrs} under {name} of type {type}")
        else:
            attrs = obj.__getattribute__(name).__dict__

        return name, attrs
    except ParseConfigException as e:
        raise e
    # except Exception as e:
    #     raise ParseConfigException(f" exception occurred while parsing pair {obj}") from e


def parse_triplet(obj: SimpleNamespace) -> List[Tuple[str, str, Dict]]:
    def extract_label(lst):
        return next(label for label in lst if not label.startswith("__"))

    if not isinstance(obj, SimpleNamespace):
        raise ParseConfigException(f"expecting a triplet {obj}")

    try:
        type = extract_label(dir(obj))
        triplets = []

        for v in obj.__getattribute__(type):
            name = extract_label(dir(v))

            if isinstance(v.__getattribute__(name), list):
                attrs = v.__getattribute__(name)[0].__dict__

                if len(v.__getattribute__(name)) > 1:
                    raise ParseConfigException(f"did not expect a block after {attrs} under {name} of type {type}")
            else:
                attrs = v.__getattribute__(name).__dict__

            triplets.append((type, name, attrs))

        return triplets
    except ParseConfigException as e:
        raise e
    except Exception as e:
        raise ParseConfigException(f" exception occurred while parsing triplet {obj}") from e


class Parser:
    def __init__(self):
        pass

    @staticmethod
    def _parse_variable(obj) -> Variable:
        name, attributes = parse_pair(obj)
        return Variable(name, attributes.get('default', None))

    @staticmethod
    def _parse_provider(obj) -> List[ProviderConfig]:
        return [ProviderConfig(type, name, attributes) for type, name, attributes in parse_triplet(obj)]

    @staticmethod
    def _parse_config(obj) -> List[Config]:
        return [Config(type, name, attributes) for type, name, attributes in parse_triplet(obj)]

    @staticmethod
    def _parse_resource_base_config(obj) -> List[BaseConfig]:
        return [BaseConfig(type, name, attributes) for type, name, attributes in parse_triplet(obj)]

    @staticmethod
    def _filter_resources(base_configs, providers) -> List[ResourceConfig]:
        resources = []

        for base_config in base_configs:
            resources.append(resource_from_basic_config(base_config, providers))

        return resources

    @staticmethod
    def _validate_variables(variables: List[Variable]):
        if len(variables) != len(set(variables)):
            raise ParseConfigException(f'detected duplicate variables')

        for variable in variables:
            if variable.value is None:
                raise ParseConfigException(f'variable {variable .name} is not bound')

    @staticmethod
    def _validate_providers(providers: List[ProviderConfig]):
        if len(providers) == 0:
            raise ParseConfigException("no providers found ...")

        if len(providers) != len(set(providers)):
            raise ParseConfigException(f'detected duplicate providers')

        from amscrot.exceptions import ProviderTypeNotSupported

        for provider in providers:
            if provider.type not in Constants.PROVIDER_CLASSES:
                raise ProviderTypeNotSupported(provider.type)

    @staticmethod
    def _validate_configs(configs: List[Config]):
        from amscrot.exceptions import ConfigTypeNotSupported

        for config in configs:
            if config.type not in Constants.CONFIG_SUPPORTED_TYPES:
                raise ConfigTypeNotSupported(config.type)

    @staticmethod
    def _validate_resources(resources: List[ResourceConfig]):
        # if len(resources) == 0:
        #     raise ParseConfigException("no resources found ...")

        if len(resources) != len(set(resources)):
            raise ParseConfigException(f'detected duplicate resources')

        from amscrot.exceptions import ResourceTypeNotSupported

        for resource in resources:
            if resource.type not in Constants.RES_SUPPORTED_TYPES:
                raise ResourceTypeNotSupported(resource.type)

        for resource in resources:
            count = resource.attributes.get(Constants.RES_COUNT, 1)

            if count > 1 and resource.type in Constants.RES_RESTRICTED_TYPES:
                raise ParseConfigException(f'{resource.label} is of type {resource.type} and cannot have count > 1')

    @staticmethod
    def parse_variables(ns_list: list, var_dict: dict) -> List[Variable]:
        variables = []

        for ns in ns_list:
            if hasattr(ns, 'variable') and ns.variable:
                temp_variables = [Parser._parse_variable(variable) for variable in ns.variable]
                variables.extend(temp_variables)

        if var_dict:
            variable_map = {v.name: v for v in variables}

            for key, value in var_dict.items():
                variable_map[key] = Variable(key, value)

            variables = list(variable_map.values())

        Parser._validate_variables(variables)
        return variables

    @staticmethod
    def parse_providers(ns_list: list) -> List[ProviderConfig]:
        providers = []

        for ns in ns_list:
            if hasattr(ns, 'provider') and ns.provider:
                temp_providers = [Parser._parse_provider(provider) for provider in ns.provider]
                temp_providers = sum(temp_providers, [])
                providers.extend(temp_providers)

        Parser._validate_providers(providers)
        normalize(providers)
        return providers

    @staticmethod
    def parse_configs(ns_list: List[SimpleNamespace]) -> List[Config]:
        configs = []

        for ns in ns_list:
            if hasattr(ns, 'config') and ns.config:
                temp_configs = [Parser._parse_config(config) for config in ns.config]
                temp_configs = sum(temp_configs, [])
                configs.extend(temp_configs)

        Parser._validate_configs(configs)
        return configs

    @staticmethod
    def parse_resource_base_configs(ns_list: List[SimpleNamespace]) -> List[BaseConfig]:
        resource_base_configs = []

        for ns in ns_list:
            if hasattr(ns, 'resource') and ns.resource:
                temp_resource_base_configs = [Parser._parse_resource_base_config(resource) for resource in ns.resource]
                temp_resource_base_configs = sum(temp_resource_base_configs, [])
                resource_base_configs.extend(temp_resource_base_configs)

        return resource_base_configs

    @staticmethod
    def parse(*, dir_path: Union[str, None] = None, content: Union[str, None] = None,
              var_dict: Union[Dict, None] = None) -> Tuple[List[ProviderConfig], List[ResourceConfig]]:

        from .utils import load_as_ns_from_yaml

        ns_list = load_as_ns_from_yaml(dir_path=dir_path, content=content)
        variables = Parser.parse_variables(ns_list, var_dict)

        providers = Parser.parse_providers(ns_list)
        configs = Parser.parse_configs(ns_list)
        resource_base_configs = Parser.parse_resource_base_configs(ns_list)
        variable_evaluator = VariableEvaluator(variables=variables, providers=providers, configs=configs,
                                               resources=resource_base_configs)
        providers, configs, resource_configs = variable_evaluator.evaluate()

        evaluator = Evaluator(providers=providers, configs=configs, resources=resource_configs)

        providers, configs, resource_configs = evaluator.evaluate()
        resources = Parser._filter_resources(resource_configs, providers)

        Parser._validate_resources(resources)
        resources = [r for r in resources if r.attributes.get(Constants.RES_COUNT, 1) > 0]

        from .resource_dependency_helper import ResourceDependencyEvaluator

        dependency_evaluator = ResourceDependencyEvaluator(resources, providers)
        dependency_map = dependency_evaluator.evaluate()
        ordered_resources = order_resources(dependency_map)
        return providers, ordered_resources
