# `/marke_neu` – neue Marke per Skill im Marken-Chat – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Im Marken-Chat startet `/marke_neu Firmenname [Webseite]` (auch `/skill marke-neu …`) ein geführtes Gespräch nach dem Skill `marke-neu`.
- Am Ende steht nach Bestätigung eine aktive Marke: im Umschalter, Profil gefüllt, Pflichtteil (Impressum, Abmeldehinweis, ggf. Vermittlerangaben) gespeichert, Layout gespiegelt.
- Dazu ein Lader und ein Leitfaden für Marketing-Skills (`spaces/marketing/skills/`).

**Architecture:**
- **Skills:** `claw/skills.py` liest `skills/*/SKILL.md` (OpenClaw-Frontmatter, einzeilig), bildet Befehlsnamen nach OpenClaw-Regel, verweigert reservierte Namen und Doppelungen. Der Skill-Text kommt wie bei `workers/video_claw.py` in den System-Prompt, denn der Shim reicht keine OpenClaw-Werkzeuge durch.
- **Entwurfs-Mandant:** Neue Spalten `mandanten.einrichtung` (`'laeuft'|'abgebrochen'|NULL`) und `mandanten.einrichtung_stand`. `/marke_neu` legt einen inaktiven Mandanten mit `einrichtung='laeuft'` an. Die Marken-Funktionen akzeptieren zusätzlich `einrichtung='laeuft'`; alles andere (Newsletter, Vorlagen, Plan, Reels) sieht nur `aktiv` und die unveränderte Cookie-Wahl.
- **Runde:** `marken_arbeiter` erkennt `einrichtung='laeuft'` am Auftrag, hängt Skill-Text und „Stand der Einrichtung“ an, übernimmt alle Profiländerungen direkt und schreibt den Pflichtteil über eine neue Arbeiter-Route. Rechtsangaben gelten nur, wenn sie wörtlich in Nachricht oder gelesenem Seitentext stehen.
- **Oberfläche:** Die Marken-Seite bekommt eine eigene Wahl `?einrichtung=<id>`, Fortschritt, „Marke anlegen“ und „Einrichtung abbrechen“.

**Tech Stack:** Python 3.12, FastAPI (Marketing-API), Starlette (sales-ui), PostgreSQL/Supabase (Schema `marketing`), pytest.

**Spec:** sales-claw `docs/superpowers/specs/2026-10-21-marke-neu-skill-design.md`.

**Repos:**
- Tasks 1–7 in **vibemind-os** (MOS) `master`, Pfade relativ zu `spaces/marketing/`. Eigener Worktree unter `C:/Users/User/ClaudeWork/` (z. B. `wt-mos-marke-neu`), gepusht nach `origin master`. Der Haupt-Checkout `C:/Users/User/Desktop/Vibemind_V1/vibemind-os` ist ein alter, schmutziger Pin – dort nichts lesen oder committen.
- Task 8 in **sales-claw** (SC) `feat/stufe-1-fundament`, eigener Worktree, Pfade relativ zum Repo-Root.
- Task 9 (Auslieferung + Abnahme) macht der Koordinator, nicht ein Implementierer.

**Testbefehle:**
- **MOS** (aus dem Worktree-Root): `C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests spaces/marketing/claw/tests -q -p no:cacheprovider --basetemp C:/Temp/pt-marke-neu` (einzelne Dateien statt der Ordner während TDD). `--basetemp` muss auf C: liegen. Vorbestehend rot: `test_cockpit_contract`, `test_abschnitte`, `test_formular_entwurf`, `test_gestaltung_pruefen`.
- **Migration:** `…python.exe -m spaces.marketing.scripts.migration_probe spaces/marketing/db/086_marke_einrichtung.sql spaces/marketing/db/verify_086.sql` → `PROBE OK (zurueckgerollt)`. Läuft immer in einer Transaktion mit ROLLBACK.
- **SC** (PowerShell, aus `sales-mcp`, DB-Klon `sales_struktur` im Container `sales-testdb` auf `127.0.0.1:55600`):
  `$env:SALES_DB_URL='postgresql://postgres:ci@127.0.0.1:55600/sales_struktur'; $env:SALES_DB_SCHEMA='sales_test'; & E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q -p no:cacheprovider`. Lauscht 55600 nicht (Weiterleitung `sales-testdb-fwd` nach Docker-Neustart tot), direkt `127.0.0.1:55432` nehmen. Jede Datei einzeln. Vorbestehend rot: `test_bild_route_entschluesselt_nur_einmal`.

## Global Constraints

- **Befehl:** Skill `marke-neu` → Befehl `/marke_neu`, zusätzlich `/skill marke-neu [text]`. Bei `/skill` gelten Bindestrich, Unterstrich und Leerraum als gleich.
- **Befehlsname bereinigen (OpenClaw-Regel):** klein, `[^a-z0-9_]` → `_`, `_` am Rand entfernen, höchstens 32 Zeichen.
- **Reservierte Namen**, als Konstanten mit Quellenangabe in `claw/skills.py`:
  - OpenClaw (eingebaute Befehle des Gateways): `help, commands, tools, skill, status, tasks, approve, context, btw, export, tts, whoami, session, subagents, acp, focus, agents, kill, steer, config, mcp, plugins, debug, usage, stop, restart, activation, send, reset, new, compact, think, verbose, trace, fast, reasoning, elevated, exec, model, models, queue, bash`
  - Telegram-Bot (`workers/telegram_bot.py`): `neu, new, reset, start, hilfe, help`
  - Kollision oder Doppelung ist ein Fehler (Test schlägt fehl), nie still `_2`.
- **Frontmatter `marke-neu`:** `name: marke-neu`, `description:` ≤ 100 Zeichen, `user-invocable: true`, `metadata: {"vibemind":{"chats":["marke"],"schritte":7}}`. Unbekannte Schlüssel ignoriert der Lader. Ohne `metadata.vibemind.chats` gehört ein Skill zu keinem Chat (`newsletter-bild` bleibt unberührt); die 100-Zeichen-Grenze prüft der Test nur für Skills mit Chat.
- **Schritte des Gesprächs** (Titel wörtlich): 1 „Name und Webseite“, 2 „Pflichtangaben für Newsletter“, 3 „Wer und was“, 4 „Aussehen“, 5 „Stimme“, 6 „Belege“, 7 „Zusammenfassung und Bestätigung“. Je Runde: was übernommen wurde (kurz), Fortschritt „Schritt n von 7“, **genau eine** nächste Frage, ein Satz, wozu die Angabe dient.
- **Pflicht für den Abschluss:** Schritt 1 und Schritt 2. Impressum und Abmeldehinweis lassen sich nicht überspringen. Vermittlerangaben sind Pflicht nur, wenn der Betreiber „Seid ihr Finanz- oder Versicherungsvermittler?“ mit Ja beantwortet hat; der Agent stellt die Frage, entscheidet sie nie.
- **`abmelde_hinweis`** muss `{abmeldelink}` enthalten. Vorgabe (wie 050): `Du bekommst diese Mail, weil du dich eingetragen hast. Abmelden: {abmeldelink}`.
- **Rechtsangaben** (Impressum, Vermittlerangaben) nur, wenn der Text (Leerraum zusammengefasst) als Teilstring in der Nachricht des Betreibers oder in einem gelesenen Seitentext vorkommt; sonst verworfen mit Hinweis.
- **Mandanten-id aus dem Namen:** Umlaute → ae/oe/ue/ss, klein, `[^a-z0-9]` → `_`, Folgen von `_` zu einem, `_` am Rand weg, beginnt sie nicht mit einem Buchstaben, Präfix `m_`, kürzer als 2 → Anhang `_marke`, auf 31 Zeichen gekürzt (`^[a-z][a-z0-9_]{1,30}$`), bei Kollision `_2`, `_3` … (vor dem Anhang gekürzt, damit 31 gilt).
- **Namensregeln:** gleicher Name (ohne Groß/Klein, getrimmt) wie eine **aktive** Marke → abgelehnt. Gleicher Name wie eine Einrichtung (`laeuft` oder `abgebrochen`) → fortgesetzt (`einrichtung='laeuft'`). Pro Name höchstens ein Mandant.
- **Firmenwahl:** Cookie `mk_mandant` und `marketing_mandant.waehlen()` bleiben unverändert (nur aktive). Einrichtungen sind nur über `?einrichtung=<id>` auf `/marketing/layouts` wählbar, geprüft gegen `GET /mandanten?einrichtung=1`.
- **Während der Einrichtung** gelten alle Profiländerungen direkt (auch Farben, Schriften, Logo, Webseite). Rückgängig setzt wie heute nur Abschnittstexte zurück.
- **Abschluss:** `pult_mandant_aktivieren` setzt `aktiv=true, einrichtung=NULL` und prüft serverseitig Name, Impressum, Abmeldehinweis mit `{abmeldelink}` und die Vermittler-Regel. Gespiegelt wird nicht in dieser Route; der Arbeiter spiegelt nach jeder Übernahme, der Abgleich (600 s) erfasst die Marke ab Aktivierung.
- **Abbruch:** `einrichtung='abgebrochen'`, nichts wird gelöscht; der Ordner `companys/<Name>/` bleibt und wird im Abschlussbericht genannt.
- **Migration:** Plan nutzt **086**. Vor dem Anlegen gegen `origin/master` (`git ls-tree origin/master spaces/marketing/db/`) und `WORKBOARD.md` prüfen (083/084 sind vermutlich von anderen Sessions belegt); ist 086 belegt, die nächste freie Nummer nehmen und überall ersetzen. Kein `SECURITY DEFINER`, keine eigenen GRANTs (Default Privileges aus 003), Sperrreihenfolge wie 064: `mandanten → marken_auftraege → marken_vorschlaege`.
- **Texte** deutsch, kurz, im Ton der bestehenden Marken-Seite. Keine Telegram-/Gateway-Befehle, keine Laden-Anbindung, kein Umbau bestehender Skills, kein Löschen über die Oberfläche.

## Review Focus

1. **Firmenname mit Zeichen, die als Ordnername nicht gehen** (`Müller/Söhne`, `A:B`, nur Leerzeichen, 200 Zeichen): Die Einrichtung wird mit deutschem Grund abgelehnt, bevor ein Mandant entsteht – sonst scheitert später `markenprofil._ordner_fuer_schreiben` bei jeder Übernahme. Test: `verify_086` (h) und `test_marke_neu_name_ungueltig_422` (Task 6).
2. **Halbfertige Marke per Cookie oder alter Adresse wählen:** Cookie `mk_mandant=<einrichtung-id>` fällt auf die Vorgabe zurück; ein POST mit `einrichtung=<id>` einer inzwischen abgeschlossenen oder abgebrochenen Einrichtung handelt nie an der Cookie-Firma, sondern antwortet 422 „bitte Seite neu laden“. Tests: `test_cookie_auf_einrichtung_faellt_auf_vorgabe`, `test_post_mit_veralteter_einrichtung_422` (Task 8).
3. **Modell gibt das Impressum leicht umformatiert wieder** (andere Zeilenumbrüche, doppelte Leerzeichen): Der Wortlaut-Vergleich fasst Leerraum zusammen und erkennt es als belegt; ein umformuliertes oder erfundenes wird verworfen. Tests: `test_pflichtteil_leerraum_egal`, `test_pflichtteil_erfunden_verworfen` (Task 3).
4. **`/marke_neu` mit angehängten Dateien:** Die Dateien würden der gerade gewählten (anderen) Firma zugeordnet. Die UI lehnt Befehle mit Anhängen vor dem Ablegen ab, die API ebenso. Tests: `test_befehl_mit_anhang_abgewiesen_ohne_ablage` (Task 8), `test_marke_neu_mit_anhaengen_400` (Task 6).
5. **Zweites `/marke_neu` mit demselben Namen, während der Assistent noch arbeitet:** Es entsteht kein zweiter Mandant und kein Fehlerbild; die API antwortet mit der bestehenden Einrichtung (`fortgesetzt: true`, `auftrag: null`), die UI leitet dorthin. Test: `test_marke_neu_fortsetzen_waehrend_runde` (Task 6).

---

### Task 1: Skill-Lader, Skill `marke-neu`, Leitfaden

**Files:**
- Create: `claw/skills.py`, `skills/marke-neu/SKILL.md`, `skills/README.md`
- Test: `claw/tests/test_skills.py`

**Interfaces – Produces:**
- `SKILLS_ORDNER: Path` (= `spaces/marketing/skills`)
- `RESERVIERT_OPENCLAW: frozenset[str]`, `RESERVIERT_TELEGRAM: frozenset[str]`, `RESERVIERT: frozenset[str]` (Vereinigung) – Werte aus den Global Constraints, Kommentar mit Quelle (OpenClaw-Doku „Slash commands“, `workers/telegram_bot.py`).
- `class SkillFehler(ValueError)`
- `@dataclass(frozen=True) class Skill: name: str; befehl: str; beschreibung: str; chats: tuple[str, ...]; schritte: int | None; anweisung: str; pfad: Path`
- `befehlsname(name: str) -> str`
- `frontmatter(text: str) -> tuple[dict[str, str], str]` – einzeilige `schluessel: wert`-Zeilen zwischen `---`; Rest = Anweisung (wie `video_claw._ohne_kopf`). Kein Frontmatter → `SkillFehler`.
- `laden(ordner: Path = SKILLS_ORDNER) -> list[Skill]` – alle `*/SKILL.md`, sortiert nach Name. `SkillFehler` bei fehlendem `name`/`description`, reserviertem oder doppeltem Befehl, ungültigem `metadata`-JSON.
- `befehle(chat: str, ordner: Path = SKILLS_ORDNER) -> list[Skill]` – nur Skills mit `chat in skill.chats` und `user-invocable` nicht `false`.
- `aufloesen(text: str, chat: str, ordner: Path = SKILLS_ORDNER) -> tuple[Skill, str] | None` – `/<befehl> rest` oder `/skill <name> rest`; `rest` getrimmt. Kein passender Skill → `None` (ob der Text überhaupt mit `/` beginnt, prüft der Aufrufer).

- [ ] **Step 1: Tests schreiben** (Fixture-Ordner in `tmp_path` für die Regeln, echter Ordner für den Bestand):
  - `test_befehlsname_openclaw_regel`: `befehlsname("marke-neu") == "marke_neu"`, `befehlsname("  Foo.Bar!! ") == "foo_bar"`, `len(befehlsname("a" * 40)) == 32`.
  - `test_reserviert_enthaelt_beide_listen`: `{"new", "reset", "help", "skill", "status", "stop", "model", "config", "bash"} <= RESERVIERT` und `{"neu", "start", "hilfe"} <= RESERVIERT`.
  - `test_reservierter_name_ist_fehler`: Skill `name: new` → `pytest.raises(SkillFehler)`; ebenso `name: Neu`.
  - `test_doppelter_befehl_ist_fehler`: `marke-neu` und `marke_neu` in zwei Ordnern → `SkillFehler`.
  - `test_frontmatter_und_anweisung`: Anweisung beginnt mit der ersten Zeile nach dem zweiten `---`; unbekannter Schlüssel `foo: bar` stört nicht.
  - `test_ohne_chats_kein_befehl`: Skill ohne `metadata` → in `laden`, nicht in `befehle("marke")`.
  - `test_aufloesen_varianten`: `/marke_neu Probe GmbH https://x.de` → `(skill, "Probe GmbH https://x.de")`; `/skill marke-neu Probe`, `/skill marke_neu Probe`, `/skill marke neu Probe` → derselbe Skill, Rest `"Probe"`; `/MARKE_NEU` → derselbe Skill; `/new`, `/foo`, `hallo` → `None`; Skill eines anderen Chats → `None`.
  - `test_echte_skills_gueltig`: `laden()` wirft nicht; jeder Skill mit Chat hat `len(beschreibung) <= 100`; `newsletter-bild` ist geladen, aber in keinem `befehle(...)`.
  - `test_marke_neu_inhalt`: `befehle("marke")` enthält genau `marke_neu`; `schritte == 7`; die Anweisung enthält die sieben Schritt-Titel wörtlich, `{abmeldelink}`, „Finanz- oder Versicherungsvermittler“, „genau eine“ und den Feldnamen `pflichtteil`.
- [ ] **Step 2: Rot.** `…pytest spaces/marketing/claw/tests/test_skills.py -q` → FAIL (`ModuleNotFoundError: spaces.marketing.claw.skills`).
- [ ] **Step 3: Umsetzen.** `claw/skills.py` nach den Interfaces. `skills/marke-neu/SKILL.md`: Frontmatter aus den Global Constraints; darunter die Anweisung für das Modell – Ziel, die sieben Schritte mit ihren Feldern (Spec „Das Gespräch“), Regeln (Webseite zuerst auswerten, nur Lücken fragen, eine Frage pro Runde, Fortschritt, Rechtsangaben nur wörtlich, Vermittler-Frage stellen statt entscheiden, „weiß ich nicht / später“ = übersprungen außer bei Schritt 2), Antwortformat-Ergänzung (`pflichtteil`, `uebersprungen`, `vermittler`, siehe Task 4) und Schritt 7 (Zusammenfassung mit Impressum/Abmeldehinweis/Vermittlerangaben wörtlich, Hinweis auf den Knopf „Marke anlegen“). `skills/README.md`: die sechs Punkte aus der Spec „Leitfaden für Marketing-Skills“, kurz.
- [ ] **Step 4: Grün.** Dieselbe Datei → PASS.
- [ ] **Step 5: Commit** `feat(marketing): Skill-Lader und Skill marke-neu mit Leitfaden`

### Task 2: Migration 086 – Einrichtung neuer Marken

**Files:**
- Create: `db/086_marke_einrichtung.sql`, `db/verify_086.sql`

**Interfaces – Produces:**
- `marketing.mandanten`: `einrichtung text` mit CHECK `einrichtung IN ('laeuft','abgebrochen')`, `einrichtung_stand jsonb NOT NULL DEFAULT '{}'`, `eingerichtet_von text`; Tabellen-CHECK `einrichtung IS NULL OR NOT aktiv`.
- `marketing._mandant_id_aus_name(p_name text) RETURNS text` – Regel aus den Global Constraints, ohne Kollisionsprüfung.
- `marketing.pult_mandant_einrichten(p_name text, p_von text) RETURNS jsonb` → `{"id", "name", "fortgesetzt": bool}`.
  - Name getrimmt, 2–80 Zeichen, ohne `<>:"/\|?*` und Steuerzeichen, nicht `.`/`..` – sonst `'Ungültiger Firmenname'`.
  - Aktive Marke gleichen Namens → `'Diese Marke gibt es schon – bitte im normalen Marken-Chat weiterarbeiten'`.
  - Inaktive Marke gleichen Namens ohne Einrichtung → `'Eine inaktive Marke mit diesem Namen gibt es schon'`.
  - Einrichtung gleichen Namens → `einrichtung='laeuft'`, `fortgesetzt: true`.
  - Sonst neue Zeile: `aktiv=false, einrichtung='laeuft', eingerichtet_von=p_von, verteiler='{}', pflichtteil='{"impressum":"","abmelde_hinweis":"","vermittlerangaben":""}'`, id mit `_2`, `_3` … bei Kollision.
- `marketing.pult_mandant_pflichtteil_setzen(p_mandant text, p_pflichtteil jsonb, p_stand jsonb DEFAULT NULL) RETURNS jsonb` → `{"pflichtteil", "stand"}`.
  - Nur bei `einrichtung='laeuft'` (sonst `'Keine laufende Einrichtung'`).
  - `p_pflichtteil` NULL oder Objekt mit Schlüsseln ⊆ `impressum, abmelde_hinweis, vermittlerangaben`, je Text; Grenzen 2000/500/2000; nicht leerer `abmelde_hinweis` ohne `{abmeldelink}` → `'Der Abmeldehinweis braucht {abmeldelink}'`. Wird in `pflichtteil` gemischt.
  - `p_stand` NULL oder Objekt ⊆ `uebersprungen` (Array aus 1, 3, 4, 5, 6 – 2 und 7 nie), `vermittler` (boolean oder null). Wird in `einrichtung_stand` gemischt.
- `marketing.pult_mandant_aktivieren(p_mandant text, p_von text) RETURNS boolean` – nur bei `laeuft`; prüft Name, `impressum` nicht leer, `abmelde_hinweis` mit `{abmeldelink}`, `einrichtung_stand->'vermittler'` ist boolean, bei `true` `vermittlerangaben` nicht leer; kein offener/laufender Auftrag außer `wissen` (`'Der Assistent arbeitet gerade'`). Setzt `aktiv=true, einrichtung=NULL`. Deutsche Gründe je Fall.
- `marketing.pult_mandant_einrichtung_abbrechen(p_mandant text, p_von text) RETURNS boolean` – `laeuft` → `abgebrochen`, sonst `'Keine laufende Einrichtung'`.
- Neu definiert, **Körper wörtlich aus der zuletzt gültigen Fassung**, einzige Änderung `AND aktiv` → `AND (aktiv OR einrichtung = 'laeuft')`:
  - `pult_marke_anlegen(text, text, jsonb)` und `pult_marke_bearbeitung_anlegen(text, jsonb)` und `pult_marke_uebernehmen(uuid, text, text)` aus 066,
  - `pult_marke_rueckgaengig(uuid, text, text)` aus 078.
- `pult_marke_naechster(interval, text[])` aus 066 wörtlich, die Rückgabe zusätzlich mit `'einrichtung', m.einrichtung` und, nur wenn `laeuft`, `'pflichtteil', m.pflichtteil, 'einrichtung_stand', m.einrichtung_stand`.
- Kopfkommentar mit RUNBOOK: Ein Replay von 064/066/078 überschreibt die neu definierten Funktionen – danach 086 erneut einspielen und `verify_060 … verify_066`, `verify_078`, `verify_086` zusammen proben.

- [ ] **Step 1: `verify_086.sql`** im Stil von `verify_078.sql` (Probe-Firmen `probe_086_*`, jeder Fall `RAISE EXCEPTION 'verify_086: …'`):
  - (a) Spalten und CHECKs vorhanden; `aktiv=true` mit `einrichtung='laeuft'` scheitert am CHECK.
  - (b) `_mandant_id_aus_name`: `'Müller & Söhne GmbH'` → `'mueller_soehne_gmbh'`, `'3D Druck'` → `'m_3d_druck'`, `'A'` → `'a_marke'`, 60 Zeichen → Länge 31 und passt auf die id-Regex.
  - (c) einrichten: neue Zeile inaktiv/`laeuft`; zweiter Aufruf mit `'probe 086 a '` → `fortgesetzt`, keine zweite Zeile; nach Abbruch fortsetzbar.
  - (d) verschiedene Namen mit gleicher id → `_2`.
  - (e) Name einer aktiven Marke (`vibemind`, `VibeMind`) abgelehnt.
  - (f) `pult_marke_anlegen` geht für `laeuft`, scheitert für `abgebrochen` und für inaktive ohne Einrichtung; ebenso `pult_marke_uebernehmen`.
  - (g) `pflichtteil_setzen`: mischt; ohne `{abmeldelink}` abgelehnt; unbekannter Schlüssel abgelehnt; `uebersprungen: [2]` abgelehnt; bei aktiver Marke abgelehnt.
  - (h) Namen `'A/B'`, `'   '`, `'x:y'`, 81 Zeichen abgelehnt.
  - (i) aktivieren: ohne Impressum abgelehnt; `vermittler` null abgelehnt; `vermittler: true` ohne Angaben abgelehnt; vollständig → `aktiv`, `einrichtung` NULL; danach nicht erneut aktivierbar.
  - (j) `pult_marke_naechster` liefert `einrichtung` und bei `laeuft` `pflichtteil`.
  - (k) bestehende Mandanten unverändert (`einrichtung` NULL, `aktiv` wie vorher).
- [ ] **Step 2: Rot.** Probe nur mit `verify_086.sql` → bricht bei (a) ab.
- [ ] **Step 3: `086_marke_einrichtung.sql`** nach den Interfaces, idempotent, eine Transaktion.
- [ ] **Step 4: Grün.** `migration_probe 086 verify_086` → `PROBE OK`. Dazu `migration_probe 086 verify_064 verify_066 verify_078 verify_086` → `PROBE OK` (alte Nachweise bleiben gültig).
- [ ] **Step 5: Commit** `feat(marketing): Migration 086 Einrichtung neuer Marken`

### Task 3: Stand der Einrichtung und Pflichtteil-Prüfung (rein)

**Files:**
- Create: `claw/einrichtung.py`
- Test: `claw/tests/test_einrichtung.py`

**Interfaces – Produces:**
- `SCHRITTE: tuple[tuple[int, str], ...]` – die sieben Titel aus den Global Constraints.
- `FELDER: dict[int, tuple[str, ...]]` – 1: `webseite`; 3: `Kurz gesagt, Wer wir sind, Angebote, Zielgruppe, Abgrenzung`; 4: `akzent, zweitfarbe, grund, text, schrift_anzeige, schrift_text, logo`; 5: `Ton, Wörter, Do & Don'ts` (Sprechstimme optional); 6: `Fakten und Zahlen, Kanäle, Menschen, Bildstil`. Schritt 2 wird aus dem Pflichtteil berechnet, Schritt 7 ist nie vorab erledigt.
- `ABMELDE_VORGABE: str` (Wortlaut aus den Global Constraints)
- `stand(name: str, profil: dict | None, hat_logo: bool, pflichtteil: dict, einrichtung_stand: dict) -> dict` → `{"schritte": [{"nr", "titel", "erledigt", "offen": [feld, …]}], "naechster": int, "abschliessbar": bool}`. `profil` = `{"werte": {...}, "abschnitte": {...}}` (Form von `marken_spiegel.profil`). Schritt erledigt = alle Felder gefüllt oder `nr in uebersprungen`. Schritt 2 erledigt = Impressum nicht leer, Abmeldehinweis mit `{abmeldelink}`, `vermittler` ist bool, bei `true` Vermittlerangaben nicht leer. `abschliessbar` = Schritt 1 und 2 erledigt (Schritt 1: Name nicht leer, Webseite gefüllt oder übersprungen). `naechster` = kleinster offener Schritt, sonst 7.
- `stand_text(s: dict) -> str` – Block „STAND DER EINRICHTUNG“ für den Prompt: je Schritt `Schritt n von 7 – <Titel>: erledigt | offen (<Felder>)`, dazu „Nächster Schritt: n“.
- `pflichtteil_pruefen(roh: object, belege: list[str]) -> tuple[dict, list[str]]` – gibt die übernehmbaren Felder und Hinweise zurück. Impressum/Vermittlerangaben nur, wenn `_normal(text)` Teilstring von `_normal(beleg)` für einen Beleg ist (`_normal` = Leerraum zu einem Leerzeichen, getrimmt); sonst verworfen mit „Impressum nicht übernommen: steht weder in deiner Nachricht noch auf einer gelesenen Seite“ (bzw. „Vermittlerangaben …“). `abmelde_hinweis` ohne `{abmeldelink}` verworfen mit Hinweis. Nicht-Objekt oder unbekannte Schlüssel → nur Hinweis, leeres Ergebnis.

- [ ] **Step 1: Tests:**
  - `test_stand_leer`: nur Name → Schritt 1 offen (`webseite`), `naechster == 1`, `abschliessbar is False`.
  - `test_stand_uebersprungen_zaehlt`: `uebersprungen: [1, 3]` → Schritte 1 und 3 erledigt.
  - `test_schritt2_braucht_vermittler_antwort`: Impressum + Vorgabe-Abmeldehinweis, `vermittler` fehlt → Schritt 2 offen; `vermittler: False` → erledigt; `vermittler: True` ohne Angaben → offen.
  - `test_abschliessbar_nur_mit_1_und_2`: 1 und 2 erledigt, 3–6 offen → `abschliessbar is True`, `naechster == 3`.
  - `test_schritt4_logo`: alle Farben und Schriften, `hat_logo=False` → offen mit `["logo"]`.
  - `test_stand_text_format`: enthält `"Schritt 2 von 7 – Pflichtangaben für Newsletter: offen"` und `"Nächster Schritt: 1"`.
  - `test_pflichtteil_aus_nachricht_uebernommen`: Impressum steht in der Nachricht → übernommen, keine Hinweise.
  - `test_pflichtteil_leerraum_egal`: Beleg mit Zeilenumbrüchen und doppelten Leerzeichen, Modelltext einzeilig → übernommen.
  - `test_pflichtteil_erfunden_verworfen`: Text in keinem Beleg → nicht im Ergebnis, Hinweis beginnt mit „Impressum nicht übernommen“.
  - `test_abmeldehinweis_ohne_platzhalter_verworfen` und `test_abmeldehinweis_vorgabe_ohne_beleg_ok`.
- [ ] **Step 2: Rot** (`ModuleNotFoundError`). **Step 3: Umsetzen.** **Step 4: Grün.**
- [ ] **Step 5: Commit** `feat(marketing): Stand der Einrichtung und Pruefung der Pflichtangaben`

### Task 4: Prompt für die Einrichtung (`claw/marken_prompt.py`)

**Files:**
- Modify: `claw/marken_prompt.py` (`antwort_lesen`, `nutzer_text`, neu `system_einrichtung`, `EINRICHTUNG_FORMAT`)
- Test: `claw/tests/test_marken_prompt.py`

**Interfaces:**
- Consumes: `skills.Skill` (Task 1).
- Produces:
  - `EINRICHTUNG_FORMAT: str` – Ergänzung des Antwortformats: neben `vorschlag` dürfen `"pflichtteil": null | {"impressum"?, "abmelde_hinweis"?, "vermittlerangaben"?}`, `"uebersprungen": [Schrittnummern]`, `"vermittler": true | false | null` stehen; Hinweis, dass in der Einrichtung jede Profiländerung sofort gilt.
  - `system_einrichtung(skill: Skill) -> str` = `SYSTEM + "\n\n---\n\n# Einrichtung einer neuen Marke (Skill " + skill.name + ")\n\n" + skill.anweisung + "\n\n" + EINRICHTUNG_FORMAT`.
  - `antwort_lesen(..., einrichtung: bool = False)` liefert zusätzlich `"pflichtteil": dict | None`, `"uebersprungen": list[int]`, `"vermittler": bool | None`. Form-Prüfung: `pflichtteil` Objekt oder null, `uebersprungen` Liste von Zahlen aus 1, 3, 4, 5, 6 (andere Werte → `AntwortFehler`), `vermittler` bool oder null. Ohne `einrichtung` werden die drei Felder ignoriert (`None`, `[]`, `None`).
  - `nutzer_text(..., einrichtung_stand: str = "")` – nicht leer → Block direkt nach `NACHRICHT`.

- [ ] **Step 1: Tests:**
  - `test_system_einrichtung_enthaelt_skill_und_format`: Ergebnis beginnt mit `SYSTEM`, enthält `skill.anweisung` und `"pflichtteil"`; das normale `SYSTEM` enthält `"uebersprungen"` nicht.
  - `test_antwort_lesen_einrichtung_felder`: JSON mit `pflichtteil`, `uebersprungen: [3]`, `vermittler: false` → genau diese Werte.
  - `test_antwort_lesen_uebersprungen_2_fehler`: `uebersprungen: [2]` → `AntwortFehler`.
  - `test_antwort_lesen_ohne_einrichtung_ignoriert_pflichtteil`: gleiches JSON ohne `einrichtung=True` → `pflichtteil is None`.
  - `test_nutzer_text_mit_stand`: Block steht nach der Zeile `NACHRICHT:`.
- [ ] **Steps 2–4:** Rot, umsetzen, grün; die übrigen Tests in `test_marken_prompt.py` bleiben grün.
- [ ] **Step 5: Commit** `feat(marketing): Marken-Prompt fuer die Einrichtung neuer Marken`

### Task 5: Runde der Einrichtung im Marken-Arbeiter

**Files:**
- Modify: `workers/marken_arbeiter.py` (`MarkenApi.pflichtteil`, `_chat_mit_spur`, `_seiten_lesen`, `_gespeichert`)
- Test: `tests/test_marken_arbeiter.py`

**Interfaces:**
- Consumes: Auftrag aus `pult_marke_naechster` mit `einrichtung`, `pflichtteil`, `einrichtung_stand` (Task 2); `skills.laden`, `einrichtung.stand/stand_text/pflichtteil_pruefen` (Tasks 1, 3); `marken_prompt.system_einrichtung`, `antwort_lesen(einrichtung=True)`, `nutzer_text(einrichtung_stand=…)` (Task 4); Arbeiter-Route `POST /api/marke/arbeiter/{aid}/pflichtteil` (Task 6).
- Produces:
  - `MarkenApi.pflichtteil(aid, daten: dict) -> dict` → POST `/{aid}/pflichtteil` mit `{"pflichtteil"?: dict, "stand"?: {"uebersprungen", "vermittler"}}`.
  - `EINRICHTUNG_SKILL = "marke-neu"`
  - `_seiten_lesen(..., belege: list[str] | None = None)` hängt `seite.text` jeder gelesenen Seite an.
  - `_gespeichert(vorschlag, profil, immer_direkt: bool = False)` – `immer_direkt` setzt `direkt=True` unabhängig von `ist_direkt`; die `DIREKT_MAX`-Grenze gilt weiter.

**Verhalten bei `auftrag["einrichtung"] == "laeuft"`** (nur `art == "chat"`; Bearbeitung bleibt wie heute):
- System-Prompt `system_einrichtung(skill)`; der Skill wird je Runde mit `skills.laden()` gesucht. Fehlt er → `_Aufgeben("Skill marke-neu fehlt – Einrichtung nicht möglich")`.
- `stand` aus `markenprofil.lesen` (Werte, Abschnitte, `logo_pfad`), `auftrag["pflichtteil"]`, `auftrag["einrichtung_stand"]`; `stand_text` geht in `nutzer_text`.
- Belege = `[auftrag["nachricht"]] + [s.text for s in fund.seiten] + Texte der `lesen`-Folgerunde`.
- Nach der gültigen Antwort, vor `vorschlag`/`fertig`: `pflichtteil_pruefen` → Hinweise anhängen; ist etwas übrig oder sind `uebersprungen`/`vermittler` gesetzt, `api.pflichtteil(aid, …)`. Scheitert der Aufruf mit `ApiFehler` 422, nur Hinweis „Pflichtangaben nicht gespeichert: <Grund>“, kein Abbruch.
- Vorschlag mit `_gespeichert(…, immer_direkt=True)` und `direkt=True` an die VM.

- [ ] **Step 1: Tests** (bestehende Fälschungen aus `test_marken_arbeiter.py` wiederverwenden):
  - `test_einrichtung_skill_im_system_prompt`: der an `fragen_strom` übergebene System-Text enthält die Anweisung von `marke-neu` und „STAND DER EINRICHTUNG“ steht im Nutzertext.
  - `test_einrichtung_farben_gelten_direkt`: Vorschlag ändert `akzent` → `api.vorschlag` bekommt `direkt=True`; ohne Einrichtung bleibt `direkt=False` (Gegenprobe).
  - `test_einrichtung_impressum_aus_nachricht_gespeichert`: Impressum steht in der Nachricht → `api.pflichtteil` mit genau diesem Text, vor `api.vorschlag` aufgerufen.
  - `test_einrichtung_erfundenes_impressum_nicht_gespeichert`: kein `pflichtteil`-Aufruf mit Impressum, Hinweis „Impressum nicht übernommen“ in den Hinweisen.
  - `test_einrichtung_impressum_von_gelesener_seite`: Text nur auf der per `lesen` gelesenen Seite → gespeichert.
  - `test_einrichtung_pflichtteil_422_nur_hinweis`: `api.pflichtteil` wirft `ApiFehler(422, …)` → Auftrag endet `fertig`, Hinweis „Pflichtangaben nicht gespeichert“.
  - `test_bearbeitung_in_einrichtung_unveraendert`: `art == "bearbeitung"` mit `einrichtung` → kein Skill im Prompt.
- [ ] **Steps 2–4:** Rot, umsetzen, grün; ganze `test_marken_arbeiter.py` grün.
- [ ] **Step 5: Commit** `feat(marketing): Marken-Arbeiter fuehrt die Einrichtung nach dem Skill`

### Task 6: API – Befehle, Einrichtung, Pflichtteil, Abschluss

**Files:**
- Modify: `api/marke.py`, `api/medien_mandant.py` (`GET /mandanten`)
- Test: `tests/test_marke_api.py` (neue Routen in `PULT_ROUTEN`/`ARBEITER_ROUTEN`), `tests/test_medien_mandant.py`

**Interfaces:**
- Consumes: DB-Funktionen aus Task 2; `skills.aufloesen/befehle` (Task 1); `einrichtung.stand` (Task 3).
- Produces:
  - `GET /api/pult/mandanten[?einrichtung=1]` → Einträge `{id, name, aktiv, einrichtung}`; mit `einrichtung=1` nur `einrichtung = 'laeuft'`.
  - `POST /api/pult/marke/chat` – Nachricht beginnt (nach `lstrip`) mit `/`:
    - `skills.aufloesen(nachricht, "marke")` ist `None` → **400** `"Unbekannter Befehl. Verfügbar: /marke_neu – <beschreibung>"` (alle Befehle des Chats, ohne SQL).
    - `marke-neu`: `kontext.anhaenge` nicht leer → **400** `"Dateien bitte erst in der Einrichtung schicken"`. Rest leer → **400** `"Bitte so: /marke_neu Firmenname [Webseite]"`. Letztes Wort mit `https?://` ist die Webseite, der Rest der Name.
    - `pult_mandant_einrichten(name, von)` (`von` aus dem Körper, sonst `"Marken-Chat"`), dann `pult_marke_anlegen(id, "Neue Marke einrichten: <Name>[ Webseite: <url>]", {"skill": "marke-neu"})`. Lehnt die DB mit „Der Assistent arbeitet gerade“ ab, gilt `auftrag: null`.
    - Antwort `{"auftrag": str | None, "einrichtung": {"id", "name", "fortgesetzt"}}`. DB-Ablehnung beim Einrichten → 422 mit Grund.
    - Ohne `/` am Anfang: unverändert `{"auftrag"}`.
  - `GET /api/pult/marke` zusätzlich: `befehle: [{"befehl": "/marke_neu", "beschreibung"}]`, `einrichtung: "laeuft" | "abgebrochen" | None`, bei `laeuft` `einrichtung_stand` = `einrichtung.stand(name, profil, hat_logo, pflichtteil, einrichtung_stand)` (Profil aus `marken_spiegel.profil`, Logo aus dem gespiegelten `gestalt.logo`) und `pflichtteil`.
  - `POST /api/pult/marke/einrichtung/abschliessen {mandant, von}` → `pult_mandant_aktivieren` → `{"ok": true}`; DB-Ablehnung 422 mit Grund.
  - `POST /api/pult/marke/einrichtung/abbrechen {mandant, von}` → `pult_mandant_einrichtung_abbrechen` → `{"ok": true}`.
  - `POST /api/marke/arbeiter/{aid}/pflichtteil {pflichtteil?, stand?}` → `_in_arbeit(a)`, nur `art == "chat"` (sonst 422), Mandant aus dem Auftrag → `pult_mandant_pflichtteil_setzen(mandant, pflichtteil, stand)` → `{"pflichtteil", "stand"}`. Formprüfung vor SQL (Objekte, Schlüssel wie in Task 2), sonst 422.
  - `arbeiter_vorschlag`: `direkt` für einen Vorschlag, der nicht nur Text ändert (`not marken_prompt.ist_direkt(…)`), gilt nur, wenn der Mandant des Auftrags `einrichtung = 'laeuft'` hat; sonst wird nicht direkt übernommen (Vorschlag bleibt offen).

- [ ] **Step 1: Tests:**
  - `test_mandanten_liefert_einrichtung_und_filter`: SQL mit `einrichtung = 'laeuft'` nur bei `?einrichtung=1`; Feld `einrichtung` im Ergebnis.
  - `test_befehl_unbekannt_400_ohne_sql`: `/foo`, `/new`, `/neu` → 400, Detail enthält `/marke_neu`; `len(f.sql)` unverändert.
  - `test_marke_neu_ohne_namen_400`.
  - `test_marke_neu_legt_einrichtung_und_runde_an`: `/marke_neu Probe GmbH https://probe.de` → SQL `pult_mandant_einrichten('Probe GmbH', …)`, danach `pult_marke_anlegen('probe_gmbh', 'Neue Marke einrichten: Probe GmbH Webseite: https://probe.de'`; Antwort mit `einrichtung.id == "probe_gmbh"`.
  - `test_skill_form_gleich`: `/skill marke-neu Probe GmbH` → derselbe SQL-Aufruf.
  - `test_marke_neu_aktive_marke_422`: DB-Fehler „Diese Marke gibt es schon …“ → 422 mit Text.
  - `test_marke_neu_name_ungueltig_422`: DB-Fehler „Ungültiger Firmenname“ → 422.
  - `test_marke_neu_mit_anhaengen_400`.
  - `test_marke_neu_fortsetzen_waehrend_runde`: einrichten → `fortgesetzt: true`, anlegen wirft „Der Assistent arbeitet gerade“ → 200, `auftrag is None`.
  - `test_stand_liefert_befehle_und_einrichtung`: `befehle[0]["befehl"] == "/marke_neu"`; bei `laeuft` `einrichtung_stand.schritte` hat 7 Einträge.
  - `test_abschliessen_und_abbrechen`: richtige SQL-Aufrufe; DB-Ablehnung „Impressum fehlt“ → 422.
  - `test_arbeiter_pflichtteil`: in Arbeit → SQL mit Mandant des Auftrags; Auftrag nicht in Arbeit → 409; Form falsch (`pflichtteil: "x"`, Schlüssel `foo`) → 422 ohne SQL.
  - `test_vorschlag_direkt_farben_nur_in_einrichtung`: `direkt=True` mit `akzent` – Mandant aktiv → kein `pult_marke_uebernehmen`; Mandant `laeuft` → `pult_marke_uebernehmen` aufgerufen.
- [ ] **Steps 2–4:** Rot, umsetzen, grün; `test_marke_api.py` und `test_medien_mandant.py` komplett grün.
- [ ] **Step 5: Commit** `feat(marketing): /marke_neu in der Marken-API, Einrichtung abschliessen und abbrechen`

### Task 7: Vermittlerangaben im Newsletter-Fuß

**Files:**
- Modify: `claw/bloecke_mjml.py` (`pflicht_fuss`, `text_mit_fuss`), `claw/pult_render.py` (`mail_html`), `claw/seite_html.py` (`html`)
- Test: `claw/tests/test_bloecke_mjml.py`, `claw/tests/test_pult_render.py`, `tests/test_seite_html.py`

**Interfaces – Produces:** In allen vier Füßen steht `pflichtteil["vermittlerangaben"]` (getrimmt, escaped wie das Impressum) zwischen Impressum und Abmeldehinweis, nur wenn nicht leer. `seite_mail` nutzt `pflicht_fuss` und erbt es.

- [ ] **Step 1: Tests:** je Renderer `test_vermittlerangaben_unter_impressum` (Text erscheint, Position nach dem Impressum und vor dem Abmeldehinweis, `<` wird escaped) und `test_ohne_vermittlerangaben_unveraendert` (Ausgabe mit `"vermittlerangaben": ""` ist byte-gleich zur Ausgabe ohne den Schlüssel). Für `text_mit_fuss`: Reihenfolge Impressum, Vermittlerangaben, Abmeldehinweis.
- [ ] **Steps 2–4:** Rot, umsetzen, grün; `test_seite_mail.py` bleibt grün.
- [ ] **Step 5: Commit** `feat(marketing): Vermittlerangaben im Newsletter-Fuss`

### Task 8: Oberfläche (sales-claw)

**Files:**
- Modify: `sales-mcp/marketing_mandant.py`, `sales-mcp/ui_marke.py`
- Test: `sales-mcp/tests/test_marke_seite.py`

**Interfaces:**
- Consumes: API aus Task 6 (`GET /mandanten?einrichtung=1`, Antwort von `POST /marke/chat`, `GET /marke` mit `befehle`/`einrichtung`/`einrichtung_stand`/`pflichtteil`, `POST /marke/einrichtung/abschliessen|abbrechen`).
- Produces:
  - `marketing_mandant.einrichtungen() -> list[dict]` – GET `/mandanten?einrichtung=1`, wirft `PultFehler`. `waehlen`, `firma`, `umschalter` **unverändert**.
  - `ui_marke.adresse(..., einrichtung: str | None = None)` – hängt `einrichtung=<id>` an; `ziel(einrichtung: str | None) -> str` ersetzt die Konstante `ZIEL` in allen Weiterleitungen.
  - In `routen`: `async def marken_firma(request, form=None) -> tuple[str, list[dict], dict | None]` – `einrichtung` aus Query (GET) bzw. Formularfeld (POST). Nicht gesetzt → `marketing_mandant.firma` wie heute, dritter Wert `None`. Gesetzt und in `einrichtungen()` → `(id, liste, eintrag)`. Gesetzt, aber unbekannt: GET → wie nicht gesetzt; POST → 422 „Die Einrichtung ist abgeschlossen oder abgebrochen – bitte Seite neu laden. Nichts wurde geändert.“
  - Alle Handler der Seite (`marke`, `vorschau`, `senden`, `vorschlag_aktion`, `rueckgaengig`, `bearbeiten`) nutzen `marken_firma`; alle Formulare tragen ein verstecktes Feld `einrichtung`, wenn eine gewählt ist.
  - Neue Routen `POST /marketing/marke/einrichtung/abschliessen` und `/abbrechen` (CSRF, Feld `einrichtung` Pflicht). Abschließen → Weiterleitung auf `SEITE?reiter=profil` und setzt das Cookie `mk_mandant` auf die neue Firma (wie die Route `/marketing/mandant` in `ui_marketing.py`). Abbrechen → `SEITE` mit Meldung, die den Ordner `companys/<Name>/` nennt, der liegen bleibt.

**Verhalten:**
- `senden`: Nachricht beginnt mit `/` und hat Dateien → 422 „Befehle bitte ohne Dateien senden“ **vor** dem Ablegen. Der Körper an `/marke/chat` bekommt `"von": ui._ui_akteur(request)`. Enthält die Antwort `einrichtung.id`, Weiterleitung auf `/marketing/layouts?einrichtung=<id>&reiter=chat#ende`.
- Unter dem Eingabefeld eine Zeile „Befehle: /marke_neu – neue Marke einrichten“ aus `d["befehle"]`.
- In einer Einrichtung über dem Chat: „<Name> – in Einrichtung“, Link „Zurück zu <bisherige Firma>“ (`SEITE` ohne Parameter), Fortschrittsleiste aus `einrichtung_stand.schritte` (erledigt/offen, „Schritt n von 7“), Knopf „Marke anlegen“ nur bei `abschliessbar`, Knopf „Einrichtung abbrechen“ immer.
- Auf der normalen Marken-Seite: kleine Liste „In Einrichtung“ mit Links auf `?einrichtung=<id>` (nur wenn `einrichtungen()` nicht leer; Fehler der Liste blendet sie nur aus).

- [ ] **Step 1: Tests** (Fälschung `Falsch` aus `test_marke_seite.py`):
  - `test_befehlszeile_unter_eingabe`.
  - `test_senden_marke_neu_leitet_zur_einrichtung`: API-Antwort mit `einrichtung.id = "probe_gmbh"` → 303 auf `/marketing/layouts?einrichtung=probe_gmbh&reiter=chat#ende`; Körper enthält `von`.
  - `test_befehl_mit_anhang_abgewiesen_ohne_ablage`: 422, keine Datei im Medienordner, kein API-Aufruf.
  - `test_unbekannter_befehl_zeigt_grund`: API 400 mit Befehlsliste → Fehlerseite zeigt den Text.
  - `test_einrichtung_kopf_fortschritt_knoepfe`: `?einrichtung=probe_gmbh` (in der Einrichtungs-Liste) → API-Aufruf `/marke?mandant=probe_gmbh`, Seite zeigt „Probe GmbH – in Einrichtung“, „Schritt“, „Einrichtung abbrechen“; „Marke anlegen“ nur bei `abschliessbar: true`.
  - `test_formulare_tragen_einrichtung`: jedes `<form` der Seite enthält `name="einrichtung" value="probe_gmbh"`.
  - `test_cookie_auf_einrichtung_faellt_auf_vorgabe`: Cookie `mk_mandant=probe_gmbh` ohne Parameter → API-Aufruf mit `mandant=vibemind`.
  - `test_post_mit_veralteter_einrichtung_422`: `senden` mit `einrichtung=alt_weg` (nicht in der Liste) → 422, kein `/marke/chat`-Aufruf.
  - `test_abschliessen_setzt_cookie_und_leitet`: richtiger API-Aufruf, `Set-Cookie: mk_mandant=probe_gmbh`, 303 auf `…reiter=profil`; API 422 → Fehlerseite mit Grund.
  - `test_abbrechen_nennt_ordner`.
  - `test_liste_in_einrichtung_auf_normaler_seite`.
- [ ] **Steps 2–4:** Rot, umsetzen, grün; `test_marke_seite.py`, `test_marketing_pult.py`, `test_laden_marke_ui.py` grün.
- [ ] **Step 5: Commit** `feat(marketing-ui): /marke_neu im Marken-Chat, Einrichtung mit Fortschritt und Abschluss`

### Task 9: Auslieferung und Abnahme (Koordinator, kein Implementierer-Task)

**Auslieferung** – API am PC/VM und sales-claw zusammen ausliefern (wie beim Marken-Chat):

- [ ] **Step 1: Claims.** `WORKBOARD.md` lesen, Claim für Migration + Marketing-Dienste + sales-claw eintragen und sofort committen (nur die eigene Zeile stagen). Migrationsnummer ein letztes Mal gegen `origin/master` prüfen.
- [ ] **Step 2: Migration auf der VM.** Sicherung von `marketing.mandanten` und der Funktionen wie üblich (Dump vor dem Einspielen), dann `086_marke_einrichtung.sql` einspielen, danach `verify_086.sql` über `migration_probe` → `PROBE OK`.
- [ ] **Step 3: MOS pushen** (`origin master`). VM-API über `marketing-aktualisieren.sh` nachziehen.
- [ ] **Step 4: PC.** Im Haupt-Checkout die betroffenen Dateien per Byte-Vergleich als alt/neu/FREMD einordnen; bei FREMD abbrechen (nicht nur melden). Dann `git restore --source=<sha> --worktree -- <dateien>` (inkl. `skills/` und `claw/skills.py`, `claw/einrichtung.py`). Neu starten: `marketing_api` (:5510) und den Chat-/Marken-Arbeiter (`marketing_chat_arbeiter`, :8134) über `claw/scripts/marketing-dienste-starten.ps1 -Nur`.
- [ ] **Step 5: SC pushen** (`feat/stufe-1-fundament`) und `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`. Erwartet: „ALLE PRUEFUNGEN GRUEN“.

**Abnahme** (Spec „Abnahme“, auf der VM-Oberfläche):

- [ ] `/marke_neu Probe GmbH https://<echte Seite>` im Marken-Chat → Weiterleitung in die Einrichtung; „Probe GmbH“ ist im Umschalter nicht da, nur unter „In Einrichtung“; Newsletter-Anlegen, Vorlagen, Kampagnenplan und Reels zeigen sie nicht – auch nicht mit Cookie `mk_mandant=probe_gmbh` von Hand.
- [ ] Der Agent füllt aus der Webseite vor, fragt danach je Runde genau eine Lücke, zeigt „Schritt n von 7“.
- [ ] Ein erfundenes Impressum wird nicht übernommen (Hinweis sichtbar); ein im Chat geschriebenes schon.
- [ ] `/new`, `/neu`, `/foo` → Hinweis mit der Befehlsliste, kein Auftrag. `/marke_neu fin2gether` → abgelehnt.
- [ ] „Marke anlegen“ fehlt ohne Impressum; der direkte POST wird abgelehnt.
- [ ] „Marke anlegen“ → Firma aktiv und normal im Umschalter, Profil-Reiter zeigt die Abschnitte, Newsletter-Vorschau zeigt Impressum und Abmeldehinweis, Layout trägt Farben und Logo.
- [ ] Eine zweite Probe abbrechen und mit `/marke_neu <gleicher Name>` fortsetzen.
- [ ] Aufräumen (nur in der Abnahme): Wegwerf-Mandanten samt Aufträgen/Vorschlägen/Spiegel/Layout per SQL entfernen, Ordner `companys/Probe GmbH/` am PC löschen.
- [ ] Claims schließen, Worktrees entfernen.
