param(
    [string]$ProjectDir = "",
    [string]$InboxDir = "",
    [string]$TaskName = "Macro Regime Radar OneDrive Portfolio Import",
    [string]$Time = "21:30",
    [ValidateSet("Daily", "Weekdays")]
    [string]$Frequency = "Weekdays"
)

$ErrorActionPreference = "Stop"
if (-not $ProjectDir) {
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
else {
    $ProjectDir = (Resolve-Path $ProjectDir).Path
}
if (-not $InboxDir) {
    if (-not $env:OneDrive) {
        throw "OneDrive path was not detected. Pass -InboxDir explicitly."
    }
    $InboxDir = Join-Path $env:OneDrive "Trading\Revolut Transaction Statement"
}

New-Item -ItemType Directory -Force -Path $InboxDir | Out-Null

$runner = Join-Path $ProjectDir "scripts\run_portfolio_report.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Cannot find $runner"
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-File", ('"{0}"' -f $runner),
    "-ProjectDir", ('"{0}"' -f $ProjectDir),
    "-StatementDir", ('"{0}"' -f $InboxDir)
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $ProjectDir
if ($Frequency -eq "Weekdays") {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
    $scheduleText = "Monday-Friday at $Time local time"
}
else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $scheduleText = "Every day at $Time local time"
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Import the latest Revolut CSV from the OneDrive inbox and refresh the local Macro Regime Radar report." `
    -Force | Out-Null

Write-Host "OneDrive Revolut inbox is ready."
Write-Host "Inbox folder: $InboxDir"
Write-Host "Scheduled task registered: $TaskName"
Write-Host "Schedule: $scheduleText"
Write-Host ""
Write-Host "On your phone, save each new Revolut statement into the OneDrive inbox folder."
Write-Host "Keep only the latest export for each account in the inbox to avoid overlapping statement windows."
