# Emotion Analyzer

Recognises a speaker's emotion from a short voice recording by combining how it sounds and what is said. It runs offline on a laptop CPU in about one second.

> Work in progress. This README becomes the full user guide (install, run, train, deploy, citations) in Phase 10. The design lives in `specs.md`.

## Install (local, Windows)

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
git config core.hooksPath .githooks
```

## Run the tests

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
.venv\Scripts\python.exe -m pytest -m "not slow"
```

## Running in production

The app runs on this laptop. Phones on the same Wi-Fi reach it over HTTPS, and an optional Cloudflare tunnel gives an internet address (spec §12).

### One-time setup (administrator)

Windows lets other devices in only through a firewall rule, and this rule applies to Private networks. Open PowerShell **as administrator** and run:

Working directory: any

```
New-NetFirewallRule -DisplayName "Emotion Analyzer (TCP 8443)" -Direction Inbound -Protocol TCP -LocalPort 8443 -Profile Private -RemoteAddress LocalSubnet -Action Allow
```

Then set the Wi-Fi to Private, either in Settings (Network & internet → Wi-Fi → the network's properties → Private network) or in the same administrator PowerShell:

Working directory: any

```
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```

Private also turns on Windows' other Private-network rules, such as network discovery, on that network. On a network you don't trust, use the hotspot below instead.

### Start the server

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
powershell -ExecutionPolicy Bypass -File scripts\serve.ps1
```

It checks the models, makes or renews the self-signed certificate, prints the addresses and starts the server on port 8443. On the phone:

1. Open the `https://<LAN IP>:8443` address it prints.
2. Accept the certificate warning once. In Chrome, tap Advanced, then Proceed. In Safari, tap Show Details, then visit this website.
3. Upload and recording both work after that.

The certificate covers the laptop's current address. When the address changes (for example on a hotspot), `serve.ps1` makes a new one, and phones accept it once more. Stop the server with Ctrl+C.

### Check it

With the server running, this calls `/api/health` and `/api/analyze` through the real LAN address, checks the certificate, and checks that no audio file can be fetched:

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
```

### Internet link (optional)

In a second window, with the server running:

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1
```

It prints a random `https://….trycloudflare.com` address, also saved in `logs\tunnel_url.txt`, that works from anywhere (for example a phone on mobile data) while it runs. Anyone with the address can use the app, so stop it with Ctrl+C when you're done. The app serves no audio files, so nobody can play your recordings through it. To check it:

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1 -Url https://<the address>.trycloudflare.com
```

### If the phone can't connect: the hotspot fallback

Campus Wi-Fi often blocks traffic between devices (client isolation). Then:

1. Turn on a phone's hotspot and connect the laptop and the phone to it.
2. Windows usually marks a new network as Public: set it to Private as above (`-InterfaceAlias "Wi-Fi"` still applies).
3. Restart `serve.ps1`. It makes a certificate for the new address and prints the new URL.

Alternatively use the internet link, which doesn't need the phone and the laptop on the same network.

If Windows once showed a firewall prompt for Python and it was cancelled, there may be a rule that blocks Python, and block rules beat the allow rule. List them in an administrator PowerShell, and delete any it shows under Windows Defender Firewall → Advanced settings → Inbound Rules:

Working directory: any

```
Get-NetFirewallRule -Action Block -Enabled True | Where-Object DisplayName -like "*python*"
```

### Access log

Every request is one JSON line in `logs\server.log` (git-ignored): time, client IP, user agent, endpoint, status and processing time, plus `cf_ip` for requests through the tunnel.

### Offline check

With Wi-Fi switched off and the server stopped, this starts the server with `HF_HUB_OFFLINE=1`, analyses the committed fixture `tests\fixtures\speech_short.wav` on `https://localhost:8443`, writes `results\offline_check.txt` and stops the server:

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
powershell -ExecutionPolicy Bypass -File scripts\offline_check.ps1
```
