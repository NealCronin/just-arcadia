# ARCADIA Session 0 Documentation Pack

This pack defines the architecture and development contracts for rebuilding Almost ARCADIA as a headless Python package.

The documents are intended to be copied into the root of the new headless branch or repository before implementation begins.

## Contents

- `docs/architecture.md` — agreed system behavior and boundaries.
- `docs/contracts.md` — dependency rules and module-design requirements.
- `docs/legacy-inventory.md` — map from Almost ARCADIA 0.6.12 to future modules.
- `docs/decisions/` — architecture decision records.
- `docs/sessions/session-template.md` — template for one-module development sessions.
- `docs/handoffs/README.md` — required handoff format between sessions.
- `SESSION_0_LOCAL_AGENT_PROMPT.md` — implementation prompt for project scaffolding and tooling.

## Prototype priorities

ARCADIA is currently a research prototype. Optimize for:

1. debuggability;
2. reliability during demonstrations;
3. modularity and extensibility;
4. usability by a technical operator.

Do not introduce enterprise deployment, multi-user permissions, authentication, licensing, packaging bureaucracy, or premature performance optimization unless later requirements make them necessary.
