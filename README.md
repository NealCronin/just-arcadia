# ARCADIA

ARCADIA is being rebuilt as a headless Python package for running fixed-sequence
research pipelines that depend on local or remote model inference.

This branch contains the **Session 0 scaffold**: project tooling, package
metadata, continuous integration, and the minimal installable `arcadia` package.
No domain functionality (inference, service lifecycle, transport, pipeline,
storage, or UI) is implemented yet.

## Legacy versions

The legacy Almost ARCADIA 0.6.12 (Django-based UI) is preserved as the
Git tag [`legacy-ui-0.6.12`](https://github.com/arcadia/arcadia/tags/legacy-ui-0.6.12).
The current branch is `headless-core`.

## Documentation

Architecture, contracts, and session documents live in [`docs/`](docs/):

- [`docs/architecture.md`](docs/architecture.md) — system behavior and boundaries
- [`docs/contracts.md`](docs/contracts.md) — module dependency rules and contracts
- [`docs/legacy-inventory.md`](docs/legacy-inventory.md) — migration map from legacy
- [`docs/decisions/`](docs/decisions/) — architecture decision records (ADRs)
- [`docs/sessions/session-template.md`](docs/sessions/session-template.md) — session template
- [`docs/handoffs/README.md`](docs/handoffs/README.md) — handoff format between sessions

## Development environment

### Prerequisites

- Python 3.11 or later

### Setup

```bash
python -m pip install -e ".[dev]"
```

[`uv`](https://docs.astral.sh/uv/) can be used if available, but is not required:

```bash
uv pip install -e ".[dev]"
```

### Running checks

```bash
# POSIX (Linux/macOS)
./scripts/check.sh

# Windows
.\scripts\check.ps1
```

These scripts run:

1. `ruff format --check .`
2. `ruff check .`
3. `mypy src/arcadia`
4. `pytest`
5. `python -m build`

## License

ARCADIA is proprietary research software. See the repository for details.
