param(
  [string]$Version = "",
  [string]$BundlePath = "",
  [switch]$CreatePortableZip
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Assert-LastExitCode([string]$StepName) {
  if ($LASTEXITCODE -ne 0) {
    throw "$StepName failed with exit code $LASTEXITCODE."
  }
}

if (Test-Path ".venv\Scripts\python.exe") {
  $python = (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
  $python = "python"
}

if (-not $Version) {
  $Version = & $python -c "from app_meta import APP_VERSION; print(APP_VERSION)"
  Assert-LastExitCode "resolve app version"
}

$Version = "$Version".Trim()
if (-not $Version) {
  throw "Unable to resolve app version."
}

$distRoot = Join-Path $repoRoot "dist"
if ($BundlePath) {
  $desktopBundle = (Resolve-Path $BundlePath).Path
} else {
  $desktopBundle = Join-Path $distRoot "NASMusicBox"
}
if (-not (Test-Path $desktopBundle)) {
  throw "Desktop bundle not found: $desktopBundle"
}

$versionsRoot = Join-Path $distRoot "versions"
$versionedBundle = Join-Path $versionsRoot "NASMusicBox-v$Version"
$versionsReadme = Join-Path $versionsRoot "README.txt"
$latestLauncher = Join-Path $distRoot "Open-Latest-NASMusicBox.bat"
$latestInfo = Join-Path $distRoot "LATEST-VERSION.txt"
$releaseRoot = Join-Path $distRoot "release"
$portableZip = Join-Path $releaseRoot "NASMusicBox-portable.zip"

New-Item -ItemType Directory -Force -Path $versionsRoot | Out-Null
if (Test-Path $versionedBundle) {
  Remove-Item $versionedBundle -Recurse -Force
}
Copy-Item $desktopBundle $versionedBundle -Recurse

$versionsReadmeContent = @"
NAS Music Box - Version Archives

This folder stores archived desktop bundles by version.

Current latest version: v$Version

Recommended usage:
1. Open ..\Open-Latest-NASMusicBox.bat for the newest desktop build
2. Use versioned folders here only when you need to inspect or keep older builds
3. Keep old versions here instead of mixing multiple EXE folders in dist\
"@
[System.IO.File]::WriteAllText($versionsReadme, $versionsReadmeContent.TrimStart(), [System.Text.UTF8Encoding]::new($false))

$bundleLauncher = Join-Path $versionedBundle "Launch-NASMusicBox.bat"
$bundleLauncherContent = @"
@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0NASMusicBox.exe"
"@
[System.IO.File]::WriteAllText($bundleLauncher, $bundleLauncherContent.TrimStart(), [System.Text.UTF8Encoding]::new($false))

$relativeLatestBundle = ".\versions\NASMusicBox-v$Version\NASMusicBox.exe"
$latestLauncherContent = @"
@echo off
setlocal
cd /d "%~dp0"
if not exist "$relativeLatestBundle" (
  echo [ERROR] Latest desktop build not found: $relativeLatestBundle
  pause
  exit /b 1
)
start "" "$relativeLatestBundle"
"@
[System.IO.File]::WriteAllText($latestLauncher, $latestLauncherContent.TrimStart(), [System.Text.UTF8Encoding]::new($false))

$latestInfoContent = @"
NAS Music Box - Latest Desktop Build

Current version: v$Version

Open the latest build:
1. Double-click dist\Open-Latest-NASMusicBox.bat
2. Or open dist\versions\NASMusicBox-v$Version\ and run NASMusicBox.exe

Folders:
- dist\NASMusicBox                         Active build output for tooling
- dist\versions\NASMusicBox-v$Version     Versioned bundle archive
- dist\release                            Installer and portable zip
"@
[System.IO.File]::WriteAllText($latestInfo, $latestInfoContent.TrimStart(), [System.Text.UTF8Encoding]::new($false))

Write-Host "[INFO] Versioned bundle prepared: $versionedBundle"
Write-Host "[INFO] Versions README prepared: $versionsReadme"
Write-Host "[INFO] Latest launcher prepared: $latestLauncher"
Write-Host "[INFO] Latest version note prepared: $latestInfo"

if ($CreatePortableZip) {
  New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
  if (Test-Path $portableZip) {
    Remove-Item $portableZip -Force
  }
  Compress-Archive -Path $versionedBundle -DestinationPath $portableZip -Force
  Write-Host "[INFO] Portable zip prepared: $portableZip"
}
