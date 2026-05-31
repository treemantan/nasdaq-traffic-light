@echo off
setlocal

cd /d "%~dp0"
set PROJECT_DIR=%CD%

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\setup_onedrive_portfolio_inbox.ps1" -ProjectDir "%PROJECT_DIR%"

if errorlevel 1 (
  echo.
  echo OneDrive portfolio inbox setup failed.
  pause
  exit /b 1
)

echo.
echo OneDrive portfolio inbox setup completed successfully.
pause
