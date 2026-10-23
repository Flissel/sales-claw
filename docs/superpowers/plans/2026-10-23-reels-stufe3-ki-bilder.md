# Reels Stufe 3 – KI-Bilder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Reel lässt sich aus 3–5 eigens erzeugten KI-Bildern bauen. Zuerst entwirft ein KI-Schritt die Bildideen aus Thema und dem Bildstil der Marke. Daraus entstehen die Bilder (FLUX.2) im Format des Reels. Der Betreiber sieht sie, kann einzelne neu erzeugen lassen und gibt dann den Reel-Bau frei. Gebaut wird mit dem vorhandenen Ablauf `reel-aus-bildern`.

**Architecture:**
- **Datenbank:** neue Tabelle `marketing.reel_bilder` (ein Bildplatz je Zeile). Der Newsletter-Bildpfad (`bild_auftraege`, 056→063→080) bleibt unberührt. Ein Video-Auftrag mit KI-Bildern durchläuft vor dem bekannten `offen` drei neue Status: `ideen` → `bilder_laufen` → `bilder_pruefen`.
- **Bild-Arbeiter (PC):** Er übernimmt beide Vorstufen. Zuerst schreibt er die Ideen über einen kurzen Aufruf an die Video-Shim :8118 (Ausweichweg: lokales Ollama). Danach erzeugt er die Bilder einzeln nacheinander über `_bilder`/FLUX.2.
- **Video-Claw:** Er sieht diese Status nie und startet erst bei `offen`. Dann stehen die gewählten Bilder schon in `briefing.bilder`.

**Tech Stack:** PostgreSQL (`marketing`), FastAPI, Bild-Arbeiter mit ComfyUI/FLUX.2, sales-ui (Starlette, ohne JavaScript), pytest.

**Spec:** Antworten des Betreibers vom 23.10.2026:
- Der Claw beschreibt die Bilder aus Thema und Bildstil.
- Die Bilder werden vor dem Reel-Bau geprüft, einzelne lassen sich neu erzeugen.
- Es gibt 3–5 Bilder, die Zahl ist wählbar.
- Freigegeben ist Stufe 3 von 3 (20.10.).

Die Vermessung mit Datei und Zeile steht in `C:/Users/User/AppData/Local/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/ki-bilder-survey.md`. Die Ausführung kopiert sie in den SDD-Arbeitsordner. Grundlage ist Stufe 2 (`briefing.format`).

## Entscheidungen (E1–E10)

- **E1 – Migration `090_reel_bilder.sql`** (+ `verify_090.sql`). Die Nummer bleibt mit Abstand reserviert, frei wäre 087.

  Die Tabelle `marketing.reel_bilder`:
  - `id uuid pk`
  - `video_auftrag uuid not null references marketing.video_auftraege(id) on delete cascade`
  - `nr smallint check 1..5`
  - `idee text check 1..600`
  - `status text check in ('offen','in_arbeit','fertig','fehler','verworfen') default 'offen'`
  - `datei text null check (datei ~ '^ki-[0-9a-f]{8}-[1-5]-[0-9]{1,3}\.jpg$')`
  - `versuch smallint not null default 1`
  - `vergeben_bis timestamptz`, `befund text default ''`
  - `erstellt_am`, `geaendert_am`
  - Unique-Index `(video_auftrag, nr) where status <> 'verworfen'`.

  `video_auftraege.status` bekommt zusätzlich `ideen`, `bilder_laufen` und `bilder_pruefen`. Der Check wird per `drop constraint if exists` + `add` neu gesetzt.

  Die Funktionen sind alle `REVOKE ALL FROM PUBLIC`, die Rechte stehen wie bei den Nachbarn:
  - `video_ideen_naechster(frist) → jsonb|null`: nimmt einen Auftrag mit Status `ideen` unter Sperre und Frist und gibt `{id, mandant, titel, briefing}` zurück.
  - `video_ideen_setzen(id, ideen jsonb) → int`: Die Ideen sind ein Array aus 3–5 Strings, das muss zu `briefing.ki.anzahl` passen. Die Funktion legt die `reel_bilder`-Zeilen an und setzt den Auftrag auf `bilder_laufen`.
  - `reel_bild_naechster(frist) → jsonb|null`: gibt `{id, video_auftrag, nr, idee, versuch, mandant, format, titel}` zurück, ältester Auftrag zuerst. Es gibt eine Versuchsgrenze von 2; danach wird das Bild `fehler`.
  - `reel_bild_fertig(id, datei) → bool`: Sind danach alle aktiven Bilder des Auftrags `fertig` oder `fehler`, wechselt der Auftrag auf `bilder_pruefen`.
  - `reel_bild_fehler(id, befund) → bool`: wirkt gleich wie `fertig`, nur mit Fehler.
  - `reel_bild_neu(id, mandant, idee text default null) → uuid`: Nur möglich, wenn der Auftrag `bilder_pruefen` ist und das Bild zur Firma gehört. Die alte Zeile wird `verworfen`, eine neue Zeile mit gleicher `nr`, `versuch+1` und gleicher oder neuer Idee entsteht, und der Auftrag geht zurück auf `bilder_laufen`.
  - `video_ki_freigeben(id, mandant) → bool`: Nur bei `bilder_pruefen` und mindestens 1 fertigen Bild. Setzt `briefing.bilder` auf die `datei`-Liste der fertigen Bilder in `nr`-Reihenfolge und den Status auf `offen`.
  - `video_abbrechen` (072) nimmt auch die drei neuen Status an.
  - `video_naechster` (085) bleibt unverändert. Er nimmt nur `offen` und abgelaufene `in_arbeit`; ein Test sichert das ab.
- **E2 – Bestellung.** Die Art bleibt `bilder`. `briefing.ki = {"anzahl": 3..5}` macht daraus einen KI-Auftrag.
  - `briefing_pruefen` verlangt dann keine `bilder` (die Liste muss leer sein oder fehlen) und prüft `anzahl`.
  - `_anlegen` legt den Auftrag mit dem Status `ideen` statt `offen` an (SQL-Funktion `video_auftrag_anlegen` mit neuem Parameter `p_status default 'offen'`, nur `offen` oder `ideen` erlaubt).
  - „Nochmal“ (`video_nochmal`) übernimmt das Briefing **mit** `briefing.bilder` (die gewählten Bilder) und baut sofort (`offen`). Für neue KI-Bilder bestellt man ein neues Reel. Das steht so auch auf der Seite.
- **E3 – Ideen.**
  - Der Bild-Arbeiter ruft `video_ideen_naechster` über eine neue Arbeiter-Route `POST /api/video/arbeiter/ideen/naechster` auf (X-Bild-Key).
  - Mit einem Aufruf an die Video-Shim :8118 (Budget `marketing-video`) entwirft er N kurze Bildbeschreibungen. Eingaben sind Thema, Sprechertext, `abschnitte.Bildstil` der Marke aus dem Spiegel und das Format.
  - Die Antwort ist ein JSON-Array mit N Strings, jeweils höchstens 600 Zeichen, ohne Text oder Schrift im Bild.
  - Gelingt der Shim-Aufruf nicht, kommt lokales Ollama `qwen2.5:7b` mit demselben Prompt dran. Scheitert auch das, geht der Auftrag nach 2 Versuchen auf `fehler` mit dem Befund „Bildideen konnten nicht erzeugt werden“.
  - Das Ergebnis geht über `POST /api/video/arbeiter/{aid}/ideen` an die Datenbank.
- **E4 – Bilder.**
  - Größen je Format: `reel` 864×1536, `quadrat` 1024×1024, `quer` 1536×864.
  - Der Prompt besteht aus Idee und Bildstil und wird über `bild_prompt` markengerecht gebaut, wie bei Newsletter-Bildern.
  - Die Erzeugung läuft über den vorhandenen `_bilder`/`_flux2`-Weg mit einem Adapter (`weiter`, `bild`, `fertig`, `zurueck` → die neuen Routen).
  - Der Dateiname lautet `ki-<aid8>-<nr>-<versuch>.jpg`. Er ist bei jeder Neuerzeugung neu, also wird nie etwas überschrieben.
  - Das Bild wird hochgeladen über `POST /api/video/arbeiter/reel-bild/{bid}` (roher JPEG, höchstens 1 MiB), der Firma zugeordnet (`medien_mandant.zuordnen`) und als `reel_bild_fertig` vermerkt.
  - Streng nacheinander: Newsletter-Bilder haben Vorrang, danach kommen die Reel-Bilder.
  - Kein `/interrupt`, kein Neustart und kein Kill von ComfyUI.
- **E5 – Arbeiter-Routen.** Sie liegen in einem neuen Modul `api/reel_bilder.py`, mit X-Bild-Key und der Ausnahme vom globalen Schlüssel wie bei `/api/video/arbeiter/`:
  - `ideen/naechster`, `{aid}/ideen`, `{aid}/ideen-fehler`
  - `reel-bild/naechster`, `reel-bild/{bid}` (Upload), `reel-bild/{bid}/fehler`, `reel-bild/{bid}/weiter` (Frist verlängern)
- **E6 – Pult-Routen** (X-Pult-Key, mit Firmenprüfung):
  - `POST /api/pult/video/{aid}/ki/neu` mit dem Körper `{bild, mandant, idee?}`
  - `POST /api/pult/video/{aid}/ki/freigeben` mit dem Körper `{mandant}`
  - `GET /api/pult/video` liefert je Zeile zusätzlich `ki_bilder: [{id, nr, idee, status, datei, befund}]`, ohne die verworfenen, und nur bei KI-Aufträgen.
  - DB-Fehler werden zu 422 mit der Meldung.
- **E7 – Seite.**
  - **Schritt 1:** eine vierte Karte „Aus KI-Bildern – ich entwerfe 3 bis 5 Bilder im Bildstil deiner Marke“.
  - **Schritt 2 für `ki`:** Anzahl 3/4/5 als Radioknöpfe (Vorgabe 4) und der Hinweis „dauert etwa 2 Minuten je Bild“.
  - **Schritt 3:** wie bisher, mit Format und Stimme.
  - **Detailseite:** Status-Texte „Bildideen werden geschrieben“, „Bilder entstehen (2 von 4)“ und „Bilder prüfen“.
    - Bei `bilder_pruefen` steht ein Raster der Bilder in ihrem Format. Unter jedem Bild stehen die Idee (ausklappbar) und ein Formular „Neu erzeugen“ mit einem optionalen Textfeld „andere Idee“. Darunter ein Knopf „Reel bauen“ (CSRF), der nur erscheint, wenn mindestens 1 Bild fertig ist.
    - Fehlgeschlagene Bilder zeigen den Befund und „Neu erzeugen“.
    - Automatisches Neuladen gibt es nur bei `ideen` und `bilder_laufen`, nie bei `bilder_pruefen`.
  - Die Galerie ordnet `ideen`, `bilder_laufen` und `bilder_pruefen` unter „In Arbeit“ ein, und `bilder_pruefen` bekommt einen eigenen Chip „Bilder prüfen“.
  - Keine verbotenen Stämme. Pfade: `/marketing/reels/{aid}/ki/neu` und `/marketing/reels/{aid}/ki/bauen`.
- **E8 – Agenten-Werkzeug.** `reel_beauftragen` bekommt `ki_anzahl` (0 = aus). Der Agent bestellt damit, die Prüfung bleibt beim Betreiber.
- **E9 – Gleichzeitigkeit.**
  - Ein Bild hat eine Frist von 10 min, verlängert per `weiter`. Der Arbeiter verlängert während der Erzeugung.
  - Der Video-Claw und der Bild-Arbeiter überlappen nicht, weil `video_naechster` diese Status nicht sieht.
  - Speicher: Auch die Reel-Bilder laufen nacheinander. Vor dem echten Lauf in Task 6 wird der Speicher geprüft.
- **E10 – Kein Deploy ohne Betreiber-OK.** Reihenfolge: Migration → Marketing (VM-API + PC-Bild-Arbeiter) → sales-claw.

## Global Constraints

- **Repos:**
  - **MOS** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent` (master). Fremde schmutzige Dateien werden nie gestaged.
  - **SC** = `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw` (feat/stufe-1-fundament). `.superpowers/` wird nie gestaged.
- **Git:**
  - Git über PowerShell. Vor jedem Commit `git status` und `git pull --no-rebase`. Nur eigene Dateien stagen. Nicht pushen, außer in Task 6.
  - Commits als Conventional Commits mit der Schlusszeile `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Dateien nicht von LF auf CRLF umschreiben. Python-Skripte schreiben mit `newline='\n'`.
- **Migration:** idempotent, eine Transaktion. Geprüft wird nur per Rollback-Probe (`$env:SUPABASE_SSH_HOST='offload-vm'; $env:SUPABASE_DB_CONTAINER='debian-supabase-db-1'; python -m spaces.marketing.scripts.migration_probe …`), die mit `verify_090: ok` enden muss. Echt eingespielt wird nur in Task 6.
- **Tests:**
  - **MOS:** `python -m pytest spaces/marketing -q --basetemp C:/Temp/pt-ki`, erlaubt sind nur die 17 bekannten Fehler.
  - **SC:** Python-3.12-venv `…/scratchpad/venv-sales3` mit dem DB-Klon `sales_struktur` auf `127.0.0.1:55600`. Nur die Basis-Fehlschläge sind erlaubt; die Basis wird vorher gemessen.
- **Speicher:** Der Speicher ist knapp, deshalb laufen keine Testläufe parallel. ComfyUI wird nie beendet.
- **sales-ui:** Kein JavaScript. Farben nur über Variablen. Touch-Ziele mindestens 44 px. Fremdwerte gehen durch `ui._e`. Echte Umlaute. Die Darstellungs-Wache (`test_darstellung`) muss grün bleiben.

## Review Focus

1. **Der Video-Claw greift nie zu früh zu.** `video_naechster` liefert keinen Auftrag in `ideen`, `bilder_laufen` oder `bilder_pruefen`. Test in `verify_090` und `test_video_naechster_ignoriert_ki_status`.
2. **Neu erzeugen überschreibt nichts und zählt richtig.** Ein neuer Versuch bekommt einen neuen Dateinamen. Die verworfene Zeile zählt nicht, und der Auftrag wechselt erst wieder auf `bilder_pruefen`, wenn alle aktiven Bilder fertig sind. Tests in `verify_090` (b, c).
3. **Fremde Firma.** `ki/neu` und `ki/freigeben` für einen Auftrag oder ein Bild einer anderen Firma führen zu 404 bzw. 422 (Test in T2 und T4).
4. **Ideen-Ausgabe kaputt.** Gibt die Shim kein Array, die falsche Anzahl, zu lange Texte oder leere Strings zurück, wird repariert oder gekürzt, sonst kommt der Ausweichweg über Ollama und am Ende `fehler`. Es gibt nie halbe Zeilen (Test in T3).
5. **Teilweiser Fehlschlag.** 4 Bilder, 1 davon `fehler`: Prüfen ist möglich, und „Reel bauen“ nimmt nur die 3 fertigen (Test in T1 verify und T4).

---

### Task 1: Migration 090 (MOS)

**Files:** neu `spaces/marketing/db/090_reel_bilder.sql` und `spaces/marketing/db/verify_090.sql`.

- [ ] **Step 0:** Prüfen, dass 090 frei ist (`git fetch`, `git ls-tree`). 072, 085 und die aktuelle Fassung von `video_auftrag_anlegen` lesen.
- [ ] **Step 1:** `verify_090.sql` zuerst schreiben, mit dem Probe-Mandanten `probe_090`. Fälle:
  - (a) Status-Check und Tabelle stimmen, und `video_naechster` übergeht die KI-Status.
  - (b) Ein Durchlauf: anlegen (`ideen`) → `ideen_naechster` → `ideen_setzen` (falsche Anzahl wirft) → 4× `reel_bild_naechster` und `reel_bild_fertig`, wobei eins als `reel_bild_fehler` endet → der Auftrag steht auf `bilder_pruefen`.
  - (c) `reel_bild_neu`: Die alte Zeile wird `verworfen`, die neue hat `versuch` 2, der Auftrag steht auf `bilder_laufen`. Danach wieder fertig → `bilder_pruefen`.
  - (d) `video_ki_freigeben`: `briefing.bilder` enthält genau die fertigen Bilder in `nr`-Reihenfolge, der Status ist `offen`.
  - (e) Falscher Status, fremder Mandant, Datei mit falschem Präfix werfen.
  - (f) `video_abbrechen` funktioniert bei den neuen Status.
- [ ] **Step 2:** Probe nur mit verify. Erwartet: FAIL.
- [ ] **Step 3:** 090 schreiben.
- [ ] **Step 4:** Probe 090 + verify_090 muss `ok` ergeben. Danach die Wiederholung zusammen mit 072, 085 und 090.
- [ ] **Step 5: Commit.** `feat(reels): Migration 090 KI-Bilder fuer Reels`

### Task 2: API – Bestellung, Arbeiter- und Pult-Routen (MOS)

**Files:** `api/video.py` (`briefing_pruefen`, `_anlegen`, `_liste` mit `ki_bilder`), neu `api/reel_bilder.py` (E5, E6), `api/server.py` (Router und Ausnahme vom Schlüssel), `claw/werkzeuge.py` (`reel_beauftragen ki_anzahl`); Tests `tests/test_reel_bilder_api.py` (neu), `tests/test_video_api.py`.

- [ ] **Failing Tests schreiben**, dazu die neuen Routen in die 401-Listen:
  - `test_ki_bestellung_status_ideen`, `test_ki_anzahl_grenzen`
  - `test_ideen_naechster_und_setzen`
  - `test_reel_bild_upload_prueft_jpeg_und_name`
  - `test_ki_neu_und_freigeben_mandant_404`, `test_ki_neu_db_fehler_422`
  - `test_liste_hat_ki_bilder`
  - `test_video_naechster_ignoriert_ki_status` (SQL-String)
  - `test_reel_beauftragen_ki_anzahl`
- [ ] **Umsetzen** nach E2, E5, E6 und E8. **Vollsuite. Commit.** `feat(reels): API fuer KI-Bilder`

### Task 3: Bild-Arbeiter – Ideen und Reel-Bilder (MOS)

**Files:** `workers/bild_worker.py` (Schleife: Newsletter zuerst, dann Ideen, dann Reel-Bilder), neu `claw/reel_ideen.py` (Prompt und Ausgabe prüfen, Shim plus Ollama-Ausweichweg); Tests `tests/test_reel_ideen.py`, `tests/test_bild_worker.py`.

- [ ] **Failing Tests schreiben:**
  - `test_ideen_prompt_hat_thema_bildstil_format`
  - `test_ideen_ausgabe_repariert_oder_verworfen` (Review Focus 4)
  - `test_ideen_ollama_ausweichweg`
  - `test_reel_bild_groesse_je_format`
  - `test_reel_bild_name_mit_versuch`
  - `test_newsletter_vor_reel_bildern`
  - `test_reel_bild_fehler_meldet_befund`
  - `test_kein_interrupt_oder_kill`
- [ ] **Umsetzen** nach E3, E4 und E9. **Vollsuite. Commit.** `feat(reels): Bild-Arbeiter erzeugt Ideen und Reel-Bilder`

### Task 4: Seite – Bestellen mit KI, Bilder prüfen, Neu erzeugen, Reel bauen (SC)

**Files:** `sales-mcp/ui_reels.py`, `sales-mcp/ui.py` (CSS); Tests `tests/test_reels.py`, `tests/test_darstellung.py`.

- [ ] **Failing Tests schreiben:**
  - `test_schritt1_hat_ki_karte`
  - `test_schritt2_ki_anzahl_vorgabe_vier`
  - `test_bestellen_ki_sendet_anzahl_ohne_bilder`
  - `test_detail_status_texte_ki`
  - `test_pruefen_raster_im_format_mit_neu_und_bauen`
  - `test_kein_refresh_bei_bilder_pruefen`
  - `test_neu_erzeugen_post` (CSRF, Firma)
  - `test_reel_bauen_post`
  - `test_bauen_nur_mit_fertigem_bild`
  - `test_galerie_chip_bilder_pruefen`
  - `test_fremdes_bild_404`
- [ ] **Umsetzen** nach E7. Bildschirmfotos bei 1440 und 390 px: Schritt 2 KI, Prüfseite mit 4 Bildern (eins fehlgeschlagen), quer und hoch. **Commit.** `feat(reels): KI-Bilder bestellen und pruefen`

### Task 5: Gesamtprüfung (Controller)

Die ganze Kette über beide Repos: Bestellung → `ideen` → Bild-Arbeiter → `bilder_pruefen` → Seite → Freigabe → `offen` → Video-Claw → Reel. Dazu Review Focus 1–5 und die Reihenfolge der Auslieferung.

### Task 6: Ausliefern (nur nach Betreiber-OK)

- [ ] **Step 1:** Rollback-Probe von 090, dann echt einspielen, dann verify.
- [ ] **Step 2: Marketing.**
  1. Pushen.
  2. Den PC-Haupt-Checkout einordnen (alt, neu oder FREMD) und die Dateien nachziehen.
  3. `marketing_api`, `marketing_bild_arbeiter`, `marketing_claw_mcp` und `marketing_video_claw` neu starten.
- [ ] **Step 3:** sales-claw pushen und `update.sh` laufen lassen (zieht die VM-API mit).
- [ ] **Step 4: Echter Lauf.** Vorher den Speicher prüfen.
  1. Ein KI-Reel mit 4 Bildern im Format `quer` bestellen.
  2. Warten auf `bilder_pruefen`.
  3. Ein Bild neu erzeugen lassen.
  4. „Reel bauen“.
  5. Das fertige Reel mit ffprobe (1920×1080) und an Einzelbildern prüfen.

  Von jedem Schritt gibt es ein Bildschirmfoto.
- [ ] **Step 5:** WORKBOARD schließen, Memory nachtragen.

## Self-Review (erledigt)

- **Abdeckung:**
  - Ideen → E3 und T3.
  - Bilder im Format → E4 und T3.
  - Prüfen und Neu erzeugen → E1, E6, E7 und T1, T2, T4.
  - Freigabe → E1 und T1, T2, T4.
  - Anzahl 3–5 → E2 und T2, T4.
  - Agent → E8.
  - Nochmal → E2.
- **Typen und Namen:**
  - `ki_bilder` in der Liste.
  - `briefing.ki.anzahl`.
  - Status `ideen`, `bilder_laufen`, `bilder_pruefen`.
  - Dateiname `ki-<aid8>-<nr>-<versuch>.jpg`.
- **Offen:** keine.
