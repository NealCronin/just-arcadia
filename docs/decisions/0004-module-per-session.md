# ADR 0004: Design One Major Module per Development Session

- Status: Accepted
- Date: 2026-07-27

## Context

ARCADIA will be developed through multiple focused agent sessions. Without strict scope and handoff requirements, each session may reinterpret architecture, duplicate behavior, or modify unrelated modules.

## Decision

Assign each major module to one primary implementation session.

Every session receives:

- architecture and contract documents;
- public APIs from prerequisite modules;
- an explicit file scope;
- required behaviors and failure cases;
- acceptance tests;
- non-goals.

Every session produces:

- one focused module;
- tests;
- public documentation;
- a handoff record;
- known limitations and assumptions.

A session may not silently change an earlier public contract.

## Consequences

### Positive

- Work remains reviewable and bounded.
- Module ownership is clear.
- Later sessions receive explicit, reusable contracts.
- Architectural drift becomes visible.

### Negative

- Some sessions may discover that an earlier contract needs revision.
- Documentation and handoff work are mandatory.
- Cross-cutting refactors require deliberate coordination rather than opportunistic edits.

## Rejected alternatives

### Allow each session to refactor whatever it needs

Rejected because it would recreate the same broad, difficult-to-debug coupling as the legacy project.
