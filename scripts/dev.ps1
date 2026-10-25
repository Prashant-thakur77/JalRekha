$ErrorActionPreference = "Stop"

Write-Host "Starting Dev Servers..."
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$BackendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$PowerShellExe = (Get-Command powershell.exe).Source
$CmdExe = (Get-Command cmd.exe).Source
$backendCommand = "Set-Location '$BackendDir'; & '$BackendPython' -m uvicorn jalrekha.main:app --reload --port 8000"
$frontendCommand = "cd /d `"$FrontendDir`" && npm.cmd run dev -- --host 127.0.0.1 --port 5173"

$backendProcess = Start-Process -FilePath $PowerShellExe `
    -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCommand `
    -PassThru
$frontendProcess = Start-Process -FilePath $CmdExe `
    -ArgumentList "/k", $frontendCommand `
    -PassThru

Write-Host "Backend API at http://localhost:8000"
Write-Host "Frontend App at http://localhost:5173"
Write-Host "Backend PID: $($backendProcess.Id)"
Write-Host "Frontend PID: $($frontendProcess.Id)"
