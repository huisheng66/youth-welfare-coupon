# One-click local start (PC + phone on same Wi-Fi)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendPort = 19001
$FrontendPort = 5173

Write-Host "==> Backend port: $BackendPort (127.0.0.1, proxied by Vite)"
Write-Host "==> Frontend port: $FrontendPort (HTTPS + 0.0.0.0, LAN / camera)"

# Ensure backend venv
if (-not (Test-Path "$Root\backend\.venv\Scripts\python.exe")) {
  Write-Host "Creating Python venv..."
  Push-Location "$Root\backend"
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  Pop-Location
}

# Keep proxy target in vite.config.js pointing at backend
$vitePath = "$Root\frontend\vite.config.js"
if (Test-Path $vitePath) {
  $vite = Get-Content $vitePath -Raw
  $vite = $vite -replace "target:\s*'http://127\.0\.0\.1:\d+'", "target: 'http://127.0.0.1:$BackendPort'"
  Set-Content -Path $vitePath -Value $vite -Encoding UTF8
}

if (-not (Test-Path "$Root\frontend\node_modules")) {
  Write-Host "Installing frontend deps..."
  Push-Location "$Root\frontend"
  npm install
  Pop-Location
}

# Firewall: allow inbound 5173 for private networks (may need admin once)
try {
  $rule = Get-NetFirewallRule -DisplayName "YouthWelfare-Vite-5173" -ErrorAction SilentlyContinue
  if (-not $rule) {
    New-NetFirewallRule -DisplayName "YouthWelfare-Vite-5173" -Direction Inbound -Protocol TCP -LocalPort $FrontendPort -Action Allow -Profile Private -ErrorAction Stop | Out-Null
    Write-Host "Firewall rule added for port $FrontendPort (Private)"
  }
} catch {
  Write-Host "NOTE: Could not add firewall rule (run PowerShell as Admin if phone still cannot open page)"
}

# LAN IPv4 (prefer WLAN)
$lan = Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
  Sort-Object { if ($_.InterfaceAlias -match 'WLAN|Wi-?Fi|无线') { 0 } else { 1 } } |
  Select-Object -First 1 -ExpandProperty IPAddress

Write-Host "Starting backend..."
Start-Process -FilePath "$Root\backend\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$BackendPort" `
  -WorkingDirectory "$Root\backend" -WindowStyle Minimized

# Wait for health
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 1
    if ($r.StatusCode -eq 200) { $healthy = $true; break }
  } catch { }
  Start-Sleep -Milliseconds 500
}
if ($healthy) {
  Write-Host "Backend health OK"
} else {
  Write-Host "WARNING: Backend health not ready yet; frontend may retry via proxy"
}

Write-Host "Starting frontend (HTTPS + LAN, for phone camera)..."
Start-Process -FilePath "npm" `
  -ArgumentList "run","dev","--","--host","0.0.0.0","--port","$FrontendPort" `
  -WorkingDirectory "$Root\frontend" -WindowStyle Minimized

Write-Host ""
Write-Host "PC:    https://127.0.0.1:$FrontendPort/   (accept self-signed cert once)"
if ($lan) {
  Write-Host "Phone: https://${lan}:$FrontendPort/   (HTTPS required for camera)"
} else {
  Write-Host "Phone: https://<电脑WLAN-IP>:$FrontendPort/"
}
Write-Host "API:   http://127.0.0.1:$BackendPort/docs"
Write-Host "Demo:  admin/admin123  issuer/issuer123  merchant1|merchant2/merchant123  youth1|youth2/youth123"
Write-Host ""
Write-Host "Phone: same Wi-Fi; first open may warn about certificate -> Advanced -> Proceed"
Write-Host "If camera still blocked: use 拍照识别 / 相册选图"
