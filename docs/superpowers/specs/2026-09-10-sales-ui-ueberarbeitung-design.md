# sales-ui — Überarbeitung in vier Stufen

**Datum:** 2026-09-10
**Auslöser:** Vollständiger Browser-Durchgang durch alle zwölf Seiten der laufenden
Oberfläche (`https://vibemind-offload-1.tail6c7d61.ts.net/`) gemeinsam mit dem Betreiber.
Jede Seite wurde angesehen, die Befunde vorgelegt und pro Seite entschieden, was
besser werden soll.

**Status:** Design, vom Betreiber freigegeben. Umsetzung folgt stufenweise.

---

## 1. Ausgangslage

`sales-ui` ist der siebte Container von sales-claw: eine serverseitig gerenderte
Freigabe- und Datenansicht vor der Kundendatenbank. Der gesamte Code steht in
**einer Datei mit 4.965 Zeilen** (`sales-mcp/ui.py`), gebaut auf Starlette, HTML per
String-Aufbau, Stil als ein großes Inline-`<style>`.

Die Oberfläche ist **absichtlich skriptfrei**: jede Antwort trägt
`Content-Security-Policy: default-src 'none'`, erlaubt sind nur Inline-CSS und
Formulare an `'self'`. Der Code begründet das ausdrücklich — *„eine Freigabe-
oberfläche ohne Skripte ist eine Zusage, keine Bequemlichkeit"*. Keine externen
Fonts, keine CDNs.

Diese Zusage bleibt tragend. Sie wird an genau einer Stelle und kontrolliert
gelockert (siehe §2.1).

### Gemessener Zustand beim Durchgang (2026-09-10, ~00:40)

| Kennzahl | Wert |
|---|---|
| Kontakte | 461 laut Navigation, **469** laut WhatsApp-Seite |
| Consent | **459 von 461 auf `unknown`**, 2 auf `existing` |
| Pipeline | 348 neu · 92 recherchiert · 0 qualifiziert · 0 kontaktiert · 18 geantwortet · 3 termin |
| Posteingang | 12 unbeantwortet, älteste seit 37 h |
| Kundennachrichten gesamt | 1.155 |
| Medien | 16 Dateien, davon 15 nie gesendet |
| WhatsApp-Entwürfe im Verlauf | 5 von 5 abgelehnt |

Der Consent-Befund erklärt den Pipeline-Stillstand: ohne `opt_in` oder
`existing_customer` entsteht kein Erstansprache-Entwurf, also bleiben 348 Kontakte
dauerhaft auf „neu".

---

## 2. Randbedingungen und Grundsatzentscheidungen

### 2.1 Skriptfrei bleibt — mit einer eng begrenzten Ausnahme

**Entscheidung:** Ein einziges Skript von etwa 20 Zeilen, mit `nonce` ausgeliefert,
CSP von `default-src 'none'` auf `script-src 'self' 'nonce-…'` verengt.

Was es darf: einen schlanken Endpunkt (`/api/stand`) abfragen, der ausschließlich
Zählstände liefert, und bei Änderung ein Banner einblenden — *„3 neue Entwürfe —
laden"*.

Was es nicht darf: die Seite von selbst neu laden, Formularinhalte anfassen,
Fremddaten rendern. Der Grund für die heutige Abschaltung des Auto-Refresh
(Tippverlust beim Bearbeiten eines Entwurfs) bleibt damit adressiert: **nichts
passiert ohne Klick des Betreibers.**

Alles Übrige aus der Wunschliste kommt ohne Skripte aus: Suche, Filter, Sortierung,
Paginierung, Massenaktionen (Checkboxen plus ein Absenden), Woche/Monat-Umschalter,
farbige Termine, der komplette Optik-Umbau.

Zusätzlich nötig: `img-src 'self'` für die Medien-Vorschau (kein JavaScript, nur
Bilder aus eigener Quelle).

### 2.2 `ui.py` wird beim Umbau aufgeteilt

Nicht als eigener Refactoring-Schritt, sondern seitenweise während der Arbeit:
wer eine Seite umbaut, löst sie in ein eigenes Modul heraus.

```
sales-mcp/ui/
  __init__.py      Routen, App, Middleware (was heute unten in ui.py steht)
  geruest.py       HTML-Rahmen, Navigation, Fehlerseiten
  stil.py          das gesamte CSS
  heute.py  kontakte.py  kalender.py  freigaben.py  einordnung.py
  pipeline.py  ergebnisse.py  medien.py  kanaele.py  mitarbeiter.py
```

Die Schutzkanten bleiben, wo sie sind: das UI ruft weiterhin ausschließlich die
Chat-Werkzeuge aus `server.py` und baut kein eigenes SQL. Diese Regel gilt für
jedes neue Modul unverändert.

### 2.3 Reihenfolge ist bindend

Die Stufen bauen aufeinander auf. Eine Abhängigkeit ist kritisch und darf nicht
umgangen werden:

> **Die Posteingang-Seite darf erst verschwinden, wenn die automatische
> Entwurfserzeugung aus Stufe 3 nachweislich läuft.** Andernfalls verliert der
> Betreiber die einzige Übersicht über unbeantwortete Nachrichten.

---

## 3. Stufe 1 — Wahrheit und Fehler

Kleinste Stufe, größte Sofortwirkung. Nichts davon ändert Struktur oder Bedienung.

### 3.1 Umlaute

Die Texte stehen im Python-Quelltext in ASCII-Umschreibung: „aelteste", „naechsten",
„oeffnen", „Entwuerfe", „Oberflaeche", „laedt", „bestaetigt", „Aendern", „Groesse",
„Loeschen". Direkt daneben stehen echte Umlaute aus Kundendaten („Videogespräch",
„Rü", „Ena Ottenschläger"), was den Bruch sichtbar macht.

Zu tun: alle Anzeigetexte in `ui.py` (und den daraus entstehenden Modulen) auf echte
Umlaute umstellen. Betroffen sind Anzeigetexte, **nicht** Bezeichner, DB-Spalten,
Dateinamen oder Werkzeugnamen.

Prüfschritt: sicherstellen, dass die Antwort `charset=utf-8` trägt und die Datei
selbst UTF-8 ist.

### 3.2 Doppeltes HTML-Escaping

Beleg: auf `/freigaben` erscheint `Video Call mit Sophie &amp; Stephane` als
sichtbarer Text; auf `/kalender` sogar `Video Call mit Sophie &amp;amp\; Stephane`.

Das heißt: ein bereits escapeter Wert läuft ein zweites (auf dem Kalenderpfad ein
drittes) Mal durch `html.escape`. Zu tun: die Stelle finden, an der escapeter Text
gespeichert oder weitergereicht wird — vermutlich beim Übernehmen der Termintitel
aus dem Kalender-Import — und genau einmal escapen, nämlich beim Rendern.

Bestandsdaten mit `&amp;` in der Datenbank müssen einmalig bereinigt werden.

### 3.3 Kalender: Zeitzone und Duplikate

Zwei getrennte Fehler, sichtbar am selben Termin:

* **Versatz:** „Video Call mit Sophie & Stephane" steht in der Kalender-Tabelle um
  **21:00**, in der Vergangen-Tabelle um **19:00**. Zwei Stunden — der Abstand
  zwischen UTC und deutscher Sommerzeit. Eine der beiden Darstellungen rechnet nicht
  um.
* **Duplikate:** derselbe Termin erscheint am 5.9. viermal im Monatsgitter und
  zweimal in der Tabelle, einmal mit Ort „Video Call", einmal mit der Meet-URL. Der
  eigene Termin-Store und der importierte Kalender enthalten denselben Termin, ohne
  dass sie zusammengeführt werden.

Zu tun: alle Zeitpunkte in einer Zone speichern (UTC) und genau einmal beim Rendern
in lokale Zeit umrechnen. Für die Duplikate ein Zusammenführungs-Merkmal einführen
(Titel + Startzeit + Kontakt), damit ein Termin einmal erscheint — mit der
vollständigeren der beiden Ortsangaben.

### 3.4 461 gegen 469

Die Navigation zählt 461 Kontakte, die WhatsApp-Seite 469. Zu klären, welche Zählung
was einschließt (Archivierte? Sammelkontakte? Gesperrte?), dann **eine** Zählweise
festlegen und beide Stellen daraus speisen.

### 3.5 Kleinere Fehler

* `/pipeline` gibt **zweimal** `<h1>Pipeline</h1>` aus.
* `/favicon.ico` liefert 404 bei jedem Seitenaufruf.
* Karten- und Verlaufstexte brechen hart bei etwa 90 Zeichen mitten im Wort ab
  („Thema Vibe ·", „Rü ·", „Kennenlernen Förderini"). Zu tun: an Wortgrenzen kürzen,
  vollständigen Text als `title` mitgeben.
* Auf „Heute" widersprechen sich die Zahlen: die Kopfzeile sagt „1 Entscheidung
  wartet", darunter stehen zwei Termine, eine Einordnung und zwölf unbeantwortete
  Nachrichten; die Chips zeigen „Termine 2", direkt darunter steht „Keine offenen
  Entwürfe". Eine ehrliche Zählung, die alle Posten einschließt.

---

## 4. Stufe 2 — Struktur

### 4.1 „Heute" zeigt nur den heutigen Tag

**Betreiber-Entscheidung:** Termine ohne festes Datum sind **keine Aufgabe des
Betreibers**, sondern werden vom Bot im Gespräch geklärt. Der Abschnitt „Termine ohne
festes Datum" verschwindet aus „Heute" — und ebenso aus „Freigaben" und „Kalender".

Was „Heute" stattdessen zeigt:

1. Termine **des heutigen Tages**, mit Uhrzeit und Kontakt
2. Entwürfe, die auf Freigabe warten — **inline freigebbar oder ablehnbar**, ohne
   die Seite zu verlassen
3. Einordnungen, die anstehen
4. Fällige Wiedervorlagen (die Funktion bleibt, ihre eigene Seite nicht — §4.2)

### 4.2 Wiedervorlagen-Seite entfällt

Die Seite besteht heute aus einer einzigen Zeile („Keine offenen. Eine anlegen: auf
der Kontaktseite") und ist damit eine Sackgasse. Die **Funktion** bleibt auf der
Kontaktseite; fällige Wiedervorlagen erscheinen in „Heute". Der Navigationspunkt
entfällt, `/wiedervorlagen` leitet auf `/` um.

### 4.3 Posteingang-Seite entfällt — nach Stufe 3

Siehe die Abhängigkeit in §2.3. Die Seite hat heute zwei sachliche Fehler, die
ohnehin verschwinden müssen:

* Fünf Einträge heißen „Unbekannte Eingaenge" und verlinken auf den Sammelkontakt,
  obwohl direkt daneben „gehoert zu Christian Willuweit / Diana / Raik / Ivan" steht.
  Wo die Zuordnung bekannt ist, gehört der echte Kontakt hin.
* Bilder erscheinen als `[Bild — kein Text zum Mitlesen]` ohne jede Vorschau.

Solange die Seite noch existiert, werden beide korrigiert.

### 4.4 Kontaktliste

Heute: 461 Zeilen am Stück, rund 1.800 Schaltflächen im HTML, keine Suche, kein
Filter, keine Sortierung — nur „auch archivierte zeigen".

Zu bauen (alles serverseitig, ohne Skript):

* **Suche** über Name, Firma, E-Mail, Telefon und Notizen — Volltext mit
  Teilwort-Treffern
* **Filter** nach Stufe, Consent, Autonomie, Kanal
* **Sortierung** über Spaltenköpfe (Name, Stufe, Score, Zuletzt)
* **Paginierung**, 50 Zeilen je Seite
* **Massenaktionen**: Zeilen ankreuzen, dann gemeinsam archivieren, Autonomie setzen
  oder Stufe ändern — über dieselben Chat-Werkzeuge wie die Einzelaktion, je Kontakt
  einzeln aufgerufen, damit jede Schutzkante greift

Der Consent-Befund (459 von 461 auf `unknown`) wird als Filter sichtbar, damit
erkennbar ist, wie viele Kontakte für eine Erstansprache gesperrt sind.

### 4.5 Kontakt-Detailseite: von 13 Abschnitten auf 4

Heute stehen dreizehn Abschnitte untereinander, vier davon leer („Verträge (0)",
„Recherche: noch keine Firmendaten", „Kontaktprofil: noch keins", „Wiedervorlagen:
keine"), dazwischen lange Erklärabsätze. Name, Telefon und E-Mail erscheinen zweimal
— einmal als Anzeigetabelle, einmal als Formular.

Neue Gliederung:

1. **Kopf** — Name, Status, Consent, Kanäle, Autonomie, Pipeline-Stufe; kompakt und
   direkt bearbeitbar. Löst die Doppelung auf.
2. **Verlauf** — Ereignisse chronologisch, **neueste zuerst** (heute: älteste zuerst).
3. **Wissen** — Bedarfsstand, Firmenrecherche, Kontaktprofil, Verträge in einem
   Block; leere Teile als dünne Zeile statt als eigene Überschrift mit Absatz.
4. **Steuerung** — eingeklappt: WhatsApp-Freigabe, „Privat", Wiedervorlage anlegen,
   Archiv.

Die Erklärtexte („Consent ist die dokumentierte Werbe-Einwilligung nach UWG …")
wandern hinter Info-Symbole (`<details>`, kein Skript nötig). Ihr Inhalt bleibt
erhalten — er ist fachlich wichtig, nur nicht dauerhaft sichtbar.

### 4.6 Kalender: Woche als Standard

* **Umschalter Woche / Monat**, Woche ist die Voreinstellung
* **Farbcodierung wie in Outlook** — je Kategorie eine Farbe (Kundentermin,
  interner Termin, unbestätigt); Farben aus dem bestehenden Variablensatz, in hellem
  und dunklem Thema auf Kontrast geprüft
* Statt fünf Listen (Monatsgitter, „Kommende (0)", „Ohne festes Datum (2)",
  „Offene Wiedervorlagen (0)", „Kalender (8)", „Vergangen (4)") nur noch: Ansicht +
  eine Liste „Kommende" + einklappbar „Vergangene". „Ohne festes Datum" entfällt
  (§4.1).
* Titel im Gitter an Wortgrenzen kürzen, vollständig im `title`

### 4.7 Einordnung: Profile füllen

In „Bereits entschieden (24)" steht bei fast jeder Zeile `noch keins` in der
Profil-Spalte: eingeordnete Kontakte bleiben ohne Profil liegen.

Zu bauen: je Zeile eine Schaltfläche „Profil anfordern" (dasselbe Werkzeug wie auf
der Kontaktseite), plus eine Sammelaktion für alle Zeilen ohne Profil. Das Profil
entsteht beim nächsten Agentenlauf; an den Kunden geht dabei nichts.

*Nicht Teil dieser Stufe, aber festgehalten:* die Zuordnung läuft über ein natives
Auswahlfeld mit **461 Einträgen ohne Suche**. Der Betreiber hat das bewusst nicht
priorisiert. Die Empfehlung bleibt bestehen (§8).

---

## 5. Stufe 3 — Neue Mechanik

### 5.1 Automatische Entwürfe nach Schreibpause

**Die zentrale Änderung.** Betreiber-Vorgabe im Wortlaut: *„Bot erstellt automatisch
Entwürfe nachdem der User 20 s nichts mehr schreibt, ich gebe frei."*

Heute läuft `antworten-pruefen` alle zwei Stunden (gemessen auf der WhatsApp-Seite).
Das erklärt die zwölf unbeantworteten Nachrichten mit bis zu 37 Stunden Wartezeit.

Neu:

* Eingehende Kundennachricht startet einen Zeitgeber von **20 Sekunden**.
* Jede weitere Nachricht desselben Kontakts setzt ihn zurück — damit entsteht ein
  Entwurf auf den **ganzen Gedanken**, nicht auf jeden Satzfetzen.
* Läuft er ab, erzeugt der Bot einen Entwurf. Der geht in `pending` und erscheint
  unter „Freigaben" und auf „Heute".
* **Nichts wird gesendet.** Die bestehenden Kanten bleiben unangetastet:
  WhatsApp-Freigabe je Kontakt, Consent nach UWG, Freigabe durch den Betreiber.
* Der Zwei-Stunden-Lauf bleibt als Netz für alles, was der Zeitgeber verpasst hat
  (Neustart, Ausfall).

Ort: `sales-mcp/inbox.py` (Eingang) und `sales-mcp/auto.py` (Entwurfserzeugung) —
nicht in der Oberfläche.

Offen zu klären bei der Umsetzung: Was passiert bei Kontakten auf Autonomie
`manuell` oder `ignorieren`, und was bei Nachrichten ohne Text (Bilder)?

### 5.2 Live-Hinweis auf neue Entwürfe

Der eine erlaubte Skript-Einsatz aus §2.1. Neuer Endpunkt `/api/stand` liefert
ausschließlich Zahlen (offene Entwürfe je Kanal, Einordnungen, Termine heute). Das
Banner erscheint auf „Heute" und „Freigaben".

### 5.3 „Ergebnisse" mit echtem Inhalt

Heute: zwei Überschriften und zwei Striche.

Zu bauen:

* **Kennzahlen** — Antwortquote, Termine je Woche, Durchlaufzeit je Pipeline-Stufe,
  Verhältnis freigegebener zu abgelehnten Entwürfen je Kanal
* **Gewonnen / Verloren mit Grund** — beim Stufenwechsel auf `gewonnen`/`verloren`
  wird ein Grund erfasst (das Begründungsfeld existiert bereits bei
  `kontakt_stufe`) und hier ausgewertet
* **Verlauf über Zeit** — Wochen- und Monatsvergleich statt Momentaufnahme

Die Ablehnquote ist dabei die interessanteste Zahl: fünf von fünf WhatsApp-Entwürfen
im Verlauf sind abgelehnt. Sichtbar gemacht wird das zum Steuerungssignal.

### 5.4 Medien

* **Upload aus dem Chat** — ausdrücklicher Betreiber-Wunsch. Der Web-Upload existiert
  bereits (`/medien`, erlaubt `.ics .jpeg .jpg .mp3 .mp4 .ogg .pdf .png`, max. 15 MB);
  was fehlt, ist der Weg über den Chat. Neu: ein Werkzeug, das eine im Chat
  übergebene Datei in die Medienliste aufnimmt, sodass sie sofort an Entwürfe
  gehängt werden kann. Dieselben Prüfungen wie beim Web-Upload (Typ, Größe,
  Namenskollision).
* **Vorschau statt Dateiname** — Thumbnails für Bild, PDF-Erstseite und Video-
  Standbild. Braucht `img-src 'self'` in der CSP (§2.1), kein Skript.
* **Zweck hinterlegen** — je Datei ein Feld „wofür gedacht" (Erstgespräch,
  Terminbestätigung, Bedarfsanalyse …), damit der Bot die passende Datei wählt statt
  zu raten. Erklärt zugleich, warum 15 von 16 Dateien nie gesendet wurden.

### 5.5 Mitarbeiter-Bereich und Wissensquelle

Ausgangspunkt: `C:\Users\User\Downloads\transfer-01a07b81` — **74 Dateien, 3,8 GB**
Einarbeitungsmaterial (Fin2Gether/VFS: Fiko-Videos, Mitarbeiterunterlagen,
Antragsformulare, Produkt-PDFs; 44 PDF, 15 DOCX, 8 MP4, 4 PPT/PPTX, 1 XLSX, 1 ZIP).

Betreiber-Entscheidung: **beides** — eigener Bereich in der Oberfläche *und*
Wissensquelle für den Bot.

* **Bereich** `/mitarbeiter`: Ordnerstruktur zum Durchsehen und Herunterladen,
  getrennt von den Bot-Medien. Diese Dateien gehen **nicht** an Kunden.
* **Wissensquelle**: Text aus PDF und DOCX extrahieren und indexieren, damit der Bot
  Produkt- und Antragsfragen beantworten kann.

Zwei Punkte sind vor der Umsetzung zu klären:

1. **Größe.** 3,8 GB passen nicht in den 15-MB-Rahmen der Medien-Tabelle. Der
   Mitarbeiter-Bereich braucht eine eigene Ablage (Volume oder Dateipfad), keine
   Aufnahme in `media/`.
2. **Datenschutz.** Es handelt sich um Unterlagen eines Finanzvertriebs; einzelne
   Dateien („log in.docx", Antragsformulare) können Zugangs- oder Personendaten
   enthalten. Vor der Indexierung ist zu prüfen, was hineindarf — im Zweifel gilt der
   bestehende Grundsatz, sensible Daten nicht in eine durchsuchbare Wissensbasis zu
   legen.

### 5.6 E-Mail und LinkedIn überwachen wie WhatsApp

`/whatsapp` ist die stärkste Seite der Anwendung: eine belegte Kette Handy → OpenWA →
Webhook → Posteingang → Datenbank, jede Station mit Beleg und Zeitstempel. Für die
beiden anderen Kanäle gibt es nichts Vergleichbares, obwohl über beide Nachrichten
ein- und ausgehen.

Zu bauen: dieselbe Darstellung für E-Mail (SMTP/IMAP) und LinkedIn, zusammengefasst
unter `/kanaele` mit einem Abschnitt je Kanal. Dazu eine **Störungshistorie** — wann
war eine Verbindung weg und wie lange — statt nur „jetzt gerade verbunden".

### 5.7 OpenWA-Schlüssel automatisch bereitstellen

Betreiber-Frage: kann der API-Schlüssel automatisch initialisiert werden, etwa per
Setup-Skript in die `.env`?

**Antwort: ja, der halbe Weg existiert bereits.** In `docker-compose.openwa.yml`
(Zeilen 91–97) ist dokumentiert: `API_MASTER_KEY` bleibt absichtlich ungesetzt, weil
OpenWA beim allerersten Boot selbst einen zufälligen Admin-Schlüssel erzeugt, ihn
nach `/app/data/.api-key` im Volume schreibt und einmalig im Startup-Log ausgibt.

Zu bauen: ein Schritt in `deploy/bootstrap.sh`, der den Schlüssel aus dem Volume
liest (`docker exec openwa cat /app/data/.api-key`) und als `OPENWA_API_KEY=` in die
`.env` schreibt, falls dort noch keiner steht. Damit tippt ihn niemand mehr ab.

**Mit Prüfschritt, nicht als Zusage:** ob sich damit auch die *eingebettete*
OpenWA-Oberfläche im iframe automatisch anmelden lässt, hängt davon ab, wie deren
Dashboard sein Token ablegt. Das ist am laufenden Dashboard zu messen, bevor es
zugesagt wird.

---

## 6. Stufe 4 — Optik

Betreiber-Entscheidung: **deutlich aufwerten**, nicht nur aufräumen. Die Anwendung
soll auch für Dritte vorzeigbar sein.

Randbedingung: keine externen Fonts, keine CDNs (CSP und Offline-Tauglichkeit).
Gearbeitet wird also mit Systemschriften und dem bestehenden Variablensatz.

* **Typografie** — eine klare Größenskala, ausreichender Zeilenabstand,
  Systemschrift-Stapel mit vernünftigem Rückfall
* **Farben** — der bestehende Satz aus hellem und dunklem Thema bleibt die
  Grundlage (er ist bereits auf Kontrast geprüft) und wird erweitert um Statusfarben
  für Pipeline-Stufen und Terminkategorien
* **Status-Marker** — einheitliche Gestaltung für Stufe, Consent, Autonomie,
  Verbindungszustand; heute ist jede Stelle anders gestaltet
* **Karten und Tabellen** — gemeinsame Abstände, Rahmen und Ecken; die bestehende
  Umwandlung von Tabellen in Karten unterhalb 640 px bleibt erhalten
* **Leere Zustände** — statt „—" und „Nichts offen" eine ruhige, erklärende
  Darstellung
* **Dark Mode** — bleibt und wird mitgepflegt

Das CSS zieht dabei in `sales-mcp/ui/stil.py` um (§2.2).

---

## 7. Nicht im Umfang

* **Löschen von Kontakten oder Nachrichten** — die Rolle `sales_app` hat kein
  DELETE-Recht, und das ist eine bewusste Entscheidung (siehe Kopfkommentar in
  `ui.py`).
* **Versand aus der Oberfläche** — bleibt beim Chat und beim Dispatcher.
* **Ziehen von Karten in der Pipeline** — braucht Skripte über das in §2.1 erlaubte
  Maß hinaus. Vom Betreiber nicht priorisiert.

---

## 8. Aufgeschoben, aber empfohlen

Zwei Punkte, die der Betreiber bewusst nicht gewählt hat und die hier festgehalten
werden, damit sie nicht verloren gehen:

1. **Suchfeld statt 461er-Auswahlfeld in der Einordnung** (§4.7). Die Zuordnung ist
   der Kern dieser Seite und läuft heute über ein natives Auswahlfeld mit 461
   alphabetischen Einträgen ohne Suche.
2. **Ablehngrund erfassen.** Fünf von fünf WhatsApp-Entwürfen wurden abgelehnt, ohne
   dass irgendwo festgehalten wird, warum. Ohne diese Rückmeldung schlägt der Bot
   weiter dasselbe vor.

**Semantische Suche** (Betreiber-Frage): in der Pipeline bringt sie nichts — deren
Spalten sind Zustände, keine Bedeutungen. Wertvoll wäre sie über den
**Nachrichteninhalten**: „wer hat nach Preisen gefragt", „wer wollte einen Termin und
ist versandet". Dafür wären Einbettungen über die 1.155 Kundennachrichten nötig;
Qdrant und der Embedder laufen im Umfeld bereits. Sinnvoll als eigener Schritt nach
Stufe 3, wenn die Volltextsuche aus §4.4 steht und sich zeigt, wo sie nicht reicht.

---

## 9. Prüfung

Für jede Stufe gilt: **am laufenden System gemessen, nicht am Code behauptet.**

* Stufe 1: Seiten im Browser aufrufen, Umlaute und Escaping prüfen; derselbe Termin
  muss überall dieselbe Uhrzeit tragen und einmal erscheinen; beide Kontaktzählungen
  müssen übereinstimmen.
* Stufe 2: Suche, Filter, Sortierung, Paginierung und Massenaktionen gegen die echten
  461 Kontakte; Kontaktseite auf vollständige Bearbeitbarkeit prüfen.
* Stufe 3: eine echte Nachricht schicken und messen, ob nach 20 Sekunden ein Entwurf
  in `pending` steht — und ob eine schnelle Folgenachricht den Zeitgeber
  zurücksetzt. Erst wenn das steht, darf die Posteingang-Seite verschwinden.
* Stufe 4: beide Themen (hell/dunkel) und die Ansicht auf dem iPhone, über das der
  Betreiber die Oberfläche per Tailscale erreicht.
