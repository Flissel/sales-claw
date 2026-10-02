# Newsletter-Bilder freistellen (Baustein B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Klick „Freistellen“ im Newsletter-Editor stellt das Hauptmotiv eines Bildplatzes frei (PNG mit Transparenz), ersetzt das Bild im Platz und legt die Datei in die Medien.

**Architecture:** Neuer Auftragsmodus `freistellen` (Migration 059). Der Bild-Arbeiter am PC holt die Quelle wie beim Überarbeiten, schickt sie durch einen ComfyUI-Ablauf mit den eingebauten Knoten `LoadBackgroundRemovalModel`/`RemoveBackground` (BiRefNet), prüft den Vordergrundanteil und lädt ein PNG über die um PNG erweiterte Upload-Route hoch; `fertig` setzt es als neue Fassung ein. sales-ui reicht `freistellen: true` durch und liefert Schwarz-Weiß mit Alpha; der Editor bekommt den Knopf.

**Tech Stack:** Python 3.11/3.12, FastAPI, Pillow, PostgreSQL/plpgsql, ComfyUI (BiRefNet, MIT), Starlette (sales-ui), React/TypeScript (Editor).

**Spec:** `docs/superpowers/specs/2026-10-02-newsletter-bild-freistellen-design.md` (sales-claw `d0fd843`)

## Global Constraints

- Repos: **MOS** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent` (Branch `master`, `spaces/marketing`), **SC** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw` (Branch `feat/stufe-1-fundament`). Vor jedem Commit `git rev-parse --show-toplevel` und `git branch --show-current` prüfen; nie im Haupt-Checkout `C:\Users\User\Desktop\Vibemind_V1\vibemind-os` committen. Nur eigene Dateien stagen (in SC nie `.superpowers/`), nie stashen, nie force-pushen, keine Hooks umgehen, Git über PowerShell.
- Kein Modell auf der VM. BiRefNet nur am PC in ComfyUI.
- Modelldatei: `model.safetensors` aus `ZhengPeng7/BiRefNet` (MIT), Ablage `C:\ComfyUI-Modelle\background_removal\birefnet.safetensors`.
- Auftragsmodi: `neu`, `ueberarbeiten`, `freistellen`. Freistellen braucht genau einen Platz (`platz` nicht leer) mit echtem Bild (kein Platzhalter `medien:platzhalter-…`, kein `grafik: true`).
- Qualitätsregel: Vordergrundanteil (Alpha > 128) < 2 % oder > 98 % ⇒ Befund „Kein klares Motiv gefunden“, Platz bleibt.
- Ergebnisdatei: `nl-<auftrag8>-<platz>-frei.png`; PNG ≤ 4 MB, sonst vorher auf längste Kante 1600 px verkleinern; JPEG-Weg unverändert (≤ 1 MB, `nl-<auftrag8>-<platz>.jpg`).
- Live-DB nur per `python -m spaces.marketing.scripts.migration_probe …` (Transaktion + ROLLBACK) bis zur Auslieferung.
- Tests MOS: `python -m pytest spaces/marketing -q -p no:cacheprovider` (bekannte fremde Fehlschläge: `test_formular_entwurf`, `test_cockpit_contract`, ggf. `test_send_paranoid`).
- Tests SC (aus `sales-mcp`, Wegwerf-Postgres :55432 – Start/Stop wie im Plan 2026-10-01): `& "E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\venv-sales\Scripts\python.exe" -m pytest <dateien> -q -p no:cacheprovider` mit `SALES_DB_URL=postgresql://postgres@127.0.0.1:55432/postgres`, `SALES_DB_SCHEMA=sales_test`. Editor: `cd editor ; npx tsc --noEmit ; npm test ; npm run build`.

## Review Focus

1. **Maske invertiert** (ComfyUI `JoinImageWithAlpha` erwartet 1 = transparent, `RemoveBackground` liefert 1 = Vordergrund): Ergebnis wäre „Hintergrund behalten“ – Task 4 prüft es am echten Bild.
2. **Freistellen auf einem Platzhalter oder einer Grafik** muss 422 geben, nicht still einen Auftrag anlegen – Tests in Task 2 und 5.
3. **Großes PNG** (Foto 1536 px mit Alpha > 4 MB) muss verkleinert statt abgelehnt werden – Test in Task 3.
4. **Schwarz-Weiß eines freigestellten Bildes** behält Transparenz – Test in Task 5.
5. **Arbeiter ohne Modelldatei** gibt den Auftrag mit klarem Befund zurück, nicht als Absturz-Schleife – Test in Task 3.

---

### Task 1: Migration 059 – Modus `freistellen` (MOS)

**Files:**
- Create: `spaces/marketing/db/059_bild_freistellen.sql`, `spaces/marketing/db/verify_059.sql`

**Interfaces:**
- Produces (DB): `bild_auftraege.modus` erlaubt `freistellen`; `marketing.pult_bild_auftrag(p_inhalt, p_platz, p_nur_leere, p_hinweis, p_urheber, p_staerke, p_modus)` nimmt `freistellen` an und setzt den Modus nur bei `p_modus <> 'freistellen'` und `p_staerke = 100` auf `neu`; für `freistellen` ist `p_platz` Pflicht.

- [ ] **Step 1: `verify_059.sql` schreiben (zuerst – die Probe ist der Test)**

```sql
-- Nachweise fuer 059, nur ueber migration_probe (Transaktion + ROLLBACK).
DO $$ DECLARE v_inhalt uuid; v_id uuid; v_modus text; BEGIN
  ASSERT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bild_auftraege_modus_check'
                 AND pg_get_constraintdef(oid) LIKE '%freistellen%'), 'Modus-Check kennt freistellen';
  SELECT id INTO v_inhalt FROM marketing.inhalte WHERE art = 'newsletter' AND status = 'entwurf' LIMIT 1;
  IF v_inhalt IS NOT NULL THEN
    v_id := marketing.pult_bild_auftrag(v_inhalt, 'kopf_bild', false, '', 'mensch', 100, 'freistellen');
    SELECT modus INTO v_modus FROM marketing.bild_auftraege WHERE id = v_id;
    ASSERT v_modus = 'freistellen', 'Staerke 100 macht aus freistellen kein neu';
    BEGIN
      PERFORM marketing.pult_bild_auftrag(v_inhalt, NULL, false, '', 'mensch', 0, 'freistellen');
      ASSERT false, 'freistellen ohne Platz muss scheitern';
    EXCEPTION WHEN raise_exception THEN NULL; END;
  END IF;
END $$;
SELECT 'verify_059 ok' AS ergebnis;
```

- [ ] **Step 2: Probe gegen die Live-DB ohne 059 laufen lassen – muss scheitern**

Run: `python -m spaces.marketing.scripts.migration_probe spaces/marketing/db/verify_059.sql`
Expected: Fehler „Modus-Check kennt freistellen“.

- [ ] **Step 3: `059_bild_freistellen.sql` schreiben**

```sql
-- 059_bild_freistellen.sql - Auftragsmodus freistellen (sales-claw Spec
-- 2026-10-02-newsletter-bild-freistellen-design.md §2). Additiv, idempotent.
BEGIN;
ALTER TABLE marketing.bild_auftraege DROP CONSTRAINT IF EXISTS bild_auftraege_modus_check;
ALTER TABLE marketing.bild_auftraege ADD CONSTRAINT bild_auftraege_modus_check
  CHECK (modus IN ('neu','ueberarbeiten','freistellen'));

CREATE OR REPLACE FUNCTION marketing.pult_bild_auftrag(
    p_inhalt uuid, p_platz text, p_nur_leere boolean, p_hinweis text, p_urheber text,
    p_staerke int, p_modus text) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE v_id uuid;
BEGIN
  IF p_staerke IS NULL OR p_staerke < 0 OR p_staerke > 100 THEN
    RAISE EXCEPTION 'Staerke muss 0 bis 100 sein'; END IF;
  IF p_modus IS NULL OR p_modus NOT IN ('neu', 'ueberarbeiten', 'freistellen') THEN
    RAISE EXCEPTION 'Modus muss neu, ueberarbeiten oder freistellen sein'; END IF;
  IF p_modus = 'freistellen' AND (p_platz IS NULL OR p_platz = '') THEN
    RAISE EXCEPTION 'Freistellen braucht einen Bildplatz'; END IF;
  v_id := marketing.pult_bild_auftrag(p_inhalt, p_platz, p_nur_leere, p_hinweis, p_urheber);
  UPDATE marketing.bild_auftraege
     SET staerke = p_staerke,
         modus = CASE WHEN p_modus = 'freistellen' THEN 'freistellen'
                      WHEN p_staerke = 100 THEN 'neu' ELSE p_modus END
   WHERE id = v_id;
  RETURN v_id;
END $$;
COMMIT;
```

- [ ] **Step 4: Probe mit 059 – muss grün sein**

Run: `python -m spaces.marketing.scripts.migration_probe spaces/marketing/db/059_bild_freistellen.sql spaces/marketing/db/verify_059.sql`
Expected: `verify_059 ok`, `PROBE OK (zurueckgerollt)`.

- [ ] **Step 5: Commit (MOS)**

```powershell
git add spaces/marketing/db/059_bild_freistellen.sql spaces/marketing/db/verify_059.sql
git commit -m "feat(marketing): Migration 059 - Bildauftragsmodus freistellen"
```

---

### Task 2: API – Freistell-Aufträge annehmen, PNG-Upload (MOS)

**Files:**
- Modify: `spaces/marketing/api/bilder.py` (Auftrag anlegen ~Zeile 80–95, `arbeiter_bild` ~Zeile 223–265)
- Test: `spaces/marketing/tests/test_bilder_api.py`

**Interfaces:**
- Consumes: DB-Funktion aus Task 1; `bildplaetze.finde(dok)`, `bildplaetze.ist_leer(url)`.
- Produces: `POST /api/pult/inhalte/{iid}/bilder` mit `modus: "freistellen"` (Pflicht `platz`; 422 „Freistellen geht nur bei einem Bildplatz mit echtem Bild“ wenn der Platz fehlt, leer/Platzhalter ist oder `grafik: true` trägt; `staerke` wird als 0 gespeichert); `POST /api/bilder/arbeiter/{aid}/bild?platz=…&format=png` nimmt PNG mit Alpha (≤ 4 MB) an und legt `nl-<aid8>-<platz>-frei.png` ab, Antwort `{"name": …}`.

- [ ] **Step 1: Failing Tests** (Muster der bestehenden Tests in `test_bilder_api.py` verwenden: gefälschte DB, `tmp_path` als `MARKETING_BILD_ORDNER`)

```python
import io

from PIL import Image


def _png(alpha=True, groesse=(64, 64)):
    b = io.BytesIO()
    Image.new("RGBA" if alpha else "RGB", groesse, (10, 20, 30, 0) if alpha else (10, 20, 30)).save(b, "PNG")
    return b.getvalue()


def test_png_upload_frei(arbeiter_client, auftrag_ok, tmp_path):
    r = arbeiter_client.post(f"/api/bilder/arbeiter/{AID}/bild?platz=kopf_bild&format=png", content=_png())
    assert r.status_code == 200 and r.json()["name"] == f"nl-{AID[:8]}-kopf_bild-frei.png"
    assert (tmp_path / f"nl-{AID[:8]}-kopf_bild-frei.png").read_bytes()[:4] == b"\x89PNG"


@pytest.mark.parametrize("roh", [b"\xff\xd8\xff" + b"x" * 50, b"\x89PNGkaputt", "ohne_alpha"])
def test_png_upload_abgelehnt(arbeiter_client, auftrag_ok, roh):
    daten = _png(alpha=False) if roh == "ohne_alpha" else roh
    assert arbeiter_client.post(f"/api/bilder/arbeiter/{AID}/bild?platz=kopf_bild&format=png",
                                content=daten).status_code == 422


def test_png_zu_gross(arbeiter_client, auftrag_ok):
    r = arbeiter_client.post(f"/api/bilder/arbeiter/{AID}/bild?platz=kopf_bild&format=png",
                             content=b"\x89PNG" + b"0" * (4 * 1024 * 1024 + 1))
    assert r.status_code == 413


def test_jpeg_weg_unveraendert(arbeiter_client, auftrag_ok):
    # bestehender JPEG-Test bleibt gruen; zusaetzlich: format=jpg explizit
    ...
```
(Fixturnamen `arbeiter_client`, `auftrag_ok`, Konstante `AID` an die tatsächlichen Namen in `test_bilder_api.py` angleichen; den JPEG-Test als echten Test mit gültigem JPEG ausschreiben.)
Für den Pult-Auftrag (in derselben Datei oder `tests/test_pult_api.py`, wo der Auftrag-Endpunkt getestet wird):
```python
def test_freistellen_braucht_echtes_bild(db, c):
    # neueste Fassung: kopf_bild mit Platzhalter -> 422; t1_bild mit echtem Bild -> SQL mit 'freistellen'
    ...
```
mit drei Fällen: Platzhalter-URL ⇒ 422, `grafik: true` ⇒ 422, `medien:nl-1234abcd-kopf_bild.jpg` ⇒ 200 und SQL enthält `'freistellen'` und Stärke `0`; ohne `platz` ⇒ 422.

- [ ] **Step 2: FAIL bestätigen** – Run: `python -m pytest spaces/marketing/tests/test_bilder_api.py -q -p no:cacheprovider`

- [ ] **Step 3: Implementieren**

Auftrag anlegen: `modus` erlaubt `("neu", "ueberarbeiten", "freistellen")`. Bei `freistellen`: `platz` Pflicht (`_PLATZ`-Regel); neueste Fassung lesen (`SELECT bloecke FROM marketing.inhalt_fassungen WHERE inhalt = … ORDER BY fassung DESC LIMIT 1`), Block `dok[platz]` prüfen: Typ `Image` oder `Container`, `props.url` vorhanden und `not bildplaetze.ist_leer(url)`, `props.grafik is not True` – sonst 422 mit dem Text aus den Interfaces; `staerke = 0`, `nur_leere = false`.
`arbeiter_bild`: Parameter `format: str = Query("jpg")`; `format not in ("jpg", "png")` ⇒ 422. Für `png`: `PNG_MAX = 4 * 1024 * 1024` statt `BILD_MAX` (413-Text „Bild groesser als 4 MB“), Prüfung
```python
def _png_pruefen(roh: bytes) -> None:
    if not roh.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "Kein PNG")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(roh)) as b:
            b.verify()
        with Image.open(io.BytesIO(roh)) as b:
            if b.mode not in ("RGBA", "LA") and "transparency" not in b.info:
                raise HTTPException(422, "PNG ohne Transparenz")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "PNG nicht lesbar")
```
Name `nl-{a[:8]}-{platz}-frei.png`; Ablage wie beim JPEG (Zwischendatei, chmod 0644, `os.replace`).

- [ ] **Step 4: PASS** – Run: `python -m pytest spaces/marketing/tests/test_bilder_api.py spaces/marketing/tests/test_pult_api.py -q -p no:cacheprovider`

- [ ] **Step 5: Commit (MOS)**

```powershell
git add spaces/marketing/api/bilder.py spaces/marketing/tests/test_bilder_api.py spaces/marketing/tests/test_pult_api.py
git commit -m "feat(marketing): Freistell-Auftraege nur fuer echte Bilder, PNG-Upload mit Transparenz"
```

---

### Task 3: Bild-Arbeiter – Freistell-Zweig (MOS)

**Files:**
- Create: `spaces/marketing/bilder/freistellen_api.json`
- Modify: `spaces/marketing/claw/bild_comfy.py` (neue Funktion `freistellen`), `spaces/marketing/workers/bild_worker.py` (`ArbeiterApi.bild`, `ein_durchlauf`, neue Funktion `_freistellen`)
- Test: `spaces/marketing/tests/test_bild_worker.py`, `spaces/marketing/claw/tests/test_bild_comfy.py` (falls vorhanden; sonst in `test_bild_worker.py`)

**Interfaces:**
- Consumes: Route aus Task 2 (`format=png`), `ArbeiterApi.quelle`, `quelle_normalisieren`.
- Produces: `bild_comfy.freistellen(quelle: bytes, zeitlimit_s: int = 300) -> bytes` (PNG RGBA, Originalgröße); `ArbeiterApi.bild(aid, platz, daten: bytes, format: str = "jpg") -> str`; `bild_worker.FREI_MIN = 0.02`, `FREI_MAX = 0.98`, `PNG_MAX = 4 * 1024 * 1024`, `vordergrund_anteil(png: bytes) -> float`, `png_passend(png: bytes) -> bytes` (verkleinert auf längste Kante 1600 px, wenn > PNG_MAX).

- [ ] **Step 1: Ablauf-JSON anlegen**

`spaces/marketing/bilder/freistellen_api.json`:
```json
{
  "1": {"class_type": "LoadImage", "inputs": {"image": "quelle.png"}},
  "2": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": "birefnet.safetensors"}},
  "3": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
  "4": {"class_type": "InvertMask", "inputs": {"mask": ["3", 0]}},
  "5": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["1", 0], "alpha": ["4", 0]}},
  "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "newsletter-frei"}}
}
```
(Ob `InvertMask` nötig ist, entscheidet Task 4 am echten Bild; der Knoten bleibt hier, Task 4 entfernt ihn bei Bedarf.)

- [ ] **Step 2: Failing Tests**

```python
import io

from PIL import Image

from spaces.marketing.workers import bild_worker as bw


def _rgba(anteil: float, groesse=(100, 100)) -> bytes:
    bild = Image.new("RGBA", groesse, (0, 0, 0, 0))
    voll = int(groesse[0] * groesse[1] * anteil)
    px = bild.load()
    for i in range(voll):
        px[i % groesse[0], i // groesse[0]] = (200, 100, 50, 255)
    b = io.BytesIO()
    bild.save(b, "PNG")
    return b.getvalue()


def test_vordergrund_anteil():
    assert abs(bw.vordergrund_anteil(_rgba(0.5)) - 0.5) < 0.02


def test_png_passend_verkleinert_grosses():
    gross = Image.effect_noise((2400, 1600), 80).convert("RGBA")
    b = io.BytesIO()
    gross.save(b, "PNG")
    roh = b.getvalue()
    assert len(roh) > bw.PNG_MAX or True   # Rauschen ist gross; wenn nicht, Grenze im Test kuenstlich senken
    klein = bw.png_passend(roh, grenze=len(roh) - 1)
    with Image.open(io.BytesIO(klein)) as k:
        assert max(k.size) == 1600 and k.mode == "RGBA"


@pytest.mark.parametrize("anteil,erwartet", [(0.5, "fertig"), (0.005, "zurueck"), (0.995, "zurueck")])
def test_freistellen_qualitaetsregel(anteil, erwartet, falsche_api, falsches_comfy):
    falsches_comfy.frei = _rgba(anteil)
    falsche_api.auftrag = {"id": AID, "platz": "kopf_bild", "modus": "freistellen", "staerke": 0,
                           "bloecke": DOK_MIT_ECHTEM_BILD}
    assert bw.ein_durchlauf(falsche_api, comfy=falsches_comfy, ...) == erwartet
    if erwartet == "fertig":
        assert falsche_api.hochgeladen[-1][2] == "png"
        assert falsche_api.fertig_ergebnis == {"kopf_bild": f"nl-{AID[:8]}-kopf_bild-frei.png"}
    else:
        assert "Kein klares Motiv gefunden" in falsche_api.zurueck_befund


def test_freistellen_ohne_modell_gibt_zurueck(falsche_api, falsches_comfy):
    falsches_comfy.fehler = bild_comfy.ComfyFehler("Erzeugung in ComfyUI fehlgeschlagen")
    ...
    assert bw.ein_durchlauf(...) == "zurueck" and "Freistellen nicht verfügbar" in falsche_api.zurueck_befund
```
(Die bestehenden Fälschungen in `test_bild_worker.py` – API- und ComfyUI-Doubles – erweitern statt neue zu erfinden: Comfy-Double bekommt `freistellen(quelle)`, API-Double `bild(..., format)`. Freistellen braucht weder Sehmodell noch Prompt noch FLUX: die Tests stellen sicher, dass `prompt`, `sehen` und `comfy.erzeugen` nicht aufgerufen werden.)

- [ ] **Step 3: FAIL bestätigen.**

- [ ] **Step 4: Implementieren**

`bild_comfy.py`:
```python
ABLAUF_FREISTELLEN = Path(os.environ.get("COMFYUI_ABLAUF_FREISTELLEN") or
                          Path(__file__).resolve().parents[1] / "bilder" / "freistellen_api.json")


def freistellen(quelle: bytes, zeitlimit_s: int = 300) -> bytes:
    if not quelle:
        raise ComfyFehler("Ausgangsbild fehlt")
    name = _hochladen(f"nl-frei-{uuid.uuid4().hex[:12]}.img", quelle)
    ablauf = json.loads(ABLAUF_FREISTELLEN.read_text(encoding="utf-8"))
    ablauf["1"]["inputs"]["image"] = name
    return _ausfuehren(ablauf, zeitlimit_s)
```
`bild_worker.py`:
```python
FREI_MIN, FREI_MAX = 0.02, 0.98
PNG_MAX = 4 * 1024 * 1024


def vordergrund_anteil(png: bytes) -> float:
    from PIL import Image
    with Image.open(io.BytesIO(png)) as b:
        a = b.convert("RGBA").getchannel("A")
        hist = a.histogram()
        return sum(hist[129:]) / max(1, a.size[0] * a.size[1])


def png_passend(png: bytes, grenze: int = PNG_MAX) -> bytes:
    if len(png) <= grenze:
        return png
    from PIL import Image
    with Image.open(io.BytesIO(png)) as b:
        b = b.convert("RGBA")
        b.thumbnail((1600, 1600), Image.LANCZOS)
        out = io.BytesIO()
        b.save(out, "PNG", optimize=True)
        return out.getvalue()


def _freistellen(api, aid, auftrag, ziele, comfy) -> tuple[dict, list[str]] | str:
    platz = next((p for p in ziele if p.id == auftrag.get("platz")), None)
    if platz is None or platz.leer:
        return {}, ["Freistellen braucht einen Bildplatz mit Bild"]
    if not api.weiter(aid):
        return "verworfen"
    roh = api.quelle(aid, platz.id)
    quelle = quelle_normalisieren(roh) if roh and len(roh) <= QUELLE_MAX else None
    if quelle is None:
        return {}, [f"{platz.id}: Quellbild fehlt oder unlesbar"]
    try:
        frei = comfy.freistellen(quelle)
    except bild_comfy.ComfyFehler as e:
        return {}, [f"Freistellen nicht verfügbar: {e}"]
    finally:
        comfy.freigeben()
    anteil = vordergrund_anteil(frei)
    if not FREI_MIN <= anteil <= FREI_MAX:
        return {}, ["Kein klares Motiv gefunden"]
    daten = png_passend(frei)
    if len(daten) > PNG_MAX:
        return {}, [f"{platz.id}: freigestelltes Bild zu groß"]
    name = api.bild(aid, platz.id, daten, format="png")
    return {platz.id: name}, [f"freigestellt ({anteil:.0%} Motiv)"]
```
`ArbeiterApi.bild(self, aid, platz, daten, format="jpg")`: Pfad `…/bild?platz=…&format={format}`, Content-Type `image/png` bzw. `image/jpeg`.
`ein_durchlauf`: nach `ziele` (vor `_erzeugen`):
```python
        if auftrag.get("modus") == "freistellen":
            erg = _freistellen(api, aid, auftrag, ziele, comfy)
            if erg == "verworfen":
                return "verworfen"
            ergebnis, befunde = erg
            if not ergebnis:
                api.zurueck(aid, "; ".join(befunde), True)
                return "zurueck"
            api.fertig(aid, ergebnis, "; ".join(befunde), {})
            return "fertig"
```
(Die `_dienste_bereit`-Prüfung bleibt vorne – sie startet ComfyUI bei Bedarf.)

- [ ] **Step 5: PASS** – Run: `python -m pytest spaces/marketing/tests/test_bild_worker.py -q -p no:cacheprovider`; danach volle Suite einmal.

- [ ] **Step 6: Commit (MOS)**

```powershell
git add spaces/marketing/bilder/freistellen_api.json spaces/marketing/claw/bild_comfy.py spaces/marketing/workers/bild_worker.py spaces/marketing/tests/test_bild_worker.py
git commit -m "feat(marketing): Bild-Arbeiter stellt frei (BiRefNet ueber ComfyUI), Qualitaetsregel, PNG-Upload"
```

---

### Task 4: Modell installieren und Ablauf am echten Bild prüfen (PC, MOS-Werkzeug)

**Files:**
- Create: `spaces/marketing/scripts/freistellen_probe.py`
- Modify (PC, nicht im Repo): `E:\ComfyUI\extra_model_paths.yaml` (`background_removal: background_removal/` unter `ssd_flux`), Datei `C:\ComfyUI-Modelle\background_removal\birefnet.safetensors`
- Possibly modify: `spaces/marketing/bilder/freistellen_api.json` (InvertMask entfernen, falls das echte Ergebnis es verlangt)

**Interfaces:**
- Consumes: `bild_comfy.freistellen`, `bild_worker.vordergrund_anteil`.
- Produces: `python -m spaces.marketing.scripts.freistellen_probe <bild> <ausgabe.png>` – stellt ein lokales Bild frei, druckt Vordergrundanteil und Laufzeit.

- [ ] **Step 1: Modell holen** – `model.safetensors` von `https://huggingface.co/ZhengPeng7/BiRefNet/resolve/main/model.safetensors` nach `C:\ComfyUI-Modelle\background_removal\birefnet.safetensors` (Größe prüfen ≈ 0,9 GB; Lizenz MIT im Bericht vermerken). `extra_model_paths.yaml` ergänzen. ComfyUI neu starten (aktuell läuft die Ersatzinstanz auf :8189 – `COMFYUI_URL` berücksichtigen) und mit `GET /object_info/LoadBackgroundRemovalModel` prüfen, dass `birefnet.safetensors` gelistet ist.

- [ ] **Step 2: Probe-Skript schreiben** (liest Bild, `quelle_normalisieren`, `bild_comfy.freistellen`, schreibt PNG, druckt Anteil + Sekunden) und mit einem Personenfoto (z. B. aus `C:\Users\User\Desktop\Vibemind_V1\.playwright-mcp` oder einem FLUX-Bild aus `scratchpad\probe-echt`) laufen lassen.

- [ ] **Step 3: Maske prüfen** – Ergebnis-PNG ansehen (Read-Werkzeug): Ist die Person sichtbar und der Hintergrund transparent? Wenn umgekehrt: Knoten `4` (InvertMask) aus `freistellen_api.json` entfernen und `5.alpha` auf `["3", 0]` setzen, erneut prüfen. Ergebnis und Screenshot-Pfade im Bericht.

- [ ] **Step 4: Test für das Skript** (Argumentprüfung, ohne ComfyUI) und **Commit (MOS)**

```powershell
git add spaces/marketing/scripts/freistellen_probe.py spaces/marketing/bilder/freistellen_api.json spaces/marketing/tests/test_freistellen_probe.py
git commit -m "feat(marketing): Freistell-Probe und am echten Bild geprueft"
```

---

### Task 5: sales-ui – Freistellen durchreichen, Schwarz-Weiß mit Alpha (SC)

**Files:**
- Modify: `sales-mcp/ui_editor.py` (`editor_bild` ~Zeile 255–280, Bildroute `?sw=1`)
- Test: `sales-mcp/tests/test_editor_seite.py`

**Interfaces:**
- Consumes: Pult-API aus Task 2.
- Produces: `POST /marketing/editor/{iid}/bild` mit `{"platz": "<id>", "freistellen": true}` ⇒ Nutzlast an die Pult-API `{"platz": …, "hinweis": "", "nur_leere": false, "staerke": 0, "modus": "freistellen"}`; `freistellen` ohne `platz` ⇒ 422; Fehler der API (422) werden mit ihrem Grund weitergegeben. `?sw=1` liefert für Bilder mit Alpha ein PNG im Modus `LA`.

- [ ] **Step 1: Failing Tests**

```python
def test_freistellen_nutzlast(angemeldet, pult):
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", json={"platz": "i", "freistellen": True},
                        headers={**HOST, "X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 200
    methode, pfad, daten = pult.aufrufe[-1]
    assert pfad == f"/inhalte/{IID}/bilder" and daten["modus"] == "freistellen" and daten["staerke"] == 0


@pytest.mark.parametrize("body", [{"freistellen": True}, {"platz": "i", "freistellen": "ja"}])
def test_freistellen_ungueltig(angemeldet, pult, body):
    r = angemeldet.post(f"/marketing/editor/{IID}/bild", json=body, headers={**HOST, "X-CSRF": ui.CSRF_TOKEN})
    assert r.status_code == 422


def test_sw_behaelt_alpha(...):
    # transparentes PNG in den Medien, ?sw=1 -> PNG, Modus LA, Alpha erhalten
    ...
```
(Den `test_sw`-Test nach dem Muster des bestehenden Schwarz-Weiß-Tests aus Baustein A ausschreiben: signiertes Token über `ui_editor.bild_token()`.)

- [ ] **Step 2: FAIL bestätigen** – **Step 3: Implementieren** – in `editor_bild`: `freistellen = body.get("freistellen", False)`; nicht bool ⇒ 422; wenn `True`: `platz` Pflicht ⇒ sonst 422 „Freistellen braucht einen Bildplatz“; Nutzlast wie in den Interfaces (Stärke/neu ignorieren). Bildroute: bei `?sw=1` und Bild mit Alpha (`mode in ("RGBA","LA","P")` mit Transparenz) ⇒ `ImageOps.grayscale` auf RGB, Alpha anhängen ⇒ `LA`, als PNG ausliefern. – **Step 4: PASS** (`tests/test_editor_seite.py`) – **Step 5: Commit (SC)**

```powershell
git add sales-mcp/ui_editor.py sales-mcp/tests/test_editor_seite.py
git commit -m "feat(ui): Freistellen im Editor durchreichen, Schwarz-Weiss behaelt Transparenz"
```

---

### Task 6: Editor – Knopf „Freistellen“ (SC)

**Files:**
- Modify: `editor/src/App/InspectorDrawer/ConfigurationPanel/input-panels/ImageSidebarPanel.tsx`, `editor/src/pult.ts` (neue Funktion `bildFreistellen`), `editor/src/bildfeld.ts` (Hilfsfunktion `freistellbar`)
- Test: `editor/src/bildfeld.test.ts` (vitest), `sales-mcp/tests/test_editor_paket.py`
- Build: `sales-mcp/static/editor/*`

**Interfaces:**
- Consumes: Route aus Task 5.
- Produces: `freistellbar(props: { url?: string | null; grafik?: boolean | null }): boolean` (wahr nur bei echter Medien-URL, kein Platzhalter, keine Grafik); `bildFreistellen(s: Start, platz: string): Promise<{ ok: true } | { ok: false; grund: string }>`.

- [ ] **Step 1: Failing vitest**

```ts
import { describe, expect, it } from 'vitest';
import { freistellbar } from './bildfeld';

describe('freistellbar', () => {
  it('nur echtes Bild', () => {
    expect(freistellbar({ url: '/medien/datei/nl-1234abcd-kopf.jpg' })).toBe(true);
    expect(freistellbar({ url: '/medien/datei/platzhalter-2x1.png' })).toBe(false);
    expect(freistellbar({ url: '' })).toBe(false);
    expect(freistellbar({ url: '/medien/datei/tech-signal-aaaaaa.png', grafik: true })).toBe(false);
  });
});
```

- [ ] **Step 2: FAIL** (`npm test`) – **Step 3: Implementieren**: `freistellbar` in `bildfeld.ts` (nutzt die vorhandene Platzhalter-Erkennung `istLeer`); `bildFreistellen` in `pult.ts` analog `bildBeauftragen` mit Body `{ platz, freistellen: true }`; im Bild-Panel unter dem Erzeugen-Knopf: Knopf „Freistellen“ (`variant="outlined"`), sichtbar wenn `freistellbar(data.props)`, deaktiviert bei `ungespeichert` mit Hinweis „Erst speichern“, nach Erfolg Rückmeldung „Freistellen beauftragt – das Bild kommt als neue Fassung.“ und `standAbfragen()`. – **Step 4: PASS** (`npx tsc --noEmit ; npm test ; npm run build`), Paket-Test:
```python
def test_paket_kennt_freistellen():
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    assert "Freistellen beauftragt" in text and "freistellen" in text
```
– **Step 5: Commit (SC)**

```powershell
git add editor/src sales-mcp/static/editor sales-mcp/tests/test_editor_paket.py
git commit -m "feat(editor): Knopf Freistellen fuer Bildplaetze mit echtem Bild"
```

---

### Task 7: Auslieferung und echter Lauf – nur nach Freigabe des Betreibers

- [ ] **Step 1:** Claims (WORKBOARD `cc-bild-freistellen`, secondbrain Koordination: VM-Migration 059 + update.sh).
- [ ] **Step 2:** Volle Testläufe MOS und SC (Editor, sales-mcp Editor/Pult/Paket/ui).
- [ ] **Step 3:** Migration 059: Probe, dann anwenden (`_db._run_psql`), `verify_059` per Probe.
- [ ] **Step 4:** Push MOS (bei fremden Commits auf `origin/master`: Merge in temporärem Worktree wie am 01.10.) und SC.
- [ ] **Step 5:** VM `bash deploy/update.sh` (marketing-api + sales-ui).
- [ ] **Step 6:** PC: Haupt-Checkout `spaces/marketing` nachziehen (vorher Datei-Vergleich gegen den letzten ausgelieferten Stand), Bild-Arbeiter neu starten (mit `COMFYUI_URL`, solange ComfyUI auf :8189 läuft).
- [ ] **Step 7:** Echter Lauf: im Probe-Newsletter „Probe Vorlage Studio“ ein FLUX-Bild und ein hochgeladenes Personenfoto freistellen (über die Pult-API mit `modus=freistellen`), Ergebnis ansehen (Transparenz, Kanten), Medienbibliothek zeigt `-frei.png`.
- [ ] **Step 8:** Claims schließen, Gedächtnis ergänzen, Bericht.
