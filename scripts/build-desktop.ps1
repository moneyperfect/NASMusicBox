param(
  [switch]$Clean
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (Test-Path ".venv\Scripts\python.exe") {
  $python = (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
  $python = "python"
}

Write-Host "[INFO] Installing Python dependencies..."
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt -r requirements-dev.txt

Write-Host "[INFO] Building frontend..."
Push-Location frontend
if (Test-Path "package-lock.json") {
  npm ci
} else {
  npm install
}
npm run build
Pop-Location

Write-Host "[INFO] Generating app assets..."
& $python scripts/generate_app_assets.py

if ($Clean -and (Test-Path "dist\NASMusicBox")) {
  Remove-Item "dist\NASMusicBox" -Recurse -Force
}

Write-Host "[INFO] Building desktop bundle..."
& $python -m PyInstaller packaging/NASMusicBox.spec --noconfirm --clean

Write-Host "[INFO] Desktop build complete: $repoRoot\dist\NASMusicBox"
