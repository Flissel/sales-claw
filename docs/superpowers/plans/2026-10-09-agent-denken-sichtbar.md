# Agent-Denken sichtbar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Betreiber sieht beim Editor-Agenten und beim Marken-Chat Claudes zusammengefasstes Denken und die Arbeitsschritte, live während der Runde und danach pro Runde aufklappbar.

**Architecture:**
- Der Marketing-Shim startet die Claude-CLI auf Wunsch mit `--thinking-display summarized` und reicht `thinking_delta` als `reasoning_content` im SSE-Strom weiter.
- Der Chat-Arbeiter sammelt Denken und Schritte in einer gedrosselten `Spur` und schreibt sie über neue Arbeiter-Routen in die Auftragszeilen der VM (Migration 065).
- Die Stand-Routen liefern beides aus, Sales-Seite „Marke“ und Editor zeigen es an.

**Tech Stack:**
- Python 3.11: FastAPI (Marketing-API), http.server (Shim, Arbeiter), Starlette (sales-ui), pytest.
- PostgreSQL / plpgsql (Supabase auf der VM).
- React + MUI + zustand im Editor (vitest, `react-dom/server` für Render-Tests).

**Spec:** `docs/superpowers/specs/2026-10-09-agent-denken-sichtbar-design.md` (sales-claw)

## Repos und Arbeitsweise

- **MOS** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent`, Branch `master`.
  - Dateien liegen unter `spaces/marketing/...`.
  - Vor **jedem** Commit `git rev-parse --show-toplevel` und `git branch --show-current` prüfen. Niemals im Haupt-Checkout `C:/Users/User/Desktop/Vibemind_V1/vibemind-os` committen.
  - Tests:
    ```
    cd C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent
    C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/<pfad> -q
    ```
- **SC** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`.
  - sales-ui-Tests:
    ```
    cd sales-mcp && <venv-sales python> -m pytest tests/test_marke_seite.py -q
    ```
    Umgebung wie in den bestehenden Tests, siehe `constraints.md` im SDD-Ordner.
  - Editor:
    ```
    cd editor && npx vitest run && npx tsc --noEmit && npm run build
    ```
    Das gebaute Bundle `sales-mcp/static/editor` wird mit committet.
- Commits: Conventional Commits auf Deutsch, Trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Nur eigene Dateien einzeln stagen.
  - Nie `git add -A`, nie `.superpowers/` stagen.
  - Nie stash, force oder `--no-verify`.
- Kein Deploy, keine Migration gegen echte DBs, kein Neustart von Diensten. Das macht der Controller in Task 9 nach Freigabe des Betreibers.

## Global Constraints

- Denken nur auf Anforderung: Body-Schlüssel `"marketing_denken": true`. Nur dann setzt der Shim `--max-thinking-tokens 4000 --thinking-display summarized`.
- `MARKETING_DENKEN=0` in der Shim-Umgebung lässt die Schalter immer weg.
- `thinking_delta` → `choices[0].delta.reasoning_content`; `text_delta` bleibt `delta.content`.
- Rückfall: Lehnt die CLI den Schalter ab (`unknown option`, bevor etwas geliefert wurde), folgt genau ein Neustart ohne Schalter. Vorher kommt `reasoning_content` = `(Denken nicht verfügbar)`.
- Drossel: höchstens ein Schreibvorgang je 2 s pro Auftrag, der Endstand immer.
- Gespeichertes Denken: höchstens 20 000 Zeichen. Bei Überlauf bleibt das Ende, vorn steht `… gekürzt` plus Zeilenumbruch.
- Höchstens 60 Schritte, je höchstens 200 Zeichen Text, `zeit` als `HH:MM:SS`.
- Trennzeile Korrekturrunde: `— Korrekturrunde —` (mit Leerzeilen davor und danach).
- Kennzeichnung im UI: `Claudes Gedanken (zusammengefasst, englisch)`. Aufklapp-Titel: `Gedanken & Schritte`. Live-Titel: `Denkt nach …`. Schalter: `Gedanken ausblenden` / `Gedanken einblenden`.
- Schritte enthalten nie Schlüssel, Umgebungswerte oder URLs mit Zugangsdaten. Der Arbeiter schreibt nur feste Satzbausteine, Zahlen, Block-Schrittnamen und Prüf-Gründe.
- Sichtbar nur in der Betreiber-Oberfläche (Editor, Seite „Marke“). Nie in Newsletter, Exporte, Vorschauen.
- Sichtbarkeit darf einen Auftrag nie scheitern lassen: Jeder Fehler beim Sammeln oder Senden wird geschluckt.

## Review Focus

1. **Lange Runde mit viel Denken (>20 000 Zeichen):** Das Ende bleibt erhalten, vorn steht „… gekürzt“, die DB nimmt es an. Tests: Task 3 (`test_denken_kuerzt_vorn`) und Task 2 (Grenze in SQL).
2. **VM kurz nicht erreichbar während der Runde:** Die Runde läuft weiter und schreibt beim nächsten Takt erneut. Tests: Task 3 (`test_senden_fehler_bleibt_offen`), Task 5 (`test_denken_route_weg_kippt_auftrag_nicht`).
3. **CLI-Update entfernt den Schalter:** Die Runde gelingt ohne Denken, im Denken steht „(Denken nicht verfügbar)“. Test: Task 1 (`test_rueckfall_ohne_denk_schalter`).
4. **Gestoppter oder gescheiterter Auftrag:** Das bisher Gesammelte steht trotzdem an der Zeile. Tests: Task 5 (`test_stopp_sendet_spur_vor_gestoppt`), Task 6 (`test_aufgeben_sendet_spur`).
5. **Älterer Auftrag ohne Spalteninhalt (NULL):** Die Seiten zeigen dafür kein leeres Aufklapp-Element. Tests: Task 7 (`test_ohne_spur_kein_details`), Task 8 (`rendert nichts ohne Spur`).

---

### Task 1: Shim reicht das Denken weiter

**Files:**
- Modify: `spaces/marketing/claw/shim/marketing_shim.py` (MOS):
  - `_build_command` (ca. Z. 296-400)
  - `text_stuecke` (Z. 505-550)
  - `stream_claude` (Z. 553-625)
  - `_send_stream` (Z. 681-731)
  - Handler-Streamzweig (Z. 862-881)
- Modify: `spaces/marketing/claw/shim/tests/falsche_cli.py`
- Test: `spaces/marketing/claw/shim/tests/test_marketing_shim.py`

**Interfaces:**
- Produces:
  - `class Denken(str)`: ein Strom-Stück, das Denken ist und kein Antworttext.
  - `DENK_TOKEN = 4000`, `DENKEN_NICHT_VERFUEGBAR = "(Denken nicht verfügbar)"`.
  - `text_stuecke(zeilen, mit_denken: bool = False) -> Iterator[str]`
  - `stream_claude(..., denken: bool = False)`
  - `stream_denkend(**kw) -> Iterator[str]`
  - `_build_command(..., denken: bool = False)`
  - SSE-Chunk `{"choices":[{"delta":{"reasoning_content": "<text>"}}]}`.

- [ ] **Step 1: Falsche CLI kann denken**

In `falsche_cli.py` vor dem `if modus == "exit":` einfügen:

```python
def denk_delta(text):
    print('{"type":"stream_event","event":{"type":"content_block_delta","index":0,'
          '"delta":{"type":"thinking_delta","thinking":"%s"}}}' % text, flush=True)


if modus == "denken_abgelehnt" and "--thinking-display" in argv:
    sys.stderr.write("error: unknown option '--thinking-display'\n")
    sys.exit(1)
if "stream-json" in argv and "--thinking-display" in argv and modus != "denken_abgelehnt":
    print(START, flush=True)
    denk_delta("Let me think")
    denk_delta(" about it.")
    delta("Antwort")
    print('{"type":"result","subtype":"success","is_error":false,"result":"Antwort"}', flush=True)
    sys.exit(0)
```

- [ ] **Step 2: Failing tests schreiben**

An `test_marketing_shim.py` anhängen. Nutze die vorhandenen Fixtures `server` und `protokoll` und den Helfer, mit dem die bestehenden Streamtests `/v1/chat/completions` mit `stream: True, marketing_stream: True` posten und die SSE-Zeilen sammeln (z. B. wie in `test_stream_echt_und_in_reihenfolge`). Lege, falls nicht vorhanden, einen Helfer `_sse(server, body) -> list[dict]` an, der die `data:`-JSON-Objekte ohne `[DONE]` liefert.

```python
def _denk_body(**extra):
    return {"model": "claude-code-sonnet", "stream": True, "marketing_stream": True,
            "messages": [{"role": "user", "content": "hi"}], **extra}


def test_denk_schalter_nur_auf_anforderung(server, protokoll):
    _sse(server, _denk_body())
    argv = json.loads(protokoll.read_text(encoding="utf-8"))["argv"]
    assert "--thinking-display" not in argv
    _sse(server, _denk_body(marketing_denken=True))
    argv = json.loads(protokoll.read_text(encoding="utf-8"))["argv"]
    i = argv.index("--thinking-display")
    assert argv[i + 1] == "summarized"
    assert argv[argv.index("--max-thinking-tokens") + 1] == "4000"


def test_marketing_denken_0_schaltet_ab(server, protokoll, monkeypatch):
    monkeypatch.setenv("MARKETING_DENKEN", "0")
    _sse(server, _denk_body(marketing_denken=True))
    argv = json.loads(protokoll.read_text(encoding="utf-8"))["argv"]
    assert "--thinking-display" not in argv and "--max-thinking-tokens" not in argv


def test_denken_kommt_als_reasoning_content(server):
    chunks = _sse(server, _denk_body(marketing_denken=True))
    deltas = [c["choices"][0]["delta"] for c in chunks]
    denken = "".join(d.get("reasoning_content", "") for d in deltas)
    inhalt = "".join(d.get("content", "") or "" for d in deltas)
    assert denken == "Let me think about it."
    assert inhalt == "Antwort"                 # Denken nie im Inhalt


def test_rueckfall_ohne_denk_schalter(server, monkeypatch):
    monkeypatch.setenv("FALSCH_MODUS", "denken_abgelehnt")
    chunks = _sse(server, _denk_body(marketing_denken=True))
    deltas = [c["choices"][0]["delta"] for c in chunks]
    assert "".join(d.get("reasoning_content", "") for d in deltas) == "(Denken nicht verfügbar)"
    assert "".join(d.get("content", "") or "" for d in deltas) == "eins zwei drei"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_text_stuecke_ohne_mit_denken_ignoriert_thinking():
    zeilen = ['{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"x"}}}',
              '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"a"}}}']
    assert list(shim.text_stuecke(zeilen)) == ["a"]
    mit = list(shim.text_stuecke(zeilen, mit_denken=True))
    assert mit == ["x", "a"] and isinstance(mit[0], shim.Denken) and not isinstance(mit[1], shim.Denken)
```

Hinweis: Falls die Fixture `server` `FALSCH_MODUS` beim Start liest statt pro Aufruf, setze den Modus so, wie es `test_cli_exit_im_stream_gibt_error_chunk` tut.

- [ ] **Step 3: Tests laufen lassen, sie schlagen fehl**

Run: `...python.exe -m pytest spaces/marketing/claw/shim/tests/test_marketing_shim.py -q -k "denk or rueckfall or text_stuecke_ohne"`
Expected: FAIL (`--thinking-display` fehlt, `Denken` existiert nicht).

- [ ] **Step 4: Implementieren**

In `marketing_shim.py`:

```python
DENK_TOKEN = 4000
DENKEN_NICHT_VERFUEGBAR = "(Denken nicht verfügbar)"


class Denken(str):
    """Ein Strom-Stueck mit Claudes (zusammengefasstem) Denken - nie Antworttext."""


def _denken_erlaubt() -> bool:
    return os.environ.get("MARKETING_DENKEN", "1").strip() != "0"
```

`_build_command(...)` bekommt `denken: bool = False`. Direkt nach dem Setzen der stream-json-Schalter, also dort, wo `streaming` `--include-partial-messages` ergänzt:

```python
    if denken and streaming and _denken_erlaubt():
        argv += ["--max-thinking-tokens", str(DENK_TOKEN), "--thinking-display", "summarized"]
```

`text_stuecke(zeilen, mit_denken: bool = False)`: Im `content_block_delta`-Zweig vor dem `text_delta`-Fall:

```python
            elif (
                mit_denken
                and isinstance(event, dict)
                and event.get("type") == "content_block_delta"
                and isinstance(delta, dict)
                and delta.get("type") == "thinking_delta"
                and isinstance(delta.get("thinking"), str)
                and delta["thinking"]
            ):
                yield Denken(delta["thinking"])
```

Denken setzt weder `geliefert` noch `neuer_turn`, denn der Rückfall auf `result` gilt nur für Antworttext.

`stream_claude(..., denken: bool = False)` reicht `denken` an `_build_command` weiter und ruft `text_stuecke(proc.stdout, mit_denken=denken)`.

Neu, direkt nach `stream_claude`:

```python
def stream_denkend(**kw) -> Iterator[str]:
    """stream_claude mit Rueckfall: lehnt die CLI den (undokumentierten) Denk-Schalter ab, bevor
    etwas kam, einmal ohne ihn - vorher ein Denk-Stueck "(Denken nicht verfuegbar)"."""
    if not kw.get("denken"):
        yield from stream_claude(**kw)
        return
    geliefert = False
    try:
        for stueck in stream_claude(**kw):
            geliefert = True
            yield stueck
        return
    except ShimError as exc:
        if geliefert or "unknown option" not in str(exc).lower():
            raise
    yield Denken(DENKEN_NICHT_VERFUEGBAR)
    yield from stream_claude(**{**kw, "denken": False})
```

`_send_stream`: In der Schleife `for text in pieces:`:

```python
                for text in pieces:
                    delta: dict[str, Any] = (
                        {"reasoning_content": str(text)} if isinstance(text, Denken) else {"content": text})
```

Der Rest bleibt, einschließlich `role` am ersten Chunk.

Prüfe `_gebucht(...)`: Es muss die Stücke unverändert durchreichen. Ein `str(...)`/`"".join` darin würde die `Denken`-Klasse verlieren. Gegebenenfalls nur durchreichen.

Handler-Streamzweig: `denken = body.get("marketing_denken") is True` lesen und `stream_claude(` durch `stream_denkend(` mit zusätzlichem `denken=denken` ersetzen. Der Nicht-Stream-Pfad (`run_claude`) bleibt unverändert.

- [ ] **Step 5: Tests laufen lassen**

Run: `...python.exe -m pytest spaces/marketing/claw/shim/tests -q`
Expected: alle PASS, die bestehenden unverändert grün.

- [ ] **Step 6: Commit (MOS)**

```
git add spaces/marketing/claw/shim/marketing_shim.py spaces/marketing/claw/shim/tests/falsche_cli.py spaces/marketing/claw/shim/tests/test_marketing_shim.py
git commit -m "feat(marketing): Shim reicht Claudes Denken als reasoning_content weiter"
```

---

### Task 2: Migration 065 — Spalten und Schreibfunktionen

**Files:**
- Create: `spaces/marketing/db/065_denken.sql` (MOS)
- Create: `spaces/marketing/db/verify_065.sql`

**Interfaces:**
- Produces:
  - Spalten `denken text`, `schritte jsonb` an `marketing.chat_auftraege` und `marketing.marken_auftraege`.
  - `marketing._spur_pruefen(text, jsonb) RETURNS void` (wirft bei Verstoß).
  - `marketing.pult_chat_denken(p_auftrag uuid, p_denken text, p_schritte jsonb) RETURNS boolean`: false, wenn der Auftrag nicht mit gültiger Vergabe `in_arbeit` ist.
  - `marketing.pult_marke_denken(p_auftrag uuid, p_denken text, p_schritte jsonb) RETURNS boolean`, Semantik wie oben.

- [ ] **Step 1: verify_065.sql (der Test) schreiben**

Stil wie `db/verify_064.sql`: läuft nur über `migration_probe`, eigene Probe-Firma, am Ende die Zeile `verify_065 ok` genau so, wie verify_064 sein `verify_064 ok` ausgibt (dort nachsehen). Inhalt:

```sql
-- Nachweise fuer 065, nur ueber migration_probe (eine Transaktion + ROLLBACK).
CREATE TEMP TABLE _p065 ON COMMIT DROP AS SELECT NULL::text AS k, NULL::uuid AS id LIMIT 0;

DO $$ DECLARE v uuid; i uuid; BEGIN
  INSERT INTO marketing.mandanten (id, name, aktiv) VALUES ('probe_denken', 'Probe Denken', true);
  INSERT INTO marketing.marken_auftraege (mandant, art, nachricht, status, vergeben_bis)
  VALUES ('probe_denken', 'chat', 'x', 'in_arbeit', now() + interval '5 minutes') RETURNING id INTO v;
  INSERT INTO _p065 VALUES ('marke_ok', v);
  INSERT INTO marketing.marken_auftraege (mandant, art, nachricht, status, vergeben_bis)
  VALUES ('probe_denken', 'uebernehmen', 'y', 'in_arbeit', now() - interval '1 second') RETURNING id INTO v;
  INSERT INTO _p065 VALUES ('marke_abgelaufen', v);
  INSERT INTO marketing.inhalte (mandant, art, titel) VALUES ('probe_denken', 'newsletter', 'Probe 065')
  RETURNING id INTO i;
  INSERT INTO marketing.chat_auftraege (inhalt, art, nachricht, status, vergeben_bis)
  VALUES (i, 'chat', 'z', 'in_arbeit', now() + interval '5 minutes') RETURNING id INTO v;
  INSERT INTO _p065 VALUES ('chat_ok', v);
  INSERT INTO marketing.chat_auftraege (inhalt, art, nachricht, status)
  VALUES (i, 'chat', 'w', 'fertig') RETURNING id INTO v;
  INSERT INTO _p065 VALUES ('chat_fertig', v);
END $$;

DO $$ DECLARE ok boolean; s jsonb := '[{"zeit":"08:03:41","text":"Frage an Claude"}]'; BEGIN
  ok := marketing.pult_marke_denken((SELECT id FROM _p065 WHERE k='marke_ok'), 'Let me think', s);
  IF NOT ok THEN RAISE EXCEPTION 'marke_ok muss true sein'; END IF;
  IF (SELECT denken FROM marketing.marken_auftraege WHERE id=(SELECT id FROM _p065 WHERE k='marke_ok')) <> 'Let me think'
    THEN RAISE EXCEPTION 'denken nicht gespeichert'; END IF;
  IF (SELECT schritte FROM marketing.marken_auftraege WHERE id=(SELECT id FROM _p065 WHERE k='marke_ok')) <> s
    THEN RAISE EXCEPTION 'schritte nicht gespeichert'; END IF;
  IF marketing.pult_marke_denken((SELECT id FROM _p065 WHERE k='marke_abgelaufen'), 'x', '[]') THEN
    RAISE EXCEPTION 'abgelaufene Vergabe darf nicht schreiben'; END IF;
  IF NOT marketing.pult_chat_denken((SELECT id FROM _p065 WHERE k='chat_ok'), 'c', s) THEN
    RAISE EXCEPTION 'chat_ok muss true sein'; END IF;
  IF marketing.pult_chat_denken((SELECT id FROM _p065 WHERE k='chat_fertig'), 'c', s) THEN
    RAISE EXCEPTION 'fertiger Auftrag darf nicht schreiben'; END IF;
  IF marketing.pult_chat_denken(gen_random_uuid(), 'c', s) THEN
    RAISE EXCEPTION 'unbekannter Auftrag darf nicht schreiben'; END IF;
END $$;

-- Grenzen: jede Verletzung wirft
DO $$ DECLARE a uuid := (SELECT id FROM _p065 WHERE k='chat_ok'); geworfen boolean; BEGIN
  geworfen := false;
  BEGIN PERFORM marketing.pult_chat_denken(a, repeat('x', 20101), '[]');
  EXCEPTION WHEN others THEN geworfen := true; END;
  IF NOT geworfen THEN RAISE EXCEPTION 'Denken > 20100 muss werfen'; END IF;
  geworfen := false;
  BEGIN PERFORM marketing.pult_chat_denken(a, 'x',
    (SELECT jsonb_agg(jsonb_build_object('zeit','08:00:00','text','s')) FROM generate_series(1,61)));
  EXCEPTION WHEN others THEN geworfen := true; END;
  IF NOT geworfen THEN RAISE EXCEPTION '61 Schritte muessen werfen'; END IF;
  geworfen := false;
  BEGIN PERFORM marketing.pult_chat_denken(a, 'x', jsonb_build_array(jsonb_build_object('zeit','08:00:00','text',repeat('t',201))));
  EXCEPTION WHEN others THEN geworfen := true; END;
  IF NOT geworfen THEN RAISE EXCEPTION 'Schritt > 200 muss werfen'; END IF;
  geworfen := false;
  BEGIN PERFORM marketing.pult_chat_denken(a, 'x', '{"a":1}');
  EXCEPTION WHEN others THEN geworfen := true; END;
  IF NOT geworfen THEN RAISE EXCEPTION 'Schritte als Objekt muss werfen'; END IF;
  -- genau an der Grenze geht es
  IF NOT marketing.pult_chat_denken(a, repeat('x', 20100),
    (SELECT jsonb_agg(jsonb_build_object('zeit','08:00:00','text',repeat('t',200))) FROM generate_series(1,60)))
    THEN RAISE EXCEPTION 'Grenzwerte muessen gehen'; END IF;
END $$;
```

Danach die Erfolgszeile im Stil von verify_064. Falls `marken_auftraege` oder `chat_auftraege` Pflichtspalten haben, die oben fehlen, ergänze sie nach `db/064_marke.sql:95ff` bzw. `db/060_gestaltung_und_chat.sql:67ff`.

- [ ] **Step 2: Probe, sie schlägt fehl**

Run (aus dem MOS-Root, Lese-Probe gegen die VM-DB mit ROLLBACK):

```
SUPABASE_SSH_HOST=offload-vm SUPABASE_DB_CONTAINER=debian-supabase-db-1 \
  C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m spaces.marketing.scripts.migration_probe \
  spaces/marketing/db/verify_065.sql
```

Expected: FAIL (`function marketing.pult_marke_denken ... does not exist`).

- [ ] **Step 3: 065_denken.sql schreiben**

```sql
-- 065: Denken und Schritte der Agenten-Auftraege (Spec sales-claw 2026-10-09-agent-denken-sichtbar).
-- Idempotent, eine Transaktion.
BEGIN;

ALTER TABLE marketing.chat_auftraege ADD COLUMN IF NOT EXISTS denken text;
ALTER TABLE marketing.chat_auftraege ADD COLUMN IF NOT EXISTS schritte jsonb;
ALTER TABLE marketing.marken_auftraege ADD COLUMN IF NOT EXISTS denken text;
ALTER TABLE marketing.marken_auftraege ADD COLUMN IF NOT EXISTS schritte jsonb;

-- Grenzen auch in der DB: 20 000 Zeichen + Kuerzungsvermerk, 60 Schritte, je 200 Zeichen Text.
CREATE OR REPLACE FUNCTION marketing._spur_pruefen(p_denken text, p_schritte jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE s jsonb;
BEGIN
  IF p_denken IS NOT NULL AND char_length(p_denken) > 20100 THEN RAISE EXCEPTION 'Denken zu lang'; END IF;
  IF p_schritte IS NULL OR jsonb_typeof(p_schritte) <> 'array' THEN
    RAISE EXCEPTION 'Schritte muessen eine Liste sein'; END IF;
  IF jsonb_array_length(p_schritte) > 60 THEN RAISE EXCEPTION 'Hoechstens 60 Schritte'; END IF;
  FOR s IN SELECT * FROM jsonb_array_elements(p_schritte) LOOP
    IF jsonb_typeof(s) <> 'object'
       OR jsonb_typeof(s->'zeit') IS DISTINCT FROM 'string' OR char_length(s->>'zeit') > 20
       OR jsonb_typeof(s->'text') IS DISTINCT FROM 'string' OR char_length(s->>'text') > 200 THEN
      RAISE EXCEPTION 'Schritt ungueltig'; END IF;
  END LOOP;
END $$;

-- Sperrt nur die Auftragszeile (eine einzige Sperre => keine Reihenfolge zu beachten).
-- geaendert_am bleibt unberuehrt (es ordnet Verlauf und letzte Uebernahme).
CREATE OR REPLACE FUNCTION marketing.pult_chat_denken(p_auftrag uuid, p_denken text, p_schritte jsonb)
RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE a marketing.chat_auftraege;
BEGIN
  PERFORM marketing._spur_pruefen(p_denken, p_schritte);
  SELECT * INTO a FROM marketing.chat_auftraege WHERE id = p_auftrag FOR UPDATE;
  IF NOT FOUND OR a.status <> 'in_arbeit' OR a.vergeben_bis IS NULL OR a.vergeben_bis <= now() THEN
    RETURN false; END IF;
  UPDATE marketing.chat_auftraege SET denken = p_denken, schritte = p_schritte WHERE id = a.id;
  RETURN true;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_marke_denken(p_auftrag uuid, p_denken text, p_schritte jsonb)
RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE a marketing.marken_auftraege;
BEGIN
  PERFORM marketing._spur_pruefen(p_denken, p_schritte);
  SELECT * INTO a FROM marketing.marken_auftraege WHERE id = p_auftrag FOR UPDATE;
  IF NOT FOUND OR a.status <> 'in_arbeit' OR a.vergeben_bis IS NULL OR a.vergeben_bis <= now() THEN
    RETURN false; END IF;
  UPDATE marketing.marken_auftraege SET denken = p_denken, schritte = p_schritte WHERE id = a.id;
  RETURN true;
END $$;

COMMIT;
```

- [ ] **Step 4: Probe grün, auch zweifach angewendet**

Run:

```
... migration_probe spaces/marketing/db/065_denken.sql spaces/marketing/db/065_denken.sql \
  spaces/marketing/db/verify_060.sql spaces/marketing/db/verify_061.sql spaces/marketing/db/verify_062.sql \
  spaces/marketing/db/verify_063.sql spaces/marketing/db/verify_064.sql spaces/marketing/db/verify_065.sql
```

Expected: `verify_060 ok` … `verify_065 ok`, `PROBE OK (zurueckgerollt)`.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/db/065_denken.sql spaces/marketing/db/verify_065.sql
git commit -m "feat(marketing): Migration 065 Denken und Schritte der Agenten-Auftraege"
```

---

### Task 3: Die Spur (Sammeln, Drosseln, Kürzen)

**Files:**
- Create: `spaces/marketing/claw/denkspur.py` (MOS)
- Test: `spaces/marketing/tests/test_denkspur.py`

**Interfaces:**
- Produces: `class Spur` mit
  - `__init__(self, senden: Callable[[str, list[dict]], bool], uhr=time.monotonic, jetzt=lambda: time.strftime("%H:%M:%S"), drossel_s: float = 2.0)`
  - `denken(text: str) -> None`
  - `schritt(text: str) -> None`
  - `korrektur() -> None`
  - `melden(immer: bool = False) -> None`
  - `ende() -> None`
  - Eigenschaften `denken_text: str`, `schritte: list[dict]`, `aus: bool`.
  - `senden` liefert `False` = Auftrag gehört uns nicht mehr (danach sendet die Spur nie wieder), `True` = weiter. Eine Ausnahme in `senden` wird geschluckt; der Stand bleibt offen für den nächsten Takt.
- Konstanten: `DENKEN_MAX = 20_000`, `SCHRITTE_MAX = 60`, `SCHRITT_MAX = 200`, `DROSSEL_S = 2.0`, `GEKUERZT = "… gekürzt\n"`, `KORREKTUR = "\n\n— Korrekturrunde —\n\n"`.

- [ ] **Step 1: Failing tests**

```python
from spaces.marketing.claw import denkspur


class Uhr:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _spur(gesendet, uhr=None, antwort=True):
    def senden(d, s):
        gesendet.append((d, [dict(x) for x in s]))
        return antwort
    return denkspur.Spur(senden, uhr=uhr or Uhr(), jetzt=lambda: "08:03:41")


def test_erstes_denken_geht_sofort_dann_gedrosselt():
    g, uhr = [], Uhr()
    sp = _spur(g, uhr)
    sp.denken("a")
    sp.denken("b")
    assert [d for d, _ in g] == ["a"]
    uhr.t = 2.0
    sp.denken("c")
    assert [d for d, _ in g] == ["a", "abc"]


def test_ende_sendet_immer_den_stand():
    g, uhr = [], Uhr()
    sp = _spur(g, uhr)
    sp.denken("a")
    sp.denken("b")
    sp.ende()
    assert g[-1][0] == "ab"


def test_schritte_mit_zeit_und_grenzen():
    g = []
    sp = _spur(g)
    for i in range(70):
        sp.schritt(f"s{i}" + "x" * 300)
    assert len(sp.schritte) == 60
    assert sp.schritte[0]["text"].startswith("s10")
    assert all(len(s["text"]) == 200 and s["zeit"] == "08:03:41" for s in sp.schritte)


def test_denken_kuerzt_vorn():
    g = []
    sp = _spur(g)
    sp.denken("A" * 15_000)
    sp.denken("B" * 15_000)
    t = sp.denken_text
    assert t.startswith(denkspur.GEKUERZT)
    assert len(t) <= denkspur.DENKEN_MAX
    assert t.endswith("B" * 15_000)


def test_sehr_viel_denken_bleibt_begrenzt_und_markiert():
    sp = _spur([])
    for _ in range(100):
        sp.denken("x" * 10_000)
    assert len(sp.denken_text) <= denkspur.DENKEN_MAX
    assert sp.denken_text.startswith(denkspur.GEKUERZT)


def test_korrektur_haengt_trennzeile_und_schritt_an():
    sp = _spur([])
    sp.denken("erst")
    sp.korrektur()
    sp.denken("dann")
    assert sp.denken_text == "erst" + denkspur.KORREKTUR + "dann"
    assert sp.schritte[-1]["text"] == "Korrekturrunde"


def test_senden_false_schaltet_ab():
    g, uhr = [], Uhr()
    sp = _spur(g, uhr, antwort=False)
    sp.denken("a")
    uhr.t = 10
    sp.denken("b")
    sp.ende()
    assert len(g) == 1 and sp.aus


def test_senden_fehler_bleibt_offen():
    aufrufe, uhr = [], Uhr()

    def senden(d, s):
        aufrufe.append(d)
        if len(aufrufe) == 1:
            raise OSError("weg")
        return True
    sp = denkspur.Spur(senden, uhr=uhr, jetzt=lambda: "08:00:00")
    sp.denken("a")            # wirft intern, wird geschluckt
    uhr.t = 2.0
    sp.melden()               # offen geblieben => sendet erneut
    assert aufrufe == ["a", "a"] and not sp.aus


def test_leeres_denken_ignoriert():
    g = []
    sp = _spur(g)
    sp.denken("")
    sp.denken(None)  # type: ignore[arg-type]
    assert g == []
```

- [ ] **Step 2: Laufen lassen, schlägt fehl**

Run: `...python.exe -m pytest spaces/marketing/tests/test_denkspur.py -q`
Expected: FAIL (`ModuleNotFoundError: denkspur`).

- [ ] **Step 3: Implementieren**

```python
"""Denk- und Schrittspur eines Agenten-Auftrags (Spec sales-claw 2026-10-09-agent-denken-sichtbar).

Sammelt Claudes zusammengefasstes Denken und kurze Arbeitsschritte und meldet beides gedrosselt
ueber `senden(denken, schritte) -> bool`. Sichtbarkeit darf einen Auftrag nie kippen: jeder Fehler
beim Senden wird geschluckt, der Stand bleibt fuer den naechsten Takt offen."""
from __future__ import annotations

import time
from collections.abc import Callable

DENKEN_MAX = 20_000
SCHRITTE_MAX = 60
SCHRITT_MAX = 200
DROSSEL_S = 2.0
GEKUERZT = "… gekürzt\n"
KORREKTUR = "\n\n— Korrekturrunde —\n\n"


class Spur:
    def __init__(self, senden: Callable[[str, list[dict]], bool], uhr: Callable[[], float] = time.monotonic,
                 jetzt: Callable[[], str] = lambda: time.strftime("%H:%M:%S"), drossel_s: float = DROSSEL_S):
        self._senden, self._uhr, self._jetzt, self._drossel = senden, uhr, jetzt, drossel_s
        self._denken = ""
        self._gekuerzt = False
        self.schritte: list[dict] = []
        self._gesendet_am: float | None = None
        self._offen = False
        self.aus = False

    @property
    def denken_text(self) -> str:
        if not self._gekuerzt and len(self._denken) <= DENKEN_MAX:
            return self._denken
        return GEKUERZT + self._denken[-(DENKEN_MAX - len(GEKUERZT)):]

    def _anhaengen(self, text: str) -> None:
        self._denken += text
        if len(self._denken) > 2 * DENKEN_MAX:      # Speicher begrenzen; denken_text kuerzt ohnehin
            self._denken = self._denken[-DENKEN_MAX:]
            self._gekuerzt = True

    def denken(self, text: str) -> None:
        if not isinstance(text, str) or not text:
            return
        self._anhaengen(text)
        self._offen = True
        self.melden()

    def schritt(self, text: str) -> None:
        self.schritte.append({"zeit": self._jetzt(), "text": str(text)[:SCHRITT_MAX]})
        del self.schritte[:-SCHRITTE_MAX]
        self._offen = True
        self.melden()

    def korrektur(self) -> None:
        self._anhaengen(KORREKTUR)
        self.schritt("Korrekturrunde")

    def melden(self, immer: bool = False) -> None:
        if self.aus or not (self._offen or immer):
            return
        jetzt = self._uhr()
        if not immer and self._gesendet_am is not None and jetzt - self._gesendet_am < self._drossel:
            return
        self._gesendet_am, self._offen = jetzt, False
        try:
            weiter = self._senden(self.denken_text, list(self.schritte))
        except Exception:  # noqa: BLE001 - Sichtbarkeit darf einen Auftrag nie kippen
            self._offen = True
            return
        if weiter is False:
            self.aus = True

    def ende(self) -> None:
        self.melden(immer=True)
```

- [ ] **Step 4: Tests grün**

Run: `...python.exe -m pytest spaces/marketing/tests/test_denkspur.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/claw/denkspur.py spaces/marketing/tests/test_denkspur.py
git commit -m "feat(marketing): Denkspur sammelt Denken und Schritte gedrosselt"
```

---

### Task 4: API — Arbeiter schreibt die Spur, Stand liefert sie

**Files:**
- Modify: `spaces/marketing/api/chat.py` (MOS):
  - Arbeiter-Routen, neben `arbeiter_zwischenstand` ca. Z. 714
  - `chat_stand` Z. 133-157
- Modify: `spaces/marketing/api/marke.py`:
  - `marke_stand` Z. 68-125
  - Arbeiter-Routen
- Test: `spaces/marketing/tests/test_chat_api.py`, `spaces/marketing/tests/test_marke_api.py`

**Interfaces:**
- Consumes: `marketing.pult_chat_denken`, `marketing.pult_marke_denken` (Task 2).
- Produces:
  - `POST /api/chat/arbeiter/{aid}/denken` und `POST /api/marke/arbeiter/{aid}/denken`, Header `X-Bild-Key`.
    - Body `{"denken": str, "schritte": [{"zeit": str, "text": str}]}`.
    - Antwort `{"ok": true}` oder 409 `{"detail": "Auftrag nicht mehr in Arbeit"}`, 422 bei Formfehler.
  - `chat.spur_pruefen(payload: dict) -> tuple[str, list[dict]]` (von marke.py importiert).
  - `GET /api/pult/inhalte/{iid}/chat`: jeder `verlauf`-Eintrag und `live` haben zusätzlich `denken: str` (leer statt NULL) und `schritte: list` (leer statt NULL).
  - `GET /api/pult/marke`:
    - jeder `auftraege`-Eintrag hat `denken`, `schritte`;
    - `letzte_uebernahme` hat `schritte`;
    - neues Feld `laufend`: `{"art": str, "denken": str, "schritte": list}` des Auftrags in `in_arbeit` (neuester) oder `null`.

- [ ] **Step 1: Failing tests**

Nutze die vorhandenen Test-Muster der beiden Dateien: wie dort `_schreiben` / `_lesen` gemockt oder per Fake-DB beantwortet und wie Header gesetzt werden. Neue Tests:

`test_chat_api.py`:

```python
def test_denken_route_schreibt_und_meldet_ok(client, db):              # Fixtures wie in der Datei
    db.antworten["pult_chat_denken"] = {"ok": True}
    r = client.post(f"/api/chat/arbeiter/{AID}/denken", headers=BILD,
                    json={"denken": "Let me think", "schritte": [{"zeit": "08:03:41", "text": "Frage an Claude"}]})
    assert r.status_code == 200 and r.json() == {"ok": True}
    sql = db.letztes("pult_chat_denken")
    assert "Let me think" in sql and "Frage an Claude" in sql


def test_denken_route_verloren_ist_409(client, db):
    db.antworten["pult_chat_denken"] = {"ok": False}
    r = client.post(f"/api/chat/arbeiter/{AID}/denken", headers=BILD, json={"denken": "", "schritte": []})
    assert r.status_code == 409


@pytest.mark.parametrize("body", [
    {"denken": 5, "schritte": []},
    {"denken": "x", "schritte": {}},
    {"denken": "x" * 20101, "schritte": []},
    {"denken": "x", "schritte": [{"zeit": "08:00:00", "text": "t" * 201}]},
    {"denken": "x", "schritte": [{"zeit": "08:00:00"}]},
    {"denken": "x", "schritte": [{"zeit": "08:00:00", "text": "s"}] * 61},
])
def test_denken_route_form_422(client, db, body):
    r = client.post(f"/api/chat/arbeiter/{AID}/denken", headers=BILD, json=body)
    assert r.status_code == 422


def test_denken_route_ohne_schluessel_401(client):
    r = client.post(f"/api/chat/arbeiter/{AID}/denken", json={"denken": "", "schritte": []})
    assert r.status_code in (401, 403)


def test_chat_stand_liefert_denken_und_schritte(client, db):
    # Verlaufszeile mit NULL-Spalten (alter Auftrag) und eine mit Inhalt; live mit Denken
    ...  # Muster der bestehenden chat_stand-Tests verwenden
    j = client.get(f"/api/pult/inhalte/{IID}/chat", headers=PULT).json()
    assert j["verlauf"][0]["denken"] == "" and j["verlauf"][0]["schritte"] == []
    assert j["verlauf"][1]["denken"] == "Let me think"
    assert j["live"]["denken"] == "laufend" and j["live"]["schritte"][0]["text"] == "Frage an Claude"
```

Der Test `test_chat_stand_liefert_denken_und_schritte` muss konkret ausgeschrieben werden, nach dem Muster des bestehenden Tests für `chat_stand` in der Datei. Kein `...` im Commit.

`test_marke_api.py`: dieselben vier Routen-Tests für `/api/marke/arbeiter/{aid}/denken` mit `pult_marke_denken`, dazu:

```python
def test_marke_stand_liefert_spur_und_laufend(client, db):
    # auftraege-Zeile mit denken/schritte, letzte_uebernahme mit schritte, ein in_arbeit-Auftrag
    j = client.get("/api/pult/marke?mandant=fin2gether", headers=PULT).json()
    assert j["auftraege"][0]["schritte"][0]["text"] == "Webseite gelesen (3 Seiten)"
    assert j["letzte_uebernahme"]["schritte"][0]["text"] == "Rowboat geschrieben"
    assert j["laufend"] == {"art": "chat", "denken": "Let me", "schritte": [{"zeit": "08:00:00", "text": "Frage an Claude"}]}


def test_marke_stand_ohne_laufenden_auftrag(client, db):
    j = client.get("/api/pult/marke?mandant=fin2gether", headers=PULT).json()
    assert j["laufend"] is None
```

Auch diese beiden konkret nach dem Muster des bestehenden `marke_stand`-Tests ausschreiben.

- [ ] **Step 2: Laufen lassen, schlägt fehl**

Run: `...python.exe -m pytest spaces/marketing/tests/test_chat_api.py spaces/marketing/tests/test_marke_api.py -q -k "denken or spur or laufend"`
Expected: FAIL (404 bzw. fehlende Felder).

- [ ] **Step 3: Implementieren**

`chat.py`, oben bei den Konstanten:

```python
SPUR_DENKEN_MAX = 20_100
SPUR_SCHRITTE_MAX = 60
SPUR_SCHRITT_MAX = 200
SPUR_KOERPER_MAX = 256 * 1024
```

```python
def spur_pruefen(payload: dict) -> tuple[str, list[dict]]:
    """Form von {denken, schritte} (Spec 2026-10-09); die DB prueft dieselben Grenzen noch einmal."""
    denken, schritte = payload.get("denken", ""), payload.get("schritte", [])
    if not isinstance(denken, str) or len(denken) > SPUR_DENKEN_MAX:
        raise HTTPException(422, f"denken muss Text mit hoechstens {SPUR_DENKEN_MAX} Zeichen sein")
    if not isinstance(schritte, list) or len(schritte) > SPUR_SCHRITTE_MAX:
        raise HTTPException(422, f"schritte muss eine Liste mit hoechstens {SPUR_SCHRITTE_MAX} Eintraegen sein")
    for s in schritte:
        if (not isinstance(s, dict) or set(s) != {"zeit", "text"} or not isinstance(s["zeit"], str)
                or len(s["zeit"]) > 20 or not isinstance(s["text"], str) or len(s["text"]) > SPUR_SCHRITT_MAX):
            raise HTTPException(422, "Schritt muss {zeit, text} mit hoechstens 200 Zeichen Text sein")
    return denken, schritte


@arbeiter_router.post("/{aid}/denken")
async def arbeiter_denken(aid: str, request: Request, x_bild_key: str | None = Header(None)):
    _bild_schluessel(x_bild_key)
    a = _auftrag_id(aid)
    denken, schritte = spur_pruefen(await _json_gekappt(request, SPUR_KOERPER_MAX))
    zeile = await run_in_threadpool(_schreiben, lambda:
        f"SELECT marketing.pult_chat_denken({lit(a)}::uuid, {lit(denken)}, "
        f"{lit(json.dumps(schritte, ensure_ascii=False))}::jsonb) AS ok")
    if not zeile.get("ok"):
        raise HTTPException(409, "Auftrag nicht mehr in Arbeit")
    return {"ok": True}
```

`chat_stand`: In die Verlaufs-SELECT nach `fassung_nachher, ` einfügen:

```
"coalesce(denken, '') AS denken, coalesce(schritte, '[]'::jsonb) AS schritte, "
```

In die Live-SELECT `"SELECT id, status, nachricht, schritt, schritt_nr, zwischenstand, stopp, coalesce(denken, '') AS denken, coalesce(schritte, '[]'::jsonb) AS schritte FROM ..."` und in `live = {...}` ergänzen: `"denken": z.get("denken") or "", "schritte": z.get("schritte") or []`.

`marke.py`: `spur_pruefen` und `SPUR_KOERPER_MAX` aus `chat` importieren, so wie `_medien_ausliefern` importiert ist. Die Route `arbeiter_denken` wie oben, aber mit `pult_marke_denken`. Den Header-Check und den Auftrags-id-Helfer nimmst du so, wie die übrigen Marke-Arbeiter-Routen sie verwenden.

`marke_stand`:
- `auftraege`-SELECT: nach `vorschlag, ` einfügen: `coalesce(denken, '') AS denken, coalesce(schritte, '[]'::jsonb) AS schritte, `.
- `letzte`-SELECT: `coalesce(schritte, '[]'::jsonb) AS schritte` ergänzen.
- Neu:

```python
    laufend = _lesen_einer(lambda:
        "SELECT art, coalesce(denken, '') AS denken, coalesce(schritte, '[]'::jsonb) AS schritte "
        f"FROM marketing.marken_auftraege WHERE mandant = {lit(m)} AND status = 'in_arbeit' "
        "ORDER BY geaendert_am DESC LIMIT 1")
```

Im Rückgabe-Dict dazu `"laufend": laufend or None`.

- [ ] **Step 4: Tests grün, ganze Dateien**

Run: `...python.exe -m pytest spaces/marketing/tests/test_chat_api.py spaces/marketing/tests/test_marke_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/api/chat.py spaces/marketing/api/marke.py spaces/marketing/tests/test_chat_api.py spaces/marketing/tests/test_marke_api.py
git commit -m "feat(marketing): Arbeiter schreibt Denkspur, Stand liefert Denken und Schritte"
```

---

### Task 5: Chat-Arbeiter — Denken anfordern, Editor-Spur

**Files:**
- Modify: `spaces/marketing/workers/chat_worker.py` (MOS):
  - `frage_strom` Z. 125-168
  - `ChatApi` Z. 50-105
  - `_Live` Z. 270-345
  - `_strom_lesen` Z. 346-368
  - `chat_bearbeiten` / `_bearbeiten` Z. 545-686
- Test: `spaces/marketing/tests/test_chat_worker.py`

**Interfaces:**
- Consumes:
  - `denkspur.Spur` (Task 3).
  - Arbeiter-Route `POST /api/chat/arbeiter/{aid}/denken` (Task 4).
  - Shim-Feld `delta.reasoning_content` (Task 1).
- Produces:
  - `frage_strom(system, nachrichten, url=LLM_URL, modell=MODELL, denken: Callable[[str], None] | None = None)`: Mit `denken` sendet es `"marketing_denken": true` und ruft `denken(text)` je `reasoning_content`.
  - `ChatApi.denken(aid, denken: str, schritte: list[dict]) -> dict`
  - `spur_senden(api, aid) -> Callable[[str, list[dict]], bool]`: `False` bei `ApiFehler` mit Code in `FREMD`; `True` sonst, auch bei Netzfehler (dann übersprungen).
  - `_strom_lesen(..., spur: denkspur.Spur | None = None)`.

Konvention: Jedes `fragen_strom` wird jetzt mit dem Schlüsselwort `denken=` aufgerufen. Passe die Fake-Funktionen in `test_chat_worker.py` und `test_marken_arbeiter.py` so an, dass sie `denken=None` annehmen. Nur die Signatur, das Verhalten der bestehenden Tests bleibt gleich.

- [ ] **Step 1: Failing tests**

```python
def _sse_zeilen(*deltas):
    import json as _j
    zeilen = [b"data: " + _j.dumps({"choices": [{"delta": d, "finish_reason": None}]}).encode() + b"\n\n"
              for d in deltas]
    zeilen.append(b"data: " + _j.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode() + b"\n\n")
    zeilen.append(b"data: [DONE]\n\n")
    return zeilen


def test_frage_strom_trennt_denken_und_inhalt(monkeypatch):
    gesendet = {}

    class Antwort:
        def __init__(self, zeilen): self.zeilen = zeilen
        def __iter__(self): return iter(self.zeilen)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(req, timeout):
        gesendet["body"] = json.loads(req.data)
        return Antwort(_sse_zeilen({"reasoning_content": "Let me"}, {"content": '{"a":'},
                                   {"reasoning_content": " think"}, {"content": "1}"}))
    monkeypatch.setattr(cw.urllib.request, "urlopen", urlopen)
    denken = []
    teile = list(cw.frage_strom("S", [{"role": "user", "content": "x"}], denken=denken.append))
    assert "".join(teile) == '{"a":1}'
    assert "".join(denken) == "Let me think"
    assert gesendet["body"]["marketing_denken"] is True


def test_frage_strom_ohne_denken_fordert_nichts_an(monkeypatch):
    # wie oben, aber ohne denken=: Body ohne marketing_denken, reasoning_content wird ignoriert
    ...


def test_editor_spur_schritte_und_ende(...):
    # chat_bearbeiten mit Fake-Strom, der denken("Let me think") aufruft und eine gueltige Antwort
    # mit einer Aenderung (schritt "Titel kuerzen") liefert; Fake-api zeichnet api.denken-Aufrufe auf.
    # Erwartet: letzter denken-Aufruf vor api.fertig enthaelt "Let me think" und die Schritte
    # ["Frage an Claude", "Titel kuerzen", "Fassung gespeichert"] in dieser Reihenfolge.
    ...


def test_korrekturrunde_in_spur(...):
    # erster Strom liefert unlesbare Antwort, zweiter gueltige: Schritte enthalten "Korrekturrunde",
    # Denken enthaelt "— Korrekturrunde —"
    ...


def test_schoenheitspruefung_als_schritt(...):
    # api.pruefen liefert beim ersten Versuch "knopf: #ffffff auf #f66c1e unter 3.0:1"
    # => Schritt "Schönheitsprüfung: knopf: ..." erscheint
    ...


def test_stopp_sendet_spur_vor_gestoppt(...):
    # Stopp waehrend des Stroms: api.denken wird vor api.gestoppt aufgerufen (Reihenfolge der Fake-Aufrufe)
    ...


def test_aufgeben_sendet_spur_vor_zurueck(...):
    # zweimal unlesbar: api.denken vor api.zurueck
    ...


def test_denken_route_weg_kippt_auftrag_nicht(...):
    # api.denken wirft OSError bei jedem Aufruf: Auftrag endet trotzdem mit api.fertig ("fertig")
    ...


def test_denken_409_schaltet_spur_ab(...):
    # api.denken wirft ApiFehler(409, ...) beim ersten Aufruf: danach kein weiterer denken-Aufruf
    ...
```

Die mit `...` markierten Tests schreibst du konkret aus, mit den Fake-Fixtures, die `test_chat_worker.py` für `chat_bearbeiten` schon hat (Fake-api mit Aufrufliste, Fake-`fragen_strom`). Im Commit bleibt kein `...`.

- [ ] **Step 2: Laufen lassen, schlägt fehl**

Run: `...python.exe -m pytest spaces/marketing/tests/test_chat_worker.py -q -k "denken or spur or korrektur or schoenheit or stopp_sendet or aufgeben_sendet"`
Expected: FAIL.

- [ ] **Step 3: Implementieren**

`frage_strom`: Parameter `denken=None`. Body bauen und, wenn `denken`, `koerper["marketing_denken"] = True` setzen. In der Schleife nach `wahl = ...`:

```python
                d = wahl.get("delta") or {}
                gedacht = d.get("reasoning_content")
                if denken is not None and isinstance(gedacht, str) and gedacht:
                    denken(gedacht)
                inhalt = d.get("content") or ""
```

Statt der bisherigen `inhalt`-Zeile. Der Rest bleibt.

`ChatApi`:

```python
    def denken(self, aid, denken: str, schritte: list[dict]) -> dict:
        return self._post(f"/{aid}/denken", {"denken": denken, "schritte": schritte})
```

Modulfunktion (nach `FREMD`):

```python
def spur_senden(api, aid):
    """Senden fuer die Denkspur: False = Auftrag gehoert uns nicht mehr; sonst True (auch bei Netzfehler:
    der naechste Takt versucht es erneut, der Auftrag laeuft weiter)."""
    def senden(denken: str, schritte: list[dict]) -> bool:
        try:
            api.denken(aid, denken, schritte)
        except ApiFehler as e:
            return e.code not in FREMD
        except (OSError, ValueError):
            return True
        return True
    return senden
```

`_Live.__init__` bekommt `spur=None` (als `self.spur`). In `aenderung` ganz am Ende, nach `self.offen = True`: `if self.spur is not None: self.spur.schritt(self.schritt)`.

`_strom_lesen(fragen_strom, nachrichten, live, halter, system=..., spur=None)`:

```python
    if spur is not None:
        spur.schritt("Frage an Claude")
    strom = iter(fragen_strom(system, nachrichten, denken=spur.denken if spur is not None else None))
```

`chat_bearbeiten`:
- `spur = denkspur.Spur(spur_senden(api, aid), uhr=uhr)` anlegen.
- `_Live(..., spur=spur)` und `spur` an `_bearbeiten` weiterreichen.
- `zurueckgeben` ruft zuerst `spur.ende()`.
- Im `except _Stopp`-Zweig steht `spur.ende()` vor `api.gestoppt(...)`.

`_bearbeiten`:
- `_strom_lesen(..., spur=spur)` aufrufen.
- Vor dem Korrekturversuch (`if versuch == 1:` Zweig, vor `continue`): `spur.korrektur()`.
- Nach `grund = api.pruefen(aid, bloecke)`: `if grund: spur.schritt(f"Schönheitsprüfung: {grund}")`.
- Unmittelbar vor `antwort_vm = api.fertig(...)`:

```python
        if bildauftraege:
            spur.schritt(f"Bilder beauftragt: {len(bildauftraege)}")
        if ergebnis.geaendert:
            spur.schritt("Fassung gespeichert")
        spur.ende()
```

`from spaces.marketing.claw import denkspur` zu den Importen.

- [ ] **Step 4: Tests grün (ganze Datei + Marken-Arbeiter wegen Fake-Signatur)**

Run: `...python.exe -m pytest spaces/marketing/tests/test_chat_worker.py spaces/marketing/tests/test_marken_arbeiter.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/workers/chat_worker.py spaces/marketing/tests/test_chat_worker.py spaces/marketing/tests/test_marken_arbeiter.py
git commit -m "feat(marketing): Editor-Agent fordert Denken an und fuehrt eine Spur"
```

---

### Task 6: Marken-Arbeiter — Spur für Chat und Übernahme

**Files:**
- Modify: `spaces/marketing/workers/marken_arbeiter.py` (MOS):
  - `_text_holen` Z. 76-115
  - `chat_bearbeiten` Z. 135-181
  - `uebernehmen` Z. 295-340
- Test: `spaces/marketing/tests/test_marken_arbeiter.py`

**Interfaces:**
- Consumes:
  - `cw.spur_senden(api, aid)`, `denkspur.Spur` (Tasks 3, 5).
  - `MarkenApi` erbt `ChatApi.denken`, `PFAD` = `/api/marke/arbeiter` → Route aus Task 4.
- Produces: Schrittsätze (wörtlich):
  - `Webseite gelesen (<n> Seiten)`
  - `Webseite nicht lesbar`
  - `Logo-Kandidaten: <n>`
  - `Frage an Claude`
  - `Antwort geprüft: <Grund>`
  - `Korrekturrunde`
  - `Vorschlag abgelegt`
  - `Antwort ohne Vorschlag`
  - `Rowboat geschrieben`
  - `Logo verkleinert`
  - `Spiegel aktualisiert`
  - `Spiegel abgelehnt: <Grund>`

- [ ] **Step 1: Failing tests**

Mit den Fakes aus `test_marken_arbeiter.py` (Fake-api mit Aufrufliste, Fake-`webseite_lesen`, Fake-`fragen_strom`, das jetzt `denken=None` annimmt und `denken("Thinking about colors")` aufruft, falls gesetzt):

```python
def test_marken_chat_spur(...):
    # Nachricht mit URL, Fund mit 3 seiten und 2 logos, gueltiger Vorschlag
    # => letzter denken-Aufruf vor api.vorschlag: denken enthaelt "Thinking about colors",
    #    Schritte == ["Webseite gelesen (3 Seiten)", "Logo-Kandidaten: 2", "Frage an Claude", "Vorschlag abgelegt"]


def test_marken_chat_webseite_nicht_lesbar(...):
    # Fund mit 0 seiten => erster Schritt "Webseite nicht lesbar"


def test_marken_chat_korrektur(...):
    # erste Antwort ungueltig (AntwortFehler "Kontrast zu schwach"), zweite gueltig
    # => Schritte enthalten "Antwort geprüft: Kontrast zu schwach" und "Korrekturrunde"


def test_aufgeben_sendet_spur(...):
    # zweimal ungueltig => api.denken vor api.zurueck


def test_uebernahme_spur(...):
    # gueltige Uebernahme mit Logo, Spiegel ok
    # => Schritte ["Rowboat geschrieben", "Logo verkleinert", "Spiegel aktualisiert"], denken == "",
    #    api.denken vor api.fertig


def test_uebernahme_spiegel_abgelehnt_spur(...):
    # _spiegeln liefert Fehlertext "Logo zu gross" => Schritt "Spiegel abgelehnt: Logo zu gross"
```

Jeden Test konkret nach den bestehenden Mustern der Datei ausschreiben.

- [ ] **Step 2: Laufen lassen, schlägt fehl**

Run: `...python.exe -m pytest spaces/marketing/tests/test_marken_arbeiter.py -q -k spur`
Expected: FAIL.

- [ ] **Step 3: Implementieren**

- `from spaces.marketing.claw import denkspur` importieren.
- `_text_holen(..., spur)`: neuer Parameter `spur`. Pro Versuch vor dem Strom `spur.schritt("Frage an Claude")`, dann `strom = iter(fragen_strom(marken_prompt.SYSTEM, nachrichten, denken=spur.denken))`.

`chat_bearbeiten`:

```python
    spur = denkspur.Spur(cw.spur_senden(api, aid), uhr=uhr)
    try:
        return _chat_mit_spur(api, auftrag, aid, spur, fragen_strom, webseite_lesen, logo_laden, wurzel,
                              uhr, schlafen, halten_takt_s)
    except (_Aufgeben, cw._Verloren):
        spur.ende()
        raise
```

`_chat_mit_spur` ist der bisherige Rumpf ab `mandant, name = _firma(auftrag)`, mit diesen Ergänzungen:
- Nach `fund = webseite_lesen(url) if url else None`:

```python
        if url:
            spur.schritt(f"Webseite gelesen ({len(fund.seiten)} Seiten)" if fund is not None and fund.seiten
                         else "Webseite nicht lesbar")
            if fund is not None and fund.logos:
                spur.schritt(f"Logo-Kandidaten: {len(fund.logos)}")
```

- `_text_holen(..., spur)` aufrufen.
- Im `except marken_prompt.AntwortFehler as e:` beim Versuch 1, vor dem Anhängen der Korrekturnachricht:

```python
            spur.schritt(f"Antwort geprüft: {e}")
            spur.korrektur()
```

- Vor `api.fertig(...)` (kein Vorschlag): `spur.schritt("Antwort ohne Vorschlag"); spur.ende()`.
- Vor `api.vorschlag(...)`: `spur.schritt("Vorschlag abgelegt"); spur.ende()`.

`uebernehmen`:
- Am Anfang `spur = denkspur.Spur(cw.spur_senden(api, aid))`.
- Den Rumpf in `try: ... except (_Aufgeben, cw._Verloren): spur.ende(); raise` fassen.
- Nach `markenprofil.schreiben(...)`: `spur.schritt("Rowboat geschrieben")`.
- Nach dem Spiegelaufruf: `gestalt = spiegel_gestalt(neu)` vorab in eine Variable ziehen und `if gestalt.get("logo"): spur.schritt("Logo verkleinert")`.
- Dann `spur.schritt(f"Spiegel abgelehnt: {fehler}" if fehler else "Spiegel aktualisiert")`.
- Vor `api.fertig(...)`: `spur.ende()`.

- [ ] **Step 4: Tests grün**

Run: `...python.exe -m pytest spaces/marketing/tests/test_marken_arbeiter.py spaces/marketing/tests/test_chat_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (MOS)**

```
git add spaces/marketing/workers/marken_arbeiter.py spaces/marketing/tests/test_marken_arbeiter.py
git commit -m "feat(marketing): Marken-Chat und Uebernahme fuehren eine Denkspur"
```

---

### Task 7: Seite „Marke“ zeigt Denken und Schritte

**Files:**
- Modify: `sales-mcp/ui_marke.py` (SC):
  - `chat_html` Z. 179-195
  - `letzte_html` Z. 164-177
  - `formular_html` bzw. die Statuszeile
- Modify: `sales-mcp/ui.py` (CSS-Block nahe Z. 1114 `.marke-chat`)
- Test: `sales-mcp/tests/test_marke_seite.py`

**Interfaces:**
- Consumes: `GET /api/pult/marke`-Felder `auftraege[].denken|schritte`, `letzte_uebernahme.schritte`, `laufend` (Task 4).
- Produces:
  - `spur_html(a: dict, offen: bool = False) -> str`: `""` ohne Schritte und ohne Denken, sonst `<details class="spur">`.
  - `laufend_html(d: dict) -> str`: Live-Block oder `""`.

- [ ] **Step 1: Failing tests**

Nach dem Muster der bestehenden Tests in `test_marke_seite.py` (Fake-Pult-Antwort für `GET /marke`, Seite abrufen, HTML prüfen):

```python
def test_runde_mit_spur_hat_details(...):
    # auftraege[0] fertig mit denken "Let me <think>" und schritte [{"zeit":"08:03:41","text":"Webseite gelesen (3 Seiten)"}]
    html = ...
    assert '<details class="spur">' in html
    assert "Gedanken &amp; Schritte" in html
    assert "Claudes Gedanken (zusammengefasst, englisch)" in html
    assert "Let me &lt;think&gt;" in html                     # escaped
    assert "08:03:41" in html and "Webseite gelesen (3 Seiten)" in html


def test_ohne_spur_kein_details(...):
    # auftraege[0] mit denken "" und schritte []
    assert "spur" not in html


def test_laufend_zeigt_live_ausschnitt(...):
    # laeuft True, laufend {"art":"chat","denken": "A"*1000 + "ENDE", "schritte":[{"zeit":"08:00:01","text":"Frage an Claude"}]}
    assert 'class="spur-live"' in html
    assert "Denkt nach …" in html
    assert "ENDE" in html and "A" * 700 not in html          # nur die letzten ~600 Zeichen
    assert "Frage an Claude" in html


def test_uebernahme_schritte_in_letzte(...):
    # letzte_uebernahme fertig, hinweise [], schritte [{"zeit":"08:02:13","text":"Rowboat geschrieben"}]
    assert "Rowboat geschrieben" in html
```

Jeden Test konkret nach den bestehenden Mustern ausschreiben.

- [ ] **Step 2: Laufen lassen, schlägt fehl**

Run: `cd sales-mcp && <venv-sales python> -m pytest tests/test_marke_seite.py -q -k "spur or laufend or uebernahme_schritte"`
Expected: FAIL.

- [ ] **Step 3: Implementieren**

In `routen(ui)` neben den anderen Helfern:

```python
    LIVE_ZEICHEN = 600
    LIVE_SCHRITTE = 8
    KENNUNG = "Claudes Gedanken (zusammengefasst, englisch)"

    def _schritte(schritte) -> list[dict]:
        return [s for s in (schritte or []) if isinstance(s, dict)
                and isinstance(s.get("zeit"), str) and isinstance(s.get("text"), str)]

    def _schritt_liste(schritte: list[dict]) -> str:
        return ('<ol class="spur-schritte">'
                + "".join(f'<li><span class="zeit">{e(s["zeit"])}</span> {e(s["text"])}</li>' for s in schritte)
                + "</ol>") if schritte else ""

    def spur_html(a: dict, offen: bool = False) -> str:
        schritte = _schritte(a.get("schritte"))
        denken = a.get("denken") if isinstance(a.get("denken"), str) else ""
        if not schritte and not denken.strip():
            return ""
        teile = [_schritt_liste(schritte)]
        if denken.strip():
            teile.append(f'<p class="meta">{e(KENNUNG)}</p><pre class="spur-denken">{e(denken)}</pre>')
        return (f'<details class="spur"{" open" if offen else ""}><summary>Gedanken &amp; Schritte</summary>'
                + "".join(teile) + "</details>")

    def laufend_html(d: dict) -> str:
        l = d.get("laufend")
        if not isinstance(l, dict):
            return ""
        schritte = _schritte(l.get("schritte"))[-LIVE_SCHRITTE:]
        denken = l.get("denken") if isinstance(l.get("denken"), str) else ""
        ausschnitt = ("…" + denken[-LIVE_ZEICHEN:]) if len(denken) > LIVE_ZEICHEN else denken
        if not schritte and not ausschnitt.strip():
            return '<div class="spur-live"><p class="meta">Denkt nach …</p></div>'
        return ('<div class="spur-live"><p class="meta">Denkt nach …</p>' + _schritt_liste(schritte)
                + (f'<p class="meta">{e(KENNUNG)}</p><pre class="spur-denken">{e(ausschnitt)}</pre>'
                   if ausschnitt.strip() else "") + "</div>")
```

- `chat_html`: Jede Runde bekommt `spur_html(a)` nach den Hinweisen angehängt. Läuft die Runde noch (`status` `offen` oder `in_arbeit`), gibt es stattdessen kein Aufklapp-Element, denn der Live-Block steht oben.
- `letzte_html`: In beiden Ausgabezweigen `spur_html(z)` anhängen. Gibt es nur Schritte und keine Hinweise und den Status `fertig`, liefere `'<p class="meta">Letzte Übernahme: ' + e(antwort) + "</p>" + spur_html(z)`.
- `laufend_html(d)` direkt unter der Statuszeile ausgeben, also dort, wo „Der Marken-Agent arbeitet gerade …“ bzw. „Wird übernommen …“ steht, und nur, wenn `d.get("laeuft") or d.get("uebernahme")`.

CSS in `ui.py` direkt nach `.chat-agent`:

```css
.spur { margin: .2rem 0 0 1.2rem; font-size: .85rem; }
.spur summary { cursor: pointer; color: var(--leise); }
.spur-schritte { margin: .3rem 0; padding-left: 1.2rem; }
.spur-schritte .zeit { color: var(--leise); font-variant-numeric: tabular-nums; }
.spur-denken { white-space: pre-wrap; font: inherit; font-size: .8rem; color: var(--leise); max-height: 18rem; overflow: auto; margin: .2rem 0; }
.spur-live { margin: .4rem 0 .8rem; padding: .4rem .6rem; border-left: 2px solid var(--linie); }
```

Prüfe in `ui.py`, ob die Variablen `--leise` und `--linie` existieren. Wenn nicht, nimm die Namen, die `.meta` bzw. `.chat-du` benutzen.

- [ ] **Step 4: Tests grün (ganze Datei)**

Run: `cd sales-mcp && <venv-sales python> -m pytest tests/test_marke_seite.py tests/test_marketing_pult.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (SC)**

```
git add sales-mcp/ui_marke.py sales-mcp/ui.py sales-mcp/tests/test_marke_seite.py
git commit -m "feat(ui): Marke zeigt Denken und Schritte des Agenten live und aufklappbar"
```

---

### Task 8: Editor zeigt Denken und Schritte

**Files:**
- Modify: `editor/src/chat.ts`:
  - Typen Z. 12-29
  - `eintragLesen` Z. 152-175
  - `liveLesen` Z. 177-186
- Create: `editor/src/App/Chat/Gedanken.tsx`
- Modify: `editor/src/App/Chat/ChatLeiste.tsx`:
  - `Eintrag` Z. 243-300
  - `Aktionen`-Typ Z. ~235-242
  - Aufbau der Aktionen Z. ~395-412
- Test: `editor/src/chat.spur.test.ts`, `editor/src/App/Chat/Gedanken.test.tsx`
- Build: `sales-mcp/static/editor` (gebautes Bundle, mit committen)

**Interfaces:**
- Consumes: `chat.json`-Felder `verlauf[].denken|schritte`, `live.denken|schritte` (Task 4, sales-ui reicht unverändert durch).
- Produces:
  - `export type SpurSchritt = { zeit: string; text: string }`.
  - `ChatEintrag.denken: string`, `ChatEintrag.schritte: SpurSchritt[]`.
  - `ChatLive.denken: string`, `ChatLive.schritte: SpurSchritt[]`.
  - `export function schritteLesen(v: unknown): SpurSchritt[]`
  - `export function denkAusschnitt(text: string, zeichen = 600): string`
  - `export function gedankenSichtbarLesen(): boolean`, `export function gedankenSichtbarSchreiben(an: boolean): void` (Schlüssel `vibemind.editor.gedanken`, Werte `'an'`/`'aus'`, Vorgabe sichtbar, jeder Zugriff in try/catch).
  - Komponenten `GedankenLive({ live, sichtbar, umschalten })` und `GedankenAufklapp({ denken, schritte })`.

- [ ] **Step 1: Failing tests**

`editor/src/chat.spur.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { denkAusschnitt, schritteLesen } from './chat';
import { gedankenSichtbarLesen, gedankenSichtbarSchreiben } from './App/Chat/Gedanken';

describe('schritteLesen', () => {
  it('nimmt nur {zeit, text} mit Strings, hoechstens 60', () => {
    const roh = [{ zeit: '08:00:01', text: 'a' }, { zeit: 1, text: 'b' }, 'x', { zeit: '08:00:02' },
      ...Array.from({ length: 70 }, (_, i) => ({ zeit: '08:00:03', text: `s${i}` }))];
    const s = schritteLesen(roh);
    expect(s.length).toBe(60);
    expect(s[0]).toEqual({ zeit: '08:00:01', text: 'a' });
  });
  it('liefert [] fuer Nicht-Listen', () => {
    expect(schritteLesen(null)).toEqual([]);
    expect(schritteLesen({})).toEqual([]);
  });
});

describe('denkAusschnitt', () => {
  it('kurz bleibt unveraendert', () => expect(denkAusschnitt('abc')).toBe('abc'));
  it('lang: Ende mit Auslassung', () => {
    const t = denkAusschnitt('A'.repeat(1000) + 'ENDE', 600);
    expect(t.startsWith('…')).toBe(true);
    expect(t.endsWith('ENDE')).toBe(true);
    expect(t.length).toBe(601);
  });
});

describe('gedankenSichtbar', () => {
  it('Vorgabe sichtbar, ueberlebt fehlenden localStorage', () => {
    const alt = globalThis.localStorage;
    // @ts-expect-error - Test ohne localStorage
    delete globalThis.localStorage;
    expect(gedankenSichtbarLesen()).toBe(true);
    expect(() => gedankenSichtbarSchreiben(false)).not.toThrow();
    if (alt) globalThis.localStorage = alt;
  });
});
```

`editor/src/App/Chat/Gedanken.test.tsx` (Render ohne DOM über `react-dom/server`):

```tsx
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { GedankenAufklapp, GedankenLive } from './Gedanken';

const live = { schritt: '', schritt_nr: 0, zwischenstand: null, stopp: null,
  denken: 'Let me think', schritte: [{ zeit: '08:03:41', text: 'Frage an Claude' }] };

describe('GedankenLive', () => {
  it('zeigt Denken und Schritte, wenn sichtbar', () => {
    const html = renderToStaticMarkup(<GedankenLive live={live} sichtbar umschalten={() => {}} />);
    expect(html).toContain('Denkt nach …');
    expect(html).toContain('Let me think');
    expect(html).toContain('Frage an Claude');
    expect(html).toContain('Gedanken ausblenden');
  });
  it('ausgeblendet: nur der Schalter', () => {
    const html = renderToStaticMarkup(<GedankenLive live={live} sichtbar={false} umschalten={() => {}} />);
    expect(html).toContain('Gedanken einblenden');
    expect(html).not.toContain('Let me think');
  });
  it('rendert nichts ohne Spur', () => {
    const leer = { ...live, denken: '', schritte: [] };
    expect(renderToStaticMarkup(<GedankenLive live={leer} sichtbar umschalten={() => {}} />)).toBe('');
  });
});

describe('GedankenAufklapp', () => {
  it('zugeklappt mit Titel, Kennung erst aufgeklappt', () => {
    const html = renderToStaticMarkup(<GedankenAufklapp denken="Let me think" schritte={live.schritte} />);
    expect(html).toContain('Gedanken &amp; Schritte');
    expect(html).not.toContain('Let me think');
  });
  it('rendert nichts ohne Spur', () => {
    expect(renderToStaticMarkup(<GedankenAufklapp denken="" schritte={[]} />)).toBe('');
  });
});
```

Prüfe, dass `vitest` diese `.tsx`-Tests mitnimmt (`Sperre.test.tsx` läuft schon) und dass `react-dom/server` verfügbar ist; es ist Teil von `react-dom`.

- [ ] **Step 2: Laufen lassen, schlägt fehl**

Run: `cd editor && npx vitest run src/chat.spur.test.ts src/App/Chat/Gedanken.test.tsx`
Expected: FAIL (Exporte fehlen).

- [ ] **Step 3: Implementieren**

`chat.ts`:

```ts
export type SpurSchritt = { zeit: string; text: string };

export function schritteLesen(v: unknown): SpurSchritt[] {
  if (!Array.isArray(v)) return [];
  const aus: SpurSchritt[] = [];
  for (const s of v) {
    if (istObjekt(s) && typeof s.zeit === 'string' && typeof s.text === 'string') aus.push({ zeit: s.zeit, text: s.text });
  }
  return aus.slice(0, 60);          // die DB liefert ohnehin hoechstens 60
}

export function denkAusschnitt(text: string, zeichen = 600): string {
  return text.length > zeichen ? '…' + text.slice(-zeichen) : text;
}
```

- `ChatEintrag` erweitern um `denken: string; schritte: SpurSchritt[]`.
- `ChatLive` erweitern um `denken: string; schritte: SpurSchritt[]`.
- In `eintragLesen` und `liveLesen` ergänzen: `denken: typeof v.denken === 'string' ? v.denken : '', schritte: schritteLesen(v.schritte)`.
- Alle Stellen, die `ChatEintrag` oder `ChatLive` als Literal bauen (Tests, Fixtures), mit `denken: ''`, `schritte: []` ergänzen, bis `npx tsc --noEmit` grün ist.

`App/Chat/Gedanken.tsx`:

```tsx
// Denken und Schritte des Agenten (Spec 2026-10-09-agent-denken-sichtbar): live unter der
// Fortschritts-Linie, danach pro Verlaufseintrag aufklappbar. Nur Betreiber-Oberflaeche.
import { useEffect, useRef, useState } from 'react';
import { Box, ButtonBase } from '@mui/material';

import { denkAusschnitt, type ChatLive, type SpurSchritt } from '../../chat';
import { FARBE } from '../../pultFarben';

const SCHLUESSEL = 'vibemind.editor.gedanken';
const KENNUNG = 'Claudes Gedanken (zusammengefasst, englisch)';

export function gedankenSichtbarLesen(): boolean {
  try {
    return globalThis.localStorage?.getItem(SCHLUESSEL) !== 'aus';
  } catch {
    return true;
  }
}

export function gedankenSichtbarSchreiben(an: boolean): void {
  try {
    globalThis.localStorage?.setItem(SCHLUESSEL, an ? 'an' : 'aus');
  } catch {
    /* privates Fenster o. ae.: dann eben nicht gemerkt */
  }
}

export function useGedankenSichtbar(): [boolean, () => void] {
  const [an, setAn] = useState(gedankenSichtbarLesen);
  return [an, () => setAn((alt) => { gedankenSichtbarSchreiben(!alt); return !alt; })];
}

function Schritte({ schritte }: { schritte: SpurSchritt[] }) {
  if (schritte.length === 0) return null;
  return (
    <Box component="ol" sx={{ m: 0, pl: 2.5, fontSize: 12, color: FARBE.gedaempft, lineHeight: 1.6 }}>
      {schritte.map((s, i) => (
        <li key={i}>
          <Box component="span" sx={{ fontVariantNumeric: 'tabular-nums', mr: 0.75 }}>{s.zeit}</Box>
          {s.text}
        </li>
      ))}
    </Box>
  );
}

function Denken({ text, mitlaufen }: { text: string; mitlaufen: boolean }) {
  const ref = useRef<HTMLPreElement | null>(null);
  useEffect(() => {
    if (mitlaufen && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [text, mitlaufen]);
  if (!text.trim()) return null;
  return (
    <>
      <Box sx={{ fontSize: 11, color: FARBE.gedaempft, mt: 0.5 }}>{KENNUNG}</Box>
      <Box component="pre" ref={ref} sx={{ m: 0, mt: 0.25, whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 11.5,
        lineHeight: 1.5, color: FARBE.gedaempft, maxHeight: mitlaufen ? 120 : 320, overflow: 'auto' }}>
        {text}
      </Box>
    </>
  );
}

export function GedankenLive({ live, sichtbar, umschalten }: { live: ChatLive; sichtbar: boolean; umschalten: () => void }) {
  if (!live.denken.trim() && live.schritte.length === 0) return null;
  return (
    <Box sx={{ ml: 1, pl: 1.25, borderLeft: `2px solid ${FARBE.linie}` }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, color: FARBE.gedaempft }}>
        <span>Denkt nach …</span>
        <ButtonBase onClick={umschalten} sx={{ fontSize: 11, color: FARBE.gedaempft, textDecoration: 'underline' }}>
          {sichtbar ? 'Gedanken ausblenden' : 'Gedanken einblenden'}
        </ButtonBase>
      </Box>
      {sichtbar && (
        <>
          <Schritte schritte={live.schritte.slice(-8)} />
          <Denken text={denkAusschnitt(live.denken, 1200)} mitlaufen />
        </>
      )}
    </Box>
  );
}

export function GedankenAufklapp({ denken, schritte }: { denken: string; schritte: SpurSchritt[] }) {
  const [offen, setOffen] = useState(false);
  if (!denken.trim() && schritte.length === 0) return null;
  return (
    <Box sx={{ mt: 0.75 }}>
      <ButtonBase onClick={() => setOffen((o) => !o)} sx={{ fontSize: 11, color: FARBE.gedaempft }}>
        {offen ? '▾' : '▸'} Gedanken &amp; Schritte
      </ButtonBase>
      {offen && (
        <Box sx={{ mt: 0.5 }}>
          <Schritte schritte={schritte} />
          <Denken text={denken} mitlaufen={false} />
        </Box>
      )}
    </Box>
  );
}
```

Prüfe in `pultFarben.ts`, ob `FARBE.linie` existiert. Sonst nimm die vorhandene Rahmenfarbe, die ChatLeiste für Trennlinien nutzt.

Hinweis: `Gedanken &amp; Schritte` im JSX wird als `&` gerendert, `renderToStaticMarkup` escaped es zu `&amp;`. Der Test erwartet `Gedanken &amp; Schritte`. Schreib im JSX `Gedanken & Schritte` und lass den Test so.

`ChatLeiste.tsx`:
- `Aktionen` um `live: ChatLive | null; gedankenSichtbar: boolean; gedankenUmschalten: () => void` erweitern.
- Beim Bau der Aktionen gilt:
  - `live: chat?.live ?? null` (der Ort, an dem `chat` gelesen wird).
  - `const [gedankenSichtbar, gedankenUmschalten] = useGedankenSichtbar();`
- In `Eintrag`, im `laeuftNoch(e)`-Zweig, wird der `LaufBlase` umschlossen:

```tsx
        <>
          <LaufBlase text={...wie bisher...} />
          {a.live && <GedankenLive live={a.live} sichtbar={a.gedankenSichtbar} umschalten={a.gedankenUmschalten} />}
        </>
```

- Im abgeschlossenen Zweig, in der `Blase` direkt nach dem Hinweis-`ul`: `<GedankenAufklapp denken={e.denken} schritte={e.schritte} />`.

- [ ] **Step 4: Tests, Typen, Build**

Run: `cd editor && npx vitest run && npx tsc --noEmit && npm run build`
Expected: alle Tests PASS, `tsc` ohne Fehler (`npx --prefix` zählt nicht), Build schreibt nach `sales-mcp/static/editor`.

Dann die Editor-Tests der sales-ui:

Run: `cd sales-mcp && <venv-sales python> -m pytest tests/test_editor_seite.py tests/test_editor_paket.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (SC)**

```
git add editor/src/chat.ts editor/src/chat.spur.test.ts editor/src/App/Chat/Gedanken.tsx editor/src/App/Chat/Gedanken.test.tsx editor/src/App/Chat/ChatLeiste.tsx sales-mcp/static/editor
```

Dazu jede Fixture- oder Testdatei, die für `denken`/`schritte` angepasst wurde, einzeln. Dann:

```
git commit -m "feat(editor): Denken und Schritte des Agenten live und aufklappbar"
```

---

### Task 9: Auslieferung und echter Lauf (Controller, nach Freigabe des Betreibers)

Nicht von einem Subagenten. Reihenfolge zwingend:

1. **Claims:** WORKBOARD (`Vibemind_V1/WORKBOARD.md`) und secondbrain (`00_Meta/002_Koordination_Live.md`) eintragen und sofort committen.
2. **Migration 065:** Probe `065` + `verify_060..065`, dann `065` echt anwenden. Danach `verify_065` noch einmal über `migration_probe`, denn verify braucht die Transaktion.
3. **Push:** MOS `master`, SC `feat/stufe-1-fundament`.
4. **VM:** `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'` muss mit „ALLE PRUEFUNGEN GRUEN“ und neuer Marketing-Seite enden.
5. **PC:**
   - Haupt-Checkout `spaces/marketing` per Hash-Vergleich und `git restore --source=<sha> --worktree -- spaces/marketing` synchronisieren.
   - Shim :8117 und Chat-Arbeiter :8134 neu starten: die Prozesse beenden, dann `marketing-dienste-starten.ps1`.
   - :8114 und ComfyUI nicht anfassen.
6. **Echter Lauf:**
   - Eine Marken-Runde fin2gether, z. B. „Mach den Ton-Abschnitt kürzer“. Während der Runde `GET /api/pult/marke` zweimal: `laufend.denken` wächst, `laufend.schritte` enthält „Frage an Claude“. Danach hat der Auftrag in `auftraege` nicht-leeres `denken`.
   - Eine Editor-Runde am Entwurf „Probe Mandant fin2gether“: während der Runde liefert `GET /api/pult/inhalte/{iid}/chat` in `live.denken` Text, danach steht er am Verlaufseintrag.
   - Ergebnis dem Betreiber zur Sichtprüfung im Browser melden, für Seite „Marke“ und Editor.
7. **Claims schließen**, Memory-Eintrag „Marketing-API auch auf der VM“ um 065 ergänzen.
