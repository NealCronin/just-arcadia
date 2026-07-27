# ADR 0002: Use a Unified Compute-Node and Port-Service Model

- Status: Accepted
- Date: 2026-07-27

## Context

A machine may orchestrate an analysis, host models locally, or provide remote compute over LAN or VPN. Treating "client" and "host" as different service implementations duplicates logic and makes local execution a special case.

Each model server is naturally reachable at an inference port, and the operator may intentionally run the same model with different settings on different ports.

## Decision

Represent every machine that can host inference as a compute node.

A service instance is identified during a node session by:

```text
compute node + inference port
```

Local and remote compute must expose equivalent high-level operations.

The instruction interface provisions and monitors services. Inference requests go directly to the configured service port.

Submitting a different effective service specification to an occupied ARCADIA-managed port replaces the current service on that port.

## Consequences

### Positive

- Local and remote execution share one architecture.
- Multiple independent model instances are naturally represented.
- Tool stages only need inference endpoints.
- Port replacement behavior is predictable.

### Negative

- Port conflicts and replacement state transitions require careful handling.
- Service identity does not survive a node restart.
- Higher-level profiles are needed to make repeated configurations convenient.

## Rejected alternatives

### Separate client and host runtime classes

Rejected because a client machine can also host models, and both roles require identical backend behavior.

### Identify services only by model name

Rejected because the same model may run on multiple ports with different settings.
