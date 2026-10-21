# Puts ShelfReady online from this PC: the API runs here, a Cloudflare quick tunnel gives it a public
# https address, and the web app on Vercel is rebuilt to call that address.
#
#   powershell -ExecutionPolicy Bypass -File deploy\go_live.ps1          # start once
#   powershell -ExecutionPolicy Bypass -File deploy\go_live.ps1 -Watch   # start and keep it up
#
# -Watch keeps this window open and, every 30 s, checks the API and the public tunnel: a stopped API is
# restarted, a dead tunnel is replaced and the web app redeployed with its new address (a quick tunnel
# gets a new address each time, and it does not survive the network dropping, e.g. when the PC sleeps).
# While it runs it also asks Windows not to sleep (closing the lid can still sleep, depending on settings).
# Run it in your own terminal, not from an editor task, so closing the editor does not stop it. Ctrl+C stops it.
#
# Needs: cloudflared, the Vercel CLI logged in, and frontend/ linked to the Vercel project.

param([switch]$Watch)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$site = "https://shelfready-check.vercel.app"
$origins = "http://localhost:3000,$site,https://shelfready-iota.vercel.app,https://shelfready-praharj123barman-3726s-projects.vercel.app"
$log = Join-Path $env:TEMP "shelfready_tunnel.log"
$localHealth = "http://127.0.0.1:8000/api/health"

function Test-Url([string]$url) {
  try { Invoke-RestMethod $url -TimeoutSec 15 | Out-Null; return $true } catch { return $false }
}

function Start-Api {
  Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  Write-Host "Starting the API (minimized window 'ShelfReady API')..."
  $api = "`$Host.UI.RawUI.WindowTitle='ShelfReady API'; `$env:CORS_ORIGINS='$origins'; " +
         "Set-Location '$root\backend'; ..\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $api -WindowStyle Minimized
  for ($i = 0; $i -lt 60; $i++) { if (Test-Url $localHealth) { return } Start-Sleep -Seconds 1 }
  throw "The API did not start. Look at the 'ShelfReady API' window."
}

function Start-Tunnel {
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
  Remove-Item $log -ErrorAction SilentlyContinue
  Write-Host "Starting the tunnel..."
  Start-Process cloudflared -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8000", "--logfile", $log -WindowStyle Minimized
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
      $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
      if ($m) { Write-Host "Tunnel: $($m.Matches[0].Value)"; return $m.Matches[0].Value }
    }
  }
  throw "The tunnel did not start. See $log"
}

function Publish-Frontend([string]$apiUrl) {
  Write-Host "Rebuilding the web app on Vercel (about 1 minute)..."
  vercel deploy --prod --yes --cwd "$root\frontend" --build-env "NEXT_PUBLIC_API_URL=$apiUrl" | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-Host "The Vercel deploy failed (exit $LASTEXITCODE): run it again." -ForegroundColor Red; return }
  Write-Host "Live: $site" -ForegroundColor Green
}

function Wait-PublicUrl([string]$url) {
  # a new quick tunnel can take a few seconds before its address answers
  for ($i = 0; $i -lt 30; $i++) { if (Test-Url "$url/api/health") { return $true } Start-Sleep -Seconds 2 }
  return $false
}

Write-Host "Stopping an old API or tunnel, if any..."
Start-Api
$url = Start-Tunnel
Publish-Frontend $url
if (-not $Watch) {
  Write-Host "Keep this PC on and awake, with the two minimized windows open."
  Write-Host "To keep it up automatically, run this script with -Watch instead."
  return
}

# ---------------- watch ----------------
Add-Type -Namespace ShelfReady -Name Power -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
'@
[ShelfReady.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
Write-Host "Watching (every 30 s). This PC will not go to sleep on its own while this window is open. Ctrl+C stops."
[void](Wait-PublicUrl $url)
$tunnelFailures = 0
try {
  while ($true) {
    Start-Sleep -Seconds 30
    $stamp = Get-Date -Format "HH:mm:ss"
    if (-not (Test-Url $localHealth)) {
      Write-Host "$stamp API not answering: restarting it." -ForegroundColor Yellow
      Start-Api
    }
    $alive = (Get-Process cloudflared -ErrorAction SilentlyContinue) -and (Test-Url "$url/api/health")
    $tunnelFailures = if ($alive) { 0 } else { $tunnelFailures + 1 }
    if ($tunnelFailures -ge 2) {  # two checks in a row (a minute), so one slow request does not trigger it
      Write-Host "$stamp Tunnel down: starting a new one and redeploying the web app." -ForegroundColor Yellow
      $url = Start-Tunnel
      [void](Wait-PublicUrl $url)
      Publish-Frontend $url
      $tunnelFailures = 0
    }
  }
} finally {
  [ShelfReady.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null  # sleep allowed again
}
