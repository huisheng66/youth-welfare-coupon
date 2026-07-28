# External web/API security scan using Nuclei (+ optional built-in audits).
# Usage:
#   .\scripts\external_scan.ps1
#   .\scripts\external_scan.ps1 -Target http://127.0.0.1:19001 -SkipBuiltin
# Requires: nuclei in PATH or %USERPROFILE%\go\bin\nuclei.exe
param(
  [string]$Target = "http://127.0.0.1:19001",
  [switch]$SkipBuiltin,
  [switch]$SkipNuclei
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "reports"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "==> Target: $Target"
Write-Host "==> Reports: $Out"

# --- Built-in business audits ---
if (-not $SkipBuiltin) {
  $py = Join-Path $Root "backend\.venv\Scripts\python.exe"
  if (-not (Test-Path $py)) { $py = "python" }
  Write-Host ""
  Write-Host "==> security_audit.py"
  Push-Location (Join-Path $Root "backend")
  try {
    & $py scripts\security_audit.py 2>&1 | Tee-Object (Join-Path $Out "security_audit_$Stamp.log")
    & $py scripts\security_audit_extra.py 2>&1 | Tee-Object (Join-Path $Out "security_audit_extra_$Stamp.log")
  } finally {
    Pop-Location
  }
}

# --- Nuclei ---
if (-not $SkipNuclei) {
  $nuclei = $null
  foreach ($c in @(
      (Join-Path $env:USERPROFILE "go\bin\nuclei.exe"),
      (Join-Path $env:GOPATH "bin\nuclei.exe"),
      "nuclei.exe",
      "nuclei"
    )) {
    if ($c -and (Get-Command $c -ErrorAction SilentlyContinue)) {
      $nuclei = (Get-Command $c).Source
      break
    }
    if ($c -and (Test-Path $c)) {
      $nuclei = $c
      break
    }
  }
  if (-not $nuclei) {
    Write-Host "nuclei not found. Install: go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest" -ForegroundColor Yellow
    exit 2
  }
  Write-Host ""
  Write-Host "==> Nuclei: $nuclei"
  & $nuclei -update-templates 2>&1 | Out-Null

  $jsonl = Join-Path $Out "nuclei_$Stamp.jsonl"
  Write-Host "Scanning $Target (tags: exposure,misconfig,config,tech,token,jwt,cors,header,xss,sqli,cve)..."
  Write-Host "Tip: if many false 'missing headers' appear, set GLOBAL_IP_MAX_REQUESTS=0 and restart API (rate-limit 429)."

  & $nuclei -u $Target `
    -tags "exposure,misconfig,config,tech,token,jwt,cors,header,xss,sqli,cve" `
    -severity info `
    -rate-limit 30 `
    -c 10 `
    -timeout 8 `
    -retries 1 `
    -ni `
    -jsonl-export $jsonl `
    -silent

  if (Test-Path $jsonl) {
    $n = (Get-Content $jsonl | Measure-Object -Line).Lines
    Write-Host "Nuclei findings lines: $n -> $jsonl"
    # Summarize template-ids
    Get-Content $jsonl | ForEach-Object {
      try {
        $j = $_ | ConvertFrom-Json
        $id = $j.'template-id'
        $name = $j.'matcher-name'
        if ($name) { "$id : $name" } else { $id }
      } catch { }
    } | Group-Object | Sort-Object Count -Descending | ForEach-Object {
      "  $($_.Count)x $($_.Name)"
    }
  }
}

Write-Host ""
Write-Host "Done. See docs/security-tools.md for more GitHub scanners."
Write-Host "ZAP: .\scripts\zap-baseline.ps1 -Target $Target  (needs Docker)"
