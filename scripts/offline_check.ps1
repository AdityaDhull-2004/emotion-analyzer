# Offline check (spec sections 10.4c and 12, AC-17).
#
#   powershell -ExecutionPolicy Bypass -File scripts\offline_check.ps1
#
# Run it with Wi-Fi switched off and the server stopped. It sets HF_HUB_OFFLINE=1, starts the
# server on https://localhost:8443, analyses the committed text-to-speech fixture
# tests\fixtures\speech_short.wav, writes results\offline_check.txt and stops the server. The
# result records whether the network really was off.

param([string]$OutFile = "results\offline_check.txt")

$ErrorActionPreference = "Continue"  # native stderr is not an error; failures are checked explicitly
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = 8443
$Base = "https://localhost:$Port"
$Tls = @("--cacert", "certs/cert.pem", "--ssl-no-revoke")
$env:HF_HUB_OFFLINE = "1"

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is in use: stop the running server (Ctrl+C in its window) and run this again."
}
if (-not (Test-Path "certs\cert.pem")) { throw "No certificate: run scripts\serve.ps1 once first." }

# Ping can't tell: networks often block it. The internet counts as reachable if either HTTPS
# request gets any answer (Hugging Face is what HF_HUB_OFFLINE keeps the app from contacting).
$adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object Status -eq "Up" | ForEach-Object Name)
$internet = $false
foreach ($site in @("https://huggingface.co", "https://1.1.1.1")) {
    curl.exe --silent --head --max-time 8 --ssl-no-revoke --output NUL $site
    if ($LASTEXITCODE -eq 0) { $internet = $true }
}

# A committed fixture, never one of the user's recordings (spec section 12, v1.6).
$clip = "tests\fixtures\speech_short.wav"
if (-not (Test-Path $clip)) { throw "The fixture $clip is missing." }
$clipNote = "tests\fixtures\speech_short.wav (committed text-to-speech fixture)"

New-Item -ItemType Directory -Force logs | Out-Null
$started = Get-Date
$server = Start-Process -FilePath ".venv\Scripts\python.exe" -PassThru -WindowStyle Hidden `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port",
                  "--ssl-keyfile", "certs/key.pem", "--ssl-certfile", "certs/cert.pem", "--workers", "1" `
    -RedirectStandardOutput "logs\offline_server.out.txt" -RedirectStandardError "logs\offline_server.err.txt"

$health = $null
try {
    for ($i = 0; $i -lt 120 -and -not $health; $i++) {
        Start-Sleep -Seconds 1
        if ($server.HasExited) { break }
        $out = curl.exe --silent --fail --max-time 5 @Tls "$Base/api/health"
        if ($LASTEXITCODE -eq 0) { $health = $out | ConvertFrom-Json }
    }
    $startSeconds = ((Get-Date) - $started).TotalSeconds
    $answer = $null
    if ($health) {
        $body = curl.exe --silent --show-error --fail --max-time 120 @Tls -F "audio=@$clip" "$Base/api/analyze"
        if ($LASTEXITCODE -eq 0) { $answer = $body | ConvertFrom-Json }
    }
} finally {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}

$offline = -not $internet
$analysed = $answer -and $answer.speech_detected -and $answer.overall
if ($offline -and $analysed) { $verdict = "PASS: the server started and analysed a clip with the network off (AC-17)" }
elseif ($analysed) { $verdict = "NOT VALID: the analysis worked, but the internet was reachable, so this wasn't offline" }
else { $verdict = "FAIL: see logs\offline_server.err.txt" }

$lines = @(
    "Offline check (spec 10.4c, AC-17)",
    "date: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))",
    "HF_HUB_OFFLINE: $env:HF_HUB_OFFLINE",
    "network adapters up: $(if ($adapters.Count) { $adapters -join ', ' } else { 'none' })",
    "internet reachable (HTTPS to huggingface.co or 1.1.1.1): $(if ($internet) { 'yes' } else { 'no' })",
    "server: $(if ($health) { 'started, models loaded: ' + $health.models_loaded } else { 'did not start' }) after $([math]::Round($startSeconds, 1)) s on $Base",
    "clip: $clipNote"
)
if ($analysed) {
    $lines += "answer: $($answer.overall.label) ($([math]::Round(100 * $answer.overall.confidence))%), $($answer.segments.Count) segment(s), processed in $($answer.timing_ms.total) ms"
} elseif ($answer) {
    $lines += "answer: no speech detected"
}
$lines += "result: $verdict"
Set-Content -Path $OutFile -Value $lines -Encoding utf8
$lines | ForEach-Object { Write-Host $_ }
