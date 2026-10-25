$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src  = Join-Path $here "jalrekha-demo-artifacts"
$zip  = Join-Path $here "jalrekha-demo-artifacts.zip"

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $src "*") -DestinationPath $zip -CompressionLevel Optimal

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  jalrekha-demo-artifacts.zip" | Out-File -FilePath (Join-Path $here "SHA256SUMS.txt") -Encoding utf8

Write-Host "Built: $zip"
Write-Host "SHA256: $hash"
