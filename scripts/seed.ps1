$ErrorActionPreference = "Stop"

Write-Host "Running Seeding Script..."
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$BackendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

& $BackendPython -m jalrekha.scripts.seed
Write-Host "Seeding Complete."
