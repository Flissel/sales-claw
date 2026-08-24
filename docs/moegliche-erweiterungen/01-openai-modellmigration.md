# OpenAI als produktiver Modellanbieter

**Status:** lokal implementiert, Live-Aktivierung offen

## Ausgangslage

Die Migration folgt dem Plan
`docs/superpowers/plans/2026-08-24-sales-claw-openai-migration.md`. Die
Repository-Konfiguration und die lokalen Verträge sind umgesetzt. Eine
ChatGPT-Plus- oder Pro-Subscription enthält keine API-Nutzung; der Bot benötigt
separat eingerichtetes API-Billing und einen eigenen Projekt-Key
([ChatGPT Plus](https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus),
[ChatGPT-Abo und API](https://help.openai.com/en/articles/8156019-how-can-i-move-my-chatgpt-subscription-to-the-api)).

## Ziel

OpenAI ist der einzige konfigurierte Modellanbieter für OpenClaw und
automatische Antworten. Es gibt keinen automatischen Provider- oder
Modell-Fallback, damit Kosten, Fehlerbilder und Modellverhalten eindeutig
bleiben.

## Planentscheidung vom 24.08.2026

- OpenClaw verwendet standardmäßig `openai/gpt-5.6-terra`, weil der
  dialogorientierte Agent Qualität und Kosten ausbalancieren soll.
- Der volumenstärkere Auto-Responder verwendet standardmäßig
  `gpt-5.6-luna`.
- Beide Modellnamen bleiben Konfiguration. Der Fachcode enthält keinen
  stillen Ersatzwert und wechselt bei Fehlern nicht zu einem anderen Provider.
- Modellaufrufe des Auto-Responders verwenden die OpenAI Responses API mit
  `store=false` und strukturiertem JSON-Output.

## Lokal umgesetzter Umfang

- testbare OpenAI-Provider-Schnittstelle für den Auto-Responder,
- konfigurierbares Modell ohne stillen Ersatzwert im Fachcode,
- Timeout, maximales Ausgabe-Tokenbudget und strukturierte Fehlerklassen,
- metadata-only Nutzungsprotokoll ohne Prompt- oder Kundentext in Logs,
- OpenAI-only Repo-Saat für OpenClaw ohne Fallback.

## Sicherheitsgrenzen

- Fehlender `OPENAI_API_KEY` oder `OPENAI_MODEL` beendet `sales-auto` mit
  Exit `2`, bevor Nachrichten verarbeitet werden.
- Ein Timeout erzeugt keinen zweiten, unkontrollierten Modellaufruf.
- Modellantworten lösen nie direkt externe Aktionen aus; sie durchlaufen die
  vorhandenen Freigabe- und Versandverträge.
- `OPENAI_API_KEY` liegt nur in `.env`, nie in JSON, Logs oder Chat.
- Bestehende OpenClaw-State-Volumes werden von der Repo-Saat nicht
  überschrieben. Ihre Migration ist ein separates Betreiber-Gate.

## Akzeptanzkriterien

- Auto-Responder-Verhaltenstests laufen gegen einen Fake-OpenAI-Transport.
- OpenClaw ist auf `openai/gpt-5.6-terra` ohne Fallback konfiguriert.
- `sales-auto` ist auf `gpt-5.6-luna`, Responses API, `store=false` und
  Structured Output konfiguriert
  ([Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create),
  [Modelle](https://developers.openai.com/api/docs/models)).
- Modellfehler und Rate Limits hinterlassen einen nachvollziehbaren, aber
  inhaltsfreien Fehlerzustand.
- Modell und Ausgabe-Tokenlimit sind pro Deployment konfigurierbar.

## Noch nicht ausgeführt

Kein echter OpenAI-Aufruf, keine API-Key-Prüfung, keine Kosten- oder
Rate-Limit-Beobachtung, keine OpenClaw-State-Migration, kein Containerstart,
keine WhatsApp-Antwort, kein Deployment und kein Cutover sind Teil der lokalen
Implementierung. Der nächste einzelne Betreiber-Schritt ist, API-Billing und
Projekt-Key einzurichten und anschließend in einem separat autorisierten Lauf
genau einen metadata-only OpenAI-Preflight ohne Kundeninhalt auszuführen.
