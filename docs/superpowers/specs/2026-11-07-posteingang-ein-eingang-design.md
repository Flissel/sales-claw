# Ein Posteingang für alles, was reinkommt – Design

Stand 07.11.2026 · sales-claw · Entscheidungen von Felix (Betreiber) im Gespräch vom 07.11.

## Absicht

Der Posteingang ist der eine Ort, an dem alles ankommt, was von außen
reinkommt. Felix: „Der Posteingang von WhatsApp und der Maileingang von den
Mails ist beides incoming. Deswegen sollte es zusammen sein.“ Mails sind
keine Auswertung, sondern Eingang.

Heute stehen „Posteingang“ (`/posteingang`, nur Chats) und „Mails“ (`/post`)
getrennt im Menü unter **Analyse**. Der Posteingang zeigt unbeantwortete
WhatsApp- und Telegram-Nachrichten. Für Mails gibt es dort nur einen Verweis.
Die Mails wurden am 03.11. aus Datenschutzgründen herausgenommen (Ruling R10/R14):
Der alte Block zeigte private Post jeder Anmeldung.

Zweites Anliegen: Datenschutz (DSGVO) und keine Überwachung anderer.
**Ein Container (Laden) entspricht einem Nutzer. Seine Mails bleiben bei ihm.**
Niemand sonst sieht sie, auch die Leitung nicht, weder private noch
Business-Mails. **Nur die Kalender sind geteilt.**

## Ziele

**Z1 – Menü.** „Posteingang“ verlässt die Gruppe Analyse und wird der
erste Eintrag im Menü. „Mails“ (`/post`) steht direkt darunter. *(Die genaue
Form ist meine Entscheidung: eigene Gruppe ganz oben oder an der Spitze von
„Aufgaben“.)*

**Z2 – Eine Liste.** `/posteingang` zeigt in einer gemeinsamen Liste:
- **Chats** wie heute: unbeantwortete Kundennachrichten (WhatsApp, Telegram),
  je Kontakt die jüngste, Fenster 48 Std. Die Logik bleibt unverändert.
- **Mails** des angemeldeten Besitzers, die Aufmerksamkeit brauchen
  (`ziel = posteingang`, also auch „Zum Nachsehen“) und noch nicht erledigt sind.

Jeder Eintrag trägt ein Kanal-Abzeichen. Bei Mails ist das „E-Mail“ plus die
Postfach-Kennung, z. B. gmx-felix. Die Liste ist nach Wartezeit sortiert, der
älteste Eintrag oben (wie heute). Sensible Mails zeigen nur den Kopf, wie
überall (bestehende Regel). Die Suche oben durchsucht Chats und die eigenen Mails.

**Z3 – Wann eine Mail den Posteingang verlässt** (Felix). Es gibt genau
drei Wege:
1. **Beantwortet:** Eine Antwort ist rausgegangen. Gilt für beide Wege:
   - über sales-claw (Entwurf aus `mail_beantworten`, freigegeben und versendet)
   - direkt aus Gmail oder GMX. Das erkennt das System an der
     IMAP-Markierung `\Answered` der Originalmail.
2. **Bezahlt:** bei Rechnungen. Vorerst setzt Felix das per Knopf
   „Bezahlt“. Später setzt ein Bezahlungsagent (eigenes Projekt) dieselbe
   Markierung. Sie wird deshalb jetzt als eigenes Feld angelegt, nicht als Sonderfall
   von „erledigt“.
3. **Erledigt:** Knopf für alles andere, z. B. Sicherheitswarnungen, Fristen,
   Vertragsänderungen.

Ohne eines dieser drei Signale bleibt eine Mail im Posteingang. Je Mail wird
gespeichert, wie und wann sie erledigt wurde. *(Meine Entscheidung: Das
Erledigen lässt sich in der Mail-Ansicht unter `/post` rückgängig machen.)*

**Z4 – Mails am Kontakt.** Hat der Absender schon einen Kontakt (Adresse
gleich, ohne Rücksicht auf Groß- und Kleinschreibung), steht die Mail in
dessen Verlauf neben den WhatsApp-Nachrichten. **Sehen darf sie dort nur der
Besitzer des Postfachs.** Unbekannte Absender stehen nur im Posteingang, mit
einem Knopf „Kontakt anlegen“. Es werden keine Kontakte automatisch angelegt,
sonst füllt sich die Liste mit Versanddiensten. *(Meine Entscheidung,
Felix hat zugestimmt.)*

**Z5 – Sichtbarkeit: nur der Besitzer** (Felix, DSGVO).
- `post_struktur.sichtbar_sql`: Die Freigaben für die Leitung (alle Business-Mails)
  und für Abteilungen (Business-Fächer über `post_abteilung_faecher`) fallen
  weg. Jede Mail sieht nur ihr `besitzer`.
- Der Agent (`ist_agent`) sieht nur Business-Mails des Container-Besitzers
  (`POST_BESITZER`), die nicht sensibel sind. Mails anderer Besitzer sieht er nie.
- Das gilt überall, wo Mailinhalt auftaucht: Posteingang, `/post`,
  Kontakt-Verlauf, Suche, Chat-Werkzeuge.
- Kalender bleiben geteilt (unverändert).

## Keine Ziele

- Spracheingabe, Sprachausgabe/ElevenLabs. Das sind eigene Themen.
- Der Bezahlungsagent selbst. Hier entsteht nur die Markierung „bezahlt“.
- Verschieben im Postfach (`POST_ORDNEN`). Das bleibt unabhängig.
- Outlook-Anbindung.
- Änderungen an der Chat-Logik des Posteingangs.

## Das darf nicht passieren

- Eine andere Anmeldung als der Besitzer sieht Inhalt oder Kopf einer Mail.
  Das gilt auch für die Leitung, für einen Kollegen über den Kontakt-Verlauf und
  für den Agenten bei Mails anderer.
- Der Posteingang läuft mit Altbestand voll: Über 10.000 alte Mails werden
  gerade eingeordnet, viele davon mit Aufmerksamkeit.
- Eine Mail verschwindet ohne eines der drei Signale aus Z3.
- Newsletter-Absender werden zu Kontakten.

## Vorgaben

- **Ladenfest:** Der zweite Laden (Ivan, Sophie) bucht nie auf Schema oder IDs
  des Betreibers.
- **Logs:** Keine Geheimnisse und kein Mailtext in Logs, nur IDs und Typen.
- **Tests:** nur in `sales_test` auf der VM. Schema-Änderungen idempotent in
  `db/post-sammelstelle.sql`.
- **Freigaben:** Ausrollen nur mit Felix' OK. Kein SQL gegen `sales` ohne OK.
- **Datenzugriff:** Mailfunktionen laufen immer über
  `post_struktur.sichtbar_sql` bzw. `mail_lesen`.

## Bekannte Stolperstellen

- `server.mail_beantworten` legt heute bei unbekanntem Absender **automatisch
  einen Kontakt an** und bucht die eingehende Mail **mit Text** als
  `activities`-Zeile `kundenantwort` (kanal email). Diese Zeilen sieht heute
  jede Anmeldung im Verlauf. Das widerspricht Z4 und Z5 und muss angepasst
  werden.
- **Altbestand:** In den Posteingang kommen nur Mails ab dem Stichtag
  `POST_AUFRAEUMEN_AB` (`post_ziel.ALTBESTAND_AB`). Ältere Mails mit
  Aufmerksamkeit bleiben im Reiter „Aufmerksamkeit“ unter `/post`. *(Meine
  Entscheidung.)* Ist der Stichtag nicht gesetzt, nimmt der Posteingang keine Mails auf und
  sagt das sichtbar.
- **`\Answered` ist nur so aktuell wie die letzte Abholung.**
  Für Mails, die noch im Posteingang stehen, muss die Markierung je Runde
  neu gelesen werden. Heute holt `sales-post` nur neue Mails ab.

## Festlegungen nach der Prüfung (meine Entscheidungen, Felix prüft beim Lesen)

1. **Alte Verlaufszeilen mit Mailtext:** Bestehende `activities`-Zeilen
   `kundenantwort` mit `kanal = email` werden nicht gelöscht, sondern beim Lesen
   gefiltert. Sie gelten als Mails des Container-Besitzers (`POST_BESITZER`) und
   sind nur für ihn sichtbar. Das ist umkehrbar und braucht kein SQL gegen `sales`.
   Ob sie später geschwärzt oder gelöscht werden, entscheidet Felix gesondert.
2. **Antwort erkennen:** zwei Signale, für alle Anbieter.
   - die Markierung `\Answered` der Originalmail
   - eine Mail im Gesendet-Ordner (`\Sent`), deren `In-Reply-To` oder `References`
     die `message_id` der Originalmail nennt. Das ist für Gmail nötig, das
     `\Answered` bei Antworten aus der Weboberfläche nicht verlässlich setzt.
   Ein Treffer reicht.
3. **Verschobene oder verschwundene Mails:** Nachgelesen wird im aktuellen
   Ordner (`ordner`). Ist die Mail dort nicht mehr auffindbar, bleibt sie im
   Posteingang, mit dem Hinweis „im Postfach nicht mehr gefunden“. Erledigen
   geht dann nur per Knopf (Z3: nichts verschwindet ohne Signal).
4. **Besitzer:** Jede Mail hat genau einen `besitzer` (heute Pflicht beim
   Abholen). Gemeinschaftspostfächer gibt es nicht. Das Feld `leitung`
   bleibt am Betrachter für andere Zwecke. `post_abteilung_faecher` wird für
   Mails nicht mehr abgefragt, die Tabelle bleibt (nichts löschen).
5. **Agent:** sieht nur Mails mit `besitzer = POST_BESITZER`, Bereich business,
   nicht sensibel. Ist `POST_BESITZER` leer, sieht er keine Mails (fail closed).
6. **Erster Lauf:** Bevor Mails im Posteingang erscheinen, läuft für alle
   Kandidaten ab dem Stichtag einmal der Antwort-Abgleich. Die Liste ist
   seitenweise wie `/post`.
7. **Knopf „Bezahlt“:** nur bei Mails im Fach „Rechnungen“ (gibt es unter
   privat und business). Alle anderen bekommen „Erledigt“. Rechnungen
   lassen sich trotzdem auch per „Erledigt“ abhaken, ohne als bezahlt zu gelten.

## Für den Bauenden offen

- Wie Erledigt, Bezahlt und Beantwortet gespeichert werden (Spalten an
  `post_mails` oder eigene Tabelle) und wie Kontakt und Mail verknüpft werden.
- Wie der Verlauf mailbezogene Einträge nach Besitzer filtert.
- Die Gestaltung der Knöpfe und Abzeichen in der bestehenden UI-Sprache.
- Wie oft und in welchen Mengen die `\Answered`-Markierungen nachgelesen werden.
