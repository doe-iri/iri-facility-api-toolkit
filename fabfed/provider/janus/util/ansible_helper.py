#!/usr/bin/env python3
# MIT License
#
# Copyright (c) 2020 FABRIC Testbed
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
#
# Author: Komal Thareja (kthare10@renci.org)
# Create a callback plugin so we can capture the output
import os
import traceback
from typing import Tuple

from ansible import context
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.inventory.manager import InventoryManager
from ansible.module_utils.common.collections import ImmutableDict
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.callback import CallbackBase
from ansible.vars.manager import VariableManager
from ansible_runner import Runner, RunnerConfig


class PlaybookException(Exception):
    """
    Playbook Exception
    """
    pass


class ResultsCollectorJSONCallback(CallbackBase):
    """A callback plugin used for performing an action as results come in.

    If you want to collect all results into a single object for processing at
    the end of the execution, look into utilizing the ``json`` callback plugin
    or writing your own custom callback plugin.
    """

    def __init__(self, *args, **kwargs):
        super(ResultsCollectorJSONCallback, self).__init__(*args, **kwargs)
        self.host_ok = {}
        self.host_unreachable = {}
        self.host_failed = {}

    def v2_runner_on_unreachable(self, result):
        """
        Store the result in an instance attribute for retrieval later
        @param result result
        """
        host = result._host
        if host is not None:
            self.host_unreachable[host.get_name()] = result

    def v2_runner_on_ok(self, result, *args, **kwargs):
        """
        Store the result in an instance attribute for retrieval later
        @param result result
        """
        host = result._host
        if host is not None:
            self.host_ok[host.get_name()] = result

    def v2_runner_on_failed(self, result, *args, **kwargs):
        """
        Store the result in an instance attribute for retrieval later
        @param result result
        """
        host = result._host
        if host is not None:
            self.host_failed[host.get_name()] = result

    def __get_json_result(self, host_result_map: dict, host: str = None):
        """
        Get Json Result for a host
        @param host host
        @param host_result_map map containing host results
        """
        if host is None:
            if host_result_map is not None and len(host_result_map) > 0:
                result = next(iter(host_result_map.values()))
                return result._result
        else:
            result = host_result_map.get(host, None)
            if result is not None:
                return result._result
        return None

    def get_json_result_ok(self, host: str = None):
        """
        Get Json OK Result for a host
        @param host host
        """
        return self.__get_json_result(host=host, host_result_map=self.host_ok)

    def get_json_result_unreachable(self, host: str = None):
        """
        Get Json Unreachable Result for a host
        @param host host
        """
        return self.__get_json_result(host=host, host_result_map=self.host_unreachable)

    def get_json_result_failed(self, host: str = None):
        """
        Get Json Failed Result for a host
        @param host host
        """
        return self.__get_json_result(host=host, host_result_map=self.host_failed)

    def is_failed_or_unreachable(self) -> Tuple[bool, str]:
        status = False
        msg = None
        if len(self.host_failed) > 0 or len(self.host_unreachable) > 0:
            status = True
            result = self.get_json_result_failed()
            if result is not None:
                msg = result.get('msg', None)
            else:
                result = self.get_json_result_unreachable()
                if result is not None:
                    msg = result.get('msg', None)

        return status, msg

    def dump_all(self, host_result_map: dict, logger):
        if host_result_map is not None and len(host_result_map) > 0:
            for result in host_result_map.values():
                logger.info(self._dump_results(result=result._result))

    def dump_all_failed(self, logger):
        self.dump_all(host_result_map=self.host_failed, logger=logger)

    def dump_all_ok(self, logger):
        self.dump_all(host_result_map=self.host_ok, logger=logger)

    def dump_all_unreachable(self, logger):
        self.dump_all(host_result_map=self.host_unreachable, logger=logger)


class AnsibleHelper:
    """
    Helper class to invoke the Ansible Playbook
    """
    def __init__(self, inventory_path: str, logger):
        self.results_callback = ResultsCollectorJSONCallback()
        self.loader = DataLoader()
        self.inventory = InventoryManager(loader=self.loader, sources=[inventory_path])
        self.variable_manager = VariableManager(loader=self.loader, inventory=self.inventory)
        self.logger = logger

    def add_vars(self, host: str, var_name: str, value: str):
        """
        Set environment variables needed by the playbook
        @param host host
        @param var_name variable name
        @param value value
        """
        self.variable_manager.set_host_variable(host=host, varname=var_name, value=value)

    def run_playbook(self, playbook_path: str, tags: list = [], limit: str = None):
        """
        Run a playbook
        @param playbook_path path for the playbook
        @raises Exception in case of failure
        """
        if not os.path.exists(playbook_path):
            raise PlaybookException("Playbook not found")

        context.CLIARGS = ImmutableDict(connection='smart', tags=tags, listtags=False, listtasks=False, listhosts=False,
                                        syntax=False,
                                        module_path=None, forks=100, private_key_file=None,
                                        ssh_common_args=None, ssh_extra_args='-o StrictHostKeyChecking=no',
                                        sftp_extra_args=None,
                                        scp_extra_args=None, become=False,
                                        become_method='sudo', become_user='root', verbosity=True, check=False,
                                        start_at_task=None)
        passwords = {}

        if limit:
            try:
                self.inventory.subset(limit)
            except Exception as e:
                self.logger.debug(f"Error filtering hosts: {e}")

        pbex = PlaybookExecutor(playbooks=[playbook_path], inventory=self.inventory,
                                variable_manager=self.variable_manager,
                                loader=self.loader, passwords=passwords)

        #pbex._tqm._stdout_callback = self.results_callback
        try:
            results = pbex.run()
            self.logger.debug(f"Playbook result: {results}")

            status, msg = self.results_callback.is_failed_or_unreachable()
            if status:
                raise PlaybookException(f"Playbook has failed tasks: {msg}")
        finally:
            self.logger.debug("OK:")
            self.results_callback.dump_all_ok(logger=self.logger)
            self.logger.debug("Failed:")
            self.results_callback.dump_all_failed(logger=self.logger)
            self.logger.debug("Unreachable:")
            self.results_callback.dump_all_unreachable(logger=self.logger)
            if self.loader is not None:
                self.loader.cleanup_all_tmp_files()

    def get_result_callback(self):
        """
        Fetch the Result Callback which contains all the results
        @return result callback
        """
        return self.results_callback

    def set_extra_vars(self, extra_vars: dict):
        """
        Set Extra Variables
        :param extra_vars: Extra variable dict
        :return:
        """
        self.variable_manager._extra_vars = extra_vars


class AnsibleRunnerHelper:
    """
    Helper class to invoke the Ansible Playbook
    """
    def __init__(self, inventory_path: str, logger):
        self.loader = DataLoader()
        self.inventory_path = inventory_path
        self.inventory = InventoryManager(loader=self.loader, sources=[inventory_path])
        self.variable_manager = VariableManager(loader=self.loader, inventory=self.inventory)
        self.logger = logger

    def add_vars(self, host: str, var_name: str, value: str):
        """
        Set environment variables needed by the playbook
        @param host host
        @param var_name variable name
        @param value value
        """
        self.variable_manager.set_host_variable(host=host, varname=var_name, value=value)

    def run_playbook(self, playbook_path: str, tags: list = [], limit: str = None):
        rc = RunnerConfig(
            forks=100,
            private_data_dir='/tmp/fabfed_ansible',
            project_dir='ansible',
            playbook=playbook_path,
            tags=','.join(tags),
            limit=limit,
            inventory=self.inventory_path,
            extravars=self.variable_manager.get_vars()
        )

        def my_event_handler(event):
            if dump := event.get("stdout"):
                self.logger.info(dump)

        rc.prepare()
        rc.suppress_ansible_output = True
        r = Runner(config=rc, event_handler=my_event_handler)
        r.run()
        self.logger.debug(f"Playbook result: {r.stats}")

    def get_result_callback(self):
        """
        Fetch the Result Callback which contains all the results
        @return result callback
        """
        return self.results_callback

    def set_extra_vars(self, extra_vars: dict):
        """
        Set Extra Variables
        :param extra_vars: Extra variable dict
        :return:
        """
        self.variable_manager._extra_vars = extra_vars
