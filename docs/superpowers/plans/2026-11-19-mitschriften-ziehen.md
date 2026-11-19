# Mitschriften per Ziehen verschieben – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mitschrift-Karten auf `/mitschriften` lassen sich auf einen Rubrik-Reiter ziehen; „Kurse“ ist immer ein Reiter.

**Architecture:** Server rendert ziehbare Karten, ein verstecktes Formular `#dnd-verschieben` und ein `<script src>`;
`static/mitschriften/ziehen.js` füllt das Formular beim Ablegen und schickt es an den unveränderten
`POST /mitschriften/verschieben`. Ziel-Rubrik liest das Skript aus dem `rubrik`-Parameter des Reiter-Links
(`ui_muster.reiter` bleibt unverändert; „Handbücher“ hat keinen `rubrik`-Parameter und ist damit kein Ziel).

**Tech Stack:** Python/Starlette (`sales-mcp/ui_mitschriften.py`), Vanilla-JS, pytest gegen `sales_test`.

**Spec:** `docs/superpowers/specs/2026-11-19-mitschriften-ziehen-design.md`

## Global Constraints

- Gleicher Weg wie das Formular: `POST /mitschriften/verschieben` mit `csrf`, `uid`, `rubrik` – Handler unverändert.
- Kein eingebettetes Skript; Skript als Datei über gesicherte Route `GET /mitschriften/ziehen.js`
  (`media_type="text/javascript"`, Kopfzeilen `cache-control: no-cache`, `X-Content-Type-Options: nosniff`, wie
  `ui_struktur.skript`). Seite mit Skript bekommt `Content-Security-Policy: ui_kalender.csp_kalender(ui)`.
- Nur-Lesen (`_schreiben()` falsch): keine `draggable`-Karten, kein `<script`, kein `#dnd-verschieben`.
- „Kurse“ = `kurs_mitschrift.RUBRIK_KURSE`, Vergleich mit `kurs_mitschrift.ist_kurs` (Groß/klein egal).
- Kein `console.log`; deutsche Texte mit Umlauten. Ohne Rückfrage verschieben (kein `confirm`).
- Tests nur per `bash .superpowers/sdd/2026-11-14-abnahme-befunde/vm_test.sh tests/test_ui_mitschriften.py`.

## Review Focus

1. Nur „Kundentermine“ vorhanden → Aufruf `/mitschriften` ohne `rubrik` zeigt Kundentermine, nicht den leeren „Kurse“.
2. Eine Rubrik heißt schon „kurse“ (klein) → kein zweiter Reiter „Kurse“.
3. Karte auf den eigenen Reiter oder auf „Handbücher“ ziehen → nichts passiert.
4. Rubrik mit Sonderzeichen/Leerzeichen im Reiter-Link → Skript liest den decodierten Namen.
5. `/mitschriften?rubrik=Kurse` bei 0 Kurs-Einträgen → 200 mit „Keine Mitschriften in dieser Rubrik.“

---

### Task 1: Ziehbare Karten, Kurse-Reiter, Skript

**Files:**
- Modify: `sales-mcp/ui_mitschriften.py` (`_reiter_sortiert`/`seite`/`_karte`/`routen`)
- Create: `sales-mcp/static/mitschriften/ziehen.js`
- Modify: `sales-mcp/ui.py:1650-1652` (CSS neben `.struktur-liste`-Regeln)
- Test: `sales-mcp/tests/test_ui_mitschriften.py`

**Interfaces:**
- Produces: Route `GET /mitschriften/ziehen.js`; Karte `<article class="karte" draggable="true" data-uid="…">` mit
  Griff `<span class="griff" aria-hidden="true">⠿</span>`; Formular
  `<form method="post" action="/mitschriften/verschieben" id="dnd-verschieben" hidden>` mit `csrf`, `uid`, `rubrik`.

- [ ] **Step 1: Failing tests** in `tests/test_ui_mitschriften.py`:

```python
def test_kurse_immer_als_reiter():
    _mit("c@x", titel="Kunde", rubrik="Kundentermine")
    t = _get("/mitschriften").text
    reiter = t[t.index('class="reiter"'):]
    reiter = reiter[:reiter.index("</nav>")]
    assert "?rubrik=Kurse" in reiter and '<span class="zahl">0</span>' in reiter
    assert "Kunde" in t.split("</nav>", 1)[1]          # Vorgabe bleibt erster nicht leerer Reiter
    k = _get("/mitschriften?rubrik=Kurse")
    assert k.status_code == 200 and "Keine Mitschriften in dieser Rubrik." in k.text

def test_kurse_klein_kein_doppelter_reiter():
    _mit("c@x", rubrik="kurse")
    t = _get("/mitschriften").text
    reiter = t[t.index('class="reiter"'):]
    reiter = reiter[:reiter.index("</nav>")]
    assert reiter.casefold().count("?rubrik=kurse") == 1

def test_ziehen_fuer_schreibende():
    _mit("a@x", rubrik="Kundentermine")
    r = _get("/mitschriften?rubrik=Kundentermine")
    t = r.text
    assert 'draggable="true"' in t and 'data-uid="a@x"' in t
    assert 'id="dnd-verschieben"' in t and f'name="csrf" value="{ui.CSRF_TOKEN}"' in t
    assert t.lower().count("<script") == 1
    assert '<script src="/mitschriften/ziehen.js" defer></script>' in t
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert "<details" in t and 'name="neue_rubrik"' in t      # Formular bleibt, eingeklappt
    s = _get("/mitschriften/ziehen.js")
    assert s.status_code == 200 and s.headers["content-type"].startswith("text/javascript")
    assert "dnd-verschieben" in s.text and "console.log" not in s.text

def test_ziehen_nicht_fuer_lesen(scharf):
    _mit("a@x", rubrik="Kundentermine")
    t = _get("/mitschriften?rubrik=Kundentermine", _anmelden("lena", "lesen")).text
    assert 'draggable="true"' not in t and "<script" not in t.lower() and "dnd-verschieben" not in t
```

- [ ] **Step 2: Run, expect FAIL** – `bash .superpowers/sdd/2026-11-14-abnahme-befunde/vm_test.sh tests/test_ui_mitschriften.py -k "kurse or ziehen"`

- [ ] **Step 3: Implement**
  - `_reiter_sortiert`: unverändert; in `seite` zu `zahlen` den Eintrag `RUBRIK_KURSE: 0` ergänzen, wenn es
    Mitschriften gibt und keine Rubrik `ist_kurs` ist (für `_leiste` dieselbe Ergänzung, z. B. Hilfsfunktion
    `_zahlen_mit_kursen() -> dict[str, int]`, die `seite` und `_leiste` nutzen). Ohne jede Mitschrift bleibt die
    Seite „Noch keine Mitschriften …“.
  - Vorgabe-Reiter: erster Name mit Zahl > 0; `?rubrik=` eines vorhandenen (auch leeren) Reiters wird angezeigt.
  - `_karte` bei `csrf`: `draggable="true" data-uid="{_e(uid)}"`, Griff-Span vor dem Titel, bestehendes
    Verschieben-Formular in `<details class="verschieben"><summary>Verschieben …</summary>…</details>`.
  - `seite` bei `_schreiben()`: verstecktes Formular `#dnd-verschieben` + `<script src="/mitschriften/ziehen.js" defer>`
    und CSP `ui_kalender.csp_kalender(ui)`.
  - Route `/mitschriften/ziehen.js` (gesichert, Muster `ui_struktur.skript`), Datei `static/mitschriften/ziehen.js`:
    Karten `article.karte[draggable="true"]` → `dragstart` merkt `data-uid`; Ziele `nav.reiter a`, deren `href`
    einen `rubrik`-Parameter hat (`new URL(a.href, location.href).searchParams.get("rubrik")`); `dragover`
    `preventDefault` + Klasse `ablage`; `drop` auf den aktiven Reiter (`aria-current="page"`) tut nichts, sonst
    Formular füllen und `submit()`.
  - CSS in `ui.py`: `.karte[draggable="true"] .griff { cursor: grab; }`, `.karte.wird-gezogen { opacity: .5; }`
    (`.ablage` gibt es schon).

- [ ] **Step 4: Run, expect PASS** – ganze Datei: `bash …/vm_test.sh tests/test_ui_mitschriften.py tests/test_ui_kurs.py`;
  Punkte 3 und 4 der Review Focus (nur Skript) prüft der Controller nach dem Ausrollen im Browser.
  dazu `node --check sales-mcp/static/mitschriften/ziehen.js`.

- [ ] **Step 5: Commit** – `feat(mitschriften): Karten per Ziehen auf Reiter verschieben, Kurse immer als Reiter`
