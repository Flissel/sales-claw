# Editierbare Nachrichten- und LinkedIn-Entwürfe

**Status:** gewünschte Erweiterung, noch nicht implementiert

## Ziel

Sales-User können WhatsApp-, E-Mail- und LinkedIn-Entwürfe in der UI vor der
Freigabe bearbeiten. Text und zugeordnete Medien werden gemeinsam angezeigt.

## Fachlicher Vertrag

- Bearbeitbar sind grundsätzlich nur noch nicht versendete Entwürfe.
- Jede inhaltliche Änderung setzt eine vorhandene Freigabe zurück.
- Ein bereits geclaimter oder versendeter Entwurf wird nie in-place geändert.
- Für eine Korrektur nach dem Versand entsteht ein neuer Entwurf mit Verweis
  auf den Ursprung.
- Änderung, Zeitpunkt und Sales-User werden protokolliert.

## UI

- Bearbeiten-Aktion auf Entwurfsdetail und Kontaktverlauf,
- kanalabhängige Zeichenzähler und Vorschau,
- LinkedIn-Vorschau für Text und Medien,
- explizite Warnung, wenn eine Freigabe durch die Bearbeitung verfällt,
- Konflikthinweis bei paralleler Änderung in einem zweiten Browser-Tab.

## Sicherheitsgrenzen

- Empfänger, Kanal und Kontakt können nicht unbemerkt zusammen mit dem Text
  geändert werden.
- Claims, externe IDs und Versandbelege bleiben unveränderlich.
- Die finale Speicherung prüft erneut den erwarteten Ausgangsstatus.

## Akzeptanzkriterien

- UI und Chat verwenden dieselbe zentrale Änderungsfunktion.
- Bearbeitung eines freigegebenen Entwurfs führt zu `pending`.
- Versendete oder in Versand befindliche Entwürfe werden abgewiesen.
- Der Audit-Verlauf zeigt alte und neue Version ohne Secret- oder Tokenwerte.
