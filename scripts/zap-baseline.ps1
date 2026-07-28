# OWASP ZAP baseline via Docker Desktop.
# Usage:
#   # Scan local API (Docker must reach host):
#   .\scripts\zap-baseline.ps1 -Target http://host.docker.internal:19001
#   # Scan staging:
#   .\scripts\zap-baseline.ps1 -Target https://staging.example.com
#
# Prerequisites: Docker Desktop running (docker version works in this shell).
param(
  [Parameter(Mandatory = $false)]
  [string]$Target = "http://host.docker.internal:19001",

  [switch]$FailOnWarn  # drop -I so ZAP exit non-zero on warnings
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "reports"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Report = "zap-baseline-$Stamp.html"

function Resolve-Docker {
  $candidates = @(
    "docker",
    "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
    "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin\docker.exe"
  )
  foreach ($c in $candidates) {
    try {
      if ($c -eq "docker") {
        $null = & docker version 2>$null
        if ($LASTEXITCODE -eq 0) { return "docker" }
      } elseif (Test-Path $c) {
        $null = & $c version 2>$null
        if ($LASTEXITCODE -eq 0) { return $c }
      }
    } catch { }
  }
  return $null
}

$docker = Resolve-Docker
if (-not $docker) {
  Write-Host @"
Docker CLI not found or Docker engine is not running.

1. Install / start Docker Desktop (Windows).
2. Open a NEW terminal after install so PATH includes docker.exe.
3. Verify:  docker version
4. Ensure API is reachable from containers, e.g. API on 0.0.0.0:19001 or use:
     -Target http://host.docker.internal:19001
5. Re-run:  .\scripts\zap-baseline.ps1
"@ -ForegroundColor Yellow
  exit 2
}

Write-Host "Docker: $docker"
Write-Host "ZAP baseline -> $Target"
Write-Host "Report: reports/$Report"

# Docker Desktop on Windows: host.docker.internal resolves to host
# Mount reports dir for HTML output
$outWin = (Resolve-Path $Out).Path
# Convert to docker path style for -v (Docker Desktop accepts Windows paths)
$extra = @()
if (-not $FailOnWarn) { $extra += "-I" }

& $docker pull ghcr.io/zaproxy/zaproxy:stable
if ($LASTEXITCODE -ne 0) {
  Write-Host "Trying docker.io mirror name zaproxy/zap-stable..." -ForegroundColor Yellow
  & $docker pull zaproxy/zap-stable
  $image = "zaproxy/zap-stable"
} else {
  $image = "ghcr.io/zaproxy/zaproxy:stable"
}

$args = @(
  "run", "--rm",
  "-v", "${outWin}:/zap/wrk/:rw",
  "-t", $image,
  "zap-baseline.py",
  "-t", $Target,
  "-r", $Report
) + $extra

Write-Host "Running: docker $($args -join ' ')"
& $docker @args
$code = $LASTEXITCODE

Write-Host ""
Write-Host "ZAP exit code: $code  (with -I, warnings still exit 0)"
Write-Host "Open report: $Out\$Report"
if (-not (Test-Path (Join-Path $Out $Report))) {
  Write-Host "Report file missing — check Docker volume mount permissions." -ForegroundColor Yellow
}
exit $code
