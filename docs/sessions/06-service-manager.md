# Session 06: Service Manager and Backend Contract

- Status: in-progress
- Branch: `session/06-service-manager`
- Owner: local agent session
- Module: `arcadia.services`
- Canonical path: `docs/sessions/06-service-manager.md`

## Objective

Implement the generic, synchronous, thread-safe service lifecycle layer for one compute-node process.

Session 06 must deliver:

- one in-memory service slot per inference port;
- a backend protocol for Sessions 07 and 08;
- ensure, healthy reuse, replacement, explicit health checks, stop, and shutdown;
- same-port lifecycle serialization with independent operations on different ports;
- coherent `ServiceStatus` and `OperationStatus` snapshots;
- runtime resolution through Session 05;
- structured lifecycle events through Session 03;
- bounded diagnostics and service-log access;
- rejection of unmanaged listeners on requested ports;
- best-effort cleanup of manager-owned services;
- no real llama.cpp, SAM3, transport, inference, CLI, or UI implementation.

`ServiceManager` owns generic lifecycle policy and opaque backend instances. Backends own model/file resolution, downloads, process or runtime creation, readiness checks, backend diagnostics, logs, and full process-tree/runtime cleanup.

## Architectural context

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/README.md
docs/sessions/05-hardware-detection-and-runtime-resolution.md
src/arcadia/models/services.py
src/arcadia/models/errors.py
src/arcadia/models/common.py
src/arcadia/events/**
src/arcadia/hardware/**
tests/test_package.py
pyproject.toml
```

Relevant authoritative rules:

- Service identity is node session plus inference port.
- Node service state is in memory only and is not restored or reattached after restart.
- `ServiceManager` is the sole owner of service slots and backend handles.
- The same requested spec on a healthy ready port is reused.
- A different spec on the same port replaces the old service after the old service stops.
- The manager never adopts or kills an unmanaged process.
- Same-port lifecycle operations serialize; different ports may overlap in different caller threads.
- The primary API is synchronous. Future wrappers may invoke it from their own worker threads.
- Transport may call the manager but may not reproduce lifecycle transitions.
- Analysis-time configuration locking belongs to the analysis engine, not this module.

Start from the latest `headless-core`, not a stale Session 05 branch.

## Session workflow

1. Create `session/06-service-manager` from current `headless-core`.
2. Add this file at its canonical path and mark it `in-progress` in the first session commit.
3. Run baseline validation.
4. Implement only this work order.
5. Run focused, full, build, and clean-wheel validation.
6. Fill in the completion record in this same file.
7. Mark Session 06 completed in `docs/sessions/README.md` only after validation succeeds.
8. Do not create a separate prompt, design, or handoff document.

## Scope

### Allowed files

```text
src/arcadia/services/**
tests/unit/services/**
tests/contract/test_service_backend_contract.py
tests/integration/test_service_manager_integration.py
tests/test_package.py
docs/sessions/06-service-manager.md
docs/sessions/README.md
```

Modify `pyproject.toml` only if package discovery genuinely requires it. Add no runtime dependency.

### Prohibited work

Do not implement or modify:

- llama.cpp commands, Hugging Face downloads, launch flags, health endpoints, or process classes;
- SAM3 checkpoint/model loading, Torch, inference, or GPU allocation;
- HTTP schemas, servers, clients, or direct inference clients;
- analysis retry/restart policy, Priority Map, Tool SDK, analysis engine, CLI, Django, or another UI;
- persistent node state, process reattachment, automatic port allocation, model-fit estimates, or resource scheduling;
- background polling, manager-owned worker threads, async APIs, cancellation, or task queues;
- authentication, TLS, or public-network hardening;
- Session 01–05 public contracts unless a blocker is documented and work stops for review.

Do not import `llama_cpp`, Torch, OpenCV, Ultralytics, MLX, Django, FastAPI, Uvicorn, requests, or Priority Map.

## Package structure

```text
src/arcadia/services/
├── __init__.py
├── backend.py
├── models.py
└── manager.py
```

A small private helper module is acceptable. Avoid a large class hierarchy.

Do not re-export this package from `arcadia.__init__`. Root import must remain lightweight.

## Required public API

`from arcadia.services import ...` must expose:

```text
BackendInstance
BackendProgressReporter
ServiceBackend
ServiceDiagnostics
ServiceLogSnapshot
PortInspector
TcpPortInspector
ServiceManager
```

Use the existing Session 01 exceptions rather than duplicating them:

```text
ServiceError
ServiceConflictError
ServiceStartupError
ServiceHealthError
ServiceNotRunningError
```

## Public support models

### `BackendInstance`

Implement an immutable standard-library dataclass:

```python
@dataclass(frozen=True, slots=True)
class BackendInstance:
    endpoint: ServiceEndpoint
    resolved_settings: ResolvedRuntimeSettings
    handle: object
```

The handle is opaque to the manager and must never appear in statuses, diagnostics, logs, events, or transport payloads.

### Diagnostics and logs

Implement Pydantic 2 models using `ModelBase` behavior (`extra="forbid"`, frozen, validated defaults, defensive JSON copies, lossless JSON round trips):

```python
class ServiceDiagnostics(ModelBase):
    port: int
    service_type: ServiceType
    state: ServiceState
    backend_id: str
    details: dict[str, Any] = {}
    updated_at: datetime


class ServiceLogSnapshot(ModelBase):
    port: int
    service_type: ServiceType
    backend_id: str
    text: str
    tail_lines: int
    updated_at: datetime
```

Requirements:

- Validate exact ports and integers, aware UTC timestamps, non-empty backend IDs, and JSON-compatible details.
- `tail_lines >= 0`; `text` may be empty.
- Safe diagnostic details may include PID, exit code, log size/time, cache path, or backend version.
- Never expose secrets, environment dumps, complete command lines, handles, or traceback objects.

## Backend contract

### Progress reporter

```python
@runtime_checkable
class BackendProgressReporter(Protocol):
    def report(
        self,
        *,
        state: ServiceState,
        progress: float | None = None,
        message: str = "",
    ) -> None: ...
```

Rules:

- Start reporters accept only `RESOLVING`, `DOWNLOADING`, and `STARTING`.
- Stop reporters accept only `STOPPING`.
- Backends never report terminal `READY`, `FAILED`, or `STOPPED`.
- Numeric progress must be finite and within `0.0..1.0`.
- Invalid reports fail the operation with `ServiceError(code="service_progress_invalid")`.
- Messages must be concise and sanitized.

### Backend protocol

```python
@runtime_checkable
class ServiceBackend(Protocol):
    @property
    def backend_id(self) -> str: ...

    def start(
        self,
        spec: ServiceSpec,
        resolved_settings: ResolvedRuntimeSettings,
        progress: BackendProgressReporter,
    ) -> BackendInstance: ...

    def check_health(self, instance: BackendInstance) -> None: ...

    def stop(
        self,
        instance: BackendInstance,
        progress: BackendProgressReporter,
    ) -> None: ...

    def diagnostics(self, instance: BackendInstance) -> Mapping[str, Any]: ...

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str: ...
```

Backend requirements:

- `backend_id` is stable and non-empty, for example `llama_cpp` or `sam3`.
- `start` may synchronously resolve/download assets and launch a service, but must not mutate its inputs.
- `check_health` returns normally only when the instance is usable.
- `stop` is idempotent for an already-exited manager-owned instance.
- Process backends terminate their complete owned process tree using platform-appropriate containment. Session 06 defines this requirement; later backend sessions implement it.
- A backend never terminates a process it did not create and return in a `BackendInstance`.
- `diagnostics` and `read_logs` are bounded, read-only, and safe while the service is running or after it stopped.
- `read_logs` returns at most the requested final logical lines and replaces decoding errors.
- Backend-raised `ServiceError` values pass through after manager recording; arbitrary exceptions are translated at the manager boundary.

## Port inspection

```python
@runtime_checkable
class PortInspector(Protocol):
    def is_in_use(self, port: int) -> bool: ...


class TcpPortInspector:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        timeout_seconds: float = 0.2,
    ) -> None: ...

    def is_in_use(self, port: int) -> bool: ...
```

Requirements:

- Standard library only; validate host, exact port, and finite positive timeout.
- Import and construction perform no probe.
- Perform a bounded local TCP-listener probe.
- A positive probe without a manager-owned live service raises `ServiceConflictError(code="service_port_in_use")` before backend start.
- Probe failure fails closed with `ServiceConflictError(code="service_port_probe_failed")`.
- This preflight does not remove bind races; backend bind failures remain authoritative.
- Never adopt a responding listener as an ARCADIA service.

## `ServiceManager`

### Construction

Use a constructor equivalent to:

```python
class ServiceManager:
    def __init__(
        self,
        *,
        hardware: HardwareCapabilities,
        backends: Mapping[ServiceType, ServiceBackend],
        event_emitter: EventEmitter | None = None,
        port_inspector: PortInspector | None = None,
        clock: Callable[[], datetime] | None = None,
        operation_id_factory: Callable[[], str] | None = None,
        register_atexit: bool = True,
    ) -> None: ...
```

Construction must:

- validate and detach the hardware snapshot and backend mapping;
- allow one backend object to serve both `LLM` and `VISUAL_LLM`;
- reject invalid keys, objects, or empty backend IDs;
- default to an empty `EventEmitter`, `TcpPortInspector`, aware UTC clock, and UUID4 operation IDs;
- start no service, thread, hardware detection, or port probe;
- optionally register one weak-reference `atexit` cleanup callback;
- install no global signal handler.

### Public methods

```python
@property
def hardware(self) -> HardwareCapabilities: ...

@property
def is_closed(self) -> bool: ...

def ensure_service(self, spec: ServiceSpec) -> ServiceStatus: ...

def stop_service(self, port: int) -> ServiceStatus: ...

def check_health(self, port: int) -> ServiceStatus: ...

def get_status(self, port: int) -> ServiceStatus: ...

def list_statuses(self) -> tuple[ServiceStatus, ...]: ...

def get_operation(self, operation_id: str) -> OperationStatus: ...

def list_operations(self, port: int | None = None) -> tuple[OperationStatus, ...]: ...

def get_diagnostics(self, port: int) -> ServiceDiagnostics: ...

def get_logs(self, port: int, *, tail_lines: int = 200) -> ServiceLogSnapshot: ...

def shutdown(self) -> tuple[ServiceStatus, ...]: ...

def __enter__(self) -> ServiceManager: ...

def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
```

Every public result is a fresh validated snapshot. Never expose private records, locks, mappings, or handles.

## Lifecycle requirements

### Operation records

Every non-no-op ensure, reuse health check, explicit health check, stop, replacement, and shutdown stop creates an `OperationStatus`.

- Create `PENDING`, immediately move to `RUNNING`, then finish `SUCCEEDED` or `FAILED`.
- `ServiceStatus.operation_id` identifies the active or most recent operation for the slot.
- Timestamps are aware UTC and non-decreasing.
- Terminal failures store `ArcadiaError.to_info()`.
- History is in-memory and creation-ordered; port filtering preserves order.
- Unknown IDs raise `ServiceError(code="service_operation_not_found")`.

### Ensure an unused or stopped port

Under the per-port lifecycle lock:

1. Reject a closed manager and validate the public `ServiceSpec` instance.
2. Select the backend for `spec.service_type`; missing mapping raises `ServiceStartupError(code="service_backend_unavailable")`.
3. Reject an unmanaged listener.
4. Record `RESOLVING` and call `resolve_runtime_settings(spec, hardware)` without mutating inputs.
5. Call backend `start` with a start-only progress reporter.
6. Validate the `BackendInstance`: endpoint port/type match the spec and returned backend name matches initial resolution.
7. Call backend `check_health` once.
8. Record `READY`, endpoint, final resolved settings, and `started_at`.

Invalid backend results raise `ServiceStartupError(code="service_backend_contract_invalid")`.

### Reuse the same specification

When the slot is `READY` and `requested_spec == spec`:

- call backend `check_health` under the port lock;
- on success, do not stop or start, preserve original `started_at`, complete the operation, and emit `service.reused`;
- on failure, record `FAILED`, hide the endpoint, retain the instance for cleanup/diagnostics, and raise `ServiceHealthError`.

### Replace a different specification

Hold the port lock for the complete replacement:

1. Stop the current manager-owned live/failed instance first.
2. Keep the old spec and handle authoritative until stop succeeds.
3. If stop fails, do not call the new backend.
4. After successful stop, record `STOPPED` and provision the new spec normally.
5. Do not roll back or restart the old service if the new start fails.
6. A failed new start leaves `FAILED` with the new requested spec and no endpoint.

Replacement must support a change of service type and backend.

### Stop

- Unknown port: `ServiceNotRunningError(code="service_not_managed")`.
- Already stopped: idempotent no-op returning a fresh snapshot.
- Live/failed-owned instance: `STOPPING` -> backend `stop` -> `STOPPED`.
- `STOPPED` exposes no endpoint and has no live ownership.
- Retain the latest stopped instance only for bounded diagnostics/log access until a new instance replaces it or the manager object is released.
- Stop failure records `FAILED`, hides the endpoint, retains the instance for another cleanup attempt, and raises the backend error or `ServiceError(code="service_stop_failed")`.

### Health

- Unknown or non-ready slots raise `ServiceNotRunningError(code="service_not_ready")`.
- A successful check preserves `READY` and original `started_at`.
- A failed check records `FAILED`, hides the endpoint, retains the instance, and raises `ServiceHealthError`.
- No automatic polling or restart occurs.

### Diagnostics and logs

- Unknown port: `ServiceNotRunningError(code="service_not_managed")`.
- `get_diagnostics` returns authoritative generic state and merges fresh backend details when an instance exists.
- Backend details cannot overwrite model-level port/type/state/backend fields.
- `get_logs` accepts exact `tail_lines` from `1` through `5000`.
- No created instance: `ServiceNotRunningError(code="service_logs_unavailable")`.
- Snapshot the instance under the registry lock, release the lock, then call the backend without the lifecycle lock so reads can overlap backend I/O.
- Arbitrary failures become `service_diagnostics_failed` or `service_logs_failed` `ServiceError`s.
- These reads create no operation and change no lifecycle state.

### Failure translation

- Preserve backend-raised `ServiceError` values after recording them.
- Arbitrary start: `ServiceStartupError(code="service_startup_failed")`.
- Arbitrary health: `ServiceHealthError(code="service_health_failed")`.
- Arbitrary stop: `ServiceError(code="service_stop_failed")`.
- Retain the original exception as `cause`.
- Details may contain only safe values such as port, service type, backend ID, and exception type.
- Never include environment values, handles, raw command lines/output, arbitrary file contents, or tracebacks in statuses or events.

### Shutdown

`shutdown()` permanently closes the manager:

1. Atomically mark it closing so no new lifecycle operation begins.
2. Process managed ports in ascending order, one port lock at a time.
3. Naturally wait for an already-running operation by acquiring its port lock.
4. Attempt every remaining live or failed-owned stop even after individual failures.
5. Mark closed and unregister `atexit`.
6. Return final statuses when all stops succeed.
7. After all attempts, raise `ServiceError(code="service_shutdown_incomplete")` when any stop failed; details contain only failed ports and stable error codes.

Additional rules:

- A second shutdown is idempotent.
- Lifecycle calls after shutdown raise `ServiceError(code="service_manager_closed")`.
- Status, operation, diagnostics, and logs remain readable after shutdown.
- The `atexit` callback performs the same best-effort cleanup but suppresses escaping exceptions.
- No guarantee is possible for `SIGKILL`, machine loss, or forced interpreter termination; backend process containment remains required.
- `__exit__` calls shutdown. It must not replace an exception already active in the context with a cleanup exception.

## State and concurrency

The manager owns an immutable hardware snapshot, a detached backend map, private slot records, current/retained backend instances, operation history, a registry lock, one lifecycle lock per port, and closing/closed state.

Requirements:

- All public methods are thread-safe.
- Same-port lifecycle calls fully serialize.
- Different ports may overlap when called from different threads.
- Status/operation reads run while backend I/O is active.
- Diagnostic/log reads do not take the lifecycle lock.
- Never hold the registry lock while calling port inspection, resolution, backend methods, event sinks, or user-provided clock/ID functions.
- Normal lifecycle operations acquire only one port lock.
- Event-sink failure never changes lifecycle outcome.
- Introduce no background thread, async lock, or global mutable singleton.

Required invariants:

- At most one current or retained `BackendInstance` exists per port.
- Only the backend that created an instance receives it for health, stop, diagnostics, or logs.
- The slot backend/instance changes only after successful old-instance stop.
- A failed health or stop never leaves an advertised ready endpoint.
- An unmanaged listener is never reused or terminated.
- Requested specs, resolved settings, and hardware inputs are never mutated.
- Public snapshots are detached and validation-backed.
- Service and operation failure records use the same error code.

## Status rules

Use existing `ServiceStatus` and `OperationStatus` without modification.

- `READY`: endpoint, requested spec, resolved settings, no error, and `started_at`.
- `FAILED`: typed error and no advertised endpoint.
- `STOPPED`: no endpoint and no error; prior spec/settings may remain for diagnostics.
- Endpoint, spec, status port, and service type always agree.
- `updated_at` changes on visible transitions/progress.
- Reuse preserves service `started_at`; replacement gets a new one only when ready.
- Status lists are ordered by ascending port.

## Structured events

Use source:

```text
arcadia.services.ServiceManager
```

Emit stable kinds:

```text
service.operation.started
service.operation.progress
service.state.changed
service.reused
service.operation.succeeded
service.operation.failed
service.shutdown.started
service.shutdown.completed
service.shutdown.incomplete
```

Requirements:

- Operation events include `operation_id`.
- Data is JSON-safe and includes applicable port, service type, backend ID, old/new state, and progress.
- Failures use `EventLevel.ERROR` and attach `ArcadiaErrorInfo`.
- Normal transitions use `INFO`; detailed progress may use `DEBUG`.
- Do not repeat the full service spec in every event.
- Per-operation event order matches observable state order.
- Use `EventEmitter`; sink failures remain isolated.

## Explicit non-goals

Session 06 does not provide:

- a real backend;
- process/log-capture implementation;
- autonomous crash detection or restart counters;
- automatic replacement after health failure;
- background operation submission, cancellation, or pause/resume;
- remote node operations or inference requests;
- saved profiles, persistent history, dynamic backend registration, or free-port selection.

## Tests required

### Unit tests

Use deterministic fake backends, handles, clock, operation IDs, port inspector, and event sink. Cover:

- import/construction side-effect boundaries and dependency detachment;
- constructor validation;
- successful ensure and exact state/event order;
- real Session 05 resolution invocation and input non-mutation;
- missing backend, unmanaged port, and failed port probe;
- invalid backend results and typed/arbitrary backend failures;
- healthy reuse without stop/start and failed reuse health;
- replacement order, cross-backend replacement, stop failure, start failure, and no rollback;
- stop success, stopped no-op, unknown port, and stop failure;
- health success/failure;
- progress state/value validation;
- operation history, filtering, timestamps, errors, and unknown IDs;
- diagnostics/logs, bounds, stopped access, and error translation;
- detached status/model snapshots and ordering;
- event-sink failure isolation;
- same-port serialization with a blocking fake;
- different-port overlap with caller threads;
- shutdown ordering, cleanup continuation, aggregate failure, closure, and idempotence;
- post-shutdown reads and lifecycle rejection;
- context cleanup and preservation of an active context exception;
- weak-reference `atexit` registration/unregistration without real child processes.

### Contract tests

Create a reusable behavioral suite for fake and future real backends. Verify:

- stable backend ID;
- no input mutation;
- endpoint/spec and resolved-backend agreement;
- health behavior and idempotent stop;
- allowed progress states;
- bounded JSON diagnostics and logs;
- no handle leakage through public models or events.

Structure it so Sessions 07 and 08 can run their backends through the same contract.

### Integration tests

Combine real Session 01, 03, and 05 modules with a lightweight fake backend:

- synthetic CUDA, Metal, and CPU snapshots;
- actual runtime resolution through the manager;
- actual `EventEmitter` and memory sink;
- ensure, reuse, replacement, failed health, logs/diagnostics, stop, and shutdown;
- JSON round trips for status, operation, diagnostics, logs, event, and resolved settings;
- no real model, GPU, subprocess, listener, or external network dependency.

### Package tests

Extend `tests/test_package.py` to verify:

- `import arcadia` does not import `arcadia.services`;
- `import arcadia.services` imports no heavy/future backend package;
- import starts no thread, process, port probe, or hardware detection;
- the built wheel contains the package and public imports work cleanly.

## Validation

Run and record exact results:

```bash
python -m pip install -e ".[dev]"
ruff format --check src/arcadia/services tests/unit/services tests/contract/test_service_backend_contract.py tests/integration/test_service_manager_integration.py tests/test_package.py
ruff check src/arcadia/services tests/unit/services tests/contract/test_service_backend_contract.py tests/integration/test_service_manager_integration.py tests/test_package.py
mypy src/arcadia
pytest tests/unit/services tests/contract/test_service_backend_contract.py tests/integration/test_service_manager_integration.py tests/test_package.py
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

Clean-wheel smoke test in a new temporary virtual environment:

1. Install the built wheel without editable source access.
2. Import `arcadia.services`.
3. Construct synthetic CPU hardware, a fake backend, and a fake free-port inspector.
4. Ensure, inspect diagnostics/logs, reuse, stop, and shut down one service.
5. Verify JSON round trips for all public snapshots.
6. Confirm no heavy package was imported.

Never claim an unexecuted command passed.

## Definition of done

- [ ] Required public API exists and root import remains lightweight.
- [ ] No runtime dependency is added.
- [ ] Construction starts no service, thread, hardware probe, or port probe.
- [ ] Backend contract supports future llama.cpp and SAM3 implementations.
- [ ] Ensure, reuse, replacement, health, stop, diagnostics/logs, and shutdown are deterministic.
- [ ] Same-port operations serialize; different ports can overlap.
- [ ] Unmanaged listeners are rejected and never adopted or terminated.
- [ ] Session 05 resolution is used without mutating inputs.
- [ ] Status and operation snapshots remain coherent through failures.
- [ ] Handles never cross public boundaries.
- [ ] Events are emitted and sink failures are isolated.
- [ ] Shutdown attempts every owned service and reports aggregate failure honestly.
- [ ] No real backend, transport, inference, CLI, or UI code is introduced.
- [ ] Focused/full tests, Ruff, mypy, build, and clean-wheel validation pass.
- [ ] This file contains an honest completion record.
- [ ] Session index is updated only after completion.

## Stop conditions

Stop and record the issue rather than expanding scope if implementation requires changing Session 01 service/status/error models, Session 03 event contracts, or Session 05 resolution contracts; adding a runtime dependency; implementing a real backend; introducing async/background workers; persisting node state; moving lifecycle logic into transport; or weakening failure/package-isolation guarantees.

A partial implementation with an accurate record is preferable to an undocumented contract change.

---

# Completion record

The implementation agent fills this section before stopping and changes the top status to `completed`, `partial`, or `blocked`.

## Outcome

Not yet implemented.

## Files changed

Not yet implemented.

## Delivered public API

Not yet implemented.

## State and side effects

Not yet implemented.

## Errors and events

Not yet implemented.

## Tests and validation

Not yet implemented. Record exact commands and results; never claim an unexecuted command passed.

## Decisions and deviations

Not yet implemented.

## Known limitations

Not yet implemented.

## Assumptions and risks

Not yet implemented.

## Next-session prerequisites

Session 07 should receive a stable `ServiceBackend` contract and a tested `ServiceManager` capable of hosting a llama.cpp backend without owning backend-specific process, model, or download logic.
