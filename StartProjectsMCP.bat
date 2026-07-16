@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Start ProjectsMCP Platform
cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8090"
set "UV_CMD="

echo Starting ProjectsMCP Platform...
echo URL: http://%HOST%:%PORT%/sse
echo Config: %CD%\config.json
echo.

where uv >nul 2>&1
if not errorlevel 1 set "UV_CMD=uv"

if not defined UV_CMD (
    py -m uv --version >nul 2>&1
    if not errorlevel 1 set "UV_CMD=py -m uv"
)

if not defined UV_CMD (
    python -m uv --version >nul 2>&1
    if not errorlevel 1 set "UV_CMD=python -m uv"
)

if not defined UV_CMD goto uv_error

echo Using: %UV_CMD%
echo Starting MCP proxy...
echo.
call %UV_CMD% tool run mcp-proxy --host %HOST% --port %PORT% -- %UV_CMD% run --with-requirements requirements.txt python server.py
if errorlevel 1 goto error
goto end

:uv_error
echo uv is not installed or cannot be found.
echo Please run SetupProjectsMCP.bat first.
goto end

:error
echo.
echo ProjectsMCP failed to start. Please check the error message above.

:end
echo.
pause
endlocal
