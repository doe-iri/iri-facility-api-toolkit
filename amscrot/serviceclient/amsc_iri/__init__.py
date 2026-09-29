"""IRI service client -- transparent version-dispatching factory.

Consumer code creates ``IriServiceClient(name=..., credential=...)`` exactly
as before.  The factory inspects the ``api_version`` credential field (or
auto-probes the endpoint) and returns an instance of the correct versioned
implementation:

* :class:`._v1.IriServiceClientV1` -- for v1 endpoints (``amsc_iri``)
* :class:`._v2.IriServiceClientV2` -- for v2 endpoints (``amsc_iri_v2``)

The :class:`._base.IriServiceClientBase` base class and the
:class:`.version_prober.VersionProber` are also re-exported for advanced use.
"""

from amscrot.serviceclient.amsc_iri.iri_service_client import IriServiceClientBase
from amscrot.serviceclient.amsc_iri.version_prober import VersionProber

# Default API version when probing fails and no override is provided.
_DEFAULT_API_VERSION = 1


def _resolve_version_from_kwargs(kwargs: dict) -> int:
    """Determine the API version before creating the client.

    Resolution order:
    1. ``api_version`` key in credential dict/object -> use directly.
    2. ``api_version`` in credentials.yml section -> use directly.
    3. VersionProber auto-detection against the endpoint.
    4. Fallback to ``_DEFAULT_API_VERSION``.
    """
    import os
    import yaml
    from pathlib import Path
    from amscrot.util import utils

    logger = utils.get_logger()

    # -- 0. Check direct kwarg ---------------------------------------------
    direct_av = kwargs.get('api_version')
    if direct_av is not None:
        return int(direct_av)

    # -- 1. Check credential object (dict or has .to_dict) -----------------
    credential = kwargs.get('credential')
    if credential:
        creds = {}
        if hasattr(credential, 'to_dict'):
            creds = credential.to_dict()
        elif isinstance(credential, dict):
            creds = credential

        av = creds.get('api_version')
        if av is not None:
            return int(av)

        # We have an endpoint for probing
        api_endpoint = creds.get('api_endpoint')
        api_key = creds.get('api_key')
        if not api_key and creds.get('pat_file'):
            api_key = utils.load_pat_from_file(creds.get('pat_file'))
        if api_endpoint:
            return _probe_version(api_endpoint, api_key, logger)

    # -- 2. Check credentials.yml ------------------------------------------
    from amscrot.util.constants import Constants

    profile = kwargs.get('profile')
    name = kwargs.get('name')
    credential_file = kwargs.get('credential_file')
    default_file = os.path.join(str(Path.home()), '.amscrot', 'credentials.yml')
    cred_file = credential_file or default_file
    cred_file = os.path.expanduser(cred_file)

    if os.path.exists(cred_file):
        try:
            with open(cred_file, 'r') as f:
                credentials = yaml.safe_load(f) or {}

            lookups = []
            if profile:
                lookups.append(profile)
            if name and name not in lookups:
                lookups.append(name)
            lookups.append(Constants.ServiceType.IRI)

            for key in lookups:
                if key in credentials:
                    section = credentials[key]
                    av = section.get('api_version')
                    if av is not None:
                        return int(av)

                    api_endpoint = section.get('api_endpoint')
                    api_key = section.get('api_key')
                    if not api_key and section.get('pat_file'):
                        api_key = utils.load_pat_from_file(section.get('pat_file'))
                    if api_endpoint:
                        return _probe_version(api_endpoint, api_key, logger)
                    break
        except Exception:
            pass

    # -- 3. Check endpoint_uri kwarg (from ServiceClient init) ----
    endpoint_uri = kwargs.get('endpoint_uri')
    if endpoint_uri:
        return _probe_version(endpoint_uri, None, logger)

    # -- 4. Fallback -------------------------------------------------------
    return _DEFAULT_API_VERSION


# Shared prober instance (avoids re-creating for each client)
_prober: VersionProber = None


def _probe_version(api_endpoint: str, api_key: str, logger) -> int:
    """Use VersionProber to detect the endpoint's API version."""
    global _prober
    try:
        if _prober is None:
            _prober = VersionProber()
        return _prober.detect_version(api_endpoint, api_key=api_key)
    except Exception as exc:
        logger.warning(
            f"[IriServiceClient] Version probing failed for "
            f"{api_endpoint}: {exc}; falling back to v{_DEFAULT_API_VERSION}"
        )
        return _DEFAULT_API_VERSION


class IriServiceClient:
    """Factory that creates the correct versioned IRI service client.

    Usage is identical to the previous monolithic class::

        client = IriServiceClient(name="nersc", credential=cred)
        # Returns IriServiceClientV1 or IriServiceClientV2

    The returned object is a subclass of :class:`IriServiceClientBase`
    (and therefore :class:`ServiceClient`), so ``isinstance(client,
    IriServiceClientBase)`` is ``True``.
    """

    def __new__(cls, **kwargs):
        version = _resolve_version_from_kwargs(kwargs)

        if version >= 2:
            from amscrot.serviceclient.amsc_iri._v2 import IriServiceClientV2
            return IriServiceClientV2(**kwargs)
        else:
            from amscrot.serviceclient.amsc_iri._v1 import IriServiceClientV1
            return IriServiceClientV1(**kwargs)
