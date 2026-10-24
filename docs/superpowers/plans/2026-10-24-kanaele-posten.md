# Beiträge auf weitere Kanäle (Bluesky, Mastodon, Telegram-Kanal, Discord, dev.to) – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- sales-claw kann eigene Beiträge (ohne Empfänger) auf Bluesky, Mastodon, einem Telegram-Kanal, Discord (Webhook) und dev.to (nur als Entwurf dort) veröffentlichen.
- Der Ablauf ist derselbe wie bei LinkedIn: Entwurf → Freigabe in `/freigaben` → Versand durch einen Dienst, höchstens einmal, Beleg in `activities`, Kadenz je Kanal.
- Alles steht bereit, bevor der Betreiber Zugänge einträgt. Ohne Zugang heißt es „noch nicht verbunden“, nie Fehler.

**Architecture:**
- **Metadaten getrennt von Geheimnissen:** `sales-mcp/kanaele.py` hält die Registry ohne Netz und ohne Zugänge (Grenzen, Medien, Kadenz, Env-Namen) und liest/schreibt die Tabelle `kanal_status`. `server.py`, `ui.py` und `ui_reels.py` importieren nur dieses Modul und kennen nie einen Schlüssel (Präzisierung 1).
- **Adapter:** `kanal_api.py` ist der HTTP-Kern (stdlib `urllib`, austauschbar über `kanal_api.HTTP`, Fehlereinordnung `dauerhaft|ungewiss`, Geheimnisse aus jedem Text entfernt). `kanal_adapter.py` hat je Kanal eine Funktion `senden_<kanal>` und `SENDER: dict[str, Sender]`.
- **Dienst:** `kanal_dispatch.py` (Container `sales-kanaele`) ist ein Dauerdienst nach dem Muster von `linkedin_dispatch.py`: Claim je Kanalwert mit `recipient='eigenes-profil'`, Beleg vor Buchung, `ungewiss` sperrt jede Wiederholung, Kadenz und Frischegrenze je Kanal. Jede Runde schreibt je Kanal eine Zeile in `kanal_status`. Ein Fehler in einem Kanal hält die anderen nicht auf.
- **Entwürfe:** MCP-Werkzeug `kanal_post_entwurf`, Skill `kanal-post`, Knopf „Auf Kanälen teilen“ auf der Reels-Seite, Marketing-Aufträge `<kanal>_post` über `versandauftrag_uebernehmen`.
- **Oberfläche:** `/freigaben` kennt die fünf Kanäle. Neue Admin-Seite `/einstellungen/kanaele` zeigt „verbunden ja/nein“, den letzten Beitrag mit Link, Kadenz und Grenze.
- **Zugänge:** `deploy/kanal-zugang-eintragen.sh <kanal>` fragt verdeckt ab, schreibt `~/sales-claw/.env` und erzeugt nur `sales-kanaele` neu.

**Tech Stack:** Python 3.12 (sales-mcp: psycopg, Starlette, pytest, stdlib `urllib`/`json`/`uuid`), PostgreSQL (`db/provision.sql`, Supabase-Schema `marketing`), Bash, Docker Compose, Markdown-Skill (OpenClaw).

**Spec:** sales-claw `docs/superpowers/specs/2026-10-24-kanaele-posten-design.md`. Der Abschnitt „Präzisierungen nach Builder-Check“ ist verbindlich und geht dem Entwurfsteil vor.

**Repos:**
- Tasks 1–9 in **sales-claw** (SC), Branch `feat/stufe-1-fundament`, Pfade relativ zum Repo-Root. Eigener Worktree unter `C:/Users/User/ClaudeWork/` (z. B. `wt-sales-kanaele`, detached auf `origin/feat/stufe-1-fundament`). Vor dem Push `git fetch origin && git rebase origin/feat/stufe-1-fundament`, dann `git push origin HEAD:feat/stufe-1-fundament`.
- Task 10 in **vibemind-os** (MOS) `master`, Pfade relativ zu `spaces/marketing/`. Eigener Worktree (z. B. `C:/Users/User/ClaudeWork/wt-mos-kanaele` auf `origin/master`), gepusht nach `origin master`. Der Haupt-Checkout `C:/Users/User/Desktop/Vibemind_V1/vibemind-os` ist ein alter Pin: dort nichts lesen oder committen.
- Task 11 (Auslieferung und Abnahme) macht der Koordinator, kein Implementierer.

**Testbefehle:**
- **SC** (Git Bash, aus `sales-mcp/`, Container `sales-testdb`, bei Bedarf `docker start sales-testdb`):
  `SALES_DB_URL='postgresql://postgres:ci@127.0.0.1:55432/sales_struktur' SALES_DB_SCHEMA=sales_test C:/Users/User/AppData/Local/Temp/claude/c--Users-User-Desktop-Vibemind-V1/1c07de95-6394-472f-950f-4226a85d9fbb/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q -p no:cacheprovider`
  - Jede Datei einzeln.
  - Vorbestehend rot: `test_bild_route_entschluesselt_nur_einmal`.
  - Ein sporadisches `FileNotFoundError` in `sales-mcp-test-dateien` kommt von parallelen fremden Läufen: einmal wiederholen.
  - Jedes andere Rot gegen BASE in einem Wegwerf-Worktree prüfen, nie per Stash.
- **provision.sql in die Test-DB** (nach jeder Änderung daran, zweimal hintereinander, damit die Idempotenz gezeigt ist):
  `docker exec -i sales-testdb psql -U postgres -d sales_struktur -v ON_ERROR_STOP=1 < db/provision.sql`
- **Bash-Tests** (Git Bash, Repo-Root): `bash deploy/tests/<datei>.sh` → letzte Zeile `OK`.
- **MOS** (aus dem Worktree-Root): `C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m pytest spaces/marketing/tests spaces/marketing/claw/tests -q -p no:cacheprovider --basetemp C:/Temp/pt-kanaele` (während TDD einzelne Dateien). Vorbestehend rot: `test_cockpit_contract`, `test_abschnitte`, `test_formular_entwurf`, `test_gestaltung_pruefen`.
- **Migrationsprobe:** `SUPABASE_SSH_HOST=offload-vm SUPABASE_DB_CONTAINER=debian-supabase-db-1 C:/Users/User/Desktop/Vibemind_V1/.venv/Scripts/python.exe -m spaces.marketing.scripts.migration_probe <dateien>` → `PROBE OK (zurueckgerollt)`. Läuft immer in einer Transaktion mit ROLLBACK.

## Global Constraints

- **Kanalwerte in `drafts.channel`:** `bluesky`, `mastodon`, `telegram_kanal`, `discord`, `devto`. Immer `recipient='eigenes-profil'`. `telegram_kanal` ist getrennt vom bestehenden `telegram` (Direktnachrichten).
- **Anzeigenamen:** Bluesky, Mastodon, Telegram-Kanal, Discord, dev.to. Reihenfolge überall wie hier.
- **Zugänge (Env-Namen, wörtlich):**
  - bluesky: `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`
  - mastodon: `MASTODON_INSTANCE`, `MASTODON_TOKEN`
  - telegram_kanal: `TELEGRAM_KANAL_ID`, `TELEGRAM_KANAL_BOT_TOKEN`
  - discord: `DISCORD_ANKUENDIGUNG_WEBHOOK`
  - devto: `DEVTO_API_KEY`
  - Geheim sind davon `BLUESKY_APP_PASSWORD`, `MASTODON_TOKEN`, `TELEGRAM_KANAL_BOT_TOKEN`, `DISCORD_ANKUENDIGUNG_WEBHOOK`, `DEVTO_API_KEY`. Handle, Instanz und Kanal-ID sind keine Geheimnisse, werden aber trotzdem nie in UI oder Log ausgegeben.
- **Grenzen, Medien, Kadenz:**

  | Kanal | Text max | mit Medien max | Bilder max | Video max | Bild max Bytes | Video max Bytes | Kadenz/Tag | Hashtags |
  |---|---|---|---|---|---|---|---|---|
  | bluesky | 300 | 300 | 4 | 0 | 1 000 000 | – | 3 | ja |
  | mastodon | 500 | 500 | 4 | 1 | 16 MiB | 40 MiB | 3 | ja |
  | telegram_kanal | 4096 | 1024 | 1 | 1 | 10 MiB | 50 MiB | 3 | nein |
  | discord | 2000 | 2000 | 1 | 1 | 10 MiB | 10 MiB | 3 | nein |
  | devto | 100 000 | – | 0 | 0 | – | – | 1 | nein |

  Bilder und Video nie gemischt. Bei Telegram und Discord höchstens **ein** Medium insgesamt. dev.to: Titel Pflicht, 1–128 Zeichen. Textlänge = `len(str)`. `medien.MAX_BYTES` (15 MiB) gilt zusätzlich über `medien.pruefe_anhang`.
- **Betreff und Thema (Präzisierung 7):** `subject = f"Post: {thema}"`, bei devto `subject = titel`. `drafts.thema = thema[:200]`. Doppel-Prüfung je Kanal über `lower(btrim(thema))`, abgelehnte zählen nicht, `trotzdem=True` übergeht sie.
- **Sammelkontakt (Präzisierung 2):** alle Entwürfe an `server.LINKEDIN_POST_LEAD_ID`. Keine neue Env-Variable.
- **Beleg (Präzisierung 10):** `activities.type='versand'`, `payload = {"draft_id", "kanal", "weg": "kanal-dispatcher", "empfaenger": "eigenes-profil", "beitrag": <id>, "url": <öffentliche URL oder null>, "medienart"}`. Ungewiss: dieselbe Zeilenart mit `"beitrag": null, "url": null, "ungewiss": true, "grund"`.
- **Kadenz und Frische (Präzisierung 3):** Kadenz zählt `versand`-Belege je `payload->>'kanal'` seit `date_trunc('day', now())` (DB-Zeit), `ungewiss` zählt mit. Freigaben mit `approved_at < now() - interval '7 days'` bleiben liegen.
- **Claim (Präzisierung 4):** `update drafts set status='failed', error=<_claim_marke()> where id=%s and status='approved' and channel=%s and recipient='eigenes-profil'`. Den Kanalwert liefert nur die Registry, er kommt nie aus Eingaben. Aus `dispatch.py` werden nur `_claim_marke`, `_als_gesendet_buchen`, `_als_fehler_buchen` (und `_einzeilig`) importiert.
- **Tabelle `kanal_status` (Präzisierung 1):** `kanal text primary key, verbunden boolean not null default false, geprueft_am timestamptz not null default now(), letzter_fehler text`. In allen Laden-Schemas (Schleife in provision.sql) und in `laden-anlegen.sql`. Fehlt Zeile oder Tabelle, gilt „nicht verbunden“.
- **Nur Haupt-Laden (Präzisierung 5):** `sales-kanaele` läuft nur im Basis-Laden. Kein Eintrag in `deploy/laden-anlegen.sh` und keiner in `deploy/laeden/beispiel.env`.
- **Marketing-Auftragskanäle (Präzisierung 6):** `bluesky_post`, `mastodon_post`, `telegram_kanal_post`, `discord_post`, `devto_post`. Migration **092** (gegen `origin/master` geprüft: 091 ist die letzte, Claim `cc-kanaele-posten` im WORKBOARD).
- **Geheimnisse:** Kein Schlüssel, Token, Passwort, Session-JWT oder Webhook-Pfad in Exceptions, `drafts.error`, `kanal_status.letzter_fehler`, Logs, UI oder Skriptausgaben. Fehlertexte nennen den Schritt (`createRecord`, `sendPhoto` …), nie die URL.
- **dev.to:** immer `published: false`. Hinweistext in Freigabe und Werkzeug: „wird als Entwurf bei dev.to angelegt“.
- **Keine neue Abhängigkeit:** nur stdlib (`urllib.request`, `json`, `uuid`, `re`). `sales-mcp/requirements.txt` bleibt unverändert.
- **Stil:** Code-Kommentare deutsch mit ae/oe/ue wie in den Dateien, UI-Texte mit echten Umlauten (Wächter in `test_darstellung.py`). Conventional Commits auf Deutsch mit Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nur eigene Dateien stagen, nie `.superpowers/`, nie stashen, keine Hooks umgehen.
- **Kein Umbau des LinkedIn-Wegs:** `linkedin_dispatch.py`, `post_entwurf_erstellen` und `linkedin_api.py` bleiben unverändert (bis auf den Aufruf in `versandauftrag_uebernehmen`).

## Review Focus

1. **Text, der erst beim Bearbeiten zu lang wird** (Bluesky-Entwurf mit 280 Zeichen, in `/freigaben` auf 340 bearbeitet; Telegram-Text 1500 Zeichen mit Bild): Die Bearbeitung wird mit Grenze und Kanalname abgelehnt. Es entsteht kein freigebbarer Entwurf, der erst beim Versand scheitert. Test: `test_bearbeiten_haelt_kanalgrenze` (Task 5). Der Dienst prüft beim Versand zusätzlich nach (`test_zu_langer_text_geht_nicht_raus`, Task 4).
2. **`@everyone` oder `@here` im Discord-Text:** Der Beitrag pingt niemanden (`allowed_mentions: {"parse": []}`). Test: `test_discord_pingt_niemanden` (Task 2).
3. **Zugangswert mit falscher Form oder Windows-Zeilenende** (`MASTODON_INSTANCE=mastodon.social\r`, `http://…`, Telegram-ID ohne `@`/`-100`): `strip()` beim Lesen, Formprüfung über `kanaele.zugang_pruefen`. Ein ungültiger Wert ergibt „nicht verbunden“ mit `letzter_fehler`, der nur den Namen nennt, nie den Wert. Tests: `test_zugang_crlf_wird_entfernt`, `test_zugang_falsche_form_nennt_nur_namen` (Task 1). Das Eintrage-Skript lehnt Zeichen außerhalb `[A-Za-z0-9._:/@+=~%?&-]` ab (`$` würde Compose interpolieren). Test in `deploy/tests/test_kanal_zugang_eintragen.sh` (Task 9).
4. **Hashtag oder Link mit Umlaut auf Bluesky** (`Grüße #KünstlicheIntelligenz https://vibemind.de.`): Facetten stehen auf UTF-8-Byte-Grenzen, der Satzpunkt gehört nicht zum Link. Test: `test_bluesky_facetten_byteversatz` (Task 3).
5. **Kanal wird nach der Freigabe getrennt oder fällt aus** (Zugang entfernt; Anbieter antwortet 503): Der freigegebene Entwurf bleibt `approved` liegen und die Karte sagt „Kanal nicht verbunden – bleibt liegen“. Ein 503 beim Veröffentlichen ist `ungewiss` und sperrt die Wiederholung. Die anderen Kanäle laufen in derselben Runde weiter. Tests: `test_nicht_verbundener_kanal_bleibt_liegen`, `test_ausfall_eines_kanals_haelt_andere_nicht_auf` (Task 4), `test_freigegeben_nicht_verbunden_hinweis` (Task 7).

---

### Task 1: Datenbank und Kanal-Registry (`kanaele.py`)

**Files:**
- Modify: `db/provision.sql` (CHECK-Block bei „Telegram als Kanal“, ca. Z. 288; neue Tabelle in derselben Laden-Schleife wie `empfehlungslisten`, Grants nach deren Muster; Grant-Block am Ende ca. Z. 543–562)
- Modify: `db/laden-anlegen.sql` (`like sales.kanal_status including all` + Grant)
- Create: `sales-mcp/kanaele.py`
- Test: `sales-mcp/tests/test_kanaele.py`, `sales-mcp/tests/test_kanal_status_schema.py`

**Interfaces – Produces:**
- `@dataclass(frozen=True) class KanalInfo: name: str; anzeige: str; env_namen: tuple[str, ...]; geheim_namen: tuple[str, ...]; max_zeichen: int; max_zeichen_mit_medien: int; bilder_max: int; video_max: int; medien_max: int; bild_max_bytes: int; video_max_bytes: int; kadenz_pro_tag: int; titel_pflicht: bool; titel_max: int; hashtags: bool`
- `KANAELE: dict[str, KanalInfo]`, Werte und Reihenfolge aus den Global Constraints. `medien_max` = 4 (bluesky, mastodon), 1 (telegram_kanal, discord), 0 (devto). `titel_max` = 128 (devto), sonst 0.
- `MEDIUM_ART: Literal["bild", "video"]`
- `zugang_lesen(info: KanalInfo, env: Mapping[str, str]) -> dict[str, str]`: je Name `env.get(n, "").strip()`.
- `zugang_pruefen(info: KanalInfo, zugang: Mapping[str, str]) -> str | None`: `None` = verbunden. Sonst ein deutscher Satz, der nur Namen nennt (`"BLUESKY_APP_PASSWORD fehlt"`, `"MASTODON_INSTANCE hat kein gültiges Format"`). Formregeln:
  - `MASTODON_INSTANCE`: `^https://[a-z0-9.-]+\.[a-z]{2,}/?$` nach `lower()`. Ein nackter Host wird vorher zu `https://<host>`.
  - `TELEGRAM_KANAL_ID`: `^(@[A-Za-z0-9_]{5,32}|-100[0-9]{5,15})$`
  - `DISCORD_ANKUENDIGUNG_WEBHOOK`: `^https://(discord|discordapp)\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+$`
  - `BLUESKY_HANDLE`: enthält einen Punkt, ohne `@` am Anfang (ein führendes `@` wird entfernt).
- `instanz_normalisieren(wert: str) -> str` (von `zugang_pruefen` und vom Mastodon-Adapter genutzt).
- `pruefe_entwurf(info: KanalInfo, text: str, titel: str, medien: Sequence[tuple[str, MEDIUM_ART, int]]) -> str | None`: Medien als `(name, art, bytes)`. Gibt einen deutschen Ablehnungsgrund zurück oder `None`. Geprüft werden Länge (mit Medien die Grenze `max_zeichen_mit_medien`), Titelpflicht und -länge, „titel gibt es nur bei dev.to“, Anzahl, Art, Mischung und Bytes je Art.
- `status_lesen(q) -> dict[str, dict]`: `kanal → {"verbunden": bool, "geprueft_am", "letzter_fehler"}`. Fehlt die Tabelle (`psycopg.errors.UndefinedTable`, Code nach provision noch nicht ausgerollt) → `{}`. Andere DB-Fehler gehen weiter.
- `verbunden(q, kanal: str) -> bool` (fehlende Zeile → `False`).
- `status_schreiben(q, kanal: str, verbunden: bool, fehler: str | None, *, fehler_loeschen: bool = False) -> None`: Upsert `on conflict (kanal) do update`, `geprueft_am = now()`. Ein gegebener `fehler` wird auf 300 Zeichen gekappt und geschrieben. Bei `fehler=None` bleibt der bisherige `letzter_fehler` stehen, außer `fehler_loeschen=True`.
- provision.sql: `drafts_channel_check` mit `('email','whatsapp','linkedin','voice','video','meeting_invite','telegram','bluesky','mastodon','telegram_kanal','discord','devto')`. `%I.kanal_status` in der Laden-Schleife. Grants `select, insert, update` an `sales_app` (Schema `sales`) und `sales_app_<laden>` nach dem Muster von `empfehlungslisten`, kein DELETE.

- [ ] **Step 1: Tests schreiben.**
  - `test_kanaele.py` (rein, ohne DB):
    - `test_registry_reihenfolge_und_werte`: `list(KANAELE) == ["bluesky", "mastodon", "telegram_kanal", "discord", "devto"]`. Je Kanal `max_zeichen`, `kadenz_pro_tag`, `env_namen` wie in der Tabelle. `KANAELE["devto"].titel_pflicht is True`.
    - `test_geheim_namen_sind_teilmenge`: `set(i.geheim_namen) <= set(i.env_namen)` für alle Kanäle. `KANAELE["discord"].geheim_namen == ("DISCORD_ANKUENDIGUNG_WEBHOOK",)`.
    - `test_zugang_crlf_wird_entfernt`: `zugang_lesen(KANAELE["mastodon"], {"MASTODON_INSTANCE": "mastodon.social\r", "MASTODON_TOKEN": " abc123\r\n"}) == {"MASTODON_INSTANCE": "mastodon.social", "MASTODON_TOKEN": "abc123"}`. `zugang_pruefen` darauf → `None`.
    - `test_zugang_fehlt`: leeres env → `"BLUESKY_HANDLE fehlt"` steht im Grund.
    - `test_zugang_falsche_form_nennt_nur_namen`: `MASTODON_INSTANCE="http://geheim-instanz.example"` → der Grund enthält `MASTODON_INSTANCE`, aber nicht `geheim-instanz`. Ebenso Telegram-ID `"12345"` und ein Discord-Webhook mit fremdem Host.
    - `test_pruefe_entwurf_grenzen`: Bluesky mit 301 Zeichen → Grund mit „300“. Telegram mit 1025 Zeichen und einem Bild → Grund mit „1024“, ohne Bild → `None`. Bluesky mit Video → Grund. Mastodon mit 5 Bildern → Grund. Mastodon mit Bild und Video → Grund. Discord mit 2 Bildern → Grund. Bluesky-Bild mit 1 000 001 Bytes → Grund. devto ohne Titel → Grund, mit 129 Zeichen Titel → Grund, mit Bild → Grund. Bluesky mit Titel → „titel gibt es nur bei dev.to“.
  - `test_kanal_status_schema.py` (DB, Stil `test_empfehlungslisten_schema.py`):
    - `test_provision_text`: `"%I.kanal_status" in PROVISION`, `"'telegram_kanal'" in PROVISION`, `"grant select, insert, update on sales.kanal_status to sales_app" in PROVISION`, `"delete on sales.kanal_status" not in PROVISION`. `laden-anlegen.sql` enthält `like sales.kanal_status including all`.
    - `test_tabelle_in_sales_test`: Spalten `{"kanal", "verbunden", "geprueft_am", "letzter_fehler"}`.
    - `test_channel_check_nimmt_neue_kanaele`: Insert in `drafts` mit `channel='devto'` gelingt. `channel='instagram'` → `psycopg.errors.CheckViolation`.
    - `test_status_schreiben_und_lesen`: zweimal `status_schreiben(server._q, "bluesky", True, None)` → genau eine Zeile. Dann `status_schreiben(..., False, "BLUESKY_HANDLE fehlt")` → `status_lesen(server._q)["bluesky"]["verbunden"] is False`. `verbunden(server._q, "mastodon") is False` ohne Zeile.
    - `test_status_lesen_ohne_tabelle`: `q`, das `psycopg.errors.UndefinedTable` wirft → `{}`.
    - Fixture: `truncate sales_test.kanal_status, sales_test.drafts, sales_test.activities, sales_test.leads cascade`.
- [ ] **Step 2: Rot.** Beide Dateien → FAIL (`ModuleNotFoundError: kanaele`, fehlende Tabelle).
- [ ] **Step 3: Umsetzen.** `kanaele.py` nach den Interfaces. provision.sql und laden-anlegen.sql idempotent (`create table if not exists`, `drop constraint if exists` + `add`). Den Kommentar beim CHECK-Block um einen Satz zum 24.10.2026 ergänzen.
- [ ] **Step 4: provision.sql zweimal in die Test-DB** (Befehl oben), beide Läufe ohne Fehler.
- [ ] **Step 5: Grün.** Beide Dateien → PASS. Gegenprobe ohne Rückfall: `test_empfehlungslisten_schema.py`, `test_admin_auftraege_tabelle.py`.
- [ ] **Step 6: Commit** `feat(kanaele): Registry und Tabelle kanal_status, neue Kanalwerte im drafts-CHECK`

### Task 2: HTTP-Kern und Adapter Telegram-Kanal, Discord, dev.to

**Files:**
- Create: `sales-mcp/kanal_api.py`, `sales-mcp/kanal_adapter.py`
- Test: `sales-mcp/tests/test_kanal_api.py`, `sales-mcp/tests/test_kanal_adapter.py`

**Interfaces – Consumes:** `kanaele.KANAELE`, `kanaele.instanz_normalisieren`.

**Interfaces – Produces (`kanal_api.py`):**
- `class KanalFehler(Exception): __init__(self, meldung: str, *, ungewiss: bool = False, status: int | None = None)` mit den Attributen `ungewiss`, `status` und `art` (Property: `"ungewiss"` oder `"dauerhaft"`).
- `@dataclass(frozen=True) class Anfrage: methode: str; url: str; kopf: dict[str, str]; daten: bytes | None; frist: float`
- `@dataclass(frozen=True) class Antwort: status: int; kopf: dict[str, str]; rumpf: bytes`
- `HTTP: Callable[[Anfrage], Antwort]`, Vorgabe `_urllib_http`. Sie gibt bei `HTTPError` eine `Antwort` mit dem Code zurück und wirft nur Netzfehler weiter (`TimeoutError`, `urllib.error.URLError`, `OSError`). Tests ersetzen das Modulattribut.
- `@dataclass(frozen=True) class Medium: name: str; mimetyp: str; daten: bytes; art: Literal["bild", "video"]`
- `@dataclass(frozen=True) class Beleg: beitrag: str; url: str` (`url` darf `""` sein).
- `Sender = Callable[[Mapping[str, str], str, list[Medium], str, str], Beleg]`. Argumente: `(zugang, text, medien, titel, schluessel)`, `schluessel` = draft_id (Idempotenz).
- `ohne_geheimnisse(text: str, geheimnisse: Iterable[str]) -> str`: jeder Wert mit `len >= 6` wird zu `<geheim>`. Dazu `https?://\S*(/bot[^/\s]+|/webhooks/\S+)` → `<adresse>`.
- `ruf(anfrage: Anfrage, *, kanal: str, was: str, veroeffentlicht: bool, geheimnisse: Iterable[str]) -> Antwort`. Einordnung:
  - 2xx: Rückgabe.
  - 4xx außer 408: `KanalFehler` dauerhaft.
  - 408, 5xx, `TimeoutError`, `URLError`, `OSError`: ungewiss, wenn `veroeffentlicht` gilt, sonst dauerhaft.
  - Meldung: `f"{anzeige}: HTTP {status} bei {was}: {rumpf[:300]}"` bzw. `f"{anzeige}: keine Antwort bei {was} – ob der Beitrag entstanden ist, ist UNBEKANNT"`. Immer durch `ohne_geheimnisse`, nie mit URL.
- `json_ruf(...gleiche Parameter...) -> dict`: Ist der Rumpf eines 2xx-Aufrufs mit `veroeffentlicht=True` kein JSON-Objekt, folgt `KanalFehler` ungewiss („Antwort ohne lesbare Kennung“).
- `multipart(felder: Mapping[str, str], dateien: Sequence[tuple[str, str, str, bytes]]) -> tuple[bytes, str]`: `(feld, dateiname, mimetyp, daten)`, Rückgabe `(rumpf, content_type)`, Grenze `uuid4().hex`.

**Interfaces – Produces (`kanal_adapter.py`):**
- `senden_telegram_kanal`, `senden_discord`, `senden_devto` mit der Signatur `Sender`.
  - **Telegram:** `https://api.telegram.org/bot<token>/sendMessage` (JSON `{chat_id, text}`), `sendPhoto` bzw. `sendVideo` (multipart: `chat_id`, `caption`, Datei im Feld `photo`/`video`). Antwort `{"ok": true, "result": {"message_id", "chat": {"username"?}}}`, sonst ungewiss. `beitrag = str(message_id)`. `url`: mit `chat.username` → `https://t.me/<username>/<id>`, bei ID `@name` → `https://t.me/<name>/<id>`, bei `-100<n>` → `https://t.me/c/<n>/<id>`.
  - **Discord:** zuerst `GET <webhook>` (`veroeffentlicht=False`) für `guild_id` und `channel_id`. Dann `POST <webhook>?wait=true`, JSON `{content, allowed_mentions: {"parse": []}}` bzw. multipart mit `payload_json` und `files[0]`. `beitrag = message.id`, `url = https://discord.com/channels/<guild_id>/<channel_id>/<id>`. Geheimnisse: der Webhook-Wert und sein letztes Pfadsegment.
  - **dev.to:** `POST https://dev.to/api/articles`, Kopf `api-key`, JSON `{"article": {"title": titel, "body_markdown": text, "published": false}}`. `beitrag = str(id)`, `url = antwort["url"]`.
- `SENDER: dict[str, Sender]` (Task 3 trägt bluesky und mastodon nach). `assert set(SENDER) <= set(KANAELE)`.

- [ ] **Step 1: Tests schreiben.** Autouse-Fixture: `kanal_api.HTTP` wird ein Rekorder, der vorbereitete `Antwort`en oder Ausnahmen liefert und jede `Anfrage` merkt. Riegel: ruft ein Test mehr auf als vorbereitet, schlägt er fehl, es gibt nie ein echtes Netz.
  - `test_kanal_api.py`:
    - `test_ohne_geheimnisse_ersetzt_werte_und_adressen`: Token `123456:ABCdef` und `https://api.telegram.org/bot123456:ABCdef/sendPhoto` → beides fehlt im Ergebnis, `<geheim>` bzw. `<adresse>` stehen darin.
    - `test_ruf_4xx_dauerhaft`: 400 → `KanalFehler`, `art == "dauerhaft"`, `status == 400`.
    - `test_ruf_5xx_ungewiss_nur_beim_veroeffentlichen`: 503 mit `veroeffentlicht=True` → `ungewiss`, mit `False` → `dauerhaft`.
    - `test_ruf_timeout_ungewiss`: Rekorder wirft `TimeoutError` → `ungewiss`, die Meldung enthält „UNBEKANNT“.
    - `test_kein_schluessel_im_fehlertext`: 401 mit Rumpf, der das Token spiegelt → das Token fehlt in `str(fehler)`, die URL ebenso.
    - `test_json_ruf_unlesbar_beim_veroeffentlichen_ungewiss`: 200 mit Rumpf `"<html>"` → `ungewiss`.
    - `test_multipart_traegt_felder_und_datei`: Rumpf enthält `name="chat_id"`, `filename="a.jpg"` und `Content-Type: image/jpeg`. `content_type` beginnt mit `multipart/form-data; boundary=`.
  - `test_kanal_adapter.py`, je Adapter mindestens Erfolg, 4xx dauerhaft, Timeout ungewiss und „kein Schlüssel im Fehlertext“:
    - `test_telegram_text_erfolg`: Anfrage an `…/sendMessage`, JSON `chat_id == "@vibemind_kanal"`. Beleg `("42", "https://t.me/vibemind_kanal/42")`.
    - `test_telegram_bild_als_caption`: ein Bild → `…/sendPhoto`, multipart mit `caption`.
    - `test_telegram_privater_kanal_url`: ID `-1001234567890`, Antwort ohne username → `https://t.me/c/1234567890/42`.
    - `test_telegram_ok_false_ungewiss`: 200 mit `{"ok": false}` → `ungewiss`.
    - `test_telegram_403_dauerhaft_ohne_token`.
    - `test_telegram_timeout_ungewiss`.
    - `test_discord_erfolg_mit_link`: erst GET, dann POST mit `?wait=true`. Beleg-URL `https://discord.com/channels/G/C/M`.
    - `test_discord_pingt_niemanden`: Text `"@everyone neu!"` → JSON `allowed_mentions == {"parse": []}`.
    - `test_discord_get_scheitert_nichts_gepostet`: GET 404 → `dauerhaft`, genau ein Aufruf.
    - `test_discord_fehlertext_ohne_webhook`: POST 400 → weder Webhook-Wert noch Token-Segment stehen in `str(fehler)`.
    - `test_devto_immer_unveroeffentlicht`: JSON `article.published is False`, `title == titel`, Kopf `api-key` gesetzt. Beleg aus `id`/`url`.
    - `test_devto_422_dauerhaft_ohne_schluessel`, `test_devto_timeout_ungewiss`.
- [ ] **Step 2: Rot.** Beide Dateien → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Umsetzen** nach den Interfaces. Fristen: JSON 30 s, Uploads 300 s (Konstanten `FRIST_JSON`, `FRIST_UPLOAD`).
- [ ] **Step 4: Grün.** Beide Dateien → PASS.
- [ ] **Step 5: Commit** `feat(kanaele): HTTP-Kern und Adapter Telegram-Kanal, Discord, dev.to`

### Task 3: Adapter Bluesky und Mastodon

**Files:**
- Modify: `sales-mcp/kanal_adapter.py`
- Test: `sales-mcp/tests/test_kanal_adapter_upload.py`

**Interfaces – Consumes:** alles aus Task 2.

**Interfaces – Produces:**
- `bluesky_facetten(text: str) -> list[dict]`. Link: `https?://\S+` ohne abschließendes `.,;:!?)`, ergibt `app.bsky.richtext.facet#link` mit `uri`. Hashtag: `(?<!\w)#([^\s#.,;:!?()]+)`, ergibt `#tag` mit `tag` ohne `#`. `index.byteStart`/`byteEnd` sind UTF-8-Byteversätze.
- `senden_bluesky` (Sender). PDS `BLUESKY_PDS = os.environ.get("BLUESKY_PDS", "https://bsky.social")` ist ein optionaler, nicht geheimer Wert und steht nicht in `env_namen`. Ablauf:
  1. `com.atproto.server.createSession` (`identifier` = Handle, `password`; `veroeffentlicht=False`) → `accessJwt`, `did`. Den JWT ab hier zu den Geheimnissen nehmen.
  2. je Bild `com.atproto.repo.uploadBlob` (Rohbytes, `Content-Type` = mimetyp, `veroeffentlicht=False`) → `blob`.
  3. `com.atproto.repo.createRecord` (`veroeffentlicht=True`) mit `record = {"$type": "app.bsky.feed.post", "text", "createdAt" (UTC ISO mit `Z`), "facets", "langs": ["de"]}`. Mit Bildern zusätzlich `embed = {"$type": "app.bsky.embed.images", "images": [{"alt": "", "image": blob}]}`.
  4. `beitrag = uri`, `url = https://bsky.app/profile/<handle>/post/<rkey>` (`rkey` = letztes Segment der `uri`).
- `senden_mastodon` (Sender). Basis `instanz_normalisieren(MASTODON_INSTANCE)`, Kopf `Authorization: Bearer <token>`. Ablauf:
  1. je Medium `POST /api/v2/media` (multipart `file`, `description=""`, `veroeffentlicht=False`) → `id`.
  2. Bei 202 oder `url is None` so lange `GET /api/v1/media/<id>` abfragen, bis `url` gesetzt ist, höchstens `MASTODON_MEDIEN_FRIST_S = 240`, Takt `MASTODON_MEDIEN_TAKT_S = 5`. Das Warten läuft über das Modulattribut `warten = time.sleep`, damit Tests es ersetzen können. Fristablauf → dauerhaft.
  3. `POST /api/v1/statuses` (`veroeffentlicht=True`), JSON `{"status": text, "media_ids": [...], "visibility": "public"}`, Kopf `Idempotency-Key: <schluessel>`.
  4. `beitrag = id`, `url = antwort["url"]`.
- `SENDER` um `bluesky` und `mastodon` ergänzt. Danach gilt `set(SENDER) == set(KANAELE)`.

- [ ] **Step 1: Tests schreiben** (Rekorder-Fixture wie in Task 2):
  - `test_bluesky_facetten_byteversatz`: Text `"Grüße #KünstlicheIntelligenz https://vibemind.de."`. Die Hashtag-Facette hat `byteStart == len("Grüße ".encode())`, `tag == "KünstlicheIntelligenz"`. Die Link-Facette hat `uri == "https://vibemind.de"` und `byteEnd == len("Grüße #KünstlicheIntelligenz https://vibemind.de".encode())`.
  - `test_bluesky_text_erfolg`: ohne Bilder genau zwei Aufrufe (createSession, createRecord). `record.text == text`, `"embed" not in record`. Beleg-URL `https://bsky.app/profile/vibemind.bsky.social/post/3kabc`.
  - `test_bluesky_bilder_alt_leer`: zwei Bilder → zwei uploadBlob-Aufrufe mit `Content-Type: image/png`, `embed.images[*].alt == ""`.
  - `test_bluesky_login_401_dauerhaft_nichts_gepostet`: genau ein Aufruf, `dauerhaft`. Das Passwort fehlt in `str(fehler)`.
  - `test_bluesky_createrecord_timeout_ungewiss`.
  - `test_bluesky_jwt_nie_im_fehlertext`: createRecord 400 mit Rumpf, der den `accessJwt` spiegelt → der JWT fehlt in `str(fehler)`.
  - `test_mastodon_text_erfolg_mit_idempotenz`: genau ein Aufruf an `https://mastodon.social/api/v1/statuses`, Kopf `Idempotency-Key == schluessel`.
  - `test_mastodon_instanz_ohne_schema`: `MASTODON_INSTANCE="mastodon.social"` → URL beginnt mit `https://mastodon.social/`.
  - `test_mastodon_video_wartet_auf_verarbeitung`: v2/media → 202 `{"id": "m1", "url": null}`, dann GET `url: null`, dann GET mit URL, dann statuses mit `media_ids == ["m1"]`. `warten` ersetzt, Aufrufe gezählt.
  - `test_mastodon_verarbeitung_frist_dauerhaft`: GET bleibt `url: null` → `dauerhaft`, kein statuses-Aufruf.
  - `test_mastodon_422_dauerhaft_ohne_token`, `test_mastodon_statuses_503_ungewiss`.
  - `test_sender_fuer_jeden_kanal`: `set(kanal_adapter.SENDER) == set(kanaele.KANAELE)`.
- [ ] **Step 2: Rot.** → FAIL (`AttributeError: bluesky_facetten`).
- [ ] **Step 3: Umsetzen** nach den Interfaces.
- [ ] **Step 4: Grün.** `test_kanal_adapter_upload.py` und `test_kanal_adapter.py` → PASS.
- [ ] **Step 5: Commit** `feat(kanaele): Adapter Bluesky und Mastodon mit Medien-Upload`

### Task 4: Dauerdienst `kanal_dispatch.py`

**Files:**
- Create: `sales-mcp/kanal_dispatch.py`
- Test: `sales-mcp/tests/test_kanal_dispatch.py`

**Interfaces – Consumes:** `kanaele.KANAELE`, `kanaele.zugang_lesen`, `kanaele.zugang_pruefen`, `kanaele.pruefe_entwurf`, `kanaele.status_schreiben`. `kanal_api.KanalFehler`, `kanal_api.Medium`, `kanal_api.Beleg`, `kanal_api.ohne_geheimnisse`. `kanal_adapter.SENDER`. `dispatch._claim_marke`, `dispatch._als_gesendet_buchen`, `dispatch._als_fehler_buchen`, `dispatch._einzeilig`. `medien.pruefe_anhang`, `medien.endpunkt_und_typ`, `medien.lies`. `server._q`.

**Interfaces – Produces:**
- Konstanten: `KANAL_INTERVAL_S` (Env, Vorgabe 60), `KANAL_FRISCHE_TAGE` (Env, Vorgabe 7), `KANAL_ONCE` (Env-Schalter wie `LINKEDIN_ONCE`), `WEG = "kanal-dispatcher"`, `LOG = logging.getLogger("sales-kanaele")`.
- `class BeitragFehler(Exception)`
- `claim(kanal: str, draft_id: str) -> dict | None`: SQL aus den Global Constraints, `returning id, lead_id, subject, body, media_ref, thema`, dazu die `marke`. `kanal not in KANAELE` → `ValueError`.
- `bereits_veroeffentlicht(kanal: str, draft_id: str) -> str | None`: wie bei LinkedIn, aber mit `payload->>'kanal' = %s`.
- `heute_anzahl(kanal: str) -> int`
- `wartende(kanal: str) -> list[dict]`: `approved`, Kanal, `eigenes-profil`, sortiert nach `approved_at`, mit der Spalte `zu_alt` = `approved_at < now() - make_interval(days => %s)`.
- `medien_laden(kanal: str, media_ref: str | None) -> list[Medium]`: wirft `BeitragFehler` bei unzulässigem Namen, unbekannter Art oder einer Grenze aus `pruefe_entwurf`.
- `verarbeite_draft(kanal: str, draft_id: str) -> str`. Ausgänge wie in `linkedin_dispatch.verarbeite_draft`: `schon_veroeffentlicht`, `uebersprungen`, `leer`, `medien_unbrauchbar`, `zu_lang`, `fehler`, `ungewiss`, `ungewiss_ohne_nachweis`, `veroeffentlicht_ohne_nachweis`, `veroeffentlicht_ohne_buchung`, `veroeffentlicht`. Reihenfolge:
  1. `bereits_veroeffentlicht`, dann `claim`.
  2. Text und Medien gegen `pruefe_entwurf` prüfen (Fehler: `_als_fehler_buchen`, „es ging NICHTS raus“).
  3. Zugang aus `os.environ` lesen und senden.
  4. `KanalFehler.ungewiss`: Ungewiss-Beleg schreiben, dann Fehlerbuchung mit `UNGEWISS: …`.
  5. `KanalFehler` dauerhaft: Fehlerbuchung mit dem Text.
  6. Jede andere Ausnahme aus `senden` gilt als **ungewiss**. Ob der veröffentlichende Aufruf schon draußen war, ist dann unbekannt.
  7. Erfolg: zuerst der Beleg (Präzisierung 10), dann `_als_gesendet_buchen`.
  - Alle Texte durch `ohne_geheimnisse` mit den Werten aus `geheim_namen`.
- `eine_runde_kanal(kanal: str) -> str`. Ausgänge:
  - `nicht_verbunden`: schreibt `status_schreiben(..., False, grund)`, Entwürfe bleiben unangetastet.
  - `kadenz`
  - `nichts`: loggt die Zahl liegengebliebener zu alter Freigaben.
  - die Ausgänge von `verarbeite_draft`
  - Bei verbundenem Kanal schreibt sie `status_schreiben(q, kanal, True, <fehlertext oder None>, fehler_loeschen=(ausgang == "veroeffentlicht"))`.
- `eine_runde() -> dict[str, str]`: alle Kanäle der Registry. Jede Ausnahme außer `psycopg.Error` wird je Kanal gefangen, geloggt und als `letzter_fehler` (Typname plus bereinigter Text) geschrieben. Ausgang `"ausnahme"`, die Schleife läuft weiter.
- `main() -> int`: Logging wie bei LinkedIn (auch an `dispatch.LOG`), SIGTERM/SIGINT beenden nach der Runde. Endet nie, weil Zugänge fehlen (Präzisierung 9). `psycopg.Error` → Ausgang `db-ausfall`, weiter. Im Normalzustand (`nichts`, `kadenz`, `nicht_verbunden`) kein Log je Runde. Beim Start eine Zeile mit `schema`, `intervall`, `frische` und der Zahl verbundener Kanäle, nie mit Werten.

- [ ] **Step 1: Tests schreiben** (Stil `test_linkedin_dispatch.py`):
  - Riegel: `SALES_DB_SCHEMA=sales_test` hart gesetzt, Schema-Wache. Autouse-Fixture: truncate `activities, drafts, leads, kanal_status` cascade. Je Kanal eine Attrappe in `kanal_adapter.SENDER` über `monkeypatch.setitem`, die merkt, was veröffentlicht worden wäre. `kanal_api.HTTP` zeigt auf eine Funktion, die den Test scheitern lässt. Gesetzt sind gültige Zugänge für bluesky und mastodon über `monkeypatch.setenv`, die anderen drei Kanäle bleiben ohne Zugang. Hilfsfunktion `_entwurf(kanal, status="approved", approved_vor_tagen=0, media_ref=None, body="Hallo")`.
  - `test_veroeffentlicht_bucht_beleg_vor_sent`: Ausgang `veroeffentlicht`. `drafts.status == "sent"`, genau eine `versand`-Zeile mit `payload == {"draft_id", "kanal": "bluesky", "weg": "kanal-dispatcher", "empfaenger": "eigenes-profil", "beitrag": "at://x/app.bsky.feed.post/1", "url": "https://bsky.app/…", "medienart": "text"}`.
  - `test_doppelversand_ausgeschlossen`: nach Erfolg den Entwurf von Hand auf `approved` zurücksetzen und erneut verarbeiten → `schon_veroeffentlicht`, die Attrappe wurde genau einmal gerufen.
  - `test_claim_greift_nur_eigenes_profil_und_kanal`: Ein `telegram`-Entwurf (Direktnachricht) und ein `linkedin`/`eigenes-profil`-Entwurf auf `approved` bleiben nach `eine_runde()` unverändert.
  - `test_ungewiss_sperrt_wiederholung`: Die Attrappe wirft `KanalFehler(…, ungewiss=True)`. Ausgang `ungewiss`, `drafts.error` beginnt mit `UNGEWISS`, Beleg mit `ungewiss: true` und `beitrag: null`. Erneut freigegeben und verarbeitet → `schon_veroeffentlicht`.
  - `test_unerwartete_ausnahme_beim_senden_ist_ungewiss`: Die Attrappe wirft `KeyError` → Ausgang `ungewiss`.
  - `test_dauerhaft_wird_fehler_und_ist_wiederholbar`: `KanalFehler("x")` → `fehler`, kein `versand`-Beleg.
  - `test_kadenz_je_kanal`: drei Bluesky-Belege von heute → Bluesky `kadenz`, Mastodon veröffentlicht trotzdem. Ein Ungewiss-Beleg zählt mit.
  - `test_frischegrenze`: approved vor 8 Tagen → `nichts`, der Entwurf bleibt `approved`.
  - `test_nicht_verbundener_kanal_bleibt_liegen`: ein freigegebener `discord`-Entwurf ohne Zugang → Ausgang `nicht_verbunden`, Status bleibt `approved`. Die `kanal_status`-Zeile `discord` hat `verbunden false` und `letzter_fehler` enthält `DISCORD_ANKUENDIGUNG_WEBHOOK`.
  - `test_ausfall_eines_kanals_haelt_andere_nicht_auf`: `kanal_dispatch.heute_anzahl` per `monkeypatch` so ersetzt, dass es für `bluesky` `RuntimeError` wirft → `eine_runde()["bluesky"] == "ausnahme"`, `["mastodon"] == "veroeffentlicht"`. Die `kanal_status`-Zeile `bluesky` nennt `RuntimeError` in `letzter_fehler`.
  - `test_zu_langer_text_geht_nicht_raus`: Bluesky-Body mit 301 Zeichen → `zu_lang`, die Attrappe wurde nicht gerufen, im Fehlertext steht „300“.
  - `test_medien_bild_wird_geladen`: Ein PNG in einem `tmp_path`-Medienordner (wie im LinkedIn-Test über `medien.MEDIA_VERZEICHNIS`), `media_ref="a.png"` → die Attrappe bekommt einen `Medium` mit `art="bild"`. Ein `.pdf` → `medien_unbrauchbar`.
  - `test_status_ohne_zugaenge_alle_nicht_verbunden`: Alle Env-Werte entfernt, `eine_runde()` → fünf Zeilen `verbunden false`, alle Ausgänge `nicht_verbunden`.
  - `test_kein_geheimnis_in_status_und_fehler`: Die Attrappe wirft `KanalFehler`, deren Text das App-Passwort enthält → weder `drafts.error` noch `kanal_status.letzter_fehler` enthalten es.
- [ ] **Step 2: Rot.** → FAIL (`ModuleNotFoundError: kanal_dispatch`).
- [ ] **Step 3: Umsetzen** nach den Interfaces. Den Moduldocstring kurz halten und auf `linkedin_dispatch.py` für die ausführliche Begründung von Claim, Beleg und Ungewiss verweisen.
- [ ] **Step 4: Grün.** `test_kanal_dispatch.py` und `test_linkedin_dispatch.py` (unverändert grün) → PASS.
- [ ] **Step 5: Commit** `feat(kanaele): Dauerdienst kanal_dispatch mit Claim, Beleg und Kadenz je Kanal`

### Task 5: Werkzeug `kanal_post_entwurf`, Grenzen beim Bearbeiten, Marketing-Aufträge

**Files:**
- Modify: `sales-mcp/server.py`: neues Werkzeug nach `post_entwurf_erstellen` (ca. Z. 2834). In `_entwurf_erstellen` ein Hinweis bei Kanalwerten der Registry (ca. Z. 2551). In `entwurf_bearbeiten` (ca. Z. 6591) die Grenzen. `versandauftrag_uebernehmen` (ca. Z. 8603). `WERKZEUGE` (ca. Z. 8964).
- Modify: `sales-mcp/lead_fluss.py` (`POST_KANAL`), `sales-mcp/historie.py` (`_KANAL`)
- Test: `sales-mcp/tests/test_kanal_post_entwurf.py`. Ergänzen: `tests/test_versandauftrag.py`, `tests/test_werkzeuge.py` (Zähler), `tests/test_historie.py`

**Interfaces – Consumes:** `kanaele.KANAELE`, `kanaele.pruefe_entwurf`, `kanaele.verbunden`, `medien.pruefe_anhang`, `medien.endpunkt_und_typ`, `medien.pfad`, `server._anhang_gesperrt`, `server.LINKEDIN_POST_LEAD_ID`.

**Interfaces – Produces:**
- `@_gesichert def kanal_post_entwurf(kanal: str, thema: str, text: str, titel: str = "", medien_dateien: str = "", trotzdem: bool = False) -> str` (JSON).
  - Prüfreihenfolge:
    1. Kanal in der Registry, sonst Fehler mit der Liste und dem Satz „LinkedIn: post_entwurf_erstellen“.
    2. Thema und Text nicht leer.
    3. `kanaele.verbunden(_q, kanal)`, sonst `"Kanal <Anzeige> ist noch nicht verbunden – es entsteht kein Entwurf. Zugang eintragen: bash deploy/kanal-zugang-eintragen.sh <kanal>"`.
    4. Doppel-Thema je Kanal (Text wie bei `post_entwurf_erstellen`, Hinweis auf `trotzdem=True`).
    5. Medien: Komma-Liste. Je Name `pruefe_anhang` und `_anhang_gesperrt`. Art über `endpunkt_und_typ` (`send-image` → bild, `send-video` → video, sonst Fehler), Bytes über `os.path.getsize(medien.pfad(basis))`.
    6. `pruefe_entwurf`.
    7. Sammelkontakt gesetzt und vorhanden (Texte wie bei `post_entwurf_erstellen`).
  - Danach Insert nach den Global Constraints. Antwort `{draft_id, status, kanal, medien_dateien, hinweis}`. Der `hinweis` sagt bei devto „wird nach der Freigabe als Entwurf bei dev.to angelegt“, sonst „veröffentlicht sales-kanaele nach der Freigabe“.
  - Der Docstring ist der Werkzeugtext für den Agenten (kurz): eine Fassung je Kanal, Grenzen, keine Kundendaten, vorher den Skill `kanal-post`.
- `_entwurf_erstellen`: Für Kanalwerte aus `KANAELE` lautet der Fehler „<Kanal> ist ein Beitragskanal ohne Empfänger – kanal_post_entwurf nutzen“. Die erlaubten Direktkanäle bleiben unverändert.
- `entwurf_bearbeiten`: bei `d["channel"] in KANAELE` und `recipient == 'eigenes-profil'` die Prüfung `pruefe_entwurf(info, neu, <titel = betreff bei devto, sonst "">, <medien des Ergebnisses>)`. Ein Grund → `{"fehler": grund}`, nichts geändert.
- `lead_fluss.POST_KANAL: dict[str, str] = {"linkedin_post": "linkedin", "bluesky_post": "bluesky", "mastodon_post": "mastodon", "telegram_kanal_post": "telegram_kanal", "discord_post": "discord", "devto_post": "devto"}`.
- `versandauftrag_uebernehmen`: `if kanal in lead_fluss.POST_KANAL`. Ziel `linkedin` → unverändert `post_entwurf_erstellen(betreff, text, medien_datei=datei)`. Sonst `kanal_post_entwurf(ziel, betreff, text, titel=betreff if ziel == "devto" else "", medien_dateien=datei)`. Absage und Annahme wie bisher. Den Docstring um die Postkanäle ergänzen.
- `historie._KANAL` um `"bluesky": "Bluesky", "mastodon": "Mastodon", "telegram_kanal": "Telegram-Kanal", "discord": "Discord", "devto": "dev.to"`.
- `WERKZEUGE`: `kanal_post_entwurf` direkt nach `post_entwurf_erstellen` mit Kommentar (24.10.2026, Verträge `tests/test_kanal_post_entwurf.py`).

- [ ] **Step 1: Tests schreiben.**
  - `test_kanal_post_entwurf.py` (DB). Fixture: truncate inklusive `kanal_status`, Sammelkontakt anlegen wie in `test_linkedin_posts.py`, `status_schreiben(server._q, "bluesky", True, None)` und dasselbe für `devto`:
    - `test_entwurf_pending_am_sammelkontakt`: `kanal_post_entwurf("bluesky", "Herbst", "Hallo #KI")` → Zeile mit `channel='bluesky'`, `recipient='eigenes-profil'`, `subject='Post: Herbst'`, `thema='Herbst'`, `status='pending'`, `lead_id` = Sammelkontakt.
    - `test_nicht_verbunden_klare_ablehnung`: `mastodon` (ohne Zeile) → im Fehler stehen „noch nicht verbunden“ und `kanal-zugang-eintragen.sh mastodon`, kein Insert.
    - `test_unbekannter_kanal_nennt_liste`: `"linkedin"` → Fehler enthält `post_entwurf_erstellen`. `"instagram"` → Fehler enthält `bluesky`.
    - `test_grenze_beim_anlegen`: Bluesky mit 301 Zeichen → Fehler mit „300“.
    - `test_doppel_thema_je_kanal`: zweimal Bluesky „Herbst“ → beim zweiten ein Fehler mit `trotzdem=True`. Mit `trotzdem=True` → angelegt. devto „Herbst“ (mit Titel) → angelegt (anderer Kanal). Nach `rejected` ist es wieder frei.
    - `test_devto_titel_ist_betreff`: `kanal_post_entwurf("devto", "Herbst", "# Text", titel="Unser Herbst")` → `subject='Unser Herbst'`, `hinweis` enthält „Entwurf bei dev.to“. Ohne Titel → Fehler.
    - `test_gesperrte_datei_abgelehnt`: `medien_meta` mit `bot_darf_senden=false` → Fehler wie bei `post_entwurf_erstellen`.
    - `test_ohne_kanal_status_tabelle_nicht_verbunden`: `kanaele.status_lesen` auf `{}` gepatcht → „noch nicht verbunden“.
    - `test_entwurf_erstellen_verweist_auf_kanal_post`: `entwurf_erstellen(lead, "bluesky", "x")` → Fehler enthält `kanal_post_entwurf`.
    - `test_bearbeiten_haelt_kanalgrenze`: Bluesky-Entwurf mit 280 Zeichen, `entwurf_bearbeiten(id, "x" * 340)` → Fehler mit „300“, Body unverändert. Telegram-Kanal-Entwurf (Status für `telegram_kanal` gesetzt) mit Bild und `entwurf_bearbeiten` auf 1500 Zeichen → Fehler mit „1024“.
  - `test_versandauftrag.py` ergänzen (Stil der Datei, `_q` und Werkzeuge gefälscht):
    - `test_postkanaele_sind_eine_zuordnung`: `lead_fluss.POST_KANAL["bluesky_post"] == "bluesky"`, `len(lead_fluss.POST_KANAL) == 6`.
    - `test_bluesky_auftrag_geht_an_kanal_post_entwurf`: Fälschung von `server.kanal_post_entwurf` merkt `(kanal, thema, text, titel, medien_dateien)` → `("bluesky", "Herbst", "Hallo", "", "")`, Auftrag `angenommen`. `empfaenger_leads` wird nicht gerufen.
    - `test_devto_auftrag_betreff_wird_titel`: `titel == betreff`.
    - `test_nicht_verbundener_kanal_wird_abgesagt_mit_grund`: Fälschung liefert `{"fehler": "Kanal Discord ist noch nicht verbunden …"}` → Absage mit diesem Grund wörtlich.
    - `test_linkedin_post_bleibt_beim_alten_weg`: `linkedin_post` → `post_entwurf_erstellen` gerufen, `kanal_post_entwurf` nicht.
  - `test_werkzeuge.py`: Zähler +1 mit Kommentar `24.10.2026: kanal_post_entwurf (Beitraege auf weitere Kanaele)`, dazu `"kanal_post_entwurf" in namen`.
  - `test_historie.py`: `historie._KANAL["telegram_kanal"] == "Telegram-Kanal"`.
- [ ] **Step 2: Rot.** Die vier Dateien → FAIL an den neuen Tests.
- [ ] **Step 3: Umsetzen** nach den Interfaces.
- [ ] **Step 4: Grün.** Die vier Dateien plus `test_linkedin_posts.py` → PASS.
- [ ] **Step 5: Commit** `feat(kanaele): Werkzeug kanal_post_entwurf, Kanalgrenzen beim Bearbeiten, Marketing-Postkanaele`

### Task 6: Skill `kanal-post` und Agenten-Regeln

**Files:**
- Create: `config/workspace/skills/kanal-post/SKILL.md`
- Modify: `config/workspace/AGENTS.md`: Liste „Betreiber-Werkzeuge sind im Kundenchat tabu“ (ca. Z. 639) um `kanal_post_entwurf`, dazu ein kurzer Absatz neben dem zu `post_entwurf_erstellen` (ca. Z. 307).
- Test: `sales-mcp/tests/test_skill_kanal_post.py`. Ergänzen: `tests/test_agents_regeln.py`

**Interfaces – Consumes:** `kanal_post_entwurf(kanal, thema, text, titel, medien_dateien, trotzdem)` aus Task 5.

- [ ] **Step 1: Tests schreiben** (Stil `test_skill_linkedin_post.py`):
  - `test_frontmatter`: Kopf enthält `name: kanal-post`, `description:` mit „Bluesky“, „Mastodon“, „Telegram“, „Discord“ und „dev.to“. `metadata` hat ein `openclaw`-Emoji wie der LinkedIn-Skill.
  - `test_nennt_linkedin_skill_fuer_linkedin`: `"linkedin-post"` steht im Text.
  - `test_je_kanal_grenze_und_hashtag_regel`: Die Zahlen `300`, `500`, `4096`, `1024` und `2000` stehen im Text. „mit Hashtags“ steht im Satz zu Bluesky/Mastodon, „ohne Hashtags“ im Satz zu Discord/Telegram.
  - `test_nur_verbundene_kanaele`: Text enthält „noch nicht verbunden“ und `/einstellungen/kanaele`.
  - `test_vorschau_wortgleich_vor_anlegen`: „wortgleich“ steht im Text, `t.index("Vorschau") < t.index("kanal_post_entwurf(")`. Ein „Ok“ des Betreibers ist Pflicht vor dem Anlegen.
  - `test_devto_als_entwurf`: „Entwurf bei dev.to“ und „Titel“ stehen im Text.
  - `test_agents_regeln.py`: `test_kanal_post_im_kundenchat_tabu` → `"`kanal_post_entwurf`" in _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")`. `test_kanal_post_ueber_skill` → `"Skill `kanal-post`"` steht in TEXT.
- [ ] **Step 2: Rot.** → FAIL (Datei fehlt).
- [ ] **Step 3: Umsetzen.** Der Skill hat die Schritte:
  1. Einsammeln (Thema, Anlass, Bild/Video, Link).
  2. Kanalwahl. Nur verbundene Kanäle anbieten. Wählt der Betreiber einen nicht verbundenen, sagt der Agent das und nennt `/einstellungen/kanaele`.
  3. Je Kanal eine eigene Fassung mit Grenze, Ton und Hashtag-Regel aus den Global Constraints. Bei dev.to Titel und Markdown-Artikel.
  4. Wortgleiche Vorschau aller Fassungen in einer Nachricht.
  5. Erst nach „Ok“ je Kanal `kanal_post_entwurf(…)` aufrufen und die draft_ids nennen.
  - Dazu Regeln: keine Kundendaten, keine Produkt- oder Tarifempfehlung, Doppel-Thema nur mit `trotzdem=True` nach Rückfrage. AGENTS.md: ein Satz „Beiträge auf Bluesky, Mastodon, Telegram-Kanal, Discord und dev.to laufen über den Skill `kanal-post` (`kanal_post_entwurf`)“.
- [ ] **Step 4: Grün.** Beide Dateien → PASS. `deploy/smoke.sh` misst Bootstrap-Grenzen: Wächst `AGENTS.md`, zählt `wc -c config/workspace/AGENTS.md` und muss unter `bootstrapMaxChars` bleiben (Wert in `smoke.sh` Abschnitt 8+9 nachsehen).
- [ ] **Step 5: Commit** `feat(kanaele): Skill kanal-post, Werkzeug im Kundenchat tabu`

### Task 7: Freigaben-Seite kennt die fünf Kanäle

**Files:**
- Modify: `sales-mcp/ui.py`:
  - `FREIGABE_ARTEN` (ca. Z. 8129)
  - `_badge` (ca. Z. 2374), Badge-CSS (ca. Z. 1751)
  - `inbox` (ca. Z. 3623, Block „wartend“ ca. Z. 3697)
  - `_entwurf_karte_offen`
  - `_verlauf_entwuerfe` und `_verlauf_zeile_entwurf` (ca. Z. 3767–3795)
  - `freigaben_verlauf` (404-Text)
  - `heute` (Chips ca. Z. 8324)
- Test: `sales-mcp/tests/test_kanaele_freigabe.py`

**Interfaces – Consumes:** `kanaele.KANAELE`, `kanaele.status_lesen(server._q)`.

**Interfaces – Produces:**
- `FREIGABE_ARTEN = (("whatsapp", "WhatsApp"), ("linkedin", "LinkedIn"), ("email", "E-Mail")) + tuple((k, i.anzeige) for k, i in kanaele.KANAELE.items())`
- `KANAL_ANZEIGE: dict[str, str]` (nur die fünf). `_badge(kanal)` zeigt für diese den Anzeigenamen, sonst unverändert den Rohwert.
- CSS: `.badge.bluesky, .badge.mastodon, .badge.telegram_kanal, .badge.discord, .badge.devto { background: transparent; color: var(--schrift); border: 1px solid var(--lila); }` (Umriss als farbunabhängiges Merkmal).
- `inbox`: Ein Block der fünf neuen Arten erscheint nur, wenn er offene, gescheiterte oder freigegebene Einträge hat oder der Kanal laut `status_lesen` verbunden ist. Bei `heute` erscheinen die Chips der fünf nur mit `> 0` offenen.
- Hinweis an freigegebenen Karten der fünf (`recipient == 'eigenes-profil'`):
  - verbunden → „Der Dienst sales-kanaele veröffentlicht den Beitrag (höchstens <kadenz> pro Tag). Freigaben, die älter als 7 Tage sind, bleiben liegen.“
  - nicht verbunden → „Kanal nicht verbunden – bleibt liegen, bis der Zugang eingetragen ist.“
  - devto zusätzlich „wird als Entwurf bei dev.to angelegt“
  - `approved_at` älter als 7 Tage → „Älter als 7 Tage freigegeben – wird nicht mehr automatisch veröffentlicht.“
- Offene devto-Karte: Hinweis „Freigeben legt den Artikel als Entwurf bei dev.to an – veröffentlicht wird dort von Hand.“
- Verlauf: `_verlauf_entwuerfe` liefert zusätzlich `beleg_url` (left join lateral auf die jüngste `versand`-Zeile mit `payload->>'draft_id' = d.id::text`). `_verlauf_zeile_entwurf` hängt `<a href="…" rel="noopener">Beitrag ansehen</a>` nur an, wenn `beleg_url` mit `https://` beginnt (escaped).
- Der 404-Text von `freigaben_verlauf` nennt die Arten aus `FREIGABE_ARTEN`.
- `_ZEILE_KANAELE` bleibt `("whatsapp", "email")`.

- [ ] **Step 1: Tests schreiben** (Client und Anmeldung wie in den bestehenden UI-Tests, z. B. `test_whatsapp_kopplung.py`/`test_ui.py`. Fixture: truncate `drafts, activities, leads, kanal_status` cascade, Sammelkontakt anlegen):
  - `test_freigaben_zeigt_offenen_bluesky_entwurf`: pending `bluesky` → Seite enthält `class="badge bluesky">Bluesky<` und den Text.
  - `test_leere_unverbundene_kanaele_ohne_block`: ohne Entwürfe und ohne Status → die Seite enthält „Mastodon“ nicht als Blocküberschrift und hat HTTP 200.
  - `test_verbundener_kanal_hat_block`: `status_schreiben(…, "mastodon", True, None)` → Block „Mastodon“ mit „Nichts offen.“
  - `test_kein_direkt_freigeben_in_der_zeile`: pending `discord` mit 50 Zeichen → `ui._direkt_freigebbar(z) is False`. Auf `/` steht kein Zeilen-Freigeben-Formular für diesen Entwurf.
  - `test_devto_hinweis_entwurf_bei_devto`: pending `devto` → „als Entwurf bei dev.to“ steht auf `/freigaben`.
  - `test_freigegeben_nicht_verbunden_hinweis`: approved `discord` ohne Status → „Kanal nicht verbunden – bleibt liegen“.
  - `test_freigegeben_zu_alt_hinweis`: approved `bluesky` (verbunden) mit `approved_at = now() - 8 days` → „Älter als 7 Tage“.
  - `test_verlauf_verlinkt_beleg`: sent `bluesky` plus `versand`-Beleg mit `url` `https://bsky.app/profile/x/post/1` → `/freigaben/verlauf/bluesky` enthält `href="https://bsky.app/profile/x/post/1"`. Ein Beleg mit `url` `javascript:alert(1)` → kein `href` damit.
  - `test_verlauf_unbekannte_art_nennt_neue`: `/freigaben/verlauf/foo` → 404, Text enthält „bluesky“.
  - `test_ohne_kanal_status_tabelle_kein_absturz`: `kanaele.status_lesen` liefert `{}` → `/freigaben` 200.
  - `test_heute_chip_nur_mit_offenen`: ohne neue Entwürfe kein `badge telegram_kanal` auf `/`, mit einem pending genau einer.
- [ ] **Step 2: Rot.** → FAIL an den neuen Tests.
- [ ] **Step 3: Umsetzen** nach den Interfaces.
- [ ] **Step 4: Grün.** `test_kanaele_freigabe.py`, `test_ui.py` und `test_darstellung.py` → PASS (bis auf das vorbestehende Rot).
- [ ] **Step 5: Commit** `feat(ui): Freigaben fuer Bluesky, Mastodon, Telegram-Kanal, Discord, dev.to`

### Task 8: Kanal-Statusseite und „Auf Kanälen teilen“ bei Reels

**Files:**
- Create: `sales-mcp/ui_kanaele.py`
- Modify: `sales-mcp/ui.py`: `_ADMIN_BASIS_PFADE` (ca. Z. 562), `_GRUPPEN` Admin (ca. Z. 2049), `app`-Routen (`*ui_kanaele.routen(sys.modules[__name__])`).
- Modify: `sales-mcp/ui_reels.py`: `aktionen_html` (ca. Z. 317), neue Route `f"{SEITE}/kanaele"`.
- Test: `sales-mcp/tests/test_ui_kanaele.py`. Ergänzen: `tests/test_reels.py`

**Interfaces – Consumes:** `kanaele.KANAELE`, `kanaele.status_lesen`, `server.kanal_post_entwurf`.

**Interfaces – Produces:**
- `ui_kanaele.PFAD = "/einstellungen/kanaele"`, `ui_kanaele.routen(ui) -> list[Route]` (Muster `ui_struktur.routen`, `ui` wird hereingereicht).
- `ui_kanaele.letzte_beitraege(q) -> dict[str, dict]`: `select distinct on (payload->>'kanal') payload, created_at from activities where type='versand' and payload->>'weg'='kanal-dispatcher' order by payload->>'kanal', created_at desc`.
- Seite: eine Tabelle, je Kanal der Registry eine Zeile:
  - Spalte Kanal (Anzeigename)
  - Spalte Verbunden: „Ja“ / „Nein“, „geprüft am …“
  - Spalte Letzter Beitrag: Zeit plus Link „ansehen“ nur bei `https://`, „ungewiss – auf dem Kanal nachsehen“ bei `ungewiss`, sonst „–“
  - Spalte Kadenz/Tag
  - Spalte Grenze: Zeichen, mit Medien
  - Spalte Hinweis: bei „Nein“ die Env-Namen als `<code>` und `bash deploy/kanal-zugang-eintragen.sh <kanal>`, dazu `letzter_fehler` (escaped)
  - Nie ein Env-Wert, die Seite liest keine Umgebung.
- `_ADMIN_BASIS_PFADE` + `"/einstellungen/kanaele"`. `_GRUPPEN["Admin"]` + `("/einstellungen/kanaele", "Kanäle")`.
- Reels:
  - Unter dem LinkedIn-Formular (nur `m == eigene_firma()`) ein zweites Formular `action="{SEITE}/kanaele"` mit den Feldern `datei`, `thema` (Reel-Titel), `text` (Vorschlag = Reel-Titel), `link` (optional, nur `https://`, höchstens 300 Zeichen) und dem Knopf „Auf Kanälen teilen“.
  - Route `kanaele_teilen`: CSRF und Eigentum wie `post_vorbereiten`. Medienart des Reels über `medien.endpunkt_und_typ`. Ziel sind die Kanäle, die laut `status_lesen` verbunden sind und diese Art nehmen (`video_max >= 1` bzw. `bilder_max >= 1`), devto nie.
  - Je Ziel: `fassung = kuerzen(text, grenze - (len(link) + 2 if link else 0)) + ("\n\n" + link if link else "")`. `grenze` = `max_zeichen_mit_medien`. Dann `server.kanal_post_entwurf(kanal, thema, fassung, medien_dateien=datei)`.
  - Kein passender verbundener Kanal → 422 „Kein verbundener Kanal nimmt dieses Reel (Video). Kanäle: /einstellungen/kanaele“. Sonst eine Ergebnisseite mit je Kanal „angelegt“ oder dem Grund (escaped) und dem Link „/freigaben“.
- `ui_reels.kuerzen(text: str, grenze: int) -> str`: Ist der Text zu lang, wird er am letzten Leerzeichen vor `grenze - 1` gekürzt, dazu `…`. Sonst unverändert.

- [ ] **Step 1: Tests schreiben.**
  - `test_ui_kanaele.py`:
    - `test_alle_fuenf_nicht_verbunden_ohne_status`: die Seite hat 200 und für jeden Anzeigenamen „Nein“. `BLUESKY_APP_PASSWORD` steht als Name da, `kanal-zugang-eintragen.sh bluesky` ebenso.
    - `test_kein_env_wert_auf_der_seite`: `monkeypatch.setenv("BLUESKY_APP_PASSWORD", "geheim-xyz-123")` → `"geheim-xyz-123" not in seite`.
    - `test_verbunden_mit_letztem_beitrag`: Status bluesky verbunden, dazu ein Beleg mit `url` → „Ja“ und `href="https://bsky.app/…"`.
    - `test_ungewisser_beleg_ohne_link`: Beleg `ungewiss: true` → „ungewiss“ und kein `href` für diesen Kanal.
    - `test_letzter_fehler_escaped`: `letzter_fehler = "<script>x</script>"` → escaped.
    - `test_nur_freigeben_im_basis_laden`: `ui._pfad_erlaubt("kalender", "/einstellungen/kanaele") is False`. `("freigeben", …)` ist `True` mit `server.SCHEMA == "sales_test"`.
    - `test_im_menue_unter_admin`: `("/einstellungen/kanaele", "Kanäle")` steht in der Admin-Gruppe von `ui._GRUPPEN`.
    - `test_ohne_tabelle_kein_absturz`: `status_lesen` → `{}` ergibt 200.
  - `test_reels.py` ergänzen (Fixtures `angemeldet`, `pult` der Datei):
    - `test_kanaele_knopf_nur_eigene_firma`: Für die eigene Firma stehen `action="/marketing/reels/kanaele"` und „Auf Kanälen teilen“ auf der Seite, für eine fremde nicht.
    - `test_kanaele_teilen_nur_verbundene_mit_video`: Status mastodon, discord und bluesky verbunden, `server.kanal_post_entwurf` gefälscht (merkt die Aufrufe). Reel `vid-…mp4` → Aufrufe genau für `mastodon` und `discord`, nicht für `bluesky` (nimmt kein Video) und nicht für `devto`.
    - `test_kanaele_teilen_kuerzt_und_haengt_link`: Text mit 3000 Zeichen, Link `https://vibemind.de/r` → Discord-Fassung `len <= 2000` und endet auf `"\n\nhttps://vibemind.de/r"`.
    - `test_kanaele_teilen_ohne_verbundenen_422`.
    - `test_kanaele_teilen_link_nur_https`: `link="javascript:x"` → 422.
    - `test_kuerzen`: `kuerzen("aa bb cc dd", 7) == "aa bb…"` (am Leerzeichen gekürzt, `len <= 7`), `kuerzen("kurz", 10) == "kurz"`.
- [ ] **Step 2: Rot.** → FAIL.
- [ ] **Step 3: Umsetzen** nach den Interfaces.
- [ ] **Step 4: Grün.** `test_ui_kanaele.py`, `test_reels.py` und `test_ui.py` → PASS.
- [ ] **Step 5: Commit** `feat(ui): Kanal-Statusseite und Reels auf Kanaelen teilen`

### Task 9: Compose-Dienst `sales-kanaele`, Update, Smoke, Eintrage-Skript, Doku

**Files:**
- Modify: `docker-compose.yml` (neuer Dienst direkt nach `sales-linkedin`, ca. Z. 629)
- Modify: `deploy/update.sh` (`KERN_ALLE` Z. 32; Block „sales-linkedin und sales-telegram TEILEN SICH das sales-mcp-Image“ ca. Z. 327 um `sales-kanaele`)
- Modify: `deploy/smoke.sh` (Abschnitt 1 Containerliste Z. 55; Abschnitt 10 `erwartete_container` Z. 273)
- Modify: `sales-mcp/tests/test_laden_parameter.py` (Mengen Z. 394–401)
- Create: `deploy/kanal-zugang-eintragen.sh`, `deploy/tests/test_kanal_zugang_eintragen.sh`
- Modify: `.env.example`, `docs/10_SECRETS_ROTATION.md`
- Test: `sales-mcp/tests/test_kanal_deploy.py`

**Interfaces – Consumes:** `kanaele.KANAELE` (Env-Namen), `kanal_dispatch.py` als Befehl.

**Interfaces – Produces:**
- Compose-Dienst `sales-kanaele`:
  - `build: ./sales-mcp`, `image: sales-claw-sales-mcp:local`, `container_name: ${LADEN_PRAEFIX:-sales}-kanaele`, `command: python kanal_dispatch.py`, `restart: unless-stopped`, kein `env_file`.
  - `environment`: `SALES_DB_URL=${SALES_DB_URL}`, die neun Kanal-Variablen je `NAME=${NAME:-}`, `BLUESKY_PDS=${BLUESKY_PDS:-https://bsky.social}`, `KANAL_INTERVAL_S=60`, `TZ=${TZ:-Europe/Berlin}`.
  - Beide Medienordner `:ro` wie bei `sales-linkedin`.
  - `stop_grace_period: 120s`, Logging und sonstige Rechte wie bei `sales-linkedin`.
  - Kopfkommentar: nur Basis-Laden (Präzisierung 5), läuft auch ohne Zugänge.
- `KERN_ALLE` endet auf `… sales-linkedin sales-kanaele`. Der Image-Block nimmt `sales-kanaele` mit (nur wenn er läuft).
- `smoke.sh`: Abschnitt 1 prüft `sales-kanaele` (running). Kanäle ohne Zugang prüft smoke nicht. Abschnitt 10 erwartet `sales-kanaele` in der Containermenge.
- `deploy/kanal-zugang-eintragen.sh <kanal>`:
  - `set -euo pipefail`, nie `set -x`.
  - Kanal → Namen per `case`, wörtlich wie in `kanaele.py`. Unbekannter Kanal → Exit 2 mit Liste.
  - Env-Datei `${SALES_ENV_DATEI:-$HOME/sales-claw/.env}`, Projektordner `$(dirname "$ENV_DATEI")`, Befehl `${DOCKER:-docker}`.
  - Je Name `IFS= read -r -s -p "<NAME>: " wert` (Prompt auf stderr), danach `wert="${wert%$'\r'}"`. Leer → Abbruch Exit 3. Zeichen außerhalb `^[A-Za-z0-9._:/@+=~%?&-]+$` → Abbruch Exit 3 mit „<NAME> enthält unzulässige Zeichen“, ohne Wert.
  - Erst wenn alle Werte gelesen sind: `umask 077`, Sicherung `.env.vor-<kanal>-<YYYYmmdd-HHMMSS>` (`cp`, dann `chmod 600`). Neue Datei im selben Ordner aus allen Zeilen ohne `^(NAME1|NAME2)=`, dazu die neuen `NAME=wert`. `chmod 600`, `mv` über die alte.
  - Danach `( cd "$PROJEKT" && $DOCKER compose up -d --no-deps --force-recreate sales-kanaele )`.
  - Ausgabe nur: „<n> Wert(e) für <kanal> eingetragen, Sicherung: <dateiname>. sales-kanaele neu erzeugt – Stand unter /einstellungen/kanaele.“
- `.env.example`: Block „Eigene Kanäle (24.10.2026)“ mit den neun Namen leer und dem Hinweis auf das Skript. `docs/10_SECRETS_ROTATION.md`: je Kanal eine Zeile (Name, wo erzeugt, Rotation = neu erzeugen + Skript erneut).

- [ ] **Step 1: Tests schreiben.**
  - `test_kanal_deploy.py` (rein, liest Dateien):
    - `test_compose_dienst_hat_alle_kanal_variablen_mit_leerer_vorgabe`: Für jeden Namen aller `KANAELE[*].env_namen` steht `f"{n}=${{{n}:-}}"` im Abschnitt `sales-kanaele:` von `docker-compose.yml`. `env_file` steht dort nicht, `command: python kanal_dispatch.py` schon.
    - `test_update_und_smoke_kennen_den_dienst`: `KERN_ALLE` in `update.sh` enthält `sales-kanaele`, die Containerschleife in Abschnitt 1 von `smoke.sh` und `erwartete_container` ebenso.
    - `test_nicht_in_laden_anlegen`: `sales-kanaele` steht nicht in `deploy/laden-anlegen.sh` und nicht in `deploy/laeden/beispiel.env`.
    - `test_eintrage_skript_kennt_dieselben_namen`: Für jeden Kanal stehen dessen Namen im `case`-Zweig `<kanal>)` von `kanal-zugang-eintragen.sh`.
    - `test_env_example_nennt_namen`: alle neun Namen stehen in `.env.example` und in `docs/10_SECRETS_ROTATION.md`.
  - `test_laden_parameter.py`: Die beiden Mengen werden um `sales-kanaele` erweitert (der Test läuft nur mit Docker, `@ohne_docker`).
  - `deploy/tests/test_kanal_zugang_eintragen.sh` (Muster `test_linkedin_nachlauf.sh`, gefälschtes `docker` in `$T`, `SALES_ENV_DATEI=$T/.env` mit den Zeilen `ANDERES=1` und `BLUESKY_HANDLE=alt.bsky.social`):
    1. `printf 'neu.bsky.social\nabcd-efgh-ijkl-mnop\n' | bash kanal-zugang-eintragen.sh bluesky >out 2>err` → Exit 0. `.env` enthält genau eine `BLUESKY_HANDLE=neu.bsky.social`, `BLUESKY_APP_PASSWORD=abcd-efgh-ijkl-mnop` und `ANDERES=1`.
    2. `abcd-efgh` steht weder in `out` noch in `err`.
    3. Genau eine Sicherung `.env.vor-bluesky-*` mit dem alten Inhalt. Auf Linux (`uname -s` = Linux) haben `.env` und die Sicherung `stat -c %a` = 600.
    4. Das docker-Log zeigt `compose up -d --no-deps --force-recreate sales-kanaele` und keinen anderen Dienst.
    5. Ein Wert mit `$` (`'pa$$wort'`) → Exit 3, `.env` unverändert, keine Sicherung, kein docker-Aufruf, der Wert steht nicht in der Ausgabe.
    6. Ein leerer Wert → Exit 3. Ein unbekannter Kanal `instagram` → Exit 2.
    7. Eingabe mit `\r\n` → in `.env` steht der Wert ohne `\r`.
    - Letzte Zeile `OK`.
- [ ] **Step 2: Rot.** `test_kanal_deploy.py` und das Bash-Testskript → FAIL.
- [ ] **Step 3: Umsetzen** nach den Interfaces.
- [ ] **Step 4: Grün.** `test_kanal_deploy.py`, `test_laden_parameter.py` (mit Docker) und `bash deploy/tests/test_kanal_zugang_eintragen.sh` → PASS/`OK`. `docker compose config --env-file /dev/null --services` (Linux) bzw. `--env-file NUL` (Windows) nennt `sales-kanaele` (Lehre: Compose liest sonst die Projekt-`.env`).
- [ ] **Step 5: Commit** `feat(deploy): Dienst sales-kanaele, Zugangs-Skript, Update und Smoke`

### Task 10: Marketing – Migration 092 und Auftragskanäle (vibemind-os)

**Files:**
- Create: `db/092_versandauftraege_kanaele.sql`, `db/verify_092.sql`
- Modify: `claw/werkzeuge.py` (`VERSANDKANAELE` Z. 308, Docstring `versand_beauftragen`), `api/server.py` (Docstring `versandauftrag_anlegen_route` Z. 521), `README.md` (Z. 89)
- Test: `claw/tests/test_versand_beauftragen.py` (ergänzen)

**Interfaces – Produces:**
- 092, idempotent, eine Transaktion:
  - `versandauftraege_kanal_check` per `DROP CONSTRAINT IF EXISTS` + `ADD` mit `('whatsapp','email','linkedin','linkedin_post','telegram','bluesky_post','mastodon_post','telegram_kanal_post','discord_post','devto_post')`.
  - `CREATE OR REPLACE FUNCTION marketing.versandauftrag_anlegen(text,text,text,text,text,text,text)` mit dem **Körper wörtlich aus 043**. Nur drei Änderungen:
    1. Die Kanalliste im ersten `IF` und im Grund nennt die fünf neuen Werte („Beitrag auf den eigenen Kanal, ohne Empfänger“).
    2. `IF p_kanal = 'linkedin_post'` wird zu `IF p_kanal IN ('linkedin_post','bluesky_post','mastodon_post','telegram_kanal_post','discord_post','devto_post')`. Die beiden Absagetexte setzen den Kanal per `format('%s …', p_kanal)` ein.
    3. `v_kennung := 'post:eigenes-profil'` bleibt.
  - Kein `SECURITY DEFINER`, keine neuen GRANTs. Ein `CREATE OR REPLACE` mit gleicher Signatur behält die Rechte, `sales_app` bekommt kein EXECUTE.
  - Kopfkommentar mit RUNBOOK: Ein Replay von 043 überschreibt die Funktion. Danach 092 erneut einspielen und `verify_043` + `verify_092` zusammen proben.
- `VERSANDKANAELE = ("whatsapp", "email", "linkedin", "linkedin_post", "bluesky_post", "mastodon_post", "telegram_kanal_post", "discord_post", "devto_post")`. Der Docstring von `versand_beauftragen` nennt die Postkanäle: ohne `empfaenger`, `betreff` als Thema, bei devto als Titel. Kanal nicht verbunden → sales-claw sagt ab, mit Grund.

- [ ] **Step 1: `verify_092.sql`** im Stil von `verify_043.sql` (Probe-Texte mit `probe_092`, jeder Fall `RAISE EXCEPTION 'verify_092: …'`):
  - (a) CHECK enthält `bluesky_post`. Ein direkter Insert mit `kanal='instagram_post'` scheitert.
  - (b) `versandauftrag_anlegen('bluesky_post', '', 'Hallo', 'Herbst')` → `ok true`. Die Zeile hat `kennung 'post:eigenes-profil'`.
  - (c) Derselbe Aufruf erneut → `wiederholung true`.
  - (d) `'mastodon_post'` mit Empfänger `'a@b.de'` → `ok false`, der Grund enthält `mastodon_post`.
  - (e) `'devto_post'` ohne Betreff → `ok false`.
  - (f) `'instagram_post'` → `ok false`, der Grund enthält „Unzulaessiger Kanal“.
  - (g) `'linkedin_post'` verhält sich wie vorher: ohne Empfänger ok, mit Empfänger der alte Hinweis auf `linkedin`.
  - (h) `has_function_privilege('sales_app', 'marketing.versandauftrag_anlegen(text,text,text,text,text,text,text)', 'EXECUTE')` ist false.
  - (i) `marketing.versandauftraege_offen(50)` liefert die Zeile aus (b) mit `kanal = 'bluesky_post'`.
- [ ] **Step 2: Rot.** Probe nur mit `verify_092.sql` → bricht bei (a) ab.
- [ ] **Step 3: `092_versandauftraege_kanaele.sql`** nach den Interfaces.
- [ ] **Step 4: Grün.** `migration_probe spaces/marketing/db/092_versandauftraege_kanaele.sql spaces/marketing/db/verify_092.sql` → `PROBE OK (zurueckgerollt)`. Dazu `migration_probe 092 verify_043 verify_092` → `PROBE OK`.
- [ ] **Step 5: Tests** in `test_versand_beauftragen.py` (Rekorder der Datei):
  - `test_versandkanaele_kennen_die_postkanaele`: `{"bluesky_post", "mastodon_post", "telegram_kanal_post", "discord_post", "devto_post"} <= set(werkzeuge.VERSANDKANAELE)`. Jeder der Werte steht im Docstring von `versand_beauftragen`.
  - `test_postkanal_geht_ohne_empfaenger_durch`: `kanal="bluesky_post", nachricht="Hallo", betreff="Herbst"` → der Rekorder sieht `daten["kanal"] == "bluesky_post"` und `daten["empfaenger"] == ""`, Ergebnis `ok true`.
  - Rot → umsetzen → `…pytest spaces/marketing/claw/tests/test_versand_beauftragen.py` → PASS. Danach die ganze MOS-Suite: nur das vorbestehende Rot.
- [ ] **Step 6: Commit** `feat(marketing): Migration 092 Postkanaele fuer Versandauftraege` und Push `origin master` (vorher `git fetch && git rebase origin/master`, die Nummer 092 noch einmal prüfen).

### Task 11: Auslieferung und Abnahme (Koordinator, kein Implementierer-Task)

**Auslieferung:**

- [ ] **Step 1: Claims.** `WORKBOARD.md` lesen, den Claim `cc-kanaele-posten` um VM-Deploy und Marketing-Migration ergänzen, nur die eigene Zeile stagen und sofort committen. 092 ein letztes Mal gegen `origin/master` prüfen.
- [ ] **Step 2: provision.sql auf der VM VOR update.sh.** Sicherung `bash ~/sales-claw/deploy/sicherung.sh` (oder den üblichen Dump), dann `psql … -v ON_ERROR_STOP=1 -f db/provision.sql` aus dem neuen Stand (Datei vorher per `scp` oder `git show origin/feat/stufe-1-fundament:db/provision.sql` holen). Prüfen: `\d sales.kanal_status` existiert, `drafts_channel_check` nennt `devto`, ebenso in `sales_ivan`.
- [ ] **Step 3: Marketing-Migration.** Dump von `marketing.versandauftraege` und der Funktion `versandauftrag_anlegen` (`pg_get_functiondef`). Dann `092` einspielen, danach `migration_probe verify_043 verify_092` → `PROBE OK`. MOS ist gepusht (Task 10), die VM-API zieht `marketing-aktualisieren.sh` nach (nur Docstrings, kein Neustart nötig, außer das Skript macht ihn ohnehin).
- [ ] **Step 4: SC pushen** und `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`.
  - Erwartet ist „Abnahme UEBERSPRUNGEN: unvollstaendiger Stack“. `sales-kanaele` steht neu in `KERN_ALLE`, lief vorher nicht, und update.sh startet nur, was vorher lief.
  - Dann `ssh offload-vm 'cd ~/sales-claw && docker compose up -d --no-deps sales-kanaele && bash deploy/smoke.sh --nur-basis'` → „ALLE PRUEFUNGEN GRUEN“.
  - Ab jetzt deckt jedes weitere update.sh den Dienst samt Abnahme ab.
- [ ] **Step 5: Gateway.** AGENTS.md und der neue Skill lösen beim Update den Gateway-Neustart aus. Prüfen mit `docker exec sales-claw sh -c 'ls /home/node/.openclaw/workspace/skills/kanal-post/SKILL.md && grep -c kanal_post_entwurf /home/node/.openclaw/workspace/AGENTS.md'` (≥ 1).
- [ ] **Step 6: Setup-Prompts.** In `C:\Users\User\Desktop\VibeMind-Kanaele-Prompts.md` je Kanal „im OpenFang-Tresor speichern“ ersetzen durch „im Passwort-Manager notieren und mit `bash ~/sales-claw/deploy/kanal-zugang-eintragen.sh <kanal>` auf die VM bringen“ (Datei liegt außerhalb der Repos, nicht committen).

**Abnahme ohne Zugangsdaten** (Spec „Abnahme“, sofort):

- [ ] `docker logs sales-kanaele --tail 20` zeigt eine Startzeile mit „0 verbunden“ und keinen Neustart-Zyklus (`docker inspect -f '{{.RestartCount}}' sales-kanaele` = 0).
- [ ] `/einstellungen/kanaele` (VM-Oberfläche, Rolle freigeben) zeigt alle fünf als „Nein“ mit Env-Namen und Skript-Hinweis. Ivans Laden zeigt den Menüpunkt nicht.
- [ ] Im Betreiber-Chat: „Mach einen Bluesky-Post zu …“ → der Skill sagt „noch nicht verbunden“. Ein direkter Werkzeugaufruf `kanal_post_entwurf` lehnt mit klarer Meldung ab.
- [ ] `/freigaben` und `/` laden unverändert. Ein LinkedIn-Probeweg ist nicht nötig: `docker logs sales-linkedin --since 10m` ohne neuen Fehler, `test_linkedin_dispatch.py` war grün.
- [ ] Smoke grün (Step 4).

**Abnahme mit Test-Zugang** (erst, wenn der Betreiber den ersten Kanal, Bluesky oder Mastodon, mit dem Skript eingetragen hat, und erst nach seinem Ok):

- [ ] `/einstellungen/kanaele` zeigt den Kanal als „Ja“ (spätestens nach 60 s).
- [ ] `kanal_post_entwurf(<kanal>, "Probe", "Test – bitte ignorieren")` anlegen (Chat oder Skill), in `/freigaben` freigeben.
- [ ] Binnen etwa 60 s steht der Beitrag auf dem Kanal. Verlauf und Statusseite zeigen den Beleg-Link.
- [ ] `select payload from sales.activities where type='versand' and payload->>'weg'='kanal-dispatcher' order by created_at desc limit 1` hat die Felder aus Präzisierung 10.
- [ ] Der Betreiber löscht den Beitrag von Hand auf dem Kanal.
- [ ] Claims schließen, Worktrees entfernen (nur eigene), Gedächtnis aktualisieren.
