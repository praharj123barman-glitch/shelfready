# Puts ShelfReady online from this PC: the API runs here, a Cloudflare quick tunnel gives it a public
# https address, and the web app on Vercel is rebuilt to call that address.
# Run it again after a restart or sleep: the tunnel address changes each time it starts.
#
#   powershell -ExecutionPolicy Bypass -File deploy\go_live.ps1
#
# Needs: cloudflared, the Vercel CLI logged in, and frontend/ linked to the Vercel project.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$site = "https://shelfready-check.vercel.app"
$origins = "http://localhost:3000,$site,https://shelfready-iota.vercel.app,https://shelfready-praharj123barman-3726s-projects.vercel.app"
$log = Join-Path $env:TEMP "shelfready_tunnel.log"

Write-Host "Stopping an old API or tunnel, if any..."
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item $log -ErrorAction SilentlyContinue

Write-Host "Starting the API (minimized window 'ShelfReady API')..."
$api = "`$Host.UI.RawUI.WindowTitle='ShelfReady API'; `$env:CORS_ORIGINS='$origins'; " +
       "Set-Location '$root\backend'; ..\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $api -WindowStyle Minimized

Write-Host "Starting the tunnel..."
Start-Process cloudflared -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8000", "--logfile", $log -WindowStyle Minimized
$url = $null
for ($i = 0; $i -lt 60 -and -not $url; $i++) {
  Start-Sleep -Seconds 1
  if (Test-Path $log) {
    $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Value }
  }
}
if (-not $url) { throw "The tunnel did not start. See $log" }
Write-Host "Tunnel: $url"

Write-Host "Waiting for the API..."
for ($i = 0; $i -lt 60; $i++) {
  try { Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
}

Write-Host "Rebuilding the web app on Vercel (about 1 minute)..."
vercel deploy --prod --yes --cwd "$root\frontend" --build-env "NEXT_PUBLIC_API_URL=$url" | Out-Null

Write-Host ""
Write-Host "Live: $site" -ForegroundColor Green
Write-Host "Keep this PC on and awake, with the two minimized windows open."
