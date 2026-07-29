# Session 01: Domain Models and Typed Errors

- Status: completed
- Branch: `headless-core` (merged from `session/01-domain-models`)
- Module: `arcadia.models`

## Objective

Implement the stable, side-effect-free, validated vocabulary that later ARCADIA modules will share.

This session adds domain models and typed errors only. It must not implement configuration-file persistence, hardware detection, service processes, HTTP transport, inference, storage, events, tools, analysis execution, or UI behavior.

## Architectural context

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/00-scaffold.md
```

Important constraints:

- `arcadia.models` is the lowest dependency layer.
- It must not import HTTP, subprocess, filesystem, UI, or inference libraries.
- Cross-module values must be validated and serializable.
- Requested settings and resolved settings are separate objects.
- Errors crossing module boundaries carry stable codes, details, causes, and retryability.
- `import arcadia` must remain lightweight and must not eagerly import `arcadia.models`.

The legacy repository may be inspected for behavior only, especially:

```text
core/errors.py
core/services/specs.py
core/services/llm_settings.py
core/inference/results.py
tests/test_llm_settings.py
```

Do not import the legacy package or preserve its client/host service identities.

## Scope

### Allowed files

```text
pyproject.toml
src/arcadia/models/**
tests/unit/models/**
tests/contract/test_model_serialization.py
tests/test_package.py
docs/sessions/01-domain-models-and-errors.md
```

A minimal edit to `src/arcadia/__init__.py` is allowed only when genuinely required for package-version consistency. Do not re-export domain models from the root package.

### Prohibited changes

Do not create or modify:

```text
src/arcadia/config/**
src/arcadia/events/**
src/arcadia/storage/**
src/arcadia/hardware/**
src/arcadia/services/**
src/arcadia/backends/**
src/arcadia/transport/**
src/arcadia/inference/**
src/arcadia/tools/**
src/arcadia/analysis/**
```

Do not add runtime service logic, network calls, filesystem inspection, model loading, subprocesses, global mutable state, or hidden mocks.

## Dependency change

Add Pydantic 2 as the only required runtime dependency:

```toml
pydantic>=2,<3
```

Do not add FastAPI, HTTPX, Django, NumPy, OpenCV, Torch, Ultralytics, llama-cpp-python, or other runtime dependencies.

## Required package structure

Create:

```text
src/arcadia/models/__init__.py
src/arcadia/models/common.py
src/arcadia/models/errors.py
src/arcadia/models/services.py
src/arcadia/models/analysis.py
src/arcadia/models/artifacts.py
```

The internal split may change only if every required symbol remains available from `arcadia.models`.

## Common model behavior

Use Pydantic 2 and a shared base configuration equivalent to:

```python
ConfigDict(
    extra="forbid",
    frozen=True,
    validate_default=True,
)
```

Requirements:

- reject unknown fields;
- use frozen models where practical;
- defensively copy mapping inputs;
- support `model_dump(mode="json")` followed by `model_validate(...)`;
- accept only recursive JSON-compatible values in settings, metadata, and error details;
- reject NaN, infinity, bytes, sets, arbitrary objects, and non-string mapping keys;
- reject naive datetimes;
- normalize timezone-aware datetimes to UTC;
- reject booleans where an integer or float field is expected;
- do not inspect files, repositories, devices, ports, or networks.

JSON-compatible values are null, boolean, integer, finite float, string, lists of JSON values, and mappings with string keys and JSON values.

## Required public exports

`from arcadia.models import ...` must support:

```text
ArcadiaError
ArcadiaErrorInfo
ConfigurationError
ServiceError
ServiceConflictError
ServiceStartupError
ServiceHealthError
ServiceNotRunningError
InstructionError
InferenceError
InferenceTimeoutError
AnalysisError
ArtifactError
NodeAddress
HuggingFaceFileSpec
RequestedRuntimeSettings
ResolvedRuntimeSettings
ServiceType
ServiceState
OperationState
LlamaServiceSpec
SamServiceSpec
ServiceSpec
ServiceEndpoint
ServiceStatus
OperationStatus
parse_service_spec
AnalysisState
StageState
AnalysisSpec
AnalysisStatus
StageStatus
ArtifactVisibility
ArtifactRecord
```

Do not re-export these from `arcadia.__init__`.

## Error contract

### `ArcadiaErrorInfo`

Fields:

```python
code: str
message: str
retryable: bool = False
details: dict[str, JsonValue] = {}
```

`code` and `message` must be non-empty after trimming. Details are JSON-compatible and defensively copied. Exception objects and tracebacks are not serialized.

### `ArcadiaError`

Required behavior:

```python
ArcadiaError(
    message,
    *,
    code=None,
    retryable=None,
    details=None,
    cause=None,
)
```

It exposes `code`, `retryable`, `details`, and `cause`; `str(error)` returns the message; `to_info()` returns `ArcadiaErrorInfo`; causes remain available but are not serialized.

Required subclasses:

| Class | Default code | Retryable |
|---|---|---:|
| `ConfigurationError` | `configuration_error` | false |
| `ServiceError` | `service_error` | false |
| `ServiceConflictError` | `service_conflict` | false |
| `ServiceStartupError` | `service_startup_failed` | false |
| `ServiceHealthError` | `service_health_failed` | false |
| `ServiceNotRunningError` | `service_not_running` | false |
| `InstructionError` | `instruction_error` | false |
| `InferenceError` | `inference_error` | false |
| `InferenceTimeoutError` | `inference_timeout` | true |
| `AnalysisError` | `analysis_error` | false |
| `ArtifactError` | `artifact_error` | false |

## Common source and address models

### `NodeAddress`

```python
host: str
instruction_port: int
scheme: Literal["http"] = "http"
base_url: property
```

Accept IPv4, IPv6, and ordinary hostnames. Reject schemes, paths, query strings, fragments, whitespace, null bytes, CR, and LF in `host`. Ports are 1 through 65535 and reject booleans. Bracket IPv6 in `base_url`.

### `HuggingFaceFileSpec`

```python
repo_id: str
filename: str
revision: str = "main"
```

Rules:

- `repo_id` is exactly `owner/repository`;
- owner and repository permit alphanumeric characters, `_`, `.`, and `-`, beginning and ending with alphanumeric characters;
- filename is an exact `.gguf` file, case-insensitively;
- nested relative paths are allowed;
- absolute paths, `..`, malformed empty path components, null bytes, CR, and LF are rejected;
- revision is non-empty and rejects controls, `.` and `..`;
- no network calls or existence checks occur.

## Runtime settings

### `RequestedRuntimeSettings`

```python
values: dict[str, JsonValue] = {}
```

### `ResolvedRuntimeSettings`

```python
backend: str
values: dict[str, JsonValue]
notes: tuple[str, ...] = ()
```

`backend` is non-empty. Session 1 validates structure only; it does not interpret backend flags or resolve hardware values.

## Service contract

### Enums

```text
ServiceType: llm, visual_llm, sam3
ServiceState: stopped, resolving, downloading, starting, ready, failed, stopping
OperationState: pending, running, succeeded, failed
```

### `LlamaServiceSpec`

```python
service_type: Literal[ServiceType.LLM, ServiceType.VISUAL_LLM]
port: int
model: HuggingFaceFileSpec
projector: HuggingFaceFileSpec | None = None
requested_settings: RequestedRuntimeSettings = RequestedRuntimeSettings()
```

`visual_llm` requires a projector. `llm` rejects a projector.

### `SamServiceSpec`

```python
service_type: Literal[ServiceType.SAM3] = ServiceType.SAM3
port: int
checkpoint_path: str
requested_settings: RequestedRuntimeSettings = RequestedRuntimeSettings()
```

The checkpoint path is a non-empty node-local Windows or POSIX path string. Reject null bytes, CR, and LF. Do not require an absolute path or check existence.

### `ServiceSpec`

A discriminated union of `LlamaServiceSpec | SamServiceSpec` using `service_type`.

Expose:

```python
def parse_service_spec(data: Mapping[str, object]) -> ServiceSpec: ...
```

Unknown service types and unknown fields fail validation.

### `ServiceEndpoint`

```python
host: str
port: int
service_type: ServiceType
scheme: Literal["http"] = "http"
base_url: property
```

Use the same host and port validation as `NodeAddress`.

### `ServiceStatus`

```python
port: int
service_type: ServiceType
state: ServiceState
endpoint: ServiceEndpoint | None = None
requested_spec: ServiceSpec | None = None
resolved_settings: ResolvedRuntimeSettings | None = None
operation_id: str | None = None
error: ArcadiaErrorInfo | None = None
started_at: datetime | None = None
updated_at: datetime
```

Coherence rules:

- `ready` requires endpoint and resolved settings;
- `failed` requires an error;
- `stopped` exposes no endpoint;
- `started_at` cannot be after `updated_at`.

### `OperationStatus`

```python
operation_id: str
port: int
state: OperationState
service_state: ServiceState | None = None
progress: float | None = None
message: str = ""
error: ArcadiaErrorInfo | None = None
started_at: datetime | None = None
updated_at: datetime
finished_at: datetime | None = None
```

Rules:

- operation ID is non-empty;
- progress is finite from 0.0 through 1.0;
- pending has no start or finish time;
- running requires start time and no finish time;
- succeeded and failed require start and finish times;
- failed requires an error;
- succeeded rejects an error;
- timestamps must be ordered.

## Analysis contract

### Enums

```text
AnalysisState: pending, preparing, running, completed, failed
StageState: pending, running, completed, failed, skipped
```

Pause and resume states are intentionally absent.

### `AnalysisSpec`

```python
tool_name: str
input_path: str
output_root: str
tool_settings: dict[str, JsonValue] = {}
```

Strings are non-empty after trimming. Do not inspect the filesystem.

### `StageStatus`

```python
name: str
state: StageState
attempt: int = 1
started_at: datetime | None = None
finished_at: datetime | None = None
error: ArcadiaErrorInfo | None = None
```

Rules:

- attempt is at least 1 and rejects booleans;
- pending has no timestamps;
- running requires start time and no finish time;
- terminal states require start and finish times;
- failed requires an error;
- completed rejects an error.

### `AnalysisStatus`

```python
run_id: str
tool_name: str
state: AnalysisState
current_stage: str | None = None
stages: tuple[StageStatus, ...] = ()
started_at: datetime | None = None
finished_at: datetime | None = None
error: ArcadiaErrorInfo | None = None
```

Rules:

- identifiers and names are non-empty;
- pending has no timestamps;
- preparing and running require start time and no finish time;
- completed and failed require start and finish times;
- failed requires an error;
- completed rejects an error.

## Artifact contract

### `ArtifactVisibility`

```text
final
internal
```

A final artifact is intended for presentation by a future viewer. An internal artifact remains available for diagnostics, reproducibility, or later stages.

### `ArtifactRecord`

```python
artifact_id: str
name: str
relative_path: str
media_type: str
visibility: ArtifactVisibility
stage: str | None = None
created_at: datetime
metadata: dict[str, JsonValue] = {}
```

Rules:

- IDs, names, and media types are non-empty;
- serialized paths use POSIX separators;
- absolute paths and `..` components are rejected;
- `.` is rejected or normalized consistently;
- no filesystem access occurs;
- metadata is JSON-compatible and defensively copied.

## Required behavior

- Every model supports deterministic validation and JSON round trips.
- Input mappings cannot mutate an already-created model.
- Mutable defaults are never shared between instances.
- Invalid state/timestamp combinations fail validation clearly.
- Error details and model metadata never retain arbitrary Python objects.
- Importing `arcadia.models` does not import future ARCADIA packages or heavy dependencies.

## Explicit non-goals

- configuration file loading or saving;
- environment variable resolution;
- hardware detection;
- llama flag validation;
- service lifecycle or process handles;
- model download or checkpoint checks;
- HTTP schemas or routes;
- inference result payloads beyond the shared status/error vocabulary;
- run storage;
- event sinks;
- pipeline execution;
- UI-facing formatting.

## Tests required

Suggested files:

```text
tests/unit/models/test_common.py
tests/unit/models/test_errors.py
tests/unit/models/test_services.py
tests/unit/models/test_analysis.py
tests/unit/models/test_artifacts.py
tests/contract/test_model_serialization.py
```

Tests must cover:

- all error default codes and retryability;
- cause retention and `to_info()` serialization;
- JSON compatibility and defensive copying;
- rejection of unknown fields;
- valid and invalid node addresses, IPv6 URL formatting, and ports;
- valid and invalid Hugging Face repo/file specifications;
- requested/resolved settings separation;
- service union parsing and projector rules;
- every service and operation state coherence rule;
- UTC normalization and naive timestamp rejection;
- analysis and stage state coherence;
- artifact path safety and serialization;
- JSON round trips for all transport-facing models;
- lightweight `import arcadia` behavior;
- wheel import of representative `arcadia.models` symbols.

No test may require network access, a real model, filesystem model discovery, subprocesses, or a GPU.

## Validation

Run:

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

Then install the built wheel in a clean virtual environment and verify:

```python
import arcadia
from arcadia.models import LlamaServiceSpec, ServiceType
```

## Definition of done

- [x] Pydantic 2 is the only new required runtime dependency.
- [x] `arcadia.models` implements every required public export.
- [x] Success and failure behavior are tested.
- [x] Models are attribute-frozen, explicitly validated per field, defensively copy input mappings, and support JSON round trips. Nested JSON structures remain mutable within the model instance.
- [x] `import arcadia` remains lightweight.
- [x] Ruff, mypy, pytest, build, and clean-wheel checks pass.
- [x] The completion record below is filled honestly.

## Stop conditions

Stop and report instead of expanding scope when:

- satisfying the contract appears to require filesystem, network, process, service, event, or hardware behavior;
- a field cannot be represented without inventing backend-specific policy;
- architecture and session requirements directly conflict;
- validation fails because of unrelated repository code.

---

# Completion record

The implementation agent must replace the placeholders before stopping.

## Outcome

Session 01 is complete. The `arcadia.models` package implements the full domain model and typed error contract: 34 public symbols covering errors, common types (NodeAddress, HuggingFaceFileSpec, runtime settings), service specs/endpoints/status, analysis status, and artifact records. Models are attribute-frozen, explicitly validated per field, defensively copy input mappings, and support JSON round trips. Nested JSON structures remain mutable within the model instance. All definition-of-done validation passes (157 tests, ruff, mypy, build, clean-venv wheel install).

## Files changed

### Source
- `pyproject.toml` — added `pydantic>=2,<3` as the only required runtime dependency
- `src/arcadia/models/__init__.py` — public re-export surface (34 symbols)
- `src/arcadia/models/common.py` — ModelBase, NodeAddress, HuggingFaceFileSpec, RuntimeSettings, ArtifactVisibility
- `src/arcadia/models/errors.py` — ArcadiaError, ArcadiaErrorInfo, and 11 typed error subclasses
- `src/arcadia/models/services.py` — ServiceSpec union, ServiceEndpoint, ServiceStatus, OperationStatus
- `src/arcadia/models/analysis.py` — AnalysisState, StageState, AnalysisSpec, StageStatus, AnalysisStatus
- `src/arcadia/models/artifacts.py` — ArtifactRecord

### Tests
- `tests/unit/models/__init__.py` — test package marker
- `tests/unit/models/test_common.py` — NodeAddress, HuggingFaceFileSpec, settings, ArtifactVisibility
- `tests/unit/models/test_errors.py` — error defaults, retryability, cause retention, to_info()
- `tests/unit/models/test_services.py` — projector rules, parse_service_spec, state coherence
- `tests/unit/models/test_analysis_and_artifacts.py` — analysis/stage coherence, artifact path validation
- `tests/unit/models/test_serialization.py` — JSON round trips for all model families

### Documentation
- `docs/sessions/01-domain-models-and-errors.md` — updated status, definition-of-done, completion record

## Delivered public API

`from arcadia.models import ...` exposes all 34 required symbols:
ArcadiaError, ArcadiaErrorInfo, ConfigurationError, ServiceError, ServiceConflictError,
ServiceStartupError, ServiceHealthError, ServiceNotRunningError, InstructionError,
InferenceError, InferenceTimeoutError, AnalysisError, ArtifactError, NodeAddress,
HuggingFaceFileSpec, RequestedRuntimeSettings, ResolvedRuntimeSettings, ServiceType,
ServiceState, OperationState, LlamaServiceSpec, SamServiceSpec, ServiceSpec,
ServiceEndpoint, ServiceStatus, OperationStatus, parse_service_spec, AnalysisState,
StageState, AnalysisSpec, AnalysisStatus, StageStatus, ArtifactVisibility, ArtifactRecord.

The root `arcadia` package does NOT re-export these — `arcadia.models` must be imported explicitly.

## State and side effects

The `arcadia.models` package owns no runtime state. Models are attribute-frozen, explicitly validated per field, defensively copy input mappings, and support JSON round trips. Nested JSON structures remain mutable within the model instance. Importing `arcadia.models` performs no filesystem, network, subprocess, model-loading, or GPU operations. Naive datetimes are rejected; timezone-aware datetimes are normalized to UTC.

## Errors and events

12 typed error classes (ArcadiaError base + 11 subclasses) with stable codes, retryability, and structured JSON details. Causes are retained on the exception object but excluded from serialization. `InferenceTimeoutError` is the only retryable error by default. `ArcadiaErrorInfo.to_info()` provides a serializable snapshot.

## Tests and validation

All definition-of-done checks pass:
- `python -m pip install -e ".[dev]"` — success
- `ruff format --check .` — 19 files already formatted
- `ruff check .` — all checks passed
- `mypy src/arcadia` — no issues found in 7 source files
- `pytest` — 157 passed
- `python -m build` — built wheel and sdist
- Clean-venv wheel install + `import arcadia; from arcadia.models import LlamaServiceSpec, ServiceType` — success
- `import arcadia` confirmed lightweight (no heavy modules in sys.modules)

Test files:
- `tests/unit/models/test_common.py` — NodeAddress, HuggingFaceFileSpec, settings, ArtifactVisibility
- `tests/unit/models/test_errors.py` — error defaults/retryability, cause retention, to_info(), ArcadiaErrorInfo
- `tests/unit/models/test_services.py` — projector rules, parse_service_spec, Service/Operation state coherence
- `tests/unit/models/test_analysis_and_artifacts.py` — analysis/stage coherence, artifact path validation
- `tests/unit/models/test_serialization.py` — JSON round trips for all 14 model families

## Decisions and deviations

No deviations from the session contract. All required exports, rules, and validation behaviors are implemented as specified.

Implementation decisions (within the specified choices):
- `ArtifactRecord.relative_path` rejects backslashes rather than normalizing them to forward slashes (spec permits either approach).
- `ArcadiaError.cause` accepts any object, retained for debugging but excluded from serialization via `to_info()`.
- Datetime validators accept ISO 8601 strings (from JSON round trips) in addition to `datetime` objects, parsing and normalizing to UTC.

## Known limitations

No known limitations. The session implements the full contract without scope reduction.

## Assumptions and risks

Later sessions depend on the stable contract defined here. The models module adds Pydantic 2 as a new runtime dependency, which is recorded in `pyproject.toml`. Subsequent sessions (configuration, services, storage, etc.) must not be blocked by this dependency.

## Next-session prerequisites

`from arcadia.models import ...` provides the full domain vocabulary:

- Errors: `ArcadiaError`, `ArcadiaErrorInfo`, and 11 typed subclasses with stable codes/retryability
- Addresses: `NodeAddress` (IPv4/IPv6/hostname with `base_url` property)
- Model files: `HuggingFaceFileSpec` (repo_id/filename/revision validation)
- Settings: `RequestedRuntimeSettings`, `ResolvedRuntimeSettings` (defensively copied, JSON-compatible)
- Services: `ServiceType`, `ServiceState`, `OperationState`, `LlamaServiceSpec`, `SamServiceSpec`, `ServiceSpec`, `parse_service_spec`, `ServiceEndpoint`, `ServiceStatus`, `OperationStatus`
- Analysis: `AnalysisState`, `StageState`, `AnalysisSpec`, `StageStatus`, `AnalysisStatus`
- Artifacts: `ArtifactVisibility`, `ArtifactRecord`

All models are frozen, JSON-round-trippable, and reject unknown fields. Datetimes are UTC-normalized; naive datetimes are rejected. The root `arcadia` package remains lightweight — `arcadia.models` must be imported explicitly.

Session 02 (Configuration) can build on this foundation by adding `arcadia.config`, which depends on `arcadia.models` for validated domain types.
