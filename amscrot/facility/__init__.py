"""High-level facility convenience API for AmSCROT.

Provides a Pythonic, minimal-boilerplate interface for IRI job submission::

    from amscrot.client import Client

    client = Client()
    facility = client.facility("https://api.alcf.anl.gov", token="...")
    job = facility.resource("Polaris").submit(
        executable="/bin/echo",
        nodes=1,
        queue="debug",
        account="datascience",
        duration=300,
    )
    job.wait()
"""

from amscrot.facility.client import FacilityClient
from amscrot.facility.models import Resource, Job
from amscrot.facility.filesystem import FilesystemClient
from amscrot.facility.task import Task
from amscrot.model.metadata import Incident, StatusEvent

__all__ = [
    "FacilityClient",
    "Resource",
    "Job",
    "FilesystemClient",
    "Task",
    "Incident",
    "StatusEvent",
]
