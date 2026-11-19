# Mitschriften per Ziehen verschieben – Design (kurz)

Stand 19.11.2026, Freigabe Felix („ok“ auf den Vorschlag im Chat).

## Absicht

Felix will eine Mitschrift-Karte auf `/mitschriften` mit der Maus auf einen Reiter ziehen (vor allem „Kurse“),
statt je Karte Auswahlfeld und Knopf zu bedienen. Anlass: Termine wie der Kurs mit Arjun (19.11.) müssen nach dem
Termin nach „Kurse“, damit Kursmitschrift und Handbuch entstehen.

## Ziele

- Jede Karte ist ziehbar (Griff „⠿“), jeder Rubrik-Reiter der Leiste ist Ablageziel; der Reiter wird beim
  Darüberziehen hervorgehoben. Loslassen verschiebt sofort (ohne Rückfrage, Verschieben ist umkehrbar – Felix'
  Vorschlag ohne Einwand) und landet wie heute auf dem Ziel-Reiter.
- „Kurse“ steht **immer** in der Leiste, auch mit 0 Einträgen; ein Klick darauf zeigt „Keine Mitschriften in dieser
  Rubrik.“ (heute springt ein unbekannter Reiter auf den ersten).
- Das bestehende Formular bleibt als Rückfall (Handy/Touch, neue Rubrik, ohne Skript), aber kleiner: eingeklappt in
  `<details><summary>Verschieben …</summary>`.

## Nicht-Ziele

- Kein Ziehen am Handy/Touch, kein Umsortieren innerhalb einer Rubrik, kein Ziehen auf „Handbücher“.
- Keine neue Rubrik per Ziehen (dafür bleibt das Formular).
- Keine Änderung an `mitschrift_bericht.verschieben` oder am Takt.

## Vorgaben

- Gleicher Weg wie das Formular: das Skript füllt ein verstecktes Formular und schickt es an
  `POST /mitschriften/verschieben` (CSRF, Rechte „lesen“/„kalender“ dürfen nicht, Rubrik-Prüfung – alles unverändert).
- Seiten-CSP ohne eingebettetes Skript: eigene Datei `static/mitschriften/ziehen.js`, ausgeliefert über eine
  gesicherte Route (Muster `ui_struktur.skript`), Seite mit `ui_kalender.csp_kalender(ui)` (wie `/team/struktur`).
- Nur-Lesen-Anmeldungen: keine ziehbaren Karten, kein Skript, kein verstecktes Formular.
- Kein `console.log`, Texte deutsch mit Umlauten.

## Ansätze

1. **Reiter als Ablageziele, Formular per Skript abschicken (gewählt).** Klein, nutzt Prüfung und Rechte des
   bestehenden Wegs, Muster existiert (Team-Struktur).
2. Eigene JSON-Schnittstelle + `fetch` ohne Neuladen. Mehr Code, zweiter Prüfweg, CSP bräuchte `connect-src` – verworfen.
3. Eigene Ablageleiste über der Liste statt der Reiter. Doppelte Leiste ohne Mehrwert – verworfen.

## Dem Bauenden überlassen

Genaue CSS-Klassen, Aussehen des Griffs und der Hervorhebung (an `.struktur-liste` angelehnt), Tests im Stil von
`tests/test_ui_mitschriften.py` / `tests/test_struktur_seite.py`.
