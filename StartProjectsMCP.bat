@echo off
setlocal EnableExtensions
chcp 65001 >nul
title ProjectsMCP Platform
cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8090"

echo Starting ProjectsMCP Platform...
echo URL: http://%HOST%:%PORT%/sse
echo Logs: %CD%\logs
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_projectsmcp.ps1" -HostAddress "%HOST%" -Port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="75" goto RESTART_MONITOR
if "%EXIT_CODE%"=="76" goto ALREADY_RUNNING_MONITOR

if not "%EXIT_CODE%"=="0" (
    echo.
    echo ProjectsMCP failed or stopped unexpectedly.
    echo Check the newest file under: %CD%\logs
)

if /I not "%PROJECTSMCP_NO_PAUSE%"=="1" (
    echo.
    pause
)

endlocal & exit /b %EXIT_CODE%

:ALREADY_RUNNING_MONITOR
title ProjectsMCP Status Monitor
echo.
echo ProjectsMCP is already running.
echo This window will monitor the existing process instead of starting another instance.
echo Closing this window will NOT stop ProjectsMCP.
echo Press Ctrl+C to stop monitoring.
echo.
goto MONITOR_LOOP

:RESTART_MONITOR
title ProjectsMCP Status Monitor
echo.
echo ProjectsMCP was intentionally restarted.
echo This window is now monitoring the replacement process.
echo Closing this window will NOT stop ProjectsMCP.
echo Press Ctrl+C to stop monitoring.
echo.

:MONITOR_LOOP
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
  "$p=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue ^| Select-Object -First 1; $listenerPid=if($p){$p.OwningProcess}else{0}; $ready=$false; if($p){try{$r=Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/mcp' -Method Get -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop; $ready=$r.StatusCode -lt 500}catch{if($_.Exception.Response){$ready=[int]$_.Exception.Response.StatusCode -lt 500}}}; $state=if($ready){'RUNNING'}elseif($p){'STARTING'}else{'OFFLINE'}; Write-Host ('[{0}] ProjectsMCP {1}  PID={2}  Port=%PORT%  MCPReady={3}' -f (Get-Date -Format 'HH:mm:ss'),$state,$listenerPid,$ready)"
timeout /t 5 /nobreak >nul
goto MONITOR_LOOP
