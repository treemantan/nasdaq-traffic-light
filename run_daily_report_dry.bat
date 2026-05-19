@echo off
setlocal

cd /d "%~dp0"
set PROJECT_DIR=%CD%

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\run_market_report.ps1" -ProjectDir "%PROJECT_DIR%" -ConfigPath "config.example.json" -DryRun

if errorlevel 1 (
  echo.
  echo Nasdaq Traffic Light dry run failed. Check logs\market-report-YYYY-MM-DD.log
  pause
  exit /b 1
)

echo.
echo Nasdaq Traffic Light dry run completed successfully.
pause
