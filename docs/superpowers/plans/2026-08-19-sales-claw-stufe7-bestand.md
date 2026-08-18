# sales-claw Stufe 7 — Bestandspflege Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bestandskunden-Pflege als Konstruktion: Verträge mit automatischen
Ablauf-Wiedervorlagen, ein Wochen-KPI-Bericht und eine strukturierte
Beraterin-Übergabe — alles ohne DDL, ohne neue Egress-Pfade, durch die
bestehenden Muster (jsonb-Enrichment, activities append-only, /reports).

**Architecture:** Drei unabhängige Werkzeug-Gruppen in `sales-mcp/server.py`,
je eine eigene Testdatei. Verträge leben in `leads.enrichment.vertraege`
(jsonb-Array, ein `jsonb_set` mit coalesce-Append reicht — der Pfad ist
einstufig, anders als beim zweistufigen `{profil,feld}`-Fall). Wiedervorlagen
entstehen über das bestehende Ereignis/Gegen-Ereignis-Muster
(`activities` type `wiedervorlage` / `wiedervorlage_erledigt`). Die Übergabe
schreibt über `recherche.report_schreiben` (Pfad-Härtung wiederverwenden)
nach `/reports`.

**Tech Stack:** Python 3.12 im Container `sales-mcp` (psycopg 3, mcp 2.0),
PostgreSQL 17 (VM-Supabase, Schemata `sales`/`sales_test`), pytest im
Container.

**Spec:** Auftrag des Betreibers 2026-08-19 („plan für alles") auf Basis der
Bewertung in der Session: (1) Verträge + Auto-Wiedervorlagen sind der größte
fehlende CRM-Baustein (Bestandsgeschäft lebt von Ablaufdaten), (2) Wochen-KPI
für die Strukturvertriebs-Steuerung, (3) Übergabe schließt die
§34d-Kette Assistent → Beraterin. Kein separates Spec-Dokument; dieses
Kapitel ist die Spezifikation.

## Global Constraints

- `.env` NIEMALS lesen oder anzeigen; Werte nur maschinell in Prozesse.
- `docker compose config` VERBOTEN (inlined Secrets). `--remove-orphans` VERBOTEN (räumt openwa samt WhatsApp-Session ab).
- Token/DSN nie in argv, nie im Output. DB-Arbeit: `docker exec sales-mcp python -c "..."` mit `os.environ` IM Container.
- Kein DDL — `sales_app` kann es nicht, und 42501 ist Absicht.
- Tests NUR gegen `sales_test`: Kopfzeilen-Muster aus `tests/test_recherche.py` übernehmen (`os.environ["SALES_DB_SCHEMA"] = "sales_test"` HART vor dem Import + `schema_wache`-Fixture mit assert).
- Jede Werkzeugfunktion hinter `@_gesichert` — der Dekorator nutzt `functools.wraps`; ohne wraps sind die MCP-Schemas leer (Task-4-Vorfall).
- Git-Bash-Falle: vor Container-Pfaden `export MSYS_NO_PATHCONV=1`, sonst wird `/app/tests` zu einem Windows-Pfad.
- Deploy immer: `docker compose build sales-mcp && docker compose up -d sales-mcp sales-dispatch sales-inbox` (openwa/sales-claw nicht anfassen).
- AGENTS.md-Änderungen deployen: `docker compose cp config/workspace/AGENTS.md sales-claw:/home/node/.openclaw/workspace/AGENTS.md`, MD5 BEIDSEITIG vergleichen.
- Conventional Commits, ein Commit je Task, NICHT pushen (macht der Koordinator).
- **Basis-Vorbehalt:** Parallel läuft `firma_anreichern` (macht 22 Werkzeuge). VOR Task 1: `git log --oneline -3` prüfen und die Werkzeug-Zähler-Tests (`test_werkzeuge.py`, `test_recherche.py`) RELATIV erhöhen, nicht absolut raten. Nach Stufe 7: Basis + 4 (vertrag_speichern, vertraege_ablaufend, wochenbericht, uebergabe_erstellen).

---

### Task 1: Verträge + automatische Ablauf-Wiedervorlage

**Files:**
- Modify: `sales-mcp/server.py` (neue Werkzeuge nach `wiedervorlage_erledigt`, ~Zeile 275; `profil_lesen` ~Zeile 276; `WERKZEUGE`-Tupel am Dateiende)
- Test: `sales-mcp/tests/test_vertraege.py` (neu)
- Modify: `config/workspace/AGENTS.md` (Abschnitt „Bedarfsanalyse" ergänzen)

**Interfaces:**
- Consumes: `_q`, `_json`, `_gesichert`, `date`/`datetime` (bereits importiert), Wiedervorlage-Insert-Muster aus `wiedervorlage_setzen` (server.py:248-251: `activities(lead_id, type='wiedervorlage', payload={"faellig_am": ..., "notiz": ...})`).
- Produces: `vertrag_speichern(lead_id: str, sparte: str, ablauf: str = "", gesellschaft: str = "", notiz: str = "") -> str` (JSON: `{"vertrag": {...}, "wiedervorlage": {"faellig_am": ...}|null}`); `vertraege_ablaufend(tage: int = 90) -> str` (JSON: `{"anzahl": n, "vertraege": [{"lead_id","name","sparte","ablauf"}]}`). `profil_lesen` liefert zusätzlich `"vertraege": [...]`.

- [ ] **Step 1: Failing Tests schreiben** — `sales-mcp/tests/test_vertraege.py`:

```python
"""Vertragstests fuer Vertraege + Ablauf-Wiedervorlagen gegen sales_test.

Ein Vertrag ist eine vom Kunden GENANNTE Tatsache (Dokumentation, keine
Beratung — §34d bleibt unberuehrt). Er liegt in leads.enrichment.vertraege
(jsonb-Array); mit Ablaufdatum entsteht automatisch eine Wiedervorlage
90 Tage vorher ueber das bestehende Ereignis-Muster.
"""
import json
import os
from datetime import date, timedelta

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")


def _lead():
    return server._q(
        "insert into leads (name, phone, source) values "
        "('Max Bestand', '+491701234567', 'whatsapp') returning id")[0]["id"]


def test_vertrag_landet_im_enrichment_array(  ):
    lead = _lead()
    ablauf = (date.today() + timedelta(days=200)).isoformat()
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", ablauf=ablauf,
        gesellschaft="Beispiel AG", notiz="vom Kunden genannt"))
    assert antwort["vertrag"]["sparte"] == "BU"
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]["enrichment"]
    assert len(e["vertraege"]) == 1
    assert e["vertraege"][0]["ablauf"] == ablauf
    # Zweiter Vertrag haengt sich AN, ueberschreibt nicht.
    json.loads(server.vertrag_speichern(lead_id=str(lead), sparte="Haftpflicht"))
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]["enrichment"]
    assert [v["sparte"] for v in e["vertraege"]] == ["BU", "Haftpflicht"]


def test_ablauf_erzeugt_wiedervorlage_90_tage_vorher():
    lead = _lead()
    ablauf = date.today() + timedelta(days=200)
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", ablauf=ablauf.isoformat()))
    erwartet = (ablauf - timedelta(days=90)).isoformat()
    assert antwort["wiedervorlage"]["faellig_am"] == erwartet
    wv = server._q("select payload from activities where type='wiedervorlage'")
    assert len(wv) == 1 and wv[0]["payload"]["faellig_am"] == erwartet
    assert "BU" in wv[0]["payload"]["notiz"]


def test_naher_ablauf_wird_nicht_in_die_vergangenheit_gelegt():
    lead = _lead()
    ablauf = date.today() + timedelta(days=10)   # 90 Tage vorher waere vorbei
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="KFZ", ablauf=ablauf.isoformat()))
    assert antwort["wiedervorlage"]["faellig_am"] == date.today().isoformat()


def test_ohne_ablauf_keine_wiedervorlage_und_vergangenheit_nur_hinweis():
    lead = _lead()
    antwort = json.loads(server.vertrag_speichern(lead_id=str(lead), sparte="Hausrat"))
    assert antwort["wiedervorlage"] is None
    alt = (date.today() - timedelta(days=5)).isoformat()
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="Reise", ablauf=alt))
    assert antwort["wiedervorlage"] is None
    assert "Vergangenheit" in antwort["hinweis"]
    assert server._q("select count(*) as n from activities "
                     "where type='wiedervorlage'")[0]["n"] == 0


def test_kaputtes_datum_und_leere_sparte_ergeben_fehler():
    lead = _lead()
    assert "fehler" in json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", ablauf="31.12.2027"))
    assert "fehler" in json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="  "))
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]["enrichment"]
    assert "vertraege" not in (e or {})


def test_profil_lesen_zeigt_vertraege():
    lead = _lead()
    server.vertrag_speichern(lead_id=str(lead), sparte="BU")
    profil = json.loads(server.profil_lesen(str(lead)))
    assert profil["vertraege"][0]["sparte"] == "BU"


def test_vertraege_ablaufend_filtert_fenster_und_sortiert():
    lead = _lead()
    for sparte, tage in (("BU", 30), ("Hausrat", 80), ("KFZ", 200)):
        server.vertrag_speichern(
            lead_id=str(lead), sparte=sparte,
            ablauf=(date.today() + timedelta(days=tage)).isoformat())
    antwort = json.loads(server.vertraege_ablaufend(tage=90))
    assert [v["sparte"] for v in antwort["vertraege"]] == ["BU", "Hausrat"]
    assert antwort["anzahl"] == 2


def test_signaturen_ueberleben_den_dekorator():
    import inspect
    assert list(inspect.signature(server.vertrag_speichern).parameters) == [
        "lead_id", "sparte", "ablauf", "gesellschaft", "notiz"]
    assert list(inspect.signature(server.vertraege_ablaufend).parameters) == ["tage"]
    assert server.vertrag_speichern in server.WERKZEUGE
    assert server.vertraege_ablaufend in server.WERKZEUGE
```

- [ ] **Step 2: Fehlschlag verifizieren.** Image bauen, Tests laufen lassen:
`export MSYS_NO_PATHCONV=1; docker compose build sales-mcp && docker compose up -d sales-mcp && docker exec sales-mcp python -m pytest /app/tests/test_vertraege.py -q` — Erwartet: FAIL (`vertrag_speichern` existiert nicht).

- [ ] **Step 3: Implementierung in `server.py`** (nach `wiedervorlage_erledigt`):

```python
WIEDERVORLAGE_VORLAUF_TAGE = 90


def _wiedervorlage_anlegen(lead_id, faellig: "date", notiz: str) -> str:
    """Interner Kern von wiedervorlage_setzen — auch vertrag_speichern legt
    darueber an, damit es genau EIN Insert-Muster gibt."""
    zeilen = _q(
        "insert into activities (lead_id, type, payload) values (%s, "
        "'wiedervorlage', %s) returning id",
        (lead_id, _json({"faellig_am": faellig.isoformat(), "notiz": notiz})))
    return str(zeilen[0]["id"])


@_gesichert
def vertrag_speichern(lead_id: str, sparte: str, ablauf: str = "",
                      gesellschaft: str = "", notiz: str = "") -> str:
    """Einen vom Kunden GENANNTEN Vertrag am Kontakt festhalten —
    Dokumentation, keine Beratung. Mit `ablauf` (ISO YYYY-MM-DD) entsteht
    automatisch eine Wiedervorlage 90 Tage vor Ablauf (nie in der
    Vergangenheit; liegt der Ablauf selbst zurueck, nur ein Hinweis) —
    der beste Terminanlass im Bestand entsteht damit von selbst."""
    if not (sparte or "").strip():
        return _json({"fehler": "Keine Sparte angegeben."})
    datum = None
    if (ablauf or "").strip():
        try:
            datum = date.fromisoformat(ablauf.strip())
        except ValueError:
            return _json({"fehler": f"Ungueltiges Datum '{ablauf}' — "
                                    f"erwartet ISO-Format YYYY-MM-DD."})
    vertrag = {k: v for k, v in {
        "sparte": sparte.strip(), "gesellschaft": gesellschaft.strip(),
        "ablauf": datum.isoformat() if datum else "",
        "notiz": notiz.strip(),
        "erfasst": datetime.now(timezone.utc).date().isoformat(),
    }.items() if v}
    zeilen = _q(
        "update leads set enrichment = jsonb_set(enrichment, '{vertraege}', "
        "coalesce(enrichment->'vertraege', '[]'::jsonb) || %s::jsonb, true) "
        "where id = %s returning id", (_json(vertrag), lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    heute = datetime.now(timezone.utc).date()
    wiedervorlage, hinweis = None, None
    if datum and datum < heute:
        hinweis = (f"Ablauf {datum.isoformat()} liegt in der Vergangenheit — "
                   f"keine Wiedervorlage angelegt.")
    elif datum:
        faellig = max(heute, datum - timedelta(days=WIEDERVORLAGE_VORLAUF_TAGE))
        wv_id = _wiedervorlage_anlegen(
            lead_id, faellig,
            f"Vertragsablauf {vertrag['sparte']} am {datum.isoformat()}")
        wiedervorlage = {"aktivitaets_id": wv_id,
                         "faellig_am": faellig.isoformat()}
    return _json(_ohne_none({"vertrag": vertrag,
                             "wiedervorlage": wiedervorlage,
                             "hinweis": hinweis}))


@_gesichert
def vertraege_ablaufend(tage: int = 90) -> str:
    """Welche Vertraege laufen in den naechsten `tage` Tagen ab? Quelle fuer
    proaktive Bestandsarbeit und den Wochenbericht."""
    try:
        fenster = max(1, min(int(tage), 365))
    except (TypeError, ValueError):
        fenster = 90
    zeilen = _q(
        "select l.id as lead_id, l.name, v->>'sparte' as sparte, "
        "       v->>'ablauf' as ablauf "
        "from leads l, jsonb_array_elements(l.enrichment->'vertraege') v "
        "where jsonb_typeof(l.enrichment->'vertraege') = 'array' "
        "  and v->>'ablauf' <> '' "
        "  and (v->>'ablauf')::date "
        "      between current_date and current_date + %s "
        "order by (v->>'ablauf')::date", (fenster,))
    return _json({"anzahl": len(zeilen), "fenster_tage": fenster,
                  "vertraege": zeilen})
```

Hinweise für den Umsetzer: `timedelta` zu den bestehenden `datetime`-Imports
ergänzen, falls es fehlt. `_ohne_none` existiert bereits (b2b_leads nutzt es);
fehlt es wider Erwarten, `{k: v for k, v in d.items() if v is not None}`
inline. Der einstufige `jsonb_set`-Pfad `{vertraege}` braucht KEIN
verschachteltes jsonb_set — das Elternobjekt ist die Wurzel (Kontrast zum
Kommentar bei `profil_aktualisieren`, server.py:296-303). In `wiedervorlage_setzen`
den Insert (Zeilen 248-251) durch einen Aufruf von `_wiedervorlage_anlegen`
ersetzen — Rueckgabeformat unveraendert lassen.

- [ ] **Step 4: `profil_lesen` erweitern** — in der Rueckgabe (server.py:285-289) ergaenzen: `"vertraege": e.get("vertraege", []),` nach der `"bedarf"`-Zeile.

- [ ] **Step 5: Beide Werkzeuge ins `WERKZEUGE`-Tupel** (hinter `wiedervorlage_erledigt`), Zaehler-Tests RELATIV +2 anpassen (Namen der Tests auf die neue Zahl umbenennen, `vertrag_speichern`/`vertraege_ablaufend` in die Namensliste aufnehmen).

- [ ] **Step 6: Bauen + Tests gruen:** `docker compose build sales-mcp && docker compose up -d sales-mcp sales-dispatch sales-inbox`, dann `docker exec sales-mcp python -m pytest /app/tests -q` — GESAMTE Suite, Erwartung: alles gruen.

- [ ] **Step 7: AGENTS.md** — im Abschnitt „Bedarfsanalyse" (nach den Leitfragen) ergaenzen:

```markdown
**Vertraege festhalten.** Nennt der Kunde einen bestehenden Vertrag
(Sparte, Gesellschaft, Ablaufdatum), speichere ihn mit
`vertrag_speichern` — das ist Dokumentation seiner Angaben, KEINE
Bewertung (du empfiehlst weiterhin nichts, siehe „Verbote"). Mit
Ablaufdatum entsteht automatisch eine Wiedervorlage 90 Tage vorher —
der natuerliche Anlass fuer das naechste Gespraech. `vertraege_ablaufend`
beantwortet „was laeuft demnaechst ab?".
```

Deploy per `docker compose cp` + MD5 beidseitig (Global Constraints).

- [ ] **Step 8: Commit:** `git add sales-mcp/server.py sales-mcp/tests/test_vertraege.py sales-mcp/tests/test_werkzeuge.py sales-mcp/tests/test_recherche.py config/workspace/AGENTS.md && git commit -m "feat(bestand): Vertraege mit automatischer Ablauf-Wiedervorlage"`

### Task 2: Wochenbericht (KPI)

**Files:**
- Modify: `sales-mcp/server.py` (neues Werkzeug nach `digest`; `WERKZEUGE`)
- Test: `sales-mcp/tests/test_wochenbericht.py` (neu)
- Modify: `docs/03_RUNBOOK.md` (Cron-Anleitung, optional aktivierbar)

**Interfaces:**
- Consumes: `_q`, `_json`, `_gesichert`; `vertraege_ablaufend` aus Task 1 (JSON-String, mit `json.loads` weiterverwenden); Ereignistypen: `bedarf`, `kundenantwort`, `wiedervorlage`, `wiedervorlage_erledigt`, `recherche` (payload enthaelt `kosten_usd` bei Recherche-Laeufen); `drafts.sent_at`/`channel`.
- Produces: `wochenbericht() -> str` — JSON mit `zeitraum`, `neue_leads` (je source), `bedarf` (antworten, kontakte), `versand` (je Kanal), `wiedervorlagen` (neu, erledigt), `entwuerfe_offen_jetzt`, `recherche_kosten_usd`, `vertraege_ablaufend_30`, `text` (fertiger Mehrzeiler fuer den Chat).

- [ ] **Step 1: Failing Tests** — `sales-mcp/tests/test_wochenbericht.py` (Kopf wie Task 1: Schema hart, `schema_wache`, `leer`-Fixture):

```python
def test_wochenbericht_zaehlt_die_letzten_sieben_tage():
    lead = _lead()   # Helfer wie in test_vertraege.py
    server.aktivitaet_loggen(lead_id=str(lead), typ="bedarf",
                             inhalt="einkommen beantwortet")
    server._q("insert into drafts (lead_id, channel, recipient, body, status, "
              "sent_at) values (%s,'whatsapp','+491701234567','x','sent', now())",
              (lead,))
    b = json.loads(server.wochenbericht())
    assert b["neue_leads"] == {"whatsapp": 1}
    assert b["bedarf"]["antworten"] == 1
    assert b["versand"] == {"whatsapp": 1}
    assert "Wochenbericht" in b["text"]


def test_alte_ereignisse_zaehlen_nicht():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload, created_at) "
              "values (%s, 'bedarf', '{}', now() - interval '8 days')", (lead,))
    b = json.loads(server.wochenbericht())
    assert b["bedarf"]["antworten"] == 0


def test_wiedervorlagen_saldo_und_recherche_kosten():
    lead = _lead()
    server.wiedervorlage_setzen(lead_id=str(lead),
                                faellig_am=date.today().isoformat(), notiz="x")
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'recherche', %s)",
              (lead, json.dumps({"kosten_usd": 0.0402})))
    b = json.loads(server.wochenbericht())
    assert b["wiedervorlagen"] == {"neu": 1, "erledigt": 0}
    assert b["recherche_kosten_usd"] == 0.04
```

Hinweis: exakte Signatur von `aktivitaet_loggen` vor dem Schreiben aus
server.py:~220 ablesen (Parametername `typ`/`inhalt` gegenpruefen) und den
Test daran ausrichten — NICHT raten.

- [ ] **Step 2: Fehlschlag verifizieren** (Build + gezielter pytest-Lauf wie Task 1 Step 2). Erwartet: FAIL (`wochenbericht` nicht definiert).

- [ ] **Step 3: Implementierung** (nach `digest`):

```python
@_gesichert
def wochenbericht() -> str:
    """Die Steuerungszahlen der letzten 7 Tage — freitags lesen (oder per
    Cron bekommen): was kam rein, was ging raus, was blieb liegen. Nur
    Lesezugriffe, versendet nichts."""
    seit = "now() - interval '7 days'"
    neue = _q(f"select coalesce(source,'unbekannt') as s, count(*) as n "
              f"from leads where created_at >= {seit} group by s")
    bedarf = _q(f"select count(*) as antworten, "
                f"count(distinct lead_id) as kontakte "
                f"from activities where type='bedarf' and created_at >= {seit}")
    versand = _q(f"select channel, count(*) as n from drafts "
                 f"where sent_at >= {seit} group by channel")
    wv = _q(f"select type, count(*) as n from activities "
            f"where type in ('wiedervorlage','wiedervorlage_erledigt') "
            f"and created_at >= {seit} group by type")
    offen = _q("select count(*) as n from drafts where status='pending'")
    kosten = _q(f"select coalesce(sum((payload->>'kosten_usd')::numeric),0) as k "
                f"from activities where type='recherche' "
                f"and payload ? 'kosten_usd' and created_at >= {seit}")
    ablaufend = json.loads(vertraege_ablaufend(tage=30))
    wv_map = {z["type"]: z["n"] for z in wv}
    daten = {
        "zeitraum": "letzte 7 Tage",
        "neue_leads": {z["s"]: z["n"] for z in neue},
        "bedarf": dict(bedarf[0]),
        "versand": {z["channel"]: z["n"] for z in versand},
        "wiedervorlagen": {"neu": wv_map.get("wiedervorlage", 0),
                           "erledigt": wv_map.get("wiedervorlage_erledigt", 0)},
        "entwuerfe_offen_jetzt": offen[0]["n"],
        "recherche_kosten_usd": round(float(kosten[0]["k"]), 2),
        "vertraege_ablaufend_30": ablaufend["anzahl"],
    }
    zeilen = [f"Wochenbericht ({daten['zeitraum']}):",
              f"- Neue Kontakte: "
              f"{sum(daten['neue_leads'].values())} ({daten['neue_leads']})",
              f"- Bedarfsantworten: {daten['bedarf']['antworten']} "
              f"von {daten['bedarf']['kontakte']} Kontakten",
              f"- Versendet: {daten['versand'] or 'nichts'}",
              f"- Wiedervorlagen: {daten['wiedervorlagen']['neu']} neu, "
              f"{daten['wiedervorlagen']['erledigt']} erledigt",
              f"- Offene Entwuerfe jetzt: {daten['entwuerfe_offen_jetzt']}",
              f"- Recherche-Kosten: ${daten['recherche_kosten_usd']}",
              f"- Vertraege mit Ablauf in 30 Tagen: "
              f"{daten['vertraege_ablaufend_30']}"]
    return _json({**daten, "text": "\n".join(zeilen)})
```

(Die `seit`-Interpolation ist ein konstanter String, kein Nutzereingang —
trotzdem Kommentar dranschreiben, warum das hier kein Injection-Risiko ist.)

- [ ] **Step 4: Registrieren + Zaehler +1**, Build, GESAMTE Suite gruen (wie Task 1 Step 6).

- [ ] **Step 5: Runbook-Abschnitt** in `docs/03_RUNBOOK.md` — Cron OPTIONAL dokumentieren, nicht anlegen (der Betreiber entscheidet): Vorlage ist der bestehende Morgen-Digest-Cron (docs/03, Abschnitt „Morgen-Digest" — gleiche `openclaw cron add`-Mechanik, Prompt „Ruf wochenbericht auf und liefere NUR dessen text-Feld", Freitag 16:00 `0 16 * * 5`, Zeitzone Europe/Berlin, gleiches `--to` wie der Digest-Cron).

- [ ] **Step 6: Commit:** `git add sales-mcp/server.py sales-mcp/tests/test_wochenbericht.py sales-mcp/tests/test_werkzeuge.py sales-mcp/tests/test_recherche.py docs/03_RUNBOOK.md && git commit -m "feat(bestand): Wochenbericht — Steuerungszahlen der letzten 7 Tage"`

### Task 3: Beraterin-Übergabe

**Files:**
- Modify: `sales-mcp/server.py` (neues Werkzeug nach `wochenbericht`; `WERKZEUGE`)
- Test: `sales-mcp/tests/test_uebergabe.py` (neu)
- Modify: `config/workspace/AGENTS.md` (Verbote-Abschnitt: Verweis ergaenzen)

**Interfaces:**
- Consumes: `profil_lesen`-Datenquellen (gleiche Queries), `recherche.slug(*teile) -> str` und `recherche.report_schreiben(dateiname, inhalt) -> (pfad, ueberschrieben)` (recherche.py:197/223 — Pfad-Haertung inklusive), Ereignistyp `offener_punkt`.
- Produces: `uebergabe_erstellen(lead_id: str) -> str` — JSON mit `pfad`, `text` (vollstaendiges Markdown), `offene_punkte_anzahl`.

- [ ] **Step 1: Failing Tests** — `sales-mcp/tests/test_uebergabe.py` (Kopf wie Task 1; zusaetzlich `monkeypatch.setattr(recherche, "REPORT_VERZEICHNIS", str(tmp_path))` in einer autouse-Fixture, Muster test_recherche.py:99):

```python
def test_uebergabe_sammelt_profil_bedarf_und_offene_punkte(tmp_path):
    lead = _lead()
    server.profil_aktualisieren(str(lead), "beruf", "Schreinermeister")
    server.bedarf_speichern(str(lead), "einkommen", "3800 netto")
    server.aktivitaet_loggen(lead_id=str(lead), typ="offener_punkt",
                             inhalt="Frage nach BU-Nachversicherung")
    antwort = json.loads(server.uebergabe_erstellen(str(lead)))
    assert antwort["offene_punkte_anzahl"] == 1
    text = antwort["text"]
    for erwartet in ("Max Bestand", "Schreinermeister", "3800 netto",
                     "BU-Nachversicherung", "Consent"):
        assert erwartet in text
    inhalt = open(antwort["pfad"].replace("/reports", str(tmp_path)),
                  encoding="utf-8").read()
    assert inhalt == text


def test_uebergabe_wird_protokolliert_und_unbekannter_lead_faellt_sauber():
    lead = _lead()
    server.uebergabe_erstellen(str(lead))
    assert server._q("select count(*) as n from activities "
                     "where type='uebergabe'")[0]["n"] == 1
    assert "fehler" in json.loads(server.uebergabe_erstellen(
        "00000000-0000-0000-0000-000000000000"))
```

Hinweis: exakte Signaturen von `profil_aktualisieren`, `bedarf_speichern`,
`aktivitaet_loggen` vor dem Schreiben im Code ablesen und die Testaufrufe
daran ausrichten (Parameternamen variieren, z. B. `frage_id` bei
`bedarf_speichern`).

- [ ] **Step 2: Fehlschlag verifizieren** (Build + gezielter Lauf). Erwartet: FAIL.

- [ ] **Step 3: Implementierung:**

```python
@_gesichert
def uebergabe_erstellen(lead_id: str) -> str:
    """Strukturierte Uebergabe eines Kontakts an die Beraterin — alles, was
    §34d-relevante Beratung braucht, aus dem Bestand: Profil, beantworteter
    Bedarf, Vertraege, offene Punkte, letzte Aktivitaeten. Schreibt die
    Markdown-Fassung nach /reports und gibt den Volltext zurueck. Versendet
    NICHTS — weitergeben tut sie der Betreiber."""
    leads = _q("select name, phone, consent_status, enrichment, notes "
               "from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    l, e = leads[0], leads[0]["enrichment"] or {}
    offene = _q("select payload, created_at from activities "
                "where lead_id = %s and type = 'offener_punkt' "
                "order by created_at", (lead_id,))
    letzte = _q("select type, payload, created_at from activities "
                "where lead_id = %s order by created_at desc limit 10",
                (lead_id,))
    heute = datetime.now(timezone.utc).date().isoformat()
    zeilen = [f"# Uebergabe: {l['name']}", "",
              f"Stand {heute} · Consent: {l['consent_status']} · "
              f"Telefon: {l['phone'] or '—'}", "", "## Profil"]
    zeilen += [f"- {k}: {v}" for k, v in (e.get("profil") or {}).items()] or ["- (leer)"]
    zeilen += ["", "## Bedarfsanalyse (Angaben des Kunden)"]
    zeilen += [f"- {k}: {v}" for k, v in (e.get("bedarf") or {}).items()] or ["- (leer)"]
    zeilen += ["", "## Vertraege (vom Kunden genannt)"]
    zeilen += [f"- {v.get('sparte','?')} ({v.get('gesellschaft','?')}), "
               f"Ablauf {v.get('ablauf','unbekannt')}"
               for v in (e.get("vertraege") or [])] or ["- (keine genannt)"]
    zeilen += ["", "## Offene Punkte fuer die Beratung"]
    zeilen += [f"- {p['payload'].get('inhalt', p['payload'])}" for p in offene] \
        or ["- (keine)"]
    zeilen += ["", "## Letzte Aktivitaeten"]
    zeilen += [f"- {a['created_at']:%Y-%m-%d} {a['type']}" for a in letzte]
    zeilen += ["", "---", "Erstellt vom Assistenten. KEINE Beratung, keine "
               "Produktbewertung — reine Zusammenstellung der Kundenangaben."]
    text = "\n".join(zeilen)
    name = f"uebergabe-{recherche.slug(l['name'])}-{heute}.md"
    pfad, _ueberschrieben = recherche.report_schreiben(name, text)
    _q("insert into activities (lead_id, type, payload) values "
       "(%s, 'uebergabe', %s) returning id",
       (lead_id, _json({"pfad": pfad, "offene_punkte": len(offene)})))
    return _json({"pfad": pfad, "text": text,
                  "offene_punkte_anzahl": len(offene)})
```

Umsetzer-Hinweis: `report_schreiben`-Rueckgabeform (Pfad, ueberschrieben)
und `offener_punkt`-Payload-Schluessel (`inhalt`?) VOR dem Verdrahten im
Code nachlesen (aktivitaet_loggen, server.py:~220) und Code/Tests exakt
daran ausrichten.

- [ ] **Step 4: Registrieren + Zaehler +1**, Build, GESAMTE Suite gruen.

- [ ] **Step 5: AGENTS.md** — im Verbote-Abschnitt beim Beraterin-Verweis ergaenzen: „Sammeln sich offene Punkte, biete `uebergabe_erstellen` an — die Zusammenstellung ist erlaubt, die Bewertung nicht." Deploy + MD5.

- [ ] **Step 6: Commit:** `git add sales-mcp/server.py sales-mcp/tests/test_uebergabe.py sales-mcp/tests/test_werkzeuge.py sales-mcp/tests/test_recherche.py config/workspace/AGENTS.md && git commit -m "feat(bestand): Beraterin-Uebergabe als strukturierter Report"`

### Task 4: Abschluss-Review (Pflicht)

- [ ] Scoped Review durch frischen Reviewer (Muster der Stufe-5/6-Reviews): Gate-Invariante (kein neuer Egress), §34d-Wortlaut in vertrag_speichern/uebergabe (Dokumentation vs. Bewertung), SQL-Injection-Blick auf die interval-Interpolation, jsonb-Kanten (Nicht-Array in vertraege), Zaehler-Konsistenz, Suite-Lauf. Befunde fixen, dann Push durch den Koordinator.

---

## Stufe 8+ — Vorentscheidungen (je eigener Plan NACH Messung)

Bewusst NICHT als Tasks ausgeplant — jede Zeile braucht erst eine Messung
oder eine Betreiber-Aktion; Kostenkontrolle und Messen-zuerst sind
Projektgesetz.

| Vorhaben | Erster Schritt (messen/klaeren) | Gate |
|---|---|---|
| **Kalender/Termine** | ICS-Datei-Erzeugung nach `/reports` (kein externer Dienst, pure Python) als Task vermessen: reicht Betreibern eine .ics zum Anklicken? | Kein Cloud-Kalender ohne Betreiber-Konto-Entscheidung |
| **E-Mail-Versand** | Schema kennt `channel='email'` schon. Messen: SMTP-Anbieter des Betreibers (GMX?), App-Passwort-Verfahren, Limits | Gleiche Gate-Konstruktion wie WhatsApp (Dispatcher-Zwilling), NIE ohne Freigabe |
| **LinkedIn-Posts-API** | BETREIBER-AKTION: LinkedIn-Developer-App anlegen (Scope `w_member_social`), OAuth-Redirect klaeren | Ohne App keine Automatisierung; Handversand bleibt Standard |
| **Proxmox-Multi-User** | docs/07-Overrides gegen aktuellen Stand pruefen; je Nutzer: eigene Nummer, eigener Container, eigenes Schema | Vom Betreiber geparkt — erst auf Zuruf |
| **Review-Backlog** | E1 (source-Wechsel fuer konvertierte Recherche-Leads), T2 (APIFY_TOKEN-Vererbung), D1/B3/D4, B5/B8/B9 | Sammel-Task „Politur", kein Feature |

---

## Self-Review (erledigt)

Spec-Abdeckung: alle drei Spec-Punkte haben Tasks (T1/T2/T3), Review ist T4,
Spaeteres ist ausdruecklich Vorentscheidung. Platzhalter: keine — wo eine
Signatur nicht aus diesem Plan stammt, steht der exakte Ablese-Ort im Code
plus die Anweisung, Tests daran auszurichten. Typkonsistenz:
`vertraege_ablaufend(tage=30)` in T2 nutzt die T1-Signatur; `recherche.slug`/
`report_schreiben` in T3 sind mit Zeilennummern belegt.
