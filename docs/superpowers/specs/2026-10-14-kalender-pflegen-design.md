# Kalender: wie Google, Termine in der Oberfläche pflegen — Design (Block B)

Stand: 2026-10-14 · Status: in drei Abschnitten vom Betreiber freigegeben

Block B von drei. Block A (Agent, Freigabe, Versand) ist seit 14.10. live; Block C (Kontaktliste) folgt.

## Anlass

Der Betreiber findet den Kalender „nicht wirklich schön“ und will Termine in der Oberfläche pflegen.

Heute (gemessen 14.10.):
- `/kalender` ist ein Monatsgitter plus die Liste „Kommende Termine“.
- Je Kundentermin gibt es nur die Knöpfe „verschieben“ und „absagen“.
- Kundentermine sind keine eigenen Datensätze, sondern Aktivitäten am Kontakt (`termin`, `termin_abgesagt`). Dazu kommen eine ICS-Datei, ein CalDAV-Eintrag im Namecheap-Kalender des Betreibers und eine Wiedervorlage.
- Für eigene Termine ohne Kontakt gibt es keinen Speicherort.
- Kollegen-Kalender kommen lesend über `kalender_quellen`.
- Alle Seiten laufen ohne JavaScript (`default-src 'none'`). Die Ausnahme ist der Editor mit eigenem, eingechecktem Bundle von derselben Herkunft.

## Entscheidungen des Betreibers

| Frage | Antwort |
|---|---|
| Welche Termine pflegen | Kundentermine **und** eigene Termine (Blocker, interne Meetings): anlegen, ändern, löschen; alles auch im Namecheap-Kalender |
| Ansicht/Bedienung | Wie Google Kalender: Tag/Woche/Monat/Liste, Ziehen und Größe ändern |
| Speicher | Weg A: eigene Tabelle nur für eigene Termine; Kundentermine bleiben im Protokoll am Kontakt |
| Kundentermin geändert | Kalender sofort aktualisieren **und Entwurf an den Kunden zur Freigabe** |
| Extras | Konflikt-Warnung, Videoraum-Knopf, Handy-Termine sichtbar (eigener Namecheap-Kalender lesend) |
| Nicht dabei | Rückgängig nach Ziehen, wiederkehrende Termine, Buchungslink für Kunden |

## 1. Daten und Schnittstelle

### 1.1 Eigene Termine (neu)

Tabelle `eigene_termine` je Laden (in `db/provision.sql`, Schema-Schleife, additiv und idempotent):

```
uid text primary key, titel text not null, beginn timestamptz not null,
dauer_minuten int not null check (dauer_minuten between 5 and 1440),
ort text, notiz text, teilnehmer text[] not null default '{}',
kalender_stand text,            -- 'eingetragen' | Fehlertext (CalDAV)
erstellt_am timestamptz not null default now(),
geaendert_am timestamptz not null default now()
```

- `uid` hat das Format `<uuid>@sales-claw`, wie bei Kundenterminen.
- Anlegen und Ändern schreiben per `kalender.eintragen(uid, ics)` in den CalDAV-Kalender des Betreibers. Löschen läuft über `kalender.loeschen(uid)`.
- Scheitert CalDAV, bleibt der Datensatz, `kalender_stand` trägt den Grund, und die Oberfläche zeigt „nicht im Handy-Kalender“.
- Rechte: `sales_app` bekommt `select, insert, update, delete` auf diese Tabelle. Ein Löschen ist hier fachlich gewollt, anders als bei `drafts`.

### 1.2 Kundentermine (bestehend, erweitert)

Sie bleiben im Protokoll am Kontakt. Verschieben und Absagen laufen über `termin_verschieben` und `termin_absagen`.

**Neu: `termin_aendern(lead_id, uid, datum, uhrzeit, dauer_minuten, thema, ort)`**
- Technisch arbeitet es wie Verschieben: alt absagen, neu bestätigen, mit allen Feldern übernehmbar.
- Ohne jede Änderung kommt der Fehler „nichts geändert“.

**Entwurf an den Kunden bei jeder Änderung bzw. Absage aus der Oberfläche:**
- Hat der Kontakt eine E-Mail: Entwurf über den Weg von `termin_einladen` mit aktualisierter Einladung (ICS, `SEQUENCE` erhöht; bei Absage `METHOD:CANCEL`, falls `kalender.py` das kann, sonst ein Text-Entwurf).
- Sonst, wenn WhatsApp freigegeben ist: Text-Entwurf mit dem neuen Termin bzw. der Absage.
- Sonst: kein Entwurf, Hinweis „kein Kanal zum Kunden – bitte selbst Bescheid geben“.
- Alle Entwürfe sind `pending`. Es gilt die Freigabe wie immer (Block A).

**Neuer Kundentermin aus dem Kalender:** Kontakt suchen, dann `termin_bestaetigen`. Optional erzeugt das Häkchen „Einladung als Entwurf“ mit `termin_einladen` einen Entwurf.

**Alt-Termine ohne `uid`** (vor 01.09.2026): nur anzeigen.

### 1.3 Handy-Termine (neu, lesend)

- Der eigene CalDAV-Kalender des Betreibers (`CALDAV_URL`) wird für den angezeigten Zeitraum gelesen, mit derselben Lese-Logik wie bei den Kollegen-Kalendern.
- Ereignisse, deren `uid` zu einem eigenen Termin oder einem Kundentermin gehört, werden herausgefiltert (keine Doppelten).
- Der Rest erscheint als „Handy-Termin“: grau, nicht bearbeitbar.
- Ist der Kalender nicht abrufbar, zeigt die Oberfläche den Hinweis „Handy-Termine gerade nicht abrufbar“.

### 1.4 Konflikt-Warnung

- Vor Anlegen, Ziehen und Ändern wird gegen alle Arten geprüft: Kunde, eigen, Kollegen, Handy.
- Basis ist das bestehende `termin_konflikte`, erweitert um die neuen Arten.
- Bei einer Überschneidung antwortet die Schnittstelle `409` mit der Liste. Die Oberfläche bietet „trotzdem speichern“ (gleiche Anfrage mit `trotzdem: true`) oder „abbrechen“.
- Sind Handy- oder Kollegen-Kalender nicht abrufbar, sagt die Warnung „unvollständig geprüft“.

### 1.5 Videoraum

- Der Knopf „Videoraum“ im Anlegen- und Bearbeiten-Fenster trägt einen Raum-Link als Ort ein.
- Er nutzt dieselbe Funktion wie `termin_bestaetigen(konferenz_raum=True)` (`KONFERENZ_ANBIETER`, Rückfall Jitsi).
- Neue Route `POST /kalender/videoraum`, die nur den Link liefert.

### 1.6 JSON-Schnittstelle (sales-ui)

Alle Routen verlangen eine Anmeldung. Schreibende Routen verlangen eine CSRF-Marke wie die übrigen Formulare. Die Rolle `kalender` darf nur lesen; schreibende Aufrufe geben 403.

| Route | Zweck |
|---|---|
| `GET /kalender/termine.json?von=&bis=` | Alle Arten mit `art` (kunde/eigen/kollege/handy), `bearbeitbar`, `kontakt` (Name, lead_id), `uid`, `beginn`, `ende`, `titel`, `ort`, `geaendert_am` |
| `POST /kalender/termine` | Anlegen: eigener Termin oder Kundentermin (`lead_id`, `einladung: bool`) |
| `PATCH /kalender/termine/<uid>` | Ändern (Zeit, Dauer, Titel, Ort, Notiz) mit `geaendert_am` des Lesestands; bei Kundenterminen mit `draft_id` in der Antwort |
| `DELETE /kalender/termine/<uid>` | Eigener Termin: löschen. Kundentermin: absagen (`grund` Pflicht) plus Entwurf |
| `POST /kalender/videoraum` | Raum-Link |

Gleichzeitige Änderung: Passt `geaendert_am` nicht mehr, kommt `409` mit „inzwischen geändert – neu laden“.

## 2. Oberfläche

**Bundle:**
- Neuer Ordner `kalender/` (Vite, TypeScript, FullCalendar MIT: `core`, `daygrid`, `timegrid`, `list`, `interaction`).
- Gebaut nach `sales-mcp/static/kalender/kalender.js` und `.css`, eingecheckt wie der Editor und ausgeliefert über eine Route wie `/static/editor`.
- Nur `/kalender` bekommt `script-src 'self'` (plus `connect-src 'self'`). Alle anderen Seiten bleiben ohne JavaScript.

**Ansichten:**
- Woche ist Standard: sichtbar 07:00–20:00 und scrollbar, Arbeitszeit 08:00–18:00 hervorgehoben, Wochenende abgedunkelt.
- Umschaltbar sind Tag, Woche, Monat und Liste. Am Handy (schmale Breite) startet die Liste.
- Navigation über „Heute“ und vor/zurück. Die zuletzt gewählte Ansicht steht in `localStorage` (Zugriff in try/catch).

**Farben:**
- Kunde: Markenfarbe, mit Kontaktname.
- Eigen: Blau.
- Kollege: gedecktes Grün, mit Name.
- Handy: Grau.
- Abgesagte werden nicht angezeigt.

**Bedienung:**
- **Leerer Platz anklicken oder ziehen:** Fenster „Neuer Termin“.
  - Art wählbar (eigen/Kunde mit Kontaktsuche).
  - Felder: Titel/Thema, Dauer, Ort, Videoraum, Notiz; beim Kunden zusätzlich „Einladung als Entwurf“.
- **Termin anklicken:** Bearbeiten-Fenster mit denselben Feldern, dazu „Löschen“ bzw. „Absagen“ (Grund-Feld) und „Zum Kontakt“.
- **Ziehen/Größe ändern bei eigenen Terminen:** sofort speichern.
- **Ziehen/Größe ändern bei Kundenterminen:** Bestätigungsfenster „Verschieben auf <Tag Zeit> – Entwurf an Kunden wird angelegt“ mit OK/Abbrechen. Abbrechen setzt das Ereignis zurück.
- **Kollegen- und Handy-Termine:** nicht ziehbar, Klick zeigt nur Details.

**Rückmeldungen:**
- Kleiner Hinweis „Entwurf an Kunde angelegt – in Freigaben“ mit Link.
- Fehler stehen im Klartext.
- Konflikte erscheinen als Fenster mit „trotzdem“ oder „abbrechen“.

**Kontaktseite:** Ein Link „im Kalender öffnen“ führt zu `/kalender?datum=<tag>&ansicht=woche`.

**Rolle `kalender`:** dieselbe Ansicht ohne Anlegen, Ziehen und Bearbeiten (`editable: false`, `selectable: false`).

## 3. Fehlerfälle, Tests, Auslieferung

### Fehlerfälle

| Fall | Verhalten |
|---|---|
| CalDAV beim Speichern nicht erreichbar | Bei uns gespeichert, Hinweis „nicht im Handy-Kalender“. Erneuter Versuch beim nächsten Speichern bzw. Knopf „erneut eintragen“ |
| CalDAV beim Lesen nicht erreichbar | Ohne Handy-Termine, Hinweis oben; Konfliktprüfung „unvollständig“ |
| Gleichzeitige Änderung | 409 „inzwischen geändert – neu laden“ |
| Kundentermin ohne uid | Nur anzeigen, mit Begründung |
| Kunde ohne E-Mail und ohne freigegebenes WhatsApp | Änderung gespeichert, Hinweis „kein Kanal zum Kunden – bitte selbst Bescheid geben“ |
| Zeit in der Vergangenheit | Anlegen und Ziehen dorthin abgelehnt; Ansehen geht |
| Rolle `kalender` schreibt | 403 |
| CSRF fehlt oder falsch | 403 |

### Tests

- **sales-mcp (Test-Postgres `sales_test`):**
  - `eigene_termine` CRUD mit gefaktem CalDAV, inklusive `kalender_stand` bei Ausfall.
  - `termin_aendern`: Protokoll und Entwurf je Kanal (E-Mail mit ICS, WhatsApp-Text, kein Kanal → Hinweis).
  - Absage mit Pflichtgrund und Entwurf.
  - Konflikte über vier Arten.
  - Handy-Lesen filtert eigene uids.
  - Gleichzeitigkeit gibt 409.
- **sales-ui:**
  - `termine.json` je Rolle.
  - CSRF und Rolle bei schreibenden Routen.
  - CSP: `script-src 'self'` nur auf `/kalender`.
  - Drift-Test, dass das Bundle eingecheckt ist und zur Quelle passt (wie beim Editor).
- **Kalender-Bundle (vitest):**
  - Umrechnung Schnittstelle ↔ FullCalendar-Ereignis.
  - Dauer beim Größe-Ändern.
  - Bestätigungsfenster nur bei Kundenterminen.
  - Keine Bearbeitung bei `bearbeitbar: false` und für die Rolle `kalender`.
- **Echter Lauf nach der Auslieferung:**
  - Eigenen Termin anlegen (erscheint im Handy-Kalender), ziehen, löschen.
  - Probe-Kundentermin verschieben: Entwurf liegt in den Freigaben.
  - Termin am Handy anlegen: erscheint grau, die Konfliktwarnung greift.

### Auslieferung

1. `db/provision.sql` als `supabase_admin` (neue Tabelle) VOR `deploy/update.sh` (Erfahrung Block A).
2. Danach `update.sh` auf der VM.
3. Dann der echte Lauf.

## Nicht Teil dieses Blocks

- Rückgängig nach dem Ziehen.
- Wiederkehrende Termine.
- Buchungslink für Kunden.
- Bearbeiten von Kollegen- oder Handy-Terminen.
- Block C (Kontaktliste).
