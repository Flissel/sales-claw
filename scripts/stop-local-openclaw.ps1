#requires -Version 7
<#
.SYNOPSIS
  Stoppt den lokalen OpenClaw-Gateway und weist nach, dass er wirklich steht.
.NOTES
  Zwei gleichzeitige Baileys-Sitzungen auf denselben Credentials melden das
  verknuepfte Geraet ab. Stillstand wird deshalb geprueft, nicht angenommen.
#>
[CmdletBinding()]
param([int]$LokalerPort = 18793)

$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

Write-Host "Dienststatus vorher:"
openclaw daemon status 2>&1 | Write-Host

Write-Host "Stoppe Gateway-Dienst…"
openclaw daemon stop 2>&1 | Write-Host

Start-Sleep -Seconds 3

# Die Entscheidung faellt ueber Test-PortFrei — dort wird ein Abfragefehler
# geworfen statt als "frei" durchgewinkt. Get-NetTCPConnection kommt nur noch
# fuer die Diagnose zum Einsatz, wenn ohnehin feststeht, dass etwas lauscht.
if (-not (Test-PortFrei -Port $LokalerPort)) {
    Write-Host "Port $LokalerPort lauscht weiterhin." -ForegroundColor Red
    $listener = Get-NetTCPConnection -LocalPort $LokalerPort -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" |
            Select-Object ProcessId, CommandLine | Format-List
    }
    Write-Host "Nicht selbst beenden — Ursache klaeren und dem Betreiber vorlegen." -ForegroundColor Yellow
    exit 1
}

Write-Host "Port $LokalerPort ist frei — lokaler Gateway steht." -ForegroundColor Green
exit 0
