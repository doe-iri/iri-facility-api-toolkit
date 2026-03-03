"""
AmscrotBaseOperator -- base class that creates an amscrot Client + Session.

The Session is created fresh in each execute() call (Airflow spawns a new
process per task). State is carried between tasks via XCom, not in-process
memory. All service-client lifecycle happens within a single Session that
is scoped to the lifetime of execute().
"""
from __future__ import annotations

from airflow.models import BaseOperator
from amscrot.client.client import Client
from amscrot.client.models import Session


class AmscrotBaseOperator(BaseOperator):
    """Base operator that wires up an amscrot Client and Session.

    Parameters
    ----------
    session_name:
        Name for the amscrot Session. Determines the local storage path
        at ``~/.amscrot/sessions/<session_name>/``.
    service_type:
        One of the ``Constants.ServiceType`` values, e.g. ``"esnet-iri"``.
    service_name:
        Label for this service client instance.
    profile:
        Credential profile name in ``~/.amscrot/credentials.yml``.
    credential_file:
        Path to the credentials file. Defaults to ``~/.amscrot/credentials.yml``.
    """

    template_fields = ("profile", "session_name")

    def __init__(
        self,
        *,
        session_name: str,
        service_type: str,
        service_name: str,
        profile: str,
        credential_file: str = "~/.amscrot/credentials.yml",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session_name = session_name
        self.service_type = service_type
        self.service_name = service_name
        self.profile = profile
        self.credential_file = credential_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_session(self) -> tuple[Session, object]:
        """Create a Client + Session + ServiceClient for this task.

        Returns (session, service_client).
        """
        from amscrot.serviceclient import ServiceClient

        client = Client()
        session = client.create_session(self.session_name)
        sc = ServiceClient.create(
            type=self.service_type,
            name=self.service_name,
            profile=self.profile,
            credential_file=self.credential_file,
        )
        session.add_service_client(sc)
        return session, sc

    def execute(self, context):
        raise NotImplementedError("Subclasses must implement execute()")
