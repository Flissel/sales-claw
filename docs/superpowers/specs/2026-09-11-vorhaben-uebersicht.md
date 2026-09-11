# Vier Vorhaben rund um Termine — Übersicht, Reihenfolge, Abhängigkeiten

**Datum:** 2026-09-11
**Zweck:** Aus der Frage „wie verbinde ich meinen Kalender mit dem des Teams" sind vier
Vorhaben geworden. Dieses Dokument hält fest, wie sie zusammenhängen und warum sie in
dieser Reihenfolge stehen.

---

## Die vier

| # | Vorhaben | Spec | Größe |
|---|---|---|---|
| 1 | **Team-Terminabstimmung** — Sicht auf die Kalender der Kollegen, Termine per Einladung statt Eintrag | `2026-09-11-team-terminabstimmung-design.md` | mittel |
| 2 | **Mehrere Instanzen** — je Teammitglied eine sales-claw auf der VM | `2026-09-11-mehrere-instanzen-design.md` | groß |
| 3 | **Eigener Kalenderserver** — SOGo aus dem vorhandenen Mailcow, auf der VM | `2026-09-11-eigener-kalenderserver-design.md` | mittel + Umzug |
| 4 | **Terminbuchung durch Kunden** — Buchungsseite fürs LinkedIn-Profil | `2026-09-11-terminbuchung-kunden-design.md` | mittel, nach außen sichtbar |

---

## Reihenfolge und warum

**1 zuerst.** Es ist das einzige, das sofort Nutzen bringt und dabei **nichts** voraussetzt:
keine neuen Instanzen, keinen neuen Server. Die Kollegen wirken über ihren normalen Kalender
mit. Und es liefert zwei Bausteine, auf denen alles Weitere steht — verlässliche
Frei/Belegt-Auskunft und funktionierende Einladungen.

**3 Schritt 1 (SOGo einschalten) parallel.** Billig, reversibel, schafft Wissen: Kann SOGo,
was der Entwurf von einem Kalenderserver erwartet? Das lässt sich klären, während 1 gebaut
wird, und ohne dass etwas umzieht.

**4 danach.** Die Buchungsseite ist eine Einladung, die der Kunde auslöst. Ohne 1 wäre sie
ein Versprechen ohne Deckung — und sie ist das einzige Vorhaben, dessen Fehler Fremde sehen.

**2 zuletzt, oder wenn das Team wächst.** Mehrere Instanzen sind Betriebsarbeit ohne
unmittelbaren fachlichen Gewinn: Die Terminabstimmung aus 1 funktioniert mit einer Instanz.
Sie werden nötig, wenn Kollegen **eigene** Bots für ihre eigenen Kunden brauchen — nicht,
um Termine zu teilen.

**3 Schritte 2–3 (Umzug) nach Bedarf.** Ein Mailserver-Umzug ist unumkehrbar genug, um
einen konkreten Anlass abzuwarten: ein Kunde, dessen Anbieter keine Freigaben kann, oder
ein Ärgernis mit Namecheap.

---

## Abhängigkeiten

```
1 Team-Terminabstimmung
├── liefert Frei/Belegt  ──────────→ 4 Terminbuchung
├── liefert Einladungen  ──────────→ 4 Terminbuchung
└── Quellen als Liste    ──────────→ 3 Kalenderserver (Endpunktwechsel ohne Codeänderung)

2 Mehrere Instanzen — unabhängig von allen dreien
```

Die Quellenliste aus Vorhaben 1 ist der Grund, warum 3 später **keine** Codeänderung mehr
braucht: Ob hinter einem Endpunkt PrivateEmail, SOGo oder etwas Drittes steht, ist der
Software gleichgültig. Diese Entkopplung ist bewusst früh eingezogen.

---

## Was am 11.09.2026 gemessen wurde

Diese Befunde tragen alle vier Specs und wurden am laufenden System erhoben, nicht vermutet:

* Der Kalenderserver (`dav.privateemail.com`, SabreDAV) meldet **`resource-sharing`,
  `calendarserver-sharing`, `calendar-auto-schedule`, `calendar-availability`,
  `calendar-proxy`** — Freigaben, Einladungen und Frei/Belegt sind vorhanden.
* Der Betreiber hat **genau einen Kalender**; Privates und Geschäftliches liegen zusammen.
  Ein zweiter Kalender ist Voraussetzung für volle Sichtbarkeit im Team.
* `kalender.ics()` erzeugt bewusst **kein `METHOD:`** (RFC 4791 verbietet es in
  CalDAV-Dateien). Einladungen brauchen `METHOD:REQUEST` — es sind **zwei** Fassungen
  derselben Buchung nötig.
* Der Mailversand kann **keine Anhänge** (kein `multipart`, kein `MIMEBase`) — für
  Einladungen zu erweitern.
* Das Postfach wird per IMAP **nur lesend** genutzt — Antworten auf Einladungen zu
  verarbeiten ist neu.
* Eine zweite sales-claw-Instanz **startet heute nicht**: neun feste Containernamen, fester
  Projektname, vier literal benannte Volumes — darunter `sales-claw-state` mit der
  WhatsApp-Anmeldung.
* `SALES_DB_SCHEMA` ist bereits parametrisierbar; das `compliance`-Schema (Sperrliste) liegt
  außerhalb und **soll** von allen Instanzen geteilt werden.
* Mailcow läuft (zehn Container) **in WSL auf dem Arbeitsrechner**, ohne SOGo-Container —
  der Kalenderserver ist abgewählt, nicht abwesend.

---

## Was in keinem der vier Vorhaben steckt

* **Mandantenfähigkeit in der Anwendung** — eine Instanz mit mehreren getrennten Benutzern.
  Das wäre ein Umbau der Anwendung statt des Deployments.
* **Ein eigenes Protokoll zwischen den Bots.** Der Kalenderstandard leistet den Austausch
  bereits und funktioniert auch mit Menschen ohne sales-claw. Ein Eigenbau wäre teurer und
  könnte weniger.
* **Schreiben in fremde Kalender.** Gelesen wird alles Freigegebene, geschrieben nur der
  eigene; alles andere läuft über Einladungen.
* **Automatisches Zusagen.** Der Betreiber entscheidet, nicht der Bot.
