# Tailscale-Einladungen aus der Oberfläche — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Knopf im Basis-Laden, mit dem die Rolle `freigeben` eine Tailscale-Einladung
per E-Mail-Adresse auslöst, ohne SSH auf die VM.

**Architecture:** Dieselbe Infrastruktur wie „Laden anlegen aus der Oberfläche"
(`sales.admin_auftraege`, der 20-Sekunden-Zeitgeber `deploy/admin-auftrag-ausfuehren.sh`,
das Rollen-Tor `_pfad_erlaubt`) bekommt eine zweite Auftragsart. Die Oberfläche legt eine
Zeile an, der Wirt liest sie ab und ruft Tailscales API auf — kein neuer Mechanismus, keine
neue Tabelle, kein neuer Zeitgeber.

**Tech Stack:** PostgreSQL (psycopg3, `sales.admin_auftraege`), Starlette (`sales-mcp/ui.py`),
Bash (`deploy/admin-auftrag-ausfuehren.sh`), `curl` gegen `api.tailscale.com`, `python3` für
JSON-Auf-/Abbau (wie im bestehenden Skript bereits üblich).

**Spec:** `docs/superpowers/specs/2026-09-22-tailscale-einladung-design.md`

## Global Constraints

- Schema-Namen-Muster für Läden bleibt `^[a-z][a-z0-9_]{0,30}$` — unverändert, betrifft
  diesen Plan nicht direkt.
- **Niemals** ein Geheimnis (Passwort, API-Schlüssel) über `argv` — weder `-v name=wert`
  bei `psql`, noch `-e NAME=wert`/`-H "Header: wert"` bei `docker exec`/`curl`. Immer per
  vorangestellter Umgebungszuweisung + bloßer Namensform (`NAME="$wert" docker exec -e
  NAME ...`), bei `curl` per `-K -` mit der Konfigurationszeile über `stdin`.
- **Niemals** `docker compose ... up -d` ohne explizite Dienstnamen.
- `sales_app` bekommt auf `admin_auftraege` nur `select, insert` — nie `update`/`delete`.
  Nur der Wirt (als `supabase_admin`, über `docker exec`) ändert `status`/`ergebnis`/`fehler`.
- Jeder Fehlschlag endet mit `status = 'fehler'` — nie `'erfolg'`, wenn nicht wirklich alles
  gelang.
- `LC_ALL=C` in jedem neuen/geänderten Bash-Skript (dieses Skript setzt es bereits global).
- Kein JavaScript — die Oberfläche fährt `default-src 'none'`. Das bestehende
  `<meta http-equiv="refresh">`-Muster (`_seite(..., refresh=N)`) bleibt der einzige Weg,
  auf ein Ergebnis zu warten.
- Kein Subagent führt einen echten Produktionsschritt (Zugangsdaten-Datei auf der VM
  anlegen, systemd neu laden, eine echte E-Mail verschicken) ohne die ausdrückliche
  Freigabe des Betreibers aus.

---

## Vorab gemessen (gilt für alle Tasks)

* `db/provision.sql:357-375` — der bestehende `admin_auftraege`-Block, `art text not null
  check (art = 'laden_anlegen')`, `name` mit hartem Regex-CHECK, keine `email`-Spalte.
* `db/provision.sql:159-161` und `:206-221` zeigen das idiomatische Muster für „CHECK auf
  einer bereits bestehenden Tabelle ändern": `alter table ... drop constraint if exists
  <name>` gefolgt von `alter table ... add constraint <name> check (...)` — ein CHECK lässt
  sich nicht nachrüsten, nur ersetzen. Postgres benennt einen unbenannten Spalten-CHECK
  standardmäßig `<tabelle>_<spalte>_check` — genau das nutzen `benutzer_rolle_check`,
  `drafts_channel_check`, `kalender_quellen_url_check` bereits als Namen.
* Lokale Testdatenbank: `docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 <
  db/provision.sql` spielt Änderungen an `provision.sql` in die lokale `sales_test`-Instanz
  ein — **nach jeder Änderung an `provision.sql` erneut ausführen, bevor die Testsuite
  läuft** (idempotent, ein wiederholter Lauf ist folgenlos).
* `sales-mcp/mailadresse.py` — eine bereits bestehende, geprüfte E-Mail-Validierung
  (`pruefe(roh) -> (adresse, None) | (None, fehler)`), Whitelist-basiert, schließt
  Kopfzeilen-Injektion (`\r`, `\n`), Kommas/Semikolons und Mehrfach-`@` aus. `ui.py`
  importiert sie noch nicht, kann es aber gefahrlos (kein Zyklus: `mailadresse.py` importiert
  selbst nichts Projekteigenes).
* `sales-mcp/ui.py:520-536` — `_pfad_erlaubt`, heute hart auf den einen Pfad
  `/team/laden-anlegen` verdrahtet.
* `sales-mcp/ui.py:1172-1193` — `_GRUPPEN`, die „Admin"-Gruppe hat heute einen Eintrag.
* `sales-mcp/ui.py:4012-4086` — `_admin_auftrag_ergebnis_text`, `laden_anlegen_seite`,
  `aktion_laden_anlegen` — das Muster, das dieser Plan für die zweite Auftragsart mitbenutzt.
* `sales-mcp/ui.py:6049-6051` — die bestehenden Routen-Einträge.
* `deploy/admin-auftrag-ausfuehren.sh` (vollständig gelesen) — `psql_admin()`,
  `fehler_melden()` (per `trap ... ERR`), `freier_port()`, dann sieben nummerierte Schritte
  für `art = 'laden_anlegen'`. Schritt 0 (Selbstheilung) und Schritt 1 (Auftrag abholen)
  filtern heute hart auf `art = 'laden_anlegen'`.
* `deploy/systemd/sales-admin-auftraege.timer`/`.service` laufen bereits live auf der VM
  (`OnUnitActiveSec=20s`) — **keine neuen systemd-Einheiten nötig**, nur eine Ergänzung am
  bestehenden `.service` (`EnvironmentFile=`).
* `.env.example` (Repo-Wurzel) zeigt das Namens-Muster für ein Beispiel-Secret-File, das
  NICHT auf `*.env` endet und darum von der `.gitignore`-Regel `*.env` (Zeile 2-3)
  verschont bleibt — derselbe Trick trägt `tailscale-admin.env.example` (verfolgt) neben
  der echten, nie eingecheckten `tailscale-admin.env` (endet auf `.env`, von der
  bestehenden Regel automatisch erfasst — keine `.gitignore`-Änderung nötig).
* Tailscales API (recherchiert, siehe Spec §1.2): `POST
  /api/v2/tailnet/{tailnet}/user-invites`, Felder `email`/`role`, verlangt einen
  personengebundenen Schlüssel (kein OAuth-Client). Antwort kann `inviteUrl` enthalten.
  Das genaue Fehler-JSON-Format war nicht abschließend zu klären — der Code fragt sowohl
  `message` als auch `error` ab, mit rohem Text als letztem Rückfall.

---

### Task 1: Datenbank — zweite Auftragsart, `email`-Spalte

**Files:**
- Modify: `db/provision.sql:357-375`
- Modify: `sales-mcp/tests/test_admin_auftraege_tabelle.py`

**Interfaces:**
- Produces: Spalte `sales.admin_auftraege.email` (nullable `text`); `art` akzeptiert jetzt
  `'laden_anlegen'` **und** `'tailscale_einladen'`; `name` ist nullable, mit einem CHECK,
  der es nur für `art = 'laden_anlegen'` erzwingt; `email` mit einem CHECK, der es nur für
  `art = 'tailscale_einladen'` erzwingt (beide CHECKs behandeln `NULL` explizit als
  Verstoß, nicht als stillen Durchlass — SQL-CHECKs lassen `NULL`-Ausdrücke sonst
  passieren). Task 2 und Task 3 lesen/schreiben diese Spalte.

- [ ] **Step 1: Den bestehenden `admin_auftraege`-Block in `db/provision.sql` erweitern**

Ersetze den Block `db/provision.sql:357-375`:

```sql
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

durch:

```sql
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
    -- Tailscale-Einladungen (Spec 2026-09-22-tailscale-einladung-design,
    -- §2.1): zweite Auftragsart in derselben Tabelle statt einer zweiten
    -- Tabelle/eines zweiten Zeitgebers — `art` ist genau als
    -- Unterscheidungsmerkmal angelegt. `add column if not exists` und
    -- `drop constraint if exists` + `add constraint`, weil die Tabelle auf
    -- beiden Schemata laengst existiert (dasselbe Muster wie beim
    -- drafts_channel_check/benutzer_rolle_check weiter oben in dieser
    -- Datei) — ein CHECK laesst sich nicht nachruesten, nur ersetzen.
    --
    -- Beide neuen CHECKs nennen `is not null` ausdruecklich: ein CHECK der
    -- Form "art <> 'x' or email ~ muster" LAESST eine NULL-email fuer
    -- art='x' durch, weil "NULL ~ muster" in SQL weder wahr noch falsch
    -- ist, sondern NULL — und ein CHECK gilt bei einem NULL-Ergebnis als
    -- NICHT verletzt. Ohne "is not null" waere die Pflichtangabe wirkungslos.
    execute format('alter table %I.admin_auftraege '
                   'add column if not exists email text', s);
    execute format('alter table %I.admin_auftraege '
                   'alter column name drop not null', s);
    execute format('alter table %I.admin_auftraege '
                   'drop constraint if exists admin_auftraege_art_check', s);
    execute format($chk$alter table %I.admin_auftraege add constraint
      admin_auftraege_art_check
      check (art in ('laden_anlegen', 'tailscale_einladen'))$chk$, s);
    execute format('alter table %I.admin_auftraege '
                   'drop constraint if exists admin_auftraege_name_check', s);
    execute format($chk$alter table %I.admin_auftraege add constraint
      admin_auftraege_name_check
      check (art <> 'laden_anlegen'
             or (name is not null and name ~ '^[a-z][a-z0-9_]{0,30}$'))$chk$, s);
    execute format('alter table %I.admin_auftraege '
                   'drop constraint if exists admin_auftraege_email_check', s);
    execute format($chk$alter table %I.admin_auftraege add constraint
      admin_auftraege_email_check
      check (art <> 'tailscale_einladen'
             or (email is not null
                 and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'))$chk$, s);
  end loop;
end $$;
```

- [ ] **Step 2: Lokale Testdatenbank neu provisionieren**

Run: `docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 < db/provision.sql`
Expected: Zeilen `ALTER TABLE`/`DO` ohne `ERROR`, `NOTICE: ... already exists, skipping` für
alles Vorbestehende.

- [ ] **Step 3: `test_admin_auftraege_tabelle.py` — bestehende Tests anpassen**

In `sales-mcp/tests/test_admin_auftraege_tabelle.py`, ersetze
`test_tabelle_existiert_mit_den_erwarteten_spalten`:

```python
def test_tabelle_existiert_mit_den_erwarteten_spalten():
    zeilen = server._q(
        "select column_name from information_schema.columns "
        "where table_schema = 'sales_test' and table_name = 'admin_auftraege' "
        "order by ordinal_position")
    spalten = [z["column_name"] for z in zeilen]
    assert spalten == ["id", "art", "name", "angefordert_von", "status",
                        "ergebnis", "fehler", "erstellt_am", "erledigt_am",
                        "email"]
```

Ersetze `test_art_erlaubt_nur_laden_anlegen`:

```python
def test_art_erlaubt_nur_die_beiden_bekannten_werte():
    with server.pool.connection() as conn:
        try:
            conn.execute(
                "insert into admin_auftraege (art, name, angefordert_von) "
                "values ('etwas_anderes', 'probe', 'test')")
            assert False, "haette am CHECK scheitern muessen"
        except Exception as e:
            assert "23514" in str(getattr(e, "sqlstate", "") or e)
        conn.rollback()
        # Positivprobe: die zweite Auftragsart ist jetzt erlaubt.
        conn.execute(
            "insert into admin_auftraege (art, email, angefordert_von) "
            "values ('tailscale_einladen', 'kolleg@example.com', 'test')")
        conn.rollback()
```

- [ ] **Step 4: Vier neue Tests anfügen**

Am Ende von `sales-mcp/tests/test_admin_auftraege_tabelle.py` anfügen:

```python
def test_name_darf_bei_tailscale_einladen_leer_sein():
    """Die alte Fassung erzwang 'name not null' fuer JEDE Zeile — eine
    Einladung ohne Ladennamen waere daran gescheitert, obwohl sie gar
    keinen braucht."""
    with server.pool.connection() as conn:
        conn.execute(
            "insert into admin_auftraege (art, email, angefordert_von) "
            "values ('tailscale_einladen', 'kolleg@example.com', 'test')")
        conn.rollback()


def test_name_darf_bei_laden_anlegen_nicht_leer_sein():
    """Deckt die NULL-Luecke ab: 'art <> x or name ~ muster' liesse ein
    NULL durch, weil 'NULL ~ muster' weder wahr noch falsch ist. Ohne das
    ausdrueckliche 'is not null' im CHECK waere dieser Test gruen, obwohl
    admin-auftrag-ausfuehren.sh dann mit einem leeren Ladennamen weiterliefe."""
    with server.pool.connection() as conn:
        hat_sqlstate = False
        try:
            conn.execute(
                "insert into admin_auftraege (art, angefordert_von) "
                "values ('laden_anlegen', 'test')")
        except Exception as e:
            hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
        assert hat_sqlstate, "name=NULL haette am CHECK scheitern muessen"
        conn.rollback()


@pytest.mark.parametrize("schlechte_email", [
    "keineadresse", "kein-at-zeichen.de", "ohne-punkt@domain",
    "mit leerzeichen@domain.de", ""])
def test_email_erzwingt_ein_vernuenftiges_muster(schlechte_email):
    with server.pool.connection() as conn:
        hat_sqlstate = False
        try:
            conn.execute(
                "insert into admin_auftraege (art, email, angefordert_von) "
                "values ('tailscale_einladen', %s, 'test')", (schlechte_email,))
        except Exception as e:
            hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
        assert hat_sqlstate, f"'{schlechte_email}' haette am CHECK scheitern muessen"
        conn.rollback()


def test_email_darf_bei_tailscale_einladen_nicht_leer_sein():
    """Dieselbe NULL-Luecke wie bei name oben, gespiegelt fuer email."""
    with server.pool.connection() as conn:
        hat_sqlstate = False
        try:
            conn.execute(
                "insert into admin_auftraege (art, angefordert_von) "
                "values ('tailscale_einladen', 'test')")
        except Exception as e:
            hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
        assert hat_sqlstate, "email=NULL haette am CHECK scheitern muessen"
        conn.rollback()
```

Diese vier Tests brauchen `import pytest` am Dateikopf — prüfen, ob es schon steht (die
bestehende Datei nutzt bisher kein `pytest.mark.parametrize`); falls nicht, `import pytest`
direkt unter `import os` ergänzen.

- [ ] **Step 5: Tests laufen lassen**

Run: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e
SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest
tests/test_admin_auftraege_tabelle.py -v`
Expected: alle Tests grün (9 insgesamt: 5 bestehende, davon 2 ersetzt, plus 4 neue — netto
9 Funktionen in der Datei nach diesem Schritt).

- [ ] **Step 6: Commit**

```bash
git add db/provision.sql sales-mcp/tests/test_admin_auftraege_tabelle.py
git commit -m "feat(sales-claw): admin_auftraege um Tailscale-Einladungen erweitern"
```

---

### Task 2: Oberfläche — neue Seite, Rollen-Tor, Menü

**Files:**
- Modify: `sales-mcp/ui.py`
- Create: `sales-mcp/tests/test_tailscale_einladen_seite.py`

**Interfaces:**
- Consumes: `sales.admin_auftraege` mit Spalte `email` und `art in ('laden_anlegen',
  'tailscale_einladen')` (Task 1). `mailadresse.pruefe(roh) -> (adresse, None) | (None,
  fehler)` (bereits vorhanden, `sales-mcp/mailadresse.py`).
- Produces: Routen `GET/POST /team/tailscale-einladen`,
  `POST /team/tailscale-einladen/anfordern`. Task 3 liest/schreibt dieselbe Tabelle über
  `art = 'tailscale_einladen'`, unabhängig von dieser Seite — keine Python-Schnittstelle
  zwischen Task 2 und Task 3.

- [ ] **Step 1: `mailadresse` importieren**

In `sales-mcp/ui.py`, Zeile 202-204 (`import kalender` / Leerzeile / `import server`)
ersetzen durch:

```python
import kalender
import mailadresse

import server
```

- [ ] **Step 2: `_pfad_erlaubt` auf beide Admin-Pfade verallgemeinern**

Ersetze `sales-mcp/ui.py:520-536` (die ganze Funktion `_pfad_erlaubt` bis zum ersten
`return True`-Zweig):

```python
_ADMIN_BASIS_PFADE = ("/team/laden-anlegen", "/team/tailscale-einladen")


def _pfad_erlaubt(rolle: str, pfad: str) -> bool:
    """Darf diese Rolle diesen Pfad sehen? `kalender` ist eingeschraenkt,
    jeder Pfad in `_ADMIN_BASIS_PFADE` zusaetzlich auf `freigeben` im
    Basis-Laden — sonst saehe Ivan (selbst mit der Rolle `freigeben` in
    seinem eigenen Laden) Knoepfe, die auf dem Wirt handeln (Container
    erzeugen, eine Tailscale-Einladung mit dem persoenlichen Schluessel
    des Betreibers verschicken).

    `sales_test` zaehlt hier als Basis-Laden, nicht als eigener Laden: die
    Tabelle admin_auftraege existiert genau dort und in `sales`, nirgends
    sonst (db/provision.sql, hartes array['sales','sales_test'], Aufgabe 1 /
    test_admin_auftraege_tabelle.py::test_admin_auftraege_existiert_in_...);
    der Testcontainer verbindet ausschliesslich mit `sales_test` (nie mit
    `sales`), waere `sales_test` hier NICHT gleichgestellt, saehe keiner
    der beiden Knoepfe in JEDEM Testlauf niemand — auch nicht die Rolle
    `freigeben` selbst."""
    if any(pfad == p or pfad.startswith(p + "/") for p in _ADMIN_BASIS_PFADE):
        return rolle == "freigeben" and server.SCHEMA in ("sales", "sales_test")
    if rolle != "kalender":
        return True
```

(Der Rest der Funktion — `return any(pfad == p or pfad.startswith(p + "/") for p in
_KALENDER_ROLLE_PFADE)` — bleibt unverändert direkt darunter stehen.)

- [ ] **Step 3: `_GRUPPEN` um den zweiten Admin-Eintrag ergänzen**

In `sales-mcp/ui.py:1192`, ersetze:

```python
    ("Admin", (("/team/laden-anlegen", "Laden anlegen"),)),
```

durch:

```python
    ("Admin", (("/team/laden-anlegen", "Laden anlegen"),
               ("/team/tailscale-einladen", "Team-Mitglied einladen"))),
```

- [ ] **Step 4: `_admin_auftrag_ergebnis_text` um den Tailscale-Zweig erweitern**

Ersetze `sales-mcp/ui.py:4012-4030` (die ganze Funktion):

```python
def _admin_auftrag_ergebnis_text(zeile) -> str:
    """Menschenlesbare Zusammenfassung eines Auftrags — nie mehr behaupten,
    als 'status' hergibt (siehe Spec §2.4: der Wirt schreibt 'fehler', nie
    'erfolg', wenn nur ein Schritt fehlt; hier wird das nur ANGEZEIGT).
    Verzweigt zusaetzlich auf `zeile["art"]`, weil 'erfolg' bei den beiden
    Auftragsarten voellig verschiedene Formen von `ergebnis` traegt."""
    if zeile["status"] == "offen":
        return "wartet auf den Wirt (bis zu 20 Sekunden)"
    if zeile["status"] == "laeuft":
        return ("wird gerade verschickt …" if zeile["art"] == "tailscale_einladen"
                 else "wird gerade angelegt …")
    # K1 (Schlusspruefung des vorigen Untervorhabens): server.pool laeuft
    # mit psycopg3/dict_row — eine jsonb-Spalte kommt bereits als
    # Python-dict zurueck, nicht als String. json.loads() darauf wirft
    # TypeError.
    info = zeile["ergebnis"] or {}
    if zeile["art"] == "tailscale_einladen":
        if zeile["status"] == "fehler":
            return f"FEHLER — {_e(zeile['fehler'] or 'kein Grund vermerkt')}"
        link = info.get("inviteUrl")
        zusatz = f" Link zum Weitergeben: {_e(link)}" if link else ""
        return f"Einladung verschickt.{zusatz}"
    if zeile["status"] == "fehler":
        erledigt = ", ".join(info.get("erledigt", [])) or "nichts"
        grund = zeile["fehler"] or "kein Grund vermerkt"
        return f"FEHLER — erledigt: {_e(erledigt)}. {_e(grund)}"
    return (f"Wegwerf-Passwort: {_e(info.get('passwort', '?'))} — "
            f"Serve-Port: {_e(str(info.get('port_serve', '?')))}. "
            f"{_e(info.get('hinweis', ''))}")
```

- [ ] **Step 5: `laden_anlegen_seite`s Abfrage um `art` ergänzen**

`_admin_auftrag_ergebnis_text` liest jetzt `zeile["art"]` — die bestehende Seite muss es
mitliefern. In `sales-mcp/ui.py`, innerhalb `laden_anlegen_seite` (um Zeile 4038-4041),
ersetze:

```python
    zeilen = server._q(
        "select name, status, ergebnis, fehler, erstellt_am "
        "from admin_auftraege where art = 'laden_anlegen' "
        "order by erstellt_am desc limit 10")
```

durch:

```python
    zeilen = server._q(
        "select art, name, status, ergebnis, fehler, erstellt_am "
        "from admin_auftraege where art = 'laden_anlegen' "
        "order by erstellt_am desc limit 10")
```

- [ ] **Step 6: Die neue Seite und ihre Aktion schreiben**

Direkt nach `aktion_laden_anlegen` (nach `sales-mcp/ui.py:4086`, vor der Leerzeile zu
`team_kalender`) einfügen:

```python
@_gesichert_seite
async def tailscale_einladen_seite(request):
    """Einen neuen Menschen zum Tailnet einladen. Erreichbar nur fuer Rolle
    `freigeben` im Basis-Laden (_pfad_erlaubt) — kein zweiter Check hier
    noetig, die Middleware hat den Pfad bereits verweigert, wenn wir hier
    ankommen. Automatisiert wird ausschliesslich die Einladung selbst —
    die Tailscale-Zugriffsregel bleibt Handarbeit (Spec §4)."""
    zeilen = server._q(
        "select art, email, status, ergebnis, fehler, erstellt_am "
        "from admin_auftraege where art = 'tailscale_einladen' "
        "order by erstellt_am desc limit 10")
    wartet = any(z["status"] in ("offen", "laeuft") for z in zeilen)
    if zeilen:
        tabelle = _tabelle(
            ["E-Mail", "Status", "Ergebnis"],
            [[_e(z["email"]), _e(z["status"]),
              _admin_auftrag_ergebnis_text(z)] for z in zeilen])
    else:
        tabelle = "<p>Noch kein Auftrag.</p>"
    rumpf = (
        '<form method="post" action="/team/tailscale-einladen/anfordern">'
        f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}">'
        '<label>E-Mail-Adresse des neuen Menschen<br>'
        '<input type="email" name="email" required '
        'placeholder="z. B. kolleg@example.com"></label> '
        '<button type="submit">Einladen</button>'
        '</form>'
        f'<h2>Bisherige Einladungen</h2>{tabelle}')
    return _seite("Team-Mitglied einladen", rumpf, refresh=5 if wartet else None)


@_gesichert_seite
async def aktion_tailscale_einladen(request):
    form = await request.form()
    if not _csrf_ok(form):
        return _fehlerseite(
            400, "Ungültige Anfrage",
            "Die Anfrage trägt keine gültige Marke dieser Oberfläche. "
            "Seite neu laden und erneut versuchen.")
    email, fehler = mailadresse.pruefe(str(form.get("email") or ""))
    if fehler:
        return _fehlerseite(
            400, "Ungültige E-Mail-Adresse", f"{fehler}. Nichts wurde angefordert.")
    server._q(
        "insert into admin_auftraege (art, email, angefordert_von) "
        "values ('tailscale_einladen', %s, %s) returning id",
        (email, _ui_akteur(request)))
    return RedirectResponse("/team/tailscale-einladen", status_code=303)
```

- [ ] **Step 7: Routen registrieren**

In `sales-mcp/ui.py`, nach Zeile 6051 (`Route("/team/laden-anlegen/anfordern", ...)`)
einfügen:

```python
    Route("/team/tailscale-einladen", tailscale_einladen_seite),
    Route("/team/tailscale-einladen/anfordern", aktion_tailscale_einladen,
          methods=["POST"]),
```

- [ ] **Step 8: Testdatei schreiben**

Neue Datei `sales-mcp/tests/test_tailscale_einladen_seite.py`:

```python
"""Rollen-Tor und Formular fuer '/team/tailscale-einladen'.

WELCHE KAPUTTE FASSUNG FAENGT JEDER TEST?
-------------------------------------------------------------------------
* test_nur_freigeben_und_basis_laden_duerfen — eine Fassung, die
  _ADMIN_BASIS_PFADE vergisst und nur "/team/laden-anlegen" prueft, wuerde
  diesen Pfad fuer JEDE Rolle in JEDEM Laden oeffnen.
* test_schlechte_adresse_wird_serverseitig_abgewiesen — ein Formular, das
  dem type="email"-Attribut des Browsers vertraut, laesst jede Zeichenkette
  durch, die jemand ohne Browser (curl, ein Skript) schickt.
* test_zeile_traegt_den_angemeldeten_namen — dieselbe Kopierfalle wie bei
  '/team/laden-anlegen': eine Fassung, die den Namen hart auf
  'betreiber-ui' setzt, wuerde nie zeigen, WER eine Einladung angefordert
  hat.
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
        conn.execute(
            "truncate sales_test.admin_auftraege, sales_test.benutzer cascade")


@pytest.fixture
def scharf():
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-die-suite"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _benutzer(name, rolle="freigeben", passwort="korrekt-pferd-9"):
    server._q(
        "insert into benutzer (name, rolle, passwort_hash, aktiv) values "
        "(%s, %s, %s, true) returning name",
        (name, rolle, ui._passwort_hashen(passwort)))
    return name


def _post(pfad, daten, host=HOST_OK, client=None):
    return (client or CLIENT).post(
        pfad, data=daten, headers={"host": host}, follow_redirects=False)


def _get(pfad, host=HOST_OK, client=None):
    return (client or CLIENT).get(pfad, headers={"host": host})


def test_nur_freigeben_und_basis_laden_duerfen():
    assert ui._pfad_erlaubt("freigeben", "/team/tailscale-einladen") is True
    assert ui._pfad_erlaubt("lesen", "/team/tailscale-einladen") is False
    assert ui._pfad_erlaubt("kalender", "/team/tailscale-einladen") is False


def test_freigeben_ausserhalb_des_basis_ladens_darf_nicht(monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._pfad_erlaubt("freigeben", "/team/tailscale-einladen") is False
    assert ui._pfad_erlaubt(
        "freigeben", "/team/tailscale-einladen/anfordern") is False


@pytest.mark.parametrize("schlechte_adresse", [
    "keineadresse", "ohne-punkt@domain", "mit leerzeichen@domain.de", "",
    "zwei@at@zeichen.de"])
def test_schlechte_adresse_wird_serverseitig_abgewiesen(schlechte_adresse):
    r = _post("/team/tailscale-einladen/anfordern",
              {"email": schlechte_adresse, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_ohne_csrf_token_wird_nichts_angelegt():
    r = _post("/team/tailscale-einladen/anfordern", {"email": "kolleg@example.com"})
    assert r.status_code == 400
    zeilen = server._q("select count(*) as n from admin_auftraege")
    assert zeilen[0]["n"] == 0


def test_gute_adresse_legt_eine_zeile_mit_status_offen_an():
    r = _post("/team/tailscale-einladen/anfordern",
              {"email": "kolleg@example.com", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    zeilen = server._q(
        "select email, status, angefordert_von from admin_auftraege")
    assert len(zeilen) == 1
    assert zeilen[0]["email"] == "kolleg@example.com"
    assert zeilen[0]["status"] == "offen"
    assert zeilen[0]["angefordert_von"] == "betreiber-ui"


def test_seite_traegt_auffrischen_solange_ein_auftrag_offen_ist():
    server._q(
        "insert into admin_auftraege (art, email, angefordert_von) "
        "values ('tailscale_einladen', 'kolleg@example.com', 'test')")
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' in r.text


def test_seite_traegt_kein_auffrischen_wenn_alles_erledigt_ist():
    server._q(
        "insert into admin_auftraege "
        "(art, email, angefordert_von, status, erledigt_am) values "
        "('tailscale_einladen', 'kolleg@example.com', 'test', 'erfolg', now())")
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert 'http-equiv="refresh"' not in r.text


def test_seite_ohne_javascript():
    r = _get("/team/tailscale-einladen")
    assert "<script" not in r.text.lower()


def test_seite_zeigt_erfolgsergebnis_mit_echtem_json_ohne_absturz():
    server._q(
        "insert into admin_auftraege "
        "(art, email, angefordert_von, status, ergebnis, erledigt_am) "
        "values ('tailscale_einladen', 'kolleg@example.com', 'test', 'erfolg', "
        "%s::jsonb, now())",
        ('{"inviteUrl": "https://login.tailscale.com/admin/invite/probe123"}',))
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert "probe123" in r.text


def test_seite_zeigt_fehlerergebnis_ohne_absturz():
    server._q(
        "insert into admin_auftraege "
        "(art, email, angefordert_von, status, fehler, erledigt_am) "
        "values ('tailscale_einladen', 'kolleg@example.com', 'test', 'fehler', "
        "'HTTP 400: bereits eingeladen', now())")
    r = _get("/team/tailscale-einladen")
    assert r.status_code == 200
    assert "bereits eingeladen" in r.text


def test_scharfe_anmeldung_traegt_den_echten_namen(scharf):
    _benutzer("lena")
    login = _post("/login", {"name": "lena", "passwort": "korrekt-pferd-9",
                             "csrf": ui.CSRF_TOKEN})
    assert login.status_code == 303
    r = _post("/team/tailscale-einladen/anfordern",
              {"email": "kolleg@example.com", "csrf": ui.CSRF_TOKEN},
              client=TestClient(ui.app, cookies=login.cookies))
    assert r.status_code == 303
    zeilen = server._q("select angefordert_von from admin_auftraege")
    assert zeilen[0]["angefordert_von"] == "lena"
```

- [ ] **Step 9: Tests laufen lassen**

Run: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e
SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest
tests/test_tailscale_einladen_seite.py tests/test_laden_anlegen_seite.py -v`
Expected: alle Tests grün — insbesondere auch die bestehenden `test_laden_anlegen_seite.py`-
Tests, damit Step 5 (die `art`-Spalte in der Abfrage) nichts an der bestehenden Seite
zerbrochen hat.

- [ ] **Step 10: Volle Suite laufen lassen**

Run: `docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m
pytest -q`
Expected: alle Tests grün, keine neuen Fehlschläge irgendwo sonst im Haus.

- [ ] **Step 11: Commit**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_tailscale_einladen_seite.py
git commit -m "feat(sales-claw): Oberflaeche fuer Tailscale-Einladungen"
```

---

### Task 3: Wirt-Orchestrator — zweiter Zweig, Selbstheilung erweitern, Zugangsdaten

**Files:**
- Modify: `deploy/admin-auftrag-ausfuehren.sh`
- Modify: `deploy/systemd/sales-admin-auftraege.service`
- Create: `tailscale-admin.env.example`

**Interfaces:**
- Consumes: `sales.admin_auftraege` mit `art = 'tailscale_einladen'` und einer `email`-Spalte
  (Task 1). Umgebungsvariablen `TAILSCALE_API_KEY`, `TAILSCALE_TAILNET` aus der
  Prozessumgebung des Skripts (neu, per `EnvironmentFile=` in diesem Task).
- Produces: `status = 'erfolg'` mit `ergebnis = {"inviteUrl": "..."}` (leerer String, falls
  Tailscales Antwort keine enthielt) oder `status = 'fehler'` mit einer Textmeldung in
  `fehler` — dieselbe Form, die Task 2s `_admin_auftrag_ergebnis_text` bereits erwartet.

- [ ] **Step 1: Schritt 0 (Selbstheilung) auf beide Auftragsarten ausweiten**

In `deploy/admin-auftrag-ausfuehren.sh`, ersetze den Kommentar- und SQL-Block ab
`# --- 0. Haengende Auftraege ...` (aktuell Zeile 128-142):

```bash
# --- 0. Haengende Auftraege aus einem fruehen Absturz zurueckholen --------
# Spec §2.4 (Laden anlegen) / Spec 2026-09-22-tailscale-einladung-design
# §2.4 (Tailscale-Einladungen): ein 'laeuft', das laenger als 10 Minuten
# steht, ist kein laufender Auftrag mehr, sondern ein Rest eines
# abgebrochenen Laufs (Neustart, systemctl stop, OOM, ein haengender
# Tailscale-API-Aufruf trotz --max-time — keiner davon laesst den ERR-Trap
# feuern). Gilt fuer BEIDE Auftragsarten, sonst gibt es fuer die neuere
# keinen Weg zurueck: sales_app hat kein update/delete auf admin_auftraege.
psql_admin <<'SQL'
update sales.admin_auftraege
   set status = 'fehler',
       fehler = 'Haengender Auftrag: laenger als 10 Minuten auf ''laeuft'' '
                'stehengeblieben, vom naechsten Durchlauf zurueckgesetzt.',
       erledigt_am = now()
 where art in ('laden_anlegen', 'tailscale_einladen') and status = 'laeuft'
   and erstellt_am < now() - interval '10 minutes';
SQL
```

- [ ] **Step 2: Schritt 1 (Auftrag abholen) auf beide Auftragsarten ausweiten**

Ersetze den Block ab `# --- 1. Naechsten offenen Auftrag ...` (aktuell Zeile 144-157):

```bash
# --- 1. Naechsten offenen Auftrag holen, sofort auf 'laeuft' setzen -------
# Tab-getrennt (nicht '|'): eine E-Mail-Adresse darf laut mailadresse.py
# im lokalen Teil ein '|' enthalten (RFC-5322-atext) — ein Tab kommt weder
# in einem Ladennamen ([a-z0-9_]) noch in einer zulaessigen Adresse vor
# (mailadresse.py schliesst Leerraum/Steuerzeichen bewusst aus).
ZEILE="$(psql_admin -tAc \
  "select id || chr(9) || art || chr(9) || coalesce(name, '') || chr(9) \
          || coalesce(email, '') \
   from sales.admin_auftraege \
   where art in ('laden_anlegen', 'tailscale_einladen') and status = 'offen' \
   order by erstellt_am limit 1")"
if [ -z "$ZEILE" ]; then
  exit 0
fi
IFS=$'\t' read -r AUFTRAG_ID ART LADEN_NAME EINLADEN_EMAIL <<< "$ZEILE"
psql_admin -v id="$AUFTRAG_ID" <<'SQL'
update sales.admin_auftraege set status = 'laeuft' where id = :'id'::uuid;
SQL
ERLEDIGT+=("aufnahme")

if [ "$ART" = "laden_anlegen" ]; then
```

- [ ] **Step 3: Die bestehenden Schritte 2-7 in den `laden_anlegen`-Zweig einrücken**

Alles zwischen der alten Zeile 157 (`ERLEDIGT+=("aufnahme")`) und der abschließenden
`trap - ERR`-Zeile — also die komplette bisherige Schritt-2-bis-7-Logik (Ports suchen,
`deploy/laden-anlegen.sh` aufrufen, `db/laden-anlegen.sql`, Container starten, Konto
anlegen, Erfolg melden) — bekommt eine Einrückung von zwei Leerzeichen (jede Zeile), damit
sie innerhalb des neuen `if [ "$ART" = "laden_anlegen" ]; then ... fi`-Blocks steht. Der
Inhalt selbst ändert sich nicht — nur die Einrückung. Am Ende dieses eingerückten Blocks
(nach der bisherigen letzten SQL-Zeile `SQL` des Erfolgs-Updates) folgt direkt Step 4
unten.

- [ ] **Step 4: Den neuen `tailscale_einladen`-Zweig anfügen**

Direkt nach dem eingerückten Ende von Step 3 (nach dessen letztem `SQL`-Heredoc-Ende),
noch vor der abschließenden `trap - ERR`-Zeile, einfügen:

```bash
elif [ "$ART" = "tailscale_einladen" ]; then
  # --- 2. Zugangsdaten aus der Wirt-Umgebung lesen -------------------------
  # Niemals aus einem Container — siehe Spec §1.3 (T5a-Prinzip). Die Datei
  # deploy/systemd/sales-admin-auftraege.service traegt sie per
  # EnvironmentFile= in die Prozessumgebung DIESES Skripts, siehe
  # tailscale-admin.env.example.
  if [ -z "${TAILSCALE_API_KEY:-}" ] || [ -z "${TAILSCALE_TAILNET:-}" ]; then
    echo "FEHLER: TAILSCALE_API_KEY/TAILSCALE_TAILNET nicht gesetzt (siehe " \
         "tailscale-admin.env.example)." >&2
    false
  fi
  ERLEDIGT+=("zugangsdaten")

  # --- 3. Anfrage-Rumpf ueber python3 bauen, nicht per printf/Verkettung ---
  # EINLADEN_EMAIL besteht die Datenbank-CHECK-Pruefung (Aufgabe 1), die
  # etwas WEITER ist als mailadresse.pruefes eigene Whitelist (die
  # Datenbank-Pruefung schliesst nur '@'/Leerraum aus, nicht z. B. ein
  # Anfuehrungszeichen). Ein direkt verkettetes '{"email":"%s",...}' waere
  # angreifbar, sollte je eine Zeile diese Pruefung umgehen (z. B. ein
  # direkter SQL-Insert ausserhalb der Oberflaeche). json.dumps() entkommt
  # korrekt, unabhaengig vom Inhalt.
  ANFRAGE_JSON="$(EINLADEN_EMAIL="$EINLADEN_EMAIL" python3 -c '
import json, os
print(json.dumps({"email": os.environ["EINLADEN_EMAIL"], "role": "member"}))')"
  ERLEDIGT+=("anfrage-aufbau")

  # --- 4. Tailscale-Einladung anfordern -------------------------------------
  # Der persoenliche API-Schluessel geht NIE ueber curls eigenes -H/--Argv
  # (dort woertlich im Argv des Aufrufs sichtbar, dieselbe Leck-Klasse wie
  # LADEN_PASSWORT/ERGEBNIS oben) — stattdessen per stdin an `curl -K -`,
  # das eine kleine Konfigurationszeile liest statt eines
  # Kommandozeilenarguments. --max-time 15: der einzige Schritt in dieser
  # Datei, der ueber das lokale Netz hinausgeht und deshalb wirklich
  # haengen kann — die anderen sind alle localhost (docker exec/psql).
  ANTWORT="$(printf 'header = "Authorization: Bearer %s"\n' \
      "$TAILSCALE_API_KEY" | \
    curl -sS --max-time 15 -K - \
      -X POST \
      "https://api.tailscale.com/api/v2/tailnet/$TAILSCALE_TAILNET/user-invites" \
      -H "Content-Type: application/json" \
      -d "$ANFRAGE_JSON" \
      -w $'\n%{http_code}')"
  HTTP_CODE="${ANTWORT##*$'\n'}"
  ANTWORT_RUMPF="${ANTWORT%$'\n'*}"
  ERLEDIGT+=("api-aufruf")

  # --- 5. Ergebnis auswerten -------------------------------------------------
  # Tailscales genaues Fehler-JSON-Format war zum Entwurfszeitpunkt nicht
  # zweifelsfrei zu klaeren (Spec §1.2) — deshalb defensiv: sowohl
  # "message" als auch "error" versuchen, sonst der rohe Antwortkoerper
  # (gekuerzt). Ein einziger python3-Aufruf gibt STATUS und Nutzlast
  # tab-getrennt zurueck (derselbe Trenner-Grund wie beim Einlesen des
  # Auftrags in Schritt 1).
  AUSWERTUNG="$(HTTP_CODE="$HTTP_CODE" ANTWORT_RUMPF="$ANTWORT_RUMPF" \
    python3 -c '
import json, os
code = os.environ["HTTP_CODE"]
rumpf = os.environ["ANTWORT_RUMPF"]
try:
    daten = json.loads(rumpf)
except (ValueError, TypeError):
    daten = {}
if code.startswith("2"):
    print("erfolg\t" + json.dumps({"inviteUrl": daten.get("inviteUrl", "")}))
else:
    grund = (daten.get("message") or daten.get("error")
             or "HTTP " + code + ": " + rumpf[:200])
    print("fehler\t" + grund)
')"
  STATUS="${AUSWERTUNG%%$'\t'*}"
  NUTZLAST="${AUSWERTUNG#*$'\t'}"
  ERLEDIGT+=("auswertung")

  if [ "$STATUS" = "fehler" ]; then
    echo "FEHLER: Tailscale-Einladung fehlgeschlagen — $NUTZLAST" >&2
    false
  fi

  # --- 6. Erfolg melden -------------------------------------------------------
  DATEN="$NUTZLAST" docker exec -i -e DATEN debian-supabase-db-1 \
    psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 \
    -v id="$AUFTRAG_ID" <<'SQL'
\getenv ergebnis DATEN
update sales.admin_auftraege
   set status = 'erfolg', ergebnis = :'ergebnis'::jsonb, erledigt_am = now()
 where id = :'id'::uuid;
SQL
fi

trap - ERR
```

- [ ] **Step 5: Syntax prüfen**

Run: `bash -n deploy/admin-auftrag-ausfuehren.sh`
Expected: keine Ausgabe, Exit 0.

- [ ] **Step 6: Von Hand gegen eine Attrappe prüfen — Erfolgsfall**

Lokal (nicht auf der VM), eine `curl`-Attrappe vorn im `PATH` platzieren, die eine
Tailscale-Erfolgsantwort simuliert:

```bash
mkdir -p /tmp/attrappen-bin
cat > /tmp/attrappen-bin/curl <<'EOF'
#!/usr/bin/env bash
cat > /tmp/curl-config-aufzeichnung.txt
echo '{"inviteUrl":"https://login.tailscale.com/admin/invite/probeXYZ"}'
echo "200"
EOF
chmod +x /tmp/attrappen-bin/curl
```

Ein Skript-Fragment testen, das nur den `tailscale_einladen`-Zweig isoliert nachstellt
(die volle Datei braucht eine echte `admin_auftraege`-Zeile und `debian-supabase-db-1`,
was lokal nicht existiert — dieser Schritt prüft NUR den curl-/JSON-Teil):

```bash
PATH="/tmp/attrappen-bin:$PATH" EINLADEN_EMAIL="probe@example.com" \
  TAILSCALE_API_KEY="tskey-probe" TAILSCALE_TAILNET="example.com" bash -c '
ANFRAGE_JSON="$(EINLADEN_EMAIL="$EINLADEN_EMAIL" python3 -c "
import json, os
print(json.dumps({\"email\": os.environ[\"EINLADEN_EMAIL\"], \"role\": \"member\"}))")"
ANTWORT="$(printf "header = \"Authorization: Bearer %s\"\n" "$TAILSCALE_API_KEY" | \
  curl -sS --max-time 15 -K - -X POST \
  "https://api.tailscale.com/api/v2/tailnet/$TAILSCALE_TAILNET/user-invites" \
  -H "Content-Type: application/json" -d "$ANFRAGE_JSON" -w $'"'"'\n%{http_code}'"'"')"
echo "ANTWORT war: $ANTWORT"
'
grep -F "tskey-probe" /tmp/curl-config-aufzeichnung.txt && \
  echo "SCHLUESSEL STAND IM ARGV — FEHLER" || \
  echo "kein Treffer im Argv — Schluessel kam nur ueber die Attrappen-eigene stdin an"
```

Expected: `ANTWORT war: {"inviteUrl":...}\n200`, und die zweite Zeile bestätigt „kein
Treffer im Argv" — der Schlüssel erscheint nirgends in `/tmp/curl-config-aufzeichnung.txt`
außer als Teil der `-K`-Konfigurationszeile (die die Attrappe absichtlich mitschreibt, um
genau das zu belegen). `rm -rf /tmp/attrappen-bin /tmp/curl-config-aufzeichnung.txt`
danach.

- [ ] **Step 7: Von Hand gegen eine Attrappe prüfen — hängender Aufruf + Selbstheilung**

Spec §5 Punkt 3 verlangt beides zusammen: dass `--max-time` einen hängenden Aufruf wirklich
beendet, UND dass eine liegengebliebene `'laeuft'`-Zeile mit `art = 'tailscale_einladen'`
vom erweiterten Schritt 0 ebenso zurückgesetzt wird wie eine mit `art = 'laden_anlegen'`.

**a) `--max-time` schneidet wirklich ab** — eine `curl`-Attrappe, die künstlich 20 Sekunden
schläft, gegen ein `--max-time 15`:

```bash
mkdir -p /tmp/attrappen-bin
cat > /tmp/attrappen-bin/curl <<'EOF'
#!/usr/bin/env bash
sleep 20
echo '{"message":"sollte nie ankommen"}'
echo "200"
EOF
chmod +x /tmp/attrappen-bin/curl
time (PATH="/tmp/attrappen-bin:$PATH" curl -sS --max-time 15 -K /dev/null \
  -X POST "https://beispiel.invalid/" -d '{}' -w '\n%{http_code}'; \
  echo "Exit-Code: $?")
rm -rf /tmp/attrappen-bin
```

Expected: bricht nach ca. 15 Sekunden ab (nicht 20), `Exit-Code` ungleich 0 — `curl`s
eigener Timeout-Exit (28), der über `set -e`/den ERR-Trap denselben Weg nach `status =
'fehler'` nimmt wie jeder andere Fehlschlag in diesem Skript.

**b) Schritt 0 setzt beide Auftragsarten zurück** — gegen die lokale Testdatenbank:

```bash
docker exec -i sales-testdb psql -U postgres <<'SQL'
insert into sales_test.admin_auftraege
  (art, email, angefordert_von, status, erstellt_am)
values
  ('tailscale_einladen', 'alt@example.com', 'test', 'laeuft',
   now() - interval '11 minutes'),
  ('tailscale_einladen', 'frisch@example.com', 'test', 'laeuft', now());

update sales_test.admin_auftraege
   set status = 'fehler',
       fehler = 'Haengender Auftrag: laenger als 10 Minuten auf ''laeuft'' '
                'stehengeblieben, vom naechsten Durchlauf zurueckgesetzt.',
       erledigt_am = now()
 where art in ('laden_anlegen', 'tailscale_einladen') and status = 'laeuft'
   and erstellt_am < now() - interval '10 minutes';

select email, status from sales_test.admin_auftraege order by email;
SQL
```

Expected: `UPDATE 1` (nur die 11-Minuten-alte Zeile), die Abschlussabfrage zeigt
`alt@example.com` auf `fehler`, `frisch@example.com` weiterhin auf `laeuft`. Danach
`docker exec -i sales-testdb psql -U postgres -c "truncate sales_test.admin_auftraege"`
zum Aufräumen.

- [ ] **Step 8: `deploy/systemd/sales-admin-auftraege.service` um `EnvironmentFile=` ergänzen**

Ersetze den vollständigen Inhalt von `deploy/systemd/sales-admin-auftraege.service`:

```ini
[Unit]
Description=sales-claw: Admin-Auftraege aus sales.admin_auftraege ausfuehren

[Service]
Type=oneshot
User=debian
# TAILSCALE_API_KEY/TAILSCALE_TAILNET fuer den tailscale_einladen-Zweig
# von admin-auftrag-ausfuehren.sh — ausschliesslich hier, nie in einem
# Container (T5a-Prinzip, Spec 2026-09-22-tailscale-einladung-design §1.3).
# "-" davor: eine fehlende Datei ist NICHT fatal, damit 'laden_anlegen'-
# Auftraege weiterlaufen, auch bevor die Tailscale-Zugangsdaten je
# eingerichtet wurden.
EnvironmentFile=-/home/debian/sales-claw/tailscale-admin.env
ExecStart=/usr/bin/bash /home/debian/sales-claw/deploy/admin-auftrag-ausfuehren.sh
```

- [ ] **Step 9: Beispiel-Zugangsdatendatei anlegen**

Neue Datei `tailscale-admin.env.example` (Repo-Wurzel):

```bash
# ---------------------------------------------------------------------------
# Zugangsdaten fuer deploy/admin-auftrag-ausfuehren.sh, Zweig
# 'tailscale_einladen' (Spec 2026-09-22-tailscale-einladung-design).
#
# NIE in die normale .env/deploy/laeden/*.env — diese Datei wird
# AUSSCHLIESSLICH per EnvironmentFile= in die Prozessumgebung des
# systemd-Dienstes sales-admin-auftraege.service geladen, nie in einen
# Container gereicht (T5a-Prinzip). Auf der VM: von diesem Beispiel
# kopieren nach 'tailscale-admin.env' (ohne ".example" — der Dateiname
# endet dann auf ".env" und ist damit automatisch durch die bestehende
# .gitignore-Regel "*.env" erfasst, chmod 600 setzen.
# ---------------------------------------------------------------------------

# Personengebundener API-Schluessel eines Owner/Admin/IT-Admin des
# Tailnet — Tailscale erzwingt das fuer /user-invites, ein OAuth-Client-
# Token reicht dafuer NICHT (siehe Spec §1.2). In der Tailscale-Verwaltung
# unter "Keys" erzeugen, so eng scopen wie dort angeboten.
TAILSCALE_API_KEY=

# Der Tailnet-Bezeichner, wie er in der Tailscale-Verwaltung steht (z. B.
# der eigene Domainname). Ob der Platzhalter "-" ("das Tailnet dieses
# Schluessels") fuer /user-invites funktioniert, war aus der Dokumentation
# nicht zweifelsfrei zu klaeren — hier den echten Namen eintragen, nicht
# raten.
TAILSCALE_TAILNET=
```

- [ ] **Step 10: Commit**

```bash
git add deploy/admin-auftrag-ausfuehren.sh deploy/systemd/sales-admin-auftraege.service \
        tailscale-admin.env.example
git commit -m "feat(sales-claw): Wirt-Orchestrator - Tailscale-Einladungen ausfuehren"
```

---

### Task 4: Runbook und der echte Probelauf

**Files:**
- Modify: `docs/03_RUNBOOK.md`

**Interfaces:**
- Consumes: alles aus Aufgabe 1-3.
- Produces: nichts — dies ist die Abnahme.

- [ ] **Step 1: Abschnitt „Team-Mitglied per Tailscale einladen" ergänzen**

In `docs/03_RUNBOOK.md`, direkt nach Abschnitt „7. Laden anlegen aus der Oberfläche"
(endet mit dem Runbook-Ausschnitt zu `db-identitaet <name> ok`), einen neuen Abschnitt „8.
Team-Mitglied per Tailscale einladen" einfügen mit:

* Voraussetzung: `tailscale-admin.env` liegt auf der VM unter
  `/home/debian/sales-claw/tailscale-admin.env` (aus `tailscale-admin.env.example`
  kopiert, `chmod 600`, `TAILSCALE_API_KEY`/`TAILSCALE_TAILNET` ausgefüllt), danach
  `sudo systemctl daemon-reload && sudo systemctl restart sales-admin-auftraege.timer`
  (systemd liest `EnvironmentFile=` nur beim (Neu-)Start des Dienstes ein — eine allein
  neu geschriebene Datei ohne Neustart wirkt erst beim nächsten Reboot).
* Weg: Anmeldung als Rolle `freigeben` im Basis-Laden → Menü → **Admin** → **Team-Mitglied
  einladen** → E-Mail-Adresse eintragen → **Einladen**. Dieselbe
  `<meta http-equiv="refresh">`-Seite wie bei „Laden anlegen" — kein JavaScript, alle 5
  Sekunden neu geladen, bis ein Ergebnis feststeht.
* Mit Erfolg zeigt die Zeile „Einladung verschickt." plus, falls Tailscales Antwort einen
  Link enthielt, „Link zum Weitergeben: …" — nützlich, falls die E-Mail selbst nicht
  ankommt.
* Mit Fehler zeigt die Zeile Tailscales eigene Fehlermeldung (z. B. bereits eingeladen,
  ungültiger Schlüssel, Ratenlimit).
* Was danach von Hand bleibt (Spec §4, ausdrücklich nicht automatisiert): die
  Tailscale-Zugriffsregel für den neuen Menschen, siehe Abschnitt „6. Zugang: eigener
  Serve-Port und eigene Zugriffsregel" weiter oben in diesem Runbook.

- [ ] **Step 2: HALT — der Probelauf braucht die ausdrückliche Freigabe des Betreibers**

Erst nach Zustimmung, in dieser Reihenfolge:

1. Auf der VM `tailscale-admin.env` aus dem Beispiel anlegen, `chmod 600`, echte Werte
   eintragen.
2. `sudo systemctl daemon-reload && sudo systemctl restart sales-admin-auftraege.timer`.
3. Über die Oberfläche eine Einladung an eine selbst kontrollierte Wegwerf-Adresse
   auslösen.
4. Innerhalb von höchstens 20 Sekunden erscheint `status='laeuft'`, danach `'erfolg'` oder
   `'fehler'` mit einem genannten Grund.
5. Bei Erfolg: den Eingang der Einladungs-E-Mail an der Wegwerf-Adresse bestätigen.
6. **Aufräumen** (ein Probelauf ist keine echte Einladung): die Einladung über die
   Tailscale-Verwaltung (Users-Seite, ausstehende Einladungen) von Hand zurückziehen.

- [ ] **Step 3: Commit**

```bash
git add docs/03_RUNBOOK.md
git commit -m "docs: Tailscale-Einladungen aus der Oberflaeche im Runbook"
```
