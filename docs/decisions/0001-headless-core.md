# ADR 0001: Build ARCADIA as a Headless Python Core

- Status: Accepted
- Date: 2026-07-27

## Context

Almost ARCADIA 0.6.12 combines Django presentation, persistent configuration, service management, model inference, analysis orchestration, and Priority Map adaptation. The project achieves part of the desired workflow, but failures are difficult to isolate and debug.

The intended system behavior should be usable by researchers without requiring the web interface, and future wrappers should not become alternative implementations of the pipeline.

## Decision

Create a new headless `arcadia` Python package as the authoritative implementation.

The package will expose normal Python APIs and later a diagnostic CLI. Django or another UI may be built as a thin wrapper only after the headless workflow is proven.

Almost ARCADIA 0.6.12 will be preserved as a behavioral reference rather than refactored in place.

## Consequences

### Positive

- Core behavior can be tested without Django.
- Failures can be localized to smaller modules.
- Scripts, notebooks, CLIs, and future UIs can share one implementation.
- Heavy inference dependencies can become optional.
- Tool integrations can be tested independently.

### Negative

- Some working legacy code must be selectively migrated or rewritten.
- The first milestone will temporarily have less visual functionality.
- Legacy behavior must be documented to avoid accidental regressions.

## Rejected alternatives

### Continue refactoring the Django project in place

Rejected because current responsibilities are too intertwined and later modules would remain coupled to global application state.

### Build another UI first

Rejected because it would reproduce the same debugging problem before the underlying service and pipeline contracts are stable.
