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

    def _import_sense_metadata_api(self):
        """
        Import MetadataApi from the SENSE-O python client.

        Supports:
          1) installed package import (preferred)
          2) local repo checkout at <repo>/sense-o-py-client by adding it to sys.path
        """
        try:
            from sense.client.metadata_api import MetadataApi  # type: ignore
            return MetadataApi
        except ModuleNotFoundError as first_err:
            # Try to locate a local checkout by walking up from this file.
            here = Path(__file__).resolve()

            candidates: list[Path] = []

            # Optional explicit override (useful in CI / custom layouts)
            override = os.environ.get("SENSE_O_PY_CLIENT_PATH")
            if override:
                candidates.append(Path(override).expanduser().resolve())

            # Look for <ancestor>/sense-o-py-client (original behavior)
            for parent in here.parents:
                candidates.append(parent / "sense-o-py-client")

                # Also look for a sibling: <ancestor>/../sense-o-py-client
                # This matches layouts like:
                #   Projects/
                #     amsc-isro-toolkit/
                #     sense-o-py-client/
                if parent.parent != parent:
                    candidates.append(parent.parent / "sense-o-py-client")

            def _iter_possible_package_roots(checkout_dir: Path) -> list[Path]:
                """
                Return directories that might be the actual import root for the `sense` package.
                Supports both:
                  - <checkout>/sense/...
                  - <checkout>/src/sense/...
                """
                roots: list[Path] = []
                roots.append(checkout_dir)
                roots.append(checkout_dir / "src")
                return roots

            def _looks_like_sense_client_root(root: Path) -> bool:
                return (root / "sense" / "client" / "metadata_api.py").is_file()

            added_any = False
            for checkout in candidates:
                if not (checkout.exists() and checkout.is_dir()):
                    continue

                for root in _iter_possible_package_roots(checkout):
                    if not (root.exists() and root.is_dir()):
                        continue
                    if not _looks_like_sense_client_root(root):
                        continue

                    root_str = str(root)
                    if root_str not in sys.path:
                        sys.path.insert(0, root_str)
                        added_any = True

            if added_any:
                # If some other `sense` package was imported earlier, Python may keep using it
                # even after sys.path changes. Drop it from the import cache so the retry
                # resolves `sense` from the newly-added checkout path.
                for modname in list(sys.modules.keys()):
                    if modname == "sense" or modname.startswith("sense."):
                        sys.modules.pop(modname, None)

                try:
                    from sense.client.metadata_api import MetadataApi  # type: ignore
                    return MetadataApi
                except ModuleNotFoundError:
                    pass

            raise ModuleNotFoundError(
                "Unable to import `sense.client.metadata_api` required for remote metadata fetch.\n"
                "Tried importing from the active environment, then adding a local `sense-o-py-client/` checkout to sys.path.\n"
                "Verify that either:\n"
                "  - the SENSE-O client package is installed in this environment, OR\n"
                "  - a `sense-o-py-client/` directory exists and contains `sense/client/metadata_api.py`.\n"
                "Tip: if your checkout is a sibling of this repo, this code now searches that layout too.\n"
                "You can also set SENSE_O_PY_CLIENT_PATH to the checkout directory.\n"
                f"Original error: {first_err}"
            ) from first_err

    def _is_remote_not_found(self, err: Exception) -> bool:
        """
        Heuristic for SENSE-O client behavior:
        it raises ValueError for HTTP errors and includes 404/NOT_FOUND in the message.
        """
        msg = str(err)
        return ("Returned code 404" in msg) or ("NOT_FOUND" in msg) or ("Record not found" in msg)

    def _get_remote_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata from the remote repository using SENSE-O `MetadataApi()`.

        Returns:
            dict when found and valid; otherwise None (e.g., record not found).
        """
        MetadataApi = self._import_sense_metadata_api()

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
##############################################################################
##############################################################################
##############################################################################


##############################################################################
##############################################################################
##############################################################################

# import os
# from amscrot.util import utils
# from typing import Union, Dict, List, Any
# from amscrot.exceptions import ControllerException
# from amscrot.util.constants import Constants
#
#
# from pydantic import BaseModel, Field
#
# config_metadata= {
#     """
#     l: local metadata repository,
#     r: remote metadata repository
#     """
# 'metadata_id': str,
# 'lPATH': str,           # main directory path if local storage is available
# 'ldbPATH': str,         # path to local storage
# 'ldbTYPE': str,         # type of database file, e.g., txt, json, yml, etc
# 'lservicePATH': str, # path to software service manages local storage. May be redundant
# 'rURL': str,           # endpoint location where metadata are remotely stored, e.g., sense-o
# 'rdbTYPE': str,         # type of database file, e.g., json, yml, etc
# 'rserviceURL': str # path to endpoint service manages remote metadata,
# }
#
#
# #TODO
# # 1- local storage: save metadata local as json file, nosql(manodb,tinydb),
# # 2- remote storage: remote metadata at sense-o using sense-o-py-client, (look at sense_provider at sense directory)
# # 3- methods to update local/remote storage from cache.
#
# #TODO
# # 1- create structure for metadata configureations, e.g, path of installed local metadata agent, its storage, etc,
# # 2- look at amscorot_manager for its configurations, e.g.,  base_dir = os.path.join(str(Path.home()), '.amscrot', 'sessions') change sessions with metadata for local storage
#
# class MetadataManager():
#
#     def __init__(self, config_metadata: Dict,metadata_preference: str, metadata_id: str) -> Dict:
#         self.config_metadata = self.initialize_metadata_structure(config_metadata, metadata_id)
#         self.metadata_location_preference = metadata_preference # Options ['local', 'remote', 'most_updated', 'local|remote', 'remote|local']
#
#     def initialize_metadata_structure(self, config_metadata: Dict, metadata_id: str) -> Dict:
#         import os
#         from pathlib import Path
#         import json
#
#         self.config_metadata['metadata_id']=metadata_id
#         # initialize local metadata
#         base_dir = os.path.join(str(Path.home()), '.amscrot', 'metadata')
#         os.makedirs(base_dir, exist_ok=True)
#         self.config_metadata['lPATH']=base_dir
#         self.config_metadata['ldbPATH']=base_dir
#         self.config_metadata['ldbTYPE']='json'
#
#         # initialize remote metadata
#
#         return self.config_metadata
#
#
#     #@classmethod
#     def get_metadata(self) -> Dict:
#         import json
#         from pathlib import Path
#         import subprocess
#         import os
#         import yaml
#         from amscrot.provider.sense.sense_constants import SENSE_CONF_ATTRS
#         def get_lmetadata():
#             try:
#                 with open(os.path.join(self.config_metadata['ldbPATH'],self.config_metadata['metadata_id']), 'r') as file:
#                     data = json.load(file)
#                     return data
#             except FileNotFoundError:
#                 print(f"Error: The file '{self.config_metadata['metadata_id']}' was not found.")
#                 return None
#
#         def get_rmetadata():
#             try:
#                 if os.path.join(Path.home(), '.sense-o-auth.yaml'):
#                     script_path = os.path.join(Path.home(),"Projects","sense-o-py-client","util","sense_util.py")
#
#                     command = [
#                         "python",
#                         str(script_path),  # Convert Path object to string for the command
#                         "--metadata-get",
#                         "--domain", "INSTANCE",
#                         "-n", "fetch_metadata"
#                     ]
#
#                     try:
#                         result = subprocess.run(command, check=True, capture_output=True, text=True)
#
#                         metadata_dict = json.loads(result.stdout)
#
#                     except subprocess.CalledProcessError as e:
#                         print(f"Error: Script failed with return code {e.returncode}")
#                         print(f"Details: {e.stderr}")
#                     except json.JSONDecodeError:
#                         print("Error: Output was not valid JSON.")
#                         print(f"Raw output received: {result.stdout}")
#                 return metadata_dict
#
#             except Exception as e:
#                 print(f"An unexpected error occurred: {e}")
#                 return None
#
#
#
#         if self.metadata_location_preference == 'local':
#             metadata=get_lmetadata()
#         elif self.metadata_location_preference == 'remote':
#             metadata=get_rmetadata()
#         elif self.metadata_location_preference == 'local|remote':
#             metadata=get_lmetadata()
#             if metadata is not None:
#                 return metadata
#             else:
#                 return get_rmetadata()
