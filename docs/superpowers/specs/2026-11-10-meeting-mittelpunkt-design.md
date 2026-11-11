# Meeting-Mittelpunkt: Termin, Briefing, Mitschrift

Stand: 2026-11-10 · Laden: nur Felix (`sales`) · Status: **freigegeben von Felix am 10.11.**, Jitsi-Tor bestanden am 11.11. (§6)

## 1. Warum

Felix führt Kundengespräche gemischt am PC und am Handy, über Meet, Teams, Zoom und Jitsi. Heute
steht im sales-claw-Kalender zu einem Termin wenig mehr als Zeit, Thema und Ort. Was im Gespräch
gesagt wurde, steht nirgends.

Felix will drei Dinge:

- Mit einem Tipp ins Gespräch kommen, egal auf welcher Plattform.
- Vorher kurz wissen, mit wem er spricht und was offen ist.
- Auch nach Monaten nachvollziehen können, was er mit einem Kunden besprochen hat, vor allem die
  Painpoints.

Seine Worte: „In diesem Kalender müssen so datenreiche Events drinstehen, dass eine AI damit
arbeiten kann.“

Grundsatz aus dem Auftrag: **nichts doppelt bauen**. Wo sales-claw schon etwas hat (Termine,
Kontakte, Freigabe, Kalender-Abgleich, Videoräume), wird es erweitert, nicht ersetzt.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

**Ziele**

1. **Termin-Akte:** Jeder Kundentermin hat eine eigene Seite mit großem „Beitreten“-Knopf und allen
   Daten (Teilnehmer, Beschreibung, Einwahl, Link, Verlauf). Dieselben Daten gibt es als JSON für
   Agenten.
2. **CRM-Verknüpfung:** Teilnehmer eines Termins sind Kontakte im CRM. Unbekannte werden angelegt.
3. **Briefing:** etwa 30 Minuten vor dem Termin, mit Hinweis aufs Handy und auf den PC.
4. **Mitschrift:** Ein Bot nimmt am Gespräch teil und schreibt mit. Danach entsteht lokal eine
   Auswertung als Markdown, und das CRM wird ergänzt.

**Nicht-Ziele (diese Stufe)**

- Ivans Laden. Alles hier gilt nur für `sales`.
- Ein eigener Jitsi-Server. Felix will Jitsi als Open-Source-Linie. Ein selbst betriebenes Jitsi ist
  ein eigenes, späteres Vorhaben (§11).
- Die Google-Kalender-Anbindung (Runbook Teil B) und die Reparatur des Meet-Schlüssels. Beides ist
  zurückgestellt. Die Akte nutzt, was Teil A heute liefert, und nimmt Google-Daten mit, sobald es
  sie gibt.
- Telefontermine ohne Link. Sie bekommen Akte und Briefing, aber keine Mitschrift.
- Video- oder Audioaufzeichnung. Gespeichert wird nur der Text.

**Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)**

- Gesprochenes oder Kundentext geht an einen KI-Anbieter in der Cloud.
- Etwas geht ohne Felix' Freigabe an den Kunden.
- Der Bot bleibt im Gespräch oder die Mitschrift bleibt liegen, nachdem der Kunde Nein gesagt hat.
- Ein Kontakt mit Löschantrag oder Privat-Vermerk taucht wieder auf.
- Daten aus Felix' Laden landen in Ivans Laden oder umgekehrt.

## 3. Was Felix entschieden hat

Diese Punkte stehen fest. Der Builder hält sich daran.

| Thema | Entscheidung |
|---|---|
| Mitschrift | **Immer an.** Zweck: nachvollziehen, was mit jedem Kunden besprochen wurde, auch nach Monaten. |
| Einwilligung | Felix fragt **selbst zu Beginn** des Gesprächs, ausdrücklich. |
| Nein des Kunden | **Ein Klick** wirft den Bot hinaus und verwirft die Mitschrift. Der Termin bekommt den Vermerk „ohne Aufnahme“. |
| Auswertung | Alles Verwertbare festhalten, **vor allem Painpoints**. Format: **Markdown**, keine Tabelle, damit es später weiterverarbeitet werden kann. |
| KI | Auswertung von Briefing und Mitschrift **lokal mit Ollama**. Kein Kundentext an einen KI-Anbieter. |
| Zusammenfassung an Kunden | **Nur wenn der Kunde sie will.** Felix fragt zu Beginn und setzt dann mit einem Klick „will Zusammenfassung“. Daraus entsteht ein Entwurf, der nur nach Freigabe rausgeht. |
| Unbekannte Teilnehmer | **„Muss im CRM stehen.“** Sie werden angelegt. |
| Briefing | Hinweis **aufs Handy und auf den PC** über den Bot-Kanal. Felix: Telegram oder WhatsApp reicht, beides gibt es auch am PC. |
| Termin-Ansicht | **Variante C:** großer „Beitreten“-Knopf oben, darunter die Reiter **Details / Briefing / Verlauf**, nach dem Gespräch zusätzlich **Mitschrift**. |
| Beitritt | Felix nimmt gemischt teil (PC und Handy). Die Mitschrift muss **immer** funktionieren, unabhängig vom Gerät. Sprecherzuordnung ist erwünscht. |
| Bot | Er kommt **von selbst**, ohne dass Felix ihn schickt. Felix lässt ihn einmal aus dem Wartebereich herein. |
| Videoraum-Anbieter | **Beides:** Meet und Jitsi. Jitsi ist die Linie, die als Open Source betrieben werden soll. |
| Welche Termine | **Kundentermin** = jeder sales-claw-Termin, außerdem jeder Kalendertermin aus einer Geschäftsquelle mit **mindestens einem externen Teilnehmer**. Extern heißt: nicht Felix, nicht Team (Ivan und alle mit Login im Laden), keine Ressource. Termine mit **mehr als 10 Teilnehmern** (Webinare) zählen nicht. Auf der Termin-Seite kann Felix vorher **„Kein Bot“** setzen. Nur Kundentermine bekommen Akte, Bot und neue Kontakte. |
| Jitsi | **Erst testen.** In der nächsten Testrunde wird Vexa auf meet.jit.si geprüft. Klappt es, bleibt der Plan. Klappt es nicht, entscheidet Felix neu (eigenes Jitsi in diese Stufe oder Jitsi vorerst ohne Mitschrift). Das ist ein Tor **vor** dem Planen. |
| Fremde Gespräche | Lädt der Kunde ein (Felix ist nur Gast), **klopft der Bot trotzdem an**. Der Gastgeber des Kunden lässt ihn herein. |

## 4. Rahmen

- **Laden-Trennung:** Alles läuft im Schema `sales` mit der Rolle von Felix' Laden. Kein Zugriff
  auf `sales_ivan`. Der Bot-Dienst und seine Daten sind Felix' Laden zugeordnet.
- **Sperren:** Kontakte mit `_loeschantrag`, `_privat` oder einem Eintrag in `compliance.sperrliste`
  werden nie angelegt, nie verknüpft und erscheinen nie in Briefing, Akte oder Hinweis.
- **Geheimnisse und Kundentext nicht in Logs.** Das gilt auch für Mitschriften, Teilnehmeradressen
  und Meeting-Passcodes.
- **Prüfen gegen `sales_test`.** Schreibende SQL-Tests laufen nur dort.
- **Freigabe-Weg:** Alles an Kunden läuft über `drafts` und die bestehende Freigabe. sales-claw ist
  der einzige Sende-Weg.
- **Ausrollen:** kein Deploy und kein Start ohne Felix' OK. VM- und PC-Arbeit wird vorher in
  `secondbrain/00_Meta/002_Koordination_Live.md` eingetragen.
- **Lokale Modelle:** `.env.example` schließt lokale Modelle für sales-claw aus („die Maschine trägt
  es nicht“). Das gilt für die VM weiter. Für die Auswertung in diesem Vorhaben hebt Felix' Entscheidung
  den Ausschluss auf, mit Ollama auf dem **PC** (§7). Der Kommentar in `.env.example` wird
  entsprechend angepasst. Der Agent-Weg über OpenClaw bleibt unverändert.

## 5. Die vier Teile

### 5.1 Termin-Akte

**Heute:**
- Kundentermine stehen append-only in `activities` (`type='termin'`, Payload mit `datum`,
  `uhrzeit`, `dauer_minuten`, `thema`, `ort`, `uid`).
- Fremde Kalendertermine stehen in `kalender_termine`, nur mit `titel`, `ort` und Zeiten.
- Eine Einzelansicht gibt es nur als Dialog im Kalender (`kalender/src/fenster.ts`).
- Ein Videoraum-Link steht nur in `ort`.

**Neu: eine Termin-Akte je Termin**, über `uid` an den bestehenden Termin gebunden. Sie ersetzt die
Ereignisse in `activities` nicht, sondern sammelt alles an einer Stelle. Inhalt:

- **Zeit:** Beginn, Ende, Zeitzone.
- **Herkunft:** `sales-claw` oder `kalender` (Quelle).
- **Titel und Thema.**
- **Beitreten:** Link, Plattform (`google_meet`, `teams`, `zoom`, `jitsi`, `sonstige`), Passcode
  (nur gespeichert, nie geloggt) und Telefoneinwahl, falls vorhanden.
- **Teilnehmer:** Name, Adresse, Rolle (Organisator/Gast), `lead_id` oder „nicht verknüpft“ mit Grund.
- **Beschreibung/Agenda**, einzeilig bereinigt wie bei den Rowboat-Notizen.
- **Mitschrift-Status:** `geplant`, `wartet_auf_einlass`, `läuft`, `fertig`, `ohne_aufnahme`,
  `fehlgeschlagen` (mit Grund), `kein_link`.
- **Schalter:** `will_zusammenfassung` (Felix' Klick).
- **Verweise** auf Briefing, Mitschrift, Auswertung und Entwurf.

**Daten füllen:**
- Termine aus sales-claw: aus der Payload. Der Link kommt aus `ort`.
- Termine aus Kalenderquellen: Der Abgleich (`kalender_abgleich.py`) übernimmt zusätzlich
  Beschreibung, Teilnehmer und Konferenzlink. Bei iCal sind das `DESCRIPTION`, `ATTENDEE`,
  `ORGANIZER`, `URL` und die `X-…-CONFERENCE`-Felder. Bei Google kommen `conferenceData`,
  `hangoutLink`, `attendees` und `description` dazu, sobald Teil B lebt.
- Für Quellen mit `bereich=privat` gilt weiter `kalender_sichtbarkeit.details_speichern`: Von dort
  wird nichts übernommen, und es entsteht keine Akte.
- Der Link wird aus Ort, Beschreibung und Konferenzdaten erkannt. Der Builder pflegt dafür eine
  Musterliste je Plattform (meet.google.com, teams.microsoft.com, teams.live.com, zoom.us/j und
  Subdomains, meet.jit.si sowie Hosts aus einer Liste `JITSI_HOSTS`).

**Termin-Seite in sales-ui (Variante C):** neue Route `/termine/{uid}`, für das Handy gebaut:
- Oben Titel, Kunde mit Firma, Zeit und der große Knopf **„Beitreten“**. Er öffnet den Link direkt,
  am Handy also die jeweilige App.
- Darunter die Reiter **Details** (Teilnehmer, Beschreibung, Einwahl, Agenda), **Briefing** und
  **Verlauf** (alle Mails, Termine und früheren Mitschriften zum Kontakt).
- Nach dem Gespräch kommt der Reiter **Mitschrift** dazu.
- Während des Gesprächs zeigt die Seite den Bot-Status und zwei Knöpfe: **„Ohne Aufnahme“** und
  **„Will Zusammenfassung“**.
- Der Kalender-Dialog und der Reiter „Termine“ am Kontakt verlinken auf diese Seite.

**Für Agenten:** `GET /termine/{uid}.json` mit derselben Akte und ein MCP-Werkzeug
`termin_akte_lesen(uid)`. Beide geben gesperrte Kontakte nicht aus.

### 5.2 CRM-Verknüpfung

- **Bekannte Adresse:** Jeder Teilnehmer wird über die E-Mail-Adresse mit `leads` verknüpft.
- **Unbekannte Adresse:** Es wird ein Kontakt angelegt mit `source='aus Kalender'`,
  `consent_status='unknown'`, Name aus dem Kalendereintrag und Firma aus der Domain, wenn sie
  eindeutig ist (Vermutung, siehe §9).
- **Nie angelegt werden:**
  - Felix' eigene Adressen. Der Builder nimmt die Postfächer und Absender aus der Konfiguration des
    Ladens.
  - Adressen auf der Sperrliste, mit Löschantrag oder mit Privat-Vermerk.
  - Kalender-Ressourcen (Räume, Gruppen, `noreply`-Adressen).
  - Teilnehmer aus Quellen mit `bereich=privat`.
- **Keine Werbung:** Ein angelegter Kontakt bekommt keine Werbe-Ansprache. Die bestehende
  UWG-Prüfung in `_entwurf_erstellen` bleibt die Schranke. Anlegen ist nicht Einwilligen.
- **Verlauf:** Jede Verknüpfung erscheint im Verlauf des Kontakts als Termin-Ereignis.

### 5.3 Briefing

- **Wann:** etwa 30 Minuten vor Beginn. Neu erstellt wird nur, wenn sich der Termin oder die Daten
  zum Kontakt seitdem geändert haben.
- **Inhalt**, aus sales-claw zusammengesetzt:
  - wer (Name, Rolle, Firma) und woher (Quelle, erster Kontakt)
  - letzte Kontakte (Mails, Nachrichten, Termine)
  - offene Zusagen und Wiedervorlagen
  - Painpoints aus früheren Mitschriften
  - Ziel des Termins, sofern bekannt
- **Zwei Schichten:**
  1. Ein **Faktenteil** ohne KI, immer verfügbar.
  2. Ein kurzer **Fließtext** von Ollama. Fehlt Ollama (PC aus), gibt es nur den Faktenteil mit dem
     Vermerk „ohne KI-Text“.
- **Hinweis an Felix:** direkt über die Telegram-Bot-API an `TELEGRAM_CHAT_ID`, so wie es
  `deploy/token-ablauf-waechter.sh` heute schon macht. Er läuft nicht über den OpenClaw-Agenten, damit
  Kundendaten kein Cloud-Modell berühren.
  - Inhalt: Uhrzeit, Kunde, Thema und zwei Links, **„Briefing öffnen“** (Termin-Seite) und
    **„Beitreten“**. Keine weiteren Kundendaten.
  - Telegram erscheint auf Handy und PC.
- **Anzeige:** im Reiter Briefing der Termin-Seite.

### 5.4 Mitschrift und Auswertung

**Bot: Vexa, selbst betrieben auf der VM.** Grund: Nur ein Bot, der wie ein Teilnehmer beitritt,
funktioniert unabhängig davon, ob Felix am PC oder am Handy ist. Auf dem Gerät mitzuschneiden geht am
Handy nicht.

Gewählt wurde Vexa (Apache-2.0):
- deckt Meet, Teams, Zoom und Jitsi ab
- Spracherkennung mit faster-whisper lokal
- Sprechernamen aus der Plattform

Verworfen wurden Attendee (ELv2, kein Jitsi, nur Deepgram-Cloud) und Jibri (nur mit eigenem Jitsi).

**Betrieb:**
- Eigenes Compose-Projekt auf der VM. Ports nur `127.0.0.1`.
- Spracherkennung `Systran/faster-whisper-small` auf der CPU. Sprache Deutsch voreingestellt,
  englische Passagen kommen trotzdem richtig (Spike).
- Kein Audio gespeichert (`recording_enabled=false`).
- Image-Version fest gepinnt.
- Die Agent-Funktionen von Vexa bleiben aus, ohne Modell-Schlüssel.
- Vexas eigenen Kalender-Abgleich nutzen wir nicht. sales-claw sagt Vexa, wann es wohin soll.

**Ablauf:**

1. **Einplanen:** Ein Taktgeber in sales-claw schickt etwa 1 Minute vor Beginn jedes Termins mit
   erkanntem Link den Bot: `POST /bots` mit `bot_name="VibeMind Mitschrift"`, `language="de"`,
   `recording_enabled=false` und `automatic_leave.max_wait_for_admission` = 30 Minuten.
   Vexas eigenes Auto-Join nutzen wir nicht. Im Spike hat es Name und Sprache nicht übernommen und
   ist an einer Schlüsselprüfung gescheitert.
2. **Einlass:** Felix lässt den Bot herein. Der Kunde sieht „VibeMind Mitschrift“ in der
   Teilnehmerliste.
3. **Nein:** „Ohne Aufnahme“ stoppt den Bot (`DELETE /bots/...`) und löscht die Mitschrift in Vexa
   (`DELETE /meetings/{id}`). Bei sales-claw kommt nichts an. Die Akte bekommt den Status
   `ohne_aufnahme`.
4. **Ende:** Der Bot geht von selbst, wenn alle weg sind. Danach holt sales-claw die Segmente
   (Sprecher, Zeit, Text) und löscht sie bei Vexa. Gespeichert werden sie **an der Termin-Akte**,
   nicht an einem einzelnen Kontakt. Die Akte ist mit allen verknüpften Teilnehmern verbunden. So hat
   eine Mitschrift auch dann einen Ort, wenn mehrere oder gar keine Kontakte verknüpft sind. Im
   Verlauf jedes verknüpften Kontakts erscheint ein Verweis darauf.
5. **Auswertung (Ollama, PC):** Aus der Mitschrift entsteht ein Markdown-Dokument, gespeichert als
   Ereignis `termin_auswertung`. Abschnitte:
   - Kurzfassung
   - **Painpoints**, wörtlich belegt mit Zeitmarke
   - Ziele und Wünsche des Kunden
   - Zahlen und Fakten (Mitarbeiter, Tools, Budget, Fristen)
   - Einwände und Bedenken
   - Zusagen von Felix
   - Zusagen des Kunden
   - Nächste Schritte mit Termin
   - Entscheider und Beteiligte
   - Offene Fragen
   - Stimmung
6. **CRM:**
   - Das **Termin-Ergebnis** wird nur **vorgeschlagen** (stattgefunden, Erfolg, `was`). Felix
     bestätigt es mit einem Klick auf der Termin-Seite, erst dann schreibt `_termin_ergebnis`. Grund:
     `_termin_ergebnis` setzt die Pipeline-Stufe, geht nur einmal je Termin und darf laut Code „nur mit
     der Antwort des Betreibers, nie geraten“ schreiben.
   - Termine, die nur aus dem Kalender kommen, haben keine `termin`-Zeile in `activities`. Für sie
     legt das Bestätigen eine an.
   - Zusagen werden als Wiedervorlagen vorgeschlagen.
   - Painpoints kommen in den Verlauf.
   - Feldänderungen am Kontakt (Status, Rolle, Firma) werden nur vorgeschlagen.
   - Alle Vorschläge bestätigt Felix auf der Termin-Seite.
7. **Rowboat:** Die Auswertung erscheint als eigene Notiz neben der Termin-Notiz
   (`companys/<Firma>/Termine/`, `parent` auf die Termin-Notiz). Zuständig ist der Geschäftsdaten-Lauf
   im Repo **vibemind-os** (`spaces/rowboat/geschaeftsdaten/`, Timer auf der VM). Er liest über die
   Sichten für `rowboat_leser` (`sales.rowboat_ereignisse`) und wendet dieselbe Bereinigung an. Die
   Sicht und der Lauf werden um Auswertungen erweitert. Das ist Arbeit in vibemind-os, nicht in
   sales-claw.
8. **Zusammenfassung an den Kunden:** Nur wenn `will_zusammenfassung` gesetzt ist, entsteht über
   `_entwurf_erstellen` ein E-Mail-Entwurf an den Kunden. Inhalt ist eine kundentaugliche Fassung
   ohne interne Abschnitte (Einwände, Stimmung). Er geht nur nach Felix' Freigabe raus.

**Einladungstext** (`server.py` bei `_termin_einladen`): Bekommt eine Zeile, dass VibeMind das
Gespräch mitschreibt, die Mitschrift auf eigenen Servern bleibt und der Kunde zu Beginn Nein sagen
kann. Wortlaut legt der Builder vor, Felix gibt ihn frei.

**Verwerfen geht auch danach:** „Ohne Aufnahme“ bleibt nach dem Gespräch als **„Mitschrift
verwerfen“** auf der Termin-Seite. Es löscht Mitschrift, Auswertung, Rowboat-Notiz, Verlaufs-Verweise
und alle noch offenen Vorschläge dieses Termins. Dafür trägt alles Abgeleitete einen Verweis auf
seine Mitschrift. Bestätigte Vorschläge bleiben, die hat Felix selbst entschieden.

**Gesperrte Teilnehmer:** Steht ein eingeladener Teilnehmer auf der Sperrliste oder hat einen
Löschantrag oder Privat-Vermerk, schickt der Taktgeber **keinen Bot**. Die Akte bekommt den Status
`ohne_aufnahme` mit Grund „gesperrter Teilnehmer“.

**Aufbewahrung:**
- Mitschrift und Auswertung bleiben, solange die Akte besteht.
- Löschantrag eines Teilnehmers löscht Mitschrift und Auswertung **aller Termine, an denen er
  teilgenommen hat**. Das ist einfacher und sicherer als seine Sätze einzeln herauszuschneiden.
- Bei Vexa bleibt nach dem Abholen nichts.

## 6. Plattformen und was der Spike gezeigt hat

Spike vom 09.–11.11. auf der VM (Vexa v0.12.28, Wegwerf-Aufbau). Am 11.11. komplett abgebaut. Der
echte Betrieb wird neu und sauber aufgesetzt.

| Prüfung | Ergebnis |
|---|---|
| Deutsche Erkennung (CPU, small) | fehlerfrei. 14 s Sprache in 3,6 s, warm |
| Meet: Anklopfen, Einlass, Live-Mitschrift | ✅ in ~20 s im Gespräch, Segmente live |
| Meet: Sprechername | ✅ „felix Baumann“ aus der Plattform |
| Gemischte Sprache (de/en) | ✅ englischer Satz korrekt als Englisch |
| Last im Gespräch | ~¼ Kern, ~2,6 GB RAM gesamt |
| Wartezeit, Aufgeben ohne Einlass | ✅ wie eingestellt |
| Vexa-Auto-Join | ❌ scheiterte an Schlüsselprüfung, ignoriert Name/Sprache (deshalb eigener Taktgeber) |
| Zwei Sprecher | offen |
| Teams, Zoom | offen |
| Jitsi auf meet.jit.si | ❌ für uns unbrauchbar: Seit 2023 öffnet der Raum erst, wenn ein Moderator angemeldet ist (Google/GitHub). Ein Kunde, der vor Felix kommt, steht vor einem verschlossenen Raum, und der Bot wartet ins Leere |
| Jitsi auf meet.ffmuc.net (Freifunk München) | ✅ 11.11.: Bot ohne Anmeldung und ohne Einlass im Raum, ~1 Min. freie Rede durchgehend mitgeschrieben (11 Segmente, live), Sprechername „Felix Baumann“, Deutsch gut lesbar. Eigennamen und Fachwörter verhört das kleine Modell („BAV“ ja, Firmennamen nein). Allein gelassen geht der Bot selbst (`left_alone`) |

**Jitsi-Tor: bestanden** (11.11.). Der Plan darf geschrieben werden.

Die offenen Zeilen sind **Abnahmetests** (§10). Fällt im Betrieb eine Plattform durch, bekommt deren
Termin den Status `fehlgeschlagen` mit Grund, und der Rest funktioniert weiter.

**Ausnahme Jitsi:** Der Jitsi-Test ist ein Tor vor dem Planen (§3). sales-claw legt eigene Videoräume
heute auf meet.jit.si an, weil der Meet-Schlüssel kaputt ist. Ohne Jitsi hätten Felix' eigene Termine
also meist keine Mitschrift.

**Meine Entscheidung aus dem Test (Felix kann widersprechen):** sales-claw legt Jitsi-Räume künftig auf
**meet.ffmuc.net** an statt auf meet.jit.si (`JITSI_BASIS` in `sales-mcp/konferenz.py`, als
Einstellung `JITSI_BASIS` mit diesem Standard). Grund: Dort braucht weder Felix noch der Kunde eine
Anmeldung, und der Bot kommt ohne Einlass hinein. Der Server steht in München und wird vom Freifunk
München betrieben. Mit dem eigenen Jitsi (§11) wird nur diese Einstellung umgestellt. Vexa erkennt
`meet.*`-Adressen bei gezielt übergebenen Links selbst; für den Taktgeber wird der Host zusätzlich in
`VEXA_JITSI_HOSTS` eingetragen, damit auch die Kalender-Erkennung ihn kennt.

## 7. Ollama

- **Wo:** auf dem PC (RTX 3060, 12 GB). Die VM hat keine Grafikkarte und trägt es nicht.
- **Zugang:** Die VM erreicht Ollama über Tailscale, wie heute schon sales-stt. Ollama läuft heute nicht
  dauerhaft. Es wird als Dienst beim Anmelden gestartet, nach dem Muster der bestehenden PC-Aufgaben.
- **Warteschlange:** Ist der PC aus, warten Auswertungen und werden nachgeholt. Das Briefing fällt
  auf den Faktenteil zurück.
- **Modell:** Wahl beim Builder, mit einer kurzen Vergleichsprobe auf deutschen Gesprächstexten.
  Installiert sind unter anderem `gemma4`, `qwen2.5:7b` und `llama3.1:8b`. Lange Mitschriften
  werden abschnittsweise verarbeitet.
- **Abgrenzung:** Es geht nur Text zu Ollama, nichts an OpenRouter, Anthropic oder einen anderen
  Anbieter. Ein Test stellt sicher, dass Auswertung und Briefing keinen anderen Endpunkt kennen.

## 8. Was dem Builder überlassen ist

- Tabellen- und Spaltennamen der Akte, und ob sie Tabelle oder Sicht über `activities` und
  `kalender_termine` ist.
- Takt des Taktgebers. Ob Bot-Start und Briefing in einem oder zwei Diensten laufen.
- Prompt-Aufbau, Stückelung langer Mitschriften, Modellwahl (§7).
- Aussehen der Termin-Seite im Rahmen von Variante C. Vorlage ist das Bild aus dem Brainstorming.
- Wie die Musterliste für Links gepflegt wird.
- Wo die Telegram-Chat-ID herkommt. Sie ist heute leer: Felix schreibt dem Bot einmal, der Builder
  liest die ID aus und legt sie verdeckt ab.

## 9. Meine Annahmen (bitte beim Lesen prüfen)

Diese Punkte hat Felix nicht entschieden. Ich habe sie so gesetzt:

1. **Telegram statt WhatsApp** für den Hinweis. Der WhatsApp-Weg an Felix läuft heute über den
   OpenClaw-Agenten, also ein Cloud-Modell. Telegram geht direkt.
2. **Kein Audio speichern**, nur Text.
3. **Termin-Ergebnis, Wiedervorlagen und Feldänderungen nur als Vorschlag**, den Felix bestätigt.
   Nur Verweise im Verlauf werden direkt geschrieben.
8. **Mitschrift an der Akte**, nicht an einem Kontakt. Löschantrag eines Teilnehmers löscht die
   Mitschriften aller seiner Termine.
9. **Kein Bot**, wenn ein gesperrter Teilnehmer eingeladen ist.
10. **„Mitschrift verwerfen“ auch nach dem Gespräch**, mit allem Abgeleiteten.
4. **Firma aus der Mail-Domain** nur bei Firmendomains, nicht bei gmail/web.de usw.
5. **Eigener Taktgeber statt Vexa-Auto-Join** (§5.4).
6. **Hinweiszeile in der Einladung** zusätzlich zur Frage zu Beginn.
7. **Nur Felix' Laden** in dieser Stufe.

## 10. Abnahme

1. Ein Termin mit Videoraum aus sales-claw (heute Jitsi, nach der Reparatur Meet): Akte vollständig,
   „Beitreten“ öffnet am Handy die passende App.
1a. Ein Kalendertermin nur mit Ivan und ein Webinar mit 30 Teilnehmern: **keine** Akte, kein Bot,
   keine neuen Kontakte. Ein Termin mit „Kein Bot“: Akte und Briefing, aber kein Bot.
2. Ein Termin aus einer iCal-Quelle mit Teams-Link und zwei Gästen:
   - Akte mit Link und Teilnehmern
   - ein bekannter Gast verknüpft
   - ein unbekannter Gast als Kontakt `aus Kalender` angelegt
   - Felix' eigene Adresse und eine gesperrte Adresse **nicht** angelegt
3. 30 Minuten vorher kommt der Telegram-Hinweis mit beiden Links. Das Briefing zeigt Fakten und
   KI-Text. Bei ausgeschaltetem Ollama nur Fakten mit Vermerk.
4. Je ein echtes Testgespräch auf **Meet, Teams, Zoom und Jitsi** mit zwei Sprechern und mindestens
   5 Minuten:
   - Bot kommt von selbst und steht im Wartebereich
   - Sprecher richtig zugeordnet
   - Deutsch gut lesbar
   - Ergebnis je Plattform im Protokoll
5. „Ohne Aufnahme“ während des Gesprächs: Bot weg innerhalb von 30 s, bei sales-claw und Vexa keine
   Mitschrift, Status `ohne_aufnahme`.
6. Nach dem Gespräch:
   - Auswertung mit allen Abschnitten im Reiter Mitschrift
   - Painpoints mit Zeitmarke
   - Termin-Ergebnis vorausgefüllt
   - Rowboat-Notiz neben der Termin-Notiz
7. „Will Zusammenfassung“ gesetzt: Entwurf erscheint in `/freigaben` und geht erst nach Freigabe raus.
   Ohne den Schalter entsteht kein Entwurf.
8. Netzwerkprobe: Während Briefing und Auswertung geht keine Verbindung an einen KI-Anbieter.
9. In keinem Log steht Mitschrift-Text, Teilnehmeradresse oder Passcode.
10. Ivans Laden ist unverändert.

## 11. Danach

- **Eigenes Jitsi auf der VM** (Open-Source-Linie). Bis dahin dient meet.ffmuc.net (§6); danach
  wird nur `JITSI_BASIS` umgestellt. Eigenes Design.
- **Meet-Schlüssel reparieren** (Google-App veröffentlichen, braucht `vibemind.space/privacy` live).
  Bis dahin bekommen sales-claw-Einladungen mit Videoraum einen Jitsi-Link statt Meet. Dazu wird die
  falsche Aussage in `deploy/google-meet-zugang.py` korrigiert: Im Testmodus verfällt der Schlüssel
  nach 7 Tagen.
- **Google-Kalender (Teil B)**, damit Termine aus Felix' Google-Kalender mit allen Feldern kommen.
- Ivans Laden.
