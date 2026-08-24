# Medienbibliothek und Chat-Referenzen

**Status:** gewünschte Erweiterung, noch nicht implementiert

## Ziel

Sales-User laden Bilder, Videos und Dokumente vom Handy oder Computer über die
UI oder den Bot hoch. Medien werden mit strukturierten Metadaten gespeichert,
einem Kontakt oder Thema zugeordnet und in Chat sowie Entwürfen stabil
referenziert.

## Medienobjekt

Ein Medium benötigt mindestens:

- stabile Medien-ID statt freiem Dateipfad,
- ursprünglichen Dateinamen und MIME-Typ,
- Bytezahl und Prüfsumme,
- hochladenden Sales-User und Zeitpunkt,
- optionale Kontakt-, Kampagnen- und Themenzuordnung,
- Titel, Beschreibung und interne Schlagwörter,
- Aufbewahrungs- und Sichtbarkeitsstatus.

## Uploadwege

- Browser-Upload für Handy und Desktop,
- Chat-Upload über einen kontrollierten Bot-Anhang,
- gemeinsamer serverseitiger Validierungs- und Speicherpfad,
- Fortschrittsanzeige für größere Dateien.

## Nutzung im Chat

Der Bot sucht Medien anhand von Metadaten und zeigt eine kurze Trefferliste.
Der Sales-User wählt eine stabile Medien-ID. Erst danach wird das Medium einem
Entwurf oder einer Information für einen Kontakt zugeordnet. Unscharfe
Treffer dürfen nicht automatisch versendet werden.

## Sicherheitsgrenzen

- Allowlist für Dateitypen und harte Größenlimits,
- MIME- und Dateisignaturprüfung,
- keine Ausführung oder direkte Veröffentlichung hochgeladener Dateien,
- keine Dateisystempfade in Chat, UI oder Modellprompt,
- Berechtigungsprüfung pro Sales-User und Kontakt,
- Löschen oder Ersetzen eines bereits versendeten Mediums verändert keinen
  historischen Versandbeleg.

## Akzeptanzkriterien

- UI- und Bot-Upload erzeugen dasselbe Medienobjekt.
- Doppelte Bytes werden über die Prüfsumme erkannt.
- Entwürfe referenzieren Medien-IDs statt lokaler Pfade.
- Metadaten sind im Chat suchbar, Inhalte werden nur bei Berechtigung geladen.
- Versand verweigert fehlende, gesperrte oder nicht eindeutig gewählte Medien.
