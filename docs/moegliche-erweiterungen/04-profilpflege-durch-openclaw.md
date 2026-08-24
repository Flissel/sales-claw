# Regelmäßige Profilpflege durch OpenClaw

**Status:** gewünschte Erweiterung, noch nicht implementiert

## Ziel

OpenClaw aktualisiert das strukturierte Profil eines Kontakts nach mehreren
neuen eingehenden Nachrichten. Die Auswertung erfolgt pro Kontakt, nicht über
einen globalen Zähler.

## Vorgeschlagener Ablauf

1. Eingehende, einem Kontakt zugeordnete Nachrichten erhöhen einen
   Profil-Aktualisierungszähler.
2. Ab einem konfigurierbaren Schwellwert wird genau ein Aktualisierungsjob
   beansprucht.
3. OpenClaw erhält das vorhandene Profil und nur die seit der letzten
   Aktualisierung hinzugekommenen Nachrichten.
4. Vorgeschlagene Profilfelder werden über die bestehende zentrale
   Profilfunktion gespeichert.
5. Der verarbeitete Nachrichtenstand und das Ergebnis werden protokolliert.

## Noch festzulegen

- Standardwert für „alle paar Nachrichten“,
- ob der Schwellwert global oder pro Kontakt einstellbar ist,
- welche Profilfelder automatisch geändert werden dürfen,
- ob sensible oder unsichere Erkenntnisse zunächst als Vorschlag erscheinen.

## Sicherheitsgrenzen

- Derselbe Nachrichtenbereich wird nicht doppelt verarbeitet.
- Modelltext darf keine Kontakt-ID oder Profilfelder frei erfinden.
- Bestehende bestätigte Profilwerte werden nicht still überschrieben.
- Fehler lassen den Zähler wiederholbar, erzeugen aber keine Endlosschleife.

## Akzeptanzkriterien

- Zählung und Claim sind transaktional pro Kontakt.
- Parallele Worker erzeugen höchstens ein Profilupdate je Nachrichtenbereich.
- Jede Feldänderung enthält Quelle, Zeitpunkt und Modelllauf-ID.
- UI und Chat zeigen den letzten Profilaktualisierungsstand.
