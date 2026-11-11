# Ollama am PC (11.11.2026) - einziger KI-Endpunkt fuer Briefings und
# Mitschrift-Auswertungen von sales-claw (Meeting-Mittelpunkt).
#
# Regel des Betreibers: keine Modelle auf dem Mini-PC und kein Kundentext an
# fremde KI-Dienste. Ollama laeuft deshalb hier; die VM (sales-mcp) erreicht es
# ueber das Tailnet (tailscale serve --tcp 11434) mit OLLAMA_URL.
#
# Idempotent: antwortet /api/tags schon mit 200, endet das Skript sofort. Die
# Aufgabe "VibeMind Ollama" ruft es bei Anmeldung und alle 5 Minuten - das ist
# zugleich der Waechter. Ollama bindet nur 127.0.0.1; erreichbar wird es nur
# ueber das Tailnet.
param(
    [string]$ModellOrdner = 'E:\ollama\models',
    [string]$LogOrdner = (Join-Path $env:LOCALAPPDATA 'VibeMind\logs\ollama'),
    [int]$Port = 11434
)
$ErrorActionPreference = 'Stop'

# Lebt er? Nur per Anfrage pruefen (nicht per Prozess- oder Portliste), sonst
# startet das Skript alle 5 Minuten eine weitere Kopie.
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/tags" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) { exit 0 }
} catch { }

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) { throw "ollama fehlt im PATH - bitte installieren." }

New-Item -ItemType Directory -Force -Path $LogOrdner | Out-Null
# Nur fuer den Kindprozess: Start-Process erbt die Umgebung dieses Prozesses.
$env:OLLAMA_MODELS = $ModellOrdner
$env:OLLAMA_HOST = "127.0.0.1:$Port"
Start-Process -FilePath $ollama.Source -ArgumentList 'serve' -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogOrdner 'ollama.log') `
    -RedirectStandardError (Join-Path $LogOrdner 'ollama.err.log')

# Dienst vor dem Freigeben im Tailnet kurz abwarten.
$bereit = $false
for ($i = 0; $i -lt 20 -and -not $bereit; $i++) {
    Start-Sleep -Seconds 1
    try {
        $bereit = (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/tags" -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200
    } catch { }
}
if (-not $bereit) { throw "ollama antwortet nach 20 s nicht auf 127.0.0.1:$Port" }

# Idempotent: setzt dieselbe Freigabe erneut.
tailscale serve --bg --tcp $Port "tcp://127.0.0.1:$Port"
