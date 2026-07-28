# Session 00: Headless Project Scaffold

- Status: completed
- Branch: `headless-core`
- Completion commit: `13eddb3` with later handoff correction `ee0f1d5`

## Objective

Create a clean, installable, headless Python package for ARCADIA without migrating Django or inference functionality. Establish project-wide architecture, dependency rules, testing, packaging, and CI so later modules can be implemented independently.

## Planned scope

- Create the `src/arcadia` package.
- Keep `import arcadia` lightweight and free of heavy optional dependencies.
- Configure packaging, Ruff, mypy, pytest, and build validation.
- Add cross-platform CI and wheel installation smoke tests.
- Record the headless architecture and legacy migration map.
- Implement no domain, service, inference, storage, transport, tool, or UI behavior.

---

# Completion record

## Outcome

Session 0 completed successfully. The repository now contains an installable `arcadia-core` 0.1.0 scaffold and the project-wide architecture documents. No domain functionality was added.

## Files changed

### Source

- `src/arcadia/__init__.py`
- `src/arcadia/py.typed`

### Tests

- `tests/test_package.py`
- package markers under `tests/unit`, `tests/contract`, and `tests/integration`

### Tooling and CI

- `pyproject.toml`
- `.gitignore`
- `scripts/check.sh`
- `scripts/check.ps1`
- `.github/workflows/ci.yml`

### Documentation

- `README.md`
- `docs/architecture.md`
- `docs/contracts.md`
- `docs/legacy-inventory.md`
- ADRs 0001 through 0004

## Delivered public API

```python
import arcadia

arcadia.__version__  # "0.1.0"
```

No other public symbols are exposed.

## State and side effects

The package owns no runtime state. Importing `arcadia` performs no filesystem, network, subprocess, model-loading, or GPU operations.

## Errors and events

None.

## Tests and validation

The Session 0 implementation reported:

- Ruff format check: passed
- Ruff lint: passed
- mypy: passed
- pytest: 5 passed
- package build: passed
- clean-wheel import smoke test: passed
- GitHub Actions on Ubuntu Python 3.11 and 3.12: passed
- GitHub Actions on Windows Python 3.11: passed
- GitHub Actions on macOS Python 3.11: passed

## Decisions and deviations

- The legacy Django application remains in `NealCronin/Almost-ARCADIA` as read-only behavioral reference.
- Python 3.11+ is required.
- `setuptools` and a `src/` layout are used.
- Heavy feature dependency groups exist as empty placeholders.
- Licensing was intentionally deferred for the prototype.

## Known limitations

- No lockfile is committed.
- No CUDA, Metal, llama.cpp, SAM, or Priority Map behavior exists yet.
- Optional dependency groups remain empty until their owning sessions.

## Assumptions and risks

- The legacy repository or a local 0.6.12 copy remains available when behavioral comparison is needed.
- Base package imports must continue avoiding Django, FastAPI, Uvicorn, OpenCV, Torch, Ultralytics, and llama-cpp-python.

## Next-session prerequisites

Session 1 may add `arcadia.models` and Pydantic 2 while preserving the lightweight root import. The existing package tests intentionally continue prohibiting future `arcadia.services`, `arcadia.analysis`, and `arcadia.tools` packages until their owning sessions.
