# Mögliche Erweiterungen für Sales-Claw

**Status:** Produkt-Backlog, keine Implementierungsfreigabe

Diese Sammlung hält die gewünschten nächsten Ausbaustufen fest. Die Dokumente
sind bewusst noch keine ausführbaren Implementierungspläne. Vor der Umsetzung
erhält jede Erweiterung eine eigene Spezifikation, Tests und Freigabe.

## Empfohlene Reihenfolge

1. [Kontaktbezogene Autoantworten](07-kontaktbezogene-autoantworten.md)
2. [Kontaktlebenszyklus und Einordnung](03-kontakte-lebenszyklus-und-einordnung.md)
3. [Editierbare Nachrichten- und LinkedIn-Entwürfe](02-entwuerfe-und-linkedin-editieren.md)
4. [Medienbibliothek und Chat-Referenzen](08-medienbibliothek-und-chat-referenzen.md)
5. [Regelmäßige Profilpflege durch OpenClaw](04-profilpflege-durch-openclaw.md)
6. [UI vollständig über den Chat orchestrieren](05-chat-orchestrierte-ui.md)
7. [Apify sinnvoll in das Salesteam integrieren](06-apify-im-salesteam.md)

## Zurückgestellt bis zum Produktivbetrieb

- [OpenAI als produktiver Modellanbieter](01-openai-modellmigration.md)

Betreiberentscheidung vom 25.08.2026: Die Anlage ist bis auf Weiteres ein
persönliches System und eine Demo. Erst wenn sie in Produktion geht, wird die
Anbieterfrage interessant.

Der Grund steht im Dokument selbst: eine ChatGPT-Plus- oder Pro-Subscription
enthält keine API-Nutzung, der Wechsel verlangt also ein separat abgerechnetes
OpenAI-Konto und kostet je Aufruf. Der laufende Betrieb nutzt dagegen ein
Anthropic-Abo-Token (`claude setup-token`), das keine zusätzlichen Kosten je
Nachricht erzeugt.

Damit ist auch die Ausgangslage jenes Dokuments überholt: der Anthropic-Pfad
ist seit Einrichtung des Abo-Tokens keine blosse Demo mehr. Die Migration ist
auf `feat/openai-migration` implementiert und getestet; sie liegt bereit, ist
aber bewusst nicht scharf geschaltet — das Laufzeit-Volume steht unverändert
auf `anthropic/claude-sonnet-5`.

Vor einer späteren Aktivierung gehört ausserdem der Commit `93e3bb9`
(bootstrapMaxChars) auf jenen Branch übernommen, sonst erreicht `AGENTS.md`
den Agenten dort wieder nur zu 41 Prozent.

## Bereits teilweise vorhanden

- Kontakte lassen sich in der UI bearbeiten, archivieren und wiederherstellen.
- Profile können über Chat-Werkzeuge gelesen und aktualisiert werden.
- Entwürfe besitzen bereits Kanal, Text und `media_ref`.
- Apify wird bereits begrenzt für Google-Maps-Recherche eingesetzt.
- Ein Anthropic-basierter Auto-Responder existiert als Demo.

Die Erweiterungen sollen diese Verträge weiterverwenden, nicht parallele
Schreibwege oder zweite Datenmodelle einführen.

## Gemeinsame Leitplanken

- Externe Aktionen und irreversible Löschungen bleiben explizite Gates.
- UI, Chat und Hintergrunddienste verwenden dieselben Domain-Funktionen.
- Jede Änderung ist einem Sales-User und einem Kontakt zuordenbar.
- Secrets, Kundendaten und Medieninhalte erscheinen nicht in Logs.
- Automatisierung beginnt pro Kontakt fail-closed.
- Freigegebene oder bereits versendete Inhalte werden nicht still verändert.

## Zusätzlich vorgemerkt

- [Optionales Zustimmungs-Gate für Autoantworten](autoantwort-zustimmungs-gate.md)
