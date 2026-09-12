# Kalenderquellen und Team-Sicht — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Kollege verbindet seinen Kalender über einen Link im Tailnet selbst, seine Termine erscheinen benannt in der Oberfläche, und kein Terminvorschlag kollidiert mehr mit ihm oder dem Betreiber.

**Architecture:** Fremde Kalender kommen als abonnierte ICS-Adressen herein (§2.1 Weg 3) — keine Zugangsdaten, kein CalDAV-Handschlag. Ein neues, datenbankfreies Modul `kalenderquellen.py` holt und zerlegt sie mit den Zerlegern, die `kalender.py` bereits hat; die Datenbankzugriffe liegen wie beim Vorbild `medien.py`/`server.medien_meta_*` in `server.py`. Darauf setzt eine gemeinsame Belegungsliste über **alle** Quellen, aus der die Kollisionsprüfung und die Team-Sicht gespeist werden.

**Tech Stack:** Python 3.12 (Container), Starlette (serverseitig gerendertes HTML, **kein JavaScript**), psycopg, PostgreSQL, `urllib.request`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-team-terminabstimmung-design.md` (Revision 12.09.2026)

## Global Constraints

- **Kein JavaScript, keine CSP-Änderung.** Die Oberfläche ist bewusst skriptfrei; die CSP lautet `default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; media-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`.
- **Fremddaten durch `_e()`** — im Text **und** in Attributwerten.
- **Echte Umlaute in allen Anzeigetexten.** Ein Wächter-Test in `test_darstellung.py` prüft die Zeichenketten in `ui.py`.
- **Die geheime Kalenderadresse ist ein Geheimnis** (Spec §4): nie ins Log, nie in eine Fehlermeldung, nie in die Oberfläche — auch nicht für den Betreiber.
- **Das Freigabe-Gate bleibt unangetastet.** Dieses Vorhaben liest nur; es erzeugt keinen Entwurf und versendet nichts.
- **Nur lesend nach außen.** In fremde Kalender wird nie geschrieben.
- **Tests laufen gegen `SALES_DB_SCHEMA=sales_test`**, ausschließlich im Container.
- **Ein eigener User-Agent ist Betriebsvoraussetzung** (WAF-Kante, `kalender.CALDAV_USER_AGENT`) — jede ausgehende HTTP-Anfrage setzt ihn.

## Testumgebung

```bash
docker build -t sales-mcp-ci ./sales-mcp
docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test \
  -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/ -q --tb=short -p no:cacheprovider
```

Ausgangswert: **1734 Tests grün.** Nach jeder Änderung unter `sales-mcp/` das Image neu bauen. Bei Docker-Problemen **BLOCKED melden, nichts selbst reparieren.**

Die Compose-Wächter (`scripts/tests/test_proxmox_compose.py`) brauchen `git` und laufen deshalb **auf dem Host**, nicht im Container — und sie lesen `git show HEAD:`, prüfen also nur **committeten** Stand.

## Zwei Befunde, die den Plan prägen

**Es gibt heute keine Überlappungsprüfung.** `server.py` ruft `kalender.termine_lesen` an keiner Stelle auf; die einzigen beiden Aufrufer sind Anzeigestellen in `ui.py` (Zeilen 3632 und 5119). Die Spec spricht in §2.2 vom „Erweitern" der Doppelbelegungs-Erkennung — es gibt keine, sie wird hier gebaut.

**`termine_lesen` kennt kein Ende.** Es liefert `{"beginn", "titel", "ort", "uid"}`. `DTEND` wird von `kalender.ics()` geschrieben, aber nirgends im Baum gelesen. Ohne Endzeit ist keine Überlappung berechenbar — Aufgabe 3 holt das nach.

---

### Task 1: Tabelle `kalender_quellen` und ihre Datenbankzugriffe

**Files:**
- Modify: `db/provision.sql` (im `foreach s in array array['sales','sales_test']`-Block, hinter der Tabelle `medien_meta`)
- Modify: `sales-mcp/server.py` (neue Funktionen hinter `medien_meta_setzen`)
- Test: `sales-mcp/tests/test_kalenderquellen_db.py` (neu)

**Interfaces:**
- Produces:
  - `server.kalenderquellen_lesen(nur_aktive: bool = True) -> list[dict]` — Felder `id` (str), `anzeigename`, `art`, `url`, `aktiv`, `zuletzt_gelesen`, `letzter_fehler`, `termine_zuletzt`
  - `server.kalenderquelle_speichern(anzeigename: str, url: str) -> str` (gibt die `id` zurück; bei gleichem `anzeigename` wird die vorhandene Zeile ersetzt)
  - `server.kalenderquelle_stand_setzen(quelle_id: str, anzahl: int | None, fehler: str | None) -> None`
  - `server.kalenderquelle_entfernen(quelle_id: str) -> bool`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`sales-mcp/tests/test_kalenderquellen_db.py`:

```python
"""Die Liste der abonnierten Fremdkalender — Spec 2026-09-11 §2.1 Weg 3."""
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


def test_quelle_anlegen_und_lesen():
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    quellen = server.kalenderquellen_lesen()
    assert len(quellen) == 1, quellen
    assert quellen[0]["anzeigename"] == "Ivan"
    assert quellen[0]["url"] == "https://example.test/a.ics"
    assert quellen[0]["art"] == "ics"
    assert quellen[0]["aktiv"] is True


def test_gleicher_name_ersetzt_statt_zu_verdoppeln():
    """Verbindet ein Kollege seinen Kalender ein zweites Mal — weil er die
    Adresse zurueckgesetzt hat —, soll die alte, tote Adresse verschwinden
    und nicht daneben stehenbleiben und stuendlich Fehler produzieren."""
    server.kalenderquelle_speichern("Ivan", "https://example.test/alt.ics")
    server.kalenderquelle_speichern("Ivan", "https://example.test/neu.ics")
    quellen = server.kalenderquellen_lesen()
    assert len(quellen) == 1, quellen
    assert quellen[0]["url"] == "https://example.test/neu.ics"


def test_stand_wird_festgehalten():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 14
    assert q["letzter_fehler"] is None
    assert q["zuletzt_gelesen"] is not None


def test_fehler_loescht_den_alten_zaehler_nicht():
    """Ein einzelner Abrufausfall darf die letzte bekannte Zahl nicht
    wegwischen — sonst sieht die Seite aus, als sei nie etwas angekommen."""
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    server.kalenderquelle_stand_setzen(qid, 14, None)
    server.kalenderquelle_stand_setzen(qid, None, "Zeitgrenze")
    q = server.kalenderquellen_lesen()[0]
    assert q["termine_zuletzt"] == 14
    assert q["letzter_fehler"] == "Zeitgrenze"


def test_entfernen():
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    assert server.kalenderquelle_entfernen(qid) is True
    assert server.kalenderquellen_lesen() == []
    assert server.kalenderquelle_entfernen(qid) is False
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag prüfen**

```bash
docker build -q -t sales-mcp-ci ./sales-mcp && docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/test_kalenderquellen_db.py -q --tb=short -p no:cacheprovider
```

Erwartet: FEHLSCHLAG — `relation "sales_test.kalender_quellen" does not exist`.

- [ ] **Step 3: Tabelle in `db/provision.sql` ergänzen**

Direkt hinter dem `create table ... medien_meta`-Block, **innerhalb** derselben `foreach s`-Schleife:

```sql
    -- Abonnierte Fremdkalender (Spec 2026-09-11 §2.1 Weg 3, ergaenzt
    -- 12.09.2026). `url` ist die GEHEIME iCal-Adresse eines Kollegen und
    -- damit ein Geheimnis mit der Berechtigung darin: wer sie kennt, liest
    -- den Kalender. Sie wird nie angezeigt und nie geloggt (Spec §4).
    -- `art` ist heute nur 'ics'; der eigene CalDAV-Kalender bleibt in der
    -- .env, weil er Zugangsdaten braucht und genau einer ist.
    execute format($ddl$
      create table if not exists %I.kalender_quellen (
        id uuid primary key default gen_random_uuid(),
        anzeigename text not null check (anzeigename <> ''),
        art text not null default 'ics' check (art in ('ics')),
        url text not null check (url <> ''),
        aktiv boolean not null default true,
        zuletzt_gelesen timestamptz,
        letzter_fehler text,
        termine_zuletzt int,
        created_at timestamptz not null default now()
      )$ddl$, s);
    execute format('create unique index if not exists '
                   'kalender_quellen_name_idx on %I.kalender_quellen '
                   '(anzeigename)', s);
```

- [ ] **Step 4: Schema auf die Testdatenbank anwenden**

`provision.sql` läuft **nicht** automatisch. Auf die Testdatenbank anwenden:

```bash
docker exec -i sales-testdb psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "create table if not exists sales_test.kalender_quellen (id uuid primary key default gen_random_uuid(), anzeigename text not null check (anzeigename <> ''), art text not null default 'ics' check (art in ('ics')), url text not null check (url <> ''), aktiv boolean not null default true, zuletzt_gelesen timestamptz, letzter_fehler text, termine_zuletzt int, created_at timestamptz not null default now()); create unique index if not exists kalender_quellen_name_idx on sales_test.kalender_quellen (anzeigename);"
```

**In den Bericht schreiben:** dass dieselbe Anweisung vor der Inbetriebnahme auch auf `sales` laufen muss. Das ist ein Betreiber-Schritt, kein Codeschritt.

- [ ] **Step 5: Die Datenbankzugriffe in `server.py` ergänzen**

Hinter `medien_meta_setzen`. **Kein `@_werkzeug`-Dekorator** — das sind interne Helfer, keine Werkzeuge für das Sprachmodell:

```python
def kalenderquellen_lesen(nur_aktive: bool = True) -> list:
    """Die abonnierten Fremdkalender. Enthaelt die GEHEIME Adresse — der
    Aufrufer darf sie benutzen, aber niemals anzeigen oder loggen."""
    bedingung = "where aktiv" if nur_aktive else ""
    return [dict(z, id=str(z["id"])) for z in _q(
        f"select id, anzeigename, art, url, aktiv, zuletzt_gelesen, "
        f"letzter_fehler, termine_zuletzt from kalender_quellen "
        f"{bedingung} order by anzeigename")]


def kalenderquelle_speichern(anzeigename: str, url: str) -> str:
    """Anlegen oder die Adresse eines bekannten Namens ersetzen.

    Ersetzen statt danebenlegen: setzt ein Kollege seine Adresse zurueck
    und verbindet neu, wuerde die alte sonst stuendlich Fehler erzeugen und
    niemand wuesste, welche der beiden gilt.
    """
    return str(_q(
        "insert into kalender_quellen (anzeigename, url) values (%s, %s) "
        "on conflict (anzeigename) do update set url = excluded.url, "
        "aktiv = true, letzter_fehler = null, zuletzt_gelesen = null "
        "returning id", (anzeigename.strip(), url.strip()))[0]["id"])


def kalenderquelle_stand_setzen(quelle_id: str, anzahl, fehler) -> None:
    """Nach jedem Abruf. `anzahl=None` laesst den alten Zaehler stehen —
    ein einzelner Ausfall soll die letzte bekannte Zahl nicht wegwischen."""
    _q("update kalender_quellen set zuletzt_gelesen = now(), "
       "letzter_fehler = %s, "
       "termine_zuletzt = coalesce(%s, termine_zuletzt) "
       "where id = %s", (fehler, anzahl, quelle_id))


def kalenderquelle_entfernen(quelle_id: str) -> bool:
    return bool(_q("delete from kalender_quellen where id = %s returning id",
                   (quelle_id,)))
```

- [ ] **Step 6: Tests laufen lassen**

Befehl aus Schritt 2. Erwartet: **5 passed**.

- [ ] **Step 7: Volle Suite**

Erwartet: 1734 + 5 = **1739 grün**.

- [ ] **Step 8: Commit**

```bash
git add db/provision.sql sales-mcp/server.py sales-mcp/tests/test_kalenderquellen_db.py
git commit -m "feat(kalender): Tabelle und Zugriffe fuer abonnierte Fremdkalender"
```

---

### Task 2: ICS-Adresse abholen und zerlegen

**Files:**
- Create: `sales-mcp/kalenderquellen.py`
- Test: `sales-mcp/tests/test_kalenderquellen.py` (neu)

**Interfaces:**
- Consumes: `kalender._ics_feld`, `kalender._ics_tzid`, `kalender._ics_zeit`, `kalender.CALDAV_USER_AGENT`, `kalender.TIMEOUT_S`
- Produces:
  - `kalenderquellen.hole(url: str) -> tuple[list, str | None]` — `(termine, fehler)`; `termine` = `[{"beginn": datetime, "ende": datetime, "titel": str, "ort": str, "uid": str}]`, aufsteigend
  - `kalenderquellen.MAX_BYTES` (int)
  - `kalenderquellen.ohne_adresse(text: str, url: str) -> str`

**Warum ein eigenes Modul:** `kalender.py` ist der eigene, **schreibende** CalDAV-Weg mit Zugangsdaten. Fremde Quellen sind rein lesend, ohne Anmeldung, und kommen von beliebigen Anbietern. Getrennte Module halten die beiden Wahrheiten auseinander; die Zerleger werden importiert, nicht abgeschrieben.

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`sales-mcp/tests/test_kalenderquellen.py`:

```python
"""Abonnierte Fremdkalender holen und zerlegen — ohne Netz."""
import threading
from datetime import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import kalenderquellen


_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Europe/Berlin\r\n"
    "BEGIN:DAYLIGHT\r\n"
    "TZOFFSETFROM:+0100\r\n"
    "TZOFFSETTO:+0200\r\n"
    "TZNAME:CEST\r\n"
    "DTSTART:19700329T020000\r\n"
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\n"
    "END:DAYLIGHT\r\n"
    "END:VTIMEZONE\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:zweiter@google\r\n"
    "DTSTART;TZID=Europe/Berlin:20261002T140000\r\n"
    "DTEND;TZID=Europe/Berlin:20261002T153000\r\n"
    "SUMMARY:Zweiter Termin\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:erster@google\r\n"
    "DTSTART;TZID=Europe/Berlin:20261001T090000\r\n"
    "DTEND;TZID=Europe/Berlin:20261001T100000\r\n"
    "SUMMARY:Erster Termin\r\n"
    "LOCATION:Büro\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n")


class _Stub:
    def __init__(self):
        self.status = 200
        self.rumpf = _ICS.encode("utf-8")
        self.typ = "text/calendar; charset=utf-8"
        self.kopfzeilen = []


@pytest.fixture
def server_stub():
    stub = _Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            stub.kopfzeilen.append(dict(self.headers))
            self.send_response(stub.status)
            self.send_header("Content-Type", stub.typ)
            self.send_header("Content-Length", str(len(stub.rumpf)))
            self.end_headers()
            self.wfile.write(stub.rumpf)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    stub.url = f"http://127.0.0.1:{httpd.server_address[1]}/privat.ics"
    yield stub
    httpd.shutdown()


def test_termine_werden_gelesen_und_sortiert(server_stub):
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert fehler is None, fehler
    assert [t["titel"] for t in termine] == ["Erster Termin", "Zweiter Termin"]
    assert termine[0]["ort"] == "Büro"
    assert termine[0]["uid"] == "erster@google"


def test_ende_wird_gelesen(server_stub):
    """Ohne Endzeit ist keine Ueberlappung berechenbar. DTEND wurde im Baum
    bisher NUR geschrieben, nie gelesen."""
    termine, _ = kalenderquellen.hole(server_stub.url)
    dauer = termine[0]["ende"] - termine[0]["beginn"]
    assert dauer.total_seconds() == 3600, termine[0]


def test_zeiten_sind_zonenbewusst(server_stub):
    termine, _ = kalenderquellen.hole(server_stub.url)
    assert termine[0]["beginn"].tzinfo is not None
    assert termine[0]["beginn"].astimezone(timezone.utc).hour == 7


def test_eigener_user_agent_wird_gesetzt(server_stub):
    """Betriebsvoraussetzung, nicht Kosmetik: die WAF vor dav.privateemail.com
    weist die Vorgabe-Kennung von urllib mit 403 ab (kalender.py, Messreihe
    vom 19.08.2026). Ein fremder Anbieter kann dasselbe tun."""
    kalenderquellen.hole(server_stub.url)
    assert "urllib" not in server_stub.kopfzeilen[0]["User-Agent"].lower()


def test_webseite_statt_kalender_wird_benannt(server_stub):
    """Der haeufigste Bedienfehler: die oeffentliche Adresse oder ein Link
    auf eine Webseite. Der Text muss sagen, WAS ankam — sonst sucht der
    Kollege an der falschen Stelle."""
    server_stub.rumpf = b"<!doctype html><html><body>Anmelden</body></html>"
    server_stub.typ = "text/html; charset=utf-8"
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert "Webseite" in fehler, fehler


def test_http_fehler_wird_gemeldet(server_stub):
    server_stub.status = 404
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert "404" in fehler, fehler


def test_zu_grosse_antwort_wird_abgewiesen(server_stub):
    server_stub.rumpf = b"BEGIN:VCALENDAR\r\n" + b"X" * (
        kalenderquellen.MAX_BYTES + 1)
    termine, fehler = kalenderquellen.hole(server_stub.url)
    assert termine == []
    assert "gross" in fehler.lower(), fehler


def test_nur_http_und_https():
    termine, fehler = kalenderquellen.hole("file:///etc/passwd")
    assert termine == []
    assert "http" in fehler.lower(), fehler


def test_die_adresse_steht_in_keinem_fehlertext():
    """Spec §4: die Adresse ist ein Geheimnis mit der Berechtigung darin.
    Ein Fehlertext geht in die Datenbank und auf den Bildschirm."""
    url = "https://calendar.google.com/ical/GEHEIM123/basic.ics"
    _, fehler = kalenderquellen.hole(url)
    assert fehler is not None
    assert "GEHEIM123" not in fehler, fehler


def test_ohne_adresse_filtert_auch_teile():
    url = "https://calendar.google.com/ical/GEHEIM123/basic.ics"
    text = f"Fehler beim Abruf von {url} (Zeitgrenze)"
    sauber = kalenderquellen.ohne_adresse(text, url)
    assert "GEHEIM123" not in sauber
    assert "Zeitgrenze" in sauber
```

- [ ] **Step 2: Test laufen lassen und Fehlschlag prüfen**

```bash
docker build -q -t sales-mcp-ci ./sales-mcp && docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/test_kalenderquellen.py -q --tb=short -p no:cacheprovider
```

Erwartet: FEHLSCHLAG — `ModuleNotFoundError: No module named 'kalenderquellen'`.

- [ ] **Step 3: `sales-mcp/kalenderquellen.py` schreiben**

```python
"""Abonnierte FREMDE Kalender — rein lesend, ohne Zugangsdaten.

Abgrenzung zu `kalender.py`: dort steht der EIGENE Kalender, schreibend,
mit Zugangsdaten aus der `.env`. Hier stehen die Kalender der Kollegen,
die ueber eine geheime iCal-Adresse abonniert werden (Spec
`2026-09-11-team-terminabstimmung-design.md` §2.1 Weg 3). Zwei Wege, zwei
Module — die Zerleger werden aus `kalender` IMPORTIERT, nicht abgeschrieben,
damit es nicht zwei Auffassungen davon gibt, was ein DTSTART bedeutet.

DIE ADRESSE IST EIN GEHEIMNIS. Sie traegt ihre Berechtigung in sich: wer
sie kennt, liest den Kalender vollstaendig, ohne Anmeldung. Jeder
Fehlertext laeuft deshalb durch `ohne_adresse` — dieselbe Klasse wie
`kalender._ohne_geheimnis` fuer das CalDAV-Passwort.

KEINE DATENBANK. Wie `medien.py` und `recherche.py`: das Modul ist ohne
Datenbank testbar, die Zugriffe liegen in `server.py`.
"""
import urllib.error
import urllib.parse
import urllib.request

import kalender

# 5 MB. Ein Jahreskalender mit einigen hundert Terminen liegt bei wenigen
# hundert Kilobyte; alles darueber ist entweder ein Irrtum oder ein Ziel,
# das uns vollaeuft. Gelesen wird hoechstens so viel — nicht erst geprueft,
# nachdem alles im Speicher liegt.
MAX_BYTES = 5 * 1024 * 1024

_SCHEMATA = ("http", "https")

# Wie beim CalDAV-Weg: Zeitgrenze und eigene Kennung. Ein fremder Anbieter
# darf die Vorgabe-Kennung von urllib genauso abweisen wie die WAF vor
# dav.privateemail.com es tut (Messreihe im Kopf von kalender.py).
TIMEOUT_S = kalender.TIMEOUT_S
USER_AGENT = kalender.CALDAV_USER_AGENT

FEHLER_MAXLAENGE = 300


def ohne_adresse(text: str, url: str) -> str:
    """Die Adresse aus einem Fehlertext entfernen — ganz und in Teilen.

    Ganz: manche Bibliotheken haengen die URL an ihre Meldung. In Teilen:
    der Pfad allein genuegt einem Angreifer bereits, wenn er den Host kennt.
    """
    text = (text or "").replace(url, "<Adresse>")
    zerlegt = urllib.parse.urlsplit(url)
    if zerlegt.path and len(zerlegt.path) > 1:
        text = text.replace(zerlegt.path, "<Pfad>")
    if zerlegt.query:
        text = text.replace(zerlegt.query, "<Abfrage>")
    return text[:FEHLER_MAXLAENGE]


def _sieht_aus_wie_kalender(text: str) -> bool:
    return "BEGIN:VCALENDAR" in text[:2000].upper()


def hole(url: str):
    """Eine abonnierte Adresse abrufen -> (termine, fehler).

    `termine` = [{"beginn", "ende", "titel", "ort", "uid"}], aufsteigend.
    Wirft nie: eine unerreichbare Quelle darf keine Seite und keinen
    Werkzeugaufruf kosten, sie kostet nur ihre eigenen Termine.
    """
    url = (url or "").strip()
    zerlegt = urllib.parse.urlsplit(url)
    if zerlegt.scheme not in _SCHEMATA:
        return [], ("Die Adresse muss mit http:// oder https:// beginnen — "
                    f"gefunden wurde '{zerlegt.scheme or 'nichts'}'.")
    try:
        anfrage = urllib.request.Request(
            url, method="GET", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            # Ein Byte mehr als erlaubt lesen: nur so laesst sich "zu gross"
            # von "genau an der Grenze" unterscheiden, ohne dem
            # Content-Length-Kopf zu glauben.
            roh = antwort.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        return [], ohne_adresse(
            f"Der Anbieter antwortet mit HTTP {e.code}. Stimmt die Adresse "
            f"noch, oder wurde sie zurueckgesetzt?", url)
    except Exception as e:                # noqa: BLE001 — Netz, Zeitgrenze, TLS
        return [], ohne_adresse(
            f"Die Adresse ist nicht erreichbar ({type(e).__name__}).", url)

    if len(roh) > MAX_BYTES:
        return [], (f"Die Antwort ist groesser als {MAX_BYTES // 1024 // 1024} "
                    f"MB — das ist kein Kalender, den wir laden wollen.")

    text = roh.decode("utf-8", "replace")
    if not _sieht_aus_wie_kalender(text):
        return [], ("Dort liegt kein Kalender, sondern eine Webseite. "
                    "Wahrscheinlich ist es die oeffentliche Adresse oder der "
                    "Link zum Kalender im Browser — gebraucht wird die "
                    "geheime Adresse im iCal-Format, sie endet meist auf "
                    "'.ics'.")

    termine = []
    for teil in text.split("BEGIN:VEVENT")[1:]:
        block = teil.split("END:VEVENT", 1)[0]
        beginn = kalender._ics_zeit(kalender._ics_feld(block, "DTSTART"),
                                    kalender._ics_tzid(block, "DTSTART"))
        if beginn is None:
            continue
        ende = kalender._ics_zeit(kalender._ics_feld(block, "DTEND"),
                                  kalender._ics_tzid(block, "DTEND"))
        termine.append({
            "beginn": beginn,
            # Ohne DTEND gilt der Termin als punktuell. NICHT geraten: eine
            # erfundene Dauer erzeugte Kollisionen, die es nicht gibt.
            "ende": ende if ende and ende > beginn else beginn,
            "titel": kalender._ics_feld(block, "SUMMARY")[:200],
            "ort": kalender._ics_feld(block, "LOCATION")[:120],
            "uid": kalender._ics_feld(block, "UID")[:120]})
    termine.sort(key=lambda t: t["beginn"])
    return termine, None
```

- [ ] **Step 4: Tests laufen lassen**

Befehl aus Schritt 2. Erwartet: **10 passed**.

- [ ] **Step 5: Volle Suite**

Erwartet: **1749 grün**.

- [ ] **Step 6: Commit**

```bash
git add sales-mcp/kalenderquellen.py sales-mcp/tests/test_kalenderquellen.py
git commit -m "feat(kalender): abonnierte Fremdkalender abholen und zerlegen"
```

---

### Task 3: Gemeinsame Belegungsliste über alle Quellen

**Files:**
- Modify: `sales-mcp/kalender.py` (`termine_lesen`, Endzeit ergänzen)
- Modify: `sales-mcp/server.py` (neue Funktion `belegungen`)
- Test: `sales-mcp/tests/test_belegungen.py` (neu)
- Test: `sales-mcp/tests/test_termin.py` (bestehende Erwartung an `termine_lesen` ergänzen)

**Interfaces:**
- Consumes: `kalenderquellen.hole`, `server.kalenderquellen_lesen`, `server.kalenderquelle_stand_setzen`
- Produces: `server.belegungen(tage_voraus: int = 60) -> tuple[list, list]` — `(eintraege, luecken)`; `eintraege` = `[{"beginn", "ende", "titel", "ort", "quelle"}]`, `luecken` = `[{"quelle": str, "grund": str}]`

**Wichtig:** `kalender.termine_lesen` hat heute zwei Aufrufer (`ui.py:3632`, `ui.py:5119`). Ein zusätzliches Feld `ende` bricht sie nicht — ein entferntes oder umbenanntes Feld schon. Nur **ergänzen**.

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`sales-mcp/tests/test_belegungen.py`:

```python
"""Die gemeinsame Belegung ueber alle Quellen — Spec §2.2.

Der Betreiber hat das am 12.09.2026 ausdruecklich verlangt: "dass Ivans und
meiner dann beruecksichtigt wird". Geprueft wird gegen JEDE aktive Quelle.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender  # noqa: E402
import kalenderquellen  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


@pytest.fixture(autouse=True)
def kein_eigener_kalender(monkeypatch):
    """Ohne CALDAV_* liefert termine_lesen leer — der Ausgangszustand im
    CI-Container. Tests, die den eigenen Kalender brauchen, biegen um."""
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([], None))
    yield


def _t(tag, stunde):
    return datetime(2026, 10, tag, stunde, tzinfo=timezone.utc)


def test_fremde_quelle_erscheint_mit_namen(monkeypatch):
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([
        {"beginn": _t(1, 9), "ende": _t(1, 10), "titel": "Kundentermin",
         "ort": "", "uid": "x"}], None))
    eintraege, luecken = server.belegungen()
    assert luecken == []
    assert len(eintraege) == 1
    assert eintraege[0]["quelle"] == "Ivan"
    assert eintraege[0]["titel"] == "Kundentermin"


def test_eigener_und_fremder_kalender_zusammen(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([
        {"beginn": _t(1, 14), "ende": _t(1, 15), "titel": "Eigener",
         "ort": "", "uid": "e"}], None))
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([
        {"beginn": _t(1, 9), "ende": _t(1, 10), "titel": "Ivans",
         "ort": "", "uid": "i"}], None))
    eintraege, _ = server.belegungen()
    assert [e["titel"] for e in eintraege] == ["Ivans", "Eigener"]
    assert {e["quelle"] for e in eintraege} == {"Ivan", "Betreiber"}


def test_unerreichbare_quelle_wird_als_luecke_gemeldet(monkeypatch):
    """Sie darf NICHT stillschweigend als 'frei' gelten — sonst schlaegt der
    Bot ausgerechnet dann Termine vor, wenn er am wenigsten weiss."""
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole",
                        lambda url: ([], "Nicht erreichbar (TimeoutError)."))
    eintraege, luecken = server.belegungen()
    assert eintraege == []
    assert len(luecken) == 1
    assert luecken[0]["quelle"] == "Ivan"
    assert "erreichbar" in luecken[0]["grund"]


def test_der_stand_wird_festgehalten(monkeypatch):
    qid = server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([
        {"beginn": _t(1, 9), "ende": _t(1, 10), "titel": "A", "ort": "",
         "uid": "x"}], None))
    server.belegungen()
    q = [z for z in server.kalenderquellen_lesen() if z["id"] == qid][0]
    assert q["termine_zuletzt"] == 1
    assert q["letzter_fehler"] is None


def test_inaktive_quelle_wird_nicht_abgerufen(monkeypatch):
    server.kalenderquelle_speichern("Ivan", "https://example.test/a.ics")
    with server.pool.connection() as conn:
        conn.execute("update sales_test.kalender_quellen set aktiv = false")
    gerufen = []
    monkeypatch.setattr(kalenderquellen, "hole",
                        lambda url: gerufen.append(url) or ([], None))
    eintraege, luecken = server.belegungen()
    assert gerufen == []
    assert eintraege == [] and luecken == []


def test_eigener_kalenderfehler_ist_auch_eine_luecke(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen",
                        lambda *a, **k: ([], "Kalender nicht erreichbar."))
    eintraege, luecken = server.belegungen()
    assert [l["quelle"] for l in luecken] == ["Betreiber"]
```

Und in `sales-mcp/tests/test_termin.py` anhängen:

```python
def test_termine_lesen_liefert_auch_das_ende(kalender_stub):
    """DTEND wurde im ganzen Baum nur GESCHRIEBEN, nie gelesen — ohne
    Endzeit ist keine Ueberlappung berechenbar (Spec §2.2)."""
    kalender_stub.rumpf = (
        '<?xml version="1.0"?><multistatus xmlns="DAV:">'
        '<response><propstat><prop><calendar-data>'
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u1\r\n"
        "DTSTART;TZID=Europe/Berlin:20261001T090000\r\n"
        "DTEND;TZID=Europe/Berlin:20261001T104500\r\n"
        "SUMMARY:Mit Ende\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        '</calendar-data></prop></propstat></response></multistatus>'
    ).encode("utf-8")
    termine, fehler = kalender.termine_lesen()
    assert fehler is None, fehler
    assert (termine[0]["ende"] - termine[0]["beginn"]).total_seconds() == 6300
```

> **Hinweis an den Umsetzer:** Der Name der CalDAV-Stub-Fixture in `test_termin.py` ist zu prüfen (die Datei hat einen `_Stub` und einen `http.server`-Thread, siehe Kopf der Datei). Nimm die dort vorhandene Fixture; erfinde keine zweite.

- [ ] **Step 2: Tests laufen lassen und Fehlschlag prüfen**

```bash
docker build -q -t sales-mcp-ci ./sales-mcp && docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/test_belegungen.py tests/test_termin.py -q --tb=short -p no:cacheprovider
```

Erwartet: FEHLSCHLAG — `AttributeError: module 'server' has no attribute 'belegungen'` und `KeyError: 'ende'`.

- [ ] **Step 3: `kalender.termine_lesen` um die Endzeit ergänzen**

In `sales-mcp/kalender.py`, im `termine_lesen`-Schleifenkörper, **zusätzlich** zu den vorhandenen Feldern:

```python
        ende = _ics_zeit(_ics_feld(block, "DTEND"),
                         _ics_tzid(block, "DTEND"))
        termine.append({
            "beginn": beginn,
            # Ergaenzt 12.09.2026: DTEND wurde im Baum bis dahin nur
            # GESCHRIEBEN (ics()), nie gelesen — ohne Endzeit laesst sich
            # keine Ueberlappung berechnen (Spec §2.2). Nur ERGAENZT, die
            # beiden Anzeigestellen in ui.py bleiben unberuehrt.
            # Fehlt DTEND, gilt der Termin als punktuell statt geraten.
            "ende": ende if ende and ende > beginn else beginn,
            "titel": _ics_feld(block, "SUMMARY")[:200],
            "ort": _ics_feld(block, "LOCATION")[:120],
            "uid": _ics_feld(block, "UID")[:120]})
```

- [ ] **Step 4: `server.belegungen` schreiben**

Hinter `kalenderquelle_entfernen`:

```python
# Anzeigename der eigenen Quelle. Er steht neben fremden Namen in derselben
# Liste, deshalb ein Name und kein leeres Feld.
EIGENE_QUELLE = "Betreiber"


def belegungen(tage_voraus: int = 60):
    """Alle Termine aller aktiven Quellen -> (eintraege, luecken).

    `eintraege` = [{"beginn", "ende", "titel", "ort", "quelle"}], aufsteigend.
    `luecken`   = [{"quelle", "grund"}] — Quellen, die gerade nichts sagen.

    DIE LUECKEN SIND DER PUNKT (Spec §2.2): eine Quelle, die nicht
    antwortet, gilt NICHT als frei. Wer sie stillschweigend ueberginge,
    liesse den Bot ausgerechnet dann Termine vorschlagen, wenn er am
    wenigsten weiss. Jeder Aufrufer muss die Luecken weiterreichen.
    """
    eintraege, luecken = [], []

    eigene, fehler = kalender.termine_lesen(0, tage_voraus)
    if fehler:
        luecken.append({"quelle": EIGENE_QUELLE, "grund": fehler})
    for t in eigene:
        eintraege.append({**t, "quelle": EIGENE_QUELLE})

    for quelle in kalenderquellen_lesen():
        termine, fehler = kalenderquellen.hole(quelle["url"])
        kalenderquelle_stand_setzen(
            quelle["id"], None if fehler else len(termine), fehler)
        if fehler:
            luecken.append({"quelle": quelle["anzeigename"], "grund": fehler})
            continue
        for t in termine:
            eintraege.append({**t, "quelle": quelle["anzeigename"]})

    eintraege.sort(key=lambda e: e["beginn"])
    return eintraege, luecken
```

`import kalenderquellen` am Dateikopf von `server.py` ergänzen (neben `import kalender`).

- [ ] **Step 5: Tests laufen lassen**

Befehl aus Schritt 2. Erwartet: **alle grün**.

- [ ] **Step 6: Volle Suite**

Erwartet: **1756 grün**.

- [ ] **Step 7: Commit**

```bash
git add sales-mcp/kalender.py sales-mcp/server.py sales-mcp/tests/test_belegungen.py sales-mcp/tests/test_termin.py
git commit -m "feat(kalender): gemeinsame Belegung ueber alle Quellen, mit Luecken"
```

---

### Task 4: Kollisionsprüfung in den Terminwerkzeugen

**Files:**
- Modify: `sales-mcp/server.py` (`_kollisionen`, `termin_konflikte`, Einbau in `termin_bestaetigen` und `termin_einladen`)
- Test: `sales-mcp/tests/test_kollision.py` (neu)

**Interfaces:**
- Consumes: `server.belegungen`
- Produces:
  - `server._kollisionen(beginn: datetime, dauer_minuten: int) -> tuple[list, list]` — `(treffer, luecken)`; `treffer` = `[{"quelle", "titel", "beginn", "ende"}]`
  - Werkzeug `termin_konflikte(datum: str, uhrzeit: str, dauer_minuten: int = TERMIN_DAUER_VORGABE) -> str`
  - `termin_bestaetigen` und `termin_einladen` tragen im JSON zusätzlich `kollisionen` (Liste) und `quellen_luecken` (Liste)

**Ruling (im Plan entschieden, nicht offengelassen):** Eine Kollision **blockiert nicht**. Der Betreiber ruft das Werkzeug bewusst auf; ein hartes Nein an dieser Stelle nähme ihm eine Entscheidung ab, die ihm gehört (eine Doppelbuchung kann gewollt sein). Gemeldet wird sie deutlich — im Rückgabewert **und** im `hinweis`. Das Werkzeug `termin_konflikte` ist die Stelle, an der der Bot **vor** dem Vorschlagen fragt; damit erfüllt §2.2 „schlägt keinen kollidierenden Termin vor", ohne dem Menschen die Hand zu führen.

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`sales-mcp/tests/test_kollision.py`:

```python
"""Kollisionspruefung ueber alle Quellen — Spec §2.2, Pruefung 3a/3b."""
import json
import os
from datetime import datetime, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.leads, sales_test.kalender_quellen cascade")
    yield


def _belegt(*eintraege, luecken=()):
    return lambda tage_voraus=60: (list(eintraege), list(luecken))


def _e(tag, von, bis, quelle, titel="Belegt"):
    return {"beginn": datetime(2026, 10, tag, von, tzinfo=timezone.utc),
            "ende": datetime(2026, 10, tag, bis, tzinfo=timezone.utc),
            "titel": titel, "ort": "", "quelle": quelle}


def _beginn(tag, stunde):
    return datetime(2026, 10, tag, stunde, tzinfo=timezone.utc)


def test_ueberlappung_beim_kollegen_wird_gefunden(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Ivans Kundentermin")))
    treffer, luecken = server._kollisionen(_beginn(1, 9), 30)
    assert len(treffer) == 1
    assert treffer[0]["quelle"] == "Ivan"
    assert treffer[0]["titel"] == "Ivans Kundentermin"


def test_ueberlappung_beim_betreiber_wird_gefunden(monkeypatch):
    """Gegenprobe zur vorigen: beide Richtungen, wie Pruefung 3a verlangt."""
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Betreiber", "Eigener")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 30)
    assert [t["quelle"] for t in treffer] == ["Betreiber"]


def test_anschliessender_termin_ist_keine_kollision(monkeypatch):
    """Ende gleich Beginn heisst nacheinander, nicht gleichzeitig — sonst
    waere jeder Tag mit Terminkette blockiert."""
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 10), 30)
    assert treffer == []


def test_termin_davor_ist_keine_kollision(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 14, 15, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 60)
    assert treffer == []


def test_punktueller_termin_ohne_dauer_kollidiert_nicht(monkeypatch):
    """Fehlt DTEND, ist ende == beginn. Ein solcher Eintrag darf nicht den
    ganzen Tag blockieren."""
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 9, 9, "Ivan")))
    treffer, _ = server._kollisionen(_beginn(1, 9), 30)
    assert treffer == []


def test_luecken_werden_durchgereicht(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    treffer, luecken = server._kollisionen(_beginn(1, 9), 30)
    assert treffer == []
    assert luecken[0]["quelle"] == "Ivan"


def test_werkzeug_meldet_frei(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt())
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:00", 30))
    assert antwort["frei"] is True
    assert antwort["kollisionen"] == []


def test_werkzeug_meldet_belegt_mit_namen(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Kundentermin")))
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:30", 30))
    assert antwort["frei"] is False
    assert "Ivan" in antwort["hinweis"]


def test_werkzeug_ist_bei_luecken_nicht_einfach_frei(monkeypatch):
    """Der wichtigste Fall: nichts gefunden, aber auch nichts gewusst."""
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    antwort = json.loads(server.termin_konflikte("2026-10-01", "09:00", 30))
    assert antwort["frei"] is False
    assert "Ivan" in antwort["hinweis"]


def test_ungueltiges_datum_wird_abgewiesen():
    antwort = json.loads(server.termin_konflikte("morgen", "09:00"))
    assert "fehler" in antwort


def _lead():
    return str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values ('Ivan K', 'k@example.test', '+491701234567', 'whatsapp', "
        "'existing_customer') returning id")[0]["id"])


def test_einladung_nennt_die_kollision(monkeypatch):
    monkeypatch.setattr(server, "belegungen",
                        _belegt(_e(1, 9, 10, "Ivan", "Kundentermin")))
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@vibemind.space")
    antwort = json.loads(server.termin_einladen(
        _lead(), "2026-10-01", "09:30", thema="Test"))
    assert "fehler" not in antwort, antwort
    assert antwort["kollisionen"], antwort
    assert "Ivan" in antwort["hinweis"]


def test_kollision_blockiert_die_einladung_NICHT(monkeypatch):
    """Bewusste Entscheidung: der Betreiber ruft das Werkzeug absichtlich
    auf. Eine Doppelbuchung kann gewollt sein; gemeldet wird sie, verhindert
    nicht."""
    monkeypatch.setattr(server, "belegungen", _belegt(_e(1, 9, 10, "Ivan")))
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "felix@vibemind.space")
    lead = _lead()
    json.loads(server.termin_einladen(lead, "2026-10-01", "09:30", thema="T"))
    assert len(server._q(
        "select id from drafts where lead_id = %s", (lead,))) == 1
```

- [ ] **Step 2: Tests laufen lassen und Fehlschlag prüfen**

```bash
docker build -q -t sales-mcp-ci ./sales-mcp && docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/test_kollision.py -q --tb=short -p no:cacheprovider
```

Erwartet: FEHLSCHLAG — `AttributeError: module 'server' has no attribute '_kollisionen'`.

- [ ] **Step 3: `_kollisionen` und das Werkzeug schreiben**

Hinter `belegungen` in `server.py`:

```python
def _kollisionen(beginn, dauer_minuten: int):
    """Wer ist zu dieser Zeit schon belegt? -> (treffer, luecken).

    Ueberlappung im halboffenen Sinn: Ende gleich Beginn ist NACHEINANDER,
    nicht gleichzeitig. Ohne diese Kante waere jeder Tag mit einer
    Terminkette durchgehend blockiert.
    """
    ende = beginn + timedelta(minutes=dauer_minuten)
    eintraege, luecken = belegungen()
    treffer = [
        {"quelle": e["quelle"], "titel": e["titel"],
         "beginn": e["beginn"].isoformat(), "ende": e["ende"].isoformat()}
        for e in eintraege
        # e["ende"] > e["beginn"] schliesst punktuelle Eintraege aus (kein
        # DTEND) — sie wuerden sonst als nulllanges Fenster mitzaehlen.
        if e["ende"] > e["beginn"] and e["beginn"] < ende and e["ende"] > beginn]
    return treffer, luecken


def _kollisionstext(treffer, luecken) -> str:
    """Ein Satz fuer Mensch und Modell — beide lesen denselben."""
    teile = []
    if treffer:
        wer = ", ".join(
            f"{t['quelle']} ({t['titel']})" if t["titel"] else t["quelle"]
            for t in treffer)
        teile.append(f"ACHTUNG, zu dieser Zeit ist schon etwas: {wer}.")
    if luecken:
        wer = ", ".join(l["quelle"] for l in luecken)
        teile.append(
            f"Ausserdem war {wer} gerade nicht abrufbar — dort kann etwas "
            f"liegen, das hier fehlt.")
    return " ".join(teile)


@_werkzeug
def termin_konflikte(datum: str, uhrzeit: str,
                     dauer_minuten: int = TERMIN_DAUER_VORGABE) -> str:
    """Ist diese Zeit bei ALLEN Beteiligten frei? Fragt jede Quelle.

    VOR einem Terminvorschlag aufrufen. Es wird nichts angelegt und nichts
    versendet — das hier ist eine reine Auskunft.

    `frei` ist nur dann wahr, wenn nichts kollidiert UND jede Quelle
    geantwortet hat. War eine Quelle stumm, ist die Antwort NICHT „frei":
    eine unbekannte Belegung ist keine freie Zeit (Spec §2.2).
    """
    beginn, tag, zeit, fehler = _termin_zeitpunkt(datum, uhrzeit)
    if fehler:
        return _json({"fehler": fehler})
    dauer = _termin_dauer(dauer_minuten)
    treffer, luecken = _kollisionen(beginn, dauer)
    text = _kollisionstext(treffer, luecken)
    return _json({
        "frei": not treffer and not luecken,
        "kollisionen": treffer,
        "quellen_luecken": luecken,
        "hinweis": text or (f"{tag.isoformat()} {zeit:%H:%M} ist bei allen "
                            f"bekannten Quellen frei.")})
```

Das neue Werkzeug in die Werkzeugliste am Dateiende aufnehmen (dort, wo `termin_bestaetigen` und `termin_einladen` registriert sind).

- [ ] **Step 4: In `termin_bestaetigen` und `termin_einladen` einbauen**

In **beiden** Funktionen, unmittelbar nach der Zeile `dauer = _termin_dauer(dauer_minuten)`:

```python
    # Kollisionen melden, nicht verhindern (Entscheidung im Plan vom
    # 12.09.2026): der Betreiber ruft dieses Werkzeug bewusst auf, und eine
    # Doppelbuchung kann gewollt sein. Wer vorher wissen will, ob frei ist,
    # nimmt `termin_konflikte`.
    kollisionen, quellen_luecken = _kollisionen(beginn, dauer)
    kollisionstext = _kollisionstext(kollisionen, quellen_luecken)
```

Und im jeweiligen `return _json({...})` ergänzen:

```python
                  "kollisionen": kollisionen,
                  "quellen_luecken": quellen_luecken,
```

sowie den vorhandenen `hinweis` voranstellen lassen:

```python
                  "hinweis": (kollisionstext + " " if kollisionstext else "")
                             + <bisheriger Hinweistext>,
```

> **An den Umsetzer:** `<bisheriger Hinweistext>` ist der Ausdruck, der dort heute schon steht — wörtlich übernehmen, nicht neu formulieren. In `termin_einladen` beginnt er mit „Die Einladung liegt zur Freigabe."

- [ ] **Step 5: Tests laufen lassen**

Befehl aus Schritt 2. Erwartet: **12 passed**.

- [ ] **Step 6: Volle Suite**

Erwartet: **1768 grün**. Schlagen Tests in `test_termin.py` oder `test_termin_einladen.py` fehl, weil `belegungen()` dort echte HTTP-Aufrufe versucht: eine autouse-Fixture in **denselben** Dateien ergänzen, die `server.belegungen` auf `lambda tage_voraus=60: ([], [])` setzt — **nicht** die Erwartungen der Tests ändern.

- [ ] **Step 7: Commit**

```bash
git add sales-mcp/server.py sales-mcp/tests/test_kollision.py
git commit -m "feat(termin): Kollisionspruefung ueber alle Quellen, mit Werkzeug"
```

---

### Task 5: Rolle `kalender` und die Verbindungsseite im Tailnet

**Files:**
- Modify: `db/provision.sql` (CHECK der Spalte `benutzer.rolle` erweitern)
- Modify: `sales-mcp/ui.py` (Rollenwache, zwei Routen, zwei Seiten, Navigation)
- Test: `sales-mcp/tests/test_kalender_verbinden.py` (neu)

**Interfaces:**
- Consumes: `server.kalenderquelle_speichern`, `server.kalenderquellen_lesen`, `kalenderquellen.hole`
- Produces: Routen `GET /team/kalender` und `POST /team/kalender/verbinden`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`sales-mcp/tests/test_kalender_verbinden.py`:

```python
"""Der Kollege verbindet selbst — Spec §2.7, Pruefung 1 (Torschritt)."""
import os

import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalenderquellen  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
    yield


def _post(daten):
    return CLIENT.post("/team/kalender/verbinden", data=daten,
                       follow_redirects=False)


def test_seite_erklaert_den_weg_je_anbieter():
    seite = CLIENT.get("/team/kalender").text
    assert "Google" in seite and "Apple" in seite and "Outlook" in seite
    # Der genaue Klickweg, nicht nur der Name des Anbieters.
    assert "Geheime Adresse im iCal-Format" in seite


def test_verbinden_meldet_die_zahl_der_termine(monkeypatch):
    """Der Kern von §2.7: sofortige Rueckmeldung im Klartext."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([
        {"beginn": __import__("datetime").datetime(2026, 10, 1, 9,
         tzinfo=__import__("datetime").timezone.utc),
         "ende": __import__("datetime").datetime(2026, 10, 1, 10,
         tzinfo=__import__("datetime").timezone.utc),
         "titel": "A", "ort": "", "uid": "x"}], None))
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200, antwort.text
    assert "1 Termin" in antwort.text
    assert server.kalenderquellen_lesen()[0]["anzeigename"] == "Ivan"


def test_falscher_link_wird_benannt_nicht_nur_abgewiesen(monkeypatch):
    """Der haeufigste Bedienfehler. 'Ungueltig' hilft niemandem weiter."""
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: (
        [], "Dort liegt kein Kalender, sondern eine Webseite."))
    antwort = _post({"name": "Ivan", "url": "https://example.test/",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 200
    assert "Webseite" in antwort.text
    assert server.kalenderquellen_lesen() == []


def test_die_adresse_erscheint_nach_dem_speichern_nirgends(monkeypatch):
    """Spec §4: sie ist ein Schluessel, kein Anzeigewert — auch nicht fuer
    den Betreiber."""
    geheim = "https://calendar.google.com/ical/GEHEIM123/basic.ics"
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))
    _post({"name": "Ivan", "url": geheim, "csrf": ui.CSRF_TOKEN})
    assert "GEHEIM123" not in CLIENT.get("/team/kalender").text


def test_ohne_csrf_passiert_nichts():
    antwort = _post({"name": "Ivan", "url": "https://example.test/a.ics"})
    assert antwort.status_code == 403
    assert server.kalenderquellen_lesen() == []


def test_leerer_name_wird_abgewiesen(monkeypatch):
    monkeypatch.setattr(kalenderquellen, "hole", lambda url: ([], None))
    antwort = _post({"name": "  ", "url": "https://example.test/a.ics",
                     "csrf": ui.CSRF_TOKEN})
    assert antwort.status_code == 400
    assert server.kalenderquellen_lesen() == []


def test_rolle_kalender_darf_die_seite_und_sonst_nichts(monkeypatch):
    """Die vorhandene Rolle `lesen` 'sieht alles' — also auch saemtliche
    Kontakte und den Posteingang. Fuer einen Kollegen ist das zu viel."""
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "geheim")
    assert ui._pfad_erlaubt("kalender", "/team/kalender") is True
    assert ui._pfad_erlaubt("kalender", "/kalender") is True
    assert ui._pfad_erlaubt("kalender", "/kontakte") is False
    assert ui._pfad_erlaubt("kalender", "/posteingang") is False
    assert ui._pfad_erlaubt("kalender", "/freigaben") is False
    assert ui._pfad_erlaubt("lesen", "/kontakte") is True
```

- [ ] **Step 2: Tests laufen lassen und Fehlschlag prüfen**

```bash
docker build -q -t sales-mcp-ci ./sales-mcp && docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/test_kalender_verbinden.py -q --tb=short -p no:cacheprovider
```

Erwartet: FEHLSCHLAG — 404 auf `/team/kalender`, `AttributeError: _pfad_erlaubt`.

- [ ] **Step 3: Die Rolle in `db/provision.sql` zulassen**

Im `create table ... benutzer`-Block:

```sql
        rolle text not null check (rolle in ('lesen','freigeben','kalender')),
```

Und auf beide Schemata der Testdatenbank anwenden:

```bash
docker exec -i sales-testdb psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "alter table sales_test.benutzer drop constraint if exists benutzer_rolle_check; alter table sales_test.benutzer add constraint benutzer_rolle_check check (rolle in ('lesen','freigeben','kalender'));"
```

**In den Bericht:** dieselbe Anweisung muss vor der Inbetriebnahme auf `sales` laufen.

- [ ] **Step 4: Rollenwache in `ui.py` erweitern**

Neben der vorhandenen Prüfung (heute bei etwa Zeile 512):

```python
# Was die schmale Rolle `kalender` sehen darf. Ergaenzt 12.09.2026: die
# vorhandene Rolle `lesen` "sieht alles" — das sind saemtliche Kontakte,
# Entwuerfe und der Posteingang, also der komplette Kundenstamm. Ein
# Kollege, der nur Termine abgleichen soll, bekommt das nicht.
# Praefixe, keine Regex: eine Liste, die man vorlesen kann.
_KALENDER_ROLLE_PFADE = ("/team/kalender", "/kalender", "/logout", "/login")


def _pfad_erlaubt(rolle: str, pfad: str) -> bool:
    """Darf diese Rolle diesen Pfad sehen? Nur `kalender` ist eingeschraenkt."""
    if rolle != "kalender":
        return True
    return any(pfad == p or pfad.startswith(p + "/")
               for p in _KALENDER_ROLLE_PFADE)
```

In der Wache, **nach** `scope["benutzer_rolle"] = benutzer["rolle"]` und **vor** der `lesen`-Prüfung:

```python
        if not _pfad_erlaubt(benutzer["rolle"], scope["path"]):
            antwort = _fehlerseite(
                403, "Nicht für diese Anmeldung",
                "Diese Anmeldung sieht den Kalender und die Seite zum "
                "Verbinden — sonst nichts. Nichts wurde getan.")
            await antwort(scope, receive, send)
            return
```

Die `lesen`-Prüfung muss zusätzlich `kalender` umfassen, damit auch sie nichts verändert:

```python
        if (benutzer["rolle"] in ("lesen", "kalender")
                and scope["method"] not in ("GET", "HEAD")
                and scope["path"] not in ("/logout",
                                          "/team/kalender/verbinden")):
```

> **Warum `/team/kalender/verbinden` ausgenommen ist:** Das ist die eine Schreibaktion, die dieser Rolle gehört — sie trägt die eigene Adresse ein. Ohne Ausnahme könnte der Kollege die Seite sehen, aber nicht benutzen.

- [ ] **Step 5: Die Seite bauen**

```python
# Klickwege je Anbieter. Ein Text fuer alle waere hier der Fehler: wer
# Google nutzt, soll nicht durch vier Absaetze zu Apple lesen muessen.
_ANBIETER_WEGE = (
    ("Google Kalender",
     "Einstellungen → „Einstellungen für meine Kalender" → deinen Kalender "
     "wählen → „Kalender integrieren" → <b>Geheime Adresse im iCal-Format</b>"),
    ("Apple iCloud",
     "Kalender-App → Kalender einblenden → beim Kalender auf das Symbol → "
     "„Öffentlicher Kalender" aktivieren → Adresse kopieren"),
    ("Outlook / Microsoft 365",
     "Einstellungen → Kalender → „Freigegebene Kalender" → „Kalender "
     "veröffentlichen" → Berechtigung „Alle Details" → <b>ICS-Link</b> kopieren"),
)


@_gesichert_seite
async def team_kalender(request):
    """Die Seite, über die ein Kollege seinen Kalender verbindet."""
    zeilen = []
    for quelle in server.kalenderquellen_lesen(nur_aktive=False):
        stand = (f"zuletzt gelesen {_zeit(quelle['zuletzt_gelesen'])}"
                 if quelle["zuletzt_gelesen"] else "noch nicht gelesen")
        if quelle["letzter_fehler"]:
            stand += f" — {_e(quelle['letzter_fehler'])}"
        elif quelle["termine_zuletzt"] is not None:
            stand += f", {quelle['termine_zuletzt']} Termine"
        # Die Adresse steht hier NICHT (Spec §4).
        zeilen.append([_e(quelle["anzeigename"]), stand])
    tabelle = (_tabelle(["Name", "Stand"], zeilen) if zeilen else
               '<p class="meta">Noch kein Kalender verbunden.</p>')

    wege = "".join(
        f'<details><summary>{_e(name)}</summary><p class="meta">{weg}</p>'
        f'</details>' for name, weg in _ANBIETER_WEGE)

    formular = (
        f'<form method="post" action="/team/kalender/verbinden">'
        f'<input type="hidden" name="csrf" value="{_e(CSRF_TOKEN)}">'
        f'<label>Dein Name<br><input name="name" required></label>'
        f'<label>Geheime Kalenderadresse<br>'
        f'<input name="url" type="text" required '
        f'placeholder="https://…/basic.ics"></label>'
        f'<button type="submit">Verbinden und prüfen</button></form>')

    return _seite("Kalender verbinden",
                  '<h1>Kalender verbinden</h1>'
                  '<p class="meta">Suche unten deinen Anbieter, hole dir die '
                  'geheime Adresse und füge sie ein. Es wird sofort geprüft, '
                  'ob sie stimmt. Du kannst sie bei deinem Anbieter jederzeit '
                  'zurücksetzen — dann endet der Zugriff sofort.</p>'
                  + wege + formular + '<h2>Verbunden</h2>' + tabelle)


@_gesichert_seite
async def aktion_kalender_verbinden(request):
    """Adresse prüfen, dann erst speichern — nie umgekehrt.

    Die sofortige Rückmeldung ist der Kern von §2.7: der häufigste Fehler
    ist die öffentliche statt der geheimen Adresse, und ohne Prüfung merkt
    das niemand — die Sicht bliebe tagelang leer.
    """
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(403, "Abgewiesen",
                            "Fehlende oder falsche CSRF-Marke.")
    name = str(form.get("name") or "").strip()[:80]
    url = str(form.get("url") or "").strip()
    if not name:
        return _fehlerseite(400, "Name fehlt",
                            "Ohne Namen lässt sich der Kalender später "
                            "niemandem zuordnen.")
    termine, fehler = server.kalenderquellen.hole(url)
    if fehler:
        return _seite("Kalender verbinden", (
            f'<h1>Das hat nicht geklappt</h1>'
            f'<p class="fehler">{_e(fehler)}</p>'
            f'<p class="meta">Nichts wurde gespeichert.</p>'
            f'<p><a href="/team/kalender">Zurück und erneut versuchen</a></p>'))
    server.kalenderquelle_speichern(name, url)
    naechster = ""
    if termine:
        naechster = (f" Der nächste ist „{_e(termine[0]['titel'])}" + '" am '
                     f"{_zeit(termine[0]['beginn'])}.")
    return _seite("Kalender verbunden", (
        f'<h1>Passt</h1>'
        f'<p>Ich sehe {len(termine)} Termin{"e" if len(termine) != 1 else ""} '
        f'in deinem Kalender.{naechster}</p>'
        f'<p class="meta">Die Adresse ist gespeichert und wird ab jetzt nicht '
        f'mehr angezeigt.</p>'
        f'<p><a href="/team/kalender">Zur Übersicht</a></p>'))
```

Routen eintragen:

```python
    Route("/team/kalender", team_kalender),
    Route("/team/kalender/verbinden", aktion_kalender_verbinden,
          methods=["POST"]),
```

> **An den Umsetzer:** `_zeit`, `_tabelle`, `_seite`, `_fehlerseite`, `_gesichert_seite` sind vorhandene Helfer in `ui.py` — die genauen Namen und Signaturen dort prüfen und verwenden, nicht nachbauen. Gibt es keinen Helfer `_zeit` für die Anzeige eines Zeitpunkts, nimm den, der auf der Kalenderseite verwendet wird.

- [ ] **Step 6: Tests laufen lassen**

Befehl aus Schritt 2. Erwartet: **7 passed**.

- [ ] **Step 7: Volle Suite und Umlaut-Wächter**

Erwartet: **1775 grün**. Der Wächter in `test_darstellung.py` prüft echte Umlaute in `ui.py` — schlägt er an, ist ein Anzeigetext in ASCII geschrieben.

- [ ] **Step 8: Commit**

```bash
git add db/provision.sql sales-mcp/ui.py sales-mcp/tests/test_kalender_verbinden.py
git commit -m "feat(ui): Kollegen verbinden ihren Kalender selbst, mit schmaler Rolle"
```

---

### Task 6: Team-Sicht — fremde Termine mit Namen

**Files:**
- Modify: `sales-mcp/ui.py` (Kalenderseite: `belegungen` statt `kalender.termine_lesen`)
- Test: `sales-mcp/tests/test_team_sicht.py` (neu)

**Interfaces:**
- Consumes: `server.belegungen`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`sales-mcp/tests/test_team_sicht.py`:

```python
"""Fremde Termine erscheinen benannt — Spec §2.5, Pruefung 2."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)


def _bald(stunden):
    return datetime.now(timezone.utc) + timedelta(hours=stunden)


def _belegt(*eintraege, luecken=()):
    return lambda tage_voraus=60: (list(eintraege), list(luecken))


def test_fremder_termin_traegt_den_namen(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(
        {"beginn": _bald(24), "ende": _bald(25), "titel": "Kundentermin",
         "ort": "", "quelle": "Ivan"}))
    seite = CLIENT.get("/kalender").text
    assert "Kundentermin" in seite
    assert "Ivan" in seite


def test_stumme_quelle_wird_auf_der_seite_genannt(monkeypatch):
    """Eine Luecke, die niemand sieht, ist schlimmer als keine Sicht."""
    monkeypatch.setattr(server, "belegungen", _belegt(
        luecken=[{"quelle": "Ivan", "grund": "Nicht erreichbar."}]))
    seite = CLIENT.get("/kalender").text
    assert "Ivan" in seite
    assert "erreichbar" in seite


def test_fremddaten_erscheinen_escaped(monkeypatch):
    monkeypatch.setattr(server, "belegungen", _belegt(
        {"beginn": _bald(24), "ende": _bald(25),
         "titel": "<script>alert(1)</script>", "ort": "",
         "quelle": "<b>Ivan</b>"}))
    seite = CLIENT.get("/kalender").text
    assert "<script>alert(1)</script>" not in seite
    assert "&lt;script&gt;" in seite
    assert "<b>Ivan</b>" not in seite
```

- [ ] **Step 2: Tests laufen lassen und Fehlschlag prüfen**

Erwartet: FEHLSCHLAG — der Name der Quelle steht nicht auf der Seite.

- [ ] **Step 3: Die Kalenderseite umstellen**

In `ui.py` an der Stelle, die heute `kalender.termine_lesen()` aufruft (etwa Zeile 3632): auf `server.belegungen()` umstellen, den Namen der Quelle je Eintrag ausgeben und die Lücken als Hinweiszeile über der Liste zeigen.

```python
    eintraege, luecken = server.belegungen()
    if luecken:
        wer = ", ".join(_e(l["quelle"]) for l in luecken)
        teile.append(
            f'<p class="hinweis">Nicht abrufbar: {wer}. Dort können Termine '
            f'liegen, die hier fehlen.</p>')
```

Je Eintrag den Namen als eigenes Element neben Titel und Zeit — wie heute die Marke „zwei Quellen" (Spec §2.5: schlichte Anzeige, die Farbgebung gehört zu Stufe 4 der Oberflächen-Überarbeitung).

> **An den Umsetzer:** Die zweite Stelle (`ui.py:5119`, Startseite „Heute") bleibt vorerst auf `kalender.termine_lesen` — sie zeigt bewusst nur den eigenen Tag. Das ist eine Entscheidung, keine Auslassung; schreib sie als Kommentar an die Stelle.

- [ ] **Step 4: Tests laufen lassen**

Erwartet: **3 passed**.

- [ ] **Step 5: Volle Suite**

Erwartet: **1778 grün**.

- [ ] **Step 6: Commit**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_team_sicht.py
git commit -m "feat(ui): fremde Termine erscheinen mit dem Namen ihrer Quelle"
```

---

## Nicht in diesem Plan

* **Ein Abrufdienst.** `belegungen()` holt bei jedem Aufruf. Bei zwei bis fünf Quellen ist das eine HTTP-Anfrage je Quelle und Aufruf — vertretbar. Ein Zwischenspeicher mit Verfallszeit ist die naheliegende nächste Stufe, wenn es spürbar wird.
* **CalDAV-Quellen in der Tabelle.** Der eigene Kalender bleibt in der `.env`; er braucht Zugangsdaten und es gibt genau einen. Die Spalte `art` hat den Platz schon.
* **Farbige Wochenansicht** — Stufe 4 der Oberflächen-Überarbeitung (Spec §2.5).
* **Freie Zeiten vorschlagen.** `termin_konflikte` beantwortet „ist diese Zeit frei"; „finde mir eine freie Zeit" ist eine eigene Aufgabe.
* **Die Messung „taucht eine CalDAV-Freigabe im fremden Konto auf?"** — mit Weg 3 nicht mehr Voraussetzung (Spec §2.1, Revision).

## Nach dem letzten Task — Betreiberschritte

1. Auf der Produktionsdatenbank anwenden: die Tabelle `kalender_quellen` und die erweiterte `rolle`-Bedingung (siehe Task 1 Schritt 4 und Task 5 Schritt 3).
2. Ein Konto mit der Rolle `kalender` anlegen (`deploy/benutzer-anlegen.sh`).
3. Den Kollegen ins Tailnet holen und ihm den Link auf `/team/kalender` schicken.
4. `docs/06_DSGVO.md` und `docs/08_TOMS.md` ergänzen (Spec §4) — **vor** der Inbetriebnahme.
5. `docs/04_BACKUP_RESTORE.md`: die Sicherung enthält jetzt fremde Kalenderadressen.
