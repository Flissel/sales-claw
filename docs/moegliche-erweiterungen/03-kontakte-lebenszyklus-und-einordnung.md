# Kontaktlebenszyklus und Einordnung

**Status:** teilweise vorhanden, Ausbau gewünscht

## Ausgangslage

Kontakte können bereits bearbeitet, archiviert und wiederhergestellt werden.
Hartes Löschen ist bislang bewusst ausgeschlossen, weil Nachrichten,
Entwürfe, Aktivitäten und Wiedervorlagen am Kontakt hängen.

## Ziel

Sales-User verwalten den vollständigen Kontaktlebenszyklus und ordnen jeden
Kontakt über ein Dropdown einer Kategorie zu:

- **Team**,
- **Privat**,
- **Kunde**.

Die Kategorie wird in Kontaktliste, Detailseite, Suche, Chat-Werkzeugen und
Automatisierungsregeln einheitlich verwendet.

## Archivieren und Löschen

- Archivieren bleibt die normale, reversible Aktion.
- Wiederherstellen bleibt jederzeit möglich.
- Löschen erhält einen getrennten Zweischritt-Dialog mit Auswirkungsanzeige.
- Vor einer Implementierung ist zu entscheiden, ob „Löschen“ echte physische
  Löschung, Anonymisierung oder nur dauerhafte Deaktivierung bedeutet.
- Kontakte mit Versand-, Einwilligungs- oder Audit-Historie dürfen nicht durch
  einfaches Kaskadenlöschen verschwinden.

## Rollen

Die Aktionen werden einem authentifizierten Sales-User zugeordnet. Ein späteres
Rollenkonzept kann Archivieren, Wiederherstellen und Löschen getrennt erlauben.

## Akzeptanzkriterien

- Einordnungs-Dropdown enthält exakt Team, Privat und Kunde.
- UI und Chat ändern die Einordnung über dieselbe Domain-Funktion.
- Archivierte Kontakte bleiben vollständig auditierbar.
- Eine Löschaktion zeigt vorher alle betroffenen abhängigen Datensätze als
  Anzahlen und führt ohne zweite Bestätigung keine Änderung aus.
- Die genaue Löschsemantik wird vor Implementierung separat freigegeben.
