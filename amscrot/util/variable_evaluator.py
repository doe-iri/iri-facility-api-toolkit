from types import SimpleNamespace
from typing import List, Tuple

from amscrot.exceptions import ParseConfigException
from amscrot.util.config_models import Variable, ProviderConfig, Config, BaseConfig, Dependency, DependencyInfo
from amscrot.util.constants import Constants


class VariableEvaluator:
    def __init__(self, *, variables: List[Variable], providers: List[ProviderConfig], configs: List[Config],
                 resources: List[BaseConfig]):
        self.variables = variables
        self.providers = providers
        self.configs = configs
        self.resources = resources

    def find_variable(self, path: str) -> BaseConfig or Dependency:
        parts = path.split('.')
        assert parts[0] == 'var'

        if len(parts) != 2:
            raise ParseConfigException(f"bad variable dependency {path}")

        for variable in self.variables:
            if variable.name == parts[1]:
                return variable.value

        raise ParseConfigException(f'variable not found at {path}')

    def handle_substitution(self, value):
        if isinstance(value, str):
            value = value.strip()

            if value.startswith('{{') and value.endswith('}}'):
                path = value[2:-2].strip()

                if path.startswith('var'):
                    return self.find_variable(path)

            return value
        elif isinstance(value, list):
            temp = []
            for val in value:
                temp.append(self.handle_substitution(val))
            return temp
        elif isinstance(value, dict):
            temp = {}

            for k, val in value.items():
                temp[k] = self.handle_substitution(val)

            return temp
        elif isinstance(value, SimpleNamespace):
            return self.handle_substitution(vars(value))
        else:
            return value

    def evaluate(self) -> Tuple[List[ProviderConfig], List[Config], List[BaseConfig]]:
        config_entries: List[BaseConfig] = []
        config_entries.extend(self.providers)
        config_entries.extend(self.configs)
        config_entries.extend(self.resources)

        for config_resource_entry in config_entries:
            attrs = {}

            for key, value in config_resource_entry.attributes.items():
                attrs[key] = self.handle_substitution(value)

            config_resource_entry.attributes = attrs

        return self.providers, self.configs, self.resources


class Evaluator:
    def __init__(self, *, providers: List[ProviderConfig], configs: List[Config], resources: List[BaseConfig]):
        self.providers = providers
        self.configs = configs
        self.resources = resources

    def find_object(self, path: str) -> BaseConfig or Dependency:
        parts = path.lower().split('.')
        config_entries: List[BaseConfig] = []
        config_entries.extend(self.providers)
        config_entries.extend(self.configs)
        config_entries.extend(self.resources)

        if len(parts) < 2:
            raise ParseConfigException(f"bad dependency {path}")

        temp = [Config.__name__, ProviderConfig.__name__]

        for config_entry in config_entries:
            if config_entry.type == parts[0] and config_entry.var_name == parts[1]:
                if config_entry.__class__.__name__ not in temp and config_entry.type in Constants.RES_SUPPORTED_TYPES:
                    return DependencyInfo(resource=config_entry, attribute='.'.join(parts[2:]))

                return config_entry

        raise ParseConfigException(f'config entry not found at {path}')

    def handle_substitution(self, value):
        if isinstance(value, str):
            value = value.strip()

            if value.startswith('{{') and value.endswith('}}'):
                path = value[2:-2].strip()
                return self.find_object(path)

            return value
        elif isinstance(value, list):
            temp = []
            for val in value:
                temp.append(self.handle_substitution(val))
            return temp
        elif isinstance(value, dict):
            temp = {}

            for k, val in value.items():
                temp[k] = self.handle_substitution(val)

            return temp
        elif isinstance(value, SimpleNamespace):
            raise Exception(f'{value}')
            # return self.handle_substitution(vars(value))
        else:
            return value

    def evaluate(self) -> Tuple[List[ProviderConfig], List[Config], List[BaseConfig]]:
        for config_resource_entry in self.resources:
            attrs = {}

            for key, value in config_resource_entry.attributes.items():
                attrs[key] = self.handle_substitution(value)

            config_resource_entry.attributes = attrs

        return self.providers, self.configs, self.resources
