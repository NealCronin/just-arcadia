<#
.SYNOPSIS
    ARCADIA local validation script (PowerShell).

.DESCRIPTION
    Runs the same checks as CI: format, lint, type-check, test, and build.
#>
$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    & $Command

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Invoke-Checked { ruff format --check . }
Invoke-Checked { ruff check . }
Invoke-Checked { mypy src/arcadia }
Invoke-Checked { pytest }
Invoke-Checked { python -m build }
