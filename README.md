# ARCADIA

ARCADIA is being rebuilt as a headless Python package for running fixed-sequence
research pipelines that depend on local or remote model inference.

The repository currently contains the completed Session 0 scaffold and the
completed Session 1 domain-models layer. No inference, service lifecycle,
transport, pipeline, storage, or UI functionality is implemented yet.

## Legacy implementation

The previous Django-based Almost ARCADIA implementation remains available in
the separate [`NealCronin/Almost-ARCADIA`](https://github.com/NealCronin/Almost-ARCADIA)
repository.

This repository contains the clean headless rewrite. The legacy implementation
may be consulted as a read-only behavioral reference, but it is not imported by
or included in the new package.

## Documentation

Project-wide documentation lives in [`docs/`](docs/):

- [`docs/architecture.md`](docs/architecture.md) — system behavior and boundaries
- [`docs/contracts.md`](docs/contracts.md) — module dependency rules and contracts
- [`docs/legacy-inventory.md`](docs/legacy-inventory.md) — migration map from legacy
- [`docs/decisions/`](docs/decisions/) — architecture decision records
- [`docs/sessions/`](docs/sessions/) — one canonical work-order and completion file per development session

The current implementation session is Session 02 (Configuration). See the
[`docs/sessions/README.md`](docs/sessions/README.md) session index and the
Session 01 completion record for completed work.

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
