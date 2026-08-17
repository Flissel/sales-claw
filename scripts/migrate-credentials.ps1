#requires -Version 7
<#
.SYNOPSIS
  Uebertraegt die WhatsApp-Kopplung von der lokalen Installation ins Volume.
.NOTES
  Setzt voraus, dass der lokale Gateway steht (stop-local-openclaw.ps1) und
  der Container gestoppt ist.
#>
[CmdletBinding()]
param(
    [string]$LokalerZustand = "$env:USERPROFILE\.openclaw",
    [string]$StateVolume    = 'sales-claw-state',
    [string]$Container      = 'sales-claw',
    [int]$LokalerPort       = 18793
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

$quelle = Join-Path $LokalerZustand 'credentials\whatsapp'
if (-not (Test-Path $quelle)) { throw "Keine WhatsApp-Kopplung unter $quelle" }

if (-not (Test-PortFrei -Port $LokalerPort)) {
    throw "Lokaler Gateway lauscht noch auf $LokalerPort. Erst stop-local-openclaw.ps1 ausfuehren."
}
if (docker ps --filter "name=$Container" --format '{{.Names}}' | Where-Object { $_ -eq $Container }) {
    throw "Container '$Container' laeuft. Erst 'docker compose down' ausfuehren."
}

$sicherung = Join-Path (Split-Path $PSScriptRoot -Parent) "credentials-sicherung-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -Recurse -Path (Join-Path $LokalerZustand 'credentials') -Destination $sicherung
Write-Host "Sicherung angelegt: $sicherung"

$elternVoll = (Resolve-Path (Split-Path $quelle -Parent)).Path
docker run --rm -v "${StateVolume}:/state" -v "${elternVoll}:/quelle:ro" alpine:3.20 `
    sh -c 'mkdir -p /state/credentials && cp -a /quelle/whatsapp /state/credentials/ && chown -R 1000:1000 /state/credentials'
if ($LASTEXITCODE -ne 0) { throw "Kopieren der Credentials fehlgeschlagen" }

$pruef = docker run --rm -v "${StateVolume}:/state:ro" alpine:3.20 `
    sh -c 'test -d /state/credentials/whatsapp && echo ja || echo nein'
if ($pruef.Trim() -ne 'ja') { throw "Credentials liegen nach dem Kopieren nicht im Volume" }

Write-Host "WhatsApp-Kopplung ins Volume uebernommen." -ForegroundColor Green
exit 0
