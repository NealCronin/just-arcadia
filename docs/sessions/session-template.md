# Session XX: <Module Name>

## Objective

State the single module or capability this session must design and implement.

## Architectural context

Summarize only the architecture decisions relevant to this module. Link to the authoritative documents rather than redefining them.

## Prerequisite public APIs

List the exact modules, types, protocols, and functions this session may consume.

## Allowed files

List the files and directories the session may create or modify.

Example:

```text
src/arcadia/events/**
tests/unit/events/**
tests/contract/test_event_sinks.py
docs/handoffs/session-03-events.md
```

## Prohibited changes

List modules and contracts the session must not modify.

## Required public API

Describe required classes, protocols, functions, and return values. Prefer behavioral requirements over forcing internal implementation details.

## State ownership

Describe all state this module may own and the lifecycle of that state.

## External side effects

Identify permitted filesystem, network, process, model, GPU, event, or timing behavior.

## Events emitted

List required event kinds and their minimum data.

## Errors raised

List required typed errors, stable error codes, and retryability.

## Required behavior

1. Describe the successful path.
2. Describe replacement or reuse behavior where applicable.
3. Describe failure behavior.
4. Describe cleanup and shutdown behavior.
5. Describe concurrency behavior.

## Explicit non-goals

List related features that must not be implemented in this session.

## Tests required

### Unit tests

- <case>
- <case>

### Contract tests

- <case>

### Integration tests

- <case, if any>

## Validation commands

```bash
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

Add module-specific commands where necessary.

## Definition of done

- [ ] Public API implemented
- [ ] Success behavior tested
- [ ] Failure behavior tested
- [ ] No prohibited imports or dependencies
- [ ] Documentation and docstrings complete
- [ ] Handoff document written
- [ ] Full validation passes

## Handoff requirements

Create:

```text
docs/handoffs/session-XX-<module>.md
```

Use the format defined in `docs/handoffs/README.md`.
