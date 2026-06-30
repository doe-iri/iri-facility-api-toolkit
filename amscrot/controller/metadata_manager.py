import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
import os

from amscrot.util.utils import get_logger
from amscrot.util.constants import Constants

logger = get_logger()


@dataclass(frozen=True)
class MetadataConfig:
    """
    Metadata manager configuration.
    """
    metadata_id: Optional[str]
    local_base_dir: Path
    local_file_ext: str = "json"
    remote_domain: str = "WORKSPACE"

    @property
    def local_metadata_path(self) -> Optional[Tuple[Path, float]]:
        """
        Returns (path, mtime) as follows:
        1- If metadata_id is given, return that file.
        2- If not: return the most updated metadata file in the local cache directory.
        3- If no file exists, return None.
        """
        base_dir = self.local_base_dir
        ext = (self.local_file_ext or "json").lstrip(".")
        pattern = f"*.{ext}"

        try:
            if not base_dir.exists() or not base_dir.is_dir():
                return None
            if self.metadata_id is not None:  # if the exact cached metadata is requested
                record = self.local_base_dir / f"{self.metadata_id}.{self.local_file_ext}"
                if not record.exists():
                    return None
                return record, record.stat().st_mtime

            else:  # bring all the cached files with their modification time and return the most recent one
                newest = max(
                    (p for p in base_dir.glob(pattern) if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    default=None,
                )
                if newest is None:
                    return None

                mod_ts = newest.stat().st_mtime
                return newest, mod_ts
        except OSError:
            # If we can't access the directory or stat files, fall back to "no local metadata".
            return None


class MetadataManager:
    """
    Retrieve metadata from either local cache or a remote metadata service.
    """

    def __init__(self, config_metadata: Optional[Dict[str, Any]], metadata_fetch_mode: str, metadata_id: Optional[str]):
        self.metadata_fetch_mode = metadata_fetch_mode
        self.config = self._build_config(config_metadata=config_metadata or {}, metadata_id=metadata_id)

    @classmethod
    def fetch(
        cls,
        *,
        metadata_fetch_mode: str = "local|remote",
        metadata_id: Optional[str] = None,
        config_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Convenience helper used by ServiceClient.discover().

        Returns:
            Metadata dict if found; otherwise None.
        """
        mgr = cls(config_metadata=config_metadata, metadata_fetch_mode=metadata_fetch_mode, metadata_id=metadata_id)
        return mgr.get_metadata()

    def _build_config(self, *, config_metadata: Dict[str, Any], metadata_id: Optional[str]) -> MetadataConfig:
        """
        Build and normalize metadata configuration and ensure local directories exist.
        """
        base_dir = Path.home() / ".amscrot" / Constants.METADATA_BASE_DIR
        base_dir.mkdir(parents=True, exist_ok=True)

        remote_domain = str(config_metadata.get("remote_domain", "WORKSPACE"))

        return MetadataConfig(
            metadata_id=(str(metadata_id) if metadata_id is not None else None),
            local_base_dir=base_dir,
            local_file_ext=str(config_metadata.get("local_file_ext", "json")),
            remote_domain=remote_domain,
        )

    def _get_local_metadata(self) -> Optional[Tuple[Dict[str, Any], float]]:
        """
        Load metadata from the local cache file.
        """
        result = self.config.local_metadata_path
        if result is None:
            logger.info(f"No local metadata file(s) found in {self.config.local_base_dir}")
            return None
        path, mod_ts = result
        if path is None or not path.exists():
            logger.info(f"Local metadata not found at {path}")
            return None

        try:
            with path.open("r", encoding="utf-8") as fp:
                return json.load(fp), mod_ts
        except json.JSONDecodeError as e:
            logger.warning(f"Local metadata file is not valid JSON: {path}: {e}")
            return None
        except OSError as e:
            logger.warning(f"Unable to read local metadata file: {path}: {e}")
            return None

    def _to_st_mtime(self, s: str) -> float:
        """
        Parse a datetime string and return its UTC timestamp.
        Supports multiple common formats.
        """
        s = s.strip()
        formats = [
            '%Y-%m-%d %H:%M:%S %Z',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S.%f',
        ]

        for fmt in formats:
            try:
                if fmt.endswith('%z') or fmt.endswith('Z'):
                    dt = datetime.strptime(s, fmt)
                else:
                    val = s[:-1] if s.endswith('Z') else s
                    dt = datetime.strptime(val, fmt)

                if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue

        try:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass

        logger.warning(f"Unable to parse datetime string: '{s}'. Defaulting to epoch.")
        return 0.0

    def _get_remote_metadata(self) -> Optional[Tuple[Dict[str, Any], float]]:
        """
        Fetch metadata from the remote repository using SENSE-O `MetadataApi()`.

        Returns dict when found and valid; otherwise None (e.g., records not found)
                (metadata object, mtime) as follows.
            1- if metadata_id is given, return that remote case metadata object
            2- if not:  return the most updated metadata object in remote cache under specified domain
            3- if no metadata object, return None
        """
        if not os.getenv("HOME"):
            os.environ["HOME"] = str(Path.home())

        try:
            from sense.client.metadata_api import MetadataApi
        except ImportError as e:
            logger.warning(f"SENSE-O client library not available: {e}")
            return None

        # Preflight: the SENSE-O client expects an auth config file.
        auth_path = Path.home() / ".sense-o-auth.yaml"
        if not auth_path.exists():
            raise FileNotFoundError(
                f"SENSE-O auth config not found at '{auth_path}'. "
                "Remote metadata fetch expects the SENSE-O client default configuration."
            )

        metadata_api = MetadataApi()

        try:
            if self.config.metadata_id is not None:
                latest_record = metadata_api.get_metadata(
                    domain=self.config.remote_domain,
                    name=self.config.metadata_id,
                    full=True
                )
            else:
                records = metadata_api.get_metadata(domain=self.config.remote_domain)

                if not records:
                    logger.info("No remote metadata records found")
                    return None

                latest_record = max(
                    (record for record in records if record and record.get("edited")),
                    key=lambda d: self._to_st_mtime(d["edited"]),
                    default=None
                )

            if latest_record is None:
                logger.info("No remote metadata record found")
                return None

            # Determine the edited timestamp
            if isinstance(latest_record, dict) and "edited" in latest_record:
                latest_record_mtime = self._to_st_mtime(latest_record["edited"])
            else:
                latest_record_mtime = datetime.now(timezone.utc).timestamp()

        except ValueError as e:
            logger.info(f"Remote metadata not found: {e}")
            return None

        # Extract payload from the record
        payload = latest_record.get("data") if isinstance(latest_record, dict) else latest_record

        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as e:
                raise ValueError(f"Remote metadata payload returned a string but not valid JSON: {e}") from e
            if not isinstance(parsed, dict):
                raise TypeError(f"Unexpected remote metadata payload JSON type: {type(parsed)}")
            return parsed, latest_record_mtime

        if not isinstance(payload, dict):
            raise TypeError(f"Unexpected remote metadata type: {type(payload)}")

        return payload, latest_record_mtime

    def get_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve metadata based on the configured location fetch_mode.
        """
        fetch_mode = (self.metadata_fetch_mode or "").strip().lower()

        if fetch_mode not in {"local", "remote", "local|remote"}:
            raise ValueError("Invalid metadata fetch_mode. Expected: 'local', 'remote', 'local|remote'")

        metadata: Optional[Dict[str, Any]] = None

        if fetch_mode == "local":
            result = self._get_local_metadata()
            if result is not None:
                metadata, _ = result
            return metadata
        elif fetch_mode == "remote":
            result = self._get_remote_metadata()
            if result is not None:
                metadata, _ = result
            return metadata

        elif fetch_mode == "local|remote":
            try:
                result_l = self._get_local_metadata()
            except Exception as e:
                logger.warning(f"Failed to fetch local metadata: {e}")
                result_l = None

            try:
                result_r = self._get_remote_metadata()
            except Exception as e:
                logger.warning(f"Failed to fetch remote metadata: {e}")
                result_r = None

            metadata_l, mod_ts_l = result_l if result_l is not None else (None, None)
            metadata_r, mod_ts_r = result_r if result_r is not None else (None, None)

            if metadata_l is not None and metadata_r is not None:
                if mod_ts_l > mod_ts_r:
                    metadata = metadata_l
                    logger.info("Using local metadata (more recent than remote)")
                else:
                    metadata = metadata_r
                    logger.info("Using remote metadata (more recent than local)")
            elif metadata_l is not None:
                metadata = metadata_l
                logger.info("Using local metadata (remote not available)")
            elif metadata_r is not None:
                metadata = metadata_r
                logger.info("Using remote metadata (local not available)")

            if metadata is None:
                logger.warning("Metadata: null (no local or remote metadata found)")

            return metadata

        return metadata


class DiscoveryCache:
    """Local file cache for ServiceClient discovery results.

    Stores per-service-client native discovery items as JSON under
    ``~/.amscrot/metadata/discovery/``. Each cache entry includes a
    timestamp so callers can apply TTL-based expiration.

    Typical usage::

        cache = DiscoveryCache()
        cached = cache.load_discovery("nersc")       # returns DiscoveryResult or None
        cache.save_discovery("nersc", live_result)    # persist after a live call
        cache.invalidate("nersc")                     # delete one entry
        cache.invalidate_all()                        # clear entire cache
    """

    DEFAULT_MAX_AGE_SECONDS = 3600  # 1 hour

    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = base_dir or (Path.home() / ".amscrot" / Constants.DISCOVERY_CACHE_DIR)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, client_name: str) -> Path:
        """Return the JSON file path for a given service client name."""
        safe_name = client_name.replace("/", "_").replace("..", "_")
        return self._base_dir / f"{safe_name}.json"

    def save_discovery(self, client_name: str, discovery_result: Any) -> Path:
        """Persist a DiscoveryResult's native items to a timestamped JSON file.

        Args:
            client_name: Service client identifier (e.g. 'nersc', 'esnet-east').
            discovery_result: A DiscoveryResult instance whose items will be
                serialized via their ``to_dict()`` method.

        Returns:
            Path to the written cache file.
        """
        items_list: List[Dict[str, Any]] = []
        for item in discovery_result:
            if hasattr(item, "to_dict"):
                items_list.append(item.to_dict())
            elif isinstance(item, dict):
                items_list.append(item)

        payload = {
            "client_name": client_name,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "items": items_list,
        }

        path = self._cache_path(client_name)
        temp_path = path.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as fp:
                json.dump(payload, fp, indent=2, default=str)
            temp_path.replace(path)
            logger.info(f"Discovery cache saved for '{client_name}' ({len(items_list)} items)")
        except OSError as e:
            logger.warning(f"Failed to save discovery cache for '{client_name}': {e}")
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

        return path

    def load_discovery(
        self,
        client_name: str,
        max_age_seconds: Optional[float] = None,
    ) -> Optional[Any]:
        """Load a cached discovery result if it exists and is not expired.

        Args:
            client_name: Service client identifier.
            max_age_seconds: Maximum age in seconds before the cache is
                considered stale. Defaults to ``DEFAULT_MAX_AGE_SECONDS``.
                Pass ``0`` or a negative value to treat any cache as expired.

        Returns:
            A ``DiscoveryResult`` rebuilt from the cached items, or ``None``
            if the cache is missing, unreadable, or expired.
        """
        from amscrot.model.discovery import DiscoveryResult, DiscoveredResource

        if max_age_seconds is None:
            max_age_seconds = self.DEFAULT_MAX_AGE_SECONDS

        path = self._cache_path(client_name)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Discovery cache unreadable for '{client_name}': {e}")
            return None

        # Check TTL
        cached_at_str = payload.get("cached_at", "")
        try:
            cached_at = datetime.fromisoformat(cached_at_str)
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.warning(f"Discovery cache has invalid timestamp for '{client_name}', treating as expired")
            return None

        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if max_age_seconds > 0 and age > max_age_seconds:
            logger.info(
                f"Discovery cache expired for '{client_name}' "
                f"(age={age:.0f}s, max={max_age_seconds:.0f}s)"
            )
            return None

        # Rebuild DiscoveryResult from cached items
        raw_items = payload.get("items", [])
        items = []
        for raw in raw_items:
            items.append(DiscoveredResource(
                type=raw.get("type", "unknown"),
                data=raw.get("data", {}),
            ))

        logger.info(
            f"Discovery cache hit for '{client_name}' "
            f"({len(items)} items, age={age:.0f}s)"
        )
        return DiscoveryResult(items=items)

    def invalidate(self, client_name: str) -> bool:
        """Delete the cache entry for a specific service client.

        Returns:
            True if a file was removed, False if no cache existed.
        """
        path = self._cache_path(client_name)
        if path.exists():
            path.unlink()
            logger.info(f"Discovery cache invalidated for '{client_name}'")
            return True
        return False

    def invalidate_all(self) -> int:
        """Remove all cached discovery files.

        Returns:
            Number of files removed.
        """
        count = 0
        for path in self._base_dir.glob("*.json"):
            try:
                path.unlink()
                count += 1
            except OSError:
                pass
        if count:
            logger.info(f"Discovery cache cleared ({count} entries removed)")
        return count