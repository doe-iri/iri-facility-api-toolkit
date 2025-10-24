import logging

import chi
import chi.lease
import paramiko


class LeaseHelper:
    def __init__(self, *, lease_name: str, logger: logging.Logger):
        self.lease_name = lease_name
        self.logger = logger
        self.lease = None

    def get_reservation_id(self):
        return self.lease["reservations"][0]["id"]

    def delete_lease(self):
        try:
            chi.lease.delete_lease(self.lease_name)
            self.logger.info(f"Deleted lease {self.lease_name}")
        except ValueError as ve:
            if "No leases found for name" not in str(ve):
                raise ve

        self.lease = None

    def create_lease_if_needed(self, *, reservations, retry):
        self.lease = None

        try:
            self.lease = chi.lease.get_lease(self.lease_name)
        except ValueError as ve:
            if "No leases found for name" not in str(ve):
                raise ve
        except Exception as e:
            self.logger.error(f"Error checking for lease {self.lease_name} {e}")
            raise e

        if self.lease:
            self.logger.info(f"Found lease {self.lease_name}: {self.lease['status']}")

            if self.lease["status"] == 'ACTIVE':
                return

            if self.lease["status"] == 'ERROR' or self.lease["status"] == 'TERMINATED':
                try:
                    self.delete_lease()
                    assert not self.lease
                except Exception as e:
                    self.logger.error(f"Error deleting lease {self.lease_name} with status=ERROR: {e}")
                    raise e

        if not self.lease:
            self.logger.info(f"Creating lease {self.lease_name}:{reservations}")
            chi.lease.create_lease(lease_name=self.lease_name, reservations=reservations)

        assert retry > 0

        from keystoneauth1.exceptions.connection import ConnectFailure

        for i in range(retry):
            try:
                chi.lease.wait_for_active(self.lease_name)
                self.lease = chi.lease.get_lease(self.lease_name)
                self.logger.debug(f"lease {self.lease}: status={self.lease['status']}")
                assert self.lease["status"] == 'ACTIVE'
                return
            except ConnectFailure as cf:
                self.logger.warning(f"Error while waiting for {self.lease_name}: tried={i + 1} {cf}")
            except TimeoutError as te:
                self.logger.warning(f"Error while waiting for {self.lease_name}: tried={i + 1} {te}")

        raise Exception(f'Was not able to create an active lease {self.lease_name}. Try again !!!!')


# noinspection PyBroadException
def get_paramiko_key(private_key_file: str, private_key_passphrase: str = None):
    if private_key_passphrase:
        try:
            return paramiko.RSAKey.from_private_key_file(private_key_file,
                                                         password=private_key_passphrase)
        except Exception:
            return paramiko.ecdsakey.ECDSAKey.from_private_key_file(private_key_file,
                                                                    password=private_key_passphrase)
    else:
        try:
            return paramiko.RSAKey.from_private_key_file(private_key_file)
        except Exception:
            return paramiko.ecdsakey.ECDSAKey.from_private_key_file(private_key_file)


class SshHelper:
    def __init__(self, host, user, key):
        self.host = host
        self.user = user
        self.key = key
        self.client = None
        self.ftp_client = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.host, username=self.user, pkey=self.key)

    def connect_ftp(self):
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.host, username=self.user, pkey=self.key)
        self.ftp_client = self.client.open_sftp()

    # noinspection PyBroadException
    def close_quietly(self):
        if self.ftp_client:
            try:
                self.ftp_client.close_quietly()
                self.ftp_client = None
            except Exception:
                pass

        if self.client:
            try:
                self.client.close_quietly()
                self.client = None
            except Exception:
                pass
