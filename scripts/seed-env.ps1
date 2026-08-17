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

# Den OpenRouter-Schluessel am Praefix erkennen, nicht am Ablageort: in dieser
# Installation liegt er unter einem Skill-Eintrag, dessen Name ihn nicht
# erwarten laesst. Das Praefix ist das verlaessliche Merkmal.
$openrouter = $null
foreach ($e in $cfg.skills.entries.PSObject.Properties) {
    if ($e.Value.apiKey -is [string] -and $e.Value.apiKey.StartsWith('sk-or-v1-')) {
        $openrouter = $e.Value.apiKey
        break
    }
}
$openai = $cfg.env.OPENAI_API_KEY

$zeilen = @(
    '# Erzeugt von scripts/seed-env.ps1. Enthaelt Geheimnisse — nicht versionieren.',
    'TZ=Europe/Berlin',
    "OPENROUTER_API_KEY=$openrouter",
    "OPENAI_API_KEY=$openai"
)
$zielVoll = [System.IO.Path]::GetFullPath($Ziel)
Set-Content -Path $zielVoll -Value $zeilen -Encoding utf8

# Vererbte Rechte entfernen, nur der aktuelle Benutzer darf lesen und schreiben.
icacls $zielVoll /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

Write-Host ("OPENROUTER_API_KEY: " + $(if ($openrouter) { 'uebernommen' } else { 'NICHT gefunden' }))
Write-Host ("OPENAI_API_KEY:     " + $(if ($openai)     { 'uebernommen' } else { 'NICHT gefunden' }))
Write-Host "Geschrieben nach $zielVoll"
exit 0
