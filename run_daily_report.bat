@echo off
setlocal

cd /d "%~dp0"
set PROJECT_DIR=%CD%

REM SMTP password is loaded from secrets\smtp_password.secure.xml if present.
REM To create it, run:
REM   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\store_smtp_password.ps1 -AppPassword "your_app_password"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\run_market_report.ps1" -ProjectDir "%PROJECT_DIR%" -ConfigPath "config.email.json"

if errorlevel 1 (
  echo.
  echo Macro Regime Radar run failed. Check logs\market-report-YYYY-MM-DD.log
  pause
  exit /b 1
)

echo.
echo Macro Regime Radar report sent successfully.
echo Log file: logs\market-report-YYYY-MM-DD.log
pause
