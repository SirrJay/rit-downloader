# Builds the Windows installer:  build\installer\RitDownloader-Setup-Windows.exe
# Usage:  powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 [-Version 1.2.0] [-Python python]
param(
  [string]$Version = "",
  [string]$Python = "python",
  [string]$UpdateRepo = $env:RIT_UPDATE_REPO,
  [string]$Publisher = "Rit Downloader"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

# ---- version + update channel baked into the app
$vfile = "app\version.py"
$vtext = Get-Content $vfile -Raw
if ($Version) { $vtext = $vtext -replace 'VERSION = ".*?"', "VERSION = `"$Version`"" }
if ($UpdateRepo) { $vtext = $vtext -replace 'UPDATE_REPO = ".*?"', "UPDATE_REPO = `"$UpdateRepo`"" }
Set-Content $vfile $vtext -NoNewline -Encoding utf8
$Version = ([regex]'VERSION = "(.*?)"').Match($vtext).Groups[1].Value
Write-Host "== Building Rit Downloader $Version for Windows" -ForegroundColor Cyan

# ---- clean build environment
if (-not (Test-Path "build\venv\Scripts\python.exe")) { & $Python -m venv build\venv }
$py = "build\venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q --upgrade -r packaging\requirements.txt
if ($LASTEXITCODE) { throw "pip install failed" }

# ---- helper programs (ffmpeg, ffprobe, deno)
& $py app\setup_ffmpeg.py --dest build\tools\win-x64 --target win-x64 --deno
if ($LASTEXITCODE) { throw "tool download failed" }

# ---- Windows file version resource
$parts = ($Version.Split('.') + @('0','0','0','0'))[0..3] -join ', '
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', '$Publisher'),
    StringStruct('FileDescription', 'Rit Downloader'),
    StringStruct('FileVersion', '$Version'),
    StringStruct('ProductName', 'Rit Downloader'),
    StringStruct('ProductVersion', '$Version'),
    StringStruct('OriginalFilename', 'RitDownloader.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content build\win_version.txt -Encoding utf8

# ---- freeze
$env:RIT_TOOLS = "$root\build\tools\win-x64"
& $py -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work packaging\rit.spec
if ($LASTEXITCODE) { throw "PyInstaller failed" }

# ---- portable zip (no install needed)
New-Item -ItemType Directory -Force build\installer | Out-Null
& $py -c @"
import os, time, zipfile
src, out = r'build\dist\RitDownloader', r'build\installer\RitDownloader-Portable-Windows.zip'
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for dp, _, fn in os.walk(src):
        for f in fn:
            full = os.path.join(dp, f)
            for attempt in range(10):   # antivirus may briefly lock freshly written files
                try:
                    z.write(full, os.path.join('RitDownloader', os.path.relpath(full, src))); break
                except PermissionError:
                    time.sleep(1)
            else:
                raise SystemExit('locked: ' + full)
"@
if ($LASTEXITCODE) { throw "portable zip failed" }

# ---- installer
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup not found. Install it:  winget install JRSoftware.InnoSetup" }
& $iscc /Qp "/DAppVersion=$Version" "/DPublisher=$Publisher" packaging\windows\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }

# ---- optional code signing (set RIT_SIGN_CMD, e.g. a signtool or Azure Trusted Signing command with {file})
if ($env:RIT_SIGN_CMD) {
  $cmd = $env:RIT_SIGN_CMD.Replace("{file}", "$root\build\installer\RitDownloader-Setup-Windows.exe")
  Invoke-Expression $cmd
}
Get-ChildItem build\installer | Format-Table Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
Write-Host "Done." -ForegroundColor Green
