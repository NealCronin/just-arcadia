# Session 03: Events and Structured Logging

- Status: completed
- Branch: `headless-core` (merged from `session/03-events`)
- Owner: local agent session
- Module: `arcadia.events`

## Objective

Implement the structured event and logging layer shared by later ARCADIA modules.

Session 03 must provide:

- one validated event envelope for service, analysis, tool, storage, and diagnostic events;
- safe delivery to one or more event sinks;
- sink-failure isolation so observability failures never crash the operation being observed;
- an in-memory sink for tests and status consumers;
- a callback sink for future CLI and UI adapters;
- an append-only JSONL sink for chronological logs;
- helpers for serializing events and recording exceptions with full traceback details.

This module reports activity. It does not own service state, analysis state, run directories, artifacts, or configuration.

## Architectural context

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/README.md
docs/sessions/02-configuration.md
```

Important rules:

- Long-running and externally observable operations report progress through structured events.
- Every event contains a UTC timestamp, kind, severity, source, message, structured data, and run or operation identifiers when applicable.
- Event consumers must not depend on a particular UI.
- A failing event sink must not terminate the operation that emitted the event.
- Broad exception handling is allowed at the event-sink isolation boundary, but the original traceback must be retained.
- Session 04 will own run directories and reproducibility manifests. Session 03 may append to an explicitly supplied JSONL path but must not choose or create a run directory.

Use only public APIs from `arcadia.models`. Do not modify Session 01 or Session 02 contracts unless a genuine blocker is documented.

## Scope

### Allowed files

```text
src/arcadia/events/**
tests/unit/events/**
tests/contract/test_event_serialization.py
tests/integration/test_jsonl_events.py
tests/test_package.py
docs/sessions/03-events-and-structured-logging.md
docs/sessions/README.md
```

No new runtime dependency should be necessary.

### Prohibited work

Do not create or implement:

```text
arcadia.storage
arcadia.hardware
arcadia.services
arcadia.backends
arcadia.transport
arcadia.inference
arcadia.tools
arcadia.analysis
arcadia.cli
```

Do not add:

- service or analysis state machines;
- run-directory creation or artifact registration;
- log rotation, compression, retention, or remote log shipping;
- HTTP, WebSocket, database, Django, or UI integration;
- background worker threads, queues, or async event loops;
- global event buses or process-wide singleton sinks;
- automatic configuration loading;
- model, GPU, network, or subprocess behavior;
- interception of stdout or stderr;
- a Python `logging.Handler` bridge unless required by an existing test or documented blocker.

## Package structure

Create:

```text
src/arcadia/events/
├── __init__.py
├── models.py
├── emitter.py
├── sinks.py
└── serialization.py
```

A different internal split is acceptable only when the required public API remains available from `arcadia.events`.

## Required public API

`from arcadia.events import ...` must expose:

```text
EventLevel
ArcadiaEvent
EventSink
SinkFailure
EmitReport
EventEmitter
InMemoryEventSink
CallbackEventSink
JsonlEventSink
make_event
exception_event
dumps_event
loads_event
```

Do not re-export these from `arcadia.__init__`. Plain `import arcadia` must remain lightweight.

## Event model

### `EventLevel`

Use a string enum with:

```python
class EventLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
```

### `ArcadiaEvent`

Use a frozen Pydantic 2 model with behavior equivalent to `extra="forbid"` and `validate_default=True`.

Required fields:

```python
event_id: str
timestamp: datetime
kind: str
level: EventLevel
source: str
message: str
data: dict[str, JsonValue]
run_id: str | None = None
operation_id: str | None = None
error: ArcadiaErrorInfo | None = None
```

Rules:

- `event_id` defaults to a newly generated UUID string and is non-empty.
- `timestamp` defaults to current UTC time.
- supplied timestamps must be timezone-aware and normalize to UTC;
- `kind` is a lowercase dot-delimited identifier such as `service.download.progress`, `analysis.started`, or `artifact.recorded`;
- each kind segment uses letters, digits, and underscores, begins with a letter, and contains no whitespace or controls;
- `source`, `message`, and supplied identifiers are non-empty after trimming;
- `data` contains recursive JSON-compatible values only, rejects non-finite floats and non-string mapping keys, and is defensively copied;
- `error` uses the public `ArcadiaErrorInfo` model;
- the event JSON representation must round-trip without losing enum values, timestamps, identifiers, data, or error information.

Nested JSON values may remain mutable, matching the current domain-model convention. Sinks must never mutate an event.

## Event creation

### `make_event(...)`

Provide a typed convenience function that constructs an `ArcadiaEvent` and accepts all semantic fields while allowing optional caller-supplied `event_id` and `timestamp` for deterministic tests and imported records.

It performs validation only and has no I/O.

### `exception_event(...)`

Create an error event from any `BaseException`.

Required behavior:

- default level is `EventLevel.ERROR`;
- include the exception class name and a complete formatted traceback in `data`;
- preserve caller-provided JSON data without mutating it;
- when the exception is an `ArcadiaError`, use `error.to_info()`;
- for an arbitrary exception, create `ArcadiaErrorInfo` with code `unhandled_exception`, the exception message or class name, and `retryable=False`;
- do not serialize the exception object itself;
- allow explicit run and operation IDs.

## Serialization

### `dumps_event(event)`

Return one compact JSON object without a trailing newline.

Requirements:

- deterministic key ordering;
- preserved Unicode;
- no NaN or infinity;
- typed validation failure for non-`ArcadiaEvent` inputs is not required because the function signature is authoritative, but failures must be clear.

### `loads_event(text)`

Parse one JSON object into `ArcadiaEvent`.

Reject malformed JSON, non-object roots, unknown fields, invalid timestamps, and invalid event values. This low-level parser may raise `ValueError` or Pydantic `ValidationError`; transport-specific typed error translation belongs to later sessions.

## Sink protocol and emitter

### `EventSink`

Define a runtime-checkable protocol:

```python
class EventSink(Protocol):
    def emit(self, event: ArcadiaEvent) -> None: ...
```

A sink may raise. Application modules must publish through `EventEmitter`, which isolates those failures.

### `SinkFailure`

Use an immutable standard-library dataclass containing:

```python
sink_name: str
exception_type: str
message: str
traceback: str
```

It must not retain the exception object.

### `EmitReport`

Use an immutable dataclass containing:

```python
delivered: int
failures: tuple[SinkFailure, ...]
```

Expose convenience properties:

```python
attempted: int
ok: bool
```

### `EventEmitter`

An instance owns an ordered collection of sinks.

Required API:

```python
EventEmitter(sinks: Iterable[EventSink] = ())
add_sink(sink: EventSink) -> None
remove_sink(sink: EventSink) -> bool
emit(event: ArcadiaEvent) -> EmitReport
```

Required behavior:

- preserve sink registration order;
- reject duplicate registration of the same sink object;
- `remove_sink` uses object identity and returns whether removal occurred;
- be safe for concurrent `emit`, `add_sink`, and `remove_sink` calls;
- snapshot the sink list before callbacks so no internal lock is held while invoking external code;
- attempt every registered sink even when an earlier sink fails;
- catch `BaseException` only at this sink-isolation boundary;
- return complete `SinkFailure` records including formatted traceback;
- never raise because a sink failed;
- an emitter with no sinks returns a successful report with zero attempted deliveries;
- do not emit recursive `sink_failed` events automatically.

## Built-in sinks

### `InMemoryEventSink`

Required API:

```python
emit(event: ArcadiaEvent) -> None
snapshot() -> tuple[ArcadiaEvent, ...]
clear() -> None
len(sink) -> int
```

Use a lock so concurrent emission and snapshots are safe. Preserve emission order. Do not mutate events.

### `CallbackEventSink`

Wrap a callable receiving one `ArcadiaEvent`. It contains no failure handling itself; callback failures are isolated by `EventEmitter`.

Validate that the supplied callback is callable.

### `JsonlEventSink`

Append events to a caller-supplied path.

Constructor:

```python
JsonlEventSink(path: str | os.PathLike[str], *, fsync: bool = False)
```

Required behavior:

- validate the path argument at construction without touching the filesystem;
- do not create parent directories;
- on each `emit`, append exactly one UTF-8 JSON object followed by `\n`;
- open in append mode so existing log entries are preserved;
- serialize writes from concurrent threads using a lock;
- flush each event;
- when `fsync=True`, call `os.fsync` after flushing;
- close the file handle after each emission so the sink has no required shutdown lifecycle;
- propagate filesystem and serialization failures to `EventEmitter` for isolation;
- never rotate, truncate, rewrite, or parse the log automatically.

Session 04 will create the parent run directory and decide the JSONL path.

## State and side effects

- `ArcadiaEvent`, helpers, `EventEmitter`, `InMemoryEventSink`, and `CallbackEventSink` perform no filesystem, network, process, model, or GPU work.
- `EventEmitter` and in-memory sinks own instance-local mutable state only.
- `JsonlEventSink.emit()` is the only filesystem side effect.
- The module must not consult environment variables or configuration files.

## Tests required

### Event-model tests

Cover:

- default UUID and UTC timestamp;
- caller-supplied deterministic ID and timestamp;
- timezone normalization and naive timestamp rejection;
- valid and invalid event kinds;
- source, message, run-ID, and operation-ID validation;
- JSON data validation and defensive copying;
- unknown-field rejection;
- `ArcadiaErrorInfo` inclusion;
- complete JSON round trip.

### Exception-event tests

Cover:

- `ArcadiaError` conversion through `to_info()`;
- arbitrary exception conversion to `unhandled_exception`;
- exception type and full traceback in data;
- caller data is preserved and not mutated;
- no exception object enters JSON output.

### Emitter and sink tests

Cover:

- ordered delivery to multiple sinks;
- no-sink reports;
- duplicate registration rejection;
- identity-based removal;
- one failing sink does not block later sinks;
- sink failure includes exception type, message, and traceback;
- catching a `BaseException` subclass at the isolation boundary;
- callback delivery and callback failure;
- in-memory snapshot, clear, length, and order;
- concurrent emissions produce the expected event count without loss.

### JSONL integration tests

Using temporary directories, cover:

- append without truncation;
- one parseable event per line;
- preserved Unicode;
- parent directory is not created automatically;
- concurrent writes produce complete, parseable lines without interleaving;
- `fsync=True` invokes `os.fsync`;
- write failures are returned by `EventEmitter` while another sink still succeeds;
- an existing file remains intact except for successful append operations.

### Package tests

- `import arcadia` does not eagerly import `arcadia.events`.
- `arcadia.events` imports no config, storage, hardware, service, backend, transport, inference, tool, analysis, CLI, UI, or heavy-inference module.
- All Session 01 and Session 02 tests remain unchanged and pass.

## Validation

Run before and after implementation:

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

Install the built wheel in a clean virtual environment and verify:

```python
from arcadia.events import EventEmitter, InMemoryEventSink, make_event

sink = InMemoryEventSink()
emitter = EventEmitter([sink])
report = emitter.emit(make_event(kind="test.started", source="smoke", message="started"))
assert report.ok
assert len(sink) == 1
```

Never claim an unexecuted command passed.

## Definition of done

- [x] Every required public export exists.
- [x] No new runtime dependency was added.
- [x] Events validate and round-trip through JSON.
- [x] Exception events retain complete traceback details without serializing exception objects.
- [x] Sink failures never escape `EventEmitter.emit()`.
- [x] Remaining sinks receive an event after another sink fails.
- [x] In-memory, callback, and JSONL sinks behave as specified.
- [x] Concurrent emission and JSONL writes are tested.
- [x] JSONL logging does not choose or create run directories.
- [x] No service, storage, hardware, transport, inference, tool, analysis, CLI, or UI behavior was added.
- [x] Root import remains lightweight.
- [x] Ruff, mypy, pytest, build, and clean-wheel validation pass.
- [x] This same file contains an honest completion record.
- [x] `docs/sessions/README.md` marks Session 03 completed only after validation succeeds.

## Stop conditions

Stop and record the issue instead of expanding scope if implementation requires changing Session 01 or Session 02 public contracts, adding a runtime dependency, creating run storage, implementing a queue, or repairing unrelated repository code.

---

# Completion record

The implementation agent fills this section before stopping.

## Outcome

Session 03 is complete. `arcadia.events` implements validated event envelopes, exception conversion, deterministic serialization, concurrent sink delivery, and isolated sink failures.

## Files changed

- `src/arcadia/events/__init__.py`
- `src/arcadia/events/models.py`
- `src/arcadia/events/emitter.py`
- `src/arcadia/events/sinks.py`
- `src/arcadia/events/serialization.py`
- `tests/unit/events/__init__.py`
- `tests/unit/events/test_events.py`
- `tests/contract/test_event_serialization.py`
- `tests/integration/test_jsonl_events.py`
- `tests/test_package.py`
- `docs/sessions/03-events-and-structured-logging.md`
- `docs/sessions/README.md`

## Delivered public API

`arcadia.events` exports `EventLevel`, `ArcadiaEvent`, `EventSink`, `SinkFailure`, `EmitReport`, `EventEmitter`, `InMemoryEventSink`, `CallbackEventSink`, `JsonlEventSink`, `make_event`, `exception_event`, `dumps_event`, and `loads_event`. `make_event()` defaults `level` to `EventLevel.INFO`. The root `arcadia` package does not re-export them.

## State and side effects

The event model, event helpers, emitter, in-memory sink, and callback sink own only instance-local memory. `JsonlEventSink.emit()` is the sole filesystem side effect; it appends to the caller-supplied path and never creates parent directories or run directories. No configuration or environment loading occurs.

## Errors and events

`EventEmitter.emit()` catches `BaseException` only around individual sink callbacks, records sink name, exception type, message, and formatted traceback in immutable `SinkFailure` values, and continues with later sinks. `exception_event()` records exception type and traceback while serializing `ArcadiaError` through `to_info()` or using `unhandled_exception` for arbitrary exceptions.

## Tests and validation

Validation completed:

- `python -m pip install -e ".[dev]"` — success
- `ruff format --check .` — 50 files already formatted
- `ruff check .` — success
- `mypy src/arcadia` — success
- `pytest` — 380 passed
- `python -m build` — wheel and sdist built successfully
- Clean virtual environment wheel smoke test — `EventEmitter` delivered one event to `InMemoryEventSink`

## Decisions and deviations

No deviations from the public contract and no runtime dependency changes. The event model uses a local equivalent of the Session 01 Pydantic model configuration rather than importing Session 01 internals.

## Known limitations

No known limitations within Session 03 scope. Log rotation, retention, remote shipping, asynchronous delivery, and run-directory ownership remain intentionally out of scope.

## Assumptions and risks

`arcadia.events` imports only Pydantic and standard-library modules plus public `arcadia.models` error types. JSONL path creation and filesystem errors remain the caller/emitter boundary's responsibility.

## Next-session prerequisites

Session 04 can provide a run directory and pass its JSONL event-log path to `JsonlEventSink`; later service, analysis, tool, storage, and diagnostic modules can publish through `EventEmitter` using the stable event envelope.
