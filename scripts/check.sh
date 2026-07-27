#!/usr/bin/env bash
# ARCADIA local validation script (POSIX shell).
# Runs the same checks as CI: format, lint, type-check, test, and build.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
