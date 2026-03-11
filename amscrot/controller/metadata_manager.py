import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import sys
import os
import numpy as np
from datetime import datetime, timezone


from amscrot.util.utils import get_logger

logger = get_logger()


@dataclass(frozen=True)
class MetadataConfig:
    """
    Metadata manager configuration.
    # ... existing code ...
    """
    metadata_id: Optional[str]
    local_base_dir: Path
    local_file_ext: str = "json"
    remote_domain: str = "WORKSPACE"
    # This value is a *record name* in the remote metadata repository.
    # If you don't override it via config, MetadataManager._build_config() will default it to metadata_id.

    @property
    def local_metadata_path(self) -> Optional[tuple[Path, float]]:
        """
        Returns (path, mtime) as follows.
        1- if metadata_ id is given, return that file
        2- if not:  return the most updated metadata file in the local cache directory
        3- if no file exists, return None
        """
        base_dir = self.local_base_dir
        ext = (self.local_file_ext or "json").lstrip(".")
        pattern = f"*.{ext}"

        try:
            if not base_dir.exists() or not base_dir.is_dir():
                return None
            if self.metadata_id is not None: # if the exact cached metadata is requested
                record = self.local_base_dir / f"{self.metadata_id}.{self.local_file_ext}"
                return record, record.stat().st_mtime

            else: # bring all the cached files with their modification time and return the most recent one
                newest = max(
                    (p for p in base_dir.glob(pattern) if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    default=None,
                )
                if newest is None:
                    return None

                mod_ts = newest.stat().st_mtime
                logger.info(f'#######################{newest}###################################')
                return newest, mod_ts
        except OSError:
            # If we can't access the directory or stat files, fall back to "no local metadata".
            return None





class MetadataManager:
    """
    Retrieve metadata from either local cache or a remote metadata service.
    # ... existing code ...
    """

    # def __init__(self, config_metadata: Optional[Dict[str, Any]], metadata_fetch_mode: str, metadata_id: str|None):
    #     self.metadata_fetch_mode = metadata_fetch_mode
    #     self.config = self._build_config(config_metadata=config_metadata or {}, metadata_id=metadata_id)
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
        base_dir = Path.home() / ".amscrot" / "metadata"
        base_dir.mkdir(parents=True, exist_ok=True)

        remote_domain = str(config_metadata.get("remote_domain", "WORKSPACE"))



        return MetadataConfig(
            metadata_id=(str(metadata_id) if metadata_id is not None else None),
            local_base_dir=base_dir,
            local_file_ext=str(config_metadata.get("local_file_ext", "json")),
            remote_domain=remote_domain,
        )



    def _get_local_metadata(self) -> Optional[tuple[Path, float]]:
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

    #
    #
    #
    # def _get_remote_metadata(self) -> Optional[Dict[str, Any]]:
    #     """
    #     Fetch metadata from the remote repository using SENSE-O `MetadataApi()`.
    #
    #     Returns:
    #         dict when found and valid; otherwise None (e.g., record not found).
    #     """
    #     if not os.getenv("HOME"):
    #         os.environ["HOME"] = str(Path.home())
    #
    #     from sense.client.metadata_api import MetadataApi
    #
    #     # Preflight: the SENSE-O client expects an auth config file.
    #     auth_path = Path.home() / ".sense-o-auth.yaml"
    #     if not auth_path.exists():
    #         raise FileNotFoundError(
    #             f"SENSE-O auth config not found at '{auth_path}'. "
    #             "Remote metadata fetch expects the SENSE-O client default configuration "
    #             "(same behavior as sense_util.py)."
    #         )
    #
    #     metadata_api = MetadataApi()
    #
    #     try:
    #         record = metadata_api.get_metadata(domain=self.config.remote_domain, name=self.config.metadata_id)
    #     except ValueError as e:
    #         # If the record doesn't exist, treat it as "no remote metadata" so
    #         # local|remote / remote|local preference works without crashing.
    #         if self._is_remote_not_found(e):
    #             logger.info(
    #                 "Remote metadata not found (404): "
    #                 f"{self.config.remote_domain}/{self.config.metadata_id}"
    #             )
    #             return None
    #         raise
    #
    #     # Normalize return types for the rest of amscrot.
    #     if isinstance(record, str):
    #         try:
    #             parsed = json.loads(record)
    #         except json.JSONDecodeError as e:
    #             raise ValueError(f"Remote metadata returned a string but not valid JSON: {e}") from e
    #         if not isinstance(parsed, dict):
    #             raise TypeError(f"Unexpected remote metadata JSON type: {type(parsed)}")
    #         return parsed
    #
    #     if not isinstance(record, dict):
    #         raise TypeError(f"Unexpected remote metadata type: {type(record)}")
    #
    #     return record

    def _to_st_mtime(self, s: str) -> float:
        # Parse and ensure UTC timezone
        dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S %Z')
        if dt.tzinfo is None:  # safety, in case %Z isn't recognized on some platforms
            dt = dt.replace(tzinfo=timezone.utc)

        st_mtime = dt.timestamp()
        return st_mtime

    def _get_remote_metadata(self) -> Optional[tuple[Path, float]]:
        """
        Fetch metadata from the remote repository using SENSE-O `MetadataApi()`.

        Returns dict when found and valid; otherwise None (e.g., records not found)
                (metadata object, mtime) as follows.
            1- if metadata_ id is given, return that remote case metadata object
            2- if not:  return the most updated metadata object in remote cache under specified domain
            3- if no metadata object, return None
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
            if self.config.metadata_id is not None:
                latest_record = metadata_api.get_metadata(domain=self.config.remote_domain, name=self.config.metadata_id,full=True,)
            else:
                records = metadata_api.get_metadata(domain=self.config.remote_domain)
                #records = metadata_api.get_metadata(domain='INSTANCE')
                latest_record=max(records, key=lambda d: self._to_st_mtime(d['edited']), default=None)
            latest_record_mtime = self._to_st_mtime(latest_record['edited'])

        except ValueError as e:
            # If the records don't exist, treat it as "no remote metadata" so
            if self._is_remote_not_found(e):
                logger.info("Remote metadata not found (404): ")
                return None
            raise

        # Normalize return types for the rest of amscrot.
        if isinstance(latest_record, str):
            try:
                parsed = json.loads(latest_record)
            except json.JSONDecodeError as e:
                raise ValueError(f"Remote metadata returned a string but not valid JSON: {e}") from e
            if not isinstance(parsed, dict):
                raise TypeError(f"Unexpected remote metadata JSON type: {type(parsed)}")
            return parsed,latest_record_mtime

        if not isinstance(latest_record, dict):
            raise TypeError(f"Unexpected remote metadata type: {type(latest_record)}")

        return latest_record,latest_record_mtime


    def get_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve metadata based on the configured location fetch_mode.
        """
        fetch_mode = (self.metadata_fetch_mode or "").strip().lower()

        if fetch_mode not in {"local", "remote", "local|remote", "remote|local"}:
            raise ValueError("Invalid metadata fetch_mode. Expected: 'local', 'remote', 'local|remote', 'remote|local'")

        metadata: Optional[Dict[str, Any]] = None

        if fetch_mode == "local":
            metadata,mod_ts = self._get_local_metadata()
        elif fetch_mode == "remote":
            metadata,mod_ts = self._get_remote_metadata()
        elif fetch_mode == "local|remote":
            try:
                metadata_l,mod_ts_l = self._get_local_metadata()
                metadata_r, mod_ts_r = self._get_remote_metadata()
                if metadata_l and metadata_r is not None:
                    metadata=metadata_l if mod_ts_l > mod_ts_r else metadata_r
                    logger.info(f'#######################{"metadata local:",metadata_l if mod_ts_l > mod_ts_r else "metadata remote:",metadata_r}###################################')
            except Exception as e:
                logger.warning(f"metadata fetch failed (local|remote), leaving metadata as None: {e}")
                metadata = None

        if metadata is None:
            print("Metadata: null")
        #else:
            #print(json.dumps(metadata, indent=2, default=str))

        return metadata

    # how to run
    # from amscrot.controller.metadata_manager import MetadataManager
    # mtd=MetadataManager.fetch(metadata_fetch_mode='remote', metadata_id='service_client_metadata')
    # print(mtd)