Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..\\frontend")
npm run dev -- --host 0.0.0.0 --port 5173
