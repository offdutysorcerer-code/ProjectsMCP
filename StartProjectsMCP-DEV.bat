@echo off
setlocal EnableExtensions
chcp 65001 >nul
title ProjectsMCP DEV
cd /d "%~dp0"
set "PORT=8091"

echo Starting ProjectsMCP DEV...
echo Local SSE: http://127.0.0.1:%PORT%/sse
echo Public SSE: https://mcp-dev.offdutylab.xyz/sse
echo Logs: %CD%\logs\dev
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_projectsmcp_dev.ps1" -HostAddress 127.0.0.1 -Port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="76" goto MONITOR
if not "%EXIT_CODE%"=="0" (
  echo.
  echo ProjectsMCP DEV failed or stopped unexpectedly.
  echo Check: %CD%\logs\dev
  pause
  endlocal & exit /b %EXIT_CODE%
)
endlocal & exit /b 0

:MONITOR
title ProjectsMCP DEV Status Monitor
echo.
echo ProjectsMCP DEV is already running.
echo Closing this window will NOT stop the DEV service.
echo Press Ctrl+C to stop monitoring.
echo.
:LOOP
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$listener=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue ^| Select-Object -First 1; $listenerPid=if($listener){$listener.OwningProcess}else{0}; $ready=$false; if($listener){try{$req=[System.Net.HttpWebRequest]::Create('http://127.0.0.1:%PORT%/mcp');$req.Method='GET';$req.Timeout=1500;$res=$req.GetResponse();try{$ready=[int]$res.StatusCode -lt 500}finally{$res.Dispose()}}catch [System.Net.WebException]{if($_.Exception.Response){try{$ready=[int]$_.Exception.Response.StatusCode -lt 500}finally{$_.Exception.Response.Dispose()}}}}; $s=if($ready){'RUNNING'}elseif($listener){'STARTING'}else{'OFFLINE'}; Write-Host ('[{0}] ProjectsMCP DEV {1}  PID={2}  Port=%PORT%  MCPReady={3}' -f (Get-Date -Format 'HH:mm:ss'),$s,$listenerPid,$ready)"
timeout /t 5 /nobreak >nul
goto LOOP
