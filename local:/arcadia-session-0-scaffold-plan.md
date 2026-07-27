# Session 0: ARCADIA Headless Core Scaffold

## Context

Reimplement Almost ARCADIA as a headless Python package `arcadia` (distribution `arcadia-core`, version `0.1.0`) under `src/` layout. Session 0 creates the project scaffold, tooling, CI, and minimal installable package with zero domain logic. No inference, service lifecycle, transport, pipeline, storage, or UI functionality.

Authoritative documents (all present in `docs/`):
- `docs/architecture.md` — system behavior and boundaries
- `docs/contracts.md` — dependency rules (Section 4: base `import arcadia` must NOT import django, fastapi, uvicorn, cv2, torch, ultralytics, llama-cpp-python, or Priority Map)
- `docs/legacy-inventory.md` — legacy component map
- `docs/decisions/0001–0004` — ADRs
- `docs/sessions/session-template.md` — module session template
- `docs/handoffs/README.md` — handoff format

The `SESSION_0_LOCAL_AGENT_PROMPT.md` file contains the detailed implementation prompt (279 lines). It IS the spec for this work.

## Repository state

- Git: no commits yet, branch `main`, no tags, no `headless-core` branch
- Working tree: `.DS_Store`, `README.md`, `SESSION_0_LOCAL_AGENT_PROMPT.md`, `docs/`
- No `arcadia` package exists yet
- Need to: commit current state → tag `legacy-ui-0.6.12` → create `headless-core` branch

## Approach

### Step 1: Git baseline preservation

Since there are no commits, create an initial commit on `main`, then tag `legacy-ui-0.6.12` and create branch `headless-core` from it. The "legacy" here is just the docs/prompt pack since there is no legacy source code in this repo.

```bash
git add -A
git -c user.name='ARCADIA Session 0' -c user.email='session0@arcadia.local' commit -m "Preserve Session 0 documentation pack"
git tag -a legacy-ui-0.6.12 -m "ARCADIA Session 0 documentation and prompt pack"
git checkout -b headless-core
```

### Step 2: Create `pyproject.toml`

Distribution: `arcadia-core` v0.1.0, import package `arcadia`, Python >=3.11, setuptools>=69, src layout.

Key contents:
- `[build-system]` with `setuptools>=69` and `wheel`
- `[project]` with name="arcadia-core", version="0.1.0", requires-python=">=3.11"
- `[project.optional-dependencies]` groups: `node`, `llama`, `sam`, `priority-map`, `dev` (dev includes pytest, pytest-cov, ruff, mypy, build)
- `[tool.setuptools.packages.find]` where `src`
- `[tool.setuptools.package-data]` includes `py.typed`
- `[tool.ruff]` line-length=120
- `[tool.mypy]` python_version=3.11
- `[tool.pytest.ini_options]` testpaths=["tests"]

Use sensible compatible ranges (>=) not exact pins.

### Step 3: Create `src/arcadia/__init__.py`

```python
"""ARCADIA: headless research orchestration package."""

__version__ = "0.1.0"
```

Simple constant, no importlib.metadata import.

### Step 4: Create `src/arcadia/py.typed`

Empty marker file for PEP 561 type completeness.

### Step 5: Create test directories and tests

- `tests/unit/` — unit test directory (with `.gitkeep` or `__init__.py`)
- `tests/contract/` — contract test directory
- `tests/integration/` — integration test directory
- `tests/test_package.py` — the three required tests:

```python
"""Package import and version tests."""

import sys

# ... heavy module test via subprocess

def test_import_succeeds():
    import arcadia
    assert arcadia is not None

def test_version():
    assert arcadia.__version__ == "0.1.0"

def test_no_heavy_imports():
    # Run in subprocess to guarantee clean interpreter
    result = subprocess.run(
        [sys.executable, "-c", "import arcadia"],
        capture_output=True,
        timeout=30,
    )
    result.check_returncode()
    heavy_modules = [
        "django", "fastapi", "uvicorn", "cv2", "torch",
        "ultralytics", "llama_cpp",
    ]
    # Check sys.modules in the subprocess
```

The heavy-import test must run in a subprocess for a clean interpreter. The test code will check that none of the 7 heavy modules appear in `sys.modules` after `import arcadia`.

### Step 6: Create `.gitignore`

Cover: Python (`__pycache__`, `*.pyc`, `*.egg-info`, `dist/`, `build/`, `.venv/`, `.env`), test (`.pytest_cache`, `.coverage`, `htmlcov/`), build artifacts, editor configs (`.vscode/`, `.idea/`, `*.swp`), OS (`.DS_Store`), model caches (`models/`, `*.gguf`, `cache/`), run outputs, local secrets.

Do NOT ignore source docs or `py.typed`.

### Step 7: Create `README.md`

Concise root README explaining:
- ARCADIA is being rebuilt as headless research orchestration
- The branch contains scaffold and architecture only
- Legacy UI preserved in `legacy-ui-0.6.12` tag
- How to create development environment (`python -m pip install -e ".[dev]"`)
- How to run checks (`scripts/check.sh` or `scripts/check.ps1`)
- Where architecture/session docs live (`docs/`)

Do NOT advertise unimplemented functionality.

### Step 8: Create `examples/README.md`

Simple README stating runnable examples will be added after public APIs exist. No fake example code.

### Step 9: Create `scripts/check.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

Make executable with `chmod +x`.

### Step 10: Create `scripts/check.ps1`

PowerShell equivalent:
```powershell
$ErrorActionPreference = "Stop"
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

### Step 11: Create `.github/workflows/ci.yml`

GitHub Actions CI with matrix:
- Ubuntu: Python 3.11 and 3.12
- Windows: Python 3.11
- macOS: Python 3.11

Jobs:
1. Run core checks: install package + dev deps, run `scripts/check.*` equivalent
2. At least one job (Ubuntu 3.11) builds wheel, creates clean venv, installs only the wheel, runs `python -c "import arcadia; print(arcadia.__version__)"`

No CUDA, Metal, llama.cpp, SAM, or Priority Map in CI.

### Step 12: Create `docs/handoffs/session-00-scaffold.md`

Handoff following `docs/handoffs/README.md` format:
- Summary
- Files created or changed
- Public API (`arcadia.__version__`)
- State owned (none)
- External side effects (none)
- Events emitted (none)
- Errors raised (none)
- Concurrency and shutdown (none)
- Tests added (test_package.py)
- Validation performed (commands run + results)
- Architectural decisions (ADR references)
- Known limitations
- Assumptions
- Requirements for the next session

## Critical files & anchors

| File | Anchor | Reason |
|------|--------|--------|
| `SESSION_0_LOCAL_AGENT_PROMPT.md` | Full spec (lines 1–279) | Authoritative requirements |
| `docs/contracts.md` | Section 4, lines 66–83 | Heavy-import prohibition |
| `docs/handoffs/README.md` | Full format | Handoff document structure |
| `src/arcadia/__init__.py` | `__version__` | Package identity |
| `pyproject.toml` | `[project]` section | Distribution metadata |

## Verification

After all files created, run (in environment with uv/python available):

1. `python -m pip install -e ".[dev]"` — must succeed
2. `python -c "import arcadia; print(arcadia.__version__)"` — must print `0.1.0`
3. `python -c "import sys; import arcadia; print([m for m in ['django','fastapi','uvicorn','cv2','torch','ultralytics','llama_cpp'] if m in sys.modules])"` — must print `[]`
4. `pytest` — all tests pass
5. `ruff format --check .` — passes
6. `ruff check .` — passes
7. `mypy src/arcadia` — passes
8. `python -m build` — wheel builds successfully
9. Wheel install smoke test: build wheel, create temp venv, install only the wheel, `python -c "import arcadia; print(arcadia.__version__)"` — prints `0.1.0`

## Assumptions & contingencies

- **Git environment**: The environment has `git`, `python` (3.11+), and `uv` (optional) available. If `uv` is unavailable, pip workflow is used. If `uv` is available, it may be used but is not committed as a runtime dependency.
- **Lockfile**: If `uv lock` fails due to network restrictions, skip committing `uv.lock` and document the limitation. The prompt explicitly states: "Do not fail Session 0 solely because a lockfile cannot be generated without network access."
- **No network**: If `pip install` cannot download dev dependencies (pytest, ruff, mypy, build), record which tools could not be validated and leave the exact validation commands for the operator. All file structure will still be correct.
- **Tag/branch existence**: If `legacy-ui-0.6.12` tag or `headless-core` branch already exists (they don't currently), verify target and document without overwriting destructively.
- **Tool versions**: Using compatible ranges (e.g., `ruff>=0.1.0`, `pytest>=8.0.0`) rather than exact pins since no lockfile is guaranteed.
- **py.typed**: Included as package data so downstream type checking works. This is a simple empty file.
