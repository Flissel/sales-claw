# OpenAI als produktiver Modellanbieter

**Status:** gewünschte Erweiterung, noch nicht implementiert

## Ausgangslage

Der bestehende automatische Antwortdienst verwendet die Anthropic Messages
API und dient nur als Demo. `OPENAI_API_KEY` ist bereits als Konfigurationsfeld
vorgesehen. Eine ChatGPT-Plus- oder Pro-Subscription enthält keine API-Nutzung;
der Bot benötigt ein separat abgerechnetes OpenAI-API-Konto.

## Ziel

OpenAI wird der produktive Modellanbieter für OpenClaw und automatische
Antworten. Es gibt zunächst keinen automatischen Anthropic-Fallback, damit
Kosten, Fehlerbilder und Modellverhalten eindeutig bleiben.

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
