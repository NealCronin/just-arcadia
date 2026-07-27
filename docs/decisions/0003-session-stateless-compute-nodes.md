# ADR 0003: Keep Compute Nodes Session-Stateless

- Status: Accepted
- Date: 2026-07-27

## Context

The orchestrator always knows which model and settings it needs for each stage. Persisting previous host service definitions introduces PID recovery, stale state, port reconciliation, and ambiguity about whether a process still matches the remembered configuration.

The prototype values predictable behavior and debuggability over automatic recovery after a node restart.

## Decision

A compute node stores service definitions and process handles only in memory for the lifetime of its ARCADIA process.

After a node restart:

- the service registry is empty;
- the orchestrator must provision required services again;
- the node does not reconnect to or terminate unrelated pre-existing processes;
- services launched by the node are stopped during graceful shutdown.

The orchestrator remains the source of desired service configuration.

## Consequences

### Positive

- No stale persisted process state.
- Simpler startup and shutdown behavior.
- Easier debugging and testing.
- No PID reuse or old-port recovery logic.

### Negative

- Required services must be reprovisioned after a restart.
- A node crash may leave a backend process requiring operating-system cleanup if graceful shutdown does not occur.
- The orchestrator must retain reusable service profiles.

## Rejected alternatives

### Persist and restore every service

Rejected for the first prototype because the recovery logic is disproportionately complex and the orchestrator can resend desired state.
