# OWASP ZAP baseline via Docker.
# Usage: .\scripts\zap-baseline.ps1 -Target https://staging.example.com
param(
  [Parameter(Mandatory = $true)]
  [string]$Target
)

$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "reports"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Report = "zap-baseline-$Stamp.html"

Write-Host "ZAP baseline -> $Target"
Write-Host "Report: reports/$Report"

docker run --rm `
  -v "${Out}:/zap/wrk/:rw" `
  -t ghcr.io/zaproxy/zaproxy:stable `
  zap-baseline.py -t $Target -r $Report -I

Write-Host "Done. Archive reports/$Report with commit hash and triage notes."
Write-Host "See docs/security-ops.md section 7e"
