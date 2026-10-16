# C1 Kontaktarten & Bereiche

Stand: 16.10.2026 · Status: vom Betreiber im Chat freigegeben (Entwurf), Spec zur Durchsicht
Teil 1 von 4 des Kontaktlisten-Umbaus (Block C). C2 Abschlüsse & Projekte, C3 Kontakt-Historie
und C4 Empfehlungslisten (Pole Position, Mitarbeitervorschläge) bauen darauf auf und bekommen je
eine eigene Spec.

## 1. Anlass

Der Betreiber will die Kontaktliste nach Zielgruppen trennen. Vorgaben im Chat vom 15./16.10.:
- Mitarbeiterliste, Privatpersonen und Firmenkontakte unterscheiden.
- Pole-Position-Kontakte sind Firmen (für bAV) oder Personen, die für Mitarbeit, private
  Vorsorge/Versicherung oder Immobilien in Frage kommen.
- IT-Lösungen und Homelab-Lösungen sind eigene Bereiche, bAV und private Rente ebenfalls.

Gemessen am 16.10.2026 auf der VM (Schema `sales`):
- 567 Kontakte, davon 477 mit Firmenfeld (fast alle aus der Google-Maps-Recherche,
  `source='recherche'`).
- Die Kontaktliste zeigt höchstens 500 Einträge (`ui.KONTAKTE_MAX`). 67 Kontakte sind heute in
  der Liste unsichtbar.
- Auf der Kontaktseite lassen sich nur `name`, `phone` und `email` ändern
  (`server.KONTAKT_FELDER`), das Firmenfeld nicht.
- Die bestehende Markierung „privat“ (`enrichment._privat`, 17 Kontakte) bedeutet „persönlicher
  Kontakt, nichts speichern“. Sie ist **keine** Kundengruppe und bleibt unverändert.

## 2. Entscheidungen des Betreibers

| Frage | Entscheidung |
|---|---|
| Feste Arten oder Art + Bereiche? | **Art + Bereiche.** Art ist Person oder Firma, Bereiche gibt es mehrere gleichzeitig. Die Mitarbeiterliste zeigt Personen mit Bereich Mitarbeiter. |
| Bestand? | **Automatisch + Liste.** Firmenfeld ergibt Firma, Recherche-Firmen bekommen zusätzlich bAV, alle anderen werden Person ohne Bereich. Ein Reiter „Nicht eingeordnet“ zeigt sie zum Nachpflegen. Privat markierte bleiben unberührt. |
| Wer pflegt? | Der Betreiber auf der Kontaktseite, der Agent auf Zuruf oder bei eindeutigem Gesprächsinhalt, jeweils mit Meldung im Chat. |

## 3. Modell

**Art** (`enrichment.art`), genau ein Wert:

| Schlüssel | Anzeige |
|---|---|
| `person` | Person |
| `firma` | Firma |

**Bereiche** (`enrichment.bereiche`, Liste ohne Doppelte, Reihenfolge wie hier):

| Schlüssel | Anzeige |
|---|---|
| `bav` | bAV |
| `mitarbeiter` | Mitarbeiter |
| `vorsorge` | Private Vorsorge/Versicherung |
| `immobilien` | Immobilien |
| `it` | IT-Lösung |
| `homelab` | Homelab |

- Beide Schlüssel fehlen bei Kontakten, die nie eingeordnet wurden. Die Oberfläche zeigt dann
  „—“. Gefiltert wird so: ohne `art` gilt als „Person“, wenn kein Firmenfeld gesetzt ist, sonst
  als „Firma“. So bleibt ein neuer Kontakt vor der ersten Einordnung trotzdem filterbar.
- **„Nicht eingeordnet“** heißt: `bereiche` fehlt oder ist leer.
- **„Mitarbeiter-Kandidaten“** heißt: Art (wirksam) Person und `mitarbeiter` in `bereiche`.
- Am Datenbankschema ändert sich nichts. Beide Werte liegen in der bestehenden Spalte
  `leads.enrichment` (jsonb).
- **Protokoll:** Jede Änderung bucht eine Aktivität `einordnung` mit der Nutzlast
  `{"art_vorher", "art", "bereiche_vorher", "bereiche", "weg": "ui"|"agent"|"bestand"}`. Der Wert
  `actor` ist `human` (ui), `agent` oder `cron` (bestand).
- **Sperren:** Kontakte mit Markierung privat (`server._privat`) und der Sammelkontakt werden nie
  eingeordnet. Werkzeug und Formular lehnen ab, die Bestandsaufnahme überspringt sie. Archivierte
  Kontakte dürfen eingeordnet werden.

## 4. Bausteine

### 4.1 Kern (sales-mcp/server.py)

- Konstanten `ARTEN = ("person", "firma")`, `BEREICHE` als geordnetes Mapping Schlüssel → Anzeige
  (Tabelle §3).
- `_einordnung(enrichment, company) -> (art_wirksam: str, bereiche: list[str])`, rein, ohne DB.
- `_einordnen(lead_id, art=None, hinzu=(), weg=(), quelle="agent") -> dict` ist der einzige
  Schreibweg. Er prüft Schlüssel, Sperren und Existenz, schreibt `enrichment` per jsonb-Merge (nur
  `art`/`bereiche`, nie andere Schlüssel), bucht `einordnung` und gibt `{art, bereiche}` oder
  `{fehler}` zurück. Hat sich nichts geändert, wird nichts gebucht und `{..., "unveraendert": true}`
  zurückgegeben.
- Agent-Werkzeug `kontakt_einordnen(lead_id: str, art: str = "", bereiche_hinzu: list = [],
  bereiche_weg: list = []) -> str` als dünne Hülle (`quelle="agent"`). Es kommt in `WERKZEUGE`.
- `kontakt_anlegen` setzt bei neuen Kontakten `art` sofort: `firma`, wenn `company` gesetzt ist bzw.
  der Name eine Firma in Klammern trägt, wie bei Visitenkarten („Mario Ries (Conrad Electronic
  SE)“), sonst `person`. Es wird keine `einordnung`-Aktivität gebucht, das Anlegen selbst ist
  protokolliert.
- `profil_lesen` gibt `art` (wirksam) und `bereiche` mit aus.
- `KONTAKT_FELDER` bekommt `company` dazu (Werkzeug `kontakt_aktualisieren` und Formular),
  höchstens 200 Zeichen.
- `einordnung_bestand() -> dict` (kein Werkzeug) setzt für jeden Kontakt **ohne** `art`, der nicht
  privat und kein Sammelkontakt ist, die Art nach Firmenfeld. Kontakte mit `source='recherche'` und
  Art firma bekommen `bereiche=["bav"]`. Jede Änderung wird als `einordnung` mit `weg: "bestand"`
  gebucht. Rückgabe `{firmen, personen, bav, uebersprungen}`. Idempotent: ein zweiter Lauf ändert
  nichts.

### 4.2 Oberfläche (sales-mcp/ui.py)

**`/kontakte`:**
- **Reiter** (Query `ansicht`): `alle` (Vorgabe) · `personen` · `firmen` · `mitarbeiter`
  (Mitarbeiter-Kandidaten) · `offen` (nicht eingeordnet). Jeder Reiter zeigt seine Anzahl.
- **Bereich-Filter** (Query `bereich`, einer der Schlüssel), kombinierbar mit dem Reiter.
- **Suche** (Query `q`, höchstens 100 Zeichen, Teiltreffer ohne Groß/Klein in Name, Firma und
  Telefon). Die Telefonsuche vergleicht Ziffern.
- **Blättern** (Query `seite`, 100 Kontakte je Seite) ersetzt die 500er-Grenze.
- Bestehende Schalter bleiben erhalten (`archiv=1`).
- Neue Spalte „Einordnung“ mit Art-Chip und Bereich-Chips.
- Gefiltert wird in SQL, nicht in Python.

**Kontaktseite `/kontakte/{id}`:**
- Kasten „Einordnung“ mit Radiogruppe Art und je einem Häkchen pro Bereich, Knopf „Speichern“.
  POST `/kontakte/einordnen` mit CSRF wie die anderen Formulare. Gespeichert wird über `_einordnen(...,
  quelle="ui")`, danach Redirect zurück zur Kontaktseite. Bei privat oder Sammelkontakt erscheint
  der Kasten nicht, und ein POST wird mit 403 abgelehnt.
- Das Bearbeiten-Formular zeigt `company` (Feld „Firma“).
- Rolle `lesen` bzw. `kalender`: nur Anzeige, wie bisher bei Schreibformularen.

### 4.3 Agent (config/workspace/AGENTS.md)

Kurzer Abschnitt „Einordnung“ mit diesen Regeln:
- Art und Bereiche, mit der Tabelle aus §3.
- Wann `kontakt_einordnen` benutzt wird: auf Zuruf des Betreibers oder bei eindeutigem
  Gesprächsinhalt (z. B. „interessiert sich für private Rente“ → `vorsorge`). Nie raten.
- Jede Änderung im Chat nennen, z. B. „eingeordnet: Person · Vorsorge“.
- Privat markierte Kontakte und den Sammelkontakt nie einordnen.

`kontakt_einordnen` kommt in die Liste der Werkzeuge, die im Kundenchat tabu sind.

## 5. Bewusst nicht in C1

- Abschlüsse und Projekte je Bereich (C2), Kontakt-Historie inklusive Newsletter (C3),
  Empfehlungslisten mit Foto-Erfassung und PDF (C4).
- Frei definierbare Bereiche. Die sechs Bereiche stehen im Code, ein neuer ist eine
  Codeänderung.
- Massenbearbeitung (mehrere Kontakte auf einmal einordnen).

## 6. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Unbekannter Art- oder Bereich-Schlüssel | `{fehler}` mit der Liste der gültigen Schlüssel, nichts geschrieben |
| Kontakt privat oder Sammelkontakt | `{fehler}` (Werkzeug), 403 (Formular), übersprungen (Bestand) |
| Kontakt existiert nicht / ungültige id | `{fehler}` bzw. 404 |
| Gleicher Bereich in hinzu und weg | `{fehler}`, nichts geschrieben |
| Nichts geändert | kein Protokolleintrag, `unveraendert: true` |
| Suche mit Sonderzeichen (`%`, `_`, `'`) | als Text behandelt (escapt), kein SQL-Fehler |
| `seite` außerhalb des Bereichs oder kein Integer | letzte bzw. erste Seite, kein Fehler |
| DB nicht erreichbar | Kontaktliste zeigt Fehlerseite wie bisher, Werkzeug gibt `{fehler}` zurück |

## 7. Tests

- **Kern:** `_einordnung` (wirksame Art ohne `art`), `_einordnen` (Gültigkeit, Sperren, Merge
  lässt andere enrichment-Schlüssel unangetastet, Protokoll mit vorher/nachher, unverändert ohne
  Protokoll), `kontakt_einordnen` registriert mit Signatur, `kontakt_anlegen` setzt die Art (mit
  Firma, mit Klammer-Firma, ohne Firma), `company` über `kontakt_aktualisieren`, `profil_lesen`
  enthält die Einordnung, `einordnung_bestand` (Zuordnung, privat/Sammel übersprungen,
  idempotent).
- **UI:**
  - Reiter und Anzahlen, Bereich-Filter, Suche mit Sonderzeichen, Blättern über 100 hinaus (mehr
    als 500 Kontakte erzeugen, alle erreichbar).
  - Einordnung-Formular speichert und protokolliert `weg: ui`, CSRF fehlt ergibt 403, privat
    ergibt 403, Rolle lesen sieht kein Formular.
  - Firma bearbeitbar, alles escapt.
- **Prompt:** Drift-Test `test_agents_regeln.py` (Werkzeug in Abschnitt und Tabu-Liste).
- **Live nach Deploy:**
  - Probelauf, dann Lauf von `einordnung_bestand()` auf der VM. Die Zahlen werden mit der
    Messung verglichen (477 mit Firmenfeld → firma).
  - Reiter und Suche per HTTP-Probe im Container `sales-ui`.
  - Nicht eingeordnete zählen.
