"""IRI API version discovery and caching.

Probes IRI facility endpoints to determine the highest supported API version,
and caches the results on disk so subsequent toolkit invocations skip the probe.

Usage::

    prober = VersionProber()

    # Auto-detect (checks cache first, probes on miss/stale)
    version = prober.detect_version("https://iri-dev.ppg.es.net")

    # Force a fresh probe (ignores cache)
    version = prober.detect_version("https://iri-dev.ppg.es.net", force=True)

    # Inspect / clear the cache
    prober.clear_cache()
    prober.clear_cache("https://iri-dev.ppg.es.net")
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from amscrot.util import utils

logger = utils.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Versions to probe, ordered highest-first.  The prober returns the
#: first version whose ``/api/vN/openapi.json`` endpoint returns HTTP 200.
PROBE_VERSIONS = [2, 1]

#: Relative path template appended to the base URL.
PROBE_PATH_TEMPLATE = "/api/v{version}/openapi.json"

#: Default time-to-live for cached entries (7 days in seconds).
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 604 800

#: Cache file location under ``~/.amscrot/metadata/``.
CACHE_FILENAME = "iri_version_cache.json"


def _cache_path() -> Path:
    """Return the resolved path to the version cache file."""
    return Path.home() / ".amscrot" / "metadata" / CACHE_FILENAME


# ---------------------------------------------------------------------------
# VersionProber
# ---------------------------------------------------------------------------

class VersionProber:
    """Discover and cache the highest IRI API version supported by an endpoint.

    The prober issues lightweight HTTP requests to each candidate version's
    ``openapi.json`` endpoint (highest first) using :mod:`urllib3`, which is
    already a transitive dependency of the ``amsc_iri`` generated client.

    Results are persisted to ``~/.amscrot/metadata/iri_version_cache.json``
    with a configurable TTL so that normal toolkit usage never re-probes
    unless the cache has expired.

    Args:
        ttl_seconds: How long a cached entry is considered fresh.
            Defaults to :data:`DEFAULT_TTL_SECONDS` (7 days).
        probe_versions: Ordered list of version integers to try.
            Defaults to :data:`PROBE_VERSIONS` ``[2, 1]``.
        timeout: Per-request connect+read timeout in seconds.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        probe_versions: list[int] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._ttl = ttl_seconds
        self._versions = probe_versions or list(PROBE_VERSIONS)
        self._timeout = timeout
        self._cache: Dict[str, Any] | None = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_version(
        self,
        base_url: str,
        *,
        force: bool = False,
        api_key: str | None = None,
    ) -> int:
        """Return the highest IRI API version supported by *base_url*.

        1. If *force* is ``False`` (default), check the on-disk cache first.
        2. On cache miss or stale entry, probe the endpoint live.
        3. Cache the result for future calls.
        4. If all probes fail, fall back to ``1``.

        Args:
            base_url: The IRI facility base URL (e.g.
                ``https://iri-dev.ppg.es.net``).  Trailing slashes are
                stripped automatically.
            force: Skip the cache and always probe live.
            api_key: Optional Bearer token to include in probe requests
                (some endpoints may require authentication even for the
                OpenAPI spec).

        Returns:
            Integer API version (e.g. ``1`` or ``2``).
        """
        base_url = base_url.rstrip("/")

        if not force:
            cached = self._get_cached(base_url)
            if cached is not None:
                logger.debug(
                    f"[VersionProber] Using cached API version {cached} "
                    f"for {base_url}"
                )
                return cached

        version = self._probe(base_url, api_key=api_key)
        self._set_cached(base_url, version)
        logger.info(
            f"[VersionProber] Detected API version {version} for {base_url}"
        )
        return version

    def clear_cache(self, base_url: str | None = None) -> None:
        """Remove one or all entries from the version cache.

        Args:
            base_url: If given, only remove the entry for this URL.
                If ``None``, clear the entire cache.
        """
        if base_url is None:
            self._cache = {}
        else:
            cache = self._load_cache()
            cache.pop(base_url.rstrip("/"), None)
            self._cache = cache
        self._save_cache()

    def get_cached_version(self, base_url: str) -> Optional[int]:
        """Return the cached version for *base_url*, or ``None`` if absent/stale."""
        return self._get_cached(base_url.rstrip("/"))

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    def _probe(self, base_url: str, *, api_key: str | None = None) -> int:
        """Issue HTTP requests to find the highest supported version.

        Tries each version in :attr:`_versions` (highest first).  The first
        one that returns HTTP 200 wins.  Falls back to ``1`` if all fail.
        """
        import urllib3

        # Disable SSL warnings for probing (some dev endpoints use self-signed certs)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        http = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=self._timeout, read=self._timeout),
            cert_reqs="CERT_NONE",
        )

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for version in self._versions:
            probe_url = base_url + PROBE_PATH_TEMPLATE.format(version=version)
            try:
                resp = http.request("GET", probe_url, headers=headers)
                logger.debug(
                    f"[VersionProber] Probe {probe_url} -> HTTP {resp.status}"
                )
                if resp.status == 200:
                    return version
            except Exception as exc:
                logger.debug(
                    f"[VersionProber] Probe {probe_url} failed: {exc}"
                )

        logger.warning(
            f"[VersionProber] All probes failed for {base_url}; "
            f"falling back to v{self._versions[-1]}"
        )
        return self._versions[-1]  # lowest version as fallback

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
            logger.warning(
                f"[VersionProber] Could not read cache at {path}: {exc}"
            )
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
            logger.warning(
                f"[VersionProber] Could not write cache to {path}: {exc}"
            )

    def _get_cached(self, base_url: str) -> Optional[int]:
        """Return the cached version if present and fresh, else ``None``."""
        cache = self._load_cache()
        entry = cache.get(base_url)
        if not entry:
            return None

        probed_at = entry.get("probed_at", 0)
        if isinstance(probed_at, str):
            try:
                probed_at = datetime.fromisoformat(
                    probed_at.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                probed_at = 0

        age = time.time() - probed_at
        if age > self._ttl:
            logger.debug(
                f"[VersionProber] Cache entry for {base_url} expired "
                f"({age:.0f}s > {self._ttl}s TTL)"
            )
            return None

        return entry.get("api_version")

    def _set_cached(self, base_url: str, version: int) -> None:
        """Write an entry to the in-memory cache and persist."""
        cache = self._load_cache()
        cache[base_url] = {
            "api_version": version,
            "probed_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": self._ttl,
        }
        self._cache = cache
        self._save_cache()
