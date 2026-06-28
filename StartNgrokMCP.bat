@echo off
echo DEBUG: StartNgrokMCP.bat started
chcp 65001
title ProjectsMCP Ngrok Tunnel
cd /d D:\AIProjects\ProjectsMCP
echo DEBUG: Current dir = D:\AIProjects\ProjectsMCP
set "PORT=8090
echo Starting ngrok tunnel for ProjectsMCP...
echo Local URL: http://127.0.0.1:%PORT%/sse
echo.
where ngrok
if errorlevel 1 goto install_ngrok
goto start_ngrok
:install_ngrok
echo ngrok was not found in PATH.
echo Trying to install ngrok through winget...
echo.
where winget
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
