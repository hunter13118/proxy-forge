# Starts proxy-forge on http://127.0.0.1:7870. All of its model work goes to the studio's /v1/ai API (STUDIO_URL, http://127.0.0.1:7860 unless set): start the studio first (D:\studio-home\start-studio.ps1).
# Everything lives on D: and G:; nothing on C:.
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tmp = "D:\studio-home\tmp"
New-Item -ItemType Directory -Force $tmp | Out-Null
$env:TEMP = $tmp; $env:TMP = $tmp
# Reaching it from outside (docs in README: "The tunnel"): the same Clerk instance and the same allowed people as the studio. With no allowed user every request from outside is refused.
$env:STUDIO_CLERK_ISSUER = "https://civil-stinkbug-5610.clerk.accounts.dev"
if (Test-Path "D:\studio-home\clerk-users.txt") { $env:STUDIO_CLERK_USERS = ((Get-Content "D:\studio-home\clerk-users.txt") | ? { $_ -match '^\s*user_' } | % { $_.Trim() }) -join "," }
# a broken leftover Ollama folder on C: in PATH makes pip/python fail; keep it out of this process
$env:PATH = (($env:PATH -split ';' | Where-Object { $_ -and $_ -notmatch 'Programs\\Ollama' }) -join ';')
if (Test-Path "$here\extra.env") { foreach ($l in Get-Content "$here\extra.env") { if ($l -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2].Trim() } } }

try { Invoke-WebRequest "$(if ($env:STUDIO_URL) { $env:STUDIO_URL } else { 'http://127.0.0.1:7860' })/health" -UseBasicParsing -TimeoutSec 3 | Out-Null }
catch { Write-Warning "The studio is not answering: start it first (D:\studio-home\start-studio.ps1). Drawing waits for it." }
# proxy-forge's own Cloudflare tunnel (a user-level process; the studio's and the owner's other tunnels are separate and untouched)
$cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$tunnelUp = [bool](Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue | ? { $_.CommandLine -match 'proxy-forge\.yml' })
if (-not $tunnelUp -and (Test-Path $cf) -and (Test-Path "$here\cloudflared\proxy-forge.yml")) {
    New-Item -ItemType Directory -Force "$here\logs" | Out-Null
    Start-Process -FilePath $cf -ArgumentList "--config", "$here\cloudflared\proxy-forge.yml", "tunnel", "--no-autoupdate", "run" -WindowStyle Hidden `
        -RedirectStandardOutput "$here\logs\cloudflared.out" -RedirectStandardError "$here\logs\cloudflared.err"
}
Set-Location $here
& "$here\.venv\Scripts\python.exe" -m proxy_forge
