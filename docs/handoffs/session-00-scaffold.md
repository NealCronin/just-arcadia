# Session 0 Handoff: Scaffold

## Summary

Created the headless ARCADIA core project scaffold, development tooling, CI configuration, and a minimal installable `arcadia` package (`arcadia-core` v0.1.0). No domain functionality (inference, service lifecycle, transport, pipeline, storage, or UI) is implemented.

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

### Version control
- Initial commit on `main` preserving the Session 0 documentation pack
- Annotated tag `legacy-ui-0.6.12`
- Branch `headless-core` created from the tag

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

All commands run on the `headless-core` branch. Environment: Python 3.13.12,
macOS 25.5.0 (arm64), setuptools-backed build.

```bash
# Install package and dev dependencies
python -m pip install -e ".[dev]"
# Result: Successfully installed arcadia-core-0.1.0

# Format check
ruff format --check .
# Result: 19 files already formatted — PASS

# Lint
ruff check .
# Result: OK (1 file left unchanged) — PASS

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

### Wheel install smoke test

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

## Known limitations

- The optional dependency groups `node`, `llama`, `sam`, and `priority-map` are
  empty placeholders; their contents will be defined when the owning sessions are
  implemented.
- No lockfile (`uv.lock` or similar) is committed. Generate one when network
  access allows: `uv lock` or `pip freeze > requirements.lock`.
- The wheel smoke test in CI installs to `--target` rather than a full venv to
  avoid platform-specific venv path issues in GitHub Actions.

## Assumptions

- Python 3.11+ is available in the development environment.
- `uv` is optional; `pip install -e ".[dev]"` is the canonical install path.
- No CUDA, Metal, llama.cpp, SAM, or Priority Map validation is performed in
  Session 0 CI. These will be validated in later sessions on self-hosted systems.
- The base package must never import heavy dependencies (django, fastapi,
  uvicorn, cv2, torch, ultralytics, llama-cpp-python). This invariant is
  enforced by `tests/test_package.py::test_no_heavy_imports`.

## Requirements for the next session

- The package is installed in editable mode (`pip install -e ".[dev]"`).
- `arcadia.__version__` equals `"0.1.0"` and can be imported without side effects.
- The `tests/` directory structure is ready with `unit/`, `contract/`, and
  `integration/` directories.
- Tool configuration is ready: ruff (line-length 120), mypy (python 3.11),
  pytest (testpaths = `["tests"]`).
- The `legacy-ui-0.6.12` Git tag preserves the Session 0 documentation pack for
  reference.
