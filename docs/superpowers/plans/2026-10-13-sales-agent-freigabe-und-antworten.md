# Sales-Agent Block A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Der Sales-Agent beantwortet Postfach-Mails als Entwurf im selben Mailverlauf.
- Betreiber-Aufträge scheitern nicht mehr an der Stufe „manuell“ oder an einer fehlenden Einwilligung.
- Ein „ja“ im Chat gibt frei und meldet den Versand.
- Fehler werden immer genannt.
- Ignorierte Absender, die Kontakt werden, sind wieder sichtbar.
- Die Bedarfsanalyse ist abgeschaltet.

**Architecture:**
- Alles liegt im MCP-Server `sales-mcp/server.py` (Werkzeuge im Tupel `WERKZEUGE`), dazu Postfach (`postfach.py`), Versand (`mail_dispatch.py`), Schema (`db/provision.sql`), Oberfläche (`ui.py`) und Prompt (`config/workspace/AGENTS.md`).
- Neue Werkzeuge: `mail_beantworten`, `versand_abwarten`.
- Bestehende Werkzeuge bekommen den Parameter `auftrag_betreiber`.
- Der Cron-Befund wird auf der VM gemessen und dann behoben.

**Tech Stack:** Python 3.12, psycopg 3, FastMCP, Starlette (sales-ui), PostgreSQL (Supabase auf der VM, Schema je Laden), openclaw (Agent im Container `sales-claw`).

**Spec:** `docs/superpowers/specs/2026-10-13-sales-agent-freigabe-und-antworten-design.md`

## Global Constraints

**Repo und Git**
- Repo SC = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`.
  - Vor jedem Commit `git -C <SC> rev-parse --show-toplevel` und `git -C <SC> branch --show-current` prüfen.
- Git nur über PowerShell. Conventional Commits auf Deutsch, letzter Absatz `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Nur eigene Dateien einzeln stagen. Nie `.superpowers/`, nie stash, force oder `--no-verify`.

**Tests**
- Aus `<SC>/sales-mcp`, gegen die Test-Postgres :55432 (der Controller startet sie):
  `$env:SALES_DB_URL='postgresql://postgres@127.0.0.1:55432/postgres'; $env:SALES_DB_SCHEMA='sales_test'; & E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q`
- Die DB-Fixtures stehen je Testdatei: `os.environ["SALES_DB_SCHEMA"]="sales_test"; import server`, `schema_wache` und `saubere_tabellen` (truncate activities, drafts, personas, leads). Neue Testdateien kopieren dieses Muster aus `tests/test_uwg.py:26-41`.

**Verbote:** kein Deploy, kein Zugriff auf die echte DB, kein Neustart. Das macht der Controller in Task 9 nach Freigabe.

**Wortlaute (exakt)**
- „Mail nicht mehr im Postfach“
- „Kontakt steht auf manuell – Entwurf liegt zur Freigabe“
- „stand auf Ignorieren – aufgehoben, neue Nachrichten sind wieder sichtbar.“
- „bleibt liegen, bis das Postfach eingetragen ist“
- Einwilligungsart `betreiber_auftrag`, Quelle `Betreiber-Auftrag vom <TT.MM.JJJJ>`.
- Schalter `SALES_BEDARFSANALYSE`, Vorgabe `aus`. Nur `an` schaltet ein.
- Freigabewörter im Prompt: „ja“, „senden“, „raus“, „freigeben“, „ok“.

## Rulings (Controller, gegen die Spec abgewogen)

- **R1: WhatsApp-Freigabe bleibt.** `entwurf_erstellen` verlangt für WhatsApp weiter die Kontakt-Freigabe (`_whatsapp_freigegeben`). `auftrag_betreiber` setzt sie nicht. Die Spec fordert das nicht, und eine Freigabe ist eine eigene Betreiber-Handlung. Der Fehler wird nach 2.3 genannt.
- **R2: Bausteine der Ignorieren-Aufhebung.** Sie läuft über das bestehende Ereignis `absender_beachtet` (`_absender_ereignis(ABSENDER_BEACHTET, kennung, lead_id)`). `absender_ist_ignoriert` wertet die jüngste Aussage aus und kennt die `@lid`-Brücke schon. Die einmalige Reparatur von Arjun und Muttu nutzt das bestehende Werkzeug `eingang_einordnen(absender, "beachten")` (Task 9).
- **R3: Wo die Mail gebucht wird.** `mail_beantworten` bucht die eingegangene Mail als Aktivität `kundenantwort` mit `kanal: email`. Erst dadurch gilt `_hat_selbst_geschrieben`.
- **R4: Wie Spec 2.1 umgesetzt wird.** Die Spec-Zeile „Freigabe im Chat“ wird nur als Prompt-Regel umgesetzt. `entwurf_freigeben` bleibt unverändert, Code muss sich nicht ändern.

## Review Focus

1. **Der Absender einer Postfach-Mail ist schon Kontakt,** aber mit anderer Groß- und Kleinschreibung oder mit Anzeigename („Leo W <leo.w@…>“). Erwartet: derselbe Kontakt, kein Duplikat. Test in Task 3.
2. **„Re: Re: Thema“ bzw. „AW: Thema“.** Erwartet: kein drittes „Re:“, der Betreff bleibt „AW: Thema“ bzw. „Re: Thema“. Test in Task 3.
3. **Die Mail hat keine Message-ID** (selten, aber möglich). Erwartet: Der Entwurf entsteht trotzdem, nur ohne Verlaufs-Header. Test in Task 3 und Task 1.
4. **Ein Kontakt, dessen Nummer nie ignoriert war, wird freigegeben.** Erwartet: kein Ereignis `absender_beachtet`, kein Aufhebungssatz. Test in Task 4.
5. **`versand_abwarten` auf einen Entwurf, der noch `pending` ist** (Freigabe vergessen). Erwartet: sofort „nicht freigegeben“ statt 60 Sekunden Warten. Test in Task 5.

---

### Task 1: Schema, Message-ID und Mailverlauf

**Files:**
- Modify: `db/provision.sql` (in der Schema-Schleife, beim Muster `add column if not exists cc`, Z.~211, und beim CHECK-Muster Z.217-221)
- Modify: `sales-mcp/server.py` (`EINWILLIGUNG_ARTEN`, Z.6416)
- Modify: `sales-mcp/postfach.py` (`lesen`, Z.433, und `liste`, Z.388)
- Modify: `sales-mcp/mail_dispatch.py` (`claim`, Z.233; `nachricht_bauen`, Z.282; `nachricht_mit_einladung`, Z.411; `verarbeite_draft`, Z.561)
- Test: `sales-mcp/tests/test_mail_dispatch.py`, `sales-mcp/tests/test_postfach.py`, `sales-mcp/tests/test_uwg.py`

**Interfaces:**
- Produces:
  - Spalte `drafts.antwort_auf text` (Message-ID, ohne spitze Klammern gespeichert).
  - `consent_status` erlaubt zusätzlich `'betreiber_auftrag'`.
  - `server.EINWILLIGUNG_ARTEN = ("opt_in", "existing_customer", "betreiber_auftrag")`.
  - `postfach.lesen(uid)` und `postfach.liste(n)` liefern zusätzlich `"message_id": str` (ohne `<>`, leer, wenn sie fehlt).
  - `mail_dispatch.nachricht_bauen(..., antwort_auf: str = "")` setzt bei nicht leerem Wert `In-Reply-To: <id>` und `References: <id>`. Gleiches gilt für `nachricht_mit_einladung(..., antwort_auf="")`.

- [ ] **Step 1: Failing Tests.**
  - `tests/test_mail_dispatch.py`:
```python
def test_antwort_header_gesetzt():
    n = mail_dispatch.nachricht_bauen("a@example.org", "Re: Frage", "Hallo", antwort_auf="abc123@mail.example.org")
    assert n["In-Reply-To"] == "<abc123@mail.example.org>"
    assert n["References"] == "<abc123@mail.example.org>"


def test_ohne_antwort_keine_header():
    n = mail_dispatch.nachricht_bauen("a@example.org", "Hallo", "Text")
    assert n["In-Reply-To"] is None and n["References"] is None
```
    Dazu ein DB-Test im Stil der bestehenden `verarbeite_draft`-Tests. Ein Draft mit `antwort_auf='abc@x'` wird versendet. Die gefakte `senden`-Funktion bekommt eine Nachricht mit `In-Reply-To: <abc@x>`.
  - `tests/test_postfach.py`: Im bestehenden Fake-IMAP-Muster der Datei hat eine Nachricht den Header `Message-ID: <m1@ex.org>`. `lesen()` liefert `message_id == "m1@ex.org"`. Ohne Header ist das Feld `""`.
  - `tests/test_uwg.py`:
```python
def test_betreiber_auftrag_ist_grundlage():
    lead = _lead()
    json.loads(server.einwilligung_erfassen(lead, "betreiber_auftrag", "Betreiber-Auftrag vom 13.10.2026"))
    antwort = json.loads(server.entwurf_erstellen(lead, "email", "Hallo Udo"))
    assert "fehler" not in antwort, antwort
```
- [ ] **Step 2: Laufen lassen.** Erwartet: FAIL.
- [ ] **Step 3: Implementieren.**
  - **`provision.sql`:** in der Schleife nach der `cc`-Zeile:
```sql
    execute format('alter table %I.drafts add column if not exists antwort_auf text', s);
    execute format('alter table %I.leads drop constraint if exists leads_consent_status_check', s);
    execute format($chk$alter table %I.leads add constraint leads_consent_status_check
      check (consent_status in ('opt_in','existing_customer','inbound','unknown','betreiber_auftrag'))$chk$, s);
```
    Den Namen des bestehenden Constraints vorher in der Test-DB prüfen: `select conname from pg_constraint where conrelid='sales_test.leads'::regclass and contype='c'`. Weicht er ab, wird genau dieser Name gedroppt.
  - **`server.py`:** `EINWILLIGUNG_ARTEN = ("opt_in", "existing_customer", "betreiber_auftrag")`.
  - **`postfach.py`:** In `lesen` und `liste` kommt `"message_id": _kopf(nachricht, "Message-ID").strip().strip("<>")` hinzu. Bei `liste` steht dafür die jeweilige Nachrichtenvariable der Schleife.
  - **`mail_dispatch.py`:**
    - `nachricht_bauen(adresse, betreff, rumpf, cc=None, absender=None, antwort_auf: str = "")` setzt nach `Subject`:
```python
    kennung = str(antwort_auf or "").strip().strip("<>")
    if kennung:
        nachricht["In-Reply-To"] = f"<{kennung}>"
        nachricht["References"] = f"<{kennung}>"
```
    - Dasselbe gilt für `nachricht_mit_einladung`.
    - `claim()` liefert zusätzlich `antwort_auf` (in der `returning`-Liste).
    - `verarbeite_draft` reicht `z.get("antwort_auf") or ""` an beide Bauer weiter.
- [ ] **Step 4: Grün** für die drei Testdateien vollständig, dazu `tests/test_links_und_cc.py`. Die geänderte `provision.sql` wird erst gegen die Test-DB angewendet (wie die Datei sich selbst anwendet, steht in ihrem Kopf), dann laufen die Tests.
- [ ] **Step 5: Commit**
```
git add db/provision.sql sales-mcp/server.py sales-mcp/postfach.py sales-mcp/mail_dispatch.py sales-mcp/tests/test_mail_dispatch.py sales-mcp/tests/test_postfach.py sales-mcp/tests/test_uwg.py
git commit -m "feat(sales): Mailverlauf (antwort_auf, In-Reply-To), Message-ID im Postfach, Einwilligung betreiber_auftrag" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `auftrag_betreiber` — manuell und Einwilligung

**Files:**
- Modify: `sales-mcp/server.py` (`entwurf_erstellen`, Z.2200; `antwort_entwerfen`, Z.6048)
- Test: `sales-mcp/tests/test_autonomie.py`, `sales-mcp/tests/test_uwg.py`

**Interfaces:**
- Consumes: `EINWILLIGUNG_ARTEN` mit `betreiber_auftrag` (Task 1).
- Produces:
  - `entwurf_erstellen(lead_id, kanal, text, betreff="", medien_datei="", auftrag_betreiber: bool = False) -> str`
  - `antwort_entwerfen(lead_id, text, medien_datei="", auftrag_betreiber: bool = False) -> str`
  - `server._grundlage_aus_auftrag(lead_id: str) -> bool`: bucht die Einwilligung, wenn keine vorliegt; True heißt, es wurde gebucht.
  - Konstante `MANUELL_AUFTRAG_HINWEIS = "Kontakt steht auf manuell – Entwurf liegt zur Freigabe"`.

- [ ] **Step 1: Failing Tests.**
  - `test_uwg.py`:
```python
def test_auftrag_bucht_grundlage_und_entwurf_entsteht():
    lead = _lead()
    antwort = json.loads(server.entwurf_erstellen(lead, "email", "Hallo Udo", auftrag_betreiber=True))
    assert "fehler" not in antwort, antwort
    z = server._q("select consent_status from leads where id = %s", (lead,))[0]
    assert z["consent_status"] == "betreiber_auftrag"
    a = server._q("select payload from activities where lead_id = %s and type = 'werbe_einwilligung'", (lead,))
    assert a and a[0]["payload"]["quelle"].startswith("Betreiber-Auftrag vom ")


def test_ohne_auftrag_bleibt_die_sperre():
    lead = _lead()
    assert "fehler" in json.loads(server.entwurf_erstellen(lead, "email", "Hallo Udo"))


def test_vorhandene_grundlage_wird_nicht_ueberschrieben():
    lead = _lead()
    server.einwilligung_erfassen(lead, "opt_in", "Formular")
    server.entwurf_erstellen(lead, "email", "Hallo", auftrag_betreiber=True)
    assert server._q("select consent_status from leads where id = %s", (lead,))[0]["consent_status"] == "opt_in"
```
  - `test_autonomie.py`, im Stil der bestehenden Tests: der Kontakt steht auf `manuell`, WhatsApp ist freigegeben.
```python
def test_manuell_mit_auftrag_ergibt_pending(...):
    a = json.loads(server.antwort_entwerfen(lead, "Hallo!", auftrag_betreiber=True))
    assert "fehler" not in a and a["status"] == "pending"
    assert a["hinweis"] == server.MANUELL_AUFTRAG_HINWEIS


def test_manuell_ohne_auftrag_weiter_nichts(...):
    a = json.loads(server.antwort_entwerfen(lead, "Hallo!"))
    assert "fehler" in a


def test_auftrag_bei_auto_geht_nicht_automatisch_raus(...):
    # Stufe auto + Zustimmung: mit auftrag_betreiber entsteht trotzdem nur 'pending' (Spec 1.2: nie ohne Freigabe)
    a = json.loads(server.antwort_entwerfen(lead, "Hallo!", auftrag_betreiber=True))
    assert a["status"] == "pending"
```
    Für `ignorieren` bleibt die Ablehnung, auch mit Auftrag.
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren.**
```python
MANUELL_AUFTRAG_HINWEIS = "Kontakt steht auf manuell – Entwurf liegt zur Freigabe"


def _grundlage_aus_auftrag(lead_id: str) -> bool:
    """Spec 1.4: der Betreiber verlangt den Kontakt — die Grundlage verantwortet er. Nur wenn keine vorliegt."""
    z = _q("select consent_status from leads where id = %s", (lead_id,))
    if not z or z[0]["consent_status"] in EINWILLIGUNG_ARTEN or _hat_selbst_geschrieben(lead_id):
        return False
    einwilligung_erfassen(lead_id, "betreiber_auftrag",
                          f"Betreiber-Auftrag vom {datetime.now(ZoneInfo('Europe/Berlin')):%d.%m.%Y}")
    return True
```
  `datetime` und `ZoneInfo` importieren, falls sie in `server.py` fehlen. `einwilligung_erfassen` ist mit `@_gesichert` dekoriert. Sein JSON-Ergebnis auf `fehler` prüfen und dann `False` zurückgeben.
  - **`entwurf_erstellen`:** neuer letzter Parameter `auftrag_betreiber: bool = False`. Direkt vor dem UWG-Tor (Z.~2254):
```python
    if auftrag_betreiber and kanal in ("whatsapp", "email", "telegram"):
        _grundlage_aus_auftrag(lead_id)
```
  - **`antwort_entwerfen`:** neuer Parameter `auftrag_betreiber: bool = False`. Die Stufen-Ablehnung (Z.6079-6085) wird zu:
```python
    stufe = _autonomie(leads[0]["enrichment"])
    if auftrag_betreiber and stufe != "ignorieren":
        roh = entwurf_erstellen(lead_id, "whatsapp", text, medien_datei=medien_datei, auftrag_betreiber=True)
        antwort = json.loads(roh)
        if "fehler" in antwort:
            return roh
        return _json({**antwort, "autonomie": stufe,
                      "hinweis": MANUELL_AUFTRAG_HINWEIS if stufe == "manuell"
                      else "Entwurf liegt zur Freigabe"})
    if stufe not in ("halbauto", "auto"):
        ...unveraendert...
```
  - In den Docstrings beider Werkzeuge einen Satz zu `auftrag_betreiber` ergänzen: „nur im Betreiber-Chat, wenn der Betreiber den Kontakt ausdrücklich verlangt; nie im Kundenchat“.
- [ ] **Step 4: Grün:** `tests/test_uwg.py tests/test_autonomie.py tests/test_werkzeuge.py tests/test_zustimmung.py` vollständig.
- [ ] **Step 5: Commit**
```
git add sales-mcp/server.py sales-mcp/tests/test_uwg.py sales-mcp/tests/test_autonomie.py
git commit -m "feat(sales): Betreiber-Auftrag schlaegt manuell und bucht die Einwilligung" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `mail_beantworten`

**Files:**
- Modify: `sales-mcp/server.py` (neue Funktion bei `postfach_mail_lesen`, Z.~2881; Eintrag in `WERKZEUGE`, Z.7719ff)
- Create: `sales-mcp/tests/test_mail_beantworten.py`

**Interfaces:**
- Consumes: `postfach.lesen(uid)` mit `message_id` (Task 1); `entwurf_erstellen(..., auftrag_betreiber=True)` (Task 2); Spalte `drafts.antwort_auf`.
- Produces: `mail_beantworten(uid: str, text: str) -> str`.
  - Erfolg: `{"draft_id", "status": "pending", "lead_id", "an", "betreff", "neuer_kontakt": bool}`.
  - Fehler: `{"fehler": ...}`.
  - `noreply`-Absender: `{"frage": "..."}`.

- [ ] **Step 1: Failing Tests.** Neue Datei mit dem DB-Fixture-Muster. `postfach` wird per `monkeypatch.setattr(server.postfach, "lesen", ...)` und `konfiguriert` → True gefakt.
```python
MAIL = {"uid": "7", "von": "Leo W <Leo.W@Example.com>", "an": "ich@vibemind.space", "betreff": "Kurze Frage",
        "datum": "Tue, 13 Oct 2026 07:00:00 +0200", "text": "Hallo, ...", "message_id": "m-7@example.com"}

def _postfach(monkeypatch, mail):
    monkeypatch.setattr(server.postfach, "konfiguriert", lambda: True)
    monkeypatch.setattr(server.postfach, "lesen", lambda uid: mail if mail and uid == mail["uid"] else None)

def test_neuer_kontakt_entwurf_im_verlauf(monkeypatch):
    _postfach(monkeypatch, MAIL)
    a = json.loads(server.mail_beantworten("7", "Hallo Leo, danke!"))
    assert a["status"] == "pending" and a["neuer_kontakt"] is True and a["betreff"] == "Re: Kurze Frage"
    d = server._q("select channel, recipient, subject, antwort_auf, status from drafts where id = %s", (a["draft_id"],))[0]
    assert (d["channel"], d["recipient"], d["antwort_auf"], d["status"]) == ("email", "leo.w@example.com", "m-7@example.com", "pending")
    l = server._q("select source, consent_status from leads where id = %s", (a["lead_id"],))[0]
    assert l["source"] == "email"
    assert server._hat_selbst_geschrieben(a["lead_id"])

def test_vorhandener_kontakt_kein_duplikat(monkeypatch):           # Review Focus 1
    lead = str(server._q("insert into leads (name, email, source) values ('Leo', 'leo.w@example.com', 'email') returning id")[0]["id"])
    _postfach(monkeypatch, MAIL)
    a = json.loads(server.mail_beantworten("7", "Hallo"))
    assert a["lead_id"] == lead and a["neuer_kontakt"] is False
    assert server._q("select count(*) n from leads")[0]["n"] == 1

def test_eingang_einmal_gebucht(monkeypatch):
    _postfach(monkeypatch, MAIL)
    a = json.loads(server.mail_beantworten("7", "Eins"))
    server._q("update drafts set status = 'rejected' where id = %s returning id", (a["draft_id"],))
    json.loads(server.mail_beantworten("7", "Zwei"))
    n = server._q("select count(*) n from activities where type = 'kundenantwort' and payload->>'message_id' = 'm-7@example.com'")[0]["n"]
    assert n == 1

@pytest.mark.parametrize("betreff,erwartet", [("Re: Thema", "Re: Thema"), ("AW: Thema", "AW: Thema"),
                                              ("RE: Re: Thema", "RE: Re: Thema"), ("Thema", "Re: Thema"), ("", "Re: (ohne Betreff)")])
def test_betreff(monkeypatch, betreff, erwartet):                  # Review Focus 2
    _postfach(monkeypatch, {**MAIL, "betreff": betreff})
    assert json.loads(server.mail_beantworten("7", "x"))["betreff"] == erwartet

def test_ohne_message_id(monkeypatch):                              # Review Focus 3
    _postfach(monkeypatch, {**MAIL, "message_id": ""})
    a = json.loads(server.mail_beantworten("7", "x"))
    assert server._q("select antwort_auf from drafts where id = %s", (a["draft_id"],))[0]["antwort_auf"] is None

def test_mail_weg(monkeypatch):
    _postfach(monkeypatch, None)
    assert json.loads(server.mail_beantworten("9", "x"))["fehler"].startswith("Mail nicht mehr im Postfach")

@pytest.mark.parametrize("von", ["noreply@shop.de", "No-Reply <no-reply@x.org>", "MAILER-DAEMON@mx.de"])
def test_noreply_rueckfrage(monkeypatch, von):
    _postfach(monkeypatch, {**MAIL, "von": von})
    a = json.loads(server.mail_beantworten("7", "x"))
    assert "frage" in a and server._q("select count(*) n from drafts")[0]["n"] == 0
```
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren** in `server.py`:
```python
_NOREPLY = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster)@", re.I)
_RE = re.compile(r"^\s*(re|aw|wg|fwd?)\s*:", re.I)


def _antwort_betreff(roh: str) -> str:
    b = (roh or "").strip()
    if not b:
        return "Re: (ohne Betreff)"
    return b if _RE.match(b) else f"Re: {b}"


@_gesichert
def mail_beantworten(uid: str, text: str) -> str:
    """Auf eine Mail aus dem Betreiber-Postfach antworten (Spec 2026-10-13 §1.1). Nur Betreiber-Chat.
    Legt einen E-MAIL-Entwurf 'pending' im selben Mailverlauf an — versendet nichts. Kontakt wird ueber die
    Absenderadresse gefunden oder angelegt; die eingegangene Mail wird als Kundennachricht gebucht."""
    if not postfach.konfiguriert():
        return _json({"fehler": "Kein Betreiber-Postfach eingerichtet."})
    try:
        mail = postfach.lesen(str(uid))
    except Exception as e:  # noqa: BLE001 - IMAP-Stoerung wird Meldung
        return _json({"fehler": f"Postfach nicht erreichbar ({type(e).__name__})."})
    if not mail:
        return _json({"fehler": f"Mail nicht mehr im Postfach (uid {uid})."})
    name, adresse = email.utils.parseaddr(mail.get("von") or "")
    adresse = adresse.strip().lower()
    if not adresse or _NOREPLY.match(adresse):
        return _json({"frage": f"Die Mail kommt von „{mail.get('von')}“ — eine automatische Adresse. "
                               "Wohin soll die Antwort gehen?"})
    z = _q("select id from leads where lower(email) = %s order by created_at limit 1", (adresse,))
    neu = not z
    lead_id = str(z[0]["id"]) if z else str(_q(
        "insert into leads (name, email, source) values (%s, %s, 'email') returning id",
        ((name or adresse.split("@")[0]).strip()[:120], adresse))[0]["id"])
    mid = (mail.get("message_id") or "").strip()
    if not mid or not _q("select 1 from activities where lead_id = %s and type = 'kundenantwort' "
                         "and payload->>'message_id' = %s limit 1", (lead_id, mid)):
        _q("insert into activities (lead_id, type, payload, actor) values (%s, 'kundenantwort', %s, 'human') "
           "returning id", (lead_id, _json({"kanal": "email", "message_id": mid, "betreff": mail.get("betreff") or "",
                                            "text": (mail.get("text") or "")[:4000], "richtung": "eingehend"})))
    betreff = _antwort_betreff(mail.get("betreff") or "")
    roh = entwurf_erstellen(lead_id, "email", text, betreff=betreff, auftrag_betreiber=True)
    a = json.loads(roh)
    if "fehler" in a:
        return roh
    if mid:
        _q("update drafts set antwort_auf = %s where id = %s returning id", (mid, a["draft_id"]))
    return _json({"draft_id": a["draft_id"], "status": a["status"], "lead_id": lead_id, "an": adresse,
                  "betreff": betreff, "neuer_kontakt": neu})
```
  - `import email.utils` und `re` prüfen bzw. ergänzen.
  - `mail_beantworten` kommt ins Tupel `WERKZEUGE` neben `postfach_mail_lesen`.
  - Zeilen-Schreibweise und Spaltennamen der `kundenantwort`-Payload an bestehenden `kundenantwort`-Buchungen angleichen (`grep -n "'kundenantwort'" sales-mcp/*.py`). Nötig sind mindestens `kanal`, `message_id`, `text` und `richtung`.
- [ ] **Step 4: Grün:** `tests/test_mail_beantworten.py tests/test_postfach.py tests/test_uwg.py tests/test_werkzeuge.py`.
- [ ] **Step 5: Commit**
```
git add sales-mcp/server.py sales-mcp/tests/test_mail_beantworten.py
git commit -m "feat(sales): mail_beantworten - Antwort auf Postfach-Mail als Entwurf im Mailverlauf" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Ignorieren aufheben bei Freigabe

**Files:**
- Modify: `sales-mcp/server.py` (neuer Helfer bei `absender_ist_ignoriert`, Z.4439; `_whatsapp_freigabe_setzen`, Z.527; `entwurf_freigeben`, Z.5250)
- Modify: `sales-mcp/ui.py` (`aktion_freigeben`, Z.2699; `aktion_kontakt_freigeben`, Z.3294)
- Test: `sales-mcp/tests/test_ignorieren.py`

**Interfaces:**
- Produces: `server.ignorieren_aufheben(lead_id: str) -> str | None`. Gibt den Satz „<Name> stand auf Ignorieren – aufgehoben, neue Nachrichten sind wieder sichtbar.“ zurück oder `None`, wenn nichts ignoriert war.
  - Die Rückgabe von `kontakt_freigeben` und `entwurf_freigeben` enthält dann zusätzlich `"ignorieren_aufgehoben": "<Satz>"`.

- [ ] **Step 1: Failing Tests** in `test_ignorieren.py`, Fixture-Muster wie dort:
```python
def test_freigabe_hebt_ignorieren_auf():
    lead = _lead_mit_nummer("+4915752415952")
    server._absender_ereignis(server.ABSENDER_IGNORIERT, "4915752415952@c.us", lead)
    assert server.absender_ist_ignoriert("4915752415952@c.us")
    a = json.loads(server.kontakt_freigeben(lead))
    assert "stand auf Ignorieren – aufgehoben" in a["ignorieren_aufgehoben"]
    assert not server.absender_ist_ignoriert("4915752415952@c.us")


def test_entwurf_freigabe_hebt_auf():
    ...  # Kontakt per Betreiber-Auftrag mit E-Mail-Entwurf, Nummer ignoriert -> entwurf_freigeben hebt auf


def test_nie_ignoriert_kein_ereignis():                              # Review Focus 4
    lead = _lead_mit_nummer("+4915000000001")
    a = json.loads(server.kontakt_freigeben(lead))
    assert "ignorieren_aufgehoben" not in a
    assert server._q("select count(*) n from activities where type = 'absender_beachtet'")[0]["n"] == 0


def test_kontakt_ohne_nummer():
    ...  # nur E-Mail -> None, kein Fehler
```
  Dazu ein UI-Test: `POST /freigaben/<id>/freigeben` hebt auf. Muster in `tests/test_ui.py` suchen und übernehmen.
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren:**
```python
def ignorieren_aufheben(lead_id: str) -> str | None:
    """Spec 1.5: wird ein ignorierter Absender echter Kontakt (Freigabe), faellt die Markierung weg.
    Schreibt 'absender_beachtet' (juengste Aussage gewinnt; @lid-Bruecke wie absender_ist_ignoriert)."""
    z = _q("select name, phone from leads where id = %s", (lead_id,))
    ziffern = re.sub(r"\D", "", (z[0]["phone"] or "") if z else "")
    if not ziffern:
        return None
    kennung = f"{ziffern}@c.us"
    if not absender_ist_ignoriert(kennung):
        return None
    _absender_ereignis(ABSENDER_BEACHTET, kennung, lead_id)
    _q("insert into activities (lead_id, type, payload) values (%s, 'absender_ignorieren_aufgehoben', %s) returning id",
       (lead_id, _json({"absender": kennung})))
    return f"{z[0]['name']} stand auf Ignorieren – aufgehoben, neue Nachrichten sind wieder sichtbar."
```
  - **`_whatsapp_freigabe_setzen(lead_id, True)`:** nach dem Insert `kontakt_freigabe` wird `ignorieren_aufheben` aufgerufen; der Satz kommt in die JSON-Rückgabe. Bei `False` geschieht nichts.
  - **`entwurf_freigeben`:** nach der Freigabe-Aktivität wird `ignorieren_aufheben(z["lead_id"])` aufgerufen, sofern `lead_id` gesetzt ist; der Satz kommt in die Rückgabe.
  - **`ui.aktion_freigeben` und `ui.aktion_kontakt_freigeben`:** nach erfolgreicher Freigabe `server.ignorieren_aufheben(...)` aufrufen. Die Oberfläche zeigt den Satz in der bestehenden Rückmeldung, falls es einen Mechanismus dafür gibt (`grep -n "meldung\|hinweis" ui.py` an diesen Stellen); sonst genügt der Aufruf.
- [ ] **Step 4: Grün:** `tests/test_ignorieren.py tests/test_einordnung.py tests/test_kontakt_freigabe.py tests/test_freigaben.py tests/test_ui.py`.
- [ ] **Step 5: Commit**
```
git add sales-mcp/server.py sales-mcp/ui.py sales-mcp/tests/test_ignorieren.py
git commit -m "feat(sales): Freigabe hebt Ignorieren eines Absenders auf" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `versand_abwarten`

**Files:**
- Modify: `sales-mcp/server.py` (neu bei `entwurf_freigeben`; `WERKZEUGE`)
- Create: `sales-mcp/tests/test_versand_abwarten.py`

**Interfaces:**
- Consumes: `mail_dispatch.kunden_identitaet()` (vorhanden).
- Produces: `versand_abwarten(draft_id: str, max_s: int = 60) -> str`. Rückgabe `{"draft_id", "ergebnis": "sent"|"failed"|"wartet"|"nicht_freigegeben"|"rejected", "kanal", "fehler"?: str, "hinweis"?: str}`.
  - Testbar über die Modul-Variablen `server._SCHLAF = time.sleep` und `server._UHR = time.monotonic`.

- [ ] **Step 1: Failing Tests:**
```python
def test_sofort_sent():                                             # Status bereits sent
    d = _draft(status="sent")
    assert json.loads(server.versand_abwarten(d))["ergebnis"] == "sent"


def test_failed_mit_grund():
    d = _draft(status="failed", error="SMTP 550")
    a = json.loads(server.versand_abwarten(d))
    assert a["ergebnis"] == "failed" and "550" in a["fehler"]


def test_pending_sofort(monkeypatch):                               # Review Focus 5
    d = _draft(status="pending")
    schlaefe = []
    monkeypatch.setattr(server, "_SCHLAF", schlaefe.append)
    assert json.loads(server.versand_abwarten(d))["ergebnis"] == "nicht_freigegeben" and schlaefe == []


def test_wartet_bis_frist(monkeypatch):
    d = _draft(status="approved", channel="whatsapp")
    t = [0.0]
    monkeypatch.setattr(server, "_UHR", lambda: t[0])
    monkeypatch.setattr(server, "_SCHLAF", lambda s: t.__setitem__(0, t[0] + s))
    assert json.loads(server.versand_abwarten(d, max_s=10))["ergebnis"] == "wartet"


def test_wird_waehrend_des_wartens_sent(monkeypatch):
    d = _draft(status="approved", channel="whatsapp")
    def schlaf(s):
        server._q("update drafts set status = 'sent' where id = %s returning id", (d,))
    monkeypatch.setattr(server, "_SCHLAF", schlaf)
    assert json.loads(server.versand_abwarten(d))["ergebnis"] == "sent"


def test_mail_ohne_kundenpostfach(monkeypatch):
    d = _draft(status="approved", channel="email")
    monkeypatch.setattr(server.mail_dispatch, "kunden_identitaet", lambda: type("I", (), {"brauchbar": lambda self: False})())
    a = json.loads(server.versand_abwarten(d))
    assert a["ergebnis"] == "wartet" and "bleibt liegen, bis das Postfach eingetragen ist" in a["hinweis"]
```
  `_draft(...)` legt einen Lead und eine Draft-Zeile direkt per SQL an. Wie `server` `mail_dispatch` importiert, prüfen (`grep -n "import mail_dispatch\|mail_dispatch" server.py`). Gibt es keinen Import, wird `kunden_identitaet` lazy im Werkzeug importiert, und der Test patcht das Modul `mail_dispatch`.
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren:**
```python
_SCHLAF = time.sleep
_UHR = time.monotonic
VERSAND_TAKT_S = 3


@_gesichert
def versand_abwarten(draft_id: str, max_s: int = 60) -> str:
    """Nach einer Freigabe: wartet hoechstens max_s Sekunden, bis der Versanddienst den Entwurf verschickt hat
    (Spec 2.2). Ergebnis sent | failed (mit Grund) | wartet | nicht_freigegeben | rejected. Versendet selbst nichts."""
    ende = _UHR() + max(0, min(int(max_s), 120))
    while True:
        z = _q("select status, channel, error from drafts where id = %s", (draft_id,))
        if not z:
            return _json({"fehler": f"Kein Entwurf {draft_id}."})
        s, kanal = z[0]["status"], z[0]["channel"]
        if s == "pending":
            return _json({"draft_id": draft_id, "ergebnis": "nicht_freigegeben", "kanal": kanal})
        if s in ("sent", "rejected"):
            return _json({"draft_id": draft_id, "ergebnis": s, "kanal": kanal})
        if s == "failed":
            return _json({"draft_id": draft_id, "ergebnis": "failed", "kanal": kanal, "fehler": z[0]["error"] or ""})
        if kanal == "email":
            import mail_dispatch
            if not mail_dispatch.kunden_identitaet().brauchbar():
                return _json({"draft_id": draft_id, "ergebnis": "wartet", "kanal": kanal,
                              "hinweis": "Freigegeben, bleibt liegen, bis das Postfach eingetragen ist."})
        if _UHR() >= ende:
            return _json({"draft_id": draft_id, "ergebnis": "wartet", "kanal": kanal,
                          "hinweis": "liegt freigegeben in der Warteschlange"})
        _SCHLAF(VERSAND_TAKT_S)
```
  `versand_abwarten` kommt in `WERKZEUGE`.
- [ ] **Step 4: Grün:** neue Datei, dazu `tests/test_werkzeuge.py`.
- [ ] **Step 5: Commit**
```
git add sales-mcp/server.py sales-mcp/tests/test_versand_abwarten.py
git commit -m "feat(sales): versand_abwarten meldet ist raus / nicht raus / wartet" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Bedarfsanalyse abschalten

**Files:**
- Modify: `sales-mcp/server.py` (`WERKZEUGE`-Registrierung am Dateiende; `digest`, Z.4155-4180 und 4276; `uebergabe_erstellen`, Z.5088)
- Modify: `sales-mcp/ui.py` (`kontakt_detail`, Z.5237-5250)
- Test: `sales-mcp/tests/test_bedarfsanalyse_schalter.py` (neu)

**Interfaces:**
- Produces: `server.bedarfsanalyse_an() -> bool` (liest `SALES_BEDARFSANALYSE` je Aufruf; True nur bei `"an"`). `server.BEDARFS_WERKZEUGE = (bedarf_speichern, bedarf_offen)`.

- [ ] **Step 1: Failing Tests:**
```python
def test_aus_ist_vorgabe(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    assert server.bedarfsanalyse_an() is False


def test_werkzeuge_ohne_bedarf(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    namen = {f.__name__ for f in server.aktive_werkzeuge()}
    assert "bedarf_speichern" not in namen and "bedarf_offen" not in namen and "entwurf_erstellen" in namen


def test_an_bringt_sie_zurueck(monkeypatch):
    monkeypatch.setenv("SALES_BEDARFSANALYSE", "an")
    assert {"bedarf_speichern", "bedarf_offen"} <= {f.__name__ for f in server.aktive_werkzeuge()}


def test_digest_ohne_bedarf(monkeypatch):
    monkeypatch.delenv("SALES_BEDARFSANALYSE", raising=False)
    assert "unvollstaendige_bedarfsanalysen" not in json.loads(server.digest())


def test_uebergabe_ohne_abschnitt(monkeypatch):
    ...  # Lead mit enrichment.bedarf -> uebergabe_erstellen enthaelt "## Bedarfsanalyse" nicht
```
  Dazu ein UI-Test: Die Kontaktseite enthält „Bedarfsstand“ nicht. Muster aus `tests/test_ui.py` übernehmen.
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementieren:**
```python
def bedarfsanalyse_an() -> bool:
    return os.environ.get("SALES_BEDARFSANALYSE", "").strip().lower() == "an"


BEDARFS_WERKZEUGE = (bedarf_speichern, bedarf_offen)


def aktive_werkzeuge() -> tuple:
    return tuple(f for f in WERKZEUGE if bedarfsanalyse_an() or f not in BEDARFS_WERKZEUGE)
```
  - Die Registrierung am Dateiende läuft über `for _fn in aktive_werkzeuge(): mcp.tool()(_fn)`.
  - Im `digest` werden der Block (Z.4169-4180) und der Schlüssel nur bei `bedarfsanalyse_an()` berechnet bzw. gesetzt.
  - In `uebergabe_erstellen` werden die beiden Zeilen (Z.5088-5089) nur bei `bedarfsanalyse_an()` angehängt.
  - In `ui.kontakt_detail` wird der Bedarfsstand-Block nur bei `server.bedarfsanalyse_an()` gezeigt.
  - Bestehende Tests, die die Bedarfsanalyse prüfen (`test_werkzeuge.py`, `test_uebergabe.py`, `test_recherche.py`, `test_ui.py`, `test_zustimmung.py`, `test_dsgvo.py`, `test_privat.py`), bekommen `monkeypatch.setenv("SALES_BEDARFSANALYSE", "an")` in den betroffenen Tests. Sie werden nicht gelöscht.
- [ ] **Step 4: Grün:** die komplette Suite `tests/ -q`, denn der Schalter berührt viele Dateien.
- [ ] **Step 5: Commit**
```
git add sales-mcp/server.py sales-mcp/ui.py sales-mcp/tests/test_bedarfsanalyse_schalter.py <angepasste Testdateien>
git commit -m "feat(sales): Bedarfsanalyse per SALES_BEDARFSANALYSE abschaltbar (Vorgabe aus)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Prompt-Regeln in `AGENTS.md` mit Drift-Test

**Files:**
- Modify: `config/workspace/AGENTS.md`
- Create: `sales-mcp/tests/test_agents_regeln.py`

**Interfaces:**
- Consumes: die Werkzeugnamen `mail_beantworten`, `versand_abwarten` und den Parameter `auftrag_betreiber` (Tasks 2, 3, 5).

- [ ] **Step 1: Failing Drift-Test:**
```python
from pathlib import Path
TEXT = (Path(__file__).resolve().parents[2] / "config" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")

def test_nie_automatisch_antworten():
    assert "Eingehende Nachrichten erzeugen höchstens einen Entwurf zur Freigabe" in TEXT

def test_postfach_antwort_ueber_mail_beantworten():
    assert "mail_beantworten" in TEXT and "nie eigenmächtig den Kanal" in TEXT

def test_auftrag_betreiber_erklaert():
    assert "auftrag_betreiber=true" in TEXT

def test_freigabe_im_chat():
    for wort in ("„ja“", "„senden“", "„raus“", "„freigeben“", "„ok“"):
        assert wort in TEXT
    assert "keine zweite Rückfrage" in TEXT
    assert "versand_abwarten" in TEXT

def test_fehler_nie_verschlucken():
    assert "Liefert ein Werkzeug einen Fehler, nennst du ihn im selben Zug" in TEXT

def test_bedarfsanalyse_raus():
    assert "## Bedarfsanalyse" not in TEXT and "Leitfaden-Frage" not in TEXT
```
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: `AGENTS.md` ändern:**
  - **Bedarfsanalyse raus:**
    - Abschnitt `## Bedarfsanalyse` (Z.81-97) löschen. Der Absatz `**Vertraege festhalten.**` darin bleibt und wandert unter `## Termine` bzw. an das Ende des vorigen Abschnitts.
    - In Z.27-37 (Rolle) die Sätze zum Leitfaden entfernen, etwa „findest … per Leitfaden heraus“ und „Bedarfslücken: zeigt der Leitfaden …“. Bleiben soll: „Terminanlässe nennt der Betreiber.“
    - In Z.544-549 „Bedarfsanalyse“ aus der Aufzählung und den Satz „hoechstens EINE Leitfaden-Frage je Nachricht“ streichen.
    - In Z.1036 „und Bedarfsanalysen“ streichen.
  - **Neuer Abschnitt `## Antworten nur mit Freigabe`** vor `## Entwuerfe` (Z.586):
```
## Antworten nur mit Freigabe

- **Eingehende Nachrichten erzeugen höchstens einen Entwurf zur Freigabe** und einen Hinweis an den Betreiber — nie einen Versand ohne seine Freigabe. Das gilt auch für Kontakte, deren Ignorieren gerade aufgehoben wurde.
- **Antwort auf eine Postfach-Mail** („dort antworten“, „auf die Mail antworten“): immer `mail_beantworten(uid, text)`. Du wechselst nie eigenmächtig den Kanal und fragst nicht nach einer Telefonnummer, wenn die Anfrage per Mail kam.
- **Verlangt der Betreiber ausdrücklich, jemandem zu schreiben**, rufst du `entwurf_erstellen` bzw. `antwort_entwerfen` mit `auftrag_betreiber=true` auf. Dann entsteht der Entwurf auch bei Stufe „manuell“, und eine fehlende Einwilligung gilt als vom Betreiber bestätigt (sie wird mit Quelle gebucht). Nie im Kundenchat, nie aus eigenem Antrieb.
```
  - **Absatz Z.673-680 (Freigabe) ersetzen durch:**
```
- **Freigabe im Chat:** Zeige den Entwurf einmal vollständig (Empfänger, Kanal, Betreff, Text). Antwortet der Betreiber in der nächsten Nachricht mit „ja“, „senden“, „raus“, „freigeben“ oder „ok“, rufst du `entwurf_freigeben` für genau diesen Entwurf auf — keine zweite Rückfrage. „ändere …“ heißt `entwurf_bearbeiten` und den neuen Text erneut zeigen. Sind mehrere Entwürfe offen und ist unklar, welcher gemeint ist, fragst du einmal kurz nach. Ablehnen nur, wenn der Betreiber ausdrücklich ablehnt.
- **Nach jeder Freigabe** rufst du `versand_abwarten(draft_id)` auf und meldest das Ergebnis in einem Satz: „Ist raus an X (E-Mail)“, „Nicht raus: <Grund>“ oder „liegt freigegeben in der Warteschlange“ bzw. „bleibt liegen, bis das Postfach eingetragen ist“.
```
    Der bestehende Absatz „Nach einer WhatsApp- oder E-Mail-Freigabe …“ (Z.682ff) wird gestrichen, weil die Zeile oben ihn ersetzt. Der LinkedIn-Absatz bleibt.
  - **Ganz oben**, im ersten Regelabschnitt, kommt diese Regel dazu:
```
- **Liefert ein Werkzeug einen Fehler, nennst du ihn im selben Zug** — ein Satz: was nicht ging, warum, und der nächste Schritt. Nie stillschweigend weitermachen oder ein anderes Ergebnis berichten.
```
- [ ] **Step 4: Grün:** `tests/test_agents_regeln.py`, dazu ein `grep -n "Leitfaden\|bedarf_" config/workspace/AGENTS.md`. Erwartet: keine Treffer bis auf ausdrücklich gewollte Verweise, und die müssen dann begründet im Report stehen.
- [ ] **Step 5: Commit**
```
git add config/workspace/AGENTS.md sales-mcp/tests/test_agents_regeln.py
git commit -m "feat(sales): Agent-Regeln - Antworten nur mit Freigabe, Freigabe im Chat, Fehler nennen, ohne Bedarfsanalyse" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Cronjob läuft in der Betreiber-Sitzung — messen, dann beheben (Controller, VM nur lesend bis zum Befund)

**Files:** abhängig vom Befund, z. B. `deploy/cron/*.json`, `deploy/cron/README.md`, `docs/03_RUNBOOK.md`.

- [ ] **Step 1: Messen,** ohne etwas zu ändern:
  - **openclaw-Version:** `docker exec sales-claw openclaw --version`.
  - **Aktive Cron-Jobs:** `docker exec sales-claw openclaw cron list --json`. Hat `postfach-check` `sessionTarget=isolated`?
  - **Sitzungsdateien:** In `ab0d7fa9…jsonl` steht der Cron-Prompt (`[cron:394e7e93… postfach-check]`). Prüfen, ob es zu derselben Zeit eine eigene isolierte Sitzungsdatei gibt. Wenn ja, wird nur der Bericht (`announce`) in die Hauptsitzung gespiegelt; das ist der Befund „Zustellung als Nachricht“.
  - **Welche Sitzung der WhatsApp-Chat des Betreibers nutzt** (`sessions.json` bzw. `session key`), und ob angekündigte Cron-Ergebnisse dort als `user`-Nachricht mit `[cron:…]`-Präfix landen.
- [ ] **Step 2: Ruling im Ledger** mit Ursache und gewählter Behebung. Mögliche Wege, vom kleinsten zum größten:
  - (a) `delivery.mode` so stellen, dass der Bericht als eigene Nachricht an den Betreiber geht, ohne in die Agent-Sitzung zu schreiben, falls openclaw das kennt (`openclaw cron add --help` prüfen).
  - (b) Prompt-Regel: Nachrichten mit Präfix `[cron:` sind Berichte; ein folgendes „ja“ des Betreibers bezieht sich nie auf sie, sondern auf den letzten Entwurf des Agenten. Das kommt in `AGENTS.md` mit Drift-Test in `test_agents_regeln.py`.
  - (c) Der Job wird auf einen eigenen Agenten (`agentId`) mit eigener Sitzung gelegt.
- [ ] **Step 3: Umsetzen** (Repo-Änderungen mit Test bzw. Drift-Test) und committen. Die Änderung an Cron-Jobs **auf der VM** passiert erst in Task 9.

---

### Task 9: Auslieferung und echter Lauf (Controller, nur nach Freigabe des Betreibers)

- [ ] **Claims** in WORKBOARD und secondbrain, nur die eigene Zeile stagen.
- [ ] **Push** von SC `feat/stufe-1-fundament`, dann auf der VM `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`. Das spielt `provision.sql` je Laden ein und baut die Container neu. Erwartet: „ALLE PRUEFUNGEN GRUEN“.
- [ ] **Cron-Änderung aus Task 8** auf der VM übernehmen, wie dort entschieden.
- [ ] **Einmalige Reparatur** im Container `sales-mcp`: `eingang_einordnen(absender="4915752415952@c.us", entscheidung="beachten")` und dasselbe für `4915565715663@c.us`, beides über das Werkzeug. Danach gibt `absender_ist_ignoriert(...)` für beide False zurück.
- [ ] **Echter Lauf:**
  1. Eine Probe-Mail an das Betreiber-Postfach. Im Chat „dort antworten: Danke, passt“, der Agent nutzt `mail_beantworten`, zeigt den Entwurf, dann „ja“, dann „Ist raus“. Die Mail kommt im selben Verlauf an (Header prüfen).
  2. Ein Auftrag an einen Kontakt auf „manuell“ mit freigegebener WhatsApp ergibt einen Entwurf `pending` mit Hinweis.
  3. Eine Probe-WhatsApp an einen ignorierten, inzwischen freigegebenen Testkontakt ist als `kundenantwort` sichtbar, und es geht nichts automatisch raus.
  4. Ein Werkzeugfehler (z. B. `mail_beantworten` mit unbekannter uid) wird im Chat genannt.
- [ ] **Claims schließen,** Memory aktualisieren.
