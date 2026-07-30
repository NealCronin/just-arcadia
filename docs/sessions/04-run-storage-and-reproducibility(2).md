# Session 04: Run Storage and Reproducibility

- Status: completed
- Branch: `session/04-run-storage`
- Owner: local agent session
- Module: `arcadia.storage`

## Objective

Implement the filesystem-backed run-storage layer for headless ARCADIA.

Session 04 must provide:

- one self-contained directory per analysis run;
- a validated, versioned reproducibility manifest;
- atomic manifest replacement;
- a stable path for the Session 03 JSONL event log;
- an append-only JSONL artifact index;
- safe artifact paths beneath the run output directory;
- reopening and validation of existing run directories;
- typed storage failures with stable codes.

This module persists run records. It does not execute analyses, emit events, detect hardware, provision services, perform inference, or interpret tool settings.

## Architectural context

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/README.md
docs/sessions/03-events-and-structured-logging.md
src/arcadia/models/**
src/arcadia/events/**
```

The legacy repository may be inspected as a read-only reference, especially `core/storage.py`, `tests/test_storage.py`, and `web/artifacts.py`.

Important rules:

- The orchestrator owns persistent run storage.
- `RunStore` owns run metadata and artifact records, not active analysis state.
- Session 03 owns event envelopes and delivery. Session 04 exposes an event-log path but does not write events.
- Configuration snapshots are supplied as JSON-compatible data; do not load global configuration automatically.
- Completed artifacts must survive a later pipeline failure.
- Tools write inside the run `outputs/` directory unless a future API explicitly delegates another path.
- Cross-process locking is not required for the one-orchestrator prototype.
- Use only public APIs from earlier modules; do not import private helpers.

## Scope

### Allowed files

```text
src/arcadia/storage/**
tests/unit/storage/**
tests/contract/test_run_manifest_serialization.py
tests/integration/test_run_storage.py
tests/test_package.py
docs/sessions/04-run-storage-and-reproducibility.md
docs/sessions/README.md
```

Modify `pyproject.toml` only if package discovery requires it. Add no runtime dependency.

### Prohibited work

Do not implement hardware, services, backends, transport, inference, tools, analysis, CLI, or UI modules.

Do not add:

- a database, YAML, TOML, migration, or configuration merging;
- event delivery or a second JSONL event sink;
- hardware detection or runtime resolution;
- service lifecycle, networking, model download, or inference;
- analysis transitions, cancellation, scheduling, or active-run locking;
- artifact rendering, run deletion, retention, compression, upload, or export packaging;
- background workers, async queues, polling, file watching, or global stores;
- automatic repair or rewriting of corrupt runs.

Do not change Session 01–03 public contracts unless a genuine blocker is documented.

## Package structure

```text
src/arcadia/storage/
├── __init__.py
├── errors.py
├── models.py
├── serialization.py
└── store.py
```

A different internal split is acceptable only if the public API remains unchanged.

## Required public API

`from arcadia.storage import ...` must expose:

```text
RUN_MANIFEST_SCHEMA_VERSION
StorageError
RunNotFoundError
RunConflictError
RunCorruptError
RunManifest
RunPaths
RunStore
dumps_manifest
loads_manifest
```

Do not re-export these from `arcadia.__init__`.

## Error contract

Use the public `ArcadiaError` base.

| Exception | Default code | Retryable |
|---|---|---:|
| `StorageError` | `storage_error` | false |
| `RunNotFoundError` | `run_not_found` | false |
| `RunConflictError` | `run_conflict` | false |
| `RunCorruptError` | `run_corrupt` | false |

Use these override codes where applicable:

```text
storage_read_failed
storage_write_failed
storage_serialization_failed
artifact_registration_failed
artifact_conflict
```

Public storage operations must not expose raw JSON, Pydantic, Unicode, path-construction, or OS exceptions. Retain useful causes, keep details JSON-safe, and never serialize full file contents, exception objects, or tracebacks. Use the existing `ArtifactError` for artifact-specific failures.

## Run-directory layout

A created run uses exactly:

```text
<output_root>/<run_id>/
├── manifest.json
├── events.jsonl
├── artifacts.jsonl
└── outputs/
```

Rules:

- `run_id` is one safe path component;
- reject empty IDs, `.`/`..`, slashes, backslashes, controls, and Windows drive-prefix syntax;
- preserve case and ordinary human-readable characters;
- never silently normalize an unsafe ID;
- create `events.jsonl` empty for Session 03, but never write event records here;
- `artifacts.jsonl` is append-only and owned by this module;
- creation may create missing `output_root` parents;
- never overwrite or adopt an existing run path;
- after failed creation, clean only content newly created by that call.

## `RunPaths`

Use an immutable dataclass:

```python
@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    manifest_path: Path
    event_log_path: Path
    artifact_index_path: Path
    outputs_dir: Path
```

All paths are absolute and derived from the run directory. Construction performs no I/O.

## `RunManifest`

Use frozen Pydantic 2 models with `extra="forbid"` and validated defaults.

```python
RUN_MANIFEST_SCHEMA_VERSION = 1


class RunManifest:
    schema_version: int = RUN_MANIFEST_SCHEMA_VERSION
    run_id: str
    created_at: datetime
    updated_at: datetime
    analysis_spec: AnalysisSpec
    analysis_status: AnalysisStatus
    configuration: dict[str, JsonValue] = {}
    service_specs: dict[str, ServiceSpec] = {}
    resolved_settings: dict[str, ResolvedRuntimeSettings] = {}
    hardware: dict[str, JsonValue] = {}
    endpoint_assignments: dict[str, ServiceEndpoint] = {}
    metadata: dict[str, JsonValue] = {}
```

Validation requirements:

- support only exact integer schema version `1`; reject `True`, `1.0`, and `"1"`;
- validate `run_id` with the directory-component rules;
- reject naive timestamps and normalize aware timestamps to UTC;
- require `updated_at >= created_at`;
- require `analysis_status.run_id == run_id`;
- require `analysis_status.tool_name == analysis_spec.tool_name`;
- require non-empty, control-free, case-sensitive mapping keys and reject collisions after trimming;
- parse dict service specs using public `parse_service_spec`;
- require resolved-setting and endpoint keys to exist in `service_specs`;
- require endpoint service types to match their service specs;
- validate and defensively copy recursive JSON data;
- reject unknown fields and support lossless JSON round trips.

`configuration` stores the requested configuration snapshot supplied by the future analysis engine. Do not import `arcadia.config`.

`hardware` remains generic JSON until Session 05 defines hardware models. Do not invent that schema here.

### Immutable manifest fields

After run creation, reject changes to:

```text
schema_version
run_id
created_at
analysis_spec
configuration
service_specs
```

Allow later modules to update:

```text
updated_at
analysis_status
resolved_settings
hardware
endpoint_assignments
metadata
```

`updated_at` must be monotonic relative to the stored manifest. This module enforces persistence invariants but does not implement analysis-state transition rules.

## Manifest serialization

### `dumps_manifest(manifest)`

Return deterministic JSON with two-space indentation, sorted keys, preserved Unicode, no non-finite floats, and one trailing newline. Translate wrong types or serialization failures to `StorageError(code="storage_serialization_failed")`.

### `loads_manifest(text)`

- require string input and a top-level object;
- reject malformed JSON;
- check the exact schema-version JSON type before Pydantic coercion;
- return a validated `RunManifest`;
- translate failures to `RunCorruptError`;
- retain causes and expose only sanitized validation location/message/type details;
- never include the full input text in error details.

## `RunStore`

`RunStore` is an instance-local filesystem boundary. It must not cache authoritative manifest or artifact state across calls.

```python
class RunStore:
    @classmethod
    def create(cls, output_root: str | os.PathLike[str], manifest: RunManifest) -> RunStore: ...

    @classmethod
    def open(cls, run_dir: str | os.PathLike[str]) -> RunStore: ...

    @property
    def paths(self) -> RunPaths: ...

    def read_manifest(self) -> RunManifest: ...
    def write_manifest(self, manifest: RunManifest) -> None: ...

    def artifact_path(
        self,
        relative_path: str,
        *,
        must_exist: bool = False,
    ) -> Path: ...

    def record_artifact(
        self,
        record: ArtifactRecord,
        *,
        fsync: bool = False,
    ) -> bool: ...

    def list_artifacts(self) -> tuple[ArtifactRecord, ...]: ...
```

### Creation

`create()` must:

1. Validate arguments before filesystem changes.
2. Create missing output-root parents.
3. Fail with `RunConflictError` if the final run path already exists as a file, directory, or symlink.
4. Create the exact layout above.
5. Write all manifest bytes, flush, and `fsync` before returning.
6. Clean a newly created incomplete run after failure.
7. Never remove or alter a pre-existing path.
8. Emit no event automatically.

### Opening and reading

`open()` must perform no writes or repair. It requires the manifest, both JSONL files, and `outputs/`; validates the manifest and complete artifact index; and requires the directory name to equal `manifest.run_id`.

Use:

- `RunNotFoundError` for absent paths;
- `RunCorruptError` for malformed, incomplete, inconsistent, or unsafe contents;
- typed storage errors for unreadable paths.

`read_manifest()` rereads and validates disk state each call and returns a detached model.

### Atomic manifest writes

`write_manifest()` must:

1. Validate normal and immutable-field rules.
2. Serialize before touching `manifest.json`.
3. Write all bytes to a same-directory temporary file.
4. Flush and `fsync` it.
5. Replace with `os.replace`.
6. Clean temporary files after failure.
7. Preserve the old manifest if writing or replacement fails before replacement completes.

Do not add backups, retries, or migration.

### Artifact paths

`artifact_path()` resolves a path relative to `outputs/`.

- require a non-empty string;
- reject absolute paths, drive prefixes, backslashes, controls, empty components, `.`, and `..`;
- return an absolute path beneath `outputs/`;
- reject lexical and existing-symlink escape;
- with `must_exist=True`, require an existing regular file;
- with `must_exist=False`, create nothing and ensure existing parent symlinks cannot escape;
- use `ArtifactError(code="artifact_registration_failed")` on failure.

### Artifact recording

`record_artifact()` must:

- require an `ArtifactRecord` instance;
- require its relative path to be an existing regular file beneath `outputs/`;
- append one compact deterministic UTF-8 JSON object plus `\n`;
- preserve append order and serialize operations through an instance lock;
- complete partial writes, flush every append, and optionally `fsync`;
- never mutate records or rewrite/truncate successful prior entries;
- return `True` for a new append;
- return `False` without appending for an equal existing artifact ID;
- raise `ArtifactError(code="artifact_conflict")` for the same ID with different data;
- translate other failures to `ArtifactError(code="artifact_registration_failed")`.

Build the complete JSON line before opening the file. When feasible with standard-library APIs, restore the original byte length if an append fails after a partial write. Record any platform limitation honestly.

`list_artifacts()` rereads and validates the complete index, preserving order. Empty files return an empty tuple. Blank, malformed, non-object, unknown-field, invalid, or duplicate-ID lines are `RunCorruptError`; never repair them automatically.

## Concurrency

- Use instance-local locks for manifest replacement and artifact operations.
- Concurrent operations through one store instance must not interleave or corrupt files.
- Do not hold locks around unrelated caller code.
- Cross-process locking and coordination between separate `RunStore` objects for the same run are unsupported.
- Add no scheduler, queue, worker thread, or async API.

## State and side effects

Allowed side effects are limited to explicit run creation, manifest reads/writes, empty log creation, artifact-index reads/appends, and filesystem inspection needed for containment.

The module must not write events, load application configuration, inspect hardware, access the network, start processes or services, perform inference, sleep, retry automatically, or delete completed data.

## Tests required

### Models and serialization

Cover:

- representative manifests and complete JSON round trips;
- exact schema-version types;
- safe/unsafe run IDs;
- UTC normalization and naive rejection;
- timestamp ordering and analysis identity coherence;
- service-spec parsing and resolved/endpoint references;
- endpoint/service-type mismatch;
- JSON validation, defensive copies, key collisions, and unknown fields;
- deterministic formatting, Unicode, trailing newline;
- malformed/non-object input and sanitized errors;
- load/dump/load equality.

### Run creation, opening, and manifest updates

Using temporary directories and failure injection, cover:

- output-root creation and exact layout;
- empty event/artifact logs;
- existing file/directory/symlink conflicts;
- creation cleanup without touching pre-existing paths;
- open without writes or mtime changes;
- missing/incomplete/corrupt runs and run-ID mismatch;
- invalid path argument types;
- successful atomic replacement;
- immutable-field and decreasing-time rejection;
- partial writes and write/flush/`fsync`/replace failures preserving the old manifest;
- temporary-file cleanup and concurrent write integrity;
- no POSIX-only permission assumptions.

### Artifact paths and index

Cover:

- valid nested paths and every rejected path form;
- `must_exist` behavior, directory rejection, and symlink escape where supported;
- no target or parent creation;
- append/list order and parseable compact JSONL;
- Unicode, optional `fsync`, and partial writes;
- idempotent duplicate and conflicting duplicate IDs;
- missing/outside-output artifacts;
- failed append preserving a valid prior index;
- concurrent records without loss or interleaving;
- corrupt, blank, non-object, unknown-field, invalid, and duplicate-ID existing lines;
- reopening validates the complete artifact index.

### Package tests

- `import arcadia` does not eagerly import `arcadia.storage`.
- `arcadia.storage` imports no config, events, hardware, services, backends, transport, inference, tools, analysis, CLI, UI, or heavy inference modules.
- Earlier session tests remain unchanged and pass.

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

Install the wheel in a clean environment and verify:

```python
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from arcadia.models import AnalysisSpec, AnalysisState, AnalysisStatus
from arcadia.storage import RunManifest, RunStore

with TemporaryDirectory() as root:
    now = datetime.now(UTC)
    manifest = RunManifest(
        run_id="smoke-run",
        created_at=now,
        updated_at=now,
        analysis_spec=AnalysisSpec(
            tool_name="smoke",
            input_path="input",
            output_root=root,
        ),
        analysis_status=AnalysisStatus(
            run_id="smoke-run",
            tool_name="smoke",
            state=AnalysisState.PENDING,
        ),
    )
    store = RunStore.create(root, manifest)
    assert store.read_manifest() == manifest
    assert store.paths.event_log_path.exists()
```

Never claim an unexecuted command passed.

## Definition of done

- [ ] Every required public export exists.
- [ ] No runtime dependency was added.
- [ ] Manifests validate and round-trip.
- [ ] Creation produces the exact layout without overwriting existing paths.
- [ ] Existing runs reopen without mutation.
- [ ] Manifest replacement is atomic under injected failures.
- [ ] Immutable manifest fields cannot change.
- [ ] Artifact paths cannot escape `outputs/`.
- [ ] Artifact records append incrementally and deterministic duplicate behavior is tested.
- [ ] Concurrent operations through one store instance do not corrupt files.
- [ ] Storage does not write events or import future runtime modules.
- [ ] Root import remains lightweight.
- [ ] Ruff, mypy, pytest, build, and clean-wheel validation pass.
- [ ] This file contains an honest completion record.
- [ ] `docs/sessions/README.md` marks Session 04 completed only after validation succeeds.

## Stop conditions

Stop and record the issue instead of expanding scope if implementation requires changing an earlier public contract, adding a dependency/database, implementing event delivery or runtime modules, adding cross-process locking, or repairing unrelated code.

---

# Completion record

## Outcome

Completed. `arcadia.storage` now owns versioned run manifests, the exact per-run directory layout, atomic manifest replacement, safe output paths, and append-only artifact records.

## Files changed

- `src/arcadia/storage/__init__.py`
- `src/arcadia/storage/errors.py`
- `src/arcadia/storage/models.py`
- `src/arcadia/storage/serialization.py`
- `src/arcadia/storage/store.py`
- `tests/unit/storage/__init__.py`
- `tests/unit/storage/test_models.py`
- `tests/contract/test_run_manifest_serialization.py`
- `tests/integration/test_run_storage.py`
- `tests/test_package.py`
- `docs/sessions/04-run-storage-and-reproducibility(2).md`
- `docs/sessions/README.md`

## Delivered public API

`arcadia.storage` exports `RUN_MANIFEST_SCHEMA_VERSION`, `StorageError`, `RunNotFoundError`, `RunConflictError`, `RunCorruptError`, `RunManifest`, `RunPaths`, `RunStore`, `dumps_manifest`, and `loads_manifest`. The root `arcadia` package does not re-export or eagerly import storage.

## State and side effects

`RunStore` owns only filesystem-backed manifest and artifact-index access for one run directory. Creation makes the exact layout and empty event/artifact JSONL files; it never writes events. Manifest replacement uses a same-directory, flushed and fsynced temporary file plus `os.replace`. Artifact operations use instance-local locks, preserve append order, and validate containment beneath `outputs/`. Failed append recovery truncates to the original length when the process remains alive; a process crash can leave an incomplete line, which reopening reports as corruption rather than repairing.

## Errors and events

Storage boundaries translate filesystem, encoding, JSON, validation, and serialization failures into typed storage failures without embedding persisted contents or tracebacks in details. Artifact path and recording failures use `ArtifactError` with `artifact_registration_failed` or `artifact_conflict`. This module emits no events.

## Tests and validation

Completed:

- `python -m pip install -e ".[dev]"` — success.
- Initial `ruff format --check .` — identified the supplied Session 04 document as the sole unformatted file; it was formatted before implementation validation.
- `ruff format --check .` — 60 files already formatted.
- `ruff check .` — success.
- `mypy src/arcadia` — success.
- `pytest` — 405 passed.
- `python -m build` — sdist and wheel built successfully.
- Clean-virtual-environment wheel smoke test — created `smoke-run`, reread the equal manifest, and confirmed `events.jsonl` exists.

Focused validation also passed: `ruff format --check` and `ruff check` for storage/tests, `mypy src/arcadia`, and storage/package tests (`34 passed`).

## Decisions and deviations

No earlier public contract changed and no runtime dependency was added. Run manifests retain service specifications through the public `parse_service_spec` API; they do not import configuration, events, or future runtime modules.

## Known limitations

Cross-process locking and coordination between independent `RunStore` instances are intentionally unsupported. A crash during an artifact append is detected as corrupt JSONL on a later read; automatic repair is intentionally out of scope.

## Assumptions and risks

The caller owns tool writes and must use `outputs/`; `record_artifact()` requires the referenced regular file to exist. The event-log path is provisioned for Session 03’s `JsonlEventSink`, but storage never creates an event sink or writes event records.

## Next-session prerequisites

Session 05 and later modules can create or reopen validated run directories, pass `RunStore.paths.event_log_path` to the event sink, atomically persist permitted manifest updates, write artifacts below `RunStore.paths.outputs_dir`, and register those artifacts incrementally.
