# Kalender verbinden (Besitzer, Business/Privat, Google) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jeder verbundene Kalender bekommt Besitzer und Einordnung (Business/Privat). Termine werden alle 5 Minuten in eine Tabelle abgeglichen. Oberfläche und Agent zeigen sie nach der Sichtbarkeitsregel. Google-Kalender lassen sich per Anmeldung verbinden.

**Architecture:**
- Ein neuer Dienst `sales-kalender` (`kalender_abgleich.py`, gleiches Image wie sales-mcp) holt iCal- und Google-Quellen in `kalender_termine`.
- Fremde Privattermine speichert er nur mit Zeit.
- Oberfläche (`kalender_sicht`) und Agent (`server.belegungen`) lesen nur noch diese Tabelle und maskieren über ein reines Modul `kalender_sichtbarkeit.py`.
- Google-Refresh-Token werden mit `post_tresor` versiegelt, unter einem eigenen Schlüsselpaar `KALENDER_SCHLUESSEL_*`. Den privaten Schlüssel hat nur `sales-kalender`.

**Tech Stack:**
- Python 3 (Starlette-UI in `ui.py`, psycopg3) und urllib für die Google-REST-API, ohne Google-Bibliothek, wie `konferenz.py`.
- `recurring-ical-events` für Serientermine.
- TypeScript + FullCalendar 6 (`kalender/`, vite/vitest).
- PostgreSQL (Supabase auf der VM).

**Spec:** `docs/superpowers/specs/2026-11-08-kalender-verbinden-design.md`

## Global Constraints

- **Sichtbarkeit (Spec §2.2):** eigene Kalender voll; fremde Business voll; fremde Privat nur als Block mit dem Titel genau `Privattermin`, ohne Ort.
- **Agent (Spec §2.3):**
  - Betrachter ist `post_struktur.container_besitzer()`. Ist er leer, gilt jeder Privat-Kalender als fremd.
  - Jede Lücke ergibt „unvollständig“, nie „frei“.
- **Datensparsamkeit (Spec §6.3):** Für Quellen mit `bereich='privat'` und `besitzer != container_besitzer()` werden `titel` und `ort` NIE gespeichert, auch nicht kurzzeitig, auch nicht in Logs oder Fehlertexten.
- **Geheimnisse:**
  - Refresh-Token, Client-Secret und iCal-Adressen erscheinen in keiner Ausgabe, keinem Log und keiner Fehlermeldung.
  - Fehlertexte von Google werden auf den Typ reduziert (`GoogleFehler("…")` mit festen deutschen Texten).
- **Frische (Spec §6.2):**
  - Abgleich alle `KALENDER_INTERVAL_S=300` Sekunden.
  - Eine Quelle ist Lücke, wenn `zuletzt_gelesen` fehlt oder älter als `FRISCHE_MIN=15` Minuten ist, oder wenn `letzter_fehler` gesetzt ist.
- **Abgleich-Fenster:** 30 Tage zurück, 180 Tage voraus.
- **Google-Scopes:** genau `https://www.googleapis.com/auth/calendar.calendarlist.readonly https://www.googleapis.com/auth/calendar.events.readonly`, dazu `access_type=offline`, `prompt=consent`.
- **Rücksprung:** `UI_BASIS_URL` + `/team/kalender/google/zurueck`.
- **Env-Namen:**
  - `GOOGLE_KALENDER_CLIENT_ID` und `GOOGLE_KALENDER_CLIENT_SECRET` (sales-ui und sales-kalender);
  - `KALENDER_SCHLUESSEL_OEFFENTLICH` (nur sales-ui);
  - `KALENDER_SCHLUESSEL_PRIVAT` (nur sales-kalender);
  - `KALENDER_INTERVAL_S`.
- **Rechte:** Entfernen, Pausieren und Bereich ändern darf nur der Besitzer der Quelle oder die Rolle `freigeben`.
- **Bestehende Quellen:** Besitzer = Laden-Besitzer, Bereich `privat` (Spec §2.9). Neu verbundene haben keinen Standard; der Bereich ist Pflicht.
- **Ladenfest:** Jede Abfrage läuft im Schema des eigenen Ladens; kein Code nennt `sales` fest.
- **Nichts ausrollen:**
  - Kein Deploy, kein `psql` gegen `sales`, kein Start eines Dienstes auf der VM ohne OK des Betreibers.
  - Tests laufen nur gegen `sales_test`.
- **Testlauf (Python), immer auf der VM:**
  ```
  tar -cf - --exclude=__pycache__ --exclude=.pytest_cache sales-mcp db | ssh offload-vm 'rm -rf /tmp/kv && mkdir -p /tmp/kv && tar -xf - -C /tmp/kv'
  ssh offload-vm 'cd ~/sales-claw && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test -e PYTHONDONTWRITEBYTECODE=1 -v /tmp/kv/sales-mcp:/app sales-claw-sales-mcp:local sh -c "pip install -q recurring-ical-events >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider <TESTS>"'
  ```
  - Aufräumen: `ssh offload-vm 'docker run --rm -v /tmp:/t sales-claw-sales-mcp:local rm -rf /t/kv'`.
  - Vorbestehende Rote stellt man durch denselben Lauf auf `git archive feat/stufe-1-fundament sales-mcp db` fest; nur neue Rote zählen.
- **Testlauf (TypeScript):** `cd kalender && npm ci && npm test`. Bundle: `npm run build` schreibt `sales-mcp/static/kalender/*`, das Ergebnis wird committet.
- **Arbeitsort:**
  - Worktree `C:/Users/User/ClaudeWork/wt-sales-kalender`, Branch `feat/kalender-verbinden`; Dateien mit CRLF (autocrlf).
  - Conventional Commits mit Zeile `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Kein Push ohne OK.

## Review Focus

1. **Ganztägige Termine** (Google `start.date`, iCal `VALUE=DATE`): Sie erscheinen in der Ganztags-Zeile. „Frei“ markierte Termine (Google `transparency: transparent`, iCal `TRANSP:TRANSPARENT`, z. B. Geburtstage) blockieren den Agenten nicht. → Tests in Task 3 und Task 8.
2. **Abgesagte Google-Termine** (`status: cancelled`) erscheinen nirgends. → Test in Task 8.
3. **Bei Google widerrufener Zugang** (`invalid_grant`): Die Quelle zeigt „Zugang abgelaufen – bitte neu verbinden“ und ist eine Lücke; der Agent sagt nie „frei“. → Test in Task 8.
4. **Wechsel Business→Privat:** Die gespeicherten Titel fremder Quellen sind sofort weg, nicht erst beim nächsten Abgleich. → Test in Task 5.
5. **Derselbe Termin in zwei Kalendern derselben Person**, einer davon fremd-privat: Er erscheint einmal, und für fremde Betrachter maskiert. → Test in Task 2.

---

### Task 1: Datenbank – Besitzer, Bereich, Konten, Termin-Tabelle

**Files:**
- Create: `db/kalender-verbinden.sql`
- Modify: `db/laden-anlegen.sql` (Hinweis-Kommentar am Ende: Datei je Laden zusätzlich einspielen); `deploy/laden-anlegen.sh` (in der Echo-Anleitung den psql-Aufruf für `db/kalender-verbinden.sql` ergänzen)
- Test: `sales-mcp/tests/test_kalender_verbinden_schema.py`

**Interfaces:**
- Produces:
  - **Tabelle `kalender_quellen`**, neue Spalten:
    - `besitzer text` (nach Rückfüllen `not null`);
    - `bereich text not null check (bereich in ('business','privat'))`;
    - `konto_id uuid null references <schema>.kalender_konten(id)`;
    - `google_id text null`.
    - Dazu: `art` erlaubt `'ics','google'`, und der Unique-Index geht von `(anzeigename)` auf `(besitzer, anzeigename)`.
  - **Tabelle `kalender_konten`:**
    - Spalten `id uuid pk`, `besitzer text not null`, `anbieter text not null check (anbieter in ('google'))`, `adresse text not null`, `zugang_versiegelt text`, `kalender_liste jsonb not null default '[]'`, `aktiv boolean not null default true`, `created_at timestamptz default now()`.
    - Unique `(besitzer, anbieter, adresse)`.
    - Rechte select, insert, update.
  - **Tabelle `kalender_termine`:**
    - Spalten `quelle_id uuid not null references kalender_quellen(id)`, `uid text not null default ''`, `beginn timestamptz not null`, `ende timestamptz not null`, `ganztaegig boolean not null default false`, `frei boolean not null default false`, `titel text`, `ort text`, `abgeglichen_am timestamptz not null default now()`.
    - Indizes auf `(beginn)` und `(quelle_id)`.
    - Rechte select, insert, update, **delete** (Spec §5 Löschrecht).

- [ ] **Step 1: Write the failing test** `test_kalender_verbinden_schema.py`. Es spielt die Datei per `psql` NICHT ein; es liest die Datei und prüft die Struktur, nach dem Muster von `tests/test_post_aufraeumen_schema.py`:

```python
def test_bestehende_quellen_werden_privat_und_gehoeren_dem_laden():
    sql = SQL.read_text(encoding="utf-8")
    assert "set besitzer = :'besitzer'" in sql and "bereich = 'privat'" in sql
    assert "where besitzer is null" in sql          # idempotent: zweiter Lauf aendert nichts

def test_termine_tabelle_hat_loeschrecht_und_konten_nicht():
    sql = SQL.read_text(encoding="utf-8")
    assert re.search(r"select, insert, update, delete[^;]*kalender_termine", sql)
    assert not re.search(r"delete[^;]*kalender_konten", sql)

def test_name_ist_nur_je_besitzer_eindeutig():
    sql = SQL.read_text(encoding="utf-8")
    assert "drop index if exists" in sql and "(besitzer, anzeigename)" in sql
```

Dazu ein DB-Test mit `server._q` gegen `sales_test`, nachdem die Datei eingespielt ist (Step 3): Eine Quelle mit `bereich='geheim'` scheitert am Check.

- [ ] **Step 2: Run, expect FAIL** (Datei fehlt).
- [ ] **Step 3: Write `db/kalender-verbinden.sql`.**
  - Kopf und Rechte-Block nach dem Muster von `db/post-sammelstelle.sql`: `set_config`, Rolle `sales_app` bzw. `sales_app_<laden>`, sonst `raise notice`.
  - Aufruf: `psql -v ON_ERROR_STOP=1 -v schema=<s> -v besitzer=<name> -f db/kalender-verbinden.sql`. Fehlt `besitzer` und gibt es Zeilen mit `besitzer is null`, bricht das Skript ab.
  - Idempotent: `add column if not exists` und `create … if not exists`. `alter column besitzer set not null` erst nach dem Rückfüllen.
  - Bestehende Zeilen ohne Bereich bekommen `'privat'`, über einen vorübergehenden Default, der danach wieder entfernt wird.
  - Einspielen nur auf `sales_test`: `docker exec -i debian-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 -v schema=sales_test -v besitzer=felix < db/kalender-verbinden.sql`, zweimal, damit die Idempotenz geprüft ist.
- [ ] **Step 4: Run tests, expect PASS.**
- [ ] **Step 5: Commit** `feat(kalender): Besitzer, Bereich und Abgleich-Tabelle`.

### Task 2: Sichtbarkeit als reines Modul

**Files:**
- Create: `sales-mcp/kalender_sichtbarkeit.py`
- Test: `sales-mcp/tests/test_kalender_sichtbarkeit.py`

**Interfaces:**
- Produces:
  - `PRIVATTERMIN = "Privattermin"`
  - `def details_speichern(besitzer: str, bereich: str, laden_besitzer: str) -> bool`: False genau dann, wenn `bereich == "privat"` und (`laden_besitzer == ""` oder `besitzer != laden_besitzer`).
  - `def maskiert(besitzer: str, bereich: str, betrachter: str) -> bool`: True genau dann, wenn `bereich == "privat"` und (`betrachter == ""` oder `besitzer != betrachter`).
  - `def anwenden(termine: list[dict], betrachter: str) -> list[dict]`:
    - Eingang: Dicts mit `quelle_id, quelle, besitzer, bereich, uid, beginn, ende, ganztaegig, frei, titel, ort`.
    - Ausgang: dieselben Dicts plus `maskiert: bool` und `kalender: list[str]`, maskiert mit `titel=PRIVATTERMIN, ort=""`.
    - Zusammengeführt wird je `besitzer`: gleiche nicht-leere `uid`, sonst gleiches Tripel `(titel, beginn, ende)`, wenn beide einen Titel haben.
    - Der zusammengeführte Termin ist maskiert, wenn irgendeine Kopie maskiert ist, und `frei` nur, wenn alle Kopien frei sind.
    - Sortiert nach `beginn`.

- [ ] **Step 1: Failing tests**

```python
def test_eigene_privat_voll_fremde_privat_maskiert():
    t = _t(besitzer="felix", bereich="privat", titel="Zahnarzt")
    assert anwenden([t], "felix")[0]["titel"] == "Zahnarzt"
    aus = anwenden([t], "ivan")[0]
    assert aus["titel"] == "Privattermin" and aus["ort"] == "" and aus["maskiert"]

def test_ohne_betrachter_ist_jedes_privat_maskiert():
    assert anwenden([_t(bereich="privat")], "")[0]["maskiert"]

def test_business_fremd_voll():
    assert anwenden([_t(besitzer="ivan", bereich="business", titel="Kunde X")], "felix")[0]["titel"] == "Kunde X"

def test_doppelter_termin_einmal_und_strenger():
    a = _t(quelle="Arbeit", bereich="business", uid="u1", titel="Treffen")
    b = _t(quelle="Privat", bereich="privat", uid="u1", titel="Treffen")
    aus = anwenden([a, b], "ivan")
    assert len(aus) == 1 and aus[0]["titel"] == "Privattermin"
    assert sorted(aus[0]["kalender"]) == ["Arbeit", "Privat"]

def test_verschiedene_besitzer_werden_nicht_zusammengefuehrt():
    assert len(anwenden([_t(besitzer="felix", uid="u1"), _t(besitzer="ivan", uid="u1")], "felix")) == 2

def test_details_speichern():
    assert details_speichern("felix", "privat", "felix")
    assert not details_speichern("ivan", "privat", "felix")
    assert not details_speichern("felix", "privat", "")
    assert details_speichern("ivan", "business", "felix")
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `kalender_sichtbarkeit.py` (reines Modul, keine Importe aus `server`).
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(kalender): Sichtbarkeitsregel Business/Privat`.

### Task 3: Serientermine, Ganztägiges und „frei“ aus iCal

**Files:**
- Modify: `sales-mcp/kalenderquellen.py` (`hole()` und Parser); `sales-mcp/requirements.txt` (+ `recurring-ical-events>=3.3`)
- Test: `sales-mcp/tests/test_kalenderquellen.py`

**Interfaces:**
- Produces:
  - `hole(url, tage_zurueck=7, tage_voraus=60)` behält Signatur und Rückgabe `(termine, fehler)`.
  - Jeder Termin hat zusätzlich `ganztaegig: bool` und `frei: bool`.
  - Serientermine kommen als einzelne Vorkommen, mit der UID der Serie plus `#<beginn-iso>`.
  - Die bisherige Warnung „Serientermine nicht ausgewertet“ entfällt.
  - Sicherheitsprüfungen (`_ziel_erlaubt`, Größenlimit, `ohne_adresse`) bleiben unverändert.

- [ ] **Step 1: Failing tests** in `test_kalenderquellen.py`. Die ICS-Texte stehen im Test; die HTTP-Antwort ist gemockt wie in den bestehenden Tests.
  - `test_woechentliche_serie_wird_aufgeloest`: `RRULE:FREQ=WEEKLY;COUNT=3` ergibt 3 Termine mit verschiedenen `uid` und keinen `fehler`.
  - `test_ganztaegig_value_date`: `DTSTART;VALUE=DATE:20261110` ergibt `ganztaegig=True`, `beginn` 10.11. 00:00 Ortszeit, `ende` 11.11. 00:00.
  - `test_transparent_ist_frei`: `TRANSP:TRANSPARENT` ergibt `frei=True`.
  - `test_ausnahme_exdate_fehlt`: ein `EXDATE` fällt aus der Serie.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Das Zerlegen übernimmt `icalendar` plus `recurring_ical_events.of(cal).between(von, bis)`; der bisherige Handparser für diesen Teil wird ersetzt. Zeitzonen über `TZID`, die Ausgabe ist UTC-aware.
- [ ] **Step 4: Run** `tests/test_kalenderquellen.py tests/test_kalenderquellen_db.py tests/test_kalender_verbinden.py`, expect PASS. Bestehende Tests, die die alte Serien-Warnung erwarten, werden angepasst; jede Anpassung steht im Commit-Text.
- [ ] **Step 5: Commit** `feat(kalender): Serientermine und ganztaegige Termine aus iCal`.

### Task 4: Abgleich-Dienst (iCal) und Speichern

**Files:**
- Create: `sales-mcp/kalender_abgleich.py`
- Modify: `sales-mcp/server.py` (neue DB-Funktionen, s. Interfaces); `docker-compose.yml` (Dienst `sales-kalender`, nach dem Muster `sales-post`, `restart: unless-stopped`, `KALENDER_INTERVAL_S: 300`, `POST_BESITZER`); `deploy/update.sh` (`sales-kalender` wie `sales-post` in `KERN_OPTIONAL`)
- Test: `sales-mcp/tests/test_kalender_abgleich.py`

**Interfaces:**
- Consumes: `kalender_sichtbarkeit.details_speichern` (Task 2); `kalenderquellen.hole` (Task 3).
- Produces:
  - **In `server.py`:**
    - `kalendertermine_ersetzen(quelle_id: str, termine: list[dict], details: bool) -> int`: löscht und fügt in EINER Transaktion ein. Bei `details=False` werden `titel` und `ort` als NULL geschrieben.
    - `kalenderquelle_stand_setzen` bleibt, wie gehabt.
  - **In `kalender_abgleich.py`:**
    - `FENSTER_ZURUECK_TAGE = 30`, `FENSTER_VORAUS_TAGE = 180`, `INTERVAL_S` aus `KALENDER_INTERVAL_S` (Vorgabe 300).
    - `quelle_abgleichen(quelle: dict) -> tuple[int | None, str | None]`:
      - Erfolg ersetzt die Termine und setzt den Stand.
      - Bei Fehler bleiben alte Termine stehen; `letzter_fehler` wird gesetzt.
      - Teilerfolg (`termine` und `fehler`) speichert die Termine und setzt `letzter_fehler`.
    - `runde() -> dict` (Zähler `quellen`, `fehler`).
    - `main() -> int`: Schleife mit `threading.Event`-Stopp und SIGTERM wie `post_abholen.main`. `KALENDER_ONCE=1` = eine Runde.
      - Alle 30 s gleicht sie aktive Quellen mit `zuletzt_gelesen is null` sofort ab; das sind neu verbundene (Spec §6.2 „sofort einmal“).
      - Die volle Runde läuft alle `INTERVAL_S`.
    - Dispatch nach `art`: `ics` über `kalenderquellen.hole`, `google` über Task 8 (bis dahin: Quelle überspringen, Stand „Google noch nicht unterstützt“).

- [ ] **Step 1: Failing tests** (DB `sales_test`, `hole` gemockt):

```python
def test_fremde_privatquelle_speichert_keinen_titel(monkeypatch):
    monkeypatch.setenv("POST_BESITZER", "felix")
    q = _quelle(besitzer="ivan", bereich="privat")
    _hole_liefert(monkeypatch, [_termin(titel="Zahnarzt", ort="Praxis")])
    kalender_abgleich.quelle_abgleichen(q)
    zeile = _termine(q["id"])[0]
    assert zeile["titel"] is None and zeile["ort"] is None

def test_eigene_privatquelle_speichert_titel(monkeypatch): ...   # besitzer=felix -> titel "Zahnarzt"

def test_fehler_laesst_alte_termine_stehen(monkeypatch):
    # erst 1 Termin gespeichert, dann hole -> ([], "nicht erreichbar")
    assert len(_termine(q["id"])) == 1 and _stand(q["id"])["letzter_fehler"]

def test_ersetzen_entfernt_abgesagte(monkeypatch):    # 2 Termine, dann 1 -> 1 Zeile
def test_kein_titel_im_log(caplog, monkeypatch):      # fremd-privat: "Zahnarzt" nicht in caplog.text
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `server.kalendertermine_ersetzen`, `kalender_abgleich.py` und den Compose-Dienst. Der Compose-Test in `tests/test_post_abholen.py` (`test_schluessel_nur_bei_sales_post`) muss weiter grün sein.
- [ ] **Step 4: Run** `tests/test_kalender_abgleich.py tests/test_post_abholen.py::test_schluessel_nur_bei_sales_post`, expect PASS.
- [ ] **Step 5: Commit** `feat(kalender): Abgleich-Dienst sales-kalender fuer iCal-Quellen`.

### Task 5: Lesen nach Regel – Oberfläche und Agent

**Files:**
- Modify:
  - `sales-mcp/server.py`:
    - neu `kalendertermine_lesen`;
    - `belegungen()` liest Quellen-Termine daraus statt `kalenderquellen.hole`;
    - `team_kalender_aus`-Filter entfernen;
    - neue Pflege-Funktionen.
  - `sales-mcp/kalender_sicht.py`:
    - `_sammeln` liest `server.kalendertermine_lesen` statt `hole`;
    - `ereignisse(von, bis, betrachter)` und `konflikte(beginn, dauer, ausser_uid, betrachter)` bekommen den Betrachter.
- Test: `sales-mcp/tests/test_kalender_sicht.py`, `tests/test_belegungen.py`, `tests/test_kollision.py`, `tests/test_kalenderquellen_db.py`

**Interfaces:**
- Consumes: `kalender_sichtbarkeit.anwenden` (Task 2); Tabelle `kalender_termine` (Task 1).
- Produces:
  - **`server.kalendertermine_lesen(von: datetime, bis: datetime, betrachter: str) -> tuple[list[dict], list[dict]]`**:
    - Rückgabe sind (Termine nach `anwenden`, Lücken `[{quelle, grund}]`).
    - Nur aktive Quellen, Frische-Regel `FRISCHE_MIN = 15`.
    - Grund-Texte: `"noch nicht abgeglichen"`, `"seit über 15 Minuten nicht abgeglichen"`, sonst der gespeicherte `letzter_fehler`.
  - **`belegungen(tage_voraus=60)`** nutzt `betrachter = post_struktur.container_besitzer()`.
    - Maskierte Einträge haben `titel="Privattermin"`.
    - Einträge mit `frei=True` fallen aus `eintraege` heraus, zählen also nicht als Kollision.
  - **`kalender_sicht.ereignisse(von, bis, betrachter: str) -> dict`**:
    - Termine aus Quellen haben `art="kalender"` und die Felder `quelle_id, quelle, besitzer, bereich, maskiert, kalender, ganztaegig`.
    - Zusätzlich gibt es den Schlüssel `"ebenen": [{"id", "name", "besitzer", "bereich"}]`. Er enthält die festen Ebenen `kunde` „Kundentermine“, `eigen` „Eigene Termine“ und `handy` „Laden-Kalender“, dazu jede aktive Quelle mit `id = quelle_id`.
  - **`server.kalenderquelle_bereich_setzen(quelle_id: str, bereich: str, besitzer: str | None) -> bool`**:
    - `besitzer=None` heißt: darf alle.
    - Bei Wechsel auf `privat` und wenn `details_speichern(...)` False ist, setzt die Funktion in derselben Transaktion `titel = null, ort = null` in `kalender_termine` dieser Quelle.
  - **`server.kalenderquelle_entfernen(quelle_id: str, besitzer: str | None) -> bool`**: zusätzlich Besitzerprüfung und `delete from kalender_termine where quelle_id = …`.
  - **`server.kalenderquelle_pausieren(quelle_id: str, aktiv: bool, besitzer: str | None) -> bool`.**
  - **`server.kalenderquelle_speichern(anzeigename: str, url: str, besitzer: str, bereich: str) -> str`**: Konflikt jetzt auf `(besitzer, anzeigename)`.

- [ ] **Step 1: Failing tests:**
  - `test_ivan_sieht_felix_privat_als_privattermin`: `ereignisse(..., betrachter="ivan")` für eine Quelle von felix/privat liefert `titel == "Privattermin"` und `maskiert`.
  - `test_veraltete_quelle_ist_luecke`: `zuletzt_gelesen = now() - 16 min` ergibt einen Hinweis in `ereignisse`; `konflikte(...)["unvollstaendig"] is True`.
  - `test_agent_sieht_privattermin_als_belegt`: In `belegungen()` mit `POST_BESITZER=felix` und einer Quelle von ivan/privat steht `titel == "Privattermin"`.
  - `test_freier_termin_kollidiert_nicht`: `frei=True` ergibt in `_kollisionen` keinen Treffer.
  - `test_wechsel_auf_privat_loescht_fremde_titel_sofort` (Review Focus 4): Quelle ivan/business mit Titel, `kalenderquelle_bereich_setzen(id, "privat", "ivan")`; danach `titel is None` in der Tabelle.
  - `test_nur_besitzer_entfernt`: `kalenderquelle_entfernen(id, "ivan")` auf eine Quelle von felix gibt False, die Zeile bleibt aktiv.
  - Bestehende Tests, die „belegt“ oder `team_kalender_aus` erwarten, werden auf die neue Regel umgestellt; jede Umstellung steht im Commit-Text.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
  - Den Zugriff auf den CalDAV-Kalender des Ladens (`kalender.termine_lesen`, Art `handy`) unverändert lassen; er gehört dem Laden-Besitzer und ist Business.
  - Die Stelle in `ui.py` um „Doppelt belegt“ (`EIGENE_QUELLE`-Paarung, ~Zeile 6269–6310) so anpassen, dass sie weiter funktioniert.
- [ ] **Step 4: Run** `tests/test_kalender_sicht.py tests/test_belegungen.py tests/test_kollision.py tests/test_kalenderquellen_db.py tests/test_ui_kalender.py`, expect PASS.
- [ ] **Step 5: Commit** `feat(kalender): Termine nach Business/Privat fuer Oberflaeche und Agent`.

### Task 6: Oberfläche „Kalender verbinden“ mit Besitzer und Bereich

**Files:**
- Modify: `sales-mcp/ui.py` (`team_kalender`, `aktion_kalender_verbinden`, `aktion_kalender_entfernen`, neue Aktionen `aktion_kalender_bereich`, `aktion_kalender_pausieren`, Routen, Rollen-Ausnahmeliste in `AnmeldeWache` ~Zeile 681)
- Test: `sales-mcp/tests/test_kalender_verbinden.py`

**Interfaces:**
- Consumes: Pflege-Funktionen aus Task 5.
- Produces:
  - Die Routen `POST /team/kalender/bereich` und `POST /team/kalender/pausieren` nehmen Formularfelder `quelle_id`, `bereich` bzw. `aktiv` (`"1"`/`"0"`) und `csrf`.
  - Beide stehen, wie `/team/kalender/verbinden` und `/team/kalender/entfernen`, in der Ausnahmeliste für die Rollen `lesen`/`kalender`.
  - Besitzer ist immer `_ui_akteur(request)`, bei Rolle `freigeben` darf der Wert `None` (alle) sein.
  - Das Namensfeld bestimmt nur noch den Anzeigenamen, NICHT den Besitzer.

- [ ] **Step 1: Failing tests:**
  - `test_bereich_ist_pflicht`: POST verbinden ohne `bereich` → 400 „Business oder Privat wählen“, nichts gespeichert.
  - `test_besitzer_ist_angemeldete_person`: Als `ivan` verbinden → Zeile mit `besitzer == "ivan"`, auch wenn `name="felix"`.
  - `test_kalender_rolle_entfernt_fremde_quelle_nicht`: Als `ivan` die Quelle von felix entfernen → 403, Zeile aktiv.
  - `test_freigeben_entfernt_jede`.
  - `test_meine_kalender_zeigt_keine_adresse`: Die Seite enthält die URL nicht, aber Name, Bereich und Stand.
  - `test_bereich_wechseln_als_besitzer`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Seitenaufbau nach Spec §6.4:
  - oben „Mit Google verbinden“: Platzhalter-Abschnitt, der Knopf kommt in Task 9;
  - dann „Meine Kalender“: eigene Quellen mit Bereich-Auswahl, Pausieren/Fortsetzen, Entfernen;
  - dann „Andere Anbieter (Adresse)“: bisheriges Formular plus Pflicht-Radio Business/Privat;
  - für `freigeben` zusätzlich „Kalender im Team“: Name, Besitzer, Bereich, Stand.
  - Nach dem Speichern einer iCal-Quelle ruft die UI `kalender_abgleich.quelle_abgleichen` direkt auf. Das ist der sofortige erste Abgleich; die UI braucht dafür kein Geheimnis.
  - Test `test_ical_quelle_sofort_abgeglichen`: Nach dem POST stehen Termine in `kalender_termine`.
- [ ] **Step 4: Run** `tests/test_kalender_verbinden.py`, expect PASS.
- [ ] **Step 5: Commit** `feat(kalender): Kalender verbinden mit Besitzer und Business/Privat`.

### Task 7: Kalender-Seite – Ebenen, von–bis, Ganztags-Zeile

**Files:**
- Modify:
  - `sales-mcp/ui.py`: `_team_ebenen` und `aktion_team_ebenen` und Route `/kalender/team` entfernen; in `kalender_abschnitte` den Aufruf entfernen.
  - `sales-mcp/ui_kalender.py`: `termine_json` übergibt `betrachter`. Der Betrachter ist `request.scope["benutzer_name"]`; ohne Anmeldung ist er `post_struktur.container_besitzer()`.
  - `kalender/src/abbild.ts`, `kalender/src/einstellungen.ts`, `kalender/src/main.ts`, `kalender/src/kalender.css`.
  - Neu: `kalender/src/ebenen.ts`.
  - Bundle unter `sales-mcp/static/kalender/`.
- Test: `kalender/src/abbild.test.ts`, `kalender/src/einstellungen.test.ts`, neu `kalender/src/ebenen.test.ts`; `sales-mcp/tests/test_ui_kalender.py`

**Interfaces:**
- Consumes: `ereignisse(...)["ebenen"]` und die Termin-Felder aus Task 5.
- Produces:
  - **`Art`** = `'kunde' | 'eigen' | 'handy' | 'kalender'`.
  - **`zuEvent`:**
    - bei `kalender` der Titel `"<titel> (<quelle>)"`;
    - bei `maskiert` ist `title === "Privattermin (<besitzer>)"`, und `editable=false`;
    - `allDay = ganztaegig`.
  - **`ebenen.ts`:**
    - `farbeFuer(ebeneId: string, index: number): string` aus fester Palette von 8 Farben;
    - `ausgeschaltet(): Set<string>` und `umschalten(id: string): void` über `localStorage` (`vk-ebenen-aus`; jeder Zugriff in try/catch);
    - `filtern(events, aus)`.

- [ ] **Step 1: Failing tests (vitest):**

```ts
it('zeigt von-bis in jeder Ansicht', () => {
  const o = grundOptionen(true);
  expect(o.displayEventEnd).toBe(true);
  expect(o.allDaySlot).toBe(true);
  expect(o.eventTimeFormat).toEqual({ hour: '2-digit', minute: '2-digit', hour12: false });
});
it('maskierter Termin zeigt nur Privattermin', () => {
  const ev = zuEvent({ id: 'k:1', art: 'kalender', titel: 'Privattermin', beginn: B, ende: E,
    bearbeitbar: false, maskiert: true, besitzer: 'ivan', quelle: 'Privat' } as Ereignis);
  expect(ev.title).toBe('Privattermin (ivan)');
  expect(ev.editable).toBe(false);
});
it('ausgeschaltete Ebene wird gefiltert', () => { /* filtern([...], new Set(['q1'])) */ });
```

  Python: `test_termine_json_maskiert_fuer_ivan`: Als ivan angemeldet liefert `/kalender/termine.json` für die Quelle von felix/privat „Privattermin“. `test_keine_team_ebenen_box`: `/kalender` enthält „Team-Ebenen“ nicht mehr.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
  - Ebenen-Leiste über dem Kalender: Schalter je Ebene mit Farbpunkt, aus `ebenen` der Antwort.
  - Termin-Schrift in `.fc-event` mindestens `0.85rem`.
  - Detail-Dialog (`detailsOeffnen`): bei maskiert nur Zeit von–bis und Besitzer; sonst Titel, Ort, Zeit und „steht in: <kalender>“.
  - Danach `npm run build`.
- [ ] **Step 4: Run** `cd kalender && npm test` und den Python-Testlauf `tests/test_ui_kalender.py tests/test_kalender_paket.py`, expect PASS.
- [ ] **Step 5: Commit** `feat(kalender): Ebenen je Kalender, von-bis und Ganztagszeile`.

> **Zwischenstand:** Nach Task 7 ist alles ohne Google ausrollbar. Das bringt den spürbaren Nutzen: Der Betreiber sieht seine Termine voll. Ausrollen nur mit OK.

### Task 8: Google-Zugang (Client) und Abgleich für Google-Quellen

**Files:**
- Create: `sales-mcp/google_kalender.py`, `deploy/kalender-schluessel.sh` (Kopie des Musters `deploy/post-schluessel.sh` mit `KALENDER_SCHLUESSEL_*`), `deploy/google-kalender-zugang.sh` (fragt Client-ID und Client-Secret per `read -s` ab und schreibt sie in die `.env`, Muster `deploy/postfach-zugang.sh`; nichts erscheint in der Ausgabe)
- Modify:
  - `sales-mcp/post_tresor.py`: `versiegeln(klartext, oeffentlich_pem=None, env_name=ENV_OEFFENTLICH)` und `oeffnen(versiegelt, privat_pem=None, env_name=ENV_PRIVAT)`; die Vorgaben bleiben, damit die Post-Aufrufer unverändert funktionieren.
  - `sales-mcp/kalender_abgleich.py`: `google`-Zweig.
  - `docker-compose.yml`:
    - `KALENDER_SCHLUESSEL_PRIVAT` + `GOOGLE_KALENDER_*` nur bei `sales-kalender`;
    - `KALENDER_SCHLUESSEL_OEFFENTLICH` + `GOOGLE_KALENDER_*` bei `sales-ui`.
- Test: `sales-mcp/tests/test_google_kalender.py`, `tests/test_kalender_abgleich.py`, `tests/test_post_tresor.py`, neuer Compose-Test `test_kalender_schluessel_nur_bei_sales_kalender`

**Interfaces:**
- Produces in `google_kalender.py`, alle HTTP-Aufrufe über eine Funktion `_anfrage(methode, url, daten=None, token=None) -> dict` (in Tests gemockt):
  - `class GoogleFehler(Exception)` mit festen Texten; `ZUGANG_ABGELAUFEN = "Zugang abgelaufen – bitte neu verbinden"`.
  - `SCOPES` (Global Constraints), `RUECKSPRUNG_PFAD = "/team/kalender/google/zurueck"`.
  - `def ruecksprung_url() -> str` (`UI_BASIS_URL` ohne Schrägstrich am Ende + Pfad).
  - `def anmelde_url(state: str) -> str`.
  - `def code_tauschen(code: str) -> dict` → `{"refresh_token": str, "access_token": str}`. Fehlt `refresh_token`, wirft die Funktion `GoogleFehler("Google hat keinen dauerhaften Zugang geliefert")`.
  - `def zugang_erneuern(refresh_token: str) -> str`. Bei `invalid_grant` wirft sie `GoogleFehler(ZUGANG_ABGELAUFEN)`.
  - `def kalender_liste(access_token: str) -> list[dict]` → `[{"id", "name", "primaer": bool}]`, alle Seiten.
  - `def termine(access_token: str, kalender_id: str, von: datetime, bis: datetime) -> list[dict]`:
    - Rückgabe in derselben Form wie `kalenderquellen.hole`, also `beginn, ende, titel, ort, uid, ganztaegig, frei`.
    - Abfrage mit `singleEvents=true`, `maxResults=2500`, allen Seiten.
    - `status == "cancelled"` fällt raus; `transparency == "transparent"` ergibt `frei=True`.
- `kalender_abgleich.quelle_abgleichen` mit `art == "google"`:
  1. Konto lesen;
  2. `post_tresor.oeffnen(..., env_name="KALENDER_SCHLUESSEL_PRIVAT")`;
  3. `zugang_erneuern`;
  4. `termine`;
  5. speichern wie bei iCal.
  - Ein Access-Token pro Konto und Runde.

- [ ] **Step 1: Failing tests:**
  - `test_abgesagte_termine_fallen_raus` (Review Focus 2).
  - `test_ganztaegig_und_transparent`: `start.date` ergibt `ganztaegig`; `transparency` ergibt `frei` (Review Focus 1).
  - `test_invalid_grant_wird_luecke` (Review Focus 3): Nach `quelle_abgleichen` ist `letzter_fehler == ZUGANG_ABGELAUFEN`, und `kalendertermine_lesen` meldet eine Lücke.
  - `test_fehlertext_ohne_token`: Mit `_anfrage` als HTTP 400 samt Body, der Token und Secret enthält, steht nichts davon in `str(fehler)` oder `caplog.text`.
  - `test_seiten_werden_alle_gelesen`: `nextPageToken`.
  - `test_tresor_mit_eigenem_schluesselpaar`: versiegeln/öffnen über `env_name`.
  - Compose: `KALENDER_SCHLUESSEL_PRIVAT` steht nur in `sales-kalender`; `GOOGLE_KALENDER_CLIENT_SECRET` nur in `sales-kalender` und `sales-ui`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_google_kalender.py tests/test_kalender_abgleich.py tests/test_post_tresor.py tests/test_post_abholen.py`, expect PASS.
- [ ] **Step 5: Commit** `feat(kalender): Google-Kalender lesen und abgleichen`.

### Task 9: „Mit Google verbinden“ in der Oberfläche

**Files:**
- Modify: `sales-mcp/ui.py` (Knopf in `team_kalender`, Routen `GET /team/kalender/google/start`, `GET /team/kalender/google/zurueck`, `POST /team/kalender/google/uebernehmen`, Rollen-Ausnahmen); `sales-mcp/server.py` (`kalenderkonto_speichern`, `kalenderkonto_lesen`, `google_quelle_speichern`)
- Test: `sales-mcp/tests/test_kalender_google_ui.py`

**Interfaces:**
- Consumes: `google_kalender.anmelde_url/code_tauschen/kalender_liste` (Task 8); `post_tresor.versiegeln(..., env_name="KALENDER_SCHLUESSEL_OEFFENTLICH")`.
- Produces:
  - `server.kalenderkonto_speichern(besitzer: str, adresse: str, zugang_versiegelt: str, kalender_liste: list[dict]) -> str`: Upsert auf `(besitzer, 'google', adresse)`; `adresse` ist die `id` des primären Kalenders.
  - `server.kalenderkonto_lesen(konto_id: str) -> dict | None`.
  - `server.google_quelle_speichern(konto_id: str, google_id: str, anzeigename: str, besitzer: str, bereich: str) -> str`: Upsert auf `(besitzer, anzeigename)`, `art='google'`, `url=null`.
  - In `ui.py`:
    - `_google_state(name: str) -> str`: HMAC mit `UI_SESSION_SECRET` über Name und Ablauf (10 Minuten).
    - `_google_state_pruefen(state: str) -> str | None`.
- Ablauf:
  1. `start` leitet auf `anmelde_url(_google_state(akteur))`.
  2. `zurueck` prüft den State (der Name muss die angemeldete Person sein). Dann `code_tauschen`, `kalender_liste`, Token versiegeln, `kalenderkonto_speichern`, und das Auswahlformular zeigen: je Kalender „übernehmen“ plus Pflicht-Radio Business/Privat.
  3. `uebernehmen` legt die gewählten Quellen an und stößt keinen Abruf in der UI an; die UI hat den privaten Schlüssel nicht. Die Seite sagt „Erste Termine erscheinen innerhalb einer Minute“; der Abgleich-Dienst prüft neue Quellen alle 30 s (Task 4).
  - Fehlt eine `GOOGLE_KALENDER_*`- oder `KALENDER_SCHLUESSEL_OEFFENTLICH`-Variable, zeigt der Knopf den Hinweis „Google-Anbindung ist noch nicht eingerichtet“ und ist inaktiv.
  - Auf „Meine Kalender“ steht unter Google-Quellen der Hinweis „Zugriff bei Google entziehen: myaccount.google.com/permissions“.
  - Beim Entfernen der letzten Quelle eines Kontos wird dessen `zugang_versiegelt` auf NULL gesetzt.

- [ ] **Step 1: Failing tests** (Google-Aufrufe gemockt):
  - `test_state_eines_anderen_wird_abgewiesen`: State für `felix`, angemeldet als `ivan` → 400, nichts gespeichert.
  - `test_abgelaufener_state`: 11 Minuten alt → 400.
  - `test_token_wird_versiegelt_gespeichert`: Die DB-Zeile enthält den Klartext-Token nicht; `oeffnen` mit dem Testschlüssel ergibt ihn.
  - `test_auswahl_ohne_bereich_abgewiesen`.
  - `test_ohne_einrichtung_kein_knopf`.
  - `test_letzte_quelle_entfernt_vernichtet_zugang`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_kalender_google_ui.py tests/test_kalender_verbinden.py`, expect PASS.
- [ ] **Step 5: Commit** `feat(kalender): Mit Google verbinden`.

### Task 10: Anleitung und Ausroll-Schritte (nur Doku)

**Files:**
- Modify: `docs/03_RUNBOOK.md` (neuer Abschnitt „Kalender verbinden (Google)“); `docs/06_DSGVO.md` (Abschnitt Kalender: Besitzer, Bereich, fremde Privattermine nur mit Zeit, versiegelte Google-Zugänge)
- Test: keiner. Prüfung: Jede im Runbook genannte Datei bzw. jedes Skript existiert (`test -f`).

- [ ] **Step 1: Runbook schreiben.**
  - **Google-Projekt anlegen (Betreiber, Schritt für Schritt):**
    - neues Projekt, Google Calendar API aktivieren;
    - Zustimmungsbildschirm Extern, Status „In Produktion“;
    - OAuth-Client „Webanwendung“ mit Rücksprung `<UI_BASIS_URL>/team/kalender/google/zurueck`.
  - **Dann:**
    1. `bash deploy/google-kalender-zugang.sh`;
    2. `bash deploy/kalender-schluessel.sh`;
    3. `db/kalender-verbinden.sql` mit `-v schema=sales -v besitzer=felix`;
    4. `bash deploy/update.sh`;
    5. `docker compose up -d sales-kalender`.
    - Jeder Schritt braucht das OK des Betreibers.
  - **Probe:** `/team/kalender` → Google verbinden → nach etwa einer Minute Termine im Kalender.
  - **Hinweis:** Lehnt Google den Rücksprung ab: anhalten, nicht umbauen (Spec §5).
- [ ] **Step 2: Prüfen**, dass alle genannten Pfade existieren.
- [ ] **Step 3: Commit** `docs(kalender): Anleitung Google-Kalender und Ausrollen`.
