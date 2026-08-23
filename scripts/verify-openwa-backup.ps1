#requires -Version 7
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Quelle
)

$ErrorActionPreference = 'Stop'
$Volume = 'openwa-data'

function Test-GanzeZahl {
    param([object]$Wert)

    return (($Wert -is [int]) -or ($Wert -is [long]))
}

function Get-NormaleDateienImArchiv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Quellordner
    )

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker ist nicht verfuegbar.'
    }

    $pruefskript = @'
set -eu
tar -tf /quelle/openwa.tar >/dev/null
anzahl="$(tar -tvf /quelle/openwa.tar | awk 'substr($1, 1, 1) == "-" { n++ } END { print n + 0 }')"
printf 'OPENWA_ENTRIES=%s\n' "$anzahl"
'@

    $dockerAusgabe = @(
        & docker run --rm `
            --mount "type=bind,source=$Quellordner,target=/quelle,readonly" `
            alpine:3.20 sh -c $pruefskript 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw 'openwa.tar ist kein lesbares tar-Archiv.'
    }

    $zaehlerZeilen = @(
        $dockerAusgabe |
            ForEach-Object { $_.ToString().Trim() } |
            Where-Object { $_ -match '^OPENWA_ENTRIES=[0-9]+$' }
    )
    if ($zaehlerZeilen.Count -ne 1) {
        throw 'Die Zahl der normalen Dateien konnte nicht eindeutig ermittelt werden.'
    }

    return [long]$zaehlerZeilen[0].Substring('OPENWA_ENTRIES='.Length)
}

if (-not (Test-Path -LiteralPath $Quelle -PathType Container)) {
    throw '-Quelle muss ein vorhandener Ordner sein.'
}
$quelleVoll = (Resolve-Path -LiteralPath $Quelle).Path

$elemente = @(Get-ChildItem -LiteralPath $quelleVoll -Force)
if ($elemente.Count -ne 2) {
    throw 'Der Backupordner muss genau MANIFEST.json und openwa.tar enthalten.'
}
foreach ($dateiname in @('MANIFEST.json', 'openwa.tar')) {
    $treffer = @(
        $elemente |
            Where-Object { (-not $_.PSIsContainer) -and ($_.Name -ceq $dateiname) }
    )
    if ($treffer.Count -ne 1) {
        throw 'Der Backupordner muss genau MANIFEST.json und openwa.tar enthalten.'
    }
}

$manifestPfad = Join-Path $quelleVoll 'MANIFEST.json'
try {
    $manifest = Get-Content -Raw -LiteralPath $manifestPfad | ConvertFrom-Json
}
catch {
    throw 'MANIFEST.json ist kein gueltiges JSON-Dokument.'
}

$manifestFelder = @($manifest.PSObject.Properties.Name)
if (-not ($manifestFelder -ccontains 'schema') -or
    -not (Test-GanzeZahl $manifest.schema) -or
    [long]$manifest.schema -ne 1) {
    throw 'MANIFEST.json hat nicht schema=1.'
}
if (-not ($manifestFelder -ccontains 'volume') -or
    -not ($manifest.volume -is [string]) -or
    $manifest.volume -cne $Volume) {
    throw 'MANIFEST.json gilt nicht fuer openwa-data.'
}
if (-not ($manifestFelder -ccontains 'archive') -or
    -not ($manifest.archive -is [pscustomobject])) {
    throw 'MANIFEST.json enthaelt keine Archivmetadaten.'
}

$archivFelder = @($manifest.archive.PSObject.Properties.Name)
foreach ($feld in @('bytes', 'sha256', 'entries')) {
    if (-not ($archivFelder -ccontains $feld)) {
        throw "MANIFEST.json fehlt archive.$feld."
    }
}
if (-not (Test-GanzeZahl $manifest.archive.bytes) -or
    [long]$manifest.archive.bytes -lt 0) {
    throw 'archive.bytes muss eine nichtnegative ganze Zahl sein.'
}
if (-not ($manifest.archive.sha256 -is [string]) -or
    $manifest.archive.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'archive.sha256 muss ein SHA-256-Hash sein.'
}
if (-not (Test-GanzeZahl $manifest.archive.entries) -or
    [long]$manifest.archive.entries -lt 0) {
    throw 'archive.entries muss eine nichtnegative ganze Zahl sein.'
}

$archivPfad = Join-Path $quelleVoll 'openwa.tar'
$bytezahl = (Get-Item -LiteralPath $archivPfad).Length
if ($bytezahl -ne [long]$manifest.archive.bytes) {
    throw 'Die Bytezahl von openwa.tar stimmt nicht mit MANIFEST.json ueberein.'
}

$sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivPfad).Hash.ToLowerInvariant()
if ($sha256 -cne $manifest.archive.sha256.ToLowerInvariant()) {
    throw 'Der SHA-256-Hash von openwa.tar stimmt nicht mit MANIFEST.json ueberein.'
}

$dateizahl = Get-NormaleDateienImArchiv -Quellordner $quelleVoll
if ($dateizahl -ne [long]$manifest.archive.entries) {
    throw 'Die Dateizahl von openwa.tar stimmt nicht mit MANIFEST.json ueberein.'
}

Write-Output 'openwa-data: verifiziert'
Write-Output "Bytezahl: $bytezahl"
Write-Output "Dateizahl: $dateizahl"
Write-Output "SHA-256: $sha256"
