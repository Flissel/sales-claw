# Meeting-Mittelpunkt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jeder Kundentermin in Felix' Laden bekommt eine Termin-Akte mit „Beitreten“-Knopf, verknüpfte CRM-Kontakte, ein Briefing 30 Minuten vorher und eine lokale Mitschrift mit Auswertung und CRM-Vorschlägen.

**Architecture:** Neue, kleine Module in `sales-mcp/` (Akte, Teilnehmer, Link-Erkennung, Vexa-, Ollama- und Telegram-Client, Briefing, Auswertung). Dazu kommt ein Taktgeber-Dienst `sales-termine`, der Akten abgleicht, Briefings und Bots zeitgerecht auslöst und Mitschriften abholt. Die Termin-Seite `/termine/{uid}` kommt als `ui_termin.py` in die bestehende Starlette-UI. Vexa läuft als eigenes Compose-Projekt auf der VM, Ollama auf dem PC hinter Tailscale.

**Tech Stack:** Python 3.12, psycopg (über `server._q`), Starlette (UI), `icalendar` + `recurring_ical_events`, urllib (keine neuen HTTP-Bibliotheken), TypeScript/vitest (Kalender), Vexa v0.12.28 (Apache-2.0), faster-whisper small (CPU), Ollama auf dem PC.

**Spec:** `docs/superpowers/specs/2026-11-10-meeting-mittelpunkt-design.md`. Die Spec ist die Autorität. Bei Widerspruch gilt sie.

**Nicht in diesem Plan:** Rowboat-Notiz der Auswertung (§5.4 Punkt 7). Das ist Arbeit in **vibemind-os** (`spaces/rowboat/geschaeftsdaten/`, Sicht `sales.rowboat_ereignisse`) und bekommt einen eigenen, kleinen Plan, sobald Task 1 hier gemergt ist. Dieser Plan liefert dafür die Tabelle `termin_mitschriften` mit `auswertung_md`.

## Global Constraints

- Nur Schema `sales` (Felix' Laden). Kein Zugriff auf `sales_ivan`. Neue Tabellen kommen trotzdem über die Schema-Schleife in `db/provision.sql` in jeden Laden, damit `laden-anlegen.sql` konsistent bleibt (Spec §4).
- Gesperrt heißt: `compliance.sperrliste` (über `server._sperre`) **oder** `enrichment._loeschantrag` **oder** `enrichment._privat`. Gesperrte werden nie angelegt, nie verknüpft und erscheinen nie in Briefing, Akte, JSON, MCP oder Telegram-Hinweis (Spec §4, §5.1).
- In keinem Log stehen Mitschrift-Text, Teilnehmeradressen, Passcodes, `VEXA_API_KEY` oder `TELEGRAM_BOT_TOKEN`. Jedes neue Modul bekommt einen `caplog`-Test dafür (Spec §4, §10.9).
- Kundentext geht nur an `OLLAMA_URL`. Briefing und Auswertung importieren weder `gateway` noch einen anderen KI-Client (Spec §7, §10.8).
- Alles an Kunden läuft über `server._entwurf_erstellen` und die Freigabe (Spec §4).
- Schreibende DB-Tests nur gegen `sales_test`. Jeder neue Testmodul setzt `os.environ["SALES_DB_SCHEMA"]="sales_test"` vor `import server`. Testlauf (einer gleichzeitig):
  `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest -q <datei>`
- Bot-Parameter fest: `bot_name="VibeMind Mitschrift"`, `language="de"`, `recording_enabled=false`, `automatic_leave.max_wait_for_admission=1800000` (30 min) (Spec §5.4).
- Mitschrift-Status-Werte in der DB (ASCII): `geplant`, `wartet_auf_einlass`, `laeuft`, `fertig`, `ohne_aufnahme`, `fehlgeschlagen`, `kein_link`. Anzeige mit Umlaut („läuft“).
- Plattform-Werte: `google_meet`, `teams`, `zoom`, `jitsi`, `sonstige`.
- `activities` bleibt append-only. Mitschrift, Auswertung und Vorschläge liegen in eigenen, löschbaren Tabellen. In `activities` wird nur geschrieben, was Felix bestätigt (Termin-Ergebnis, Termin-Zeile für Kalendertermine, Wiedervorlagen).
- Kein neues HTTP-Paket. Clients nutzen `urllib.request` wie `konferenz.py`.
- Kein Deploy, kein `docker compose up`, kein SQL auf der VM, keine PC-Aufgabe ohne Felix' OK (Task 17 ist der Halt).
- Commits: Conventional Commits, Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Arbeitszweig `feat/meeting-mittelpunkt`, abgezweigt vom **aktuellen** `origin/feat/stufe-1-fundament` (vorher `git fetch`). Diesen Plan und die Spec per Cherry-Pick von `docs/meeting-mittelpunkt` mitnehmen.

## Review Focus

1. **Verschobener oder verschwundener Termin.** Ein Kalendertermin bekommt nach dem Anlegen der Akte eine neue Zeit (gleiche uid) oder verschwindet aus der Quelle. Erwartet: Bot und Briefing richten sich nach der neuen Zeit. Ein verschwundener künftiger Termin bekommt `abgesagt_am` und weder Bot noch Hinweis. Test in Task 5.
2. **Derselbe Termin doppelt.** Er steht in zwei Kalenderquellen, oder ein sales-claw-Termin taucht auch im verbundenen Kalender auf. Erwartet: genau eine Akte und ein Bot, sales-claw gewinnt bei `herkunft`. Test in Task 5.
3. **Vexa nicht erreichbar oder Abholen scheitert mitten drin.** Erwartet: Die Akte geht mit Grund auf `fehlgeschlagen`, wenn der Bot nicht startet. Scheitert das Abholen, bleibt der Status, und die nächste Runde versucht es wieder. Gelöscht wird bei Vexa **erst nach** dem Commit der lokalen Mitschrift. Test in Task 11.
4. **Ollama lange aus.** Erwartet: Das Briefing kommt rechtzeitig nur mit Fakten und Vermerk, der Telegram-Hinweis genau einmal. Auswertungen bleiben `offen` und werden später nachgeholt, eine je Runde, ohne Fehlerflut im Log. Tests in Task 9 und Task 11.
5. **uid mit `@`, `#` und `/` in Links.** Kalender-uids sehen so aus: `abc@google.com#2026-11-12T09:00:00+00:00`. Erwartet: Termin-Seite, JSON, Telegram-Link und Kalender-Dialog finden die Akte. Test in Task 12.

---

## Dateien

| Datei | Verantwortung |
|---|---|
| `db/provision.sql` (ändern) | Tabellen `termin_akten`, `termin_teilnehmer`, `termin_mitschriften`, `termin_vorschlaege` je Laden, mit Grants |
| `db/kalender-verbinden.sql` (ändern) | `kalender_termine` + `beschreibung`, `teilnehmer`, `konferenz` |
| `db/laden-anlegen.sql` (ändern) | neue Tabellen für neue Läden |
| `sales-mcp/termin_link.py` (neu) | Link, Plattform, Passcode und Einwahl aus Text erkennen |
| `sales-mcp/konferenz.py` (ändern) | `JITSI_BASIS` aus der Umgebung, Standard `https://meet.ffmuc.net` |
| `sales-mcp/kalenderquellen.py`, `server.py:kalendertermine_ersetzen` (ändern) | iCal-Felder für Beschreibung, Teilnehmer und Konferenz |
| `sales-mcp/teilnehmer.py` (neu) | eigene/Team-Adressen, Ressourcen, Sperren, Kundentermin-Regel, CRM-Verknüpfung |
| `sales-mcp/termin_akte.py` (neu) | Akten abgleichen, lesen, Status setzen |
| `sales-mcp/vexa.py` (neu) | Vexa-Client |
| `sales-mcp/ollama.py` (neu) | Ollama-Client (einziger KI-Weg für Kundentext) |
| `sales-mcp/betreiber_hinweis.py` (neu) | Telegram-Nachricht an Felix |
| `sales-mcp/briefing.py` (neu) | Faktenteil + KI-Text |
| `sales-mcp/auswertung.py` (neu) | Mitschrift → JSON → Markdown, Vorschläge, Kundenfassung |
| `sales-mcp/termin_takt.py` (neu) | Taktgeber-Dienst |
| `sales-mcp/ui_termin.py` (neu) | `/termine/{uid}`, JSON, Aktionen |
| `sales-mcp/ui.py`, `historie.py`, `kalender_sicht.py`, `kalender/src/fenster.ts` (ändern) | Verlinkung, Verlauf, Doppel-Schutz |
| `sales-mcp/server.py` (ändern) | MCP `termin_akte_lesen`, Einladungszeile, Löschantrag, Auskunft |
| `docker-compose.yml`, `deploy/update.sh`, `deploy/smoke.sh`, `.env.example` (ändern) | Dienst `sales-termine`, Umgebung |
| `deploy/vexa/` (neu) | Compose, `.env.example`, `vexa-anbinden.sh` |
| `scripts/ollama-pc.ps1`, `scripts/ollama-pc-aufgabe.ps1` (neu) | Ollama am PC starten und als Aufgabe registrieren |
| `docs/03_RUNBOOK.md`, `docs/06_DSGVO.md` (ändern) | Betrieb, Löschung |

---

### Task 1: Schema

**Files:**
- Modify: `db/provision.sql` (in der Schema-Schleife, nach dem `einstellungen`-Block ~:287-303)
- Modify: `db/kalender-verbinden.sql` (nach der `kalender_termine`-DDL ~:127)
- Modify: `db/laden-anlegen.sql`
- Test: `sales-mcp/tests/test_termin_schema.py`

**Interfaces:**
- Produces (Spalten, die alle späteren Tasks nutzen):
  - `termin_akten(uid text primary key, herkunft text not null check in ('sales-claw','kalender'), quelle_id uuid null, termin_activity_id uuid null, beginn timestamptz not null, ende timestamptz not null, zeitzone text not null default 'Europe/Berlin', titel text, thema text, beschreibung text, link text, plattform text null check in ('google_meet','teams','zoom','jitsi','sonstige'), passcode text, einwahl text, status text not null default 'geplant' check in (7 Werte), status_grund text, kein_bot boolean not null default false, will_zusammenfassung boolean not null default false, abgesagt_am timestamptz, vexa_meeting_id integer, vexa_plattform text, vexa_native_id text, bot_geschickt_am timestamptz, briefing_md text, briefing_stand text, briefing_mit_ki boolean, briefing_am timestamptz, hinweis_gesendet_am timestamptz, erstellt_am timestamptz not null default now(), geaendert_am timestamptz not null default now())`
  - `termin_teilnehmer(uid text references termin_akten(uid) on delete cascade, adresse text not null, name text, rolle text not null check in ('organisator','gast'), lead_id uuid null references leads(id) on delete set null, grund text, primary key (uid, adresse))`. `grund` ist bei `lead_id is null` gesetzt, z. B. `eigene Adresse`, `Team`, `Ressource`, `gesperrt`, `private Quelle`.
  - `termin_mitschriften(id uuid primary key default gen_random_uuid(), uid text not null unique references termin_akten(uid) on delete cascade, segmente jsonb not null, geholt_am timestamptz not null default now(), auswertung_status text not null default 'offen' check in ('offen','fertig','fehler','leer'), auswertung_json jsonb, auswertung_md text, auswertung_am timestamptz, modell text, entwurf_id uuid)`
  - `termin_vorschlaege(id uuid primary key default gen_random_uuid(), mitschrift_id uuid not null references termin_mitschriften(id) on delete cascade, art text not null check in ('termin_ergebnis','wiedervorlage','feld'), lead_id uuid null references leads(id) on delete cascade, daten jsonb not null, status text not null default 'offen' check in ('offen','bestaetigt','verworfen'), erstellt_am timestamptz not null default now(), erledigt_am timestamptz)`
  - `kalender_termine` + `beschreibung text`, `teilnehmer jsonb`, `konferenz text` (alle nullable)
  - Index `termin_akten(beginn)`, `termin_teilnehmer(lead_id)`.
  - Grants: `sales_app` bzw. `sales_app_<laden>` bekommt `select, insert, update, delete` auf die vier Tabellen. `sales_test` bekommt zusätzlich `truncate` (Muster `kalender-verbinden.sql:169-172`).

- [ ] **Step 1: Failing test** `test_termin_schema.py`:
  - `test_tabellen_und_spalten_da`: `information_schema.columns` für `sales_test` enthält alle oben genannten Spalten der vier Tabellen und die drei neuen in `kalender_termine`.
  - `test_status_check_lehnt_unbekanntes_ab`: Ein Insert mit `status='läuft'` (mit Umlaut) wirft `CheckViolation`.
  - `test_mitschrift_loescht_vorschlaege_mit`: `delete from termin_mitschriften` entfernt die zugehörigen `termin_vorschlaege`.
  - `test_akte_loeschen_kaskadiert`: Das Löschen der Akte entfernt Teilnehmer und Mitschrift.
- [ ] **Step 2:** Test laufen lassen. Erwartet: FAIL (Relation existiert nicht).
- [ ] **Step 3:** DDL in die drei SQL-Dateien schreiben (idempotent: `create table if not exists`, `add column if not exists`, CHECK per drop/add). Danach lokal gegen die Test-DB einspielen: `psql … -f db/provision.sql` und `psql … -v schema=sales_test -v besitzer=felix -f db/kalender-verbinden.sql`. Zweimal laufen lassen, um die Idempotenz zu beweisen.
- [ ] **Step 4:** Test laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(db): Tabellen fuer Termin-Akte, Teilnehmer, Mitschrift, Vorschlaege`.

### Task 2: Link-Erkennung und Jitsi-Server

**Files:**
- Create: `sales-mcp/termin_link.py`
- Modify: `sales-mcp/konferenz.py:56` (`JITSI_BASIS`)
- Test: `sales-mcp/tests/test_termin_link.py`, `sales-mcp/tests/test_konferenz.py` (Erwartungen `meet.jit.si` → `meet.ffmuc.net`)

**Interfaces:**
- Produces: `erkennen(*texte: str) -> dict | None`. Rückgabe `{"link": str, "plattform": str, "passcode": str, "einwahl": str}`, sonst `None`. Der erste Treffer in der Reihenfolge der Texte gewinnt, also Konferenzfeld vor Ort vor Beschreibung.
- Produces: `jitsi_hosts() -> set[str]` liest `JITSI_HOSTS` (Komma-Liste) zur Laufzeit. Immer enthalten: `meet.jit.si` und der Host aus `konferenz.jitsi_basis()`.
- Produces: `konferenz.jitsi_basis() -> str` liest `JITSI_BASIS` zur Laufzeit, Standard `https://meet.ffmuc.net`. `jitsi_raum()` nutzt sie.

- [ ] **Step 1: Failing tests** `test_termin_link.py`:
  ```python
  def test_meet():   assert erkennen("Ort: https://meet.google.com/abc-defg-hij")["plattform"] == "google_meet"
  def test_teams():  assert erkennen("https://teams.microsoft.com/l/meetup-join/19%3ameeting_X%40thread.v2/0")["plattform"] == "teams"
  def test_teams_live(): assert erkennen("https://teams.live.com/meet/9312345")["plattform"] == "teams"
  def test_zoom_subdomain(): r = erkennen("https://us02web.zoom.us/j/81234567890?pwd=abc"); assert (r["plattform"], r["passcode"]) == ("zoom", "abc")
  def test_jitsi_ffmuc(): assert erkennen("https://meet.ffmuc.net/Raum1")["plattform"] == "jitsi"
  def test_jitsi_aus_liste(monkeypatch): monkeypatch.setenv("JITSI_HOSTS", "video.firma.de"); assert erkennen("https://video.firma.de/x")["plattform"] == "jitsi"
  def test_sonstiger_link_nur_wenn_kein_bekannter(): assert erkennen("https://example.com/x") is None
  def test_passcode_aus_text(): assert erkennen("https://teams.microsoft.com/l/meetup-join/x", "Kenncode: 7Hx9") ["passcode"] == "7Hx9"
  def test_einwahl(): assert erkennen("https://meet.google.com/abc-defg-hij", "Telefon: +49 30 1234567 PIN: 123 456#")["einwahl"].startswith("+49 30 1234567")
  def test_vorrang_reihenfolge(): assert "zoom" == erkennen("https://zoom.us/j/1234567890", "https://meet.google.com/abc-defg-hij")["plattform"]
  def test_kein_link(): assert erkennen("", None, "Büro 3. Stock") is None
  ```
  Ein beliebiger Link ohne bekannte Plattform ergibt `None`, nicht `sonstige`. `sonstige` nur für bekannte Videodienste ohne Bot-Unterstützung (Webex, GoTo: `webex.com`, `gotomeeting.com`, `meet.goto.com`). Test `test_webex_sonstige`.
  In `test_konferenz.py` die fünf `meet.jit.si`-Erwartungen auf `https://meet.ffmuc.net/` umstellen. Neu: `test_jitsi_basis_aus_umgebung` (`JITSI_BASIS=https://jitsi.example.org` → Raum beginnt damit).
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Musterliste als Modul-Konstante `MUSTER: tuple[tuple[str, re.Pattern], ...]`. Hosts nach dem Parsen mit `urllib.parse` prüfen, nie als Teilstring (Subdomain-Regel wie Vexa `_host_is`). Satzzeichen am Link-Ende abschneiden (`>`, `)`, `.`, `,`).
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS, `test_konferenz.py` ebenfalls grün.
- [ ] **Step 5:** Commit `feat(termin): Link-Erkennung je Plattform, Jitsi auf meet.ffmuc.net`.

### Task 3: iCal-Abgleich mit Beschreibung, Teilnehmern, Konferenz

**Files:**
- Modify: `sales-mcp/kalenderquellen.py` (`_aufklappen` ~:343)
- Modify: `sales-mcp/server.py:3670` (`kalendertermine_ersetzen`)
- Test: `sales-mcp/tests/test_kalenderquellen.py` (erweitern), `sales-mcp/tests/test_kalender_abgleich.py` (erweitern)

**Interfaces:**
- Produces: Jeder Termin aus `kalenderquellen.hole()` trägt zusätzlich:
  - `beschreibung: str` (max 4000 Zeichen, einzeilig bereinigt: Whitespace-Läufe → ein Leerzeichen)
  - `teilnehmer: list[{"adresse": str (lower), "name": str, "rolle": "organisator"|"gast", "art": str}]`. `art` ist der CUTYPE in Kleinbuchstaben, Standard `individual`. Höchstens 50 Einträge, damit Webinare erkennbar bleiben: Zusätzlich gibt es `teilnehmer_anzahl: int` mit der echten Zahl.
  - `konferenz: str` aus `URL`, `X-GOOGLE-CONFERENCE`, `X-MICROSOFT-SKYPETEAMSMEETINGURL`, `X-MICROSOFT-ONLINEMEETINGCONFLINK`, sonst `""`.
- Produces: `kalender_termine.beschreibung/teilnehmer/konferenz` werden nur geschrieben, wenn `mit_details` wahr ist, sonst NULL (gleiche Regel wie `titel`/`ort`). `teilnehmer` wird als `{"liste": [...], "anzahl": n}` gespeichert.
- Google-Quellen (`google_kalender.FELDER_TERMINE`) bleiben unverändert. Das ist Teil B (Spec §2 Nicht-Ziele).

- [ ] **Step 1: Failing tests**:
  - `test_vevent_mit_teilnehmern`: Ein ICS mit `ORGANIZER;CN=Kunde:mailto:K@Firma.de`, zwei `ATTENDEE` (einer `CUTYPE=ROOM`), `DESCRIPTION` mit Teams-Link und `X-MICROSOFT-SKYPETEAMSMEETINGURL`. Erwartet: drei Teilnehmer, Adressen klein geschrieben, Organisator mit Rolle `organisator`, Raum mit `art == "room"`, `konferenz` = Teams-URL.
  - `test_beschreibung_gekappt_und_einzeilig`: 10 000 Zeichen mit Zeilenumbrüchen ergeben höchstens 4000 Zeichen ohne `\n`.
  - `test_webinar_anzahl`: 60 ATTENDEE ergeben `len(teilnehmer) == 50` und `teilnehmer_anzahl == 60`.
  - `test_privat_speichert_keine_details` (in `test_kalender_abgleich.py`, Muster :156): Für eine `bereich='privat'`-Quelle eines fremden Besitzers sind `beschreibung`, `teilnehmer` und `konferenz` NULL, und `caplog.text` enthält keine Teilnehmeradresse.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. `mailto:` abstreifen, CN als Name, `ROLE=CHAIR` oder `ORGANIZER` zählt als organisator. Die Felder bleiben in der Child-Process-Grenze von `_aufklappen_mit_zeitgrenze`, damit die Rückgabe serialisierbar bleibt.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(kalender): Beschreibung, Teilnehmer und Konferenzlink aus iCal uebernehmen`.

### Task 4: Teilnehmer und CRM-Verknüpfung

**Files:**
- Create: `sales-mcp/teilnehmer.py`
- Test: `sales-mcp/tests/test_teilnehmer.py`

**Interfaces:**
- Consumes: `server._q`, `server._sperre(email, phone) -> str`, `server._loeschantrag(enr)`, `server._privat(enr)`, `mail_dispatch.EMAIL_ABSENDER`, Tabellen `post_konten`, `kalender_konten`, `termin_teilnehmer`.
- Produces:
  - `nicht_extern() -> set[str]`. Liefert alle Adressen (lower) aus `post_konten.adresse` (alle Besitzer, also auch Team), `kalender_konten.adresse`, `EMAIL_ABSENDER`, `SMTP_USER`, `postfach.IMAP_USER` und der Env-Liste `TERMIN_TEAM_ADRESSEN` (Komma).
  - `ist_ressource(adresse: str, art: str) -> bool`. Wahr bei `art in {"room","resource","group"}`, bei Local-Part `noreply`, `no-reply`, `donotreply`, `do-not-reply`, und bei Domain-Endung `resource.calendar.google.com` oder `group.calendar.google.com`.
  - `sperrgrund(adresse: str) -> str`. Liefert `""` oder einen Grund: `_sperre(adresse, "")`, sonst ein Lead mit dieser Adresse und `_loeschantrag` oder `_privat`.
  - `ist_kundentermin(herkunft: str, bereich: str, teilnehmer: list[dict], anzahl: int) -> tuple[bool, str]`. Regel aus Spec §3:
    - `herkunft == "sales-claw"` → `(True, "")`.
    - `bereich == "privat"` → `(False, "private Quelle")`.
    - `anzahl > 10` → `(False, "mehr als 10 Teilnehmer")`.
    - Keine externe Adresse (nicht in `nicht_extern()`, keine Ressource) → `(False, "keine externen Teilnehmer")`.
  - `FREEMAIL: frozenset[str]` mit mindestens `gmail.com, googlemail.com, web.de, gmx.de, gmx.net, gmx.at, gmx.ch, t-online.de, outlook.com, outlook.de, hotmail.com, hotmail.de, live.com, live.de, yahoo.com, yahoo.de, icloud.com, me.com, mail.de, freenet.de, posteo.de, mailbox.org, protonmail.com, proton.me, aol.com`.
  - `firma_aus_domain(adresse: str) -> str`. Liefert `""` bei Freemail, sonst den Domain-Stamm mit großem Anfangsbuchstaben (`k@mueller-bau.de` → `Mueller-bau`).
  - `verknuepfen(uid: str, teilnehmer: list[dict], *, darf_anlegen: bool) -> list[dict]`. Schreibt `termin_teilnehmer` per Upsert und gibt die Zeilen zurück.
    - Adresse in `nicht_extern()` → `grund="eigene Adresse"` (Felix-Adressen) bzw. `"Team"` (Team-Adressen).
    - Ressource → `"Ressource"`.
    - `sperrgrund` → `"gesperrt"`. Der echte Grund wird nicht gespeichert.
    - Bekannte Adresse → `lead_id` aus `select id from leads where lower(email)=%s order by created_at limit 1`.
    - Unbekannt und `darf_anlegen` → `insert into leads (name, email, company, source, consent_status, enrichment)` mit `source='aus Kalender'`, `consent_status='unknown'`, `name` = CN oder Local-Part, `company` = `firma_aus_domain`, `enrichment={"art":"kontakt","aus_termin":uid}`.
    - Unbekannt und nicht `darf_anlegen` → `grund="private Quelle"`.

- [ ] **Step 1: Failing tests** (alle gegen `sales_test`, Fixture leert `leads`, `termin_teilnehmer`, `termin_akten`, `post_konten`):
  - `test_bekannter_gast_verknuepft`
  - `test_unbekannter_gast_angelegt`: `source == "aus Kalender"`, `consent_status == "unknown"`, `company == "Firma"` bei `x@firma.de`.
  - `test_freemail_ohne_firma`
  - `test_eigene_adresse_nicht_angelegt`: Adresse aus `post_konten` mit `besitzer='felix'`, dazu `EMAIL_ABSENDER`.
  - `test_team_adresse_nicht_angelegt`: Adresse über `TERMIN_TEAM_ADRESSEN`.
  - `test_gesperrte_adresse_nicht_angelegt`: Sperrliste-Eintrag in `compliance_test`. Danach existiert kein Lead, und `grund == "gesperrt"`.
  - `test_loeschantrag_lead_nicht_verknuepft`: `lead_id is None`, `grund == "gesperrt"`.
  - `test_ressource_und_noreply`
  - `test_kundentermin_regeln`: parametrisiert über die vier Fälle oben plus „nur Ivan“ (Team) → False und „Webinar 30“ → False.
  - `test_kein_log_mit_adresse`: `caplog` mit DEBUG enthält keine der Testadressen.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(termin): Teilnehmer klassifizieren und mit dem CRM verknuepfen`.

### Task 5: Termin-Akte abgleichen und lesen

**Files:**
- Create: `sales-mcp/termin_akte.py`
- Modify: `sales-mcp/kalender_sicht.py:30` (`kundenzeilen` überspringt Payload mit `aus_kalender: true`)
- Test: `sales-mcp/tests/test_termin_akte.py`

**Interfaces:**
- Consumes: `termin_link.erkennen`, `teilnehmer.ist_kundentermin`, `teilnehmer.verknuepfen`, `kalender_sicht.kundenzeilen()`, `server.kalenderquellen_lesen`, Tabelle `kalender_termine`, `post_struktur.container_besitzer()`, `kalender_sichtbarkeit.details_speichern`.
- Produces:
  - `abgleichen(jetzt: datetime) -> dict`. Gibt `{"neu": int, "geaendert": int, "abgesagt": int}` zurück.
    - Fenster: `jetzt - 1 Tag` bis `jetzt + 30 Tage`.
    - Quellen: sales-claw-`termin`-Zeilen (nicht abgesagt; `beginn` aus `datum`+`uhrzeit` in Europe/Berlin, `ende` = `beginn + dauer_minuten`; Link aus `ort`, Lead als Gast) und `kalender_termine` aus aktiven Quellen mit `details_speichern`.
    - Pro uid genau eine Akte. sales-claw gewinnt `herkunft`.
    - Zeit-, Titel- und Link-Änderungen werden nachgezogen und setzen `geaendert_am`. Ist der Status noch `geplant`, wird `briefing_stand` geleert, damit das Briefing neu entsteht.
    - Eine künftige Akte, deren Termin in keiner Quelle mehr steht, bekommt `abgesagt_am`. Das gilt auch für `termin_abgesagt`.
    - Ohne Link: `status='kein_link'`. Kommt ein Link dazu, wird `kein_link` zurück auf `geplant` gesetzt.
    - Nicht-Kundentermine bekommen keine Akte.
  - `lesen(uid: str) -> dict | None`. Liefert die Akte als Dict, gesperrte Teilnehmer (`grund == "gesperrt"`) fehlen ganz. `passcode` ist enthalten, das Dict wird nie geloggt. Schlüssel:
    `uid, herkunft, beginn, ende, zeitzone, titel, thema, beschreibung, beitreten{link,plattform,passcode,einwahl}, teilnehmer[{name,adresse,rolle,lead_id,grund}], status, status_grund, kein_bot, will_zusammenfassung, abgesagt, briefing{markdown,mit_ki,am}|None, mitschrift{id,segmente,auswertung_status,auswertung_md}|None, vorschlaege[...]`
  - `status_setzen(uid: str, status: str, grund: str = "", **felder) -> None`. `felder` aus der Menge der `termin_akten`-Spalten, sonst `ValueError`.
  - `hat_gesperrte(uid: str) -> bool`.
  - `akten_eines_leads(lead_id) -> list[str]`.

- [ ] **Step 1: Failing tests**:
  - `test_salesclaw_termin_ergibt_akte`: `server.termin_bestaetigen(lead, "2099-01-10", "10:00", ort="https://meet.ffmuc.net/R1")` → Akte mit `plattform == "jitsi"`, Teilnehmer = Lead.
  - `test_kalendertermin_mit_externem_ergibt_akte_und_kontakt`
  - `test_nur_team_und_webinar_keine_akte` (Spec §10 1a)
  - `test_private_quelle_keine_akte`
  - `test_verschoben_zieht_zeit_nach` (Review Focus 1): gleiche uid, neue Zeit in `kalender_termine`, zweiter `abgleichen` → neues `beginn`, `briefing_stand is None`.
  - `test_verschwunden_wird_abgesagt` (Review Focus 1)
  - `test_doppelt_ergibt_eine_akte` (Review Focus 2): gleiche uid in zwei Quellen plus als sales-claw-Termin → eine Akte, `herkunft == "sales-claw"`.
  - `test_ohne_link_kein_link_status`, `test_link_nachgetragen_wird_geplant`
  - `test_lesen_ohne_gesperrte`
  - `test_kundenzeilen_ueberspringt_aus_kalender` (für die spätere Bestätigung aus Task 12)
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Upsert mit `insert … on conflict (uid) do update`. Zeiten intern als aware UTC.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(termin): Termin-Akte aus sales-claw- und Kalenderterminen`.

### Task 6: Vexa-Client

**Files:**
- Create: `sales-mcp/vexa.py`
- Test: `sales-mcp/tests/test_vexa.py` (lokaler `HTTPServer`-Stub nach dem Muster `meet_stub` in `test_konferenz.py`)

**Interfaces:**
- Env (zur Laufzeit gelesen): `VEXA_URL` (Standard `http://vexa-lite:8056`), `VEXA_API_KEY`, `VEXA_TIMEOUT_S` (20), `VEXA_LOBBY_WARTEN_MS` (1800000).
- Produces:
  - `class VexaFehler(Exception)`. Die Meldung enthält nie den Schlüssel.
  - `konfiguriert() -> bool`
  - `bot_schicken(meeting_url: str) -> dict`. Ruft `POST /bots` mit genau `{"meeting_url", "bot_name": "VibeMind Mitschrift", "language": "de", "recording_enabled": False, "automatic_leave": {"max_wait_for_admission": VEXA_LOBBY_WARTEN_MS}}` auf und gibt `{"meeting_id": int, "plattform": str, "native_id": str, "status": str}` zurück.
  - `meeting_lesen(meeting_id: int) -> dict`. Gibt `{"status": str, "grund": str, "ende_grund": str}` zurück, Quelle `GET /meetings` (Liste filtern; gibt es `GET /meetings/{id}`, ist das zu bevorzugen). `grund` kommt aus `data.reason`, `ende_grund` aus `data.completion_reason`.
  - `segmente_holen(meeting_id: int) -> list[dict]`. Quelle `GET /transcripts/by-id/{id}`, Elemente `{"sprecher": str, "beginn": str (ISO aus absolute_start_time), "text": str, "sprache": str}`, sortiert nach `beginn`.
  - `bot_stoppen(plattform: str, native_id: str) -> None`. Ruft `DELETE /bots/{plattform}/{quote(native_id, safe='@.')}` auf, 404 zählt als Erfolg.
  - `meeting_loeschen(meeting_id: int) -> None`. Ruft `DELETE /meetings/{id}` auf, 404 zählt als Erfolg.
  - `abbilden(vexa_status: str) -> str`. `requested`, `joining`, `awaiting_admission` → `wartet_auf_einlass`; `active` → `laeuft`; `completed` → `fertig`; `failed` → `fehlgeschlagen`; alles andere → `wartet_auf_einlass`.
- Header `X-API-Key`. Ohne Schlüssel wirft jeder Aufruf `VexaFehler("VEXA_API_KEY fehlt")`.

- [ ] **Step 1: Failing tests**: `test_bot_body_exakt` (Stub prüft JSON-Körper und Header), `test_segmente_sortiert_und_abgebildet`, `test_stoppen_404_ok`, `test_native_id_mit_at` (Pfad `/bots/jitsi/R1@meet.ffmuc.net`), `test_fehler_ohne_schluessel_im_text` (Stub antwortet 500, Fehlermeldung und `caplog` enthalten den Schlüssel nicht), `test_abbilden` (parametrisiert).
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(termin): Vexa-Client`.

### Task 7: Ollama-Client mit Endpunkt-Schranke, PC-Skripte

**Files:**
- Create: `sales-mcp/ollama.py`
- Create: `scripts/ollama-pc.ps1`, `scripts/ollama-pc-aufgabe.ps1`
- Test: `sales-mcp/tests/test_ollama.py`

**Interfaces:**
- Env: `OLLAMA_URL` (kein Standard; leer heißt nicht konfiguriert), `OLLAMA_MODELL` (Standard `qwen2.5:7b`, Task 17 kann umstellen), `OLLAMA_TIMEOUT_S` (300).
- Produces:
  - `class OllamaFehler(Exception)`
  - `erreichbar() -> bool`: `GET {OLLAMA_URL}/api/tags`, 3 s Zeitlimit. Nie eine Exception.
  - `chat(system: str, nutzer: str, *, als_json: bool = False) -> str`: `POST {OLLAMA_URL}/api/chat` mit `{"model", "messages", "stream": false, "options": {"temperature": 0.2}}` und `"format": "json"` bei `als_json`. Gibt `message.content` zurück.
- `scripts/ollama-pc.ps1` (Muster `Vibemind_V1/scripts/sales_stt_pc.ps1`):
  - idempotent: endet, wenn `http://127.0.0.1:11434/api/tags` 200 liefert;
  - sonst `OLLAMA_MODELS=E:\ollama\models` und `OLLAMA_HOST=127.0.0.1:11434` setzen und `ollama serve` versteckt starten, Log nach `%LOCALAPPDATA%\VibeMind\logs\ollama\`;
  - danach `tailscale serve --bg --tcp 11434 tcp://127.0.0.1:11434`.
- `scripts/ollama-pc-aufgabe.ps1`: registriert die Aufgabe „VibeMind Ollama“ bei Anmeldung und alle 5 Minuten (Muster `register-bubble-sync-task.ps1`, `ShouldProcess`).

- [ ] **Step 1: Failing tests**:
  - `test_nicht_konfiguriert`: ohne `OLLAMA_URL` gilt `erreichbar() is False`, und `chat` wirft `OllamaFehler`.
  - `test_chat_body` (Stub)
  - `test_einziger_endpunkt` (Spec §7, §10.8): `urllib.request.urlopen` patchen und alle URLs sammeln. Dann `briefing.erstellen` (Task 9) und `auswertung.auswerten` (Task 10) mit Stub-Ollama aufrufen; alle gesammelten Hosts == Host von `OLLAMA_URL`. In Task 7 als `pytest.importorskip("briefing")` anlegen, damit der Test ab Task 9/10 automatisch scharf wird.
  - `test_keine_fremden_ki_importe`: `ast` über `briefing.py`, `auswertung.py` und `ollama.py`. Kein Import von `gateway`, `openai`, `anthropic`, `requests`, `httpx`. `importorskip` wie oben.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL bzw. SKIP für die beiden Schranken-Tests.
- [ ] **Step 3:** Client und beide Skripte schreiben. Die Skripte werden **nicht** ausgeführt (Task 17).
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS bzw. SKIP.
- [ ] **Step 5:** Commit `feat(termin): Ollama-Client und PC-Startskripte`.

### Task 8: Telegram-Hinweis an Felix

**Files:**
- Create: `sales-mcp/betreiber_hinweis.py`
- Test: `sales-mcp/tests/test_betreiber_hinweis.py`

**Interfaces:**
- Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_API_BASIS` (Standard `https://api.telegram.org`).
- Produces: `senden(text: str, *, link_vorschau: bool = False) -> bool`. Wahr nur bei HTTP 200 und `ok`. Nie eine Exception. Importiert `server` **nicht**.
- Bei Fehlern wird nur `HTTP <code>` bzw. der Fehlertyp geloggt, nie Text, Token oder Chat-ID.

- [ ] **Step 1: Failing tests**: `test_senden_ok` (Stub prüft `chat_id`, `text`, `disable_web_page_preview`), `test_ohne_konfiguration_false`, `test_kein_import_von_server` (`"server" not in sys.modules` nach frischem Import in einem Subprozess), `test_log_ohne_token_und_text`.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren (urllib-POST, Formular-kodiert).
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(termin): Telegram-Hinweis an den Betreiber`.

### Task 9: Briefing

**Files:**
- Create: `sales-mcp/briefing.py`
- Test: `sales-mcp/tests/test_briefing.py`

**Interfaces:**
- Consumes: `termin_akte.lesen`, `historie.kontakt_historie(lead_id, tage=365)`, `server._offene_wiedervorlagen(lead_id)`, Tabelle `leads`, frühere `termin_mitschriften.auswertung_json` der Akten desselben Leads (`termin_akte.akten_eines_leads`), `ollama.erreichbar`, `ollama.chat`.
- Produces:
  - `fakten(uid: str) -> dict`. Je verknüpftem, nicht gesperrtem Lead: `name, rolle (title), firma, quelle (source), erster_kontakt (created_at, Datum), letzte_kontakte (max 5 aus kontakt_historie), offene_wiedervorlagen, painpoints (aus früheren Auswertungen, max 8, mit Datum)`. Dazu `ziel` (Thema und gekürzte Beschreibung) und `beginn`.
  - `fakten_markdown(f: dict) -> str`. Abschnitte `## Wer`, `## Letzte Kontakte`, `## Offen`, `## Painpoints aus früheren Gesprächen`, `## Ziel`. Leere Abschnitte erscheinen als „—“.
  - `erstellen(uid: str) -> dict`. Gibt `{"markdown": str, "mit_ki": bool, "stand": str}` zurück. `stand` ist sha256 über `json.dumps(fakten, sort_keys=True, default=str)`. Mit Ollama steht oben `## Kurz` mit 3–5 Sätzen, sonst die Zeile `_ohne KI-Text_`.
  - `hinweis_text(akte: dict, ui_basis: str) -> str`. Genau vier Zeilen: `🗓 {HH:MM} {Kunde}`, `{Thema}`, `Briefing öffnen: {ui_basis}/termine/{quote(uid, safe='')}`, `Beitreten: {link}`. `{Kunde}` ist der erste verknüpfte Lead mit Firma in Klammern, sonst der Titel. Ohne Link entfällt die letzte Zeile. Keine weiteren Kundendaten.

- [ ] **Step 1: Failing tests**:
  - `test_fakten_inhalt`
  - `test_ohne_ollama_nur_fakten` (Review Focus 4): `ollama.erreichbar` auf False patchen → `mit_ki is False`, `"_ohne KI-Text_" in markdown`.
  - `test_mit_ollama_kurztext`
  - `test_stand_aendert_sich_mit_neuer_mail`
  - `test_gesperrter_lead_fehlt`
  - `test_hinweis_nur_vier_zeilen_ohne_adressen`: keine E-Mail-Adresse und keine Telefonnummer im Text, uid mit `#` korrekt kodiert.
  - Der `importorskip`-Schranken-Test aus Task 7 wird jetzt aktiv und muss grün sein.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Prompt: System = „Du bereitest Felix auf ein Kundengespräch vor. Antworte auf Deutsch in 3–5 Sätzen, nur aus den gegebenen Fakten, nichts erfinden.“, Nutzer = `fakten_markdown`.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(termin): Briefing mit Faktenteil und lokalem KI-Text`.

### Task 10: Auswertung, Vorschläge, Kundenfassung

**Files:**
- Create: `sales-mcp/auswertung.py`
- Test: `sales-mcp/tests/test_auswertung.py`, Fixture `sales-mcp/tests/daten/mitschrift_beispiel.json` (erfundenes deutsches Gespräch, ~40 Segmente, zwei Sprecher)

**Interfaces:**
- Consumes: `ollama.chat(..., als_json=True)`.
- Produces:
  - `ABSCHNITTE: tuple[tuple[str, str], ...]`. Die Reihenfolge aus Spec §5.4 Punkt 5 als Paare (JSON-Schlüssel, Überschrift):
    `("kurzfassung","Kurzfassung"), ("painpoints","Painpoints"), ("ziele","Ziele und Wünsche"), ("fakten","Zahlen und Fakten"), ("einwaende","Einwände und Bedenken"), ("zusagen_felix","Zusagen von Felix"), ("zusagen_kunde","Zusagen des Kunden"), ("naechste_schritte","Nächste Schritte"), ("beteiligte","Entscheider und Beteiligte"), ("offene_fragen","Offene Fragen"), ("stimmung","Stimmung")`
  - `auswerten(segmente: list[dict]) -> dict`. Gibt ein JSON-Dict mit allen Schlüsseln aus `ABSCHNITTE` zurück, dazu `ergebnis: {"stattgefunden": bool, "erfolg": bool|None, "was": str}`.
    - `painpoints` ist eine Liste von `{"zitat": str, "zeit": "mm:ss", "sprecher": str}`. Die Zeit ist relativ zum ersten Segment und wird **vom Code** aus dem Segment gesetzt, auf das das Modell per Index verweist (`{"zitat", "segment": int}`), nie vom Modell geraten.
    - `zusagen_felix` und `naechste_schritte` sind Listen von `{"text": str, "datum": "YYYY-MM-DD"|null}`.
    - Alle anderen Abschnitte sind Listen von Strings, nur `kurzfassung` und `stimmung` sind Strings.
    - Lange Mitschriften werden in Stücke von höchstens `AUSWERTUNG_STUECK_ZEICHEN = 12000` Zeichen geteilt, je Stück ausgewertet und dann zusammengeführt (Listen vereinigen, Duplikate per normalisiertem Text entfernen, `kurzfassung` aus den Stück-Kurzfassungen per zweitem Aufruf).
    - Ungültiges JSON → ein zweiter Versuch, dann `OllamaFehler`.
  - `markdown(a: dict) -> str`. `## {Überschrift}` je Abschnitt in der festen Reihenfolge. Painpoint-Zeile: `- „{zitat}“ ({zeit}, {sprecher})`. Leere Abschnitte: `- —`. Keine Tabellen.
  - `vorschlaege(a: dict, lead_ids: list[str]) -> list[dict]`. Elemente `{"art", "lead_id", "daten"}`:
    - ein `termin_ergebnis` mit `daten = a["ergebnis"]` für den ersten Lead;
    - je `zusagen_felix`-Eintrag eine `wiedervorlage` mit `daten = {"faellig_am": datum or heute+3 Tage, "notiz": text}`;
    - `feld`-Vorschläge nur, wenn `a` den optionalen Schlüssel `felder: {"title"?, "company"?}` enthält.
  - `kundenfassung(a: dict, anrede: str) -> str`. Klartext für die E-Mail: Anrede, Abschnitte Kurzfassung, Ziele und Wünsche, Zusagen (beide Seiten), Nächste Schritte und Offene Fragen, Gruß. **Nie** Painpoints, Einwände, Stimmung oder Beteiligte.
- Prompt-Aufbau ist Builder-Sache (Spec §8). Pflicht: Antwort nur als JSON nach Schema, deutsch, „Painpoints = Probleme, Ärger, Kosten, Zeitverlust des Kunden, wörtlich zitiert“.

- [ ] **Step 1: Failing tests** (Ollama per Stub, der feste JSON-Antworten liefert):
  - `test_markdown_alle_abschnitte_in_reihenfolge` (Spec §10.6)
  - `test_painpoint_zeit_aus_segment`: Segment 5 hat `beginn` 75 s nach dem ersten → `"01:15"`.
  - `test_stueckelung`: Eine 30 000-Zeichen-Mitschrift ergibt drei Stück-Aufrufe und einen Zusammenführ-Aufruf. Doppelte Painpoints erscheinen nur einmal.
  - `test_kaputtes_json_einmal_wiederholt`
  - `test_vorschlaege`
  - `test_kundenfassung_ohne_interna`: Texte aus `einwaende`, `stimmung` und `painpoints` kommen nicht vor.
  - `test_kein_log_mit_mitschrift`: Kein Segmenttext steht in `caplog`.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS. Die Schranken-Tests aus Task 7 sind jetzt alle aktiv und grün.
- [ ] **Step 5:** Commit `feat(termin): Auswertung der Mitschrift als Markdown mit Vorschlaegen`.

### Task 11: Taktgeber `sales-termine`

**Files:**
- Create: `sales-mcp/termin_takt.py`
- Modify: `docker-compose.yml` (neuer Dienst `sales-termine` nach dem Muster `sales-kalender`; Image `sales-claw-sales-mcp:local`, `command: python termin_takt.py`, Umgebung = Anker `*sales_mcp_umgebung` plus `VEXA_*`, `OLLAMA_*`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `UI_BASIS_URL`, `JITSI_HOSTS`, `TERMIN_TEAM_ADRESSEN`, `TERMIN_TAKT_S`; keine `ports:`; zusätzlich im externen Netz `vexa` mit `name: vexa_default`)
- Modify: `deploy/update.sh` (`KERN_OPTIONAL` + `sales-termine`), `deploy/smoke.sh` (eigener Abschnitt nach Muster Abschnitt 20/21: läuft er nicht, wird er übersprungen; Vexa-Gesundheit nur im Vollmodus), `sales-mcp/tests/test_laden_parameter.py` (Containerliste), `.env.example` (Block „Meeting-Mittelpunkt“ mit allen neuen Variablen, ohne Werte)
- Test: `sales-mcp/tests/test_termin_takt.py`

**Interfaces:**
- Consumes: alles aus Task 4–10.
- Produces: `runde(jetzt: datetime) -> dict` und `main()` (Schleife alle `TERMIN_TAKT_S`, Standard 30; `TERMIN_EINMAL=1` macht eine Runde). Eine Runde in dieser Reihenfolge, jeder Schritt mit eigenem `try`, damit ein Fehler den Rest nicht stoppt:
  1. `termin_akte.abgleichen(jetzt)`
  2. **Briefing:** Akten mit `0 < beginn - jetzt <= 30 min`, nicht abgesagt. Neu erstellen, wenn `briefing_stand` leer ist oder sich vom neuen `stand` unterscheidet. Telegram nur, wenn `hinweis_gesendet_am is null` **und** `beginn > jetzt`. `hinweis_gesendet_am` wird nur bei `senden() is True` gesetzt.
  3. **Bot:** Akten mit `status='geplant'`, Link, `not kein_bot`, nicht abgesagt, `beginn - jetzt <= 60 s` und `jetzt < ende`.
     - Hat die Akte gesperrte Teilnehmer, gibt es keinen Bot: `ohne_aufnahme`, Grund `gesperrter Teilnehmer`.
     - Sonst `vexa.bot_schicken(link)`, dann `status='wartet_auf_einlass'` mit `vexa_*` und `bot_geschickt_am`.
     - `VexaFehler` → `fehlgeschlagen` mit Grund `Bot konnte nicht starten`.
  4. **Verfolgen:** Akten mit Status `wartet_auf_einlass` oder `laeuft`: `vexa.meeting_lesen`.
     - `failed` → `fehlgeschlagen`, Grund aus Vexa (z. B. „nicht eingelassen“).
     - `completed` → `vexa.segmente_holen`, dann in **einer Transaktion** `termin_mitschriften` anlegen (bei 0 Segmenten `auswertung_status='leer'`) und Status `fertig`.
     - **Erst danach** `vexa.meeting_loeschen`. Scheitert das Löschen, bleibt `vexa_meeting_id` stehen, und die nächste Runde löscht nur nach.
  5. **Nachlöschen:** `fertig` oder `ohne_aufnahme` mit gesetzter `vexa_meeting_id` → `meeting_loeschen`, dann `vexa_meeting_id = null`.
  6. **Auswerten:** Wenn `ollama.erreichbar()`, **eine** Mitschrift mit `auswertung_status='offen'` (älteste zuerst).
     - `auswerten`, `markdown`, `vorschlaege` speichern, Status `fertig`.
     - Bei `will_zusammenfassung`: `server._entwurf_erstellen(lead_id, "email", auswertung.kundenfassung(a, anrede), betreff=f"Zusammenfassung unseres Gesprächs vom {datum}", termin_bezug=True, thema="termin_zusammenfassung")` für den ersten verknüpften Lead. Die `draft_id` kommt nach `entwurf_id`.
     - `OllamaFehler` → `fehler`. Bei `fehler` gibt es einen Neuversuch nach 1 h (`auswertung_am` als Merker), höchstens 3-mal, danach bleibt es bei `fehler`.
     - Ollama aus → nichts tun und nichts loggen außer einer INFO-Zeile beim Wechsel erreichbar ↔ nicht erreichbar.
- Logger `logging.getLogger("sales-termine")` mit eigenem stdout-Handler (Muster `telegram_dispatch.py:321-339`). Geloggt werden nur uid-Hash (erste 8 Zeichen sha256), Status und Zähler.

- [ ] **Step 1: Failing tests** (Vexa, Ollama und Telegram per Monkeypatch):
  - `test_briefing_30_min_vorher_und_hinweis_einmal`
  - `test_briefing_neu_bei_aenderung_ohne_zweiten_hinweis`
  - `test_bot_eine_minute_vorher_mit_festen_parametern`
  - `test_kein_bot_schalter`
  - `test_kein_bot_bei_gesperrtem`
  - `test_kein_link_kein_bot`
  - `test_taktgeber_spaet_gestartet_schickt_noch_waehrend_termin`: `beginn` vor 10 min, `ende` in 50 min.
  - `test_nicht_eingelassen_fehlgeschlagen`
  - `test_vexa_weg_beim_start_fehlgeschlagen` (Review Focus 3)
  - `test_abholen_scheitert_bleibt_und_wiederholt` (Review Focus 3): `segmente_holen` wirft beim ersten Mal → kein Mitschrift-Datensatz, kein `meeting_loeschen`. Beim zweiten Mal Erfolg → Mitschrift da, `meeting_loeschen` genau einmal.
  - `test_loeschen_erst_nach_commit`: Die Aufrufreihenfolge wird protokolliert, Insert steht vor `meeting_loeschen`.
  - `test_null_segmente_leer`
  - `test_ollama_aus_auswertung_wartet` (Review Focus 4): drei Runden ohne Ollama → Status bleibt `offen`, höchstens eine INFO-Zeile.
  - `test_zusammenfassung_nur_mit_schalter` (Spec §10.7): ohne Schalter kein Draft, mit Schalter ein Draft `status='pending'`.
  - `test_log_ohne_kundendaten`: Nach einer vollen Runde mit allen Pfaden enthält `caplog` keine Adresse, keinen Passcode, keinen Segmenttext und keinen Schlüssel.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren, Compose, `update.sh`, `smoke.sh`, `.env.example` und die Containerliste anpassen. `scripts/check-compose-bindings.py` und `scripts/tests/test_proxmox_compose.py` laufen lassen.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS, Compose-Prüfungen grün, `bash deploy/tests/*.sh` grün.
- [ ] **Step 5:** Commit `feat(termin): Taktgeber fuer Briefing, Bot, Abholen und Auswertung`.

### Task 12: Termin-Seite, JSON und MCP-Werkzeug

**Files:**
- Create: `sales-mcp/ui_termin.py`
- Modify: `sales-mcp/termin_akte.py` (`aufnahme_beenden`)
- Modify: `sales-mcp/ui.py` (`*ui_termin.routen(sys.modules[__name__])` **vor** Routen mit Platzhaltern; Stil-Zusätze in `_STIL`)
- Modify: `sales-mcp/server.py` (Werkzeug `termin_akte_lesen` + Eintrag in `WERKZEUGE` ~:10361)
- Test: `sales-mcp/tests/test_ui_termin.py`, `sales-mcp/tests/test_termin_akte_mcp.py`

**Interfaces:**
- Consumes: `termin_akte.lesen`, `termin_akte.status_setzen`, `vexa.bot_stoppen`, `vexa.meeting_loeschen`, `server._termin_ergebnis`, `server._wiedervorlage_anlegen`, `server.entwurf_ablehnen`, `server._q`.
- Produces:
  - `termin_akte.aufnahme_beenden(uid: str, grund: str) -> None` (in `termin_akte.py`, hier eingeführt): Bot stoppen und bei Vexa löschen, falls `vexa_meeting_id` gesetzt ist. Danach die lokale Mitschrift löschen und den Status `ohne_aufnahme` mit `grund` setzen. Schlägt Vexa fehl, bleibt `vexa_meeting_id` stehen, der Taktgeber löscht nach. Wird von der Aktion `ohne_aufnahme` und von Task 14 genutzt.
  - `GET /termine/{kennung:path}`. Endet `kennung` auf `.json`, gibt es `_ok(termin_akte.lesen(uid))` (`@_gesichert_json`), sonst die HTML-Seite (`@_gesichert_seite`). Unbekannt → 404.
  - HTML nach Variante C: oben Titel, Kunde mit Firma, Zeit und der Knopf „Beitreten“ (`<a class="knopf gross" href="{link}">`, mindestens 56px hoch). Darunter die Reiter Details, Briefing und Verlauf (`ui_muster.reiter`), dazu Mitschrift, sobald eine Mitschrift existiert.
    - Verlauf: `historie.kontakt_historie` je verknüpftem Lead, plus Links auf frühere Akten dieser Leads.
    - Statuszeile mit Anzeige-Text (`laeuft` → „läuft“).
    - Bei `wartet_auf_einlass` oder `laeuft`: Knöpfe „Ohne Aufnahme“ und „Will Zusammenfassung“.
    - Vor dem Termin: Schalter „Kein Bot“.
    - Nach dem Gespräch: Vorschläge mit „Übernehmen“ und „Verwerfen“, außerdem „Mitschrift verwerfen“.
  - `POST /termine/{kennung:path}` mit Formfeld `aktion` und `csrf`; Rolle muss `_AKTIVE_ROLLE` sein; Antwort 303 zurück auf die Seite:
    - `ohne_aufnahme`: `termin_akte.aufnahme_beenden(uid, "Kunde hat abgelehnt")`.
    - `will_zusammenfassung`: Schalter umdrehen.
    - `kein_bot`: Schalter umdrehen, nur solange der Status `geplant` oder `kein_link` ist.
    - `vorschlag_uebernehmen` (+ `vorschlag_id`):
      - `termin_ergebnis`: Bei `herkunft='kalender'` ohne `termin_activity_id` zuerst eine `activities`-Zeile `type='termin'` für `lead_id` anlegen, Payload `{datum, uhrzeit, dauer_minuten, thema, ort: link, uid, aus_kalender: true}`, und `termin_activity_id` setzen. Dann `server._termin_ergebnis(termin_activity_id, **daten, quelle="termin-seite")`. Bei Fehler („schon gebucht“) bleibt der Vorschlag offen, und die Meldung wird angezeigt.
      - `wiedervorlage`: `_wiedervorlage_anlegen(lead_id, date.fromisoformat(faellig_am), notiz)`.
      - `feld`: `update leads set title/company … where id = lead_id`, nur diese zwei Spalten.
      - Danach Status `bestaetigt`.
    - `vorschlag_verwerfen` (+ `vorschlag_id`): Status `verworfen`.
    - `mitschrift_verwerfen`: Ein offener Entwurf (`entwurf_id`, Status `pending`) wird abgelehnt. Die Mitschrift wird gelöscht, die offenen Vorschläge gehen per Kaskade mit, bestätigte Wirkungen bleiben in `activities`. Status `ohne_aufnahme`, Grund `nachträglich verworfen`.
  - MCP `termin_akte_lesen(uid: str) -> str`: `_json(termin_akte.lesen(uid) or {"fehler": "Keine Akte zu dieser uid."})`. Ohne `passcode`, denn das MCP geht über einen Agenten.

- [ ] **Step 1: Failing tests** (`test_ui_termin.py`, Muster `test_ui_kalender.py`):
  - `test_seite_mit_beitreten_knopf`
  - `test_json_gleich_wie_lesen`
  - `test_uid_mit_sonderzeichen` (Review Focus 5): `abc@google.com#2026-11-12T09:00:00+00:00` über `quote(uid, safe='')` liefert 200 für HTML und JSON.
  - `test_ohne_aufnahme_stoppt_und_loescht`: Vexa-Stub wird mit `bot_stoppen` und `meeting_loeschen` aufgerufen, danach keine Mitschrift und Status `ohne_aufnahme`.
  - `test_ohne_aufnahme_vexa_weg_trotzdem_status`
  - `test_kein_bot_nach_start_nicht_aenderbar`
  - `test_termin_ergebnis_kalendertermin_legt_terminzeile_an`
  - `test_termin_ergebnis_zweimal_bleibt_offen`
  - `test_wiedervorlage_uebernehmen`
  - `test_mitschrift_verwerfen_raeumt_ab_und_lehnt_entwurf_ab`
  - `test_csrf_pflicht` (403 ohne Token)
  - `test_rolle_lesen_darf_nicht_posten`
  - `test_gesperrter_teilnehmer_nicht_in_html_und_json`
  - `test_mcp_ohne_passcode`
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren. Mobile Regeln aus `ui.py:823-850` gelten: Touch-Ziele ≥ 44px, kein waagrechtes Scrollen, Dark Mode über die vorhandenen Variablen.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(sales-ui): Termin-Seite mit Beitreten, Briefing, Verlauf und Mitschrift`.

### Task 13: Verlinkung und Verlauf

**Files:**
- Modify: `kalender/src/fenster.ts` (~:195 neben „Zum Kontakt“), danach `npm run build` (aktualisiert `sales-mcp/static/kalender` + `MANIFEST.json`)
- Modify: `sales-mcp/ui.py:8170` (`_kontakt_termine`: Zeile verlinkt auf `/termine/{quote(uid, safe='')}`, wenn eine Akte existiert, sonst wie bisher)
- Modify: `sales-mcp/historie.py` (`kontakt_historie`: zusätzliche Einträge aus `termin_teilnehmer` ⨝ `termin_akten` (Art `termin_akte`, Text „Termin: {titel}“) und aus `termin_mitschriften` (Art `mitschrift`, Text „Mitschrift vorhanden“). Je Painpoint ein Eintrag der Art `painpoint` mit dem Zitat. Alles abgeleitet, nichts in `activities`.)
- Test: `kalender/src/fenster.test.ts`, `sales-mcp/tests/test_historie.py`, `sales-mcp/tests/test_ui_kontakt*.py` (bestehende Datei für den Termine-Reiter), `sales-mcp/tests/test_kalender_paket.py`

**Interfaces:**
- Produces in `fenster.ts`: reine Funktion `aktenLink(uid: string): string`, Ergebnis `"/termine/" + encodeURIComponent(uid)`. Der Dialog zeigt „Termin-Seite“ für Kundentermine (`ev.extendedProps.uid` gesetzt und Ereignis-id beginnt mit `kunde:` oder `kalender:`).

- [ ] **Step 1: Failing tests**:
  - `aktenLink` mit `#` und `@` (vitest)
  - `test_historie_zeigt_akte_mitschrift_painpoints`
  - `test_historie_nach_verwerfen_leer`: Mitschrift gelöscht → keine `mitschrift`- und keine `painpoint`-Einträge mehr.
  - `test_kontakt_termine_link_auf_akte`
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren, `npm run build`.
- [ ] **Step 4:** `npm test` und die pytest-Dateien laufen lassen. Erwartet: PASS, `test_kalender_paket.py` grün.
- [ ] **Step 5:** Commit `feat(termin): Kalender, Kontakt und Verlauf verlinken die Termin-Akte`.

### Task 14: Einladungszeile und Löschantrag

**Files:**
- Modify: `sales-mcp/server.py:2349-2360` (Einladungstext in `_termin_einladen`)
- Modify: `sales-mcp/server.py:8817` (`loeschantrag_vermerken`), `server.py:8758` (`kontakt_auskunft`)
- Modify: `docs/06_DSGVO.md` (Checkliste: Mitschriften), `.env.example` (Kommentar :12-15 ergänzen: Ausnahme Ollama am **PC** für Briefing/Auswertung, VM bleibt ohne Modell, OpenClaw-Weg unverändert)
- Test: `sales-mcp/tests/test_termin_einladen.py`, `sales-mcp/tests/test_dsgvo.py`

**Interfaces:**
- Einladungszeile nur, wenn `termin_link.erkennen(ort)` einen Treffer liefert. Der Wortlaut ist ein **Vorschlag**, den Felix vor dem Merge freigibt (Spec §5.4). Der Builder setzt ihn so und markiert ihn im PR:
  `Hinweis: VibeMind schreibt das Gespräch mit, damit nichts verloren geht. Die Mitschrift bleibt auf unseren eigenen Servern. Möchten Sie das nicht, sagen Sie es einfach zu Beginn – dann läuft das Gespräch ohne Mitschrift.`
  Die Zeile steht als Konstante `EINLADUNG_MITSCHRIFT_HINWEIS` in `server.py`.
- `loeschantrag_vermerken`: zusätzlich `delete from termin_mitschriften where uid in (select uid from termin_teilnehmer where lead_id = %s)` und `update termin_teilnehmer set lead_id = null, grund = 'gesperrt' where lead_id = %s`. Läuft ein Bot für eine solche Akte (`wartet_auf_einlass` oder `laeuft`), gilt dieselbe Logik wie `ohne_aufnahme` aus Task 12 (`termin_akte.aufnahme_beenden(uid, "Löschantrag eines Teilnehmers")` aus Task 12).
- `kontakt_auskunft`: Abschnitt `termine` mit den Akten des Leads, Mitschrift-Segmenten und Auswertung.

- [ ] **Step 1: Failing tests**:
  - `test_einladung_mit_videolink_hat_hinweis`
  - `test_einladung_ohne_link_ohne_hinweis`
  - `test_loeschantrag_loescht_mitschriften_aller_termine`: zwei Akten, in beiden der Lead → beide Mitschriften weg, eine dritte Akte ohne ihn bleibt.
  - `test_loeschantrag_beendet_laufenden_bot`
  - `test_auskunft_enthaelt_mitschrift`
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren, `docs/06_DSGVO.md` und `.env.example` anpassen.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS. Danach die **ganze** Suite einmal laufen lassen, Erwartet: grün bis auf vorher schon rote Tests (vorher/nachher vergleichen und im Bericht nennen).
- [ ] **Step 5:** Commit `feat(termin): Hinweis in der Einladung, Loeschantrag raeumt Mitschriften ab`.

### Task 15: Vexa-Betrieb (Dateien, kein Start)

**Files:**
- Create: `deploy/vexa/docker-compose.yml`, `deploy/vexa/.env.example`, `deploy/vexa-anbinden.sh`
- Create: `deploy/tests/test_vexa_compose.sh` (oder pytest in `scripts/tests/`)
- Modify: `docs/03_RUNBOOK.md` (Abschnitt „Meeting-Mittelpunkt“)

**Interfaces:**
- Compose-Projekt `name: vexa`, Netz `vexa_default`, Dienste nach dem Vorbild `deploy/lite/Makefile` aus Vexa **v0.12.28** (dort ablesen: Umgebung, Volumes, Healthchecks):
  - `vexa-lite`: Image `vexaai/vexa-lite` **per Digest gepinnt**. `RUNTIME_BACKEND=process`, `VEXA_JITSI_HOSTS=meet.ffmuc.net`. Port nur `127.0.0.1:8056`. Agent-Funktionen aus, kein Modell-Schlüssel (Spec §5.4).
  - `vexa-lite-whisper`: `fedirz/faster-whisper-server` CPU **per Digest gepinnt**, Modell `Systran/faster-whisper-small`, kein Port nach außen.
  - `vexa-lite-postgres`: `postgres:17-alpine` per Digest. `vexa-lite-storage`: `versity/versitygw:v1.8.0` per Digest.
  - Volumes mit Präfix `vexa-` (`vexa-pgdata`, `vexa-storagedata`, `vexa-whisper-modelle`).
- `deploy/vexa-anbinden.sh` (idempotent, Muster `kanal-zugang-eintragen.sh`, nichts auf stdout außer ok/Fehler):
  1. `ADMIN_TOKEN` zufällig erzeugen, falls `deploy/vexa/.env` fehlt (Datei 600).
  2. Über die Admin-API (im Container, `X-Admin-API-Key`) einen Nutzer `sales` anlegen und einen Token mit `scopes=bot,tx` holen.
  3. `PUT /user/transcription` mit Platzhalter-Token (Spike: ohne das scheitert die Spracherkennung).
  4. `VEXA_API_KEY=` in die sales-claw-`.env` schreiben (Backup, Temp-Datei 600, `mv`).
- Test: `docker compose -f deploy/vexa/docker-compose.yml config` ist gültig. Alle `ports:` beginnen mit `127.0.0.1:`. Jedes `image:` enthält `@sha256:`. Kein `0.0.0.0`.

- [ ] **Step 1:** Failing Test schreiben (Compose-Prüfung).
- [ ] **Step 2:** Test laufen lassen. Erwartet: FAIL (Datei fehlt).
- [ ] **Step 3:** Dateien schreiben. Die Digests holt der Builder mit `docker buildx imagetools inspect <image:tag>` (nur lesen, nichts starten). Runbook-Abschnitt: Start, Anbinden, Smoke, Rückbau (`docker compose -p vexa down`, Volumes `vexa-*` einzeln löschen, nie `prune`).
- [ ] **Step 4:** Test laufen lassen. Erwartet: PASS.
- [ ] **Step 5:** Commit `feat(deploy): Vexa als eigenes Compose-Projekt mit gepinnten Images`.

### Task 16: Gesamtprüfung und PR

- [ ] **Step 1:** Ganze sales-mcp-Suite, `npm test` (kalender), `deploy/tests/*.sh`, `scripts/tests/*` laufen lassen. Erwartet: grün bzw. nur vorher schon rote Tests.
- [ ] **Step 2:** Alle Dateien des Zweigs auf Logaufrufe mit `teilnehmer`, `adresse`, `passcode`, `segmente`, `text` prüfen (`git diff origin/feat/stufe-1-fundament... | grep -n "log\."`) und jede Fundstelle begründen.
- [ ] **Step 3:** PR gegen `feat/stufe-1-fundament` öffnen. Im PR-Text stehen: Einladungs-Wortlaut zur Freigabe, offene Abnahmetests (§10), Plan B (Rowboat in vibemind-os), Ausrollen erst nach Felix' OK. Kein Merge.

### Task 17: Ausrollen und Abnahme — **HALT: nur mit Felix' ausdrücklichem OK**

Erst Claim `cc-meeting-ausrollen` in `secondbrain/00_Meta/002_Koordination_Live.md` eintragen und committen. Jede Zeile hier ist eine Änderung an VM, DB oder PC.

- [ ] SQL einspielen (`db/provision.sql`, `db/kalender-verbinden.sql -v schema=sales -v besitzer=felix`) als `supabase_admin`, vorher Sicherung (`deploy/sicherung.sh`).
- [ ] Vexa starten (`docker compose -f deploy/vexa/docker-compose.yml up -d`), `deploy/vexa-anbinden.sh`, Gesundheit prüfen.
- [ ] Am PC `scripts/ollama-pc.ps1` und `scripts/ollama-pc-aufgabe.ps1` ausführen, `OLLAMA_URL` in die VM-`.env`. Tailscale-ACL prüfen: Port 11434 nur für `offload-vm`. Ollama hat keinen eigenen Schlüssel, die Schranke ist das Tailnet. Das Ergebnis steht im Runbook.
- [ ] **Modellprobe** (Spec §7): `qwen2.5:7b`, `llama3.1:8b` und `gemma4` auf `tests/daten/mitschrift_beispiel.json` laufen lassen. Bewertet werden gültiges JSON, Painpoints wörtlich und Laufzeit. Das Ergebnis kommt ins Runbook, `OLLAMA_MODELL` wird entsprechend gesetzt.
- [ ] Telegram-Chat-ID: Felix schreibt dem Bot einmal. Die ID wird mit `getUpdates` ausgelesen und verdeckt als `TELEGRAM_CHAT_ID` in die `.env` geschrieben (Muster `kanal-zugang-eintragen.sh`, nie ausgeben).
- [ ] `deploy/update.sh` (baut und startet `sales-termine` mit), `deploy/smoke.sh` grün.
- [ ] Abnahme Spec §10, Punkte 1–10, mit Felix. Je Plattform (Meet, Teams, Zoom, Jitsi) ein Gespräch mit zwei Sprechern und mindestens 5 Minuten. Das Ergebnis kommt als Tabelle ins Runbook. Punkt 6 (Rowboat) wartet auf Plan B.
- [ ] Claim schließen, WORKBOARD `cc-meeting-mittelpunkt` schließen.
