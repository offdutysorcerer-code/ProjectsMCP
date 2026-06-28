@echo off
chcp 65001 >nul
title Start ProjectsMCP Platform
cd /d D:\AIProjects\ProjectsMCP
set "HOST=127.0.0.1"
set "PORT=8090"
echo Starting ProjectsMCP Platform...
echo URL: http://%HOST%:%PORT%/sse
echo Config: D:\AIProjects\ProjectsMCP\config.json
echo.
where uv >nul 2>&1
if errorlevel 1 goto uv_error
echo Starting MCP proxy...
echo.
uv tool run mcp-proxy --host %HOST% --port %PORT% -- uv run --with-requirements requirements.txt python server.py
if errorlevel 1 goto error
goto end
:uv_error
echo uv was not found in PATH.
echo Please install uv or run this on the original Windows user account.
goto end
:error
echo.
echo ProjectsMCP failed to start. Please check the error message above.
:end
echo.
pause
