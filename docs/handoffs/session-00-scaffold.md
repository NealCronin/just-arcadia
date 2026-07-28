# Session 0 Handoff: Scaffold

## Summary

Created the headless ARCADIA core project scaffold, development tooling, CI configuration, and a minimal installable `arcadia` package (`arcadia-core` v0.1.0). No domain functionality (inference, service lifecycle, transport, pipeline, storage, or UI) is implemented.

This is a new repository. The legacy Django-based Almost ARCADIA implementation is **not** included in this repository — it remains available as a read-only reference at [`NealCronin/Almost-ARCADIA`](https://github.com/NealCronin/Almost-ARCADIA) or at a local reference path supplied by the operator (e.g., `/Users/neal/Downloads/Almost-ARCADIA-0.6.12/`).

There is no current licensing declaration; licensing is intentionally deferred.

## Files created or changed

### Source
- `src/arcadia/__init__.py` — package init, exposes `__version__ = "0.1.0"`
- `src/arcadia/py.typed` — PEP 561 type marker (empty file)

### Tests
- `tests/__init__.py` — package marker
- `tests/test_package.py` — import, version, heavy-import, and no-future-packages tests
- `tests/unit/__init__.py` — package marker
- `tests/contract/__init__.py` — package marker
- `tests/integration/__init__.py` — package marker

### Configuration
- `pyproject.toml` — build system, project metadata, optional dependency groups, ruff/mypy/pytest config

### Tooling
- `.gitignore` — Python, editor, OS, build, model cache, and run output ignores
- `scripts/check.sh` — POSIX validation script (executable)
- `scripts/check.ps1` — PowerShell validation script

### CI
- `.github/workflows/ci.yml` — GitHub Actions CI with cross-platform matrix and wheel smoke test

### Documentation
- `README.md` — updated root documentation for the new project
- `examples/README.md` — placeholder for future examples

### Architecture documentation (preserved from Session 0 prompt)
- `docs/architecture.md` — system behavior and boundaries
- `docs/contracts.md` — module dependency rules and contracts
- `docs/legacy-inventory.md` — migration map from legacy
- `docs/decisions/0001-headless-core.md` — ADR 0001
- `docs/decisions/0002-compute-node-model.md` — ADR 0002
- `docs/decisions/0003-session-stateless-compute-nodes.md` — ADR 0003
- `docs/decisions/0004-module-per-session.md` — ADR 0004
- `docs/sessions/session-template.md` — session template
- `docs/handoffs/README.md` — handoff format between sessions
- `SESSION_0_LOCAL_AGENT_PROMPT.md` — original Session 0 implementation prompt

## Public API

```python
import arcadia

arcadia.__version__  # "0.1.0"
```

No other public symbols are exposed. `__version__` is a simple constant; no
`importlib.metadata` import occurs.

## State owned

None. The package has no runtime state.

## External side effects

None. Importing `arcadia` performs no filesystem, network, subprocess, or
model-loading operations.

## Events emitted

None.

## Errors raised

None at import time.

## Concurrency and shutdown

Not applicable — no concurrent or background operations exist.

## Tests added

- `tests/test_package.py::test_import_succeeds` — `import arcadia` succeeds
- `tests/test_package.py::test_version` — `__version__ == "0.1.0"`
- `tests/test_package.py::test_no_heavy_imports` — subprocess test verifying that
  `django`, `fastapi`, `uvicorn`, `cv2`, `torch`, `ultralytics`, and `llama_cpp`
  are not imported by `import arcadia`
- `tests/test_package.py::test_no_future_implementation_packages` — verifies that
  `arcadia.services`, `arcadia.analysis`, and `arcadia.tools` do not exist

## Validation performed

All commands run on the `headless-core` branch.

### Session 0 initial validation

Environment: Python 3.13.12, macOS 25.5.0 (arm64), setuptools-backed build.

```bash
# Install package and dev dependencies
python -m pip install -e ".[dev]"
# Result: Successfully installed arcadia-core-0.1.0

# Format check
ruff format --check .
# Result: 19 files already formatted — PASS

# Lint
ruff check .
# Result: OK — PASS

# Type-check
mypy src/arcadia
# Result: OK (1 source file) — PASS

# Tests
pytest
# Result: 4 passed in 0.03s — PASS

# Build
python -m build
# Result: Successfully built arcadia_core-0.1.0-py3-none-any.whl — PASS
```

### Wheel install smoke test (Session 0)

```bash
# Build wheel
python -m build --wheel
# Result: Successfully built arcadia_core-0.1.0-py3-none-any.whl

# Install in clean venv
python -m venv /tmp/arcadia-test-venv
/tmp/arcadia-test-venv/bin/pip install dist/*.whl
# Result: Successfully installed arcadia-core-0.1.0

# Verify import in clean environment
/tmp/arcadia-test-venv/bin/python -c "import arcadia; print(arcadia.__version__)"
# Result: 0.1.0 — PASS

# Verify no heavy imports in clean environment
/tmp/arcadia-test-venv/bin/python -c "import arcadia, sys; heavy=['django','fastapi','uvicorn','cv2','torch','ultralytics','llama_cpp']; print([m for m in heavy if m in sys.modules])"
# Result: [] — PASS
```

### Session 0 cleanup validation

After the Session 0 cleanup pass:

```bash
# Install package and dev dependencies
python -m pip install -e ".[dev]"
# Result: Successfully installed arcadia-core-0.1.0 — PASS

# Format check
ruff format --check .
# Result: all files already formatted — PASS

# Lint
ruff check .
# Result: OK — PASS

# Type-check
mypy src/arcadia
# Result: OK — PASS

# Tests
pytest
# Result: 4 passed — PASS

# Build
python -m build
# Result: Successfully built arcadia_core-0.1.0-py3-none-any.whl — PASS
```

### Wheel install smoke test (Session 0 cleanup)

```bash
# Build wheel
python -m build --wheel
# Result: Successfully built arcadia_core-0.1.0-py3-none-any.whl — PASS

# Create clean virtual environment
python -m venv .wheel-test-venv

# Install wheel in clean environment
.wheel-test-venv/bin/python -m pip install --upgrade pip
.wheel-test-venv/bin/python -m pip install dist/*.whl
# Result: Successfully installed arcadia-core-0.1.0 — PASS

# Verify clean import
.wheel-test-venv/bin/python -c "import arcadia; print(arcadia.__version__)"
# Result: 0.1.0 — PASS

### GitHub Actions CI status

All CI jobs on `headless-core` branch (commit `a43f856`):

- Tests (Python 3.11 on ubuntu-latest) — success
- Tests (Python 3.12 on ubuntu-latest) — success
- Tests (Python 3.11 on windows-latest) — success
- Tests (Python 3.11 on macos-latest) — success
- Build and install wheel smoke test — success
```

## Architectural decisions

- **ADR 0001**: Build ARCADIA as a headless Python core — this session implements
  the scaffold for that decision.
- **ADR 0004**: One major module per development session — Session 0 is the
  scaffold module; subsequent sessions will add domain packages.
- `src/` layout used per the Session 0 specification.
- `__version__` is a simple constant rather than computed from distribution
  metadata to keep the base import lightweight and avoid `importlib` overhead.
- Optional dependency groups (`node`, `llama`, `sam`, `priority-map`) defined as
  empty placeholders for future sessions; `dev` group includes pytest, pytest-cov,
  ruff, mypy, and build.
- Line length of 120 used per the Session 0 specification.
- No licensing declaration is included; licensing is intentionally deferred.
- Repository URLs corrected to reference `NealCronin/just-arcadia`.
- The legacy implementation is external and read-only.

## Known limitations

- The optional dependency groups `node`, `llama`, `sam`, and `priority-map` are
  empty placeholders; their contents will be defined when the owning sessions are
  implemented.
- No lockfile (`uv.lock` or similar) is committed. Generate one when network
  access allows: `uv lock` or `pip freeze > requirements.lock`.
- No CUDA, Metal, llama.cpp, SAM, or Priority Map validation is performed in
  Session 0 CI. These will be validated in later sessions on self-hosted systems.
- Licensing is not declared. This is intentional for the prototype phase.

## Assumptions

- Python 3.11+ is available in the development environment.
- `uv` is optional; `pip install -e ".[dev]"` is the canonical install path.
- The base package must never import heavy dependencies (django, fastapi,
  uvicorn, cv2, torch, ultralytics, llama-cpp-python). This invariant is
  enforced by `tests/test_package.py::test_no_heavy_imports`.
- The legacy Almost ARCADIA 0.6.12 implementation is available externally at
  [`NealCronin/Almost-ARCADIA`](https://github.com/NealCronin/Almost-ARCADIA)
  or at a local reference path. Operators should supply the local path if
  consulting legacy behavior.

## Requirements for the next session

- The package is installed in editable mode (`pip install -e ".[dev]"`).
- `arcadia.__version__` equals `"0.1.0"` and can be imported without side effects.
- The `tests/` directory structure is ready with `unit/`, `contract/`, and
  `integration/` directories.
- Tool configuration is ready: ruff (line-length 120), mypy (python 3.11),
  pytest (testpaths = `["tests"]`).
- The legacy implementation is available externally at
  [`NealCronin/Almost-ARCADIA`](https://github.com/NealCronin/Almost-ARCADIA).
  A local reference path may be supplied by the operator.
