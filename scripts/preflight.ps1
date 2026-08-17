#requires -Version 7
<#
.SYNOPSIS
  Prüft alle Voraussetzungen, bevor am Container oder an der lokalen
  OpenClaw-Installation etwas verändert wird.
.NOTES
  Verändert nichts. Exit 0 = alles bereit, Exit 1 = mindestens eine Prüfung fehlgeschlagen.
#>
[CmdletBinding()]
param(
    [int]$GatewayPort = 18894,
    [int]$MinFreeGb   = 5
)

$ErrorActionPreference = 'Continue'
$script:Fehler = 0

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

function Pruefe {
    param([string]$Name, [scriptblock]$Test, [string]$Hinweis = '')
    try {
        $ergebnis = & $Test
        if ($ergebnis) { Write-Host "[OK]     $Name" -ForegroundColor Green }
        else {
            Write-Host "[FEHLER] $Name" -ForegroundColor Red
            if ($Hinweis) { Write-Host "         $Hinweis" -ForegroundColor Yellow }
            $script:Fehler++
        }
    } catch {
        Write-Host "[FEHLER] $Name — $($_.Exception.Message)" -ForegroundColor Red
        if ($Hinweis) { Write-Host "         $Hinweis" -ForegroundColor Yellow }
        $script:Fehler++
    }
}

Write-Host "== Preflight sales-claw ==" -ForegroundColor Cyan

Pruefe "Docker-Daemon erreichbar" {
    $null = docker version --format '{{.Server.Version}}' 2>$null
    $LASTEXITCODE -eq 0
} "Docker Desktop starten."

Pruefe "Gateway-Port $GatewayPort ist frei" {
    Test-PortFrei -Port $GatewayPort
} "Anderen Port wählen oder belegenden Prozess beenden."

Pruefe "mindestens $MinFreeGb GB frei auf C:" {
    $frei = (Get-PSDrive -Name C).Free / 1GB
    Write-Host ("         frei: {0:N1} GB" -f $frei) -ForegroundColor DarkGray
    $frei -ge $MinFreeGb
} "Docker-Image und Volumes brauchen Platz; C: war hier schon zweimal knapp."

Pruefe "lokales OpenClaw-Zustandsverzeichnis vorhanden" {
    Test-Path "$env:USERPROFILE\.openclaw\openclaw.json"
} "Ohne die lokale Installation gibt es keine Kopplung zum Übernehmen."

Pruefe "WhatsApp-Kopplung lokal vorhanden" {
    Test-Path "$env:USERPROFILE\.openclaw\credentials\whatsapp"
} "Ohne credentials/whatsapp muss im Container per QR neu gepairt werden."

Pruefe "Image-Tag in der Registry abrufbar" {
    $null = docker manifest inspect ghcr.io/openclaw/openclaw:2026.7.1-slim 2>$null
    $LASTEXITCODE -eq 0
} "Netzwerk prüfen oder Tag korrigieren."

Pruefe "kein fremder Container belegt den Namen sales-claw" {
    # Exakter Filter. Docker filtert sonst per Teilzeichenkette, wodurch die
    # Pruefung Container mitzaehlt, die uns nichts angehen.
    -not (docker ps -a --filter "name=^sales-claw$" --format '{{.Names}}')
} "Es existiert bereits ein Container namens sales-claw — Namenskollision klaeren, bevor irgendetwas gestartet wird."

Pruefe "openclaw-festival gehoert nicht zu unserem Compose-Projekt" {
    # Das ist die reale Gefahr: traegt ein fremder Container unser
    # Compose-Projektlabel, raeumt ihn ein 'docker compose down' in diesem
    # Verzeichnis mit ab. Existiert er nicht, kann nichts kollidieren.
    $festival = docker ps -a --filter "name=^openclaw-festival$" --format '{{.Names}}'
    if (-not $festival) { return $true }
    $projekt = docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' openclaw-festival
    $projekt -ne 'sales-claw'
} "openclaw-festival traegt unser Compose-Projektlabel — 'docker compose down' wuerde ihn mit abraeumen."

Write-Host ""
if ($script:Fehler -gt 0) {
    Write-Host "$($script:Fehler) Prüfung(en) fehlgeschlagen." -ForegroundColor Red
    exit 1
}
Write-Host "Alle Prüfungen bestanden." -ForegroundColor Green
exit 0
