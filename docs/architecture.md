# ARCADIA Headless Architecture

## 1. Purpose

ARCADIA is a headless Python orchestration package for running fixed-sequence research pipelines that depend on local or remote model inference.

The first supported tool will be Priority Map. Other research tools may be added later through a common tool interface.

ARCADIA Core must be usable directly as a Python module and through a diagnostic CLI. A web or desktop interface will be added only after the headless workflow has been proven reliable.

## 2. Design priorities

The current goal is a strong research demo, not a product intended for thousands of untrusted users.

Priorities, in order:

1. Debuggability
2. Reliability
3. Extensibility
4. Usability for a power user
5. Performance where it materially affects the demo

Non-priorities for the first prototype:

- authentication and user accounts;
- TLS and public-internet deployment;
- multi-tenant scheduling;
- automatic model deletion or cache eviction;
- distributed pipeline stages running concurrently;
- pause and resume;
- enterprise configuration management;
- hidden restrictions on advanced runtime settings.

## 3. Core terminology

### Orchestrator

The process that owns an analysis run. It:

- loads the selected tool configuration;
- chooses a compute node and inference port for each inference stage;
- asks nodes to provision services;
- passes the resulting inference endpoints to the tool;
- records events, settings, logs, artifacts, and final status.

The future UI will be a wrapper around the orchestrator.

### Compute node

A machine capable of hosting one or more model services.

A compute node may be:

- the same machine as the orchestrator; or
- a remote machine reachable over LAN or VPN.

"Client" and "host" describe roles, not different implementations. The orchestrator machine can also host local models.

### Instruction server

A thin HTTP wrapper on a compute node. It accepts service setup and lifecycle instructions and exposes progress, status, logs, and hardware capabilities.

The instruction server does not proxy inference. Once a service is ready, inference requests go directly to that service's inference port.

### Service instance

One inference service bound to one port on one compute node.

Its stable identity during a node session is:

```text
compute node + inference port
```

The same model running on two ports represents two independent service instances, even when the model file is identical.

### Tool

A fixed-sequence research pipeline implemented in Python. The tool owns its internal stage order and non-inference processing. ARCADIA supplies configured inference endpoints, run storage, events, and orchestration.

### Analysis

One execution of one tool over one input dataset. Only one analysis may be active in the first prototype.

## 4. System topology

```text
Orchestrator machine
├── Python API / diagnostic CLI / future UI
├── Analysis engine
├── Tool implementation
├── Run storage and logs
├── Local compute node
│   ├── Instruction interface or direct local adapter
│   └── Model services by port
└── Remote node clients
    ├── Remote compute node A
    │   ├── Instruction server
    │   └── Model services by port
    └── Remote compute node B
        ├── Instruction server
        └── Model services by port
```

Local and remote nodes must satisfy the same conceptual interface. Higher layers should not need separate pipeline logic for local and remote inference.

## 5. Compute-node behavior

### 5.1 Node configuration

A remote compute node is manually configured by the operator using:

- its LAN or VPN address; and
- its instruction port.

Automatic discovery is not required.

The instruction server binds to the user-selected LAN or VPN address. Plain HTTP is acceptable for the prototype's trusted-network deployment.

### 5.2 Session-stateless nodes

A compute node does not restore previously hosted services after its ARCADIA process restarts.

The orchestrator is authoritative. It sends the desired service specification whenever it needs a service.

On node startup:

- the service registry is empty;
- no old service definitions are loaded;
- no attempt is made to reattach to previous model processes;
- services launched by the current node process are stopped when that process exits.

### 5.3 Port ownership

Each inference port is a service slot.

When the orchestrator submits a specification for an unused port, the node provisions it.

When it submits the same effective specification to an already-ready port, the node may reuse the running service.

When it submits a different specification to the same port, the node:

1. verifies that no analysis configuration change is being applied during an active run;
2. stops the existing service;
3. resolves or downloads the requested model;
4. starts the replacement service;
5. health-checks it;
6. reports the new endpoint as ready.

A service remains running until:

- the node process exits; or
- the orchestrator replaces the configuration assigned to that port.

### 5.4 Model source

For llama.cpp-backed services, the orchestrator supplies:

- a Hugging Face repository;
- an exact model filename;
- requested runtime settings;
- the desired inference port.

The llama-cpp-python integration is responsible for finding a cached model or downloading it. Split-GGUF-specific application logic is out of scope for the first prototype.

The operator must be notified when a model is being downloaded and whether hosting ultimately succeeds.

Models are deleted only through an explicit manual action. Automatic cache eviction is out of scope.

Gated Hugging Face repositories are out of scope initially.

### 5.5 Hardware capabilities

Each compute node reports detected capabilities such as:

- operating system;
- CPU and logical cores;
- system memory;
- CUDA availability and GPU information;
- Metal/MPS availability;
- available inference backends.

Automatic resolution may provide recommended runtime values, but power-user overrides are always permitted.

Both the requested settings and the resolved settings actually used must be recorded for reproducibility.

## 6. Analysis behavior

### 6.1 Concurrency

Only one analysis may run at a time in the first prototype.

Pipeline stages run sequentially. Parallel stage scheduling and resource estimation are out of scope.

A compute node may host multiple model services simultaneously when the operator's selected configuration fits the machine. ARCADIA does not initially estimate whether a configuration will fit before starting it.

If a requested service cannot start because resources are insufficient, the operation fails and both the orchestrator and node receive an error event.

### 6.2 Configuration immutability

Analysis configuration is immutable while an analysis is running.

Configuration changes may be made only when no tool is active. This avoids model or endpoint changes halfway through a fixed pipeline.

Pause and resume are not required. A failure stops the pipeline while preserving completed work.

### 6.3 Failure policy

Transient network timeouts may be retried using a configurable retry policy.

If a model service crashes during inference:

1. attempt to restart the service;
2. retry the failed stage or request;
3. if the service fails again, stop the pipeline;
4. emit a concise error for presentation;
5. preserve full diagnostic details in the run log;
6. preserve all completed artifacts.

Invalid configuration, missing model files, failed model loads, and malformed inputs should fail immediately rather than being retried repeatedly.

Production execution must never silently replace a failed model with a mock implementation.

## 7. Priority Map boundary

Priority Map owns its fixed pipeline and frame-processing loop.

For the first integration:

- source frames remain on the orchestrator machine;
- datasets may contain dozens of gigabytes of frames;
- only frames needed for inference are transferred to remote services;
- VLM inference may run locally or remotely;
- SAM inference may run locally or remotely;
- all other Priority Map processing remains on the orchestrator machine;
- intermediate artifacts remain on the machine that produced them;
- final results are registered for future viewers;
- output is written incrementally so completed frames survive a crash.

The operator can configure:

- which node and port serve each inference stage;
- `sam_step`;
- VLM image resize behavior;
- SAM image resize behavior;
- frame skipping;
- fastest-possible processing or source-frame-rate pacing;
- retry settings.

SAM responses initially use JSON-compatible arrays and include:

- masks;
- labels;
- confidence values;
- bounding boxes;
- source image dimensions;
- processed image dimensions or scale information.

Payload optimization is deferred unless it prevents the demo from completing acceptably.

## 8. State ownership

### Configuration state

Human-editable persistent configuration belongs to the orchestrator. It includes:

- known node addresses;
- tool profiles;
- stage endpoint selections;
- requested model and runtime settings;
- retry settings;
- output settings.

### Node runtime state

A compute node owns only in-memory state for services launched during its current process lifetime.

### Analysis state

The analysis engine owns:

- active run identity;
- active tool state;
- current stage;
- final run status;
- run-scoped cancellation;
- configuration lock for the duration of the run.

### Tool state

A tool owns its internal sequential processing state. It may not mutate global ARCADIA configuration or service registries directly.

## 9. Observability and reproducibility

Every run must have:

- a run ID;
- one chronological JSONL event log;
- UTC ISO 8601 timestamps;
- requested settings;
- resolved runtime settings;
- detected hardware information;
- model repository and exact filename;
- endpoint assignments;
- tool settings;
- artifact records;
- final status;
- full errors and relevant service logs.

Every long-running service setup operation must have an operation ID and observable state such as:

```text
stopped
resolving
downloading
starting
ready
failed
stopping
```

Modules must emit structured events rather than relying on direct printing or UI-specific dictionaries.

## 10. Wrapper boundary

The future wrapper may:

- edit configurations;
- submit an analysis;
- display events and status;
- show final artifacts;
- expose service setup progress;
- export run directories.

The wrapper must not:

- build backend launch commands;
- download models;
- own model processes;
- implement retries;
- execute a pipeline loop;
- contain Priority Map internals;
- translate backend-specific failures itself.

All application behavior must remain available through the Python API without the wrapper.

## 11. Initial platform scope

The first working prototype must support:

- NVIDIA CUDA systems; and
- Apple Silicon systems using Metal/MPS where supported by the relevant backend.

CPU fallback may exist, but it is not the primary performance target.
