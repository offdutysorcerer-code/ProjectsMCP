@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem Some MCP-launched child processes inherit a reduced environment.
if not defined SystemRoot set "SystemRoot=C:\Windows"
if not defined WINDIR set "WINDIR=%SystemRoot%"
if not defined ProgramData set "ProgramData=C:\ProgramData"
if not defined ProgramFiles set "ProgramFiles=C:\Program Files"
if not defined ProgramFiles(x86) set "ProgramFiles(x86)=C:\Program Files (x86)"
if not defined TMP set "TMP=%TEMP%"
set "A0_PROJECTSMCP_ROOT=%~dp0"

dotnet run --project "%~dp0A0.ControlCenter\A0.ControlCenter.csproj"
endlocal
