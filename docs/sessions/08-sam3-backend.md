# Session 08: SAM 3 Backend and Image Segmentation Service

- Status: in-progress
- Branch: `headless-core` — direct implementation and push required by the operator
- Owner: local agent session
- Module: `arcadia.backends.sam3`
- Canonical path: `docs/sessions/08-sam3-backend.md`

## Objective

Implement the second real ARCADIA service backend: a synchronous Meta SAM 3 image-segmentation service for `SamServiceSpec`.

Session 08 must deliver:

- a `ServiceBackend` implementation with stable backend ID `sam3`;
- validation and use of one manually supplied local SAM 3 checkpoint;
- a dedicated managed worker subprocess that loads the model once;
- a small HTTP image-segmentation service bound to the requested inference port;
- stable health, information, segmentation-request, segmentation-response, and error schemas;
- text-prompt image segmentation returning masks, labels, confidences, boxes, and image dimensions as JSON-compatible arrays;
- one live SAM 3 model per backend/node process and serialized model inference;
- explicit CUDA-only production support for the initial backend, with typed rejection of CPU and Metal requests rather than silent fallback;
- complete owned-process-tree termination on macOS/Linux and Windows;
- safe bounded diagnostics and logs while running and after stop;
- transactional cleanup when startup fails;
- lazy optional dependencies so the base package remains lightweight;
- tests requiring no real checkpoint, GPU, external network, Torch, or installed SAM 3 runtime;
- final commits pushed directly to `origin/headless-core`.

This session implements the SAM 3 backend and the service hosted behind its inference port. Generic port ownership, replacement, operation history, lifecycle events, and node shutdown remain owned by Session 06 `ServiceManager`. Remote instruction transport and the reusable direct-inference client remain Sessions 09–12.

## Authoritative context

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/README.md
docs/sessions/05-hardware-detection-and-runtime-resolution.md
docs/sessions/06-service-manager.md
docs/sessions/07-llama-cpp-backend.md
src/arcadia/models/common.py
src/arcadia/models/services.py
src/arcadia/models/errors.py
src/arcadia/hardware/resolution.py
src/arcadia/services/backend.py
src/arcadia/services/models.py
src/arcadia/services/manager.py
src/arcadia/backends/llama_cpp/**
tests/contract/test_service_backend_contract.py
tests/test_package.py
pyproject.toml
```

Inspect the legacy Almost ARCADIA SAM code read-only for behavioral characterization where useful. Do not import the legacy package or reproduce its global state, UI state, hidden mock fallback, target-coordinate output, or mixed model/server/orchestration ownership.

Review the current official SAM 3 repository and README before implementing the real runtime boundary:

```text
https://github.com/facebookresearch/sam3
https://github.com/facebookresearch/sam3/blob/main/README.md
https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md
```

Do not assume an upstream API from memory. Pin implementation behavior to the installed package APIs actually exercised by tests or the optional manual smoke.

Relevant project rules:

- Service identity is node session plus inference port.
- `ServiceManager` owns lifecycle policy and opaque backend instances.
- The backend that creates an instance exclusively owns its process, runtime files, health checks, logs, and cleanup.
- `ServiceBackend.start()` is transactional and releases everything created during a failed attempt.
- Process backends terminate their complete owned process tree.
- The operator supplies a local checkpoint path. ARCADIA does not download SAM checkpoints.
- One SAM model is loaded per node/backend instance and model inference is serialized.
- Inference goes directly to the returned SAM service endpoint, not through the future instruction server.
- Requested and resolved settings are immutable inputs and are never mutated.
- Production failures never substitute a mock model, empty fake result, or fake endpoint.
- Root and base-package imports remain lightweight.
- Source images remain on the orchestrator until sent to an inference endpoint.
- The initial prototype may use JSON-compatible arrays even when they are not the most bandwidth-efficient encoding.

Current upstream limitations must be represented honestly:

- The official SAM 3 repository currently documents Python 3.12+, PyTorch 2.7+, and a CUDA-compatible GPU as prerequisites.
- The official checkpoint workflow is gated and operator-managed.
- The initial ARCADIA implementation therefore supports real CUDA execution only.
- CPU and Apple Metal remain detectable by Session 05 but are not claimed as supported by this backend.
- SAM 3.1 checkpoint compatibility must not be claimed unless the exact installed upstream code and checkpoint are proven together. Do not add checkpoint-key rewriting or unofficial compatibility patches in this session.

## Git and delivery workflow

This session intentionally overrides the normal per-session branch convention. Work directly on `headless-core` and publish the completed session there.

Before editing:

```bash
git fetch origin
git switch headless-core
git pull --ff-only origin headless-core
git status --short
```

Requirements:

1. Begin only from a clean, current `headless-core`.
2. Copy this file to `docs/sessions/08-sam3-backend.md`.
3. Change its status to `in-progress`.
4. Commit and push the session start before implementation:

   ```bash
   git add docs/sessions/08-sam3-backend.md
   git commit -m "docs: start SAM 3 backend session"
   git push origin headless-core
   ```

5. Implement only this work order.
6. Run all required validation.
7. Fill in the completion record and set status to `completed`, `partial`, or `blocked`.
8. Mark Session 08 in `docs/sessions/README.md` only when the final status is `completed`.
9. Commit the implementation and documentation with a clear message such as:

   ```bash
   git commit -m "feat: add SAM 3 service backend"
   ```

10. Push directly to `origin/headless-core`.
11. Never force-push.
12. If the remote moved, fetch and rebase the clean local commits onto `origin/headless-core`, rerun affected validation, and push normally.
13. Before stopping, verify:

   ```bash
   git status --short
   git fetch origin
   test "$(git rev-parse HEAD)" = "$(git rev-parse origin/headless-core)"
   ```

The final working tree must be clean and the final local commit must exist on `origin/headless-core`. If blocked or partial, commit and push the honest completion record rather than leaving local-only work.

## Scope

### Allowed files

```text
src/arcadia/backends/__init__.py
src/arcadia/backends/sam3/**
tests/unit/backends/sam3/**
tests/contract/test_sam3_backend_contract.py
tests/contract/test_sam3_inference_protocol.py
tests/integration/test_sam3_backend_integration.py
tests/integration/test_sam3_worker_integration.py
tests/helpers/**
tests/test_package.py
pyproject.toml
docs/sessions/08-sam3-backend.md
docs/sessions/README.md
```

Only add or modify a helper under `tests/helpers/` when more than one Session 08 test module uses it.

### Prohibited changes

Do not implement or modify:

- Session 01 service specifications, statuses, endpoint models, or shared error hierarchy;
- Session 03 event models or sinks;
- Session 05 hardware detection or runtime resolution;
- Session 06 manager lifecycle, backend protocol, slot records, concurrency, operation history, or events;
- Session 07 llama.cpp backend behavior or public API;
- instruction protocol/server/client, reusable direct inference clients, Tool SDK, analysis engine, Priority Map, CLI, Django, or UI;
- video segmentation, tracking, sessions, or temporal memory;
- point, box, mask, exemplar-image, or agent prompts;
- model training, fine-tuning, evaluation, checkpoint conversion, or checkpoint-key repair;
- Hugging Face authentication, checkpoint download, gated-repository automation, or cache management;
- automatic GPU/resource-fit estimation or device fallback;
- background crash polling, automatic restart, or autonomous service replacement;
- multiple Uvicorn workers, multiple model replicas, or parallel SAM inference;
- multipart upload, WebSocket streaming, shared-memory transport, compressed mask formats, or RLE optimization;
- arbitrary user-provided child environment variables, Python modules, commands, or secrets;
- shell command construction or `shell=True`;
- production mock inference or hidden empty-result fallback.

Do not silently change an earlier public contract. Stop and record a blocker if the existing `ServiceBackend` contract cannot support the implementation.

## Package structure

Create a package equivalent to:

```text
src/arcadia/backends/sam3/
├── __init__.py
├── backend.py
├── checkpoint.py
├── config.py
├── health.py
├── process.py
├── protocol.py
├── runtime.py
├── settings.py
└── worker.py
```

A slightly smaller internal layout is acceptable, but keep these responsibilities separable and independently testable:

- public protocol models;
- backend configuration;
- checkpoint validation;
- resolved-setting translation;
- child-process ownership;
- HTTP health probing;
- model-runtime adaptation;
- worker application/entry point;
- `ServiceBackend` orchestration.

`arcadia.backends.__init__` must not eagerly import concrete implementations. Do not re-export this package from `arcadia.__init__` or `arcadia.services`.

`protocol.py` must remain lightweight and importable without Torch, NumPy, Pillow, FastAPI, Uvicorn, or SAM 3.

## Optional dependencies and runtime environment

Keep the base dependency list unchanged.

Update the existing `sam` optional dependency group with bounded worker-service dependencies equivalent to:

```toml
sam = [
    "fastapi>=0.115,<1",
    "uvicorn>=0.34,<1",
    "pillow>=11,<13",
    "numpy>=2,<3",
]
```

Adjust lower bounds only when a concrete used API justifies it.

Do **not** add Torch, TorchVision, CUDA wheels, or the official `sam3` repository as unconditional project dependencies. They are platform-specific and must be installed by the operator in the configured SAM worker Python environment.

The selected worker Python environment must contain:

- Python 3.12 or newer;
- the built/current `arcadia-core[sam]` package;
- a compatible CUDA-enabled PyTorch and TorchVision installation;
- the official SAM 3 package from its repository;
- any upstream runtime dependencies required by that exact SAM 3 revision;
- access to the manually downloaded checkpoint path.

All imports of FastAPI, Uvicorn, Pillow, NumPy, Torch, TorchVision, or SAM 3 must be lazy. Importing `arcadia.backends.sam3`, constructing protocol/configuration objects, and constructing a backend with injected fakes must work in a base installation.

## Required public API

`from arcadia.backends.sam3 import ...` must expose:

```text
SAM3_BACKEND_ID
SAM3_INFERENCE_SCHEMA_VERSION
Sam3BackendConfig
Sam3Backend
Sam3SegmentRequest
Sam3SegmentResponse
Sam3ErrorResponse
```

Constants:

```python
SAM3_BACKEND_ID = "sam3"
SAM3_INFERENCE_SCHEMA_VERSION = 1
```

`Sam3Backend` must satisfy `isinstance(backend, ServiceBackend)` through the runtime-checkable Session 06 protocol.

Do not add a new exception hierarchy. Backend failures use existing `ServiceError`, `ServiceConflictError`, `ServiceStartupError`, and `ServiceHealthError` with stable Session 08 codes. HTTP error payloads use existing `ArcadiaErrorInfo`.

## Public inference protocol

Use Pydantic 2 models with `extra="forbid"`, frozen values, validated defaults, aware serialization behavior where applicable, defensive copies, and lossless JSON round trips.

The models must contain no Torch tensors, NumPy arrays, Pillow images, bytes, open files, process handles, paths, or arbitrary Python objects.

### `Sam3SegmentRequest`

Implement fields equivalent to:

```python
class Sam3SegmentRequest(ModelBase):
    schema_version: int = SAM3_INFERENCE_SCHEMA_VERSION
    image_base64: str
    text_prompt: str
    max_long_edge: int | None = None
    score_threshold: float = 0.0
    mask_threshold: float = 0.5
    max_detections: int = 128
```

Validation:

- schema version is exact integer `1`; reject booleans, floats, strings, and other versions;
- `image_base64` is a non-empty string without whitespace-only content;
- decoded-size and image-pixel limits are enforced by the worker configuration, not by trusting encoded length alone;
- `text_prompt` is trimmed, non-empty, at most 512 Unicode code points, and contains no null, CR, LF, or disallowed control characters;
- `max_long_edge` is `None` or an exact integer from `64` through `8192`;
- thresholds are finite numeric values from `0.0` through `1.0`, never booleans;
- `max_detections` is an exact integer from `1` through `512`;
- request values do not mutate shared configuration.

The first service supports one text concept per request. Empty or negative-result prompts are valid requests and may produce zero detections.

### `Sam3SegmentResponse`

Implement fields equivalent to:

```python
class Sam3SegmentResponse(ModelBase):
    schema_version: int = SAM3_INFERENCE_SCHEMA_VERSION
    source_width: int
    source_height: int
    processed_width: int
    processed_height: int
    coordinate_space: Literal["processed"] = "processed"
    box_format: Literal["xyxy"] = "xyxy"
    mask_encoding: Literal["binary_rows"] = "binary_rows"
    labels: tuple[str, ...]
    confidences: tuple[float, ...]
    boxes: tuple[tuple[float, float, float, float], ...]
    masks: tuple[tuple[tuple[int, ...], ...], ...]
```

Contract:

- dimensions are exact positive integers;
- all result collections have equal detection counts;
- labels are non-empty trimmed strings and initially equal the request text prompt;
- confidences are finite values in `0.0..1.0`;
- boxes are finite processed-image pixel coordinates in `x_min, y_min, x_max, y_max` order;
- boxes are clipped to processed image bounds and satisfy `x_min <= x_max`, `y_min <= y_max`;
- every mask has exactly `processed_height` rows and every row has exactly `processed_width` exact integer values;
- mask values are only `0` or `1`, never booleans in serialized output;
- masks and boxes remain in processed-image coordinates;
- source and processed dimensions provide the scale needed by later clients/tools;
- zero detections are valid and return empty labels, confidences, boxes, and masks;
- no target coordinates, centroids, rendering colors, image paths, or backend tensors are returned.

The JSON-array representation is intentionally simple for the prototype. Do not introduce RLE, PNG mask blobs, NumPy binary payloads, or multipart responses in this session.

### `Sam3ErrorResponse`

Implement:

```python
class Sam3ErrorResponse(ModelBase):
    schema_version: int = SAM3_INFERENCE_SCHEMA_VERSION
    error: ArcadiaErrorInfo
```

Worker errors must be concise, stable, and safe for transport. Do not expose absolute paths, environment values, checkpoint contents, raw image data, stack traces, model internals, or arbitrary upstream exception messages.

## `Sam3BackendConfig`

Implement an immutable validated configuration object. A frozen dataclass or Pydantic model is acceptable.

Required fields and defaults equivalent to:

```python
class Sam3BackendConfig:
    bind_host: str = "127.0.0.1"
    advertise_host: str | None = None
    health_host: str | None = None
    startup_timeout_seconds: float = 900.0
    preflight_timeout_seconds: float = 30.0
    health_timeout_seconds: float = 2.0
    poll_interval_seconds: float = 0.5
    stop_timeout_seconds: float = 30.0
    kill_timeout_seconds: float = 10.0
    max_request_bytes: int = 32 * 1024 * 1024
    max_image_pixels: int = 50_000_000
    max_detections: int = 128
    bpe_path: Path | None = None
    runtime_dir: Path | None = None
    python_executable: str = sys.executable
```

Validation and behavior:

- hosts use existing ARCADIA host validation;
- all timeout/interval values are finite and greater than zero;
- byte/pixel/detection limits are exact positive integers, never booleans;
- `max_request_bytes` is at least 1 MiB and at most 256 MiB;
- `max_image_pixels` is at least 1,000,000 and at most 200,000,000;
- `max_detections` is from 1 through 512;
- `python_executable` is a non-empty path-like string without null/CR/LF characters;
- optional paths are detached `Path` values and are not created during construction;
- construction performs no optional imports, filesystem writes, network requests, process creation, port probes, sleeps, or hardware detection;
- `advertise_host` defaults to `bind_host` unless the bind host is wildcard;
- wildcard bind hosts (`0.0.0.0` or `::`) require an explicit non-wildcard `advertise_host`;
- `health_host` defaults to a locally reachable address: `127.0.0.1` for IPv4 wildcard binding, `::1` for IPv6 wildcard binding, otherwise `bind_host`;
- returned `ServiceEndpoint.host` uses `advertise_host`, never an unusable wildcard address.

## Backend construction and injection boundaries

Use a constructor equivalent to:

```python
class Sam3Backend:
    def __init__(
        self,
        *,
        config: Sam3BackendConfig | None = None,
        checkpoint_validator: object | None = None,
        process_launcher: object | None = None,
        health_probe: object | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None: ...
```

Concrete injection protocols may remain private. They must allow deterministic tests without monkeypatching global modules.

Construction requirements:

- validate and detach configuration;
- store lightweight real boundaries or factories without invoking them;
- perform no checkpoint read, optional import, model load, CUDA probe, process launch, HTTP request, sleep, filesystem write, or port probe;
- own no process-global service registry;
- own an instance-level lock and active-handle identity enforcing one live SAM service per backend object;
- be thread-safe when Session 06 calls the same backend object from different port-operation threads;
- do not serialize unrelated non-SAM backends;
- ensure a failed start releases the one-instance reservation.

A compute node must register one shared `Sam3Backend` object for `ServiceType.SAM3`. Creating multiple backend objects to bypass the one-model rule is unsupported and must not be done by ARCADIA node construction.

## Accepted service specifications

`start()` accepts only `SamServiceSpec` with `service_type == ServiceType.SAM3`.

Requirements:

- reject `LlamaServiceSpec` and arbitrary objects with `ServiceStartupError(code="sam3_spec_invalid")`;
- require `resolved_settings.backend == "sam3"`;
- endpoint port and type come only from the spec;
- never mutate the spec, checkpoint string, requested settings, resolved settings, or their mappings;
- refuse a second live instance owned by the same backend with `ServiceConflictError(code="sam3_instance_already_running")`;
- no checkpoint download, repository lookup, filename guessing, or automatic replacement occurs inside the backend.

## Checkpoint validation

The checkpoint is manually supplied through `SamServiceSpec.checkpoint_path`.

Before process launch:

1. Convert the supplied string to a detached local `Path` and expand `~`.
2. Resolve it to an absolute path for the private worker configuration.
3. Require an existing readable regular file with non-zero size.
4. Reject directories, sockets, devices, broken links, null/control characters, and unreadable files.
5. Do not require one filename or extension when the installed upstream runtime accepts the checkpoint.
6. Do not hash a multi-gigabyte checkpoint during ordinary startup.
7. Record only safe identity such as basename and size in diagnostics.
8. Never expose the absolute path in public status, events, diagnostics, returned logs, or HTTP responses.

Translate failures to stable `ServiceStartupError` codes such as:

```text
sam3_checkpoint_missing
sam3_checkpoint_invalid
sam3_checkpoint_unreadable
```

The backend must never modify, copy, delete, chmod, rename, or automatically evict the checkpoint.

## Runtime setting translation

Session 05 returns `ResolvedRuntimeSettings(backend="sam3", values=...)`. Translate it deterministically into a private worker configuration and child environment.

Supported top-level resolved values:

```text
device
device_index
autocast_dtype
enable_tf32
compile
model_options
```

Behavior:

- `device` must resolve to `cuda`; `cpu`, `metal`, and any other value fail with `sam3_device_unsupported`;
- `device_index` is an exact non-negative integer and is required for CUDA after Session 05 resolution;
- expose only that selected GPU to the child through `CUDA_VISIBLE_DEVICES=<device_index>`;
- inside the worker, the selected visible device is addressed as `cuda`/`cuda:0`;
- default `autocast_dtype` is `bfloat16`;
- accepted autocast values are `bfloat16`, `float16`, and `float32`;
- `float32` disables autocast;
- `enable_tf32` is an exact boolean defaulting to `true`;
- `compile` is an exact boolean defaulting to `false` and maps only to a proven official builder option;
- `model_options` is a detached JSON object with lowercase snake-case keys;
- reject unknown top-level values rather than silently ignoring them;
- reject generic `threads` because the initial production backend is CUDA-only;
- reject credentials, tokens, environment mappings, command/module overrides, arbitrary paths, and private-key-like names;
- reject non-finite values and unsupported nested objects.

Backend-owned builder values may not be overridden through `model_options`, including equivalents of:

```text
checkpoint_path
load_from_HF
device
eval_mode
bpe_path
compile
enable_segmentation
```

The worker must call the installed official image builder using the manually supplied checkpoint and behavior equivalent to:

```python
build_sam3_image_model(
    checkpoint_path=checkpoint_path,
    load_from_HF=False,
    device="cuda",
    eval_mode=True,
    enable_segmentation=True,
    ...validated_model_options,
)
```

Use the installed upstream signature rather than blindly forwarding unsupported values. `Sam3Processor` is then constructed once for the loaded image model.

If `bpe_path` is configured, validate it as a readable regular file and pass it explicitly. Otherwise use the installed official package default. Do not download tokenizer assets at runtime.

Do not add SAM 3.1-specific checkpoint conversion, key rewriting, internal branch assumptions, or compatibility shims. The installed package and checkpoint must already be mutually compatible.

## Configured-Python dependency and CUDA preflight

Before model loading, run a bounded subprocess using the configured `python_executable` and the same selected-GPU environment intended for the worker.

The preflight must:

- use an argument list and `shell=False`;
- produce a small machine-readable JSON result;
- verify Python is at least 3.12;
- import `arcadia.backends.sam3.worker`, FastAPI, Uvicorn, Pillow, NumPy, Torch, TorchVision, and `sam3`;
- verify `torch.cuda.is_available()`;
- verify at least one CUDA device is visible after applying `CUDA_VISIBLE_DEVICES`;
- report safe version strings where available;
- load no checkpoint and perform no network request;
- suppress or bound stdout/stderr;
- complete within `preflight_timeout_seconds`.

Translate missing/broken/import-timeout dependencies and incompatible Python to stable codes:

```text
sam3_dependency_missing
sam3_python_unsupported
sam3_cuda_unavailable
sam3_preflight_failed
```

Inability to execute the configured Python is `sam3_process_launch_failed`, not `sam3_dependency_missing`.

Do not claim that preflight proves the checkpoint will load or fit in VRAM.

## Private worker configuration

For each start attempt, create a private runtime directory containing a restrictive JSON configuration file and a retained binary log.

The private worker configuration may contain:

- bind host and requested port;
- absolute checkpoint and optional BPE paths;
- selected device behavior;
- validated builder options;
- request/image/detection limits;
- inference schema version;
- safe logging settings.

Requirements:

- create runtime directories only during `start()`;
- use per-attempt unique names;
- write configuration atomically where practical;
- use restrictive file permissions on POSIX;
- never place secrets in configuration;
- never log the complete configuration;
- remove the configuration after successful readiness;
- remove all attempt-owned files after failed startup;
- retain the log after successful stop while the opaque handle remains available for diagnostics;
- remove the runtime directory best-effort when the handle is finally released.

## Worker process and HTTP service

Launch with behavior equivalent to:

```text
<configured-python> -m arcadia.backends.sam3.worker --config <private-config-path>
```

Requirements:

- argument list only, `shell=False`;
- bind exactly to configured host and requested service port;
- one worker process only;
- no Uvicorn reload, multiprocessing workers, development watcher, or shell wrapper;
- stdout and stderr are combined into the backend-owned binary log;
- process containment matches Session 07 quality: POSIX process session/group and Windows owned-tree termination;
- the process loads one checkpoint and one `Sam3Processor` before advertising readiness;
- it performs no checkpoint download and no Hugging Face authentication;
- it exposes only the routes defined below;
- it does not expose interactive documentation in the default production configuration when disabling it is straightforward;
- request access logs may be disabled to avoid logging payload metadata;
- startup failure exits non-zero after logging a concise diagnostic.

### Routes

Implement these stable routes:

```text
GET  /health
GET  /v1/info
POST /v1/segment
```

`GET /health` returns HTTP 200 only after the checkpoint, model, and processor are ready. Its payload includes only:

```json
{
  "schema_version": 1,
  "backend_id": "sam3",
  "ready": true
}
```

`GET /v1/info` returns bounded safe information such as:

- schema version;
- backend ID;
- ready state;
- supported prompt type: `text`;
- supported media type: `image`;
- box format and mask encoding;
- CUDA device visibility index inside the worker;
- safe package versions;
- configured request/image/detection limits.

It must not expose absolute paths, full environment data, checkpoint contents, commands, or process handles.

`POST /v1/segment` accepts `Sam3SegmentRequest` JSON and returns `Sam3SegmentResponse` JSON.

### HTTP error behavior

Use stable JSON `Sam3ErrorResponse` payloads.

Suggested status mapping:

| Condition | HTTP status | Error code |
|---|---:|---|
| malformed or invalid request | 400/422 | `sam3_request_invalid` |
| encoded request exceeds configured limit | 413 | `sam3_request_too_large` |
| invalid base64 or unsupported image | 400 | `sam3_image_decode_failed` |
| decoded image exceeds pixel limit | 413 | `sam3_image_too_large` |
| requested detection limit exceeds service cap | 400 | `sam3_request_invalid` |
| model unavailable/not ready | 503 | `sam3_not_ready` |
| inference or output conversion failure | 500 | `sam3_inference_failed` or `sam3_output_invalid` |

Framework-default HTML errors must not cross the service boundary for these routes.

## Image preprocessing

For each segmentation request:

1. Strictly decode base64 without accepting arbitrary data-URL prefixes.
2. Enforce decoded-byte limit before image parsing where possible.
3. Open from memory with Pillow and force complete image decoding.
4. Reject unsupported, corrupt, decompression-bomb, zero-sized, or over-limit images.
5. Convert to RGB.
6. Record source width and height.
7. If `max_long_edge` is present and the source exceeds it, downscale while preserving aspect ratio using a deterministic high-quality Pillow filter.
8. Never upscale an image solely to reach `max_long_edge`.
9. Record processed width and height.
10. Pass only the processed in-memory Pillow image to the model adapter.

Do not read an image path supplied by the request. Do not write request images to disk.

## Model runtime and serialized inference

Define a narrow internal runtime/adapter boundary so conversion and HTTP behavior can be tested with a fake model and no heavy imports.

The real runtime must:

- lazily import Torch, Pillow-dependent upstream pieces, and SAM 3 only inside the worker;
- load one model and construct one processor at startup;
- set evaluation mode;
- perform requests under `torch.inference_mode()`;
- use the configured CUDA autocast behavior;
- optionally enable TF32 only through explicit validated configuration;
- not mutate global Torch settings outside the worker process;
- hold a worker-owned lock across `set_image`, prompt application, and output extraction;
- serialize all model inference even when HTTP requests arrive concurrently;
- release per-request tensors/references after conversion;
- not call `torch.cuda.empty_cache()` after every request unless a future measured need justifies it;
- not hide CUDA OOM, model errors, or output mismatch behind empty results.

Initial prompt flow is equivalent to:

```python
state = processor.set_image(image)
output = processor.set_text_prompt(state=state, prompt=text_prompt)
```

The adapter then extracts `masks`, `boxes`, and `scores` from the official output.

### Output normalization

Normalize output deterministically:

1. Validate that masks, boxes, and scores exist and have the same leading detection count.
2. Move tensors to CPU and detach before Python conversion.
3. Accept mask shape `N x H x W` or `N x 1 x H x W`; reject other shapes.
4. Convert masks to processed-image dimensions when the official output uses another deterministic resolution.
5. Convert non-boolean masks using `mask_threshold`.
6. Convert each mask to rows of exact integer `0`/`1` values.
7. Normalize boxes to finite processed-pixel `xyxy` coordinates.
8. Clamp boxes to image bounds.
9. Convert scores to finite floats in `0.0..1.0`.
10. Filter detections below `score_threshold`.
11. Preserve upstream order among retained detections.
12. Truncate to the lower of request `max_detections` and service maximum.
13. Set every label to the normalized request text prompt.
14. Return empty arrays normally when no detections remain.

Do not invent confidence values, labels, masks, or boxes when upstream output is malformed.

## Backend startup

`Sam3Backend.start()` must:

1. Validate spec and resolved backend identity.
2. Reserve the one-model backend slot under its instance lock.
3. Validate checkpoint and optional BPE path.
4. Translate settings without mutating inputs.
5. Report `RESOLVING` while validating files/settings/environment.
6. Run configured-Python dependency/CUDA preflight.
7. Create the private runtime directory, configuration, and log.
8. Report `STARTING` before process launch.
9. Launch the contained worker process.
10. Poll `GET /health` until valid readiness, process exit, or startup timeout.
11. Verify response schema version and backend ID.
12. Optionally verify `GET /v1/info` contains the expected protocol values.
13. Remove the private config after readiness.
14. Return `BackendInstance` with:

   - advertised `ServiceEndpoint`;
   - the unchanged/equivalent resolved settings;
   - an opaque private handle owning process, containment, log, runtime directory, checkpoint identity, and backend identity.

The backend must not return until the model is loaded and `/health` is valid.

No `DOWNLOADING` progress state is expected because checkpoints are manual. Do not report fake download progress.

### Startup polling

- use configured monotonic timing for timeout decisions;
- use injected sleeper in tests;
- each probe is individually bounded;
- connection refusal during startup is expected and retryable until timeout;
- malformed ready responses are not success;
- process exit before readiness fails immediately;
- startup timeout terminates and reaps the entire owned process tree;
- failed attempts remove config/log/runtime files and release the one-model reservation;
- never include arbitrary worker log content in public error details.

## Health checks

`check_health(instance)` must:

- validate the opaque handle belongs to this backend;
- fail if the process exited;
- issue bounded `GET /health`;
- require HTTP 200, schema version `1`, backend ID `sam3`, and `ready == true`;
- translate failures to `ServiceHealthError` with stable safe codes;
- perform no inference and no model reload;
- preserve interrupts and interpreter-exit exceptions.

Suggested codes:

```text
sam3_handle_invalid
sam3_process_exited
sam3_health_failed
```

## Stop and cleanup

`stop(instance, progress)` must:

- validate ownership;
- report only `ServiceState.STOPPING`;
- be idempotent after the owned process has exited;
- terminate the complete owned process tree gracefully, then forcefully after timeout;
- reap the child;
- release the one-model reservation only after the process is known exited;
- remove private config and transient files best-effort;
- retain the bounded log/runtime identity while the handle remains available;
- never terminate an unowned PID or listener;
- raise `ServiceError(code="sam3_stop_failed")` on incomplete owned-tree cleanup.

POSIX behavior must use a new process session/group and group signaling. Windows behavior must use platform-appropriate process-group/tree containment equivalent in safety to Session 07. Do not weaken Session 06 transactional or shutdown-retry guarantees.

## Diagnostics and logs

`diagnostics(instance)` returns a bounded JSON-safe mapping.

Allowed fields include:

```text
backend_id
pid
running
return_code
checkpoint_name
checkpoint_size_bytes
device
device_index
autocast_dtype
schema_version
python_version
torch_version
sam3_version
started_at
log_size_bytes
runtime_file_count
```

Requirements:

- no absolute paths;
- no complete command or environment;
- no checkpoint data or hash requirement;
- no opaque handle or containment object;
- callable while running and after stop;
- bounded file inspection only;
- arbitrary failures translated safely by the manager boundary.

`read_logs(instance, tail_lines)` must:

- validate exact positive bounds supplied by Session 06;
- read only the final requested logical lines;
- replace decoding errors;
- bound bytes read even for very long lines;
- redact checkpoint/BPE/runtime absolute paths and configured Python path;
- avoid returning environment dumps, request image data, base64 payloads, or tracebacks containing sensitive paths;
- remain usable after stop while the handle is retained.

## Stable backend error codes

Use existing typed service exceptions with stable codes including:

```text
sam3_spec_invalid
sam3_backend_mismatch
sam3_checkpoint_missing
sam3_checkpoint_invalid
sam3_checkpoint_unreadable
sam3_bpe_invalid
sam3_settings_invalid
sam3_setting_unsupported
sam3_device_unsupported
sam3_python_unsupported
sam3_dependency_missing
sam3_cuda_unavailable
sam3_preflight_failed
sam3_instance_already_running
sam3_process_launch_failed
sam3_process_exited
sam3_startup_timeout
sam3_health_failed
sam3_handle_invalid
sam3_stop_failed
sam3_diagnostics_failed
sam3_logs_failed
```

Rules:

- preserve backend-raised `ServiceError` subclasses;
- translate arbitrary `Exception` at public backend boundaries while retaining it as `cause`;
- do not catch `KeyboardInterrupt`, `SystemExit`, or unrelated `BaseException` values;
- details contain only safe JSON values such as service port/type, exception type, checkpoint basename/size, selected device index, PID, return code, and setting name;
- never place raw command output, logs, paths, image contents, tensor values, environment values, or traceback text in error details.

Worker-only inference error codes remain in HTTP error responses and do not become lifecycle states unless health/process failure also occurs.

## State and concurrency

The backend owns:

- immutable configuration;
- lightweight injected boundaries;
- an instance lock and at most one active/retained process handle;
- per-handle process containment, log, runtime directory, endpoint, and safe identity metadata.

The worker owns:

- one loaded model;
- one processor;
- one inference lock;
- immutable service limits/settings;
- no persistent request history.

Concurrency requirements:

- backend public methods are thread-safe;
- two concurrent `start()` calls on one backend cannot load two models;
- a second start fails clearly while one live instance is reserved;
- stop and health operate only on the creating handle;
- worker HTTP requests may arrive concurrently but model execution is strictly serialized;
- pure health/info requests need not acquire the model-inference lock;
- model initialization occurs once;
- no background model-refresh or crash-monitor thread is introduced;
- no global mutable model singleton exists in the orchestrator process.

## Explicit non-goals

Session 08 does not provide:

- CPU or Metal SAM 3 execution;
- SAM 1, SAM 2, or Ultralytics compatibility;
- video tracking or multi-frame state;
- visual point/box/mask/exemplar prompts;
- batch inference across multiple images in one request;
- streaming or asynchronous inference APIs;
- shared memory or binary mask transport;
- a reusable orchestrator-side SAM client;
- retries, service restart policy, or analysis-stage recovery;
- remote instruction APIs;
- Priority Map integration;
- checkpoint/model acquisition or login;
- model version migration or fine-tuned checkpoint repair;
- automatic selection among SAM 3 and SAM 3.1 checkpoints;
- performance tuning beyond explicit safe runtime settings.

## Tests required

All standard tests must use fakes, temporary files, local loopback processes, and synthetic images. They must not import or require real Torch, TorchVision, SAM 3, CUDA, a real checkpoint, Hugging Face access, or external network access.

### Unit tests: protocol

Cover:

- schema-version exactness;
- request trimming, control rejection, thresholds, dimensions, and exact integer rules;
- response count coherence;
- confidence/box finiteness and bounds;
- binary mask values and exact row dimensions;
- zero-detection response;
- error-response round trip;
- defensive copying and unknown-field rejection;
- JSON round trips without heavy imports.

### Unit tests: configuration and settings

Cover:

- default and explicit hosts;
- wildcard advertise/health behavior including IPv6;
- timeout/limit/path/python validation;
- constructor side-effect boundary;
- CUDA-only device translation;
- CUDA index environment selection;
- autocast dtype, TF32, compile, and model options;
- reserved/unknown/credential-like settings;
- non-finite and mutable nested-value rejection;
- input non-mutation.

### Unit tests: checkpoint and preflight

Cover:

- valid regular file;
- missing, empty, directory, broken-link, unreadable, and unusual-extension cases;
- safe basename/size identity;
- no checkpoint mutation;
- configured Python command shape and `shell=False`;
- Python-version, missing-dependency, CUDA-unavailable, malformed-result, timeout, and launch-failure translation;
- selected-GPU environment;
- no checkpoint load/network call during preflight;
- no raw output/path leakage.

### Unit tests: model adapter and worker logic

Using fake tensor/array adapters or small NumPy substitutes only when the optional dependency is explicitly available in that test environment, cover:

- strict base64 decoding;
- decoded-byte and pixel limits;
- corrupt/unsupported image handling;
- RGB conversion;
- deterministic no-upscale resize and dimensions;
- one text prompt;
- serialized fake model calls under concurrent requests;
- mask shape normalization;
- thresholding and integer conversion;
- score filtering and stable truncation;
- box clipping and validation;
- zero detections;
- mismatched/malformed model outputs;
- safe HTTP-style error mapping;
- no image/request persistence.

Keep core normalization functions independent of FastAPI route objects so they remain testable without optional server imports.

### Unit tests: process/backend

Cover:

- public import/construction without heavy imports;
- spec/backend validation;
- one-instance reservation and concurrent-start rejection;
- reservation release after failed start and successful stop;
- progress order (`RESOLVING`, `STARTING`, no fake `DOWNLOADING`);
- checkpoint/preflight/config/launch/health sequence;
- process exit and startup timeout cleanup;
- config removal after readiness;
- invalid handle and cross-backend handle rejection;
- successful and failed health;
- idempotent stop;
- POSIX and Windows process-tree behavior through fakes;
- safe diagnostics and bounded/redacted logs;
- arbitrary-exception translation and `BaseException` propagation;
- no mutation of public inputs.

### Contract tests

`tests/contract/test_sam3_backend_contract.py` must run the reusable Session 06 backend contract against `Sam3Backend` with injected fake checkpoint/process/health boundaries.

Verify:

- stable backend ID;
- accepted `SamServiceSpec`;
- endpoint and resolved-backend agreement;
- health and idempotent stop;
- allowed progress states;
- bounded JSON diagnostics/logs;
- no handle/path leakage;
- manager ensure, health, diagnostics/logs, stop, and shutdown;
- one SAM backend object cannot host two live ports.

`tests/contract/test_sam3_inference_protocol.py` must freeze the request/response/error JSON contract for Session 12.

### Integration tests

Use a local standard-library fake worker subprocess or an injected lightweight service process. Do not launch Torch/SAM 3.

Cover:

- real `ServiceManager` plus `Sam3Backend` lifecycle;
- local readiness polling;
- protocol-valid `/health` and `/v1/info` responses;
- a synthetic `/v1/segment` request/response through the local fake worker where practical;
- process exit before ready;
- malformed health response;
- startup timeout;
- diagnostics/logs after stop;
- process-tree cleanup;
- JSON round trips;
- no external network.

When FastAPI/Uvicorn are not installed by the normal dev environment, worker-route integration may use injected application/runtime boundaries or be marked as an optional extra smoke. Core protocol and worker logic must still have non-skipped tests.

### Package tests

Extend `tests/test_package.py` to verify:

- `import arcadia` does not import `arcadia.backends` or `arcadia.backends.sam3`;
- `import arcadia.backends` imports no concrete backend;
- `import arcadia.backends.sam3` imports no FastAPI, Uvicorn, Pillow, NumPy, Torch, TorchVision, or upstream SAM 3 module;
- import and construction start no process, thread, CUDA check, filesystem write, HTTP probe, or checkpoint validation;
- the built base wheel contains protocol/config/backend modules;
- a missing real worker dependency fails through a typed startup error rather than raw `ImportError`.

## Validation

Record exact commands and results. Never claim an unexecuted command passed.

### Baseline

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src/arcadia
pytest
```

### Focused validation

```bash
ruff format --check src/arcadia/backends tests/unit/backends/sam3 tests/contract/test_sam3_backend_contract.py tests/contract/test_sam3_inference_protocol.py tests/integration/test_sam3_backend_integration.py tests/integration/test_sam3_worker_integration.py tests/test_package.py
ruff check src/arcadia/backends tests/unit/backends/sam3 tests/contract/test_sam3_backend_contract.py tests/contract/test_sam3_inference_protocol.py tests/integration/test_sam3_backend_integration.py tests/integration/test_sam3_worker_integration.py tests/test_package.py
mypy src/arcadia
pytest tests/unit/backends/sam3 tests/contract/test_sam3_backend_contract.py tests/contract/test_sam3_inference_protocol.py tests/integration/test_sam3_backend_integration.py tests/integration/test_sam3_worker_integration.py tests/test_package.py
```

If one listed integration file is intentionally unnecessary, document why and remove it from both the implementation and validation command rather than leaving a nonexistent path.

### Full validation

```bash
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

### Clean-wheel smoke test

In a new temporary virtual environment with no editable source access:

1. Install the built base wheel without `[sam]`.
2. Import `arcadia.backends.sam3` and construct protocol/config/backend objects.
3. Confirm FastAPI, Uvicorn, Pillow, NumPy, Torch, TorchVision, and upstream SAM 3 are absent from `sys.modules`.
4. Confirm a real default start boundary reports a typed missing/incompatible worker dependency without checkpoint download or raw import failure.
5. Construct the backend with fake checkpoint/process/health boundaries.
6. Use it through a real `ServiceManager` to ensure, check health, inspect diagnostics/logs, stop, and shut down a fake service.
7. Round-trip request, zero-detection response, error response, service status, diagnostics, and logs.
8. Confirm no opaque handle, absolute checkpoint path, runtime path, or Python path leaks through serialized public values.

### Optional worker-extra smoke

In a separate temporary Python 3.12 environment, install the built wheel with `[sam]` but without Torch or upstream SAM 3.

Verify:

- the worker module reaches its explicit dependency preflight/entry boundary;
- server dependencies import successfully;
- missing Torch/SAM 3 is classified safely;
- no model or network action occurs.

This smoke is useful but not required when the environment cannot install the worker extra.

### Optional manual CUDA smoke

Only on a deliberately prepared CUDA machine with a compatible Python 3.12+ environment, official SAM 3 package, compatible CUDA-enabled Torch, and manually downloaded known-compatible checkpoint:

1. Install the current ARCADIA wheel with `[sam]` into that same worker environment.
2. Construct synthetic CUDA `HardwareCapabilities` and resolve a `SamServiceSpec`.
3. Start the service through `ServiceManager`.
4. Verify `/health` and `/v1/info`.
5. Send one small image and text concept to `/v1/segment`.
6. Verify coherent source/processed dimensions and equal-length mask/label/confidence/box arrays.
7. Confirm two concurrent requests execute model inference serially where observable.
8. Inspect safe diagnostics and bounded logs.
9. Stop and verify the complete worker process tree exited.
10. Record the exact upstream SAM 3 revision, checkpoint filename, Python, Torch, CUDA, GPU, and outcome.

Prefer the known SAM 3.0 `sam3.pt` path for the first smoke unless SAM 3.1 compatibility has been independently proven. Do not download a multi-gigabyte checkpoint merely to satisfy ordinary session completion.

## Definition of done

- [ ] Work began from current clean `headless-core`.
- [ ] The canonical session file was committed and pushed with status `in-progress`.
- [ ] Required public API exists with backend ID `sam3` and schema version `1`.
- [ ] Base imports remain lightweight and optional dependencies are lazy.
- [ ] Manual checkpoint validation performs no download or mutation.
- [ ] Configured-Python preflight verifies Python, dependencies, and selected CUDA visibility.
- [ ] CPU and Metal requests fail explicitly without fallback.
- [ ] Worker loads one image model and one processor before readiness.
- [ ] One live model per backend/node and serialized inference are enforced.
- [ ] `/health`, `/v1/info`, and `/v1/segment` contracts are stable and tested.
- [ ] Responses contain masks, labels, confidences, boxes, and source/processed dimensions as JSON-compatible arrays.
- [ ] Zero detections are valid; malformed output is never converted into fake success.
- [ ] Process launch uses an argument list, `shell=False`, private config, and owned log.
- [ ] POSIX and Windows process-tree containment are implemented and simulated in tests.
- [ ] Failed starts clean every attempt-owned process/file and release the one-model reservation.
- [ ] Health, idempotent stop, diagnostics, and bounded/redacted logs satisfy Session 06.
- [ ] No checkpoint is automatically downloaded, copied, modified, or deleted.
- [ ] No direct client, instruction transport, analysis, tool, Priority Map, CLI, or UI code was added.
- [ ] Unit, contract, integration, package, full-suite, build, and clean-wheel validation pass or are recorded honestly.
- [ ] Completion record and session index are accurate.
- [ ] Final commits were pushed normally to `origin/headless-core`.
- [ ] Working tree is clean and local `HEAD` equals `origin/headless-core`.

## Stop conditions

Stop and record `partial` or `blocked` rather than expanding scope if implementation requires:

- changing Session 01, 03, 05, 06, or 07 public contracts;
- adding Torch, CUDA wheels, or official SAM 3 to base dependencies;
- claiming CPU or Metal support without a proven upstream path;
- moving generic lifecycle policy into the backend;
- adopting or killing unmanaged processes;
- weakening process-tree cleanup, one-model ownership, serialized inference, or transactional-start requirements;
- downloading/checking in a checkpoint or using external network in standard tests;
- adding unofficial checkpoint conversion or SAM 3.1 key rewriting;
- storing credentials in settings, files, logs, manifests, or responses;
- adding retries, auto-restart, remote instruction transport, Priority Map, or analysis behavior;
- force-pushing or overwriting remote `headless-core` history.

An honest pushed partial implementation is preferable to an undocumented contract change or local-only work.

---

# Completion record

The implementation agent fills this section before stopping and changes the top status to `completed`, `partial`, or `blocked`.

## Outcome

Describe what was implemented and the final status.

## Git delivery

Record:

- starting `origin/headless-core` commit;
- session-start commit and push;
- implementation/completion commits and pushes;
- any rebase and rerun validation;
- final local `HEAD` and `origin/headless-core` equality;
- confirmation that no force push was used.

## Files changed

List source, tests, dependency metadata, and documentation.

## Delivered public API

Record the actual exports and any differences from the planned contract.

## State and side effects

Document:

- backend-owned process/runtime/checkpoint identity state;
- worker-owned model/processor/inference lock;
- filesystem, subprocess, HTTP, CUDA, and model-loading behavior;
- one-model and cleanup behavior.

## Inference protocol

Record final route paths, schema versions, request/response fields, mask/box coordinate rules, limits, and zero-detection behavior.

## Settings and platform support

Record supported settings, CUDA behavior, selected-GPU mapping, installed-runtime expectations, and explicit unsupported devices/checkpoints.

## Errors

List stable backend and worker error codes actually delivered, including any deviations.

## Tests and validation

Record every exact command run and result. Distinguish:

- focused tests;
- full suite;
- build;
- clean-wheel smoke;
- worker-extra smoke;
- optional real CUDA/checkpoint smoke.

Never claim an unexecuted command passed.

## Decisions and deviations

Record contract differences, upstream API adaptations, dependency changes, or process-containment decisions. Add an ADR only for a lasting project-wide architectural change.

## Known limitations

Include unsupported devices, prompts, media, checkpoint families, transport encodings, platform smoke gaps, and upstream compatibility risks.

## Assumptions and risks

Later sessions must not mistake hardware visibility, dependency preflight, or fake-worker tests for proof that an arbitrary checkpoint fits or works.

## Next-session prerequisites

State the exact stable backend, service routes, protocol models, lifecycle guarantees, and limitations available to Sessions 09–12.
