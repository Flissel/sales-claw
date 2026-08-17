#requires -Version 7
<#
.SYNOPSIS
  Legt die Volumes an und spielt die Saat-Konfiguration ein.
.NOTES
  Idempotent: eine bereits vorhandene openclaw.json im Volume wird NICHT
  überschrieben. Das Volume ist die Wahrheit, das Repo nur die Saat.
#>
[CmdletBinding()]
param(
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$ConfigFile  = "$PSScriptRoot\..\config\openclaw.json"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $ConfigFile)) { throw "Saat-Konfiguration nicht gefunden: $ConfigFile" }

foreach ($v in @($StateVolume, $KeysVolume)) {
    if (-not (docker volume ls --format '{{.Name}}' | Where-Object { $_ -eq $v })) {
        docker volume create $v | Out-Null
        Write-Host "Volume angelegt: $v"
    } else {
        Write-Host "Volume vorhanden: $v"
    }
}

# Prüfen, ob im Volume bereits eine Konfiguration liegt.
$vorhanden = docker run --rm -v "${StateVolume}:/state" alpine:3.20 `
    sh -c 'test -f /state/openclaw.json && echo ja || echo nein'

if ($vorhanden.Trim() -eq 'ja') {
    Write-Host "openclaw.json liegt bereits im Volume — nicht überschrieben." -ForegroundColor Yellow
    exit 0
}

$konfig = Get-Item $ConfigFile
docker run --rm -v "${StateVolume}:/state" -v "$($konfig.DirectoryName):/saat:ro" alpine:3.20 `
    sh -c "cp /saat/$($konfig.Name) /state/openclaw.json && chown 1000:1000 /state/openclaw.json"

Write-Host "Saat-Konfiguration eingespielt." -ForegroundColor Green
exit 0
