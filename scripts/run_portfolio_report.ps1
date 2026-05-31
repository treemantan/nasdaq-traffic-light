param(
    [string]$ProjectDir = "",
    [string]$StatementDir = "",
    [string]$StatementPattern = "trading-account-statement_*.csv",
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
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -Path $script:LogFile -Value $line -Encoding UTF8
    Write-Host $line
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

Write-Log "Starting local portfolio import and report generation."
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
        throw "No Revolut statement CSV found. Save the latest trading-account-statement_*.csv export into the configured inbox."
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
        Write-Log "Keep only one latest export per investment account in the statement directory to avoid double counting overlapping exports." "WARN"
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
        Write-Log ("Latest HTML report: {0}" -f $latestReport.FullName)
    }
    Write-Log "Local portfolio report completed successfully."
    exit 0
}
catch {
    Write-Log $_.Exception.Message "ERROR"
    Write-Log "Local portfolio report failed." "ERROR"
    exit 1
}
