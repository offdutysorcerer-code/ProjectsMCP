@echo off
chcp 65001 >nul
title Setup ProjectsMCP Platform

cd /d "%~dp0"

echo Setting up ProjectsMCP Platform dependencies...
echo.

where uv >nul 2>&1
if errorlevel 1 goto install_uv

echo [1/2] Installing Python packages from requirements.txt through uv...
uv run --with-requirements requirements.txt python -c "import mcp; import playwright; print('Python packages OK')"
if errorlevel 1 goto error

goto playwright

:install_uv
echo uv was not found in PATH.
echo Installing uv for the current Windows user through Python...
echo.

python --version >nul 2>&1
if errorlevel 1 goto python_error

python -m pip install --user uv
if errorlevel 1 goto uv_error

echo.
echo uv was installed successfully.
echo Continuing setup through python -m uv...
echo.

echo [1/2] Installing Python packages from requirements.txt through uv...
python -m uv run --with-requirements requirements.txt python -c "import mcp; import playwright; print('Python packages OK')"
if errorlevel 1 goto error

:playwright
echo.
echo [2/2] Installing Playwright Chromium through uv...
where uv >nul 2>&1
if errorlevel 1 (
    python -m uv run --with-requirements requirements.txt python -m playwright install chromium
) else (
    uv run --with-requirements requirements.txt python -m playwright install chromium
)
if errorlevel 1 goto error

echo.
echo Setup completed.
goto end

:python_error
echo.
echo Python was not found.
echo Please install Python first, then run SetupProjectsMCP.bat again.
goto end

:uv_error
echo.
echo Failed to install uv automatically.
echo Please check that Python and pip are installed correctly, then try:
echo python -m pip install --user uv
goto end

:error
echo.
echo Setup failed. Please check the error message above.

:end
echo.
pause
