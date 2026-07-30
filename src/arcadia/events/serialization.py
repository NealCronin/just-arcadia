"""Deterministic JSON serialization and exception-to-event helpers."""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from typing import Any

from arcadia.events.models import ArcadiaEvent, EventLevel
from arcadia.models import ArcadiaError, ArcadiaErrorInfo

__all__ = ["make_event", "exception_event", "dumps_event", "loads_event"]


def make_event(
    *,
    kind: str,
    level: EventLevel,
    source: str,
    message: str,
    data: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: datetime | None = None,
    run_id: str | None = None,
    operation_id: str | None = None,
    error: ArcadiaErrorInfo | None = None,
) -> ArcadiaEvent:
    """Construct and validate an event without performing I/O."""
    values: dict[str, Any] = {
        "kind": kind,
        "level": level,
        "source": source,
        "message": message,
        "data": {} if data is None else data,
        "run_id": run_id,
        "operation_id": operation_id,
        "error": error,
    }
    if event_id is not None:
        values["event_id"] = event_id
    if timestamp is not None:
        values["timestamp"] = timestamp
    return ArcadiaEvent.model_validate(values)


def exception_event(
    exception: BaseException,
    *,
    kind: str = "diagnostic.exception",
    level: EventLevel = EventLevel.ERROR,
    source: str = "arcadia",
    message: str | None = None,
    data: dict[str, Any] | None = None,
    run_id: str | None = None,
    operation_id: str | None = None,
    event_id: str | None = None,
    timestamp: datetime | None = None,
) -> ArcadiaEvent:
    """Create an error event retaining type and complete traceback details."""
    if not isinstance(exception, BaseException):
        raise TypeError("exception must be a BaseException")

    details = {} if data is None else dict(data)
    details["exception_type"] = type(exception).__name__
    details["traceback"] = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))

    if isinstance(exception, ArcadiaError):
        error = exception.to_info()
    else:
        exception_message = str(exception).strip() or type(exception).__name__
        error = ArcadiaErrorInfo(code="unhandled_exception", message=exception_message, retryable=False)

    return make_event(
        kind=kind,
        level=level,
        source=source,
        message=error.message if message is None else message,
        data=details,
        run_id=run_id,
        operation_id=operation_id,
        event_id=event_id,
        timestamp=timestamp,
        error=error,
    )


def dumps_event(event: ArcadiaEvent) -> str:
    """Return one compact, deterministic JSON object without a newline."""
    return json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def loads_event(text: str) -> ArcadiaEvent:
    """Parse one JSON object into a validated event."""
    value = json.loads(text, parse_constant=_reject_json_constant)
    if not isinstance(value, dict):
        raise ValueError("event JSON root must be an object")
    return ArcadiaEvent.model_validate(value)
