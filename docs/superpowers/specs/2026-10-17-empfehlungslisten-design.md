# C4 Empfehlungslisten (Pole Position, Mitarbeitervorschläge)

Stand: 17.10.2026 · Status: vom Betreiber im Chat freigegeben (Entwurf), Spec zur Durchsicht
Teil 4 von 4 des Kontaktlisten-Umbaus (Block C). Setzt C1 voraus (Art + Bereiche, live seit
17.10.2026, sales-claw `79f0fe1`).

## 1. Anlass

Der Betreiber arbeitet mit zwei Papier-Vordrucken von fin2gether (Vorlagen:
`Downloads/Pole Position.pdf`, `Downloads/MAV-Liste pdf.pdf`):

| Vordruck | Kopf | Spalten | Zeilen |
|---|---|---|---|
| **Pole Position – Konzept für den Aufbau von Empfehlungen** | Name, Vorname, Struktur | Name, Vorname, Beruf, Alter, Ort, Telefon, Termin, Ergebnis | 15 |
| **Mitarbeitervorschläge** | Name, Struktur | Vorname/Name, Alter (ab 22), Beruf, Telefon, Was zeichnet aus, Was interessiert, Termin | 25 |

Der Kopf trägt den Berater (Betreiber) und seine Struktur, die Zeilen die empfohlenen Menschen.
Pole-Position-Kontakte sind Firmen (bAV) oder Personen für Mitarbeit, private
Vorsorge/Versicherung oder Immobilien.

Gewünscht (Chat 16./17.10.):
- ausgefüllte Liste fotografieren, daraus Kontakte machen;
- die Liste digital führen;
- die Liste als PDF ausgeben.

## 2. Entscheidungen des Betreibers

| Frage | Entscheidung |
|---|---|
| Wer steht im Kopf? | Der Berater und seine Struktur |
| Empfehlungsgeber | **Einer pro Blatt**; jede Zeile wird mit „empfohlen von X“ verknüpft |
| Einwilligung beim Foto | **Pro Liste bestätigen**: „Hat X alle gefragt, ob du dich melden darfst?“ Ja setzt das Häkchen für alle Zeilen. Einzelne Zeilen lassen sich später umstellen. |
| Termin/Ergebnis | **Auswahl + echter Termin.** Ergebnis ist offen · nicht erreicht · Termin vereinbart · kein Interesse · Abschluss, dazu Notiz. Termin ist ein echter Kundentermin. |
| PDF | **Wie der Vordruck**: gleiche Spalten, Querformat, Titel des Vordrucks, ohne Logo |
| Aufbau | Neue Tabelle für Listen, Zeilen sind normale Kontakte |

## 3. Modell

### 3.1 Tabelle `empfehlungslisten` (db/provision.sql, je Laden-Schema; DDL nur über provision.sql als supabase_admin)

| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` | uuid pk default gen_random_uuid() | |
| `art` | text not null check in ('pole_position','mitarbeitervorschlaege') | Vordruck |
| `empfohlen_von_lead` | uuid null references leads(id) on delete set null | Empfehlungsgeber im CRM |
| `empfohlen_von_name` | text not null | Anzeigename, 1–120 Zeichen |
| `datum` | date not null | Datum der Liste |
| `berater_name` | text not null default '' | Kopf „Name/Vorname“ |
| `struktur` | text not null default '' | Kopf „Struktur“ |
| `bereiche` | jsonb not null default '[]' | C1-Bereiche, für die die Liste gedacht ist |
| `einwilligung` | boolean not null default false | „vorab gefragt“ für die Liste bestätigt |
| `einwilligung_am` | timestamptz null | |
| `erstellt_am` | timestamptz not null default now() | |

Rechte wie bei `eigene_termine`: `sales_app` auf `sales`, Laden-Rollen (`sales_app_<laden>`) je
Schema auf `select, insert, update`. Ein Delete gibt es nicht, Listen werden nicht gelöscht.
`db/laden-anlegen.sql` bekommt die Tabelle mit.

### 3.2 Zeilen = Kontakte

Jede Zeile ist ein `leads`-Eintrag. Die Vordruck-Daten liegen in `enrichment.empfehlung`:

```json
{"liste_id": "<uuid>", "beruf": "", "alter": null, "ort": "",
 "zeichnet_aus": "", "interessiert": "", "ergebnis": "offen", "notiz": "",
 "einwilligung": true}
```

- **`ergebnis`:** `offen` · `nicht_erreicht` · `termin` · `kein_interesse` · `abschluss`. Anzeige:
  offen · nicht erreicht · Termin vereinbart · kein Interesse · Abschluss.
- **`alter`:** int 16–99 oder null. Bei Mitarbeitervorschlägen unter 22 gibt es nur einen Hinweis,
  keine Sperre.
- **Name:** „Vorname Name“ in `leads.name`, Telefon in `leads.phone`.
- **Dubletten:** Eine Telefonnummer, die schon zu einem Kontakt gehört (`kontakt_anlegen`-Dedup),
  verknüpft den bestehenden Kontakt. Ist dort schon eine `empfehlung` aus einer anderen Liste
  gespeichert, bleibt sie, und die neue Liste führt den Kontakt nur als „schon bekannt“ (siehe
  §4.1). Privat markierte Kontakte werden nicht verknüpft, die Zeile wird abgewiesen und dem
  Betreiber gemeldet.
- **Einordnung (C1)** über `_einordnen(..., quelle="agent"|"ui")`:
  - Mitarbeitervorschläge → `person` + `mitarbeiter`.
  - Pole Position → Bereiche der Liste. Eine Zeile, die der Betreiber in der Vorschau als Firma
    kennzeichnet, wird `firma` + `bav`.
- **Einwilligung:** Ist sie für die Zeile gesetzt, wird sie über `einwilligung_erfassen(lead,
  "opt_in", quelle=f"Empfehlung: vorab gefragt von {empfohlen_von_name} (Liste {datum})")` gebucht.
  Ohne Häkchen wird nichts gebucht, der Kontakt bleibt `unknown`, und die bestehenden UWG-Tore
  greifen. Wird das Häkchen später entfernt, folgt `einwilligung_widerrufen(lead, "Empfehlung:
  Häkchen entfernt")`.
- **Termin:** Ein Kundentermin des Kontakts (Aktivität `termin`, nicht abgesagt) setzt `ergebnis`
  auf `termin`, solange es `offen` oder `nicht_erreicht` war. Gerechnet wird das in der Anzeige,
  nicht gespeichert, damit Absagen sich von selbst zurücknehmen.

## 4. Bausteine

### 4.1 Kern (sales-mcp/empfehlungen.py, neues Modul; server.py nur Werkzeug-Hüllen)

- `liste_anlegen(art, empfohlen_von_name, datum, zeilen, empfohlen_von_lead=None, berater_name=None,
  struktur=None, bereiche=(), einwilligung=False, quelle="agent") -> dict`
  - **`zeilen`:** Liste aus `{vorname, name, beruf, alter, ort, telefon, zeichnet_aus,
    interessiert, firma: bool}`. Höchstens 25 Zeilen (Mitarbeitervorschläge) bzw. 15 (Pole
    Position). Je Zeile ist `vorname` oder `name` Pflicht, `telefon` optional. Textfelder
    höchstens 200 Zeichen.
  - **Kopf:** `berater_name`/`struktur` sind None? Dann werden sie von der jüngsten Liste
    übernommen, sonst `''`.
  - **Schreiben:** Liste und Zeilen in einer Transaktion. Je Zeile Kontakt anlegen oder
    verknüpfen, `enrichment.empfehlung` setzen (nur bei neuen Kontakten oder bei bestehenden ohne
    `empfehlung`), einordnen und gegebenenfalls die Einwilligung buchen. Außerdem eine Aktivität
    `empfehlung` am Kontakt, Nutzlast `{liste_id, empfohlen_von_name}`.
  - **Rückgabe:** `{liste_id, neu, verknuepft, abgewiesen: [{zeile, grund}], hinweise}`.
- `listen() -> list` (Übersicht mit Zählern je Ergebnis).
- `liste(liste_id) -> dict` (Kopf und Zeilen mit wirksamem Ergebnis).
- `zeile_setzen(lead_id, ergebnis=None, notiz=None, einwilligung=None, quelle="ui") -> dict`
  (Einwilligung bucht oder widerruft wie in §3.2).
- `zeile_hinzufuegen(liste_id, zeile, quelle="ui") -> dict`.
- `pdf(liste_id) -> bytes` (reportlab, siehe §4.3).
- **Agent-Werkzeuge in server.py:**
  - `empfehlungsliste_anlegen(art, empfohlen_von, datum, zeilen, einwilligung, bereiche=[],
    berater_name="", struktur="")`. `empfohlen_von` ist eine lead_id oder ein Name: Ist es eine
    gültige lead_id eines Kontakts, wird sie verknüpft, sonst gilt es als Name.
  - `empfehlungslisten_zeigen(liste_id="")` (ohne id die Übersicht).
  - Beide kommen in `WERKZEUGE` und in die Tabu-Liste für Kundenchats.

### 4.2 Agent (Skill `config/workspace/skills/empfehlungsliste/SKILL.md` + AGENTS.md-Verweis)

**Auslöser:** Foto oder Diktat einer Empfehlungsliste, Pole Position, Mitarbeitervorschläge,
„Empfehlungen“, „Wen kennst du“-Liste.

1. **Lesen.** Das Bild wird gelesen (Vision), die Tabelle als nummerierte Zeilen im Chat gezeigt.
   Unsichere Felder bekommen ein `(?)`. Nichts wird geraten. Unleserliche Felder bleiben leer und
   werden genannt.
2. **Eine gesammelte Rückfrage:**
   - Welcher Vordruck?
   - Wer hat die Liste gegeben (Name, ggf. CRM-Kontakt)? Datum?
   - Hat dieser Mensch **alle** gefragt, ob du dich melden darfst?
   - Für welche Bereiche ist die Liste (nur Pole Position)? Welche Zeilen sind Firmen?
   - Korrekturen an den gelesenen Zeilen?
   - Name und Struktur für den Kopf: nur beim ersten Mal, danach vorbelegt.
3. **Anlegen.** Erst auf das Ok des Betreibers `empfehlungsliste_anlegen(...)` aufrufen und das
   Ergebnis in einer Zeile melden („Liste angelegt: 12 neu, 2 schon bekannt, 1 abgewiesen
   (privat)“, mit Link `/empfehlungen/<id>`).
4. **Ansprache:** Empfohlene werden nie von sich aus angeschrieben. Entwürfe gibt es nur auf
   Zuruf und nur mit Einwilligung, wie bei allen Kontakten.

### 4.3 Oberfläche (sales-mcp/ui_empfehlungen.py, eingehängt wie ui_kalender)

- **`GET /empfehlungen`:** Tabelle der Listen mit Datum, Vordruck, Empfehlungsgeber (Link zum
  Kontakt, falls verknüpft), Anzahl und Zählern (offen / Termin / Abschluss). Neueste zuerst.
- **`GET /empfehlungen/{id}`:**
  - **Kopf:** Vordruck, Empfehlungsgeber, Datum, Name/Struktur, Einwilligung.
  - **Tabelle** in Spaltenreihenfolge des Vordrucks:
    - Name → Kontaktseite;
    - Ergebnis als Auswahl;
    - Notiz;
    - Häkchen „darf kontaktiert werden“;
    - Termin: Datum des nächsten Kundentermins oder Knopf „Termin“ → `/kalender?neu=kunde&lead_id=<id>`.
  - **Speichern** je Zeile per POST `/empfehlungen/zeile` (CSRF).
  - **„Zeile hinzufügen“** per POST `/empfehlungen/{id}/zeile`.
  - **„PDF“** per `GET /empfehlungen/{id}.pdf`.
- **Kalender-Vorbelegung:** `/kalender?neu=kunde&lead_id=…` öffnet den Neu-Dialog mit dem Kontakt
  vorgewählt. Das ist eine kleine Erweiterung in `kalender/src` (Startparameter lesen).
- **Navigation:** „Empfehlungen“ unter „Analyse“ neben „Kontakte“.
- **Rollen:** `lesen` sieht alles, schreibt nichts. `kalender` hat keinen Zugriff.
- **PDF:** reportlab, A4 quer.
  - Titelzeile wie der Vordruck; Kopf mit „Name: … Struktur: …“ (Pole Position zusätzlich
    „Vorname“ aus `berater_name` geteilt), dazu Empfohlen von und Datum.
  - Tabelle mit den Vordruck-Spalten. Die Spalte „Ergebnis“ (nur Pole Position) zeigt den
    Anzeigetext. „Termin“ zeigt das Datum des Kundentermins.
  - Leere Restzeilen bis 15 bzw. 25, damit das Blatt auf Papier weitergeführt werden kann. Mehr
    Zeilen ergeben eine Folgeseite.
  - Ohne Logo. Lange Texte werden umbrochen. Schrift Helvetica mit Transliteration wie in
    `formular.py`.

## 5. Bewusst nicht in C4

- Abschlüsse und Projekte (C2), Kontakt-Historie (C3).
- Automatische Ansprache der Empfohlenen.
- Löschen von Listen. Eine Zeile entfernt man, indem man den Kontakt archiviert.
- Das fin2gether-Logo und eine Einstellungsseite (der Kopf wird pro Liste gespeichert und von der
  jüngsten Liste vorbelegt).

## 6. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Zu viele Zeilen, leere Zeile, Feld zu lang, Alter außerhalb 16–99 | `{fehler}` mit Zeilennummer, nichts angelegt (Transaktion) |
| Telefonnummer unlesbar/ungültig | Zeile ohne Telefon anlegen, Hinweis „Telefon prüfen“ |
| Nummer gehört privat markiertem Kontakt | Zeile abgewiesen (`abgewiesen`), Rest wird angelegt |
| Nummer gehört Kontakt mit Empfehlung aus anderer Liste | verknüpft als „schon bekannt“, alte Empfehlung bleibt |
| Empfehlungsgeber-lead_id unbekannt | als Name behandelt |
| Häkchen entfernt | Widerruf gebucht, `consent_status` zurück auf `unknown` |
| Liste unbekannt (UI/PDF) | 404 |
| DB nicht erreichbar | Werkzeug `{fehler}`, UI 503 wie bisher |
| Sonderzeichen/HTML in Namen | escaped in UI, transliteriert im PDF |

## 7. Tests

- **Kern (`tests/test_empfehlungen.py`, Name vorher prüfen):**
  - Anlegen beider Vordrucke; Grenzen 15/25; Pflichtfelder.
  - Dublette: verknüpft, Privat abgewiesen, fremde Empfehlung bleibt.
  - Einordnung je Vordruck; Firmenzeile → firma + bav.
  - Einwilligung pro Liste und das Umstellen je Zeile (Buchung/Widerruf).
  - Kopf-Vorbelegung aus der letzten Liste; Transaktion (Fehler in Zeile 7 → nichts angelegt).
  - Wirksames Ergebnis durch Termin; abgesagter Termin nimmt es zurück.
- **Werkzeuge:** registriert, Signaturen, Tabu-Liste, Drift-Test AGENTS/Skill.
- **UI:**
  - Übersicht und Liste; Ergebnis/Notiz/Häkchen speichern; CSRF 403; Rolle `lesen` ohne
    Formulare; `kalender` kein Zugriff.
  - Escaping; 404.
  - PDF: Content-Type, Seitenzahl bei 16 bzw. 26 Zeilen, Text enthält Titel und Spalten
    (`pypdf`).
- **Kalender:** vitest für den Startparameter `neu=kunde&lead_id`.
- **Live nach Deploy:**
  1. provision.sql als supabase_admin, Tabelle und Rechte je Schema prüfen.
  2. `/empfehlungen` per HTTP prüfen (leer, 200).
  3. Den vollen Ablauf (Anlegen, Ansicht, PDF) im Container gegen das Schema `sales_test` fahren.
     Listen lassen sich nicht löschen, eine Probeliste im echten Schema bliebe sichtbar.
  4. Die erste echte Liste legt der Betreiber per Foto an. Danach werden Ansicht und PDF
     gemeinsam geprüft.
