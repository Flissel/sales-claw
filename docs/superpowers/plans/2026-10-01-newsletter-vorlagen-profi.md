# Newsletter-Vorlagen in Profi-Qualität (Baustein A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sieben hochwertige Newsletter-Vorlagen (studio, zeitung, firmenblatt, minimal, klassik, bildkopf, tech), die beim Anlegen automatisch Logo und Farben des Ladens übernehmen und im Editor, in der DB-Prüfung und im Renderer dieselben neuen Gestaltungsmittel verstehen.

**Architecture:** Neue Felder im bestehenden Blockformat (Email-Builder-JSON) werden in drei Schichten gleich eingeführt: Renderer `bloecke_mjml.py` (vibemind-os), DB-Prüfung `pult_bloecke_fehler` (Migration 058) und Editor-Schemata (sales-claw). Vorlagen tragen eine Rollen-Tabelle `root.data.rollen` (Pfad → Rolle) mit gültigen Musterfarben; „Neu aus Vorlage“ in der Marketing-API füllt die Rollen aus dem Standard-Layout des Ladens, legt Logo und tech-Grafiken als Dateien ab und übergibt das fertige Dokument der DB. sales-ui liefert selbst gehostete OFL-Schriften und Graustufen-Bilder aus.

**Tech Stack:** Python 3.11/3.12, FastAPI, mjml-python, Pillow, PostgreSQL/plpgsql (Supabase), Starlette (sales-ui), React + zod + @usewaypoint (Editor), Vite, vitest (neu, nur dev).

**Spec:** `docs/superpowers/specs/2026-10-01-newsletter-vorlagen-profi-design.md` (sales-claw, Commit `053db43`)

## Global Constraints

- Zwei Repos: **MOS** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent` (Branch `master`, Ordner `spaces/marketing`), **SC** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw` (Branch `feat/stufe-1-fundament`). Commits direkt auf diese Branches (Projektregel), nur eigene Dateien stagen, nie stashen, nie force-pushen, keine Hooks umgehen. Git über PowerShell.
- Kein KI-Modell auf der VM. Pillow-Zeichnen/Graustufen ist kein Modell und darf auf der VM laufen.
- Keine Google-Fonts-Einbindung (DSGVO): Schriften nur aus sales-ui `/marketing/schrift/…`. Alle Schriften unter SIL Open Font License, Lizenztexte liegen bei den Dateien.
- Keine Vorlage wird aus Canva kopiert; Platzhaltertexte sind für Läden geschrieben und als Platzhalter erkennbar („[Telefon]“, „[Website]“, „@[instagram]“).
- Farben im Blockformat immer `#rrggbb` (DB-Regel); Rollen stehen nie als `{…}` in Farbfeldern, sondern in `root.data.rollen`.
- Live-DB nur lesend bzw. per `python -m spaces.marketing.scripts.migration_probe <dateien>` (eine Transaktion + ROLLBACK). Migration 058 wird erst in Task 11 nach Freigabe angewendet.
- Mail-HTML jeder Vorlage < 102 KB (Gmail kürzt sonst).
- Kontrast: Fließtext ≥ 4,5 : 1, große Überschriften (≥ 24 px) und Knopftext ≥ 3 : 1 (WCAG, `schoenheit.kontrast`).
- Tests MOS: `cd <MOS> ; python -m pytest spaces/marketing -q -p no:cacheprovider`. Bekannte fremde Fehlschläge (nicht anfassen): `test_send_paranoid.py` (3), `test_cockpit_contract.py` (1), `test_formular_entwurf.py` (1).
- Tests SC: aus `sales-mcp`, mit Wegwerf-Postgres: `& "E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\venv-sales\Scripts\python.exe" -m pytest <dateien> -q -p no:cacheprovider` mit `$env:SALES_DB_URL="postgresql://postgres@127.0.0.1:55432/postgres"; $env:SALES_DB_SCHEMA="sales_test"`. Postgres starten: `& "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe" -D "E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\pgdata" -o "-p 55432" -l "<scratchpad>\pg.log" -w start` (danach wieder stoppen). Bekannte fremde Fehlschläge: `test_ui.py::test_anlegen_erzeugt_den_kontakt_mit_der_rufnummer_der_kennung`, `test_ui.py::test_anlegen_einer_bereits_aufgeloesten_lid_nimmt_die_gespeicherte_nummer`.
- Editor prüfen nur mit `cd <SC>\editor ; npx tsc --noEmit` (nie `npx --prefix …`), bauen mit `npm run build` (schreibt `sales-mcp/static/editor/*`).

## Review Focus

1. **Gelber/sehr heller Ladenakzent** (`#facc15`): Akzent als Text auf hellem Grund muss abgedunkelt werden, Text auf Akzentflächen wird fast schwarz – Test in Task 3.
2. **Laden ohne Standard-Layout oder ohne Logo**: „Neu“ darf nie scheitern; Ersatzpalette und Wortmarke – Tests in Task 3 und Task 5.
3. **Editor speichert einen Vorlagenblock nach Bearbeitung**: neue Felder (letterSpacing, ANZEIGE, Container-Hintergrund) dürfen nicht verschwinden – vitest in Task 9.
4. **Vorschau im Pult zeigt die Schriften**: sandboxed iframe braucht `font-src` und die Schriftroute `Access-Control-Allow-Origin: *` – Test in Task 8.
5. **Alte Entwürfe ohne neue Felder** rendern unverändert (gleiches MJML wie vorher) – Test in Task 1.

---

## Schrift-Register (gilt für Task 1, 8 und 9 – Werte wörtlich übernehmen)

| ID | Familie (CSS) | Ersatzstapel | Dateien (Gewicht-Stil) | fontsource-Slug |
|---|---|---|---|---|
| cormorant | Cormorant Garamond | Georgia, 'Times New Roman', serif | 400-normal, 400-italic | cormorant-garamond |
| dm-sans | DM Sans | Arial, Helvetica, sans-serif | 400-normal, 700-normal | dm-sans |
| playfair | Playfair Display | Georgia, 'Times New Roman', serif | 900-normal | playfair-display |
| poppins | Poppins | Arial, Helvetica, sans-serif | 400-normal, 600-normal, 700-normal | poppins |
| young-serif | Young Serif | Georgia, serif | 400-normal | young-serif |
| manrope | Manrope | Arial, Helvetica, sans-serif | 300-normal, 400-normal, 700-normal | manrope |
| bodoni | Bodoni Moda | Didot, Georgia, serif | 500-normal, 500-italic | bodoni-moda |
| montserrat | Montserrat | Arial, Helvetica, sans-serif | 400-normal, 600-normal | montserrat |
| josefin | Josefin Sans | 'Trebuchet MS', Arial, sans-serif | 300-normal, 700-normal | josefin-sans |
| oxanium | Oxanium | 'Trebuchet MS', Arial, sans-serif | 600-normal, 700-normal | oxanium |
| rajdhani | Rajdhani | 'Arial Narrow', Arial, sans-serif | 500-normal, 600-normal | rajdhani |

Dateiname in SC: `sales-mcp/static/schriften/<id>-<gewicht>-<stil>.woff2`.

## Vorlagen → Schriftpaar (`root.data.schriften`)

studio: anzeige `cormorant`, text `dm-sans` · zeitung: `playfair` / `poppins` · firmenblatt: `young-serif` / `poppins` · minimal: `manrope` / `manrope` · klassik: `bodoni` / `montserrat` · bildkopf: `josefin` / `josefin` · tech: `oxanium` / `rajdhani`.

## Rollen (gilt für Task 3, 5, 7)

`root.data.rollen` ist ein Objekt `{ "<blockId>/<pfad mit />": "<rolle>" }`, z. B. `{"kopf_band/data/style/backgroundColor": "akzent", "marke_logo/data/props/url": "logo", "marke_wort/data/props/text": "laden"}`. Rollen: `akzent`, `zweit`, `akzent_hell`, `auf_akzent`, `auf_zweit`, `akzent_text`, `akzent_ring1`, `akzent_ring2`, `akzent_rahmen`, `laden`, `logo`, `signal_bild`, `glow_bild`. Die Vorlage selbst trägt an diesen Stellen gültige Musterwerte (Musterpalette Akzent `#c2410c`, `flaeche` `#2f4858`), damit sie validiert und als Vorschau zeigbar ist. Marken-Blöcke heißen immer `marke_logo` (Image) und `marke_wort` (Heading).

---

### Task 1: Renderer versteht die neuen Gestaltungsmittel (MOS)

**Files:**
- Create: `spaces/marketing/claw/schriften.py`
- Modify: `spaces/marketing/claw/bloecke_mjml.py` (`_block`, `_kinder_als_section`, `nach_mjml`, `rendern`)
- Modify: `spaces/marketing/api/pult.py` (`_bloecke_html`, Zeilen ~239–247)
- Test: `spaces/marketing/claw/tests/test_bloecke_mjml.py`, `spaces/marketing/tests/test_pult_api.py`

**Interfaces:**
- Produces: `schriften.REGISTER: dict[str, dict]` (Schlüssel `familie`, `stapel`, `dateien: list[tuple[int, str]]`); `schriften.css_familie(id: str) -> str` (z. B. `"'Poppins', Arial, Helvetica, sans-serif"`, unbekannt → `""`); `bloecke_mjml.nach_mjml(dokument, betreff, vorschautext, pflichtteil, bild_basis="", breite=600, schrift_basis="")`; `bloecke_mjml.rendern(..., bild_basis="", handy=False, schrift_basis="")`; `pult.schrift_basis_aus(bild_basis: str) -> str`.

- [ ] **Step 1: Schrift-Register anlegen**

`spaces/marketing/claw/schriften.py`:
```python
"""Schrift-Register der Newsletter-Vorlagen (sales-claw Spec 2026-10-01-newsletter-
vorlagen-profi-design.md §4). Alle Schriften stehen unter der SIL Open Font
License und werden von sales-ui unter /marketing/schrift/ ausgeliefert - nie
von Google (DSGVO). Die IDs muessen mit sales-mcp/schriften.py (sales-claw)
und dem Editor-Schema uebereinstimmen."""
from __future__ import annotations

REGISTER: dict[str, dict] = {
    "cormorant": {"familie": "Cormorant Garamond", "stapel": "Georgia, 'Times New Roman', serif",
                  "dateien": [(400, "normal"), (400, "italic")]},
    "dm-sans": {"familie": "DM Sans", "stapel": "Arial, Helvetica, sans-serif",
                "dateien": [(400, "normal"), (700, "normal")]},
    "playfair": {"familie": "Playfair Display", "stapel": "Georgia, 'Times New Roman', serif",
                 "dateien": [(900, "normal")]},
    "poppins": {"familie": "Poppins", "stapel": "Arial, Helvetica, sans-serif",
                "dateien": [(400, "normal"), (600, "normal"), (700, "normal")]},
    "young-serif": {"familie": "Young Serif", "stapel": "Georgia, serif", "dateien": [(400, "normal")]},
    "manrope": {"familie": "Manrope", "stapel": "Arial, Helvetica, sans-serif",
                "dateien": [(300, "normal"), (400, "normal"), (700, "normal")]},
    "bodoni": {"familie": "Bodoni Moda", "stapel": "Didot, Georgia, serif",
               "dateien": [(500, "normal"), (500, "italic")]},
    "montserrat": {"familie": "Montserrat", "stapel": "Arial, Helvetica, sans-serif",
                   "dateien": [(400, "normal"), (600, "normal")]},
    "josefin": {"familie": "Josefin Sans", "stapel": "'Trebuchet MS', Arial, sans-serif",
                "dateien": [(300, "normal"), (700, "normal")]},
    "oxanium": {"familie": "Oxanium", "stapel": "'Trebuchet MS', Arial, sans-serif",
                "dateien": [(600, "normal"), (700, "normal")]},
    "rajdhani": {"familie": "Rajdhani", "stapel": "'Arial Narrow', Arial, sans-serif",
                 "dateien": [(500, "normal"), (600, "normal")]},
}


def css_familie(sid: str) -> str:
    s = REGISTER.get(sid or "")
    return f"'{s['familie']}', {s['stapel']}" if s else ""
```

- [ ] **Step 2: Failing tests für den Renderer schreiben**

Ans Ende von `spaces/marketing/claw/tests/test_bloecke_mjml.py`:
```python
# --- Neue Gestaltungsmittel (Spec 2026-10-01 §4) ---
from spaces.marketing.claw import bloecke_mjml as bm2, schriften


def _dok(*bloecke, **wurzel):
    ids = [b[0] for b in bloecke]
    d = {"root": {"type": "EmailLayout", "data": {"childrenIds": ids, **wurzel}}}
    for bid, typ, data in bloecke:
        d[bid] = {"type": typ, "data": data}
    return d


def test_alte_dokumente_unveraendert():
    d = _dok(("t", "Text", {"style": {}, "props": {"text": "Hallo"}}))
    assert bm2.nach_mjml(d, "B", "V", {}) == bm2.nach_mjml(d, "B", "V", {}, schrift_basis="")
    assert "mj-font" not in bm2.nach_mjml(d, "B", "V", {})


def test_anzeige_schrift_laufweite_versalien_zeilenhoehe():
    d = _dok(("h", "Heading", {"style": {"fontFamily": "ANZEIGE", "letterSpacing": 3, "textTransform": "uppercase",
                                          "lineHeight": 1.1}, "props": {"text": "Titel", "level": "h1"}}),
             schriften={"anzeige": "playfair", "text": "poppins"})
    m = bm2.nach_mjml(d, "B", "V", {}, schrift_basis="https://x.de/marketing/schrift/")
    assert "font-family=\"'Playfair Display', Georgia" in m
    assert 'letter-spacing="3px"' in m and 'text-transform="uppercase"' in m and 'line-height="1.1"' in m
    assert '<mj-font name="Playfair Display" href="https://x.de/marketing/schrift/schriften.css"' in m
    assert '<mj-all font-family="\'Poppins\', Arial' in m


def test_ohne_schrift_basis_kein_mj_font_aber_stapel():
    d = _dok(("h", "Heading", {"style": {"fontFamily": "ANZEIGE"}, "props": {"text": "T"}}),
             schriften={"anzeige": "oxanium", "text": "rajdhani"})
    m = bm2.nach_mjml(d, "B", "V", {})
    assert "mj-font" not in m and "'Oxanium', 'Trebuchet MS'" in m


def test_kursiv_in_ueberschrift():
    d = _dok(("h", "Heading", {"style": {}, "props": {"text": "Herbst*brief*"}}))
    assert "Herbst<em>brief</em>" in bm2.nach_mjml(d, "B", "V", {})


def test_container_hintergrundbild_und_farbfeld():
    d = _dok(("k", "Container", {"style": {"backgroundColor": "#2f4858", "overlay": {"farbe": "#2f4858", "deckkraft": 80}},
                                  "props": {"url": "medien:kopf.jpg", "width": 600, "height": 300, "childrenIds": []}}))
    m = bm2.nach_mjml(d, "B", "V", {}, bild_basis="https://x.de/marketing/bild/1.a/")
    assert 'background-url="https://x.de/marketing/bild/1.a/kopf.jpg"' in m
    assert 'background-size="cover"' in m and "rgba(47,72,88,0.8)" in m


def test_schwarz_weiss_haengt_sw_an():
    d = _dok(("i", "Image", {"style": {}, "props": {"url": "medien:a.jpg", "width": 600, "height": 300, "sw": True}}))
    assert 'src="https://x.de/b/a.jpg?sw=1"' in bm2.nach_mjml(d, "B", "V", {}, bild_basis="https://x.de/b/")


def test_dunkel_setzt_color_scheme():
    d = _dok(("t", "Text", {"style": {}, "props": {"text": "x"}}), dunkel=True)
    m = bm2.nach_mjml(d, "B", "V", {})
    assert 'name="color-scheme" content="dark"' in m


def test_unbekannte_schrift_id_faellt_auf_standard():
    d = _dok(("h", "Heading", {"style": {"fontFamily": "ANZEIGE"}, "props": {"text": "T"}}),
             schriften={"anzeige": "comic-sans", "text": "nix"})
    m = bm2.nach_mjml(d, "B", "V", {})
    assert "comic" not in m.lower() and "mj-font" not in m


def test_register_vollstaendig():
    assert set(schriften.REGISTER) == {"cormorant", "dm-sans", "playfair", "poppins", "young-serif", "manrope",
                                       "bodoni", "montserrat", "josefin", "oxanium", "rajdhani"}
```

- [ ] **Step 3: Tests laufen lassen – sie müssen fehlschlagen**

Run: `python -m pytest spaces/marketing/claw/tests/test_bloecke_mjml.py -q -p no:cacheprovider`
Expected: FAIL (`unexpected keyword argument 'schrift_basis'` u. a.)

- [ ] **Step 4: Renderer erweitern**

In `bloecke_mjml.py`:
1. Import `from spaces.marketing.claw import schriften` und neue Hilfen:
```python
def _rgba(farbe: str, deckkraft) -> str:
    h = str(farbe or "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", h):
        return ""
    d = max(0, min(100, _zahl(deckkraft, 100))) / 100
    return f"rgba({int(h[1:3], 16)},{int(h[3:5], 16)},{int(h[5:7], 16)},{d:g})"


def _schrift(s: dict, farben: dict) -> str:
    """font-family-Attribut fuer ANZEIGE/TEXT (Vorlagenschrift) oder die 9 Altschluessel."""
    ff = s.get("fontFamily")
    if ff == "ANZEIGE" and farben.get("anzeige"):
        return f' font-family="{_a(farben["anzeige"])}"'
    if ff == "TEXT" and farben.get("textschrift"):
        return f' font-family="{_a(farben["textschrift"])}"'
    if ff in SCHRIFTEN:
        return f' font-family="{_a(SCHRIFTEN[ff])}"'
    return ""


def _feinheiten(s: dict) -> str:
    out = ""
    if isinstance(s.get("letterSpacing"), (int, float)) and not isinstance(s.get("letterSpacing"), bool):
        out += f' letter-spacing="{max(-2, min(8, s["letterSpacing"])):g}px"'
    if s.get("textTransform") == "uppercase":
        out += ' text-transform="uppercase"'
    return out


def _zeilenhoehe(s: dict, standard: str) -> str:
    v = s.get("lineHeight")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.9 <= v <= 2.0:
        return f"{v:g}"
    return standard
```
2. `_block`: Heading → `f'... font-weight="{gewicht or "bold"}" line-height="{_zeilenhoehe(s, "1.25")}"{_schrift(s, farben)}{_feinheiten(s)}{hg}>{_kursiv(p.get("text") or "")}</mj-text>'` mit
```python
def _kursiv(roh: str) -> str:
    """Ueberschrift: nur *kursiv* wird umgesetzt, alles andere bleibt Text."""
    sicher = _a(roh).replace(chr(0), "")
    return _KURSIV.sub(r"<em>\1</em>", sicher).replace("\n", "<br>")
```
   Text → gleiche Ergänzungen (`line-height="{_zeilenhoehe(s, "1.55")}"`, `_schrift`, `_feinheiten`). Button → `_schrift(s, farben)` anhängen. Image → `ziel = bild_adresse(...)`; wenn `p.get("sw") is True` und `ziel`: `ziel += "?sw=1"`.
3. `_kinder_als_section`, Zweig `Container`: wenn `props.get("url")` und `bild_adresse(props["url"], bild_basis)` → statt der Karte:
```python
            bild = bild_adresse(props.get("url") or "", bild_basis)
            if bild:
                ov = stil.get("overlay") if isinstance(stil.get("overlay"), dict) else {}
                feld = _rgba(ov.get("farbe"), ov.get("deckkraft"))
                spalte_attr = f' background-color="{feld}"' if feld else ""
                hoehe = _zahl(props.get("height"), 0)
                teile.append(
                    f'<mj-section background-url="{_a(bild)}" background-size="cover" background-repeat="no-repeat" '
                    f'background-color="{_a(hg)}" padding="{pol}"><mj-column{spalte_attr}>'
                    + (f'<mj-spacer height="{hoehe // 6}px" />' if hoehe else "")
                    + f'{inhalt}</mj-column></mj-section>')
                continue
```
   (`pol`, `hg`, `inhalt` vor dieser Abfrage berechnen; Karte wie bisher, wenn kein Bild.)
4. `nach_mjml(..., schrift_basis: str = "")`: aus `wurzel.get("schriften")` lesen:
```python
    sw = wurzel.get("schriften") if isinstance(wurzel.get("schriften"), dict) else {}
    anzeige, textschrift = schriften.css_familie(sw.get("anzeige")), schriften.css_familie(sw.get("text"))
    farben["anzeige"], farben["textschrift"] = anzeige, textschrift
    if textschrift:
        schrift = textschrift.replace('"', "'")
    koepfe = ""
    if schrift_basis.startswith("https://") and schrift_basis.endswith("/"):
        for sid in {sw.get("anzeige"), sw.get("text")}:
            if sid in schriften.REGISTER:
                koepfe += (f'<mj-font name="{_a(schriften.REGISTER[sid]["familie"])}" '
                           f'href="{_a(schrift_basis)}schriften.css" />')
    if wurzel.get("dunkel") is True:
        koepfe += ('<mj-raw><meta name="color-scheme" content="dark"><meta name="supported-color-schemes" '
                   'content="dark"></mj-raw>')
```
   und `koepfe` in `<mj-head>` nach `<mj-preview>` einfügen.
5. `rendern(..., schrift_basis: str = "")` reicht durch.

- [ ] **Step 5: `pult.py` leitet die Schrift-Basis aus der Bild-Basis ab**

```python
_BILD_BASIS_HOST = re.compile(r"^(https://[^/\s\"'<>]+)/marketing/bild/[^/\s\"'<>]+/$")


def schrift_basis_aus(bild_basis: str) -> str:
    m = _BILD_BASIS_HOST.match(bild_basis or "")
    return f"{m.group(1)}/marketing/schrift/" if m else ""
```
In `_bloecke_html`: `bloecke_mjml.rendern(..., bild_basis=bild_basis, handy=(fmt == "handy"), schrift_basis=schrift_basis_aus(bild_basis))`.
Test in `tests/test_pult_api.py`:
```python
def test_schrift_basis_aus_bild_basis():
    assert pult.schrift_basis_aus("https://ui.tail.ts.net:8445/marketing/bild/123.abc/") == \
        "https://ui.tail.ts.net:8445/marketing/schrift/"
    assert pult.schrift_basis_aus("") == "" and pult.schrift_basis_aus("https://x/andere/") == ""
```

- [ ] **Step 6: Tests laufen lassen**

Run: `python -m pytest spaces/marketing/claw/tests/test_bloecke_mjml.py spaces/marketing/tests/test_pult_api.py -q -p no:cacheprovider`
Expected: PASS (alle, auch die bestehenden)

- [ ] **Step 7: Commit (MOS)**

```powershell
git add spaces/marketing/claw/schriften.py spaces/marketing/claw/bloecke_mjml.py spaces/marketing/api/pult.py spaces/marketing/claw/tests/test_bloecke_mjml.py spaces/marketing/tests/test_pult_api.py
git commit -m "feat(marketing): Renderer mit Vorlagenschriften, Laufweite, Versalien, Hintergrundbild und Schwarz-Weiss"
```

---

### Task 2: Migration 058 – DB-Prüfung, Vorlagen für alle Läden, „Neu“ mit fertigem Dokument (MOS)

**Files:**
- Create: `spaces/marketing/db/058_vorlagen_profi.sql`, `spaces/marketing/db/verify_058.sql`
- Modify: `spaces/marketing/claw/tests/test_startvorlagen.py` (`_fehler`-Spiegel)
- Test: `spaces/marketing/claw/tests/test_startvorlagen.py`

**Interfaces:**
- Produces (DB): `marketing.pult_inhalt_aus_vorlage(p_vorlage text, p_titel text, p_mandant text, p_bloecke jsonb, p_layout text) RETURNS uuid`; Spalte `marketing.newsletter_vorlagen.fuer_alle boolean NOT NULL DEFAULT false`; Status `zurueckgezogen`; `marketing._bild_ist_platz(b jsonb)` erkennt auch Container-Plätze und überspringt `grafik`.
- Consumes: Funktionsrumpf `pult_bloecke_fehler` aus `db/055_newsletter_editor_korrektur.sql` (vollständig kopieren und ergänzen).

- [ ] **Step 1: Spiegel in `test_startvorlagen.py` erweitern und failing Tests schreiben**

In `_fehler`: `SCHRIFTEN` um `"ANZEIGE", "TEXT"` ergänzen; nach der Zahlprüfung einfügen:
```python
        if not (_zahl_ok(style.get("letterSpacing"), -2, 8) and _zahl_ok(style.get("lineHeight"), 0.9, 2.0)):
            return f"{bid}: Feinheiten"
        if style.get("textTransform") not in (None, "none", "uppercase"):
            return f"{bid}: Versalien"
        ov = style.get("overlay")
        if ov is not None and (not isinstance(ov, dict) or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(ov.get("farbe")))
                               or not _zahl_ok(ov.get("deckkraft"), 0, 100)):
            return f"{bid}: Farbfeld"
        for k in ("sw", "grafik"):
            if props.get(k) is not None and not isinstance(props.get(k), bool):
                return f"{bid}: {k}"
        if bid == "root":
            sw = (b.get("data") or {}).get("schriften")
            ids = {"cormorant", "dm-sans", "playfair", "poppins", "young-serif", "manrope", "bodoni",
                   "montserrat", "josefin", "oxanium", "rajdhani"}
            if sw is not None and (not isinstance(sw, dict) or not set(sw) <= {"anzeige", "text"}
                                   or not all(v in ids for v in sw.values())):
                return "root: Schriften"
```
und in der URL-Prüfung `if typ in ("Image", "Container") and k == "url":`. Neue Tests:
```python
@pytest.mark.parametrize("kaputt", [
    {"style": {"letterSpacing": 9}}, {"style": {"textTransform": "lowercase"}},
    {"style": {"lineHeight": 3}}, {"style": {"overlay": {"farbe": "rot", "deckkraft": 50}}},
    {"style": {"fontFamily": "COMIC"}}, {"props": {"sw": "ja"}}])
def test_neue_felder_werden_geprueft(kaputt):
    d = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["h"]}},
         "h": {"type": "Heading", "data": {"style": kaputt.get("style", {}), "props": {"text": "x", **kaputt.get("props", {})}}}}
    assert _fehler(d)


def test_container_mit_medien_hintergrund_gueltig():
    d = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["k"], "schriften": {"anzeige": "josefin", "text": "josefin"}}},
         "k": {"type": "Container", "data": {"style": {"overlay": {"farbe": "#2f4858", "deckkraft": 80}},
                                              "props": {"url": "medien:platzhalter-2x1.png", "width": 600, "height": 300,
                                                        "childrenIds": []}}}}
    assert _fehler(d) is None
```

- [ ] **Step 2: Laufen lassen** – Run: `python -m pytest spaces/marketing/claw/tests/test_startvorlagen.py -q -p no:cacheprovider` – Expected: neue Tests PASS (der Spiegel ist die Spezifikation der SQL-Änderung); bestehende Tests bleiben grün.

- [ ] **Step 3: `058_vorlagen_profi.sql` schreiben**

```sql
-- 058: Newsletter-Vorlagen in Profi-Qualitaet (sales-claw Spec 2026-10-01
-- newsletter-vorlagen-profi-design.md). Idempotent, eine Transaktion.
BEGIN;

-- 1) Vorlagen fuer alle Laeden und zurueckziehen
ALTER TABLE marketing.newsletter_vorlagen ADD COLUMN IF NOT EXISTS fuer_alle boolean NOT NULL DEFAULT false;
DO $$ DECLARE c text; BEGIN
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'marketing.newsletter_vorlagen'::regclass
             AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%status%' LOOP
    EXECUTE format('ALTER TABLE marketing.newsletter_vorlagen DROP CONSTRAINT %I', c);
  END LOOP;
END $$;
ALTER TABLE marketing.newsletter_vorlagen ADD CONSTRAINT newsletter_vorlagen_status_check
  CHECK (status IN ('vorschlag','freigegeben','zurueckgezogen'));
```
Danach `CREATE OR REPLACE FUNCTION marketing.pult_vorlage_speichern(...)` aus 053 wörtlich übernehmen, nur die Statusprüfung auf `IN ('vorschlag','freigegeben','zurueckgezogen')` ändern.

```sql
-- 2) Bildplaetze: Container mit Hintergrundbild zaehlen, erzeugte Grafiken nicht
CREATE OR REPLACE FUNCTION marketing._bild_ist_platz(b jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(b->>'type' IN ('Image','Container')
     AND (b->>'type' = 'Image' OR (b#>>'{data,props,url}') IS NOT NULL)
     AND coalesce(b#>'{data,props,grafik}', 'false'::jsonb) <> 'true'::jsonb
     AND jsonb_typeof(b#>'{data,props,width}') = 'number' AND (b#>>'{data,props,width}')::numeric > 0
     AND jsonb_typeof(b#>'{data,props,height}') = 'number' AND (b#>>'{data,props,height}')::numeric > 0, false) $$;
```

3) `pult_bloecke_fehler`: Rumpf aus 055 vollständig kopieren und ergänzen:
- `c_schriften` um `'ANZEIGE','TEXT'`;
- `c_vorlagenschriften CONSTANT text[] := ARRAY['cormorant','dm-sans','playfair','poppins','young-serif','manrope','bodoni','montserrat','josefin','oxanium','rajdhani'];`
- in der Zahlenliste: `('letterSpacing', v_style->'letterSpacing', -2, 8)`, `('styleLineHeight', v_style->'lineHeight', 0.9, 2.0)`;
- nach den Aufzählungswerten:
```sql
    IF NOT marketing._bloecke_wahl_ok(v_style->'textTransform', ARRAY['none','uppercase']) THEN
      RETURN format('Versalien in %s muss none oder uppercase sein', v_id); END IF;
    IF v_style ? 'overlay' AND jsonb_typeof(v_style->'overlay') <> 'null' AND NOT (
         jsonb_typeof(v_style->'overlay') = 'object'
         AND coalesce(v_style->'overlay'->>'farbe', '') ~ '^#[0-9a-fA-F]{6}$'
         AND marketing._bloecke_zahl_ok(v_style->'overlay'->'deckkraft', 0, 100)) THEN
      RETURN format('Farbfeld in %s braucht farbe #rrggbb und deckkraft 0-100', v_id); END IF;
    IF (v_props ? 'sw' AND jsonb_typeof(v_props->'sw') NOT IN ('boolean','null'))
       OR (v_props ? 'grafik' AND jsonb_typeof(v_props->'grafik') NOT IN ('boolean','null')) THEN
      RETURN format('sw/grafik in %s muss true oder false sein', v_id); END IF;
    IF v_id = 'root' AND jsonb_typeof(v_b->'data'->'schriften') = 'object' AND EXISTS (
         SELECT 1 FROM jsonb_each_text(v_b->'data'->'schriften') e
          WHERE e.key NOT IN ('anzeige','text') OR NOT e.value = ANY(c_vorlagenschriften)) THEN
      RETURN 'Schriftpaar der Vorlage ist nicht erlaubt'; END IF;
```
- in der Link-/Bildschleife: `IF v_typ IN ('Image','Container') AND v_url = v_props->>'url' THEN` (Bildregel gilt für beide).

```sql
-- 4) Neu aus Vorlage mit fertigem Dokument (die API fuellt Rollen, Logo, Grafiken)
CREATE OR REPLACE FUNCTION marketing.pult_inhalt_aus_vorlage(
    p_vorlage text, p_titel text, p_mandant text, p_bloecke jsonb, p_layout text) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE v_id uuid; v_f text; v_layout text;
BEGIN
  IF length(btrim(coalesce(p_titel, ''))) = 0 THEN RAISE EXCEPTION 'Ohne Titel kein Newsletter'; END IF;
  PERFORM 1 FROM marketing.newsletter_vorlagen
   WHERE name = p_vorlage AND status = 'freigegeben' AND (mandant = p_mandant OR fuer_alle);
  IF NOT FOUND THEN RAISE EXCEPTION 'Vorlage % gibt es nicht oder sie ist nicht freigegeben', p_vorlage; END IF;
  v_f := marketing.pult_bloecke_fehler(p_bloecke);
  IF v_f IS NOT NULL THEN RAISE EXCEPTION 'Dokument ungueltig: %', v_f; END IF;
  v_layout := coalesce((SELECT name FROM marketing.layout_vorlagen WHERE name = p_layout), 'dunkel');
  INSERT INTO marketing.inhalte (mandant, art, titel) VALUES (p_mandant, 'newsletter', btrim(p_titel))
  RETURNING id INTO v_id;
  INSERT INTO marketing.inhalt_fassungen (inhalt, fassung, felder, layout, layout_fassung, urheber, format, bloecke)
  VALUES (v_id, 1, jsonb_build_object('betreff', btrim(p_titel), 'vorschautext', ''),
          v_layout, (SELECT fassung FROM marketing.layout_vorlagen WHERE name = v_layout),
          'betreiber', 'bloecke', p_bloecke);
  IF EXISTS (SELECT 1 FROM jsonb_each(p_bloecke) e WHERE marketing._bild_ist_platz(e.value)
               AND marketing._bild_platz_leer(e.value#>>'{data,props,url}')) THEN
    PERFORM marketing.pult_bild_auftrag(v_id, NULL, true, '', 'system');
  END IF;
  RETURN v_id;
END $$;

COMMIT;
```

- [ ] **Step 4: `verify_058.sql` schreiben**

```sql
-- Nachweise fuer 058, laeuft nur ueber migration_probe (eine Transaktion + ROLLBACK).
DO $$ BEGIN
  ASSERT marketing.pult_bloecke_fehler('{"root":{"type":"EmailLayout","data":{"childrenIds":["h"],"schriften":{"anzeige":"playfair","text":"poppins"}}},"h":{"type":"Heading","data":{"style":{"fontFamily":"ANZEIGE","letterSpacing":3,"textTransform":"uppercase","lineHeight":1.1},"props":{"text":"x"}}}}'::jsonb) IS NULL, 'neue Felder gueltig';
  ASSERT marketing.pult_bloecke_fehler('{"root":{"type":"EmailLayout","data":{"childrenIds":["h"]}},"h":{"type":"Heading","data":{"style":{"letterSpacing":9},"props":{"text":"x"}}}}'::jsonb) IS NOT NULL, 'Laufweite begrenzt';
  ASSERT marketing.pult_bloecke_fehler('{"root":{"type":"EmailLayout","data":{"childrenIds":["k"]}},"k":{"type":"Container","data":{"style":{"overlay":{"farbe":"#2f4858","deckkraft":80}},"props":{"url":"medien:platzhalter-2x1.png","width":600,"height":300,"childrenIds":[]}}}}'::jsonb) IS NULL, 'Container-Hintergrund gueltig';
  ASSERT marketing._bild_ist_platz('{"type":"Container","data":{"props":{"url":"medien:a.png","width":600,"height":300}}}'::jsonb), 'Container ist Platz';
  ASSERT NOT marketing._bild_ist_platz('{"type":"Image","data":{"props":{"url":"medien:a.png","width":600,"height":300,"grafik":true}}}'::jsonb), 'Grafik ist kein Platz';
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='marketing'
                 AND table_name='newsletter_vorlagen' AND column_name='fuer_alle'), 'fuer_alle da';
END $$;
SELECT 'verify_058 ok' AS ergebnis;
```

- [ ] **Step 5: Gegen die Live-DB proben (ROLLBACK)**

Run: `cd <MOS> ; python -m spaces.marketing.scripts.migration_probe spaces/marketing/db/058_vorlagen_profi.sql spaces/marketing/db/verify_058.sql`
Expected: Ausgabe enthält `verify_058 ok`, kein `ERROR`.

- [ ] **Step 6: Commit (MOS)**

```powershell
git add spaces/marketing/db/058_vorlagen_profi.sql spaces/marketing/db/verify_058.sql spaces/marketing/claw/tests/test_startvorlagen.py
git commit -m "feat(marketing): Migration 058 - neue Gestaltungsfelder, Vorlagen fuer alle Laeden, Neu mit fertigem Dokument"
```

---

### Task 3: Ladenmarke – Rollen berechnen, einsetzen, Logo ablegen; Kontrastprüfung für Blockdokumente (MOS)

**Files:**
- Create: `spaces/marketing/claw/vorlagen_marke.py`
- Modify: `spaces/marketing/claw/schoenheit.py` (neue Funktion `bloecke_pruefen`)
- Test: `spaces/marketing/claw/tests/test_vorlagen_marke.py`, `spaces/marketing/claw/tests/test_schoenheit.py`

**Interfaces:**
- Produces: `vorlagen_marke.ERSATZ_AKZENT = "#2563eb"`; `vorlagen_marke.rollen(gestalt: dict | None, grund: str) -> dict[str, str]` (Schlüssel: `akzent, zweit, akzent_hell, auf_akzent, auf_zweit, akzent_text, akzent_ring1, akzent_ring2, akzent_rahmen`); `vorlagen_marke.logo_ablegen(gestalt: dict | None, mandant: str, ordner: str) -> str | None` (liefert `"medien:<datei>"`); `vorlagen_marke.einsetzen(dok: dict, werte: dict[str, str]) -> dict` (tiefe Kopie; entfernt `marke_logo` oder `marke_wort`); `schoenheit.bloecke_pruefen(dok: dict) -> list[dict]` (Befunde wie `befund()`).

- [ ] **Step 1: Failing Tests schreiben**

`spaces/marketing/claw/tests/test_vorlagen_marke.py`:
```python
import base64
import copy

import pytest

from spaces.marketing.claw import schoenheit, vorlagen_marke as vm

WEISS = "#ffffff"


@pytest.mark.parametrize("akzent", ["#facc15", "#111111", "#c2410c", "#9ca3af"])
def test_rollen_immer_lesbar(akzent):
    r = vm.rollen({"akzent": akzent, "flaeche": "#ffffff"}, WEISS)
    assert schoenheit.kontrast(r["auf_akzent"], r["akzent"]) >= 3
    assert schoenheit.kontrast(r["akzent_text"], WEISS) >= 4.5
    assert schoenheit.kontrast(r["auf_zweit"], r["zweit"]) >= 4.5
    assert schoenheit.kontrast(r["zweit"], WEISS) >= 3          # zu helle flaeche wird ersetzt


def test_ohne_gestalt_ersatzpalette():
    r = vm.rollen(None, WEISS)
    assert r["akzent"] == vm.ERSATZ_AKZENT and all(v.startswith("#") and len(v) == 7 for v in r.values())


def test_akzent_hell_ist_toenung():
    r = vm.rollen({"akzent": "#c2410c"}, WEISS)
    assert schoenheit.kontrast(r["akzent_hell"], WEISS) < 1.3


def test_logo_wird_datei_mit_pruefsumme(tmp_path):
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode()
    g = {"logo": f"data:image/png;base64,{png}"}
    a = vm.logo_ablegen(g, "radhaus", str(tmp_path))
    b = vm.logo_ablegen(g, "radhaus", str(tmp_path))
    assert a == b and a.startswith("medien:logo-radhaus-") and a.endswith(".png")
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("gestalt", [None, {}, {"logo": "data:image/gif;base64,AAAA"}, {"logo": "https://x/y.png"}])
def test_kein_gueltiges_logo(tmp_path, gestalt):
    assert vm.logo_ablegen(gestalt, "radhaus", str(tmp_path)) is None


def test_logo_ohne_ordner(tmp_path):
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    assert vm.logo_ablegen({"logo": f"data:image/png;base64,{png}"}, "radhaus", "") is None


DOK = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["kopf"], "rollen": {
           "band/data/style/backgroundColor": "akzent", "marke_logo/data/props/url": "logo",
           "marke_wort/data/props/text": "laden"}}},
       "kopf": {"type": "Container", "data": {"style": {}, "props": {"childrenIds": ["marke_logo", "marke_wort", "band"]}}},
       "marke_logo": {"type": "Image", "data": {"style": {}, "props": {"url": "medien:platzhalter-1x1.png", "width": 120}}},
       "marke_wort": {"type": "Heading", "data": {"style": {}, "props": {"text": "[Laden]"}}},
       "band": {"type": "Text", "data": {"style": {"backgroundColor": "#c2410c"}, "props": {"text": "x"}}}}


def test_einsetzen_mit_logo():
    vorher = copy.deepcopy(DOK)
    d = vm.einsetzen(DOK, {"akzent": "#123456", "logo": "medien:logo-a-1.png", "laden": "Radhaus"})
    assert DOK == vorher                                    # Eingabe unveraendert
    assert d["band"]["data"]["style"]["backgroundColor"] == "#123456"
    assert d["marke_logo"]["data"]["props"]["url"] == "medien:logo-a-1.png"
    assert "marke_wort" not in d and "marke_wort" not in d["kopf"]["data"]["props"]["childrenIds"]


def test_einsetzen_ohne_logo_wortmarke():
    d = vm.einsetzen(DOK, {"akzent": "#123456", "laden": "Radhaus Jena"})
    assert "marke_logo" not in d and d["marke_wort"]["data"]["props"]["text"] == "Radhaus Jena"


def test_unbekannte_rolle_und_kaputter_pfad_stoeren_nicht():
    d = copy.deepcopy(DOK)
    d["root"]["data"]["rollen"]["gibtsnicht/data/x"] = "akzent"
    d["root"]["data"]["rollen"]["band/data/style/color"] = "unbekannt"
    assert vm.einsetzen(d, {"akzent": "#123456", "laden": "L"})["band"]["data"]["style"].get("color") is None
```
In `test_schoenheit.py`:
```python
def test_bloecke_pruefen_findet_schwachen_kontrast():
    d = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["t"], "canvasColor": "#ffffff"}},
         "t": {"type": "Text", "data": {"style": {"color": "#dddddd"}, "props": {"text": "x"}}}}
    assert schoenheit.bloecke_pruefen(d)
    d["t"]["data"]["style"]["color"] = "#222222"
    assert schoenheit.bloecke_pruefen(d) == []
```

- [ ] **Step 2: Laufen lassen – FAIL** (`No module named ... vorlagen_marke`).

- [ ] **Step 3: `vorlagen_marke.py` implementieren**

```python
"""Ladenmarke fuer Newsletter-Vorlagen (Spec 2026-10-01 §5): Farbrollen aus dem
Standard-Layout des Ladens berechnen, in die Vorlage einsetzen und das Logo
einmalig als Datei ablegen. Neutrale Toene der Vorlage bleiben unangetastet."""
from __future__ import annotations

import base64
import copy
import hashlib
import os
import re

from spaces.marketing.claw.schoenheit import kontrast

ERSATZ_AKZENT = "#2563eb"
FAST_SCHWARZ = "#1a1a1a"
INK = "#080b13"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_LOGO = re.compile(r"^data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)$")


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(x))) for x in (r, g, b))


def mischen(a: str, b: str, anteil_b: float) -> str:
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex(ra + (rb - ra) * anteil_b, ga + (gb - ga) * anteil_b, ba + (bb - ba) * anteil_b)


def _bis_kontrast(farbe: str, grund: str, ziel: float) -> str:
    """Farbe Richtung Schwarz (heller Grund) bzw. Weiss (dunkler Grund) schieben, bis ziel erreicht."""
    richtung = "#000000" if kontrast("#000000", grund) >= kontrast("#ffffff", grund) else "#ffffff"
    for schritt in range(0, 21):
        f = mischen(farbe, richtung, schritt / 20)
        if kontrast(f, grund) >= ziel:
            return f
    return richtung


def _auf(farbe: str) -> str:
    return max(("#ffffff", FAST_SCHWARZ), key=lambda c: kontrast(c, farbe))


def rollen(gestalt: dict | None, grund: str) -> dict[str, str]:
    g = gestalt if isinstance(gestalt, dict) else {}
    akzent = str(g.get("akzent") or "").lower()
    akzent = akzent if _HEX.match(akzent) else ERSATZ_AKZENT
    zweit = str(g.get("flaeche") or "").lower()
    if not _HEX.match(zweit) or kontrast(zweit, "#ffffff") < 3:
        zweit = _bis_kontrast(mischen(akzent, "#000000", 0.55), "#ffffff", 7)
    return {
        "akzent": akzent,
        "zweit": zweit,
        "akzent_hell": mischen("#ffffff", akzent, 0.10),
        "auf_akzent": _auf(akzent),
        "auf_zweit": _auf(zweit),
        "akzent_text": _bis_kontrast(akzent, grund if _HEX.match(grund or "") else "#ffffff", 4.5),
        "akzent_ring1": mischen(akzent, INK, 0.55),
        "akzent_ring2": mischen(akzent, INK, 0.40),
        "akzent_rahmen": mischen(akzent, INK, 0.70),
    }


def logo_ablegen(gestalt: dict | None, mandant: str, ordner: str) -> str | None:
    g = gestalt if isinstance(gestalt, dict) else {}
    m = _LOGO.match(str(g.get("logo") or ""))
    if not m or not ordner or not os.path.isdir(ordner) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,40}", mandant or ""):
        return None
    try:
        roh = base64.b64decode(m.group(2), validate=True)
    except ValueError:
        return None
    endung = "png" if m.group(1) == "png" else "jpg"
    name = f"logo-{mandant}-{hashlib.sha256(roh).hexdigest()[:10]}.{endung}"
    ziel = os.path.join(ordner, name)
    if not os.path.exists(ziel):
        tmp = ziel + ".tmp"
        with open(tmp, "wb") as f:
            f.write(roh)
        os.replace(tmp, ziel)
    return f"medien:{name}"


def _setzen(dok: dict, pfad: str, wert: str) -> None:
    teile = pfad.split("/")
    knoten = dok.get(teile[0])
    for t in teile[1:-1]:
        if not isinstance(knoten, dict):
            return
        knoten = knoten.setdefault(t, {})
    if isinstance(knoten, dict) and teile[1:]:
        knoten[teile[-1]] = wert


def _entfernen(dok: dict, bid: str) -> None:
    dok.pop(bid, None)
    for b in dok.values():
        data = (b or {}).get("data") or {}
        for liste in (data.get("childrenIds"), (data.get("props") or {}).get("childrenIds")):
            if isinstance(liste, list) and bid in liste:
                liste.remove(bid)
        for spalte in (data.get("props") or {}).get("columns") or []:
            if isinstance(spalte, dict) and bid in (spalte.get("childrenIds") or []):
                spalte["childrenIds"].remove(bid)


def einsetzen(dok: dict, werte: dict[str, str]) -> dict:
    d = copy.deepcopy(dok)
    rollen_tab = ((d.get("root") or {}).get("data") or {}).get("rollen") or {}
    for pfad, rolle in rollen_tab.items():
        if rolle in werte and pfad.split("/")[0] in d:
            _setzen(d, pfad, werte[rolle])
    _entfernen(d, "marke_wort" if werte.get("logo") else "marke_logo")
    return d
```

- [ ] **Step 4: `schoenheit.bloecke_pruefen` implementieren**

```python
def bloecke_pruefen(dok: dict) -> list:
    """Kontrast je Text-/Ueberschrift-/Knopfblock gegen seinen Grund (Block, Rahmen, Seite).
    Fliesstext >= 4,5:1, Ueberschriften ab 24 px und Knopftext >= 3:1. Wirft nie."""
    befunde = []
    try:
        wurzel = (dok.get("root") or {}).get("data") or {}
        seite = wurzel.get("canvasColor") or "#ffffff"
        textfarbe = wurzel.get("textColor") or "#242424"
        grund_von = {}
        for bid, b in dok.items():
            data = (b or {}).get("data") or {}
            hg = (data.get("style") or {}).get("backgroundColor")
            for k in ((data.get("props") or {}).get("childrenIds") or []):
                grund_von[k] = hg or seite
            for sp in (data.get("props") or {}).get("columns") or []:
                for k in (sp or {}).get("childrenIds") or []:
                    grund_von[k] = hg or seite
        for bid, b in dok.items():
            typ = (b or {}).get("type")
            data = (b or {}).get("data") or {}
            s, p = data.get("style") or {}, data.get("props") or {}
            if typ not in ("Text", "Heading", "Button"):
                continue
            grund = s.get("backgroundColor") or grund_von.get(bid, seite)
            if typ == "Button":
                vorne, hinten, ziel = p.get("buttonTextColor") or "#ffffff", p.get("buttonBackgroundColor") or "#999999", 3.0
            else:
                vorne, hinten = s.get("color") or textfarbe, grund
                gross = typ == "Heading" or (s.get("fontSize") or 16) >= 24
                ziel = 3.0 if gross else KONTRAST_TEXT
            if kontrast(vorne, hinten) < ziel:
                befunde.append(befund("blockiert", "kontrast", f"{bid}: {vorne} auf {hinten} unter {ziel}:1"))
    except (ValueError, AttributeError, TypeError):
        befunde.append(befund("blockiert", "kontrast", "Dokument nicht pruefbar"))
    return befunde
```
(`KONTRAST_TEXT` und `befund` existieren in `schoenheit.py`; prüfe die Signatur von `befund(schwere, punkt, satz)` und den Wert `KONTRAST_TEXT` dort.)

- [ ] **Step 5: Tests laufen lassen** – Run: `python -m pytest spaces/marketing/claw/tests/test_vorlagen_marke.py spaces/marketing/claw/tests/test_schoenheit.py -q -p no:cacheprovider` – Expected: PASS.

- [ ] **Step 6: Commit (MOS)**

```powershell
git add spaces/marketing/claw/vorlagen_marke.py spaces/marketing/claw/schoenheit.py spaces/marketing/claw/tests/test_vorlagen_marke.py spaces/marketing/claw/tests/test_schoenheit.py
git commit -m "feat(marketing): Ladenmarke fuer Vorlagen - Farbrollen, Logo-Datei, Kontrastpruefung fuer Blockdokumente"
```

---

### Task 4: Erzeugte tech-Grafiken mit Pillow (MOS)

**Files:**
- Create: `spaces/marketing/claw/vorlagen_grafik.py`
- Test: `spaces/marketing/claw/tests/test_vorlagen_grafik.py`

**Interfaces:**
- Consumes: `vorlagen_marke.mischen(a, b, anteil_b)`, `vorlagen_marke.rollen(...)`
- Produces: `vorlagen_grafik.signal(akzent: str, ordner: str) -> str | None` (`"medien:tech-signal-<hex6>.png"`, 1072×760), `vorlagen_grafik.glow(akzent: str, ordner: str) -> str | None` (`"medien:tech-glow-<hex6>.jpg"`, 1200×900). Ohne Ordner oder ungültige Farbe → `None`.

- [ ] **Step 1: Failing Tests**

```python
from PIL import Image

from spaces.marketing.claw import vorlagen_grafik as vg


def test_signal_und_glow_entstehen_einmal(tmp_path):
    a = vg.signal("#B5F750", str(tmp_path))
    b = vg.signal("#b5f750", str(tmp_path))
    g = vg.glow("#b5f750", str(tmp_path))
    assert a == b == "medien:tech-signal-b5f750.png" and g == "medien:tech-glow-b5f750.jpg"
    with Image.open(tmp_path / "tech-signal-b5f750.png") as bild:
        assert bild.size == (1072, 760)
        mitte = bild.convert("RGB").getpixel((536, 380))
        assert mitte == (0xb5, 0xf7, 0x50) or sum(abs(x - y) for x, y in zip(mitte, (0xb5, 0xf7, 0x50))) < 30
    with Image.open(tmp_path / "tech-glow-b5f750.jpg") as bild:
        assert bild.size == (1200, 900)
    assert len(list(tmp_path.iterdir())) == 2


def test_ungueltig(tmp_path):
    assert vg.signal("gruen", str(tmp_path)) is None and vg.glow("#b5f750", "") is None
```
(Der Kern ist in der Mitte; das Funkel-Zeichen liegt darauf – deshalb Pixel 30 px oberhalb der Mitte prüfen, falls das Zeichen die Mitte trifft: `getpixel((536, 350))`.)

- [ ] **Step 2: FAIL bestätigen.**

- [ ] **Step 3: Implementieren**

```python
"""Erzeugte Grafiken fuer die Vorlage tech (Spec 2026-10-01 §6): Signal-Karte
mit Halo, Ringen und Kern sowie ein radialer Lichtschein - im Ladenakzent,
mit Pillow gezeichnet (kein Modell, darf auf der VM laufen). Gleicher Akzent
= gleiche Datei."""
from __future__ import annotations

import os
import re

from PIL import Image, ImageDraw, ImageFilter

from spaces.marketing.claw.vorlagen_marke import INK, _rgb, mischen

SURFACE = "#111725"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _ziel(ordner: str, name: str) -> str | None:
    if not ordner or not os.path.isdir(ordner):
        return None
    return os.path.join(ordner, name)


def _speichern(bild: Image.Image, pfad: str, fmt: str) -> None:
    tmp = pfad + ".tmp"
    bild.save(tmp, fmt, **({"quality": 88} if fmt == "JPEG" else {"optimize": True}))
    os.replace(tmp, pfad)


def _halo(breite: int, hoehe: int, mitte: tuple[int, int], radius: int, innen: str, aussen: str) -> Image.Image:
    bild = Image.new("RGB", (breite, hoehe), _rgb(aussen))
    zeichner = ImageDraw.Draw(bild)
    for i in range(40, 0, -1):
        r = radius * i / 40
        farbe = mischen(innen, aussen, i / 40)
        zeichner.ellipse([mitte[0] - r, mitte[1] - r * 0.75, mitte[0] + r, mitte[1] + r * 0.75], fill=_rgb(farbe))
    return bild.filter(ImageFilter.GaussianBlur(24))


def signal(akzent: str, ordner: str) -> str | None:
    if not _HEX.match(akzent or ""):
        return None
    a = akzent.lower()
    name = f"tech-signal-{a[1:]}.png"
    pfad = _ziel(ordner, name)
    if pfad is None:
        return None
    if not os.path.exists(pfad):
        w, h, m = 1072, 760, (536, 380)
        bild = _halo(w, h, m, 520, mischen(a, SURFACE, 0.72), "#101622")
        z = ImageDraw.Draw(bild)
        for r, farbe in ((280, mischen(a, INK, 0.55)), (190, mischen(a, INK, 0.40))):
            z.ellipse([m[0] - r, m[1] - r, m[0] + r, m[1] + r], outline=_rgb(farbe), width=2)
        z.ellipse([m[0] - 100, m[1] - 100, m[0] + 100, m[1] + 100], fill=_rgb(a))
        # Funkel-Zeichen: vier spitze Rauten in Ink
        for dx, dy, s in ((0, -6, 34), (40, -40, 14), (-38, 30, 10)):
            cx, cy = m[0] + dx, m[1] + dy
            z.polygon([(cx, cy - s), (cx + s * 0.28, cy), (cx, cy + s), (cx - s * 0.28, cy)], fill=_rgb(INK))
            z.polygon([(cx - s, cy), (cx, cy - s * 0.28), (cx + s, cy), (cx, cy + s * 0.28)], fill=_rgb(INK))
        _speichern(bild, pfad, "PNG")
    return f"medien:{name}"


def glow(akzent: str, ordner: str) -> str | None:
    if not _HEX.match(akzent or ""):
        return None
    a = akzent.lower()
    name = f"tech-glow-{a[1:]}.jpg"
    pfad = _ziel(ordner, name)
    if pfad is None:
        return None
    if not os.path.exists(pfad):
        bild = _halo(1200, 900, (984, 378), 620, mischen(a, INK, 0.80), INK)
        _speichern(bild, pfad, "JPEG")
    return f"medien:{name}"
```

- [ ] **Step 4: Tests PASS.** Run: `python -m pytest spaces/marketing/claw/tests/test_vorlagen_grafik.py -q -p no:cacheprovider`

- [ ] **Step 5: Commit (MOS)**

```powershell
git add spaces/marketing/claw/vorlagen_grafik.py spaces/marketing/claw/tests/test_vorlagen_grafik.py
git commit -m "feat(marketing): tech-Grafiken (Signal-Karte, Lichtschein) im Ladenakzent mit Pillow"
```

---

### Task 5: API – „Neu aus Vorlage“ mit Ladenmarke, Vorlagenliste für alle Läden (MOS)

**Files:**
- Modify: `spaces/marketing/api/pult.py` (`inhalt_aus_vorlage`, `vorlagen`, `vorlage_vorschau`)
- Test: `spaces/marketing/tests/test_pult_api.py`

**Interfaces:**
- Consumes: `vorlagen_marke.rollen/logo_ablegen/einsetzen`, `vorlagen_grafik.signal/glow`, `api.bilder._ordner()` (liefert `MARKETING_BILD_ORDNER` = media-erzeugt; prüfe den genauen Namen in `api/bilder.py` Zeile ~49), DB-Funktion aus Task 2.
- Produces: `POST /api/pult/inhalte/aus_vorlage` unverändertes Eingabeformat (`vorlage`, `titel`, `mandant`), Antwort `{"id": "<uuid>"}`; `GET /api/pult/vorlagen` liefert eigene + `fuer_alle`, ohne `zurueckgezogen` (außer `status=zurueckgezogen` ausdrücklich).

- [ ] **Step 1: Failing Tests** (Muster `FalscheDB` aus der Datei verwenden)

```python
def test_aus_vorlage_fuellt_rollen_und_uebergibt_dokument(db, c, monkeypatch, tmp_path):
    from spaces.marketing.api import bilder
    monkeypatch.setattr(bilder, "_ordner", lambda: str(tmp_path))
    vorlage = {"root": {"type": "EmailLayout", "data": {"childrenIds": ["marke_wort", "band"], "canvasColor": "#ffffff",
               "rollen": {"band/data/style/backgroundColor": "akzent", "marke_wort/data/props/text": "laden"}}},
               "marke_wort": {"type": "Heading", "data": {"props": {"text": "[Laden]"}}},
               "band": {"type": "Text", "data": {"style": {"backgroundColor": "#c2410c"}, "props": {"text": "x"}}}}
    db.antworten = [[{"bloecke": vorlage}],
                    [{"laden": "Radhaus Jena", "layout": "radhaus-nl", "gestalt": {"akzent": "#123456"}}],
                    [{"id": "11111111-1111-1111-1111-111111111111"}]]
    r = c.post("/api/pult/inhalte/aus_vorlage", json={"vorlage": "studio", "titel": "Oktober", "mandant": "radhaus"},
               headers=H)
    assert r.status_code == 200, r.text
    sql = db.sql[2]
    assert "pult_inhalt_aus_vorlage" in sql and "#123456" in sql and "Radhaus Jena" in sql and "'radhaus-nl'" in sql
    assert "fuer_alle" in db.sql[0]


def test_aus_vorlage_ohne_layout_ersatzpalette(db, c, monkeypatch, tmp_path):
    from spaces.marketing.api import bilder
    monkeypatch.setattr(bilder, "_ordner", lambda: "")
    vorlage = {"root": {"type": "EmailLayout", "data": {"childrenIds": [], "rollen": {}}}}
    db.antworten = [[{"bloecke": vorlage}], [{"laden": "L", "layout": None, "gestalt": None}], [{"id": "x"}]]
    assert c.post("/api/pult/inhalte/aus_vorlage", json={"vorlage": "studio", "titel": "T", "mandant": "radhaus"},
                  headers=H).status_code == 200


def test_aus_vorlage_unbekannt_422(db, c):
    db.antworten = [[]]
    r = c.post("/api/pult/inhalte/aus_vorlage", json={"vorlage": "studio", "titel": "T"}, headers=H)
    assert r.status_code == 422


def test_vorlagenliste_eigene_und_fuer_alle(db, c):
    db.antworten = [[{"name": "studio", "beschreibung": "", "status": "freigegeben", "fassung": 1}]]
    assert c.get("/api/pult/vorlagen?mandant=radhaus", headers=H).status_code == 200
    assert "fuer_alle" in db.sql[0] and "zurueckgezogen" in db.sql[0]
```
Bestehende Tests zu `aus_vorlage`, die die 3-arg-Funktion erwarten, auf den neuen Ablauf anpassen (Antworten-Reihenfolge: Vorlage, Laden, Ergebnis).

- [ ] **Step 2: FAIL bestätigen.**

- [ ] **Step 3: Implementieren**

```python
from spaces.marketing.api import bilder as _bilder
from spaces.marketing.claw import vorlagen_grafik, vorlagen_marke


@router.post("/inhalte/aus_vorlage")
def inhalt_aus_vorlage(payload: dict = Body(...), x_pult_key: str | None = Header(None)):
    _schluessel(x_pult_key)
    vorlage = payload.get("vorlage")
    if not isinstance(vorlage, str) or not _VORLAGE.match(vorlage):
        raise HTTPException(422, "Unbekannte Vorlage")
    titel = payload.get("titel")
    if not isinstance(titel, str) or not titel.strip() or len(titel.strip()) > 200:
        raise HTTPException(422, "titel fehlt oder ist laenger als 200 Zeichen")
    m = _mandant(payload.get("mandant"))
    v = _lesen_einer(lambda:
        "SELECT bloecke FROM marketing.newsletter_vorlagen "
        f"WHERE name = {lit(vorlage)} AND status = 'freigegeben' AND (mandant = {lit(m)} OR fuer_alle)")
    if not v:
        raise HTTPException(422, f"Vorlage {vorlage} gibt es nicht oder sie ist nicht freigegeben")
    laden = _lesen_einer(lambda:
        "SELECT m.name AS laden, l.name AS layout, l.gestalt FROM marketing.mandanten m "
        "LEFT JOIN marketing.layout_vorlagen l ON l.mandant = m.id AND l.standard AND l.inhaltsart = 'newsletter' "
        f"WHERE m.id = {lit(m)}") or {}
    dok = v["bloecke"]
    grund = ((dok.get("root") or {}).get("data") or {}).get("canvasColor") or "#ffffff"
    werte: dict = vorlagen_marke.rollen(laden.get("gestalt"), grund)
    ordner = _bilder._ordner()
    werte["laden"] = str(laden.get("laden") or m)
    logo = vorlagen_marke.logo_ablegen(laden.get("gestalt"), m, ordner)
    if logo:
        werte["logo"] = logo
    rollen_tab = ((dok.get("root") or {}).get("data") or {}).get("rollen") or {}
    if "signal_bild" in rollen_tab.values():
        werte["signal_bild"] = vorlagen_grafik.signal(werte["akzent"], ordner) or "medien:platzhalter-4x3.png"
    if "glow_bild" in rollen_tab.values():
        werte["glow_bild"] = vorlagen_grafik.glow(werte["akzent"], ordner) or "medien:platzhalter-4x3.png"
    fertig = vorlagen_marke.einsetzen(dok, werte)
    layout = laden.get("layout")
    zeile = _schreiben(lambda:
        f"SELECT marketing.pult_inhalt_aus_vorlage({lit(vorlage)}, {lit(titel.strip())}, {lit(m)}, "
        f"{lit(json.dumps(fertig, ensure_ascii=False))}::jsonb, {lit(layout) if layout else 'NULL'}) AS id")
    return {"id": str(zeile["id"])}
```
`vorlagen`: `_auswahl(status, ("vorschlag", "freigegeben", "zurueckgezogen"), "status")`; `wo = [f"(mandant = {lit(m)} OR fuer_alle)"] + ([f"status = {lit(s)}"] if s else ["status <> 'zurueckgezogen'"])`.
`vorlage_vorschau`: `WHERE v.name = {lit(name)} AND (v.mandant = {lit(m)} OR v.fuer_alle)` und `JOIN marketing.mandanten m ON m.id = {lit(m)}` (Pflichtteil des anfragenden Ladens).
Prüfe, ob `_ordner` in `api/bilder.py` ohne Umgebungsvariable wirft; falls ja, in `try/except` auf `""` fallen.

- [ ] **Step 4: Tests PASS.** Run: `python -m pytest spaces/marketing/tests/test_pult_api.py -q -p no:cacheprovider`

- [ ] **Step 5: Commit (MOS)**

```powershell
git add spaces/marketing/api/pult.py spaces/marketing/tests/test_pult_api.py
git commit -m "feat(marketing): Neu aus Vorlage mit Ladenfarben, Logo-Datei und tech-Grafiken; Vorlagen fuer alle Laeden"
```

---

### Task 6: Bildplätze kennen Container-Hintergründe und überspringen Grafiken (MOS)

**Files:**
- Modify: `spaces/marketing/claw/bildplaetze.py` (`_platz`, `finde`)
- Test: `spaces/marketing/claw/tests/test_bildplaetze.py`

**Interfaces:**
- Produces: `bildplaetze.finde(dok)` liefert zusätzlich einen `Platz` für jeden Container mit `props.url`, `props.width`, `props.height` (> 0) und ohne `props.grafik`; Image-Blöcke mit `props.grafik is True` werden übersprungen. `Platz.flaeche` für Container-Plätze = eigene `style.backgroundColor` oder canvasColor.

- [ ] **Step 1: Failing Tests**

```python
def test_container_hintergrund_ist_platz():
    d = dok(["kopf"], kopf={"type": "Container", "data": {"style": {"backgroundColor": "#2f4858"},
            "props": {"url": "medien:platzhalter-2x1.png", "width": 600, "height": 300, "childrenIds": ["t"]}}},
            t=text("Titel"))
    plaetze = bp.finde(d)
    assert [p.id for p in plaetze] == ["kopf"]
    p = plaetze[0]
    assert (p.anzeige_breite, p.anzeige_hoehe, p.verhaeltnis, p.leer, p.flaeche) == (600, 300, "2:1", True, "#2f4858")


def test_grafik_ist_kein_platz():
    d = dok(["g"], g={"type": "Image", "data": {"style": {}, "props": {"url": "medien:tech-signal-b5f750.png",
                                                                       "width": 536, "height": 380, "grafik": True}}})
    assert bp.finde(d) == []
```

- [ ] **Step 2: FAIL bestätigen.**

- [ ] **Step 3: Implementieren** – in `_platz`: `if not isinstance(b, dict) or b.get("type") not in ("Image", "Container"): return None`; `if props.get("grafik") is True: return None`; für Container: `if b.get("type") == "Container" and not props.get("url"): return None`; Container nutzen `verfuegbar = MAIL_BREITE` und kein Padding-Abzug (`links, rechts = 0, 0`), Kontext aus den Kindtexten (`props.childrenIds`). In `finde`, Zweig `Container`: vor der Kinderschleife `if (p := _platz(dok, bid, MAIL_BREITE, oben, style.get("backgroundColor") or innen)): plaetze.append(p)`.

- [ ] **Step 4: Tests PASS** – Run: `python -m pytest spaces/marketing/claw/tests/test_bildplaetze.py spaces/marketing/tests/test_bild_worker.py -q -p no:cacheprovider`

- [ ] **Step 5: Commit (MOS)**

```powershell
git add spaces/marketing/claw/bildplaetze.py spaces/marketing/claw/tests/test_bildplaetze.py
git commit -m "feat(marketing): Bildplaetze - Container-Hintergruende als Platz, erzeugte Grafiken ausgenommen"
```

---

### Task 7: Die sieben Vorlagen bauen, einspielen, alte zurückziehen (MOS)

**Files:**
- Modify (neu schreiben): `spaces/marketing/scripts/vorlagen_bauen.py`
- Modify: `spaces/marketing/scripts/vorlagen_einspielen.py` (fuer_alle, zurückziehen)
- Delete: `spaces/marketing/vorlagen/newsletter/{newsletter,ankuendigung,einladung,produkt-neuheit,kurzer-hinweis}.json`
- Create: `spaces/marketing/vorlagen/newsletter/{studio,zeitung,firmenblatt,minimal,klassik,bildkopf,tech}.json` (vom Skript erzeugt)
- Modify: `spaces/marketing/claw/tests/test_startvorlagen.py` (NAMEN, alte Stiltests ersetzen), `spaces/marketing/tests/test_vorlagen_einspielen.py`
- Modify: `spaces/marketing/vorlagen/newsletter/HERKUNFT.md`

**Interfaces:**
- Consumes: Rollen-Konvention (oben), Schriftpaare (oben), `vorlagen_marke.rollen/einsetzen`, `schoenheit.bloecke_pruefen`, `bloecke_mjml.rendern`, `_fehler`-Spiegel.
- Produces: 7 JSON-Dateien `{"name", "beschreibung", "bloecke"}`; `vorlagen_einspielen.main(wirklich: bool) -> int` setzt `fuer_alle = true` für jede Datei und `status = 'zurueckgezogen'` für DB-Vorlagen der Startvorlagen-Liste, die keine Datei mehr haben (`newsletter`, `ankuendigung`, `einladung`, `produkt-neuheit`, `kurzer-hinweis`).

- [ ] **Step 1: Failing Tests in `test_startvorlagen.py`**

`NAMEN = ["studio", "zeitung", "firmenblatt", "minimal", "klassik", "bildkopf", "tech"]`; `test_vorlage_im_vibemind_stil`, `test_alle_fuenf_da`, `test_vorlage_ohne_logo_bild_mit_schriftzug` entfernen; neu:
```python
from spaces.marketing.claw import schoenheit, vorlagen_marke

PALETTEN = [{"akzent": "#facc15"}, {"akzent": "#111111", "flaeche": "#111111"},
            {"akzent": "#c2410c", "flaeche": "#2f4858"}, {"akzent": "#9ca3af"}]
SCHRIFTPAAR = {"studio": ("cormorant", "dm-sans"), "zeitung": ("playfair", "poppins"),
               "firmenblatt": ("young-serif", "poppins"), "minimal": ("manrope", "manrope"),
               "klassik": ("bodoni", "montserrat"), "bildkopf": ("josefin", "josefin"), "tech": ("oxanium", "rajdhani")}


def test_alle_sieben_da():
    assert sorted(p.stem for p in ORDNER.glob("*.json")) == sorted(NAMEN)


@pytest.mark.parametrize("name", NAMEN)
def test_schriftpaar_und_marke(name):
    d = _laden(name)["bloecke"]
    w = d["root"]["data"]
    assert (w["schriften"]["anzeige"], w["schriften"]["text"]) == SCHRIFTPAAR[name]
    assert "marke_logo" in d and "marke_wort" in d
    assert w["rollen"]["marke_logo/data/props/url"] == "logo" and w["rollen"]["marke_wort/data/props/text"] == "laden"


@pytest.mark.parametrize("name", NAMEN)
@pytest.mark.parametrize("gestalt", PALETTEN)
def test_jede_palette_gueltig_lesbar_und_klein(name, gestalt):
    d = _laden(name)["bloecke"]
    grund = d["root"]["data"].get("canvasColor") or "#ffffff"
    werte = {**vorlagen_marke.rollen(gestalt, grund), "laden": "Radhaus Jena",
             "signal_bild": "medien:tech-signal-aaaaaa.png", "glow_bild": "medien:tech-glow-aaaaaa.jpg"}
    fertig = vorlagen_marke.einsetzen(d, werte)
    assert _fehler(fertig) is None
    assert schoenheit.bloecke_pruefen(fertig) == []
    html = bloecke_mjml.rendern(fertig, "Betreff", "Vorschau", {"impressum": "Radhaus Jena, Wagnergasse 5",
                                "abmelde_hinweis": "Abmelden: {abmeldelink}"},
                                bild_basis="https://ui.example.de/marketing/bild/1.a/",
                                schrift_basis="https://ui.example.de/marketing/schrift/")
    assert len(html.encode("utf-8")) < 102 * 1024
    assert "{" not in "".join(str(v) for v in fertig.values() if isinstance(v, dict) and v.get("type") != "EmailLayout")


@pytest.mark.parametrize("name", NAMEN)
def test_mindestens_ein_leerer_bildplatz(name):
    from spaces.marketing.claw import bildplaetze
    assert any(p.leer for p in bildplaetze.finde(_laden(name)["bloecke"])) or name == "tech"


def test_tech_traegt_grafikrollen():
    w = _laden("tech")["bloecke"]["root"]["data"]
    assert {"signal_bild", "glow_bild"} <= set(w["rollen"].values()) and w.get("dunkel") is True
```
Bestehende Tests `test_vorlage_gueltig_und_rendert`, `test_textkante_einheitlich`, `test_keine_echt_wirkenden_beispielwerte`, `test_spalten_haben_genau_drei_eintraege`, `test_vorlage_hat_die_bildplaetze_der_spec`, `test_platzhalter_sind_klein_und_im_verhaeltnis` auf die neuen Namen/Plätze anpassen (Sinn behalten: gültig, keine echt wirkenden Daten wie echte Telefonnummern/Adressen, Spalten vollständig).

- [ ] **Step 2: FAIL bestätigen** (Dateien fehlen).

- [ ] **Step 3: `vorlagen_bauen.py` neu schreiben**

Gemeinsame Bausteine (eine Klasse `Bau` mit `bloecke: dict`, `kinder: list`, `rollen: dict`; Methoden geben die Block-ID zurück):
```python
class Bau:
    def __init__(self, name, beschreibung, grund, text, aussen, anzeige, textschrift, dunkel=False):
        self.name, self.beschreibung = name, beschreibung
        self.bloecke = {"root": {"type": "EmailLayout", "data": {
            "backdropColor": aussen, "canvasColor": grund, "textColor": text, "childrenIds": [],
            "schriften": {"anzeige": anzeige, "text": textschrift}, "rollen": {}, **({"dunkel": True} if dunkel else {})}}}

    @property
    def rollen(self):
        return self.bloecke["root"]["data"]["rollen"]

    def add(self, bid, typ, style=None, props=None, rollen=None, oben=True):
        self.bloecke[bid] = {"type": typ, "data": {"style": style or {}, "props": props or {}}}
        for pfad, rolle in (rollen or {}).items():
            self.rollen[f"{bid}/{pfad}"] = rolle
        if oben:
            self.bloecke["root"]["data"]["childrenIds"].append(bid)
        return bid

    def json(self):
        return {"name": self.name, "beschreibung": self.beschreibung, "bloecke": self.bloecke}
```
Hilfen: `pad(t, b, l=32, r=32)`, `ueber(text, groesse, farbe, anzeige=True, versal=False, sperr=None, zh=None, ausr="left", p=None)` → Heading-Style `{"fontFamily": "ANZEIGE" if anzeige else "TEXT", "fontSize": groesse, "color": farbe, ...}`, `meta(text, farbe)` → Text 11 px, `letterSpacing` 2.5, `textTransform` uppercase, `fontFamily` TEXT, `bild(w, h, alt)` mit Platzhalter `medien:platzhalter-<a>x<b>.png` aus `bildplaetze.platzhalter_name`, `knopf(text)` mit `url "https://www.example.de"`, Rollen `data/props/buttonBackgroundColor: akzent`, `data/props/buttonTextColor: auf_akzent`.
Musterwerte: Akzent `#c2410c`, `zweit` `#2f4858`, `auf_akzent` `#ffffff`, `akzent_hell` `#f9ece6`, `akzent_text` `#b23c0b`.

Je Vorlage den Aufbau aus Spec §3 umsetzen (Masthead · Hauptthema mit Bild · zwei Nebenthemen · Aktion · Abschluss mit Knopf · Fuß), mit diesen festen Werten:
- **studio**: Grund `#faf7f2`, Text `#2b2724`, außen `#efe9e0`. Masthead-Container mit Haarlinie (`borderColor #2b2724`): `meta("Ausgabe [Nr]")`, `marke_logo` (120×40) / `marke_wort` (Anzeige 26 px, sperr 4, versal), darunter Divider `#2b2724`. Hauptthema: ColumnsContainer 2 Spalten (Bild 4:5 links | Anzeige-Titel 34 px „Willkommen zum *[Monat]*brief“, Text). Nebenthemen: Überschrift links (Anzeige 26) + Text rechts (2 Spalten), Fotostreifen 3 Spalten (je 3:2). Aktion: Text + Knopf. Fuß: `meta("[Telefon] · [Website] · @[instagram]")`.
- **zeitung**: Grund `#f8f1e6`, Text `#2a2522`. Masthead: `meta` Zeile „[Laden] · @[instagram]“ (Rolle `akzent_text` für color), Divider (Rolle `akzent` für lineColor), `marke_wort` Anzeige 56 px zentriert mit Rolle `akzent_text`, Divider, Band (Text, Rolle `akzent` backgroundColor, `auf_akzent` color, versal, sperr 3). Hauptthema 2 Spalten Text | Bild `sw: true`. Aktion: Container Rolle `akzent` backgroundColor mit Heading versal (Rolle `auf_akzent`) und Text (Rolle `auf_akzent`). Nebenthema 2 Spalten Bild `sw: true` | Text mit Kicker (Rolle `akzent_text`).
- **firmenblatt**: Grund `#ffffff`, Text `#2b2724`. Masthead-Container Rolle `zweit` (backgroundColor) mit `marke_wort` Anzeige 34 px „Der *[Laden]* Rundbrief“ Rolle `akzent_hell`… Achtung Kontrast: Titel-Farbe Rolle `auf_zweit`; Datum/Ausgabe `meta` Rolle `auf_zweit`. Kontaktleiste: ColumnsContainer 3 Spalten, Hintergrund Rolle `akzent_hell`, Texte 11 px fett „[Telefon]“ „[Website]“ „@[instagram]“. Bild 2:1. Kicker (Rolle `akzent_text`) + Anzeige-Titel 24 px (Rolle `zweit`). Getöntes Feld: ColumnsContainer Rolle `akzent_hell` mit Text | Bild 3:2.
- **minimal**: Grund `#f4f3ef`, Text `#111111`. Linkzeile: ColumnsContainer 3 Spalten `meta("Laden")`, `meta("Angebote")`, `meta("Kontakt")` + Divider `#111111`. `marke_wort` Anzeige 52 px, `fontWeight normal`, `letterSpacing -1`, versal. Hauptthema 2 Spalten (Heading versal 20 px, `fontWeight normal` | Bild 4:5). Zitat: 2 Spalten (Text „→“ 28 px Rolle `akzent_text` | Text versal 16 px). Fuß: `meta`-Zeile.
- **klassik**: Grund `#ffffff`, Text `#2b2724`, alles zentriert. Ausgabezeile `meta` zentriert Rolle `akzent_text`, `marke_wort` Anzeige 44 px kursiv (Text `*[Laden]*`), Unterzeile `meta` Rolle `akzent_text`, „Was drin ist …“ `meta`, Bildreihe 3 Spalten (1:1), Überschrift versal sperr 3 (TEXT-Schrift, 16 px), Autorzeile `meta` Rolle `akzent_text`, Text links, Fußband Text Rolle `akzent` backgroundColor + `auf_akzent` color, versal.
- **bildkopf**: Grund `#efecea`, Text `#2b2724`. Kopf: Container `props.url = medien:platzhalter-2x1.png`, `width 600`, `height 300`, `style.backgroundColor` Rolle `zweit`, `style.overlay {farbe: "#2f4858", deckkraft: 86}` mit Rolle `data/style/overlay/farbe: zweit`; darin `marke_wort` Anzeige 24 px `fontWeight normal` Rolle `auf_zweit`, Heading „NEWSLETTER“ 30 px versal sperr 6 Rolle `auf_zweit`, `meta` Rolle `auf_zweit`. Hauptthema 2 Spalten: links Container… (Rahmen nur oberste Ebene!) → stattdessen ColumnsContainer mit Spaltenhintergrund über Text-`backgroundColor` Rolle `zweit` | Text + Bild 3:2. Tipp-Kasten: Container Rolle `akzent` backgroundColor, Heading + Text Rolle `auf_akzent`.
- **tech** (Spec §3.1 wörtlich): Grund/außen `#080b13`, Text `#9caabe`, `dunkel: true`. Kopf: Container `props.url` Rolle `glow_bild` (`grafik: true`, `width 600`, `height 420`, `backgroundColor #080b13`), darin `marke_wort` Anzeige 20 px `#f3f7fc` versal, Pill-Text „● [Rubrik] × [Thema]“ 12 px versal sperr 2 Rolle `akzent` (color) mit Rahmen über Container-Karte Rolle `akzent_rahmen` (borderColor)… (Rahmen nur oberste Ebene – Pill daher als eigener Container direkt unter dem Kopf), H1 40 px `#f3f7fc` `letterSpacing -1` `lineHeight 1.05`, Text 20 px Rajdhani (TEXT) `#9caabe` `lineHeight 1.45`, Knopf Rolle `akzent`/`auf_akzent` Text „[Gespräch starten] ↗“. Abschnitte mit Kicker „01 / [WAS WIR TUN]“ (Anzeige 12 px, sperr 2, versal, Rolle `akzent`), H2 34 px `#f3f7fc`, Karten als Container `backgroundColor #111725`, `borderColor #263044`, `borderRadius 12`, Innenabstand 28; Signal-Bild Image `grafik: true` 536×380 Rolle `signal_bild`; Kontaktblock Container `#111725`; Fuß Divider `#263044`, `marke_wort` nicht doppelt (Fuß-Wortmarke als normaler Text „[Laden]“ mit Rolle `laden`).

Alle Texte sind Platzhalter in eckigen Klammern oder neutrale Beispielsätze für Läden (z. B. „[Ein Satz, worum es diesen Monat geht.]“).
`main()` schreibt die sieben Dateien (`json.dumps(..., ensure_ascii=False, indent=1)`) und löscht nichts.

- [ ] **Step 4: Dateien erzeugen, alte löschen**

Run: `python -m spaces.marketing.scripts.vorlagen_bauen` ; dann `git rm spaces/marketing/vorlagen/newsletter/newsletter.json spaces/marketing/vorlagen/newsletter/ankuendigung.json spaces/marketing/vorlagen/newsletter/einladung.json spaces/marketing/vorlagen/newsletter/produkt-neuheit.json spaces/marketing/vorlagen/newsletter/kurzer-hinweis.json`

- [ ] **Step 5: `vorlagen_einspielen.py` erweitern + Test**

Nach erfolgreichem Einspielen (`--wirklich`): `UPDATE marketing.newsletter_vorlagen SET fuer_alle = true WHERE name = <name>`; danach für `ALTE = ("newsletter", "ankuendigung", "einladung", "produkt-neuheit", "kurzer-hinweis")` ohne Datei: `UPDATE marketing.newsletter_vorlagen SET status = 'zurueckgezogen' WHERE name = <name> AND status <> 'zurueckgezogen'` und Ausgabe „<name>: zurückgezogen“. Ohne `--wirklich` nur ausgeben, was geschähe. Test in `tests/test_vorlagen_einspielen.py` (Muster der bestehenden Tests mit gefälschtem `_db`): nach `main(True)` enthält das protokollierte SQL `fuer_alle = true` und `status = 'zurueckgezogen'` für `newsletter`; `main(False)` schreibt nichts.

- [ ] **Step 6: Tests PASS** – Run: `python -m pytest spaces/marketing/claw/tests/test_startvorlagen.py spaces/marketing/tests/test_vorlagen_einspielen.py -q -p no:cacheprovider`. Danach gegen die Live-DB nur prüfen (schreibt nichts, braucht 058 noch nicht für alte Felder – die neuen Felder werden erst nach 058 gültig, daher hier erwartbar „UNGUELTIG … Schriftpaar“): erst in Task 11 ausführen.

- [ ] **Step 7: `HERKUNFT.md` aktualisieren** (sieben Vorlagen, Musterkatalog statt Kopie, Schriften OFL, Spec-Verweis) und **Commit (MOS)**

```powershell
git add spaces/marketing/scripts/vorlagen_bauen.py spaces/marketing/scripts/vorlagen_einspielen.py spaces/marketing/vorlagen/newsletter spaces/marketing/claw/tests/test_startvorlagen.py spaces/marketing/tests/test_vorlagen_einspielen.py
git commit -m "feat(marketing): sieben Newsletter-Vorlagen (studio bis tech) mit Ladenrollen; alte Startvorlagen zurueckgezogen"
```

---

### Task 8: sales-ui – eigene Schriften, Schwarz-Weiß-Auslieferung, Vorschau-CSP (SC)

**Files:**
- Create: `sales-mcp/schriften.py`, `sales-mcp/static/schriften/*.woff2` (+ `OFL-<id>.txt`), `scripts/schriften_holen.py`
- Modify: `sales-mcp/ui_editor.py` (Routen `/marketing/schrift/{datei}`, Bildroute `?sw=1`, `CSP_EDITOR`), `sales-mcp/ui.py` (Anmelde-Ausnahme für `/marketing/schrift/`), `sales-mcp/ui_marketing.py` (`_CSP_VORSCHAU` + `font-src 'self'`)
- Test: `sales-mcp/tests/test_editor_seite.py`

**Interfaces:**
- Produces: `GET /marketing/schrift/schriften.css` (text/css, `@font-face` je Datei mit relativen `url(<datei>)`), `GET /marketing/schrift/<id>-<gewicht>-<stil>.woff2` (font/woff2), beide ohne Anmeldung, `Access-Control-Allow-Origin: *`, `Cache-Control: public, max-age=31536000, immutable`; Bildroute liefert bei `?sw=1` eine Graustufen-JPEG/PNG-Fassung. `schriften.REGISTER` (gleiche IDs/Familien wie MOS Task 1).

- [ ] **Step 1: Schriften holen (einmalig, Netz)**

`scripts/schriften_holen.py` lädt je Registereintrag `https://cdn.jsdelivr.net/fontsource/fonts/<slug>@latest/latin-<gewicht>-<stil>.woff2` nach `sales-mcp/static/schriften/<id>-<gewicht>-<stil>.woff2` und `https://cdn.jsdelivr.net/npm/@fontsource/<slug>/LICENSE` nach `OFL-<id>.txt`; bricht bei HTTP-Fehler mit Namen ab; schreibt nichts doppelt. Run: `python scripts/schriften_holen.py` – Expected: 24 woff2 + 11 Lizenzdateien, jede woff2 beginnt mit `wOF2`.

- [ ] **Step 2: Failing Tests** (in `test_editor_seite.py`, ohne Anmeldung mit `TestClient(ui.app)`)

```python
def test_schrift_css_ohne_anmeldung_mit_cors():
    c = TestClient(ui.app)
    r = c.get("/marketing/schrift/schriften.css", headers=HOST)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert r.headers["access-control-allow-origin"] == "*"
    assert "font-family: 'Oxanium'" in r.text and "url(oxanium-600-normal.woff2)" in r.text


def test_schriftdatei_und_nichts_anderes():
    c = TestClient(ui.app)
    r = c.get("/marketing/schrift/poppins-400-normal.woff2", headers=HOST)
    assert r.status_code == 200 and r.content[:4] == b"wOF2" and r.headers["content-type"] == "font/woff2"
    for boese in ("../ui.py", "poppins.ttf", "x-400-normal.woff2", "%2e%2e%2fui.py"):
        assert c.get(f"/marketing/schrift/{boese}", headers=HOST).status_code == 404


def test_vorschau_csp_erlaubt_eigene_schriften():
    import ui_marketing
    assert "font-src 'self'" in ui_marketing._CSP_VORSCHAU


def test_bild_sw(angemeldet, monkeypatch, tmp_path):
    from PIL import Image
    monkeypatch.setattr(server.medien, "MEDIA_VERZEICHNIS", str(tmp_path))
    Image.new("RGB", (8, 8), (200, 30, 30)).save(tmp_path / "rot.png")
    basis = ui_editor.bild_basis() or ""
    if not basis:
        pytest.skip("ohne UI_BASIS_URL kein signierter Pfad")
    pfad = basis.split("://", 1)[1].split("/", 1)[1]
    farbig = angemeldet.get(f"/{pfad}rot.png", headers=HOST)
    grau = angemeldet.get(f"/{pfad}rot.png?sw=1", headers=HOST)
    assert farbig.status_code == grau.status_code == 200
    import io
    px = Image.open(io.BytesIO(grau.content)).convert("RGB").getpixel((4, 4))
    assert px[0] == px[1] == px[2]
```
(Für `test_bild_sw` ggf. `ui.UI_BASIS_URL` per `monkeypatch.setattr(ui, "UI_BASIS_URL", "https://ui.example.de")` setzen, damit `bild_basis()` nicht leer ist.)

- [ ] **Step 3: FAIL bestätigen** (Testbefehl aus Global Constraints).

- [ ] **Step 4: Implementieren**

`sales-mcp/schriften.py`: dasselbe `REGISTER` wie MOS Task 1 (Familie + Dateien), plus
```python
ORDNER = Path(__file__).resolve().parent / "static" / "schriften"
_DATEI = re.compile(r"^([a-z-]+)-(\d{3})-(normal|italic)\.woff2$")


def datei_ok(name: str) -> bool:
    m = _DATEI.match(name or "")
    return bool(m) and m.group(1) in REGISTER and (int(m.group(2)), m.group(3)) in REGISTER[m.group(1)]["dateien"] \
        and (ORDNER / name).is_file()


def css() -> str:
    teile = []
    for sid, s in REGISTER.items():
        for gewicht, stil in s["dateien"]:
            teile.append(f"@font-face {{ font-family: '{s['familie']}'; font-style: {stil}; font-weight: {gewicht}; "
                         f"font-display: swap; src: url({sid}-{gewicht}-{stil}.woff2) format('woff2'); }}")
    return "\n".join(teile) + "\n"
```
`ui_editor.py`: Route `Route("/marketing/schrift/{datei}", schrift)` (GET/HEAD, **ohne** `@ui._gesichert_seite`):
```python
    async def schrift(request):
        datei = request.path_params["datei"]
        kopf = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff"}
        if datei == "schriften.css":
            return Response(schriften.css(), media_type="text/css", headers=kopf)
        if not schriften.datei_ok(datei):
            return Response("Nicht gefunden", status_code=404, media_type="text/plain")
        return Response((schriften.ORDNER / datei).read_bytes(), media_type="font/woff2", headers=kopf)
```
`ui.py`: neben `_SIGNIERTES_BILD` ein `_SCHRIFT = re.compile(r"/marketing/schrift/[A-Za-z0-9._-]{1,80}")` und in der Anmelde-Prüfung genauso durchlassen wie `_signiertes_bild` (nur GET/HEAD).
Bildroute `bild`: nach dem Lesen der Datei, wenn `request.query_params.get("sw") == "1"`: mit Pillow `ImageOps.grayscale` und als gleiches Format zurückgeben (PNG bleibt PNG, sonst JPEG quality 88); bei Pillow-Fehler die Originaldatei.
`CSP_EDITOR`: `font-src 'self' data:` bleibt (deckt `/marketing/schrift/` ab). `_CSP_VORSCHAU`: `"sandbox; default-src 'none'; img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'"` (`style-src 'self'`, damit `schriften.css` aus der Mail-Vorschau laden darf).

- [ ] **Step 5: Tests PASS** (Testbefehl aus Global Constraints mit `tests/test_editor_seite.py tests/test_ui.py -k "schrift or vorschau or bild"`).

- [ ] **Step 6: Commit (SC)**

```powershell
git add sales-mcp/schriften.py sales-mcp/static/schriften scripts/schriften_holen.py sales-mcp/ui_editor.py sales-mcp/ui.py sales-mcp/ui_marketing.py sales-mcp/tests/test_editor_seite.py
git commit -m "feat(ui): eigene OFL-Schriften unter /marketing/schrift, Schwarz-Weiss-Bilder, Vorschau-CSP mit Schriften"
```

---

### Task 9: Editor – erweiterte Schemata, Vorschau mit Vorlagenschriften, neue Regler (SC)

**Files:**
- Create: `editor/src/schemata.ts`, `editor/src/schemata.test.ts`, `editor/src/documents/blocks/Vorlagentext.tsx`
- Modify: `editor/src/documents/editor/core.tsx`, `editor/src/documents/blocks/Container/ContainerPropsSchema.tsx`, `editor/src/documents/blocks/Container/ContainerEditor.tsx`, `editor/src/documents/blocks/EmailLayout/EmailLayoutPropsSchema.tsx`, Panels `HeadingSidebarPanel.tsx`, `TextSidebarPanel.tsx`, `ContainerSidebarPanel.tsx`, `ImageSidebarPanel.tsx`, `editor/src/main.tsx` (Schrift-CSS laden), `editor/package.json` (vitest dev)
- Modify: `sales-mcp/static/editor/*` (Build), `sales-mcp/tests/test_editor_paket.py`

**Interfaces:**
- Consumes: Schrift-IDs (Register oben), Route `/marketing/schrift/schriften.css` (Task 8), Feldnamen aus Spec §4.
- Produces: `HeadingSchema`, `TextSchema`, `ButtonSchema`, `ImageSchema` (zod, in `schemata.ts`); `SCHRIFT_IDS`, `SCHRIFT_FAMILIE: Record<string, string>`.

- [ ] **Step 1: vitest einrichten und failing Test schreiben**

Run: `cd <SC>\editor ; npm install --save-dev vitest@^2` ; in `package.json` `"test": "vitest run"`.
`editor/src/schemata.test.ts`:
```ts
import { describe, expect, it } from 'vitest';

import { HeadingSchema, ImageSchema, TextSchema } from './schemata';
import ContainerPropsSchema from './documents/blocks/Container/ContainerPropsSchema';
import EmailLayoutPropsSchema from './documents/blocks/EmailLayout/EmailLayoutPropsSchema';

describe('neue Felder ueberleben das Bearbeiten', () => {
  it('Heading', () => {
    const d = { style: { fontFamily: 'ANZEIGE', letterSpacing: 3, textTransform: 'uppercase', lineHeight: 1.1 },
                props: { text: 'Herbst*brief*', level: 'h1' } };
    expect(HeadingSchema.parse(d)).toEqual(d);
  });
  it('Text', () => {
    const d = { style: { fontFamily: 'TEXT', letterSpacing: -1 }, props: { text: 'x', markdown: true } };
    expect(TextSchema.parse(d)).toEqual(d);
  });
  it('Image', () => {
    const d = { style: {}, props: { url: '/medien/datei/a.jpg', width: 600, height: 300, sw: true, grafik: false } };
    expect(ImageSchema.parse(d)).toEqual(d);
  });
  it('Container', () => {
    const d = { style: { overlay: { farbe: '#2f4858', deckkraft: 86 } },
                props: { childrenIds: ['a'], url: 'medien:kopf.jpg', width: 600, height: 300, grafik: false } };
    expect(ContainerPropsSchema.parse(d)).toEqual(d);
  });
  it('EmailLayout', () => {
    const d = { childrenIds: [], schriften: { anzeige: 'oxanium', text: 'rajdhani' }, dunkel: true,
                rollen: { 'a/data/props/text': 'laden' } };
    expect(EmailLayoutPropsSchema.parse(d)).toEqual(d);
  });
  it('lehnt Unsinn ab', () => {
    expect(HeadingSchema.safeParse({ style: { letterSpacing: 99 }, props: {} }).success).toBe(false);
    expect(EmailLayoutPropsSchema.safeParse({ schriften: { anzeige: 'comic' } }).success).toBe(false);
  });
});
```

- [ ] **Step 2: FAIL bestätigen** – Run: `npm test` – Expected: `Cannot find module './schemata'`.

- [ ] **Step 3: `schemata.ts` schreiben**

```ts
import { z } from 'zod';

import { ButtonPropsSchema } from '@usewaypoint/block-button';
import { HeadingPropsSchema } from '@usewaypoint/block-heading';
import { ImagePropsSchema } from '@usewaypoint/block-image';
import { TextPropsSchema } from '@usewaypoint/block-text';

export const SCHRIFT_IDS = ['cormorant', 'dm-sans', 'playfair', 'poppins', 'young-serif', 'manrope', 'bodoni',
  'montserrat', 'josefin', 'oxanium', 'rajdhani'] as const;
export const SCHRIFT_FAMILIE: Record<string, string> = {
  cormorant: "'Cormorant Garamond', Georgia, serif", 'dm-sans': "'DM Sans', Arial, sans-serif",
  playfair: "'Playfair Display', Georgia, serif", poppins: 'Poppins, Arial, sans-serif',
  'young-serif': "'Young Serif', Georgia, serif", manrope: 'Manrope, Arial, sans-serif',
  bodoni: "'Bodoni Moda', Didot, Georgia, serif", montserrat: 'Montserrat, Arial, sans-serif',
  josefin: "'Josefin Sans', 'Trebuchet MS', Arial, sans-serif", oxanium: "Oxanium, 'Trebuchet MS', Arial, sans-serif",
  rajdhani: "Rajdhani, 'Arial Narrow', Arial, sans-serif",
};
const ALT = ['MODERN_SANS', 'BOOK_SANS', 'ORGANIC_SANS', 'GEOMETRIC_SANS', 'HEAVY_SANS', 'ROUNDED_SANS',
  'MODERN_SERIF', 'BOOK_SERIF', 'MONOSPACE'] as const;
export const FontFamily = z.enum([...ALT, 'ANZEIGE', 'TEXT']).nullable().optional();
const Fein = {
  fontFamily: FontFamily,
  letterSpacing: z.number().min(-2).max(8).nullable().optional(),
  textTransform: z.enum(['none', 'uppercase']).nullable().optional(),
  lineHeight: z.number().min(0.9).max(2).nullable().optional(),
};

function mitStil<T extends z.ZodTypeAny>(basis: T, extra: z.ZodRawShape) {
  const b = basis as unknown as z.ZodObject<{ style: z.ZodTypeAny; props: z.ZodTypeAny }>;
  const stil = (b.shape.style as z.ZodNullable<z.ZodOptional<z.ZodObject<z.ZodRawShape>>>).unwrap().unwrap();
  return z.object({ style: stil.extend(extra).optional().nullable(), props: b.shape.props });
}

export const HeadingSchema = mitStil(HeadingPropsSchema, Fein);
export const TextSchema = mitStil(TextPropsSchema, Fein);
export const ButtonSchema = mitStil(ButtonPropsSchema, { fontFamily: FontFamily });
const bildProps = (ImagePropsSchema.shape.props as z.ZodNullable<z.ZodOptional<z.ZodObject<z.ZodRawShape>>>).unwrap().unwrap();
export const ImageSchema = z.object({
  style: ImagePropsSchema.shape.style,
  props: bildProps.extend({ sw: z.boolean().nullable().optional(), grafik: z.boolean().nullable().optional() })
    .optional().nullable(),
});
```
(Wenn die `unwrap()`-Reihenfolge nicht passt – `tsc` meldet es –, die Verschachtelung aus `node_modules/@usewaypoint/block-heading/dist/index.d.ts` ablesen: `ZodNullable<ZodOptional<ZodObject>>` ⇒ `.unwrap().unwrap()`.)

`ContainerPropsSchema.tsx`: `style: BaseContainerPropsSchema.shape.style` → um `overlay: z.object({ farbe: z.string().regex(/^#[0-9a-fA-F]{6}$/), deckkraft: z.number().min(0).max(100) }).nullable().optional()` erweitern (gleiche `mitStil`-Technik); `props` um `url: z.string().nullable().optional(), width: z.number().nullable().optional(), height: z.number().nullable().optional(), grafik: z.boolean().nullable().optional()`.
`EmailLayoutPropsSchema.tsx`: `schriften: z.object({ anzeige: z.enum(SCHRIFT_IDS), text: z.enum(SCHRIFT_IDS) }).partial().nullable().optional()`, `dunkel: z.boolean().nullable().optional()`, `rollen: z.record(z.string(), z.string()).nullable().optional()`.

- [ ] **Step 4: Tests PASS** – Run: `npm test` und `npx tsc --noEmit` – Expected: alle grün, 0 Fehler.

- [ ] **Step 5: Darstellung und Regler**

1. `Vorlagentext.tsx`: Wrapper-Komponenten `VorlagenHeading`/`VorlagenText`, die das Paket-Heading/-Text in ein `<div style={{ fontFamily, letterSpacing, textTransform, lineHeight }}>` setzen; `fontFamily` aus `ANZEIGE`/`TEXT` über das aktuelle Dokument (`useDocument().root.data.schriften`) und `SCHRIFT_FAMILIE`; an das Paket wird `style` ohne `fontFamily` (wenn ANZEIGE/TEXT) weitergegeben, damit das Paket nicht überschreibt. Überschrift: `*kursiv*` als `<em>` anzeigen (eigene kleine Umsetzung statt Paket-Heading für den Text).
2. `core.tsx`: `Heading: { schema: HeadingSchema, Component: VorlagenHeading … }`, `Text: { schema: TextSchema, … }`, `Button: { schema: ButtonSchema, … }`, `Image: { schema: ImageSchema, … }` (Image-Komponente: bei `sw` `filter: grayscale(1)` per Wrapper).
3. `ContainerEditor.tsx`: beim Ändern der Kinder `props: { ...props, childrenIds }` (bisher gingen `url/width/height` verloren!); Hintergrund: wenn `props.url` mit `/medien/datei/` beginnt → `backgroundImage: url(...)`, `backgroundSize: cover`, Mindesthöhe `props.height`; Farbfeld als halbtransparente Ebene.
4. Panels: Heading/Text – Auswahl „Schrift“ mit Optionen `Vorlage – Anzeige` (ANZEIGE), `Vorlage – Text` (TEXT) und den 9 bisherigen; Schalter „Versalien gesperrt“ (an: `textTransform uppercase`, `letterSpacing 2`; aus: beide `null`). Container – „Hintergrundbild aus Medien“ (Kacheln wie im ImageSidebarPanel, setzt `props.url` als `/medien/datei/<name>` und `width 600`, `height` Eingabe 120–600) + „Farbfeld“ (Farbe, Deckkraft 0–100). Image – Schalter „Schwarz-weiß“.
5. `main.tsx`: vor dem Rendern `<link rel="stylesheet" href="/marketing/schrift/schriften.css">` in `document.head` einfügen (CSP `style-src 'self'` erlaubt das).
6. `pult.ts`: die Umschreibung `medien:` ↔ `/medien/datei/` (Funktionen um Zeile 40–70) auch auf `Container.data.props.url` anwenden.

- [ ] **Step 6: Bauen und Paket-Test**

Run: `npx tsc --noEmit ; npm test ; npm run build`. In `sales-mcp/tests/test_editor_paket.py`:
```python
def test_paket_kennt_vorlagenschriften():
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    assert "Vorlage – Anzeige" in text and "Versalien gesperrt" in text and "/marketing/schrift/schriften.css" in text
```
Run (aus `sales-mcp`, Testbefehl aus Global Constraints): `tests/test_editor_paket.py tests/test_editor_seite.py` – Expected: PASS.

- [ ] **Step 7: Commit (SC)**

```powershell
git add editor/package.json editor/package-lock.json editor/src sales-mcp/static/editor sales-mcp/tests/test_editor_paket.py
git commit -m "feat(editor): Vorlagenschriften, Laufweite, Versalien, Hintergrundbild und Schwarz-Weiss bleiben beim Bearbeiten erhalten"
```

---

### Task 10: Sichtabnahme – Galerie aller Vorlagen in 600 und 380 px (MOS, Werkzeug)

**Files:**
- Create: `spaces/marketing/scripts/vorlagen_galerie.py`
- Test: `spaces/marketing/tests/test_vorlagen_galerie.py`

**Interfaces:**
- Consumes: Vorlagen-JSON (Task 7), `vorlagen_marke`, `vorlagen_grafik`, `bloecke_mjml.rendern`.
- Produces: `python -m spaces.marketing.scripts.vorlagen_galerie <zielordner> [--akzent #hex] [--flaeche #hex] [--schrift-basis https://…/] [--bild-basis https://…/]` schreibt je Vorlage `<name>-600.html` und `<name>-380.html` sowie `index.html` (iframes nebeneinander) und erzeugt tech-Grafiken + Platzhalter-Kopien im Zielordner (`bild-basis` Standard: `./`, damit lokal per `python -m http.server` zeigbar).

- [ ] **Step 1: Failing Test**

```python
from spaces.marketing.scripts import vorlagen_galerie


def test_galerie_schreibt_alle(tmp_path):
    assert vorlagen_galerie.main([str(tmp_path), "--akzent", "#c2410c", "--flaeche", "#2f4858"]) == 0
    namen = {p.name for p in tmp_path.iterdir()}
    for n in ("studio", "zeitung", "firmenblatt", "minimal", "klassik", "bildkopf", "tech"):
        assert f"{n}-600.html" in namen and f"{n}-380.html" in namen
    assert "index.html" in namen and any(n.startswith("tech-signal-") for n in namen)
```

- [ ] **Step 2: FAIL bestätigen.**

- [ ] **Step 3: Implementieren**

```python
"""Galerie fuer die Sichtabnahme (Spec 2026-10-01 §10): jede Vorlage mit einer
Ladenpalette gefuellt, in 600 und 380 px, nebeneinander in index.html.
    python -m spaces.marketing.scripts.vorlagen_galerie <ziel> [--akzent #hex] [--flaeche #hex]
           [--bild-basis https://.../] [--schrift-basis https://.../]"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import shutil
import sys

from spaces.marketing.claw import bloecke_mjml, vorlagen_grafik, vorlagen_marke

VORLAGEN = pathlib.Path(__file__).resolve().parents[1] / "vorlagen" / "newsletter"
NAMEN = ["studio", "zeitung", "firmenblatt", "minimal", "klassik", "bildkopf", "tech"]
PFLICHT = {"impressum": "[Laden] · [Straße] · [PLZ Ort]", "abmelde_hinweis": "Abmelden: {abmeldelink}"}


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("ziel")
    a.add_argument("--akzent", default="#c2410c")
    a.add_argument("--flaeche", default="#2f4858")
    a.add_argument("--bild-basis", default="")
    a.add_argument("--schrift-basis", default="")
    o = a.parse_args(argv)
    ziel = pathlib.Path(o.ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    for p in (VORLAGEN / "platzhalter").glob("*.png"):
        shutil.copy(p, ziel / p.name)
    basis = o.bild_basis or "https://galerie.invalid/"
    zellen = []
    for name in NAMEN:
        d = json.loads((VORLAGEN / f"{name}.json").read_text(encoding="utf-8"))["bloecke"]
        grund = d["root"]["data"].get("canvasColor") or "#ffffff"
        werte = {**vorlagen_marke.rollen({"akzent": o.akzent, "flaeche": o.flaeche}, grund), "laden": "[Laden]",
                 "signal_bild": vorlagen_grafik.signal(o.akzent, str(ziel)) or "medien:platzhalter-4x3.png",
                 "glow_bild": vorlagen_grafik.glow(o.akzent, str(ziel)) or "medien:platzhalter-4x3.png"}
        fertig = vorlagen_marke.einsetzen(d, werte)
        for breite, handy in ((600, False), (380, True)):
            h = bloecke_mjml.rendern(fertig, name, "", PFLICHT, bild_basis=basis, handy=handy,
                                     schrift_basis=o.schrift_basis)
            if not o.bild_basis:
                h = h.replace(basis, "")
            (ziel / f"{name}-{breite}.html").write_text(h, encoding="utf-8")
        zellen.append(f'<section><h2>{html.escape(name)}</h2><iframe src="{name}-600.html" width="620" height="1400">'
                      f'</iframe><iframe src="{name}-380.html" width="400" height="1400"></iframe></section>')
    (ziel / "index.html").write_text("<!doctype html><meta charset=utf-8><title>Vorlagen</title>"
                                     "<style>section{display:flex;gap:16px;align-items:flex-start}</style>"
                                     + "".join(zellen), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: PASS** – Run: `python -m pytest spaces/marketing/tests/test_vorlagen_galerie.py -q -p no:cacheprovider`

- [ ] **Step 5: Commit (MOS)**

```powershell
git add spaces/marketing/scripts/vorlagen_galerie.py spaces/marketing/tests/test_vorlagen_galerie.py
git commit -m "feat(marketing): Galerie-Werkzeug fuer die Sichtabnahme der Vorlagen"
```

- [ ] **Step 6: Sichtabnahme mit dem Betreiber (kein Code)** – Galerie in den Scratchpad schreiben, mit `python -m http.server` ausliefern, im Brainstorming-Begleiter (Bildschirm-Fragment mit iframes oder Screenshots) zeigen, Rückmeldung einarbeiten (Änderungen nur in `vorlagen_bauen.py`, Tests aus Task 7 erneut grün). Ohne OK des Betreibers kein Task 11.

---

### Task 11: Auslieferung (beide Repos, VM, PC) – nur nach Freigabe

**Files:** keine Codeänderung; WORKBOARD-/Koordinations-Claim und Gedächtnis.

- [ ] **Step 1: Claims** – WORKBOARD-Zeile `cc-vorlagen-profi` (Ausliefern) und secondbrain `00_Meta/002_Koordination_Live.md` (VM: update.sh, Migration 058) eintragen und sofort committen.
- [ ] **Step 2: Volle Testläufe** – MOS: `python -m pytest spaces/marketing -q -p no:cacheprovider` (nur die bekannten fremden Fehlschläge). SC: `tests/test_editor_seite.py tests/test_marketing_pult.py tests/test_editor_paket.py tests/test_ui.py` (nur die zwei bekannten). Editor: `npx tsc --noEmit ; npm test`.
- [ ] **Step 3: Migration 058 anwenden** (mit Freigabe): `python -m spaces.marketing.scripts.migration_probe …058… …verify_058…` erneut grün, dann Anwenden wie bei 057 (`_db._run_psql(<058-SQL>, None, streng=True)`), danach `verify_058.sql` erneut per Probe.
- [ ] **Step 4: Push** – MOS `git push origin HEAD:master`, SC `git push origin feat/stufe-1-fundament`.
- [ ] **Step 5: VM** – `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'` – Expected: „ALLE PRUEFUNGEN GRUEN“ und „Marketing-Seite: … neu gestartet“. Prüfen, dass die VM-venv Pillow hat (`~/marketing-os/.venv/bin/python -c "import PIL"`); sonst `pip install pillow` in dieser venv (Task-Befund dokumentieren).
- [ ] **Step 6: Vorlagen einspielen** – `python -m spaces.marketing.scripts.vorlagen_einspielen` (prüfen) → alle sieben „gueltig“ → `--wirklich` → sieben „eingespielt“, fünf „zurückgezogen“.
- [ ] **Step 7: PC** – im Haupt-Checkout nur `spaces/marketing` nachziehen (vorher Datei-Vergleich wie am 01.10.: alle Dateien = letzter ausgelieferter Stand), Bild-Arbeiter neu starten.
- [ ] **Step 8: Echter Lauf** – über die Pult-API (`aus_vorlage`) für den Laden `vibemind` je eine Probe aus `tech` und `studio` anlegen, Bildaufträge laufen lassen, Vorschau (600/380) ansehen, Stand berichten; Probe-Newsletter danach ablehnen.
- [ ] **Step 9: Claims schließen, Gedächtnis** (`project_marketing_api_auf_der_vm.md` um Vorlagen-Profi ergänzen), Bericht an den Betreiber.
