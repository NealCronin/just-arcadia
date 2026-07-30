"""Contract tests for the public structured-event serialization API."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from arcadia.events import EventLevel, dumps_event, loads_event, make_event
from arcadia.models import ArcadiaErrorInfo


def test_dumps_event_is_compact_deterministic_and_unicode_safe() -> None:
    event = make_event(
        event_id="event-1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        kind="analysis.started",
        level=EventLevel.INFO,
        source="contract",
        message="started ✓",
        data={"z": 1, "a": "✓"},
        error=ArcadiaErrorInfo(code="example", message="details"),
    )
    serialized = dumps_event(event)
    assert serialized == dumps_event(event)
    assert serialized.endswith("}")
    assert "\n" not in serialized
    assert "✓" in serialized
    assert list(json.loads(serialized)) == sorted(json.loads(serialized))
    assert loads_event(serialized) == event


@pytest.mark.parametrize("payload", ["not json", "[]", "null", "1", "NaN", '{"kind":"bad"}'])
def test_loads_event_rejects_invalid_payloads(payload: str) -> None:
    with pytest.raises((ValueError, ValidationError, json.JSONDecodeError)):
        loads_event(payload)


def test_loads_event_rejects_unknown_fields() -> None:
    payload = {
        "event_id": "event-1",
        "timestamp": "2026-01-01T00:00:00Z",
        "kind": "analysis.started",
        "level": "info",
        "source": "contract",
        "message": "started",
        "data": {},
        "unknown": True,
    }
    with pytest.raises(ValidationError):
        loads_event(json.dumps(payload))


def test_event_model_is_frozen() -> None:
    event = make_event(kind="test.started", level=EventLevel.DEBUG, source="test", message="started")
    with pytest.raises(ValidationError):
        event.message = "changed"  # type: ignore[misc]
