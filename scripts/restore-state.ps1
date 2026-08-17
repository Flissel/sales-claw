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
    if ($v -notmatch '^sales-claw-[a-z]+$') {
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
    # tar -tf listet den Inhalt, ohne zu entpacken. Schlaegt es fehl oder
    # liefert null Eintraege, ist das Archiv unbrauchbar.
    $eintraege = docker run --rm -v "${quelleVoll}:/quelle:ro" alpine:3.20 `
        sh -c "tar -tf /quelle/$name.tar 2>/dev/null | wc -l"
    if ($LASTEXITCODE -ne 0) { throw "Beschaedigt: $name.tar laesst sich nicht lesen — nichts wurde angefasst." }
    if ([int]$eintraege.Trim() -lt 1) { throw "Ohne Eintraege: $name.tar — nichts wurde angefasst." }
    Write-Host "geprueft: $name.tar ($groesse Byte, $($eintraege.Trim()) Eintraege)"
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
