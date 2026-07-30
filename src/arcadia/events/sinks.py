"""Built-in event sinks for tests, adapters, and append-only logs."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arcadia.events.models import ArcadiaEvent
from arcadia.events.serialization import dumps_event

__all__ = ["InMemoryEventSink", "CallbackEventSink", "JsonlEventSink"]


class InMemoryEventSink:
    """Collect events in emission order for tests and status consumers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[ArcadiaEvent] = []

    def emit(self, event: ArcadiaEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[ArcadiaEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


class CallbackEventSink:
    """Adapt a callable to the :class:`EventSink` protocol."""

    def __init__(self, callback: Callable[[ArcadiaEvent], Any]) -> None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._callback = callback

    def emit(self, event: ArcadiaEvent) -> None:
        self._callback(event)


class JsonlEventSink:
    """Append one compact UTF-8 event object per line to a supplied path."""

    def __init__(self, path: str | os.PathLike[str], *, fsync: bool = False) -> None:
        if isinstance(path, bytes):
            raise TypeError("path must be a string or path-like object")
        try:
            path_value = os.fspath(path)
        except TypeError as exc:
            raise TypeError("path must be a string or path-like object") from exc
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("path must be a non-empty string or path-like object")
        self._path = Path(path_value)
        self._fsync = fsync
        self._lock = threading.Lock()

    def emit(self, event: ArcadiaEvent) -> None:
        line = dumps_event(event)
        with self._lock:
            with self._path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(line)
                handle.write("\n")
                handle.flush()
                if self._fsync:
                    os.fsync(handle.fileno())
