param(
    [string]$ProjectDir = "",
    [string]$ConfigPath = "config.example.json",
    [string]$LogDir = "logs",
    [string]$CloudStatementDir = ".cloud-statements",
    [string]$LocalEnvPath = "secrets\local_pipeline.env",
    [string]$RevolutStatementDir = "",
    [string]$IbkrStatementDir = "",
    [string]$RevolutPattern = "*.csv",
    [string]$IbkrPatterns = "*.csv,*.xml",
    [string]$IbkrActivityQueryId = "1531778",
    [string]$IbkrActivityLightQueryId = "",
    [string]$IbkrTradeConfirmQueryId = "1535495",
    [switch]$SendEmail
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
        $lines += "Mode: full-local-pipeline | SendEmail: $([bool]$SendEmail)"
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
        [string[]]$Arguments,
        [switch]$AllowFailure
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

    if ($process.ExitCode -ne 0 -and -not $AllowFailure) {
        throw "$FileName exited with code $($process.ExitCode)"
    }
    return $process.ExitCode
}

function Copy-LatestStatements {
    param(
        [string]$SourceDir,
        [string[]]$Patterns,
        [string]$DestinationDir,
        [string]$Label
    )

    if (-not $SourceDir -or -not (Test-Path -LiteralPath $SourceDir)) {
        Write-Log "$Label statement folder not found; skipping: $SourceDir" "WARN"
        return
    }

    $files = @()
    foreach ($pattern in $Patterns) {
        $files += @(Get-ChildItem -LiteralPath $SourceDir -File -Filter $pattern.Trim() | Sort-Object LastWriteTime -Descending)
    }
    $files = @($files | Sort-Object FullName -Unique)
    if ($files.Count -eq 0) {
        Write-Log "$Label statement folder has no matching files: $SourceDir" "WARN"
        return
    }

    foreach ($file in $files) {
        $target = Join-Path $DestinationDir $file.Name
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        Write-Log ("Copied {0} statement: {1}" -f $Label, $file.Name)
    }
}

function Get-EnvValue {
    param([string]$Name)
    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($null -eq $value) {
        return ""
    }
    return $value
}

function Set-ProcessEnvIfMissing {
    param(
        [string]$Name,
        [string]$Value
    )
    if ((-not (Get-EnvValue $Name)) -and $Value) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
}

function Import-LocalEnvFile {
    param([string]$Path)
    if (-not $Path) {
        return
    }

    $resolvedPath = $Path
    if (-not [System.IO.Path]::IsPathRooted($resolvedPath)) {
        $resolvedPath = Join-Path $ProjectDir $resolvedPath
    }
    if (-not (Test-Path -LiteralPath $resolvedPath)) {
        Write-Log "Local env file not found; using process environment only: $resolvedPath" "WARN"
        return
    }

    foreach ($line in Get-Content -LiteralPath $resolvedPath -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($name -and $value) {
            Set-ProcessEnvIfMissing -Name $name -Value $value
        }
    }
    Write-Log "Loaded local pipeline env file for this process only: $resolvedPath"
}

Set-Location $ProjectDir
$fullLogDir = Join-Path $ProjectDir $LogDir
New-Item -ItemType Directory -Force -Path $fullLogDir | Out-Null
$script:LogFile = Join-Path $fullLogDir ("full-local-pipeline-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
$script:RunStartedAt = Get-Date
$script:RunId = "{0}-full-local" -f $script:RunStartedAt.ToString("yyyyMMdd-HHmmss-fff")
$script:RunStatus = "FAILED"
$script:LatestReportPath = ""

Write-RunBoundary "START"
Write-Log "Starting local pipeline aligned with GitHub Actions."
Write-Log "ProjectDir=$ProjectDir"
Write-Log "ConfigPath=$ConfigPath"

try {
    Import-LocalEnvFile -Path $LocalEnvPath
    Set-ProcessEnvIfMissing -Name "IBKR_ACTIVITY_QUERY_ID" -Value $IbkrActivityQueryId
    Set-ProcessEnvIfMissing -Name "IBKR_ACTIVITY_LIGHT_QUERY_ID" -Value $IbkrActivityLightQueryId
    Set-ProcessEnvIfMissing -Name "IBKR_TRADE_CONFIRM_QUERY_ID" -Value $IbkrTradeConfirmQueryId

    $statementDir = Join-Path $ProjectDir $CloudStatementDir
    New-Item -ItemType Directory -Force -Path $statementDir | Out-Null

    if (-not $RevolutStatementDir -and $env:OneDrive) {
        $RevolutStatementDir = Join-Path $env:OneDrive "Trading\Revolut Transaction Statement"
    }
    if (-not $IbkrStatementDir -and $env:OneDrive) {
        $IbkrStatementDir = Join-Path $env:OneDrive "Trading\IBKR Transaction Statement"
    }

    Copy-LatestStatements -SourceDir $RevolutStatementDir -Patterns @($RevolutPattern) -DestinationDir $statementDir -Label "Revolut"
    Copy-LatestStatements -SourceDir $IbkrStatementDir -Patterns ($IbkrPatterns -split ",") -DestinationDir $statementDir -Label "IBKR manual"

    if ($env:IBKR_FLEX_TOKEN) {
        Write-Log "IBKR_FLEX_TOKEN is present for this process; attempting IBKR Flex download."
        $downloadArgs = @(
            "scripts\download_ibkr_flex.py",
            "--output-dir", $statementDir,
            "--activity-query-id", (Get-EnvValue "IBKR_ACTIVITY_QUERY_ID"),
            "--activity-light-query-id", (Get-EnvValue "IBKR_ACTIVITY_LIGHT_QUERY_ID"),
            "--trade-confirm-query-id", (Get-EnvValue "IBKR_TRADE_CONFIRM_QUERY_ID"),
            "--query-delay-seconds", "30",
            "--transient-retries", "0",
            "--transient-wait-seconds", "0"
        )
        Invoke-LoggedProcess -FileName "python" -Arguments $downloadArgs -AllowFailure | Out-Null
    }
    else {
        Write-Log "IBKR_FLEX_TOKEN is not set in this process; skipping live IBKR Flex download and using manual OneDrive files if present." "WARN"
    }

    $statements = @(Get-ChildItem -LiteralPath $statementDir -File |
        Where-Object { $_.Extension.ToLowerInvariant() -in @(".csv", ".xml") } |
        Sort-Object Name)
    if ($statements.Count -gt 0) {
        Write-Log ("Importing {0} downloaded/manual portfolio statement file(s)." -f $statements.Count)
        $diagnostics = Join-Path $statementDir "ibkr-flex-diagnostics.json"
        $importArgs = @("scripts\import_portfolio_statements.py")
        if (Test-Path -LiteralPath $diagnostics) {
            $importArgs += @("--ibkr-diagnostics", $diagnostics)
        }
        $importArgs += @($statements | ForEach-Object { $_.FullName })
        Invoke-LoggedProcess -FileName "python" -Arguments $importArgs | Out-Null
    }
    else {
        Write-Log "No local/cloud statement files found; report will be generated without updating portfolio.csv." "WARN"
    }

    $runner = Join-Path $ProjectDir "scripts\run_market_report.ps1"
    $reportArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $runner,
        "-ProjectDir", $ProjectDir,
        "-ConfigPath", $ConfigPath,
        "-ParentRunId", $script:RunId
    )
    if (-not $SendEmail) {
        $reportArgs += "-DryRun"
    }
    Invoke-LoggedProcess -FileName "powershell.exe" -Arguments $reportArgs | Out-Null

    $latestReport = Get-ChildItem -Path (Join-Path $ProjectDir "output") -File -Filter "market-report-*.html" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestReport) {
        $script:LatestReportPath = $latestReport.FullName
        Write-Log ("Latest HTML report: {0}" -f $latestReport.FullName)
    }
    $script:RunStatus = "SUCCESS"
    Write-Log "Full local pipeline completed successfully."
    exit 0
}
catch {
    Write-Log $_.Exception.Message "ERROR"
    Write-Log "Full local pipeline failed." "ERROR"
    exit 1
}
finally {
    Write-RunBoundary "END" $script:RunStatus $script:LatestReportPath
}
