"""Unit tests for Incident and StatusEvent models in amscrot.model.metadata."""
import pytest
from amscrot.model.metadata import Incident, StatusEvent, _extract_id


class TestExtractId:
    def test_bare_id(self):
        assert _extract_id("abc-123") == "abc-123"

    def test_uri_path(self):
        assert _extract_id("/status/incidents/abc-123") == "abc-123"

    def test_trailing_slash(self):
        assert _extract_id("/status/incidents/abc-123/") == "abc-123"

    def test_none(self):
        assert _extract_id(None) is None


class TestIncidentFromDict:
    def _sample(self, **overrides):
        base = {
            "id": "inc-001",
            "name": "Storage degraded",
            "description": "Home filesystem at reduced performance.",
            "status": "active",
            "type": "performance",
            "resolution": None,
            "start": "2024-01-15T10:00:00Z",
            "end": None,
            "last_modified": "2024-01-15T10:05:00Z",
            "resource_uris": ["/status/resources/res-001"],
            "event_uris": ["/status/events/evt-001"],
        }
        base.update(overrides)
        return base

    def test_basic_fields(self):
        inc = Incident.from_dict(self._sample())
        assert inc.id == "inc-001"
        assert inc.name == "Storage degraded"
        assert inc.status == "active"
        assert inc.type == "performance"
        assert inc.start == "2024-01-15T10:00:00Z"
        assert inc.end is None

    def test_resource_ids_extracted_from_uris(self):
        inc = Incident.from_dict(self._sample())
        assert inc.resource_ids == ["res-001"]

    def test_event_ids_extracted_from_uris(self):
        inc = Incident.from_dict(self._sample())
        assert inc.event_ids == ["evt-001"]

    def test_empty_uri_lists(self):
        inc = Incident.from_dict(self._sample(resource_uris=[], event_uris=[]))
        assert inc.resource_ids is None
        assert inc.event_ids is None

    def test_missing_optional_fields(self):
        inc = Incident.from_dict({"id": "inc-002", "name": "Minimal"})
        assert inc.status is None
        assert inc.type is None
        assert inc.resource_ids is None

    def test_enum_status_unwrapped(self):
        """status should be a plain string even if the raw value is an enum-like object."""
        class FakeEnum:
            value = "resolved"
        inc = Incident.from_dict(self._sample(status=FakeEnum()))
        assert inc.status == "resolved"

    def test_repr(self):
        inc = Incident.from_dict(self._sample())
        assert "inc-001" in repr(inc)


class TestStatusEventFromDict:
    def _sample(self, **overrides):
        base = {
            "id": "evt-001",
            "name": "Filesystem I/O errors",
            "description": "Elevated error rate on scratch.",
            "status": "active",
            "occurred_at": "2024-01-15T10:02:00Z",
            "last_modified": "2024-01-15T10:02:30Z",
            "resource_uri": "/status/resources/res-001",
            "incident_uri": "/status/incidents/inc-001",
        }
        base.update(overrides)
        return base

    def test_basic_fields(self):
        evt = StatusEvent.from_dict(self._sample())
        assert evt.id == "evt-001"
        assert evt.name == "Filesystem I/O errors"
        assert evt.status == "active"
        assert evt.occurred_at == "2024-01-15T10:02:00Z"

    def test_resource_id_extracted_from_uri(self):
        evt = StatusEvent.from_dict(self._sample())
        assert evt.resource_id == "res-001"

    def test_incident_id_extracted_from_uri(self):
        evt = StatusEvent.from_dict(self._sample())
        assert evt.incident_id == "inc-001"

    def test_missing_optional_fields(self):
        evt = StatusEvent.from_dict({"id": "evt-002"})
        assert evt.name is None
        assert evt.resource_id is None
        assert evt.incident_id is None

    def test_enum_status_unwrapped(self):
        class FakeEnum:
            value = "resolved"
        evt = StatusEvent.from_dict(self._sample(status=FakeEnum()))
        assert evt.status == "resolved"
