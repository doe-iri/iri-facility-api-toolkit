"""AmSC RIG ``/ready`` discovery and caching.

The AmSC Resource Interface Gateway (RIG) exposes a single authenticated
``/ready`` endpoint that enumerates every IRI facility it fronts, along with
each facility's API version and metadata path.  This module fetches that
document and caches it on disk so repeated toolkit invocations do not re-query
the gateway.

Usage::

    prober = RigReadyProber()
    doc = prober.fetch("https://rig.staging.american-science-cloud.org",
                       api_key=token)
    for fac in doc.facilities:
        print(fac.name, fac.api_version, fac.base_url(doc.base_url))
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from amscrot.util import utils
from amscrot.util.constants import Constants

logger = utils.get_logger()

#: Default time-to-live for a cached ``/ready`` document (1 hour).
DEFAULT_TTL_SECONDS = 60 * 60

#: Default per-request connect/read timeout in seconds.
DEFAULT_TIMEOUT = 10.0


def _cache_path() -> Path:
    """Return the resolved path to the RIG ready-cache file."""
    return Path.home() / ".amscrot" / Constants.RIG_READY_CACHE_FILE


def parse_api_version(value: Any, *, default: int = 1) -> int:
    """Coerce a RIG ``api_version`` field into an integer.

    The gateway reports versions as strings like ``"v1"`` / ``"v2"``, but
    tolerate bare integers and numeric strings too.

    Args:
        value: Raw value from the ``/ready`` payload.
        default: Returned when *value* cannot be interpreted.

    Returns:
        The integer API version.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip().lower().lstrip("v")
    try:
        return int(text)
    except (TypeError, ValueError):
        logger.warning(
            f"[RigReadyProber] Unrecognized api_version {value!r}; "
            f"defaulting to v{default}"
        )
        return default


@dataclass
class RigFacility:
    """A single IRI facility advertised by the RIG ``/ready`` endpoint."""

    name: str
    api_version: int = 1
    tier: Optional[int] = None
    metadata_path: Optional[str] = None
    probe_path: Optional[str] = None
    display_url: Optional[str] = None
    health_monitored: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RigFacility":
        """Build a :class:`RigFacility` from one ``/ready`` facility entry."""
        return cls(
            name=data.get("name") or "",
            api_version=parse_api_version(data.get("api_version")),
            tier=data.get("tier"),
            metadata_path=data.get("metadata_path"),
            probe_path=data.get("probe_path"),
            display_url=data.get("display_url"),
            health_monitored=bool(data.get("health_monitored")),
            raw=dict(data),
        )

    def base_url(self, rig_base_url: str) -> str:
        """Return this facility's IRI API base URL behind the RIG proxy.

        The standard IRI paths (``/api/vN/...``) hang directly off this URL,
        so it can be handed to a normal ``IriServiceClient`` as its
        ``api_endpoint``.
        """
        root = rig_base_url.rstrip("/")
        return f"{root}{Constants.RIG_EXTERNAL_PATH}/{self.name}"

    @property
    def expected_metadata_path(self) -> str:
        """The ``metadata_path`` a standard IRI facility would advertise."""
        return f"/api/v{self.api_version}/facility"

    @property
    def path_style(self) -> str:
        """Return ``"standard"`` or ``"bare"`` based on the advertised path.

        The generated ``amsc_iri`` / ``amsc_iri_v2`` bindings hardcode
        ``/api/vN/...`` resource paths.  A facility that advertises a bare
        ``/vN/...`` prefix (as ``pnnl`` currently does) is incompatible with
        those bindings and is reported as ``"bare"`` so callers can skip it
        rather than build a client that 404s on every request.
        """
        if not self.metadata_path:
            # Nothing advertised -- assume the conventional layout.
            return "standard"
        if self.metadata_path.startswith(f"/api/v{self.api_version}"):
            return "standard"
        if self.metadata_path.startswith("/api/"):
            return "standard"
        return "bare"

    @property
    def is_standard_path(self) -> bool:
        """True when the facility uses the conventional ``/api/vN`` prefix."""
        return self.path_style == "standard"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for discovery payloads."""
        return {
            "name": self.name,
            "api_version": self.api_version,
            "tier": self.tier,
            "metadata_path": self.metadata_path,
            "probe_path": self.probe_path,
            "display_url": self.display_url,
            "health_monitored": self.health_monitored,
            "path_style": self.path_style,
        }


@dataclass
class RigReadyDocument:
    """Parsed ``/ready`` response from a RIG endpoint."""

    base_url: str
    status: Optional[str] = None
    active_roles: List[str] = field(default_factory=list)
    facilities: List[RigFacility] = field(default_factory=list)
    hub: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, base_url: str, data: Dict[str, Any]) -> "RigReadyDocument":
        """Build a :class:`RigReadyDocument` from a raw ``/ready`` payload."""
        raw_facilities = data.get("facilities") or []
        facilities = [
            RigFacility.from_dict(item)
            for item in raw_facilities
            if isinstance(item, dict) and item.get("name")
        ]
        return cls(
            base_url=base_url.rstrip("/"),
            status=data.get("status"),
            active_roles=list(data.get("active_roles") or []),
            facilities=facilities,
            hub=dict(data.get("hub") or {}),
            raw=dict(data),
        )

    @property
    def is_ready(self) -> bool:
        """True when the gateway reports itself ready."""
        return (self.status or "").lower() == "ready"

    def facility(self, name: str) -> Optional[RigFacility]:
        """Look up a facility by exact name."""
        for fac in self.facilities:
            if fac.name == name:
                return fac
        return None


class RigReadyProber:
    """Fetch and cache the RIG ``/ready`` facility listing.

    Results are persisted to ``~/.amscrot/metadata/rig_ready_cache.json``
    keyed by gateway base URL, mirroring the TTL/``force`` conventions
    already established by
    :class:`~amscrot.serviceclient.amsc_iri.version_prober.VersionProber`.

    Args:
        ttl_seconds: How long a cached entry stays fresh.
        timeout: Per-request connect+read timeout in seconds.
        verify: Whether to verify TLS certificates.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        timeout: float = DEFAULT_TIMEOUT,
        verify: bool = True,
    ) -> None:
        self._ttl = ttl_seconds
        self._timeout = timeout
        self._verify = verify
        self._cache: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        force: bool = False,
    ) -> Optional[RigReadyDocument]:
        """Return the gateway's ``/ready`` document, or ``None`` on failure.

        Args:
            base_url: RIG base URL, e.g.
                ``https://rig.staging.american-science-cloud.org``.
            api_key: AmSC PAT used as a bearer token.
            force: Bypass the cache and always query live.

        Returns:
            A :class:`RigReadyDocument`, or ``None`` if the gateway could not
            be reached and no usable cache entry exists.
        """
        base_url = (base_url or "").rstrip("/")
        if not base_url:
            logger.warning("[RigReadyProber] No base_url provided.")
            return None

        if not force:
            cached = self._get_cached(base_url)
            if cached is not None:
                logger.debug(f"[RigReadyProber] Using cached /ready for {base_url}")
                return RigReadyDocument.from_dict(base_url, cached)

        payload = self._request_ready(base_url, api_key=api_key)
        if payload is None:
            # Fall back to a stale cache entry rather than returning nothing.
            stale = self._get_cached(base_url, ignore_ttl=True)
            if stale is not None:
                logger.warning(
                    f"[RigReadyProber] Live /ready failed for {base_url}; "
                    "falling back to stale cache."
                )
                return RigReadyDocument.from_dict(base_url, stale)
            return None

        self._set_cached(base_url, payload)
        doc = RigReadyDocument.from_dict(base_url, payload)
        logger.info(
            f"[RigReadyProber] {base_url} status={doc.status} "
            f"facilities={len(doc.facilities)}"
        )
        return doc

    def clear_cache(self, base_url: Optional[str] = None) -> None:
        """Remove one or all entries from the ready cache."""
        if base_url is None:
            self._cache = {}
        else:
            cache = self._load_cache()
            cache.pop(base_url.rstrip("/"), None)
            self._cache = cache
        self._save_cache()

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _request_ready(
        self, base_url: str, *, api_key: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Issue ``GET <base_url>/ready`` and return the decoded payload."""
        url = f"{base_url}{Constants.RIG_READY_PATH}"
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            import requests

            resp = requests.get(
                url, headers=headers, timeout=self._timeout, verify=self._verify
            )
        except Exception as exc:
            logger.warning(f"[RigReadyProber] GET {url} failed: {exc}")
            return None

        if resp.status_code == 401:
            logger.error(
                f"[RigReadyProber] GET {url} -> 401 Unauthorized. "
                "Check the AmSC PAT (api_key / pat_file)."
            )
            return None
        if resp.status_code != 200:
            logger.warning(
                f"[RigReadyProber] GET {url} -> HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
            return None

        try:
            payload = resp.json()
        except ValueError as exc:
            logger.warning(f"[RigReadyProber] GET {url} returned non-JSON: {exc}")
            return None

        if not isinstance(payload, dict):
            logger.warning(
                f"[RigReadyProber] GET {url} returned unexpected payload type "
                f"{type(payload).__name__}"
            )
            return None

        return payload

    # ------------------------------------------------------------------
    # Cache I/O
    # ------------------------------------------------------------------

    def _load_cache(self) -> Dict[str, Any]:
        """Load the cache from disk, returning an empty dict on any error."""
        if self._cache is not None:
            return self._cache

        path = _cache_path()
        if not path.exists():
            self._cache = {}
            return self._cache

        try:
            with path.open("r", encoding="utf-8") as fh:
                self._cache = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"[RigReadyProber] Could not read cache at {path}: {exc}")
            self._cache = {}

        if not isinstance(self._cache, dict):
            self._cache = {}

        return self._cache

    def _save_cache(self) -> None:
        """Persist the in-memory cache to disk."""
        path = _cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as fh:
                json.dump(self._cache or {}, fh, indent=2)
        except OSError as exc:
            logger.warning(f"[RigReadyProber] Could not write cache to {path}: {exc}")

    def _get_cached(
        self, base_url: str, *, ignore_ttl: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Return the cached payload if present and fresh, else ``None``."""
        cache = self._load_cache()
        entry = cache.get(base_url)
        if not entry:
            return None

        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return None

        if ignore_ttl:
            return payload

        fetched_at = entry.get("fetched_at", 0)
        if isinstance(fetched_at, str):
            try:
                fetched_at = datetime.fromisoformat(
                    fetched_at.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                fetched_at = 0

        age = time.time() - fetched_at
        if age > self._ttl:
            logger.debug(
                f"[RigReadyProber] Cache entry for {base_url} expired "
                f"({age:.0f}s > {self._ttl}s TTL)"
            )
            return None

        return payload

    def _set_cached(self, base_url: str, payload: Dict[str, Any]) -> None:
        """Write an entry to the in-memory cache and persist it."""
        cache = self._load_cache()
        cache[base_url] = {
            "payload": payload,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": self._ttl,
        }
        self._cache = cache
        self._save_cache()
