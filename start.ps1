# One-click local start for welfare coupon system
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendPort = 19001
$FrontendPort = 5173

Write-Host "==> Backend port: $BackendPort"
Write-Host "==> Frontend port: $FrontendPort"

# Ensure backend venv
if (-not (Test-Path "$Root\backend\.venv\Scripts\python.exe")) {
  Write-Host "Creating Python venv..."
  Push-Location "$Root\backend"
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  Pop-Location
}

# Patch frontend proxy target
$vite = Get-Content "$Root\frontend\vite.config.js" -Raw
$vite = $vite -replace "target:\s*'http://127\.0\.0\.1:\d+'", "target: 'http://127.0.0.1:$BackendPort'"
Set-Content -Path "$Root\frontend\vite.config.js" -Value $vite -Encoding UTF8

if (-not (Test-Path "$Root\frontend\node_modules")) {
  Write-Host "Installing frontend deps..."
  Push-Location "$Root\frontend"
  npm install
  Pop-Location
}

Write-Host "Starting backend..."
Start-Process -FilePath "$Root\backend\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$BackendPort" -WorkingDirectory "$Root\backend" -WindowStyle Minimized

Start-Sleep -Seconds 2

Write-Host "Starting frontend..."
Start-Process -FilePath "npm" -ArgumentList "run","dev","--","--host","127.0.0.1","--port","$FrontendPort" -WorkingDirectory "$Root\frontend" -WindowStyle Minimized

Write-Host ""
Write-Host "Opened:"
Write-Host "  Web:  http://127.0.0.1:$FrontendPort/"
Write-Host "  API:  http://127.0.0.1:$BackendPort/docs"
Write-Host "  Demo: admin/admin123  merchant1/merchant123  youth1/youth123"
