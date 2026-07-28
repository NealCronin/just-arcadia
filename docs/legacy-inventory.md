# Almost ARCADIA 0.6.12 Legacy Inventory

## 1. Purpose

Almost ARCADIA 0.6.12 is the behavioral reference for the headless rewrite. It is
available as a read-only reference at
[NealCronin/Almost-ARCADIA](https://github.com/NealCronin/Almost-ARCADIA)
or at a local reference path supplied by the operator. It is not imported by
the new `arcadia` core and is not included in this repository.

The inspected archive contains substantial working behavior and a useful test baseline. The goal is selective extraction, not a line-for-line port.

## 2. Baseline

Observed package areas:

- `core/` — configuration, analysis, service lifecycle, inference clients, Priority Map adapter, tooling.
- `web/` — Django forms, views, runtime state, templates, uploads, and result presentation.
- `project/` — Django project configuration.
- `tests/` — service, inference, storage, tooling, and web tests.

The previous review established a baseline of 117 passing non-web tests when the source root was importable. Preserve this as a characterization target, not as a requirement to copy all legacy tests immediately.

Large or highly coupled files include:

- `core/pipeline/priority_map_adapter.py` — 1,015 lines
- `core/services/sam_runtime.py` — 713 lines
- `core/config.py` — 691 lines
- `core/analysis.py` — 688 lines
- `core/services/llm_runtime.py` — 552 lines
- `web/views.py` — approximately 1,478 lines in the reviewed version
- `web/forms.py` — approximately 858 lines in the reviewed version

These concentrations are major reasons for beginning with a clean headless package.

## 3. Migration classifications

### Salvage concepts

Retain behavior and tests, but redesign the API and implementation.

### Extract carefully

Move a focused implementation after removing Django, global-state, and orchestration dependencies.

### Rewrite

Use only as behavioral reference because the current responsibility boundaries conflict with the headless architecture.

### Defer

Do not move into the headless MVP.

## 4. Component map

| Legacy component | Current responsibility | Future destination | Treatment | Notes |
|---|---|---|---|---|
| `core/errors.py` | Basic exception hierarchy | `arcadia.models.errors` or `arcadia.errors` | Salvage concepts | Expand to stable codes, structured details, cause, and retryability. |
| `core/services/specs.py` | Service spec, endpoint, and status data | Session 1 domain models | Salvage concepts | Separate requested settings, resolved settings, status, and operation progress. |
| `core/inference/results.py` | LLM and segmentation result data | Session 1 domain models / Session 12 results | Salvage concepts | Avoid backend-specific raw objects. |
| `core/config.py` | Persistent configuration plus many tool and service concerns | Session 2 configuration | Rewrite | Do not preserve one giant application configuration object or live runtime concepts. |
| `core/default_config.json` | Legacy defaults | Session 2 examples or migration reference | Defer migration | New defaults should follow new schemas. |
| `core/networking.py` | Local IPv4 discovery and validation | Hardware/network helper, if needed | Extract carefully | Remote hosts are entered manually; keep only useful validation. |
| `core/storage.py` | State-directory paths | Session 4 run storage | Salvage tests and path rules | New storage owns complete run directories and manifests. |
| `core/services/progress.py` | Service setup registry and UTC helper | Session 3 events | Rewrite | Replace mutable UI-shaped status registry with event models and operation status. |
| `core/services/llm_settings.py` | HF source parsing and llama settings validation | Sessions 1, 5, and 7 | Salvage heavily | Valuable validation behavior; split schema, auto-resolution, and backend launch concerns. |
| `core/services/controller.py` | Generic service registry and lifecycle | Session 6 service manager | Rewrite | Preserve per-port ownership ideas; remove legacy client/host identities and persistence assumptions. |
| `core/services/llm_runtime.py` | Model resolution/download/start/health/logs | Session 7 llama backend | Extract carefully | Separate backend behavior from generic service lifecycle and UI progress state. |
| `core/services/sam_checkpoint.py` | SAM checkpoint path storage | Session 8 SAM backend / Session 2 config | Salvage concepts | Checkpoint remains manually supplied due to model licensing. |
| `core/services/sam_runtime.py` | SAM loading, FastAPI app, request parsing, inference | Session 8 SAM backend plus later thin server | Rewrite and extract | Split model ownership, inference, transport, and device selection. Remove production mock fallback and target coordinates. |
| `core/services/instruction_server.py` | Host setup/status HTTP API | Sessions 9 and 10 | Salvage protocol behavior | New server is a thin wrapper around ServiceManager and is session-stateless. |
| `core/services/instruction_client.py` | Remote instruction API client | Session 11 node client | Extract carefully | Align with a versioned protocol and typed errors. |
| `core/services/host_listener.py` | Listener lifecycle | Session 10 server entry point | Rewrite | Future server process owns its listener; avoid a separate UI-managed listener state machine. |
| `core/services/path_browser.py` | Remote path browsing | Future wrapper capability | Defer | Not required for headless model provisioning using HF repo and filename. |
| `core/inference/llm_client.py` | Direct LLM inference requests | Session 12 inference clients | Extract carefully | Preserve known payload/result behavior; add retry policy and typed failures. |
| `core/inference/sam_client.py` | Direct SAM requests | Session 12 inference clients | Extract carefully | Update result schema to masks, labels, confidence, boxes, and image sizes. |
| `core/analysis.py` | Analysis state, orchestration, services, tool execution | Session 14 analysis engine | Rewrite | New engine coordinates modules only and enforces one immutable active run. |
| `core/pipeline/prompts.py` | Prompt defaults and overrides | Priority Map integration or tool profile config | Extract later | Prompts belong to the tool/profile, not the generic engine. |
| `core/pipeline/priority_map_adapter.py` | Large integrated adapter for Priority Map | Session 15 Priority Map tool | Rewrite | Replace with narrow scene, SAM, progress, and artifact adapters. |
| `core/tooling/specs.py` | Tool selection and artifact categories | Session 13 Tool SDK | Salvage concepts | Replace tool-name conditionals with tool protocol and typed artifacts. |
| `core/tooling/execution.py` | Native/WSL command construction and execution | Future external-tool backend | Defer | Useful for later reconstruction tools, not the first headless milestone. |
| `core/tooling/adapters.py` | COLMAP, MASt3R-SLAM, LingBot adapters | Future tool modules | Defer | Add only after Priority Map is stable. |
| `web/runtime.py` | Global UI runtime state | None | Do not migrate | Runtime state must be owned by headless modules. |
| `web/forms.py` | Validation mixed with presentation | Future wrapper | Do not migrate into core | Move reusable validation into schemas; later UI forms consume them. |
| `web/views.py` | UI routes plus orchestration | Future wrapper | Reference only | Future routes call public headless APIs and contain no pipeline behavior. |
| `web/models.py` | Django persistence | Future wrapper or optional persistence | Defer | Initial headless run state uses files; revisit only when useful. |
| `web/tools.py` | UI tool descriptions and routing | Future wrapper | Defer | Tool discovery should eventually use the Tool SDK. |
| `web/uploads.py` | Upload management | Future wrapper | Defer | Source datasets are ordinary client-side paths in the headless API. |
| `web/artifacts.py` | Result presentation helpers | Session 4 artifact concepts / future wrapper | Salvage concepts | Core records artifacts; wrapper decides how to render them. |
| `project/*` and `manage.py` | Django application bootstrap | Future wrapper | Do not migrate | The base package must not depend on Django. |
| install scripts | Platform setup | Later developer scripts | Reference | Rebuild after actual CUDA and Metal backends are defined. |

## 5. Test migration map

| Legacy test | Future ownership | Initial action |
|---|---|---|
| `test_llm_settings.py` | Sessions 1, 5, and 7 | Use as characterization input; rewrite against separated schemas and resolver. |
| `test_progress.py` | Session 3 | Preserve expected progress concepts, replace registry-specific assertions. |
| `test_storage.py` | Session 4 | Migrate useful path and directory-safety cases. |
| `test_controller.py` | Session 6 | Preserve port replacement and lifecycle scenarios; remove legacy service identities. |
| `test_llm_runtime.py` | Session 7 | Preserve cache, download, launch, health, and termination scenarios using fakes. |
| `test_sam_checkpoint.py` | Session 8 or config | Preserve manual checkpoint behavior. |
| `test_sam_runtime.py` | Session 8 | Rewrite around one model per node, serialized inference, no target coordinates. |
| `test_instruction_server.py` | Sessions 9 and 10 | Convert to protocol and thin-route contract tests. |
| `test_instruction_client.py` | Session 11 | Convert to typed remote-node client contract tests. |
| `test_llm_client.py` | Session 12 | Preserve request and response parsing. |
| `test_sam_client.py` | Session 12 | Update for the new JSON-array response schema. |
| `test_tooling.py` | Later external-tool work | Defer. |
| `test_graph_agent.py` | Session 15, if still relevant | Reassess against current Priority Map integration. |
| `test_forms.py` and `test_web.py` | Future wrapper | Do not migrate into the headless core. |

## 6. Explicitly rejected legacy patterns

The headless implementation must not reproduce these patterns:

- one global configuration object mixing user preferences, host setup, tool settings, and runtime state;
- Django views as orchestration entry points;
- UI-specific dictionaries as the internal status model;
- model-loading, HTTP-route, and inference behavior in one file;
- fixed `client:*` and `host:*` service identities;
- hidden mock inference after a real backend failure;
- tool-specific pipeline logic inside the generic analysis coordinator;
- importing all heavy dependencies as base package requirements;
- rebuilding remote and local execution as separate pipelines.

## 7. Legacy reference policy

Later sessions may inspect the tagged legacy source and copy focused code or tests when doing so preserves known behavior.

Any copied implementation must be adapted to the new contract and must not import the legacy package.

The new test suite should favor clear behavior-based tests over preserving legacy internal implementation details.
