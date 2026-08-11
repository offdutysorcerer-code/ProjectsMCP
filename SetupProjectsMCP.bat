@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Setup ProjectsMCP Platform
cd /d "%~dp0"

set "PATH=%LOCALAPPDATA%\Microsoft\WindowsApps;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
set "UV_PYTHON=3.13"
set "PY_CMD="
set "UV_CMD="
set "START_NOW=N"

echo ========================================
echo ProjectsMCP Local Setup
echo ========================================
echo This setup prepares only the local MCP server.
echo Optional Internet tunnels are separate projects.
echo.

rem --------------------------------------------------
rem [1/2] Python and uv
rem --------------------------------------------------
echo [1/2] Checking Python and uv...
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
rem [2/2] Python packages and Playwright
rem --------------------------------------------------
echo [2/2] Installing Python packages...
call %UV_CMD% run --with-requirements requirements.txt python -c "import mcp; import playwright; print('Python packages OK')"
if errorlevel 1 goto dependency_error

echo Installing Playwright Chromium...
call %UV_CMD% run --with-requirements requirements.txt python -m playwright install chromium
if errorlevel 1 goto playwright_error

echo Python dependencies are ready.
echo.
echo ========================================
echo Local ProjectsMCP setup completed.
echo ========================================
echo Local endpoint after startup: http://127.0.0.1:8090/sse
echo.
echo Optional tunnel choices:
echo   ngrok      : A0_3-ProjectsMCP_Ngrok
echo   Cloudflare : A0_1/A0_2 ProjectsMCP Cloudflare Tunnel
echo.

set /p "START_NOW=Start ProjectsMCP now? [Y/N]: "
if /I "%START_NOW%"=="Y" start "ProjectsMCP Platform" "%~dp0StartProjectsMCP.bat"
goto success_end

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
