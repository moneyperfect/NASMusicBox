@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

set "NEED_BUILD=0"
set "KILL_PORT=0"
set "BROWSER_MODE=0"

for %%A in (%*) do (
  if /I "%%~A"=="--rebuild" set "NEED_BUILD=1"
  if /I "%%~A"=="--kill-port" set "KILL_PORT=1"
  if /I "%%~A"=="--browser" set "BROWSER_MODE=1"
)

if not exist "frontend\dist\index.html" set "NEED_BUILD=1"

if exist "%~dp0tools\ffmpeg\bin\ffmpeg.exe" (
  set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
) else (
  echo [WARN] ffmpeg not found at tools\ffmpeg\bin\ffmpeg.exe
)

if "%KILL_PORT%"=="1" (
  echo [INFO] Clearing port 8010 listeners...
  powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach($id in $p){ Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 500"
)

call :check_port_state
if "%PORT_STATE%"=="conflict" (
  echo [ERROR] Port 8010 is occupied by a process that is not responding as NAS.
  echo Run start-desktop.bat --kill-port to clear it first.
  pause
  exit /b 1
)

if "%NEED_BUILD%"=="1" (
  where node >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+ first.
    pause
    exit /b 1
  )

  where npm >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] npm not found. Please reinstall Node.js.
    pause
    exit /b 1
  )

  echo [INFO] Building frontend...
  cd /d "%~dp0frontend"

  if not exist "node_modules" (
    echo [INFO] Installing frontend dependencies...
    call npm install
    if errorlevel 1 (
      echo [ERROR] npm install failed.
      pause
      exit /b 1
    )
  )

  call npm run build
  if errorlevel 1 (
    echo [ERROR] npm run build failed.
    pause
    exit /b 1
  )

  cd /d "%~dp0"
)

if "%BROWSER_MODE%"=="1" (
  if "%PORT_STATE%"=="healthy" (
    echo [INFO] Opening NAS in browser using the existing backend...
    start "" "http://localhost:8010"
    exit /b 0
  )

  echo [INFO] Launching NAS browser mode on http://localhost:8010
  start "" "http://localhost:8010"
  "%PYTHON_EXE%" main.py
  exit /b %errorlevel%
)

echo [INFO] Launching NAS desktop shell...
"%PYTHON_EXE%" desktop_app.py
exit /b %errorlevel%

:check_port_state
set "PORT_STATE=free"
powershell -NoProfile -Command "$listener = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue; if(-not $listener){ exit 0 }; try { $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8010/health' -UseBasicParsing -TimeoutSec 2; if($response.StatusCode -eq 200){ exit 4 } } catch {}; exit 3"
if errorlevel 4 (
  set "PORT_STATE=healthy"
  goto :eof
)
if errorlevel 3 (
  set "PORT_STATE=conflict"
  goto :eof
)
goto :eof
