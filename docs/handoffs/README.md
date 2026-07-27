# ARCADIA Session Handoffs

Every implementation session must create one handoff document so the next session can use the module without reconstructing its design from source code.

## Filename

```text
session-XX-<module>.md
```

## Required format

```markdown
# Session XX Handoff: <Module>

## Summary
A concise description of what was implemented.

## Files created or changed
A complete list grouped by source, tests, and documentation.

## Public API
Document every public class, protocol, function, and important model.
Include signatures or short examples where useful.

## State owned
Describe runtime state, persistence, lifecycle, and cleanup.

## External side effects
Describe filesystem, network, subprocess, model, GPU, event, and timing behavior.

## Events emitted
List event kinds and minimum payload fields.

## Errors raised
List exception types, stable codes, retryability, and common causes.

## Concurrency and shutdown
Describe locks, queues, threads, async tasks, cancellation, and cleanup behavior.

## Tests added
List significant success, failure, boundary, and contract tests.

## Validation performed
Record the exact commands run and whether they passed.

## Architectural decisions
List any new ADRs or intentional deviations from existing documents.

## Known limitations
State what is deliberately unsupported or incomplete.

## Assumptions
State assumptions that later sessions must not mistake for proven facts.

## Requirements for the next session
List concrete APIs or behaviors available to the next module.
```

## Rules

- Do not claim a command passed unless it was actually executed.
- Do not hide failed tests or environment limitations.
- Do not use the handoff to silently redefine architecture.
- Link to an ADR when behavior changed materially.
- Mention any temporary compatibility code explicitly.
