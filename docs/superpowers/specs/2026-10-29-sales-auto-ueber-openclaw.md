# sales-auto über das OpenClaw-Gateway (29.10.2026)

## Ziel

`sales-auto` (`sales-mcp/auto.py`) ruft das Modell nicht mehr direkt bei der Anthropic-API auf, sondern über das
OpenClaw-Gateway des eigenen Ladens. Damit gibt es einen Modell- und Schlüsselort (`config/openclaw.json`) und ein
Protokoll. pm-claw kann die Tokens aus den Sitzungsdateien zählen, und die Lead-ID steht im selben Lauf.

Unverändert bleiben: Versand nur über `sales-dispatch`, nur echte Kontakte mit Kontakt-Freigabe, Sammelfenster,
höchstens ein Versuch je Kundennachricht (Anspruch und Entwurf in einer Transaktion unter
`pg_advisory_xact_lock`), `approved_by='auto-betrieb'`, keine Geheimnisse und kein Kundentext in Logs, ladenfest.

## Gemessen (OpenClaw 2026.7.1-slim, Wegwerf-Gateway auf der VM, Modell-Ersatz ohne Kosten)

| Frage | Befund |
|---|---|
| Synchroner Aufruf? | Ja: `POST /v1/chat/completions` (Doku `/app/docs/gateway/openai-http-api.md`), ab Werk aus, `gateway.http.endpoints.chatCompletions.enabled`. Läuft als normaler Agentenlauf. |
| Welcher Agent? | Bestimmt der Sitzungsschlüssel: `agent:auto:…` → Agent `auto`. **Ohne Präfix lief es bei `main` mit allen 32 Werkzeugen**, trotz `model: openclaw/auto`. |
| Unbekannter Agentenname? | Legt **still einen neuen Agenten mit allen Werkzeugen** an (gemessen: `agent:gibtsnicht:…`). `/v1/models` listet nur eingetragene Agenten. |
| Werkzeuge bei `auto`? | `tools.deny: ["*"]` entfernt alle eingebauten Werkzeuge (Log: „tool policy removed 25 tool(s)“); die mitgeschickte Funktion `antwort_abgeben` bleibt als einzige. |
| Strukturierte Antwort? | Kein `response_format`; festes `tool_choice` auf `antwort_abgeben`. Das Gateway gibt den Aufruf zurück (`finish_reason: tool_calls`), ausgeführt wird er in `auto.py`. |
| Antwortet das Modell nur mit Text? | 1 Modellaufruf, dann HTTP 502 „tool_choice required a antwort_abgeben tool call, but the agent did not produce one“. |
| Argumente passen nicht zum Schema? | Das Gateway fragt das Modell **bis zum Kontextüberlauf** neu an (283 Aufrufe in 10 s), dann dasselbe 502. Die Schleifenbremse `tools.loopDetection` greift dabei nicht; eine Zeitgrenze je Agent (`timeoutSeconds`) lehnt die Version ab. |
| Sitzungsdatei | `<state>/agents/auto/sessions/<id>.jsonl`, `sessionKey` mit Lead-ID, `usage` je Assistenten-Nachricht (`input`, `output`, `cacheRead`, `cacheWrite`). |
| Neustart nötig? | Nein: `openclaw config set` für Endpunkt und `agents.list` wirkt ohne Container-Neustart, aber erst nach dem Neuladen (am echten sales-claw 30.10. gemessen: ~1-4 s, der Endpunkt startet das Gateway intern neu). |
| Systemprompt | ~21.500 Zeichen OpenClaw-Rahmen je Lauf zusätzlich zu unseren Regeln (bei `main` mit 100.000 Zeichen AGENTS.md über 245.000 Tokens aus dem Zwischenspeicher je Lauf). |
| Ende zu Ende | `deploy/auto-anbinden.sh` gegen ein frisches Gateway, dann `auto.antwort_erzeugen` über HTTP: 1 Modellaufruf, Ergebnis übernommen. |

## Umsetzung

- `auto.py`: `_http` (Fehlerordnung wie bisher, Token in Meldungen geschwärzt), `_agent_bereit` (fail-closed:
  `openclaw/auto` muss in `/v1/models` stehen, sonst vorübergehend und nichts gesendet), `_sitzungsschluessel`
  (`agent:auto:sales-auto:lead:<uuid>:nachricht:<ms>`), `_api_aufruf` als Naht. `AUTO_AGENT = "auto"` ist eine
  Konstante. Das 502 „did not produce one“ ist endgültig (nie wiederholen, Mensch übernimmt).
- `docker-compose.yml`: `sales-auto` bekommt `OPENCLAW_URL=http://<präfix>-claw:18894` und `OPENCLAW_GATEWAY_TOKEN`,
  sonst kein Dienst. `AUTO_MODELL` entfällt; das Modell steht in der openclaw.json des Ladens.
- `config/openclaw.json` (Saat für neue Läden): Endpunkt an, Agent `auto` mit eigenem Arbeitsordner und
  `tools.deny: ["*"]`; `main` bleibt erster Eintrag.
- `deploy/auto-anbinden.sh [präfix]`: richtet Endpunkt, Agent und Arbeitsordner im laufenden Gateway ein und trägt den
  Token (aus dem Volume) verdeckt in die `.env` des Ladens; Probe über `/v1/models`. Startet nichts.

## Offen / Entscheidungen beim Betreiber

1. **Token = Operator-Zugriff** auf das Gateway (OpenClaw-Doku). Vom Betreiber am 29.10. in Kauf genommen.
2. **pm-claw zählt bisher nur `agents/main/sessions`** (Timer `pm-tokens`). Für `agents/auto/sessions` muss pm-claw
   den Pfad ergänzen; sales-claw ändert pm-claw nicht.
3. **Restrisiko Schleife**: liefert ein echtes Modell Argumente, die nicht zum Schema passen, kann ein einzelner Lauf
   viele Modellaufrufe kosten, bevor das 502 kommt. Ein echtes Modell korrigiert sich nach der Fehlermeldung
   normalerweise; begrenzt wird es nur über den Kontext des Modells.
4. Ausrollen: `update.sh`, dann `deploy/auto-anbinden.sh`, dann `sales-auto` starten — jeweils mit Betreiber-OK.

## Bericht: einen Auto-Antwort-Lauf in der Sitzungsdatei finden

```bash
docker exec sales-claw sh -c 'grep -l "sales-auto:lead:<lead-uuid>" /home/node/.openclaw/agents/auto/sessions/*.jsonl'
docker exec sales-claw sh -c 'grep -o "\"usage\":{[^}]*}" /home/node/.openclaw/agents/auto/sessions/<datei>.jsonl'
```

Der `sessionKey` lautet `agent:auto:sales-auto:lead:<lead-uuid>:nachricht:<ms>`; jede Assistenten-Nachricht trägt
`usage` mit `input`, `output`, `cacheRead`, `cacheWrite` und `totalTokens`.
