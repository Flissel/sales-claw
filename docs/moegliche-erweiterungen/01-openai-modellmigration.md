# OpenAI als produktiver Modellanbieter

**Status:** ZURÜCKGESTELLT bis zum Produktivbetrieb (Betreiberentscheidung
vom 25.08.2026). Auf `feat/openai-migration` implementiert und getestet, aber
nicht aktiviert; das Laufzeit-Volume steht weiter auf `anthropic/claude-sonnet-5`
über ein Abo-Token. Begründung siehe [README](README.md).

## Ausgangslage

Der bestehende automatische Antwortdienst verwendet die Anthropic Messages
API und dient nur als Demo. `OPENAI_API_KEY` ist bereits als Konfigurationsfeld
vorgesehen. Eine ChatGPT-Plus- oder Pro-Subscription enthält keine API-Nutzung;
der Bot benötigt ein separat abgerechnetes OpenAI-API-Konto.

## Ziel

OpenAI wird der produktive Modellanbieter für OpenClaw und automatische
Antworten. Es gibt zunächst keinen automatischen Anthropic-Fallback, damit
Kosten, Fehlerbilder und Modellverhalten eindeutig bleiben.

## Planentscheidung vom 24.08.2026

- OpenClaw verwendet standardmäßig `openai/gpt-5.6-terra`, weil der
  dialogorientierte Agent Qualität und Kosten ausbalancieren soll.
- Der volumenstärkere Auto-Responder verwendet standardmäßig
  `gpt-5.6-luna`.
- Beide Modellnamen bleiben Konfiguration. Der Fachcode enthält keinen
  stillen Ersatzwert und wechselt bei Fehlern nicht zu einem anderen Provider.
- Modellaufrufe verwenden die OpenAI Responses API mit `store=false` und
  strukturiertem JSON-Output.

## Geplanter Umfang

- gemeinsame, testbare Modellanbieter-Schnittstelle,
- OpenAI-Implementierung für Antworterzeugung und spätere Orchestrierung,
- konfigurierbares Modell ohne fest verdrahteten Modellnamen im Fachcode,
- getrennte Timeouts, Token-/Kostenlimits und strukturierte Fehlerklassen,
- metadata-only Nutzungsprotokoll ohne Prompt- oder Kundentext in Logs,
- kontrollierte Abschaltung des Anthropic-Demo-Pfads nach erfolgreicher
  Migration.

## Sicherheitsgrenzen

- Fehlender oder ungültiger API-Key beendet automatische Antworten fail-closed.
- Ein Timeout erzeugt keinen zweiten, unkontrollierten Modellaufruf.
- Modellantworten lösen nie direkt externe Aktionen aus; sie durchlaufen die
  vorhandenen Freigabe- und Versandverträge.
- API-Keys werden weder über UI noch Chat angezeigt.

## Akzeptanzkriterien

- Bestehende Auto-Responder-Verhaltenstests laufen gegen einen Fake-OpenAI-
  Transport.
- Kein Anthropic-Schlüssel ist für den produktiven Pfad erforderlich.
- Modellfehler und Rate Limits hinterlassen einen nachvollziehbaren, aber
  inhaltsfreien Fehlerzustand.
- Modell und Kostenlimit sind pro Deployment konfigurierbar.
