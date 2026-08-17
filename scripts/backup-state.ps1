#requires -Version 7
<#
.SYNOPSIS
  Sichert beide Volumes als tar-Archive und zusätzlich OpenClaws eigenes,
  verifizierbares Backup-Archiv.
.NOTES
  Zwei Wege mit Absicht: das tar-Archiv ist wortgetreu, das OpenClaw-Archiv
  kennt die Semantik (Konfiguration, Credentials, Sessions, Workspaces) und
  lässt sich mit `openclaw backup verify` prüfen.
#>
[CmdletBinding()]
param(
    [string]$Ziel        = "$PSScriptRoot\..\backups",
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$Container   = 'sales-claw'
)

$ErrorActionPreference = 'Stop'

$zeitstempel = Get-Date -Format 'yyyyMMdd-HHmmss'
$ordner = Join-Path $Ziel "sales-claw-$zeitstempel"
New-Item -ItemType Directory -Force -Path $ordner | Out-Null
$ordnerVoll = (Resolve-Path $ordner).Path

foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
    $vol, $name = $paar
    docker run --rm -v "${vol}:/quelle:ro" -v "${ordnerVoll}:/ziel" alpine:3.20 `
        tar -cf "/ziel/$name.tar" -C /quelle .
    if ($LASTEXITCODE -ne 0) { throw "tar für Volume $vol fehlgeschlagen" }
    Write-Host "gesichert: $vol -> $name.tar"
}

# OpenClaws eigenes Archiv, nur wenn der Container läuft.
$laeuft = docker ps --filter "name=$Container" --format '{{.Names}}'
if ($laeuft -contains $Container) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ordnerVoll 'openclaw-backup') | Out-Null
    docker exec $Container openclaw backup create 2>&1 | Tee-Object -FilePath (Join-Path $ordnerVoll 'openclaw-backup\create.log')
    Write-Host "OpenClaw-Backup erstellt (Pfad siehe create.log)."
} else {
    Write-Host "Container laeuft nicht — OpenClaw-eigenes Backup uebersprungen." -ForegroundColor Yellow
}

Write-Host $ordnerVoll
exit 0
