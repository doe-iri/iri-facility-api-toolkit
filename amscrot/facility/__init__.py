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
from amscrot.facility.async_client import AsyncFacilityClient
from amscrot.facility.models import Resource, Job
from amscrot.facility.async_models import AsyncResource, AsyncJob
from amscrot.facility.filesystem import FilesystemClient
from amscrot.facility.async_filesystem import AsyncFilesystemClient
from amscrot.facility.task import Task

__all__ = [
    "FacilityClient",
    "AsyncFacilityClient",
    "Resource",
    "AsyncResource",
    "Job",
    "AsyncJob",
    "FilesystemClient",
    "AsyncFilesystemClient",
    "Task",
]
