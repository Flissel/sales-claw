# C2 Verträge & Projekte · C3 Kontakt-Historie gegen Doppeltes

Stand: 17.10.2026 · Status: vom Betreiber im Chat freigegeben (Entwurf), Spec zur Durchsicht
Teil 2 und 3 des Kontaktlisten-Umbaus (Block C). Setzt C1 voraus (Art + Bereiche, live seit
17.10.2026). Die beiden Teile sind unabhängig und teilen sich nur die Kontaktseite.

## 1. Anlass und Entscheidungen

Vorgaben des Betreibers (Chat 16./17.10.):
- „Vermerken, womit die Kontakte bereits benachrichtigt worden sind“.
- „Ob schon etwas abgeschlossen worden ist, welche Software-Projekte dort waren“.
- IT-Lösungen, Homelab, bAV und private Rente dokumentieren.

| Frage | Entscheidung |
|---|---|
| C2 Felder | Status + Datum, Anbieter/Partner, Betrag (EUR), Wiedervorlage, dazu Bereich, Bezeichnung, Notiz |
| C2 fremde Verträge | **Eine Liste, zwei Arten:** „bei uns“ (eigener Abschluss/Projekt) und „fremd“ (vom Kunden genannt) |
| C3 Quellen | versendete Entwürfe, Newsletter, Termine & Einladungen, eigene Handy-Nachrichten |
| C3 Zweck | **Doppeltes verhindern** |
| C3 Erkennung | **Thema-Stichwort** je Entwurf, Frist 90 Tage |
| C3 Treffer | **Warnen, Betreiber entscheidet** (kein harter Block) |

Gemessen am 17.10.2026 (VM, Schema `sales`):
- 5289 Aktivitäten `nachricht_ausgehend`, also eigene Handy-Nachrichten, die über den
  Webhook gebucht wurden.
- 47 `versand`-Aktivitäten.
- Entwürfe nach Kanal und Status: whatsapp 19 gesendet, email 21, linkedin 6, telegram 1.
- `drafts.newsletter` (uuid) markiert Newsletter-Entwürfe.
- `enrichment.vertraege` (fremde Verträge über `vertrag_speichern`) ist bisher leer.

---

## Teil C2 — Verträge & Projekte

### 2.1 Modell

Einträge liegen weiter im Array `leads.enrichment.vertraege`, ohne DDL. Ein Eintrag sieht so
aus:

```json
{"id": "<uuid>", "art": "eigen" | "fremd", "bereich": "<C1-Schluessel>|''",
 "bezeichnung": "", "status": "angeboten|in_arbeit|abgeschlossen|beendet|''",
 "status_datum": "YYYY-MM-DD|''", "anbieter": "", "betrag": "1234.56|''",
 "wiedervorlage_am": "YYYY-MM-DD|''", "notiz": "", "erfasst": "YYYY-MM-DD",
 "wiedervorlage_id": "<activity id>|''"}
```

- **Bestehende fremde Einträge** (alte Form: `sparte`, `gesellschaft`, `ablauf`, `notiz`,
  `erfasst`) werden beim Lesen normalisiert: `art: "fremd"`, `bezeichnung` ← `sparte`,
  `anbieter` ← `gesellschaft`, `ablauf` bleibt. Fehlt `id`, wird sie beim ersten Schreiben
  vergeben. Eine Migration ist nicht nötig.
- **Status** (Schlüssel → Anzeige): `angeboten` → angeboten, `in_arbeit` → in Arbeit,
  `abgeschlossen` → abgeschlossen, `beendet` → beendet. Für `fremd` bleibt der Status leer.
- **Betrag:** Dezimalzahl ≥ 0 mit höchstens 2 Nachkommastellen, immer EUR, gespeichert als
  String mit Punkt.
- **Längen:** Textfelder höchstens 200 Zeichen. Höchstens 50 Einträge je Kontakt.
- **Protokoll:** Aktivitäten `vertrag_angelegt` und `vertrag_geaendert` mit der Nutzlast
  `{id, vorher?, nachher}`.

### 2.2 Regeln

- **Wiedervorlage, eigen:**
  - Gesetztes `wiedervorlage_am` legt eine Wiedervorlage genau zu diesem Datum an. Bei Änderung
    wird die alte quittiert (`wiedervorlage_erledigt`) und eine neue angelegt.
  - Ein Datum in der Vergangenheit gibt `{fehler}`.
  - Status `beendet` quittiert die offene Wiedervorlage.
- **Wiedervorlage, fremd:** wie heute über `vertrag_speichern`, 90 Tage vor `ablauf`.
- **`abgeschlossen`** fügt `bereich` per `_einordnen(..., hinzu=[bereich])` den Bereichen des
  Kontakts hinzu (C1), falls gesetzt.
- **UWG:** Ein Abschluss setzt **nicht** automatisch `existing_customer`. Diese Bewertung trifft
  der Betreiber über `einwilligung_erfassen`.
- **Sperren:** Privat markierte Kontakte und Sammelkontakte bekommen keine Einträge (`{fehler}`).

### 2.3 Bausteine

- **Neues Modul `sales-mcp/vertraege.py`:**
  - `eintraege(lead_id) -> list` (normalisiert, neueste zuerst)
  - `speichern(lead_id, art, bereich, bezeichnung, status="", status_datum="", anbieter="",
    betrag="", wiedervorlage_am="", notiz="", eintrag_id="", quelle="agent") -> dict` (anlegen
    oder ändern; `fremd` nur über diesen Weg aus der UI, der Agent nutzt für fremd weiter
    `vertrag_speichern`)
- **Agent-Werkzeug `abschluss_speichern(lead_id, bereich, bezeichnung, status, status_datum="",
  anbieter="", betrag="", wiedervorlage_am="", notiz="", eintrag_id="")`:**
  - nur `art="eigen"`;
  - im Kundenchat tabu;
  - Docstring: nur auf Zuruf oder bei eindeutigem Gesprächsinhalt, nie raten, jede Änderung
    nennen.
- **`vertrag_speichern`** bleibt in Signatur und Verhalten gleich, schreibt aber zusätzlich
  `id` und `art: "fremd"`.
- **`profil_lesen`:** `vertraege` liefert die normalisierte Liste.
- **Kontaktseite:** Kasten „Verträge & Projekte“.
  - Tabelle mit Art, Bereich, Bezeichnung, Status/Datum, Anbieter, Betrag, Wiedervorlage und
    Notiz.
  - Formular „Neu“ und „Bearbeiten“ je Zeile, POST `/kontakte/vertrag` mit CSRF.
  - Rolle `lesen` sieht alles ohne Formular.
- **AGENTS.md:** Kurzabschnitt in „Einordnung“ oder ein eigener Abschnitt „Verträge &
  Projekte“. Darin: Wann `abschluss_speichern` gilt und wann `vertrag_speichern`, kein
  Bestandskunden-Status ohne Betreiber. Tabu-Liste ergänzen.

---

## Teil C3 — Kontakt-Historie gegen Doppeltes

### 3.1 Modell

- **Neue Spalte `drafts.thema text null`** über `provision.sql`, je Laden-Schema, wie die
  Newsletter-Spalten. Normalisierung für den Vergleich: klein geschrieben, Leerraum
  zusammengefasst, höchstens 80 Zeichen.
- **Wer setzt das Thema?**
  - Optionaler Parameter `thema: str = ""` an `entwurf_erstellen`, `post_entwurf_erstellen`,
    `mail_beantworten` und `antwort_entwerfen`, falls vorhanden (Implementierung prüft die
    Liste der Entwurfs-Werkzeuge).
  - Die internen Wege setzen es fest: Terminnachrichten `termin`, Newsletter
    `Newsletter: <Betreff>`.

### 3.2 Prüfung vor dem Entwurf

- **`doppelt_pruefen(lead_id, thema, tage=90) -> list`** liefert Treffer
  `{draft_id, kanal, thema, status, datum}`. Treffer sind Entwürfe desselben Kontakts mit
  gleichem normalisiertem Thema und dem Status `pending`, `approved` oder `sent`, deren
  `created_at` (bzw. `sent_at`) jünger als 90 Tage ist. Das Thema `termin` wird nie geprüft.
- **Bei den Entwurfs-Werkzeugen mit Thema** gilt:
  - Gibt es Treffer und ist `trotzdem` nicht True, wird kein Entwurf angelegt, sondern
    `{"doppelt": [...], "hinweis": "Schon am TT.MM. per <Kanal> zum Thema <x> angeschrieben —
    trotzdem anlegen? Dann trotzdem=True."}` zurückgegeben.
  - Mit `trotzdem=True` entsteht der Entwurf, und der Hinweis wird im Entwurf vermerkt
    (Aktivität `doppelt_bestaetigt`).
- **Ohne Thema** keine Prüfung. Der Prompt verlangt aber ein Thema bei jeder Erstansprache und
  jedem Angebot.
- **Freigabe-Seite:** Eine Karte mit Thema zeigt, sofern Treffer existieren, „Schon
  angeschrieben: TT.MM. · Kanal · Thema“.

### 3.3 Historie

`kontakt_historie(lead_id, tage=365) -> list` mit Einträgen `{datum, art, kanal, text}`,
neueste zuerst:
- versendete Entwürfe (`sent`), mit Thema oder sonst Betreff bzw. den ersten 60 Zeichen;
- Newsletter (Entwürfe mit `newsletter`);
- `termin`, `termin_abgesagt` und `einladung_entworfen`;
- `nachricht_ausgehend` zusammengefasst je Monat: „N Nachrichten (WhatsApp vom Handy)“.

Weitere Ausgaben:
- **`profil_lesen`** bekommt `zuletzt_angeschrieben` (jüngster Eintrag ohne Handy-Summe) und
  `historie_kurz` (die letzten 5).
- **Kontaktseite:** kleine Zeitleiste „Kontakt-Historie“ (die letzten 20, Link „alle“).
- **Agent-Werkzeug `kontakt_historie_lesen(lead_id)`:** liest nur, im Kundenchat tabu.

### 3.4 Prompt

Kurzer Abschnitt „Doppeltes vermeiden“:
- Bei jeder Erstansprache und jedem Angebot ein Thema setzen.
- Bei `doppelt` dem Betreiber den früheren Kontakt nennen, nur auf sein „trotzdem“ mit
  `trotzdem=True` erneut aufrufen.

## 4. Bewusst nicht

- Provisions- und Abrechnungsfelder, Dokument-Anhänge an Verträgen.
- Automatischer Bestandskunden-Status.
- Textähnlichkeit, Filter „nie angeschrieben“ in der Kontaktliste.
- Rückwirkendes Thema für alte Entwürfe (alt = ohne Thema, keine Prüfung).

## 5. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Unbekannter Bereich/Status, Betrag kein Geld, Datum ungültig, Wiedervorlage in Vergangenheit | `{fehler}`, nichts geschrieben |
| `eintrag_id` unbekannt | `{fehler}` |
| Mehr als 50 Einträge | `{fehler}` |
| Privat/Sammel | `{fehler}` |
| Altform-Einträge mit fehlenden Feldern | normalisiert angezeigt, keine Ausnahme |
| Thema leer | keine Doppel-Prüfung |
| `drafts.thema` fehlt (Schema nicht aktualisiert) | Werkzeuge melden `{fehler}` mit Hinweis auf provision.sql statt 500 |

## 6. Tests

- **`vertraege.py`:**
  - Anlegen und Ändern eigen; Normalisierung der Altform; Betragsformat.
  - Wiedervorlage anlegen, ändern (alte quittiert) und `beendet` (quittiert).
  - `abgeschlossen` setzt den Bereich; Sperren; Grenzen.
  - `vertrag_speichern` schreibt `id`/`art` und bleibt kompatibel (bestehende Tests grün).
- **Werkzeuge:** registriert, Tabu-Liste, Drift-Test AGENTS.md.
- **UI:**
  - Kasten zeigt beide Arten; Formular speichert; CSRF; Rolle lesen; Escaping.
  - Zeitleiste zeigt Einträge; Freigabe-Karte zeigt „Schon angeschrieben“.
- **C3:**
  - `doppelt_pruefen` (Frist, Status, Normalisierung, `termin` ausgenommen).
  - Werkzeug ohne `trotzdem` legt nicht an, mit `trotzdem` legt an und protokolliert.
  - `kontakt_historie` (Quellen, Handy-Summe je Monat, Reihenfolge).
  - `profil_lesen`-Felder.
  - Schema-Test für `drafts.thema` in provision.sql.
- **Live nach Deploy:**
  1. provision.sql als supabase_admin, Spalte je Schema prüfen.
  2. Probeläufe gegen `sales_test`.
  3. Kontaktseite eines echten Kontakts per HTTP (Historie sichtbar, 200).
