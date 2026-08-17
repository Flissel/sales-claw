#requires -Version 7
<#
.SYNOPSIS
  Sichert beide Volumes als tar-Archive, schreibt ein Manifest mit Sollwerten
  und legt zusaetzlich OpenClaws eigenes Backup-Archiv ab.
.NOTES
  Der Container wird fuer die Dauer des tar-Laufs GESTOPPT. Grund: der
  Session-Store — dort liegt die WhatsApp-Kopplung — wird im Betrieb
  geschrieben. Ein tar ueber laufende Schreibvorgaenge liefert ein
  strukturell einwandfreies Archiv mit einem Zustand mitten im Schreiben.
  Die zurueckgespielte Sitzung ist dann tot, ohne dass irgendeine
  Archivpruefung das bemerken koennte. OpenClaws eigenes `backup create`
  ueberspringt aus demselben Grund fuenf fluechtige Dateien ("live sessions,
  cron logs, queues, sockets, pid/tmp") — unser tar wuerde sie mitnehmen.

  Das MANIFEST wird ZULETZT geschrieben. Sein Fehlen ist die Kennzeichnung
  eines abgebrochenen Laufs: eine Sicherung ohne Manifest gilt als
  unvollstaendig und wird beim Wiederherstellen abgelehnt.
#>
[CmdletBinding()]
param(
    [string]$Ziel        = "$PSScriptRoot\..\backups",
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$Container   = 'sales-claw',
    [switch]$OhneStopp
)

$ErrorActionPreference = 'Stop'

# Ausdrueckliche Erlaubnisliste statt Muster. Ein formtreuer Tippfehler
# ('sales-claw-stat') passt auf ein Muster, meint aber ein anderes Volume.
# Dieses Projekt hat genau zwei Volumes und genau einen Container.
$ERLAUBTE_VOLUMES = @('sales-claw-state', 'sales-claw-keys')
foreach ($v in @($StateVolume, $KeysVolume)) {
    if ($v -cnotin $ERLAUBTE_VOLUMES) {
        throw "Verweigert: '$v' ist keines der Volumes dieses Projekts ($($ERLAUBTE_VOLUMES -join ', '))."
    }
}
if ($Container -cne 'sales-claw') {
    throw "Verweigert: '$Container' ist nicht der Container dieses Projekts."
}

$zeitstempel = Get-Date -Format 'yyyyMMdd-HHmmss'
$ordner = Join-Path $Ziel "sales-claw-$zeitstempel"
New-Item -ItemType Directory -Force -Path $ordner | Out-Null
$ordnerVoll = (Resolve-Path $ordner).Path

$liefVorher = [bool](docker ps --filter "name=^$Container$" --format '{{.Names}}')

# OpenClaws semantisches Archiv zuerst — es braucht einen laufenden Container.
if ($liefVorher) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ordnerVoll 'openclaw-backup') | Out-Null
    docker exec $Container openclaw backup create 2>&1 |
        Tee-Object -FilePath (Join-Path $ordnerVoll 'openclaw-backup\create.log')
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNUNG: 'openclaw backup create' endete mit Code $LASTEXITCODE. Die tar-Archive sind massgeblich; das semantische Archiv fehlt. Siehe create.log." -ForegroundColor Yellow
    }
}

try {
    if ($liefVorher -and -not $OhneStopp) {
        Write-Host "Stoppe $Container fuer die Dauer der Sicherung…" -ForegroundColor Yellow
        docker stop $Container | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Container liess sich nicht stoppen — abgebrochen, nichts gesichert." }
    } elseif ($OhneStopp) {
        Write-Host "WARNUNG: -OhneStopp gesetzt. Die Sicherung ist crash-inkonsistent. Eine darin enthaltene WhatsApp-Sitzung kann unbrauchbar sein, obwohl alle Pruefungen bestehen." -ForegroundColor Red
    }

    $manifest = [ordered]@{
        erzeugt = (Get-Date).ToUniversalTime().ToString('o')
        # Das Feld beantwortet: "War der Container waehrend des tar-Laufs
        # garantiert still?" — nicht: "Haben WIR ihn gestoppt?"
        #
        # Der Unterschied ist nicht akademisch. War der Container beim Aufruf
        # bereits gestoppt, ist das die konsistenteste Sicherung ueberhaupt.
        # Die naheliegende Formel ($liefVorher -and -not $OhneStopp) haette
        # dafuer `false` geschrieben und beim Wiederherstellen eine sachlich
        # falsche Warnung ausgeloest — ausgerechnet fuer den besten Fall.
        #
        # Unsicher ist genau eine Lage: der Container lief und wir haben ihn
        # auf ausdruecklichen Wunsch nicht gestoppt.
        container_gestoppt = -not ($liefVorher -and $OhneStopp)
        archive = [ordered]@{}
    }

    foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
        $vol, $name = $paar
        docker run --rm -v "${vol}:/quelle:ro" -v "${ordnerVoll}:/ziel" alpine:3.20 `
            tar -cf "/ziel/$name.tar" -C /quelle .
        if ($LASTEXITCODE -ne 0) { throw "tar fuer Volume $vol fehlgeschlagen" }

        $pfad = Join-Path $ordnerVoll "$name.tar"

        # Eintragszahl mit GENAU demselben Verfahren ermitteln, das die
        # Wiederherstellung benutzt — sonst sind Soll und Ist nicht
        # vergleichbar (`tar -tf` zaehlt den './'-Eintrag mit, `find
        # -mindepth 1` nicht).
        $eintraege = docker run --rm -v "${ordnerVoll}:/quelle:ro" alpine:3.20 `
            sh -c "mkdir -p /probe && tar -xf /quelle/$name.tar -C /probe && find /probe -mindepth 1 | wc -l"
        if ($LASTEXITCODE -ne 0) { throw "Das eben erzeugte $name.tar laesst sich nicht entpacken — Sicherung abgebrochen." }

        $manifest.archive[$name] = [ordered]@{
            datei     = "$name.tar"
            sha256    = (Get-FileHash -Algorithm SHA256 -Path $pfad).Hash.ToLower()
            bytes     = (Get-Item $pfad).Length
            eintraege = [int]$eintraege.Trim()
        }
        Write-Host "gesichert: $vol -> $name.tar ($($manifest.archive[$name].bytes) Byte, $($manifest.archive[$name].eintraege) Eintraege)"
    }

    # ZULETZT. Die Existenz dieser Datei bedeutet: der Lauf ist vollstaendig.
    $manifest | ConvertTo-Json -Depth 5 |
        Set-Content -Path (Join-Path $ordnerVoll 'MANIFEST.json') -Encoding utf8
    Write-Host "MANIFEST.json geschrieben — Sicherung vollstaendig." -ForegroundColor Green
}
finally {
    if ($liefVorher -and -not $OhneStopp) {
        Write-Host "Starte $Container wieder…" -ForegroundColor Yellow
        docker start $Container | Out-Null
    }
}

Write-Host $ordnerVoll
exit 0
