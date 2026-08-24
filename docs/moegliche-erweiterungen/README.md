# Mögliche Erweiterungen für Sales-Claw

**Status:** Produkt-Backlog, keine Implementierungsfreigabe

Diese Sammlung hält die gewünschten nächsten Ausbaustufen fest. Die Dokumente
sind bewusst noch keine ausführbaren Implementierungspläne. Vor der Umsetzung
erhält jede Erweiterung eine eigene Spezifikation, Tests und Freigabe.

## Empfohlene Reihenfolge

1. [OpenAI als produktiver Modellanbieter](01-openai-modellmigration.md)
2. [Kontaktbezogene Autoantworten](07-kontaktbezogene-autoantworten.md)
3. [Kontaktlebenszyklus und Einordnung](03-kontakte-lebenszyklus-und-einordnung.md)
4. [Editierbare Nachrichten- und LinkedIn-Entwürfe](02-entwuerfe-und-linkedin-editieren.md)
5. [Medienbibliothek und Chat-Referenzen](08-medienbibliothek-und-chat-referenzen.md)
6. [Regelmäßige Profilpflege durch OpenClaw](04-profilpflege-durch-openclaw.md)
7. [UI vollständig über den Chat orchestrieren](05-chat-orchestrierte-ui.md)
8. [Apify sinnvoll in das Salesteam integrieren](06-apify-im-salesteam.md)

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
