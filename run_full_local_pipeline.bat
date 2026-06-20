@echo off
setlocal

cd /d "%~dp0"
set PROJECT_DIR=%CD%

REM This local pipeline mirrors the GitHub Actions data flow:
REM 1) copy local OneDrive Revolut/IBKR manual statements into .cloud-statements
REM 2) optionally download IBKR Flex data when temporary process env vars exist
REM 3) import all CSV/XML statements into portfolio.csv
REM 4) generate the market report locally without sending email
REM
REM Optional temporary env vars use the same names as GitHub Actions:
REM   IBKR_FLEX_TOKEN
REM   IBKR_ACTIVITY_QUERY_ID
REM   IBKR_ACTIVITY_LIGHT_QUERY_ID
REM   IBKR_TRADE_CONFIRM_QUERY_ID

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\run_full_local_pipeline.ps1" -ProjectDir "%PROJECT_DIR%" -ConfigPath "config.example.json"

if errorlevel 1 (
  echo.
  echo Full local pipeline failed. Check logs\full-local-pipeline-YYYY-MM-DD.log
  pause
  exit /b 1
)

echo.
echo Full local pipeline completed successfully.
echo Open the latest HTML file in the output folder.
echo Log file: logs\full-local-pipeline-YYYY-MM-DD.log
pause
