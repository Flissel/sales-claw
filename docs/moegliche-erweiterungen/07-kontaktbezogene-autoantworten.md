# Kontaktbezogene Autoantworten

**Status:** gewünschte Erweiterung, noch nicht implementiert

## Ziel

Ein Sales-User legt pro Kontakt fest, wie Sales-Claw auf eingehende
Nachrichten reagiert.

## Antwortmodi

1. **Aus** – keine automatische Antwort.
2. **Nur Entwurf** – der Bot erstellt einen Entwurf zur Freigabe.
3. **Automatisch natürlich verzögert** – automatische Antwort nach einer
   zufälligen Ruhezeit von 1 bis 120 Sekunden.
4. **Sofort automatisch** – automatische Antwort ohne zusätzliche Freigabe.

## Natürlich verzögerter Modus

Jede neue eingehende Nachricht desselben Kontakts verwirft den bisherigen
Timer und zieht eine neue zufällige Verzögerung zwischen 1 und 120 Sekunden.
Nach der vollständigen Ruhezeit beantwortet der Bot alle seit der letzten
Antwort noch unbeantworteten Nachrichten gemeinsam. Das soll kurze
Nachrichtenfolgen natürlich bündeln.

## Verhalten

- Der Modus wird auf der Kontaktseite angezeigt und geändert.
- Chat-Werkzeuge lesen und ändern denselben Wert.
- Eine Modusänderung wirkt auf neue Claims; bereits laufende Arbeit prüft den
  Modus unmittelbar vor dem Erstellen oder Versenden erneut.
- `Aus` bricht noch nicht versendete automatische Arbeit ab.
- Fehler erzeugen keinen unkontrollierten Retry oder Doppelversand.

## Aktuelle Entscheidung

Die Auto-Modi werden zunächst nicht technisch an einen dokumentierten
Zustimmungsnachweis gekoppelt. Ein mögliches späteres Gate ist separat unter
[Autoantwort-Zustimmungs-Gate](autoantwort-zustimmungs-gate.md) beschrieben.

## Akzeptanzkriterien

- Neue Kontakte starten im Modus Aus.
- Der Zufallswert liegt einschließlich der Grenzen zwischen 1 und 120 Sekunden.
- Jede eingehende Nachricht startet das Ruhefenster neu.
- Parallele Worker erzeugen höchstens eine Antwort für denselben
  Nachrichtenbereich.
- Sofort- und Verzögert-Modus prüfen den Kontaktmodus unmittelbar vor Versand.
