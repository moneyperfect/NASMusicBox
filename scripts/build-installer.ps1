param(
  [switch]$SkipDesktopBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (Test-Path ".venv\Scripts\python.exe") {
  $python = (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
  $python = "python"
}

if (-not $SkipDesktopBuild) {
  & (Join-Path $PSScriptRoot "build-desktop.ps1")
}

$candidatePaths = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
)

$iscc = $candidatePaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
  throw "Inno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php or run 'choco install innosetup -y'."
}

$version = & $python -c "from app_meta import APP_VERSION; print(APP_VERSION)"
if (-not $version) {
  throw "Unable to resolve app version."
}

Write-Host "[INFO] Building installer with Inno Setup..."
& $iscc "/DMyAppVersion=$version" "packaging\NASMusicBox.iss"

Write-Host "[INFO] Installer build complete: $repoRoot\dist\release"
