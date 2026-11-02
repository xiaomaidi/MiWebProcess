@echo off
setlocal
cd /d "%~dp0"
where pwsh >nul 2>nul
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
) else (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
)
echo.
pause
