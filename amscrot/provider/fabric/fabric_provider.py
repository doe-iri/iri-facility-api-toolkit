import logging

from amscrot.provider.api.provider import Provider
from ...util.constants import Constants
from .fabric_constants import *
from amscrot.util.utils import get_logger
from amscrot.exceptions import ProviderException

logger = get_logger()


class FabricProvider(Provider):
    def __init__(self, *, type, label, name, config: dict):
        super().__init__(type=type, label=label, name=name, logger=logger, config=config)
        self.slice = None
        self.retry = 5
        self.slice_init = False
        # TODO Should not be needed for fablib 1.6.4
        from fabrictestbed_extensions.fablib.constants import Constants as FC
        from amscrot.util.utils import get_base_dir

        FC.DEFAULT_FABRIC_CONFIG_DIR = get_base_dir(self.name)
        FC.DEFAULT_FABRIC_RC = f"{FC.DEFAULT_FABRIC_CONFIG_DIR}/fabric_rc"



    def _to_abs_for(self, env_var: str, config: dict):
        path = config.get(env_var)

        from pathlib import Path

        path = str(Path(path).expanduser().absolute())

        try:
            with open(path, 'r') as f:
                f.read()
                logger.debug(f"was able to read {path}")
        except Exception as e:
            raise ProviderException(f"{self.name}:Unable to read {path} for {env_var}:{e}")

        try:
            if path.endswith(".json"):
                with open(path, 'r') as fp:
                    import json

                    json.load(fp)
        except Exception as e:
            raise ProviderException(f"{self.name}:Unable to parse {path} to json for {env_var}:{e}")

        return path

    def setup_environment(self):
        config = self.config

        import os

        for attr in FAB_CONF_ATTRS:
            if config.get(attr) is None:
                raise ProviderException(f"{self.name}: Expecting a value for {attr}")

        os.environ['FABRIC_CREDMGR_HOST'] = config.get(FABRIC_CM_HOST, DEFAULT_CM_HOST)
        os.environ['FABRIC_ORCHESTRATOR_HOST'] = config.get(FABRIC_OC_HOST, DEFAULT_OC_HOST)
        os.environ['FABRIC_PROJECT_ID'] = config.get(FABRIC_PROJECT_ID)
        os.environ['FABRIC_BASTION_HOST'] = config.get(FABRIC_BASTION_HOST, DEFAULT_BASTION_HOST)
        os.environ['FABRIC_BASTION_USERNAME'] = config.get(FABRIC_BASTION_USER_NAME)

        os.environ['FABRIC_BASTION_KEY_LOCATION'] = self._to_abs_for(FABRIC_BASTION_KEY_LOCATION, config)
        os.environ['FABRIC_SLICE_PRIVATE_KEY_FILE'] = self._to_abs_for(FABRIC_SLICE_PRIVATE_KEY_LOCATION, config)
        os.environ['FABRIC_SLICE_PUBLIC_KEY_FILE'] = self._to_abs_for(FABRIC_SLICE_PUBLIC_KEY_LOCATION, config)

        token_location = self._to_abs_for(FABRIC_TOKEN_LOCATION, config)

        if Constants.COPY_TOKENS:
            import shutil
            import uuid

            destination = f'/tmp/tokens/token-{self.name}-{uuid.uuid4()}.json'
            shutil.copy2(token_location, destination)
            token_location = destination

        os.environ['FABRIC_TOKEN_LOCATION'] = token_location

        from . import fabric_slice_helper

        fabric_slice_helper.patch_for_token()

    def _init_slice(self, destroy_phase=False):
        if not self.slice_init:
            self.logger.info(f"Initializing slice {self.name}")

            import time
            from amscrot.util.utils import get_log_level, get_log_location

            location = get_log_location()

            for attempt in range(self.retry):
                try:
                    from fabrictestbed_extensions.fablib.fablib import fablib

                    if fablib.get_default_fablib_manager().get_log_file() != location:
                        self.logger.debug("Initializing fablib extensions logging ...")
                        fablib.get_default_fablib_manager().set_log_file(location)
                        fablib.get_default_fablib_manager().set_log_level(get_log_level())

                        for handler in logging.root.handlers.copy():
                            logging.root.removeHandler(handler)

                        for handler in self.logger.handlers:
                            logging.root.addHandler(handler)

                    from amscrot.provider.fabric.fabric_slice import FabricSlice

                    temp = FabricSlice(provider=self, logger=self.logger)
                    temp.init(destroy_phase)
                    self.slice = temp
                    self.logger.info(f"Done initializing slice {self.name}")
                    break
                except Exception as e:
                    if attempt == self.retry - 1:
                        raise e

                    self.logger.info(f"Initializing slice {self.name}. Going to sleep. Will retry ...{e}")
                time.sleep(2)

            self.logger.info(f"Initialized slice {self.name}")
            self.slice_init = True

    def supports_modify(self):
        return True

    def do_validate_resource(self, *, resource: dict):
        self._init_slice()
        assert self.slice.slice_object is not None
        self.slice.validate_resource(resource=resource)

    def do_add_resource(self, *, resource: dict):
        assert self.slice.slice_object is not None
        self.slice.add_resource(resource=resource)

    def do_create_resource(self, *, resource: dict):
        assert self.slice.slice_object is not None
        self.slice.create_resource(resource=resource)

    def do_wait_for_create_resource(self, *, resource: dict):
        assert self.slice.slice_object is not None
        self.slice.wait_for_create_resource(resource=resource)

    def do_delete_resource(self, *, resource: dict):
        self._init_slice(True)
        self.slice.delete_resource(resource=resource)
