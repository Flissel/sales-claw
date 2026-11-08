# Kalender verbinden: per Anmeldung, mit Besitzer und Business/Privat — Entwurf

Stand: 08.11.2026. Grundlage: Gespräch mit dem Betreiber (Felix) am 08.11.2026.
Markierung: **[Betreiber]** = so gesagt; **[Entwurf]** = Entscheidung des Entwurfs, änderbar.

## 1. Warum

Heute sieht der Betreiber im Kalender der Sales-UI bei zweien seiner eigenen
Kalender nur „felix: belegt“. Der Grund: Jeder über `/team/kalender` verbundene
Kalender gilt als Kollegen-Kalender, und die zeigen seit 28.10.2026 nur belegt/frei.
Alle drei verbundenen Kalender gehören aber ihm **[Betreiber]**.

Zweitens ist das Verbinden umständlich: Man braucht die geheime iCal-Adresse eines
Kalenders. Der Betreiber will das „easy“, per Anmeldung bei Google, auch für
künftige Teammitglieder **[Betreiber]**.

Erfolg heißt:
- Alle Kalender einer Person liegen übereinander in einer Ansicht.
- Ihre eigenen Termine sieht sie vollständig: Titel, Ort, von–bis.
- Von Teammitgliedern sieht sie die Business-Termine voll und die privaten nur als „Privattermin“ mit Zeit.
- Ein Teammitglied verbindet seinen Google-Kalender mit zwei Klicks.

## 2. Ziele

1. **Jeder Kalender hat einen Besitzer und eine Einordnung.**
   - Besitzer ist, wer ihn verbunden hat (angemeldeter Benutzer).
   - Die Einordnung ist **Business** oder **Privat**; der Besitzer wählt sie beim Verbinden und kann sie später ändern **[Betreiber]**.
2. **Sichtbarkeit je betrachtender Person** **[Betreiber]**:

   | Kalender von … | Business | Privat |
   |---|---|---|
   | mir selbst | voll (Titel, Ort, von–bis) | voll |
   | anderer Person im selben Laden | voll | nur Block „Privattermin“ mit von–bis, ohne Titel/Ort |

   „Selber Laden“ heißt: Der Kalender ist in diesem Laden verbunden. Teammitglieder
   melden sich im Laden des Betreibers an (heute Rolle `kalender`, z. B. `ivan`) und
   verbinden dort ihre Kalender. Das gilt als gemeinsames Business **[Entwurf]**.
3. **Der Agent sieht, was die Person sieht, für die er arbeitet** **[Entwurf, vom Betreiber nicht widersprochen]**.
   - Im Laden des Betreibers sieht er dessen eigene Kalender voll, Business der anderen voll und Privat der anderen als „Privattermin“.
   - Die Kollisionsprüfung (`termin_konflikte`, `termin_bestaetigen`, `termin_einladen`) zählt alle diese Zeiten als belegt.
   - Das ersetzt die Regel vom 28.10.2026 („Team-Kalender nur belegt, auch für den Agenten“).
4. **„Mit Google verbinden“**:
   - Der Knopf auf `/team/kalender` führt zur Google-Anmeldung.
   - Dort wählt man die Kalender des Kontos aus, die übernommen werden sollen, und gibt je Kalender Business oder Privat an.
   - Stufe 1 liest nur **[Entwurf; Betreiber: Eintragen in Google wäre „geschickt“, die Sales-UI reicht aber im Prinzip]**.
5. **Ebenen**:
   - Jeder Kalender ist eine eigene Ebene mit eigener Farbe.
   - Die betrachtende Person schaltet Ebenen für ihre Ansicht ein und aus. Das wirkt nur auf die Anzeige, nicht auf den Agenten **[Entwurf]**.
   - Der bisherige ladenweite Schalter „Team-Ebenen“ (Einstellung `kalender_team_aus`, wirkt auf Anzeige UND Agent) entfällt. Ersatz: Der Besitzer kann einen Kalender ganz abschalten (`aktiv`); dann zählt er auch für den Agenten nicht.
6. **Zeiten lesbar**:
   - In jeder Ansicht (Tag, Woche, Monat, Liste) steht von–bis, auch im Monat.
   - Die Schrift in Termin-Blöcken ist lesbar groß; ein Klick zeigt die Einzelheiten.
7. **Doppelte Termine einmal**:
   - Ein Termin, der in mehreren Kalendern derselben Person steht (gleiche UID, sonst gleicher Titel + gleicher Beginn + gleiches Ende), erscheint einmal.
   - Er bekommt einen Hinweis auf die Kalender, in denen er steht.
8. **Serientermine erscheinen** (heute fehlen sie: RRULE wird nicht aufgelöst, `kalenderquellen.py:279`).
   - Google liefert sie aufgelöst (`singleEvents=true`).
   - iCal-Adressen werden aufgelöst, z. B. mit `recurring-ical-events` **[Entwurf]**.
9. **Bestehende drei Kalender übernehmen**:
   - `felix`, `felix404-gmail` und der bisher inaktive `felix-gmail` bekommen Besitzer `felix`.
   - Die Einordnung wählt der Betreiber einmal in der Oberfläche.
   - Bis dahin gilt **Privat** **[Entwurf]**:
     - Für den Betreiber selbst macht das keinen Unterschied; er sieht seine Kalender ohnehin voll.
     - Im Laden gibt es aber schon den Login `ivan` (Rolle `kalender`). Er darf vor der Einordnung keine Titel sehen.
     - Neu verbundene Kalender haben nie einen Standard; die Wahl ist Pflicht.
   - Der CalDAV-Kalender aus `CALDAV_URL` (vibemind.space, heute Art `handy`/„Betreiber“) gehört dem Laden-Besitzer und ist Business **[Entwurf]**.

## 3. Nicht-Ziele (Stufe 1)

- **Eintragen in Google.** Neue Termine landen wie bisher in `eigene_termine` und per CalDAV in `CALDAV_URL`. Schreiben nach Google ist Stufe 2 und braucht einen eigenen Entwurf (Schreib-Scope, Zielkalender-Wahl, Konflikte).
- **Anmelde-Knopf für Microsoft/Outlook, iCloud, GMX.** Diese verbinden sich weiter über die iCal-Adresse. Ein Microsoft-Knopf folgt, wenn jemand ihn braucht.
- Personenübergreifende Identität über mehrere Läden. Wer in zwei Läden arbeitet, verbindet in jedem Laden einzeln.
- Freigaben einzelner Termine („diesen Privattermin doch zeigen“).
- Googles App-Prüfung (Verification). Stufe 1 lebt mit dem Warnhinweis und der Grenze von 100 Nutzern (siehe §5).

## 4. Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)

- **Titel oder Ort eines fremden Privattermins erscheinen irgendwo**, auch nicht in:
  - der Oberfläche, `/kalender/termine.json` oder dem Ergebnis eines Agent-Werkzeugs;
  - Logs oder Fehlermeldungen;
  - der Datenbank des Ladens (siehe §6.3).
- **Ein Termin fehlt still.** Ist eine Quelle nicht abrufbar, sagt die Oberfläche das, und der Agent meldet „unvollständig“, nie „frei“. Diese bestehende Regel bleibt (`server.py` `belegungen`, Lücken).
- **Geheimnisse werden sichtbar.** Google-Refresh-Token, Client-Secret und iCal-Adressen erscheinen nie in Ausgaben, Logs, Git oder Chat.
- **Jemand entfernt oder ändert den Kalender eines anderen.**
  - Heute darf jeder Angemeldete jede Quelle entfernen (`ui.py:6824`); das wird geschlossen.
  - Nur der Besitzer, oder ein Benutzer mit Rolle `freigeben`, darf entfernen, abschalten oder umordnen.
- Ein zweiter Laden liest oder schreibt im Schema eines anderen Ladens (Ladenfest-Regel).

## 5. Rahmen und Vorgaben

- **Google-Projekt**: Der Betreiber legt es selbst an; er gibt Passwörter immer selbst ein.
  - Er richtet den Zustimmungsbildschirm ein, User Type „Extern“, Status „In Produktion“.
    - Im Status „Testing“ laufen Anmeldungen nach 7 Tagen ab.
  - Er legt einen OAuth-Client vom Typ Webanwendung an.
  - Client-ID und Client-Secret trägt er per Skript selbst in die VM-`.env` ein, nach dem Muster `deploy/postfach-zugang.sh`. Der Agent sieht sie nie.
  - Der Bau liefert dafür eine kurze Schritt-für-Schritt-Anleitung.
- **Scope**: nur lesend (`calendar.readonly` oder die engeren `calendar.events.readonly` + `calendar.calendarlist.readonly`). Der Builder wählt das engste Paar, das Kalenderliste und Termine liefert.
- **Ohne Google-Prüfung**: Die Anmeldung zeigt eine Warnung „App nicht überprüft“, und es gibt insgesamt höchstens 100 Nutzer. Für das Team reicht das **[Entwurf]**.
- **Rücksprung-Adresse**:
  - Sie ist `UI_BASIS_URL` + fester Pfad, heute eine Tailscale-Adresse `https://<host>.ts.net:8444`.
  - `ts.net` steht auf der Public Suffix List (geprüft 08.11.2026). `tail6c7d61.ts.net` ist damit eine eigene Domain, die Google als autorisierte Domain annehmen sollte.
  - Der Builder bestätigt das beim Einrichten mit einem echten Anmeldeversuch.
  - Falls Google sie ablehnt: Bau anhalten und den Betreiber fragen. Ein Ersatz unter `vibemind.space` existiert heute nicht und wäre eine eigene Betriebsaufgabe.
- **Google-Projekt**: Es wird ein neues Projekt mit Web-Client angelegt **[Entwurf]**. Das bestehende Meet-Projekt (Desktop-Client, Status Testing) bleibt unberührt.
- **Läden**:
  - Der Code ist ladenfähig: Jeder Laden hat eigene Quellen, einen eigenen Abgleich und einen eigenen Rücksprung.
  - Ausgerollt wird Stufe 1 zuerst nur im Laden `sales` **[Entwurf]**.
  - „Laden-Besitzer“ ist `POST_BESITZER`. Ist er leer, gilt jeder Privat-Kalender als fremd (Ausfall zur sicheren Seite).
- **Löschrecht**: Die Abgleich-Tabelle braucht DELETE für `sales_app`, wie heute schon `eigene_termine`. Abgesagte Termine und Titel, die nach einem Wechsel Business→Privat oder nach dem Entfernen eines Kalenders gelöscht werden müssen, werden sofort beim nächsten Abgleich bzw. beim Wechsel selbst gelöscht.
- **Ausrollen**: Deploy, DB-Änderungen (`provision.sql`/`laden-anlegen.sql`) und das Einschalten brauchen jeweils das OK des Betreibers.
- **Tests**: nur gegen `sales_test` auf der VM.

## 6. Wie es gebaut wird (vom Entwurf festgelegt)

### 6.1 Datenmodell **[Entwurf]**
`kalender_quellen` bekommt:
- `besitzer` (Benutzername, nicht leer);
- `bereich` (`business` | `privat`), angelehnt an `post_konten.bereich`;
- `art` erweitert um `google`.

Für Google-Quellen:
- Die Kalender-ID von Google wird gespeichert.
- Das Konto (eine Anmeldung, mehrere Kalender) wird nur einmal gespeichert, in einer eigenen Tabelle mit versiegeltem Refresh-Token (§6.3).

Der Anzeigename ist frei wählbar und nicht mehr Träger der Identität.

### 6.2 Abgleich statt Live-Abruf **[Entwurf]**
Heute holt jede Seitenansicht und jeder Agent-Aufruf alle iCal-Adressen neu, ohne Zwischenspeicher. Neu gibt es einen **Abgleich-Dienst**:
- Er läuft alle 5 Minuten, nach dem Muster der Post-Abholung.
- Er holt die Termine aller aktiven Quellen (Google-API, iCal) in eine Tabelle, z. B. `kalender_termine`, mit Quelle, Beginn, Ende, UID und, wo erlaubt, Titel und Ort.
- Oberfläche und Agent lesen nur noch diese Tabelle und wenden die Sichtbarkeit aus §2 beim Lesen an.
- Je Quelle steht „zuletzt abgeglichen“.
  - Liegt das mehr als 15 Minuten zurück oder schlug der letzte Lauf fehl, gilt die Quelle als Lücke: Hinweis in der Oberfläche, „unvollständig“ beim Agenten.
- Ein neu verbundener Kalender wird sofort einmal abgeglichen, damit der Nutzer gleich ein Ergebnis sieht.
- Der CalDAV-Kalender des Ladens (`CALDAV_URL`) bleibt wie heute angebunden, wird aber ebenfalls über den Abgleich geführt **[Entwurf]**. Ob das passt, entscheidet der Builder (§7).

### 6.3 Datensparsamkeit und Geheimnisse **[Entwurf]**
- **Fremde Privattermine** (Besitzer ≠ Laden-Besitzer, `bereich = privat`): Der Abgleich speichert **nur Beginn, Ende und UID**, nie Titel oder Ort.
  - Folge: Ein Teammitglied sieht im Laden des Betreibers auch seine eigenen Privattermine nur als „Privattermin“. Die volle Ansicht hat es in seinem Google-Kalender.
  - Der Laden-Besitzer (`POST_BESITZER` bzw. Betreiber) sieht seine eigenen Privattermine voll.
- **Refresh-Token**: Er wird mit dem Muster `post_tresor` versiegelt (RSA-OAEP; die UI hat nur den öffentlichen Schlüssel, nur der Abgleich-Dienst den privaten). Grenze 300 Zeichen: Der Builder prüft die Länge der Google-Refresh-Token und legt die Grenze notfalls fest.
- **Client-Secret**: liegt nur in der Umgebung der UI (Code-Tausch beim Rücksprung) und des Abgleich-Dienstes.
- **iCal-Adressen**: bleiben wie heute geheim. Klartext in der DB ist ein bekannter, dokumentierter Stand (`docs/06_DSGVO.md`). Sie zu versiegeln ist erwünscht, aber kein Muss für Stufe 1.

### 6.4 Oberfläche
- **`/team/kalender`**:
  - Knopf „Mit Google verbinden“.
  - Nach dem Rücksprung erscheint die Liste der Kalender des Kontos, je Kalender mit Haken „übernehmen“ und der Wahl Business/Privat.
  - Darunter „Meine Kalender“ mit Ändern, Abschalten und Entfernen (nur eigene).
  - Der bisherige Weg per iCal-Adresse bleibt als „Andere Anbieter“ und fragt zusätzlich Business/Privat ab.
  - Der Benutzer `freigeben` sieht zusätzlich die Kalender der anderen: Name, Besitzer, Einordnung, Stand, nie Adresse oder Inhalt.
- **`/kalender`**:
  - Die Box „Team-Ebenen“ wird zu „Ebenen“: alle für mich sichtbaren Kalender, je mit Farbe und Schalter.
  - Der Schalterstand gilt je Person und Gerät (`localStorage` genügt) **[Entwurf]**.
  - Neue Ereignis-Art(en) statt `kollege`: Builder-Wahl. Pflicht ist, dass Titel, Farbe und Klick-Details der Sichtbarkeitstabelle folgen.
  - „Privattermin“ zeigt in den Details nur von–bis und den Namen des Besitzers.
- **`/kalender/termine.json`** filtert serverseitig nach der angemeldeten Person. Kundentermine und eigene Termine des Betreibers folgen derselben Tabelle wie alles andere:
  - Sie liegen im Business-Kalender des Laden-Besitzers (`CALDAV_URL`) und sind damit für Teammitglieder voll sichtbar, auch mit Kundennamen. **[Betreiber 08.11.2026: „Okay“ auf genau diese Frage]**
  - Steht derselbe Termin in einem Business- und einem Privat-Kalender, gilt für fremde Betrachter die strengere Sicht; die Maske darf beim Zusammenführen nie verloren gehen.

## 7. Dem Builder überlassen

- **Tabellen- und Spaltennamen.** Außerdem die Frage, ob die Google-Konten eine eigene Tabelle bekommen oder ob die Spalten an `kalender_quellen` hängen.
- **Abgleich-Dienst**: eigener Container oder Timer im bestehenden Abhol-Dienst. Dazu die genaue Takt- und Altersgrenze, solange „höchstens 15 Minuten alt, sonst Lücke“ gilt.
- **Wie der CalDAV-Kalender des Ladens in den Abgleich kommt**, oder ob er beim Live-Abruf bleibt.
- **Welche Bibliothek Serientermine auflöst.** Und das Zeitfenster des Abgleichs; Vorschlag 30 Tage zurück, 180 voraus.
- **Farben der Ebenen.**
- **Darstellung von–bis im Monat** (`displayEventEnd`, `eventTimeFormat`) und die Schriftgröße.
- **Migration der bestehenden Quellen**: Besitzer `felix`, Bereich `business`. `felix-gmail` bleibt inaktiv.
- **Abfolge der Aufgaben im Plan.** Sinnvoll erscheint:
  1. Besitzer, Bereich und Sichtbarkeit ohne Google (sofort spürbarer Nutzen: der Betreiber sieht seine Termine voll);
  2. dann Abgleich-Dienst;
  3. dann Google-Anmeldung.

## 8. Offene Punkte für später
- Stufe 2: Termine in Google eintragen (Zielkalender je Person).
- Microsoft-Anmeldung.
- `freie_zeiten`-Werkzeug für den Agenten (alter Plan aus `2026-09-16-getrennte-laeden-design.md`).
