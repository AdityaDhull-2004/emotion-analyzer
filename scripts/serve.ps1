# One-click start of the production server (spec section 12).
#
#   powershell -ExecutionPolicy Bypass -File scripts\serve.ps1
#
# Activates the virtual environment, checks the models are present, makes or renews the
# self-signed certificate when the LAN IP has changed, prints the LAN and localhost URLs and
# starts uvicorn on port 8443 over HTTPS with one worker. Stop it with Ctrl+C.

# Native programs (python, uvicorn) log to stderr, which Windows PowerShell 5.1 turns into
# errors when output is redirected, so failures are checked explicitly instead.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = 8443

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    throw "No virtual environment in .venv. Build it first (README, Install)."
}
. .venv\Scripts\Activate.ps1

$missing = python -c "from emotion_analyzer.fusion import missing_models; print('\n'.join(missing_models()))"
if ($LASTEXITCODE -ne 0) { throw "Couldn't import the project. Is the virtual environment complete?" }
if ($missing) {
    Write-Host "Missing models:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  $_" }
    throw "Copy the models into models\ first (KAGGLE.md, Phase 6)."
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Is the server already running?"
}

python scripts\make_cert.py --if-needed
if ($LASTEXITCODE -ne 0) { throw "Couldn't make the certificate." }
$LanIp = python scripts\make_cert.py --print-ip

Write-Host ""
Write-Host "Emotion Analyzer" -ForegroundColor Cyan
if ($LanIp) {
    Write-Host "  On this Wi-Fi:  https://${LanIp}:$Port   (accept the certificate warning once on each phone)"
    $netProfile = Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { (Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress -contains $LanIp }
    if ($netProfile -and $netProfile.NetworkCategory -ne "Private") {
        Write-Host "  Windows treats '$($netProfile.Name)' as $($netProfile.NetworkCategory): the firewall rule for port $Port applies to Private networks only (README)." -ForegroundColor Yellow
    }
} else {
    Write-Host "  No network: only this laptop can reach the app." -ForegroundColor Yellow
}
Write-Host "  On this laptop: https://localhost:$Port"
Write-Host "  Internet link:  run scripts\tunnel.ps1 in a second window once the server is up."
Write-Host ""

python -m uvicorn app.main:app --host 0.0.0.0 --port $Port --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem --workers 1
