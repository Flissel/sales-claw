# Marke per Chat – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Markenprofil je Firma (Aussehen + Stimme) in Rowboat, das der Betreiber auf der Seite „Marke“ per Chat mit Uploads und Webseite formt, mit Vorschau und „Übernehmen“; Vorlagen, Gestaltungs-Agent und Bild-Erzeugung nutzen es.

**Architecture:** Wahrheit ist `~/.rowboat/knowledge/companys/<Firma>/Marke.md` (Kopfteil + Abschnitte) mit `logo.*`; das reine Modul `claw/markenprofil.py` liest/schreibt sie. Marken-Aufträge laufen in einer eigenen Tabelle `marketing.marken_auftraege` und werden vom bestehenden Chat-Arbeiter am PC mit abgearbeitet (eigener Zweig `workers/marken_arbeiter.py`); Vorschläge liegen in `marketing.marken_vorschlaege`. Die VM bekommt das Aussehen als Spiegel ins Standard-Layout der Firma (Vorlagen und Feld-Newsletter lesen weiter dort). sales-ui ersetzt die Layout-Regler durch die Seite „Marke“ (Profil, Chat, Vorschau).

**Tech Stack:** PostgreSQL (plpgsql), FastAPI, Starlette (sales-ui ohne JS), Python (urllib/html.parser für den Webseiten-Leser), React (Editor-Band), vitest.

**Spec:** `docs/superpowers/specs/2026-10-07-marke-per-chat-design.md` (sales-claw)

## Repos und Arbeitsorte

- **MOS** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent` (master), Pfade relativ zu `spaces/marketing/`. Nie im Haupt-Checkout committen; vor jedem Commit `git rev-parse --show-toplevel` + Branch prüfen.
- **SC** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw` (`feat/stufe-1-fundament`); `.superpowers/` nie stagen; `sales-mcp/ui.py` nur eigene Hunks.
- Git über PowerShell; nie stash/push/force/--no-verify. Commit-Trailer genau `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- MOS-Tests (MOS-Wurzel): `$env:SALES_CLAW_DIR="<SC>"; C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest spaces/marketing/<pfad> -q -p no:cacheprovider` (bekannt rot: test_integrations, test_send_paranoid, test_hand_bridge, test_cockpit_contract).
- SC-Tests: Postgres :55432 (`pg_isready -h 127.0.0.1 -p 55432`; Start `pg_ctl -D <scratchpad>\pgdata -o "-p 55432" -w -t 1500 start`, kann 10–20 min dauern; Controller stoppt), `SALES_DB_URL=postgresql://postgres@127.0.0.1:55432/postgres`, `SALES_DB_SCHEMA=sales_test`, venv-sales; Vollauf bekannt rot (compliance_test) – nur fokussierte Dateien zählen. Editor: `npx vitest run`, `npx tsc --noEmit`, `npm run build` in `editor/`, Bundle mitcommitten.
- Migrationen nur per `python -m spaces.marketing.scripts.migration_probe …` (zielt auf die VM-DB, immer ROLLBACK); nie anwenden.
- SQL über `sync/_db`: kein Alias `t`; data-modifying CTEs nicht durch `_schreiben` → Schreiben über DB-Funktionen.
- Echte Rowboat-Ablage (`~/.rowboat`) in Tests nie anfassen (env `ROWBOAT_WISSEN_ORDNER` auf `tmp_path`).

## Global Constraints

- Profil: `companys/<Firma>/Marke.md`; Kopfteil zwischen `---`-Zeilen mit `akzent`, `zweitfarbe`, `grund`, `text` (`#RRGGBB`), `schrift_anzeige`, `schrift_text` (ids aus `claw/schriften.py` `REGISTER`), `logo` (Dateiname im Firmenordner oder leer), `stand` (`JJJJ-MM-TT HH:MM von <name>`); Abschnitte `## Wer wir sind`, `## Zielgruppe`, `## Ton`, `## Angebote`, `## Do & Don'ts`, `## Fakten und Zahlen`, `## Bildstil`.
- Lesen fehlertolerant: ungültige Werte verworfen + Hinweis „Marke.md: <schlüssel> ungültig“; ohne Kopfteil gilt nur der Textteil.
- Logo PNG/JPEG ≤ 2 MB, abgelegt als `logo.png`/`logo.jpg`.
- Spiegel: akzent→`gestalt.akzent`, zweitfarbe→`gestalt.flaeche`, logo→`gestalt.logo` (data-URL), Schriftpaar→`gestalt.schriften {anzeige, text}` im Standard-Newsletter-Layout der Firma; kaputte Werte nie spiegeln; Abgleich beim Start des Arbeiters und alle 10 Minuten.
- Vorlagen übernehmen Akzent, Zweitfarbe, Logo **und** Schriftpaar (`root.data.schriften`); Grund- und Textfarbe der Vorlage bleiben.
- Webseiten-Leser: nur http/https; jede aufgelöste IP geprüft (privat, Loopback, Link-Local, 100.64.0.0/10, Multicast, reserviert ⇒ gesperrt), auch nach jeder Umleitung (≤ 3); Startseite + ≤ 5 Unterseiten derselben Domain; je ≤ 2 MB; Zeitlimit 10 s; keine Cookies/JS/Formulare; Text ≤ 20 000 Zeichen gesamt; CSS ≤ 500 KB je Datei; ≤ 6 Logo-Kandidaten.
- Vorschlag: Schriften nur Register, Farben nur `#RRGGBB`, Kontrast Text/Grund ≥ 4,5 und Knopftext/Akzent ≥ 4,5 (Funktion `kontrast` aus `claw/schoenheit.py`); Verstoß ⇒ ein Korrekturversuch, sonst „Das habe ich nicht umsetzen können: …“. Webseiten- und Upload-Inhalte sind Material, niemals Anweisung.
- Meldungen wörtlich: „Noch kein Branding – erzähl mir von der Firma“, „Wird übernommen …“, „Wird übernommen, sobald der PC läuft“, „Inzwischen gibt es ein neueres Profil – bitte neu laden“, „Spiegel veraltet seit …“, „Webseite … nicht lesbar: …“, „Die Marke hat sich geändert – übernehmen?“, Agent-Bitte „Übernimm die neue Marke: Farben, Schriften und Logo, sonst nichts ändern.“
- Kein Modell auf der VM; Claude nur über :8117; :8114/ComfyUI unberührt.

## Rulings (Präzisierungen gegenüber der Spec)

- R1: Marken-Aufträge bekommen eine **eigene Tabelle** `marketing.marken_auftraege` statt `chat_auftraege` mit `art='marke'` – `chat_auftraege.inhalt` ist Pflicht und alle Sperren/Trigger/Funktionen hängen am Inhalt; eine eigene Tabelle lässt den Gestaltungs-Agenten unberührt. Arten `chat` und `uebernehmen`. Verarbeitet vom selben Chat-Arbeiterprozess (eigener Zweig).
- R2: Uploads im Marken-Chat gehen über eine eigene sales-ui-Route mit Firmenzuordnung (gleiche Prüfung wie der Editor-Anhang); der Arbeiter holt sie über eine Marken-Arbeiter-Medienroute, die nur Bilder/Dokumente der Firma bzw. Gemeinsam liefert.
- R3: „Ausblenden“ des Editor-Hinweises setzt `inhalte.marke_geaendert_am` auf NULL (Pult-Route).

## Review Focus

1. Webseiten-Adresse, die auf eine öffentliche Seite zeigt, aber per Umleitung auf `http://127.0.0.1:5510` oder `http://100.x.y.z` springt → gesperrt, nichts geladen (Test in Task 3).
2. Betreiber ändert in Rowboat von Hand `akzent: #12` (kaputt) → Profilseite zeigt Hinweis, Spiegel bleibt beim letzten gültigen Wert, Vorlagen weiter korrekt (Tests in Task 2 + Task 5).
3. Zwei Tabs übernehmen nacheinander zwei verschiedene Vorschläge → zweiter abgelehnt, Rowboat enthält genau den ersten (Tests in Task 1 + Task 4).
4. Vorschlag mit hellgrauem Text auf weißem Grund → Korrekturversuch, nie übernommen (Test in Task 5).
5. Firma ohne Rowboat-Ordner übernimmt zum ersten Mal → Ordner angelegt, Marke.md + Logo geschrieben, Link-Sperre greift trotzdem (Test in Task 2).

---

### Task 1: Migration 064 – Marken-Aufträge, Vorschläge, Markierung, Schriften im Layout (MOS)

**Files:** Create `db/064_marke.sql`, `db/verify_064.sql`.

**Interfaces – Produces:**
- `marketing.marken_auftraege (id uuid PK, mandant text NOT NULL FK mandanten, art text CHECK in ('chat','uebernehmen'), nachricht text ≤ 2000, kontext jsonb object, status CHECK in ('offen','in_arbeit','fertig','fehler'), antwort text, hinweise jsonb, vorschlag uuid NULL, versuche int, vergeben_bis timestamptz, erstellt_am, geaendert_am)`; Unique-Index: je Mandant höchstens ein `offen|in_arbeit`.
- `marketing.marken_vorschlaege (id uuid PK, mandant text FK, auftrag uuid FK marken_auftraege, vorschlag jsonb object, status CHECK in ('offen','angenommen','verworfen','ersetzt'), erstellt_am, entschieden_von, entschieden_am)`.
- `marketing.inhalte.marke_geaendert_am timestamptz NULL`; neue Tabelle `marketing.marken_spiegel (mandant PK, stand text, gespiegelt_am timestamptz, fehler text)` für „Spiegel veraltet seit …“.
- Funktionen (Regeln hier, API nur Formen): `pult_marke_anlegen(mandant, nachricht, kontext) -> uuid` (Mandant aktiv; ein laufender je Mandant ⇒ „Der Assistent arbeitet gerade“), `pult_marke_naechster(frist) -> jsonb` (ältester offener, Art + Mandant + Verlauf der letzten 10 fertigen chat-Runden + bei `uebernehmen` der Vorschlag), `pult_marke_verlaengern(id, frist) -> bool`, `pult_marke_vorschlag(auftrag, vorschlag jsonb, antwort text, hinweise jsonb) -> uuid` (setzt offene ältere auf `ersetzt`, Auftrag `fertig`), `pult_marke_fertig(auftrag, antwort, hinweise)` (für `uebernehmen` und Antworten ohne Vorschlag), `pult_marke_zurueck(auftrag, antwort)` (fehler), `pult_marke_uebernehmen(vorschlag uuid, von text) -> uuid` (nur `offen` und neuester offener des Mandanten, sonst „Inzwischen gibt es ein neueres Profil – bitte neu laden“; setzt `angenommen`, legt Auftrag `uebernehmen` an), `pult_marke_verwerfen(vorschlag, von)`, `pult_marke_spiegeln(mandant, gestalt jsonb, stand text) -> int` (Standard-Newsletter-Layout der Firma: neue Fassung über die bestehende Layout-Logik bzw. anlegen falls keins; schreibt `marken_spiegel`), `pult_marke_markieren(mandant) -> int` (setzt `marke_geaendert_am=now()` für alle `entwurf` der Firma), `pult_marke_hinweis_aus(inhalt)`.
- `pult_gestalt_fehler` (aktive Definition aus 051) erweitert: optionaler Schlüssel `schriften` = Objekt mit genau `anzeige`, `text`, je id aus der Register-Liste (als SQL-Array im Migrationskopf, gleiche ids wie `claw/schriften.py` – Test in Task 4 vergleicht beide).

- [ ] Failing `verify_064.sql` (migration_probe, eigener Probe-Mandant-Datensatz): Anlegen + zweiter laufender abgelehnt; naechster liefert Art/Mandant/Verlauf; Vorschlag ersetzt älteren; **Review Focus 3:** zweiter `uebernehmen` eines älteren Vorschlags abgelehnt mit genauer Meldung; spiegeln legt Layout an bzw. neue Fassung; markieren trifft nur `entwurf`; hinweis_aus; gestalt mit gültigen/ungültigen `schriften`. Zusammen mit verify_060–063 in EINER Probe grün.
- [ ] Commit `feat(marketing): Migration 064 Marken-Auftraege und Vorschlaege`.

### Task 2: Markenprofil lesen und schreiben (MOS, rein)

**Files:** Create `claw/markenprofil.py`; Test `claw/tests/test_markenprofil.py`.

**Interfaces – Produces:**
```python
@dataclass
class Profil:
    werte: dict          # gültige Kopfteil-Werte (nur bekannte Schlüssel)
    abschnitte: dict     # Abschnittsname -> Text
    hinweise: list[str]  # z. B. "Marke.md: akzent ungültig"
    ordner: str | None
    logo_pfad: str | None
def lesen(wurzel: str, mandant: str, name: str) -> Profil                 # wirft nie
def schreiben(wurzel: str, mandant: str, name: str, werte: dict, abschnitte: dict,
              logo: tuple[bytes, str] | None, von: str, jetzt: datetime) -> str   # Pfad der Marke.md; wirft MarkenFehler
def text(werte: dict, abschnitte: dict) -> str                             # Markdown mit Kopfteil
def fuer_prompt(profil: Profil) -> str                                     # Kopfteil als lesbare Zeilen + Abschnitte
def gestalt(werte: dict, logo: bytes | None, logo_typ: str | None) -> dict  # Spiegel-Gestalt
class MarkenFehler(Exception): ...
```
- Ordnerfindung und Link-Sperre aus `claw/markenwissen.py` wiederverwenden (`ordner_finden`, `_echt` – ggf. öffentlich machen), nicht kopieren.
- `schreiben`: legt den Firmenordner unter der Wurzel an, falls er fehlt (Name = Mandanten-Name), prüft danach die Link-Sperre; bisherige `Marke.md` → `Marke-Verlauf/JJJJ-MM-TT-HHMM.md` (Kollision `-2` …), neue Datei exklusiv über temp+replace; Logo: Typ per Signatur (PNG/JPEG), ≤ 2 MB, alte `logo.*` werden ersetzt.
- [ ] Failing tests: gültiger/kaputter/fehlender Kopfteil (**Review Focus 2**: `akzent: #12` ⇒ verworfen + Hinweis, Rest gültig); unbekannte Schrift verworfen; Abschnitte zuordnen; Rundlauf schreiben→lesen; Verlauf-Datei; **Review Focus 5:** Ordner fehlt ⇒ angelegt, Junction/Symlink als Firmenordner ⇒ MarkenFehler; Logo zu groß/kein Bild ⇒ MarkenFehler; `fuer_prompt` enthält „Akzentfarbe #…“; `gestalt` Schlüssel/Werte.
- [ ] FAIL → implementieren → PASS. Commit `feat(marketing): Markenprofil in Rowboat lesen und schreiben`.

### Task 3: Webseiten-Leser (MOS)

**Files:** Create `claw/webseite.py`; Test `claw/tests/test_webseite.py` (lokaler `http.server` im Test nur für Inhalt; die IP-Sperre wird über eine injizierbare Auflösung getestet).

**Interfaces – Produces:**
```python
@dataclass
class Seite: url: str; text: str; ueberschriften: list[str]
@dataclass
class Fund: seiten: list[Seite]; farben: list[str]; schriften: list[str]; logos: list[str]; hinweise: list[str]
def lesen(url: str, *, aufloesen=socket.getaddrinfo, oeffnen=None) -> Fund     # wirft nie; Fehler als Hinweis "Webseite <url> nicht lesbar: <grund>"
def logo_laden(url: str, *, aufloesen=socket.getaddrinfo) -> tuple[bytes, str] | None   # gleiche Sperren, ≤ 2 MB, PNG/JPEG
def adresse_erlaubt(host: str, aufloesen) -> bool
```
- Umsetzung mit `urllib` + eigenem Redirect-Handler (jede Umleitung erneut prüfen, max 3), `html.parser` für Text/Überschriften/Links/Bilder/`<link rel=stylesheet>`/`style=`; Farben per Regex (`#rgb`, `#rrggbb`, `rgb(…)` → `#rrggbb`, nach Häufigkeit), Schriftnamen aus `font-family`.
- [ ] Failing tests: `http://127.0.0.1`, `localhost`, `10.x`, `192.168.x`, `100.64.x`, `169.254.x`, `[::1]` gesperrt; **Review Focus 1:** öffentliche Auflösung, Umleitung auf 127.0.0.1 ⇒ gesperrt, Inhalt nicht geladen; mehrere A-Records einer privat ⇒ gesperrt; `ftp://` abgelehnt; > 2 MB abgebrochen; nur dieselbe Domain, ≤ 5 Unterseiten; Farben/Schriften/Logo-Kandidaten aus HTML+CSS; Text auf 20 000 gekürzt.
- [ ] FAIL → implementieren → PASS. Commit `feat(marketing): Webseiten-Leser mit Adresssperre fuer das Branding`.

### Task 4: Pult- und Arbeiter-API für die Marke, Vorlagen mit Schriftpaar (MOS)

**Files:** Create `api/marke.py`; Modify `api/server.py` (Router), `api/pult.py` (`_vorlage_fuellen`: `root.data.schriften` aus `gestalt.schriften`; `GET /inhalte/{iid}` liefert `marke_geaendert_am`), `api/bilder.py` (Bild-Arbeiter-Auftrag trägt `mandant` + `mandant_name`); Test Create `tests/test_marke_api.py`, Modify `tests/test_pult_api.py`, `tests/test_bilder_api.py`.

**Interfaces – Produces:**
- Pult (`X-Pult-Key`): `GET /api/pult/marke?mandant=` → `{"mandant","name","spiegel": {gestalt, stand, gespiegelt_am, fehler}, "auftraege": [letzte 10 chat-Runden], "laeuft": bool, "vorschlag": {id, vorschlag, erstellt_am}|null, "uebernahme": "laeuft"|null}`; `POST /api/pult/marke/chat {mandant, nachricht, kontext}`; `POST /api/pult/marke/vorschlaege/{id}/uebernehmen {von}`; `POST /api/pult/marke/vorschlaege/{id}/verwerfen {von}`; `GET /api/pult/marke/vorschlaege/{id}/vorschau?format=mail|handy&bild_basis=` (Vorlage `studio` mit dem Vorschlag gefüllt: Farbrollen aus akzent/zweitfarbe, Schriftpaar, Logo, Mustertext in Überschrift/Absatz/Betreff); `POST /api/pult/inhalte/{iid}/marke_hinweis_aus`.
- Arbeiter (`X-Bild-Key`): `POST /api/marke/arbeiter/naechster`, `/{aid}/weiter`, `/{aid}/vorschlag {vorschlag, antwort, hinweise}`, `/{aid}/fertig {antwort, hinweise}`, `/{aid}/zurueck {antwort}`, `GET /{aid}/medien/{name}` (nur Medien der Firma + Gemeinsam, wie `medien_mandant.ist_fremd`), `POST /{aid}/logo?name=` (Web-Logo-Bytes ≤ 2 MB PNG/JPEG → Medien der Firma, zugeordnet), `POST /api/marke/arbeiter/spiegeln {mandant, gestalt, stand}` und `/markieren {mandant}`.
- Register-Abgleich: Test, dass die ids im SQL-Array von 064 genau `REGISTER.keys()` sind.
- [ ] Failing tests: jede Route Erfolg + DB-Ablehnung + 401; Übernehmen-Konflikt ⇒ 422 mit Meldung (**Review Focus 3**); Vorschau rendert mit Vorschlagsfarben/-schriften; Medienroute fremd ⇒ 404; Logo-Upload Typ/Größe; `_vorlage_fuellen` setzt Schriftpaar, ohne `schriften` unverändert; Bild-Auftrag trägt Mandant.
- [ ] FAIL → implementieren → PASS. Commit `feat(marketing): Pult- und Arbeiter-API fuer die Marke`.

### Task 5: Marken-Arbeiter am PC und Agent/Bild-Anbindung (MOS)

**Files:** Create `claw/marken_prompt.py`, `workers/marken_arbeiter.py`; Modify `workers/chat_worker.py` (Schleife ruft zusätzlich den Marken-Zweig; Abgleich beim Start + alle 10 min), `claw/agent_prompt.py` (Regel „Farben nur aus der Marke …“, Markenwissen-Kopfteil über `markenprofil.fuer_prompt`), `claw/markenwissen.py` (Kopfteil nicht roh in den Prompt), `workers/bild_worker.py` + `claw/bild_prompt.py` (Abschnitt Bildstil in die Bildbeschreibung); Tests `claw/tests/test_marken_prompt.py`, `tests/test_marken_arbeiter.py`, betroffene bestehende Tests.

**Interfaces – Consumes:** Task 1–4. **Produces:** `marken_prompt.SYSTEM`, `nutzer_text(auftrag, profil, fund, unterlagen, bilder, hinweise) -> str`, `antwort_lesen(text) -> {"antwort", "vorschlag"|None}` (prüft Schlüssel, Register, Hex, Kontrast ≥ 4,5 Text/Grund und Knopftext/Akzent über `schoenheit.kontrast`, Abschnitte als Text ≤ 4000 je, Mustertext); `marken_arbeiter.ein_durchlauf(api, fragen_strom, ...) -> str`, `abgleichen(api, wurzel, mandanten) -> list[str]`.
- chat: Uploads (wie `anhaenge_vorbereiten`), Webseite (erste http(s)-Adresse in der Nachricht → `webseite.lesen`), Profil → Prompt → Claude (Shim, ohne Werkzeuge) → `antwort_lesen` → bei Fehler ein Korrekturversuch → Logo: `anhang:<name>` bleibt Medienname, `web:<n>` → `webseite.logo_laden` + `/logo` → Vorschlag ablegen.
- uebernehmen: Logo-Bytes holen (Medienroute) → `markenprofil.schreiben` → `gestalt` → `/spiegeln` → `/markieren` → `/fertig`; jeder Fehler ⇒ `/zurueck` mit Grund, nichts halb geschrieben (Marke.md erst nach erfolgreichem Logo).
- Abgleich: je aktiver Firma `markenprofil.lesen`; gültige Werte ≠ Spiegel ⇒ `/spiegeln`; ungültige nie.
- [ ] Failing tests: Prompt/Antwort (gültig; unbekannte Schrift; **Review Focus 4** hellgrau auf weiß ⇒ AntwortFehler, Korrekturversuch); Durchlauf chat mit Webseite (gefälschtes `webseite.lesen`) und Uploads; uebernehmen schreibt Rowboat (tmp) + spiegelt + markiert, Fehler beim Logo ⇒ nichts geschrieben; Abgleich spiegelt Handänderung, kaputte Werte nicht (**Review Focus 2**); Agent-Prompt nennt Markenfarben; Bildbeschreibung enthält Bildstil.
- [ ] FAIL → implementieren → PASS. Commit `feat(marketing): Marken-Chat am PC, Markenprofil fuer Agent und Bilder`.

### Task 6: Seite „Marke“ in sales-ui (SC)

**Files:** Modify `sales-mcp/ui_marketing.py` (Seiten `layouts`/`layout_editor` ersetzen durch `marke`; alte Routen leiten auf `/marketing/layouts` = neue Seite), `sales-mcp/ui.py` (nur CSS), Create `sales-mcp/ui_marke.py` (Seite + Formulare), Test Create `sales-mcp/tests/test_marke_seite.py`, Modify bestehende Layout-Tests.

- [ ] Seite `/marketing/layouts` (Name „Marke“): Firma aus `marketing_mandant.firma`; Profil kompakt (Farbfelder, Schriftmuster, Logo über die signierte Bildadresse, erste Zeilen Ton/Zielgruppe, Stand, Hinweise, „Spiegel veraltet seit …“), ohne Profil „Noch kein Branding – erzähl mir von der Firma“; Chat-Verlauf; Formular Nachricht + Datei-Upload (multipart, Uploads über eine eigene Route mit Firmenzuordnung, gleiche Prüfung wie der Editor-Anhang, R2); Meta-Refresh alle 5 s solange `laeuft` oder `uebernahme`; Vorschlag: Rahmen `…/vorschau?format=mail|handy` (Umschalter per Link), Textkarte, „Übernehmen“ (Bestätigungshaken) / „Verwerfen“; Statuszeilen „Wird übernommen …“ bzw. „Wird übernommen, sobald der PC läuft“ (wenn > 60 s offen).
- [ ] Der alte Regler-Editor (`/marketing/layout/{name}`, Speichern, Standard, Live-Vorschau) entfällt; die Pfade leiten per 303 auf `/marketing/layouts`.
- [ ] Failing tests: Profil mit/ohne Kopfteil; Chat-Senden (CSRF, Pult-Aufruf mit mandant); Upload ordnet zu; Übernehmen mit/ohne Haken, Konfliktmeldung; Verwerfen; Refresh nur bei laufend; alte Pfade leiten weiter; kein JS; alle Pult-Aufrufe im Threadpool; API weg ⇒ „Marketing gerade nicht erreichbar“.
- [ ] FAIL → implementieren → PASS. Commit `feat(ui): Seite Marke mit Chat, Vorschau und Uebernehmen`.

### Task 7: Editor-Hinweis „Marke geändert“ (SC)

**Files:** Modify `sales-mcp/ui_editor.py` (Startdaten `marke_geaendert`: true wenn `marke_geaendert_am` neuer als die neueste Fassung und Status `entwurf`; JSON-Route `POST /marketing/editor/{iid}/marke-hinweis-aus`), `editor/src/pult.ts`, `editor/src/pultZustand.ts`, `editor/src/App/…` (Band); Tests `editor/src/pult.marke.test.ts`, `sales-mcp/tests/test_editor_seite.py`, `test_editor_paket.py`.

- [ ] Band „Die Marke hat sich geändert – übernehmen?“ mit „Übernehmen“ (schickt die Agent-Bitte wörtlich über den bestehenden Chat-Weg) und „Ausblenden“ (Route → `marke_hinweis_aus`); nicht bei nurLesen/eingereicht; gesperrt solange der Agent arbeitet (vorhandene Sperre, Hooks unbedingt aufrufen).
- [ ] Failing tests: Startdaten-Bedingung (neuer/älter/eingereicht); Route CSRF + Pult-Aufruf; vitest: Band-Logik, Bitte-Text, Ausblenden; Paket-Test: Bundle enthält „Die Marke hat sich geändert“.
- [ ] FAIL → implementieren → vitest/tsc/build/Paket PASS. Commit `feat(editor): Hinweis Marke geaendert mit Uebernahme durch den Agenten` (inkl. Bundle).

### Task 8: Auslieferung und echter Lauf (Controller, nach Freigabe des Betreibers)

- [ ] Claims; Migration 064 Probe (verify_060–064) → anwenden → verify; Push MOS/SC; VM `update.sh`; Haupt-Checkout per Hash-Vergleich synchronisieren; Chat-Arbeiter :8134 und Bild-Arbeiter :8133 neu (ComfyUI nie anfassen).
- [ ] Echter Lauf (fin2gether): Webseiten-Adresse + Logo-Upload → Vorschlag → Vorschau → „Ton ruhiger“ → Übernehmen → `Marke.md` + Logo in Rowboat, Probe-Texte im Verlauf → neuer fin2gether-Newsletter aus Vorlage mit Farben/Schriften/Logo → offener Entwurf zeigt Hinweis, Klick passt an.
- [ ] Claims schließen, Memory ergänzen.
