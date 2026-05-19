param(
    [Parameter(Mandatory=$true)]
    [string]$AppPassword
)

$env:SMTP_PASSWORD = ($AppPassword -replace "\s+", "")
Write-Host "SMTP_PASSWORD set for this PowerShell session only."
Write-Host "Now run: .\run_daily_report.bat"
