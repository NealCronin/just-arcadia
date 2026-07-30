"""Unit tests for structured events, emitters, and built-in sinks."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arcadia.events import (
    ArcadiaEvent,
    CallbackEventSink,
    EmitReport,
    EventEmitter,
    EventLevel,
    InMemoryEventSink,
    SinkFailure,
    exception_event,
    make_event,
)
from arcadia.models import ArcadiaError, ArcadiaErrorInfo


def event(**overrides: object) -> ArcadiaEvent:
    values: dict[str, object] = {
        "kind": "analysis.started",
        "level": EventLevel.INFO,
        "source": "analysis",
        "message": "started",
    }
    values.update(overrides)
    return ArcadiaEvent.model_validate(values)


def test_make_event_defaults_to_info() -> None:
    created = make_event(kind="test.started", source="test", message="started")
    assert created.level is EventLevel.INFO


def test_defaults_and_timestamp_normalization() -> None:
    before = datetime.now(UTC)
    first = event()
    after = datetime.now(UTC)

    assert first.event_id
    assert before <= first.timestamp <= after
    assert first.timestamp.tzinfo is UTC

    supplied = datetime(2026, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=-5)))
    deterministic = event(event_id=" fixed ", timestamp=supplied)
    assert deterministic.timestamp == datetime(2026, 1, 2, 8, 4, tzinfo=UTC)


def test_naive_timestamp_and_invalid_kind_are_rejected() -> None:
    with pytest.raises(ValidationError):
        event(timestamp=datetime(2026, 1, 1))
    for kind in ("Analysis.started", "analysis..started", "1analysis.started", "analysis.started "):
        with pytest.raises(ValidationError):
            event(kind=kind)
    for kind in ("analysis", "analysis.started", "service_2.progress", "x1.y_2"):
        assert event(kind=kind).kind == kind


@pytest.mark.parametrize("field", ["source", "message", "run_id", "operation_id"])
def test_text_fields_are_trimmed_and_non_empty(field: str) -> None:
    assert getattr(event(**{field: " value "}), field) == "value"
    with pytest.raises(ValidationError):
        event(**{field: "   "})


def test_data_is_json_validated_and_defensively_copied() -> None:
    data = {"nested": [1, {"unicode": "✓"}]}
    created = event(data=data)
    data["nested"].append("caller mutation")
    assert created.data == {"nested": [1, {"unicode": "✓"}]}

    for invalid in ({1: "key"}, {"value": float("nan")}, {"value": object()}, {"value": (1, 2)}):
        with pytest.raises(ValidationError):
            event(data=invalid)

    with pytest.raises(ValidationError):
        event(unexpected=True)


def test_error_info_and_json_round_trip() -> None:
    original = event(
        event_id="event-1",
        timestamp=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        run_id="run-1",
        operation_id="operation-1",
        error=ArcadiaErrorInfo(code="bad_input", message="invalid", details={"field": "x"}),
        data={"count": 2},
    )
    from arcadia.events import dumps_event, loads_event

    assert loads_event(dumps_event(original)) == original


def test_make_event_and_exception_event_preserve_details() -> None:
    caller_data = {"attempt": 2}
    try:
        try:
            raise ValueError("broken")
        except ValueError as exc:
            generated = exception_event(exc, source="worker", run_id="run-1", data=caller_data)
    except Exception:
        pytest.fail("exception_event must not raise")

    assert generated.error == ArcadiaErrorInfo(code="unhandled_exception", message="broken", retryable=False)
    assert generated.data["exception_type"] == "ValueError"
    assert "Traceback (most recent call last)" in generated.data["traceback"]
    assert "raise ValueError" in generated.data["traceback"]
    assert generated.data["attempt"] == 2
    assert caller_data == {"attempt": 2}
    assert "ValueError" in generated.model_dump_json()
    assert "exception" not in generated.model_dump(mode="python")["data"]


def test_arcadia_error_uses_to_info() -> None:
    error = ArcadiaError("failed", code="known", retryable=True, details={"step": 3})
    generated = exception_event(error)
    assert generated.error == error.to_info()


def test_emitter_delivers_in_order_and_isolates_failures() -> None:
    received: list[str] = []

    class RecordingSink:
        def emit(self, event: ArcadiaEvent) -> None:
            received.append(event.source)

    class FailingSink:
        def emit(self, event: ArcadiaEvent) -> None:
            raise RuntimeError("sink broke")

    emitter = EventEmitter([RecordingSink(), FailingSink(), RecordingSink()])
    report = emitter.emit(event(source="first"))
    assert report == EmitReport(
        delivered=2,
        failures=(
            SinkFailure(
                sink_name="FailingSink",
                exception_type="RuntimeError",
                message="sink broke",
                traceback=report.failures[0].traceback,
            ),
        ),
    )
    assert report.attempted == 3
    assert not report.ok
    assert received == ["first", "first"]


def test_emitter_catches_base_exception_and_empty_report() -> None:
    class InterruptingSink:
        def emit(self, event: ArcadiaEvent) -> None:
            raise KeyboardInterrupt("stop")

    report = EventEmitter([InterruptingSink()]).emit(event())
    assert report.attempted == 1
    assert report.failures[0].exception_type == "KeyboardInterrupt"
    assert EventEmitter().emit(event()) == EmitReport(delivered=0, failures=())


def test_emitter_duplicate_and_identity_removal() -> None:
    first = InMemoryEventSink()
    equal_but_distinct = InMemoryEventSink()
    emitter = EventEmitter([first])
    with pytest.raises(ValueError):
        emitter.add_sink(first)
    assert emitter.remove_sink(equal_but_distinct) is False
    assert emitter.remove_sink(first) is True
    assert emitter.remove_sink(first) is False


def test_callback_and_memory_sink_lifecycle() -> None:
    received: list[ArcadiaEvent] = []
    callback = CallbackEventSink(received.append)
    with pytest.raises(TypeError):
        CallbackEventSink(42)  # type: ignore[arg-type]
    memory = InMemoryEventSink()
    emitter = EventEmitter([callback, memory])
    current = event()
    assert emitter.emit(current).ok
    assert received == [current]
    assert memory.snapshot() == (current,)
    assert len(memory) == 1
    memory.clear()
    assert len(memory) == 0


def test_concurrent_in_memory_emission() -> None:
    sink = InMemoryEventSink()
    emitter = EventEmitter([sink])
    threads = [threading.Thread(target=lambda: [emitter.emit(event()) for _ in range(50)]) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(sink) == 400
