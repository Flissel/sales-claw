# UI vollständig über den Chat orchestrieren

**Status:** gewünschte Erweiterung, noch nicht implementiert

## Ziel

Alle fachlichen Aktionen der UI sind auch als sichere Chat-Werkzeuge
verfügbar. Der Sales-User kann Kontakte, Entwürfe, Medien, Profile,
Automatisierung und Recherche dialogorientiert steuern.

## Architekturprinzip

UI und Chat erhalten keine getrennte Fachlogik. Beide rufen dieselben
Domain-Funktionen mit denselben Status-, Rollen- und Bestätigungsprüfungen auf.
Der Chat ist damit eine zweite Bedienoberfläche, kein privilegierter Bypass.

## Werkzeuggruppen

- Kontakte suchen, anzeigen, einordnen, archivieren und wiederherstellen,
- Entwürfe erstellen, bearbeiten, freigeben und ablehnen,
- Medien hochladen, suchen und einem Entwurf zuordnen,
- Antwortmodus eines Kontakts lesen und ändern,
- Profile lesen und Aktualisierungen anstoßen,
- Apify-Recherche starten und Ergebnisse einem Kontakt zuordnen.

## Bestätigungsmodell

- Lesende Aktionen dürfen direkt ausgeführt werden.
- Reversible Änderungen benötigen eine klare Zusammenfassung.
- Externe, versendende oder irreversible Aktionen benötigen eine explizite
  Bestätigung mit stabiler Objekt-ID.
- Ein Modell darf Bestätigungen nicht selbst erzeugen oder aus älteren
  Nachrichten ableiten.

## Akzeptanzkriterien

- Jede UI-Schreibaktion besitzt genau eine entsprechende Domain-Funktion.
- Chat und UI erzeugen identische Audit-Ereignisse.
- Werkzeugargumente verwenden IDs statt unscharfer Namensauflösung.
- Berechtigungs- und Statusfehler sind fail-closed und verändern nichts.
- Ein Test beweist, dass der Chat keine Versand- oder Löschaktion ohne
  Bestätigung auslösen kann.
