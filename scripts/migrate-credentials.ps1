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

# ---------------------------------------------------------------------------
# Erlaubnisliste statt Muster — dieselbe Begruendung wie in backup-state.ps1
# und restore-state.ps1, die hier bisher fehlte. Dieses Skript mountet ein
# Volume SCHREIBEND und fuehrt darin `chown -R` aus. Ein Tippfehler im
# Volumenamen legte bisher still ein neues Volume an und schrieb die
# Credentials dorthin; auf dieser Maschine liegt ausserdem
# `openclaw-festival-state` daneben, das einem fremden Vorhaben gehoert.
# Gross-/Kleinschreibung zaehlt (-cne): fuer Docker ist SALES-CLAW-STATE ein
# anderer Name.
# ---------------------------------------------------------------------------
if ($StateVolume -cne 'sales-claw-state') {
    throw "Verweigert: '$StateVolume' ist nicht das Zustands-Volume dieses Projekts."
}
if ($Container -cne 'sales-claw') {
    throw "Verweigert: '$Container' ist nicht der Container dieses Projekts."
}

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

# Die Quelle kommt von einem Windows-Bind-Mount und traegt dessen synthetische
# Rechte (0777) ins Volume — `cp -a` erhaelt sie. Der Eigentuemer allein reicht
# also nicht: gesetzt werden auch die Rechte, 0700 fuer Verzeichnisse und 0600
# fuer Dateien, wie OpenClaw es fuer seine eigenen sensiblen Pfade tut.
#
# Warum das hier zaehlt: nicht als Gefahrenabwehr in dieser Aufstellung — das
# Volume liegt in der Docker-Desktop-VM, uid 1000 besitzt die Dateien ohnehin.
# Die Rechte wandern aber beim Umzug auf die Proxmox-VM mit, wo andere UIDs
# existieren. Es geht um Portabilitaet und Konsistenz.
$elternVoll = (Resolve-Path (Split-Path $quelle -Parent)).Path
docker run --rm -v "${StateVolume}:/state" -v "${elternVoll}:/quelle:ro" alpine:3.20 `
    sh -c 'mkdir -p /state/credentials && cp -a /quelle/whatsapp /state/credentials/ && chown -R 1000:1000 /state/credentials && find /state/credentials -type d -exec chmod 700 {} + && find /state/credentials -type f -exec chmod 600 {} +'
if ($LASTEXITCODE -ne 0) { throw "Kopieren der Credentials fehlgeschlagen" }

# `test -d` meldete auch dann Erfolg, wenn das Verzeichnis leer war oder die
# Kopie mittendrin abbrach — bei 8003 Session-Dateien ist das der Unterschied
# zwischen einer uebernommenen und einer zerrissenen Kopplung. Verglichen wird
# deshalb die Dateizahl von Quelle und Ziel.
$sollAnzahl = (Get-ChildItem -Recurse -File $quelle).Count
$istAnzahl = docker run --rm -v "${StateVolume}:/state:ro" alpine:3.20 `
    sh -c 'find /state/credentials/whatsapp -type f | wc -l'
if ($LASTEXITCODE -ne 0) { throw "Nachzaehlen im Volume fehlgeschlagen — Uebernahme nicht bestaetigt." }
if ([int]$istAnzahl.Trim() -ne $sollAnzahl) {
    throw "Uebernahme unvollstaendig: $($istAnzahl.Trim()) von $sollAnzahl Dateien im Volume."
}
Write-Host "Uebernahme geprueft: $sollAnzahl Dateien."

Write-Host "WhatsApp-Kopplung ins Volume uebernommen." -ForegroundColor Green
exit 0
