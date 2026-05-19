param(
    [string]$TaskName = "Nasdaq Traffic Light Daily Report",
    [string]$ProjectDir = "",
    [string]$Time = "23:30",
    [ValidateSet("Daily", "Weekdays")]
    [string]$Frequency = "Daily"
)

$ErrorActionPreference = "Stop"
if (-not $ProjectDir) {
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$batPath = Join-Path $ProjectDir "run_daily_report.bat"
if (-not (Test-Path $batPath)) {
    throw "Cannot find $batPath"
}

$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $ProjectDir
if ($Frequency -eq "Weekdays") {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
    $scheduleText = "Monday-Friday at $Time local time"
}
else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $scheduleText = "Every day at $Time local time"
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Generate and email Nasdaq Traffic Light macro dashboard." -Force | Out-Null

Write-Host "Scheduled task registered: $TaskName"
Write-Host "Schedule: $scheduleText"
Write-Host "Action: $batPath"
