#requires -Version 7
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Ziel,

    [switch]$StillgelegtLassen
)

$ErrorActionPreference = 'Stop'
$Volume = 'openwa-data'
$Container = 'openwa'

function Get-NormaleDateienImArchiv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Quellordner
    )

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
        throw 'Das erzeugte openwa.tar ist kein lesbares tar-Archiv.'
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

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker ist nicht verfuegbar.'
}
$dockerVersion = @(& docker version --format '{{.Server.Version}}' 2>&1)
if ($LASTEXITCODE -ne 0 -or $dockerVersion.Count -ne 1) {
    throw 'Der Docker-Daemon ist nicht verfuegbar.'
}

$volumeName = @(& docker volume inspect --format '{{.Name}}' $Volume 2>&1)
if ($LASTEXITCODE -ne 0 -or
    $volumeName.Count -ne 1 -or
    $volumeName[0].ToString().Trim() -cne $Volume) {
    throw "Das exakte Docker-Volume '$Volume' ist nicht vorhanden."
}

$containerTreffer = @(
    & docker container ls --all `
        --filter "name=^$Container$" `
        --format '{{.Names}}' 2>&1
)
if ($LASTEXITCODE -ne 0) {
    throw 'Der Status des Containers openwa konnte nicht ermittelt werden.'
}
$containerVorhanden = @(
    $containerTreffer |
        ForEach-Object { $_.ToString().Trim() } |
        Where-Object { $_ -ceq $Container }
).Count -eq 1

$liefVorher = $false
if ($containerVorhanden) {
    $laufstatus = @(& docker inspect --format '{{.State.Running}}' $Container 2>&1)
    if ($LASTEXITCODE -ne 0 -or $laufstatus.Count -ne 1) {
        throw 'Der Laufstatus des Containers openwa konnte nicht ermittelt werden.'
    }
    $liefVorher = $laufstatus[0].ToString().Trim() -ceq 'true'
}

if (Test-Path -LiteralPath $Ziel) {
    throw '-Ziel muss ein neuer, noch nicht vorhandener Ordner sein.'
}
$zielVoll = [System.IO.Path]::GetFullPath($Ziel)
[void](New-Item -ItemType Directory -Path $zielVoll)
if (@(Get-ChildItem -LiteralPath $zielVoll -Force).Count -ne 0) {
    throw 'Der neu angelegte Zielordner ist nicht leer.'
}

$pruefAusgabe = @()
$manifestPfad = $null
try {
    if ($liefVorher) {
        $stoppAusgabe = @(& docker stop --time 30 $Container 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Der Container '$Container' konnte nicht gestoppt werden."
        }

        $stoppCode = @(& docker inspect --format '{{.State.ExitCode}}' $Container 2>&1)
        if ($LASTEXITCODE -ne 0 -or $stoppCode.Count -ne 1) {
            throw "Der Stoppzustand von '$Container' konnte nicht geprueft werden."
        }
        if ($stoppCode[0].ToString().Trim() -eq '137') {
            throw "Der Container '$Container' wurde beim Stoppen hart beendet; kein Backup erstellt."
        }
    }

    $archivAusgabe = @(
        & docker run --rm `
            --mount "type=volume,source=$Volume,target=/quelle,readonly" `
            --mount "type=bind,source=$zielVoll,target=/ziel" `
            alpine:3.20 tar -cf /ziel/openwa.tar -C /quelle . 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Das Volume '$Volume' konnte nicht gesichert werden."
    }

    $archivPfad = Join-Path $zielVoll 'openwa.tar'
    if (-not (Test-Path -LiteralPath $archivPfad -PathType Leaf)) {
        throw 'openwa.tar wurde nicht erstellt.'
    }

    $dateizahl = Get-NormaleDateienImArchiv -Quellordner $zielVoll
    $bytezahl = (Get-Item -LiteralPath $archivPfad).Length
    $sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivPfad).Hash.ToLowerInvariant()

    $manifest = [ordered]@{
        schema      = 1
        created_utc = (Get-Date).ToUniversalTime().ToString('o')
        volume      = $Volume
        archive     = [ordered]@{
            name    = 'openwa.tar'
            bytes   = $bytezahl
            sha256  = $sha256
            entries = $dateizahl
        }
    }

    $manifestPfad = Join-Path $zielVoll 'MANIFEST.json'
    $manifestTemp = Join-Path $zielVoll 'MANIFEST.json.tmp'
    $manifest |
        ConvertTo-Json -Depth 3 |
        Set-Content -LiteralPath $manifestTemp -Encoding utf8
    Move-Item -LiteralPath $manifestTemp -Destination $manifestPfad

    $verifizierer = Join-Path $PSScriptRoot 'verify-openwa-backup.ps1'
    $pruefAusgabe = @(& $verifizierer -Quelle $zielVoll)
}
catch {
    if ($null -ne $manifestPfad -and
        (Test-Path -LiteralPath $manifestPfad -PathType Leaf)) {
        Remove-Item -LiteralPath $manifestPfad -Force
    }
    throw
}
finally {
    if ($liefVorher -and -not $StillgelegtLassen) {
        $startAusgabe = @(& docker start $Container 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Der Container '$Container' konnte nach dem Backup nicht gestartet werden."
        }

        $neuerLaufstatus = @(& docker inspect --format '{{.State.Running}}' $Container 2>&1)
        if ($LASTEXITCODE -ne 0 -or
            $neuerLaufstatus.Count -ne 1 -or
            $neuerLaufstatus[0].ToString().Trim() -cne 'true') {
            throw "Der Container '$Container' laeuft nach dem Startversuch nicht."
        }
    }
}

$pruefAusgabe | Write-Output
