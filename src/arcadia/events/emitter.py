"""Thread-safe event delivery with sink-failure isolation."""

from __future__ import annotations

import threading
import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from arcadia.events.models import ArcadiaEvent

__all__ = ["EventSink", "SinkFailure", "EmitReport", "EventEmitter"]


@runtime_checkable
class EventSink(Protocol):
    """A destination for one structured event."""

    def emit(self, event: ArcadiaEvent) -> None:
        """Deliver an event, or raise when delivery fails."""
        ...


@dataclass(frozen=True, slots=True)
class SinkFailure:
    """Serializable details about one isolated sink failure."""

    sink_name: str
    exception_type: str
    message: str
    traceback: str


@dataclass(frozen=True, slots=True)
class EmitReport:
    """Result of attempting delivery to an emitter's sink snapshot."""

    delivered: int
    failures: tuple[SinkFailure, ...]

    @property
    def attempted(self) -> int:
        return self.delivered + len(self.failures)

    @property
    def ok(self) -> bool:
        return not self.failures


class EventEmitter:
    """Own and invoke an ordered, mutable collection of event sinks."""

    def __init__(self, sinks: Iterable[EventSink] = ()) -> None:
        self._lock = threading.RLock()
        self._sinks: list[EventSink] = []
        for sink in sinks:
            self.add_sink(sink)

    def add_sink(self, sink: EventSink) -> None:
        """Register ``sink`` once, preserving registration order."""
        with self._lock:
            if any(existing is sink for existing in self._sinks):
                raise ValueError("the same sink object is already registered")
            self._sinks.append(sink)

    def remove_sink(self, sink: EventSink) -> bool:
        """Remove ``sink`` by object identity and report whether it was present."""
        with self._lock:
            for index, existing in enumerate(self._sinks):
                if existing is sink:
                    del self._sinks[index]
                    return True
        return False

    def emit(self, event: ArcadiaEvent) -> EmitReport:
        """Attempt every sink without allowing sink failures to escape."""
        with self._lock:
            sinks = tuple(self._sinks)

        delivered = 0
        failures: list[SinkFailure] = []
        for sink in sinks:
            try:
                sink.emit(event)
            except BaseException as exc:
                failures.append(
                    SinkFailure(
                        sink_name=type(sink).__name__,
                        exception_type=type(exc).__name__,
                        message=str(exc),
                        traceback=traceback.format_exc(),
                    )
                )
            else:
                delivered += 1
        return EmitReport(delivered=delivered, failures=tuple(failures))
