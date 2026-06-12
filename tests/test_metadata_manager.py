import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
try:
    import numpy as np
    from amscrot.controller.metadata_manager import MetadataManager
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def test_to_st_mtime():
    mgr = MetadataManager(config_metadata={}, metadata_fetch_mode="local", metadata_id=None)
    
    # Test standard format
    ts = mgr._to_st_mtime("2026-06-12 10:20:07 UTC")
    assert ts > 0.0

    # Test space-less UTC Z format
    ts_z = mgr._to_st_mtime("2026-06-12T10:20:07Z")
    assert ts_z > 0.0
    assert ts_z == ts

    # Test microsecond formats
    ts_ms = mgr._to_st_mtime("2026-06-12T10:20:07.123456Z")
    assert ts_ms > 0.0

    # Test fallback on invalid format
    ts_invalid = mgr._to_st_mtime("invalid-date")
    assert ts_invalid == 0.0


def test_get_local_metadata(tmp_path):
    # Setup mock local metadata file
    meta_id = "test_meta"
    meta_content = {"services": [], "service_clients": [], "groups": [], "policies": {}}
    
    file_path = tmp_path / f"{meta_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(meta_content, f)

    mgr = MetadataManager(
        config_metadata={"local_file_ext": "json"},
        metadata_fetch_mode="local",
        metadata_id=meta_id
    )
    # Override local_base_dir with tmp_path
    object.__setattr__(mgr.config, "local_base_dir", tmp_path)

    result = mgr.get_metadata()
    assert result == meta_content


@patch("amscrot.controller.metadata_manager.os.path.exists")
def test_get_remote_metadata_with_envelope(mock_exists):
    # Mock preflight check (we pretend the auth config exists)
    with patch("pathlib.Path.exists", return_value=True):
        # Mock SENSE-O MetadataApi
        mock_api_cls = MagicMock()
        mock_api_instance = mock_api_cls.return_value
        
        # SENSE-O returns a dict with "edited" and serialized "data"
        mock_api_instance.get_metadata.return_value = {
            "name": "test_remote",
            "edited": "2026-06-12 10:20:07 UTC",
            "data": json.dumps({"services": [{"name": "weather-sim"}]})
        }

        with patch.dict("sys.modules", {"sense.client.metadata_api": MagicMock(MetadataApi=mock_api_cls)}):
            mgr = MetadataManager(
                config_metadata={"remote_domain": "TEST_DOMAIN"},
                metadata_fetch_mode="remote",
                metadata_id="test_remote"
            )
            result = mgr.get_metadata()
            assert result == {"services": [{"name": "weather-sim"}]}


def test_fallback_logic_local_remote():
    # Test that when remote fails (e.g., SENSE-O config missing), get_metadata falls back to local
    mgr = MetadataManager(
        config_metadata={},
        metadata_fetch_mode="local|remote",
        metadata_id="test_meta"
    )

    local_meta = {"services": ["local"]}
    local_mtime = 100.0

    # Mock _get_local_metadata and _get_remote_metadata
    mgr._get_local_metadata = MagicMock(return_value=(local_meta, local_mtime))
    mgr._get_remote_metadata = MagicMock(side_effect=FileNotFoundError("SENSE-O auth config not found"))

    # Should run successfully and return local_meta instead of raising exception
    result = mgr.get_metadata()
    assert result == local_meta


def test_comparison_logic_local_remote():
    mgr = MetadataManager(
        config_metadata={},
        metadata_fetch_mode="local|remote",
        metadata_id="test_meta"
    )

    local_meta = {"services": ["local"]}
    local_mtime = 100.0

    remote_meta = {"services": ["remote"]}
    remote_mtime = 200.0

    mgr._get_local_metadata = MagicMock(return_value=(local_meta, local_mtime))
    mgr._get_remote_metadata = MagicMock(return_value=(remote_meta, remote_mtime))

    # remote is newer, return remote
    result = mgr.get_metadata()
    assert result == remote_meta

    # local is newer, return local
    mgr._get_local_metadata = MagicMock(return_value=(local_meta, 300.0))
    result = mgr.get_metadata()
    assert result == local_meta
