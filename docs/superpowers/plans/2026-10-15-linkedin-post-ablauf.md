# LinkedIn-Post-Ablauf Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LinkedIn-Posts entstehen über einen Fragebogen-Skill. Die Markier-Liste hängt am Entwurf, und nach dem Veröffentlichen bekommt der Betreiber Link und Liste automatisch per WhatsApp.

**Architecture:**
- **Markier-Liste:** Ein neues Agent-Werkzeug speichert sie als Aktivität `linkedin_markierungen` (keine Schemaänderung). Die Freigabe-Seite zeigt sie an.
- **Meldung nach dem Posten:** Das Modul `linkedin_nachlauf.py` im Image `sales-mcp` findet unmeldete Veröffentlichungen und baut den Meldetext. Ein Wirt-Skript holt beides per systemd-Timer alle 2 Minuten ab, sendet über `openclaw message send` im Gateway-Container und bucht erst danach `linkedin_nachlauf_gemeldet`.
- **Skill:** Der Skill `linkedin-post` wird neu geschrieben (Fragebogen → Markier-Liste → Schreiben → Vorschau).

**Tech Stack:** Python 3.12 (sales-mcp, psycopg, pytest, Starlette-TestClient), Bash + systemd (VM), openclaw 2026.7.1 CLI, Markdown-Skill.

**Spec:** `docs/superpowers/specs/2026-10-15-linkedin-post-ablauf-design.md`

## Global Constraints

- Repo `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`, direkt dort committen. Vor jedem Commit `git rev-parse --show-toplevel` und `git branch --show-current` prüfen.
- Conventional Commits auf Deutsch, Trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Nur eigene Dateien stagen, nie `.superpowers/`, nie stashen, keine Hooks umgehen.
- Code-Kommentare im Stil der Dateien: Deutsch, Umlaute als ae/oe/ue.
- Tests: venv `E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe`, aus `sales-mcp/` mit `python -m pytest -q tests/<datei>`. Die Test-DB (Postgres :55432, Schema `sales_test`) muss laufen, `SALES_DB_URL` wie in den bestehenden DB-Tests. Bekannte vorbestehende Rote (nicht jagen): `test_anker_deckt_alle_gelesenen_caldav_und_verwandten_variablen_ab`, `test_termin_einladen`-Datumsfehler, 2 Medienordner-Fehler in `test_werkzeuge`. Jedes andere Rot gegen BASE in einem Wegwerf-Worktree prüfen.
- Aktivitätstypen, wörtlich: `linkedin_markierungen` (Nutzlast `{"draft_id": str, "eintraege": [{"name": str, "art": "person"|"firma", "profil": str}]}`), `linkedin_nachlauf_gemeldet` (Nutzlast `{"draft_id": str}`).
- Markier-Liste: höchstens 20 Einträge, `name` 1–120 Zeichen, `art` ∈ {person, firma}, `profil` leer oder beginnt mit `https://www.linkedin.com/` oder `https://linkedin.com/`.
- Meldefenster: `versand`-Aktivitäten mit `payload->>'kanal'='linkedin'` und nicht leerem `payload->>'beitrag'` aus den letzten 24 h.
- Post-Link: `https://www.linkedin.com/feed/update/<urn>/`
- Timer: alle 2 Minuten, nur Basis-Laden, Container `sales-mcp` und `sales-claw`. Betreiber-Nummer aus `SALES_BETREIBER_WHATSAPP` (`.env`), Format `^\+[0-9]{8,15}$`.
- Der Dienst `sales-linkedin` bekommt keinen WhatsApp-Zugang.

## Review Focus

- **Gelöschter oder alter Post beim ersten Timer-Lauf:** Der Hackathon-Post `f012dd6b` (versendet 14.10. 22:48 UTC, inzwischen gelöscht) darf nicht gemeldet werden. Task 6 bucht ihn vor dem Aktivieren als gemeldet. Task 2 testet zusätzlich die 24-h-Grenze.
- **Unsichere oder manuelle Versand-Zeilen** (`beitrag: null`, `ungewiss: true`, `weg: manuell`): Sie werden nie gemeldet (Test in Task 2).
- **Sonderzeichen und Zeilenumbrüche im Meldetext** (Namen mit `&`, `"`, `$`, Backticks): Sie gehen wörtlich an WhatsApp, ohne Shell-Interpolation (Test in Task 3).
- **Senden scheitert** (Gateway down, CLI exit ≠ 0): Nicht als gemeldet buchen, nächster Lauf versucht es erneut (Test in Task 3).
- **Markier-Liste mit HTML/Script im Namen** auf der Freigabe-Seite: escaped (Test in Task 4).

---

### Task 1: Werkzeug `post_markierungen_setzen` + Prompt-Korrektur

**Files:**
- Modify: `sales-mcp/server.py`: neues Werkzeug nach `post_entwurf_erstellen` (~2523), Lesehelfer `post_markierungen(draft_id)`, Eintrag in `WERKZEUGE` (~8122, nach `post_entwurf_erstellen`)
- Modify: `sales-mcp/tests/test_werkzeuge.py:702-718` (Zahl 92 → 93, Changelog-Kommentar)
- Modify: `config/workspace/AGENTS.md` (Abschnitt „LinkedIn-Posts (eigenes Profil)“ ~303-311, Kundenchat-tabu-Liste ~588)
- Create: `sales-mcp/tests/test_post_markierungen.py`
- Modify: `sales-mcp/tests/test_agents_regeln.py` (zwei neue Prüfungen)

**Interfaces:**
- Produces: `server.post_markierungen_setzen(draft_id: str, eintraege: list) -> str` (JSON `{"draft_id","anzahl"}` | `{"fehler"}`); `server.post_markierungen(draft_id: str) -> list[dict]` (jüngste Buchung, `[]` wenn keine). Task 2 und Task 4 nutzen `post_markierungen`.

- [ ] **Step 1: Failing tests schreiben** (`sales-mcp/tests/test_post_markierungen.py`)

```python
"""Markier-Liste fuer LinkedIn-Beitraege (Spec 2026-10-15 §4.2)."""
import inspect
import json
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def sammelkontakt(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    sammel = server._q("insert into leads (name, source) values "
                       "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", str(sammel))
    return str(sammel)


def _post(thema="Hackathon"):
    return json.loads(server.post_entwurf_erstellen(thema, "We didn't win."))["draft_id"]


PERSON = {"name": "Peter Steinacker", "art": "person",
          "profil": "https://www.linkedin.com/in/peter-steinacker-7823aa220"}
FIRMA = {"name": "BMW Group", "art": "firma", "profil": ""}


def test_setzen_und_lesen():
    d = _post()
    r = json.loads(server.post_markierungen_setzen(d, [PERSON, FIRMA]))
    assert r == {"draft_id": d, "anzahl": 2}
    assert server.post_markierungen(d) == [PERSON, FIRMA]


def test_juengste_buchung_gilt_und_leere_liste_loescht():
    d = _post()
    server.post_markierungen_setzen(d, [PERSON, FIRMA])
    server.post_markierungen_setzen(d, [FIRMA])
    assert server.post_markierungen(d) == [FIRMA]
    server.post_markierungen_setzen(d, [])
    assert server.post_markierungen(d) == []


def test_ohne_buchung_leer():
    assert server.post_markierungen(_post()) == []


@pytest.mark.parametrize("eintrag", [
    {"name": "", "art": "person", "profil": ""},
    {"name": "x" * 121, "art": "person", "profil": ""},
    {"name": "A", "art": "kunde", "profil": ""},
    {"name": "A", "art": "person", "profil": "https://evil.example/in/a"},
    {"name": "A", "art": "person", "profil": "http://www.linkedin.com/in/a"},
    {"name": "A", "art": "person"},
    "Peter",
])
def test_ungueltige_eintraege(eintrag):
    d = _post()
    r = json.loads(server.post_markierungen_setzen(d, [eintrag]))
    assert "fehler" in r
    assert server.post_markierungen(d) == []


def test_hoechstens_zwanzig():
    d = _post()
    r = json.loads(server.post_markierungen_setzen(d, [FIRMA] * 21))
    assert "fehler" in r


def test_nur_fuer_beitraege_pending_oder_approved(sammelkontakt):
    d = _post()
    server._q("update drafts set status='sent' where id=%s", (d,))
    assert "fehler" in json.loads(server.post_markierungen_setzen(d, [FIRMA]))
    dm = server._q(
        "insert into drafts (lead_id, channel, recipient, body) values "
        "(%s, 'linkedin', 'Peter', 'Hallo') returning id", (sammelkontakt,))[0]["id"]
    assert "fehler" in json.loads(server.post_markierungen_setzen(str(dm), [FIRMA]))
    assert "fehler" in json.loads(server.post_markierungen_setzen(
        "00000000-0000-0000-0000-000000000000", [FIRMA]))
    assert "fehler" in json.loads(server.post_markierungen_setzen("kaputt", [FIRMA]))


def test_approved_erlaubt():
    d = _post()
    server._q("update drafts set status='approved' where id=%s", (d,))
    assert json.loads(server.post_markierungen_setzen(d, [FIRMA]))["anzahl"] == 1


def test_registriert_und_signatur():
    assert server.post_markierungen_setzen in server.WERKZEUGE
    assert list(inspect.signature(server.post_markierungen_setzen).parameters) == [
        "draft_id", "eintraege"]
```

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_post_markierungen.py`
Expected: FAIL mit `AttributeError: module 'server' has no attribute 'post_markierungen_setzen'`

- [ ] **Step 3: Implementieren** (`server.py`, direkt nach `post_entwurf_erstellen`)

```python
# Markier-Liste (Spec 2026-10-15 §4.2). Echte @-Markierungen gehen ueber die
# LinkedIn-API nicht (fremde Personen-IDs nicht ermittelbar, Firmen-Lookup
# 403) — der Betreiber markiert nach dem Posten von Hand; diese Liste sagt
# ihm, wen. Als Aktivitaet gebucht, juengste gilt; kein Schema-Eingriff.
MARKIER_MAX = 20
MARKIER_NAME_MAX = 120
_MARKIER_PROFIL_PRAEFIXE = ("https://www.linkedin.com/", "https://linkedin.com/")


def _markier_eintrag_fehler(e) -> str | None:
    if not isinstance(e, dict):
        return "Jeder Eintrag braucht name, art und profil."
    name, art, profil = e.get("name"), e.get("art"), e.get("profil")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= MARKIER_NAME_MAX:
        return f"name fehlt oder ist laenger als {MARKIER_NAME_MAX} Zeichen."
    if art not in ("person", "firma"):
        return "art muss 'person' oder 'firma' sein."
    if not isinstance(profil, str):
        return "profil fehlt (leer lassen, wenn es keinen Link gibt)."
    if profil and not profil.startswith(_MARKIER_PROFIL_PRAEFIXE):
        return "profil muss leer sein oder mit https://www.linkedin.com/ beginnen."
    return None


@_gesichert
def post_markierungen_setzen(draft_id: str, eintraege: list) -> str:
    """Hinterlegt am LinkedIn-BEITRAG, wen der Betreiber nach dem Posten von
    Hand markiert: Liste aus {name, art: 'person'|'firma', profil: '<https://
    www.linkedin.com/...>' oder ''}, hoechstens 20. Ersetzt die vorige Liste,
    eine leere Liste loescht sie. Nur fuer Beitraege (eigenes Profil) im
    Status pending oder approved. Den Betreiber selbst nie eintragen. Nach
    dem Veroeffentlichen bekommt er Post-Link und Liste automatisch per
    WhatsApp. Veroeffentlicht und sendet NICHTS."""
    try:
        uuid.UUID(str(draft_id))
    except ValueError:
        return _json({"fehler": f"'{draft_id}' ist keine gueltige draft_id."})
    if not isinstance(eintraege, list):
        return _json({"fehler": "eintraege muss eine Liste sein."})
    if len(eintraege) > MARKIER_MAX:
        return _json({"fehler": f"Hoechstens {MARKIER_MAX} Markierungen."})
    for e in eintraege:
        fehler = _markier_eintrag_fehler(e)
        if fehler:
            return _json({"fehler": fehler})
    zeilen = _q("select lead_id, status, channel, recipient from drafts "
                "where id = %s", (draft_id,))
    if not zeilen:
        return _json({"fehler": f"Kein Entwurf mit draft_id {draft_id}."})
    d = zeilen[0]
    if d["channel"] != "linkedin" or d["recipient"] != "eigenes-profil":
        return _json({"fehler": "Markierungen gibt es nur fuer LinkedIn-Beitraege "
                                "auf dem eigenen Profil."})
    if d["status"] not in ("pending", "approved"):
        return _json({"fehler": f"Entwurf steht auf '{d['status']}' — "
                                "Markierungen nur vor dem Veroeffentlichen."})
    sauber = [{"name": e["name"].strip(), "art": e["art"], "profil": e["profil"]}
              for e in eintraege]
    _q("insert into activities (lead_id, type, payload) values "
       "(%s, 'linkedin_markierungen', %s) returning id",
       (d["lead_id"], json.dumps({"draft_id": str(draft_id), "eintraege": sauber},
                                 ensure_ascii=False)))
    return _json({"draft_id": str(draft_id), "anzahl": len(sauber)})


def post_markierungen(draft_id: str) -> list:
    """Juengste Markier-Liste eines Beitrags, [] wenn keine (kein Werkzeug)."""
    z = _q("select payload from activities where type = 'linkedin_markierungen' "
           "and payload->>'draft_id' = %s order by created_at desc, id desc limit 1",
           (str(draft_id),))
    return list((z[0]["payload"] or {}).get("eintraege") or []) if z else []
```

Prüfen, ob `uuid` in `server.py` importiert ist (`grep -n "^import uuid" sales-mcp/server.py`). Falls nicht, oben `import uuid` ergänzen. Ist `id` in `activities` keine sortierbare Spalte, `, id desc` weglassen.

`WERKZEUGE` (direkt nach `post_entwurf_erstellen`):

```python
    # Markier-Liste fuer LinkedIn-Beitraege (15.10.2026), Vertraege:
    # tests/test_post_markierungen.py.
    post_markierungen_setzen,
```

`tests/test_werkzeuge.py`: Changelog-Zeile `# 15.10.2026: post_markierungen_setzen (Markier-Liste LinkedIn), 92 -> 93.` ergänzen, `assert len(namen) == 93`.

- [ ] **Step 4: AGENTS.md anpassen**

Im Abschnitt `## LinkedIn-Posts (eigenes Profil)` den Absatz ab „`post_entwurf_erstellen(thema, text, medien_datei='')` legt einen POST fuer“ bis „ist das sein Merkposten, welches Bild/PDF er mit hochlaedt.“ ersetzen durch:

```markdown
`post_entwurf_erstellen(thema, text, medien_datei='')` legt einen POST fuer
das eigene LinkedIn-Profil des Betreibers in die Freigabe-Queue — kein
Empfaenger, Betreff „Post: <thema>". **Nichts geht ohne seine Freigabe
raus.** Nach der Freigabe veroeffentlicht der Dienst sales-linkedin den
Beitrag ueber die offizielle LinkedIn-API (Text plus Bild oder Video aus
`medien_datei`). **Jeder LinkedIn-Beitrag laeuft ueber den Skill
`linkedin-post`** (Fragebogen, Vorschau, Markier-Liste).

`post_markierungen_setzen(draft_id, eintraege)` hinterlegt, wen der
Betreiber nach dem Posten von Hand markiert (Personen und Firmen, je
`{name, art, profil}`) — @-Markierungen gehen ueber die API nicht. Nach dem
Veroeffentlichen bekommt er Post-Link und Liste automatisch per WhatsApp.
Den Betreiber selbst nie eintragen.
```

In der Kundenchat-tabu-Liste `` `medien_aus_chat_uebernehmen`, `post_entwurf_erstellen` sowie jede Recherche `` ersetzen durch `` `medien_aus_chat_uebernehmen`, `post_entwurf_erstellen`, `post_markierungen_setzen` sowie jede Recherche ``.

In `tests/test_agents_regeln.py` zwei Tests im Stil der Datei ergänzen:

```python
def test_linkedin_posts_laufen_ueber_skill_und_nicht_mehr_von_hand():
    text = AGENTS.read_text(encoding="utf-8")
    assert "Skill\n`linkedin-post`" in text or "Skill `linkedin-post`" in text
    assert "kopiert der Betreiber den Text selbst" not in text


def test_markierungen_im_kundenchat_tabu():
    assert "`post_markierungen_setzen`" in _absatz("Betreiber-Werkzeuge sind im Kundenchat tabu")
```

(Konstante bzw. Hilfsfunktion der Datei verwenden. Heißt die Pfadkonstante dort anders als `AGENTS`, diesen Namen nehmen. Lautet der Anfang des tabu-Absatzes anders, den wörtlichen Anfang aus dem bestehenden Test für `medien_aus_chat_uebernehmen` übernehmen.)

- [ ] **Step 5: Grün sehen**

Run: `python -m pytest -q tests/test_post_markierungen.py tests/test_werkzeuge.py tests/test_agents_regeln.py tests/test_linkedin_posts.py`
Expected: alles grün außer den bekannten 2 Medienordner-Roten in `test_werkzeuge`.

- [ ] **Step 6: Commit**

```bash
git add sales-mcp/server.py sales-mcp/tests/test_post_markierungen.py sales-mcp/tests/test_werkzeuge.py sales-mcp/tests/test_agents_regeln.py config/workspace/AGENTS.md
git commit -m "feat(linkedin): Markier-Liste am Beitrag (post_markierungen_setzen)"
```

---

### Task 2: Modul `linkedin_nachlauf.py` (offene Meldungen, Meldetext, Buchung)

**Files:**
- Create: `sales-mcp/linkedin_nachlauf.py`
- Create: `sales-mcp/tests/test_linkedin_nachlauf.py`

**Interfaces:**
- Consumes: `server.post_markierungen(draft_id) -> list[dict]` (Task 1), `server._q`.
- Produces (CLI, von Task 3 aufgerufen, Arbeitsverzeichnis `/app`):
  - `python linkedin_nachlauf.py liste` gibt je offene Meldung eine Zeile mit der `draft_id` aus, Exit 0.
  - `python linkedin_nachlauf.py text <draft_id>` gibt den Meldetext aus (mehrzeilig, UTF-8), Exit 0. Ist die draft_id nicht offen, Exit 3.
  - `python linkedin_nachlauf.py gemeldet <draft_id>` bucht `linkedin_nachlauf_gemeldet`, Exit 0.
- Python-API: `offene_meldungen() -> list[dict]` (`{"draft_id","beitrag"}`), `meldetext(draft_id: str, beitrag: str) -> str`, `als_gemeldet_buchen(draft_id: str) -> None`.

- [ ] **Step 1: Failing tests** (`sales-mcp/tests/test_linkedin_nachlauf.py`)

```python
"""Meldung nach dem Posten (Spec 2026-10-15 §4.4)."""
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402
import linkedin_nachlauf as nl  # noqa: E402

HIER = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def sammel(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    s = server._q("insert into leads (name, source) values "
                  "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", str(s))
    return str(s)


def _versand(sammel, beitrag="urn:li:share:1", alter_h=0, **extra):
    d = server._q("insert into drafts (lead_id, channel, recipient, body, status) "
                  "values (%s, 'linkedin', 'eigenes-profil', 'x', 'sent') returning id",
                  (sammel,))[0]["id"]
    payload = {"draft_id": str(d), "kanal": "linkedin", "weg": "linkedin-dispatcher",
               "empfaenger": "eigenes-profil", "beitrag": beitrag, "medienart": "bild",
               **extra}
    server._q("insert into activities (lead_id, type, payload, created_at) values "
              "(%s, 'versand', %s, now() - make_interval(hours => %s)) returning id",
              (sammel, json.dumps(payload), alter_h))
    return str(d)


def test_offen_und_nach_buchung_nicht_mehr(sammel):
    d = _versand(sammel)
    assert [m["draft_id"] for m in nl.offene_meldungen()] == [d]
    nl.als_gemeldet_buchen(d)
    assert nl.offene_meldungen() == []


def test_aelter_als_24h_nie(sammel):
    _versand(sammel, alter_h=25)
    assert nl.offene_meldungen() == []


def test_ungewiss_und_manuell_nie(sammel):
    _versand(sammel, beitrag=None, ungewiss=True)
    _versand(sammel, beitrag=None, weg="manuell")
    assert nl.offene_meldungen() == []


def test_whatsapp_versand_nie(sammel):
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'versand', %s) returning id",
              (sammel, json.dumps({"kanal": "whatsapp", "draft_id": "x"})))
    assert nl.offene_meldungen() == []


def test_text_ohne_liste(sammel):
    d = _versand(sammel, beitrag="urn:li:share:7516268598298845185")
    t = nl.meldetext(d, "urn:li:share:7516268598298845185")
    assert t.startswith("LinkedIn-Post ist online: "
                        "https://www.linkedin.com/feed/update/urn:li:share:7516268598298845185/")
    assert "markieren" not in t


def test_text_mit_liste(sammel):
    d = _versand(sammel)
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'linkedin_markierungen', %s) returning id",
              (sammel, json.dumps({"draft_id": d, "eintraege": [
                  {"name": "Peter Steinacker", "art": "person",
                   "profil": "https://www.linkedin.com/in/p"},
                  {"name": "BMW Group", "art": "firma", "profil": ""}]})))
    t = nl.meldetext(d, "urn:li:share:1")
    assert "Jetzt in der App markieren (Bearbeiten → @Name):" in t
    assert "- @Peter Steinacker · Person · https://www.linkedin.com/in/p" in t
    assert "- @BMW Group · Firma" in t


def _cli(*args):
    return subprocess.run([sys.executable, "linkedin_nachlauf.py", *args], cwd=HIER,
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "SALES_DB_SCHEMA": "sales_test"})


def test_cli_liste_text_gemeldet(sammel):
    d = _versand(sammel)
    r = _cli("liste")
    assert r.returncode == 0 and r.stdout.split() == [d]
    r = _cli("text", d)
    assert r.returncode == 0 and "feed/update/urn:li:share:1/" in r.stdout
    assert _cli("gemeldet", d).returncode == 0
    assert _cli("liste").stdout.strip() == ""
    assert _cli("text", d).returncode == 3
```

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_linkedin_nachlauf.py`
Expected: FAIL mit `ModuleNotFoundError: No module named 'linkedin_nachlauf'`

- [ ] **Step 3: Implementieren** (`sales-mcp/linkedin_nachlauf.py`)

```python
"""Meldung nach dem Posten (Spec 2026-10-15 §4.4).

Findet LinkedIn-Veroeffentlichungen der letzten 24 h, zu denen der
Betreiber noch keine Meldung bekommen hat, und baut den Meldetext (Post-
Link + Markier-Liste). GESENDET wird hier nichts: das macht
deploy/linkedin-nachlauf.sh auf dem Wirt ueber den Gateway-Kanal und ruft
erst nach Erfolg `gemeldet` — so bleibt sales-linkedin ohne WhatsApp-Zugang.

CLI (Arbeitsverzeichnis /app im Container sales-mcp):
  python linkedin_nachlauf.py liste               -> je Zeile eine draft_id
  python linkedin_nachlauf.py text <draft_id>     -> Meldetext (Exit 3: nicht offen)
  python linkedin_nachlauf.py gemeldet <draft_id> -> bucht die Meldung
"""
import json
import sys

import server

FENSTER_STUNDEN = 24
POST_URL = "https://www.linkedin.com/feed/update/{urn}/"
_ART = {"person": "Person", "firma": "Firma"}


def offene_meldungen() -> list:
    """[{draft_id, beitrag}] — veroeffentlicht (Beitrags-URN vorhanden),
    juenger als 24 h, noch nicht gemeldet. Unsichere und manuelle Versand-
    zeilen tragen keine URN und fallen damit heraus."""
    zeilen = server._q(
        "select v.payload->>'draft_id' as draft_id, v.payload->>'beitrag' as beitrag "
        "from activities v where v.type = 'versand' "
        "and v.payload->>'kanal' = 'linkedin' "
        "and coalesce(v.payload->>'beitrag', '') <> '' "
        "and v.created_at > now() - make_interval(hours => %s) "
        "and not exists (select 1 from activities g "
        "  where g.type = 'linkedin_nachlauf_gemeldet' "
        "  and g.payload->>'draft_id' = v.payload->>'draft_id') "
        "order by v.created_at", (FENSTER_STUNDEN,))
    return [{"draft_id": z["draft_id"], "beitrag": z["beitrag"]} for z in zeilen]


def meldetext(draft_id: str, beitrag: str) -> str:
    zeilen = [f"LinkedIn-Post ist online: {POST_URL.format(urn=beitrag)}"]
    liste = server.post_markierungen(draft_id)
    if liste:
        zeilen += ["", "Jetzt in der App markieren (Bearbeiten → @Name):"]
        for e in liste:
            teile = [f"- @{e['name']}", _ART.get(e.get("art"), "Person")]
            if e.get("profil"):
                teile.append(e["profil"])
            zeilen.append(" · ".join(teile))
    return "\n".join(zeilen)


def als_gemeldet_buchen(draft_id: str) -> None:
    lead = server._q("select lead_id from drafts where id = %s", (draft_id,))
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'linkedin_nachlauf_gemeldet', %s, 'cron') returning id",
              (lead[0]["lead_id"] if lead else None,
               json.dumps({"draft_id": str(draft_id)})))


def main(argv) -> int:
    if len(argv) >= 1 and argv[0] == "liste":
        for m in offene_meldungen():
            print(m["draft_id"])
        return 0
    if len(argv) == 2 and argv[0] == "text":
        treffer = [m for m in offene_meldungen() if m["draft_id"] == argv[1]]
        if not treffer:
            return 3
        sys.stdout.write(meldetext(argv[1], treffer[0]["beitrag"]) + "\n")
        return 0
    if len(argv) == 2 and argv[0] == "gemeldet":
        als_gemeldet_buchen(argv[1])
        return 0
    print("Aufruf: liste | text <draft_id> | gemeldet <draft_id>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
```

Prüfen: Erlaubt `activities.actor` den Wert `'cron'`? (`db/provision.sql:103-109` sagt `check (actor in ('agent','human','cron'))`, also ja.)

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_linkedin_nachlauf.py`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/linkedin_nachlauf.py sales-mcp/tests/test_linkedin_nachlauf.py
git commit -m "feat(linkedin): Nachlauf findet unmeldete Veroeffentlichungen und baut den Meldetext"
```

---

### Task 3: Wirt-Skript `deploy/linkedin-nachlauf.sh` + systemd-Timer

**Files:**
- Create: `deploy/linkedin-nachlauf.sh`
- Create: `deploy/systemd/sales-linkedin-nachlauf.service`, `deploy/systemd/sales-linkedin-nachlauf.timer`
- Create: `deploy/tests/test_linkedin_nachlauf.sh`
- Modify: `.env.example` (Variable `SALES_BETREIBER_WHATSAPP` mit Kommentar)
- Modify: `docs/03_RUNBOOK.md` (Installationsabschnitt, Muster wie whatsapp-kopplung ~3003)

**Interfaces:**
- Consumes: CLI aus Task 2 (`liste`, `text <id>`, `gemeldet <id>`), `openclaw message send --channel whatsapp --target <E.164> -m <text>` im Container `sales-claw`.
- Produces: `bash deploy/linkedin-nachlauf.sh [--trocken]`, Exit 0 (auch wenn Senden einzeln scheitert), Exit 2 bei fehlender/ungültiger Nummer. Überschreibbar per Umgebung: `DOCKER` (Standard `docker`), `SALES_BETREIBER_WHATSAPP` (sonst aus `$WURZEL/.env`).

- [ ] **Step 1: Failing test** (`deploy/tests/test_linkedin_nachlauf.sh`)

```bash
#!/usr/bin/env bash
# Test fuer deploy/linkedin-nachlauf.sh mit gefaelschtem docker.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKRIPT="$WURZEL/deploy/linkedin-nachlauf.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# Falsches docker: protokolliert jeden Aufruf (ein Argument je Zeile, NUL-
# frei), beantwortet die Nachlauf-CLI und laesst das Senden je nach
# $T/senden_scheitert scheitern.
cat > "$T/docker" <<'EOF'
#!/usr/bin/env bash
T="$(dirname "$0")"
{ printf 'AUFRUF'; for a in "$@"; do printf '\n<%s>' "$a"; done; printf '\n'; } >> "$T/log"
case "$*" in
  *"linkedin_nachlauf.py liste"*) printf 'd-1\n' ;;
  *"linkedin_nachlauf.py text d-1"*) printf 'LinkedIn-Post ist online: https://x/\n- @A & "B" $HOME `id`\n' ;;
  *"linkedin_nachlauf.py gemeldet d-1"*) echo gebucht >> "$T/gebucht" ;;
  *"message send"*) [ -f "$T/senden_scheitert" ] && exit 1; exit 0 ;;
esac
EOF
chmod +x "$T/docker"

fehler() { echo "FEHLER: $*"; exit 1; }

# 1. Ohne Nummer: Abbruch, nichts gesendet
leer="$T/leer"; mkdir -p "$leer"
if DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="" WURZEL_ENV="$leer/.env" bash "$SKRIPT" >/dev/null 2>&1; then
  fehler "ohne Nummer haette das Skript abbrechen muessen"
fi
[ ! -f "$T/log" ] || ! grep -q "message send" "$T/log" || fehler "ohne Nummer gesendet"

# 2. Senden scheitert: nicht gebucht
touch "$T/senden_scheitert"
DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" >/dev/null 2>&1 || true
[ ! -f "$T/gebucht" ] || fehler "trotz Sendefehler gebucht"
rm "$T/senden_scheitert"; : > "$T/log"

# 3. Erfolg: Text woertlich als EIN Argument, danach gebucht
DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" >/dev/null
grep -q '^<+491749708452>$' "$T/log" || fehler "Nummer nicht als eigenes Argument"
grep -qF '<- @A & "B" $HOME `id`>' "$T/log" || fehler "Text nicht woertlich uebergeben"
[ "$(cat "$T/gebucht")" = "gebucht" ] || fehler "nach Erfolg nicht gebucht"

# 4. --trocken: zeigt, sendet nicht, bucht nicht
rm -f "$T/gebucht"; : > "$T/log"
aus="$(DOCKER="$T/docker" SALES_BETREIBER_WHATSAPP="+491749708452" bash "$SKRIPT" --trocken)"
echo "$aus" | grep -q "LinkedIn-Post ist online" || fehler "--trocken zeigt keinen Text"
! grep -q "message send" "$T/log" || fehler "--trocken hat gesendet"
[ ! -f "$T/gebucht" ] || fehler "--trocken hat gebucht"

echo "OK linkedin-nachlauf"
```

- [ ] **Step 2: Rot sehen**

Run (Git-Bash): `bash deploy/tests/test_linkedin_nachlauf.sh`
Expected: FAIL, weil das Skript fehlt (`No such file`)

- [ ] **Step 3: Skript** (`deploy/linkedin-nachlauf.sh`)

```bash
#!/usr/bin/env bash
# deploy/linkedin-nachlauf.sh [--trocken]
#
# Meldung nach dem Posten (Spec 2026-10-15 §4.4). Vom Timer
# sales-linkedin-nachlauf alle 2 Minuten gestartet, nur Basis-Laden.
# Holt aus sales-mcp die unmeldeten LinkedIn-Veroeffentlichungen samt
# Meldetext, schickt ihn ueber den WhatsApp-Kanal des Gateways an den
# Betreiber und bucht ERST NACH erfolgreichem Senden "gemeldet". Scheitert
# das Senden, bleibt die Meldung offen und der naechste Lauf versucht es
# erneut (Fenster 24 h, siehe linkedin_nachlauf.py). Kein Sprachmodell.
#
# Der Text geht als EIN Argument (Array) an docker — keine Shell-
# Interpolation von Namen mit $, Backticks oder Anfuehrungszeichen.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER="${DOCKER:-docker}"
ENV_DATEI="${WURZEL_ENV:-$WURZEL/.env}"
TROCKEN=0
[ "${1:-}" = "--trocken" ] && TROCKEN=1

NUMMER="${SALES_BETREIBER_WHATSAPP-}"
if [ -z "$NUMMER" ]; then
  NUMMER="$({ grep -E '^SALES_BETREIBER_WHATSAPP=' "$ENV_DATEI" 2>/dev/null || true; } \
            | head -1 | cut -d= -f2- | tr -d '\r" ')"
fi
if ! [[ "$NUMMER" =~ ^\+[0-9]{8,15}$ ]]; then
  echo "FEHLER: SALES_BETREIBER_WHATSAPP fehlt oder ist keine E.164-Nummer (.env)." >&2
  exit 2
fi

offen="$("$DOCKER" exec sales-mcp python linkedin_nachlauf.py liste)"
while IFS= read -r draft_id; do
  [ -n "$draft_id" ] || continue
  text="$("$DOCKER" exec sales-mcp python linkedin_nachlauf.py text "$draft_id")" || continue
  if [ "$TROCKEN" = 1 ]; then
    printf 'TROCKEN %s an %s:\n%s\n\n' "$draft_id" "$NUMMER" "$text"
    continue
  fi
  befehl=("$DOCKER" exec sales-claw openclaw message send --channel whatsapp
          --target "$NUMMER" -m "$text")
  if "${befehl[@]}" >/dev/null 2>&1; then
    "$DOCKER" exec sales-mcp python linkedin_nachlauf.py gemeldet "$draft_id"
    echo "gemeldet: $draft_id"
  else
    echo "WARNUNG: Meldung fuer $draft_id nicht gesendet - naechster Lauf versucht es erneut." >&2
  fi
done <<< "$offen"
```

Der Aufruf von `docker` im Test ist `"$DOCKER"`, also ein Pfad. Die `case`-Muster im Fake prüfen `$*`, das passt auf `exec sales-mcp python linkedin_nachlauf.py liste`.

- [ ] **Step 4: systemd-Dateien**

`deploy/systemd/sales-linkedin-nachlauf.service`:
```ini
[Unit]
Description=sales-claw: Meldung nach dem LinkedIn-Posten (Link + Markier-Liste)

[Service]
Type=oneshot
User=debian
ExecStart=/usr/bin/bash /home/debian/sales-claw/deploy/linkedin-nachlauf.sh
```

`deploy/systemd/sales-linkedin-nachlauf.timer`:
```ini
[Unit]
Description=sales-claw: LinkedIn-Nachlauf alle 2 Minuten

[Timer]
OnCalendar=*:0/2
Persistent=false

[Install]
WantedBy=timers.target
```

`.env.example` (bei den LinkedIn-Variablen):
```
# WhatsApp-Nummer des Betreibers (E.164) fuer die Meldung nach dem LinkedIn-
# Posten (deploy/linkedin-nachlauf.sh). Kein Geheimnis.
SALES_BETREIBER_WHATSAPP=
```

`docs/03_RUNBOOK.md`: Abschnitt „LinkedIn-Nachlauf (15.10.2026)“ mit Zweck (2 Sätze) und Installation:
```
grep -q '^SALES_BETREIBER_WHATSAPP=' ~/sales-claw/.env || echo 'SALES_BETREIBER_WHATSAPP=+491749708452' >> ~/sales-claw/.env
bash ~/sales-claw/deploy/linkedin-nachlauf.sh --trocken
sudo cp ~/sales-claw/deploy/systemd/sales-linkedin-nachlauf.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sales-linkedin-nachlauf.timer
```

- [ ] **Step 5: Grün sehen**

Run: `bash deploy/tests/test_linkedin_nachlauf.sh`
Expected: `OK linkedin-nachlauf`

- [ ] **Step 6: Commit**

```bash
git add deploy/linkedin-nachlauf.sh deploy/systemd/sales-linkedin-nachlauf.service deploy/systemd/sales-linkedin-nachlauf.timer deploy/tests/test_linkedin_nachlauf.sh .env.example docs/03_RUNBOOK.md
git commit -m "feat(deploy): LinkedIn-Nachlauf meldet Post-Link und Markier-Liste per WhatsApp"
```

---

### Task 4: Freigabe-Seite zeigt die Markier-Liste, veralteter Hinweis korrigiert

**Files:**
- Modify: `sales-mcp/ui.py`: `_entwurf_karte_offen` (~1795-1825) und den Hinweis für freigegebene LinkedIn-Entwürfe (~2504-2507)
- Test: `sales-mcp/tests/test_ui.py` (neue Tests am Dateiende)

**Interfaces:**
- Consumes: `server.post_markierungen(draft_id) -> list[dict]` (Task 1).

- [ ] **Step 1: Failing tests** (Helfer `_lead`, `_entwurf`, `_get` der Datei nutzen; heißt der Empfänger-Parameter von `_entwurf` anders als `empfaenger`, den der Datei nehmen)

```python
def _markierungen(draft_id, eintraege):
    ui.server._q("insert into activities (lead_id, type, payload) select lead_id, "
                 "'linkedin_markierungen', %s from drafts where id = %s returning id",
                 (json.dumps({"draft_id": str(draft_id), "eintraege": eintraege}),
                  str(draft_id)))


def test_linkedin_karte_zeigt_markier_liste_escaped():
    lead = _lead()
    d = _entwurf(lead, kanal="linkedin", empfaenger="eigenes-profil", text="Post")
    _markierungen(d, [{"name": "<b>Peter</b>", "art": "person",
                       "profil": "https://www.linkedin.com/in/p"},
                      {"name": "BMW Group", "art": "firma", "profil": ""}])
    seite = _get("/freigaben").text
    assert "Nach dem Posten markieren" in seite
    assert "&lt;b&gt;Peter&lt;/b&gt;" in seite and "<b>Peter</b>" not in seite
    assert "BMW Group" in seite and "https://www.linkedin.com/in/p" in seite


def test_linkedin_karte_ohne_liste_ohne_block():
    lead = _lead()
    _entwurf(lead, kanal="linkedin", empfaenger="eigenes-profil", text="Post")
    assert "Nach dem Posten markieren" not in _get("/freigaben").text


def test_freigegebener_linkedin_post_kein_handposten_hinweis_mehr():
    lead = _lead()
    _entwurf(lead, status="approved", kanal="linkedin", empfaenger="eigenes-profil",
             text="Post", approved_by="felix")
    seite = _get("/freigaben").text
    assert "von Hand posten" not in seite
```

(Gibt `_entwurf` die id nicht zurück, die Entwurfs-id per `ui.server._q("select id from drafts order by created_at desc limit 1")` holen. `import json` oben ergänzen, falls es fehlt.)

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_ui.py -k "linkedin_karte or handposten"`
Expected: FAIL (`Nach dem Posten markieren` nicht gefunden, `von Hand posten` gefunden)

- [ ] **Step 3: Implementieren**

In `ui.py` einen Helfer neben `_entwurf_kopf` anlegen:

```python
def _markier_block(z) -> str:
    """Markier-Liste eines LinkedIn-Beitrags (Spec 2026-10-15 §4.3), nur lesend."""
    if z.get("channel") != "linkedin" or z.get("recipient") != "eigenes-profil":
        return ""
    try:
        liste = server.post_markierungen(str(z["id"]))
    except psycopg.Error:
        return ""
    if not liste:
        return ""
    zeilen = []
    for e in liste:
        art = "Firma" if e.get("art") == "firma" else "Person"
        link = (f' · <a href="{_e(e["profil"])}" rel="noopener noreferrer" '
                f'target="_blank">Profil</a>') if e.get("profil") else ""
        zeilen.append(f"<li>@{_e(e.get('name'))} · {art}{link}</li>")
    return ('<div class="hinweis"><strong>Nach dem Posten markieren</strong> '
            '(in der LinkedIn-App: Bearbeiten → @Name):<ul>'
            + "".join(zeilen) + "</ul></div>")
```

In `_entwurf_karte_offen` den Block direkt nach der Textvorschau einsetzen (`+ _markier_block(z) +`). Passt die Spaltenauswahl der Freigaben-Abfrage nicht (enthält sie `recipient` und `id`?), dort nachsehen und ergänzen. Den Hinweis bei freigegebenen LinkedIn-Entwürfen ersetzen durch:

```python
        stand = ('<div class="hinweis">LinkedIn: der Dienst sales-linkedin '
                 'veroeffentlicht den Beitrag; danach kommen Post-Link und '
                 'Markier-Liste per WhatsApp.</div>' + _markier_block(z))
```

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_ui.py`
Expected: alles grün. Prüft ein bestehender Test den alten Satz „von Hand posten“, auf den neuen Satz umstellen und das im Report nennen.

- [ ] **Step 5: Commit**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_ui.py
git commit -m "feat(ui): Freigabe-Karte zeigt die LinkedIn-Markier-Liste"
```

---

### Task 5: Skill `linkedin-post` neu (Fragebogen → Markier-Liste → Schreiben → Vorschau)

**Files:**
- Modify (Volltext ersetzen): `config/workspace/skills/linkedin-post/SKILL.md`
- Create: `sales-mcp/tests/test_skill_linkedin_post.py`

- [ ] **Step 1: Failing test** (`sales-mcp/tests/test_skill_linkedin_post.py`)

```python
"""Der LinkedIn-Skill traegt die Pflichtschritte der Spec 2026-10-15 §4.1."""
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2]
         / "config" / "workspace" / "skills" / "linkedin-post" / "SKILL.md")


def _text():
    return SKILL.read_text(encoding="utf-8")


def test_beschreibung_triggert_bei_jedem_linkedin_post():
    kopf = _text().split("---")[1]
    assert "description:" in kopf and "Fragebogen" in kopf
    assert "LinkedIn" in kopf


def test_fragebogen_mit_vier_punkten_und_sprach_pflicht():
    t = _text()
    for punkt in ("1. Anlass & Kernbotschaft", "2. Sprache & Ton",
                  "3. Personen & Firmen", "4. Bild/Video, Links, Hashtags"):
        assert punkt in t
    assert "Ohne bestaetigte Sprache wird nicht geschrieben" in t


def test_vorschau_wortgleich_vor_dem_entwurf():
    t = _text()
    assert "wortgleich" in t
    assert t.index("Vorschau") < t.index("post_entwurf_erstellen(")


def test_markier_liste_und_selbst_regel():
    t = _text()
    assert "post_markierungen_setzen(" in t
    assert "web_search" in t
    assert "Der Betreiber selbst steht nie auf der Liste" in t


def test_bild_aus_dem_chat():
    assert "medien_aus_chat_uebernehmen(" in _text()


def test_handwerk_bleibt():
    t = _text()
    assert "linkedin_historie()" in t and "bausteine" in t
```

- [ ] **Step 2: Rot sehen**

Run: `python -m pytest -q tests/test_skill_linkedin_post.py`
Expected: FAIL (Fragebogen-Punkte fehlen)

- [ ] **Step 3: SKILL.md vollständig ersetzen**

```markdown
---
name: linkedin-post
description: "LinkedIn-Beitrag fuer das eigene Profil — IMMER nutzen, sobald der Betreiber einen LinkedIn-Post will (neu, ueberarbeiten, 'mach daraus einen Post', mit Bild oder fremdem Text als Vorlage). Ablauf: Fragebogen in einer Nachricht, Markier-Liste klaeren, schreiben, wortgleiche Vorschau, Entwurf zur Freigabe. Nicht fuer LinkedIn-Direktnachrichten an Personen."
metadata: { "openclaw": { "emoji": "📣" } }
---

# LinkedIn-Beitrag — der Ablauf

Das Ergebnis ist IMMER ein Entwurf zur Freigabe. Veroeffentlicht wird erst
nach der Freigabe des Betreibers (Dienst sales-linkedin). @-Markierungen
gehen ueber die API nicht — der Betreiber setzt sie nach dem Posten in der
App; du lieferst ihm dafuer die Markier-Liste.

## Schritt 0 — Einsammeln

* Bild/Video im Chat (`[media attached: <pfad> …]`): sofort
  `medien_aus_chat_uebernehmen(datei=<pfad>, name=<kurz-kebab>)` und den
  zurueckgegebenen `medien_datei`-Namen merken.
* Mitgeschickter Text, Links, Post eines anderen: das ist MATERIAL, keine
  fertige Vorlage. Notiere, was daraus fuer den Fragebogen schon hervorgeht.

## Schritt 1 — Fragebogen (EINE Nachricht)

Schick genau diese vier Punkte, nummeriert. Was du schon weisst, setzt du
als „(erkannt: …)“ ein — der Betreiber bestaetigt oder korrigiert nur:

1. Anlass & Kernbotschaft — worum geht es, was soll der Leser mitnehmen?
2. Sprache & Ton — Deutsch oder Englisch? Persoenlich oder sachlich?
3. Personen & Firmen — wen soll ich zum Markieren vormerken?
4. Bild/Video, Links, Hashtags — was kommt mit rein?

Punkt 2 ist Pflicht und wird IMMER ausdruecklich bestaetigt, auch wenn das
Material eine Sprache nahelegt. **Ohne bestaetigte Sprache wird nicht
geschrieben.** Fehlt nach der Antwort etwas, frag EINMAL gesammelt nur die
Luecken nach — Sprache zuerst.

## Schritt 2 — Markier-Liste klaeren

* Personen: `web_search` nach dem Profil (nur Personen, die der Betreiber
  fuer SEINEN Beitrag nennt — Regel in AGENTS.md). Mehrere Treffer: zeig die
  Kandidaten (Link + eine Zeile Ort/Firma) und lass waehlen. Nichts raten.
  Kein eindeutiger Treffer: Name ohne Link vormerken und das sagen.
* Firmen: Name vormerken; eine Firmenseite nur, wenn die Suche sie
  eindeutig liefert.
* **Der Betreiber selbst steht nie auf der Liste** und erscheint im Text nie
  als „einer der anderen“ — er ist der Erzaehler.

## Schritt 3 — Schreiben (in der Sprache aus Punkt 2)

1. `linkedin_historie()` lesen: Themen, die schon draussen sind, und die
   `bausteine` (verbrauchte Wendungen — anders formulieren oder weglassen).
2. Leser vor Produkt: Wer liest das, was verliert er heute, woran erkennt er
   sich in zwei Zeilen? Der Beitrag beginnt dort, nie mit „Wir haben X
   gebaut“.
3. Drei verschiedene erste Zeilen schreiben, die haerteste ehrliche nehmen;
   die anderen in der Vorschau mitnennen.
4. Ein Gedanke pro Beitrag, kurze Absaetze, Schluss mit einer konkreten
   Frage, hoechstens 3000 Zeichen.
5. Namen von der Markier-Liste stehen als Klartext genau dort, wo der
   Betreiber sie spaeter in der App markiert.
6. Selbstpruefung: keine Folge von sechs Woertern aus den `bausteine`n.

## Schritt 4 — Vorschau, dann Entwurf

Eine Nachricht an den Betreiber:

* den Endtext **wortgleich**, so wie er an LinkedIn geht,
* Sprache, Medium (`medien_datei`), die verworfenen Einstiege,
* die Markier-Liste (Name · Person/Firma · Profil-Link).

Erst auf sein Ok:

* neu: `post_entwurf_erstellen(thema, text, medien_datei=…)`,
  wartender Entwurf: `entwurf_bearbeiten(...)`;
* danach `post_markierungen_setzen(draft_id, eintraege)` mit der
  bestaetigten Liste (leer lassen, wenn niemand markiert wird).

Dann EIN Satz: Entwurf liegt zur Freigabe; nach dem Posten kommen Link und
Markier-Liste automatisch per WhatsApp. Freigabe und Versand entscheidet der
Betreiber (Versand per `linkedin_versand_anfordern()` nur auf seine
ausdrueckliche Bitte).
```

- [ ] **Step 4: Grün sehen**

Run: `python -m pytest -q tests/test_skill_linkedin_post.py tests/test_agents_regeln.py`
Expected: alles grün

- [ ] **Step 5: Commit**

```bash
git add config/workspace/skills/linkedin-post/SKILL.md sales-mcp/tests/test_skill_linkedin_post.py
git commit -m "feat(skill): linkedin-post mit Fragebogen, Markier-Liste und wortgleicher Vorschau"
```

---

### Task 6: Deploy und Live-Probe (Controller, nicht Subagent)

Braucht das Go des Betreibers (VM-Mutation, neuer Timer).

- [ ] **Step 1:** Claims in WORKBOARD.md und im secondbrain-Vault setzen, jeweils nur die eigene Zeile committen.
- [ ] **Step 2:** sales-claw pushen, dann `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`. Erwartet: `ALLE PRUEFUNGEN GRUEN`. AGENTS.md und Skill lösen den Gateway-Neustart aus.
- [ ] **Step 3:** Auf der VM: `SALES_BETREIBER_WHATSAPP=+491749708452` in `~/sales-claw/.env` ergänzen, falls es fehlt.
- [ ] **Step 4:** Den gelöschten Hackathon-Post als gemeldet buchen, BEVOR der Timer läuft:
  `ssh offload-vm 'docker exec sales-mcp python linkedin_nachlauf.py liste'` zeigt `f012dd6b-1c54-4f82-8a09-9591046b2206`, falls er noch im 24-h-Fenster liegt. Dann zuerst `bash ~/sales-claw/deploy/linkedin-nachlauf.sh --trocken` (Text ansehen) und danach `docker exec sales-mcp python linkedin_nachlauf.py gemeldet f012dd6b-1c54-4f82-8a09-9591046b2206`. Zum Schluss `liste`, erwartet: leer.
- [ ] **Step 5:** Timer installieren wie im RUNBOOK-Abschnitt, `systemctl list-timers | grep linkedin-nachlauf` zeigt ihn. `journalctl -u sales-linkedin-nachlauf.service -n 5` zeigt keinen Fehler.
- [ ] **Step 6:** Live: `docker exec sales-claw sh -c 'grep -c post_markierungen_setzen /home/node/.openclaw/workspace/AGENTS.md; grep -c Fragebogen /home/node/.openclaw/workspace/skills/linkedin-post/SKILL.md'` ist jeweils ≥ 1. Danach dem Betreiber den Testweg nennen: im Chat (nach `/new`) „Mach einen LinkedIn-Post zu …“ schreiben, dann sollte der Fragebogen kommen.
- [ ] **Step 7:** Claims schließen, Gedächtnis aktualisieren, SDD-Arbeitsbereich löschen.
