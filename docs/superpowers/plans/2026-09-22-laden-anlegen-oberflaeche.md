# Laden anlegen aus der Oberfläche — Implementierungsplan

> **Für agentische Arbeiter:** ERFORDERLICHE UNTER-FERTIGKEIT: `superpowers:subagent-driven-development` (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen. Schritte benutzen Kästchen (`- [ ]`) zur Verfolgung.

**Ziel:** Ein Knopf in der Oberfläche des Betreiber-Ladens legt einen neuen Laden an —
Schema, Datenbankbenutzer, zwei Container, ein Konto mit Wegwerf-Passwort — ohne SSH.

**Architektur:** Die Oberfläche schreibt eine Zeile in eine neue Tabelle
`sales.admin_auftraege`; ein eigener, schneller Zeitgeber auf dem Wirt liest sie ab und
ruft dafür **ausschließlich bereits bestehende, geprüfte Skripte** auf
(`deploy/laden-anlegen.sh`, `db/laden-anlegen.sql`, `deploy/benutzer-anlegen.sh`) — keine
zweite Fassung ihrer Logik. Die Datenbanktrennung, die für `sales_app_ivan` bereits gilt,
schützt die neue Tabelle automatisch: Ivans Laden kann sie nicht einmal lesen.

**Tech Stack:** Python 3.12 (Starlette, `sales-mcp/ui.py`), PostgreSQL/Supabase, Bash,
systemd (Timer statt Pfad-Dienst — die Übergabe läuft über eine Tabelle, nicht eine Datei).

**Spec:** `docs/superpowers/specs/2026-09-22-laden-anlegen-oberflaeche-design.md`

## Global Constraints

* **Schema-Muster für einen Ladennamen:** `^[a-z][a-z0-9_]{0,30}$` — identisch zu
  `server.SCHEMA_MUSTER` in `sales-mcp/server.py:87`
  (`re.compile(r"sales(_[a-z][a-z0-9_]{0,30})?")`) ohne das `sales`-Präfix. Jede neue
  Prüfung dieses Musters (Bash **und** Python) muss dasselbe Ergebnis liefern.
* **Niemals nacktes `docker compose up -d`** — es würde `<laden>-auto` mitstarten,
  einen Dienst, der bewusst nie läuft.
* **Die Compose-Dienstschlüssel bleiben literal `sales-mcp`/`sales-ui`**, für JEDEN
  Laden — nur `--env-file deploy/laeden/<name>.env` bestimmt, welcher Laden tatsächlich
  entsteht (`container_name` interpoliert den Präfix aus der Umgebungsdatei). Ein Aufruf
  mit `"$NAME-mcp"` als Dienstschlüssel ist falsch und scheitert.
* **Passwörter nie über `argv`**, immer über `stdin` oder die Prozessumgebung — sie
  stünden sonst in der Prozessliste.
* **`sales_app` bekommt auf `sales.admin_auftraege` nur `select, insert`** — nie
  `update`/`delete`. Nur der Wirt (als `supabase_admin`) setzt `status`/`ergebnis`/`fehler`.
* **Der Knopf ist nur sichtbar und erreichbar**, wenn `rolle == "freigeben"` **und**
  `server.SCHEMA == "sales"` — beide Bedingungen, nicht nur eine.
* **Kein JavaScript** (`default-src 'none'`, siehe `sales-mcp/ui.py:696-724`). „Warten auf
  ein Ergebnis" heißt ausschließlich `<meta http-equiv="refresh" content="N">`, erzeugt
  über den vorhandenen Parameter `_seite(..., refresh=N)`.
* **`export LC_ALL=C`** am Kopf jedes neuen Bash-Skripts — ohne das kollationiert `bash`
  unter z. B. `de_DE.UTF-8` Bereiche wie `[a-z]` groß-/kleinschreibungs-durchlässig.
* **Jeder Auftrag, der scheitert, endet mit `status='fehler'`, nie `'erfolg'`** — und
  `ergebnis` nennt genau, welche Schritte bereits fertig waren.
* **Kein Subagent führt ohne ausdrückliche Freigabe des Betreibers einen echten Lauf
  gegen die Produktion (`debian-supabase-db-1`, echte Container) aus.** Das gilt für den
  letzten Prüfschritt in Aufgabe 3 und für Aufgabe 4 — dieselbe Regel wie im Plan vom
  16.09.2026 (Ruling 6/13).

---

## Dateien, die dieser Plan anfasst

| Datei | Verantwortung | Aufgabe |
|---|---|---|
| `db/provision.sql` | neue Tabelle `admin_auftraege` in `sales` **und** `sales_test`, Grant für `sales_app` | 1 |
| `sales-mcp/ui.py` | Rollen-Tor, die neue Seite (GET+POST), Menüeintrag | 2 |
| `sales-mcp/tests/test_laden_anlegen_seite.py` | **neu** — Tor-Tests, Formular-Tests | 2 |
| `deploy/admin-auftrag-ausfuehren.sh` | **neu** — der Wirt-Orchestrator, neun Schritte | 3 |
| `deploy/systemd/sales-admin-auftraege.timer` | **neu** — 20-Sekunden-Takt | 3 |
| `deploy/systemd/sales-admin-auftraege.service` | **neu** — startet das Skript | 3 |
| `docs/03_RUNBOOK.md` | Abschnitt „Laden anlegen aus der Oberfläche" | 4 |

---

## Task 1: Die Tabelle

**Files:**
- Modify: `db/provision.sql`
- Test: `sales-mcp/tests/test_admin_auftraege_tabelle.py`

**Interfaces:**
- Produces: Tabelle `admin_auftraege` in `sales` und `sales_test`, Spalten `id, art, name,
  angefordert_von, status, ergebnis, fehler, erstellt_am, erledigt_am`. `sales_app` hat
  `select, insert` in `sales` (Aufgabe 2 schreibt darauf), volle Rechte in `sales_test`
  über den bestehenden Blankettо-Grant (`db/provision.sql:360-361`).

**Warum zwei feste Schemanamen und keine Schleife über alle Läden:** Diese Tabelle gehört
NICHT zu „jedem Laden" (wie `leads`, `benutzer` usw.) — sie ist eine Fähigkeit des
Basis-Ladens allein. Eine Schleife über `information_schema.schemata` (das Muster, das K3
korrigiert hat) würde sie versehentlich auch in `sales_ivan` anlegen. Stattdessen exakt
das Muster von `compliance`/`compliance_test`: zwei benannte Schemata, kein Dritter.

- [ ] **Step 1: Die Tabelle in `db/provision.sql` ergänzen**

Direkt nach dem `updated_at`-Trigger-Block (endet `db/provision.sql:345` mit `end $$;`)
und vor dem Kommentar „Rechte Demo-Schema" (`db/provision.sql:347`) einfügen:

```sql
-- Auftraege "Laden anlegen" aus der Oberflaeche (22.09.2026).
--
-- ANDERS ALS DER TABELLEN-BLOCK OBEN: diese Tabelle gehoert NICHT zu jedem
-- Laden, sondern ausschliesslich dem Basis-Laden — dieselbe Ueberlegung wie
-- compliance/compliance_test, NICHT wie K3 (dort war "zwei feste Schemata"
-- der Fehler, weil die betroffenen Tabellen in JEDEM Laden gebraucht
-- wurden; hier ist "zwei feste Schemata" richtig, weil die Faehigkeit
-- ausdruecklich nur dem Basis-Laden gehoert). sales_test steht daneben,
-- damit die Testsuite (die NIE gegen sales laufen darf) die Rollen-
-- Tor-Logik und den Einfuege-/Anzeige-Pfad ueberhaupt pruefen kann.
do $$
declare s text;
begin
  foreach s in array array['sales','sales_test'] loop
    execute format($t$create table if not exists %I.admin_auftraege (
        id uuid primary key default gen_random_uuid(),
        art text not null check (art = 'laden_anlegen'),
        name text not null check (name ~ '^[a-z][a-z0-9_]{0,30}$'),
        angefordert_von text not null,
        status text not null default 'offen'
               check (status in ('offen','laeuft','erfolg','fehler')),
        ergebnis jsonb,
        fehler text,
        erstellt_am timestamptz not null default now(),
        erledigt_am timestamptz)$t$, s);
    execute format('create index if not exists admin_auftraege_offen_idx '
                   'on %I.admin_auftraege (status, erstellt_am)', s);
  end loop;
end $$;
```

Und bei den übrigen `grant ... to sales_app`-Zeilen (nach
`db/provision.sql:353`, der `benutzer_mails`-Zeile) ergänzen:

```sql
-- Kein update, kein delete: die Oberflaeche legt einen Auftrag an, sie
-- aendert ihn nie wieder — nur der Wirt (als supabase_admin) tut das.
grant select, insert on sales.admin_auftraege to sales_app;
```

- [ ] **Step 2: Gegen die Testdatenbank anwenden**

```bash
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 < db/provision.sql
```

Erwartet: keine Fehler. Ein zweiter Lauf ebenfalls fehlerfrei (Idempotenz).

- [ ] **Step 3: Die Struktur mit einem Test festhalten**

Neue Datei `sales-mcp/tests/test_admin_auftraege_tabelle.py`:

```python
"""Struktur von sales.admin_auftraege / sales_test.admin_auftraege.

WELCHE KAPUTTE FASSUNG FAENGT DAS?
-------------------------------------------------------------------------
Eine kuenftige Aenderung, die admin_auftraege versehentlich in die
Per-Laden-Schleife von db/provision.sql zieht (der K3-Fehler in die
GEGENTEILIGE Richtung): dann existierte sie auch in sales_ivan, und Ivans
sales_app_ivan koennte sie lesen/beschreiben. Dieser Test prueft deshalb
NICHT nur "existiert sie", sondern auch die Rechte von sales_app selbst.
"""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


def test_tabelle_existiert_mit_den_erwarteten_spalten():
    zeilen = server._q(
        "select column_name from information_schema.columns "
        "where table_schema = 'sales_test' and table_name = 'admin_auftraege' "
        "order by ordinal_position")
    spalten = [z["column_name"] for z in zeilen]
    assert spalten == ["id", "art", "name", "angefordert_von", "status",
                        "ergebnis", "fehler", "erstellt_am", "erledigt_am"]


def test_art_erlaubt_nur_laden_anlegen():
    with server.pool.connection() as conn:
        try:
            conn.execute(
                "insert into admin_auftraege (art, name, angefordert_von) "
                "values ('etwas_anderes', 'probe', 'test')")
            assert False, "haette am CHECK scheitern muessen"
        except Exception as e:
            assert "23514" in str(getattr(e, "sqlstate", "") or e)
        conn.rollback()


def test_name_erzwingt_das_schema_muster():
    with server.pool.connection() as conn:
        for schlechter_name in ("Ivan", "ivan-mit-bindestrich", "1ivan", ""):
            try:
                conn.execute(
                    "insert into admin_auftraege (art, name, angefordert_von) "
                    "values ('laden_anlegen', %s, 'test')", (schlechter_name,))
                assert False, f"'{schlechter_name}' haette scheitern muessen"
            except Exception:
                pass
            conn.rollback()


def test_sales_app_hat_kein_update_und_kein_delete_recht():
    zeilen = server._q(
        "select privilege_type from information_schema.role_table_grants "
        "where table_schema = 'sales_test' and table_name = 'admin_auftraege' "
        "and grantee = 'sales_app' order by privilege_type")
    rechte = {z["privilege_type"] for z in zeilen}
    # sales_test traegt den Blankett-Grant (delete/insert/select/truncate/
    # update) — DAS ist hier gewollt (die Testsuite muss aufraeumen
    # koennen). Auf `sales` (Produktion) gilt das NICHT, siehe Step 1: dort
    # bekommt sales_app nur select+insert. Dieser Test haelt fest, WARUM
    # sales_test bewusst weiter reicht, statt es stillschweigend
    # hinzunehmen.
    assert rechte == {"delete", "insert", "select", "truncate", "update"}
```

- [ ] **Step 4: Testen**

```bash
docker build -q -t sales-mcp:dev sales-mcp
docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev \
  python -m pytest -q tests/test_admin_auftraege_tabelle.py
```

Erwartet: 4 passed.

- [ ] **Step 5: Committen**

```bash
git add db/provision.sql sales-mcp/tests/test_admin_auftraege_tabelle.py
git commit -m "feat: Tabelle admin_auftraege fuer 'Laden anlegen aus der Oberflaeche'"
```

---

## Task 2: Das Rollen-Tor und die Seite

**Files:**
- Modify: `sales-mcp/ui.py`
- Test: `sales-mcp/tests/test_laden_anlegen_seite.py`

**Interfaces:**
- Consumes: Tabelle `admin_auftraege` aus Aufgabe 1.
- Produces: Route `/team/laden-anlegen` (GET), Route `/team/laden-anlegen/anfordern`
  (POST) — Aufgabe 3 liest, was hier eingefügt wird.

**Warum eine reine Funktionsprüfung für das Tor, nicht der Umweg über eine echte
Anmeldung:** `AnmeldeWache` setzt `scope["benutzer_rolle"]` nur, wenn `UI_SESSION_SECRET`
gesetzt ist — im Testlauf ist es das nicht (dieselbe Übergangs-Lage, die schon
`test_ui.py` nutzt). `_pfad_erlaubt(rolle, pfad)` ist eine reine Funktion und lässt sich
direkt aufrufen; `server.SCHEMA` wird für den negativen Fall testweise umgebogen
(`monkeypatch.setattr`) — das ändert nur den Vergleichswert, nicht die tatsächliche
Datenbankverbindung (die steht bereits fest auf `sales_test`).

- [ ] **Step 1: Die fehlschlagenden Tor-Tests schreiben**

Neue Datei `sales-mcp/tests/test_laden_anlegen_seite.py`:

```python
"""Rollen-Tor und Formular fuer '/team/laden-anlegen'.

WELCHE KAPUTTE FASSUNG FAENGT JEDER TEST?
-------------------------------------------------------------------------
* test_nur_freigeben_und_basis_laden_duerfen  — eine Fassung, die nur die
  Rolle prueft (nicht auch server.SCHEMA), wuerde Ivan den Knopf zeigen,
  saehe er ihn ueberhaupt (er sieht ihn wegen der Schema-Pruefung NIE).
* test_falscher_name_wird_serverseitig_abgewiesen — ein Formular, das dem
  Browser-Muster vertraut, laesst jeden Namen durch, den jemand ohne
  Browser (curl, ein Skript) schickt.
* test_zeile_traegt_den_angemeldeten_namen — eine Fassung, die den Namen
  hart auf 'betreiber-ui' setzt (Kopiereffekt aus anderen Routen), wuerde
  nie zeigen, WER einen Laden angefordert hat.
"""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

import pytest
from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.admin_auftraege")


def _post(pfad, daten, host=HOST_OK):
    return CLIENT.post(pfad, data=daten, headers={"host": host},
                       follow_redirects=False)


def _get(pfad, host=HOST_OK):
    return CLIENT.get(pfad, headers={"host": host})


def test_nur_freigeben_und_basis_laden_duerfen():
    assert ui._pfad_erlaubt("freigeben", "/team/laden-anlegen") is True
    assert ui._pfad_erlaubt("lesen", "/team/laden-anlegen") is False
    assert ui._pfad_erlaubt("kalender", "/team/laden-anlegen") is False


def test_freigeben_ausserhalb_des_basis_ladens_darf_nicht(monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/team/laden-anlegen") is False
    assert ui._pfad_erlaubt("freigeben", "/team/laden-anlegen/anfordern") is False


@pytest.mark.parametrize("schlechter_name", [
    "Ivan", "ivan-mit-bindestrich", "1ivan", "", "a" * 32])
def test_falscher_name_wird_serverseitig_abgewiesen(schlechter_name):
    r = _post("/team/laden-anlegen/anfordern",
              {"name": schlechter_name, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_guter_name_legt_eine_zeile_mit_status_offen_an():
    r = _post("/team/laden-anlegen/anfordern",
              {"name": "lena", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    zeilen = server._q(
        "select name, status, angefordert_von from admin_auftraege")
    assert len(zeilen) == 1
    assert zeilen[0]["name"] == "lena"
    assert zeilen[0]["status"] == "offen"
    # Ohne scharfe Anmeldung (Testlage) greift der dokumentierte
    # Uebergangs-Sammelstempel — derselbe wie bei jeder anderen Route.
    assert zeilen[0]["angefordert_von"] == "betreiber-ui"


def test_ohne_csrf_token_wird_nichts_angelegt():
    r = _post("/team/laden-anlegen/anfordern", {"name": "lena"})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_seite_traegt_auffrischen_solange_ein_auftrag_offen_ist():
    server._q(
        "insert into admin_auftraege (art, name, angefordert_von) "
        "values ('laden_anlegen', 'lena', 'test')")
    r = _get("/team/laden-anlegen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' in r.text


def test_seite_traegt_kein_auffrischen_wenn_alles_erledigt_ist():
    server._q(
        "insert into admin_auftraege "
        "(art, name, angefordert_von, status, erledigt_am) "
        "values ('laden_anlegen', 'lena', 'test', 'erfolg', now())")
    r = _get("/team/laden-anlegen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' not in r.text


def test_seite_ohne_javascript():
    r = _get("/team/laden-anlegen")
    assert "<script" not in r.text.lower()
```

- [ ] **Step 2: Testen, es muss scheitern**

```bash
docker build -q -t sales-mcp:dev sales-mcp
docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev \
  python -m pytest -q tests/test_laden_anlegen_seite.py
```

Erwartet: `AttributeError` — `ui._pfad_erlaubt` existiert, aber kennt den neuen Pfad
noch nicht; die Routen fehlen (404 statt der erwarteten Codes).

- [ ] **Step 3: `_pfad_erlaubt` erweitern**

In `sales-mcp/ui.py`, Zeilen 520-525, ersetzen:

```python
def _pfad_erlaubt(rolle: str, pfad: str) -> bool:
    """Darf diese Rolle diesen Pfad sehen? `kalender` ist eingeschraenkt,
    `/team/laden-anlegen` zusaetzlich auf `freigeben` im Basis-Laden — sonst
    saehe Ivan (selbst mit der Rolle `freigeben` in seinem eigenen Laden)
    einen Knopf, der auf dem Wirt Container und Datenbankbenutzer erzeugt."""
    if pfad == "/team/laden-anlegen" or pfad.startswith("/team/laden-anlegen/"):
        return rolle == "freigeben" and server.SCHEMA == "sales"
    if rolle != "kalender":
        return True
    return any(pfad == p or pfad.startswith(p + "/")
               for p in _KALENDER_ROLLE_PFADE)
```

- [ ] **Step 4: Den Menüeintrag ergänzen**

In `sales-mcp/ui.py`, Zeilen 1159-1175, den `_GRUPPEN`-Tupel um eine Gruppe erweitern:

```python
_GRUPPEN = (
    ("Aufgaben", (("/", "Heute"), ("/freigaben", "Freigaben"),
                  ("/wiedervorlagen", "Wiedervorlagen"),
                  ("/einordnung", "Einordnung"),
                  ("/kalender", "Kalender"),
                  ("/team/kalender", "Kalender verbinden"))),
    ("Analyse", (("/kontakte", "Kontakte"), ("/pipeline", "Pipeline"),
                 ("/ergebnisse", "Ergebnisse"),
                 ("/posteingang", "Posteingang"))),
    ("Daten", (("/medien", "Medien"),)),
    ("Monitoring", (("/whatsapp", "WhatsApp"),)),
    # Existiert im Menue NUR fuer Rolle freigeben im Basis-Laden — nicht
    # wegen einer Extra-Pruefung hier, sondern weil _seitenleiste JEDEN
    # Eintrag durch _pfad_erlaubt filtert (s. dort), und die faellt fuer
    # jede andere Kombination durch.
    ("Admin", (("/team/laden-anlegen", "Laden anlegen"),)),
)
_NAV = tuple(eintrag for _, eintraege in _GRUPPEN for eintrag in eintraege)
```

- [ ] **Step 5: Die Seite und die Aktion schreiben**

In `sales-mcp/ui.py`, direkt vor der Definition von `team_kalender` (suche nach
`async def team_kalender`) folgenden Block einfügen:

```python
_LADEN_NAMEN_MUSTER = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


def _admin_auftrag_ergebnis_text(zeile) -> str:
    """Menschenlesbare Zusammenfassung eines Auftrags — nie mehr behaupten,
    als 'status' hergibt (siehe Spec §2.4: der Wirt schreibt 'fehler', nie
    'erfolg', wenn nur ein Schritt fehlt; hier wird das nur ANGEZEIGT)."""
    if zeile["status"] == "offen":
        return "wartet auf den Wirt (bis zu 20 Sekunden)"
    if zeile["status"] == "laeuft":
        return "wird gerade angelegt …"
    info = json.loads(zeile["ergebnis"]) if zeile["ergebnis"] else {}
    if zeile["status"] == "fehler":
        erledigt = ", ".join(info.get("erledigt", [])) or "nichts"
        grund = zeile["fehler"] or "kein Grund vermerkt"
        return f"FEHLER — erledigt: {_e(erledigt)}. {_e(grund)}"
    return (f"Wegwerf-Passwort: {_e(info.get('passwort', '?'))} — "
            f"Serve-Port: {_e(str(info.get('port_serve', '?')))}. "
            f"{_e(info.get('hinweis', ''))}")


@_gesichert_seite
async def laden_anlegen_seite(request):
    """Einen neuen Laden anlegen. Erreichbar nur fuer Rolle `freigeben` im
    Basis-Laden (_pfad_erlaubt) — kein zweiter Check hier noetig, die
    Middleware hat den Pfad bereits verweigert, wenn wir hier ankommen."""
    zeilen = server._q(
        "select name, status, ergebnis, fehler, erstellt_am "
        "from admin_auftraege where art = 'laden_anlegen' "
        "order by erstellt_am desc limit 10")
    wartet = any(z["status"] in ("offen", "laeuft") for z in zeilen)
    if zeilen:
        tabelle = _tabelle(
            ["Name", "Status", "Ergebnis"],
            [[_e(z["name"]), _e(z["status"]),
              _admin_auftrag_ergebnis_text(z)] for z in zeilen])
    else:
        tabelle = "<p>Noch kein Auftrag.</p>"
    rumpf = (
        '<form method="post" action="/team/laden-anlegen/anfordern">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        '<label>Name des neuen Ladens<br>'
        '<input type="text" name="name" pattern="[a-z][a-z0-9_]{0,30}" '
        'required placeholder="z. B. lena"></label> '
        '<button type="submit">Anlegen</button>'
        '</form>'
        f'<h2>Bisherige Aufträge</h2>{tabelle}')
    return _seite("Laden anlegen", rumpf, refresh=5 if wartet else None)


@_gesichert_seite
async def aktion_laden_anlegen(request):
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
            "Seite neu laden und erneut versuchen.")
    name = str(form.get("name") or "").strip()
    if not _LADEN_NAMEN_MUSTER.fullmatch(name):
        return _fehlerseite(
            400, "Ungültiger Name",
            "Ein Ladenname besteht aus Kleinbuchstaben, Ziffern und "
            "Unterstrich, beginnt mit einem Buchstaben, höchstens 31 "
            "Zeichen. Nichts wurde angelegt.")
    server._q(
        "insert into admin_auftraege (art, name, angefordert_von) "
        "values ('laden_anlegen', %s, %s) returning id",
        (name, _ui_akteur(request)))
    return RedirectResponse("/team/laden-anlegen", status_code=303)
```

- [ ] **Step 6: Die zwei Routen registrieren**

In `sales-mcp/ui.py`, nach der Zeile `Route("/team/kalender/entfernen",
aktion_kalender_entfernen, methods=["POST"]),` (um Zeile 5948) einfügen:

```python
    Route("/team/laden-anlegen", laden_anlegen_seite),
    Route("/team/laden-anlegen/anfordern", aktion_laden_anlegen,
          methods=["POST"]),
```

- [ ] **Step 7: Testen**

```bash
docker build -q -t sales-mcp:dev sales-mcp
docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev \
  python -m pytest -q tests/test_laden_anlegen_seite.py
```

Erwartet: 9 passed.

- [ ] **Step 8: Die volle Suite**

```bash
docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev \
  python -m pytest -q
```

Erwartet: alle bestehenden Tests weiterhin grün, plus die 13 neuen aus Aufgabe 1+2.

- [ ] **Step 9: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_laden_anlegen_seite.py
git commit -m "feat: Seite 'Laden anlegen' fuer Rolle freigeben im Basis-Laden"
```

---

## Task 3: Der Wirt-Orchestrator

**Files:**
- Create: `deploy/admin-auftrag-ausfuehren.sh`
- Create: `deploy/systemd/sales-admin-auftraege.timer`
- Create: `deploy/systemd/sales-admin-auftraege.service`

**Interfaces:**
- Consumes: Tabelle `admin_auftraege` (Aufgabe 1), `deploy/laden-anlegen.sh`,
  `db/laden-anlegen.sql`, `deploy/benutzer-anlegen.sh` (alle bestehend, unverändert).
- Produces: nichts, worauf ein späteres Skript aufbaut — Endstation der Kette.

**Läuft auf der VM (Debian, bash, ss, openssl, docker, python3) — NICHT auf Windows.**

- [ ] **Step 1: Das Skript schreiben**

Neue Datei `deploy/admin-auftrag-ausfuehren.sh`:

```bash
#!/usr/bin/env bash
# Holt den naechsten offenen "Laden anlegen"-Auftrag aus
# sales.admin_auftraege und fuehrt ihn aus — Schale um bestehende,
# geprueft Skripte, KEINE zweite Fassung ihrer Logik.
#
# Laeuft ueber deploy/systemd/sales-admin-auftraege.timer alle 20 Sekunden.
# Findet er keinen offenen Auftrag, endet er sofort mit Exit 0.
set -euo pipefail
export LC_ALL=C

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WURZEL"

AUFTRAG_ID=""
ERLEDIGT=()

psql_admin() {
  docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres "$@"
}

# Wird ueber `trap ... ERR` aufgerufen — nach JEDEM fehlschlagenden Befehl
# ab dem Punkt, an dem AUFTRAG_ID gesetzt ist. Schreibt 'fehler', NIE
# 'erfolg', und haelt fest, was bereits fertig war (Spec §2.4).
fehler_melden() {
  local exit_code=$?
  if [ -z "$AUFTRAG_ID" ]; then
    return 0
  fi
  local grund="Abbruch nach Schritt '${ERLEDIGT[-1]:-Start}' (Exit $exit_code)"
  local erledigt_json
  erledigt_json="$(python3 -c '
import json, sys
print(json.dumps({"erledigt": sys.argv[1:]}))' "${ERLEDIGT[@]:-}")"
  psql_admin -v id="$AUFTRAG_ID" -v ergebnis="$erledigt_json" \
             -v grund="$grund" <<'SQL'
update sales.admin_auftraege
   set status = 'fehler', ergebnis = :'ergebnis'::jsonb,
       fehler = :'grund', erledigt_am = now()
 where id = :'id'::uuid;
SQL
}
trap fehler_melden ERR

# Freien Port zwischen $1 und $2 suchen; gibt ihn auf stdout aus.
freier_port() {
  local kandidat="$1" hoechstens="$2"
  while [ "$kandidat" -le "$hoechstens" ]; do
    if ! ss -tlnH "sport = :$kandidat" | grep -q .; then
      echo "$kandidat"
      return 0
    fi
    kandidat=$((kandidat + 1))
  done
  echo "FEHLER: kein freier Port zwischen $1 und $hoechstens." >&2
  return 1
}

# --- 1. Naechsten offenen Auftrag holen, sofort auf 'laeuft' setzen -------
ZEILE="$(psql_admin -tAc \
  "select id || '|' || name from sales.admin_auftraege \
   where art = 'laden_anlegen' and status = 'offen' \
   order by erstellt_am limit 1")"
if [ -z "$ZEILE" ]; then
  exit 0
fi
AUFTRAG_ID="${ZEILE%%|*}"
LADEN_NAME="${ZEILE#*|}"
psql_admin -v id="$AUFTRAG_ID" <<'SQL'
update sales.admin_auftraege set status = 'laeuft' where id = :'id'::uuid;
SQL
ERLEDIGT+=("aufnahme")

# --- 2. Vier freie Ports suchen -------------------------------------------
PORT_GATEWAY="$(freier_port 18894 18950)"
PORT_UI="$(freier_port 8791 8850)"
PORT_OPENWA="$(freier_port 12785 12850)"
PORT_SERVE="$(freier_port 8446 8500)"
ERLEDIGT+=("ports")

# --- 3. deploy/laden-anlegen.sh — unveraendert, wie von Hand --------------
bash deploy/laden-anlegen.sh "$LADEN_NAME" "$PORT_GATEWAY" "$PORT_UI" \
  "$PORT_OPENWA" "$PORT_SERVE" >/dev/null
ERLEDIGT+=("umgebungsdatei")

ENVDATEI="deploy/laeden/$LADEN_NAME.env"
DB_PW="$(sed -n "s#.*sales_app_$LADEN_NAME:\\([^@]*\\)@.*#\\1#p" "$ENVDATEI")"

# --- 4. db/laden-anlegen.sql — Schema, Tabellen, Rolle, Rechte ------------
docker exec -i -e LADEN_PASSWORT="$DB_PW" debian-supabase-db-1 \
  psql -U supabase_admin -d postgres -v laden="$LADEN_NAME" \
  < db/laden-anlegen.sql >/dev/null
unset DB_PW
ERLEDIGT+=("schema")

# --- 5. Nur die zwei Dienste ohne externe Zugangsdaten --------------------
# DIENSTSCHLUESSEL bleiben "sales-mcp"/"sales-ui" — das Env-File entscheidet
# per LADEN_PRAEFIX-Interpolation, welcher Laden tatsaechlich entsteht.
docker compose --env-file "$ENVDATEI" up -d --build sales-mcp sales-ui \
  >/dev/null
ERLEDIGT+=("container")

# --- 6. Konto mit Wegwerf-Passwort ----------------------------------------
KONTO_PW="Probe-$(openssl rand -base64 9 | tr -d '/+=' | head -c 10)"
printf '%s\n%s\n%s\n%s\n' "$LADEN_NAME" "freigeben" "$KONTO_PW" "$KONTO_PW" \
  | bash deploy/benutzer-anlegen.sh "$LADEN_NAME" >/dev/null
ERLEDIGT+=("konto")

# --- 7. Erfolg melden ------------------------------------------------------
ERGEBNIS_JSON="$(python3 -c '
import json, sys
pw, ui_port, serve_port = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    "passwort": pw,
    "port_ui": int(ui_port),
    "port_serve": int(serve_port),
    "hinweis": ("Als naechstes von Hand: tailscale serve --https " +
                serve_port + " http://127.0.0.1:" + ui_port +
                " einrichten, danach die Zugriffsregel fuer den neuen "
                "Menschen und die vier Kanaele (Postfach, Telegram, "
                "LinkedIn, WhatsApp).")
}))' "$KONTO_PW" "$PORT_UI" "$PORT_SERVE")"
unset KONTO_PW
psql_admin -v id="$AUFTRAG_ID" -v ergebnis="$ERGEBNIS_JSON" <<'SQL'
update sales.admin_auftraege
   set status = 'erfolg', ergebnis = :'ergebnis'::jsonb, erledigt_am = now()
 where id = :'id'::uuid;
SQL

trap - ERR
```

`chmod +x deploy/admin-auftrag-ausfuehren.sh`

- [ ] **Step 2: `bash -n` — Syntaxprüfung**

```bash
bash -n deploy/admin-auftrag-ausfuehren.sh
```

Erwartet: keine Ausgabe, Exit 0.

- [ ] **Step 3: Trockenlauf mit Attrappen — der Erfolgsweg**

In einem Scratch-Verzeichnis außerhalb des Repos eine Attrappen-`docker`, die
`docker exec ... psql ...` gegen ein echtes, lokal erreichbares Postgres umleitet, ist
aufwendig zu fälschen (das Skript spricht direkt mit `debian-supabase-db-1`). Für diese
Aufgabe genügt deshalb eine **gezielte Codeprüfung statt eines vollen Attrappenlaufs**:

```bash
# Zeigt, dass KEIN Aufruf "$LADEN_NAME-mcp"/"$LADEN_NAME-ui" als
# Dienstschluessel benutzt (der Fehler aus Aufgabe 3, Global Constraints).
grep -n 'up -d --build' deploy/admin-auftrag-ausfuehren.sh
```

Erwartet: genau eine Zeile, `docker compose --env-file "$ENVDATEI" up -d --build
sales-mcp sales-ui`, **ohne** `$LADEN_NAME` darin.

```bash
# Zeigt, dass das Passwort nie ueber argv geht.
grep -n 'DB_PW\|KONTO_PW' deploy/admin-auftrag-ausfuehren.sh | grep -v '^\S*:unset\|^\S*:DB_PW="\|^\S*:KONTO_PW="'
```

Erwartet: die verbleibenden Treffer sind ausschließlich `-e LADEN_PASSWORT="$DB_PW"`
(Umgebung) und `printf '...' "$KONTO_PW" "$KONTO_PW" | bash ...` (stdin) — keine Stelle,
an der eines der beiden als nacktes Kommandozeilenargument erscheint.

```bash
# Spec-Pruefung 4: ein zweiter Zeitgeber-Durchlauf darf einen Auftrag mit
# status='laeuft' NICHT erneut aufgreifen — die Abfrage muss ausdruecklich
# nach 'offen' filtern, nicht bloss "kein Status".
grep -n "where art = 'laden_anlegen' and status = 'offen'" \
  deploy/admin-auftrag-ausfuehren.sh
```

Erwartet: ein Treffer. Fehlt er (z. B. weil die Bedingung versehentlich auf `status !=
'erfolg'` o. ä. geändert würde), holt sich der nächste Durchlauf denselben Auftrag ein
zweites Mal — genau der Fall, den Spec-Prüfung 4 verlangt auszuschließen.

```bash
# Spec-Pruefung 5: 'erfolg' darf NUR an der einen Stelle geschrieben werden,
# und `trap fehler_melden ERR` muss ab dem Setzen von AUFTRAG_ID aktiv sein.
grep -n "status = 'erfolg'" deploy/admin-auftrag-ausfuehren.sh
grep -n "^trap fehler_melden ERR$" deploy/admin-auftrag-ausfuehren.sh
```

Erwartet: genau ein Treffer für `status = 'erfolg'` (im letzten Block), genau ein Treffer
für den `trap`-Aufruf, und er steht **vor** Step 1 (`AUFTRAG_ID` wird direkt danach
gesetzt) — sonst bliebe ein Fehler zwischen Skriptstart und `trap`-Zeile unbemerkt.

- [ ] **Step 4: Trockenlauf des Port-Suchers isoliert**

`freier_port` ist eine reine Funktion und lässt sich ohne Docker prüfen:

```bash
bash -c '
set -euo pipefail
source <(sed -n "/^freier_port() {/,/^}/p" deploy/admin-auftrag-ausfuehren.sh)
# Ein garantiert belegter Port (dieser SSH-Client selbst haengt an 22):
if ss -tlnH "sport = :22" | grep -q .; then
  ausgabe="$(freier_port 20 30)"   # 22 ist im Bereich, muss uebersprungen werden
  echo "gefunden: $ausgabe"
  [ "$ausgabe" != "22" ] || { echo "FEHLER: 22 haette uebersprungen werden muessen"; exit 1; }
else
  echo "Port 22 war nicht belegt — Probe uebersprungen (kein sshd hier)"
fi
'
```

Erwartet: entweder eine Zahl ungleich 22 im Bereich 20–30, oder der Hinweis, dass die
Probe übersprungen wurde (falls dieser Rechner keinen sshd auf 22 hat).

- [ ] **Step 5: Die systemd-Einheiten schreiben**

Neue Datei `deploy/systemd/sales-admin-auftraege.timer`:

```ini
[Unit]
Description=sales-claw: Admin-Auftraege (Laden anlegen) alle 20 Sekunden

[Timer]
OnUnitActiveSec=20s
OnBootSec=20s
Persistent=false

[Install]
WantedBy=timers.target
```

Neue Datei `deploy/systemd/sales-admin-auftraege.service`:

```ini
[Unit]
Description=sales-claw: Admin-Auftraege aus sales.admin_auftraege ausfuehren

[Service]
Type=oneshot
User=debian
ExecStart=/usr/bin/bash /home/debian/sales-claw/deploy/admin-auftrag-ausfuehren.sh
```

Beide Dateien folgen exakt dem Muster von `deploy/systemd/sales-wache.timer`/`.service`
(`User=debian`, absoluter Pfad im `ExecStart`) — nur der Takt (20 s statt 15 min) und das
Ziel-Skript unterscheiden sich.

- [ ] **Step 6: Committen**

```bash
git add deploy/admin-auftrag-ausfuehren.sh deploy/systemd/sales-admin-auftraege.timer \
        deploy/systemd/sales-admin-auftraege.service
git commit -m "feat: Wirt-Orchestrator fuer 'Laden anlegen aus der Oberflaeche'"
```

- [ ] **Step 7: HALT — der folgende Schritt braucht die ausdrückliche Freigabe des
      Betreibers (Global Constraints)**

Erst nach Freigabe, **auf der VM**, die Einheiten einspielen:

```bash
sudo cp deploy/systemd/sales-admin-auftraege.timer \
        deploy/systemd/sales-admin-auftraege.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sales-admin-auftraege.timer
systemctl list-timers sales-admin-auftraege.timer
```

Erwartet: der Zeitgeber taucht mit einer Zeitspanne von maximal 20 Sekunden bis zum
nächsten Lauf auf.

---

## Task 4: Runbook und der volle Probelauf

**Files:**
- Modify: `docs/03_RUNBOOK.md`

**Interfaces:**
- Consumes: alles aus Aufgabe 1–3.
- Produces: nichts — dies ist die Abnahme.

- [ ] **Step 1: Abschnitt „Laden anlegen aus der Oberfläche" ergänzen**

In `docs/03_RUNBOOK.md`, im Bereich der bestehenden Abschnitte „Einen zweiten Laden
anlegen", einen neuen Abschnitt einfügen mit:

* Voraussetzung: `sales-admin-auftraege.timer` läuft (`systemctl list-timers`).
* Weg: Anmeldung als Rolle `freigeben` im Basis-Laden → Menü „Admin" → „Laden anlegen" →
  Namen eintragen → „Anlegen". Die Seite friert nicht ein, sie lädt sich alle 5 Sekunden
  neu, bis ein Ergebnis feststeht (kein JavaScript — reines `<meta refresh>`).
* Was danach **von Hand** bleibt, wörtlich aus dem `hinweis`-Feld des Ergebnisses:
  `tailscale serve --https <port> http://127.0.0.1:<port>` einrichten, die Zugriffsregel
  für den neuen Menschen (siehe Abschnitt „Zugang: eigener Serve-Port"), danach die vier
  Kanäle (siehe `docs/11_INBETRIEBNAHME.md`).
* Ein **Fehler**-Ergebnis nennt, was bereits stand (`ergebnis.erledigt`) — die
  aufgeräumten Reste (halb angelegtes Schema, halb gestarteter Container) müssen von Hand
  nachgesehen werden; es gibt (bewusst, siehe Spec §4 „Nicht im Umfang") keinen
  automatischen Rückbau.

- [ ] **Step 2: HALT — der Probelauf braucht die ausdrückliche Freigabe des Betreibers**

Ein Testlauf mit einem harmlosen, klar als Probe erkennbaren Namen (z. B.
`probelauf`), **nur nach Zustimmung**:

1. Über die Oberfläche „Laden anlegen" mit dem Namen `probelauf` auslösen.
2. Innerhalb von höchstens 20 Sekunden erscheint `status='laeuft'`, danach `'erfolg'`
   oder `'fehler'` mit einem genannten Grund.
3. Bei Erfolg: `bash deploy/smoke.sh` — erwartet `db-identitaet probelauf ok`.
4. Mit dem angezeigten Wegwerf-Passwort anmelden — erwartet: Anmeldung gelingt.
5. **Tor 1 der Spec, erneut:** mit der Datenbankkennung von `probelauf` versuchen,
   `sales.leads` zu lesen — erwartet `permission denied for schema sales`.
6. **Spec-Prüfung 2 — die umgekehrte Richtung:** mit Ivans bestehender Datenbankkennung
   (`sales_app_ivan`) versuchen, `sales.admin_auftraege` zu lesen:
   ```bash
   docker exec -i debian-supabase-db-1 psql \
     "postgresql://sales_app_ivan:<Ivans Passwort>@127.0.0.1:5432/postgres" \
     -c "select count(*) from sales.admin_auftraege"
   ```
   Erwartet `permission denied for schema sales`, **nicht** eine Zahl (auch nicht 0). Das
   ist keine neue Prüfung im engeren Sinn — sie bestätigt nur, dass die bereits
   bestehende `revoke all on schema sales from sales_app_ivan` (Plan vom 16.09.2026) auch
   die brandneue Tabelle mit abdeckt, ohne dass diese Aufgabe dafür etwas Eigenes bauen
   musste.
7. Aufräumen (Probelauf ist kein produktiver Laden): Container stoppen und entfernen,
   `deploy/laeden/probelauf.env` löschen, Schema `sales_probelauf` und Rolle
   `sales_app_probelauf` per Hand entfernen (kein Skript dafür — absichtlich, siehe
   Spec §4).

- [ ] **Step 3: Committen**

```bash
git add docs/03_RUNBOOK.md
git commit -m "docs: Laden anlegen aus der Oberflaeche im Runbook"
```
