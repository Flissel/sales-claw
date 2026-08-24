# Apify sinnvoll in das Salesteam integrieren

**Status:** teilweise vorhanden, Ausbau gewünscht

## Ausgangslage

Apify wird bereits budgetbegrenzt für Google-Maps-Recherche eingesetzt.
Website-Anreicherung läuft bewusst ohne Apify. Der vorhandene Baustein soll
nicht durch beliebige Actor-Aufrufe ersetzt werden.

## Zielbild

Apify unterstützt das Salesteam in drei klar getrennten Stufen:

1. **Lead Discovery:** Firmen nach Region, Branche und Suchprofil finden.
2. **Qualifizierung:** strukturierte öffentliche Firmendaten und Quellen
   ergänzen.
3. **Monitoring:** bei ausgewählten Kontakten relevante öffentliche Änderungen
   erkennen und als Hinweis vorlegen.

Apify erzeugt keine Nachrichten und startet keinen Versand.

## Bedienung

- Start über UI oder Chat mit Suchprofil, Region und harter Ergebnisgrenze,
- Kostenschätzung und Budgetbestätigung vor einem bezahlten Lauf,
- Fortschritt und Ergebnisanzahlen ohne Token oder Rohkundendaten,
- Dublettenprüfung vor Übernahme in Kontakte,
- manuelle Auswahl, welche Ergebnisse gespeichert werden.

## Sicherheits- und Kostengrenzen

- Actor-Allowlist statt frei wählbarer Actor-ID,
- maximales Budget und Laufzeit pro Auftrag,
- idempotente Job-ID gegen versehentliche Doppelläufe,
- Quellen- und Zeitstempel je importiertem Feld,
- keine automatische Kontaktaufnahme aus Rechercheergebnissen.

## Akzeptanzkriterien

- Jeder Lauf ist einem Sales-User, Zweck und Budget zugeordnet.
- Ein wiederholter Request startet nicht unbemerkt einen zweiten bezahlten
  Lauf.
- Ergebnisse werden vor Speicherung dedupliziert und angezeigt.
- Herkunft und Aktualität bleiben am Kontakt sichtbar.
- Token und Apify-Query-Authentifizierung erscheinen nie in Logs oder UI.
