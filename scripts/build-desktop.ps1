param(
  [switch]$Clean
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Assert-LastExitCode([string]$StepName) {
  if ($LASTEXITCODE -ne 0) {
    throw "$StepName failed with exit code $LASTEXITCODE."
  }
}

function Assert-DesktopBundleNotRunning() {
  $runningProcesses = Get-Process -Name "NASMusicBox" -ErrorAction SilentlyContinue
  if ($runningProcesses) {
    throw "NAS Music Box is still running. Please fully exit the desktop app and any tray instance before building a new desktop version."
  }
}

if (Test-Path ".venv\Scripts\python.exe") {
  $python = (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
  $python = "python"
}

Assert-DesktopBundleNotRunning

Write-Host "[INFO] Installing Python dependencies..."
& $python -m pip install --upgrade pip
Assert-LastExitCode "python -m pip install --upgrade pip"
& $python -m pip install -r requirements.txt -r requirements-dev.txt
Assert-LastExitCode "python dependency install"

Write-Host "[INFO] Building frontend..."
Push-Location frontend
if (Test-Path "package-lock.json") {
  npm ci
  Assert-LastExitCode "npm ci"
} else {
  npm install
  Assert-LastExitCode "npm install"
}
npm run build
Assert-LastExitCode "npm run build"
Pop-Location

Write-Host "[INFO] Generating app assets..."
& $python scripts/generate_app_assets.py
Assert-LastExitCode "generate_app_assets.py"

if ($Clean -and (Test-Path "dist\NASMusicBox")) {
  Remove-Item "dist\NASMusicBox" -Recurse -Force
}

Write-Host "[INFO] Building desktop bundle..."
& $python -m PyInstaller packaging/NASMusicBox.spec --noconfirm --clean
Assert-LastExitCode "PyInstaller desktop bundle"

Write-Host "[INFO] Preparing versioned desktop artifacts..."
& (Join-Path $PSScriptRoot "build-release-assets.ps1")
Assert-LastExitCode "prepare versioned desktop artifacts"

Write-Host "[INFO] Desktop build complete: $repoRoot\dist\NASMusicBox"
Write-Host "[INFO] Open the latest build via: $repoRoot\dist\Open-Latest-NASMusicBox.bat"
