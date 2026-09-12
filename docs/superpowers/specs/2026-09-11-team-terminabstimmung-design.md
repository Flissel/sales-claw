# Team-Terminabstimmung — Sicht und Einladungen

**Datum:** 2026-09-11
**Status:** Design, vom Betreiber freigegeben. Umsetzung folgt.
**Auslöser:** Der Betreiber arbeitet eng mit Teamkollegen zusammen und will Kundentermine
planen können, ohne mit ihnen zu kollidieren: *„ich will sehen was der Ivan hat und dem
entsprechend planen"*. Termine sollen dabei **nicht** in fremde Kalender geschrieben,
sondern **als Einladung verschickt** werden, die der andere annimmt oder ablehnt —
bei Ablehnung mit Grund und optionalem Gegenvorschlag.

**Verwandte Vorhaben:** `2026-09-11-vorhaben-uebersicht.md` nennt die Reihenfolge und die
Abhängigkeiten zwischen diesem und den drei Folgevorhaben.

---

## 1. Ausgangslage, gemessen

Am 11.09.2026 gegen den laufenden Kalenderserver gemessen (lesend, von der VM aus):

| Befund | Wert |
|---|---|
| Kalenderserver | `dav.privateemail.com`, SabreDAV |
| Kalender im Konto des Betreibers | **genau einer** (`41`, Anzeigename `felix@vibemind.space`) |
| Freigabe-Fähigkeit | **vorhanden** — `resource-sharing`, `calendarserver-sharing` |
| Einladungs-Fähigkeit | **vorhanden** — `calendar-auto-schedule` |
| Frei/Belegt-Fähigkeit | **vorhanden** — `calendar-availability` |
| Stellvertreter | **vorhanden** — `calendar-proxy` |
| Kalender bereits als geteilt markiert | ja, `shared-owner` |

Im Code:

* `CALDAV_URL`/`CALDAV_USER`/`CALDAV_PASSWORT` — **genau ein** Endpunkt, zugleich Lese- und
  Schreibziel (`sales-mcp/kalender.py`).
* `kalender.ics()` erzeugt eine Kalenderdatei **ohne `METHOD:`** — ausführlich begründet
  (RFC 4791 §4.1: „MUST NOT have a METHOD property"). Für CalDAV richtig, für Einladungen
  unbrauchbar.
* Der Mailversand (`sales-mcp/mail_dispatch.py`) kennt **keine Anhänge** — kein
  `multipart`, kein `MIMEBase`.
* Das Postfach wird gelesen (`sales-mcp/postfach.py`, IMAP), ausdrücklich **nur lesend**.
* Die Oberfläche erkennt bereits doppelt belegte Zeitfenster, prüft aber nur **einen**
  Kalender.

**Alle Teammitglieder nutzen denselben Anbieter** (PrivateEmail). Die Teamgröße wächst noch.

---

## 2. Was gebaut wird

Zwei Hälften, die sich ergänzen und nicht ersetzen:

**Sicht** beantwortet „wann kann ich überhaupt einladen" — der Bot kennt die Termine der
Kollegen und schlägt keine belegten Zeiten vor.

**Einladung** macht einen Termin verbindlich — der andere sagt zu, ab, oder schlägt etwas
anderes vor.

### 2.1 Kalenderquellen werden eine Liste

Die drei `CALDAV_*`-Werte werden zu einer Liste von Quellen. Jede Quelle trägt:

* einen **Anzeigenamen** („Ivan", „Privat") — erscheint in der Oberfläche
* einen **Endpunkt** samt Zugangsdaten
* eine **Rolle**: `schreiben` (genau eine Quelle) oder `lesen` (beliebig viele)

Das ist der Angelpunkt des Entwurfs. Es löst drei Fälle mit einer Struktur: die
freigegebenen Kalender der Kollegen, den eigenen Privatkalender, und später Kunden mit
einem anderen Anbieter — ohne dass jemand Code anfasst.

Jede Quelle trägt zusätzlich eine **Art**: `caldav` (der eigene Kalender, schreibend) oder
`ics` (ein abonnierter fremder Kalender, immer nur lesend).

**Drei Wege, wie eine fremde Quelle entsteht — Weg 3 ist der Regelfall:**

1. **Entdeckt.** Gibt ein Kollege **beim selben Anbieter** seinen Kalender frei, erscheint
   er nach dem Sharing-Standard im Konto des Empfängers; ein `PROPFIND` findet ihn neben dem
   eigenen. Niemand tauscht Passwörter. Setzt voraus, dass beide Konten auf demselben Server
   liegen.
2. **Eingetragen.** Eine Quelle mit eigenen Zugangsdaten von Hand. Rückfall, unerwünscht:
   fremde Zugangsdaten zu verwalten ist die teuerste aller Varianten.
3. **Abonniert (Regelfall).** Der Kollege gibt die **geheime iCal-Adresse** seines Kalenders
   heraus — eine URL, die jeder große Anbieter anbietet (Google: „Geheime Adresse im
   iCal-Format"; Apple, Outlook, Nextcloud, PrivateEmail entsprechend). Kein Konto, kein
   Passwort, kein Zugriff auf das Postfach, vom Kollegen jederzeit widerrufbar.

> **Revision 12.09.2026 — gemessen, nicht vermutet.** Dieser Abschnitt hieß bis dahin „zwei
> Wege" und erklärte Weg 1 zum Regelfall, gestützt auf die Annahme „die Kollegen nutzen
> auch PrivateEmail". **Die Annahme ist hinfällig:** das erste Teammitglied (Ivan) arbeitet
> mit einem Google-Konto. Zwischen PrivateEmail und Google gibt es keine CalDAV-Freigabe —
> das sind zwei Server, die nichts voneinander wissen. Weg 1 bleibt als Abkürzung für
> Kollegen beim selben Anbieter im Entwurf, ist aber **nicht mehr die Grundlage**, und die
> Messung „erscheint eine Freigabe im fremden Konto?" ist damit keine Voraussetzung des
> Vorhabens mehr, sondern eine spätere Bequemlichkeit.
>
> Weg 3 trägt stattdessen, und er ist **der einzige anbieterunabhängige**. Er passt zudem
> besser zur Entkopplung, die dieser Abschnitt ohnehin herstellt: Ob hinter einer Quelle
> PrivateEmail, Google oder etwas Drittes steht, bleibt der Software gleichgültig.
>
> **Was Weg 3 kostet:** Die Adresse ist ein Schlüssel in Form einer URL — wer sie hat, liest
> den Kalender, bis der Kollege sie zurücksetzt. Sie gehört deshalb behandelt wie ein
> Passwort (§4).

### 2.2 Überlappungsprüfung wird personenübergreifend

Heute fragt die Doppelbelegungs-Erkennung: „hat der Betreiber dann schon etwas?"
Künftig: „haben **alle Beteiligten** dann schon etwas?"

**Präzisiert am 12.09.2026 auf ausdrücklichen Wunsch des Betreibers** („dass Ivans und
meiner dann berücksichtigt wird"): Geprüft wird gegen **jede aktive Quelle**, nicht gegen
eine ausgewählte. Ein Termin, an dem Betreiber und Kollege teilnehmen, ist nur dann frei,
wenn er in **beiden** Kalendern frei ist. Das ist der ganze Zweck des Vorhabens — eine
Prüfung, die nur den eigenen Kalender kennt, hat den Betreiber genau dorthin gebracht, wo
er heute steht.

Daraus folgen zwei Dinge, die leicht übersehen werden:

* **Eine Quelle, die gerade nicht abrufbar ist, darf nicht stillschweigend als „frei"
  gelten.** Sonst schlägt der Bot ausgerechnet dann Termine vor, wenn er am wenigsten
  weiß. Ist eine Quelle veraltet oder unerreichbar, sagt er es — und schlägt mit dem
  Vorbehalt vor, statt ihn zu verschweigen.
* **Der eigene Privatkalender zählt mit.** Er wird nicht freigegeben (§3 Ziffer 1), aber er
  ist eine Quelle für die eigene Belegung. Sonst wäre die Trennung in zwei Kalender ein
  Rückschritt gegenüber heute.

Der Bot schlägt keinen Termin vor, der bei einem der Beteiligten kollidiert. Findet er
keine freie Zeit, sagt er das — statt einen Vorschlag zu machen, der abgelehnt wird.

### 2.3 Termine werden als Einladung verschickt

Statt in einen fremden Kalender zu schreiben, verschickt sales-claw eine Einladung. Das
ist der etablierte Weg (iMIP: Kalenderdatei als Mailanhang) und funktioniert auch mit
Menschen **außerhalb** des Teams, die kein sales-claw haben — mit Kunden also.

**Nötig dafür:**

* **Eine zweite ICS-Fassung.** Die bestehende bleibt unverändert für CalDAV. Die neue
  trägt `METHOD:REQUEST`, `ORGANIZER` und je Teilnehmer eine `ATTENDEE`-Zeile mit
  `RSVP=TRUE`. Beide Fassungen beschreiben dieselbe Buchung unter derselben Kennung.
* **Anhänge im Mailversand.** Die Einladung reist als `text/calendar`-Teil mit
  `method=REQUEST` neben dem lesbaren Text.
* **Antworten verstehen.** Eine Zusage oder Absage kommt als Mail mit `METHOD:REPLY`
  zurück; darin steht je Teilnehmer der Status (`ACCEPTED`, `DECLINED`, `TENTATIVE`) und
  optional ein Kommentar — das ist der **Ablehnungsgrund**.
* **Gegenvorschlag verstehen.** Schlägt der andere eine andere Zeit vor, kommt
  `METHOD:COUNTER` mit dem neuen Zeitpunkt. Der Bot legt ihn dem Betreiber vor; erst
  dessen Freigabe macht daraus eine neue Einladung.

**Das Freigabe-Gate bleibt unangetastet.** Eine Einladung ist eine ausgehende Nachricht und
läuft wie jede andere durch `entwurf_erstellen` und die Freigabe des Betreibers. Es entsteht
**kein zweiter Weg nach draußen**.

### 2.4 Der Austausch zwischen den Instanzen ist der Standard selbst

Ein eigenes Protokoll zwischen den sales-claw-Instanzen wird **nicht** gebaut. Läuft die
Abstimmung über Einladungen, ist der Austausch bereits da: Die eine Instanz verschickt, die
andere empfängt im Postfach, legt vor, antwortet. Dasselbe funktioniert mit jedem
Kalenderprogramm der Welt — und mit Kollegen, die noch kein sales-claw haben.

Ein Eigenbau-Protokoll wäre teurer und könnte weniger.

### 2.5 Team-Sicht in der Oberfläche

Im Kalender wird je Eintrag sichtbar, zu wem er gehört.

**Darstellung und Daten sind hier getrennt zu betrachten, sonst blockiert das eine das
andere:** Dieses Vorhaben liefert die **Daten** — welcher Termin gehört zu wem — und eine
schlichte, sofort brauchbare Anzeige: der Name der Person am Eintrag, wie heute die Marke
„zwei Quellen". Das genügt zum Arbeiten und hängt von nichts ab.

Die **farbliche** Unterscheidung und die Wochenansicht gehören zu Stufe 4 der
Oberflächen-Überarbeitung (`2026-09-10-sales-ui-ueberarbeitung-design.md` §6) und werden
dort gebaut — mit dem Personenbezug als weiterer Farbdimension neben den Terminkategorien.
Kommt Stufe 4 später, ist das kein Hindernis; kommt sie vorher, wird hier nichts doppelt
gemacht.

Bei den offenen Einladungen zeigt die Oberfläche den Stand: wer zugesagt hat, wer abgelehnt
hat und mit welcher Begründung, wo ein Gegenvorschlag wartet.

### 2.6 Fähigkeiten je Quelle anzeigen

Beim Einrichten fragt die Software jede Quelle nach ihren Fähigkeiten — derselbe Aufruf,
mit dem die Befunde in §1 entstanden sind — und zeigt das Ergebnis. Kann ein Anbieter keine
Freigaben oder keine Einladungen, **steht es dort**, statt dass sich jemand wundert, warum
Termine fehlen.

Das folgt dem Vorbild der WhatsApp-Seite: die Kette zeigen und jede Station belegen.

### 2.7 Der Kollege verbindet seinen Kalender selbst (12.09.2026)

Eine Seite im Tailnet, erreichbar über **einen Link**, den der Betreiber verschickt. Sie
führt durch drei Schritte:

1. **„Welchen Kalender nutzt du?"** — Google, Apple, Outlook, anderer.
2. **Der Klickweg für genau diesen Anbieter.** Drei Zeilen für seinen, nicht ein Text für
   alle.
3. **Adresse einfügen — die Seite holt sie sofort ab und antwortet im Klartext:** „Passt.
   Ich sehe 14 Termine, der nächste am Montag um 09:00."

**Schritt 3 ist der Kern, nicht die Zierde.** Der häufigste Fehler ist, die *öffentliche*
statt der *geheimen* Adresse zu erwischen oder einen Link auf eine Webseite zu kopieren.
Ohne sofortige Rückmeldung merkt das niemand, und die Sicht bleibt tagelang leer, ohne dass
jemand weiß warum. Die Seite muss deshalb bei Misserfolg sagen, **was** sie stattdessen
bekommen hat — nicht „ungültig".

Danach zeigt die Seite nur noch „verbunden, zuletzt gelesen um HH:MM". **Die Adresse wird
nie wieder angezeigt**, auch nicht dem Betreiber: sie ist ein Schlüssel, kein Anzeigewert.

**Öffentlich erreichbar ist daran nichts.** Die Seite liegt hinter Tailscale, wie die
übrige Oberfläche. Das unterscheidet sie von der Kundenbuchungsseite
(`2026-09-11-terminbuchung-kunden-design.md`), die aus dem offenen Netz erreichbar sein
muss — Kollegen können ins Tailnet, Kunden nicht.

**Eine schmale Rolle `kalender`.** Heute gilt im Code: *„Rolle `lesen` sieht alles und darf
nichts verändern."* „Alles" heißt sämtliche Kontakte, Entwürfe und den Posteingang — der
komplette Kundenstamm. Ein Kollege, der nur Termine abgleichen soll, bekommt deshalb eine
dritte Rolle, die ausschließlich den Kalender und diese Seite sieht. Ohne sie ist Ziffer 2
in §3 nicht vertretbar.

---

## 3. Was der Betreiber einrichtet

1. **Einen zweiten Kalender „Privat" anlegen** und **nicht** freigeben. Solange Privates und
   Geschäftliches in einem Kalender liegen, bedeutet „das Team sieht alles" auch: das Team
   sieht Arzttermine. Das eigene Kalenderprogramm zeigt weiterhin beide übereinander.
2. **Den Kollegen ins Tailnet holen** und ihm ein Konto mit der Rolle `kalender` geben —
   damit er die eigene Seite sieht.
3. **Ihm den Verbindungslink schicken.** Den Rest macht er selbst (§2.7); der Betreiber
   muss keine Adresse abtippen und keine fremden Zugangsdaten entgegennehmen.
4. **Die Quelle benennen** — welcher Kalender gehört zu wem.

Schritt 1 ist **nicht optional**: Er ist die Voraussetzung dafür, dass volle Sichtbarkeit
vertretbar ist. Dieselbe Empfehlung gilt für den Kollegen — er sollte einen eigenen
Kalender „Arbeit" abonnierbar machen statt seinen privaten.

---

## 4. Datenschutz

Mit voller Sichtbarkeit fließen **Kundendaten zwischen Teammitgliedern**: Wer Ivans
Kalender sieht, sieht Namen und Firmen seiner Kunden. Innerhalb eines gemeinsam
verkaufenden Teams ist das üblich und zulässig — es steht aber heute in **keinem** der
Dokumente.

**Zu ergänzen, bevor die Funktion in Betrieb geht:**

* `docs/06_DSGVO.md` — wer sieht wessen Termindaten, auf welcher Grundlage
* `docs/08_TOMS.md` — wie die Trennung technisch durchgesetzt wird (getrennte Kalender,
  Leserechte statt Vollzugriff)
* `docs/07_AVV_VORLAGE.md` — **sobald sales-claw bei Kunden läuft.** Dort ist der Kunde
  Verantwortlicher und der Betreiber Auftragsverarbeiter; eine Funktion, die Termindaten
  zwischen Mitarbeitern sichtbar macht, gehört in den Vertrag.

Der Betreiber hat „volle Details" ausdrücklich gewählt. Die Alternative — nur Frei/Belegt —
bleibt technisch offen, weil der Server `calendar-availability` kann; sie wäre der
datensparsame Weg, falls ein Kunde das verlangt.

**Die geheime Kalenderadresse ist ein Geheimnis (12.09.2026, mit Weg 3 in §2.1
hinzugekommen).** Sie trägt ihre Berechtigung in sich: Wer sie kennt, liest den Kalender
des Kollegen vollständig, ohne Anmeldung und ohne Spur. Daraus folgt, ohne Ausnahme:

* Sie steht in der Datenbank, **nie** in einem Log, **nie** in einer Fehlermeldung, **nie**
  in der Oberfläche — auch nicht für den Betreiber. `kalender._ohne_geheimnis()` filtert
  bereits das CalDAV-Passwort aus Fehlertexten; dieselbe Kante gilt hier.
* Sie erscheint in **keiner** Sicherung, die das Haus verlässt, ohne dass jemand weiß, dass
  sie darin steckt — `docs/04_BACKUP_RESTORE.md` ist entsprechend zu ergänzen.
* Der Kollege muss wissen, dass **er** sie widerrufen kann, und wie. Das gehört auf die
  Verbindungsseite, nicht in eine Fußnote.

Der Widerruf ist damit beim Kollegen und nicht beim Betreiber — das ist ein Vorzug
gegenüber ausgetauschten Zugangsdaten, kein Zufall.

---

## 5. Nicht im Umfang

* **Mehrere sales-claw-Instanzen** — eigenes Vorhaben
  (`2026-09-11-mehrere-instanzen-design.md`). Dieses hier funktioniert mit einer Instanz;
  die Kollegen wirken über ihren normalen Kalender mit.
* **Schreiben in fremde Kalender** — ausdrücklich nicht. Gelesen wird alles Freigegebene,
  geschrieben nur der eigene Kalender. Alles andere geht über Einladungen.
* **Eigener Kalenderserver** — eigenes Vorhaben
  (`2026-09-11-eigener-kalenderserver-design.md`).
* **Terminbuchung durch Kunden** — eigenes Vorhaben
  (`2026-09-11-terminbuchung-kunden-design.md`).
* **Automatisches Annehmen von Einladungen** — der Betreiber entscheidet, nicht der Bot.

---

## 6. Prüfung

**Am laufenden System gemessen, nicht am Code behauptet.**

1. **Ein Kollege verbindet seinen Kalender selbst** (Torschritt, Revision 12.09.2026): Er
   öffnet den Link im Tailnet, wählt seinen Anbieter, fügt die geheime Adresse ein — und
   die Seite antwortet mit der Zahl der gefundenen Termine und dem nächsten davon. Ein
   falsch kopierter Link (öffentliche Adresse, Webseite) wird **benannt**, nicht bloß
   abgewiesen. Danach steht die Adresse nirgends mehr auf dem Bildschirm.
2. **Fremde Termine sichtbar**: Ein Termin im Kalender eines Kollegen erscheint in der
   Team-Sicht mit dessen Namen.
3. **Keine Kollisionsvorschläge**: Zu einer Zeit, in der der Kollege belegt ist, schlägt der
   Bot keinen Termin vor — und sagt, dass er keine freie Zeit findet.
3a. **Beide Seiten zählen**: Ein gemeinsamer Termin wird nur vorgeschlagen, wenn er im
   Kalender des Betreibers **und** in dem des Kollegen frei ist. Gegenprobe in beide
   Richtungen: je einmal blockiert nur der eine, dann nur der andere.
3b. **Eine stumme Quelle gilt nicht als frei**: Ist eine Quelle unerreichbar oder veraltet,
   sagt der Bot es beim Vorschlag — er verschweigt die Lücke nicht.
4. **Einladung kommt an**: Eine verschickte Einladung erscheint im Kalenderprogramm des
   Empfängers als annehmbare Einladung, nicht als Textmail mit Anhang.
5. **Zusage wird verstanden**: Nach der Annahme steht der Termin in der Oberfläche als
   zugesagt.
6. **Absage mit Grund**: Eine Ablehnung samt Begründung erscheint lesbar in der Oberfläche.
7. **Gegenvorschlag**: Ein Gegenvorschlag wird dem Betreiber vorgelegt und wird erst nach
   dessen Freigabe zur neuen Einladung.
8. **Fremder Anbieter**: Eine Einladung an ein Konto außerhalb des Teams (Kunde) verhält
   sich wie eine gewöhnliche Kalendereinladung.

Prüfung 1 ist der **Torschritt**. Bis zum 12.09.2026 war das eine andere Prüfung — „taucht
eine Freigabe im fremden Konto auf?" —, und ihr Ergebnis sollte entscheiden, ob die billige
oder die teure Fassung gebaut wird. Diese Frage ist weggefallen, weil der erste Kollege bei
einem anderen Anbieter arbeitet (§2.1). Der neue Torschritt misst dafür etwas Härteres:
ob ein Mensch, der von ICS nichts weiß, seinen Kalender in drei Schritten verbindet.
Scheitert er dort, nützt der Rest des Vorhabens nichts.
