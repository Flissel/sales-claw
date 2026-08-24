#requires -Version 7
<#
.SYNOPSIS
  Uebernimmt vorhandene API-Schluessel aus der lokalen OpenClaw-Konfiguration
  in die .env dieses Projekts.
.NOTES
  Schluesselwerte werden NIE ausgegeben — weder auf die Konsole, noch in ein
  Log, noch in eine Fehlermeldung. Das Skript meldet ausschliesslich, ob ein
  Schluessel gefunden wurde.
#>
[CmdletBinding()]
param(
    [string]$Quelle = "$env:USERPROFILE\.openclaw\openclaw.json",
    [string]$Ziel   = "$PSScriptRoot\..\.env"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Quelle)) { throw "Quelle nicht gefunden: $Quelle" }
$cfg = Get-Content -Raw -Encoding UTF8 $Quelle | ConvertFrom-Json

$openai = $cfg.env.OPENAI_API_KEY

$zeilen = @(
    '# Erzeugt von scripts/seed-env.ps1. Enthaelt Geheimnisse — nicht versionieren.',
    'TZ=Europe/Berlin',
    "OPENAI_API_KEY=$openai",
    'OPENAI_MODEL=gpt-5.6-luna'
)
$zielVoll = [System.IO.Path]::GetFullPath($Ziel)
Set-Content -Path $zielVoll -Value $zeilen -Encoding utf8

# Vererbte Rechte entfernen, nur der aktuelle Benutzer darf lesen und schreiben.
icacls $zielVoll /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

Write-Host ("OPENAI_API_KEY:     " + $(if ($openai)     { 'uebernommen' } else { 'NICHT gefunden' }))
Write-Host "Geschrieben nach $zielVoll"
exit 0
