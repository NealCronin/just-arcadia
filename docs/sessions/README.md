# ARCADIA Development Sessions

ARCADIA is developed one major module per focused agent session.

Each session uses exactly one canonical Markdown file:

```text
docs/sessions/NN-short-name.md
```

That file is both:

1. the work order given to the implementation agent; and
2. the completion record used by later sessions.

Do not create separate session prompts, design documents, handoff templates, or archived prompt copies. Git history already preserves prior versions of the session file.

## Session index

| Session | Module | Status |
|---|---|---|
| 00 | Project scaffold | Completed |
| 01 | Domain models and errors | Completed |
| 02 | Configuration | Completed |

## Session lifecycle

### 1. Plan the session

Create `docs/sessions/NN-short-name.md` with:

- status set to `planned`;
- objective and non-goals;
- prerequisite documents and APIs;
- allowed and prohibited files;
- required public API and behavior;
- failure behavior;
- tests and validation commands;
- a blank completion record.

The session file should be self-contained enough to pass directly to a local agent. It may link to `docs/architecture.md`, `docs/contracts.md`, and earlier completed session files instead of repeating stable project-wide rules.

Keep the session file focused. Aim for 100 to 250 lines for a normal module. Longer is acceptable only when defining a public protocol or many compatibility requirements — see `01-domain-models-and-errors.md` for the shared-contracts case.

### 2. Implement the session

The agent must:

1. read the authoritative project documents and current session file;
2. run baseline validation;
3. implement only the declared scope;
4. run the required validation;
5. update the same session file before stopping.

The agent marks `Status` as `in-progress` in the first commit and changes the final status to `completed`, `blocked`, or `partial` along with the completion record.

### Branch convention

Each session works on a dedicated branch:

```text
session/NN-short-name
```

Merge the session branch into `headless-core` after the work is reviewed and complete. This keeps each agent's changes reviewable and revertible as a unit.

### 3. Review the session

A reviewer should inspect:

- the code and tests;
- the final completion record;
- any changed public contracts;
- failed or skipped validation;
- assumptions that affect later sessions.

A session is not complete merely because code exists.

### 4. Start the next session

The next session normally reads only:

```text
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/sessions/NN-previous-session.md
docs/sessions/NN-current-session.md
```

It does not need to reconstruct the project from every prior session file. Stable APIs should be discoverable through source code, docstrings, tests, and the immediately preceding completion record.

## Canonical template

```markdown
# Session NN: Module Name

- Status: planned
- Branch: session/NN-short-name
- Owner: local agent session

## Objective

What this session must accomplish.

## Architectural context

Only the project-wide decisions relevant to this module. Link to the authoritative documents.

## Prerequisites

Exact documents, modules, and public APIs the agent must inspect before editing.

## Scope

### Allowed files

Paths this session may create or modify.

### Prohibited changes

Files, modules, and behaviors outside the session.

## Required public API

Classes, functions, protocols, models, and stable behavior that later modules may consume.

## Required behavior

Successful behavior, validation, failure handling, concurrency, cleanup, and serialization as applicable.

## Explicit non-goals

Related functionality that must not be implemented.

## Tests required

Unit, contract, integration, and package tests required for completion.

## Validation

Exact commands the agent must run.

## Definition of done

Checklist for completing the planned work.

---

# Completion record

The implementation agent fills this section before stopping.

## Outcome

What was implemented and the final status.

## Files changed

Source, tests, configuration, and documentation.

## Delivered public API

The actual stable API available to later sessions. Note any differences from the planned contract.

## State and side effects

State owned, filesystem/network/process/model behavior, and cleanup requirements.

## Errors and events

Typed errors raised and structured events emitted.

## Tests and validation

Exact commands run and results. Never claim an unexecuted command passed.

## Decisions and deviations

New ADRs, contract changes, or deviations from the work order.

## Known limitations

Unsupported or incomplete behavior.

## Assumptions and risks

Facts later sessions must not mistake for proven behavior.

## Next-session prerequisites

The concrete APIs and guarantees now available to the next module.
```

## Rules

- One session-specific file per session.
- The session file is updated in place; do not create a separate handoff.
- Do not duplicate stable architecture in every session file.
- Do not silently change an earlier module's public contract.
- Do not claim tests or commands passed unless they were run.
- Record partial work and environmental limitations honestly.
- Add an ADR only for a lasting architectural decision, not routine implementation details.
- Keep source code and tests authoritative; the completion record summarizes rather than reproduces every implementation detail.
