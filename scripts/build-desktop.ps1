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

if (Test-Path ".venv\Scripts\python.exe") {
  $python = (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
  $python = "python"
}

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

Write-Host "[INFO] Desktop build complete: $repoRoot\dist\NASMusicBox"
