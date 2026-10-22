# Reels Stufe 2 – Formate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reels gibt es künftig in drei Formaten: Hochformat 9:16 (Social), Quadrat 1:1 (LinkedIn) und Querformat 16:9 (Website/Präsentation). Ausgewählt wird beim Bestellen, und „Nochmal“ übernimmt das Format.

**Architecture:** Laura hat einen neuen Parameter `format` (`reel` | `quadrat` | `quer`) an `render-reel`, `stills` (Standbild) und `titelkarte`. Die Größen liegen in einer einzigen Tabelle. Bei `reel` bleibt jeder Aufruf und jeder Rezept-Hash byte-gleich. Marketing reicht `briefing.format` durch (kein DDL nötig, `briefing` ist jsonb). Die Werkzeuge des Video-Claws geben das Format an jeden Baustein weiter. Die Seite in sales-claw bietet die Auswahl an und zeigt Karte und Video im passenden Seitenverhältnis.

**Tech Stack:** Laura (Python, FastAPI, ffmpeg, uv), Marketing (FastAPI), sales-ui (Starlette), pytest.

**Spec:** Freigabe des Betreibers vom 20.10.2026 (Stufe 2 von 3). R1 nennt die Zwecke LinkedIn, Insta/TikTok/Shorts und Website/Präsentation, siehe Plan `2026-10-21-reels-stufe1.md`. Die Vermessung mit Datei und Zeile steht in `C:/Users/User/AppData/Local/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/formate-survey.md`. Für Laura ist dort `origin/main` = `b08e402` maßgeblich.

## Entscheidungen (E1–E9)

- **E1 – Namen und Größen.** Die Tabelle steht genau einmal in Laura: `FORMATE = {"reel": (1080, 1920), "quadrat": (1080, 1080), "quer": (1920, 1080)}` (neues Modul `laura/render/formate.py`). Fehlt `format`, gilt `reel`.
- **E2 – Laura `render-reel`.** `ReelRenderRequest.format: Literal["reel","quadrat","quer"] | None = None`.
  - Die Option `options["format"]` wird **nur** gesetzt, wenn `format` nicht leer und nicht `reel` ist. So bleibt der Rezept-Hash für heutige Reels gleich (Muster `rahmung`/`logo` in `api/reels.py:61-84`).
  - `handle_render` übergibt `out_size=FORMATE[f]` nur, wenn `f != "reel"`. Sonst bleibt der Aufruf byte-gleich.
  - Die Untertitel-Leinwand (`play_w`/`play_h`) kommt aus der Formatgröße.
  - Schriftgröße/Rand der Untertitel als Vorgabe je Format: `reel` 72/250, `quadrat` 64/100, `quer` 54/48. Die Vorgabe greift nur, wenn der Aufrufer `caption_fontsize`/`caption_safe_margin` **nicht** ausdrücklich gesetzt hat (`body.model_fields_set`).
  - Logo-Breite und Hook-Text richten sich nach `min(w, h)` bzw. nach der Breite statt nach festen 1080.
- **E3 – Laura Bausteine.** `StandbildRequest.format` und `TitelkarteRequest.format` (gleicher Literal). Die Handler nehmen `FORMATE[format]` statt `BREITE, HOEHE = 1080, 1920`, die Vorgabe bleibt `reel` und damit unverändert. Der Textumbruch der Titelkarte richtet sich nach der Breite: `umbrechen` mit zur Breite passender Zeilenlänge. Die API prüft weiterhin (422 bei Überlänge).
- **E4 – Gemischte Größen verboten.** Alle Bausteine eines Reels müssen im Format des Reels entstehen. Sonst bläht `_mixed_size_normalize` (`mp4.py:41-77`) die Leinwand auf das Maximum aus Breite und Höhe auf. Der Claw-Prompt verlangt das ausdrücklich. In Laura gibt es dazu einen Test, der zeigt, dass bei einheitlicher Größe die Ausgabe exakt der Formatgröße entspricht.
- **E5 – Material-Reels.** Die `rahmung` (`zuschnitt` nimmt die Mitte, `einpassen` legt eine unscharfe Fläche dahinter) gilt unverändert, nur gegen die Zielgröße. Ist das Querformat-Material eine Bildschirmaufnahme und das Ziel `quer`, bleibt es ohne Zuschnitt. Das prüft ein Test.
- **E6 – Marketing.**
  - `briefing_pruefen` nimmt `format` an (`reel`|`quadrat`|`quer`, sonst 422 „format: reel, quadrat oder quer“) und speichert es nur, wenn es nicht `reel` ist.
  - Die Werkzeuge `standbild`, `titelkarte` und `reel_bauen` im Video-Claw bekommen einen Parameter `format: str = "reel"`. Sie prüfen ihn wie `rahmung` und schicken `"format"` an Laura nur, wenn er nicht `reel` ist.
  - Der Agenten-Weg `reel_beauftragen` (`claw/werkzeuge.py:453`) bekommt ebenfalls `format`.
  - Texte: In `AGENTS.md` und den drei Skills wird „Hochformat“ zu „im Format aus dem Briefing“. Dazu kommt die Regel aus E4: „Gib JEDEM titelkarte-, standbild- und reel_bauen-Aufruf dasselbe format aus dem Briefing.“
  - Das Vorschaubild (`scale=540:-2`) bleibt, es hält das Seitenverhältnis.
  - Die Grenze von 15 MB bleibt: 1920x1080 hat dieselbe Pixelzahl wie heute.
- **E7 – Seite.**
  - Bestellschritt 3 bietet drei Karten als Radioknöpfe an: „Hochformat 9:16 – Instagram, TikTok, Shorts“ (Vorgabe), „Quadrat 1:1 – LinkedIn“, „Querformat 16:9 – Website, Präsentation“.
  - Galerie-Karte und Detail-Video bekommen je nach `briefing.format` die Klasse `f-quadrat` bzw. `f-quer` mit `aspect-ratio: 1 / 1` bzw. `16 / 9`. Die Detailseite zeigt „Format: …“.
  - Pfade und Klassen enthalten keine verbotenen Stämme.
- **E8 – Reihenfolge der Auslieferung.**
  1. Laura auf der VM, mit Rückweg-Tag `deploy-api:vor-formate`. Ein altes Laura würde `format` stillschweigend ignorieren und 9:16 liefern.
  2. Marketing (PC-Claw und -Werkzeuge, VM-API über `update.sh`).
  3. sales-claw.

  Nach dem Rendern werden die Abmessungen per `ffprobe` geprüft.
- **E9 – Laura-Repo.**
  - Gearbeitet wird in einem eigenen Worktree von `origin/main` im Submodul `vibemind-os/spaces/video/laura` auf einem Zweig `claude/reels-formate`. Danach Fast-Forward nach `main` und Push nach `origin` (`Vibemind-LAB`). Der Push braucht einen kommando-lokalen Credential-Helper, siehe Memory `project_laura_suite_and_branches`.
  - Tests laufen mit `PYTHONPATH=src uv run pytest -q <dateien>` aus `services/local-api` im Worktree.

## Global Constraints

- **Repos:**
  - **Laura:** Worktree nach E9. Niemals den Haupt-Checkout des Submoduls umschalten.
  - **MOS** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent` (master). Fremde schmutzige Dateien dort (openfang, spaces/plugin-setup/deploy/bootstrap.sh, spaces/sales-claw, spaces/shuttles/swe_desgine, voice, untracked docs/spaces/, claw/schaufenster/*, claw/agent_prompt_addition.txt) werden nie gestaged.
  - **SC** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw` (feat/stufe-1-fundament). `.superpowers/` wird nie gestaged.
- **Git:** Git läuft über PowerShell. Vor jedem Commit `git status` und `git pull --no-rebase`. Nur eigene Dateien stagen. Nicht pushen, außer in Task 5. Commits als Conventional Commits mit der Schlusszeile `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Dateien nicht von LF auf CRLF umschreiben.
- **Tests:**
  - **Laura:** die betroffenen Test-Dateien laut Vermessung, Abschnitt E.
  - **MOS:** `python -m pytest spaces/marketing -q --basetemp C:/Temp/pt-fmt`. Erlaubt sind nur die 17 bekannten Fehler (3× `SALES_CLAW_DIR`, `cockpit_contract`, `tools/tests`, `test_bilder_api`).
  - **SC:** DB-Klon `sales_struktur` auf `127.0.0.1:55600`. Erlaubt sind nur die Basis-Fehlschläge.
- **sales-ui:** Kein JavaScript. Farben nur über Variablen. Touch-Ziele mindestens 44 px. Fremdwerte gehen durch `ui._e`. Echte Umlaute. Die Darstellungs-Wache (`test_darstellung`) muss grün bleiben.
- **Live und Freigabe:** Kein Deploy ohne Betreiber-OK, das ist Task 5. Vor Video-Läufen den freien Speicher prüfen (Memory: Auslagerung/RAM).

## Review Focus

1. **Heutige Reels unverändert.** Ein Reel ohne `format` erzeugt in Laura exakt dieselben Optionen, denselben Rezept-Hash und denselben `render_clips_mp4`-Aufruf wie vorher. Tests: `test_ohne_format_bleibt_hash_und_aufruf_gleich` (T1) und `test_briefing_ohne_format_bleibt_ohne_format` (T2).
2. **Abmessungen stimmen wirklich.** Ein echter ffmpeg-Lauf in Laura liefert für `quadrat` 1080x1080 und für `quer` 1920x1080. Das gilt auch für Standbild und Titelkarte. Test: `test_echte_ausgabe_hat_formatgroesse` (T1, überspringt nur ohne ffmpeg).
3. **Gemischte Formate.** Fehlt einem Werkzeugaufruf im Claw das Format, obwohl das Briefing eines setzt, fällt das auf. Die Werkzeuge nehmen dann das Format des Auftrags aus dem Briefing über `/arbeiter/{aid}/marke` oder aus einem neuen Feld, nicht stillschweigend `reel`. Test: `test_werkzeuge_nehmen_format_des_auftrags` (T2).
4. **„Nochmal“ behält das Format.** `video_nochmal` kopiert das Briefing, also gehört `format` dazu. Test: in `verify_085` ist nichts zu tun; ein API-Test `test_nochmal_behaelt_format` (T2).
5. **Fremde oder kaputte Werte.** `format="9:16"` oder `"<x>"` führt auf allen Ebenen zu 422 bzw. zum Fehler. Die Seite escaped den Wert, und ein unbekannter Wert aus der DB ergibt im Raster die Vorgabeklasse. Tests: `test_format_ungueltig_422` (T1/T2) und `test_karte_unbekanntes_format_faellt_auf_hochformat` (T3).

---

### Task 1: Laura – Format für render-reel, Standbild und Titelkarte

**Files** (Laura `services/local-api/src/laura/…`):
- Neu: `render/formate.py`.
- Ändern: `api/models.py` (ReelRenderRequest), `api/reels.py`, `render/handlers.py` (handle_render, Untertitel-Leinwand, Vorgaben), `render/reel.py` und `render/logo.py` (Breite statt 1080), `api/bausteine.py`, `bausteine/handlers.py` und `bausteine/filter.py` (Textumbruch).
- Tests: `test_reel_render_api.py`, `test_reel_filters.py`, `test_bausteine.py`, `test_captions_ass.py`, neu `test_formate.py`.

**Interfaces:**
- **Produces:** `FORMATE: dict[str, tuple[int, int]]` und `groesse(format: str | None) -> tuple[int, int]` in `laura.render.formate`.
- **HTTP:** `POST /timelines/{id}/render-reel`, `POST /projects/{id}/stills` und `POST /projects/{id}/titelkarte` nehmen jeweils `format`.

- [ ] **Step 0:** Worktree nach E9 anlegen, `uv sync`, Basis-Lauf der betroffenen Tests (muss grün sein, Ergebnis notieren).
- [ ] **Step 1: Failing Tests schreiben.**
  - `test_ohne_format_bleibt_hash_und_aufruf_gleich`: Options-Dict, Rezept-Hash und die `render_clips_mp4`-Argumente ohne `format` sind gleich wie mit `format="reel"` und gleich wie vor der Änderung (fester erwarteter Hash aus dem Basis-Lauf).
  - `test_render_reel_quadrat_und_quer_out_size`.
  - `test_untertitel_vorgaben_je_format`: 64/100 für quadrat, 54/48 für quer, und explizite Werte gewinnen.
  - `test_standbild_und_titelkarte_in_formatgroesse`: Filtergraph enthält 1080x1080 bzw. 1920x1080.
  - `test_titelkarte_umbruch_quer_breiter`.
  - `test_format_ungueltig_422`: alle drei Routen.
  - `test_echte_ausgabe_hat_formatgroesse`: kurzer echter Lauf, `ffprobe` liefert die Abmessungen, `skipif` ohne ffmpeg.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Umsetzen nach E1–E5.
- [ ] **Step 4:** Der fokussierte Laura-Testsatz (Vermessung, Abschnitt E) muss grün sein.
- [ ] **Step 5: Commit** auf `claude/reels-formate`: `feat(reels): Format quadrat und quer fuer render-reel, Standbild und Titelkarte`.

### Task 2: Marketing – Format im Briefing, in den Werkzeugen und im Prompt

**Files** (MOS `spaces/marketing/…`):
- Ändern: `api/video.py` (`briefing_pruefen`), `video_claw/werkzeuge.py` (`standbild`, `titelkarte`, `reel_bauen`), `claw/werkzeuge.py` (`reel_beauftragen`), `video_claw/AGENTS.md`, `video_claw/skills/{reel-aus-bildern,reel-aus-material,kurzfassung}/SKILL.md`.
- Tests: `tests/test_video_api.py`, `video_claw/tests/test_werkzeuge.py`, `claw/tests/` (zu `reel_beauftragen`).

**Interfaces:**
- **Consumes:** die Laura-Felder aus T1.
- **Produces:** `briefing.format` (nur gesetzt, wenn nicht `reel`); die Werkzeugparameter `format`.

- [ ] **Step 1: Failing Tests schreiben.**
  - `test_briefing_format_wird_geprueft`: quadrat und quer werden gespeichert, reel und fehlend ergeben kein Feld, Unsinn ergibt 422.
  - `test_briefing_ohne_format_bleibt_ohne_format`.
  - `test_nochmal_behaelt_format`: Die Liste zeigt das Format des Vorgängers. Der API-Test prüft den SQL-Aufruf, das Kopieren selbst macht die DB.
  - `test_reel_bauen_schickt_format_nur_wenn_nicht_reel`.
  - `test_standbild_titelkarte_schicken_format`.
  - `test_werkzeuge_nehmen_format_des_auftrags` (Review Focus 3): Werkzeuge mit `auftrag` (`titelkarte`, `reel_bauen`) holen das Format aus dem Auftrag, wenn kein Parameter gesetzt ist. `standbild` hat keinen `auftrag`, deshalb verlangt der Prompt das Format. Die Prüfung macht `reel_bauen`: Haben die Bausteine eine andere Größe, bricht es mit einem klaren Fehler ab. Die Größen kommen aus Lauras Asset-Abmessungen, sonst weglassen und im Report begründen.
  - `test_reel_beauftragen_format`.
  - `test_prompt_nennt_format_regel`: `AGENTS.md` enthält die Regel aus E4, und kein Skill sagt mehr „Hochformat“ als feste Größe.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Umsetzen nach E6.
- [ ] **Step 4:** Die Marketing-Vollsuite darf nur die 17 bekannten Fehler haben.
- [ ] **Step 5: Commit.** `feat(reels): Format im Briefing, in den Claw-Werkzeugen und im Prompt`

### Task 3: sales-claw – Formatauswahl, Karten und Video im passenden Seitenverhältnis

**Files:** `sales-mcp/ui_reels.py` (Schritt 3, `karte`, `detail_html`), `sales-mcp/ui.py` (CSS `.f-quadrat` und `.f-quer`); Tests `tests/test_reels.py`, `tests/test_darstellung.py`.

- [ ] **Step 1: Failing Tests schreiben.**
  - `test_schritt3_drei_formate_hochformat_vorgabe`.
  - `test_bestellen_schickt_format_nur_wenn_nicht_hochformat`.
  - `test_karte_und_detail_klasse_je_format`.
  - `test_karte_unbekanntes_format_faellt_auf_hochformat`.
  - `test_detail_zeigt_format`.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Umsetzen nach E7.
- [ ] **Step 4:** `test_reels.py` und `test_darstellung.py` müssen grün sein, die Vollsuite darf nur die Basis-Fehlschläge haben. Dazu Bildschirmfotos (Galerie mit allen drei Formaten, Detail quer, Schritt 3) bei 1440 hell und 390.
- [ ] **Step 5: Commit.** `feat(reels): Formatauswahl und Karten in 1:1 und 16:9`

### Task 4: Gesamtprüfung (Controller)

Eine abschließende Prüfung über alle Repos. Der Schwerpunkt liegt auf dem Weg von der Seite über die API, den Claw und die Werkzeuge bis zu Laura, auf Review Focus 1–5 und auf der Reihenfolge der Auslieferung.

### Task 5: Ausliefern (nur nach Betreiber-OK)

- [ ] **Step 1: Laura.**
  1. `claude/reels-formate` per Fast-Forward nach `main` bringen und nach `origin` pushen.
  2. Auf der VM vorher sichern: `docker tag deploy-api:latest deploy-api:vor-formate` und `cp -a ~/laura/services/local-api ~/laura/local-api.vor-formate`.
  3. Quellen per `git archive` nach `~/laura/services`.
  4. `docker compose build api` und `up --no-deps --no-build -d api`.
  5. Health-Check.
- [ ] **Step 2: Marketing.**
  1. Pushen.
  2. Den PC-Haupt-Checkout einordnen (alt, neu oder FREMD) und die Dateien nachziehen.
  3. `marketing_video_werkzeuge`, `marketing_video_claw` und `marketing_claw_mcp` neu starten.
- [ ] **Step 3:** sales-claw pushen und `update.sh` laufen lassen. Das zieht die VM-API mit.
- [ ] **Step 4: Echter Lauf.** Vorher den Speicher prüfen. Bestellt werden je ein Reel aus 3 Bildern in `quadrat` und in `quer`. Danach per `ffprobe` die Abmessungen 1080x1080 und 1920x1080 prüfen, und auf Galerie und Detail das richtige Seitenverhältnis. Zusätzlich ein „Nochmal“ an einem davon: Das Format bleibt.
- [ ] **Step 5:** WORKBOARD schließen. Die Memory (`project_video_claw_reels`) bekommt einen Runbook-Hinweis zum Laura-Deploy.

## Self-Review (erledigt)

- **Abdeckung:**
  - Formate in Laura → T1.
  - Durchreichen → T2.
  - Auswahl und Darstellung → T3.
  - „Nochmal“ → T2 (DB kopiert ohnehin).
  - Größe und Grenzen → E6, keine Änderung.
  - Reihenfolge der Auslieferung → E8 und T5.
- **Typen:** `format` ist überall ein String aus `{reel, quadrat, quer}`. `reel` wird nie gespeichert oder gesendet, fehlend bedeutet `reel`.
- **Offen:** KI-Bilder (Stufe 3).
