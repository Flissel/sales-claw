# sales-claw Stufe 8 — Support-Posteingang

> Auftrag des Betreibers (2026-08-19): „können wir auch incoming nachrichten
> tracken ohne dass sie in der allow liste sind — halt einfach nicht
> antworten, aber dann wird das zum generellen Support für mich."

## Befund vor dem Bau (gemessen)

- `sales-inbox` empfängt bereits **alle** eingehenden Nachrichten — die
  `allowFrom`-Liste gehört zu OpenClaws ANTWORT-Verhalten und zur
  Cron-Zustellung, nicht zum OpenWA-Webhook. Unbekannte Absender landen am
  Sammelkontakt (INBOX_UNBEKANNT_LEAD_ID), die Payload trägt `absender`,
  `text`, `message_id`, `gesendet_am` (inbox.py, `speichern`/`verarbeite`).
- Was fehlt: (1) die **Unbeantwortet-Sicht**, (2) der **Digest-Block** dazu,
  (3) die Erfassung **ausgehender eigener Antworten** (`fromMe` wird heute
  verworfen — ohne sie bliebe ein von Hand beantworteter Kontakt ewig
  „unbeantwortet").
- `digest()` kennt keinerlei `kundenantwort`-Block (grep leer).

## Bindende Grundsätze

- **Es wird weiterhin NICHTS automatisch beantwortet.** Der Agent bleibt
  hinter `allowFrom`, `sales-inbox` versendet nie, das Freigabe-Gate
  (drafts, Grundsatz 1) bleibt unberührt. Stufe 8 ist reine Lese-/
  Protokollschicht.
- Append-only bleibt: alte Sammelkontakt-Zeilen werden NICHT umgehängt.
  Triage = Betreiber legt den Kontakt an (`kontakt_anlegen` mit der
  angezeigten Nummer), künftige Nachrichten routen dann von selbst
  (`lead_zu_nummer`). Das wird dokumentiert, kein Umhäng-Werkzeug gebaut.
- Alle bisherigen Sicherheitsregeln unverändert (.env nie lesen,
  compose config verboten, --remove-orphans tabu, sales_test-Wache,
  functools.wraps, MSYS_NO_PATHCONV).

## Bausteine

### E1 — Ausgehende Echos erfassen (inbox.py)

MESSEN ZUERST am laufenden System: Feldsemantik eines `fromMe`-Ereignisses
(`from`/`to`/`chatId` — wer ist der Kunde, wie erkennt man den Selbst-Chat?).
Dann statt `return 200 {"verworfen": "fromMe"}`:

- Selbst-Chat (`chatId` == eigene Nummer) weiterhin VERWERFEN — das ist der
  Notizzettel/Bot-Kanal (Digest-Zustellungen, Systemtests), kein
  Kundenverkehr, und würde das Postfach fluten.
- Sonst: `activities`-Zeile typ `nachricht_ausgehend`, actor `system`
  (es kann der Betreiber vom Handy sein ODER das Webhook-Echo eines
  Dispatcher-Versands — nicht unterscheidbar, und für den Zweck egal:
  beides heißt „der Kontakt hat eine Antwort bekommen"). Lead-Zuordnung
  über `lead_zu_nummer` auf den KUNDEN-Chat, unbekannt → Sammelkontakt.
  Dedup über `message_id` (bestehendes Muster). Payload analog eingehend
  (`text` gekürzt, `richtung: "ausgehend"`, `empfaenger`, `gesendet_am`).
- Doppelbuchung mit dem `versand`-Ereignis des Dispatchers ist AKZEPTIERT
  und wird im Code begründet: `versand` = „das System hat zugestellt"
  (Gate-Protokoll), `nachricht_ausgehend` = „im Chat steht eine Antwort"
  (Postfach-Wahrheit). Zwei Fragen, zwei Ereignisse.

### E2 — Werkzeug `posteingang(stunden=48)` (server.py)

Je Lead die JÜNGSTE `kundenantwort` im Fenster; „unbeantwortet", wenn danach
weder `versand` noch `nachricht_ausgehend` für diesen Lead protokolliert
wurde. Rückgabe: `{"anzahl_unbeantwortet", "eintraege": [{lead_id, kontakt,
absender (nur beim Sammelkontakt — dort identifiziert die Nummer den
Menschen), text_kurz, wartet_seit}]}`, älteste zuerst (wer am längsten
wartet, steht oben), Kappung `stunden` 1..168, Limit 25 Einträge mit
Gesamtzahl daneben. Beim Sammelkontakt zählt jede Absendernummer als
eigener Eintrag (mehrere Unbekannte teilen sich den Lead!) — Gruppierung
über `payload->>'absender'`.

### E3 — Digest-Block `unbeantwortete_eingaenge`

Anzahl + bis zu 5 Einträge (Kontakt bzw. Nummer, wartet seit). Damit ist der
Morgen-Digest der Support-Überblick. Bestehende Digest-Zusagen unverändert.

### E4 — AGENTS, Doku, Tests

- AGENTS.md, neuer Abschnitt „Posteingang": auf Zuruf `posteingang`
  wiedergeben; bei Unbekannten Nummer+Text zeigen und ANBIETEN, einen
  Kontakt anzulegen (Name erfragen); NIEMALS von sich aus eine Antwort an
  Nicht-`allowFrom`-Kontakte versuchen (ginge ohnehin nur über einen
  Entwurf + Freigabe — und consent gilt weiter).
- docs/03: Abschnitt „Support-Posteingang" (Was sehe ich, wie triagiere
  ich Unbekannte, warum antwortet der Bot dort nie von selbst).
- Tests: inbox-Stubtests für E1 (fromMe-Kunde → `nachricht_ausgehend`,
  fromMe-Selbst-Chat → verworfen, Dedup, unbekannter Empfänger →
  Sammelkontakt) im bestehenden inbox-Testmuster; Servertests für
  `posteingang` (beantwortet via `versand` UND via `nachricht_ausgehend`,
  Sammelkontakt-Gruppierung nach Absender, Fensterkappung) und den
  Digest-Block. Zähler 26→27 relativ.

## Reihenfolge

E1→E4 in EINEM Task (ein Umsetzer, opus), Review danach. Live-Abnahme:
eine echte eingehende Nachricht ist nicht erzwingbar — stattdessen
Webhook-Stub-Nachweis plus `posteingang` gegen die echten Bestandsdaten in
`sales` (lesend).
