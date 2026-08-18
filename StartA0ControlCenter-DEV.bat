@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem Launch the Control Center against the isolated DEV runtime/profile.
if not defined SystemRoot set "SystemRoot=C:\Windows"
if not defined WINDIR set "WINDIR=%SystemRoot%"
if not defined ProgramData set "ProgramData=C:\ProgramData"
if not defined ProgramFiles set "ProgramFiles=C:\Program Files"
if not defined ProgramFiles(x86) set "ProgramFiles(x86)=C:\Program Files (x86)"
if not defined TMP set "TMP=%TEMP%"
set "A0_PROJECTSMCP_ROOT=%~dp0"
set "A0_PROJECTSMCP_ENVIRONMENT=DEV"
set "PROJECTSMCP_ENVIRONMENT=DEV"
set "PROJECTSMCP_CONFIG_PATH=%~dp0config.dev.json"
set "PROJECTSMCP_ARTIFACTS_DIR=%~dp0artifacts\dev"

dotnet run --project "%~dp0A0.ControlCenter\A0.ControlCenter.csproj"
endlocal
