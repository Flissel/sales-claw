#requires -Version 7
<#
.SYNOPSIS
  ⚠️ NICHT MEHR AUSFUEHREN (Betreiber-Entscheidung 20.08.2026).

  Dieses Skript traegt freigegebene Kontakte in `channels.whatsapp.allowFrom`
  ein — und genau das schaltet die automatische Antwort des Agenten an diese
  Kontakte WIEDER EIN. Der Betreiber hat den Auto-Betrieb am 20.08.2026
  abgeschaltet: eingehende Nachrichten werden nur noch erfasst und
  eingeordnet, geantwortet wird ausschliesslich ueber
  entwurf_erstellen -> Freigabe -> Dispatcher.

  `allowFrom` steht deshalb bewusst nur auf den Betreiber-Nummern. Wer den
  Auto-Betrieb wieder will, entscheidet das bewusst — und liest vorher
  docs/superpowers/plans/2026-08-20-sales-claw-stufe11-einordnung.md sowie
  den Runbook-Abschnitt „Auto-Betrieb".
#>
<#
.SYNOPSIS
  Überträgt die Kontakt-Freigaben aus der Datenbank in die allowFrom-Liste
  des OpenClaw-WhatsApp-Kanals (Auto-Betrieb, Runbook „Auto-Betrieb").
.DESCRIPTION
  Die Datenbank ist der SOLLZUSTAND (kontakt_freigeben /
  kontakt_freigabe_entziehen, sichtbar über kontakte_freigegeben); wirksam
  wird er erst hier: OpenClaw hört und antwortet genau den Nummern, die in
  channels.whatsapp.allowFrom stehen (gemessener Befund, Runbook „Zustellung
  braucht die allowFrom-Nummer").

  Regeln des Abgleichs — konservativ, damit der Betreiber sich nie selbst
  aussperrt:
    * Einträge, die zu KEINEM Lead in der Datenbank gehören (die Nummer des
      Betreibers, die verknüpfte Nummer), bleiben IMMER stehen.
    * Nummern freigegebener Kontakte kommen dazu.
    * Nummern von Leads OHNE Freigabe (nie erteilt oder entzogen) fliegen
      raus.
    * Verglichen wird normalisiert über sales-mcp (nummern.py) — dieselbe
      Regel wie Anzeige und Versand.
  Danach wird sales-claw neu gestartet, denn die Konfiguration wird beim
  Start gelesen. Ohne Änderung wird nichts geschrieben und nichts
  neu gestartet.
.NOTES
  Idempotent. Das Volume ist die Wahrheit (wie seed-volume.ps1): geschrieben
  wird /state/openclaw.json im Volume sales-claw-state — beide bekannten
  Formen werden unterstützt (channels.whatsapp.allowFrom aus der Saat und
  channels.whatsapp.default.allowFrom aus dem Live-Nachtrag). sales-mcp muss
  laufen (docker compose up -d sales-mcp).
#>
[CmdletBinding()]
param(
    [string]$StateVolume = 'sales-claw-state',
    # Nur anzeigen, was passieren würde — nichts schreiben, nichts neu starten.
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

# --- 1. Sollzustand aus der Datenbank, normalisiert wie beim Versand --------
$python = @'
import json
import server
from nummern import normalisiere_empfaenger
zeilen = server._q("select phone, enrichment from leads where phone is not null")
alle, frei = set(), set()
for z in zeilen:
    chat_id, _fehler = normalisiere_empfaenger(z["phone"])
    if not chat_id:
        continue
    nummer = "+" + chat_id.split("@", 1)[0]
    alle.add(nummer)
    if server._whatsapp_freigegeben(z["enrichment"]):
        frei.add(nummer)
print(json.dumps({"alle": sorted(alle), "frei": sorted(frei)}))
'@
$rohdaten = docker compose exec -T sales-mcp python -c $python
if ($LASTEXITCODE -ne 0) { throw 'sales-mcp nicht erreichbar — erst docker compose up -d sales-mcp.' }
$db = $rohdaten | ConvertFrom-Json
$leadNummern = [System.Collections.Generic.HashSet[string]]::new([string[]]$db.alle)

# --- 2. Ist-Zustand aus dem Volume lesen ------------------------------------
$konfigRoh = docker run --rm -v "${StateVolume}:/state:ro" alpine:3.20 `
    sh -c 'cat /state/openclaw.json'
if ($LASTEXITCODE -ne 0) { throw "openclaw.json nicht lesbar aus Volume ${StateVolume} — erst seed-volume.ps1." }
$konfig = $konfigRoh | ConvertFrom-Json

# Beide bekannten Formen: die Saat legt allowFrom direkt unter
# channels.whatsapp ab, der Live-Nachtrag (Runbook) unter
# channels.whatsapp.default. Geschrieben wird, wo es schon steht.
$kanal = $konfig.channels.whatsapp
if ($null -eq $kanal) { throw 'channels.whatsapp fehlt in der Konfiguration — nichts geändert.' }
$traeger = if ($kanal.PSObject.Properties['default'] -and
               $kanal.default.PSObject.Properties['allowFrom']) { $kanal.default } else { $kanal }
if (-not $traeger.PSObject.Properties['allowFrom']) { throw 'allowFrom fehlt in der Konfiguration — nichts geändert.' }
$bisher = @($traeger.allowFrom)

# --- 3. Abgleich -------------------------------------------------------------
# Bewahrt wird alles, was keinem Lead gehört (Betreiber- und verknüpfte
# Nummer stehen nie als Lead in der DB); Lead-Nummern richten sich allein
# nach der Freigabe.
$bewahrt = @($bisher | Where-Object { -not $leadNummern.Contains($_) })
$neu = @($bewahrt + $db.frei | Select-Object -Unique | Sort-Object)
if ($neu.Count -eq 0) { throw 'Ergebnis wäre eine leere allowFrom-Liste — nichts geändert.' }

$hinzu = @($neu | Where-Object { $_ -notin $bisher })
$raus  = @($bisher | Where-Object { $_ -notin $neu })
Write-Host "Bewahrt (kein Lead): $($bewahrt -join ', ')"
Write-Host "Freigegeben laut DB: $($db.frei -join ', ')"
if ($hinzu) { Write-Host "Kommt dazu:  $($hinzu -join ', ')" -ForegroundColor Green }
if ($raus)  { Write-Host "Fliegt raus: $($raus -join ', ')" -ForegroundColor Yellow }

if (-not $hinzu -and -not $raus) {
    Write-Host 'allowFrom ist bereits auf Stand — nichts zu tun.'
    exit 0
}
if ($WhatIf) {
    Write-Host 'WhatIf: nichts geschrieben, nichts neu gestartet.'
    exit 0
}

# --- 4. Schreiben und neu starten --------------------------------------------
$traeger.allowFrom = $neu
$ziel = New-TemporaryFile
# -Depth grosszügig: ConvertTo-Json kappt sonst still bei 2 Ebenen.
$konfig | ConvertTo-Json -Depth 32 | Set-Content -Path $ziel -Encoding utf8NoBOM
docker run --rm -v "${StateVolume}:/state" -v "$($ziel.DirectoryName):/saat:ro" alpine:3.20 `
    sh -c "cp /saat/$($ziel.Name) /state/openclaw.json && chown 1000:1000 /state/openclaw.json"
if ($LASTEXITCODE -ne 0) { throw 'Schreiben ins Volume fehlgeschlagen — Konfiguration unverändert lassen und prüfen.' }
Remove-Item $ziel -Force

Write-Host 'Konfiguration geschrieben — sales-claw wird neu gestartet (liest sie beim Start).'
docker compose restart sales-claw
if ($LASTEXITCODE -ne 0) { throw 'Neustart fehlgeschlagen — docker compose ps prüfen.' }
Write-Host "Fertig: allowFrom hat jetzt $($neu.Count) Einträge." -ForegroundColor Green
