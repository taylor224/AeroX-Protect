# Assembles the per-version app payload (the auto-update unit) and its manifest.
#
#   .\assemble-bundle.ps1 -Version 1.3.0 -RuntimeDir ..\..\build\runtime -OutDir ..\..\build\dist
#
# Produces:
#   <OutDir>\aeroxprotect-windows-x64-app-v<version>.zip   (site-packages + app + frontend)
#   <OutDir>\manifest-v<version>.json
#   <OutDir>\SHA256SUMS
#
# Run AFTER: fetch-runtime.ps1, `npm run build` in frontend/ (or pass -FrontendDist).
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$RuntimeDir = "$PSScriptRoot\..\..\build\runtime",
    [string]$OutDir = "$PSScriptRoot\..\..\build\dist",
    [string]$FrontendDist = "$PSScriptRoot\..\..\frontend\dist",
    [string]$MinLauncherVersion = '1.0.0',
    [string]$MinFromVersion = '0.0.0'
)
$ErrorActionPreference = 'Stop'
$Repo = Resolve-Path "$PSScriptRoot\..\.."
$Py = Join-Path $RuntimeDir 'python\python.exe'
$Stage = Join-Path $OutDir "stage-v$Version"

if (-not (Test-Path $Py)) { throw "runtime python missing — run fetch-runtime.ps1 first" }
if (-not (Test-Path "$FrontendDist\index.html")) { throw "frontend dist missing — run npm run build" }

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage, $OutDir | Out-Null

# ── site-packages (cp313 win_amd64 wheels only — no source builds) ───────────
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install --only-binary=:all: --target "$Stage\site-packages" `
    -r "$Repo\windows\requirements-win.txt"
if ($LASTEXITCODE -ne 0) { throw 'pip install failed (a dep has no Windows wheel?)' }

# ── app source ───────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path "$Stage\app" | Out-Null
foreach ($item in 'server', 'worker', 'migrations', 'config.py') {
    Copy-Item -Recurse "$Repo\$item" "$Stage\app\$item"
}
Get-ChildItem -Recurse "$Stage\app" -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force

# ── frontend ─────────────────────────────────────────────────────────────────
Copy-Item -Recurse $FrontendDist "$Stage\frontend"

Set-Content -Path "$Stage\VERSION" -Value $Version -NoNewline -Encoding ascii

# ── import smoke test with a clean PYTHONPATH (proves the --target layout) ───
$env:PYTHONPATH = "$Stage\site-packages;$Stage\app"
& $Py -c "import flask, celery, sqlalchemy, pymysql, redis, cryptography, argon2, psutil, watchdog, pyzipper, boto3, smbprotocol, onvif, wsdiscovery, waitress, uvicorn, fastapi, httpx; import config; print('import smoke OK')"
if ($LASTEXITCODE -ne 0) { throw 'clean-PYTHONPATH import smoke test failed' }
$env:PYTHONPATH = ''

# ── zip + manifest + checksums ───────────────────────────────────────────────
$zipName = "aeroxprotect-windows-x64-app-v$Version.zip"
$zipPath = Join-Path $OutDir $zipName
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path "$Stage\*" -DestinationPath $zipPath -CompressionLevel Optimal

$sha = (Get-FileHash -Algorithm SHA256 $zipPath).Hash.ToLower()
$manifest = [ordered]@{
    version              = $Version
    launcher_version     = $MinLauncherVersion
    min_launcher_version = $MinLauncherVersion
    min_from_version     = $MinFromVersion
    python               = '3.13'
    app = [ordered]@{
        name   = $zipName
        sha256 = $sha
        size   = (Get-Item $zipPath).Length
    }
}
$manifest | ConvertTo-Json -Depth 4 |
    Set-Content -Path (Join-Path $OutDir "manifest-v$Version.json") -Encoding utf8

Get-ChildItem $OutDir -File | Where-Object { $_.Name -ne 'SHA256SUMS' } | ForEach-Object {
    '{0}  {1}' -f (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower(), $_.Name
} | Set-Content -Path (Join-Path $OutDir 'SHA256SUMS') -Encoding ascii

Remove-Item -Recurse -Force $Stage
Write-Host "bundle ready: $zipPath"
