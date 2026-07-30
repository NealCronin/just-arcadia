# Session 07: llama.cpp Backend

- Status: completed
- Branch: `headless-core` — direct implementation and push required by the operator
- Owner: local agent session
- Module: `arcadia.backends.llama_cpp`
- Canonical path: `docs/sessions/07-llama-cpp-backend.md`

## Objective

Implement the first real ARCADIA service backend: a synchronous llama.cpp backend for `llm` and `visual_llm` service specifications.

Session 07 must deliver:

- a `ServiceBackend` implementation with stable backend ID `llama_cpp`;
- exact Hugging Face model and projector file resolution through the local Hub cache;
- launch of the `llama_cpp.server` OpenAI-compatible server as a managed child process;
- deterministic translation of resolved ARCADIA settings into a llama-cpp-python server configuration;
- bounded startup polling and `/v1/models` health checks;
- complete owned-process-tree termination on macOS/Linux and Windows;
- captured logs and safe bounded diagnostics while running and after stop;
- transactional cleanup when startup fails;
- lazy optional dependencies so the base package remains lightweight;
- tests that require no model download, GPU, external network, or installed llama.cpp runtime;
- final commits pushed directly to `origin/headless-core`.

This session implements backend behavior only. Generic slot ownership, replacement, operation history, lifecycle events, and shutdown policy remain owned by Session 06 `ServiceManager`.

## Authoritative context

Read before editing:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/README.md
docs/sessions/05-hardware-detection-and-runtime-resolution.md
docs/sessions/06-service-manager.md
src/arcadia/models/common.py
src/arcadia/models/services.py
src/arcadia/models/errors.py
src/arcadia/hardware/resolution.py
src/arcadia/services/backend.py
src/arcadia/services/models.py
src/arcadia/services/manager.py
tests/contract/test_service_backend_contract.py
tests/test_package.py
pyproject.toml
```

Inspect the legacy `NealCronin/Almost-ARCADIA` repository read-only for cache, launch, health, log, and cleanup characterization where useful. Do not import the legacy package or reproduce its global/UI state.

Relevant project rules:

- Service identity is node session plus inference port.
- `ServiceManager` owns lifecycle policy and opaque backend instances.
- The backend that creates an instance exclusively owns its process, files, health checks, logs, and cleanup.
- `ServiceBackend.start()` is transactional: it must release every resource created during a failed attempt.
- Process backends must terminate their complete owned process tree.
- Exact Hugging Face repository, filename, and revision identify each model file.
- Split-GGUF-specific application logic and gated-repository workflows are outside the first prototype.
- Inference goes directly to the returned service endpoint; it is not proxied through the future instruction server.
- Requested settings and resolved settings are immutable inputs and must not be mutated.
- No production failure may silently substitute a mock model or fake endpoint.
- Root and base-package imports must remain light.

Current upstream llama-cpp-python behavior to preserve conceptually:

- the OpenAI-compatible server is launched with `python -m llama_cpp.server`;
- server configuration may be supplied through a JSON config file;
- the server exposes OpenAI-compatible endpoints including `/v1/models`;
- model and projector paths are local paths supplied to the server;
- hardware acceleration depends on how llama-cpp-python was installed, not merely on detected hardware.

Do not bind the implementation to undocumented internal llama-cpp-python objects when a subprocess/config-file boundary is sufficient.

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
2. Copy this file to `docs/sessions/07-llama-cpp-backend.md`.
3. Change its status to `in-progress`.
4. Commit and push the session start:

   ```bash
   git add docs/sessions/07-llama-cpp-backend.md
   git commit -m "docs: start llama-cpp backend session"
   git push origin headless-core
   ```

5. Implement only this work order.
6. Run all required validation.
7. Fill in the completion record and set status to `completed`, `partial`, or `blocked`.
8. Mark Session 07 in `docs/sessions/README.md` only when the final status is `completed`.
9. Commit the implementation and documentation. Use a clear final commit message such as:

   ```bash
   git commit -m "feat: add llama-cpp service backend"
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
src/arcadia/backends/llama_cpp/**
tests/unit/backends/llama_cpp/**
tests/contract/test_llama_cpp_backend_contract.py
tests/integration/test_llama_cpp_backend_integration.py
tests/test_package.py
pyproject.toml
docs/sessions/07-llama-cpp-backend.md
docs/sessions/README.md
```

A small reusable test helper under `tests/helpers/` is acceptable when it is used by more than one Session 07 test module.

### Prohibited changes

Do not implement or modify:

- Session 01 service specifications, statuses, endpoint models, or shared error hierarchy;
- Session 03 event models or sinks;
- Session 05 hardware detection or runtime resolution;
- Session 06 manager lifecycle, backend protocol, slot records, concurrency, operations, or events;
- SAM3, instruction protocol/server/client, direct inference clients, Tool SDK, analysis engine, Priority Map, CLI, Django, or UI;
- automatic model-fit estimation, context tuning, batching tuning, KV-cache sizing, or GPU-layer estimation;
- split-GGUF sibling discovery or multipart download orchestration;
- automatic cache deletion or eviction;
- authentication/TLS/public-internet hardening;
- background service polling, automatic restart, or crash monitoring;
- in-process model loading through `llama_cpp.Llama`;
- shell command construction or `shell=True`;
- arbitrary user-provided child environment variables or secrets in runtime settings.

Do not silently change an earlier public contract. Stop and record a blocker if the existing `ServiceBackend` contract cannot support the implementation.

## Package structure

Create:

```text
src/arcadia/backends/
├── __init__.py
└── llama_cpp/
    ├── __init__.py
    ├── backend.py
    ├── config.py
    ├── files.py
    ├── health.py
    ├── process.py
    └── settings.py
```

A slightly smaller internal layout is acceptable, but keep file resolution, settings translation, process ownership, and backend orchestration separable and independently testable.

`arcadia.backends.__init__` must not eagerly import backend implementations. Do not re-export this package from `arcadia.__init__` or `arcadia.services`.

## Optional dependencies

Update the existing `llama` optional dependency group. The base dependency list must remain unchanged.

Use compatible bounded requirements equivalent to:

```toml
llama = [
    "huggingface-hub>=0.34,<2",
    "llama-cpp-python[server]>=0.3,<0.4",
]
```

Adjust lower bounds only when a concrete API requirement justifies it. Do not pin to one platform wheel or CUDA build.

Installation of GPU-enabled llama-cpp-python remains an operator/platform concern. ARCADIA must not claim that CUDA or Metal is usable merely because hardware detection found a device.

All imports of `huggingface_hub`, `llama_cpp`, FastAPI, Uvicorn, or server dependencies must be lazy. Importing `arcadia.backends.llama_cpp`, constructing configuration, and constructing a backend with injected fakes must work in a base installation.

## Required public API

`from arcadia.backends.llama_cpp import ...` must expose:

```text
LLAMA_CPP_BACKEND_ID
LlamaCppBackendConfig
LlamaCppBackend
```

Use:

```python
LLAMA_CPP_BACKEND_ID = "llama_cpp"
```

`LlamaCppBackend` must satisfy `isinstance(backend, ServiceBackend)` through the runtime-checkable Session 06 protocol.

Do not add a new public exception hierarchy. Use the existing `ServiceError`, `ServiceStartupError`, and `ServiceHealthError` classes with stable Session 07 codes.

## `LlamaCppBackendConfig`

Implement an immutable, validated configuration object. A frozen dataclass or Pydantic model is acceptable.

Required fields and defaults equivalent to:

```python
class LlamaCppBackendConfig:
    bind_host: str = "127.0.0.1"
    advertise_host: str | None = None
    health_host: str | None = None
    startup_timeout_seconds: float = 300.0
    health_timeout_seconds: float = 2.0
    poll_interval_seconds: float = 0.25
    stop_timeout_seconds: float = 10.0
    kill_timeout_seconds: float = 5.0
    cache_dir: Path | None = None
    runtime_dir: Path | None = None
    python_executable: str = sys.executable
```

Validation and behavior:

- host values use existing ARCADIA host validation;
- all timeout/interval values are finite and greater than zero;
- `python_executable` is a non-empty path-like string without null/CR/LF characters;
- optional paths are detached `Path` values and are not created during construction;
- construction performs no imports of optional dependencies, filesystem writes, network requests, process creation, port probes, or hardware detection;
- `advertise_host` defaults to `bind_host` unless the bind host is wildcard;
- wildcard bind hosts (`0.0.0.0` or `::`) require an explicit non-wildcard `advertise_host`;
- `health_host` defaults to a locally reachable address: `127.0.0.1` for IPv4 wildcard binding, `::1` for IPv6 wildcard binding, otherwise `bind_host`;
- the returned `ServiceEndpoint.host` uses `advertise_host`, not an unusable wildcard address.

## Backend construction and injection boundaries

Use a constructor equivalent to:

```python
class LlamaCppBackend:
    def __init__(
        self,
        *,
        config: LlamaCppBackendConfig | None = None,
        file_resolver: object | None = None,
        process_launcher: object | None = None,
        health_probe: object | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None: ...
```

The concrete injection protocols may remain private. They must make unit tests deterministic without monkeypatching global modules.

Construction requirements:

- validate and detach configuration;
- default to real implementations only by storing lightweight factories or objects;
- perform no download, optional import, process launch, HTTP request, sleep, filesystem write, or port probe;
- own no process-global mutable registry;
- be safe for different instances/ports to be used concurrently by Session 06;
- serialize mutable state only within each opaque backend handle, not across unrelated ports.

## Accepted service specifications

`start()` accepts only `LlamaServiceSpec` values whose service type is `llm` or `visual_llm`.

Requirements:

- reject `SamServiceSpec` and arbitrary objects with `ServiceStartupError(code="llama_cpp_spec_invalid")`;
- require `resolved_settings.backend == "llama_cpp"`;
- require endpoint port and type to come from the spec;
- rely on Session 01 for projector-required/projector-forbidden validation;
- never mutate the spec, nested Hugging Face file specs, requested settings, resolved settings, or their mappings;
- reject model/projector filenames containing glob metacharacters such as `*`, `?`, `[` or `]`;
- reject recognized multipart names such as `*-00001-of-00005.gguf` with `llama_cpp_split_gguf_unsupported` rather than downloading only one part;
- never search a repository for a “best” quantization or filename.

## Hugging Face file resolution

Implement a real lazy resolver using `huggingface_hub.hf_hub_download`.

For each `HuggingFaceFileSpec`:

1. Report `RESOLVING` before cache lookup.
2. Attempt an exact cache-only lookup with the supplied `repo_id`, `filename`, `revision`, and configured cache directory.
3. On a cache miss, report `DOWNLOADING` with `progress=None` and a concise message that identifies only whether the model or projector is downloading.
4. Call `hf_hub_download` for that exact file.
5. Validate that the returned path is an existing regular file.
6. Return the local path without modifying the cached file.

Rules:

- use the library cache; do not duplicate files into an ARCADIA model directory;
- pass `revision` exactly;
- do not use `snapshot_download`, wildcard matching, repository listing, or sibling discovery;
- do not accept authentication tokens in `RequestedRuntimeSettings`;
- inherited Hugging Face environment/login behavior may be used by the library, but gated repositories remain unsupported and untested for the prototype;
- translate missing optional dependencies to `ServiceStartupError(code="llama_cpp_dependency_missing")`;
- translate cache/download/path failures to `ServiceStartupError(code="llama_cpp_model_resolve_failed")`;
- retain the original exception as `cause`;
- safe error details may contain repo ID, exact filename, revision, file role, and exception type;
- never include tokens, headers, environment values, response bodies, complete cache paths, or tracebacks in public details.

A visual service resolves the model first and then the projector. If projector resolution fails, no process may be launched.

## Runtime settings translation

Translate `ResolvedRuntimeSettings.values` into a temporary llama-cpp-python JSON server config. Do not pass user settings through a shell.

### Backend-owned values

Consume these ARCADIA values rather than forwarding them verbatim:

```text
device
device_index
threads
server_options
model_options
```

All other top-level keys are treated as llama model options for power-user compatibility.

### Option containers

- `server_options`, when present, must be a JSON object whose keys are lowercase snake-case setting names.
- `model_options`, when present, follows the same rule.
- Merge remaining top-level advanced values into model options.
- Reject duplicate keys across flat advanced values and `model_options`.
- Defensively copy all nested JSON values.
- Reject non-finite floats even if an earlier boundary was bypassed.

### Reserved server options

Reject attempts to override backend ownership, including:

```text
host
port
config_file
models
```

Also reject credential/private-key options in runtime settings. Credentials belong in the process environment or future node configuration, not run manifests.

### Reserved model options

Reject attempts to override model identity or backend-owned local files, including:

```text
model
clip_model_path
hf_model_repo_id
hf_model_repo_revision
```

Reject ambiguous duplicates such as both ARCADIA `threads` and model option `n_threads`.

### Device translation

- `device == "cpu"`: default `n_gpu_layers` to `0`; reject an explicit nonzero `n_gpu_layers` as contradictory.
- `device == "cuda"`: default `n_gpu_layers` to `-1`; require the resolved non-negative `device_index`; launch the child with only that selected physical GPU in `CUDA_VISIBLE_DEVICES`; reject user attempts to provide that environment variable through settings.
- `device == "metal"`: default `n_gpu_layers` to `-1`; do not invent a device index.
- reject any other device with `llama_cpp_settings_invalid`.
- an explicit compatible `n_gpu_layers` may override the default and may request partial offload.
- when `threads` is present, map it to `n_threads`.

ARCADIA does not verify the installed llama-cpp-python build before launch. A CPU-only wheel requested with CUDA/Metal will fail during server startup and must surface as a typed startup failure with logs retained only through the internal cause/debug path.

### Generated server configuration

Generate a JSON file equivalent to:

```json
{
  "host": "<bind_host>",
  "port": 19000,
  "models": [
    {
      "model": "<resolved local model path>",
      "clip_model_path": "<resolved local projector path when visual>",
      "n_threads": 8,
      "n_gpu_layers": -1
    }
  ]
}
```

Merge validated server and model options without allowing them to overwrite backend-owned values.

Use restrictive file permissions where supported. The generated config is runtime state, not a reproducibility artifact. It may contain operator-selected non-secret settings but must never contain credentials.

## Process launch and containment

Launch exactly one child command without a shell:

```text
<python_executable> -m llama_cpp.server --config_file <temporary-config-path>
```

Requirements:

- use `subprocess.Popen` with an argument list and `shell=False`;
- use the configured working/runtime directory only when needed;
- inherit the normal process environment, changing only backend-owned values such as `CUDA_VISIBLE_DEVICES`;
- do not log or expose the complete environment;
- redirect combined stdout/stderr to an instance-owned UTF-8-readable binary log file rather than an unread pipe;
- close parent file descriptors after launch;
- keep the process, containment object, log path, model identities, endpoint, and cleanup state inside the opaque handle;
- the opaque handle must never appear in public models, diagnostics, events, or error details.

### POSIX

- launch in a new session/process group;
- graceful stop signals the owned process group;
- after `stop_timeout_seconds`, force-kill the owned process group;
- wait for process reaping;
- never signal an unmanaged PID or process group.

### Windows

Use actual process-tree containment rather than stopping only the immediate Python process.

Preferred implementation:

- create the process suspended or otherwise safely assign it to an ARCADIA-owned Windows Job Object;
- configure kill-on-job-close;
- resume it only after assignment succeeds;
- gracefully terminate where practical, then close/terminate the job after timeout;
- use narrow standard-library `ctypes` wrappers with correct signatures and handle cleanup.

A documented `CREATE_NEW_PROCESS_GROUP` plus owned-tree `taskkill /T` fallback is acceptable only when Job Object setup is genuinely unavailable. Never invoke through a shell and never target a PID not returned by the backend launcher.

Simulate both platforms in ordinary tests. Real Windows and POSIX process-tree smoke tests may be separated and skipped when the platform is unavailable.

## Runtime files and log lifetime

For each start attempt, create a private runtime directory under `runtime_dir` or a safe temporary base.

Contents may include:

```text
server-config.json
server.log
```

Rules:

- failed starts remove the config, close descriptors, terminate/reap the process tree, and remove all attempt-owned temporary files/directories;
- after successful readiness, remove the config when it is no longer needed by the child;
- retain the log while the `BackendInstance` handle is retained so Session 06 can read logs after stop;
- arrange best-effort final cleanup when the opaque handle is discarded, without a global registry or non-daemon worker;
- stopping never deletes Hugging Face cache files;
- replacement of one service must not remove another service’s runtime files.

## Startup and readiness

After launch:

1. Report `STARTING` with a concise message.
2. Poll until the configured startup deadline.
3. On every poll, check process exit before HTTP health.
4. Probe the local health host at `/v1/models` with the configured request timeout.
5. Require HTTP 200 and valid JSON containing a `data` list.
6. Return only after readiness succeeds.
7. Remove the temporary server config after readiness.
8. Return a `BackendInstance` containing:
   - `ServiceEndpoint(advertise_host, spec.port, spec.service_type)`;
   - a detached copy of the supplied `ResolvedRuntimeSettings`;
   - the opaque owned handle.

Use a monotonic deadline for timeout calculations. Inject clock/sleep/probe boundaries so tests do not really wait.

Failure behavior:

- process exits before readiness: `ServiceStartupError(code="llama_cpp_server_exited")`;
- startup deadline expires: `ServiceStartupError(code="llama_cpp_startup_timeout")`;
- malformed successful health response: continue polling until timeout unless the process exits;
- launch failure: `ServiceStartupError(code="llama_cpp_process_launch_failed")`;
- invalid translated settings/config: `ServiceStartupError(code="llama_cpp_settings_invalid")`.

Every failure after runtime creation must invoke transactional cleanup before raising. Cleanup failure must be retained in the cause/debug chain, but must not hide the primary startup error or leak a live child silently.

## `check_health`

Requirements:

- validate that `instance.handle` is a handle created by this backend;
- reject foreign/malformed handles with `ServiceHealthError(code="llama_cpp_handle_invalid")`;
- if the process exited, raise `ServiceHealthError(code="llama_cpp_process_exited")` with safe PID and exit-code details;
- otherwise perform one bounded `/v1/models` probe;
- require HTTP 200 and valid `data` list;
- translate connection, timeout, HTTP, JSON, and shape failures to `ServiceHealthError(code="llama_cpp_health_failed")`;
- retain the cause and never include response bodies in public details;
- perform no retry loop here; Session 06 calls this synchronously and later analysis restart policy belongs to Session 14.

## `stop`

Requirements:

- validate the opaque handle and reject foreign handles with `ServiceError(code="llama_cpp_handle_invalid")`;
- report only `ServiceState.STOPPING`;
- be idempotent when called repeatedly on an already-exited/stopped handle;
- terminate the complete owned process tree using the configured graceful and forced deadlines;
- reap the immediate child;
- close containment handles and backend-owned descriptors exactly once;
- retain the log for post-stop reads;
- translate failure to `ServiceError(code="llama_cpp_stop_failed")` with safe PID/exception-type details and retained cause;
- never delete model/projector cache files.

`stop()` must be safe when called during cleanup of a partially initialized actual handle returned by a faulty boundary, and direct repeated calls must satisfy the reusable Session 06 backend contract.

## Diagnostics

`diagnostics(instance)` returns a bounded JSON-compatible mapping. Include useful fields equivalent to:

```text
pid
alive
return_code
bind_host
advertise_host
port
service_type
model_repo_id
model_filename
model_revision
projector_repo_id/projector_filename/projector_revision when present
log_size_bytes
started_at
stopped_at when known
```

Requirements:

- no opaque handle, process object, Job Object handle, file descriptor, environment mapping, token, full command line, traceback, or response body;
- avoid absolute cache/runtime paths; model identities are sufficient;
- cap diagnostic strings and validate finite numbers;
- remain callable while running and after stop;
- arbitrary internal failures become `ServiceError(code="llama_cpp_diagnostics_failed")` with retained cause.

## Logs

`read_logs(instance, *, tail_lines)` must:

- validate the handle and exact positive integer `tail_lines`;
- return at most the requested final logical lines;
- decode UTF-8 with replacement for invalid bytes;
- avoid reading the entire file for a large log; read backward in bounded blocks;
- work while the child is writing and after stop;
- return an empty string when the log exists but has no content;
- translate read failures to `ServiceError(code="llama_cpp_logs_failed")`;
- never return model files, config contents, environment values, or arbitrary paths.

Session 06 enforces the public `1..5000` bound, but the backend must still reject invalid direct calls safely.

## Stable error codes

Use these codes where applicable:

```text
llama_cpp_dependency_missing
llama_cpp_spec_invalid
llama_cpp_backend_mismatch
llama_cpp_settings_invalid
llama_cpp_split_gguf_unsupported
llama_cpp_model_resolve_failed
llama_cpp_process_launch_failed
llama_cpp_server_exited
llama_cpp_startup_timeout
llama_cpp_handle_invalid
llama_cpp_process_exited
llama_cpp_health_failed
llama_cpp_stop_failed
llama_cpp_diagnostics_failed
llama_cpp_logs_failed
```

Public details must be concise, safe, JSON-compatible, and detached. Causes retain raw internal exceptions for local diagnostics but never serialize across boundaries.

Catch and translate `Exception`, not `BaseException`. `KeyboardInterrupt`, `SystemExit`, and comparable control-flow exceptions must propagate after best-effort startup cleanup when resources were already created.

## Concurrency and state

- One backend object may serve both `llm` and `visual_llm` mappings in one `ServiceManager`.
- Different ports may start concurrently from different threads.
- Do not place a backend-wide lock around downloads, launch, health, logs, or stop.
- A handle may use a small private lock for idempotent stop/finalization state.
- Diagnostics and log reads may overlap process execution.
- File resolution may rely on Hugging Face Hub’s cache locking; do not build another global cache registry.
- No background polling thread, async task, global singleton, or persistent service registry.

## Explicit non-goals

Session 07 does not provide:

- direct chat/completions or vision inference clients;
- model discovery, model listing, quant recommendation, or wildcard selection;
- split GGUF support;
- speculative decoding, MTP, DFlash, draft-model orchestration, or multiple model processes per port;
- automatic tuning based on detected VRAM/RAM;
- automatic restart after crash;
- model cache deletion/eviction;
- API authentication or TLS;
- multiple models inside one llama-cpp-python server config;
- in-process llama.cpp execution;
- validation that a locally installed wheel was compiled for CUDA or Metal;
- installation scripts for platform-specific wheels.

The backend must still pass arbitrary valid llama model/server options through the documented option containers so later power-user profiles do not require code changes for every llama-cpp-python setting.

## Tests required

### Unit tests

Use fake file resolvers, process launchers/controllers, health probes, clocks, sleepers, and progress reporters. Cover at minimum:

- lightweight import and construction with optional packages absent;
- configuration validation and wildcard advertise/health behavior;
- stable backend ID and runtime protocol compliance;
- spec/backend validation and complete input non-mutation;
- exact model and projector resolution order;
- cache hit versus download progress states;
- missing dependency and resolver failure translation;
- glob and split-GGUF rejection;
- flat/model/server option merging, duplicate detection, reserved keys, and defensive copies;
- CPU, CUDA index/environment, Metal, threads, explicit partial offload, and contradictory settings;
- generated config contents and restrictive creation behavior;
- exact command list and `shell=False` launch;
- no command/environment/secret leakage;
- startup success, process early exit, timeout, malformed health, and launch failure;
- transactional cleanup at every failure point;
- endpoint bind/advertise/health host separation, including IPv4 and IPv6 formatting;
- health success and every failure translation;
- idempotent repeated stop and graceful-to-forced termination;
- simulated POSIX process-group containment;
- simulated Windows Job Object or documented owned-tree fallback behavior;
- diagnostics before/after stop and safe bounded fields;
- log tailing for empty, short, large, invalid UTF-8, concurrent-write, and missing/error cases;
- foreign handle rejection for health, stop, diagnostics, and logs;
- different backend handles operating concurrently without a global lock;
- `Exception` translation and `BaseException` propagation with cleanup.

### Reusable backend contract

Add `tests/contract/test_llama_cpp_backend_contract.py` and run the real `LlamaCppBackend` implementation through the Session 06 reusable behavior using injected fake boundaries.

Verify:

- `isinstance(backend, ServiceBackend)`;
- stable `backend_id`;
- start/health/diagnostics/logs/repeated stop;
- use through a real `ServiceManager`;
- both `LLM` and `VISUAL_LLM` specifications;
- no handle leakage through statuses, events, diagnostics models, or serialized output;
- no real optional dependency, model, GPU, subprocess, or network required.

Refactor the existing contract-test helper minimally only when necessary to reuse it. Do not weaken its assertions.

### Integration tests

`tests/integration/test_llama_cpp_backend_integration.py` should combine real Session 01, 05, 06, and Session 07 code with controlled lightweight boundaries.

Cover:

- real hardware resolution feeding the backend through `ServiceManager`;
- actual temporary config/log files;
- a lightweight local test HTTP server or subprocess fixture implementing `/v1/models`;
- process launch/readiness/log/stop cleanup without importing llama-cpp-python;
- healthy reuse and replacement through the real manager;
- visual model/projector path construction using local fake cache files;
- JSON round trips for manager status, operations, diagnostics, and log snapshots;
- failed startup leaves no live child or attempt directory.

Mark true platform process-tree smoke tests separately. Standard CI must not download a model or require CUDA/Metal.

### Package tests

Extend `tests/test_package.py` to verify:

- `import arcadia` does not import `arcadia.backends`;
- `import arcadia.backends` does not import `arcadia.backends.llama_cpp`;
- `import arcadia.backends.llama_cpp` does not import `llama_cpp`, `huggingface_hub`, FastAPI, or Uvicorn;
- import/construction starts no process, thread, HTTP request, download, filesystem write, port probe, or hardware detection;
- the built wheel contains the new package;
- base-wheel import works without llama extras;
- a base-wheel start attempt using real default boundaries fails with the typed dependency error rather than raw `ModuleNotFoundError`.

## Validation

Record exact commands and results in the completion record.

Baseline:

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src/arcadia
pytest
```

Focused validation:

```bash
ruff format --check src/arcadia/backends tests/unit/backends/llama_cpp tests/contract/test_llama_cpp_backend_contract.py tests/integration/test_llama_cpp_backend_integration.py tests/test_package.py
ruff check src/arcadia/backends tests/unit/backends/llama_cpp tests/contract/test_llama_cpp_backend_contract.py tests/integration/test_llama_cpp_backend_integration.py tests/test_package.py
mypy src/arcadia
pytest tests/unit/backends/llama_cpp tests/contract/test_llama_cpp_backend_contract.py tests/integration/test_llama_cpp_backend_integration.py tests/test_package.py
```

Full validation:

```bash
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

### Clean-wheel smoke test

In a new temporary virtual environment with no editable source access:

1. Install the built base wheel without `[llama]`.
2. Import `arcadia.backends.llama_cpp` and construct configuration/backend objects.
3. Confirm heavy optional packages are absent from `sys.modules`.
4. Confirm a real default start boundary reports `llama_cpp_dependency_missing` cleanly.
5. Construct the backend with fake resolver/launcher/health boundaries.
6. Use it through a real `ServiceManager` to ensure, check health, inspect diagnostics/logs, stop, and shut down a fake service.
7. Verify serialized public snapshots contain no opaque handle or absolute runtime/model path.

### Optional manual smoke

When a machine already has a compatible `llama-cpp-python[server]` installation and a deliberately selected small exact GGUF file, record a manual smoke separately:

- cache/download the exact file;
- start the server through `ServiceManager`;
- confirm `/v1/models` readiness;
- inspect logs/diagnostics;
- stop and verify the process tree exited.

This manual smoke is useful but not required for ordinary CI or completion when the environment lacks a compatible native runtime. Never download a large model merely to satisfy this session.

## Definition of done

- [x] Work began from current clean `headless-core`.
- [x] The canonical session file was committed and pushed with status `in-progress`.
- [x] Required public API exists with backend ID `llama_cpp`.
- [x] Base imports remain lightweight and optional dependencies are lazy.
- [x] Exact model/projector cache and download behavior is implemented.
- [x] Split/wildcard model selection is rejected clearly.
- [x] Resolved ARCADIA settings produce deterministic safe server configuration.
- [x] CPU, one selected CUDA device, and Metal translation are covered.
- [x] Server launch uses an argument list, `shell=False`, config file, and owned log.
- [x] Startup waits for valid `/v1/models` readiness with bounded timeouts.
- [x] POSIX and Windows process-tree containment are implemented and simulated in tests.
- [x] Failed starts clean every attempt-owned process and temporary resource.
- [x] Health, idempotent stop, diagnostics, and bounded logs satisfy Session 06.
- [x] No cache file is automatically deleted.
- [x] No direct inference, SAM, transport, analysis, tool, CLI, or UI code was added.
- [x] Unit, contract, integration, package, full-suite, build, and clean-wheel validation pass or are recorded honestly.
- [x] Completion record and session index are accurate.
- [x] Final commits were pushed normally to `origin/headless-core`.
- [x] Working tree is clean and local `HEAD` equals `origin/headless-core`.

## Stop conditions

Stop and record `partial` or `blocked` rather than expanding scope if implementation requires:

- changing Session 01, 03, 05, or 06 public contracts;
- adding llama.cpp/FastAPI/Hugging Face packages to base dependencies;
- loading models in the ARCADIA process;
- moving generic lifecycle policy into the backend;
- adopting or killing unmanaged processes;
- weakening process-tree cleanup or transactional-start requirements;
- downloading models in standard tests;
- storing credentials in runtime settings or manifests;
- adding automatic fit estimation, restart policy, transport, or inference clients;
- force-pushing or overwriting remote `headless-core` history.

An honest pushed partial implementation is preferable to an undocumented contract change or local-only work.

---

# Completion record

## Outcome

Completed. `arcadia.backends.llama_cpp` now resolves exact GGUF files, translates resolved settings, launches and owns a synchronous `llama_cpp.server` subprocess, waits for OpenAI models-endpoint readiness, and provides bounded health, stop, diagnostics, and log behavior through the Session 06 backend contract.

## Git delivery

- Starting `origin/headless-core`: `f6f7cfcda2c326ddbcb54d522a655d45b5b8d5f8`.
- Session-start commit: `e76f87a` (`docs: start llama-cpp backend session`), pushed before implementation.
- Implementation commit: `7636e84` (`feat: add llama-cpp service backend`), pushed normally.
- Final pushed commit: the completion-record commit containing this section and the final Windows-containment regression test; local `HEAD` was verified against `origin/headless-core` after push.
- No rebase conflict occurred and no force push was used.

## Files changed

- Added `src/arcadia/backends/__init__.py` and `src/arcadia/backends/llama_cpp/{__init__,backend,config,files,health,process,settings}.py`.
- Added unit tests under `tests/unit/backends/llama_cpp/`, reusable fakes under `tests/helpers/`, the llama backend contract test, and the local-subprocess integration test.
- Updated `tests/test_package.py`, `pyproject.toml`, this session record, and `docs/sessions/README.md`.

## Delivered public API

`from arcadia.backends.llama_cpp import LLAMA_CPP_BACKEND_ID, LlamaCppBackendConfig, LlamaCppBackend` is stable. `LLAMA_CPP_BACKEND_ID == "llama_cpp"` and `LlamaCppBackend` satisfies the runtime-checkable `ServiceBackend` protocol. `arcadia.backends` and the root package do not re-export concrete backends.

## State and side effects

The default resolver first performs an exact cache-only `hf_hub_download`, then downloads only the exact repository, filename, and revision after a cache miss. Each start owns a private runtime directory, restrictive JSON config, retained binary log, child process, containment boundary, endpoint, and identities. Successful readiness removes the config; failed startup terminates/reaps the tree and removes all attempt files. Stop retains the log until the opaque handle is discarded. Health uses bounded `GET /v1/models` requests. CUDA selection changes only the child environment. Hugging Face cache files are never modified or deleted.

## Settings translation

`server_options` and `model_options` accept detached JSON objects with lowercase snake-case keys; other non-owned top-level values merge into model options without duplicates. Backend-owned server/model identity keys, credentials/private keys, ambiguous `threads`/`n_threads`, and non-finite values are rejected. CPU defaults `n_gpu_layers=0`, CUDA defaults `-1` plus one `CUDA_VISIBLE_DEVICES` index, Metal defaults `-1`, compatible explicit partial offload is retained, and `threads` maps to `n_threads`. The generated config contains one local model and an optional projector.

## Errors

The implementation emits the planned stable `llama_cpp_*` codes for missing dependencies, invalid specs/backend/settings, split GGUF, model resolution, process launch/exit/timeout, invalid handles, process health, health probes, stop, diagnostics, and logs. Public details contain only bounded identities, PID/return code, setting names, and exception types; raw exceptions remain in `cause`.

## Tests and validation

- `python -m pip install -e ".[dev]"` — passed.
- Initial focused run found two test-fixture defects; after correction, `pytest -q tests/unit/backends/llama_cpp tests/contract/test_llama_cpp_backend_contract.py tests/integration/test_llama_cpp_backend_integration.py tests/test_package.py` — 57 passed.
- Final `ruff format --check .` — 100 files already formatted; `ruff check .` and `mypy src/arcadia` — passed.
- Final full suite after adding the Windows fallback assertion: `pytest -q` — 560 passed.
- `python -m build` — built the sdist and base wheel; the wheel contains the new backend package.
- Clean-wheel smoke in `/tmp/arcadia-wheel-smoke-07` — the first script run exposed and corrected a smoke-fixture progress-enum error; the final isolated base-wheel run printed `clean-wheel-smoke-ok`. It verified lazy imports, typed missing-dependency startup, fake-boundary manager lifecycle, JSON serialization, and no handle/absolute-path leakage.
- POSIX containment was simulated for graceful-to-forced signaling and exercised with a real local child process tree on macOS. Windows `CREATE_NEW_PROCESS_GROUP` launch and owned-PID `taskkill /T /F` fallback were simulated. No Windows host was available for a real process-tree smoke.
- No real llama.cpp runtime/model smoke was run; standard tests used fake GGUF files and a local standard-library HTTP subprocess without network downloads.

## Decisions and deviations

No earlier public contract or base dependency changed, and no ADR was needed. The optional `llama` extra is `huggingface-hub>=0.34,<2` plus `llama-cpp-python[server]>=0.3,<0.4`. POSIX uses a new session/process group. Windows uses the allowed `CREATE_NEW_PROCESS_GROUP` plus exact owned-PID `taskkill /T` fallback because portable `subprocess.Popen` does not expose a race-free suspended-thread Job Object assignment boundary.

## Known limitations

Split GGUF, gated-repository workflows, authentication/TLS settings, multiple models, automatic fit/tuning/restart/cache eviction, in-process inference, and runtime wheel capability detection remain unsupported. Windows containment has simulated coverage only. Logs remain available while the backend handle is retained and are removed best-effort when that handle is discarded.

## Assumptions and risks

Detected CUDA or Metal hardware does not prove the installed `llama-cpp-python` wheel supports that accelerator. Upstream server option names and JSON configuration behavior may evolve within the bounded dependency range; power-user options are validated but otherwise passed through.

## Next-session prerequisites

Later sessions may construct one `LlamaCppBackend` for both LLM service types, pass it to `ServiceManager`, and rely on return only after `/v1/models` readiness, advertised endpoints, exact model identity, transactional startup, complete owned-tree stop, post-stop diagnostics/logs, and lazy optional dependencies. Direct inference remains a later-session responsibility.
