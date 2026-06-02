param(
    [string]$ProjectDir = "",
    [string]$StatementDir = "",
    [string]$StatementPattern = "*.csv",
    [string]$ConfigPath = "config.example.json",
    [string]$LogDir = "logs",
    [switch]$UseLatestPerAccountFolder
)

$ErrorActionPreference = "Stop"
if (-not $ProjectDir) {
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
else {
    $ProjectDir = (Resolve-Path $ProjectDir).Path
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
        $lines += "Mode: local-portfolio | StatementPattern: $StatementPattern"
    }
    else {
        $lines += "Status: $Status | DurationSeconds: $duration"
        if ($ReportPath) { $lines += "Report: $ReportPath" }
    }
    $lines += $separator
    Add-Content -Path $script:LogFile -Value $lines -Encoding UTF8
    foreach ($line in $lines) { Write-Host $line }
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
$script:LogFile = Join-Path $fullLogDir ("portfolio-report-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
$script:StatusFile = Join-Path $fullLogDir "portfolio-report-status.txt"
$script:LockFile = Join-Path $fullLogDir "portfolio-report.lock"
$script:RunStartedAt = Get-Date
$script:RunId = "{0}-local-portfolio" -f $script:RunStartedAt.ToString("yyyyMMdd-HHmmss-fff")
$script:RunStatus = "FAILED"
$script:LatestReportPath = ""

function Write-Status {
    param(
        [string]$Status,
        [string]$Message
    )
    $line = "{0} [{1}] [run_id={2}] {3}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Status, $script:RunId, $Message
    Set-Content -Path $script:StatusFile -Value $line -Encoding UTF8
}

Write-RunBoundary "START"
try {
    $script:LockHandle = [System.IO.File]::Open(
        $script:LockFile,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
}
catch [System.IO.IOException] {
    Write-Log "Another portfolio report run is already active. Skipping this duplicate launch." "WARN"
    Write-Status "SKIPPED_BUSY" "Another portfolio report run is already active."
    $script:RunStatus = "SKIPPED_BUSY"
    Write-RunBoundary "END" $script:RunStatus
    exit 0
}

Write-Log "Starting local portfolio import and report generation."
Write-Status "RUNNING" "Importing the latest OneDrive CSV and generating the report."
Write-Log "ProjectDir=$ProjectDir"
if ($StatementDir) {
    Write-Log "StatementDir=$StatementDir"
}
Write-Log "StatementPattern=$StatementPattern"

try {
    if ($StatementDir -and -not (Test-Path -LiteralPath $StatementDir)) {
        throw "Revolut statement inbox does not exist: $StatementDir"
    }

    if ($StatementDir -and $UseLatestPerAccountFolder) {
        $accountFolders = @(Get-ChildItem -LiteralPath $StatementDir -Directory | Sort-Object Name)
        $statementFiles = @(
            foreach ($folder in $accountFolders) {
                $latest = Get-ChildItem -LiteralPath $folder.FullName -File -Filter $StatementPattern |
                    Sort-Object LastWriteTime -Descending |
                    Select-Object -First 1
                if ($latest) {
                    Write-Log ("Account inbox {0}: selected latest export {1}" -f $folder.Name, $latest.Name)
                    $latest
                }
            }
        )
        if ($statementFiles.Count -eq 0) {
            Write-Log "No statement found inside account folders; checking the inbox root for compatibility." "WARN"
            $statementFiles = @(Get-ChildItem -LiteralPath $StatementDir -File -Filter $StatementPattern | Sort-Object LastWriteTime -Descending)
        }
    }
    else {
        $searchDir = if ($StatementDir) { $StatementDir } else { $ProjectDir }
        $statementFiles = @(Get-ChildItem -LiteralPath $searchDir -File -Filter $StatementPattern | Sort-Object Name)
    }

    if ($statementFiles.Count -eq 0) {
        throw "No Revolut statement CSV found. Save the latest Revolut CSV export into the configured inbox."
    }

    $uniqueStatements = @(
        $statementFiles |
            Group-Object { (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash } |
            ForEach-Object { $_.Group | Select-Object -First 1 }
    )
    Write-Log ("Found {0} statement CSV file(s); importing {1} unique file(s)." -f $statementFiles.Count, $uniqueStatements.Count)
    foreach ($statement in $uniqueStatements) {
        Write-Log ("Statement: {0}" -f $statement.Name)
    }
    if ($StatementDir -and $UseLatestPerAccountFolder) {
        Write-Log "Using only the latest export from each account folder to avoid double counting overlapping statement windows."
    }
    else {
        Write-Log "Overlapping statement exports are allowed. The importer deduplicates identical transaction rows before rebuilding positions."
    }

    $importArgs = @("scripts\import_revolut_statement.py") + @($uniqueStatements | ForEach-Object { $_.FullName })
    $importExitCode = Invoke-LoggedProcess -FileName "python" -Arguments $importArgs
    if ($importExitCode -ne 0) {
        throw "Portfolio importer exited with code $importExitCode"
    }

    $runner = Join-Path $ProjectDir "scripts\run_market_report.ps1"
    $reportArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $runner,
        "-ProjectDir", $ProjectDir,
        "-ConfigPath", $ConfigPath,
        "-ParentRunId", $script:RunId,
        "-DryRun"
    )
    $reportExitCode = Invoke-LoggedProcess -FileName "powershell.exe" -Arguments $reportArgs
    if ($reportExitCode -ne 0) {
        throw "Market report runner exited with code $reportExitCode"
    }

    $latestReport = Get-ChildItem -Path (Join-Path $ProjectDir "output") -File -Filter "market-report-*.html" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestReport) {
        $script:LatestReportPath = $latestReport.FullName
        Write-Log ("Latest HTML report: {0}" -f $latestReport.FullName)
    }
    $script:RunStatus = "SUCCESS"
    Write-Log "Local portfolio report completed successfully."
    Write-Status "SUCCESS" ("Latest HTML report: {0}" -f $latestReport.FullName)
    exit 0
}
catch {
    Write-Log $_.Exception.Message "ERROR"
    Write-Log "Local portfolio report failed." "ERROR"
    Write-Status "FAILED" $_.Exception.Message
    exit 1
}
finally {
    if ($script:LockHandle) {
        $script:LockHandle.Dispose()
    }
    Write-RunBoundary "END" $script:RunStatus $script:LatestReportPath
}
