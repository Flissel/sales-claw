#requires -Version 7
<#
.SYNOPSIS
  Abnahme nach Spec §9, Kriterien 1, 2, 3 und 6.
.NOTES
  Kriterium 4 (Versionssprung) und 5 (Wiederherstellung) laufen in Task 5
  Schritt 1 bzw. Task 6 gesondert.

  Kriterium 3 (Neustart-Festigkeit) hat bewusst keine eigene Prüfung: es ist
  kein Zustand, den man messen kann, sondern eine Aussage über zwei Zeitpunkte.
  Nachgewiesen wird es dadurch, dass dieses Skript nach
  `docker compose down && docker compose up -d` erneut läuft und dasselbe
  Ergebnis liefert. Der Ablauf steht in `docs/03_RUNBOOK.md`, Abschnitt
  „Abnahme".

  Kriterium 2 wird hier **nicht** über den Klartext von `channels status`
  geprüft — siehe die Begründung an der Prüfung selbst. Der vollständige
  Nachweis (Nachricht rein, Antwort raus) bleibt von Hand zu führen.
#>
[CmdletBinding()]
param(
    [string]$Container = 'sales-claw',
    [int]$Port         = 18894
)

$ErrorActionPreference = 'Continue'
$script:Fehler = 0

. (Join-Path $PSScriptRoot 'lib\ports.ps1')

function Pruefe {
    param([string]$Name, [scriptblock]$Test, [string]$Hinweis = '')
    try {
        $ergebnis = & $Test
        if ($ergebnis) { Write-Host "[OK]     $Name" -ForegroundColor Green }
        else {
            Write-Host "[FEHLER] $Name" -ForegroundColor Red
            if ($Hinweis) { Write-Host "         $Hinweis" -ForegroundColor Yellow }
            $script:Fehler++
        }
    } catch {
        Write-Host "[FEHLER] $Name — $($_.Exception.Message)" -ForegroundColor Red
        if ($Hinweis) { Write-Host "         $Hinweis" -ForegroundColor Yellow }
        $script:Fehler++
    }
}

function Get-JsonAusAusgabe {
    <#
      Die CLI stellt dem JSON einen Warnblock in Rahmenzeichen voran. Wir
      schneiden ab der ersten Zeile, die mit '{' beginnt. Kommt kein JSON
      zurueck, liefert die Funktion $null — der Aufrufer wertet das als
      Fehler, nicht als Entwarnung.
    #>
    param([string]$Text)
    if (-not $Text) { return $null }
    $zeilen  = $Text -split "`r?`n"
    $treffer = $zeilen | Select-String -Pattern '^\s*\{' | Select-Object -First 1
    if (-not $treffer) { return $null }
    $rest = $zeilen[($treffer.LineNumber - 1)..($zeilen.Count - 1)] -join "`n"
    try { $rest | ConvertFrom-Json } catch { $null }
}

Write-Host "== Abnahme sales-claw ==" -ForegroundColor Cyan

# Einmal abfragen, beide Kanal-Pruefungen bewerten denselben Schnappschuss.
# Zwei getrennte Abfragen koennten sich widersprechen, und ein Widerspruch
# zwischen zwei Zeilen desselben Berichts ist schlechter als ein klares Nein.
$script:KanalJson = Get-JsonAusAusgabe (
    openclaw --container $Container channels status --json 2>&1 | Out-String
)

Pruefe "Kriterium 1: Container laeuft und ist healthy" {
    (docker inspect --format '{{.State.Health.Status}}' $Container 2>$null) -eq 'healthy'
} "docker compose up -d, dann bis zu 2 Minuten warten (start_period 60s)."

Pruefe "Kriterium 1b: Gateway lauscht auf 127.0.0.1:$Port" {
    -not (Test-PortFrei -Port $Port)
} "Container laeuft, aber der Gateway nimmt keine Verbindungen an — docker compose logs sales-claw."

Pruefe "Kriterium 2a: Gateway kennt den Kanal whatsapp" {
    # Das ist die Vorbedingung fuer alles Weitere und zugleich die Stelle, an
    # der die naheliegende Textpruefung LUEGT: der Klartext von
    # 'channels status' enthaelt das Wort "whatsapp" auch dann noch im
    # Config-Warnblock ("plugin not installed: whatsapp"), wenn gar kein
    # WhatsApp-Plugin geladen ist. Ein Match auf 'whatsapp' im Klartext
    # meldet dann gruen, obwohl der Kanal nicht existiert — gemessen am
    # 2026.7.1-Container in Task 5. --json fuehrt in 'channelOrder' nur
    # Kanaele, die ein geladenes Plugin tatsaechlich besitzt.
    if (-not $script:KanalJson) { return $false }
    [string[]]$script:KanalJson.channelOrder -contains 'whatsapp'
} "Kein Plugin besitzt den Kanal (no-channel-owner). 'openclaw --container $Container plugins list' und docs/05_DISASTER_RECOVERY.md."

Pruefe "Kriterium 2: WhatsApp-Kanal verbunden (kein QR, kein logout)" {
    # Positiver Nachweis zuerst: ohne registrierten Kanal gibt es nichts zu
    # bewerten. Erst danach die Gegenprobe auf Abmelde- und Pairing-Zustaende.
    # Bewusst in dieser Reihenfolge — ein fehlender Kanal enthaelt naemlich
    # auch keine negativen Marker und wuerde eine reine Gegenprobe bestehen.
    if (-not $script:KanalJson) { return $false }
    if (-not ([string[]]$script:KanalJson.channelOrder -contains 'whatsapp')) { return $false }
    $wa = $script:KanalJson.channels.whatsapp | ConvertTo-Json -Depth 8 -Compress
    if (-not $wa) { return $false }
    $wa -notmatch 'logged.?out|not.?connected|disconnected|needsPairing|pairing|"qr"'
} "Kopplung nicht verbunden. NICHT neu koppeln — erst docs/05_DISASTER_RECOVERY.md lesen; ein zweiter Kopplungsversuch meldet das verknuepfte Geraet ab."

Pruefe "Kriterium 6: openclaw-festival gehoert nicht zu unserem Compose-Projekt" {
    # Existiert er nicht, kann nichts kollidieren. Existiert er, darf er nicht
    # unser Projektlabel tragen — sonst raeumt 'docker compose down' ihn mit ab.
    $festival = docker ps -a --filter "name=^openclaw-festival$" --format '{{.Names}}'
    if (-not $festival) { return $true }
    (docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' openclaw-festival) -ne 'sales-claw'
} "openclaw-festival traegt unser Compose-Projektlabel — 'docker compose down' wuerde ihn mit abraeumen."

Pruefe "Kriterium 6b: lokaler Gateway steht (Port 18793 frei)" {
    Test-PortFrei -Port 18793
} "Die lokale Installation laeuft wieder (Anmelde-Trigger). pwsh -File scripts/stop-local-openclaw.ps1 — siehe docs/03_RUNBOOK.md."

Write-Host ""
if ($script:Fehler -gt 0) { Write-Host "$($script:Fehler) Kriterium(en) nicht erfuellt." -ForegroundColor Red; exit 1 }
Write-Host "Automatisch pruefbare Kriterien erfuellt." -ForegroundColor Green
Write-Host "Manuell noch offen: Selbst-Chat-Umlauf (Kriterium 2) — siehe docs/03_RUNBOOK.md." -ForegroundColor Yellow
exit 0
