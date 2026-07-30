# Session 05: Hardware Detection and Runtime Resolution

- Status: completed
- Branch: `session/05-hardware-runtime`
- Owner: local agent session
- Module: `arcadia.hardware`

## Objective

Implement the hardware-capability and runtime-resolution layer for headless ARCADIA.

Session 05 must provide:

- a validated, versioned hardware snapshot suitable for transport and run manifests;
- best-effort CPU, memory, NVIDIA CUDA, and Apple Silicon Metal detection;
- deterministic device resolution for LLM, visual-LLM, and SAM3 service specs;
- preservation of advanced requested settings this module does not interpret;
- typed failures for invalid or unavailable explicit device requests;
- no GPU allocation, model loading, service startup, networking, or heavy imports.

This session reports what execution devices appear available and creates a reproducible resolved-settings record. It does **not** prove that a future backend is installed, compiled for that device, or able to fit a particular model.

## Prerequisites

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/README.md
docs/sessions/04-run-storage-and-reproducibility.md
src/arcadia/models/**
src/arcadia/storage/models.py
tests/test_package.py
pyproject.toml
```

Important rules:

- CUDA and Apple Silicon Metal/MPS are the initial accelerated platform targets.
- Requested and resolved settings are separate objects; never mutate requested objects.
- Explicit unavailable overrides fail rather than silently falling back.
- No model-size, context, KV-cache, or checkpoint fit estimation in the prototype.
- Hardware is below services and transport in the dependency graph.
- `RunManifest.hardware` already accepts generic JSON; do not change its schema.
- Installed backend readiness belongs to Sessions 07 and 08, not hardware detection.
- Use only public APIs from earlier modules.

The legacy repository may be inspected read-only for platform ideas, but do not copy legacy global state or UI-shaped dictionaries.

## Session workflow

1. Start from the latest `headless-core`.
2. Create or switch to `session/05-hardware-runtime`.
3. Add this file at `docs/sessions/05-hardware-detection-and-runtime-resolution.md`; set status to `in-progress` in the first session commit.
4. Run baseline validation.
5. Implement only this work order.
6. Run required validation and a clean-wheel smoke test.
7. Update this same file with the completion record and final status.
8. Mark Session 05 completed in `docs/sessions/README.md` only after validation succeeds.
9. Do not create a separate prompt, design, or handoff document.

## Scope

### Allowed files

```text
src/arcadia/hardware/**
tests/unit/hardware/**
tests/contract/test_hardware_serialization.py
tests/integration/test_hardware_storage.py
tests/test_package.py
docs/sessions/05-hardware-detection-and-runtime-resolution.md
docs/sessions/README.md
```

Modify `pyproject.toml` only if package discovery requires it. Add no runtime dependency.

### Prohibited work

Do not implement or modify:

- service lifecycle, ports, downloads, launch flags, health checks, or process control;
- SAM model loading or inference;
- instruction transport or direct inference clients;
- retry loops, tools, Priority Map, analysis, CLI, or UI;
- config precedence, environment merging, or run-manifest migrations;
- background refresh, global detector singletons, or resource schedulers;
- model-fit estimates or automatic tuning of context, batching, KV cache, or GPU layers;
- AMD/ROCm, Intel GPU, DirectML, Vulkan, or distributed resource aggregation;
- checks that import Torch, llama-cpp-python, MLX, SAM, CUDA Python, or NVML packages.

Do not add `psutil`, `torch`, `pynvml`, `nvidia-ml-py`, `mlx`, `llama-cpp-python`, or another runtime dependency.

Do not change Session 01-04 public contracts unless a genuine blocker is documented and work stops for review.

## Package structure

```text
src/arcadia/hardware/
├── __init__.py
├── errors.py
├── models.py
├── detection.py
└── resolution.py
```

A small private helper module is acceptable. Avoid a large platform class hierarchy.

## Required public API

`from arcadia.hardware import ...` must expose:

```text
HARDWARE_SCHEMA_VERSION
OperatingSystem
DeviceKind
PlatformInfo
CpuInfo
MemoryInfo
AcceleratorInfo
HardwareCapabilities
HardwareDetector
SystemHardwareDetector
HardwareError
HardwareDetectionError
RuntimeResolutionError
detect_hardware
resolve_runtime_settings
```

Do not re-export these from `arcadia.__init__`. Root import must not eagerly import `arcadia.hardware`.

## Errors

All exceptions derive from public `ArcadiaError`.

| Exception | Default code | Retryable |
|---|---|---:|
| `HardwareError` | `hardware_error` | false |
| `HardwareDetectionError` | `hardware_detection_failed` | false |
| `RuntimeResolutionError` | `runtime_resolution_failed` | false |

Use these stable override codes where applicable:

```text
hardware_probe_failed
hardware_snapshot_invalid
runtime_settings_invalid
reserved_runtime_setting
requested_device_unavailable
requested_device_index_unavailable
```

Translate raw subprocess, CSV, `ctypes`, platform-query, Pydantic, and OS failures at public boundaries. Retain useful causes, but details must be sanitized and JSON-compatible. Never expose full command output, environment variables, arbitrary file contents, or tracebacks.

Optional platform probes are best-effort. Missing or failed optional utilities normally produce a concise note and partial snapshot, not a fatal error.

## Models

Use Pydantic 2 models with `extra="forbid"`, `frozen=True`, and `validate_default=True`. Validate defaults, reject unknown fields and non-finite floats, defensively copy mutable JSON values, and support lossless JSON round trips.

### Constants and enums

```python
HARDWARE_SCHEMA_VERSION = 1


class OperatingSystem(StrEnum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    OTHER = "other"


class DeviceKind(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"
    METAL = "metal"
```

Enum member names remain uppercase while serialized values remain lowercase.

### Model fields

```python
class PlatformInfo:
    operating_system: OperatingSystem
    release: str
    version: str
    machine: str
    python_version: str


class CpuInfo:
    logical_cores: int
    physical_cores: int | None = None
    architecture: str
    model: str | None = None


class MemoryInfo:
    total_bytes: int | None = None
    available_bytes: int | None = None


class AcceleratorInfo:
    kind: Literal[DeviceKind.CUDA, DeviceKind.METAL]
    index: int
    name: str
    total_memory_bytes: int | None = None
    available_memory_bytes: int | None = None
    driver_version: str | None = None
    identifier: str | None = None
    details: dict[str, JsonValue] = {}


class HardwareCapabilities:
    schema_version: int = HARDWARE_SCHEMA_VERSION
    detected_at: datetime
    platform: PlatformInfo
    cpu: CpuInfo
    memory: MemoryInfo
    accelerators: tuple[AcceleratorInfo, ...] = ()
    notes: tuple[str, ...] = ()
```

Validation requirements:

- accept only exact integer schema version `1`; reject `True`, `1.0`, and `"1"`;
- reject naive timestamps and normalize aware timestamps to UTC;
- trim strings, reject controls, and require non-empty machine, Python version, architecture, accelerator names, and present optional strings;
- core, index, and byte counts are exact integers, never booleans;
- `logical_cores >= 1`; known physical cores are between 1 and logical cores;
- known total memory is positive; known available memory is non-negative and no greater than known total;
- accelerator identities are unique by `(kind, index)`;
- accelerator order is deterministic: CUDA by index, then Metal by index;
- notes are trimmed, non-empty, deterministic strings;
- `details` is recursively JSON-compatible and defensively copied;
- Apple unified memory belongs in `MemoryInfo`, not dedicated accelerator VRAM.

`HardwareCapabilities.available_devices` is a read-only property returning CPU first, followed by detected CUDA and Metal kinds without duplicates.

Do **not** add `available_backends`: hardware detection cannot prove that an inference package or executable is installed and compatible.

## Detection API

```python
@runtime_checkable
class HardwareDetector(Protocol):
    def detect(self) -> HardwareCapabilities: ...


class SystemHardwareDetector:
    def __init__(self, *, command_timeout_seconds: float = 5.0) -> None: ...
    def detect(self) -> HardwareCapabilities: ...


def detect_hardware(
    detector: HardwareDetector | None = None,
) -> HardwareCapabilities: ...
```

Requirements:

- timeout is finite and greater than zero;
- constructor and module import perform no probing, subprocess execution, or caching;
- each `detect()` call creates a new snapshot and owns no authoritative state afterward;
- `detect_hardware()` defaults to `SystemHardwareDetector()`;
- validate and detach custom-detector results;
- translate invalid results or arbitrary custom-detector exceptions to `HardwareDetectionError` with retained cause;
- no global cache.

## System detection behavior

Detection is synchronous, bounded, read-only, standard-library only, and never uses `shell=True`.

Every successful real-system snapshot contains current UTC time, normalized platform data, CPU architecture, at least one logical core, best-effort physical-core/model data, best-effort memory data, accelerators, and concise caveat notes.

Use `os.cpu_count()` for the portable logical-core baseline. When invalid or `None`, use `1` and record a note.

### Linux

Use narrow standard-library reads such as `/proc/cpuinfo`, `/proc/meminfo`, and `os.sysconf` as appropriate. Parse defensively, tolerate missing fields, require no root access, and do not scan arbitrary device files. Cgroup-limit interpretation is out of scope.

### Windows

Use `platform`, `os`, and a narrow correctly typed `ctypes` wrapper for memory information. Do not require PowerShell, WMI packages, registry mutation, or admin access. Optional physical-core/model failures become notes.

### macOS / Apple Silicon

Use bounded read-only `sysctl` and optionally `system_profiler` commands.

- Identify Apple Silicon from macOS plus `arm64`/`aarch64`.
- Report one Metal accelerator at index `0` for Apple Silicon.
- Use a detected descriptive name or stable fallback `Apple Silicon GPU`.
- Keep unified memory in system memory; do not claim dedicated VRAM.
- Intel Mac Metal detection is outside initial scope.

### NVIDIA CUDA

Invoke `nvidia-smi` directly with a bounded timeout and machine-readable CSV output.

- Query only index, name, total/free memory, driver version, and UUID/identifier.
- Parse with standard-library `csv`, not naive comma splitting.
- Convert MiB to bytes using `1024 * 1024`.
- Sort by numeric index.
- Missing executable, timeout, non-zero exit, empty output, unsupported query, or malformed output produces a sanitized note and no CUDA accelerators.
- If any row is malformed, discard the CUDA result as a unit; do not expose a partially trusted inventory.
- Do not use Torch, CUDA runtime APIs, or NVML Python bindings.

A visible NVIDIA device does not prove a future backend was compiled with CUDA support.

Notes are reproducibility caveats, not logs. Never include full utility output, stack traces, usernames, home paths, or secrets.

## Runtime resolution

Implement a pure function:

```python
def resolve_runtime_settings(
    spec: ServiceSpec,
    hardware: HardwareCapabilities,
) -> ResolvedRuntimeSettings: ...
```

Requirements:

- require public service-spec and hardware model instances;
- never mutate the spec, requested settings, values mapping, or hardware;
- begin with a defensive copy of all requested values;
- preserve unknown JSON-compatible advanced settings exactly;
- interpret only `device`, `device_index`, and `threads`;
- return a fresh public `ResolvedRuntimeSettings`;
- equal inputs produce equal outputs;
- perform no I/O, optional imports, environment reads, subprocess calls, sleeps, or events.

### Backend field

Set `ResolvedRuntimeSettings.backend` from service type:

| Service type | Backend |
|---|---|
| `llm` | `llama_cpp` |
| `visual_llm` | `llama_cpp` |
| `sam3` | `sam3` |

Reject a requested `backend` key with `reserved_runtime_setting`; backend identity is not an arbitrary backend flag here.

### Device

Accepted requested values after trim/case normalization:

```text
auto
cpu
cuda
metal
mps
```

Rules:

- missing means `auto`;
- `auto` preference is CUDA, then Metal, then CPU;
- normalize `mps` to resolved `metal` and add a note;
- explicit CPU always succeeds;
- explicit CUDA requires at least one CUDA accelerator;
- explicit Metal/MPS requires a Metal accelerator;
- invalid values use `runtime_settings_invalid`;
- unavailable explicit devices use `requested_device_unavailable`;
- never silently fall back from an explicit unavailable request;
- resolved values always contain concrete `device`: `cpu`, `cuda`, or `metal`.

### Device index

- Exact integer at least zero; booleans are invalid.
- Valid only when resolved device is CUDA.
- With CUDA and no requested index, choose the lowest detected index.
- A requested index must match a detected CUDA accelerator.
- Missing index uses `requested_device_index_unavailable`.
- An index supplied for CPU or Metal uses `runtime_settings_invalid`.
- Resolved CUDA values contain selected `device_index`; CPU/Metal values omit it.

### Threads

- When supplied, require an exact integer at least one; booleans are invalid.
- Preserve it after validation.
- Do not invent a thread default.
- Do not reject it merely because a GPU was selected; later backends own that interpretation.

### Notes and limits

Use deterministic `ResolvedRuntimeSettings.notes` only for automatic decisions, for example:

```text
device auto-selected CUDA accelerator 0
no supported accelerator detected; device auto-selected CPU
normalized requested device 'mps' to 'metal'
```

Do not inspect model/checkpoint files, estimate memory fit, choose context/batch/KV/GPU-layer settings, verify compiled backend support, rewrite unknown values, read environment overrides, or merge config profiles.

## State and side effects

- Models and runtime resolution are pure.
- Real detection performs bounded read-only OS inspection and optional subprocess calls.
- No writes, network access, listeners, model loads, GPU allocation, retries, background threads, async tasks, or global mutable state.
- Available-memory fields may naturally differ between calls.
- Concurrent detector calls must not share mutable state.

## Storage integration

Do not modify `RunManifest` or storage source.

Supported use:

```python
payload = capabilities.model_dump(mode="json")
updated = manifest.model_copy(update={"hardware": payload})
store.write_manifest(updated)
```

The integration test must prove a representative hardware payload and resolved settings survive Session 04 manifest write/read and can be reconstructed as equal models. Session 05 does not automatically update manifests; the future analysis engine owns that timing.

## Tests required

### Models and serialization

Cover CPU-only, multi-CUDA, and Apple Silicon snapshots; exact schema version; UTC behavior; numeric/bool rejection; optional memory; duplicate accelerators; deterministic ordering; JSON details; notes; `available_devices`; unknown fields; and dump/load equality.

### Detection

Use simulated platform/probe results so ordinary CI needs no GPU or specific OS. Cover:

- import and construction with no side effects;
- Linux CPU/memory parsing;
- Windows memory success/failure;
- Apple Silicon Metal with detected and fallback names;
- Intel macOS not inferred as Apple Silicon;
- one/multiple CUDA GPUs, comma-containing names, MiB conversion, and sorting;
- missing, timed-out, non-zero, empty, unsupported, and malformed `nvidia-smi` results;
- malformed CUDA output discarding the complete CUDA probe;
- invalid `os.cpu_count()` fallback;
- partial optional-probe failures returning valid snapshots;
- no shell and finite timeout;
- repeated calls returning detached, uncached snapshots;
- custom detector success, invalid return, and exception translation.

A real-host smoke test may assert only platform-neutral invariants.

### Resolution

Cover every service type; backend mapping; auto preference; explicit devices; MPS alias; invalid/unavailable devices; default/explicit CUDA indexes; invalid/non-CUDA indexes; threads; reserved backend; unknown passthrough settings; unchanged inputs after success/failure; deterministic output; and stable safe errors.

### Storage and package contracts

Cover hardware/resolved-setting manifest round trip without storage changes. Update package tests to prove:

- root import does not load hardware;
- hardware import does not probe or start subprocesses;
- hardware imports no config, events, storage, services, backends, transport, inference, tools, analysis, CLI, UI, or heavy inference packages;
- earlier tests remain unchanged and pass.

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

Focused command:

```bash
pytest tests/unit/hardware tests/contract/test_hardware_serialization.py tests/integration/test_hardware_storage.py
```

Install the wheel in a clean environment and verify:

```python
from arcadia.hardware import DeviceKind, HardwareCapabilities, detect_hardware

caps = detect_hardware()
assert caps.cpu.logical_cores >= 1
assert caps.available_devices[0] == DeviceKind.CPU
assert HardwareCapabilities.model_validate_json(caps.model_dump_json()) == caps
```

Also smoke-test pure runtime resolution with synthetic hardware so the test does not depend on an accelerator.

Never claim an unexecuted command passed. Record OS-specific simulated coverage separately from real-hardware validation.

## Definition of done

- [x] Required exports exist; root import stays lightweight.
- [x] No runtime dependency is added.
- [x] Models validate and round-trip.
- [x] Detection is bounded, read-only, best-effort, and standard-library only.
- [x] CPU, memory, CUDA, and Apple Silicon paths have simulated tests.
- [x] Optional probe failure preserves a useful partial snapshot.
- [x] Import and construction perform no probing.
- [x] Resolution is deterministic and never mutates inputs.
- [x] Auto selection follows CUDA, Metal, CPU.
- [x] Explicit unavailable devices/indexes fail with stable typed errors.
- [x] Unknown advanced settings pass through unchanged.
- [x] No fit or installed-backend claims are made.
- [x] Hardware and resolved settings persist through Session 04 contracts.
- [x] Ruff, mypy, pytest, build, and clean-wheel validation pass.
- [x] This file contains an honest completion record.
- [x] Session index is updated only after completion.

## Stop conditions

Stop and record the issue rather than expanding scope if implementation requires changing `RequestedRuntimeSettings`, `ResolvedRuntimeSettings`, `ServiceSpec`, or `RunManifest`; adding a runtime dependency; importing heavy inference packages; implementing service/backend behavior; estimating model fit; adding unsupported accelerators; changing dependency direction; or weakening package-isolation tests.

A partial implementation with an accurate record is preferable to an undocumented contract change.

---

# Completion record

The implementation agent fills this section before stopping and changes the top status to `completed`, `partial`, or `blocked`.

## Outcome

Completed. `arcadia.hardware` provides validated, versioned hardware snapshots; bounded standard-library system detection; and pure runtime-device resolution for the existing service specifications.

## Files changed

- `src/arcadia/hardware/__init__.py`
- `src/arcadia/hardware/errors.py`
- `src/arcadia/hardware/models.py`
- `src/arcadia/hardware/detection.py`
- `src/arcadia/hardware/resolution.py`
- `tests/unit/hardware/__init__.py`
- `tests/unit/hardware/test_models.py`
- `tests/unit/hardware/test_detection.py`
- `tests/unit/hardware/test_resolution.py`
- `tests/contract/test_hardware_serialization.py`
- `tests/integration/test_hardware_storage.py`
- `tests/test_package.py`
- `docs/sessions/05-hardware-detection-and-runtime-resolution.md`
- `docs/sessions/README.md`

## Delivered public API

`arcadia.hardware` exports `HARDWARE_SCHEMA_VERSION`, the operating-system/device enums, all hardware snapshot models, detector protocol and system detector, typed hardware errors, `detect_hardware`, and `resolve_runtime_settings`. `arcadia` does not re-export or import this module eagerly.

## State and side effects

Models and resolution are attribute-frozen and defensively copied value operations. `SystemHardwareDetector.detect()` performs bounded read-only platform inspection and direct `nvidia-smi`/`sysctl` probes only when called; it caches nothing, allocates no GPU resources, starts no service, and performs no network I/O.

## Errors and events

All public failures derive from `ArcadiaError`. Detection translates invalid custom snapshots and probe failures to `HardwareDetectionError`; resolution uses `RuntimeResolutionError` with stable invalid-setting, reserved-setting, unavailable-device, and unavailable-index codes. This module emits no events.

## Tests and validation

Baseline:

- `python -m pip install -e ".[dev]"` — success.
- Initial `ruff format --check .` — reported this new session document as the only file requiring formatting; it was formatted before implementation validation.

Completed:

- Focused validation: `ruff format --check src/arcadia/hardware tests/unit/hardware tests/contract/test_hardware_serialization.py tests/integration/test_hardware_storage.py tests/test_package.py && ruff check src/arcadia/hardware tests/unit/hardware tests/contract/test_hardware_serialization.py tests/integration/test_hardware_storage.py tests/test_package.py && mypy src/arcadia && pytest tests/unit/hardware tests/contract/test_hardware_serialization.py tests/integration/test_hardware_storage.py tests/test_package.py` — 42 passed.
- `ruff format --check .` — 72 files already formatted.
- `ruff check .` — success.
- `mypy src/arcadia` — success.
- `pytest` — 467 passed.
- `python -m build` — sdist and wheel built successfully.
- Clean-wheel smoke test in `/tmp/arcadia-wheel-smoke-05` — installed the wheel, detected local hardware, validated the CPU/device and JSON round-trip invariants, and exercised CPU runtime resolution using synthetic hardware.

Simulated unit coverage exercises Linux CPU/memory, Windows-memory failures and the typed `GlobalMemoryStatusEx` wrapper, Apple Silicon Metal and fallback name, zero-value macOS optional probes, Intel macOS exclusion, CUDA CSV ordering/comma names/MiB conversion, empty/nonzero/unsupported/malformed/failed CUDA probes, finite timeout validation, direct `shell=False` command invocation, repeated detached detection, partial snapshots, detached custom detectors, and resolution outcomes. No manual CUDA-host validation was performed.

## Decisions and deviations

No earlier public contract changed and no runtime dependency was added. Hardware reports visible execution devices only; it intentionally does not claim inference backend installation, compilation compatibility, model fit, or GPU allocation capability.

## Known limitations

Detection is intentionally limited to CPU, NVIDIA CUDA through `nvidia-smi`, and Apple Silicon Metal. It does not discover AMD, Intel, or other accelerators, infer cgroup limits, or prove future backend availability.

## Assumptions and risks

Available-memory observations can differ across calls. NVIDIA visibility and Apple Silicon classification indicate an execution target candidate, not an installed or compatible inference backend.

## Next-session prerequisites

Sessions 06–08 can consume immutable `HardwareCapabilities` snapshots and `ResolvedRuntimeSettings`; callers retain responsibility for persisting snapshots and determining backend readiness or model fit.
