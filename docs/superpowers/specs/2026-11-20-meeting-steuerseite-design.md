# Meeting-Steuerseite: Meeting einbetten, live mitsehen, Bot pausieren

Stand 20.11.2026. Betreiber: Felix. Zweig `feat/meeting-steuerseite` ab bfafd87 (`feat/stufe-1-fundament`).

## Absicht und Warum

Felix will waehrend eines Termins auf EINER eigenen Seite sitzen: dort selbst am
Meeting teilnehmen, daneben live sehen, was der Bot mitschreibt und welche
Bildschirmbilder er speichert, und den Bot jederzeit „blind“ machen und wieder
einschalten. Grund: DSGVO. Kommen im Gespraech fremde oder heikle Daten auf
(Ton oder geteilter Bildschirm), soll fuer diese Zeit nichts davon bei uns
entstehen. Der Bot soll dabei im Raum bleiben (Betreiber-Entscheid 20.11.: „bleiben,
Ton und Bild verwerfen“); die anderen Teilnehmer sollen von der Pause nichts merken.
Wie: die Pause sitzt im Vexa-Bot selbst (Betreiber-Entscheid 20.11.: Weg B), damit
waehrend der Pause gar kein Text entsteht – nicht erst entsteht und spaeter
geloescht wird.

## Ziele

1. Seite `/termine/<uid>/live` (Rolle mit Schreibrecht): Steuerung,
   Live-Transkript, Live-Bilder; das Meeting selbst oeffnet per Knopf in einem
   eigenen Tab (Einbetten verbietet ffmuc, s. Entscheidungen).
2. Knopf **Pause** / **Weiter** fuer die Aufnahme (Ton UND Bild zusammen).
   Anzeige des Zustands gross und eindeutig („● Aufnahme laeuft“ / „⏸ Pausiert seit 11:43“).
3. Waehrend der Pause:
   - Der Vexa-Bot schickt keinen Ton an die Spracherkennung; was er beim
     Pausen-Beginn an noch nicht transkribiertem Ton gepuffert hat, wirft er weg.
   - `sales-auge` speichert keine Bildschirmbilder.
4. Live-Transkript waehrend des Termins (heute erst nach Terminende sichtbar).
5. Pausen sind sichtbar und nachvollziehbar: in der Mitschrift als Luecke
   „Pause 11:43–11:47“ (ohne Inhalt), im Verlauf der Akte mit wer/wann.
6. Gilt fuer die drei Laeden (`sales`, `sales_ivan`, `sales_sophie`) gleich – dieselbe Code-Basis.

## Nicht-Ziele (diese Runde)

- Webinare und Festival-Bot (inkl. deren STT-Zugang): eigenes, spaeteres Projekt,
  das auf dieser Seite aufbaut.
- Getrenntes Pausieren nur von Ton oder nur von Bild.
- Pause durch Teilnehmer (Chat-Befehl o. ae.) oder automatische Pause.
- Google Meet / Teams einbetten: nur Jitsi (Bildauswertung gibt es ohnehin nur fuer Jitsi).
- Den Bot den Raum verlassen lassen (verworfen, s. Ansaetze).

## Anti-Ziele (waere ein Fehlschlag, auch wenn es technisch laeuft)

- Text oder Bilder aus einer Pause landen irgendwo dauerhaft – in Vexa, in der
  Akte, in Logs, in der Mitschrift, im Briefing.
- Der Knopf zeigt „Pausiert“, waehrend der Bot noch transkribiert (Anzeige muss
  den BESTAETIGTEN Zustand zeigen, nicht den gewuenschten).
- Ein Fehler beim Pausieren bleibt still. Kann der Bot die Pause nicht bestaetigen,
  sagt die Seite das laut, und Felix kann den Bot als Notbremse entfernen.
- Die anderen Teilnehmer bemerken die Pause (Bot verlaesst den Raum, Ton/Hinweis im Meeting).

## Vorgaben (aus dem Projekt)

- Nur `sales-termine` (Taktgeber) spricht mit Vexa (Final-Review C1). Oberflaeche
  und MCP haben keinen `VEXA_API_KEY`. Die Seite schreibt den Wunsch in die DB,
  `sales-termine` setzt ihn um.
- Seiten-CSP ohne Inline-Skript; Skript als Datei ueber gesicherte Route
  (Vorbild `ui_kalender.csp_kalender`, `static/mitschriften/ziehen.js`).
- Vexa ist `vexaai/vexa-lite:v0.12.28`, laeuft als Container `vexa-lite`
  (Compose in `deploy/vexa/`). Der Bot (Node, `core/meetings/services/bot`)
  nimmt Befehle ueber den Act-Kanal (`acts.v1`, `contracts.ts`: `leave`,
  `reconfigure`, …) an; `reconfigure` behandelt der Live-Pipeline-Adapter.
- Vexa-Tonaufnahme ist aus (`recording_enabled: False`); es gibt nur Text.
- Keine Inhalte, keine Namen in Logs. Kundendaten nicht veroeffentlichen.
- Rollout gezielt (nie nacktes `up -d`), nicht waehrend eines Bot-Termins.
- Tests nur gegen `~/meeting-test`.

## Ansaetze

- **A) Bei uns verwerfen:** Bot transkribiert weiter, wir verwerfen Stuecke aus
  Pausenfenstern und loeschen sie in Vexas DB. Wenig Aufwand, aber Text entsteht
  kurz. Verworfen von Felix.
- **B) Vexa selbst pausieren (gewaehlt):** neuer Act `pause`/`resume` im Bot;
  waehrend der Pause geht kein Ton an Whisper, der Puffer wird verworfen. Kein
  Text entsteht. Mehr Aufwand: eigene Vexa-Variante pflegen.
- **C) Bot verlaesst den Raum und kommt zurueck:** sicher, aber fuer alle sichtbar
  und die Mitschrift zerfaellt in zwei Vexa-Meetings. Verworfen von Felix.

## Wie (entschieden)

### 1. Vexa-Variante (Weg B)

- Eigenes Abbild **auf dem offiziellen aufgesetzt**
  (`FROM vexaai/vexa-lite:v0.12.28`, Patch-Dateien darueber), kein voller Fork.
  Liegt in `deploy/vexa/` (Dockerfile + Patches), Tag z. B.
  `sales-vexa-lite:v0.12.28-pause1`. Begruendung: ein Update auf eine neue
  Vexa-Version heisst dann „Patch neu anwenden und Tests laufen lassen“, nicht
  einen Fork nachziehen. *(meine Festlegung)*
- Bot: Act-Kontrakt um `{ action: 'pause' }` und `{ action: 'resume' }` erweitern.
  Bei `pause`: Ton nicht mehr an Whisper geben, bereits gepufferten, noch nicht
  transkribierten Ton verwerfen; bei `resume`: wieder normal. Gilt fuer den
  Jitsi-Weg (`jitsi-capture` / Live-Pipeline). Der Bot meldet den neuen Zustand
  zurueck (Lifecycle-/Status-Ereignis), damit unsere Seite den BESTAETIGTEN
  Zustand zeigen kann.
- Meeting-API: ein Weg, `pause`/`resume` an den Bot eines Meetings zu schicken
  (z. B. Erweiterung von `PUT /bots/{platform}/{native_meeting_id}/config` oder
  eigener Endpunkt) und den Pausenzustand lesbar zu machen.
- Ein Satz, der beim Pausen-Beginn schon transkribiert ist, bleibt; was noch im
  Puffer liegt, ist weg. *(meine Festlegung – im Zweifel lieber weg)*

### 2. Pausenzustand in unserer DB

- `termin_akten` bekommt den Wunschzustand (`aufnahme_pause_gewuenscht`,
  bool) und den bestaetigten (`aufnahme_pausiert_seit`, timestamptz null).
- Tabelle `termin_pausen` (uid, von, bis, angefordert_von, bestaetigt_am) – Quelle
  fuer die Luecke in der Mitschrift und fuer den Verlauf.
- Provision ueber `db/provision.sql` (Schema-Loop), Rechte wie die Nachbartabellen.

### 3. `sales-termine`: schneller Pausenweg

- Der normale Takt (30 s) ist fuer eine DSGVO-Pause zu langsam. Eigener kurzer
  Weg in `sales-termine` nur fuer laufende Akten: reagiert auf einen Wunsch
  innerhalb von **hoechstens 2 Sekunden** (Postgres `LISTEN/NOTIFY` bevorzugt,
  sonst 1-s-Abfrage nur der laufenden Akten). *(meine Festlegung: 2 s)*
- Schickt `pause`/`resume` an Vexa, traegt nach Bot-Bestaetigung
  `aufnahme_pausiert_seit` bzw. die Pausenzeile ein. Kommt binnen 10 s keine
  Bestaetigung: Zustand „Pause nicht bestaetigt“ (laut auf der Seite),
  Betreiber-Hinweis wie bei anderen Bot-Fehlern.

### 4. `sales-auge`

- Die Soll-Bedingung (`bildschirm._SOLL`) bleibt; zusaetzlich speichert der
  Beobachter kein Bild, solange `aufnahme_pause_gewuenscht` gesetzt ist – also
  schon ab dem WUNSCH, nicht erst ab der Bot-Bestaetigung. Der Beobachter bleibt
  im Raum (kein Austreten/Eintreten). Reaktionszeit ebenfalls ≤ 2 s.

### 5. Live-Transkript

- `sales-termine` holt fuer laufende Akten die Segmente alle **5 s** und legt sie
  live in der Akte ab (dieselbe Ablage wie heute nach Terminende, nur frueher und
  wiederholt). Die Seite fragt alle 3 s ein JSON ab (Muster `bilder.json`/`bilder.js`).
  *(meine Festlegung: 5 s / 3 s)*

### 6. Die Seite

```
┌────────────────────────────────────────────────────────┐
│ Kurs mit Diana · 11:35–12:35   [ Meeting öffnen ↗ ]     │
│ ● Aufnahme läuft     [ Pause ]   [ Notbremse: Bot raus ]│
├───────────────────────────┬────────────────────────────┤
│ Transkript live           │ Bilder live (Kacheln)       │
│ 11:41 Diana: …            │                             │
│ ── Pause 11:43–11:47 ──   │                             │
└───────────────────────────┴────────────────────────────┘
```

- Das Meeting oeffnet per Knopf in einem eigenen Tab (s. Entscheidungen);
  kein iframe, kein Fremd-Skript.
- Von der bestehenden Akte `/termine/<uid>` ein Link „Live-Ansicht“, solange die
  Akte in `wartet_auf_einlass`/`laeuft` ist.
- Knopf sendet POST mit CSRF; Seite zeigt Wunsch („wird pausiert …“) bis zur
  Bestaetigung, danach den bestaetigten Zustand.
- Notbremse: Knopf „Bot entfernen“ (vorhandener Weg ueber Status-Wechsel), falls
  die Pause nicht bestaetigt wird.

### 7. Mitschrift, Briefing, Verlauf

- Mitschrift und Bildschirm-Ansicht zeigen Pausen als Luecke mit Zeitraum.
- Der Verlauf der Akte nennt Pause/Weiter mit Zeitpunkt und wer.

## Entscheidungen nach Builder-Check (Felix, 20.11.: „ok“)

- **Kein Einbetten (Weg a).** `meet.ffmuc.net` verbietet Einbetten
  (`frame-ancestors` nur fuer eigene Domains, `X-Frame-Options: SAMEORIGIN`,
  geprueft 20.11.). Die Steuerseite oeffnet das Meeting per Knopf in einem
  eigenen Tab (`target="_blank"`, `rel="noopener"`); die Seite selbst zeigt
  Steuerung, Live-Transkript und Live-Bilder. Kein `frame-src` noetig. Ein
  eigener Jitsi-Server (Einbetten frei) kommt spaeter mit Webinaren/Festival-Bot.
  Abschnitt 6 (iframe) ist damit ersetzt.
- **Ende-zu-Ende-Test des Vexa-Patches durch kurzen Tausch in Prod:** in einem
  Fenster ohne Bot-Termine (alle drei Laeden pruefen) `vexa-lite` auf das
  Patch-Abbild umstellen, mit einem Test-Jitsi-Raum pruefen (Pause → kein Text,
  auch nicht aus den Sekunden nach dem Klick; Weiter → Text), bei Fehler sofort
  zurueck auf `vexaai/vexa-lite:v0.12.28`. Claim im Koordinations-Dokument vorher.

## Nachtraege nach Builder-Check (20.11., meine Festlegungen)

- **Pausenbeginn = Klickzeit.** Der `pause`-Act traegt den Zeitpunkt des Klicks.
  Der Bot verwirft jedes Whisper-Ergebnis fuer Ton ab diesem Zeitpunkt, auch wenn
  es erst nach der Bestaetigung zurueckkommt. Was zwischen Klick und Ankunft des
  Acts schon als Segment gespeichert wurde, loescht der Vexa-Patch beim Pausieren
  aus Vexas Segment-Ablage (Segmente mit Beginn ≥ Klickzeit). Bei uns wird ein
  solches Segment ebenfalls nie uebernommen. Damit gilt „lieber weg“ hart.
- **Notbremse** laeuft ueber den schnellen Weg (≤ 2 s): Bot verlaesst den Raum,
  das Material VOR der Pause bleibt erhalten (neuer Ablauf, nicht
  `aufnahme_beenden`, das alles loescht). Der Bildbeobachter tritt mit aus.
- **Live-Transkript** liegt in einer eigenen Live-Ablage, nicht in
  `termin_mitschriften` (dort heisst eine Zeile „fertig“, Auswertung/Rubrik/
  Kursmitschrift haengen daran). Am Terminende entsteht die Mitschrift wie heute;
  die Live-Ablage wird danach geleert.
- **Verlauf** = nur auf der Akte (Liste aus `termin_pausen`), nicht in der
  Kontakt-Historie/CRM.

## Dem Bauer ueberlassen

- Genaue Stelle im Vexa-Bot, an der der Ton zu Whisper geht, und wie der Puffer
  dort verworfen wird.
- Ob die Meeting-API-Erweiterung ueber `PUT …/config` oder einen eigenen Endpunkt laeuft.
- `LISTEN/NOTIFY` vs. 1-s-Abfrage, solange ≤ 2 s gehalten werden.
- Spaltennamen, Tabellenform, JSON-Format der Live-Abfrage.
- Wie das Patch-Abbild getestet wird (mindestens: Bot-Tests des Act-Kontrakts
  laufen gruen; ein Ende-zu-Ende-Test in einem Test-Jitsi-Raum vor dem Rollout).
