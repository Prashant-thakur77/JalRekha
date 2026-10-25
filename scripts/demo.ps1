$ErrorActionPreference = "Stop"

Write-Host "Running Demo Script..."
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendPython = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"

& $BackendPython (Join-Path $RepoRoot "scripts\demo.py")
