@echo off
setlocal

cd /d "%~dp0"
set PROJECT_DIR=%CD%

if "%OneDrive%"=="" (
  echo OneDrive path was not detected.
  pause
  exit /b 1
)

set INBOX_DIR=%OneDrive%\Trading\Revolut Transaction Statement
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\run_portfolio_report.ps1" -ProjectDir "%PROJECT_DIR%" -StatementDir "%INBOX_DIR%"

if errorlevel 1 (
  echo.
  echo OneDrive portfolio report run failed. Check logs\portfolio-report-YYYY-MM-DD.log
  pause
  exit /b 1
)

echo.
echo OneDrive portfolio report generated successfully.
echo Open the latest HTML file in the output folder.
pause
