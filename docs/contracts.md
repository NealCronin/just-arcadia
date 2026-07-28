# ARCADIA Module Contracts

## 1. Purpose

This document defines how independently developed ARCADIA modules must interact.

Each major module is expected to be designed and implemented in one focused development session. Stable contracts and strict dependency direction are therefore necessary to prevent later sessions from rebuilding or bypassing earlier work.

## 2. General module requirements

Every module must document:

- its purpose;
- its public API;
- the state it owns;
- accepted inputs;
- returned outputs;
- events it emits;
- errors it raises;
- external side effects;
- allowed dependencies;
- thread-safety or concurrency assumptions;
- test strategy;
- known limitations.

A module is incomplete until both its successful behavior and its failure behavior are tested.

## 3. Dependency direction

The intended dependency direction is:

```text
models
  ↑
config / events / storage / hardware
  ↑
services / backend implementations
  ↑
transport / direct inference clients
  ↑
tool SDK and tool integrations
  ↑
analysis engine
  ↑
CLI and future UI wrappers
```

A module may directly depend only on modules shown above it in this diagram.
For example, services may import models, events, hardware, and configuration;
models may not import services.

A module must not import modules shown below it.

When a lower-level module needs behavior supplied by a higher-level module,
the lower-level or neutral layer must define a protocol that is provided
through dependency injection.

### Prohibited dependencies

- `arcadia.models` must not import HTTP, subprocess, filesystem, UI, or heavy inference libraries.
- `arcadia.config` must not import service backends or tools.
- `arcadia.events` must not depend on a UI.
- `arcadia.storage` must not start services or perform inference.
- `arcadia.hardware` must not mutate service configuration.
- `arcadia.services` must not import Priority Map or the analysis engine.
- backend implementations must not import the CLI or UI.
- transport routes must not contain service-provisioning logic.
- inference clients must not configure or start services.
- tool integrations must not own global service state.
- the analysis engine must not import Django, FastAPI route modules, or backend-specific implementation classes directly.
- wrappers must not duplicate core behavior.

## 4. Import contract

A base installation and the following statement must remain lightweight:

```python
import arcadia
```

Importing the base package must not automatically import:

- Django;
- FastAPI or Uvicorn;
- OpenCV;
- Torch;
- Ultralytics;
- llama-cpp-python;
- Priority Map.

Heavy or platform-specific dependencies must be loaded lazily within the module that owns them and exposed through optional dependency groups.

## 5. Data contract

Cross-module inputs and outputs must use one of:

- immutable or validation-backed domain models;
- documented standard-library values;
- typed protocols;
- explicitly documented JSON-compatible payloads at a transport boundary.

Modules must not communicate through undocumented dictionaries whose available keys depend on execution history.

Requested configuration and resolved runtime state are different objects. A resolver must never mutate the requested object in place.

## 6. State contract

State must have one clear owner.

### Allowed examples

- ServiceManager owns service slots and process handles.
- AnalysisEngine owns the active analysis state.
- RunStore owns run metadata and artifact records.
- A Priority Map tool instance owns frame-processing state.

### Prohibited examples

- a Django view and a service manager both updating the same service dictionary;
- several modules mutating a process-global runtime singleton;
- a tool changing saved application configuration during execution;
- a transport client treating cached remote status as authoritative runtime state.

Global mutable state is prohibited unless it is intentionally encapsulated inside one owning object and its lifecycle is explicit.

## 7. Side-effect contract

A module must state whether it performs any of these side effects:

- filesystem reads or writes;
- network requests;
- listening sockets;
- subprocess creation;
- model loading;
- GPU allocation;
- event emission;
- sleeping or retry delays.

Pure schema and domain modules must have no external side effects.

Side effects should occur at narrow boundaries that can be replaced with fakes during tests.

## 8. Error contract

Errors crossing a module boundary must be typed ARCADIA exceptions with:

- a stable error code;
- a human-readable summary;
- optional structured details;
- the original cause where useful;
- an indication of whether the failure is retryable.

Internal library exceptions may be retained as causes but should not be the only API exposed to higher layers.

Broad exception handling is acceptable only at boundaries that must translate or record arbitrary failures, such as:

- process entry points;
- HTTP route boundaries;
- analysis-run boundaries;
- event-sink isolation.

When catching a broad exception, the code must record the original traceback before returning a typed failure.

## 9. Event contract

Long-running or externally observable operations must report progress through structured events.

Every event must contain:

- UTC timestamp;
- event kind;
- severity level;
- source;
- message;
- structured data;
- a run ID or operation ID when applicable.

Modules must not depend on a specific presentation layer. Event sinks may later include:

- JSONL files;
- callbacks;
- a CLI renderer;
- a web event stream;
- in-memory test collectors.

An event-sink failure must not crash the operation that emitted the event.

## 10. Service contract

A service backend is responsible for backend-specific behavior such as model resolution, launch, health checks, and termination.

A service manager is responsible for generic port ownership, lifecycle serialization, replacement, reuse, and shutdown.

Transport routes may call the service manager but may not reproduce its state transitions.

A service manager must expose effective state rather than UI-oriented labels.

Service identity is scoped to:

```text
node session + inference port
```

A node does not persist or restore service state across process restarts.

## 11. Local and remote node contract

Local and remote compute access must present equivalent high-level operations, including:

- capabilities;
- ensure service;
- service status;
- operation progress;
- diagnostics;
- logs;
- replace the service assigned to a port;
- stop all owned services during node shutdown.

A local implementation may call a ServiceManager directly. A remote implementation may use HTTP. Higher layers must not branch on local versus remote for pipeline semantics.

Inference does not pass through the instruction interface. Direct inference clients target the provisioned endpoint.

## 12. Tool contract

A tool owns its fixed internal stage order.

A tool receives a context containing only the capabilities it needs, such as:

- input location;
- run output directory;
- configured inference endpoints;
- event sink;
- artifact recorder;
- cancellation token;
- validated tool settings.

A tool may publish artifacts and events. It may not:

- configure nodes itself unless that behavior is explicitly delegated through the context;
- mutate global application settings;
- write outside its run directory without an explicit user-selected path;
- import a UI framework;
- hide failed model inference behind mock output.

## 13. Analysis-engine contract

The analysis engine coordinates modules but should contain minimal domain-specific processing.

It must:

- enforce one active analysis;
- freeze effective configuration for the run;
- create run storage;
- provision required services;
- record requested and resolved settings;
- invoke the tool;
- stop downstream execution on failure;
- preserve partial artifacts;
- leave successfully hosted services running after the run;
- finalize a reproducibility record.

It must not implement Priority Map stages or backend launch details.

## 14. Wrapper contract

A CLI, Django application, desktop UI, or notebook integration is a presentation layer.

A wrapper may:

- gather user input;
- call public ARCADIA APIs;
- subscribe to events;
- display status and artifacts.

A wrapper may not:

- own service processes;
- calculate backend flags;
- implement retries;
- download models;
- run pipeline loops;
- store an alternative authoritative analysis state.

## 15. Concurrency contract

Initial concurrency rules:

- one active analysis per orchestrator process;
- sequential tool stages;
- operations affecting the same service port are serialized;
- unrelated service ports may start independently;
- one SAM model instance processes inference serially;
- LLM concurrency is delegated to the configured inference server.

A module introducing background threads or asynchronous execution must own and document their shutdown behavior.

The synchronous Python API is the primary contract where practical. Wrappers may place synchronous operations in background tasks for presentation.

## 16. Configuration-change contract

Saved configuration may be edited only when no analysis is running.

An analysis receives an immutable snapshot of its effective configuration. No module may silently reread and apply changed configuration during the run.

## 17. Testing contract

### Unit tests

Test one module using fakes for network, process, clock, model, and filesystem boundaries as appropriate.

### Contract tests

Verify that multiple implementations expose equivalent behavior, especially:

- local and remote node clients;
- fake and real service backends;
- event sinks;
- artifact stores.

### Integration tests

Combine several real modules with lightweight fixtures. Large model downloads and real GPUs are not required in standard CI.

### Hardware smoke tests

CUDA and Metal validation may run manually or on self-hosted systems. These tests must be clearly separated from ordinary CI.

Tests must not rely on repository-root imports. The package must be installed before test execution.

## 18. Public API change policy

A session must not silently change an earlier module's public contract.

When a contract change is necessary, the session must:

1. explain the need in its handoff;
2. update the relevant contract documentation;
3. update the owning module's tests;
4. add or amend an architecture decision record when the change affects system behavior;
5. identify downstream modules that need updates.

## 19. Session ownership policy

Each major module is assigned to one primary development session.

That session may modify:

- its own module;
- its own tests;
- its handoff document;
- minimal shared declarations explicitly granted by the session prompt.

Unrelated refactors are prohibited. Temporary compatibility code must be labeled and documented rather than hidden.
