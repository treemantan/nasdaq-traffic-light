@echo off
setlocal

cd /d "%~dp0"
set PROJECT_DIR=%CD%

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\run_portfolio_report.ps1" -ProjectDir "%PROJECT_DIR%"

if errorlevel 1 (
  echo.
  echo Portfolio report run failed. Check logs\portfolio-report-YYYY-MM-DD.log
  pause
  exit /b 1
)

echo.
echo Portfolio report generated successfully.
echo Open the latest HTML file in the output folder.
echo Log file: logs\portfolio-report-YYYY-MM-DD.log
pause
