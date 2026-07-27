<#
.SYNOPSIS
    ARCADIA local validation script (PowerShell).

.DESCRIPTION
    Runs the same checks as CI: format, lint, type-check, test, and build.
#>
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

ruff format --check .
ruff check .
mypy src/arcadia
pytest
python -m build
