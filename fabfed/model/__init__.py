from abc import ABC, abstractmethod
from collections import namedtuple
from fabfed.util.utils import get_inventory_dir, get_ssh_dir
from typing import List

class Resource(ABC):
    def __init__(self, label, name: str):
        self.label = label
        self.name = name
        self._depends_on: List[str] = list()

    def get_label(self) -> str:
        return self.label

    def get_name(self) -> str:
        return self.name

    def set_externally_depends_on(self, depends_on: List[str]):
        self._depends_on = depends_on

    def get_externally_depends_on(self) -> List[str]:
        return self._depends_on

    @abstractmethod
    def write_ansible(self, friendly_name):
        pass


class SSHNode():
    def __init__(self, user: str, host: str, keyfile: str,
                 jump_user: str = None, jump_host: str = None, jump_keyfile=None):
        self.user = user
        self.host = host
        self.keyfile = keyfile
        self.jump_user = jump_user
        self.jump_host = jump_host
        self.jump_keyfile = jump_keyfile

    @property
    def sshcmd_str(self) -> str:
        if self.jump_host and self.jump_user:
            return f"ssh {self.user}@{self.host} -J {self.jump_user}@{self.jump_host}"
        else:
            return f"ssh {self.user}@{self.host} -i {self.keyfile}"

    @property
    def proxyjump_str(self) -> str:
        if self.jump_host and self.jump_user and self.jump_keyfile:
            return f"-o ProxyJump=\"{self.jump_user}@{self.jump_host}\""
        return ""

    def write_ansible(self, friendly_name, delete=False):
        import os
        file_path = os.path.join(get_inventory_dir(friendly_name), f"{self.name}")
        ssh_config = None
        proxyjump_str = self.proxyjump_str

        if proxyjump_str:
            ssh_config = os.path.join(get_ssh_dir(friendly_name), f"ssh_config_{self.name}")
            proxyjump_str = f"-F {ssh_config} {self.proxyjump_str}"

        if delete:
            try:
                os.unlink(file_path)
            except:
                pass

            if ssh_config:
                try:
                    os.unlink(ssh_config)
                except:
                    pass
            return
        dplane_addr = self.get_dataplane_address()
        if not dplane_addr:
            dplane_addr = self.host
        hosts =f"""[{self.name}]

{self.host}
[{self.name}:vars]
ansible_connection=ssh
ansible_ssh_common_args={proxyjump_str}
ansible_ssh_private_key_file={self.keyfile}
ansible_user={self.user}
node={dplane_addr}
name={self.name}
"""
        with open(file_path, "w") as stream:
            try:
                stream.write(hosts)
            except Exception as e:
                from fabfed.exceptions import AnsibleException
                raise AnsibleException(f'Exception while saving ansible inventory at {file_path}:{e}')

        ssh_config_content = f"""
UserKnownHostsFile /dev/null
StrictHostKeyChecking no
ServerAliveInterval 120

Host {self.jump_host}
     ForwardAgent yes
     Hostname %h
     IdentityFile  {self.jump_keyfile}
     IdentitiesOnly yes
"""
        if not ssh_config:
            return

        with open(ssh_config, "w") as stream:
            try:
                stream.write(ssh_config_content)
            except Exception as e:
                from fabfed.exceptions import AnsibleException
                raise AnsibleException(f'Exception while saving ansible inventory at {file_path}:{e}')

class Node(Resource,SSHNode):
    def __init__(self, *, label, name: str, image: str, site: str, flavor: str):
        super().__init__(label, name)
        SSHNode.__init__(self, user=None, host=None, keyfile=None)
        self.image = image
        self.site = site
        self.flavor = flavor
        self.mgmt_ip = None

    def get_site(self) -> str:
        return self.site

    def get_flavor(self) -> dict or str:
        return self.flavor

    def get_image(self) -> str:
        return self.image

    def get_management_ip(self) -> str:
        return self.mgmt_ip

    @abstractmethod
    def get_reservation_state(self) -> str:
        pass

    @abstractmethod
    def get_reservation_id(self) -> str:
        pass

    @abstractmethod
    def add_route(self, subnet, gateway):
        pass

    @abstractmethod
    def get_dataplane_address(self, network=None, interface=None, af=None):
        pass

    def write_ansible(self, friendly_name, delete=False):
        SSHNode.write_ansible(self, friendly_name, delete)


class Network(Resource):
    def __init__(self, *, label, name: str, site: str):
        super().__init__(label, name)
        self.site = site

    def get_site(self) -> str:
        return self.site

    def get_reservation_id(self):
        pass

    def write_ansible(self, friendly_name, delete=False):
        pass

class Service(Resource):
    def __init__(self, *, label, name: str):
        super().__init__(label, name)

    def write_ansible(self, friendly_name, delete=False):
        pass

ResolvedDependency = namedtuple("ResolvedDependency", "resource_label attr value")
