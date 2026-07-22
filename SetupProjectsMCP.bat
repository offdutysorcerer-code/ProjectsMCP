@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Setup ProjectsMCP Platform
cd /d "%~dp0"

rem Keep the current process PATH and add standard per-user WinGet locations.
set "PATH=%LOCALAPPDATA%\Microsoft\WindowsApps;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
set "UV_PYTHON=3.13"

set "PY_CMD="
set "UV_CMD="
set "NGROK_CMD="
set "START_NOW=N"
set "START_TUNNEL=N"

echo ========================================
echo ProjectsMCP One-Click Setup
echo ========================================
echo.

rem --------------------------------------------------
rem [1/4] Python and uv
rem --------------------------------------------------
echo [1/4] Checking Python and uv...
py --version >nul 2>&1
if not errorlevel 1 set "PY_CMD=py"

if not defined PY_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD goto python_error

where uv >nul 2>&1
if not errorlevel 1 set "UV_CMD=uv"

if not defined UV_CMD (
    %PY_CMD% -m uv --version >nul 2>&1
    if not errorlevel 1 set "UV_CMD=%PY_CMD% -m uv"
)

if not defined UV_CMD (
    echo uv was not found. Installing it for the current Windows user...
    %PY_CMD% -m pip install --user --upgrade uv
    if errorlevel 1 goto uv_error
    set "UV_CMD=%PY_CMD% -m uv"
)

echo Preparing Python %UV_PYTHON%...
call %UV_CMD% python install %UV_PYTHON%
if errorlevel 1 goto managed_python_error

echo Python and uv are ready.
echo.

rem --------------------------------------------------
rem [2/4] Python packages and Playwright
rem --------------------------------------------------
echo [2/4] Installing Python packages...
call %UV_CMD% run --with-requirements requirements.txt python -c "import mcp; import playwright; print('Python packages OK')"
if errorlevel 1 goto dependency_error

echo Installing Playwright Chromium...
call %UV_CMD% run --with-requirements requirements.txt python -m playwright install chromium
if errorlevel 1 goto playwright_error

echo Python dependencies are ready.
echo.

rem --------------------------------------------------
rem [3/4] ngrok installation
rem --------------------------------------------------
echo [3/4] Checking ngrok...
call :find_ngrok
if defined NGROK_CMD goto ngrok_found

where winget >nul 2>&1
if errorlevel 1 goto winget_error

echo ngrok was not found. Installing through WinGet...
winget source update
winget install --id Ngrok.Ngrok -e --source winget --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo Initial WinGet installation failed. Repairing WinGet sources...
    winget source reset --force
    if errorlevel 1 goto ngrok_install_error
    winget source update
    winget install --id Ngrok.Ngrok -e --source winget --accept-source-agreements --accept-package-agreements
    if errorlevel 1 goto ngrok_install_error
)

call :find_ngrok
if not defined NGROK_CMD goto ngrok_path_error

:ngrok_found
echo ngrok is ready: %NGROK_CMD%
echo Checking for a supported ngrok agent update...
"%NGROK_CMD%" update
if errorlevel 1 goto ngrok_update_error
call :find_ngrok
if not defined NGROK_CMD goto ngrok_path_error
echo.

rem --------------------------------------------------
rem [4/4] ngrok authentication
rem --------------------------------------------------
echo [4/4] Checking ngrok authentication...
call :has_ngrok_token
if not errorlevel 1 goto token_ready

echo.
echo No valid ngrok configuration was detected.
echo Paste the authtoken from your ngrok dashboard.
echo The token will be stored by ngrok in the current Windows user profile.
set "NGROK_TOKEN="
set /p "NGROK_TOKEN=ngrok authtoken: "

if not defined NGROK_TOKEN goto token_skipped
"%NGROK_CMD%" config add-authtoken "%NGROK_TOKEN%"
set "NGROK_TOKEN="
if errorlevel 1 goto token_error

"%NGROK_CMD%" config check >nul 2>&1
if errorlevel 1 goto token_error

goto token_ready

:token_skipped
echo.
echo Token setup was skipped. Local ProjectsMCP can still run,
echo but StartNgrokMCP.bat will require a valid ngrok token.
goto setup_complete

:token_ready
"%NGROK_CMD%" config check >nul 2>&1
if errorlevel 1 goto token_error
echo ngrok authentication is ready.

:setup_complete
echo.
echo ========================================
echo Setup completed successfully.
echo ========================================
echo.

set /p "START_NOW=Start ProjectsMCP now? [Y/N]: "
if /I not "%START_NOW%"=="Y" goto success_end

start "ProjectsMCP Platform" "%~dp0StartProjectsMCP.bat"

timeout /t 3 /nobreak >nul
set /p "START_TUNNEL=Start ngrok tunnel now? [Y/N]: "
if /I "%START_TUNNEL%"=="Y" start "ProjectsMCP ngrok" "%~dp0StartNgrokMCP.bat"

goto success_end

:has_ngrok_token
for %%F in ("%LOCALAPPDATA%\ngrok\ngrok.yml" "%USERPROFILE%\.ngrok2\ngrok.yml") do (
    if exist "%%~F" (
        findstr /R /C:"^[ ]*authtoken:[ ]*[^ ]" "%%~F" >nul 2>&1
        if not errorlevel 1 exit /b 0
    )
)
exit /b 1

:find_ngrok
set "NGROK_CMD="

where ngrok >nul 2>&1
if not errorlevel 1 set "NGROK_CMD=ngrok"
if not defined NGROK_CMD if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe" set "NGROK_CMD=%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe"
if not defined NGROK_CMD if exist "%ProgramFiles%\WinGet\Links\ngrok.exe" set "NGROK_CMD=%ProgramFiles%\WinGet\Links\ngrok.exe"

rem WinGet portable packages may live under Packages without a Links alias in the current shell.
if not defined NGROK_CMD (
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_*") do (
        if exist "%%~D\ngrok.exe" if not defined NGROK_CMD set "NGROK_CMD=%%~D\ngrok.exe"
    )
)

exit /b 0

:python_error
echo.
echo ERROR: Python was not found.
echo Install Python 3.11 or newer and enable the Python launcher or PATH option.
goto failure_end

:managed_python_error
echo.
echo ERROR: uv could not install or locate Python %UV_PYTHON%.
goto failure_end

:uv_error
echo.
echo ERROR: uv could not be installed.
echo Try: %PY_CMD% -m pip install --user --upgrade uv
goto failure_end

:dependency_error
echo.
echo ERROR: Python packages could not be prepared from requirements.txt.
goto failure_end

:playwright_error
echo.
echo ERROR: Playwright Chromium installation failed.
goto failure_end

:winget_error
echo.
echo ERROR: WinGet was not found.
echo Install or update "App Installer" from Microsoft Store, then run setup again.
goto failure_end

:ngrok_update_error
echo.
echo ERROR: ngrok could not update to a supported agent version.
echo Try: "%NGROK_CMD%" update
echo Or download the current Windows agent from https://ngrok.com/download
goto failure_end

:ngrok_install_error
echo.
echo ERROR: ngrok installation failed even after repairing WinGet sources.
echo Manual diagnostic command:
echo winget install --id Ngrok.Ngrok -e --source winget
goto failure_end

:ngrok_path_error
echo.
echo ERROR: ngrok was installed, but ngrok.exe could not be located.
echo Open a new Command Prompt and run SetupProjectsMCP.bat again.
goto failure_end

:token_error
echo.
echo ERROR: ngrok rejected the token or the configuration could not be saved.
echo Run setup again and verify the token copied from the ngrok dashboard.
goto failure_end

:success_end
echo.
echo Setup finished. You can close this window.
echo.
pause
endlocal
exit /b 0

:failure_end
echo.
echo Setup did not complete. Review the message above and run it again.
echo.
pause
endlocal
exit /b 1
