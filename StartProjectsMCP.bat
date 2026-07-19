@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Start ProjectsMCP Platform
cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8090"

echo Starting ProjectsMCP Platform...
echo URL: http://%HOST%:%PORT%/sse
echo Logs: %CD%\logs
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_projectsmcp.ps1" -HostAddress "%HOST%" -Port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

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
