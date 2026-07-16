@echo off
setlocal EnableExtensions
chcp 65001 >nul
title ProjectsMCP Ngrok Tunnel
cd /d "%~dp0"

set "PORT=8090"
set "NGROK_CMD="

echo Starting ngrok tunnel for ProjectsMCP...
echo Current dir: %CD%
echo Local URL: http://127.0.0.1:%PORT%/sse
echo.

call :find_ngrok
if defined NGROK_CMD goto start_ngrok

echo ngrok was not found. Trying to install it through winget...
echo.
where winget >nul 2>&1
if errorlevel 1 goto winget_error

winget source update
winget install --id Ngrok.Ngrok -e --source winget --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto ngrok_error

call :find_ngrok
if not defined NGROK_CMD goto path_error

:start_ngrok
echo Starting ngrok...
echo Command: "%NGROK_CMD%" http %PORT%
echo.
"%NGROK_CMD%" http %PORT%
if errorlevel 1 goto error
goto end

:find_ngrok
set "NGROK_CMD="

for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul ^| findstr /I "Path"') do set "USER_PATH=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul ^| findstr /I "Path"') do set "MACHINE_PATH=%%B"
if defined USER_PATH if defined MACHINE_PATH set "PATH=%MACHINE_PATH%;%USER_PATH%"

where ngrok >nul 2>&1
if not errorlevel 1 set "NGROK_CMD=ngrok"
if not defined NGROK_CMD if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe" set "NGROK_CMD=%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe"
if not defined NGROK_CMD if exist "%ProgramFiles%\WinGet\Links\ngrok.exe" set "NGROK_CMD=%ProgramFiles%\WinGet\Links\ngrok.exe"
if not defined NGROK_CMD (
    for /f "delims=" %%F in ('dir /b /s "%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_*\ngrok.exe" 2^>nul') do if not defined NGROK_CMD set "NGROK_CMD=%%F"
)
exit /b 0

:winget_error
echo.
echo winget was not found.
echo Install or update "App Installer" from Microsoft Store, then try again.
goto end

:ngrok_error
echo.
echo Failed to install ngrok through winget.
echo Run this command manually to inspect the error:
echo winget install --id Ngrok.Ngrok -e --source winget
goto end

:path_error
echo.
echo ngrok was installed, but ngrok.exe could not be located.
echo Search location checked: %LOCALAPPDATA%\Microsoft\WinGet\Packages
goto end

:error
echo.
echo ngrok failed to start.
echo If this is the first run, configure your token first:
echo ngrok config add-authtoken YOUR_TOKEN
goto end

:end
echo.
pause
endlocal
