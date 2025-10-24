from .parser import Parser
from .config_models import ResourceConfig, ProviderConfig
from typing import List, Union, Dict


class WorkflowConfig:
    def __init__(self, *, provider_configs: List[ProviderConfig], resource_configs: List[ResourceConfig]):
        self.provider_configs = provider_configs
        self.resource_configs = resource_configs

    def get_provider_configs(self) -> List[ProviderConfig]:
        return self.provider_configs

    def get_resource_configs(self) -> List[ResourceConfig]:
        return self.resource_configs

    @staticmethod
    def parse(*, dir_path: Union[str, None] = None, content: Union[str, None] = None,
              var_dict: Union[Dict, None] = None):
        provider_configs, resource_configs = Parser.parse(dir_path=dir_path, content=content, var_dict=var_dict)
        return WorkflowConfig(provider_configs=provider_configs, resource_configs=resource_configs)
