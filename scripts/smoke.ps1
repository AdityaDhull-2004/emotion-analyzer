# Smoke check (spec section 12): /api/health and /api/analyze through the real LAN address, and
# a check that no audio file can be fetched from the server (section 5.3, v1.6).
#
#   powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1 -Url https://....trycloudflare.com
#
# With no -Url it uses https://<current LAN IP>:8443 and checks the server's certificate
# against certs\cert.pem, so it also proves the certificate covers the LAN IP. With -Url (for
# example the tunnel's address) it uses the normal certificate checks. The clip is the
# committed speech fixture tests\fixtures\speech_short.wav.

param([string]$Url = "")

$ErrorActionPreference = "Continue"  # native stderr is not an error; failures are checked explicitly
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($Url) {
    $Base = $Url.TrimEnd("/")
    $Tls = @("--ssl-no-revoke")
} else {
    $LanIp = & .venv\Scripts\python.exe scripts\make_cert.py --print-ip
    if (-not $LanIp) { throw "No LAN IP: is the laptop on a network?" }
    $Base = "https://${LanIp}:8443"
    $Tls = @("--cacert", "certs/cert.pem", "--ssl-no-revoke")
}
$Clip = "tests/fixtures/speech_short.wav"
Write-Host "Smoke check on $Base"

$health = curl.exe --silent --show-error --fail --max-time 30 @Tls "$Base/api/health"
if ($LASTEXITCODE -ne 0) { throw "GET /api/health failed (curl exit $LASTEXITCODE)." }
$h = $health | ConvertFrom-Json
if ($h.status -ne "ok" -or -not $h.models_loaded) { throw "Unhealthy: $health" }
Write-Host "  GET  /api/health   ok, models loaded, version $($h.version)"

$start = Get-Date
$body = curl.exe --silent --show-error --fail --max-time 120 @Tls -F "audio=@$Clip" "$Base/api/analyze"
if ($LASTEXITCODE -ne 0) { throw "POST /api/analyze failed (curl exit $LASTEXITCODE)." }
$seconds = ((Get-Date) - $start).TotalSeconds
$r = $body | ConvertFrom-Json
if (-not $r.speech_detected -or -not $r.overall) { throw "No speech detected in the speech fixture: $body" }
$label = $r.overall.label
$conf = [math]::Round(100 * $r.overall.confidence)
Write-Host ("  POST /api/analyze  ok, {0} ({1}%), {2} segment(s), server {3} ms, round trip {4:N2} s" -f $label, $conf, $r.segments.Count, $r.timing_ms.total, $seconds)
# The server serves no audio: the old demo-clip paths, data\own\ and the committed fixture,
# directly and through path tricks, must all fail without returning audio.
$probes = @("/static/samples/index.json", "/static/samples/anger_01.m4a", "/samples/anger_01.m4a",
            "/data/own/anger_01.m4a", "/static/../data/own/anger_01.m4a",
            "/static/%2e%2e/%2e%2e/data/own/anger_01.m4a", "/static/..%2f..%2ftests%2ffixtures%2fspeech_short.wav",
            "/tests/fixtures/speech_short.wav")
$codes = @()
foreach ($p in $probes) {
    $got = curl.exe --silent --path-as-is --output NUL --write-out "%{http_code} %{content_type}" --max-time 30 @Tls "$Base$p"
    $code, $type = "$got" -split " ", 2
    if ($code -match "^2" -or $type -like "audio/*") { throw "GET $p returned ${got}: the server must not serve audio." }
    $codes += $code
}
$summary = ($codes | Group-Object | ForEach-Object { "$($_.Count) x $($_.Name)" }) -join ", "
Write-Host "  no audio           $($probes.Count) paths tried (demo clips, data\own\, the fixture): $summary"
Write-Host "Smoke check passed." -ForegroundColor Green
