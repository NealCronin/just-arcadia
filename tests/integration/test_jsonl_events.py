"""Integration tests for append-only JSONL event delivery."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

from arcadia.events import (
    ArcadiaEvent,
    EventEmitter,
    EventLevel,
    InMemoryEventSink,
    JsonlEventSink,
    dumps_event,
    loads_event,
    make_event,
)


def make_test_event(index: int) -> ArcadiaEvent:
    return make_event(
        kind="service.download.progress",
        level=EventLevel.INFO,
        source="test",
        message=f"progress {index} ✓",
        data={"index": index},
        event_id=f"event-{index}",
    )


def test_jsonl_appends_and_preserves_unicode(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"existing":true}\n', encoding="utf-8")
    sink = JsonlEventSink(path)
    event = make_test_event(1)
    report = EventEmitter([sink]).emit(event)  # type: ignore[arg-type]

    assert report.ok
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"existing":true}'
    assert loads_event(lines[1]) == event
    assert "✓" in lines[1]
    assert all(json.loads(line) for line in lines)


def test_jsonl_does_not_create_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "events.jsonl"
    JsonlEventSink(path)
    assert not path.parent.exists()


def test_concurrent_jsonl_writes_are_complete(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    emitter = EventEmitter([sink])
    threads = [
        threading.Thread(target=lambda start=start: [emitter.emit(make_test_event(start + i)) for i in range(40)])
        for start in range(0, 200, 40)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200
    assert all(loads_event(line).kind == "service.download.progress" for line in lines)


def test_jsonl_fsync_and_failure_isolated(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    memory = InMemoryEventSink()
    sink = JsonlEventSink(path, fsync=True)
    event = make_test_event(3)
    with patch("arcadia.events.sinks.os.fsync") as fsync:
        report = EventEmitter([sink, memory]).emit(event)  # type: ignore[arg-type]
    assert report.ok
    fsync.assert_called_once()
    assert memory.snapshot() == (event,)

    failure_path = tmp_path / "missing" / "events.jsonl"
    failed = EventEmitter([JsonlEventSink(failure_path), memory]).emit(event)  # type: ignore[arg-type]
    assert not failed.ok
    assert failed.failures[0].exception_type == "FileNotFoundError"
    assert memory.snapshot()[-1] == event


def test_jsonl_serialization_is_one_line_without_extra_newline(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    event = make_test_event(4)
    sink.emit(event)  # type: ignore[arg-type]
    assert path.read_bytes() == (dumps_event(event) + "\n").encode("utf-8")
