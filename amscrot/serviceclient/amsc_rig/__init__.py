"""AmSC Resource Interface Gateway (RIG) service client package.

Exposes :class:`RigServiceClient`, a discovery/factory client that enumerates
the IRI facilities fronted by an AmSC RIG and expands them into ordinary
``IriServiceClient`` instances.
"""

from amscrot.serviceclient.amsc_rig.ready_prober import (
    RigFacility,
    RigReadyDocument,
    RigReadyProber,
    parse_api_version,
)
from amscrot.serviceclient.amsc_rig.rig_service_client import RigServiceClient

__all__ = [
    "RigServiceClient",
    "RigReadyProber",
    "RigReadyDocument",
    "RigFacility",
    "parse_api_version",
]
