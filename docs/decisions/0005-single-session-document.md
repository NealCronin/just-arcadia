# ADR 0005: Use One Canonical Document per Development Session

- Status: Accepted
- Date: 2026-07-28

## Context

The initial workflow created separate session prompts, design specifications, handoff templates, completed handoffs, and archived prompt copies. Those files repeated the same scope and public API in several places, made it unclear which document was authoritative, and required manual folder merging before a local agent could begin work.

Git already preserves the earlier form of a session document, so maintaining separate prompt-history copies adds little value.

## Decision

Each development session uses one canonical file:

```text
docs/sessions/NN-short-name.md
```

The file starts as the implementation work order. Before the session ends, the implementation agent updates the same file with its completion record and final status.

Project-wide architecture remains in:

```text
docs/architecture.md
docs/contracts.md
docs/decisions/
```

Session-specific API and acceptance details remain in the session file. Separate session prompt, design, handoff-template, completed-handoff, and prompt-history files are not created.

## Consequences

### Positive

- One authoritative session-specific document exists.
- A local agent can be pointed at one file.
- Planned and delivered behavior can be compared in place.
- Later sessions have a predictable location for the previous module's completion record.
- Git history preserves earlier prompt versions without a duplicate history folder.
- Repository documentation grows by one file per module instead of several.

### Negative

- Session files may be moderately long when the public API is substantial.
- The implementation agent must remember to update the same file before stopping.
- A reviewer must use Git history when the exact original work order is needed after completion edits.

## Migration

- Session 0 planning and handoff information are consolidated into `docs/sessions/00-scaffold.md`.
- Session 1 is represented by `docs/sessions/01-domain-models-and-errors.md`.
- The old `docs/handoffs/`, session template, and archived session prompt are removed.
