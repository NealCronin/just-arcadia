# Local Agent Prompt: Implement ARCADIA Session 0 Scaffold

You are preparing the repository for a clean headless rewrite of Almost ARCADIA.

## Goal

Create the project scaffold, development tooling, CI, and minimal installable `arcadia` package. Do not implement any inference, service lifecycle, transport, pipeline, storage, or UI functionality.

The architecture documents supplied with this prompt are authoritative:

- `docs/architecture.md`
- `docs/contracts.md`
- `docs/legacy-inventory.md`
- `docs/decisions/*.md`
- `docs/sessions/session-template.md`
- `docs/handoffs/README.md`

Read them before changing the repository.

## Repository strategy

1. Preserve the current Almost ARCADIA 0.6.12 state in Git before replacing the branch contents.
2. When possible, create an annotated tag named:

```text
legacy-ui-0.6.12
```

3. Create or work on a branch named:

```text
headless-core
```

4. If the tag or branch already exists, do not overwrite it destructively. Verify its target and document what you found.
5. Keep legacy source available through Git history or the tag. Do not place legacy `core`, `web`, `project`, or `manage.py` packages inside the new import path.

## Required project structure

Create or retain this structure:

```text
.github/workflows/ci.yml
docs/architecture.md
docs/contracts.md
docs/legacy-inventory.md
docs/decisions/*.md
docs/sessions/session-template.md
docs/handoffs/README.md
examples/README.md
scripts/check.sh
scripts/check.ps1
src/arcadia/__init__.py
src/arcadia/py.typed
tests/unit/
tests/contract/
tests/integration/
tests/test_package.py
.gitignore
README.md
pyproject.toml
```

Do not create empty future implementation packages such as `arcadia.services`, `arcadia.analysis`, or `arcadia.tools`. Their owning sessions will create them.

## Package identity

Use:

- distribution name: `arcadia-core`
- import package: `arcadia`
- initial version: `0.1.0`
- Python requirement: `>=3.11`
- build backend: `setuptools>=69`
- `src/` package layout

Expose `arcadia.__version__` without importing `importlib.metadata` on every call if a simple constant is sufficient for this prototype.

Include `py.typed` as package data.

## Base dependencies

Keep the base package light. Session 0 does not need a runtime dependency unless the scaffold genuinely uses it.

Define optional dependency groups for future use without forcing heavy installs. Reasonable groups are:

```text
node
llama
sam
priority-map
dev
```

Do not install or import Django, OpenCV, Torch, Ultralytics, llama-cpp-python, FastAPI, or Uvicorn as part of a plain base installation.

The `dev` group must include at least:

- pytest
- pytest-cov
- ruff
- mypy
- build

Use sensible compatible ranges rather than exact pins unless a lock tool records exact development versions.

## Development environment

Prefer `uv` for the checked-in development workflow when it is available, but ordinary pip installation must remain supported:

```bash
python -m pip install -e ".[dev]"
```

Do not make `uv` a runtime requirement.

A lockfile may be committed if generated successfully in the current environment. Do not fail Session 0 solely because a lockfile cannot be generated without network access.

## Tool configuration

Configure:

- Ruff formatting and linting
- Mypy for Python 3.11
- Pytest with `tests` as the test path
- package discovery under `src`
- package data for `py.typed`

Use a line length of 120 unless the existing repository has a strong reason to use another value.

Do not configure Django settings in Pytest.

## Required tests

Create tests proving:

1. `import arcadia` succeeds after installation.
2. `arcadia.__version__` equals `0.1.0`.
3. Importing `arcadia` does not import heavy modules.

At minimum, verify these names are absent from `sys.modules` after a clean import:

```text
django
fastapi
uvicorn
cv2
torch
ultralytics
llama_cpp
```

Use a subprocess for the heavy-import test if necessary to guarantee a clean interpreter.

4. The built wheel can be installed and imported in a clean temporary environment when feasible.

The wheel-install smoke test may be implemented in CI or a script rather than as an ordinary unit test if that is cleaner.

## Local validation scripts

Create:

```text
scripts/check.sh
scripts/check.ps1
```

They should perform equivalent checks:

```text
ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
```

Make the shell script executable.

## CI

Create GitHub Actions CI that runs the core checks.

Minimum matrix:

- Ubuntu: Python 3.11 and 3.12
- Windows: Python 3.11
- macOS: Python 3.11

All jobs should install the package and development dependencies before testing.

At least one job must:

1. build a wheel;
2. create a clean virtual environment;
3. install only the wheel;
4. run `python -c "import arcadia; print(arcadia.__version__)"`.

Do not attempt CUDA, Metal, llama.cpp, SAM, or Priority Map validation in hosted CI during Session 0.

## Root README

Write a concise README that explains:

- ARCADIA is being rebuilt as a headless research orchestration package;
- the current branch contains scaffold and architecture only;
- the legacy implementation is available externally at `NealCronin/Almost-ARCADIA`, not stored in this repository;
- how to create a development environment;
- how to run checks;
- where architecture and session documents live.

Do not advertise unimplemented model-hosting or pipeline functionality as working.

## Examples README

Create `examples/README.md` explaining that runnable examples will be added after the public APIs exist. Do not add fake example code for modules that have not been implemented.

## Gitignore

Cover standard Python, virtual environment, test, build, editor, OS, model-cache, run-output, and local-secret artifacts without ignoring source documentation.

Do not delete user datasets or model files from the working tree as part of cleanup. Only adjust ignore rules.

## Prohibited work

Do not:

- implement domain models;
- migrate `core/config.py`;
- add FastAPI routes;
- add Django;
- launch or download models;
- integrate llama-cpp-python;
- implement SAM;
- implement Priority Map;
- implement the service manager;
- create a CLI command beyond packaging placeholders;
- add authentication or TLS;
- spend time on licensing or copyright;
- copy the entire legacy test suite;
- perform unrelated refactors.

## Required handoff

Create:

```text
docs/handoffs/session-00-scaffold.md
```

Follow `docs/handoffs/README.md`.

Include:

- whether the legacy tag and branch were created;
- exact Python and tool versions used;
- files created or removed;
- commands run;
- all validation results;
- any task that could not be completed because of environment or network limitations;
- the exact clean public starting point available to Session 1.

## Definition of done

Session 0 is complete only when:

- the new source tree has no Django application code;
- the supplied architecture documents are present;
- `pip install -e ".[dev]"` succeeds in the available environment;
- `import arcadia` succeeds;
- heavy packages are not imported by the base package;
- Ruff, Mypy, Pytest, and package build pass;
- CI configuration is present;
- local check scripts are present;
- the Session 0 handoff is complete;
- no actual inference or orchestration functionality has been added.

If a validation step cannot run because the environment lacks network access or a platform, do not fabricate success. Complete all possible work, record the limitation, and leave exact commands for the operator.
