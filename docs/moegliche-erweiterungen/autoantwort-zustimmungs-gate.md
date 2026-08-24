# Mögliches Zustimmungs-Gate für automatische Antworten

**Status:** mögliche spätere Erweiterung, nicht Teil des aktuellen Funktionsumfangs

## Ausgangslage

Für jeden Kontakt soll ein Sales-User einen Antwortmodus auswählen können:

1. **Aus** – keine automatische Antwort.
2. **Nur Entwurf** – der Bot formuliert, ein Sales-User gibt den Entwurf frei.
3. **Automatisch natürlich verzögert** – der Bot antwortet nach einer zufälligen Ruhezeit von 1 bis 120 Sekunden.
4. **Sofort automatisch** – der Bot antwortet ohne zusätzliche Freigabe.

Im verzögerten Modus startet jede weitere eingehende Nachricht des Kontakts die
zufällige Ruhezeit neu. Dadurch kann der Bot mehrere kurz nacheinander gesendete
Nachrichten gemeinsam beantworten und das Gespräch wirkt natürlicher.

Die Auswahl eines Auto-Modus wird zunächst **nicht** technisch an einen
dokumentierten Zustimmungsnachweis gekoppelt.

## Mögliche spätere Erweiterung

Eine spätere Version könnte die Modi **Automatisch natürlich verzögert** und
**Sofort automatisch** erst freischalten, nachdem eine Zustimmung am Kontakt
dokumentiert wurde. Der Nachweis könnte mindestens enthalten:

- Zeitpunkt der Zustimmung,
- erfassender Sales-User,
- Herkunft oder Art der Zustimmung,
- Zeitpunkt und Verantwortlicher eines späteren Widerrufs.

Bei fehlender oder widerrufener Zustimmung würde das System fail-closed auf
**Nur Entwurf** oder **Aus** zurückfallen. Bereits geplante automatische
Antworten müssten dabei vor dem Versand abgebrochen werden.

## Nutzen

- nachvollziehbare Verantwortlichkeit,
- klare Widerrufsmöglichkeit,
- geringeres Risiko versehentlich aktivierter Auto-Kommunikation,
- belastbarer Audit-Verlauf pro Kontakt.

## Spätere Akzeptanzkriterien

- Auto-Modi lassen sich ohne aktiven Zustimmungsnachweis nicht aktivieren.
- Ein Widerruf stoppt noch nicht versendete automatische Antworten.
- Jede Änderung wird mit Zeitpunkt und Sales-User protokolliert.
- UI, Chat-Werkzeuge und Hintergrunddienst verwenden dieselbe zentrale
  Berechtigungsprüfung.
- Bestehende Kontakte beginnen nach Einführung des Gates fail-closed ohne
  automatische Freigabe.

## Nicht entschieden

- rechtliche Form und Aufbewahrungsdauer des Nachweises,
- ob eine Zustimmung kanalbezogen oder kontaktweit gilt,
- welche Rollen Zustimmung erfassen oder widerrufen dürfen,
- ob und wann ein Zustimmungsnachweis abläuft.
