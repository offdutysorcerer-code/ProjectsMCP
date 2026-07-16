@echo off
chcp 65001 >nul
title ProjectsMCP Ngrok Tunnel
cd /d "%~dp0"
set "PORT=8090"
echo Starting ngrok tunnel for ProjectsMCP...
echo Current dir: %CD%
echo Local URL: http://127.0.0.1:%PORT%/sse
echo.
where ngrok >nul 2>&1
if errorlevel 1 goto install_ngrok
goto start_ngrok
:install_ngrok
echo ngrok was not found in PATH.
echo Trying to install ngrok through winget...
echo.
where winget >nul 2>&1
if errorlevel 1 goto winget_error
winget install --id ngrok.ngrok -e
if errorlevel 1 goto ngrok_error
echo Please close this window, open a new Command Prompt, and run StartNgrokMCP.bat again.
goto end
:start_ngrok
echo Starting ngrok...
echo Command: ngrok http %PORT%
echo.
ngrok http %PORT%
if errorlevel 1 goto error
goto end
:winget_error
echo.
echo winget was not found.
goto end
:ngrok_error
echo.
echo Failed to install ngrok automatically.
goto end
:error
echo.
echo ngrok failed to start.
:end
echo.
pause
