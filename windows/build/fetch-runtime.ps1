# Fetches the pinned third-party runtime binaries for the Windows bundle.
# Every URL is version-pinned and sha256-verified — bump versions and hashes together.
#
#   .\fetch-runtime.ps1 -OutDir ..\..\build\runtime
#
# Produces:  <OutDir>\{python, ffmpeg, go2rtc, caddy, redis, mariadb, fonts, winsw}\...
param(
    [string]$OutDir = "$PSScriptRoot\..\..\build\runtime"
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ── pins ─────────────────────────────────────────────────────────────────────
# Update sha256 values when bumping. 'SKIP' disables verification for a first
# fetch — CI refuses to ship a bundle that still contains a SKIP.
$Pins = @(
    @{ Name = 'python';  Version = '3.13.7'
       Url = 'https://www.nuget.org/api/v2/package/python/3.13.7'
       Sha256 = 'SKIP'; Kind = 'nupkg' }
    @{ Name = 'ffmpeg';  Version = '7.1'
       Url = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-7.1-essentials_build.zip'
       Sha256 = 'SKIP'; Kind = 'zip' }
    @{ Name = 'go2rtc';  Version = '1.9.4'
       Url = 'https://github.com/AlexxIT/go2rtc/releases/download/v1.9.4/go2rtc_win64.zip'
       Sha256 = 'SKIP'; Kind = 'zip' }
    @{ Name = 'caddy';   Version = '2.8.4'
       Url = 'https://github.com/caddyserver/caddy/releases/download/v2.8.4/caddy_2.8.4_windows_amd64.zip'
       Sha256 = 'SKIP'; Kind = 'zip' }
    # Redis for Windows: redis-windows MSYS2 build of 7.4 (matches the Docker image
    # major); fallback pin = tporadowski 5.0.14.1 (app needs only a 3.x-era surface).
    @{ Name = 'redis';   Version = '7.4.2'
       Url = 'https://github.com/redis-windows/redis-windows/releases/download/7.4.2/Redis-7.4.2-Windows-x64-msys2.zip'
       Sha256 = 'SKIP'; Kind = 'zip' }
    @{ Name = 'mariadb'; Version = '11.8.4'
       Url = 'https://archive.mariadb.org/mariadb-11.8.4/winx64-packages/mariadb-11.8.4-winx64.zip'
       Sha256 = 'SKIP'; Kind = 'zip' }
    @{ Name = 'winsw';   Version = '2.12.0'
       Url = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe'
       Sha256 = 'SKIP'; Kind = 'exe' }
    @{ Name = 'fonts';   Version = '2.37'
       Url = 'https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip'
       Sha256 = 'SKIP'; Kind = 'zip' }
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$cache = Join-Path $OutDir '.downloads'
New-Item -ItemType Directory -Force -Path $cache | Out-Null

foreach ($pin in $Pins) {
    $dest = Join-Path $OutDir $pin.Name
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    $file = Join-Path $cache ([IO.Path]::GetFileName(([Uri]$pin.Url).AbsolutePath))
    if (-not (Test-Path $file)) {
        Write-Host "fetch $($pin.Name) $($pin.Version) <- $($pin.Url)"
        Invoke-WebRequest -Uri $pin.Url -OutFile $file
    }
    if ($pin.Sha256 -ne 'SKIP') {
        $actual = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
        if ($actual -ne $pin.Sha256.ToLower()) {
            throw "sha256 mismatch for $($pin.Name): expected $($pin.Sha256), got $actual"
        }
    } else {
        Write-Warning "$($pin.Name): sha256 pin is SKIP (fill it in before release)"
    }

    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    switch ($pin.Kind) {
        'zip'   { Expand-Archive -Path $file -DestinationPath $dest -Force }
        'nupkg' {
            $tmp = "$file.zip"; Copy-Item $file $tmp -Force
            Expand-Archive -Path $tmp -DestinationPath "$dest\_pkg" -Force
            # nuget layout: tools\ = the actual CPython tree
            Move-Item "$dest\_pkg\tools\*" $dest
            Remove-Item -Recurse -Force "$dest\_pkg", $tmp
        }
        'exe'   { Copy-Item $file (Join-Path $dest 'WinSW-x64.exe') }
    }
}

# ── normalize layouts ────────────────────────────────────────────────────────
# ffmpeg: gyan zip nests ffmpeg-<v>-essentials_build\bin — flatten to ffmpeg\bin
$ffNested = Get-ChildItem -Directory (Join-Path $OutDir 'ffmpeg') | Select-Object -First 1
if ($ffNested -and (Test-Path (Join-Path $ffNested.FullName 'bin'))) {
    Move-Item (Join-Path $ffNested.FullName '*') (Join-Path $OutDir 'ffmpeg')
    Remove-Item -Recurse -Force $ffNested.FullName
}
# redis: some builds nest a single folder — flatten to redis\redis-server.exe
$rdRoot = Join-Path $OutDir 'redis'
if (-not (Test-Path (Join-Path $rdRoot 'redis-server.exe'))) {
    $rdNested = Get-ChildItem -Recurse $rdRoot -Filter 'redis-server.exe' | Select-Object -First 1
    if ($rdNested) {
        Move-Item (Join-Path $rdNested.DirectoryName '*') $rdRoot -Force
    }
}
# mariadb: nests mariadb-<v>-winx64\ — flatten, then trim what the NVR never uses
$mdNested = Get-ChildItem -Directory (Join-Path $OutDir 'mariadb') | Select-Object -First 1
if ($mdNested -and (Test-Path (Join-Path $mdNested.FullName 'bin'))) {
    Move-Item (Join-Path $mdNested.FullName '*') (Join-Path $OutDir 'mariadb')
    Remove-Item -Recurse -Force $mdNested.FullName
}
foreach ($trim in 'mariadb-test', 'mysql-test', 'include', 'lib') {
    $p = Join-Path $OutDir "mariadb\$trim"
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
# fonts: keep only DejaVuSans.ttf
$dejavu = Get-ChildItem -Recurse (Join-Path $OutDir 'fonts') -Filter 'DejaVuSans.ttf' | Select-Object -First 1
if ($dejavu) {
    Copy-Item $dejavu.FullName (Join-Path $OutDir 'DejaVuSans.ttf')
    Remove-Item -Recurse -Force (Join-Path $OutDir 'fonts')
    New-Item -ItemType Directory -Force -Path (Join-Path $OutDir 'fonts') | Out-Null
    Move-Item (Join-Path $OutDir 'DejaVuSans.ttf') (Join-Path $OutDir 'fonts\DejaVuSans.ttf')
}

Write-Host "runtime ready at $OutDir"
