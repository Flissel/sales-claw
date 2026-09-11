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

**Zwei Wege, wie eine fremde Quelle entsteht:**

1. **Entdeckt (Regelfall).** Gibt ein Kollege seinen Kalender frei, erscheint er nach dem
   Sharing-Standard **im Konto des Empfängers**. Ein `PROPFIND` auf das eigene
   Kalender-Zuhause findet ihn dann neben dem eigenen. **Niemand tauscht Passwörter.**
2. **Eingetragen (Rückfall).** Kann ein Anbieter keine Freigaben, lässt sich eine Quelle
   mit eigenen Zugangsdaten von Hand eintragen.

> **Ungeprüfte Annahme, erster Schritt der Umsetzung:** Dass ein freigegebener Kalender im
> Konto des Empfängers auftaucht, ist die Mechanik des Standards, und der Server meldet die
> passenden Fähigkeiten — **gesehen haben wir es nicht**, weil bisher niemand etwas
> freigegeben hat. Der Plan beginnt deshalb mit einer Freigabe zwischen zwei Konten und der
> Messung, ob sie erscheint. Erscheint sie nicht, greift Weg 2 und das Vorhaben wächst um
> die Verwaltung fremder Zugangsdaten.

### 2.2 Überlappungsprüfung wird personenübergreifend

Heute fragt die Doppelbelegungs-Erkennung: „hat der Betreiber dann schon etwas?"
Künftig: „hat **die vorgesehene Person** dann schon etwas?"

Der Bot schlägt keinen Termin vor, der bei der vorgesehenen Person kollidiert. Findet er
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

---

## 3. Was der Betreiber einrichtet

1. **Einen zweiten Kalender „Privat" anlegen** und **nicht** freigeben. Solange Privates und
   Geschäftliches in einem Kalender liegen, bedeutet „das Team sieht alles" auch: das Team
   sieht Arzttermine. Das eigene Kalenderprogramm zeigt weiterhin beide übereinander.
2. **Den Geschäftskalender für die Kollegen freigeben** (Leserecht), und die Kollegen
   umgekehrt.
3. **Die entdeckten Quellen benennen** — welcher Kalender gehört zu wem.

Schritt 1 ist **nicht optional**: Er ist die Voraussetzung dafür, dass volle Sichtbarkeit
vertretbar ist.

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

1. **Freigabe erscheint** (erster Schritt, entscheidet den weiteren Umfang): Ein Kalender
   wird zwischen zwei Konten freigegeben; das `PROPFIND` auf das Kalender-Zuhause des
   Empfängers muss ihn finden.
2. **Fremde Termine sichtbar**: Ein Termin im Kalender eines Kollegen erscheint in der
   Team-Sicht mit dessen Namen.
3. **Keine Kollisionsvorschläge**: Zu einer Zeit, in der der Kollege belegt ist, schlägt der
   Bot keinen Termin vor — und sagt, dass er keine freie Zeit findet.
4. **Einladung kommt an**: Eine verschickte Einladung erscheint im Kalenderprogramm des
   Empfängers als annehmbare Einladung, nicht als Textmail mit Anhang.
5. **Zusage wird verstanden**: Nach der Annahme steht der Termin in der Oberfläche als
   zugesagt.
6. **Absage mit Grund**: Eine Ablehnung samt Begründung erscheint lesbar in der Oberfläche.
7. **Gegenvorschlag**: Ein Gegenvorschlag wird dem Betreiber vorgelegt und wird erst nach
   dessen Freigabe zur neuen Einladung.
8. **Fremder Anbieter**: Eine Einladung an ein Konto außerhalb des Teams (Kunde) verhält
   sich wie eine gewöhnliche Kalendereinladung.

Prüfung 1 ist der **Torschritt**: Ihr Ergebnis entscheidet, ob der Entwurf in der billigen
Fassung (§2.1 Weg 1) gebaut wird oder in der teureren (Weg 2).
