# Bildauswertung live in der Termin-Akte – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wenn Felix in einer Jitsi-Termin-Akte "Bildschirm auswerten" einschaltet, tritt "Laura (Bildschirm)" dem Termin bei, erfasst Standbilder des geteilten Bildschirms bei Bildänderung, beschreibt und bettet sie ein, zeigt sie live in der Akte und speist sie in die Auswertung ein.

**Architecture:** Ein neuer Dienst `sales-auge` (Abbild aus `sales-mcp/` mit Playwright-Chromium und fastembed) leitet seinen Soll-Zustand jede Runde aus der DB ab (Schalter + Bot-Status), tritt per headless Chromium bei, holt nur den Desktop-Track per JS-Canvas, legt JPEGs mit dHash-Änderungserkennung in `termin_bilder` ab und arbeitet eine Warteschlange ab (Beschreibung über das KI-Tor mit eigener Bild-Spur, Embeddings lokal, pgvector). UI und MCP lesen aus der DB und suchen über einen kleinen HTTP-Endpunkt von `sales-auge`. Die gesamte Logik außer Browser und Modellen liegt in testbaren `sales-mcp`-Modulen.

**Tech Stack:** Python 3.12, psycopg 3, Starlette (sales-ui), Playwright (Python, Chromium), fastembed, Pillow, pgvector, Postgres, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-13-bildauswertung-live-design.md`

## Global Constraints

- Nur der geteilte Bildschirm (Jitsi `videoType === 'desktop'`), nie Kamera-Tracks; der Beobachter sendet weder Ton noch Bild.
- Keine Video- oder Rohdatei, auch nicht temporär auf Platte; Bilder nur als JPEG-Bytes in `termin_bilder`.
- Beobachter nur, wenn `bildschirm_auswerten` an UND `plattform = 'jitsi'` UND `status in ('wartet_auf_einlass','laeuft')` UND `abgesagt_am is null` UND `not kein_bot` UND `vexa_meeting_id is not null`.
- Anzeigename exakt `Laura (Bildschirm)`.
- Höchstens ein Standbild alle 5 Sekunden je Termin; Obergrenze 150 Standbilder je Termin, darüber nur bei starker Änderung.
- Keine Bilder, Beschreibungen, Titel, Namen, Links oder Tokens in Logs: nur gekürzte uid (`termin_takt._h`-Muster), Zähler, Fehlerart.
- Kein bezahlter API-Aufruf: Beschreibungen nur über das KI-Tor (`OLLAMA_URL`), Embeddings lokal.
- pgvector-Typ und Operatoren schemaqualifiziert schreiben (`public.vector`, `OPERATOR(public.<=>)`): Die Dienste laufen mit `search_path=<schema>,extensions`.
- `sales-auge` hart begrenzt: `cpus: "1.5"`, `mem_limit: 1536m`.
- Rollout gezielt (nur betroffene Dienste), nie openwa neu erstellen, kein `prune`, kein `--remove-orphans`.
- Commits als Conventional Commits mit Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; Feature-Zweig `feat/bildauswertung-live` ab `origin/feat/stufe-1-fundament` (Spec und Plan liegen auf `docs/bildauswertung-live`, zuerst dorthin mergen).
- Tests im bestehenden Stil: Test-DB `sales_test` über den VM-Testlauf (`~/meeting-test`, Abbild `sales-mcp-meeting:dev`, siehe RUNBOOK), Attrappen statt Browser/KI/Modelle.

## Review Focus

1. Felix schaltet den Schalter mitten im Termin aus → Beobachter muss binnen einer Runde gehen und danach kein Bild mehr ablegen, auch wenn gerade ein Bild in Arbeit ist. (Test in Task 6: `test_abgleich_beendet_wenn_schalter_aus` und `test_ablegen_verweigert_wenn_nicht_mehr_soll`.)
2. Mitschrift wird gelöscht ("Ohne Aufnahme", "verwerfen", Löschantrag), während die Beschreibung eines Bildes läuft → das Ergebnis darf kein gelöschtes Bild wiederbeleben und nichts darf übrig bleiben. (Test in Task 4: `test_beschreibung_fuer_geloeschtes_bild_verpufft`.)
3. Ein Teilnehmer teilt, beendet, ein anderer teilt → Bild des zweiten wird erfasst, `bis` des ersten gesetzt, `geteilt_von` wechselt. (Test in Task 2: `test_wechsel_des_teilenden_setzt_bis`.)
4. KI-Tor ist durch eine lange Auswertung belegt → Bildbeschreibung wartet nicht auf deren Sperre. (Test in Task 3: `test_bild_spur_wartet_nicht_auf_text_sperre`.)
5. Akte ohne Jitsi (Meet/Teams/Zoom) → Schalter nicht einschaltbar, verständlicher Hinweis. (Test in Task 7: `test_schalter_nur_bei_jitsi`.)

---

### Task 1: Schema und Löschwege

**Files:**
- Modify: `db/provision.sql` (Block "Meeting-Mittelpunkt", nach `termin_vorschlaege`)
- Modify: `sales-mcp/termin_akte.py` (`mitschrift_entfernen`)
- Modify: `sales-mcp/server.py` (Sicherheitsnetz bei Zeile ~8904, gleiche Funktion)
- Test: `sales-mcp/tests/test_termin_schema.py`, `sales-mcp/tests/test_termin_akte.py`

**Interfaces:**
- Produces: Spalte `termin_akten.bildschirm_auswerten boolean not null default false`; Tabelle `termin_bilder`:
  `id uuid pk default gen_random_uuid()`, `uid text not null references termin_akten(uid) on delete cascade`, `aufgenommen_am timestamptz not null`, `bis timestamptz null`, `geteilt_von text null`, `bild bytea not null`, `breite int not null`, `hoehe int not null`, `dhash bigint not null`, `beschreibung text null`, `beschreibung_status text not null default 'offen' check in ('offen','fertig','fehler')`, `beschreibung_versuche int not null default 0`, `vektor_bild public.vector(512) null`, `vektor_text public.vector(384) null`, `erstellt_am timestamptz not null default now()`; Index `(uid, aufgenommen_am)`. Grants wie die anderen `termin_*`-Tabellen (sales_app bzw. `sales_app_<laden>`).
- Produces: `termin_akte.bilder_entfernen(uid: str) -> int` (Anzahl gelöschter Bilder); `mitschrift_entfernen` ruft sie auf.

- [ ] **Step 1: Failing tests**
  - `test_termin_schema.py`: Spaltenmenge von `termin_bilder` exakt wie oben; `termin_akten` enthält `bildschirm_auswerten`; Löschen der Akte löscht ihre Bilder (Kaskade).
  - `test_termin_akte.py::test_mitschrift_entfernen_loescht_bilder` (Bilder ohne Mitschrift werden mit entfernt, Bilder anderer Akten bleiben) und `test_aufnahme_beenden_loescht_bilder`.
  - `test_termin_akte.py::test_loeschantrag_sicherheitsnetz_loescht_bilder` (Weg über `server`-Funktion um Zeile 8904).
- [ ] **Step 2:** Tests laufen lassen → FAIL (Tabelle fehlt).
- [ ] **Step 3:** DDL idempotent (`create table if not exists`, `alter table … add column if not exists`), Grants, `bilder_entfernen`, Aufruf in `mitschrift_entfernen` und Sicherheitsnetz (`delete from termin_bilder where uid in (…dieselbe Teilnahme-Bedingung…)`).
- [ ] **Step 4:** `provision.sql` gegen Test-DB einspielen, Tests → PASS; komplette `test_termin_*` grün.
- [ ] **Step 5: Commit** `feat(termine): termin_bilder und Schalter bildschirm_auswerten`

### Task 2: Modul `bildschirm` – Erfassen, Ablegen, Lesen

**Files:**
- Create: `sales-mcp/bildschirm.py`
- Modify: `sales-mcp/requirements.txt` (`Pillow>=10`, falls nicht schon direkt gelistet)
- Test: `sales-mcp/tests/test_bildschirm.py`

**Interfaces:**
- Produces (Konstanten): `MIN_ABSTAND = timedelta(seconds=5)`, `SCHWELLE = 10`, `SCHWELLE_STARK = 24`, `OBERGRENZE = 150`, `MAX_BREITE = 1600`.
- Produces:
  - `dhash(jpeg: bytes) -> int` (64-bit Differenz-Hash, 9×8 Graustufen, als signiertes int64 speicherbar)
  - `abstand(a: int, b: int) -> int` (Hamming)
  - `soll_aufnehmen(letzter: int | None, neu: int, letzte_zeit: datetime | None, jetzt: datetime, anzahl: int) -> bool`
  - `beobachtung_soll() -> list[dict]` (`uid`, `link`; Bedingung exakt aus Global Constraints)
  - `ist_soll(uid: str) -> bool`
  - `bild_ablegen(uid: str, jpeg: bytes, zeitpunkt: datetime, geteilt_von: str | None) -> str | None` – verkleinert auf `MAX_BREITE`, setzt `bis` des vorigen offenen Bildes derselben Akte auf `zeitpunkt`; gibt `None` zurück und legt nichts ab, wenn `ist_soll(uid)` falsch ist (atomar in einer Transaktion mit `select … for update` auf die Akte).
  - `freigabe_ende(uid: str, zeitpunkt: datetime) -> None` – setzt `bis` des letzten offenen Bildes.
  - `bilder(uid: str) -> list[dict]` (alle Spalten außer `bild` und Vektoren, nach `aufgenommen_am`)
  - `bild_daten(uid: str, bild_id: str) -> bytes | None`
  - `bild_loeschen(uid: str, bild_id: str) -> bool`

- [ ] **Step 1: Failing tests** (Bilder mit Pillow im Test erzeugen):
  - `test_dhash_gleich_bei_gleichem_bild`, `test_dhash_weit_bei_anderem_bild` (`abstand > SCHWELLE`)
  - `test_soll_aufnehmen`: erstes Bild → True; < 5 s → False; Abstand ≤ 10 → False; Abstand 11 nach 5 s → True; `anzahl=150` und Abstand 20 → False; Abstand 25 → True
  - `test_beobachtung_soll_filter`: je eine Akte, die an genau einer Bedingung scheitert (Schalter aus, `teams`, `geplant`, abgesagt, `kein_bot`, ohne `vexa_meeting_id`) → nur die vollständige kommt zurück
  - `test_bild_ablegen_verkleinert_und_setzt_bis`
  - `test_wechsel_des_teilenden_setzt_bis` (Review Focus 3)
  - `test_ablegen_verweigert_wenn_nicht_mehr_soll` (Review Focus 1)
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(termine): Bildschirm-Standbilder erfassen und ablegen`

### Task 3: KI-Tor mit Bild-Spur

**Files:**
- Modify: `sales-ki/ki_tor.py`, `sales-mcp/ollama.py`
- Test: `sales-ki/tests/test_ki_tor.py`, `sales-mcp/tests/test_ollama.py`

**Interfaces:**
- Produces (KI-Tor): `POST /api/chat` akzeptiert in Nutzer-Nachrichten optional `images: list[str]` (Base64-JPEG, Ollama-Format). Mit Bildern: `claude_bild_fragen(system: str, nutzer: str, bilder: list[str], *, als_json: bool) -> str` über `claude -p --input-format stream-json --output-format stream-json --verbose` plus dieselben Sperr-Flags wie `claude_fragen`; eine stdin-Zeile `{"type":"user","message":{"role":"user","content":[{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":…}}…,{"type":"text","text":nutzer}]}}`; Antwort = `result` der letzten `{"type":"result"}`-Zeile. Eigene Sperre `_sperre_bild`, Zeitgrenze `KI_BILD_TIMEOUT_S` (Vorgabe 60). Ohne Bilder unverändert.
- Produces (sales-mcp): `ollama.chat(system, nutzer, *, als_json=False, timeout_s=None, bilder: list[bytes] | None = None) -> str` – hängt Base64 an die Nutzer-Nachricht als `images`.

- [ ] **Step 1: Failing tests**
  - `test_chat_mit_bild_nutzt_stream_json` (Attrappe prüft Argumente und dass die stdin-Zeile einen image-Block mit `media_type image/jpeg` enthält; Antwort aus `result`)
  - `test_bild_spur_wartet_nicht_auf_text_sperre` (Review Focus 4: Text-Sperre im Test halten, Bildanfrage kommt trotzdem durch)
  - `test_bild_log_ohne_inhalt` (kein Base64, kein Text im Log)
  - `test_ollama_chat_haengt_bilder_an` (sales-mcp)
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren; `MAX_EINGANG` bleibt 2 MB. **Step 4:** → PASS (ganze `test_ki_tor.py` und `test_ollama.py`).
- [ ] **Step 5: Commit** `feat(ki): Bildeingabe mit eigener Spur im KI-Tor`

### Task 4: Beschreiben, Einbetten, Suchen

**Files:**
- Create: `sales-mcp/bild_arbeit.py`, `sales-mcp/einbetter_fastembed.py`
- Test: `sales-mcp/tests/test_bild_arbeit.py`

**Interfaces:**
- Consumes: `bildschirm.*` (Task 2), `ollama.chat(..., bilder=)` (Task 3).
- Produces:
  - `class Einbetter(Protocol)`: `bild(jpeg: bytes) -> list[float]` (512), `text_clip(text: str) -> list[float]` (512), `text(text: str) -> list[float]` (384).
  - `BILD_PROMPT: str` – deutsch; beschreibt in höchstens 3 Sätzen, was auf dem geteilten Bildschirm zu sehen ist (Programm/Seite, lesbare Überschriften, Kernaussagen, Zahlen); nennt keine Personen anhand ihres Aussehens; erfindet nichts.
  - `MAX_VERSUCHE = 3`
  - `naechste_beschreiben(einbetter: Einbetter) -> bool` – nimmt das älteste Bild mit `beschreibung_status in ('offen','fehler') and beschreibung_versuche < 3` (`for update skip locked`), ruft das KI-Tor (Zeitgrenze 60 s), schreibt Beschreibung, `vektor_bild`, `vektor_text` mit `update … where id = %s returning id`; Fehler → `fehler`, Versuche +1; True, wenn ein Bild bearbeitet wurde.
  - `suchen(einbetter: Einbetter, text: str, uid: str | None = None, limit: int = 10) -> list[dict]` (`id`, `uid`, `aufgenommen_am`, `beschreibung`, `score`); Score = max aus Cosinus-Ähnlichkeit `vektor_bild` zu `text_clip(text)` und `vektor_text` zu `text(text)`.
  - `einbetter_fastembed.FastEmbedEinbetter` mit den Modellen `Qdrant/clip-ViT-B-32-vision`, `Qdrant/clip-ViT-B-32-text`, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (Import von fastembed nur in diesem Modul; ist ein Modellname in der eingesetzten fastembed-Version nicht vorhanden, gleichwertiges mit gleicher Dimension wählen und im Ledger als Ruling festhalten).

- [ ] **Step 1: Failing tests** (Attrappen-Einbetter mit festen Vektoren; `ollama.chat` gepatcht):
  - `test_beschreiben_schreibt_text_und_vektoren`
  - `test_beschreiben_fehler_zaehlt_versuche_bis_drei`
  - `test_beschreibung_fuer_geloeschtes_bild_verpufft` (Review Focus 2: Bild während des Chat-Aufrufs löschen → kein Fehler, nichts angelegt)
  - `test_suchen_findet_per_text_und_bild_vektor`, `test_suchen_auf_uid_begrenzt`
  - `test_kein_inhalt_im_log`
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(termine): Bilder beschreiben, einbetten und durchsuchen`

### Task 5: Bilder in der Auswertung

**Files:**
- Modify: `sales-mcp/auswertung.py` (`_zeilen`, Systemprompt), `sales-mcp/termin_takt.py` (`_auswerten_eine`), `sales-mcp/bildschirm.py`
- Test: `sales-mcp/tests/test_auswertung.py` (oder bestehende Auswertungs-Testdatei), `sales-mcp/tests/test_termin_takt.py`

**Interfaces:**
- Produces: `bildschirm.bilder_zeilen(uid: str) -> list[tuple[datetime, str]]` (nur `fertig` beschriebene Bilder).
- Produces: `auswertung._zeilen(segmente: list[dict], bilder: list[tuple[datetime, str]] | None = None) -> list[str]` – Bildzeilen `[Bild HH:MM] <Beschreibung>` (Europe/Berlin) zeitrichtig vor das erste Segment mit `beginn >= aufgenommen_am`; Segmentnummern bleiben unverändert (Bildzeilen tragen keine Nummer). `auswertung.auswerten(segmente, bilder=None)` reicht durch.
- Produces: `bildschirm.bilder_zu_abschnitt(segmente: list[dict], von: int, bis: int, bilder: list[dict]) -> list[str]` (Bild-ids, deren `aufgenommen_am` im Zeitraum von Segment `von` bis Ende Segment `bis` liegt).
- Systemprompt-Zusatz (wörtlich): „Zeilen der Form [Bild HH:MM] beschreiben, was zu diesem Zeitpunkt auf einem geteilten Bildschirm zu sehen war. Beziehe sie in Verlauf und Kurzfassung ein, wenn auf Gezeigtes Bezug genommen wird."

- [ ] **Step 1: Failing tests:** `test_zeilen_ohne_bilder_unveraendert`, `test_bildzeile_vor_passendem_segment`, `test_bildzeilen_ohne_nummer`, `test_bilder_zu_abschnitt`, `test_auswerten_eine_reicht_bilder_durch` (termin_takt).
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren. **Step 4:** → PASS (ganze `test_termin_takt.py`, Auswertungstests).
- [ ] **Step 5: Commit** `feat(termine): Bildbeschreibungen fliessen in die Auswertung`

### Task 6: Beobachter-Dienst `sales-auge`

**Files:**
- Create: `sales-mcp/auge.py` (Hauptschleife, HTTP), `sales-mcp/auge_jitsi.js` (Seiten-Skript), `sales-mcp/Dockerfile.auge`
- Modify: `docker-compose.yml`, `.env.example`
- Test: `sales-mcp/tests/test_auge.py`, `deploy/tests/test_auge_compose.sh` (Muster `test_vexa_compose.sh`)

**Interfaces:**
- Consumes: `bildschirm.beobachtung_soll/ist_soll/bild_ablegen/freigabe_ende/dhash/soll_aufnehmen` (Task 2), `bild_arbeit.naechste_beschreiben/suchen`, `FastEmbedEinbetter` (Task 4).
- Produces:
  - `auge.abgleich(soll: set[str], laufend: set[str]) -> tuple[set[str], set[str]]` (zu starten, zu beenden)
  - `auge.beitritts_url(link: str) -> str` – hängt an den Jitsi-Link: `#config.startWithAudioMuted=true&config.startWithVideoMuted=true&config.prejoinConfig.enabled=false&userInfo.displayName=%22Laura%20(Bildschirm)%22` (vorhandenes Fragment ersetzt, Query bleibt)
  - `auge.runde(sitzungen, jetzt) -> None` – je Sitzung: `window.__lauraBild()` → `{teilt: bool, von: str|null, jpeg: base64|null}`; bei `teilt` und `soll_aufnehmen` → `bild_ablegen`; Übergang teilt→nicht teilt → `freigabe_ende`.
  - `auge_jitsi.js` definiert `window.__lauraBild()`: sucht im Jitsi-Store (`APP.store.getState()['features/base/tracks']`) den entfernten Video-Track mit `videoType === 'desktop'`, zeichnet ihn in ein Canvas (max. 1600 px breit) und liefert JPEG (Qualität 0.8) plus Anzeigenamen des Teilenden; begrenzt den Empfang auf Bildschirm-Tracks (Receiver-Constraints / lastN); fasst nie Kamera-Tracks an.
  - HTTP `GET /gesund`, `POST /suche` (`{"text", "uid"?, "limit"?}` → Liste aus `bild_arbeit.suchen`), Port `AUGE_PORT` (Vorgabe 8790), nur im Compose-Netz.
  - Compose-Dienst `sales-auge`: `build: {context: ./sales-mcp, dockerfile: Dockerfile.auge}`, `container_name: ${LADEN_PRAEFIX:-sales}-auge`, `command: python auge.py`, `<<: *sales_mcp_umgebung`, `OLLAMA_URL`, `AUGE_PORT`, `AUGE_RUNDE_S` (Vorgabe 2), `KI_BILD_TIMEOUT_S`; `cpus: "1.5"`, `mem_limit: 1536m`, `restart: unless-stopped`, kein Port nach außen. `AUGE_URL: http://${LADEN_PRAEFIX:-sales}-auge:8790` an `sales-ui` und `sales-mcp`.
  - `Dockerfile.auge`: wie `Dockerfile` plus `playwright` (fest gepinnte Version) mit `playwright install --with-deps chromium`, `fastembed`; Modelle beim Bauen vorladen. Chromium-Flags: `--mute-audio`, `--use-fake-ui-for-media-stream`, `--use-fake-device-for-media-stream`.
  - Soll-Abgleich jede Runde (Vorgabe 2 s); Beschreib-Arbeit in eigenem Thread, ein Bild nach dem anderen.

- [ ] **Step 1: Failing tests:** `test_abgleich_startet_und_beendet`, `test_abgleich_beendet_wenn_schalter_aus` (Review Focus 1, über `beobachtung_soll` gegen Test-DB), `test_beitritts_url` (mit/ohne vorhandenes Fragment, Query bleibt), `test_runde_legt_bei_aenderung_ab` und `test_runde_freigabe_ende` (Seiten-Attrappe mit `evaluate`), `test_suche_endpunkt` (Einbetter-Attrappe); Compose-Test: Dienst existiert, Grenzen gesetzt, keine `ports:`, `AUGE_URL` bei sales-ui/sales-mcp.
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren. **Step 4:** → PASS; `docker compose config` fehlerfrei.
- [ ] **Step 5: Probe auf der VM (ohne Felix):** Abbild bauen; mit zwei Playwright-Seiten in einem Wegwerf-Raum auf `meet.ffmuc.net` (eine teilt per Fake-Bildschirm `getDisplayMedia` mit `--auto-select-desktop-capture-source`/Fake-Stream, eine Kamera an) prüfen, dass `__lauraBild()` nur den Desktop-Track liefert. Ergebnis im Ledger.
- [ ] **Step 6: Commit** `feat(termine): Beobachter Laura (Bildschirm) als Dienst sales-auge`

### Task 7: Akte – Schalter, Live-Reiter, Suche, MCP-Werkzeug

**Files:**
- Modify: `sales-mcp/ui_termin.py`, `sales-mcp/termin_akte.py` (`lesen` liefert `bildschirm_auswerten`, `bilder_anzahl`), `sales-mcp/server.py` (Werkzeug)
- Create: `sales-mcp/static/termin_bilder/bilder.js`
- Test: `sales-mcp/tests/test_ui_termin.py`, `sales-mcp/tests/test_termin_akte_mcp.py`

**Interfaces:**
- Consumes: `bildschirm.bilder/bild_daten/bild_loeschen/bilder_zu_abschnitt`, `AUGE_URL /suche`.
- Produces:
  - Aktion `bildschirm` (POST, CSRF): schaltet `bildschirm_auswerten` um, nur bei `plattform = 'jitsi'` und Status `geplant|kein_link|wartet_auf_einlass|laeuft`; sonst Meldung `bildschirm_nur_jitsi` („Bildschirm auswerten geht in Stufe 1 nur bei Jitsi-Terminen.") bzw. `bildschirm_gesperrt`. Knopf „Bildschirm auswerten: an/aus" in `_schalter`.
  - Aktion `bild_loeschen` (Formfeld `bild_id`).
  - Reiter `bildschirm` in `_REITER`, sichtbar wenn Schalter an oder Bilder vorhanden: Raster aus Vorschaubild, Uhrzeit (Europe/Berlin), `geteilt_von`, Beschreibung bzw. „wird beschrieben …"; Suchfeld.
  - `GET /termine/{uid}/bilder.json[?q=…]` → `{"bilder": [...], "live": bool}`; mit `q` die Treffer aus `AUGE_URL/suche` (begrenzt auf uid); `live` = Status in `wartet_auf_einlass|laeuft`.
  - `GET /termine/{uid}/bild/{bild_id}.jpg` → `image/jpeg`, `Cache-Control: private, max-age=3600`.
  - Beide Routen stehen in `routen()` VOR den `{kennung:path}`-Routen; Schutz wie die Seite (`_gesichert_seite` / `_gesichert_json`), Rollen `lesen`/`kalender` dürfen sehen, nicht schalten oder löschen.
  - `bilder.js`: holt `bilder.json` alle 3 s, solange `live`, danach einmalig; fügt nur neue Karten an; Suchfeld fragt `?q=` an.
  - Im Mitschrift-Reiter je Verlaufseintrag kleine Vorschaubilder über `bilder_zu_abschnitt`.
  - MCP-Werkzeug `termin_bilder_suchen(text: str, uid: str = "", limit: int = 10) -> str` (JSON-Liste ohne Bildbytes) in `WERKZEUGE`.
- [ ] **Step 1: Failing tests:** `test_schalter_nur_bei_jitsi` (Review Focus 5), `test_schalter_schaltet_um`, `test_schalter_csrf_und_rolle_lesen`, `test_reiter_bildschirm_zeigt_bilder`, `test_bilder_json_live`, `test_bild_jpg_fremde_uid_404`, `test_bild_loeschen`, `test_bilder_json_suche_ruft_auge` (HTTP-Attrappe), `test_route_reihenfolge_vor_kennung_path`, `test_verlauf_zeigt_vorschaubilder`, `test_mcp_termin_bilder_suchen`; alles Fremde html-escaped.
- [ ] **Step 2:** → FAIL. **Step 3:** implementieren. **Step 4:** → PASS (ganze `test_ui_termin.py`, `test_termin_akte*.py`).
- [ ] **Step 5: Commit** `feat(ui): Bildschirm-Reiter live in der Termin-Akte`

### Task 8: Doku, Rollout, Abnahme

**Files:**
- Modify: `docs/03_RUNBOOK.md` (Abschnitt Bildauswertung: Dienst, Grenzen, Not-Aus = `docker stop sales-auge`, Smoke), `docs/06_DSGVO.md` (Standbilder geteilter Bildschirme, nur intern per Schalter, keine Kameras, Löschung mit Mitschrift, Beschreibung über Anthropic), `deploy/smoke.sh` (sales-auge `/gesund`, nur wenn der Dienst läuft)

- [ ] **Step 1:** Doku und Smoke ergänzen; Commit `docs: Bildauswertung im Runbook und DSGVO`.
- [ ] **Step 2:** PR gegen `feat/stufe-1-fundament`, CI grün, Merge erst nach Review.
- [ ] **Step 3 (VM, Claim in `00_Meta/002_Koordination_Live.md` zuerst):** `db/provision.sql` gegen `sales` einspielen (Runbook-Weg); ff-merge; `docker compose build sales-ki sales-termine sales-auge`; `docker compose up -d --no-deps sales-ki sales-termine sales-mcp sales-ui sales-auge`; `deploy/smoke.sh` → „ALLE PRUEFUNGEN GRUEN".
- [ ] **Step 4:** Abnahme mit Felix nach Spec §Abnahme 1–7; Ergebnisse als Tabelle ins Runbook.
