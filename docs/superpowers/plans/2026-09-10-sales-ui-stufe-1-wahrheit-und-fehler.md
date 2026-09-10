# sales-ui Stufe 1 — Wahrheit und Fehler: Implementierungsplan

> **Für agentische Bearbeiter:** ERFORDERLICHE UNTER-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe
> abzuarbeiten. Die Schritte tragen Checkbox-Syntax (`- [ ]`) zur Nachverfolgung.

**Ziel:** Die Oberfläche zeigt keine falschen, doppelten oder verstümmelten Angaben
mehr — ohne dass sich Struktur oder Bedienung ändern.

**Architektur:** Alle Änderungen liegen in `sales-mcp/ui.py` (server-seitig
gerendertes HTML, Starlette). Kein neues Modul, keine neue Abhängigkeit, kein
JavaScript. Jede Aufgabe ist ein Vertragstest gegen `sales_test` plus die kleinste
Änderung, die ihn grün macht.

**Technik:** Python 3, Starlette, psycopg, pytest mit `starlette.testclient`,
Postgres mit pgvector.

**Spec:** `docs/superpowers/specs/2026-09-10-sales-ui-ueberarbeitung-design.md`
(Abschnitt 3, „Stufe 1 — Wahrheit und Fehler")

## Globale Randbedingungen

- **Kein JavaScript.** Die CSP bleibt in dieser Stufe unverändert bei
  `default-src 'none'`. Die Lockerung aus Spec §2.1 gehört zu Stufe 3.
- **Kein eigenes SQL für Schreibwege.** Das UI ruft ausschließlich Werkzeuge aus
  `server.py`. Stufe 1 ändert ohnehin nur Lesepfade und Darstellung.
- **Tests laufen gegen `SALES_DB_SCHEMA=sales_test`, niemals gegen `sales`.**
  Die `schema_wache`-Fixture in `tests/test_ui.py` erzwingt das; neue Testdateien
  übernehmen dasselbe Muster (`os.environ["SALES_DB_SCHEMA"] = "sales_test"` **vor**
  `import server`).
- **`ui.py` wird in dieser Stufe NICHT aufgeteilt.** Die Modularisierung aus Spec §2.2
  gehört zu Stufe 2; sie hier vorzuziehen würde jeden Diff unlesbar machen.
- **Kommentare und Docstrings bleiben unangetastet**, auch wenn sie ASCII-Umschreibungen
  enthalten. Geändert wird nur, was im Browser erscheint.

### Testlauf (gilt für jeden „Run"-Schritt unten)

**Die Umgebung steht bereits** (aufgebaut und verifiziert am 10.09.2026): Container
`sales-testdb` im Docker-Netz `sales-test-net`. Falls sie fehlt, so aufbauen — das
Rezept weicht bewusst vom CI-Workflow ab, siehe die drei Anmerkungen darunter:

```bash
docker network create sales-test-net
docker run -d --name sales-testdb --network sales-test-net \
  -e POSTGRES_PASSWORD=ci -p 55432:5432 pgvector/pgvector:pg16
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 \
  -c "create extension if not exists vector; create extension if not exists pgcrypto;"
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 < db/provision.sql
# Ohne diese Migration fallen 154 Tests aus (siehe Anmerkung 3):
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 \
  < ../marketing/db/013b_compliance_test_schema.sql
```

Danach je Lauf, aus dem Wurzelverzeichnis von sales-claw:

```bash
docker build -t sales-mcp-ci ./sales-mcp
docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test \
  -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/<datei> -q --tb=short -p no:cacheprovider
```

Im Folgenden abgekürzt als `PYTEST tests/<datei>`.

**Drei Abweichungen vom CI-Workflow, jede gemessen:**

1. **Eigenes Docker-Netz statt `--network host`.** Der CI-Workflow läuft auf
   `ubuntu-latest`, wo Host-Networking funktioniert; auf Docker Desktop für Windows
   tut es das nicht verlässlich. Der Testcontainer erreicht die Datenbank deshalb
   über den Containernamen `sales-testdb`, nicht über `localhost`.
2. **Port 55432 statt 5432.** Auf diesem Rechner belegt der Supabase-Container des
   VibeMind-Swarms bereits 5432. Der Port wird von außen ohnehin nur zum Nachsehen
   gebraucht — die Tests sprechen containerintern über 5432.
3. **`compliance_test` muss zusätzlich angelegt werden.** `sperrliste.py:30` leitet
   das Schema aus `SALES_DB_SCHEMA` ab: `sales_test` → `compliance_test`. Dessen DDL
   liegt aber im Marketing-Space (`spaces/marketing/db/013b_compliance_test_schema.sql`),
   nicht in `db/provision.sql`, und der CI-Workflow von sales-claw fährt sie nicht mit.
   Ohne sie brechen 154 Tests mit `InvalidSchemaName: schema "compliance_test" does
   not exist`. Die Migration `013_compliance_sperrliste.sql` wird **nicht** gebraucht
   und schlägt hier fehl (sie setzt das Schema `marketing` voraus).

**Ausgangswert vor Stufe 1, gemessen am 10.09.2026:**
`1508 passed, 4 warnings in 200.37s` — die Suite ist grün. Jeder Lauf nach einer
Aufgabe muss mindestens diese 1508 Tests grün halten; die Zahl steigt mit den neuen
Testdateien.

---

## Dateien

| Datei | Rolle |
|---|---|
| `sales-mcp/ui.py` | einzige geänderte Quelldatei dieser Stufe |
| `sales-mcp/tests/test_darstellung.py` | **neu** — Umlaute, Escaping, Textkürzung, Zählungen |
| `sales-mcp/tests/test_kalender_zeit.py` | **neu** — Zeitzone und Duplikate |

Die bestehenden Testdateien bleiben unverändert; sie sind die Rückversicherung, dass
Stufe 1 nichts kaputt macht.

---

## Aufgabe 1: Doppeltes HTML-Escaping

Belegt in der laufenden Anwendung: `/freigaben` zeigt den sichtbaren Text
`Video Call mit Sophie &amp; Stephane`, `/kalender` sogar
`Video Call mit Sophie &amp;amp\; Stephane`. Ein bereits escapeter Wert läuft ein
zweites Mal durch `html.escape`.

Diese Aufgabe steht zuerst, weil sie die kleinste ist und der Beweis dafür, dass die
Testkette funktioniert.

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Neu: `sales-mcp/tests/test_darstellung.py`

**Schnittstellen:**
- Verbraucht: `server._q`, `ui.app`, `_e` (`ui.py:295`)
- Erzeugt: die Testhelfer `_get`, `_lead`, `_termin_aktivitaet` — Aufgaben 2, 5, 6, 7
  bauen darauf auf

- [ ] **Schritt 1: Herausfinden, wo das zweite Escaping passiert**

Kein Code, sondern eine Messung. Der Wert kommt aus `activities.payload`. Zu klären
ist, ob dort bereits `&amp;` steht (dann escapet der **Schreibpfad** zu früh) oder ob
`&` gespeichert ist und der Lesepfad zweimal escapet.

```bash
docker exec -i sales-claw-db psql -U postgres -c \
  "select payload->>'thema' from sales.activities where type='termin' \
   and payload->>'thema' like '%amp%' limit 5;"
```

Notiere das Ergebnis in der Commit-Nachricht von Schritt 5. Steht `&amp;` in der
Datenbank, gehört zusätzlich eine einmalige Datenbereinigung dazu (Schritt 6).

- [ ] **Schritt 2: Fehlschlagenden Test schreiben**

```python
"""Vertragstests der Darstellung (Stufe 1): Escaping, Umlaute, Kuerzung, Zaehlungen.

Diese Datei prueft nicht, WAS die Oberflaeche kann, sondern ob das, was sie
zeigt, stimmt: ein kaufmaennisches Und bleibt ein kaufmaennisches Und, ein
Umlaut bleibt ein Umlaut, ein Satz endet nicht mitten im Wort.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _get(pfad, host=HOST_OK):
    return CLIENT.get(pfad, headers={"host": host})


def _lead(name="Max Bestand"):
    return str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, '+491701234567', 'whatsapp') returning id", (name,))[0]["id"])


def _termin_aktivitaet(lead_id, datum="2026-09-05", uhrzeit="19:00",
                       thema="Video Call mit Sophie & Stephane", ort=""):
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'termin', %s::jsonb)",
        (lead_id, json.dumps(
            {"datum": datum, "uhrzeit": uhrzeit, "thema": thema, "ort": ort,
             "uid": f"test-{datum}-{uhrzeit}"})))


def test_kaufmaennisches_und_erscheint_einmal_escapet():
    """`&` im Termin-Thema wird genau einmal escapet — nie `&amp;amp;`."""
    _termin_aktivitaet(_lead("Stephane B."))
    seite = _get("/kalender").text
    assert "&amp;amp;" not in seite, "doppelt escapet"
    assert "&amp;amp\\;" not in seite, "dreifach escapet"
    assert "Sophie &amp; Stephane" in seite, (
        "das kaufmaennische Und fehlt oder ist falsch escapet")
```

- [ ] **Schritt 3: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_darstellung.py::test_kaufmaennisches_und_erscheint_einmal_escapet`
Erwartet: FAIL — je nach Messung aus Schritt 1 entweder mit `&amp;amp;` im HTML
(Lesepfad escapet doppelt) oder mit fehlendem `Sophie &amp; Stephane`.

Wenn der Test hier bereits **besteht**, liegt der Fehler nicht im Lesepfad, sondern
in den Bestandsdaten. Dann Schritt 4 überspringen und direkt zu Schritt 6.

- [ ] **Schritt 4: Die doppelte Escape-Stelle entfernen**

Regel: `_e()` ist die **einzige** Stelle, die escapet, und sie wird genau beim
Zusammenbauen des HTML aufgerufen. Wer einen Wert vorher durch `html.escape` schickt
oder escapeten Text speichert, verletzt sie.

Zu tun: im Kalender- und Freigaben-Pfad jeden Aufruf suchen, bei dem ein bereits
durch `_e()` gelaufener Wert erneut durch `_e()` geht — typisch, wenn ein Helfer
eine fertige HTML-Zeichenkette zurückgibt und der Aufrufer sie noch einmal escapet.
Den äußeren Aufruf entfernen, nicht den inneren: der innere sitzt näher an den
Fremddaten.

- [ ] **Schritt 5: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_darstellung.py::test_kaufmaennisches_und_erscheint_einmal_escapet`
Erwartet: PASS

Dann die Rückversicherung, dass nichts anderes brach:

Run: `PYTEST tests/test_ui.py`
Erwartet: PASS (unverändert zur Ausgangslage)

- [ ] **Schritt 6: Bestandsdaten bereinigen — nur falls Schritt 1 `&amp;` in der Datenbank fand**

```sql
update sales.activities
   set payload = jsonb_set(payload, '{thema}',
                           to_jsonb(replace(payload->>'thema', '&amp;', '&')))
 where type = 'termin'
   and payload->>'thema' like '%&amp;%';
```

Vorher auf `sales_test` proben, vorher ein Backup ziehen (siehe
`docs/04_BACKUP_RESTORE.md`). Betrifft laut Messung vom 10.09.2026 eine Handvoll
Zeilen.

- [ ] **Schritt 7: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_darstellung.py
git commit -m "fix(ui): kaufmaennisches Und wird genau einmal escapet"
```

---

## Aufgabe 2: Umlaute in allem, was gerendert wird

Die Anzeigetexte stehen im Quelltext in ASCII-Umschreibung („aelteste", „naechsten",
„oeffnen", „Entwuerfe", „Oberflaeche", „laedt", „Aendern", „Groesse", „Loeschen"),
während direkt daneben Kundendaten mit echten Umlauten stehen („Videogespräch",
„Ena Ottenschläger"). Der Bruch ist auf jeder Seite sichtbar.

**Die Gefahr dieser Aufgabe ist ein blindes Suchen-und-Ersetzen.** In `ui.py` stehen
2.076 Vorkommen von `ae`/`oe`/`ue`/`ss`, und die meisten dürfen **nicht** angefasst
werden:

* **Bezeichner** — `_loeschantrag`, `_gesichert_seite`, `gehoert_zu`,
  `AUTONOMIE_STUFEN`. Umbenennen bricht den Code.
* **Datenbankwerte** — `bestaetigt`, `termin_abgesagt`, `rejected` sind Zustände in
  `activities.type` bzw. `drafts.status`. Wer sie im Vergleich ändert, bricht die
  Abfrage; wer sie nur in der Anzeige übersetzt, ist richtig.
* **CSS-Klassen und `data-label`** — `.badge.zustand.pending`, Klassennamen im
  `_STIL`-Block.
* **Kommentare und Docstrings** — bleiben, siehe Globale Randbedingungen.

Geändert wird ausschließlich der **Text zwischen den Tags** und Attributwerte, die
der Mensch liest (`title`, `placeholder`, `aria-label`).

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Ändern: `sales-mcp/tests/test_darstellung.py`

**Schnittstellen:**
- Verbraucht: `_get`, `_lead`, `_termin_aktivitaet` aus Aufgabe 1
- Erzeugt: `WOERTER_ASCII` (Liste geprüfter Suchbegriffe) — Aufgabe 8 nutzt sie erneut

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

An `tests/test_darstellung.py` anhängen:

```python
# Wortliste statt Regex auf `ae|oe|ue`: ein Muster wuerde bei jedem
# englischen Wort und jeder E-Mail-Adresse anschlagen. Diese Liste
# enthaelt nur Woerter, die in der laufenden Oberflaeche gemessen wurden.
WOERTER_ASCII = [
    "aelteste", "naechste", "oeffnen", "Entwuerfe", "Entwuerfen",
    "Oberflaeche", "laedt", "Aendern", "aendern", "Groesse", "Loeschen",
    "loeschen", "gehoert", "klaert", "noetig", "moeglich", "zurueck",
    "Verlaeufe", "heisst", "Eingaenge", "Faellig", "Rueckruf",
    "Begruendung", "ausdruecklich", "Schluessel",
]

SEITEN = ["/", "/freigaben", "/einordnung", "/kalender", "/kontakte",
          "/pipeline", "/ergebnisse", "/posteingang", "/medien", "/whatsapp"]


@pytest.mark.parametrize("pfad", SEITEN)
def test_seite_zeigt_echte_umlaute(pfad):
    """Keine ASCII-Umschreibung erreicht den Browser."""
    lead = _lead("Ena Ottenschläger")
    _termin_aktivitaet(lead)
    seite = _get(pfad).text
    gefunden = [w for w in WOERTER_ASCII if w in seite]
    assert not gefunden, (
        f"{pfad} zeigt ASCII-Umschreibungen: {gefunden}")
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_darstellung.py -k umlaute`
Erwartet: FAIL auf mehreren Seiten, mit der jeweiligen Wortliste im
Fehlertext. Diese Ausgabe ist die Arbeitsliste für Schritt 3.

- [ ] **Schritt 3: Anzeigetexte umstellen, Seite für Seite**

Vorgehen je Seite, in der Reihenfolge der Fehlschläge:

1. Die im Fehlertext genannten Wörter in `ui.py` suchen.
2. Je Treffer entscheiden: Anzeigetext (ändern) oder Bezeichner / DB-Wert /
   CSS-Klasse / Kommentar (**stehen lassen**).
3. Bei DB-Werten, die angezeigt werden — etwa `bestaetigt` aus
   `activities.type` — **nicht** den Wert ändern, sondern eine Übersetzung beim
   Rendern einführen:

```python
# Zustandsnamen kommen aus der Datenbank und bleiben dort, wie sie sind.
# Uebersetzt wird erst beim Anzeigen — sonst braeche jede Abfrage, die auf
# 'bestaetigt' vergleicht.
ZUSTAND_TEXT = {
    "bestaetigt": "bestätigt",
    "abgelehnt": "abgelehnt",
    "gesendet": "gesendet",
    "termin_abgesagt": "abgesagt",
    "termin_verschoben": "verschoben",
}


def _zustand_text(wert) -> str:
    return ZUSTAND_TEXT.get(str(wert or ""), str(wert or ""))
```

An den Stellen, die den Zustand ausgeben, `_e(z["status"])` durch
`_e(_zustand_text(z["status"]))` ersetzen.

4. Nach jeder Seite den Test erneut laufen lassen — die Liste wird kürzer.

- [ ] **Schritt 4: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_darstellung.py -k umlaute`
Erwartet: PASS für alle zehn Seiten

- [ ] **Schritt 5: Prüfen, dass die Kodierung stimmt**

```bash
docker run --rm --network host -e SALES_DB_SCHEMA=sales_test \
  -e SALES_DB_URL="postgresql://postgres:ci@localhost:5432/postgres" \
  sales-mcp-ci python -c "
from starlette.testclient import TestClient
import ui
r = TestClient(ui.app).get('/', headers={'host': '127.0.0.1:8791'})
print(r.headers['content-type'])
assert 'charset=utf-8' in r.headers['content-type'].lower()
print('ok')"
```

Erwartet: `text/html; charset=utf-8` und `ok`. Fehlt das Charset, ergänze es dort,
wo die `HTMLResponse` gebaut wird — sonst zeigt der Browser Kraut statt Umlauten.

- [ ] **Schritt 6: Gesamtsuite als Rückversicherung**

Run: `PYTEST tests/`
Erwartet: PASS. Schlägt etwas fehl, wurde ein DB-Wert oder Bezeichner mit umbenannt —
den Treffer zurücknehmen und stattdessen über `ZUSTAND_TEXT` übersetzen.

- [ ] **Schritt 7: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_darstellung.py
git commit -m "fix(ui): echte Umlaute in allen Anzeigetexten"
```

---

## Aufgabe 3: Kalender-Zeitzone

Derselbe Termin steht in der Kalender-Tabelle um **21:00** und in der
Vergangen-Tabelle um **19:00**. Die Ursache ist gemessen: `_zeit()` (`ui.py:310`)
rechnet nur um, wenn `dt.tzinfo` gesetzt ist —

```python
if ZEITZONE is not None and getattr(dt, "tzinfo", None) is not None:
    dt = dt.astimezone(ZEITZONE)
```

— und der Kalender speist sich aus **zwei verschiedenen Wegen**: die eigenen
Termine liegen als **Zeichenketten** `datum`/`uhrzeit` im `activities.payload`
(werden also nie umgerechnet), der CalDAV-Import liefert echte Zeitstempel
(`ui.py:3566`, `astimezone(ZEITZONE)`).

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Neu: `sales-mcp/tests/test_kalender_zeit.py`

**Schnittstellen:**
- Verbraucht: `server._q`, `ui.app`, `ui.ZEITZONE` (`ui.py:305`)
- Erzeugt: `_termin_caldav_roh()` — Aufgabe 4 nutzt es

- [ ] **Schritt 1: Messen, was CalDAV tatsächlich liefert**

Kein Code. Vor jedem Fix ist zu klären, ob `DTSTART` im VEVENT als UTC (`Z`-Suffix),
mit `TZID` oder ohne Zonenangabe („floating") kommt. Davon hängt ab, ob der
Import falsch liest oder die Anzeige falsch rechnet.

Die Lesefunktion ist `kalender.termine_lesen(tage_zurueck=7, tage_voraus=60)`
(`kalender.py:404`); sie zerlegt die VEVENTs mit `_ics_feld` und `_ics_zeit`
(`kalender.py:382`, `kalender.py:393`).

```bash
docker exec sales-mcp python -c "
import kalender, json
eintraege = kalender.termine_lesen()
print(json.dumps(eintraege[:3], default=str, indent=2, ensure_ascii=False))"
```

Zusätzlich `_ics_zeit` lesen — dort steht, wie ein `DTSTART` in ein Python-Datum
übersetzt wird, und genau dort entscheidet sich, ob eine Zone gesetzt wird:

```bash
sed -n '393,404p' sales-mcp/kalender.py
```

Ergebnis notieren — es entscheidet Schritt 4:

* **`DTSTART:20260905T170000Z`** → korrekt UTC, Anzeige rechnet richtig; der Fehler
  liegt dann bei den naiven Zeitstempeln des eigenen Stores.
* **`DTSTART;TZID=Europe/Berlin:20260905T190000`** → lokale Zeit mit Zone; wird sie
  beim Einlesen als UTC gelesen, entstehen genau die zwei Stunden Versatz.
* **`DTSTART:20260905T190000`** ohne alles → floating time; muss als Ortszeit
  gelesen werden, nicht als UTC.

- [ ] **Schritt 2: Fehlschlagenden Test schreiben**

```python
"""Vertragstests der Kalender-Zeitrechnung (Stufe 1).

Ein Termin hat EINE Uhrzeit. Dass dieselbe Buchung an zwei Stellen der
Oberflaeche zwei Uhrzeiten trug (19:00 und 21:00, gemessen 10.09.2026),
lag an zwei Wegen in dieselbe Anzeige: eigene Termine liegen als
Zeichenkette im Payload, CalDAV liefert Zeitstempel.
"""
import json
import os
from datetime import datetime, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.leads cascade")
    yield


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def test_naiver_zeitstempel_wird_als_utc_gelesen():
    """Ein Zeitstempel ohne Zone gilt als UTC und wird nach Berlin gerechnet.

    19:00 UTC sind im September 21:00 in Berlin. Vorher blieb ein naiver
    Zeitstempel ungerechnet stehen — daher zwei Uhrzeiten fuer eine Buchung.
    """
    naiv = datetime(2026, 9, 5, 19, 0, 0)
    assert ui._zeit(naiv).endswith("21:00"), (
        f"naiver Zeitstempel wurde nicht umgerechnet: {ui._zeit(naiv)}")


def test_bewusster_zeitstempel_wird_nicht_doppelt_gerechnet():
    """Ein Zeitstempel MIT Zone wird genau einmal umgerechnet."""
    bewusst = datetime(2026, 9, 5, 19, 0, 0, tzinfo=timezone.utc)
    assert ui._zeit(bewusst).endswith("21:00")
```

- [ ] **Schritt 3: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_kalender_zeit.py`
Erwartet: `test_naiver_zeitstempel_wird_als_utc_gelesen` FAIL mit `... 19:00`,
`test_bewusster_zeitstempel_wird_nicht_doppelt_gerechnet` PASS.

- [ ] **Schritt 4: `_zeit()` naive Zeitstempel als UTC lesen lassen**

In `ui.py:310` ersetzen:

```python
def _zeit(dt) -> str:
    """Zeitpunkt in Ortszeit. Ein Zeitstempel OHNE Zone gilt als UTC.

    Die Datenbank liefert durchweg `timestamptz` (db/provision.sql), also
    bewusste Zeitpunkte. Wo trotzdem ein naiver ankommt — aus einem
    JSON-Payload, aus einem Kalender-Import ohne Zonenangabe — waere die
    Alternative, ihn ungerechnet stehen zu lassen: genau das erzeugte
    dieselbe Buchung mit zwei Uhrzeiten (19:00 und 21:00, 10.09.2026).
    """
    if dt is None:
        return "—"
    if ZEITZONE is None:
        return dt.strftime("%d.%m.%Y %H:%M")
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZEITZONE).strftime("%d.%m.%Y %H:%M")
```

Dazu oben `from datetime import timezone` ergänzen (`date, datetime` stehen bereits
in der Importzeile).

**Fällt die Messung aus Schritt 1 anders aus** — CalDAV liefert `TZID` oder floating
time und wird beim Einlesen falsch interpretiert — gehört der Fix zusätzlich in
`kalender.py` an die Einlesestelle: dort die Zone aus `TZID` übernehmen bzw. floating
time als Ortszeit lesen. Der Test oben bleibt in beiden Fällen gültig.

- [ ] **Schritt 5: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_kalender_zeit.py`
Erwartet: beide PASS

Run: `PYTEST tests/test_termin.py tests/test_ui.py`
Erwartet: PASS

- [ ] **Schritt 6: Am laufenden System nachsehen**

`/kalender` im Browser öffnen. Der Termin „Video Call mit Sophie & Stephane" muss in
Monatsgitter, Kalender-Tabelle und Vergangen-Tabelle **dieselbe** Uhrzeit tragen.
Tut er das nicht, ist der Rest ein echter Quellenkonflikt und gehört in Aufgabe 4.

- [ ] **Schritt 7: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_kalender_zeit.py
git commit -m "fix(ui): naive Zeitstempel gelten als UTC — eine Buchung, eine Uhrzeit"
```

---

## Aufgabe 4: Doppelte Termine als ein Eintrag mit zwei Quellen

Betreiber-Entscheidung (Spec §3.3): **nicht** automatisch zusammenführen. Beide
Quellen sind Wahrheit; der Bot entwirrt sie später im Digest. Die Oberfläche zeigt
das Paar deshalb als **einen** Eintrag mit dem Hinweis „zwei Quellen" statt als zwei
oder vier Zeilen.

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Ändern: `sales-mcp/tests/test_kalender_zeit.py`

**Schnittstellen:**
- Verbraucht: `_zeit()` in der Fassung aus Aufgabe 3
- Erzeugt: `_termine_paaren(eigene, importierte) -> list[dict]` — jedes Element
  trägt `quellen: list[str]` mit einem oder zwei Einträgen

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

An `tests/test_kalender_zeit.py` anhängen:

```python
def test_gleicher_termin_aus_zwei_quellen_wird_ein_eintrag():
    """Eigener Store und Kalender-Import ergeben EINEN Eintrag."""
    eigene = [{"titel": "Video Call mit Sophie & Stephane",
               "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
               "ort": "Video Call", "quelle": "store"}]
    importierte = [{"titel": "Video Call mit Sophie & Stephane",
                    "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
                    "ort": "https://meet.google.com/tin-jrqe-qwx",
                    "quelle": "caldav"}]
    paare = ui._termine_paaren(eigene, importierte)
    assert len(paare) == 1, f"erwartet 1 Eintrag, bekam {len(paare)}"
    assert sorted(paare[0]["quellen"]) == ["caldav", "store"]


def test_verschiedene_termine_bleiben_getrennt():
    """Unterschiedliche Startzeiten werden NICHT zusammengezogen."""
    eigene = [{"titel": "Erstgespräch",
               "beginn": datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc),
               "ort": "", "quelle": "store"}]
    importierte = [{"titel": "Erstgespräch",
                    "beginn": datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc),
                    "ort": "", "quelle": "caldav"}]
    assert len(ui._termine_paaren(eigene, importierte)) == 2


def test_zwei_quellen_werden_in_der_seite_ausgewiesen():
    """Der Hinweis steht sichtbar am Eintrag, nicht nur in den Daten."""
    lead = server._q(
        "insert into leads (name, phone, source) values "
        "('Stephane B.', '+491701234567', 'whatsapp') returning id")[0]["id"]
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s::jsonb)",
        (lead, json.dumps(
            {"datum": "2026-09-05", "uhrzeit": "21:00",
             "thema": "Video Call mit Sophie & Stephane",
             "ort": "Video Call", "uid": "doppelt-1"})))
    seite = _get("/kalender").text
    assert seite.count("Video Call mit Sophie &amp; Stephane") <= 2, (
        "derselbe Termin steht mehr als zweimal auf der Seite "
        "(Gitter + Liste sind erlaubt)")
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_kalender_zeit.py -k quellen`
Erwartet: FAIL mit `AttributeError: module 'ui' has no attribute '_termine_paaren'`

- [ ] **Schritt 3: `_termine_paaren` schreiben**

```python
# Toleranz beim Paaren: dieselbe Buchung kann in zwei Quellen um ein paar
# Minuten auseinanderliegen (Rundung beim Import). Fuenf Minuten sind eng
# genug, dass zwei ECHTE Termine nicht verschmelzen — der Betreiber hat
# ausdruecklich entschieden, dass beide Quellen Wahrheit bleiben und
# Zweifelsfaelle im Digest geklaert werden, nicht hier.
PAAR_TOLERANZ_MIN = 5


def _termine_paaren(eigene, importierte):
    """Termine aus beiden Quellen zu einer Liste verschmelzen.

    Verschmolzen wird NICHT der Inhalt: jeder Eintrag behaelt beide
    Ortsangaben und nennt seine Quellen. Die Entscheidung, welche Fassung
    stimmt, trifft der Betreiber im Digest.
    """
    ergebnis = []
    for eintrag in list(eigene) + list(importierte):
        for vorhanden in ergebnis:
            if _gleicher_termin(vorhanden, eintrag):
                vorhanden["quellen"].append(eintrag.get("quelle", "?"))
                for feld in ("ort", "titel"):
                    if not vorhanden.get(feld) and eintrag.get(feld):
                        vorhanden[feld] = eintrag[feld]
                    elif (eintrag.get(feld)
                          and eintrag[feld] != vorhanden.get(feld)):
                        vorhanden.setdefault("abweichend", {})[feld] = \
                            eintrag[feld]
                break
        else:
            neu = dict(eintrag)
            neu["quellen"] = [eintrag.get("quelle", "?")]
            ergebnis.append(neu)
    return ergebnis


def _gleicher_termin(a, b) -> bool:
    """Gleicher Kontakt, gleiche Startzeit (+/- Toleranz), aehnlicher Titel."""
    if a.get("lead_id") and b.get("lead_id") and a["lead_id"] != b["lead_id"]:
        return False
    beginn_a, beginn_b = a.get("beginn"), b.get("beginn")
    if beginn_a is None or beginn_b is None:
        return False
    abstand = abs((beginn_a - beginn_b).total_seconds())
    if abstand > PAAR_TOLERANZ_MIN * 60:
        return False
    titel_a = str(a.get("titel") or "").strip().lower()
    titel_b = str(b.get("titel") or "").strip().lower()
    return (titel_a == titel_b
            or titel_a.startswith(titel_b[:20])
            or titel_b.startswith(titel_a[:20]))
```

- [ ] **Schritt 4: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_kalender_zeit.py -k quellen`
Erwartet: die ersten beiden PASS, `test_zwei_quellen_werden_in_der_seite_ausgewiesen`
noch FAIL (die Seite nutzt die Funktion noch nicht).

- [ ] **Schritt 5: Die Kalenderseite die Funktion nutzen lassen**

**Achtung, die beiden Quellen haben heute verschiedene Formen.** `_termine_paaren`
erwartet je Eintrag ein `beginn` als `datetime`; die eigenen Termine liegen aber als
**Zeichenketten** `datum` (`"2026-09-05"`) und `uhrzeit` (`"19:00"`) im
`activities.payload` (`ui.py:3376`–`3380`), die CalDAV-Einträge als echte
Zeitstempel. Vor dem Paaren müssen beide in dieselbe Form gebracht werden:

```python
def _beginn_aus_payload(payload):
    """`datum`+`uhrzeit` aus dem Payload zu einem bewussten Zeitpunkt.

    Die Strings im Payload sind ORTSZEIT — so hat der Betreiber sie
    diktiert und so stehen sie in der .ics. Sie als UTC zu lesen waere
    derselbe Zwei-Stunden-Fehler noch einmal, nur an anderer Stelle.
    """
    tag = str((payload or {}).get("datum") or "")
    zeit = str((payload or {}).get("uhrzeit") or "")
    if not tag:
        return None
    try:
        roh = datetime.fromisoformat(f"{tag}T{zeit or '00:00'}")
    except ValueError:
        return None
    return roh.replace(tzinfo=ZEITZONE) if ZEITZONE else roh
```

Dann beide Quellen in Listen von Wörterbüchern mit den Schlüsseln `titel`, `beginn`,
`ort`, `quelle`, `lead_id` überführen und durch `_termine_paaren` schicken, bevor sie
in `kommend`/`vergangen` einsortiert werden.

Am Eintrag den Hinweis ausgeben, wenn mehr als eine Quelle beteiligt ist:

```python
quellen_marke = (
    '<span class="badge achtung" title="Dieser Termin steht in zwei '
    'Quellen — der Assistent klärt im Digest, welche Fassung stimmt.">'
    'zwei Quellen</span> '
    if len(eintrag.get("quellen", [])) > 1 else "")
```

Weicht eine Ortsangabe ab (`eintrag["abweichend"]["ort"]`), beide zeigen — durch
„ / " getrennt, beide durch `_e()`.

- [ ] **Schritt 6: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_kalender_zeit.py`
Erwartet: alle PASS

Run: `PYTEST tests/`
Erwartet: PASS

- [ ] **Schritt 7: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_kalender_zeit.py
git commit -m "feat(ui): doppelte Termine als ein Eintrag mit zwei Quellen"
```

---

## Aufgabe 5: Kontaktzahlen benennen, was sie zählen

Gemessen: die WhatsApp-Seite zählt `select count(*) n from leads` (`ui.py:3139`) —
alle Leads einschließlich der archivierten, also 469. Die Kontaktliste filtert
Archivierte heraus (`ui.py:2429`) und zeigt 461. Beide Zahlen stimmen; falsch ist,
dass beide „Kontakte" heißen.

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Ändern: `sales-mcp/tests/test_darstellung.py`

**Schnittstellen:**
- Verbraucht: `_get`, `_lead` aus Aufgabe 1

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_whatsapp_seite_nennt_aktive_und_archivierte_getrennt():
    """Zwei Zahlen, zwei Namen — nicht zweimal 'Kontakte'."""
    _lead("Aktiv Eins")
    archiv = _lead("Archiviert Eins")
    server._q(
        "update leads set enrichment = "
        "coalesce(enrichment, '{}'::jsonb) || '{\"archiviert\": true}'::jsonb "
        "where id = %s", (archiv,))
    seite = _get("/whatsapp").text
    assert "1 aktive Kontakte" in seite or "1 aktiver Kontakt" in seite, (
        "die WhatsApp-Seite benennt die aktiven Kontakte nicht")
    assert "1 archiviert" in seite, (
        "die archivierten Kontakte werden nicht getrennt ausgewiesen")
```

Die gültige Archivregel steht in `server._archiv_sql(spalte)` (`server.py:868`) —
sie enthält bewusst eine `jsonb_typeof`-Prüfung, damit die Zeichenkette `"true"`
**nicht** als archiviert zählt. Der Test muss deshalb einen echten booleschen Wert
schreiben (`'{"archiviert": true}'::jsonb`, wie oben), sonst prüft er am Merkmal
vorbei. Weicht der Schlüsselname ab, ihn aus dieser Funktion übernehmen und nichts
nachbauen.

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_darstellung.py -k whatsapp_seite_nennt`
Erwartet: FAIL — die Seite zeigt heute „2 Kontakte"

- [ ] **Schritt 3: Die Zählung aufteilen**

In `ui.py:3139` die eine Abfrage durch zwei ersetzen, mit derselben Archivregel wie
die Kontaktliste:

```python
# Zwei Zahlen statt einer: `count(*) from leads` zaehlte auch die
# archivierten mit und hiess trotzdem "Kontakte" — dieselbe Bezeichnung
# wie in der Navigation, die nur die aktiven zaehlt (gemessen 10.09.2026:
# 469 gegen 461, Differenz genau die acht archivierten).
aktive = server._q(
    "select count(*) n from leads l "
    "where not " + server._archiv_sql("l.enrichment"))[0]["n"]
archivierte = server._q(
    "select count(*) n from leads l "
    "where " + server._archiv_sql("l.enrichment"))[0]["n"]
```

Und in der Stationenliste:

```python
("Datenbank", "gut",
 f"{aktive} aktive Kontakte, {archivierte} archiviert, "
 f"{anzahl} Kundenantworten"),
```

- [ ] **Schritt 4: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_darstellung.py -k whatsapp_seite_nennt`
Erwartet: PASS

Run: `PYTEST tests/test_monitoring.py`
Erwartet: PASS

- [ ] **Schritt 5: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_darstellung.py
git commit -m "fix(ui): aktive und archivierte Kontakte getrennt ausweisen"
```

---

## Aufgabe 6: Doppelte Überschrift und fehlendes Favicon

Zwei kleine, unabhängig prüfbare Fehler in einer Aufgabe, weil beide dieselbe
Testdatei und denselben Commit tragen.

`/pipeline` gibt zweimal `<h1>Pipeline</h1>` aus. `/favicon.ico` antwortet bei jedem
Seitenaufruf mit 404 (im Browser-Protokoll sichtbar).

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Ändern: `sales-mcp/tests/test_darstellung.py`

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
def test_pipeline_hat_genau_eine_ueberschrift():
    seite = _get("/pipeline").text
    assert seite.count("<h1") == 1, (
        f"{seite.count('<h1')} h1-Elemente auf /pipeline, erwartet 1")


def test_favicon_wird_beantwortet():
    """Kein 404 bei jedem Seitenaufruf."""
    antwort = _get("/favicon.ico")
    assert antwort.status_code in (200, 204), (
        f"/favicon.ico antwortet mit {antwort.status_code}")
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_darstellung.py -k "ueberschrift or favicon"`
Erwartet: beide FAIL (2 h1-Elemente, 404)

- [ ] **Schritt 3: Die doppelte Überschrift entfernen**

In der `pipeline`-Funktion (`ui.py:3302` ff.): `_seite()` setzt die `<h1>` bereits
aus dem Titel. Die zusätzliche `<h1>` im Rumpf ersatzlos streichen.

- [ ] **Schritt 4: Favicon beantworten**

Ein eingebettetes SVG, damit keine Datei ausgeliefert und keine CSP-Regel gelockert
werden muss:

```python
# Ein Buchstabe als SVG statt einer .ico-Datei: kein zusaetzlicher
# Mount, keine CSP-Lockerung, und das 404 bei jedem Seitenaufruf ist weg.
_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="6" fill="#1f7a4d"/>'
    '<text x="16" y="23" font-size="20" font-family="sans-serif" '
    'font-weight="700" fill="#ffffff" text-anchor="middle">S</text></svg>')


async def favicon(request):
    return Response(_FAVICON, media_type="image/svg+xml",
                    headers={"cache-control": "public, max-age=86400"})
```

Route ergänzen, **vor** allen Platzhalter-Routen:

```python
Route("/favicon.ico", favicon),
```

`Response` aus `starlette.responses` importieren, falls dort noch nicht vorhanden.

- [ ] **Schritt 5: Tests laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_darstellung.py -k "ueberschrift or favicon"`
Erwartet: beide PASS

Run: `PYTEST tests/test_pipeline.py`
Erwartet: PASS

- [ ] **Schritt 6: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_darstellung.py
git commit -m "fix(ui): eine Ueberschrift auf /pipeline, Favicon statt 404"
```

---

## Aufgabe 7: Texte an Wortgrenzen kürzen

Karten- und Verlaufstexte brechen hart bei etwa 90 Zeichen mitten im Wort ab:
„… Thema Vibe ·", „… — Rü ·", „Kennenlernen Förderini". Der Leser sieht nicht, dass
etwas fehlt, und kann den Rest nirgends abrufen.

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Ändern: `sales-mcp/tests/test_darstellung.py`

**Schnittstellen:**
- Erzeugt: `_kurz(text, laenge=90) -> str` — liefert den gekürzten Text mit `…`;
  Aufrufer setzt den vollen Text als `title`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_kuerzung_bricht_nicht_mitten_im_wort():
    lang = ("Martin bestätigt per WhatsApp Interesse und Termin Donnerstag "
            "14 Uhr; der Betreiber trägt 14:30 im Kalender ein")
    kurz = ui._kurz(lang, 60)
    assert kurz.endswith("…"), "gekuerzter Text sagt nicht, dass er gekuerzt ist"
    assert len(kurz) <= 61, f"zu lang: {len(kurz)}"
    rumpf = kurz[:-1].rstrip()
    assert lang.startswith(rumpf), "der Anfang stimmt nicht mehr"
    assert not rumpf or lang[len(rumpf):len(rumpf) + 1] in ("", " "), (
        f"mitten im Wort abgeschnitten: …{rumpf[-15:]}")


def test_kurzer_text_bleibt_unveraendert():
    assert ui._kurz("Optimal", 60) == "Optimal"
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_darstellung.py -k kuerzung`
Erwartet: FAIL mit `AttributeError: module 'ui' has no attribute '_kurz'`

- [ ] **Schritt 3: `_kurz` schreiben**

```python
def _kurz(text, laenge=90) -> str:
    """Text auf `laenge` kuerzen, aber nur an einer Wortgrenze.

    Vorher schnitt die Anzeige hart nach n Zeichen ab; auf der Startseite
    endete ein Termin mit „Thema Vibe ·" und niemand sah, dass ein Satz
    fehlte. Der volle Text gehoert vom Aufrufer als `title` mitgegeben.
    """
    text = str(text or "").strip()
    if len(text) <= laenge:
        return text
    schnitt = text[:laenge]
    leer = schnitt.rfind(" ")
    # Nur an der Wortgrenze schneiden, wenn dabei nicht mehr als ein
    # Drittel verloren geht — bei einer langen URL ohne Leerzeichen ist
    # der harte Schnitt das kleinere Uebel.
    if leer > laenge // 3 * 2:
        schnitt = schnitt[:leer]
    return schnitt.rstrip(" ,;:·-–—") + "…"
```

- [ ] **Schritt 4: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_darstellung.py -k kuerzung`
Erwartet: beide PASS

- [ ] **Schritt 5: Die Schnittstellen umstellen**

Jede Stelle suchen, die per Scheibe kürzt (`[:160]`, `[:90]`, `[:80]` an
Anzeigetexten — etwa `ui.py:3394` im Kalender) und ersetzen. Muster:

```python
voll = str(last.get("inhalt") or last.get("thema") or "")
zelle = f'<span title="{_e(voll)}">{_e(_kurz(voll, 160))}</span>'
```

Der volle Text steht damit im `title` — escapet mit `quote=True`, wie `_e` es tut.

Betrifft: Terminkarten auf `/` und `/kalender`, Verlaufszeilen auf `/freigaben`,
Nachrichtenvorschau auf `/posteingang`, Titel im Monatsgitter.

- [ ] **Schritt 6: Gesamtsuite**

Run: `PYTEST tests/`
Erwartet: PASS

- [ ] **Schritt 7: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_darstellung.py
git commit -m "fix(ui): Texte an Wortgrenzen kuerzen, voller Text im title"
```

---

## Aufgabe 8: „Heute" zählt ehrlich

Gemessen am 10.09.2026: die Kopfzeile sagt „1 Entscheidung wartet auf dich. Alles
andere laeuft." Tatsächlich standen darunter zwei Termine ohne Datum, eine offene
Einordnung und zwölf unbeantwortete Nachrichten. Zusätzlich zeigten die Chips
„Termine 2", während direkt darunter „Keine offenen Entwuerfe" stand.

Diese Aufgabe korrigiert **nur die Zählung**. Dass „Termine ohne festes Datum" ganz
verschwindet, gehört zu Stufe 2 (Spec §4.1) — bis dahin muss die Zahl wenigstens
stimmen.

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Ändern: `sales-mcp/tests/test_darstellung.py`

**Der Fehler ist eine fehlende Zeile, keine fehlende Funktion.** In `ui.py:4791`
steht bereits:

```python
offen = len(pending) + len(wiedervorlagen) + einordnung_offen
```

`termine_offen` (`ui.py:4781`) wird eine Zeile davor geholt, in der Anzeige verwendet
— und in der Summe **vergessen**. Das erklärt den gemessenen Zustand exakt: 0 Entwürfe
+ 0 Wiedervorlagen + 1 Einordnung = 1, während zwei Terminanfragen danebenstanden.

Es wird deshalb **keine neue Abfrage gebaut**. Alle Zahlen liegen bereits vor.

**Schnittstellen:**
- Verbraucht: `_get`, `_lead`, `_termin_aktivitaet` aus Aufgabe 1; die lokalen
  Variablen `pending`, `wiedervorlagen`, `einordnung_offen`, `termine_offen` in
  `heute` (`ui.py:4772`–`4791`)
- Erzeugt: nichts Neues nach außen

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_heute_zaehlt_terminanfragen_mit():
    """Eine Terminanfrage ohne Datum zaehlt als offener Posten.

    Gemessen 10.09.2026: die Kopfzeile sagte „1 Entscheidung wartet auf
    dich. Alles andere laeuft.", waehrend darunter ZWEI Terminanfragen
    ohne Datum standen — `termine_offen` fehlte in der Summe.
    """
    lead = _lead("Offen Eins")
    _termin_aktivitaet(lead, datum="", uhrzeit="",
                       thema="Donnerstag 16 Uhr — welcher?")
    _termin_aktivitaet(lead, datum="", uhrzeit="",
                       thema="Freitag vormittags?")
    seite = _get("/").text
    assert "1 Entscheidung" not in seite, (
        "zwei Terminanfragen wurden als eine gezaehlt")
    assert "2 " in seite, "die Kopfzeile nennt die zwei Anfragen nicht"


def test_heute_behauptet_keine_ruhe_wenn_etwas_offen_ist():
    """„Alles andere laeuft" darf nicht neben offenen Posten stehen."""
    lead = _lead("Offen Zwei")
    _termin_aktivitaet(lead, datum="", uhrzeit="", thema="Wann genau?")
    seite = _get("/").text
    assert "Alles andere läuft" not in seite and "Alles andere laeuft" not in seite


def test_heute_meldet_ruhe_bei_leerer_datenbank():
    seite = _get("/").text
    assert "Nichts wartet auf dich" in seite
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_darstellung.py -k heute`
Erwartet: `test_heute_zaehlt_terminanfragen_mit` FAIL (die Seite zeigt „1 Entscheidung"),
`test_heute_behauptet_keine_ruhe_wenn_etwas_offen_ist` FAIL,
`test_heute_meldet_ruhe_bei_leerer_datenbank` PASS.

- [ ] **Schritt 3: Die fehlende Zahl in die Summe nehmen**

In `ui.py:4791` ersetzen:

```python
    # `termine_offen` gehoert in die Summe: es stand eine Zeile weiter
    # oben schon bereit und wurde nur in der Anzeige benutzt. Dadurch
    # meldete die Kopfzeile „1 Entscheidung … Alles andere laeuft",
    # waehrend zwei Terminanfragen ohne Datum darunter standen
    # (gemessen 10.09.2026).
    posten = []
    if pending:
        posten.append(f"{len(pending)} Entwurf" if len(pending) == 1
                      else f"{len(pending)} Entwürfe")
    if einordnung_offen:
        posten.append(f"{einordnung_offen} Einordnung" if einordnung_offen == 1
                      else f"{einordnung_offen} Einordnungen")
    if termine_offen:
        posten.append(f"{len(termine_offen)} Terminanfrage"
                      if len(termine_offen) == 1
                      else f"{len(termine_offen)} Terminanfragen")
    if wiedervorlagen:
        posten.append(f"{len(wiedervorlagen)} Wiedervorlage"
                      if len(wiedervorlagen) == 1
                      else f"{len(wiedervorlagen)} Wiedervorlagen")
    offen = (len(pending) + len(wiedervorlagen) + einordnung_offen
             + len(termine_offen))
    satz = ("Nichts wartet auf dich. Alles läuft." if not offen else
            f"{offen} Posten warten auf dich: {', '.join(posten)}."
            if offen > 1 else f"{posten[0]} wartet auf dich.")
```

Der Halbsatz „Alles andere läuft" entfällt ersatzlos — er war genau die Behauptung,
die die Seite darunter widerlegte.

- [ ] **Schritt 4: Die Chips aus denselben Zahlen speisen**

Die Kanal-Chips („WhatsApp 0", „LinkedIn 0", „E-Mail 0", „Termine 2") und der Satz
„Keine offenen Entwürfe" stammen aus getrennten Rechnungen und widersprachen sich
deshalb. Beide aus `pending` und `termine_offen` speisen: steht dort etwas, darf
„Keine offenen Entwürfe" nicht erscheinen — und umgekehrt.

- [ ] **Schritt 5: Tests laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_darstellung.py -k heute`
Erwartet: beide PASS

Run: `PYTEST tests/test_heute.py tests/`
Erwartet: PASS

- [ ] **Schritt 6: Am laufenden System nachsehen**

`/` im Browser öffnen. Die Zahl in der Kopfzeile muss zu dem passen, was darunter
steht — und zu den Zahlen in der Navigation.

- [ ] **Schritt 7: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_darstellung.py
git commit -m "fix(ui): Heute zaehlt alle offenen Posten, nicht nur die Entwuerfe"
```

---

## Abschluss der Stufe

- [ ] **Gesamtsuite grün**

Run: `PYTEST tests/`
Erwartet: PASS. Die Zahl der Tests muss **über** dem Ausgangswert liegen (die neuen
Dateien kommen hinzu); eine gesunkene Zahl bedeutet, dass eine Testdatei nicht mehr
eingesammelt wird.

- [ ] **Durchgang am laufenden System**

Alle zwölf Seiten im Browser öffnen und prüfen:

| Prüfung | Erwartung |
|---|---|
| Umlaute | keine ASCII-Umschreibung mehr sichtbar |
| `&` in Titeln | erscheint als `&`, nicht als `&amp;` |
| Termin „Video Call …" | überall dieselbe Uhrzeit, als ein Eintrag mit „zwei Quellen" |
| WhatsApp-Seite | „aktive Kontakte" und „archiviert" getrennt benannt |
| `/pipeline` | eine Überschrift |
| Browser-Protokoll | kein 404 auf `/favicon.ico` |
| Kartentexte | enden mit `…`, voller Text im Tooltip |
| Startseite | Kopfzahl passt zum Inhalt darunter |

- [ ] **Stand im WORKBOARD nachtragen**

Den Claim `cc-sales-ui-umbau` um das Ergebnis der Stufe ergänzen (Commit-Referenzen,
was gemessen wurde) und committen.
