#requires -Version 7
<#
.SYNOPSIS
  Stellt beide Volumes aus einer Sicherung wieder her — nachdem sie gegen
  das Manifest geprueft wurden.
.NOTES
  Der Container muss gestoppt sein. Vorhandene Volume-Inhalte werden geleert.

  Mit -NurPruefen laeuft ausschliesslich die Pruefschleife: Manifest-Abgleich
  und Entpackprobe, danach Ausstieg mit Exit 0. Kein Volume wird angefasst, der
  Container darf laufen. Damit laesst sich eine Sicherung pruefen, BEVOR man
  sie braucht — bisher stellte sich ihre Tauglichkeit erst im Ernstfall heraus.

  Warum ein Manifest: Eine Pruefung ohne Sollwert kann nur feststellen, ob
  sich ein Archiv entpacken laesst — nicht, ob es noch das ist, was gesichert
  wurde. Drei Fassungen dieses Skripts sind daran gescheitert. Diese
  Korruptionsarten bestehen jede reine Entpack-Pruefung, empirisch belegt:

    • Trunkierung genau auf tar-Blockgrenze — busybox-tar liest das als
      regulaeres Archivende und meldet Erfolg. Bei einem 40-Eintrag-Archiv
      passierten 5 von 31 clustergenauen Abschnitten unentdeckt.
    • Nullgefuellte Datei — entpackt fehlerfrei zu null Eintraegen und
      sieht damit aus wie ein legitim leeres Volume.
    • Bitfaeule im Nutzdatenbereich — tar prueft Header, nicht Inhalte.

  Eine Pruefsumme gegen einen beim Sichern festgehaltenen Sollwert schliesst
  alle drei auf einmal, und das fehlende Manifest kennzeichnet zugleich einen
  abgebrochenen Sicherungslauf.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Quelle,
    [string]$StateVolume = 'sales-claw-state',
    [string]$KeysVolume  = 'sales-claw-keys',
    [string]$Container   = 'sales-claw',
    [switch]$NurPruefen
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Erlaubnisliste statt Muster. Dieses Skript LOESCHT Volume-Inhalte. Ein
# formtreuer Tippfehler ('sales-claw-stat') passt auf ein Muster, meint aber
# ein anderes Volume — das Skript legte es still an und meldete Erfolg,
# waehrend das echte Volume unberuehrt blieb. Ein falscher Erfolg ist bei
# einer Wiederherstellung fast so schlimm wie ein Datenverlust.
#
# Auch der Containername wird geprueft: ohne das macht ein Tippfehler dort
# die Laufend-Pruefung weiter unten wirkungslos.
# ---------------------------------------------------------------------------
$ERLAUBTE_VOLUMES = @('sales-claw-state', 'sales-claw-keys')
foreach ($v in @($StateVolume, $KeysVolume)) {
    if ($v -cnotin $ERLAUBTE_VOLUMES) {
        throw "Verweigert: '$v' ist keines der Volumes dieses Projekts ($($ERLAUBTE_VOLUMES -join ', '))."
    }
}
if ($Container -cne 'sales-claw') {
    throw "Verweigert: '$Container' ist nicht der Container dieses Projekts."
}

# -NurPruefen schreibt nichts: es liest die Sicherung read-only und entpackt sie
# probeweise in einen Wegwerf-Container. Der laufende Container ist dabei kein
# Hindernis — im Gegenteil. Wuerde die Pruefung ihn verlangen zu stoppen, waere
# der Trockenlauf im Alltag nicht durchfuehrbar, und niemand fuehrte ihn aus.
# Genau das ist der Zweck des Schalters: die Sicherung taugt oder taugt nicht,
# und das soll man wissen, BEVOR man sie braucht.
if (-not $NurPruefen) {
    if (docker ps --filter "name=^$Container$" --format '{{.Names}}') {
        throw "Container '$Container' laeuft. Erst 'docker compose down' ausfuehren."
    }
}

$quelleVoll = (Resolve-Path $Quelle).Path

# ---------------------------------------------------------------------------
# Das Manifest ist Pflicht. Sein Fehlen bedeutet: abgebrochener oder alter
# Sicherungslauf. Beides ist kein Grund, Volumes zu leeren.
# ---------------------------------------------------------------------------
$manifestPfad = Join-Path $quelleVoll 'MANIFEST.json'
if (-not (Test-Path $manifestPfad)) {
    throw "Kein MANIFEST.json in '$quelleVoll'. Die Sicherung ist unvollstaendig oder stammt aus einer aelteren Fassung — nichts wurde angefasst."
}
$manifest = Get-Content -Raw -Encoding UTF8 $manifestPfad | ConvertFrom-Json

if (-not $manifest.container_gestoppt) {
    Write-Host "WARNUNG: Diese Sicherung entstand bei laufendem Container. Eine darin enthaltene WhatsApp-Sitzung kann unbrauchbar sein, auch wenn saemtliche Pruefungen bestehen." -ForegroundColor Red
}

# `docker stop` meldet auch dann Erfolg, wenn der Container nach Fristablauf
# getoetet wurde. Der Beleg dafuer ist der Exit-Code des Containers selbst;
# `backup-state.ps1` haelt ihn im Manifest fest. 137 = SIGKILL — dieselbe Lage
# wie bei einer Sicherung im laufenden Betrieb, nur ohne Vorwarnung.
# Aeltere Manifeste kennen das Feld nicht; dann ist es $null und es wird
# nicht gewarnt.
if ($manifest.stop_exit_code -eq 137) {
    Write-Host "WARNUNG: Bei dieser Sicherung wurde der Container nach Fristablauf getoetet (stop_exit_code 137). Der Session-Store kann mitten im Schreiben erwischt worden sein — die enthaltene WhatsApp-Sitzung kann unbrauchbar sein." -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# BEIDE Archive gegen das Manifest pruefen, BEVOR irgendein Volume angefasst
# wird. Bei zwei Volumes entstuende sonst ein halber Zustand: eines
# ueberschrieben, eines geleert.
# ---------------------------------------------------------------------------
foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
    $vol, $name = $paar
    $datei = "$name.tar"
    $pfad  = Join-Path $quelleVoll $datei

    if (-not (Test-Path $pfad)) { throw "Fehlt in der Sicherung: $datei — nichts wurde angefasst." }

    $soll = $manifest.archive.$name
    if (-not $soll) { throw "Das Manifest kennt '$name' nicht — nichts wurde angefasst." }

    $groesse = (Get-Item $pfad).Length
    if ($groesse -ne $soll.bytes) {
        throw "Groesse weicht ab fuer $datei — Soll $($soll.bytes) Byte, Ist $groesse. Nichts wurde angefasst."
    }

    $ist = (Get-FileHash -Algorithm SHA256 -Path $pfad).Hash.ToLower()
    if ($ist -cne $soll.sha256.ToLower()) {
        throw "Pruefsumme weicht ab fuer $datei. Die Datei hat sich seit der Sicherung veraendert — nichts wurde angefasst."
    }

    # Zweite Verteidigungslinie: probeweise vollstaendig entpacken. Faengt den
    # Fall ab, dass das Archiv schon beim Sichern beschaedigt war und das
    # Manifest die Beschaedigung mitbeurkundet hat.
    $eintraege = docker run --rm -v "${quelleVoll}:/quelle:ro" alpine:3.20 `
        sh -c "mkdir -p /probe && tar -xf /quelle/$datei -C /probe && find /probe -mindepth 1 | wc -l"
    if ($LASTEXITCODE -ne 0) { throw "Beschaedigt: $datei laesst sich nicht entpacken — nichts wurde angefasst." }

    $anzahl = [int]$eintraege.Trim()
    if ($anzahl -ne $soll.eintraege) {
        throw "Eintragszahl weicht ab fuer $datei — Soll $($soll.eintraege), Ist $anzahl. Nichts wurde angefasst."
    }

    if ($anzahl -eq 0) {
        # Zulaessig, solange das Manifest es so festhaelt: ein leeres Volume
        # ist ein gueltiger Zustand. Ohne den Manifest-Abgleich waere dieser
        # Fall nicht von einer nullgefuellten Datei zu unterscheiden.
        Write-Host "HINWEIS: $datei ist leer — das Volume enthielt beim Sichern nichts. Vom Manifest bestaetigt." -ForegroundColor Yellow
    }
    Write-Host "geprueft: $datei (Groesse, Pruefsumme und $anzahl Eintraege stimmen mit dem Manifest ueberein)"
}

if ($NurPruefen) {
    Write-Host "Nur-Pruefen: beide Archive sind in Ordnung. Es wurde nichts veraendert." -ForegroundColor Green
    exit 0
}

Write-Host "Beide Archive stimmen mit dem Manifest ueberein. Jetzt erst werden die Volumes geleert." -ForegroundColor Yellow

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
