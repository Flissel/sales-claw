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

# ---------------------------------------------------------------------------
# Namensschutz. Dieses Skript LOESCHT Volume-Inhalte. Ein Tippfehler im
# Parameter wuerde sonst ein fremdes Volume treffen — auf dieser Maschine
# liegen fremde Volumes direkt daneben.
# ---------------------------------------------------------------------------
foreach ($v in @($StateVolume, $KeysVolume)) {
    # -cnotmatch: gross-/kleinschreibungsempfindlich. Das vorgabemaessige
    # -notmatch liesse 'SALES-CLAW-STATE' durch — Docker-Volumenamen sind aber
    # gross-/kleinschreibungsempfindlich, das waere ein anderes Volume.
    if ($v -cnotmatch '^sales-claw-[a-z]+$') {
        throw "Verweigert: '$v' gehoert nicht zu diesem Projekt. Erlaubt sind nur Namen der Form sales-claw-*."
    }
}

if (docker ps --filter "name=$Container" --format '{{.Names}}' | Where-Object { $_ -eq $Container }) {
    throw "Container '$Container' laeuft. Erst 'docker compose down' ausfuehren."
}

$quelleVoll = (Resolve-Path $Quelle).Path

# ---------------------------------------------------------------------------
# BEIDE Archive vollstaendig pruefen, BEVOR irgendein Volume angefasst wird.
#
# Existenz allein genuegt nicht: eine abgebrochene Kopie, eine volle Platte
# oder ein dazwischenfunkender Virenscanner hinterlassen eine Datei, die da
# ist und trotzdem nichts taugt. Wuerde erst beim Entpacken auffallen — dann
# ist das Zielvolume aber schon geleert. Bei zwei Volumes entstuende sogar ein
# halber Zustand: eines ueberschrieben, eines leer.
# ---------------------------------------------------------------------------
foreach ($paar in @(@($StateVolume,'state'), @($KeysVolume,'keys'))) {
    $vol, $name = $paar
    $pfad = Join-Path $quelleVoll "$name.tar"
    if (-not (Test-Path $pfad)) { throw "Fehlt in der Sicherung: $name.tar — nichts wurde angefasst." }
    $groesse = (Get-Item $pfad).Length
    if ($groesse -eq 0) { throw "Leer: $name.tar hat 0 Byte — nichts wurde angefasst." }
    # Probeweise VOLLSTAENDIG entpacken, in ein Wegwerf-Verzeichnis im
    # Container. Ein blosses `tar -tf` genuegt nicht: ein abgeschnittenes
    # Archiv laesst sich oft noch auflisten, aber nicht entpacken. Und der
    # Exit-Code einer Pipe (`tar -tf | wc -l`) ist der des LETZTEN Glieds —
    # also der von `wc`, das immer 0 liefert. Busybox-sh kennt kein pipefail.
    # Genau daran ist die erste Fassung dieser Pruefung gescheitert.
    #
    # Die `&&`-Kette sorgt dafuer, dass ein Fehler von `tar` den Exit-Code
    # bestimmt: bei Misserfolg laeuft `find` gar nicht erst an.
    $eintraege = docker run --rm -v "${quelleVoll}:/quelle:ro" alpine:3.20 `
        sh -c "mkdir -p /probe && tar -xf /quelle/$name.tar -C /probe && find /probe -mindepth 1 | wc -l"
    if ($LASTEXITCODE -ne 0) { throw "Beschaedigt: $name.tar laesst sich nicht entpacken — nichts wurde angefasst." }

    # Ein leeres Archiv ist KEIN Defekt. `sales-claw-keys` ist seit
    # Projektbeginn leer, und ein leeres Volume ist ein gueltiger Zustand.
    # Hier abzubrechen wuerde eine voellig intakte Sicherung fuer unbrauchbar
    # erklaeren — ein Schutz, der mehr kaputtmacht als er verhindert. Die
    # Unversehrtheit ist durch das erfolgreiche Entpacken oben bereits belegt;
    # die Eintragszahl ist Information, kein Kriterium.
    $anzahl = [int]$eintraege.Trim()
    if ($anzahl -lt 1) {
        Write-Host "HINWEIS: $name.tar ist unversehrt, aber leer — das Volume enthielt nichts." -ForegroundColor Yellow
    }
    Write-Host "probeweise entpackt: $name.tar ($groesse Byte, $anzahl Eintraege)"
}

Write-Host "Beide Archive in Ordnung. Jetzt erst werden die Volumes geleert." -ForegroundColor Yellow

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
