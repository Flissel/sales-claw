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
    [ValidatePattern('^\d{8}-\d{6}$')]
    [string]$Zeitstempel = (Get-Date -Format 'yyyyMMdd-HHmmss'),
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

$zielVoll = [System.IO.Path]::GetFullPath($Ziel)
[void][System.IO.Directory]::CreateDirectory($zielVoll)
$ordner = Join-Path $zielVoll "sales-claw-$Zeitstempel"
try {
    New-Item -ItemType Directory -Path $ordner -ErrorAction Stop | Out-Null
}
catch {
    throw 'Zielordner existiert bereits oder ist ein Symlink. Es wird nichts wiederverwendet.'
}
$ordnerVoll = (Resolve-Path $ordner).Path

$liefVorher = [bool](docker ps --filter "name=^$Container$" --format '{{.Names}}')

# Exit-Code des Containers nach unserem Stopp. Bleibt $null, wenn wir gar nicht
# gestoppt haben (Container lief nicht, oder -OhneStopp) — dann gibt es keinen
# Stopp, ueber dessen Sauberkeit sich etwas aussagen liesse.
$stopCode = $null

# Wird gesetzt, wenn der Wiederanlauf im finally-Block scheitert. Ohne das
# meldete das Skript Exit 0, obwohl der Dienst unten bleibt — ein geplanter
# Lauf haette den Ausfall nicht bemerkt (nur die rote Zeile im Protokoll).
$wiederanlaufFehler = $false

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
        # `docker stop` liefert auch dann 0, wenn der Container nach Ablauf der
        # Frist getoetet wurde (SIGKILL). Genau dieser Fall hinterlaesst den
        # zerrissenen Session-Store, den der Stopp verhindern soll — also wird
        # nach dem Stopp der Exit-Code des Containers gelesen, nicht der von
        # `docker stop`. -t 30 gibt dem Gateway Zeit, sich sauber zu beenden.
        docker stop -t 30 $Container | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Container liess sich nicht stoppen — abgebrochen, nichts gesichert." }
        $stopCode = docker inspect --format '{{.State.ExitCode}}' $Container
        if ($stopCode -eq '137') {
            throw "'$Container' wurde nach Zeitablauf getoetet (ExitCode 137). Es wird kein Backup-Manifest erzeugt."
        }
    } elseif ($OhneStopp -and $liefVorher) {
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
        # Exit-Code, mit dem der Container auf unseren Stopp hin geendet ist.
        # 0 = sauber beendet. 137 = nach Fristablauf getoetet, der Session-Store
        # kann mitten im Schreiben erwischt worden sein — `restore-state.ps1`
        # warnt dann beim Zurueckspielen. `null` = wir haben nicht gestoppt
        # (Container lief nicht, oder -OhneStopp); dann gibt es keinen Stopp zu
        # beurteilen, und `container_gestoppt` allein traegt die Aussage.
        stop_exit_code = $(if ($null -ne $stopCode) { [int]($stopCode.Trim()) } else { $null })
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
        if ($LASTEXITCODE -ne 0) {
            Write-Host "FEHLER: '$Container' liess sich nicht wieder starten (Code $LASTEXITCODE). Die Sicherung ist vollstaendig, der Dienst laeuft aber NICHT." -ForegroundColor Red
            $wiederanlaufFehler = $true
        } else {
            $status = docker inspect --format '{{.State.Status}}' $Container
            if ($status -ne 'running') {
                Write-Host "FEHLER: '$Container' meldet nach dem Start Status '$status'." -ForegroundColor Red
                $wiederanlaufFehler = $true
            }
        }
    }
}

Write-Host $ordnerVoll

# Exit-Codes: 0 = Sicherung vollstaendig und Dienst laeuft. 1 = Sicherung
# fehlgeschlagen (Ausnahme, PowerShell-Standard). 2 = Sicherung vollstaendig,
# aber der Wiederanlauf ist gescheitert.
#
# Ohne diese Unterscheidung stuende die rote Zeile aus dem finally-Block nur im
# Protokoll: ein geplanter Lauf entscheidet ueber den Exit-Code, nicht ueber die
# Farbe. Genau daran haengt der Befund — der Bot bliebe unten, der Aufrufer
# meldete Erfolg.
if ($wiederanlaufFehler) { exit 2 }
exit 0
