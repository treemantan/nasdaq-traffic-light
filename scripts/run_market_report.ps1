param(
    [string]$ProjectDir = "",
    [string]$ConfigPath = "config.email.json",
    [string]$LogDir = "logs",
    [string]$SecurePasswordPath = "secrets\smtp_password.secure.xml",
    [string]$ParentRunId = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
if (-not $ProjectDir) {
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Write-Log {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    $line = "{0} [{1}] [run_id={2}] {3}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $script:RunId, $Message
    Add-Content -Path $script:LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Write-RunBoundary {
    param(
        [string]$Boundary,
        [string]$Status = "",
        [string]$ReportPath = ""
    )
    $separator = "=" * 96
    $duration = [math]::Round(((Get-Date) - $script:RunStartedAt).TotalSeconds, 1)
    $lines = @("", $separator, ("RUN {0} | {1} | run_id={2}" -f $Boundary, (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $script:RunId))
    if ($Boundary -eq "START") {
        $lines += "Mode: market-report | DryRun: $([bool]$DryRun) | ParentRunId: $($script:ParentRunIdLabel)"
    }
    else {
        $lines += "Status: $Status | DurationSeconds: $duration"
        if ($ReportPath) { $lines += "Report: $ReportPath" }
    }
    $lines += $separator
    Add-Content -Path $script:LogFile -Value $lines -Encoding UTF8
    foreach ($line in $lines) { Write-Host $line }
}

function Set-SmtpPasswordFromSecureFile {
    param([string]$Path)

    if ($env:SMTP_PASSWORD) {
        return
    }
    if (-not (Test-Path $Path)) {
        return
    }

    $secure = Import-Clixml -Path $Path
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $env:SMTP_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Invoke-LoggedProcess {
    param(
        [string]$FileName,
        [string[]]$Arguments
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = ($Arguments | ForEach-Object {
        if ($_ -match '\s|"' ) {
            '"' + ($_ -replace '"', '\"') + '"'
        }
        else {
            $_
        }
    }) -join " "
    $psi.WorkingDirectory = (Get-Location).Path
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    foreach ($line in ($stdout -split "`r?`n")) {
        if ($line) { Write-Log $line }
    }
    foreach ($line in ($stderr -split "`r?`n")) {
        if ($line) { Write-Log $line "ERROR" }
    }

    return $process.ExitCode
}

Set-Location $ProjectDir
$fullLogDir = Join-Path $ProjectDir $LogDir
New-Item -ItemType Directory -Force -Path $fullLogDir | Out-Null
$script:LogFile = Join-Path $fullLogDir ("market-report-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
$script:RunStartedAt = Get-Date
$script:RunId = "{0}-market-report" -f $script:RunStartedAt.ToString("yyyyMMdd-HHmmss-fff")
$script:ParentRunIdLabel = if ($ParentRunId) { $ParentRunId } else { "none" }
$script:RunStatus = "FAILED"
$script:LatestReportPath = ""

Write-RunBoundary "START"
Write-Log "Starting Macro Regime Radar report."
Write-Log "ProjectDir=$ProjectDir"
Write-Log "ConfigPath=$ConfigPath"

try {
    $securePath = Join-Path $ProjectDir $SecurePasswordPath
    Set-SmtpPasswordFromSecureFile -Path $securePath

    if (-not $env:SMTP_PASSWORD) {
        Write-Log "SMTP password not found in env var or secure file. If this is not a dry run, email sending may fail." "WARN"
    }

    $python = "python"
    $args = @("-m", "market_report", "--config", $ConfigPath)
    if ($DryRun) {
        $args += "--dry-run"
    }

    Write-Log ("Running: {0} {1}" -f $python, ($args -join " "))
    $exitCode = Invoke-LoggedProcess -FileName $python -Arguments $args

    if ($exitCode -ne 0) {
        throw "market_report exited with code $exitCode"
    }

    $latestReport = Get-ChildItem -Path (Join-Path $ProjectDir "output") -File -Filter "market-report-*.html" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestReport) {
        $script:LatestReportPath = $latestReport.FullName
    }
    $script:RunStatus = "SUCCESS"
    Write-Log "Report run completed successfully."
    exit 0
}
catch {
    Write-Log $_.Exception.Message "ERROR"
    if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
        Write-Log $_.InvocationInfo.PositionMessage "ERROR"
    }
    Write-Log "Report run failed." "ERROR"
    exit 1
}
finally {
    Write-RunBoundary "END" $script:RunStatus $script:LatestReportPath
}
