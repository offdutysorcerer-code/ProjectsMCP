@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

:START
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0CreatePortablePackage.ps1"

pause
