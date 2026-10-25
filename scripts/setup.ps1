$ErrorActionPreference = "Stop"

Write-Host "Setting up JalRekha MVP..."
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$BackendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$env:UV_CACHE_DIR = Join-Path $BackendDir ".uv-cache"

Write-Host "[1] Setting up backend..."
Push-Location $BackendDir
if (!(Test-Path ".venv")) {
    uv venv
    uv pip install -e .[dev]
} else {
    Write-Host "Backend virtualenv already exists. Ensuring project is installed in editable mode."
    uv pip install -e .[dev]
}
Pop-Location

Write-Host "[2] Setting up frontend..."
Push-Location $FrontendDir
npm install --legacy-peer-deps
Pop-Location

Write-Host "[3] Fetching demo media assets..."
& $BackendPython (Join-Path $RepoRoot "scripts\fetch_demo_assets.py")

Write-Host "[4] Seeding data..."
& $BackendPython -m jalrekha.scripts.seed

Write-Host "Setup complete."
