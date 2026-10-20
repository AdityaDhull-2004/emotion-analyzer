# Optional internet link (spec section 12): a Cloudflare quick tunnel to the local server.
#
#   powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1
#
# Start scripts\serve.ps1 first. cloudflared gives a random https://....trycloudflare.com
# address that works from anywhere (for example a phone on mobile data) for as long as this
# runs; anyone with the address can use the app. The address is also written to
# logs\tunnel_url.txt. Stop it with Ctrl+C.

$ErrorActionPreference = "Continue"  # native stderr is not an error; failures are checked explicitly
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = 8443

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    throw "cloudflared isn't installed or isn't on PATH."
}
curl.exe --silent --fail --cacert certs/cert.pem --ssl-no-revoke "https://localhost:$Port/api/health" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The server isn't answering on https://localhost:$Port. Start scripts\serve.ps1 first." }

New-Item -ItemType Directory -Force logs | Out-Null
$UrlFile = Join-Path $Root "logs\tunnel_url.txt"
if (Test-Path $UrlFile) { Remove-Item $UrlFile }

# cloudflared logs to stderr, so its lines arrive here as error records.
cloudflared tunnel --url "https://localhost:$Port" --no-tls-verify 2>&1 | ForEach-Object {
    $line = "$_"
    if ($line -match "https://[-a-z0-9]+\.trycloudflare\.com") {
        Set-Content -Path $UrlFile -Value $Matches[0] -Encoding ascii
        Write-Host ""
        Write-Host "Internet link: $($Matches[0])" -ForegroundColor Green
        Write-Host ""
    }
    $line
}
