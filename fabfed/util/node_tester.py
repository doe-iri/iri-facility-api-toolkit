import time
import paramiko
import sys

from fabfed.util.utils import get_logger
from fabfed.util.constants import Constants

logger = get_logger()


class SshNodeTester:
    def __init__(self, *, nodes):
        self.nodes = nodes
        self.helpers = []
        self.passed_ssh_test = []
        self.failed_validation = []
        self.failed_ssh_test = []
        self.summary = ''

        dataplane_addresses = [n.get_dataplane_address(af=Constants.IPv4) for n in self.nodes if
                               n.get_dataplane_address(af=Constants.IPv4)]
        self.run_ping_test = len(dataplane_addresses)

        self.passed_dataplane_ping_tests = {}
        self.failed_dataplane_ping_tests = {}

        if self.run_ping_test:
            self.dataplane_addresses = dataplane_addresses

            for n in self.nodes:
                self.passed_dataplane_ping_tests[n.name] = []

        dataplane_addresses = [n.get_dataplane_address(af=Constants.IPv6) for n in self.nodes if
                               n.get_dataplane_address(af=Constants.IPv6)]
        self.run_ipv6_ping_test = len(dataplane_addresses)

        self.passed_ipv6_dataplane_ping_tests = {}
        self.failed_ipv6_dataplane_ping_tests = {}

        if self.run_ipv6_ping_test:
            self.ipv6_dataplane_addresses = dataplane_addresses

            for n in self.nodes:
                self.passed_ipv6_dataplane_ping_tests[n.name] = []

        for n in self.nodes:
            if self.run_ping_test:
                if not n.get_dataplane_address(af=Constants.IPv4):
                    self.failed_validation.append(dict(node=n.label, description="Missing ipv4 dataplane ip"))
                    continue

            # if self.run_ipv6_ping_test:
            #     if not n.get_dataplane_address(af=Constants.IPv6):
            #         self.failed_validation.append(dict(node=n.label, description="Missing ipv6 dataplane"))
            #         continue

            if n.keyfile is None or n.host is None or n.user is None:
                self.failed_validation.append(
                    dict(node=n.label,
                         description=f"Missing node info:user={n.user}:host={n.host}:keyfile={n.keyfile}"))
                continue

            jump_box = (n.jump_keyfile is None, n.jump_host is None, n.jump_user is None)

            if jump_box != (True, True, True) and jump_box != (False, False, False):
                fmt = "Missing bastion info:user={}:host={}:keyfile={}"
                self.failed_validation.append(
                    dict(node=n.label,
                         description=fmt.format(n.jump_user, n.jump_host, n.jump_keyfile)))
                continue

            helper = SshNodeHelper(node=n, label=n.name, host=n.host,
                                   user=n.user,
                                   private_key_file=n.keyfile,
                                   jump_host=n.jump_host,
                                   jump_user=n.jump_user,
                                   jump_private_key_file=n.jump_keyfile)
            self.helpers.append(helper)

    def has_failures(self):
        return self.failed_validation \
               or self.failed_ssh_test or self.failed_dataplane_ping_tests or self.failed_ipv6_dataplane_ping_tests

    def run_ssh_test(self, *, command='ls -l', retry=5, retry_interval=10):
        for helper in self.helpers:
            logger.info(f"SSH executing {command} on Node:{helper.label}")
            failed_attempts = 0

            for attempt in range(retry):
                try:
                    helper.connect()
                    _, stdout, stderr = helper.client.exec_command(command)
                    exit_code = stdout.channel.recv_exit_status()

                    if exit_code:
                        stdout = str(stdout.read(), 'utf-8').replace('\\n', '\n')
                        stderr = str(stderr.read(), 'utf-8').replace('\\n', '\n')
                        sys.stderr.write(stdout)
                        sys.stderr.write(stderr)
                        raise Exception()

                    self.passed_ssh_test.append(helper.label)
                    logger.info(f"Done with SSH {command} on Node:{helper.label}:attempts={attempt + 1}")
                    break
                except Exception as e:
                    logger.warning(f"SSH test failed:{e}. Node:{helper.label}:attempts={attempt + 1}")
                    time.sleep(retry_interval)
                    failed_attempts += 1
                finally:
                    helper.close_quietly()

            if failed_attempts == retry:
                self.failed_ssh_test.append(helper.label)

    def run_dataplane_test(self, *, command='ping -c 3', retry=3, retry_interval=10):
        for helper in self.helpers:
            node = helper.node
            dataplane_addresses = self.dataplane_addresses

            if len(self.dataplane_addresses) > 1:
               dataplane_addresses = [a for a in self.dataplane_addresses if a != node.get_dataplane_address(af=Constants.IPv4)]

            for attempt in range(retry):
                try:
                    helper.connect()

                    for dataplane_address in dataplane_addresses:
                        if dataplane_address in self.passed_dataplane_ping_tests[helper.label]:
                            continue

                        logger.info(f"SSH executing {command} {dataplane_address} on Node: {helper.label}")

                        _, stdout, stderr = helper.client.exec_command(f"{command} {dataplane_address}")
                        exit_code = stdout.channel.recv_exit_status()

                        if exit_code:
                            stdout = str(stdout.read(), 'utf-8').replace('\\n', '\n')
                            stderr = str(stderr.read(), 'utf-8').replace('\\n', '\n')
                            sys.stderr.write(stdout)
                            sys.stderr.write(stderr)
                            raise Exception(f"pinging {dataplane_address}")

                        self.passed_dataplane_ping_tests[helper.label].append(dataplane_address)

                    logger.info(f"Done with SSH {command} on Node: {helper.label}: attempts={attempt + 1}")
                    break
                except Exception as e:
                    logger.warning(f"SSH ping failed: {e}. Node: {helper.label}:attempts={attempt + 1}")
                    time.sleep(retry_interval)
                finally:
                    helper.close_quietly()

            if len(self.passed_dataplane_ping_tests[helper.label]) != len(dataplane_addresses):
                self.failed_dataplane_ping_tests[helper.label] = list(set(dataplane_addresses).difference(
                    self.passed_dataplane_ping_tests[helper.label]))

    def run_ipv6_dataplane_test(self, *, command='ping6 -c 3', retry=3, retry_interval=10):
        for helper in self.helpers:
            logger.info(f"SSH executing {command} on Node: {helper.label}")

            ipv6_dataplane_addresses = self.ipv6_dataplane_addresses

            if len(self.ipv6_dataplane_addresses) > 1:
               ipv6_dataplane_addresses = [a for a in self.ipv6_dataplane_addresses if a != node.get_dataplane_address(af=Constants.IPv6)]

            for attempt in range(retry):
                try:
                    helper.connect()

                    for dataplane_address in ipv6_dataplane_addresses:
                        if dataplane_address in self.passed_ipv6_dataplane_ping_tests[helper.label]:
                            continue

                        _, stdout, stderr = helper.client.exec_command(f"{command} {dataplane_address}")
                        exit_code = stdout.channel.recv_exit_status()

                        if exit_code:
                            stdout = str(stdout.read(), 'utf-8').replace('\\n', '\n')
                            stderr = str(stderr.read(), 'utf-8').replace('\\n', '\n')
                            sys.stderr.write(stdout)
                            sys.stderr.write(stderr)
                            raise Exception(f"pinging {dataplane_address}")

                        self.passed_ipv6_dataplane_ping_tests[helper.label].append(dataplane_address)

                    logger.info(f"Done with SSH {command} on Node: {helper.label}: attempts={attempt + 1}")
                    break
                except Exception as e:
                    logger.warning(f"SSH ping failed: {e}. Node: {helper.label}:attempts={attempt + 1}")
                    time.sleep(retry_interval)
                finally:
                    helper.close_quietly()

            if len(self.passed_ipv6_dataplane_ping_tests[helper.label]) != len(ipv6_dataplane_addresses):
                self.failed_ipv6_dataplane_ping_tests[helper.label] = list(set(ipv6_dataplane_addresses).difference(
                    self.passed_ipv6_dataplane_ping_tests[helper.label]))

    def run_tests(self, *, retry=3, retry_interval=10):
        from collections import namedtuple

        # self.run_ssh_test(retry=retry, retry_interval=retry_interval)

        if self.run_ping_test:
            self.run_dataplane_test(retry=retry, retry_interval=retry_interval)
        else:
            self.run_ssh_test(retry=retry, retry_interval=retry_interval)

        # if self.run_ipv6_ping_test:
        #     self.run_ipv6_dataplane_test(retry=retry, retry_interval=retry_interval)

        Node = namedtuple("Node", "host user key_file data_plane_address")
        JumpNode = namedtuple("Node", "host user key_file data_plane_address jump_host jump_user jump_key_file")

        node_info_list = []

        for n in self.nodes:
            if n.jump_user or n.jump_host or n.jump_keyfile:
                node_info_list.append(
                    {n.name: JumpNode(host=n.host,
                                       user=n.user,
                                       key_file=n.keyfile,
                                       data_plane_address=n.get_dataplane_address(),
                                       jump_host=n.jump_host,
                                       jump_user=n.jump_user,
                                       jump_key_file=n.jump_keyfile
                                       )
                     }
                )
            else:
                node_info_list.append({n.name: Node(host=n.host,
                                                     user=n.user,
                                                     key_file=n.keyfile,
                                                     data_plane_address=n.get_dataplane_address())})

        if self.run_ping_test or self.run_ipv6_ping_test:
            self.summary = {"SSH TEST SUMMARY": [
                {"nodes": node_info_list},
                {"passed_tests":
                    [
                        # {"passed_ssh_test": self.passed_ssh_test},
                        {"passed_ipv4_dataplane_ping_test": self.passed_dataplane_ping_tests}
                    ]},
                {"FAILED_VALIDATION": self.failed_validation},
                {"FAILED_TESTS":
                    [
                        # {"failed_ssh_test": self.failed_ssh_test},
                        {"failed_ipv4_dataplane_ping_test": [dict(src=k, destinations=v) for k, v in
                                                        self.failed_dataplane_ping_tests.items()]}
                    ]}
            ]}
        else:
            self.summary = {"SSH TEST SUMMARY": [
                {"nodes": node_info_list},
                {"passed_tests":
                    [
                        {"passed_ssh_test": self.passed_ssh_test}
                    ]},
                {"FAILED_VALIDATION": self.failed_validation},
                {"FAILED_TESTS":
                    [
                        {"failed_ssh_test": self.failed_ssh_test}
                    ]}
            ]}


class SshNodeHelper:
    # noinspection PyBroadException
    def __init__(self, *, node, label, host, user, private_key_file, jump_host=None, jump_user=None,
                 jump_private_key_file=None):
        self.node = node
        self.label = label
        self.host = host
        self.user = user
        self.jump_host = jump_host
        self.jump_user = jump_user
        self.client = None
        self.jump_client = None

        # noinspection PyBroadException
        try:
            self.key = paramiko.RSAKey.from_private_key_file(private_key_file)
        except Exception:
            self.key = paramiko.ecdsakey.ECDSAKey.from_private_key_file(private_key_file)

        if jump_private_key_file:
            try:
                self.jump_key = paramiko.RSAKey.from_private_key_file(jump_private_key_file)
            except Exception:
                self.jump_key = paramiko.ecdsakey.ECDSAKey.from_private_key_file(jump_private_key_file)

    def connect(self):
        if not self.jump_user:
            self.client = paramiko.SSHClient()
            # self.client.load_system_host_keys()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(self.host, username=self.user, pkey=self.key)
            return

        self.jump_client = paramiko.SSHClient()
        # self.jump_client.load_system_host_keys()
        self.jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.jump_client.connect(self.jump_host, username=self.jump_user, pkey=self.jump_key)

        transport = self.jump_client.get_transport()
        src_addr = (self.jump_host, 22)
        dest_addr = (self.host, 22)
        channel = transport.open_channel("direct-tcpip", dest_addr, src_addr)
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.host, username=self.user, pkey=self.key, sock=channel)

    # noinspection PyBroadException
    def close_quietly(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass

            self.client = None

        if self.jump_client:
            try:
                self.jump_client.close()
            except Exception:
                pass

            self.jump_client = None
