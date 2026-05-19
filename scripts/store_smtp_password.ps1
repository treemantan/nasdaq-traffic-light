param(
    [Parameter(Mandatory=$true)]
    [string]$AppPassword,
    [string]$ProjectDir = "",
    [string]$SecurePasswordPath = "secrets\smtp_password.secure.xml"
)

$ErrorActionPreference = "Stop"
if (-not $ProjectDir) {
    $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$fullPath = Join-Path $ProjectDir $SecurePasswordPath
$dir = Split-Path $fullPath -Parent
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$clean = $AppPassword -replace "\s+", ""
$secure = ConvertTo-SecureString $clean -AsPlainText -Force
$secure | Export-Clixml -Path $fullPath

Write-Host "SMTP app password stored for the current Windows user:"
Write-Host $fullPath
Write-Host "This file is encrypted with Windows DPAPI and is not portable to another user/machine."
