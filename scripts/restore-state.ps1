#requires -Version 7
<#
.SYNOPSIS
  Stellt beide Volumes aus einer Sicherung wieder her.
.NOTES
  Der Container muss gestoppt sein. Vorhandene Volume-Inhalte werden geleert.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Quelle,
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$Container   = 'sales-claw'
)

$ErrorActionPreference = 'Stop'

$quelleVoll = (Resolve-Path $Quelle).Path
foreach ($n in @('state.tar','keys.tar')) {
    if (-not (Test-Path (Join-Path $quelleVoll $n))) { throw "Fehlt in der Sicherung: $n" }
}

if (docker ps --filter "name=$Container" --format '{{.Names}}' | Where-Object { $_ -eq $Container }) {
    throw "Container '$Container' laeuft. Erst 'docker compose down' ausfuehren."
}

foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
    $vol, $name = $paar
    if (-not (docker volume ls --format '{{.Name}}' | Where-Object { $_ -eq $vol })) {
        docker volume create $vol | Out-Null
    }
    docker run --rm -v "${vol}:/ziel" -v "${quelleVoll}:/quelle:ro" alpine:3.20 `
        sh -c "rm -rf /ziel/..?* /ziel/.[!.]* /ziel/* 2>/dev/null; tar -xf /quelle/$name.tar -C /ziel"
    if ($LASTEXITCODE -ne 0) { throw "Wiederherstellung von $vol fehlgeschlagen" }
    Write-Host "wiederhergestellt: $name.tar -> $vol"
}

Write-Host "Wiederherstellung abgeschlossen." -ForegroundColor Green
exit 0
