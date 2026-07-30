# Session 02: Configuration

- Status: completed
- Branch: `session/02-configuration`
- Owner: local agent session
- Module: `arcadia.config`

## Objective

Implement the human-editable JSON configuration layer for headless ARCADIA.

Session 02 must provide one validated global configuration document containing:

- named local and remote compute nodes;
- reusable service profiles that pair a node with a Session 01 service specification;
- reusable tool profiles that bind inference stages to service profiles;
- retry and output settings;
- explicit extension namespaces;
- JSON load, dump, atomic save, and detached snapshot functions.

Configuration stores desired user settings only. It must not contain process handles, PIDs, service status, operation progress, resolved hardware settings, analysis history, logs, or results.

## Architectural context

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/README.md
docs/sessions/01-domain-models-and-errors.md
```

Important rules:

- Persistent configuration belongs to the orchestrator.
- A machine may be both orchestrator and compute node.
- Compute nodes are session-stateless.
- The orchestrator supplies the desired service specification and port.
- Requested runtime settings are persistent; resolved settings belong to future run manifests.
- Configuration must remain editable outside a UI.
- JSON is the only configuration format for the first prototype.
- The future analysis engine, not this module, owns the active-run configuration lock.

Use only the public Session 01 API from `arcadia.models`. Do not silently change it. Stop and document a blocker if a model change appears necessary.

## Scope

### Allowed files

```text
src/arcadia/config/**
tests/unit/config/**
tests/integration/test_config_files.py
tests/test_package.py
docs/sessions/02-configuration.md
docs/sessions/README.md
```

Modify `pyproject.toml` only if package discovery requires it. No new runtime dependency should be necessary.

### Prohibited work

Do not create or implement events, storage, hardware detection, services, backends, transport, inference, tools, analysis, CLI, or UI modules.

Do not add:

- Django, FastAPI, HTTPX, YAML, TOML, or a database;
- environment override precedence, secret resolution, or cloud providers;
- network requests, discovery, file watching, threads, or global stores;
- filesystem existence checks for models, checkpoints, inputs, or outputs;
- hardware/runtime resolution;
- service lifecycle logic;
- analysis locking or history;
- schema migration, configuration inheritance, or merging;
- automatic writes during load.

## Package structure

```text
src/arcadia/config/
├── __init__.py
├── models.py
└── files.py
```

A small private validation helper is acceptable. Do not import private helpers from `arcadia.models`.

## Public API

`from arcadia.config import ...` must expose:

```text
CONFIG_SCHEMA_VERSION
NodeKind
NodeConfig
ServiceProfile
StageBinding
ToolProfile
RetryPolicy
OutputSettings
ArcadiaConfig
load_config
loads_config
save_config
dumps_config
snapshot_config
```

Do not re-export these from `arcadia.__init__`. Plain `import arcadia` must remain lightweight.

## Model rules

Use Pydantic 2 with behavior equivalent to:

```python
ConfigDict(extra="forbid", frozen=True, validate_default=True)
```

All configuration models must:

- reject unknown ordinary fields;
- preserve future custom data only under explicit `extensions` mappings;
- validate nested extension/settings data as JSON-compatible;
- reject NaN, infinity, bytes, sets, arbitrary objects, and non-string mapping keys;
- defensively copy mapping inputs;
- reject booleans where numeric values are expected;
- support JSON-compatible `model_dump()` and revalidation;
- perform no filesystem or network work during construction.

Names used as dictionary keys or references must be non-empty after trimming and contain no control characters. Keep names case-sensitive and human-friendly; do not generate slugs or force lowercase.

Session 01 models are attribute-frozen but nested JSON values remain mutable. `snapshot_config()` must therefore detach all nested dictionaries and lists through serialization and revalidation.

## Configuration schema

### Version

```python
CONFIG_SCHEMA_VERSION = 1
```

Only version 1 is supported. A missing version uses the version-1 default. Any other supplied version must produce `config_unsupported_version` through parsing functions.

### `NodeKind`

```python
class NodeKind(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
```

### `NodeConfig`

```python
class NodeConfig:
    kind: NodeKind
    address: NodeAddress | None = None
    description: str = ""
    extensions: dict[str, JsonValue] = {}
```

Rules:

- local nodes must not provide an instruction address;
- remote nodes must provide a `NodeAddress`;
- at most one local node may exist in the root configuration;
- descriptions may be empty, otherwise trim them and reject control characters;
- do not test reachability.

### `ServiceProfile`

```python
class ServiceProfile:
    node: str
    spec: ServiceSpec
    description: str = ""
    extensions: dict[str, JsonValue] = {}
```

A service profile is a reusable desired service configuration.

Rules:

- `node` references a configured node name;
- `spec` is a Session 01 LLM, visual-LLM, or SAM service specification;
- store requested settings only;
- do not store endpoints, resolved settings, statuses, PIDs, or logs;
- multiple profiles may intentionally target the same node and port because they can be alternative quick-load configurations.

### `StageBinding`

```python
class StageBinding:
    service_profile: str
    extensions: dict[str, JsonValue] = {}
```

`service_profile` references a configured service profile. Multiple stages may reuse the same profile. Tool-specific service-type compatibility is deferred to the future tool implementation.

### `ToolProfile`

```python
class ToolProfile:
    tool_name: str
    stages: dict[str, StageBinding] = {}
    settings: dict[str, JsonValue] = {}
    description: str = ""
    extensions: dict[str, JsonValue] = {}
```

Rules:

- `tool_name` is non-empty, such as `priority_map`;
- `stages` maps inference-stage names to service profiles but does not redefine tool order;
- `settings` retains tool-owned values such as `sam_step`, resize, frame skipping, and pacing;
- this session validates JSON compatibility only and does not interpret tool settings;
- empty stages are valid.

### `RetryPolicy`

```python
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    multiplier: float = 2.0
    maximum_delay_seconds: float = 10.0
```

Rules:

- `max_attempts` includes the first attempt and must be at least 1;
- delays must be finite and non-negative;
- multiplier must be finite and at least 1.0;
- maximum delay must be at least the initial delay;
- no retry or sleeping behavior is implemented here.

### `OutputSettings`

```python
class OutputSettings:
    root: str = "./outputs"
    extensions: dict[str, JsonValue] = {}
```

`root` must be a non-empty path string without null bytes, CR, or LF. Do not expand, normalize, create, or inspect it.

### `ArcadiaConfig`

```python
class ArcadiaConfig:
    schema_version: Literal[1] = CONFIG_SCHEMA_VERSION
    nodes: dict[str, NodeConfig] = {}
    service_profiles: dict[str, ServiceProfile] = {}
    tool_profiles: dict[str, ToolProfile] = {}
    retry: RetryPolicy = RetryPolicy()
    output: OutputSettings = OutputSettings()
    extensions: dict[str, JsonValue] = {}
```

Cross-reference validation:

1. Every service profile references an existing node.
2. Every stage binding references an existing service profile.
3. At most one local node exists.
4. Empty collections are valid for a new configuration.
5. Unknown root fields fail unless data is placed under `extensions`.
6. No live or resolved runtime state is accepted.

A representative document should support local and remote nodes, a remote visual-LLM profile, a local SAM profile, and a Priority Map tool profile binding scene-understanding and segmentation stages to those profiles.

## File API

### `loads_config(text)`

- Accept JSON text.
- Require a top-level object.
- Validate and return `ArcadiaConfig`.
- Perform no file I/O.
- Convert all public failures to typed `ConfigurationError` values.

### `dumps_config(config)`

Return deterministic, human-readable JSON using:

- two-space indentation;
- sorted keys;
- preserved Unicode rather than forced ASCII escaping;
- a trailing newline.

Do not mutate the model or include non-persistent runtime data.

### `load_config(path)`

- Read explicit UTF-8 JSON.
- Never create, modify, normalize, or migrate the file.
- Return validated configuration.
- Retain original exceptions as `cause` when applicable.

### `save_config(config, path)`

Use a cross-platform atomic replacement:

1. Serialize first.
2. Create missing parent directories.
3. Write a temporary file in the destination directory.
4. Flush and `fsync` it.
5. Replace with `os.replace`.
6. Clean the temporary file after failure.
7. Leave an existing destination unchanged if writing or replacement fails before replacement completes.

No file lock is required for the one-operator prototype.

### `snapshot_config(config)`

Create a detached deep copy through JSON serialization and revalidation. Mutating nested source values must not affect the snapshot, and mutating nested snapshot values must not affect the source. Perform no I/O or runtime resolution.

## Error contract

Public parsing and file functions must raise `ConfigurationError`, not raw JSON, Pydantic, Unicode, or operating-system exceptions.

| Situation | Code |
|---|---|
| Missing file | `config_not_found` |
| Read failure | `config_read_failed` |
| UTF-8 failure | `config_decode_failed` |
| Malformed JSON | `config_invalid_json` |
| Non-object root | `config_invalid_format` |
| Model or reference validation | `config_validation_failed` |
| Unsupported schema | `config_unsupported_version` |
| Serialization failure | `config_serialization_failed` |
| Write or replace failure | `config_write_failed` |

All are non-retryable by default.

Requirements:

- messages are concise enough for a future UI or CLI;
- causes are retained but not serialized;
- details are JSON-safe;
- validation details include sanitized field location, message, and validation type only;
- never include full configuration text, arbitrary invalid objects, or tracebacks in serialized details.

## State and side effects

The module owns no global active configuration or singleton store. The only allowed side effects are explicit reads and writes from `load_config()` and `save_config()`.

It must not consult environment variables, access the network, emit events, start threads, sleep, start services, or inspect model/output paths.

## Required behavior

1. `ArcadiaConfig()` validates and round-trips.
2. Local/remote node rules and one-local-node limit are enforced.
3. Service and stage references are validated.
4. Alternative profiles may share a node and port.
5. Requested runtime settings survive round trips unchanged.
6. Root and nested extension data survive semantic round trips.
7. Unknown ordinary fields fail.
8. Retry and output settings validate without side effects.
9. Dumps are deterministic.
10. Loads never write.
11. Saves are atomic and clean failed temporary files.
12. Snapshots detach nested JSON structures in both directions.
13. No new runtime dependency is introduced.
14. Root import remains lightweight.

## Explicit non-goals

- YAML/TOML or JSON comments
- merging, inheritance, or overlays
- environment/CLI overrides
- secrets and cloud-provider profiles
- schema migration
- file locking or watching
- active-analysis locking
- runtime/hardware resolution
- path expansion
- endpoint discovery
- model download or service state
- tool-specific validation
- UI or CLI

## Tests required

### Model tests

Cover:

- default config;
- valid/invalid local and remote nodes;
- second local node rejection;
- name trimming and control-character rejection;
- valid LLM, visual-LLM, and SAM profiles;
- unknown node and service-profile references;
- profile reuse and same-port alternatives;
- requested settings preservation;
- root/nested extensions and invalid JSON values;
- unknown field rejection;
- retry boundaries and boolean rejection;
- output validation without path access;
- version 1 and unsupported versions.

### Serialization tests

Cover:

- valid text load;
- malformed JSON and non-object roots;
- validation conversion and sanitized details;
- deterministic formatting, Unicode, and trailing newline;
- load/dump/load equality;
- snapshot detachment for nested dictionaries and lists.

### File integration tests

Using temporary directories and failure injection, cover:

- missing and undecodable files;
- normal round trip;
- parent creation;
- load leaves content and modification time unchanged;
- atomic replacement;
- simulated write and `os.replace` failures preserve the old file;
- temporary cleanup;
- typed error codes and retained causes;
- no POSIX-only permission assumptions.

### Package tests

- `import arcadia` does not eagerly import `arcadia.config`.
- `arcadia.config` imports no heavy library or future runtime module.
- All Session 01 tests remain unchanged and pass.

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

Install the wheel in a clean virtual environment and verify:

```python
import arcadia
from arcadia.config import ArcadiaConfig, dumps_config, loads_config

config = ArcadiaConfig()
assert loads_config(dumps_config(config)) == config
```

Never claim an unexecuted command passed.

## Definition of done

- [ ] Every required public export exists.
- [ ] No new runtime dependency was added.
- [ ] Default and representative configurations round-trip.
- [ ] References, requested settings, extensions, retry, and output settings validate.
- [ ] All public failures use stable `ConfigurationError` codes.
- [ ] Atomic saves preserve existing files on injected failures.
- [ ] Snapshotting detaches nested structures.
- [ ] Loading never writes.
- [ ] No runtime service, hardware, transport, event, storage, analysis, CLI, or UI behavior was added.
- [ ] Root import remains lightweight.
- [ ] Ruff, mypy, pytest, build, and clean-wheel validation pass.
- [ ] This same file contains an honest completion record.
- [ ] `docs/sessions/README.md` marks Session 02 completed only after validation succeeds.

## Stop conditions

Stop and record the issue rather than expanding scope if implementation requires changing Session 01 models, runtime behavior, a new dependency, or unrelated repository repairs.

---

# Completion record

The implementation agent replaces the placeholders before stopping.

## Outcome

Session 02 is complete. The `arcadia.config` package implements the full JSON configuration layer with validated Pydantic models for compute nodes, service profiles, stage bindings, tool profiles, retry and output settings, plus file I/O with atomic saves and snapshot support. All definition-of-done validation passes.

## Files changed

### Source
- `src/arcadia/config/__init__.py` — public re-export surface (14 symbols)
- `src/arcadia/config/models.py` — CONFIG_SCHEMA_VERSION, NodeKind, NodeConfig, ServiceProfile, StageBinding, ToolProfile, RetryPolicy, OutputSettings, ArcadiaConfig with cross-reference validation
- `src/arcadia/config/files.py` — load_config, loads_config, save_config, dumps_config, snapshot_config with typed ConfigurationError codes

### Tests
- `tests/unit/config/__init__.py` — test package marker
- `tests/unit/config/test_models.py` — model validation (default config, node rules, one-local-node limit, name trimming, LLM/visual-LLM/SAM profiles, reference validation, profile reuse, extensions, unknown field rejection, retry boundaries, output validation, schema version, typed addresses, non-string keys, and normalized-key collisions)
- `tests/unit/config/test_serialization.py` — serialization (loads, malformed JSON, non-object roots, validation conversion, deterministic formatting, Unicode, trailing newline, load/dump/load equality, snapshot detachment)
- `tests/integration/test_config_files.py` — file I/O (missing/undecodable files, round trip, parent creation, non-mutating loads, atomic replacement, complete handling of partial writes, write/replace failure injection, temp cleanup, typed error codes, no POSIX-only assumptions)
- `tests/test_package.py` — added `test_import_arcadia_does_not_import_config` and `test_config_imports_no_heavy_or_future_modules`

### Documentation
- `docs/sessions/02-configuration.md` — updated status to completed, filled completion record
- `docs/sessions/README.md` — marked Session 02 completed

## Delivered public API

`from arcadia.config import ...` exposes all 14 required symbols:
CONFIG_SCHEMA_VERSION, NodeKind, NodeConfig, ServiceProfile, StageBinding, ToolProfile, RetryPolicy, OutputSettings, ArcadiaConfig, load_config, loads_config, save_config, dumps_config, snapshot_config.

The root `arcadia` package does NOT re-export these — `arcadia.config` must be imported explicitly.

## Configuration schema delivered

Root fields: `schema_version` (validated int, defaults to 1), `nodes` (dict[str, NodeConfig]), `service_profiles` (dict[str, ServiceProfile]), `tool_profiles` (dict[str, ToolProfile]), `retry` (RetryPolicy), `output` (OutputSettings), `extensions` (dict[str, JsonValue]).

Profile types: NodeConfig (kind/address/description/extensions), ServiceProfile (node/spec/description/extensions), StageBinding (service_profile/extensions), ToolProfile (tool_name/stages/settings/description/extensions).

References: service profiles reference nodes by name; stage bindings reference service profiles by name. Both are validated at ArcadiaConfig construction.

Version behavior: missing version defaults to 1; any other version raises ConfigurationError with code `config_unsupported_version`.

## State and side effects

The `arcadia.config` module owns no global active configuration or singleton store. The only side effects are explicit reads and writes from `load_config()` and `save_config()`. `save_config` uses atomic replacement: serialize first, create parent directories, write all UTF-8 payload bytes to a temp file in the destination directory (looping across short writes), fsync, then `os.replace`. On failure, the temp file is cleaned up and the existing destination is left unchanged. `load_config` never writes. `snapshot_config` performs no I/O.

## Errors and events

All public parsing and file functions raise `ConfigurationError` with stable codes: `config_not_found`, `config_read_failed`, `config_decode_failed`, `config_invalid_json`, `config_invalid_format`, `config_validation_failed`, `config_unsupported_version`, `config_serialization_failed`, `config_write_failed`. All are non-retryable by default. Causes are retained on the exception object but excluded from serialization. Validation details include sanitized field location, message, and validation type only — no full configuration text, arbitrary invalid objects, or tracebacks. No events are emitted.

## Tests and validation

All definition-of-done checks pass:
- `python -m pip install -e ".[dev]"` — success
- `ruff format --check .` — 40 files already formatted
- `ruff check .` — all checks passed
- `mypy src/arcadia` — no issues found in 10 source files
- `pytest` — 335 passed
- `python -m build` — built wheel and sdist
- Clean-venv wheel install + `import arcadia; from arcadia.config import ArcadiaConfig, dumps_config, loads_config; config = ArcadiaConfig(); assert loads_config(dumps_config(config)) == config` — success

## Decisions and deviations

No deviations from the session contract. All required exports, rules, and validation behaviors are implemented as specified.

Implementation decisions (within the specified choices):
- `schema_version` uses `int` type with a before-validator rather than `Literal[1]` so that unsupported versions raise `ConfigurationError` with `config_unsupported_version` code instead of a generic Pydantic `literal_error`.
- Boolean rejection for numeric fields uses `mode="before"` validators to catch booleans before Pydantic coerces them to integers.
- `ServiceProfile.spec` accepts dict mappings parsed by the public `parse_service_spec` API and already-parsed `ServiceSpec` instances.
- `NodeConfig.address` is explicitly typed as public `NodeAddress | None`; arbitrary duck-typed address objects are rejected.
- Named mapping keys require strings, are trimmed and control-checked, and reject normalized-name collisions instead of silently overwriting entries.
- All mutable mapping defaults use `Field(default_factory=dict)`.

## Known limitations

No known limitations. The session implements the full contract without scope reduction.

## Assumptions and risks

Later sessions depend on the stable contract defined here. The `arcadia.config` module adds no new runtime dependencies — it uses only Pydantic 2 (already required by Session 01) and the Python standard library.

## Next-session prerequisites

`from arcadia.config import ...` provides:
- Models: `ArcadiaConfig`, `NodeConfig`, `NodeKind`, `ServiceProfile`, `StageBinding`, `ToolProfile`, `RetryPolicy`, `OutputSettings`
- File I/O: `load_config`, `loads_config`, `save_config`, `dumps_config`, `snapshot_config`
- Constant: `CONFIG_SCHEMA_VERSION = 1`

All models are frozen, JSON-round-trippable, and reject unknown fields. Configuration is human-editable JSON with atomic saves. No global state, no events, no service lifecycle.
