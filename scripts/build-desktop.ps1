param(
  [switch]$Clean,
  [switch]$SkipDependencies
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

if (-not $SkipDependencies) {
  Write-Host "[INFO] Installing Python dependencies..."
  & $python -m pip install -r requirements.txt -r requirements-dev.txt
  Assert-LastExitCode "python dependency install"
}

# Keep playback self-contained on PCs without developer tooling.
$nodeTarget = Join-Path $repoRoot "tools\node\node.exe"
if (-not (Test-Path -LiteralPath $nodeTarget)) {
  $nodeSource = (Get-Command node -ErrorAction Stop).Source
  New-Item -ItemType Directory -Force -Path (Split-Path $nodeTarget) | Out-Null
  Copy-Item -LiteralPath $nodeSource -Destination $nodeTarget
  $nodeVersion = (& $nodeSource --version).Trim()
  Invoke-WebRequest -Uri "https://raw.githubusercontent.com/nodejs/node/$nodeVersion/LICENSE" -OutFile "tools\node\LICENSE.txt"
}
$bootstrap = Join-Path $repoRoot "tools\webview2\MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path -LiteralPath $bootstrap)) {
  New-Item -ItemType Directory -Force -Path (Split-Path $bootstrap) | Out-Null
  Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $bootstrap
}
if (-not (Test-Path -LiteralPath "tools\ffmpeg\bin\ffmpeg.exe")) {
  throw "Missing tools\ffmpeg\bin\ffmpeg.exe. Prepare the FFmpeg bundle before release packaging."
}

Write-Host "[INFO] Building frontend..."
Push-Location frontend
if ($SkipDependencies) {
  if (-not (Test-Path "node_modules")) { throw "Frontend dependencies are missing." }
} elseif (Test-Path "package-lock.json") {
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
  $cleanTarget = (Resolve-Path -LiteralPath "dist\NASMusicBox").Path
  if ($cleanTarget -ne (Join-Path $repoRoot "dist\NASMusicBox")) { throw "Unexpected build directory: $cleanTarget" }
  Remove-Item -LiteralPath $cleanTarget -Recurse -Force
}

Write-Host "[INFO] Building desktop bundle..."
& $python -m PyInstaller packaging/NASMusicBox.spec --noconfirm --clean
Assert-LastExitCode "PyInstaller desktop bundle"

Write-Host "[INFO] Preparing versioned desktop artifacts..."
& (Join-Path $PSScriptRoot "build-release-assets.ps1")
Assert-LastExitCode "prepare versioned desktop artifacts"

Write-Host "[INFO] Desktop build complete: $repoRoot\dist\NASMusicBox"
Write-Host "[INFO] Open the latest build via: $repoRoot\dist\Open-Latest-NASMusicBox.bat"
