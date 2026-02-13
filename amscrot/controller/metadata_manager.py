import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import sys
import os

from amscrot.util.utils import get_logger

logger = get_logger()


@dataclass(frozen=True)
class MetadataConfig:
    """
    Metadata manager configuration.
    # ... existing code ...
    """

    metadata_id: str
    local_base_dir: Path
    local_file_ext: str = "json"
    remote_domain: str = "INSTANCE"
    # This value is a *record name* in the remote metadata repository (not an API operation name).
    # If you don't override it via config, MetadataManager._build_config() will default it to metadata_id.
    remote_name: str = "gmetadata"

    @property
    def local_file_path(self) -> Path:
        """Absolute path to the local metadata cache file."""
        return self.local_base_dir / f"{self.metadata_id}.{self.local_file_ext}"


class MetadataManager:
    """
    Retrieve metadata from either local cache or a remote metadata service.
    # ... existing code ...
    """

    def __init__(self, config_metadata: Optional[Dict[str, Any]], metadata_preference: str, metadata_id: str):
        self.metadata_location_preference = metadata_preference
        self.config = self._build_config(config_metadata=config_metadata or {}, metadata_id=metadata_id)

    @classmethod
    def fetch(
        cls,
        *,
        metadata_preference: str,
        metadata_id: str = "gmetadata",
        config_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Convenience helper used by ServiceClient.discover().

        Returns:
            Metadata dict if found; otherwise None.
        """
        mgr = cls(config_metadata=config_metadata, metadata_preference=metadata_preference, metadata_id=metadata_id)
        return mgr.get_metadata()

    def _build_config(self, *, config_metadata: Dict[str, Any], metadata_id: str) -> MetadataConfig:
        """
        Build and normalize metadata configuration and ensure local directories exist.
        """
        base_dir = Path.home() / ".amscrot" / "metadata"
        base_dir.mkdir(parents=True, exist_ok=True)

        remote_domain = str(config_metadata.get("remote_domain", "INSTANCE"))

        # IMPORTANT: remote_name is the *metadata record name*.
        # Previous default "get_metadata" looked like an API operation and caused remote 404s.
        # Defaulting to metadata_id makes behavior predictable:
        #   metadata_id="gmetadata" -> GET /meta/<domain>/gmetadata
        remote_name = str(config_metadata.get("remote_name") or metadata_id)

        return MetadataConfig(
            metadata_id=str(metadata_id),
            local_base_dir=base_dir,
            local_file_ext=str(config_metadata.get("local_file_ext", "json")),
            remote_domain=remote_domain,
            remote_name=remote_name,
        )

    def _get_local_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Load metadata from the local cache file.
        """
        path = self.config.local_file_path
        if not path.exists():
            logger.info(f"Local metadata not found at {path}")
            return None

        try:
            with path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except json.JSONDecodeError as e:
            logger.warning(f"Local metadata file is not valid JSON: {path}: {e}")
            return None
        except OSError as e:
            logger.warning(f"Unable to read local metadata file: {path}: {e}")
            return None


    def _get_remote_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata from the remote repository using SENSE-O `MetadataApi()`.

        Returns:
            dict when found and valid; otherwise None (e.g., record not found).
        """
        if not os.getenv("HOME"):
            os.environ["HOME"] = str(Path.home())

        from sense.client.metadata_api import MetadataApi

        # Preflight: the SENSE-O client expects an auth config file.
        auth_path = Path.home() / ".sense-o-auth.yaml"
        if not auth_path.exists():
            raise FileNotFoundError(
                f"SENSE-O auth config not found at '{auth_path}'. "
                "Remote metadata fetch expects the SENSE-O client default configuration "
                "(same behavior as sense_util.py)."
            )

        metadata_api = MetadataApi()

        try:
            record = metadata_api.get_metadata(domain=self.config.remote_domain, name=self.config.remote_name)
        except ValueError as e:
            # If the record doesn't exist, treat it as "no remote metadata" so
            # local|remote / remote|local preference works without crashing.
            if self._is_remote_not_found(e):
                logger.info(
                    "Remote metadata not found (404): "
                    f"{self.config.remote_domain}/{self.config.remote_name}"
                )
                return None
            raise

        # Normalize return types for the rest of amscrot.
        if isinstance(record, str):
            try:
                parsed = json.loads(record)
            except json.JSONDecodeError as e:
                raise ValueError(f"Remote metadata returned a string but not valid JSON: {e}") from e
            if not isinstance(parsed, dict):
                raise TypeError(f"Unexpected remote metadata JSON type: {type(parsed)}")
            return parsed

        if not isinstance(record, dict):
            raise TypeError(f"Unexpected remote metadata type: {type(record)}")

        return record

    def get_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve metadata based on the configured location preference.
        """
        preference = (self.metadata_location_preference or "").strip().lower()

        if preference not in {"local", "remote", "local|remote", "remote|local"}:
            raise ValueError("Invalid metadata preference. Expected: 'local', 'remote', 'local|remote', 'remote|local'")

        metadata: Optional[Dict[str, Any]] = None

        if preference == "local":
            metadata = self._get_local_metadata()
        elif preference == "remote":
            metadata = self._get_remote_metadata()
        elif preference == "local|remote":
            metadata = self._get_local_metadata()
            if metadata is None:
                try:
                    metadata = self._get_remote_metadata()
                except Exception as e:
                    logger.warning(f"Remote metadata fetch failed (local|remote), leaving metadata as None: {e}")
                    metadata = None
        elif preference == "remote|local":
            try:
                metadata = self._get_remote_metadata()
            except Exception as e:
                logger.warning(f"Remote metadata fetch failed, falling back to local: {e}")
                metadata = self._get_local_metadata()

        if metadata is None:
            print("Metadata: null")
        else:
            print(json.dumps(metadata, indent=2, default=str))

        return metadata