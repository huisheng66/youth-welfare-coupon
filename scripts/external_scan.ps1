# External web/API security scan: built-in audits + custom Nuclei + ffuf + sqlmap.
# Usage:
#   .\scripts\external_scan.ps1
#   .\scripts\external_scan.ps1 -Target http://127.0.0.1:19001 -SkipBuiltin
# Requires (optional): nuclei / ffuf in %USERPROFILE%\go\bin ; tools/sqlmap clone
param(
  [string]$Target = "http://127.0.0.1:19001",
  [switch]$SkipBuiltin,
  [switch]$SkipNuclei,
  [switch]$SkipFfuf,
  [switch]$SkipSqlmap
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
  Write-Host "==> security_audit.py + extra + authz (deep IDOR)"
  Push-Location (Join-Path $Root "backend")
  try {
    & $py scripts\security_audit.py 2>&1 | Tee-Object (Join-Path $Out "security_audit_$Stamp.log")
    & $py scripts\security_audit_extra.py 2>&1 | Tee-Object (Join-Path $Out "security_audit_extra_$Stamp.log")
    & $py scripts\security_audit_authz.py 2>&1 | Tee-Object (Join-Path $Out "security_audit_authz_$Stamp.log")
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
    Write-Host "Nuclei community findings lines: $n -> $jsonl"
  }

  # Custom youth templates (expect 0 findings if auth/SQLi locked down)
  $customDir = Join-Path $Root "tools\nuclei-templates"
  $customOut = Join-Path $Out "nuclei_custom_$Stamp.jsonl"
  if (Test-Path $customDir) {
    Write-Host ""
    Write-Host "==> Nuclei custom templates: $customDir"
    Get-ChildItem $customDir -Filter "*.yaml" | ForEach-Object {
      & $nuclei -u $Target -t $_.FullName -severity info -rate-limit 20 -c 5 -timeout 8 -ni `
        -jsonl-export $customOut -silent 2>$null
    }
    $cn = 0
    if (Test-Path $customOut) { $cn = @(Get-Content $customOut).Count }
    Write-Host "Custom template findings: $cn (0 = protected routes + login SQLi OK)"
  }
}

# --- ffuf path discovery ---
if (-not $SkipFfuf) {
  $ffuf = $null
  foreach ($c in @(
      (Join-Path $env:USERPROFILE "go\bin\ffuf.exe"),
      "ffuf.exe",
      "ffuf"
    )) {
    if ($c -and (Get-Command $c -ErrorAction SilentlyContinue)) { $ffuf = (Get-Command $c).Source; break }
    if ($c -and (Test-Path $c)) { $ffuf = $c; break }
  }
  $wl = Join-Path $Root "tools\wordlists\api-paths.txt"
  if ($ffuf -and (Test-Path $wl)) {
    Write-Host ""
    Write-Host "==> ffuf path discovery"
    $csv = Join-Path $Out "ffuf_$Stamp.csv"
    & $ffuf -u "$Target/FUZZ" -w $wl -mc 200,401,403,405,422,429 -t 5 -rate 20 `
      -of csv -o $csv -noninteractive 2>$null
    if (Test-Path $csv) {
      Write-Host "ffuf report: $csv"
      Get-Content $csv | Select-Object -First 30
    }
  } else {
    Write-Host "ffuf skipped (install: go install github.com/ffuf/ffuf/v2@latest)" -ForegroundColor Yellow
  }
}

# --- sqlmap light on login JSON ---
if (-not $SkipSqlmap) {
  $sqlmap = Join-Path $Root "tools\sqlmap\sqlmap.py"
  if (Test-Path $sqlmap) {
    Write-Host ""
    Write-Host "==> sqlmap (login JSON, level=1 risk=1)"
    $log = Join-Path $Out "sqlmap_$Stamp.txt"
    Push-Location (Split-Path $sqlmap)
    try {
      python sqlmap.py -u "$Target/api/auth/login" --method=POST `
        --data='{"username":"admin*","password":"test*"}' `
        --headers="Content-Type: application/json" `
        --batch --level=1 --risk=1 --timeout=15 --retries=1 --flush-session `
        --ignore-code=400,422,429 --technique=BEUST -v 1 2>&1 |
        Tee-Object $log | Select-Object -Last 25
    } finally {
      Pop-Location
    }
    Write-Host "sqlmap log: $log"
  } else {
    Write-Host "sqlmap skipped (git clone https://github.com/sqlmapproject/sqlmap.git tools/sqlmap)" -ForegroundColor Yellow
  }
}

Write-Host ""
Write-Host "Done. See docs/security-tools.md for more GitHub scanners."
Write-Host "ZAP: .\scripts\zap-baseline.ps1 -Target $Target  (needs Docker)"
