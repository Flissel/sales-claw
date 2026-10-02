# Newsletter-Gestaltungsfläche und Gestaltungs-Agent – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Framer-artige Gestaltungsfläche (Bilder + Text frei platzieren, serverseitig flachgerechnet) und ein Chat-Agent am PC, der den ganzen Newsletter bedient, plus bestätigter Export in die Medien.

**Architecture:** Eine Fläche ist ein `Image`-Block mit `props.gestaltung` (Ebenen als Daten); die marketing-api auf der VM rechnet sie mit Pillow zu `medien:gs-<hash12>.jpg`. Chat-Nachrichten laufen als Aufträge über die VM (`marketing.chat_auftraege`) zu einem Chat-Arbeiter am PC, der Claude über den Marketing-Shim :8117 fragt, die JSON-Änderungen prüft und anwendet; die VM speichert die Fassung (Urheber `agent`). Export der Flächen rechnet die VM; Newsletter-Bilder je Gerät rechnet der PC-Arbeiter mit Playwright.

**Tech Stack:** Python 3.11/3.12, FastAPI, Pillow, PostgreSQL (plpgsql), Playwright (nur PC), Starlette (sales-ui), React 18 + MUI 5 + zustand + zod, vitest, Vite.

**Spec:** `docs/superpowers/specs/2026-10-02-newsletter-gestaltung-und-agent-design.md` (sales-claw)

## Repos und Arbeitsorte

- **MOS** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent` (Branch `master`), Pfade unten relativ zu `spaces/marketing/`. NIE im Haupt-Checkout `C:\Users\User\Desktop\Vibemind_V1\vibemind-os` committen. Fremde Dirty-Dateien im Worktree (spaces/plugin-setup, spaces/sales-claw, spaces/shuttles, voice, docs/spaces) nicht anfassen.
- **SC** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw` (Branch `feat/stufe-1-fundament`). `.superpowers/` nie stagen.
- Vor jedem Commit: `git rev-parse --show-toplevel` + `git branch --show-current` prüfen. Git über PowerShell. Kein stash, kein push (Push nur in Task 15).
- MOS-Tests: `cd <MOS>; $env:SALES_CLAW_DIR="<SC>"; C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest spaces/marketing/<pfad> -q -p no:cacheprovider`. Bekannt unabhängig rot im Gesamtlauf: test_integrations, test_send_paranoid, test_hand_bridge (Docker/Reihenfolge), test_cockpit_contract (pinnt Migrationen 001–044).
- SC-Tests: Postgres `E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\pgdata` auf :55432 (mit bash `nohup pg_ctl … start` starten, nach Ende `stop -m immediate`), `SALES_DB_URL=postgresql://postgres@127.0.0.1:55432/postgres`, `SALES_DB_SCHEMA=sales_test` (nur dieses Schema ist erlaubt; nie zwei Läufe parallel), Python `…\scratchpad\venv-sales\Scripts\python.exe -m pytest tests/<datei> -q -p no:cacheprovider` aus `sales-mcp/`. Editor: `cd editor; npx vitest run; npx tsc --noEmit; npm run build` (Bundle `sales-mcp/static/editor/{editor.js,editor.css,MANIFEST.json}` immer mit-committen).
- Migrationen nur per `python -m spaces.marketing.scripts.migration_probe spaces/marketing/db/060_gestaltung_und_chat.sql spaces/marketing/db/verify_060.sql` (Transaktion + ROLLBACK) prüfen – nie anwenden (das macht Task 15 nach Freigabe).

## Global Constraints

- Kein Modell auf der VM. Pillow auf der VM ist erlaubt. Claude (Shim :8117) und Playwright nur am PC.
- Keine Secrets in argv/Logs/Commits. Arbeiter-Schlüssel = vorhandener `MARKETING_BILD_KEY` (Header `X-Bild-Key`), Basis = `MARKETING_BILD_URL`.
- Fläche = `Image`-Block mit `props.gestaltung` (kein neuer Blocktyp).
- Formate: `quer` 3:2, `quadrat` 1:1, `hoch` 4:5, `banner` 3:1. 600er-Einheit; gerechnet 1200 px breit (Faktor 2).
- Ebenen ≤ 20; Ebenen-id `^[A-Za-z0-9_-]{1,32}$`; Text ≤ 200 Zeichen, ≤ 6 Zeilen, Umbruch nur bei `\n`; `groesse` 10–160; `zeilenabstand` 0,8–2,0; `drehung` −180…180; Farbe `^#[0-9a-fA-F]{6}$`; `alt` Pflicht ≤ 200 Zeichen.
- Schriften: die 11 Vorlagenschrift-IDs (`cormorant, dm-sans, playfair, poppins, young-serif, manrope, bodoni, montserrat, josefin, oxanium, rajdhani`) nur in ihren vorhandenen Schnitten.
- Entwurfsbild: `gs-<hash12>.jpg` in `MARKETING_BILD_ORDNER`, JPEG Qualität 88, ≤ 1 MB (Qualität in 6er-Schritten bis 64, sonst Fehler). Unsichtbar in Medienbibliothek/Picker; Aufräumen: unverwiesen und > 7 Tage, höchstens einmal je Stunde.
- Hinweise (keine Fehler): Ebene > 15 % außerhalb; Text < 22 Einheiten → „am Handy unter 12 px“; Kontrast < 3:1.
- Chat: Nachricht ≤ 2000 Zeichen; ein offener/in-Arbeit-Auftrag je Inhalt; Handspeichern während Agent arbeitet ⇒ Ablehnung „Der Assistent arbeitet gerade“; Lease 5 min; nicht abgeholt in 2 min ⇒ „Der Assistent läuft am PC und ist gerade aus“; Shim-Wiederholung bis 3 min ⇒ „Der Assistent ist gerade nicht erreichbar“; ein Korrekturversuch bei ungültiger Antwort; Kontext = letzte 10 Chatnachrichten.
- Agent-Fassungen haben Urheber `agent`; Rückgängig legt die vorige Fassung als neue Fassung an (nichts wird gelöscht).
- Export nur nach Bestätigung im Editor; Agent darf nur `export_vorschlagen`. Newsletter: Handy 375, Tablet 768, PC 1200 px Breite, JPEG ≤ 4 MB. Flächen: Handy 4:5 (`hoch`), Tablet 1:1 (`quadrat`), PC 3:2 (`quer`). Namen `<titel-slug>-<gerät>.jpg` / `<titel-slug>-<flaeche>-<gerät>.jpg`, bei Kollision `-2`, `-3` …
- Chat-Arbeiter: `workers/chat_worker.py`, Gesundheitsport 8134, Start über `marketing-dienste-starten.ps1`.
- UI „schön von Anfang an“: dunkles Gerüst (Gerüst `#0f0f11`, Panel `#17171b`, Linie `#2a2a31`, Text `#ececf1`, gedämpft `#8d8d99`, Akzent `#5b8cff`), 8-px-Raster, UI-Schrift `system-ui`, Übergänge ≤ 150 ms, sichtbarer Fokus, keine Layout-Sprünge.

## Review Focus

1. Bild-Ebene verweist auf eine inzwischen gelöschte Mediendatei → Rechnen lehnt mit 422 „Bild <name> fehlt in den Medien“ ab, Newsletter bleibt unverändert (Test in Task 4).
2. Riesige oder bösartige Quelldatei (Dekompressionsbombe, 9000×9000) als Ebene → kein Absturz, 422 „Bild <name> ist zu groß“ (Test in Task 2).
3. Claude antwortet mit Markdown-Codezaun oder Vor-/Nachtext um das JSON → Parser findet das eine JSON-Objekt; zwei Objekte oder keins ⇒ Korrekturversuch (Test in Task 9).
4. Betreiber speichert in einem zweiten Tab, während der Agent arbeitet → Ablehnung mit Grund, kein verlorenes Update; nach Ablauf (5 min) wieder möglich (verify_060 in Task 3, API-Test in Task 10).
5. Text mit Emoji oder Zeichen, die die Schrift nicht hat → Rechnen stürzt nicht ab (Ersatzglyphe erlaubt) (Test in Task 2).

---

# Teil 1 – Gestaltungsfläche (C)

### Task 1: Schriftdateien und Gestaltung prüfen (MOS)

**Files:**
- Create: `claw/schriftdateien/` (22 × `*.woff2` + 11 × `OFL-*.txt`, kopiert aus `<SC>/sales-mcp/static/schriften/`)
- Create: `claw/gestaltung.py`
- Test: `claw/tests/test_gestaltung_pruefen.py`

**Interfaces:**
- Produces:
  - `FORMATE: dict[str, tuple[int, int]]` = `{"quer": (3, 2), "quadrat": (1, 1), "hoch": (4, 5), "banner": (3, 1)}`
  - `hoehe(fmt: str) -> int` (600er-Einheit, `round(600 * b / a)` mit `(a, b) = FORMATE[fmt]` → quer 400, quadrat 600, hoch 750, banner 200)
  - `class GestaltungFehler(ValueError)`
  - `pruefen(g: object) -> dict` – gibt die normalisierte Gestaltung zurück (Zahlen als float/int, fehlende optionale Felder mit Standard) oder wirft `GestaltungFehler("<deutscher Grund>")`
  - `schrift_datei(sid: str, gewicht: int, kursiv: bool) -> str` – absoluter Pfad oder `GestaltungFehler`
  - `ORDNER_SCHRIFTEN: str`

- [ ] **Step 1: Schriften kopieren** – PowerShell: `Copy-Item <SC>\sales-mcp\static\schriften\*.woff2, <SC>\sales-mcp\static\schriften\OFL-*.txt <MOS>\spaces\marketing\claw\schriftdateien\`.

- [ ] **Step 2: Failing tests schreiben** (`claw/tests/test_gestaltung_pruefen.py`)

```python
import hashlib, os, pathlib
import pytest
from spaces.marketing.claw import gestaltung as gs

GUT = {"version": 1, "format": "quer", "hintergrund": "#F4EFE6", "ebenen": [
    {"id": "foto", "art": "bild", "quelle": "medien:nl-12345678-held_bild.jpg", "x": 300, "y": 200, "breite": 320, "drehung": 0},
    {"id": "titel", "art": "text", "text": "Herbst\nim Laden", "schrift": "playfair", "gewicht": 900,
     "kursiv": False, "groesse": 56, "farbe": "#1C1B18", "ausrichtung": "links", "zeilenabstand": 1.1,
     "x": 160, "y": 120, "drehung": -4}]}

def test_hoehen():
    assert {f: gs.hoehe(f) for f in gs.FORMATE} == {"quer": 400, "quadrat": 600, "hoch": 750, "banner": 200}

def test_gut_wird_normalisiert():
    n = gs.pruefen(GUT)
    assert n["ebenen"][1]["text"] == "Herbst\nim Laden" and n["format"] == "quer"

@pytest.mark.parametrize("aendern, grund", [
    (lambda g: g.update(version=2), "Version"),
    (lambda g: g.update(format="a4"), "Format"),
    (lambda g: g.update(hintergrund="rot"), "Farbe"),
    (lambda g: g.update(ebenen=[dict(GUT["ebenen"][0], id=f"e{i}") for i in range(21)]), "20 Ebenen"),
    (lambda g: g["ebenen"].append(dict(GUT["ebenen"][0])), "doppelt"),
    (lambda g: g["ebenen"][0].update(quelle="https://x.de/a.jpg"), "Medien"),
    (lambda g: g["ebenen"][0].update(quelle="medien:../x.jpg"), "Medien"),
    (lambda g: g["ebenen"][0].update(breite=0), "Breite"),
    (lambda g: g["ebenen"][1].update(text="x" * 201), "200 Zeichen"),
    (lambda g: g["ebenen"][1].update(text="a\nb\nc\nd\ne\nf\ng"), "6 Zeilen"),
    (lambda g: g["ebenen"][1].update(schrift="arial"), "Schrift"),
    (lambda g: g["ebenen"][1].update(gewicht=400), "Schnitt"),
    (lambda g: g["ebenen"][1].update(groesse=9), "Größe"),
    (lambda g: g["ebenen"][1].update(zeilenabstand=3), "Zeilenabstand"),
    (lambda g: g["ebenen"][1].update(drehung=181), "Drehung"),
    (lambda g: g["ebenen"][1].update(ausrichtung="block"), "Ausrichtung"),
    (lambda g: g["ebenen"][1].update(art="form"), "Art"),
    (lambda g: g["ebenen"][1].update(x=True), "Zahl"),
])
def test_fehler(aendern, grund):
    import copy
    g = copy.deepcopy(GUT); aendern(g)
    with pytest.raises(gs.GestaltungFehler, match=grund):
        gs.pruefen(g)

def test_kein_objekt():
    with pytest.raises(gs.GestaltungFehler):
        gs.pruefen([1, 2])

def test_schriften_gleich_wie_sales_claw():
    sc = os.environ.get("SALES_CLAW_DIR")
    if not sc:
        pytest.fail("SALES_CLAW_DIR setzen")
    quelle = pathlib.Path(sc) / "sales-mcp" / "static" / "schriften"
    hier = pathlib.Path(gs.ORDNER_SCHRIFTEN)
    namen = sorted(p.name for p in quelle.glob("*.woff2"))
    assert namen == sorted(p.name for p in hier.glob("*.woff2")) and len(namen) == 22
    for n in namen:
        assert hashlib.sha256((quelle / n).read_bytes()).digest() == hashlib.sha256((hier / n).read_bytes()).digest()

def test_schrift_datei():
    assert gs.schrift_datei("playfair", 900, False).endswith("playfair-900-normal.woff2")
    assert gs.schrift_datei("bodoni", 500, True).endswith("bodoni-500-italic.woff2")
    with pytest.raises(gs.GestaltungFehler):
        gs.schrift_datei("playfair", 400, False)
```

- [ ] **Step 3: Run – Expected FAIL** (`ModuleNotFoundError: gestaltung`).

- [ ] **Step 4: Implementieren** (`claw/gestaltung.py`, Teil Prüfen)

```python
"""Gestaltungsflaeche (sales-claw Spec 2026-10-02-newsletter-gestaltung-und-agent-design.md §1, §5).
Ebenen als Daten pruefen und mit Pillow zu einem JPEG rechnen. Kein Modell."""
from __future__ import annotations

import math
import os
import re

from spaces.marketing.claw import schriften

FORMATE: dict[str, tuple[int, int]] = {"quer": (3, 2), "quadrat": (1, 1), "hoch": (4, 5), "banner": (3, 1)}
BREITE = 600
FAKTOR = 2
MAX_EBENEN = 20
ORDNER_SCHRIFTEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schriftdateien")
_FARBE = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_QUELLE = re.compile(r"^medien:[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(png|jpe?g|gif|webp)$")
_AUSRICHTUNG = ("links", "mitte", "rechts")


class GestaltungFehler(ValueError):
    pass


def hoehe(fmt: str) -> int:
    a, b = FORMATE[fmt]
    return round(BREITE * b / a)


def _zahl(wert, name: str, lo: float, hi: float) -> float:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)) or not math.isfinite(wert):
        raise GestaltungFehler(f"{name} muss eine Zahl sein")
    if not lo <= wert <= hi:
        raise GestaltungFehler(f"{name} muss zwischen {lo:g} und {hi:g} liegen")
    return float(wert)


def _farbe(wert, name: str) -> str:
    if not isinstance(wert, str) or not _FARBE.fullmatch(wert):
        raise GestaltungFehler(f"Farbe {name} muss #RRGGBB sein")
    return wert.upper()


def schrift_datei(sid: str, gewicht: int, kursiv: bool) -> str:
    eintrag = schriften.REGISTER.get(sid)
    if not eintrag:
        raise GestaltungFehler(f"Schrift {sid} gibt es nicht")
    stil = "italic" if kursiv else "normal"
    if (gewicht, stil) not in [tuple(d) for d in eintrag["dateien"]]:
        raise GestaltungFehler(f"Schnitt {gewicht} {stil} gibt es für {sid} nicht")
    return os.path.join(ORDNER_SCHRIFTEN, f"{sid}-{gewicht}-{stil}.woff2")


def _ebene(e, gesehen: set) -> dict:
    if not isinstance(e, dict):
        raise GestaltungFehler("Ebene muss ein Objekt sein")
    eid = e.get("id")
    if not isinstance(eid, str) or not _ID.fullmatch(eid):
        raise GestaltungFehler("Ebenen-id ungültig")
    if eid in gesehen:
        raise GestaltungFehler(f"Ebene {eid} doppelt")
    gesehen.add(eid)
    basis = {"id": eid, "x": _zahl(e.get("x"), "x (Zahl)", -600, 1200),
             "y": _zahl(e.get("y"), "y (Zahl)", -750, 1500),
             "drehung": _zahl(e.get("drehung", 0), "Drehung", -180, 180)}
    if e.get("art") == "bild":
        q = e.get("quelle")
        if not isinstance(q, str) or not _QUELLE.fullmatch(q) or ".." in q:
            raise GestaltungFehler(f"Bild nur aus den Medien (medien:<datei>) in Ebene {eid}")
        return {**basis, "art": "bild", "quelle": q, "breite": _zahl(e.get("breite"), "Breite", 8, 3000)}
    if e.get("art") == "text":
        text = e.get("text")
        if not isinstance(text, str) or not text.strip():
            raise GestaltungFehler(f"Text fehlt in Ebene {eid}")
        if len(text) > 200:
            raise GestaltungFehler("Text höchstens 200 Zeichen")
        if text.count("\n") > 5:
            raise GestaltungFehler("Text höchstens 6 Zeilen")
        if e.get("ausrichtung", "links") not in _AUSRICHTUNG:
            raise GestaltungFehler("Ausrichtung links, mitte oder rechts")
        gewicht = e.get("gewicht")
        if isinstance(gewicht, bool) or not isinstance(gewicht, int):
            raise GestaltungFehler("Schnitt (gewicht) muss eine ganze Zahl sein")
        kursiv = e.get("kursiv", False) is True
        schrift_datei(str(e.get("schrift")), gewicht, kursiv)
        return {**basis, "art": "text", "text": text, "schrift": e["schrift"], "gewicht": gewicht,
                "kursiv": kursiv, "groesse": _zahl(e.get("groesse"), "Größe", 10, 160),
                "farbe": _farbe(e.get("farbe"), "Text"), "ausrichtung": e.get("ausrichtung", "links"),
                "zeilenabstand": _zahl(e.get("zeilenabstand", 1.2), "Zeilenabstand", 0.8, 2.0)}
    raise GestaltungFehler(f"Art der Ebene {eid} muss bild oder text sein")


def pruefen(g) -> dict:
    if not isinstance(g, dict):
        raise GestaltungFehler("Gestaltung muss ein Objekt sein")
    if g.get("version") != 1:
        raise GestaltungFehler("Version muss 1 sein")
    if g.get("format") not in FORMATE:
        raise GestaltungFehler("Format muss quer, quadrat, hoch oder banner sein")
    ebenen = g.get("ebenen")
    if not isinstance(ebenen, list):
        raise GestaltungFehler("Ebenen müssen eine Liste sein")
    if len(ebenen) > MAX_EBENEN:
        raise GestaltungFehler("Höchstens 20 Ebenen")
    gesehen: set = set()
    return {"version": 1, "format": g["format"], "hintergrund": _farbe(g.get("hintergrund"), "Hintergrund"),
            "ebenen": [_ebene(e, gesehen) for e in ebenen]}
```

Hinweis: die Meldungen müssen die Wörter aus den `match=`-Parametern enthalten („Version“, „Format“, „Farbe“, „20 Ebenen“, „doppelt“, „Medien“, „Breite“, „200 Zeichen“, „6 Zeilen“, „Schrift“, „Schnitt“, „Größe“, „Zeilenabstand“, „Drehung“, „Ausrichtung“, „Art“, „Zahl“). Prüfe `x=True` → „x (Zahl) muss eine Zahl sein“ enthält „Zahl“.

- [ ] **Step 5: Run – Expected PASS** (`claw/tests/test_gestaltung_pruefen.py`).
- [ ] **Step 6: Commit** – `git add spaces/marketing/claw/schriftdateien spaces/marketing/claw/gestaltung.py spaces/marketing/claw/tests/test_gestaltung_pruefen.py`; `feat(marketing): Gestaltungsflaeche pruefen, Vorlagenschriften fuer den Server`.

### Task 2: Gestaltung rechnen, Hinweise, Formate umstellen, Aufräumen (MOS)

**Files:**
- Modify: `claw/gestaltung.py`
- Test: `claw/tests/test_gestaltung_rechnen.py`

**Interfaces:**
- Consumes: `pruefen`, `hoehe`, `schrift_datei`, `GestaltungFehler` (Task 1).
- Produces:
  - `RENDERER = 1`
  - `schluessel(g: dict) -> str` – 12 Hex-Zeichen: `sha256(json.dumps({"r": RENDERER, "g": pruefen(g)}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))).hexdigest()[:12]`
  - `name_fuer(g: dict) -> str` = `f"gs-{schluessel(g)}.jpg"`
  - `rechnen(g: dict, quellen: list[str], ziel: str) -> dict` → `{"url": "medien:gs-….jpg", "name": str, "width": 600, "height": hoehe(fmt), "hinweise": list[str]}`; legt die Datei nur an, wenn sie fehlt (gleicher Name = gleicher Inhalt). `quellen` = Ordner in Suchreihenfolge (MARKETING_MEDIEN_ORDNER, MARKETING_BILD_ORDNER). Wirft `GestaltungFehler`.
  - `bild_rechnen(g: dict, quellen: list[str]) -> tuple[PIL.Image.Image, list[str]]` (RGB 1200×2·H, Hinweise) – von `rechnen` und Export genutzt.
  - `umformatieren(g: dict, fmt: str) -> dict` – neue Gestaltung im Zielformat: Positionen relativ zur Mitte, Größen (`breite`, `groesse`) mit `min(B2,H2)/min(B1,H1)` skaliert (B=600, H=hoehe), `groesse` auf 10–160 begrenzt.
  - `aufraeumen(ordner: str, verwiesen: set[str], jetzt: float | None = None) -> list[str]` – löscht `gs-*.jpg` nicht in `verwiesen` mit mtime älter als 7 Tage; gibt gelöschte Namen zurück.

- [ ] **Step 1: Failing tests** (`claw/tests/test_gestaltung_rechnen.py`)

```python
import io, os, time
import pytest
from PIL import Image
from spaces.marketing.claw import gestaltung as gs

def leer(fmt="quer", hg="#FFFFFF", ebenen=None):
    return {"version": 1, "format": fmt, "hintergrund": hg, "ebenen": ebenen or []}

def bild(ordner, name, farbe, groesse=(200, 100), modus="RGB"):
    Image.new(modus, groesse, farbe).save(os.path.join(ordner, name))

def text(**k):
    e = {"id": "t", "art": "text", "text": "Hallo", "schrift": "dm-sans", "gewicht": 700, "kursiv": False,
         "groesse": 48, "farbe": "#000000", "ausrichtung": "mitte", "zeilenabstand": 1.2, "x": 300, "y": 200, "drehung": 0}
    e.update(k); return e

def test_hintergrund_und_masse(tmp_path):
    r = gs.rechnen(leer(hg="#336699"), [str(tmp_path)], str(tmp_path))
    assert r["url"] == f"medien:{r['name']}" and r["name"].startswith("gs-") and (r["width"], r["height"]) == (600, 400)
    im = Image.open(tmp_path / r["name"])
    assert im.format == "JPEG" and im.size == (1200, 800)
    assert all(abs(a - b) <= 3 for a, b in zip(im.getpixel((600, 400)), (0x33, 0x66, 0x99)))

def test_bild_ebene_mittig(tmp_path):
    bild(tmp_path, "rot.png", (255, 0, 0))
    g = leer(ebenen=[{"id": "b", "art": "bild", "quelle": "medien:rot.png", "x": 300, "y": 200, "breite": 200, "drehung": 0}])
    im, _ = gs.bild_rechnen(g, [str(tmp_path)])
    assert im.getpixel((600, 400))[0] > 240            # Mitte rot
    assert im.getpixel((350, 400)) == (255, 255, 255)  # links ausserhalb (200 breit -> 400 px, 400..800)

def test_alpha_bleibt_durchsichtig(tmp_path):
    p = Image.new("RGBA", (100, 100), (0, 0, 0, 0)); p.paste((0, 0, 255, 255), (40, 40, 60, 60))
    p.save(tmp_path / "frei.png")
    g = leer(hg="#00FF00", ebenen=[{"id": "b", "art": "bild", "quelle": "medien:frei.png", "x": 300, "y": 200, "breite": 100, "drehung": 0}])
    im, _ = gs.bild_rechnen(g, [str(tmp_path)])
    assert im.getpixel((560, 360))[1] > 240 and im.getpixel((600, 400))[2] > 240

def test_drehung_aendert_pixel(tmp_path):
    bild(tmp_path, "s.png", (0, 0, 0), (400, 20))
    g0 = leer(ebenen=[{"id": "b", "art": "bild", "quelle": "medien:s.png", "x": 300, "y": 200, "breite": 400, "drehung": 0}])
    g90 = leer(ebenen=[{"id": "b", "art": "bild", "quelle": "medien:s.png", "x": 300, "y": 200, "breite": 400, "drehung": 90}])
    a, _ = gs.bild_rechnen(g0, [str(tmp_path)]); b, _ = gs.bild_rechnen(g90, [str(tmp_path)])
    assert a.getpixel((300, 400))[0] < 30 and b.getpixel((300, 400))[0] > 220
    assert b.getpixel((600, 150))[0] < 30

def test_text_wird_gezeichnet(tmp_path):
    im, _ = gs.bild_rechnen(leer(ebenen=[text()]), [str(tmp_path)])
    box = im.crop((400, 300, 800, 500)).convert("L")
    assert min(box.getdata()) < 60

def test_emoji_stuerzt_nicht_ab(tmp_path):
    gs.bild_rechnen(leer(ebenen=[text(text="Hallo 🎉 Ω")]), [str(tmp_path)])

def test_quelle_fehlt(tmp_path):
    g = leer(ebenen=[{"id": "b", "art": "bild", "quelle": "medien:weg.png", "x": 1, "y": 1, "breite": 10, "drehung": 0}])
    with pytest.raises(gs.GestaltungFehler, match="weg.png fehlt in den Medien"):
        gs.bild_rechnen(g, [str(tmp_path)])

def test_bombe(tmp_path):
    Image.new("L", (9000, 9000), 0).save(tmp_path / "riesig.png")
    g = leer(ebenen=[{"id": "b", "art": "bild", "quelle": "medien:riesig.png", "x": 1, "y": 1, "breite": 10, "drehung": 0}])
    with pytest.raises(gs.GestaltungFehler, match="zu groß"):
        gs.bild_rechnen(g, [str(tmp_path)])

def test_hash_stabil_und_idempotent(tmp_path):
    g = leer(ebenen=[text()])
    assert gs.schluessel(g) == gs.schluessel(dict(reversed(list(g.items()))))
    a = gs.rechnen(g, [str(tmp_path)], str(tmp_path)); t = os.path.getmtime(tmp_path / a["name"])
    time.sleep(0.05); b = gs.rechnen(g, [str(tmp_path)], str(tmp_path))
    assert a["name"] == b["name"] and os.path.getmtime(tmp_path / a["name"]) == t
    assert gs.schluessel(leer(ebenen=[text(text="Anders")])) != gs.schluessel(g)

def test_hinweise(tmp_path):
    g = leer(hg="#FFFFFF", ebenen=[text(groesse=16, farbe="#EEEEEE", x=590)])
    _, h = gs.bild_rechnen(g, [str(tmp_path)])
    assert any("unter 12 px" in x for x in h)
    assert any("Kontrast" in x for x in h)
    assert any("außerhalb" in x for x in h)

def test_unter_1mb(tmp_path):
    import random
    rauschen = Image.effect_noise((1200, 1200), 120).convert("RGB")
    rauschen.save(tmp_path / "rausch.png")
    g = leer("quadrat", ebenen=[{"id": "b", "art": "bild", "quelle": "medien:rausch.png", "x": 300, "y": 300, "breite": 600, "drehung": 0}])
    r = gs.rechnen(g, [str(tmp_path)], str(tmp_path))
    assert os.path.getsize(tmp_path / r["name"]) <= 1024 * 1024

def test_umformatieren():
    g = leer("quer", ebenen=[text(x=300, y=200, groesse=40)])
    h = gs.umformatieren(g, "hoch")
    assert h["format"] == "hoch" and h["ebenen"][0]["x"] == 300 and h["ebenen"][0]["y"] == 375
    assert h["ebenen"][0]["groesse"] == 60  # Skalierung min(600,750)/min(600,400) = 1.5

def test_aufraeumen(tmp_path):
    for n in ("gs-aaaaaaaaaaaa.jpg", "gs-bbbbbbbbbbbb.jpg", "nl-12345678-x.jpg"):
        (tmp_path / n).write_bytes(b"x")
    alt = time.time() - 8 * 86400
    for n in ("gs-aaaaaaaaaaaa.jpg", "gs-bbbbbbbbbbbb.jpg", "nl-12345678-x.jpg"):
        os.utime(tmp_path / n, (alt, alt))
    weg = gs.aufraeumen(str(tmp_path), {"gs-bbbbbbbbbbbb.jpg"})
    assert weg == ["gs-aaaaaaaaaaaa.jpg"] and (tmp_path / "nl-12345678-x.jpg").exists()
```

- [ ] **Step 2: Run – Expected FAIL** (`AttributeError: rechnen`).

- [ ] **Step 3: Implementieren** (in `claw/gestaltung.py` ergänzen)

```python
import hashlib
import json
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

from spaces.marketing.claw.schoenheit import kontrast

RENDERER = 1
MAX_BYTES = 1024 * 1024
MAX_PIXEL = 40_000_000
AUFRAEUM_ALTER_S = 7 * 86400


def schluessel(g: dict) -> str:
    roh = json.dumps({"r": RENDERER, "g": pruefen(g)}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:12]


def name_fuer(g: dict) -> str:
    return f"gs-{schluessel(g)}.jpg"


def _pfad(quelle: str, quellen: list[str]) -> str:
    name = quelle[len("medien:"):]
    for o in quellen:
        if not o:
            continue
        p = os.path.realpath(os.path.join(o, name))
        if os.path.commonpath([p, os.path.realpath(o)]) == os.path.realpath(o) and os.path.isfile(p):
            return p
    raise GestaltungFehler(f"Bild {name} fehlt in den Medien")


def _laden(pfad: str, name: str) -> Image.Image:
    try:
        with Image.open(pfad) as roh:
            if roh.width * roh.height > MAX_PIXEL:
                raise GestaltungFehler(f"Bild {name} ist zu groß")
            return roh.convert("RGBA")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise GestaltungFehler(f"Bild {name} ist zu groß")
    except OSError:
        raise GestaltungFehler(f"Bild {name} ist nicht lesbar")


def _text_ebene(e: dict) -> Image.Image:
    font = ImageFont.truetype(schrift_datei(e["schrift"], e["gewicht"], e["kursiv"]), int(round(e["groesse"] * FAKTOR)))
    zeilen = e["text"].split("\n")
    zh = e["groesse"] * FAKTOR * e["zeilenabstand"]
    breiten = [font.getlength(z) for z in zeilen]
    w = max(1, int(math.ceil(max(breiten))))
    h = max(1, int(math.ceil(zh * len(zeilen))))
    ebene = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ebene)
    anker = {"links": ("la", 0), "mitte": ("ma", w / 2), "rechts": ("ra", w)}[e["ausrichtung"]]
    for i, z in enumerate(zeilen):
        d.text((anker[1], i * zh + (zh - e["groesse"] * FAKTOR) / 2), z, font=font, fill=e["farbe"], anchor=anker[0])
    return ebene


def _einsetzen(leinwand: Image.Image, ebene: Image.Image, e: dict) -> tuple[int, int, int, int]:
    if e["drehung"]:
        ebene = ebene.rotate(-e["drehung"], resample=Image.BICUBIC, expand=True)
    cx, cy = e["x"] * FAKTOR, e["y"] * FAKTOR
    links, oben = int(round(cx - ebene.width / 2)), int(round(cy - ebene.height / 2))
    leinwand.paste(ebene, (links, oben), ebene)
    return links, oben, links + ebene.width, oben + ebene.height


def _ausserhalb(box, w, h) -> float:
    l, o, r, u = box
    flaeche = max(1, (r - l) * (u - o))
    innen = max(0, min(r, w) - max(l, 0)) * max(0, min(u, h) - max(o, 0))
    return 1 - innen / flaeche


def bild_rechnen(g: dict, quellen: list[str]) -> tuple[Image.Image, list[str]]:
    g = pruefen(g)
    w, h = BREITE * FAKTOR, hoehe(g["format"]) * FAKTOR
    leinwand = Image.new("RGBA", (w, h), g["hintergrund"])
    hinweise: list[str] = []
    for e in g["ebenen"]:
        if e["art"] == "bild":
            name = e["quelle"][len("medien:"):]
            quelle = _laden(_pfad(e["quelle"], quellen), name)
            bw = max(1, int(round(e["breite"] * FAKTOR)))
            bh = max(1, int(round(quelle.height * bw / quelle.width)))
            ebene = quelle.resize((bw, bh), Image.LANCZOS)
            box = _einsetzen(leinwand, ebene, e)
            beschreibung = f"Bild {name}"
        else:
            ebene = _text_ebene(e)
            unter = leinwand.crop((max(0, int(e["x"] * FAKTOR - ebene.width / 2)), max(0, int(e["y"] * FAKTOR - ebene.height / 2)),
                                   min(w, int(e["x"] * FAKTOR + ebene.width / 2) + 1), min(h, int(e["y"] * FAKTOR + ebene.height / 2) + 1)))
            box = _einsetzen(leinwand, ebene, e)
            kurz = e["text"].split("\n")[0][:30]
            beschreibung = f"Text „{kurz}“"
            if e["groesse"] < 22:
                hinweise.append(f"{beschreibung} ist am Handy unter 12 px")
            if unter.width and unter.height:
                mittel = unter.convert("RGB").resize((1, 1), Image.BOX).getpixel((0, 0))
                grund = "#%02x%02x%02x" % mittel
                if kontrast(e["farbe"].lower(), grund) < 3.0:
                    hinweise.append(f"{beschreibung}: Kontrast zum Untergrund unter 3:1")
        if _ausserhalb(box, w, h) > 0.15:
            hinweise.append(f"{beschreibung} liegt zu mehr als 15 % außerhalb der Fläche")
    return leinwand.convert("RGB"), hinweise


def _speichern(bild: Image.Image, pfad: str, ordner: str) -> None:
    for q in range(88, 63, -6):
        fd, tmp = tempfile.mkstemp(dir=ordner, suffix=".tmp")
        os.close(fd)
        try:
            bild.save(tmp, "JPEG", quality=q, optimize=True)
            if os.path.getsize(tmp) <= MAX_BYTES:
                os.chmod(tmp, 0o644)
                os.replace(tmp, pfad)
                return
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    raise GestaltungFehler("Bild wird zu groß (über 1 MB)")


def rechnen(g: dict, quellen: list[str], ziel: str) -> dict:
    g = pruefen(g)
    name = name_fuer(g)
    pfad = os.path.join(ziel, name)
    hinweise: list[str]
    bild, hinweise = bild_rechnen(g, quellen)
    if not os.path.exists(pfad):
        _speichern(bild, pfad, ziel)
    return {"url": f"medien:{name}", "name": name, "width": BREITE, "height": hoehe(g["format"]), "hinweise": hinweise}


def umformatieren(g: dict, fmt: str) -> dict:
    g = pruefen(g)
    if fmt not in FORMATE:
        raise GestaltungFehler("Format muss quer, quadrat, hoch oder banner sein")
    h1, h2 = hoehe(g["format"]), hoehe(fmt)
    s = min(BREITE, h2) / min(BREITE, h1)
    neu = []
    for e in g["ebenen"]:
        e = dict(e)
        e["x"] = round(BREITE / 2 + (e["x"] - BREITE / 2) * s, 1)
        e["y"] = round(h2 / 2 + (e["y"] - h1 / 2) * s, 1)
        if e["art"] == "bild":
            e["breite"] = round(min(3000, max(8, e["breite"] * s)), 1)
        else:
            e["groesse"] = round(min(160, max(10, e["groesse"] * s)), 1)
        neu.append(e)
    return pruefen({**g, "format": fmt, "ebenen": neu})


def aufraeumen(ordner: str, verwiesen: set[str], jetzt: float | None = None) -> list[str]:
    jetzt = time.time() if jetzt is None else jetzt
    weg = []
    for n in sorted(os.listdir(ordner)):
        if not re.fullmatch(r"gs-[0-9a-f]{12}\.jpg", n) or n in verwiesen:
            continue
        p = os.path.join(ordner, n)
        if jetzt - os.path.getmtime(p) > AUFRAEUM_ALTER_S:
            os.remove(p)
            weg.append(n)
    return weg
```

`test_umformatieren`: Mitte bleibt Mitte (x 300 → 300, y 200 → 375), Abstände zur Mitte und Größen × 1.5.

- [ ] **Step 4: Run – Expected PASS** (beide Testdateien von Task 1+2).
- [ ] **Step 5: Commit** – `feat(marketing): Gestaltungsflaeche mit Pillow rechnen, Hinweise, Formatwechsel, Aufraeumen`.

### Task 3: Migration 060 – Gestaltung im Validator, Chat-Aufträge, Sperre (MOS)

**Files:**
- Create: `db/060_gestaltung_und_chat.sql`, `db/verify_060.sql`

**Interfaces:**
- Produces (SQL):
  - `marketing._pult_bloecke_fehler_058(p jsonb) RETURNS text` (umbenannte bisherige Funktion) und neue `marketing.pult_bloecke_fehler(p jsonb) RETURNS text` = Basis + Grobprüfung `props.gestaltung` (nur bei `Image`: Objekt, `version`=1, `format` ∈ (quer,quadrat,hoch,banner), `ebenen` Array ≤ 20, `props.alt` Text ≤ 200; Meldungen: `'Gestaltung ungültig in %s'`, `'Gestaltung nur im Bild-Block (%s)'`).
  - `marketing._pult_bloecke_speichern_053(...)` (umbenannt) und neue `marketing.pult_bloecke_speichern(p_inhalt uuid, p_basis int, p_betreff text, p_vorschautext text, p_bloecke jsonb, p_urheber text, p_als_kopie boolean) RETURNS int` = bei `p_urheber='betreiber'` und laufendem Chat-Auftrag (`status IN ('offen','in_arbeit')` und (`vergeben_bis IS NULL` oder `vergeben_bis > now()`)) `RAISE EXCEPTION 'Der Assistent arbeitet gerade'`; sonst Basis.
  - Tabelle `marketing.chat_auftraege`:
    `id uuid PK DEFAULT gen_random_uuid(), inhalt uuid NOT NULL REFERENCES marketing.inhalte(id), art text NOT NULL DEFAULT 'chat' CHECK (art IN ('chat','export')), nachricht text NOT NULL DEFAULT '' CHECK (length(nachricht) <= 2000), kontext jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(kontext)='object'), status text NOT NULL DEFAULT 'offen' CHECK (status IN ('offen','in_arbeit','fertig','fehler')), antwort text NOT NULL DEFAULT '', hinweise jsonb NOT NULL DEFAULT '[]', ergebnis jsonb NOT NULL DEFAULT '{}', fassung_vorher int, fassung_nachher int, versuche int NOT NULL DEFAULT 0, vergeben_bis timestamptz, erstellt_am timestamptz NOT NULL DEFAULT now(), geaendert_am timestamptz NOT NULL DEFAULT now()`; Index `(inhalt, erstellt_am DESC)`, `(status, erstellt_am)`; `UNIQUE (inhalt) WHERE status IN ('offen','in_arbeit')`.
  - `marketing.pult_chat_aufraeumen(p_inhalt uuid) RETURNS void` – `offen` und `erstellt_am < now() - interval '2 minutes'` ⇒ `fehler`, antwort `'Der Assistent läuft am PC und ist gerade aus'`; `in_arbeit` mit abgelaufenem `vergeben_bis`: `versuche < 2` ⇒ `offen` (vergeben_bis NULL, erstellt_am = now()), sonst `fehler` `'Der Assistent ist nicht fertig geworden'`. `p_inhalt NULL` ⇒ alle.
  - `marketing.pult_chat_anlegen(p_inhalt uuid, p_art text, p_nachricht text, p_kontext jsonb) RETURNS uuid` – ruft `pult_chat_aufraeumen(p_inhalt)`; Inhalt muss Newsletter im Status `entwurf` sein (`'Nur Newsletter-Entwürfe'`); `p_art='chat'` braucht nicht-leere Nachricht; laufender Auftrag ⇒ `'Der Assistent arbeitet gerade'`; setzt `fassung_vorher` = neueste Fassung.
  - `marketing.pult_chat_naechster(p_frist interval) RETURNS jsonb` – ruft `pult_chat_aufraeumen(NULL)`; nimmt ältesten `offen` per `FOR UPDATE SKIP LOCKED`; setzt `in_arbeit, versuche+1, vergeben_bis=now()+p_frist`; gibt `{id, inhalt, art, nachricht, kontext, fassung, bloecke, betreff, vorschautext, titel, mandant, pflichtteil, verlauf}` zurück (`verlauf` = letzte 10 `fertig`/`fehler`-Chat-Aufträge desselben Inhalts, älteste zuerst, je `{nachricht, antwort}`; `pflichtteil` aus `marketing.mandanten.pflichtteil`), sonst NULL.
  - `marketing.pult_chat_verlaengern(p_auftrag uuid, p_frist interval) RETURNS boolean`.
  - `marketing.pult_chat_fertig(p_auftrag uuid, p_antwort text, p_bloecke jsonb, p_hinweise jsonb, p_ergebnis jsonb) RETURNS jsonb` – Auftrag muss `in_arbeit` mit gültiger Vergabe sein (`'Auftrag ist nicht (mehr) in Arbeit'`); wenn `p_bloecke` nicht NULL: `pult_bloecke_speichern(inhalt, fassung_vorher, betreff, vorschautext, p_bloecke, 'agent', false)` (Betreff/Vorschautext aus der neuesten Fassung `felder`); setzt `fertig`, `antwort` (≤ 4000), `hinweise`, `ergebnis`, `fassung_nachher`, `vergeben_bis=NULL`; gibt `{fassung}` (NULL ohne Blöcke) zurück.
  - `marketing.pult_chat_zurueck(p_auftrag uuid, p_antwort text) RETURNS text` – setzt `fehler` mit Antwort, `vergeben_bis=NULL`; gibt Status zurück.
  - Trigger: beim Entscheiden des Inhalts (wie `trg_bild_auftraege_verwerfen`) laufende Chat-Aufträge ⇒ `fehler` „Newsletter wurde entschieden“.

- [ ] **Step 1: verify_060.sql schreiben** (Nachweise, ohne BEGIN/COMMIT). Pflicht-Asserts (jeweils `ASSERT … , 'meldung'` in `DO $$ … $$`), mit einem per `SELECT … FROM marketing.inhalte WHERE art='newsletter' AND status='entwurf' ORDER BY erstellt_am LIMIT 1` gewählten Inhalt (wenn keiner: einen anlegen wie in verify_059 – dort nachsehen und übernehmen):
  1. `pult_bloecke_fehler` mit gültiger neuester Fassung + eingefügtem Image-Block `{"type":"Image","data":{"style":{},"props":{"url":null,"alt":"x","width":600,"height":400,"gestaltung":{"version":1,"format":"quer","hintergrund":"#FFFFFF","ebenen":[]}}}}` (Block-id `gs_probe`, in `root.data.childrenIds` gehängt) ⇒ NULL.
  2. Gleiches mit `format:"a4"` ⇒ Meldung enthält `Gestaltung ungültig`.
  3. `gestaltung` an einem `Text`-Block ⇒ `Gestaltung nur im Bild-Block`.
  4. `pult_chat_anlegen(i,'chat','Hallo','{}')` liefert uuid; zweiter Aufruf wirft `Der Assistent arbeitet gerade` (per `BEGIN … EXCEPTION WHEN OTHERS THEN v_fehler := SQLERRM; END` und `ASSERT v_fehler LIKE '%arbeitet gerade%'`).
  5. `pult_bloecke_speichern(i, neueste, betreff, vt, bloecke, 'betreiber', false)` wirft `Der Assistent arbeitet gerade`; mit `'agent'` nicht.
  6. `pult_chat_naechster('5 minutes')` liefert den Auftrag mit `bloecke` und `verlauf` (Array).
  7. `pult_chat_fertig(id,'Erledigt', bloecke, '[]','{}')` ⇒ `fassung` = neueste+1, Urheber der neuen Fassung `agent`, Status `fertig`.
  8. Ablauf: neuer Auftrag, `UPDATE … SET erstellt_am = now() - interval '3 minutes'`, `pult_chat_aufraeumen(i)` ⇒ `fehler` mit `gerade aus`.
  9. Nach Fehler wieder anlegbar.
  Ende: `SELECT 'verify_060 ok' AS ergebnis;`

- [ ] **Step 2: Probe laufen lassen – Expected FAIL** (Funktionen fehlen).

- [ ] **Step 3: 060 schreiben** (`BEGIN; … COMMIT;`, idempotent). Umbenennen idempotent:

```sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'marketing' AND p.proname = '_pult_bloecke_fehler_058') THEN
    ALTER FUNCTION marketing.pult_bloecke_fehler(jsonb) RENAME TO _pult_bloecke_fehler_058;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'marketing' AND p.proname = '_pult_bloecke_speichern_053') THEN
    ALTER FUNCTION marketing.pult_bloecke_speichern(uuid, int, text, text, jsonb, text, boolean)
      RENAME TO _pult_bloecke_speichern_053;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION marketing.pult_bloecke_fehler(p jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_basis text; v_id text; v_b jsonb; v_g jsonb;
BEGIN
  v_basis := marketing._pult_bloecke_fehler_058(p);
  IF v_basis IS NOT NULL THEN RETURN v_basis; END IF;
  FOR v_id, v_b IN SELECT key, value FROM jsonb_each(p) LOOP
    v_g := v_b #> '{data,props,gestaltung}';
    IF v_g IS NULL OR jsonb_typeof(v_g) = 'null' THEN CONTINUE; END IF;
    IF v_b->>'type' <> 'Image' THEN RETURN format('Gestaltung nur im Bild-Block (%s)', v_id); END IF;
    IF jsonb_typeof(v_g) <> 'object' OR v_g->'version' IS DISTINCT FROM '1'::jsonb
       OR coalesce(v_g->>'format', '') NOT IN ('quer','quadrat','hoch','banner')
       OR jsonb_typeof(v_g->'ebenen') IS DISTINCT FROM 'array' OR jsonb_array_length(v_g->'ebenen') > 20
       OR jsonb_typeof(v_b #> '{data,props,alt}') IS DISTINCT FROM 'string'
       OR length(v_b #>> '{data,props,alt}') > 200 THEN
      RETURN format('Gestaltung ungültig in %s', v_id);
    END IF;
  END LOOP;
  RETURN NULL;
END $$;
```

Die Speichern-Hülle analog (plpgsql, gleiche Signatur, `RETURNS int`, ruft `marketing._pult_bloecke_speichern_053(...)`). Rechte: dieselben `GRANT`/`SECURITY`-Eigenschaften wie die Originale übernehmen (in 053/058 nachsehen: falls dort `SECURITY DEFINER`/`SET search_path`/`GRANT EXECUTE … TO <rolle>` steht, identisch setzen). Tabelle, Indizes, Funktionen und Trigger gemäß Interfaces. `pult_chat_naechster` nach dem Muster von `pult_bild_naechster` (056:76-116) bauen.

- [ ] **Step 4: Probe – Expected `verify_060 ok` + `PROBE OK (zurueckgerollt)`.** Zusätzlich die Probe für 059+060 zusammen nicht nötig (059 ist live).
- [ ] **Step 5: Commit** – `feat(marketing): Migration 060 Gestaltung im Validator, Chat-Auftraege, Sperre waehrend der Assistent arbeitet`.

### Task 4: Gestaltungs-Route, Bildplätze überspringen Flächen, Aufräumen (MOS)

**Files:**
- Create: `api/gestaltung.py` (Router `pult_router = APIRouter(prefix="/api/pult")`)
- Modify: `api/server.py` (einhängen neben `_bilder`), `claw/bildplaetze.py` (`_platz` → `None` bei `props.gestaltung`)
- Test: `tests/test_gestaltung_api.py`, `claw/tests/test_bildplaetze.py` (ein neuer Fall)

**Interfaces:**
- Consumes: `gestaltung.rechnen`, `gestaltung.aufraeumen`, `gestaltung.GestaltungFehler`; `pult._schluessel`, `pult._uuid_oder_404`, `pult._lesen`, `pult.lit`.
- Produces:
  - `POST /api/pult/inhalte/{iid}/gestaltung` Body `{gestaltung: dict}` (Header `X-Pult-Key`) → `200 {url, width, height, hinweise}`; 422 `{"detail": "<Grund>"}` bei `GestaltungFehler`; 404 unbekannter Inhalt; 503 Ordner fehlt.
  - `quellen() -> list[str]` = `[MARKETING_MEDIEN_ORDNER, MARKETING_BILD_ORDNER]` (leere weglassen) – auch für Task 10/12.
  - `gestaltungen_rechnen(dok: dict) -> tuple[dict, list[str]]` – rechnet jede `Image`-Fläche, deren `url` ≠ `medien:` + `name_fuer(g)`, setzt `url/width/height`, gibt Kopie + gesammelte Hinweise (`"<block-id>: <hinweis>"`) zurück; wirft `GestaltungFehler` mit `"<block-id>: <Grund>"`.
  - `verwiesene_gs() -> set[str]` – `SELECT DISTINCT m[1] … regexp_matches(bloecke::text, 'medien:(gs-[0-9a-f]{12}\.jpg)', 'g')` über alle `inhalt_fassungen`.
  - `aufraeumen_falls_faellig(jetzt=None) -> None` – höchstens einmal je Stunde (Modulvariable), ruft `gestaltung.aufraeumen(ordner, verwiesene_gs())`, schluckt Fehler (loggt per `logging`).

- [ ] **Step 1: Failing tests** (`tests/test_gestaltung_api.py`; Fixtures wie in `tests/test_bilder_api.py`: `FalscheDB` aus `test_pult_api`, `MARKETING_PULT_KEY`, `MARKETING_BILD_ORDNER=tmp_path`, `server.API_KEY`)

```python
import os, json, pytest
from PIL import Image
from fastapi.testclient import TestClient
from spaces.marketing.api import server
from spaces.marketing.tests.test_pult_api import FalscheDB
from spaces.marketing.claw import bildplaetze

PK, AK = "pult-k", "api-k"
IID = "11111111-1111-1111-1111-111111111111"
H = {"X-Pult-Key": PK, "X-API-Key": AK}
G = {"version": 1, "format": "quer", "hintergrund": "#FFFFFF", "ebenen": []}

@pytest.fixture
def umg(monkeypatch, tmp_path):
    from spaces.marketing.sync import _db
    f = FalscheDB()
    monkeypatch.setattr(_db, "query_via_docker", f.query); monkeypatch.setattr(_db, "query_one", f.one)
    monkeypatch.setenv("MARKETING_PULT_KEY", PK); monkeypatch.setenv("MARKETING_BILD_ORDNER", str(tmp_path))
    monkeypatch.delenv("MARKETING_MEDIEN_ORDNER", raising=False)
    monkeypatch.setattr(server, "API_KEY", AK)
    return f, tmp_path

def test_rechnet_und_liefert_url(umg):
    f, ordner = umg
    f.antworten.append([{"id": IID}])
    r = TestClient(server.app).post(f"/api/pult/inhalte/{IID}/gestaltung", json={"gestaltung": G}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json(); assert d["url"].startswith("medien:gs-") and d["height"] == 400
    assert (ordner / d["url"][7:]).exists()

def test_fehlende_quelle_422(umg):
    f, _ = umg
    f.antworten.append([{"id": IID}])
    g = dict(G, ebenen=[{"id": "b", "art": "bild", "quelle": "medien:weg.png", "x": 1, "y": 1, "breite": 10, "drehung": 0}])
    r = TestClient(server.app).post(f"/api/pult/inhalte/{IID}/gestaltung", json={"gestaltung": g}, headers=H)
    assert r.status_code == 422 and "weg.png fehlt in den Medien" in r.json()["detail"]

def test_ohne_schluessel_401(umg):
    r = TestClient(server.app).post(f"/api/pult/inhalte/{IID}/gestaltung", json={"gestaltung": G}, headers={"X-API-Key": AK})
    assert r.status_code == 401

def test_gestaltungen_rechnen_setzt_url(umg):
    from spaces.marketing.api import gestaltung as ga
    dok = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["f"]}},
           "f": {"type": "Image", "data": {"style": {}, "props": {"url": None, "alt": "x", "width": 600, "height": 1, "gestaltung": G}}}}
    neu, hinweise = ga.gestaltungen_rechnen(dok)
    assert neu["f"]["data"]["props"]["url"].startswith("medien:gs-") and neu["f"]["data"]["props"]["height"] == 400
    assert dok["f"]["data"]["props"]["url"] is None  # Original unveraendert

def test_bildplaetze_ueberspringen_flaechen():
    dok = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["f"]}},
           "f": {"type": "Image", "data": {"style": {}, "props": {"url": "medien:gs-aaaaaaaaaaaa.jpg", "alt": "x",
                 "width": 600, "height": 400, "gestaltung": G}}}}
    assert bildplaetze.finde(dok) == []
```

Die erste DB-Antwort ist die Existenzprüfung des Inhalts (`SELECT id FROM marketing.inhalte WHERE id = …`); passe die Reihenfolge an deine Implementierung an, aber prüfe mit `assert` auf den SQL-Text, dass nur gelesen wird.

- [ ] **Step 2: Run – FAIL.**
- [ ] **Step 3: Implementieren.** `api/gestaltung.py`: Route prüft Schlüssel, `_uuid_oder_404`, Inhalt existiert (`_lesen`), dann `run_in_threadpool`-freier Aufruf `gestaltung.rechnen(body["gestaltung"], quellen(), ordner)` (Ordner wie `bilder._ordner()` – importieren und wiederverwenden), danach `aufraeumen_falls_faellig()`. `GestaltungFehler` → `HTTPException(422, str(e))`. In `bildplaetze._platz` am Anfang: `if isinstance(props.get("gestaltung"), dict): return None`. `server.py`: `from spaces.marketing.api import gestaltung as _gestaltung; app.include_router(_gestaltung.pult_router)`.
- [ ] **Step 4: Run – PASS** (neue Tests + `tests/test_bilder_api.py` + `claw/tests/test_bildplaetze.py`).
- [ ] **Step 5: Commit** – `feat(marketing): Gestaltungs-Route, Flaechen sind keine Bildplaetze, Entwurfsbilder aufraeumen`.

### Task 5: sales-ui – Gestaltung durchreichen, Entwurfsbilder verstecken (SC)

**Files:**
- Modify: `sales-mcp/ui_editor.py` (neue Route + Startdaten-Schlüssel), `sales-mcp/medien.py` (`gs-*` verstecken)
- Test: `sales-mcp/tests/test_editor_seite.py`, `sales-mcp/tests/test_medien_meta.py` (oder neue `tests/test_medien_gs.py`)

**Interfaces:**
- Consumes: Pult `POST /inhalte/{iid}/gestaltung` (Task 4).
- Produces:
  - `POST /marketing/editor/{iid}/gestaltung` (CSRF `x-csrf`, `@ui._gesichert_seite`) Body `{gestaltung}` → `{url, width, height, hinweise}`; 422 `{"grund"}` bei Ablehnung, 503 sonst.
  - Startdaten-Schlüssel `gestaltung_url` = `/marketing/editor/{iid}/gestaltung`.
  - `medien.ENTWURF_MUSTER = re.compile(r"^gs-[0-9a-f]{12}\.jpg$")`; `liste()` UND `liste(True)` lassen Entwurfsbilder weg; `pruefe_anhang` lehnt sie ab (Grund „Entwurfsbild“). Die angemeldete Anzeige `/medien/datei/<name>` (ui.py) muss sie weiter ausliefern (der Editor zeigt Flächen darüber) – also nur Listen und Anhänge filtern, nicht `pruefe`.

- [ ] **Step 1: Failing tests** – im Stil der vorhandenen `editor_bild`-Tests (`tests/test_editor_seite.py`, Pult per `monkeypatch.setattr(ui_editor.marketing_pult, "anfrage", fake)`):
  - Durchreichen: Fake bekommt `("POST", f"/inhalte/{iid}/gestaltung", {"gestaltung": g})`, Antwort wird 1:1 zurückgegeben (Status 200, `Cache-Control: no-store`).
  - Ohne CSRF ⇒ 403; `gestaltung` kein Objekt ⇒ 422 „Gestaltung fehlt“; Pult `PultFehler("abgelehnt", "Bild x fehlt in den Medien")` ⇒ 422 mit genau diesem Grund; `nicht_erreichbar` ⇒ 503 „Gestaltung gerade nicht möglich“.
  - Startdaten enthalten `gestaltung_url`.
  - Medien: Datei `gs-0123456789ab.jpg` im Erzeugt-Ordner (`monkeypatch.setattr(server.medien, "ERZEUGT_VERZEICHNIS", …)`) erscheint weder in `medien.liste()` noch in `liste(True)` noch in `GET /marketing/editor/medien.json`; `nl-12345678-x.jpg` schon.
- [ ] **Step 2: Run – FAIL.**
- [ ] **Step 3: Implementieren** nach dem Muster `editor_bild` (ui_editor.py:260-300); Route in die Liste NACH `/marketing/editor/{iid}/bild` einfügen.
- [ ] **Step 4: Run – PASS** (`tests/test_editor_seite.py tests/test_medien_meta.py tests/test_medien_haertung.py tests/test_marketing_pult.py`).
- [ ] **Step 5: Commit** – `feat(ui): Gestaltungsflaeche durchreichen, Entwurfsbilder aus den Medienlisten`.

### Task 6: Editor – Gestaltungs-Modell und Mathematik (SC, rein, vitest)

**Files:**
- Create: `editor/src/gestaltung.ts`, `editor/src/gestaltung.test.ts`
- Modify: `editor/src/schemata.ts` (`GestaltungSchema`, `ImageSchema` erweitert um `gestaltung`)

**Interfaces:**
- Produces (`gestaltung.ts`):
```ts
export type Format = 'quer' | 'quadrat' | 'hoch' | 'banner';
export const FORMATE: Record<Format, [number, number]> = { quer: [3, 2], quadrat: [1, 1], hoch: [4, 5], banner: [3, 1] };
export const BREITE = 600;
export function hoehe(f: Format): number;                       // Math.round(600*b/a)
export type BildEbene = { id: string; art: 'bild'; quelle: string; x: number; y: number; breite: number; drehung: number };
export type TextEbene = { id: string; art: 'text'; text: string; schrift: string; gewicht: number; kursiv: boolean;
  groesse: number; farbe: string; ausrichtung: 'links' | 'mitte' | 'rechts'; zeilenabstand: number; x: number; y: number; drehung: number };
export type Ebene = BildEbene | TextEbene;
export type Gestaltung = { version: 1; format: Format; hintergrund: string; ebenen: Ebene[] };
export function neueGestaltung(hintergrund: string): Gestaltung;          // quer, keine Ebenen
export function neueId(vorhanden: string[]): string;                       // 'e-' + 6 hex, kollisionsfrei
export function zoomFuer(platzB: number, platzH: number, f: Format): number; // min(platzB/600, platzH/hoehe), höchstens 2
export function zuEinheit(px: number, py: number, zoom: number): { x: number; y: number };
export function skalieren(e: Ebene, deltaY: number): Ebene;   // Scroll: Faktor 1.1 je -100 deltaY (exp), bild.breite 8..3000, text.groesse 10..160
export function drehen(e: Ebene, deltaY: number): Ebene;      // Shift+Scroll: 1° je 20 deltaY, -180..180 (umbrechen)
export function schieben(e: Ebene, dx: number, dy: number): Ebene;
export type Linie = { achse: 'x' | 'y'; wert: number };
export function einrasten(e: Ebene, groesse: { w: number; h: number }, andere: Ebene[], f: Format, schwelle?: number):
  { x: number; y: number; linien: Linie[] }; // rastet Mitte von e an Flächenmitte/Rand-Mitten/Mitten anderer Ebenen (Schwelle 6 Einheiten)
export function hinweise(g: Gestaltung): string[];           // Text < 22 ⇒ 'Text „<erste 30 Zeichen>“ ist am Handy unter 12 px'
export function verlauf<T>(start: T): { jetzt(): T; setzen(v: T): void; zurueck(): boolean; vor(): boolean }; // max. 100 Schritte
```
- `schemata.ts`: `GestaltungSchema` (zod) mit denselben Grenzen wie Python (Task 1); `ImageSchema.props` um `gestaltung: GestaltungSchema.nullable().optional()` erweitern.

- [ ] **Step 1: Failing tests** (`gestaltung.test.ts`)

```ts
import { describe, expect, it } from 'vitest';
import { hoehe, zoomFuer, skalieren, drehen, einrasten, hinweise, verlauf, neueGestaltung, neueId, zuEinheit } from './gestaltung';
import { GestaltungSchema } from './schemata';

const text = { id: 't', art: 'text' as const, text: 'Hallo', schrift: 'dm-sans', gewicht: 700, kursiv: false, groesse: 48,
  farbe: '#000000', ausrichtung: 'mitte' as const, zeilenabstand: 1.2, x: 300, y: 200, drehung: 0 };
const bild = { id: 'b', art: 'bild' as const, quelle: 'medien:a.png', x: 100, y: 100, breite: 200, drehung: 0 };

describe('gestaltung', () => {
  it('hoehen', () => expect([hoehe('quer'), hoehe('quadrat'), hoehe('hoch'), hoehe('banner')]).toEqual([400, 600, 750, 200]));
  it('zoom passt in den Platz und ist begrenzt', () => {
    expect(zoomFuer(1200, 2000, 'quer')).toBe(2);
    expect(zoomFuer(600, 300, 'quer')).toBeCloseTo(0.75);
  });
  it('zuEinheit teilt durch zoom', () => expect(zuEinheit(150, 90, 1.5)).toEqual({ x: 100, y: 60 }));
  it('scroll skaliert symmetrisch und begrenzt', () => {
    const groesser = skalieren(bild, -100) as typeof bild;
    expect(groesser.breite).toBeCloseTo(220);
    expect((skalieren(groesser, 100) as typeof bild).breite).toBeCloseTo(200);
    expect((skalieren({ ...text, groesse: 159 }, -1000) as typeof text).groesse).toBe(160);
    expect((skalieren({ ...bild, breite: 9 }, 1000) as typeof bild).breite).toBe(8);
  });
  it('shift-scroll dreht und bricht um', () => {
    expect(drehen(bild, 200).drehung).toBe(10);
    expect(drehen({ ...bild, drehung: 175 }, 200).drehung).toBe(-175);
  });
  it('rastet an der Flaechenmitte ein', () => {
    const r = einrasten({ ...bild, x: 303, y: 197 }, { w: 200, h: 100 }, [], 'quer');
    expect(r).toMatchObject({ x: 300, y: 200 });
    expect(r.linien).toEqual(expect.arrayContaining([{ achse: 'x', wert: 300 }, { achse: 'y', wert: 200 }]));
  });
  it('rastet nicht bei grossem Abstand', () => expect(einrasten({ ...bild, x: 250 }, { w: 10, h: 10 }, [], 'quer').x).toBe(250));
  it('handy-hinweis', () => {
    expect(hinweise({ ...neueGestaltung('#FFFFFF'), ebenen: [{ ...text, groesse: 18 }] })).toEqual(['Text „Hallo“ ist am Handy unter 12 px']);
    expect(hinweise({ ...neueGestaltung('#FFFFFF'), ebenen: [text] })).toEqual([]);
  });
  it('verlauf zurueck und vor', () => {
    const v = verlauf(1); v.setzen(2); v.setzen(3);
    expect(v.zurueck()).toBe(true); expect(v.jetzt()).toBe(2);
    expect(v.vor()).toBe(true); expect(v.jetzt()).toBe(3); expect(v.vor()).toBe(false);
  });
  it('neue id kollidiert nicht', () => {
    const ids = Array.from({ length: 50 }, () => neueId(['e-000000']));
    expect(ids.every((i) => /^e-[0-9a-f]{6}$/.test(i) && i !== 'e-000000')).toBe(true);
  });
  it('schema gleicht python-grenzen', () => {
    const g = { ...neueGestaltung('#FFFFFF'), ebenen: [text, bild] };
    expect(GestaltungSchema.safeParse(g).success).toBe(true);
    expect(GestaltungSchema.safeParse({ ...g, format: 'a4' }).success).toBe(false);
    expect(GestaltungSchema.safeParse({ ...g, ebenen: [{ ...text, text: 'x'.repeat(201) }] }).success).toBe(false);
    expect(GestaltungSchema.safeParse({ ...g, ebenen: Array.from({ length: 21 }, (_, i) => ({ ...bild, id: 'e' + i })) }).success).toBe(false);
    expect(GestaltungSchema.safeParse({ ...g, ebenen: [{ ...text, schrift: 'arial' }] }).success).toBe(false);
  });
});
```

- [ ] **Step 2: `npx vitest run src/gestaltung.test.ts` – FAIL.**
- [ ] **Step 3: Implementieren** (`skalieren`: Faktor `Math.pow(1.1, -deltaY / 100)`; `drehen`: `((d + deltaY/20 + 180) % 360 + 360) % 360 - 180`, auf ganze Grad runden; `einrasten`: Kandidaten x ∈ {0, 300, 600} ∪ Mitten anderer, y ∈ {0, hoehe/2, hoehe} ∪ Mitten anderer, nächster Kandidat innerhalb Schwelle gewinnt; `verlauf`: Array + Index, `setzen` schneidet Zukunft ab, max. 100 Einträge). `GestaltungSchema` mit `SCHRIFT_IDS` aus `schemata.ts` (Schnitt-Prüfung gegen eine Tabelle `SCHNITTE: Record<SchriftId, Array<[number, boolean]>>`, identisch zu `claw/schriften.py` REGISTER – Werte aus Interfaces der Spec/Plan-Tabelle: cormorant [400,n],[400,i]; dm-sans [400,n],[700,n]; playfair [900,n]; poppins [400,n],[600,n],[700,n]; young-serif [400,n]; manrope [300,n],[400,n],[700,n]; bodoni [500,n],[500,i]; montserrat [400,n],[600,n]; josefin [300,n],[700,n]; oxanium [600,n],[700,n]; rajdhani [500,n],[600,n]).
- [ ] **Step 4: vitest komplett + `npx tsc --noEmit` – PASS.**
- [ ] **Step 5: Commit** – `feat(editor): Gestaltungs-Modell, Zoom-, Scroll- und Einrast-Mathematik`.

### Task 7: Editor – Gestaltungsfenster (Framer-Stil) und Einbindung (SC)

**Files:**
- Create: `editor/src/App/Gestaltung/{GestaltungFenster.tsx, Flaeche.tsx, EbenenListe.tsx, Eigenschaften.tsx, gestaltungStil.ts}`
- Modify: `editor/src/documents/blocks/helpers/EditorChildrenIds/AddBlockMenu/buttons.tsx` (Eintrag „Gestaltungsfläche“), `ImageSidebarPanel.tsx` (Knopf „Gestalten“, Bildaufträge bei Flächen ausblenden), `editor/src/bildfeld.ts` (`freistellbar`/`istPlatz` → false bei `gestaltung`), `editor/src/pult.ts` (`gestaltungRechnen`), `editor/src/pultZustand.ts` (`gestaltungOffen: string | null`), `editor/src/App/index.tsx` (Fenster rendern)
- Test: `editor/src/bildfeld.test.ts` (Fälle), `editor/src/pult.gestaltung.test.ts`, `sales-mcp/tests/test_editor_paket.py` (Nachweis-Strings)

**Interfaces:**
- Consumes: Task 6 (`gestaltung.ts`, `GestaltungSchema`), Task 5 (`gestaltung_url`).
- Produces:
  - `pult.ts`: `export async function gestaltungRechnen(s: Start, g: Gestaltung): Promise<{ ok: true; url: string; width: number; height: number; hinweise: string[] } | { ok: false; grund: string }>` (POST `s.gestaltung_url`, `X-CSRF`, Fehler aus `grund`, Netzfehler „Keine Verbindung zum Pult“).
  - `Start` erhält `gestaltung_url: string`.
  - `pultStore`: `gestaltungOffen: string | null` (Block-id), `gestaltungOeffnen(id)`, `gestaltungSchliessen()`.
  - Bild-Block aus „Gestaltungsfläche“: `{ type: 'Image', data: { style: { padding: { top: 16, bottom: 16, left: 24, right: 24 } }, props: { url: null, alt: 'Gestaltung', width: 600, height: 400, contentAlignment: 'middle', linkHref: null, gestaltung: neueGestaltung(<canvasColor des Dokuments oder '#FFFFFF'>) } } }`; nach dem Einfügen öffnet sich das Fenster.

**Bedienung und Aussehen (verbindlich, Spec §3):**
- Vollbild-Overlay (`position: fixed; inset: 0; z-index` über MUI-Drawer), Farben aus `gestaltungStil.ts` = Global-Constraints-Palette; Kopfleiste 56 px; Spalten links 240 px, rechts 320 px, Mitte flexibel; 8-px-Raster; Übergänge `150ms ease-out`.
- Kopfleiste: „← Zurück zum Newsletter“, Format-Segmente (Quer 3:2 · Quadrat · Hoch 4:5 · Banner 3:1), Hintergrund-Farbfeld (Ladenfarben = Farben aus `root.data` + bereits benutzte Farben als Vorschläge), „Exportieren…“ (bleibt in Teil 1 deaktiviert mit Tooltip „Kommt mit dem Assistenten“ – Task 14 aktiviert ihn).
- Fläche: DOM-Vorschau, `transform: scale(zoom)`; Ebenen `position:absolute; left:x; top:y; transform: translate(-50%,-50%) rotate(<drehung>deg)`; Bild `width: breite`; Text `white-space: pre; font-family: schriftFamilie(id); font-weight; font-style; font-size: groesse px; line-height: zeilenabstand; color; text-align`. Bilder über `ANZEIGE + name`. Auswahl: 1-px-Akzentrahmen + 4 Eckgriffe (nur Anzeige; Größe ändert Scrollrad); Hilfslinien als 1-px-Akzentlinien beim Ziehen.
- Eingaben: Pointer-Drag (Pointer Capture) verschiebt + `einrasten`; `wheel` mit `preventDefault` (passive: false) skaliert die Auswahl, mit Shift dreht; Pfeiltasten 1/10; Entf löscht; Doppelklick auf Text ⇒ Textfeld im Eigenschaften-Panel fokussiert; Strg+Z/Strg+Y über `verlauf`.
- Ebenenliste: oberste zuerst, Drag zum Umsortieren (native HTML5 DnD), Auge (blendet nur in der Fenster-Ansicht aus; gespeichert und gerechnet werden immer alle Ebenen), Löschen; „+ Bild“ öffnet Medienauswahl (`medienListe`, freigestellte `*-frei.png` zuerst), „+ Text“ legt Text an (Schrift = Anzeigeschrift des Newsletters aus `root.data.schriften.anzeige` oder `playfair`, Schnitt = erster vorhandener, Größe 48, Farbe = `root.data.textColor` oder `#1C1B18`, Mitte der Fläche).
- Eigenschaften: Bild: Breite, Drehung, Position; Text: Text (mehrzeilig, Zähler x/200), Schrift (11 IDs, Vorschau in eigener Schrift), Schnitt (nur vorhandene), Größe, Farbe, Ausrichtung, Zeilenabstand, Drehung, Position. Alt-Text der Fläche (Pflicht) unten im Panel.
- Hinweise (`hinweise(g)`) unter der Fläche als dezente Warnzeilen.
- „Zurück zum Newsletter“: `GestaltungSchema.parse`; `gestaltungRechnen`; bei `ok`: Block-Props `{ gestaltung, url, width, height }` per `setData` setzen und Hinweise des Servers als Meldung zeigen; bei Fehler Fenster offen lassen und Grund anzeigen.
- `bildfeld.ts`: `freistellbar(props)` und `istPlatz(props)` liefern `false`, wenn `props.gestaltung` ein Objekt ist; `ImageSidebarPanel` zeigt bei Flächen nur „Gestalten“ + Alt-Text.

- [ ] **Step 1: Failing tests:** `bildfeld.test.ts` – `freistellbar({url:'medien:gs-aaaaaaaaaaaa.jpg', width:600, height:400, gestaltung:{…}})` ⇒ `false`, `istPlatz(…)` ⇒ `false`. `pult.gestaltung.test.ts` – `gestaltungRechnen` mit gemocktem `fetch` (`vi.stubGlobal('fetch', …)`): sendet POST an `gestaltung_url` mit `X-CSRF` und Body `{gestaltung}`; 422 `{grund:'Bild x fehlt in den Medien'}` ⇒ `{ok:false, grund:'Bild x fehlt in den Medien'}`; `fetch` wirft ⇒ `{ok:false, grund:'Keine Verbindung zum Pult'}`. `test_editor_paket.py` – neue Funktion `test_paket_kennt_gestaltung`: `editor.js` enthält „Gestaltungsfläche“, „Zurück zum Newsletter“, „am Handy unter 12 px“ und `gestaltung_url`.
- [ ] **Step 2: Run – FAIL.**
- [ ] **Step 3: Implementieren** (Komponenten wie oben; keine `any`; strikte Typen).
- [ ] **Step 4:** `npx vitest run`, `npx tsc --noEmit`, `npm run build`, dann `test_editor_paket.py` + `test_editor_seite.py` – PASS.
- [ ] **Step 5: Sichtprüfung:** sales-ui lokal ist nicht nötig – mit `npx vite` (dev) und einer statischen Fixture-Seite reicht ein Screenshot nicht; stattdessen im Bericht die Komponentenstruktur und die verwendeten Stilwerte auflisten. (Die echte Sichtabnahme macht Task 15.)
- [ ] **Step 6: Commit** – `feat(editor): Gestaltungsfenster im Framer-Stil mit Ebenen, Ziehen, Scrollrad und Einrasten` (inkl. Bundle).

---

# Teil 2 – Gestaltungs-Agent und Export (D)

### Task 8: Agent-Werkzeuge – Änderungen prüfen und anwenden (MOS, rein)

**Files:**
- Create: `claw/agent_werkzeuge.py`
- Test: `claw/tests/test_agent_werkzeuge.py`

**Interfaces:**
- Consumes: `gestaltung.pruefen`, `gestaltung.hoehe`, `gestaltung.umformatieren` (nicht nötig), `bildplaetze.finde`.
- Produces:
```python
class WerkzeugFehler(ValueError): ...
WERKZEUGE: tuple[str, ...] = ("block_einfuegen", "block_aendern", "block_verschieben", "block_loeschen", "farben_setzen",
    "flaeche_anlegen", "ebene_hinzufuegen", "ebene_aendern", "ebene_reihenfolge", "ebene_loeschen", "format_setzen",
    "hintergrund_setzen", "bild_erzeugen", "bild_freistellen", "bild_aus_medien", "entwurf_speichern", "export_vorschlagen")
@dataclass
class Ergebnis:
    bloecke: dict                     # neue Kopie (Original unverändert)
    geaendert: bool                   # irgendeine Block-Änderung
    bildauftraege: list[dict]         # {"platz": str, "modus": "neu"|"freistellen", "hinweis": str}
    export_vorschlag: dict | None     # {"newsletter": bool, "flaechen": list[str]}
    notiz: str                        # aus entwurf_speichern ('' sonst)
def anwenden(dok: dict, aenderungen: list, medien: set[str]) -> Ergebnis
```
- Jede Änderung ist `{"werkzeug": <name>, ...parameter}`; Parameter wie Spec §4.2. Regeln:
  - `block_einfuegen {typ ∈ (Heading, Text, Button, Image, Divider, Spacer), nach: id|null, daten: {style?, props?}}` – neue id `agent-<6hex>`; `nach=null` ⇒ ans Ende von `root.data.childrenIds`; sonst direkt hinter `nach` in dessen Elternliste (root / Container `props.childrenIds` / ColumnsContainer `props.columns[i].childrenIds`).
  - `block_aendern {id, props?, style?}` – flach mergen; `type` unveränderlich; bei Flächen sind `props.gestaltung`, `props.url`, `props.width`, `props.height` gesperrt (`WerkzeugFehler("Fläche nur mit den Flächen-Werkzeugen ändern")`); `root` nur über `farben_setzen`.
  - `block_verschieben {id, nach}`, `block_loeschen {id}` (mit allen Nachfahren; `root` verboten).
  - `farben_setzen {backdropColor?, canvasColor?, textColor?}` – nur diese drei Schlüssel, `#RRGGBB`.
  - `flaeche_anlegen {nach, format, hintergrund, alt}` – Image-Block wie Task 7 (url `None`, height = `hoehe(format)`); gibt die neue id implizit über `bloecke` zurück; Ergebnis-Notiz der ids nicht nötig – der Agent darf in DERSELBEN Antwort `"flaeche": "neu:1"` verwenden, um die n-te neu angelegte Fläche anzusprechen.
  - `ebene_hinzufuegen {flaeche, ebene}` (id optional ⇒ `e-<6hex>`; `quelle` muss in `medien` liegen), `ebene_aendern {flaeche, id, felder}` (`id`/`art` unveränderlich), `ebene_reihenfolge {flaeche, ids}` (Permutation, unten → oben), `ebene_loeschen {flaeche, id}`, `format_setzen {flaeche, format}` (setzt auch `props.height`), `hintergrund_setzen {flaeche, farbe}`; nach jeder Flächen-Änderung `gestaltung.pruefen` (Fehler ⇒ `WerkzeugFehler` mit Grund).
  - `bild_erzeugen {platz, hinweis}` / `bild_freistellen {platz}` – `platz` muss in `bildplaetze.finde(bloecke)` vorkommen (nach den Block-Änderungen); landen in `bildauftraege`.
  - `bild_aus_medien {platz, quelle}` – setzt `props.url` eines Bildplatzes (Quelle in `medien`).
  - `entwurf_speichern {notiz}` (≤ 200), `export_vorschlagen {newsletter: bool, flaechen: [id|"alle"]}`.
  - Unbekanntes Werkzeug, fehlende/zusätzliche Parameter, falsche Typen ⇒ `WerkzeugFehler("<werkzeug>: <Grund>")`. Höchstens 40 Änderungen je Antwort.

- [ ] **Step 1: Failing tests** – je Werkzeug mindestens ein Erfolgs- und ein Fehlerfall; dazu: Original-`dok` bleibt unverändert (`copy.deepcopy` vergleichen); `neu:1`-Verweis; Fläche über `block_aendern` gesperrt; Nachfahren werden mitgelöscht; 41 Änderungen ⇒ Fehler; `bild_erzeugen` auf Fläche ⇒ Fehler „kein Bildplatz“. Basisdokument im Test:

```python
DOK = {"root": {"type": "EmailLayout", "data": {"backdropColor": "#F5F4F0", "canvasColor": "#FFFFFF", "textColor": "#1C1B18",
                 "childrenIds": ["kopf", "held", "text1"]}},
       "kopf": {"type": "Heading", "data": {"style": {}, "props": {"text": "Oktober", "level": "h1"}}},
       "held": {"type": "Image", "data": {"style": {}, "props": {"url": "medien:nl-12345678-held.jpg", "alt": "", "width": 600, "height": 300}}},
       "text1": {"type": "Text", "data": {"style": {}, "props": {"text": "Hallo"}}}}
MEDIEN = {"nl-12345678-held.jpg", "person-frei.png"}
```
- [ ] **Step 2: FAIL. Step 3: Implementieren. Step 4: PASS.**
- [ ] **Step 5: Commit** – `feat(marketing): Werkzeuge des Gestaltungs-Agenten pruefen und anwenden`.

### Task 9: Agent-Prompt und Antwort lesen (MOS, rein)

**Files:**
- Create: `claw/agent_prompt.py`
- Test: `claw/tests/test_agent_prompt.py`

**Interfaces:**
- Consumes: `agent_werkzeuge.WERKZEUGE`, `schriften.REGISTER`.
- Produces:
```python
SYSTEM: str            # Rolle, Werkzeugliste mit Parametern, Gestaltungsregeln (Spec §4.3), Antwortformat
class AntwortFehler(ValueError): ...
def nutzer_text(auftrag: dict, medien: list[str]) -> str   # kompakter Kontext: Nachricht, kontext, Blöcke (JSON), Farben aus root.data, Schriften des Newsletters, Medienliste (max 200, ohne gs-*), Verlauf
def antwort_lesen(text: str) -> dict                        # {"antwort": str (1..2000), "aenderungen": list}
def korrektur_text(fehler: str) -> str                      # Folge-Nachricht für den einen Korrekturversuch
```
- `SYSTEM` muss enthalten: „Antworte mit genau einem JSON-Objekt“, alle 17 Werkzeugnamen, die Regeln „eine dominante Aussage je Fläche“, „höchstens zwei Schriften“, „Farben nur aus den Ladenfarben“, „Text auf Flächen mindestens 22“, „Exportiere nie selbst – schlage es mit export_vorschlagen vor“, „Antworte auf Deutsch, kurz, per Du“.
- `antwort_lesen`: entfernt Codezäune (```json … ```), sucht das einzige top-level JSON-Objekt (Klammerzählung mit String-Erkennung); keins oder mehrere ⇒ `AntwortFehler("Kein einzelnes JSON-Objekt")`; Felder prüfen (`antwort` nicht leer, `aenderungen` Liste, Standard `[]`).

- [ ] **Step 1: Failing tests:** reines JSON; mit ```json-Zaun; mit Vor- und Nachtext; zwei Objekte ⇒ Fehler; kaputtes JSON ⇒ Fehler; `antwort` fehlt ⇒ Fehler; Klammern in Strings (`"antwort": "a { b"`) brechen nichts; `SYSTEM` enthält alle Werkzeugnamen; `nutzer_text` enthält keine `gs-`-Namen und höchstens 200 Medien.
- [ ] **Step 2–4: FAIL → implementieren → PASS.**
- [ ] **Step 5: Commit** – `feat(marketing): Prompt und Antwortleser des Gestaltungs-Agenten`.

### Task 10: Chat- und Export-Routen der marketing-api (MOS)

**Files:**
- Create: `api/chat.py` (`pult_router` Prefix `/api/pult`, `arbeiter_router` Prefix `/api/chat/arbeiter`)
- Modify: `api/server.py` (beide einhängen; Arbeiter-Router wie `/api/bilder/arbeiter` von der globalen X-API-Key-Middleware ausnehmen – Stelle in server.py:119 nachsehen und gleich behandeln)
- Test: `tests/test_chat_api.py`

**Interfaces:**
- Consumes: SQL aus Task 3; `gestaltung` (Task 2), `api.gestaltung.gestaltungen_rechnen/quellen` (Task 4), `bilder._bild_schluessel`, `bilder._ordner`, `bilder._anlegen` (für Bildaufträge mit Urheber `agent`), `schoenheit.bloecke_pruefen/urteil`.
- Produces:
  - Pult (X-Pult-Key):
    - `POST /api/pult/inhalte/{iid}/chat {nachricht, kontext}` → `{auftrag}`; 422 Grund (z. B. „Der Assistent arbeitet gerade“).
    - `GET /api/pult/inhalte/{iid}/chat` → ruft `pult_chat_aufraeumen(i)`, liefert `{laeuft: bool, verlauf: [{id, art, nachricht, antwort, status, hinweise, ergebnis, fassung_vorher, fassung_nachher, erstellt_am}] (letzte 30, älteste zuerst)}`.
    - `POST /api/pult/inhalte/{iid}/chat/rueckgaengig {auftrag}` → nimmt `fassung_vorher` dieses fertigen Auftrags, lädt deren `bloecke` und speichert sie über `pult_bloecke_speichern(i, neueste, betreff, vt, bloecke, 'betreiber', false)` → `{fassung}`.
    - `POST /api/pult/inhalte/{iid}/export/vorschau {flaechen: [block-id]}` → je Fläche und Gerät die umformatierte Gestaltung gerechnet als Entwurfsbild: `{flaechen: {<id>: {handy: url, tablet: url, pc: url}}}`.
    - `POST /api/pult/inhalte/{iid}/export {newsletter: bool, flaechen: [block-id], bestaetigt: true}` → ohne `bestaetigt: true` 422 „Export nur mit Bestätigung“; Flächen: sofort auf der VM rechnen (`bild_rechnen` auf `umformatieren(g, {"handy":"hoch","tablet":"quadrat","pc":"quer"}[gerät])`) und als sichtbare Datei `<slug>-<flaeche>-<gerät>.jpg` speichern; Newsletter: `pult_chat_anlegen(i,'export','', {"geraete":["handy","tablet","pc"], "slug": <slug>})`. Antwort `{dateien: [name], auftrag: id|null}`.
    - Slug: Titel des Inhalts, klein, Umlaute → ae/oe/ue/ss, alles andere → `-`, mehrfach `-` zusammenfassen, max. 60; leer ⇒ `newsletter`. Kollision: `-2`, `-3` …
  - Arbeiter (X-Bild-Key):
    - `POST /api/chat/arbeiter/naechster` → `{auftrag: <jsonb aus pult_chat_naechster> + "medien": [namen ohne gs-*, max 500]}` oder `{auftrag: null}`; Frist `5 minutes`.
    - `POST /api/chat/arbeiter/{aid}/weiter` → `{ok}`.
    - `POST /api/chat/arbeiter/{aid}/fertig {antwort, bloecke|null, bildauftraege: [...], export_vorschlag|null, notiz}` → VM: wenn `bloecke`: `gestaltungen_rechnen` (Fehler ⇒ `pult_chat_zurueck` mit „Das habe ich nicht umsetzen können: <Grund>“ und 200 `{status:"fehler"}`), `pult_bloecke_fehler`-Fehler ⇒ ebenso; `schoenheit.bloecke_pruefen` ⇒ Befunde als `hinweise`; `pult_chat_fertig(...)` mit `ergebnis = {export_vorschlag, notiz, bildauftraege: [ids|grund]}`; danach Bildaufträge über `bilder._anlegen(i, {...}, "agent")` (Fehler je Auftrag als Hinweis, nicht fatal). Antwort `{fassung, hinweise}`.
    - `POST /api/chat/arbeiter/{aid}/zurueck {antwort}` → `{status}`.
    - `GET /api/chat/arbeiter/{aid}/medien/{name}` → Datei aus `quellen()` (nur wenn Auftrag `in_arbeit`; Namen-Regex wie die DB-URL-Regex ohne `medien:`), sonst 404.
    - `POST /api/chat/arbeiter/{aid}/datei?name=<slug>-<gerät>.jpg` (roher JPEG-Body ≤ 4 MB, `_jpeg_pruefen`-ähnlich, max. Kante 1200×20000) → speichert sichtbar mit Kollisions-Suffix, gibt `{name}`.

- [ ] **Step 1: Failing tests** (FalscheDB wie Task 4): Anlegen reicht SQL `marketing.pult_chat_anlegen(` durch; DB-Fehler „Der Assistent arbeitet gerade“ ⇒ 422 mit Grund; GET ruft zuerst `pult_chat_aufraeumen(`; Rückgängig nimmt `fassung_vorher`; Export ohne Bestätigung ⇒ 422; Export Fläche schreibt drei Dateien mit Slug (`Oktober-Angebot!` ⇒ `oktober-angebot-<id>-handy.jpg` …) und hängt bei Kollision `-2` an; Arbeiter ohne/mit falschem `X-Bild-Key` ⇒ 401; `fertig` mit ungültiger Gestaltung ⇒ `pult_chat_zurueck(` mit Grund; `fertig` gültig ⇒ `pult_chat_fertig(` mit `'agent'`-Fassung und anschließend `pult_bild_auftrag(` je Bildauftrag; `medien/{name}` liefert Datei, `../x` ⇒ 404; `datei` > 4 MB ⇒ 422; Review Focus 4: zweites Anlegen während laufendem Auftrag ⇒ 422 „Der Assistent arbeitet gerade“.
- [ ] **Step 2–4: FAIL → implementieren → PASS** (+ `tests/test_bilder_api.py`, `tests/test_pult_api.py`).
- [ ] **Step 5: Commit** – `feat(marketing): Chat-, Rueckgaengig- und Export-Routen fuer den Gestaltungs-Agenten`.

### Task 11: Chat-Arbeiter am PC (MOS)

**Files:**
- Create: `workers/chat_worker.py`
- Modify: `claw/scripts/marketing-dienste-starten.ps1` (Eintrag `marketing_chat_arbeiter`, Port 8134)
- Test: `tests/test_chat_worker.py`

**Interfaces:**
- Consumes: Arbeiter-Routen (Task 10), `agent_prompt` (Task 9), `agent_werkzeuge` (Task 8); aus `bild_worker`: `umgebung_laden`, `tls_kontext`, `ApiFehler`, `_Gesundheit`-Muster.
- Produces:
```python
PORT = 8134; TAKT_S = 3; SHIM_BIS_S = 180; LLM_ZEITLIMIT_S = 300
LLM_URL = os.environ.get("MARKETING_CHAT_LLM_URL", "http://127.0.0.1:8117/v1")
MODELL = os.environ.get("MARKETING_CHAT_MODELL", "claude-code-sonnet")
class ChatApi:  # basis + "/api/chat/arbeiter", X-Bild-Key
    def naechster(self) -> dict | None; def weiter(self, aid) -> bool
    def fertig(self, aid, daten: dict) -> dict; def zurueck(self, aid, antwort: str) -> str
    def medium(self, aid, name) -> bytes | None; def datei(self, aid, name, roh: bytes) -> str
def frage(system: str, nachrichten: list[dict], url=LLM_URL, modell=MODELL) -> str   # wirft LlmFehler
def chat_bearbeiten(api, auftrag, fragen=frage, uhr=time.monotonic, schlafen=time.sleep) -> str  # "fertig"|"fehler"
def ein_durchlauf(api, fragen=frage, exportieren=None, uhr=time.monotonic, schlafen=time.sleep) -> str  # "leer"|"fertig"|"fehler"
```
- Ablauf `chat_bearbeiten`: Nachrichten = `[user: nutzer_text(auftrag, auftrag["medien"])]`; `fragen` mit Wiederholung bei `LlmFehler` alle 10 s bis `SHIM_BIS_S` (vorher `api.weiter`) – danach `zurueck("Der Assistent ist gerade nicht erreichbar")`; `antwort_lesen` + `anwenden(auftrag["bloecke"], aenderungen, set(auftrag["medien"]))`; bei `AntwortFehler`/`WerkzeugFehler` genau EIN Korrekturversuch (Assistent-Antwort + `korrektur_text(fehler)` anhängen), danach `zurueck("Das habe ich nicht umsetzen können: <Grund>")`; Erfolg ⇒ `fertig(aid, {antwort, bloecke: ergebnis.bloecke if ergebnis.geaendert else None, bildauftraege, export_vorschlag, notiz})`.
- `ein_durchlauf`: `naechster`; `art == "export"` ⇒ `exportieren(api, auftrag)` (Task 12; Standard `export_worker.exportieren` lazy importiert); sonst `chat_bearbeiten`.
- `main()` wie `bild_worker.main` (Gesundheits-Thread auf 8134, Schleife mit `TAKT_S`).
- ps1-Eintrag (verbatim Stil): `@{ Name = 'marketing_chat_arbeiter'; Port = 8134; Args = @('-u', '-m', 'spaces.marketing.workers.chat_worker'); Cwd = $OsRoot; Env = @{}; Was = 'Chat-Arbeiter (Gestaltungs-Agent, fragt Claude ueber den Shim :8117)' }`.

- [ ] **Step 1: Failing tests** mit Fake-Api (protokolliert Aufrufe) und Fake-`fragen`: gültige Antwort ⇒ `fertig` mit Blöcken; Antwort nur Text ohne Änderungen ⇒ `bloecke: None`; ungültiges JSON, dann gültiges ⇒ zweite Frage enthält die Korrektur, Ergebnis `fertig`; zweimal ungültig ⇒ `zurueck` mit „Das habe ich nicht umsetzen können“; Werkzeugfehler analog; Shim wirft dauerhaft ⇒ mit Fake-Uhr nach 180 s `zurueck("Der Assistent ist gerade nicht erreichbar")`, dazwischen `weiter` aufgerufen; Export-Auftrag ruft `exportieren`; `frage` baut den Request `{"model": MODELL, "messages": [{"role":"system",...}, ...]}` an `LLM_URL + "/chat/completions"` (mit `monkeypatch` auf `urllib.request.urlopen`).
- [ ] **Step 2–4: FAIL → implementieren → PASS.**
- [ ] **Step 5: Commit** – `feat(marketing): Chat-Arbeiter am PC fragt Claude ueber den Marketing-Shim`.

### Task 12: Export-Arbeiter – Newsletter je Gerät mit Playwright (MOS)

**Files:**
- Create: `workers/export_worker.py`
- Test: `tests/test_export_worker.py`

**Interfaces:**
- Consumes: `ChatApi.medium/datei/fertig/zurueck` (Task 11), `bloecke_mjml.rendern`, `schriften.REGISTER`, `gestaltung.ORDNER_SCHRIFTEN`.
- Produces:
```python
GERAETE = {"handy": 375, "tablet": 768, "pc": 1200}
BASIS = "https://export.vibemind.invalid/"
def html_bauen(auftrag: dict) -> str     # rendern(bloecke, betreff, vorschautext, pflichtteil, bild_basis=BASIS+"medien/", schrift_basis=BASIS+"schrift/")
def schriften_css() -> str               # @font-face je REGISTER-Eintrag/Datei, src: url(<id>-<gewicht>-<stil>.woff2)
def jpeg_passend(png: bytes, grenze=4*1024*1024) -> bytes   # PNG→JPEG, Qualität 88 in 6er-Schritten bis 52, danach Fehler
def exportieren(api, auftrag, browser_starten=None) -> str  # "fertig"|"fehler"
```
- `exportieren`: Playwright (sync API, Chromium headless) – `page.route(BASIS + "**", handler)`: `medien/<name>` ⇒ `api.medium(aid, name)`, `schrift/schriften.css` ⇒ `schriften_css()`, `schrift/<datei>.woff2` ⇒ Datei aus `ORDNER_SCHRIFTEN`; alles andere `route.abort()`. Je Gerät: Viewport-Breite, `set_content(html, wait_until="networkidle")`, `screenshot(full_page=True, type="png")`, `jpeg_passend`, `api.datei(aid, f"{slug}-{geraet}.jpg", jpeg)` (Slug kommt vom Auftrag: `auftrag["kontext"]["slug"]` – Task 10 legt ihn beim Anlegen in `kontext` ab). Danach `api.fertig(aid, {antwort: "Export fertig: <namen>", bloecke: None, bildauftraege: [], export_vorschlag: None, notiz: ""})`. Fehler ⇒ `api.zurueck(aid, "Export nicht möglich: <Grund>")`.
- `browser_starten` injizierbar (Test-Fake mit `new_page/route/set_content/screenshot`).

- [ ] **Step 1: Failing tests:** `schriften_css` enthält 22 `@font-face`; `jpeg_passend` verkleinert großes Rauschen unter 4 MB bzw. wirft; `exportieren` mit Fake-Browser: drei Uploads mit `-handy/-tablet/-pc.jpg` in dieser Reihenfolge, Viewport-Breiten 375/768/1200, Route-Handler liefert Medien über `api.medium`, fremde URL ⇒ abort; Fehler beim Screenshot ⇒ `zurueck` mit „Export nicht möglich“. Ein echter Playwright-Lauf ist NICHT Teil der Unit-Tests (Task 15).
- [ ] **Step 2–4: FAIL → implementieren → PASS.**
- [ ] **Step 5: Commit** – `feat(marketing): Newsletter-Export je Geraet mit Playwright am PC`.

### Task 13: sales-ui – Chat, Rückgängig, Export durchreichen (SC)

**Files:**
- Modify: `sales-mcp/ui_editor.py`
- Test: `sales-mcp/tests/test_editor_seite.py`

**Interfaces:**
- Consumes: Pult-Routen aus Task 10.
- Produces (alle `@ui._gesichert_seite`; schreibende mit CSRF):
  - `POST /marketing/editor/{iid}/chat {nachricht (1..2000), kontext (Objekt ≤ 4 KB)}` → `{auftrag}`
  - `GET /marketing/editor/{iid}/chat.json` → Pult-GET 1:1
  - `POST /marketing/editor/{iid}/chat/rueckgaengig {auftrag}` → `{fassung}`
  - `POST /marketing/editor/{iid}/export/vorschau {flaechen}` → Pult 1:1, Entwurfsbild-URLs `medien:gs-…` werden für die Anzeige NICHT umgeschrieben (der Editor macht `zurAnzeige`).
  - `POST /marketing/editor/{iid}/export {newsletter, flaechen, bestaetigt}` → Pult 1:1
  - Startdaten-Schlüssel: `chat_url`, `chat_stand_url`, `chat_rueckgaengig_url`, `export_vorschau_url`, `export_url`.
  - Fehlerabbildung wie `editor_bild`: `abgelehnt` ⇒ 422 mit Grund; sonst 503 „Assistent gerade nicht erreichbar“.
- [ ] **Step 1: Failing tests** (Fake `marketing_pult.anfrage`): je Route Pfad/Methode/Nutzlast; CSRF fehlt ⇒ 403; Nachricht leer oder > 2000 ⇒ 422; `kontext` kein Objekt ⇒ 422; Export ohne `bestaetigt is True` ⇒ 422 „Export nur mit Bestätigung“ (schon in sales-ui); Startdaten enthalten alle fünf Schlüssel.
- [ ] **Step 2–4: FAIL → implementieren → PASS** (`test_editor_seite.py`, `test_marketing_pult.py`).
- [ ] **Step 5: Commit** – `feat(ui): Chat, Rueckgaengig und Export fuer den Gestaltungs-Agenten durchreichen`.

### Task 14: Editor – Chat-Leiste, Sperre, Rückgängig, Export-Dialog (SC)

**Files:**
- Create: `editor/src/chat.ts`, `editor/src/chat.test.ts`, `editor/src/App/Chat/ChatLeiste.tsx`, `editor/src/App/Export/ExportDialog.tsx`
- Modify: `editor/src/pultZustand.ts` (`chat`-Zustand + Abfrage alle 2 s solange `laeuft`), `editor/src/App/index.tsx` (Chat in rechter Seitenleiste, einklappbar), `editor/src/App/Gestaltung/GestaltungFenster.tsx` (Chat unter Eigenschaften, „Exportieren…“ aktiv), `editor/src/App/PultLeiste.tsx` (Speichern gesperrt während `laeuft`, Hinweis „Agent arbeitet …“), `sales-mcp/tests/test_editor_paket.py`

**Interfaces:**
- Consumes: Startdaten aus Task 13.
- Produces (`chat.ts`, rein + fetch):
```ts
export type ChatEintrag = { id: string; art: 'chat' | 'export'; nachricht: string; antwort: string; status: 'offen'|'in_arbeit'|'fertig'|'fehler';
  hinweise: string[]; ergebnis: { export_vorschlag?: { newsletter: boolean; flaechen: string[] } | null; notiz?: string };
  fassung_vorher: number | null; fassung_nachher: number | null; erstellt_am: string };
export async function chatSenden(s: Start, nachricht: string, kontext: { fenster: string; auswahl: string | null }): Promise<{ok:true; auftrag:string}|{ok:false; grund:string}>;
export async function chatLaden(s: Start): Promise<{ laeuft: boolean; verlauf: ChatEintrag[] } | null>;
export async function rueckgaengig(s: Start, auftrag: string): Promise<{ok:true; fassung:number}|{ok:false; grund:string}>;
export async function exportVorschau(s: Start, flaechen: string[]): Promise<…>;
export async function exportieren(s: Start, auswahl: { newsletter: boolean; flaechen: string[] }): Promise<{ok:true; dateien:string[]; auftrag:string|null}|{ok:false; grund:string}>;
export function neueFassungNachChat(vorher: ChatEintrag[], nachher: ChatEintrag[]): number | null; // fassung_nachher eines frisch fertigen Eintrags
export function exportVorschlag(e: ChatEintrag): { newsletter: boolean; flaechen: string[] } | null;
```
- Verhalten: Senden mit Enter (Shift+Enter = Zeile); während `laeuft` ist das Dokument schreibgeschützt (Overlay „Agent arbeitet …“ über dem Canvas, Speichern-Knopf deaktiviert); fertiger Eintrag mit neuer Fassung ⇒ dieselbe Neu-Laden-Logik wie `standAbfragen` (sessionStorage-Schleifenschutz übernehmen); jeder fertige Eintrag mit `fassung_nachher` zeigt „Rückgängig“; Hinweise des Agenten als dezente Liste unter der Antwort; `export_vorschlag` ⇒ Knopf „Exportieren…“ in der Antwort, öffnet den Dialog vorbelegt.
- Export-Dialog: Häkchen „Newsletter (Handy, Tablet, PC)“ und je Fläche; Vorschau der Flächen-Varianten (`exportVorschau`, 3 Bilder je Fläche); Dateinamen-Vorschau; Knopf „In Medien exportieren“ sendet `bestaetigt: true`; danach Liste der Dateien bzw. „Newsletter-Bilder werden am PC gerechnet – sie erscheinen gleich in den Medien“.
- Aussehen: Chat-Blasen im Stil des Gestaltungsfensters (Betreiber rechts, Akzentfläche; Agent links, Panelfläche), Eingabefeld unten fest, Schreib-Indikator (drei Punkte, 150-ms-Takt) während `laeuft`.

- [ ] **Step 1: Failing tests** (`chat.test.ts` mit `vi.stubGlobal('fetch')`): `chatSenden` sendet CSRF + Body; 422-Grund wird durchgereicht; `chatLaden` null bei Netzfehler; `neueFassungNachChat` erkennt den Übergang `in_arbeit → fertig` mit `fassung_nachher`; `exportVorschlag` liest `ergebnis.export_vorschlag`; `exportieren` sendet `bestaetigt: true`. `test_editor_paket.py`: neue Funktion `test_paket_kennt_assistenten` prüft „Agent arbeitet“, „In Medien exportieren“, „Rückgängig“, `chat_url`.
- [ ] **Step 2–4: FAIL → implementieren → vitest/tsc/build/Paket-Test PASS.**
- [ ] **Step 5: Commit** – `feat(editor): Chat mit dem Gestaltungs-Agenten, Sperre, Rueckgaengig und Export-Dialog` (inkl. Bundle).

### Task 15: Ausliefern (STOPP – nur nach ausdrücklicher Freigabe des Betreibers)

- [ ] **Step 1:** Claims: WORKBOARD (`C:\Users\User\Desktop\Vibemind_V1\WORKBOARD.md`) + `C:\Users\User\Desktop\secondbrain\00_Meta\002_Koordination_Live.md`, sofort committen.
- [ ] **Step 2:** Volle Tests: MOS `spaces/marketing` (bekannte unabhängige Rote benennen), SC `test_editor_*.py`, `test_marketing_pult.py`, `test_medien_*.py`, Editor vitest + tsc.
- [ ] **Step 3:** PC zuerst: `git restore --source=<neuer MOS-Stand> --worktree -- spaces/marketing` im Haupt-Checkout (vorher Hash-Vergleich gegen den letzten ausgelieferten Stand `972ebf4b`); Playwright-Chromium vorhanden prüfen (`python -m playwright install chromium` nur falls fehlt); Bild-Arbeiter neu starten; Chat-Arbeiter über `marketing-dienste-starten.ps1` starten; Shim :8117 und Port 8134 prüfen. ComfyUI NICHT beenden.
- [ ] **Step 4:** 060: Probe (ROLLBACK) → anwenden → `verify_060` per Probe.
- [ ] **Step 5:** Push MOS (bei bewegtem origin: Merge im Temp-Worktree) und SC; VM `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`. Prüfen, dass die marketing-api auf der VM Pillow ≥ 10 und die Schriftdateien im Checkout hat.
- [ ] **Step 6: Echter Lauf** in einem Probe-Newsletter: (a) Fläche von Hand bauen (freigestellte Person `nl-6c242352-streifen_bild3-frei.png` + Titel), speichern, Serverbild ansehen; (b) Chat: „Bau mir eine quadratische Fläche mit der Person rechts und dem Titel ‚Herbst im Laden‘ links oben“ ⇒ Fassung `agent`; (c) Chat: Einleitungstext umformulieren, danach Rückgängig; (d) Export bestätigen (Newsletter + eine Fläche) und die Dateien in den Medien ansehen; (e) Bildschirmfotos des Gestaltungsfensters und des Chats an den Betreiber zur Sichtabnahme.
- [ ] **Step 7:** Claims schließen, Memory (`project_marketing_api_auf_der_vm.md`) ergänzen, Ledger-Rulings berichten, SDD-Workspace löschen.
