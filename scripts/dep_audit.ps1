# Dependency audit: pip-audit (backend) + npm audit (frontend)
# Exit 1 if high/critical issues found.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
$Fail = 0

Write-Host "==> Backend pip-audit (requirements.txt)"
Set-Location (Join-Path $Root "backend")
$py = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
# Prefer already-installed pip-audit; try install with mirror fallback
& $py -m pip_audit --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing pip-audit..."
  & $py -m pip install -q "pip-audit>=2.7"
  if ($LASTEXITCODE -ne 0) {
    & $py -m pip install -q "pip-audit>=2.7" -i https://pypi.tuna.tsinghua.edu.cn/simple
  }
}
& $py -m pip_audit -r requirements.txt --progress-spinner off
if ($LASTEXITCODE -ne 0) {
  Write-Host "pip-audit reported issues (or tool missing)" -ForegroundColor Yellow
  $Fail = 1
}

Write-Host ""
Write-Host "==> Frontend npm audit (omit=dev, high+)"
Set-Location (Join-Path $Root "frontend")
if (-not (Test-Path "package-lock.json")) {
  Write-Host "package-lock.json missing; run npm install first" -ForegroundColor Red
  $Fail = 1
} else {
  npm audit --omit=dev --audit-level=high
  if ($LASTEXITCODE -ne 0) {
    Write-Host "npm audit reported high/critical issues" -ForegroundColor Yellow
    $Fail = 1
  }
}

Write-Host ""
if ($Fail -ne 0) {
  Write-Host "dep_audit: FAILED (see above)" -ForegroundColor Red
  exit 1
}
Write-Host "dep_audit: OK" -ForegroundColor Green
exit 0
