"""Structured events and isolated event sinks for ARCADIA."""

from arcadia.events.emitter import EmitReport, EventEmitter, EventSink, SinkFailure
from arcadia.events.models import ArcadiaEvent, EventLevel
from arcadia.events.serialization import dumps_event, exception_event, loads_event, make_event
from arcadia.events.sinks import CallbackEventSink, InMemoryEventSink, JsonlEventSink

__all__ = [
    "EventLevel",
    "ArcadiaEvent",
    "EventSink",
    "SinkFailure",
    "EmitReport",
    "EventEmitter",
    "InMemoryEventSink",
    "CallbackEventSink",
    "JsonlEventSink",
    "make_event",
    "exception_event",
    "dumps_event",
    "loads_event",
]
