# Bilder mit FLUX.2 klein — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Newsletter-Agent erzeugt Bilder mit FLUX.2 [klein] 4B, ändert vorhandene Bilder gezielt nach Anweisung und baut eigene Fotos (Mediennamen) als Vorlage ein. Das Bildfeld im Editor verliert seine KI-Knöpfe.

**Architecture:**
- **ComfyUI-Client (`bild_comfy`):** Er bekommt einen FLUX.2-Graphen mit 0–3 Referenzbildern. Die Referenzen hängt der Code dynamisch als Kette `ReferenceLatent` an.
- **Datenbank:** Migration 068 ergänzt `bild_auftraege.vorlagen` und den Modus `aendern`.
- **Bild-Arbeiter:** Er holt die Vorlagen über eine neue Arbeiter-Route und wählt das Modell per Schalter `MARKETING_BILDMODELL` (`flux2` Vorgabe, `flux1` Rückfall).
- **Agent:** Er bekommt `bild_aendern` und `vorlagen` bei `bild_erzeugen`.
- **Editor und sales-ui:** Die Bildaufträge von Hand fallen weg.

**Tech Stack:** Python 3.11 (FastAPI, Pillow), PostgreSQL/plpgsql (Supabase auf der VM), ComfyUI 0.26 (API-Format), React/TypeScript (Vite, vitest), Starlette (sales-ui).

**Spec:** `docs/superpowers/specs/2026-10-10-bilder-flux2-klein-design.md` (sales-claw)

## Global Constraints

**Repos und Arbeitsweise**
- **MOS** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent`, Branch `master`, Dateien unter `spaces/marketing/...`.
  - Vor jedem Commit `git -C <MOS> rev-parse --show-toplevel` und `git -C <MOS> branch --show-current` prüfen. Erwartet wird genau dieser Pfad und `master`.
  - Niemals im Haupt-Checkout `C:/Users/User/Desktop/Vibemind_V1/vibemind-os` committen.
- **SC** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw`, Branch `feat/stufe-1-fundament`.
- **Git:** nur über PowerShell.
  - Conventional Commits auf Deutsch, letzter Absatz `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Nur eigene Dateien einzeln stagen. Nie `git add -A`, nie `.superpowers/`, nie stash, force oder `--no-verify`.

**Tests**
- **MOS:** aus dem MOS-Root `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/<pfad> -q`.
- **Migrationen:** nur über `migration_probe`, also eine Transaktion mit ROLLBACK:
  `$env:SUPABASE_SSH_HOST='offload-vm'; $env:SUPABASE_DB_CONTAINER='debian-supabase-db-1'; & C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m spaces.marketing.scripts.migration_probe <dateien…>`
- **sales-ui:** `cd <SC>/sales-mcp; $env:SALES_DB_URL='postgresql://postgres@127.0.0.1:55432/postgres'; $env:SALES_DB_SCHEMA='sales_test'; & E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q`. Die Test-Postgres auf :55432 startet der Controller.
- **Editor:** `cd <SC>/editor; npx vitest run; npx tsc --noEmit; npm run build`. Das Bundle `sales-mcp/static/editor` wird im Editor-Task mit committet. Nur `cd editor && npx tsc --noEmit` zählt als Typprüfung.

**Verbote:** kein Deploy, keine Migration gegen die echte DB, kein Dienst-Neustart. Das macht der Controller in Task 8 nach Freigabe. **ComfyUI nie beenden**, :8114 nie anfassen, kein Modell auf der VM.

**Fachliche Werte**
- Modelldateien: `flux-2-klein-4b-fp8.safetensors` (diffusion_models), `qwen_3_4b.safetensors` (text_encoders), `flux2-vae.safetensors` (vae).
- Höchstens **3 Referenzbilder je Auftrag**. Bei `aendern` ist das Ausgangsbild Referenz 1, dazu höchstens 2 Vorlagen.
- Agent: `bild_erzeugen.vorlagen` höchstens 3, `bild_aendern.vorlagen` höchstens 2. `anweisung` und `hinweis` je höchstens 500 Zeichen.
- Schalter `MARKETING_BILDMODELL`: Vorgabe `flux2`, Rückfall `flux1`. Unbekannte Werte gelten als `flux2`.
- Wortlaute (exakt):
  - „Bildmodell FLUX.2 fehlt am PC“
  - „Zu viele Vorlagen für die Grafikkarte – mit weniger Vorlagen noch einmal“
  - „Hier ist noch kein Bild – nimm bild_erzeugen“
  - „Vorlagen nur mit FLUX.2“
  - „Bild erzeugen, ändern oder freistellen: Bild markieren und den Assistenten fragen“

## Rulings vor Beginn (Controller, gegen die Spec abgewogen)

- **R1:** Statt zwei Ablaufdateien gibt es **eine** `bilder/flux2_klein_api.json` (Text→Bild). Referenzbilder hängt `bild_comfy` als Knotenkette an. „Ändern“ ist derselbe Graph mit dem Ausgangsbild als Referenz 1.
  - Grund: gleiches Verhalten, keine doppelte Datei.
  - Kosten, falls falsch: eine zweite Datei nachreichen.
- **R2:** Die Modelle kommen nach `E:\ComfyUI\models\…` (HDD), weil C: nur 12,9 GB frei hat (gemessen 10.10.). Die FLUX.1-Dateien liegen per `extra_model_paths.yaml` auf `C:/ComfyUI-Modelle`. ComfyUI findet beide Orte.
  - Kosten: längerer Kaltstart, das misst der Messlauf.
- **R3:** Der Rückfall `flux1` für `aendern` ist der heutige Überarbeiten-Weg („neu mit Motiv“: Sehen + `bearbeitungs_prompt` + FLUX.1 Text→Bild) mit Stärke 55. Die Spec sagt „altes Bild-zu-Bild mit fester Stärke 55“, und genau das ist der heutige `ueberarbeiten`-Weg.
- **R4:** `hinweisOffen` bleibt im Editor-Store, weil andere Stellen es als Neulade-Sperre lesen. Das Bildfeld setzt es nur nicht mehr.

## Review Focus

1. **Vorlage eines fremden Mandanten** oder ein erfundener Name erreicht den Bild-Arbeiter. Erwartet: Die Arbeiter-Route `vorlage` liefert 404, der Auftrag scheitert mit dem Namen der Vorlage, und es gibt kein Bild aus fremden Medien. Test in Task 4.
2. **`aendern` auf einen Platz, dessen Bild inzwischen ein Platzhalter ist** (z. B. eine andere Runde hat das Bild entfernt). Erwartet: Befund „Quellbild fehlt“, kein neu erzeugtes Ersatzbild. Test in Task 5.
3. **ComfyUI meldet einen Fehler ohne `exception_message`** oder die Historie hat keine `messages`. Erwartet: weiter „Erzeugung in ComfyUI fehlgeschlagen“, kein Absturz. Test in Task 2.
4. **Doppelte Vorlage** (derselbe Name zweimal) oder `vorlagen` als String statt Liste vom Agenten. Erwartet: Das Werkzeug lehnt mit klarer Meldung ab, die API dedupliziert bzw. antwortet 422. Tests in Task 6 und Task 4.
5. **Alter Auftrag im Modus `ueberarbeiten`** steht beim Umstieg noch in der Warteschlange. Erwartet: Er läuft über den alten Weg (R3) weiter und scheitert nicht am neuen Modell. Test in Task 5.

---

### Task 1: Modelldateien am PC (Controller)

**Files:** keine Repo-Dateien. Ziel: `E:/ComfyUI/models/diffusion_models/`, `E:/ComfyUI/models/text_encoders/`, `E:/ComfyUI/models/vae/`.

**Interfaces:**
- Produces: Die drei Dateien sind in ComfyUI sichtbar unter `GET http://127.0.0.1:8188/models/diffusion_models`, `/models/text_encoders` und `/models/vae`.

- [ ] **Step 1: Herunterladen** (PowerShell, im Hintergrund, nacheinander):
```
curl.exe -L -o E:/ComfyUI/models/diffusion_models/flux-2-klein-4b-fp8.safetensors https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8/resolve/main/flux-2-klein-4b-fp8.safetensors
curl.exe -L -o E:/ComfyUI/models/text_encoders/qwen_3_4b.safetensors https://huggingface.co/Comfy-Org/flux2-klein-4B/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors
curl.exe -L -o E:/ComfyUI/models/vae/flux2-vae.safetensors https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors
```
Verlangt Hugging Face für das BFL-Repo eine Anmeldung, nimmt der Controller die Comfy-Org-Kopie (`Comfy-Org/flux2-klein-4B`, `split_files/diffusion_models/`) und notiert das im Ledger.

- [ ] **Step 2: Sichtbarkeit prüfen** ohne ComfyUI-Neustart (die Modelllisten werden je Anfrage neu gelesen):
```
curl -s http://127.0.0.1:8188/models/diffusion_models; curl -s http://127.0.0.1:8188/models/text_encoders; curl -s http://127.0.0.1:8188/models/vae
```
Expected: Die drei Namen erscheinen. Die Dateigröße ist jeweils größer als 100 MB, also keine HTML-Fehlerseite.

---

### Task 2: ComfyUI-Client für FLUX.2 mit Referenzbildern (MOS)

**Files:**
- Create: `spaces/marketing/bilder/flux2_klein_api.json`
- Modify: `spaces/marketing/claw/bild_comfy.py` (neue Funktion, Fehlerauswertung in `_abfragen` und `_ausfuehren`)
- Test: `spaces/marketing/claw/tests/test_bild_comfy.py`

**Interfaces:**
- Produces:
  - `bild_comfy.ABLAUF_FLUX2: Path`
  - `bild_comfy.MAX_REFERENZEN = 3`
  - `bild_comfy.erzeugen_flux2(prompt: str, breite: int, hoehe: int, seed: int, referenzen: list[bytes] = (), zeitlimit_s: int = 300) -> bytes` (PNG)
  - `bild_comfy.graph_flux2(prompt, breite, hoehe, seed, namen: list[str]) -> dict` (rein, testbar)
  - Fehler als `ComfyFehler` mit den Wortlauten „Bildmodell FLUX.2 fehlt am PC“ und „Zu viele Vorlagen für die Grafikkarte – mit weniger Vorlagen noch einmal“.

- [ ] **Step 1: Ablaufdatei anlegen** `spaces/marketing/bilder/flux2_klein_api.json`:
```json
{
  "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-2-klein-4b-fp8.safetensors", "weight_dtype": "default"}},
  "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "flux2"}},
  "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
  "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
  "5": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
  "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 1024, "height": 512, "batch_size": 1}},
  "7": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": 1024, "height": 512}},
  "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
  "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
  "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["8", 0], "guider": ["5", 0], "sampler": ["9", 0], "sigmas": ["7", 0], "latent_image": ["6", 0]}},
  "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
  "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "newsletter-bild"}}
}
```

- [ ] **Step 2: Failing Tests schreiben** in `claw/tests/test_bild_comfy.py`:
```python
def test_graph_flux2_ohne_referenzen_setzt_prompt_masse_seed():
    g = bild_comfy.graph_flux2("a red barn", 768, 512, 42, [])
    assert g["4"]["inputs"]["text"] == "a red barn"
    assert (g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]) == (768, 512)
    assert (g["7"]["inputs"]["width"], g["7"]["inputs"]["height"]) == (768, 512)
    assert g["8"]["inputs"]["noise_seed"] == 42
    assert g["5"]["inputs"]["conditioning"] == ["4", 0]
    assert not [k for k in g if k.startswith(("r", "c"))]


def test_graph_flux2_haengt_referenzen_als_kette_an():
    g = bild_comfy.graph_flux2("p", 512, 512, 1, ["a.png", "b.png"])
    assert g["r1"]["inputs"]["image"] == "a.png" and g["r2"]["inputs"]["image"] == "b.png"
    assert g["s1"]["inputs"] == {"image": ["r1", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 1}
    assert g["e1"]["inputs"] == {"pixels": ["s1", 0], "vae": ["3", 0]}
    assert g["c1"]["inputs"] == {"conditioning": ["4", 0], "latent": ["e1", 0]}
    assert g["c2"]["inputs"] == {"conditioning": ["c1", 0], "latent": ["e2", 0]}
    assert g["5"]["inputs"]["conditioning"] == ["c2", 0]
    assert g["c1"]["class_type"] == "ReferenceLatent" and g["r1"]["class_type"] == "LoadImage"


def test_erzeugen_flux2_mehr_als_drei_referenzen_abgelehnt():
    with pytest.raises(bild_comfy.ComfyFehler):
        bild_comfy.erzeugen_flux2("p", 512, 512, 1, [b"x"] * 4)


def test_erzeugen_flux2_masse_wie_flux1_geprueft():
    with pytest.raises(bild_comfy.ComfyFehler):
        bild_comfy.erzeugen_flux2("p", 500, 512, 1, [])


def test_erzeugen_flux2_laedt_referenzen_hoch_und_fuehrt_aus(monkeypatch):
    hoch, gesendet = [], {}
    monkeypatch.setattr(bild_comfy, "_hochladen", lambda name, daten: hoch.append(daten) or f"up-{len(hoch)}.png")
    monkeypatch.setattr(bild_comfy, "_ausfuehren", lambda ablauf, z: gesendet.setdefault("g", ablauf) and b"PNG")
    assert bild_comfy.erzeugen_flux2("p", 512, 512, 7, [b"eins", b"zwei"]) == b"PNG"
    assert hoch == [b"eins", b"zwei"]
    assert gesendet["g"]["r1"]["inputs"]["image"] == "up-1.png"


def test_fehlendes_modell_klarer_befund(monkeypatch):
    import io, urllib.error
    rumpf = b'{"error": {"message": "Prompt outputs failed validation"}, "node_errors": {"1": {"errors": [{"details": "unet_name: \'flux-2-klein-4b-fp8.safetensors\' not in []"}]}}}'
    def http(methode, pfad, daten=None, zeitlimit=30):
        raise urllib.error.HTTPError("u", 400, "Bad", {}, io.BytesIO(rumpf))
    monkeypatch.setattr(bild_comfy, "_http", http)
    with pytest.raises(bild_comfy.ComfyFehler, match="Bildmodell FLUX.2 fehlt am PC"):
        bild_comfy._ausfuehren(bild_comfy.graph_flux2("p", 512, 512, 1, []), 5)


def _historie(status: dict) -> bytes:
    return json.dumps({"pid": {"status": status, "outputs": {}}}).encode()


def test_speicher_voll_klarer_befund(monkeypatch):
    st = {"status_str": "error", "messages": [["execution_error", {"exception_type": "torch.OutOfMemoryError",
                                                                    "exception_message": "CUDA out of memory"}]]}
    monkeypatch.setattr(bild_comfy, "_http", lambda *a, **k: (200, _historie(st)))
    with pytest.raises(bild_comfy.ComfyFehler, match="Zu viele Vorlagen für die Grafikkarte"):
        bild_comfy._abfragen("pid")


def test_fehler_ohne_meldung_bleibt_allgemein(monkeypatch):
    monkeypatch.setattr(bild_comfy, "_http", lambda *a, **k: (200, _historie({"status_str": "error"})))
    with pytest.raises(bild_comfy.ComfyFehler, match="Erzeugung in ComfyUI fehlgeschlagen"):
        bild_comfy._abfragen("pid")
```
(`import json, pytest` und `from spaces.marketing.claw import bild_comfy` stehen schon in der Datei oder werden ergänzt.)

- [ ] **Step 3: Tests laufen lassen.**
Run: `& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/claw/tests/test_bild_comfy.py -q`
Expected: Die neuen Tests schlagen fehl (`graph_flux2` fehlt).

- [ ] **Step 4: Implementieren** in `claw/bild_comfy.py`.
  - Den Kopfkommentar um die FLUX.2-Datei ergänzen.
  - Unter `ABLAUF_FREISTELLEN` einfügen:
```python
ABLAUF_FLUX2 = Path(os.environ.get("COMFYUI_ABLAUF_FLUX2") or
                    Path(__file__).resolve().parents[1] / "bilder" / "flux2_klein_api.json")
MAX_REFERENZEN = 3
MODELL_FEHLT = "Bildmodell FLUX.2 fehlt am PC"
SPEICHER_VOLL = "Zu viele Vorlagen für die Grafikkarte – mit weniger Vorlagen noch einmal"
_FLUX2_DATEIEN = ("flux-2-klein-4b-fp8", "qwen_3_4b", "flux2-vae")


def _masse_pruefen(breite: int, hoehe: int) -> None:
    if breite % 16 or hoehe % 16 or not (256 <= breite <= 2048 and 256 <= hoehe <= 2048):
        raise ComfyFehler(f"Masse {breite}x{hoehe}: je 256-2048 und Vielfache von 16")


def graph_flux2(prompt: str, breite: int, hoehe: int, seed: int, namen: list[str]) -> dict:
    """FLUX.2-klein-Graph (bilder/flux2_klein_api.json) mit Referenzbildern als Kette ReferenceLatent:
    Text -> c1 -> c2 -> ... -> Guider. Knoten je Referenz i: r<i> Laden, s<i> auf 1 MP, e<i> VAE, c<i> Referenz."""
    g = json.loads(ABLAUF_FLUX2.read_text(encoding="utf-8"))
    g["4"]["inputs"]["text"] = prompt
    g["6"]["inputs"].update(width=breite, height=hoehe)
    g["7"]["inputs"].update(width=breite, height=hoehe)
    g["8"]["inputs"]["noise_seed"] = int(seed)
    vorher = ["4", 0]
    for i, name in enumerate(namen, 1):
        g[f"r{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[f"s{i}"] = {"class_type": "ImageScaleToTotalPixels",
                      "inputs": {"image": [f"r{i}", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                                 "resolution_steps": 1}}
        g[f"e{i}"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"s{i}", 0], "vae": ["3", 0]}}
        g[f"c{i}"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": vorher, "latent": [f"e{i}", 0]}}
        vorher = [f"c{i}", 0]
    g["5"]["inputs"]["conditioning"] = vorher
    return g


def erzeugen_flux2(prompt: str, breite: int, hoehe: int, seed: int, referenzen=(), zeitlimit_s: int = 300) -> bytes:
    referenzen = list(referenzen)
    if len(referenzen) > MAX_REFERENZEN:
        raise ComfyFehler(f"Höchstens {MAX_REFERENZEN} Referenzbilder")
    _masse_pruefen(breite, hoehe)
    namen = [_hochladen(f"nl-ref-{uuid.uuid4().hex[:12]}.png", r) for r in referenzen]
    return _ausfuehren(graph_flux2(prompt, breite, hoehe, seed, namen), zeitlimit_s)
```
  - `erzeugen` und `ueberarbeiten` rufen ebenfalls `_masse_pruefen` auf; die alte Inline-Prüfung entfällt dort.
  - `_ausfuehren`: Das POST auf `/prompt` wird in `try/except urllib.error.HTTPError as e` gefasst. Dabei `rumpf = e.read().decode("utf-8", "replace")`.
    - Enthält `rumpf` `"not in"` und einen der `_FLUX2_DATEIEN`-Namen: `raise ComfyFehler(MODELL_FEHLT) from None`.
    - Sonst: `raise ComfyFehler(f"ComfyUI lehnt den Auftrag ab: {rumpf[:200]}") from None`.
  - `_abfragen`: Beim Fehlerstatus aus `status.get("messages") or []` das erste `["execution_error", {...}]` lesen.
    - Wenn `"OutOfMemory"` in `exception_type` steht oder `"out of memory"` in `exception_message.lower()`: `raise ComfyFehler(SPEICHER_VOLL)`.
    - Sonst `raise ComfyFehler("Erzeugung in ComfyUI fehlgeschlagen" + (f": {meldung[:200]}" if meldung else ""))`.
    - Ohne Meldung bleibt der bisherige Text.
  - `import urllib.error` ergänzen.

- [ ] **Step 5: Tests grün.**
Run: wie Step 3. Expected: alle grün, inklusive der bestehenden Tests der Datei.

- [ ] **Step 6: Rauchprobe gegen das echte ComfyUI** (braucht Task 1; liest nur und erzeugt ein Bild; ComfyUI wird nicht beendet):
```
& C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -c "from spaces.marketing.claw import bild_comfy as b; import time; t=time.time(); png=b.erzeugen_flux2('a calm lake at sunrise, photo', 768, 512, 1, [], 900); open(r'E:/Temp/flux2_rauch.png','wb').write(png); print(len(png), round(time.time()-t), 's')"
```
Expected: PNG über 50 kB, Zeit notiert. Ein Knoten-Fehler (falscher Eingang) zeigt sich hier als `ComfyFehler` mit Text. Dann den Graphen an `/object_info` angleichen und die Probe wiederholen.

- [ ] **Step 7: Commit (MOS)**
```
git add spaces/marketing/bilder/flux2_klein_api.json spaces/marketing/claw/bild_comfy.py spaces/marketing/claw/tests/test_bild_comfy.py
git commit -m "feat(marketing): FLUX.2-klein-Graph mit Referenzbildern und klaren ComfyUI-Befunden" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Messlauf FLUX.1 gegen FLUX.2 (Controller)

**Files:** nur Scratchpad (`messlauf_flux2.py`, Ausgabeordner `E:/Temp/claude/…/scratchpad/messlauf/`). Keine Repo-Dateien.

**Interfaces:**
- Consumes: `bild_comfy.erzeugen`, `bild_comfy.erzeugen_flux2` (Task 2).

- [ ] **Step 1: Skript.** Drei Motive aus dem Probe-Entwurf (Kopfbild 1024×512, Thema 512×512, Ausblick 768×512) in englischen Prompts.
  - Je Motiv FLUX.1 (`erzeugen`) und FLUX.2 (`erzeugen_flux2`).
  - Zeiten: erster Aufruf je Modell = kalt, zweiter = warm.
  - Dazu ein Ändern (FLUX.2 mit dem FLUX.2-Kopfbild als Referenz und „make the sky a warm sunset, keep everything else unchanged“).
  - Dazu ein Einbau (eine Datei aus `media/` als Referenz).
  - Vor dem Wechsel zwischen den Modellen `bild_comfy.freigeben()` (12 GB).
- [ ] **Step 2: Ausführen** und eine Tabelle (Motiv, Modell, kalt/warm s) plus Bildpfade ins Ledger schreiben.
- [ ] **Step 3: Dem Betreiber die Bilder zeigen** (Pfade nennen). Sein Ok ist die Bedingung dafür, `MARKETING_BILDMODELL` in Task 8 nicht auf `flux1` zu setzen. Die Codearbeit (Tasks 4–7) wartet nicht darauf.

---

### Task 4: Migration 068 und Bild-API mit Vorlagen und `aendern` (MOS)

**Files:**
- Create: `spaces/marketing/db/068_bild_vorlagen.sql`, `spaces/marketing/db/verify_068.sql`
- Modify: `spaces/marketing/api/bilder.py` (`_anlegen`, `arbeiter_naechster`, neue Route `arbeiter_vorlage`, `_STAND_SQL`)
- Test: `spaces/marketing/tests/test_bilder_api.py`

**Interfaces:**
- Produces:
  - SQL `marketing.pult_bild_auftrag(p_inhalt uuid, p_platz text, p_nur_leere boolean, p_hinweis text, p_urheber text, p_staerke int, p_modus text, p_vorlagen jsonb) RETURNS uuid` (neue 8-arg-Hülle). Die 7-arg-Fassung lässt `aendern` zu.
  - Spalte `marketing.bild_auftraege.vorlagen jsonb NOT NULL DEFAULT '[]'`.
  - API `_anlegen(iid, payload, urheber)` nimmt `modus` ∈ {`neu`,`aendern`,`ueberarbeiten`,`freistellen`} und `vorlagen: list[str]` (höchstens 3).
  - `POST /api/bilder/arbeiter/naechster` liefert zusätzlich `vorlagen`.
  - `GET /api/bilder/arbeiter/{aid}/vorlage?name=<n>` liefert die Datei nur, wenn `n` in `vorlagen` des Auftrags steht, der Auftrag `in_arbeit` ist und die Datei für den Mandanten nicht fremd ist. Sonst 404.
  - Konstante `bilder.VORLAGEN_MAX = 3`.

- [ ] **Step 1: `068_bild_vorlagen.sql` schreiben.** Kopf wie 067 (Zweck, Spec-Verweis, „Additiv, idempotent“, „ersetzt die 7-arg-Hülle aus 059“). Inhalt in `BEGIN; … COMMIT;`:
```sql
ALTER TABLE marketing.bild_auftraege ADD COLUMN IF NOT EXISTS vorlagen jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE marketing.bild_auftraege DROP CONSTRAINT IF EXISTS bild_auftraege_vorlagen_check;
ALTER TABLE marketing.bild_auftraege ADD CONSTRAINT bild_auftraege_vorlagen_check
  CHECK (jsonb_typeof(vorlagen) = 'array' AND jsonb_array_length(vorlagen) <= 3);
ALTER TABLE marketing.bild_auftraege DROP CONSTRAINT IF EXISTS bild_auftraege_modus_check;
ALTER TABLE marketing.bild_auftraege ADD CONSTRAINT bild_auftraege_modus_check
  CHECK (modus IN ('neu','ueberarbeiten','aendern','freistellen'));

-- 7-arg (aus 059): zusaetzlich 'aendern' (braucht einen Platz mit echtem Bild)
CREATE OR REPLACE FUNCTION marketing.pult_bild_auftrag(
    p_inhalt uuid, p_platz text, p_nur_leere boolean, p_hinweis text, p_urheber text,
    p_staerke int, p_modus text) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE v_id uuid; v_url text;
BEGIN
  IF p_staerke IS NULL OR p_staerke < 0 OR p_staerke > 100 THEN
    RAISE EXCEPTION 'Staerke muss 0 bis 100 sein'; END IF;
  IF p_modus IS NULL OR p_modus NOT IN ('neu', 'ueberarbeiten', 'aendern', 'freistellen') THEN
    RAISE EXCEPTION 'Modus muss neu, aendern, ueberarbeiten oder freistellen sein'; END IF;
  IF p_modus IN ('freistellen', 'aendern') AND (p_platz IS NULL OR p_platz = '') THEN
    RAISE EXCEPTION '% braucht einen Bildplatz', initcap(p_modus); END IF;
  IF p_modus = 'aendern' THEN
    SELECT bloecke #>> ARRAY[p_platz, 'data', 'props', 'url'] INTO v_url FROM marketing.inhalt_fassungen
     WHERE inhalt = p_inhalt ORDER BY fassung DESC LIMIT 1;
    IF marketing._bild_platz_leer(v_url) THEN
      RAISE EXCEPTION 'Hier ist noch kein Bild – nimm bild_erzeugen'; END IF;
  END IF;
  v_id := marketing.pult_bild_auftrag(p_inhalt, p_platz, p_nur_leere, p_hinweis, p_urheber);
  UPDATE marketing.bild_auftraege
     SET staerke = p_staerke,
         modus = CASE WHEN p_modus IN ('freistellen', 'aendern') THEN p_modus
                      WHEN p_staerke = 100 THEN 'neu' ELSE p_modus END
   WHERE id = v_id;
  RETURN v_id;
END $$;

-- 8-arg: Vorlagen (Mediennamen, hoechstens 3, nur Texte, ohne Doppelte)
CREATE OR REPLACE FUNCTION marketing.pult_bild_auftrag(
    p_inhalt uuid, p_platz text, p_nur_leere boolean, p_hinweis text, p_urheber text,
    p_staerke int, p_modus text, p_vorlagen jsonb) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE v_id uuid; v_v jsonb := coalesce(p_vorlagen, '[]'::jsonb);
BEGIN
  IF jsonb_typeof(v_v) <> 'array' OR jsonb_array_length(v_v) > 3
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(v_v) e WHERE jsonb_typeof(e) <> 'string')
     OR (SELECT count(DISTINCT e) FROM jsonb_array_elements_text(v_v) e) <> jsonb_array_length(v_v) THEN
    RAISE EXCEPTION 'Vorlagen: hoechstens 3 verschiedene Mediennamen'; END IF;
  IF p_modus = 'freistellen' AND jsonb_array_length(v_v) > 0 THEN
    RAISE EXCEPTION 'Freistellen nimmt keine Vorlagen'; END IF;
  IF p_modus = 'aendern' AND jsonb_array_length(v_v) > 2 THEN
    RAISE EXCEPTION 'Aendern: hoechstens 2 Vorlagen (das Bild selbst ist die erste)'; END IF;
  v_id := marketing.pult_bild_auftrag(p_inhalt, p_platz, p_nur_leere, p_hinweis, p_urheber, p_staerke, p_modus);
  UPDATE marketing.bild_auftraege SET vorlagen = v_v WHERE id = v_id;
  RETURN v_id;
END $$;
```
Vorher in derselben Datei prüfen, ob `marketing._bild_platz_leer(text)` existiert (`\df` im Probelauf). Der Name stammt aus 056.

- [ ] **Step 2: `verify_068.sql` schreiben**, nach dem Muster von `verify_059.sql` und `verify_067.sql` (DO-Blöcke mit `ASSERT`, eigene Testdaten in der Transaktion). Fälle:
  - 0: Spalte `vorlagen` und die 8-arg-Funktion existieren (`to_regprocedure`).
  - 1: `neu` mit 3 Vorlagen → Zeile mit `vorlagen` = genau diese 3, Modus `neu`.
  - 2: 4 Vorlagen → Fehler; doppelte → Fehler; Zahl statt Text → Fehler.
  - 3: `aendern` auf einen Platz mit echtem Bild und 2 Vorlagen → Modus `aendern`; mit 3 Vorlagen → Fehler.
  - 4: `aendern` auf einen leeren Platz (Platzhalter-URL) → Fehler mit „Hier ist noch kein Bild“.
  - 5: `freistellen` mit Vorlage → Fehler.
  - 6: Eine alte Zeile mit Modus `ueberarbeiten` bleibt gültig (`UPDATE … SET modus='ueberarbeiten'` geht).
  - 7: Die 7-arg-Fassung ohne Vorlagen geht weiter, `vorlagen` = `[]`.
  - Abschluss `RAISE NOTICE 'verify_068 ok';`.

- [ ] **Step 3: Probelauf (ROLLBACK)**
Run: `migration_probe spaces/marketing/db/068_bild_vorlagen.sql spaces/marketing/db/verify_068.sql spaces/marketing/db/068_bild_vorlagen.sql spaces/marketing/db/verify_068.sql spaces/marketing/db/verify_059.sql`
Expected: `verify_068 ok` zweimal, `PROBE OK (zurueckgerollt)`.

- [ ] **Step 4: Failing API-Tests** in `tests/test_bilder_api.py`, im Stil der bestehenden Tests `test_auftrag_mit_staerke_und_modus` und `test_naechster_ergaenzt_staerke_modus`:
  - `test_auftrag_aendern_mit_vorlagen`: POST mit `{"platz": "<echter>", "modus": "aendern", "hinweis": "Himmel abendrot", "vorlagen": ["a.jpg"]}`. Erwartet: Das SQL ruft die 8-arg-Funktion mit `'["a.jpg"]'::jsonb` auf.
  - `test_auftrag_vorlagen_form` (parametrisiert):
    - `"vorlagen": "a.jpg"` → 422;
    - 4 Namen → 422;
    - `["../x.jpg"]` → 422;
    - `["a.jpg", "a.jpg"]` → wird zu `["a.jpg"]` dedupliziert;
    - `[1]` → 422.
  - `test_naechster_liefert_vorlagen`: Die Zusatzabfrage enthält `b.vorlagen`, die Antwort `vorlagen`.
  - `test_vorlage_route`:
    - Name nicht in den Vorlagen → 404;
    - Auftrag nicht `in_arbeit` → 404;
    - fremder Mandant (`ist_fremd` liefert True) → 404;
    - gültig → 200 mit Dateiinhalt.
- [ ] **Step 5: Test laufen lassen**, er schlägt fehl.
Run: `… -m pytest spaces/marketing/tests/test_bilder_api.py -q`.

- [ ] **Step 6: Implementieren** in `api/bilder.py`:
```python
VORLAGEN_MAX = 3


def _vorlagen_formen(roh) -> list[str]:
    if roh is None:
        return []
    if not isinstance(roh, list) or not all(isinstance(n, str) for n in roh):
        raise HTTPException(422, "vorlagen muss eine Liste von Mediennamen sein")
    namen = list(dict.fromkeys(roh))          # Doppelte raus, Reihenfolge bleibt
    if len(namen) > VORLAGEN_MAX or not all(_bilddatei_name_ok(n) for n in namen):
        raise HTTPException(422, f"vorlagen: hoechstens {VORLAGEN_MAX} gueltige Mediennamen")
    return namen
```
  - **`_anlegen`:**
    - `modus` erlaubt `("neu", "aendern", "ueberarbeiten", "freistellen")`.
    - `vorlagen = _vorlagen_formen(payload.get("vorlagen"))`.
    - Bei `aendern`: `_echtes_bild_pruefen(i, platz)` (Platz Pflicht, Meldung 422 „Hier ist noch kein Bild – nimm bild_erzeugen“, dafür `_echtes_bild_pruefen` um einen Parameter `meldung` erweitern) und `staerke = 55`.
    - Das SQL ruft die 8-arg-Hülle mit `{lit(json.dumps(vorlagen))}::jsonb` auf.
  - **`_STAND_SQL`:** liefert zusätzlich `vorlagen`.
  - **`arbeiter_naechster`:** Die Zusatzabfrage liest `b.vorlagen`.
  - **Neue Route** (Import im Rumpf, sonst Kreisimport `chat` ↔ `bilder`):
```python
@router.get("/arbeiter/{aid}/vorlage")
def arbeiter_vorlage(aid: str, name: str = Query(""), x_bild_key: str | None = Header(None)):
    _bild_schluessel(x_bild_key)
    a = _auftrag_id(aid)
    from spaces.marketing.api.chat import _medien_ausliefern
    z = _lesen_einer(lambda:
        "SELECT b.vorlagen, b.status, coalesce(b.vergeben_bis > now(), false) AS gueltig, i.mandant "
        "FROM marketing.bild_auftraege b JOIN marketing.inhalte i ON i.id = b.inhalt "
        f"WHERE b.id = {lit(a)}::uuid")
    if not z or z.get("status") != "in_arbeit" or not z.get("gueltig") or name not in (z.get("vorlagen") or []):
        raise HTTPException(404, "Unbekannte Vorlage")
    return _medien_ausliefern(name, z.get("mandant"))
```
- [ ] **Step 7: Tests grün**, dazu die bestehenden Tests der Datei und `tests/test_chat_api.py`.
- [ ] **Step 8: Commit (MOS)**
```
git add spaces/marketing/db/068_bild_vorlagen.sql spaces/marketing/db/verify_068.sql spaces/marketing/api/bilder.py spaces/marketing/tests/test_bilder_api.py
git commit -m "feat(marketing): Migration 068 - Bildauftraege mit Vorlagen und Modus aendern, Arbeiter-Route fuer Vorlagen" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Bild-Arbeiter: FLUX.2, Ändern, Vorlagen, Rückfall (MOS)

**Files:**
- Modify: `spaces/marketing/workers/bild_worker.py` (`ArbeiterApi.vorlage`, `_modell`, `_erzeugen`, `_bilder`, `ein_durchlauf`)
- Modify: `spaces/marketing/claw/bild_prompt.py` (`aenderungs_prompt`)
- Test: `spaces/marketing/tests/test_bild_worker.py`, `spaces/marketing/claw/tests/test_bild_prompt.py`

**Interfaces:**
- Consumes: `bild_comfy.erzeugen_flux2(prompt, breite, hoehe, seed, referenzen, zeitlimit_s)` (Task 2); Auftragsfelder `modus`, `hinweis`, `vorlagen`; Route `GET /api/bilder/arbeiter/{aid}/vorlage?name=` (Task 4).
- Produces:
  - `ArbeiterApi.vorlage(aid, name) -> bytes | None` (404 → None).
  - `bild_worker.modell() -> str` (`"flux2"` oder `"flux1"`, aus `MARKETING_BILDMODELL`).
  - `bild_prompt.aenderungs_prompt(anweisung: str, platz: dict) -> str` (englische Änderungsanweisung).

- [ ] **Step 1: Failing Tests** in `tests/test_bild_worker.py`. Die bestehende Fake-API und das Fake-Comfy der Datei werden um `vorlage()` und `erzeugen_flux2()` erweitert; das Fake zeichnet Prompt und Referenz-Bytes auf.
  - `test_flux2_neu_ohne_vorlagen`: Modus `neu` → `erzeugen_flux2` mit `referenzen == []`, kein `erzeugen` (FLUX.1).
  - `test_flux2_neu_mit_drei_vorlagen`: `vorlagen` = 3 Namen → `api.vorlage` dreimal, `referenzen` = 3 normalisierte PNGs in derselben Reihenfolge.
  - `test_flux2_aendern_quelle_ist_referenz_eins`:
    - Modus `aendern`, Platz mit Bild, 1 Vorlage → `referenzen[0]` = normalisierte Quelle, `referenzen[1]` = Vorlage.
    - `sehen.beschreiben` wird nicht aufgerufen.
    - Der Prompt kommt aus `aenderungs_prompt`.
  - `test_flux2_aendern_ohne_quelle_befund`: `api.quelle` liefert None → kein Bild erzeugt; das Ergebnis ist leer mit Befund „<platz>: Quellbild fehlt“; `zurueck(endgueltig=True)` (Review Focus 2).
  - `test_vorlage_fehlt_befund`: `api.vorlage` liefert None → kein Bild, Befund „Vorlage x.jpg nicht gefunden“, zurück endgültig.
  - `test_rueckfall_flux1`: `monkeypatch.setenv("MARKETING_BILDMODELL", "flux1")`.
    - Modus `neu` mit Vorlagen → `erzeugen` (FLUX.1) ohne Vorlagen, Befund enthält „Vorlagen nur mit FLUX.2“.
    - Modus `aendern` → alter Überarbeiten-Weg mit Stärke 55 (Sehen + `bearbeitungs_prompt`).
  - `test_alter_ueberarbeiten_auftrag_laeuft_alt`: Modus `ueberarbeiten` unter `flux2` → alter Weg wie heute (Review Focus 5).
  - `test_modell_schalter`: `modell()` gibt für `""`, `"flux2"` und `"quatsch"` `"flux2"` zurück, für `"flux1"` und `" FLUX1 "` `"flux1"`.
  - `test_speicher_voll_wird_befund`: Das Fake wirft `ComfyFehler(SPEICHER_VOLL)` → `zurueck` mit diesem Text (über den bestehenden except-Zweig).
  - In `claw/tests/test_bild_prompt.py`: `test_aenderungs_prompt_nutzt_ollama_und_faellt_zurueck`. Mit gefaktem `_ollama`:
    - Antwort `"Make the sky a warm sunset. Keep everything else unchanged."` wird übernommen.
    - Bei leerer Antwort ist das Ergebnis `"Keep the image unchanged except: " + anweisung`.
- [ ] **Step 2: Tests laufen**, sie schlagen fehl.
Run: `… -m pytest spaces/marketing/tests/test_bild_worker.py spaces/marketing/claw/tests/test_bild_prompt.py -q`

- [ ] **Step 3: `bild_prompt.aenderungs_prompt`**:
```python
_AENDERUNG = ("You edit an existing photo with an image model. Write ONE short English instruction for the model.\n"
              "Wish of the operator (German): {anweisung}\n"
              "Image style of the brand: {bildstil}\n"
              "Rules: say exactly what changes; end with 'Keep everything else unchanged.'; no text, no letters, "
              "no logos in the image. Answer with the instruction only.")


def aenderungs_prompt(anweisung: str, platz: dict) -> str:
    """Anweisung fuer FLUX.2-Aendern (Referenz 1 = das Bild selbst). Ollama uebersetzt und schaerft; ohne Antwort
    geht die deutsche Anweisung mit festem Rahmen durch (Qwen3 als Text-Encoder versteht sie)."""
    anfrage = _AENDERUNG.format(anweisung=(anweisung or "-")[:500], bildstil=_bildstil(platz))
    antwort = _ollama("/api/generate", {"model": TEXT_MODELL, "prompt": anfrage, "stream": False,
                                        "keep_alive": 0, "options": {"temperature": 0.3, "num_ctx": NUM_CTX}})
    kern = bereinigen(antwort.get("response", ""))
    return kern or f"Keep the image unchanged except: {anweisung.strip()[:500]}"
```

- [ ] **Step 4: Arbeiter** in `workers/bild_worker.py`.
  - **`ArbeiterApi.vorlage`:** wie `quelle`, aber URL `…/arbeiter/{aid}/vorlage?name=<quote(name)>`, 404 → None, liest höchstens `QUELLE_MAX + 1` Bytes.
  - **Schalter und Hilfen:**
```python
def modell() -> str:
    return "flux1" if os.environ.get("MARKETING_BILDMODELL", "").strip().lower() == "flux1" else "flux2"


def _vorlagen_holen(api, aid, namen) -> tuple[list[bytes], str] | str:
    """Vorlagen als normalisierte PNGs; (liste, "") oder (leer, befund) oder "verworfen"."""
    aus = []
    for n in namen:
        if not api.weiter(aid):
            return "verworfen"
        try:
            roh = api.vorlage(aid, n)
        except ApiFehler as e:
            if e.code == 422 and "in Arbeit" in e.grund:
                return "verworfen"
            raise
        png = quelle_normalisieren(roh) if roh and len(roh) <= QUELLE_MAX else None
        if png is None:
            return [], f"Vorlage {n} nicht gefunden oder unlesbar"
        aus.append(png)
    return aus, ""
```
  - **Neue Funktion `_flux2(api, aid, auftrag, ziele, comfy, prompt, messen)`** für die Modi `neu` und `aendern` unter `flux2`. Rückgabe wie `_erzeugen`: `(ergebnis, befunde, messwerte)` oder `"verworfen"`.
    - `comfy.freigeben()` vor dem Ollama-Schritt, wie heute.
    - Vorlagen einmal je Auftrag holen; bei Befund `({}, [befund], {})` zurückgeben.
    - Je Platz bei `neu`: `text = prompt.prompt_schreiben(daten, titel, hinweis)`, Referenzen = Vorlagen.
    - Je Platz bei `aendern`:
      - Quelle wie in `_erzeugen` holen (mit `api.weiter` davor und demselben „verworfen“-Mapping).
      - Fehlt die Quelle oder ist sie unlesbar: `befunde.append(f"{platz.id}: Quellbild fehlt")` und weiter, kein Ersatzbild.
      - Sonst `text = prompt.aenderungs_prompt(hinweis, daten)` und Referenzen = `[quelle] + vorlagen`.
    - `daten = {**platz.als_dict(), "palette": …, "bildstil": …}` wie in `_erzeugen`.
    - Dann `_bilder(...)` mit dem Erzeuger `lambda t, w, h, s: comfy.erzeugen_flux2(t, w, h, s, referenzen, zeitlimit_s=ERZEUGUNG_ZEITLIMIT_S)` je Platz, `staerke=100` (keine Ähnlichkeitsregel) und `quelle=None` (keine CLIP-Messung).
    - Dafür bekommt `_bilder` in `arbeit` je Eintrag einen vierten Wert `erzeuger` (Callable oder None). `None` heißt wie heute `comfy.erzeugen(text, w, h, seed, zeitlimit_s=ERZEUGUNG_ZEITLIMIT_S)`. `_erzeugen` hängt deshalb `(platz, text, quelle, None)` an.
  - **`ein_durchlauf`:** Nach dem Ollama-Bereitschaftscheck verzweigen:
    - `modus in ("neu", "aendern") and modell() == "flux2"` → `_flux2(...)`.
    - `modus == "aendern"` (flux1) → `_erzeugen` mit `{**auftrag, "modus": "ueberarbeiten", "staerke": 55}`.
    - Sonst `_erzeugen` wie heute (`neu`, `ueberarbeiten`).
    - Unter flux1 mit nicht leeren `vorlagen` wird dem Befund „Vorlagen nur mit FLUX.2“ vorangestellt.
- [ ] **Step 5: Tests grün**, dazu alle bestehenden Tests in `test_bild_worker.py`.
- [ ] **Step 6: Commit (MOS)**
```
git add spaces/marketing/workers/bild_worker.py spaces/marketing/claw/bild_prompt.py spaces/marketing/tests/test_bild_worker.py spaces/marketing/claw/tests/test_bild_prompt.py
git commit -m "feat(marketing): Bild-Arbeiter mit FLUX.2 - aendern mit Referenz, Vorlagen, Rueckfall flux1" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Agent-Werkzeuge, Chat-API und Prompt (MOS)

**Files:**
- Modify: `spaces/marketing/claw/agent_werkzeuge.py` (`WERKZEUGE`, `PARAMETER`, `bild_erzeugen`, neu `bild_aendern`, `abschliessen`)
- Modify: `spaces/marketing/api/chat.py` (`_bildauftraege_formen`, Aufruf von `_anlegen` in `arbeiter_fertig`)
- Modify: `spaces/marketing/claw/agent_prompt.py` (Werkzeugliste, Regeln)
- Test: `spaces/marketing/claw/tests/test_agent_werkzeuge.py`, `spaces/marketing/tests/test_chat_api.py`, `spaces/marketing/claw/tests/test_agent_prompt.py`

**Interfaces:**
- Consumes: `bilder._anlegen` mit `modus` `aendern` und `vorlagen` (Task 4).
- Produces:
  - Bildauftrags-Dict aus `anwenden` und `nachspielen`: `{"platz": str, "modus": "neu"|"aendern"|"freistellen", "hinweis": str, "vorlagen": list[str]}`.
  - Werkzeug `bild_aendern` (`platz`*, `anweisung`*, `vorlagen`).

- [ ] **Step 1: Failing Tests** in `claw/tests/test_agent_werkzeuge.py`. Das Testdokument hat einen Platz `held` mit echtem Bild (`medien:held.jpg`) und einen leeren Platz `leer` (Platzhalter-URL). Medienmenge `{"held.jpg", "foto.jpg", "b.jpg", "c.jpg", "d.jpg"}`.
```python
def test_bild_erzeugen_mit_vorlagen():
    e = anwenden(DOK, [{"werkzeug": "bild_erzeugen", "platz": "leer", "hinweis": "Produkt auf Holztisch",
                        "vorlagen": ["foto.jpg"]}], MEDIEN)
    assert e.bildauftraege == [{"platz": "leer", "modus": "neu", "hinweis": "Produkt auf Holztisch",
                                "vorlagen": ["foto.jpg"]}]


def test_bild_erzeugen_ohne_vorlagen_hat_leere_liste():
    e = anwenden(DOK, [{"werkzeug": "bild_erzeugen", "platz": "leer", "hinweis": "x"}], MEDIEN)
    assert e.bildauftraege[0]["vorlagen"] == []


@pytest.mark.parametrize("vorlagen,meldung", [
    ("foto.jpg", "vorlagen muss eine Liste"), (["foto.jpg", "foto.jpg"], "doppelt"),
    (["foto.jpg", "b.jpg", "c.jpg", "d.jpg"], "höchstens 3"), (["erfunden.jpg"], "gibt es nicht in den Medien")])
def test_bild_erzeugen_vorlagen_geprueft(vorlagen, meldung):
    with pytest.raises(WerkzeugFehler, match=meldung):
        anwenden(DOK, [{"werkzeug": "bild_erzeugen", "platz": "leer", "hinweis": "x", "vorlagen": vorlagen}], MEDIEN)


def test_bild_aendern():
    e = anwenden(DOK, [{"werkzeug": "bild_aendern", "platz": "held", "anweisung": "Himmel abendrot",
                        "vorlagen": ["foto.jpg"]}], MEDIEN)
    assert e.bildauftraege == [{"platz": "held", "modus": "aendern", "hinweis": "Himmel abendrot",
                                "vorlagen": ["foto.jpg"]}]


def test_bild_aendern_leerer_platz_abgelehnt():
    with pytest.raises(WerkzeugFehler, match="Hier ist noch kein Bild – nimm bild_erzeugen"):
        anwenden(DOK, [{"werkzeug": "bild_aendern", "platz": "leer", "anweisung": "x"}], MEDIEN)


def test_bild_aendern_hoechstens_zwei_vorlagen():
    with pytest.raises(WerkzeugFehler, match="höchstens 2"):
        anwenden(DOK, [{"werkzeug": "bild_aendern", "platz": "held", "anweisung": "x",
                        "vorlagen": ["foto.jpg", "b.jpg", "c.jpg"]}], MEDIEN)


def test_nachspielen_zieht_vorlagen_mit():
    ns = nachspielen(DOK, [{"werkzeug": "bild_aendern", "platz": "held", "anweisung": "x",
                            "vorlagen": ["foto.jpg"]}], MEDIEN)
    assert ns.bildauftraege[0]["vorlagen"] == ["foto.jpg"] and ns.bildauftraege[0]["modus"] == "aendern"
```
  In `tests/test_chat_api.py`:
  - `test_fertig_bildauftrag_aendern_mit_vorlagen`: `bildauftraege=[{"platz":"held","modus":"aendern","hinweis":"x","vorlagen":["foto.jpg"]}]` → `_anlegen` bekommt `modus="aendern"` und `vorlagen=["foto.jpg"]`.
  - `test_fertig_bildauftrag_vorlagen_kaputt_wird_grund`: `vorlagen="foto.jpg"` → Eintrag mit `grund`, Hinweis an der Runde, kein `_anlegen`.

  In `claw/tests/test_agent_prompt.py`: `test_bildregeln`. `SYSTEM` enthält:
  - `"bild_aendern: platz*, anweisung*"`;
  - `"vorlagen (bis zu 3 Mediennamen"`;
  - `"Logos und Schrift nie über das Bildmodell"`;
  - `"Ändern vor neu Erzeugen"`.
- [ ] **Step 2: Tests laufen**, sie schlagen fehl.
- [ ] **Step 3: Implementieren.**
  - **`agent_werkzeuge.py`:**
    - `"bild_aendern"` in `WERKZEUGE` nach `"bild_erzeugen"`.
    - `PARAMETER["bild_erzeugen"] = ({"platz", "hinweis"}, {"vorlagen"})`, `PARAMETER["bild_aendern"] = ({"platz", "anweisung"}, {"vorlagen"})`.
    - Neue Hilfen in `_Lauf`:
```python
    def vorlagen(self, wert, hoechstens: int) -> list[str]:
        if wert is None:
            return []
        if not isinstance(wert, list) or not all(isinstance(n, str) for n in wert):
            raise WerkzeugFehler("vorlagen muss eine Liste von Mediennamen sein")
        namen = [self.quelle(n)[len("medien:"):] for n in wert]
        if len(set(namen)) != len(namen):
            raise WerkzeugFehler("vorlagen: ein Name ist doppelt")
        if len(namen) > hoechstens:
            raise WerkzeugFehler(f"vorlagen: höchstens {hoechstens}")
        return namen

    def bild_erzeugen(self, a: dict) -> None:
        if not isinstance(a["hinweis"], str) or len(a["hinweis"]) > 500:
            raise WerkzeugFehler("hinweis muss Text sein (höchstens 500 Zeichen)")
        self.bild.append(("bild_erzeugen", {**a, "vorlagen": self.vorlagen(a.get("vorlagen"), 3)}))

    def bild_aendern(self, a: dict) -> None:
        if not isinstance(a["anweisung"], str) or not a["anweisung"].strip() or len(a["anweisung"]) > 500:
            raise WerkzeugFehler("anweisung muss Text sein (1-500 Zeichen)")
        self.bild.append(("bild_aendern", {**a, "vorlagen": self.vorlagen(a.get("vorlagen"), 2)}))
```
    - In `abschliessen`: Für `bild_aendern` wird geprüft, ob der Platz im Endstand ein echtes Bild trägt (`bildplaetze.finde(self.b)` → Platz mit `not bildplaetze.ist_leer(p.url)`). Sonst `raise _Spaet("bild_aendern", "Hier ist noch kein Bild – nimm bild_erzeugen")`.
    - Der Auftrag lautet `{"platz": pid, "modus": {"bild_erzeugen": "neu", "bild_aendern": "aendern", "bild_freistellen": "freistellen"}[name], "hinweis": a.get("hinweis") or a.get("anweisung") or "", "vorlagen": a.get("vorlagen", [])}`, bei `freistellen` mit `hinweis` `""` und `vorlagen` `[]`.
  - **`api/chat.py` `_bildauftraege_formen`:**
    - `modus` erlaubt `("neu", "aendern", "freistellen")`.
    - `vorlagen = b.get("vorlagen", [])` muss eine Liste aus höchstens 3 Texten sein; sonst ein Eintrag mit `"grund": "Bildauftrag ungültig"`.
    - Gültige Einträge tragen `"vorlagen"`.
    - In `arbeiter_fertig` geht `"vorlagen": b["vorlagen"]` an `_anlegen`.
  - **`agent_prompt.py`, Abschnitt „Bilder“:**
```
- bild_erzeugen: platz*, hinweis* (Motivbeschreibung, höchstens 500 Zeichen), vorlagen (bis zu 3 Mediennamen aus der Medienliste, z. B. ein angehängtes Produktfoto, das ins Motiv soll). platz = id eines vorhandenen Bildblocks.
- bild_aendern: platz*, anweisung* (was sich am vorhandenen Bild ändern soll, höchstens 500 Zeichen), vorlagen (bis zu 2 Mediennamen). Nur für Plätze mit echtem Bild.
- Ändern vor neu Erzeugen: soll nur ein Teil des Bildes anders werden, nimm bild_aendern.
- Logos und Schrift nie über das Bildmodell: ein Logo kommt als eigener Bildblock (bild_aus_medien), nie als Vorlage und nie im Hinweis.
- Welche Vorlage gemeint ist, muss eindeutig sein; sonst frag nach und ändere nichts.
```
    Die Zeile „fehlt das gewünschte Bild, sag es und biete bild_erzeugen an“ bleibt.
- [ ] **Step 4: Tests grün**, dazu `test_agent_werkzeuge.py`, `test_chat_api.py`, `test_agent_prompt.py`, `test_chat_worker.py` vollständig.
- [ ] **Step 5: Commit (MOS)**
```
git add spaces/marketing/claw/agent_werkzeuge.py spaces/marketing/api/chat.py spaces/marketing/claw/agent_prompt.py spaces/marketing/claw/tests/test_agent_werkzeuge.py spaces/marketing/tests/test_chat_api.py spaces/marketing/claw/tests/test_agent_prompt.py
git commit -m "feat(marketing): Agent kann Bilder aendern und eigene Fotos als Vorlage einbauen" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Bildfeld ohne KI-Knöpfe, sales-ui ohne Bildaufträge von Hand (SC)

**Files:**
- Modify: `editor/src/App/InspectorDrawer/ConfigurationPanel/input-panels/ImageSidebarPanel.tsx`
- Modify: `editor/src/pult.ts` (`bildBeauftragen` und `bildFreistellen` löschen, `bild_url` aus `Start`)
- Modify: `editor/src/bildfeld.ts` (`knopfText`, `staerkeWert`, `STUFE_*`, `erzeugenSperre`, `freistellbar` löschen, sofern sie sonst niemand nutzt; `tsc` zeigt es)
- Modify: zugehörige Tests (`editor/src/bildfeld.test.ts`, `editor/src/pult*.test.ts`, sofern sie die gelöschten Namen nutzen)
- Create: `editor/src/App/InspectorDrawer/ConfigurationPanel/input-panels/ImageSidebarPanel.test.tsx`
- Modify: `sales-mcp/ui_editor.py` (Handler `editor_bild` und `Route("/marketing/editor/{iid}/bild", …)` löschen, `"bild_url"` aus den Startdaten)
- Modify: `sales-mcp/tests/test_editor_seite.py`, `sales-mcp/tests/test_editor_paket.py`
- Bundle `sales-mcp/static/editor/*`

**Interfaces:**
- Produces: Startdaten ohne `bild_url`. `POST /marketing/editor/{iid}/bild` gibt 404 oder 405 zurück. Die Stand-Anzeige (`standFuer`, `standAbfragen`, `GET …/stand`) bleibt.

- [ ] **Step 1: Failing Tests.**
  - `ImageSidebarPanel.test.tsx`: das Panel mit einem Bildplatz und Store-Startwerten per `renderToStaticMarkup` rendern, Muster wie `KontextChips.test.tsx` mit `getInitialState`.
    - Erwartet: Der Text „Bild erzeugen, ändern oder freistellen: Bild markieren und den Assistenten fragen“ ist da.
    - Nicht enthalten sind „Hinweis (optional)“, „Stärke der Überarbeitung“, „Ganz neu erzeugen“ und „Freistellen“.
    - „Aus Medien wählen“ und „Alternativtext“ sind enthalten.
    - Mit einem laufenden Auftrag am Platz erscheint dessen Stand-Text als Chip.
  - `test_editor_seite.py`:
```python
def test_start_ohne_bild_url(angemeldet):
    start = _start(angemeldet.get(f"/marketing/editor/{IID}", headers=HOST).text)
    assert "bild_url" not in start


def test_bildauftrag_von_hand_gibt_es_nicht_mehr(angemeldet, pult):
    r = _senden(angemeldet, "POST", "bild", {"platz": "held", "hinweis": "x"})
    assert r.status_code in (404, 405)
    assert not [a for a in pult.aufrufe if a[1].endswith("/bilder") and a[0] == "POST"]
```
    Die bisherigen Tests zu `editor_bild` (Stärke, Freistellen, Formen) löschen.
  - `test_editor_paket.py`: Das Bundle enthält „Bild markieren und den Assistenten fragen“ und weder „Ganz neu erzeugen“ noch „Stärke der Überarbeitung“.
- [ ] **Step 2: Tests laufen**, sie schlagen fehl.
- [ ] **Step 3: Implementieren.**
  - **ImageSidebarPanel:**
    - Entfernen: die Zustände `hinweis`, `stufe`, `neu`, `laeuft` (falls nur dafür genutzt), `rueckmeldung` (nur, wenn ihn nicht auch das Medienlöschen braucht; sonst bleibt er), die Funktionen `erzeugen` und `freistellen`.
    - Im JSX alles von `<Typography variant="subtitle2">{knopfText(leer)}</Typography>` bis einschließlich des Freistellen-Blocks entfernen.
    - An dieser Stelle steht danach:
```tsx
        <Typography variant="body2" color="text.secondary">
          Bild erzeugen, ändern oder freistellen: Bild markieren und den Assistenten fragen
        </Typography>
```
    - Die Format-Zeile, den Stand-Chip und „Aus Medien wählen“ unverändert lassen. Den Text bei fehlendem Bildplatz unverändert lassen.
    - Imports bereinigen.
  - **`pult.ts`:** `bildBeauftragen`, `bildFreistellen` und das Feld `bild_url` löschen.
  - **`bildfeld.ts`:** ungenutzte Exporte löschen und ihre Tests mit.
  - **`ui_editor.py`:** `editor_bild`, seine Route und `"bild_url"` löschen.
- [ ] **Step 4: Alles grün:** `cd editor; npx vitest run; npx tsc --noEmit; npm run build` und sales-ui `tests/test_editor_seite.py tests/test_editor_paket.py`.
- [ ] **Step 5: Commit (SC)**
```
git add editor/src/App/InspectorDrawer/ConfigurationPanel/input-panels/ImageSidebarPanel.tsx editor/src/App/InspectorDrawer/ConfigurationPanel/input-panels/ImageSidebarPanel.test.tsx editor/src/pult.ts editor/src/bildfeld.ts <angepasste Testdateien> sales-mcp/ui_editor.py sales-mcp/tests/test_editor_seite.py sales-mcp/tests/test_editor_paket.py sales-mcp/static/editor
git commit -m "feat(editor): Bilder nur noch ueber den Assistenten - Bildfeld ohne KI-Knoepfe" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Auslieferung und echter Lauf (Controller, nur nach Freigabe des Betreibers)

- [ ] **Claims:** WORKBOARD und secondbrain eintragen; nur die eigene Zeile stagen.
- [ ] **Migration:**
  - Probelauf: `068 + verify_068 + verify_060 + verify_062 … verify_067`.
  - Danach 068 echt anwenden (`_db._run_psql`, `streng=True`).
  - Danach den Probelauf der Prüfskripte gegen die Live-DB wiederholen.
- [ ] **Push:** MOS `master` und SC `feat/stufe-1-fundament`; VM `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`.
- [ ] **PC:**
  - Haupt-Checkout synchronisieren. Dafür **vorher alle Dateien** in `spaces/marketing` gegen den letzten Sync-Stand `f7b6657b` hashen, dann `git restore --source=<HEAD> --worktree -- spaces/marketing`.
  - `MARKETING_BILDMODELL=flux1` in `Vibemind_V1/.env`, solange das Ok aus Task 3 fehlt.
  - :5510, :8133 und :8134 neu starten. ComfyUI nicht.
- [ ] **Echter Lauf im Probe-Entwurf:**
  - (a) Bild markieren, „Himmel abendrot“ sagen → Auftrag `aendern` → neue Fassung.
  - (b) Foto im Chat anhängen, „bau das ins Titelbild ein“ sagen → Auftrag mit `vorlagen` → neue Fassung.
  - (c) „ändere das Bild“ auf einem leeren Platz → Ablehnung „Hier ist noch kein Bild …“.
  - Zeiten und VRAM notieren.
- [ ] **Claims schließen,** Memory aktualisieren.
