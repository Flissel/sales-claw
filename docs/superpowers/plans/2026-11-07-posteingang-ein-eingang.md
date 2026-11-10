# Ein Posteingang für Chats und Mails – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/posteingang` zeigt unbeantwortete Chats und die offenen Mails des Besitzers in einer Liste. Mails verlassen sie nur über „beantwortet“, „bezahlt“ oder „erledigt“. Mails und Mail-Verlauf sieht nur ihr Besitzer.

**Architecture:** Die Sichtbarkeit bleibt zentral in `post_struktur.sichtbar_sql`, verengt auf „nur Besitzer“. Ein neues Modul `post_erledigt.py` trägt den Erledigt-Zustand (Spalten an `post_mails`), die Liste offener Mails und den Antwort-Abgleich. Den Abgleich ruft `sales-post` je Runde ohne Modell auf. `ui.py` (Posteingang, Menü, Kontakt-Verlauf) und `ui_post.py` (Knöpfe) nutzen nur diese Schnittstellen.

**Tech Stack:** Python 3.12, Starlette (serverseitiges HTML), psycopg/PostgreSQL (Schema je Laden), imaplib, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-posteingang-ein-eingang-design.md`

## Global Constraints

- Tests laufen nur in `sales_test` auf der VM. Kein SQL gegen `sales` ohne Felix' OK. So wird getestet (VM `offload-vm`, Branch vorher pushen):
  `git clone -q --depth 1 -b feat/posteingang-ein-eingang https://github.com/Flissel/sales-claw.git /tmp/pa-pe && cd ~/sales-claw && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test -v /tmp/pa-pe/sales-mcp:/app sales-claw-sales-mcp:local python -m pytest -q -p no:cacheprovider <dateien>`.
  Vorher die geänderte `db/post-sammelstelle.sql` in `sales_test` einspielen. Danach `/tmp/pa-pe` per Container löschen (`docker run --rm -v /tmp:/t sales-claw-sales-mcp:local rm -rf /t/pa-pe`). Nie zwei Läufe parallel.
- 34 Post-Tests scheitern schon auf der Basis (Dateien außerhalb `sales-mcp` fehlen im Container). Maßstab ist **keine neue** Abweichung gegenüber der Basis `1aaa2be`.
- Schema-Änderungen nur idempotent in `db/post-sammelstelle.sql` (`add column if not exists`).
- **Logs:** Keine Geheimnisse und kein Mailtext in Logs, nur IDs, Zahlen und Ausnahmetypen.
- **Ladenfest:** Der zweite Laden bucht nie auf Schema oder IDs des Betreibers. Der Container-Besitzer kommt immer aus `POST_BESITZER` der eigenen Umgebung.
- **Datenzugriff:** Mailfunktionen lesen nur über `post_struktur.sichtbar_sql` bzw. `mail_lesen`.
- **IMAP:** Der Abgleich öffnet Ordner nur lesend (`select(..., readonly=True)`) und schreibt nie ins Postfach.
- Kein Deploy ohne Felix' OK. Commits auf `feat/posteingang-ein-eingang`, Conventional Commits mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Login ohne `benutzer`-Zeile** (Basis-Zugang über Tailscale ohne persönliche Anmeldung) öffnet `/posteingang`. Erwartung: Chats wie bisher, keine Mails, Hinweis „Mails nur mit persönlicher Anmeldung“. Abgedeckt durch Test in Task 6.
2. **`POST_AUFRAEUMEN_AB` nicht gesetzt.** Erwartung: keine Mail im Posteingang, sichtbarer Hinweis. Der Abgleich tut nichts. Abgedeckt durch Tests in Task 3 und Task 6.
3. **Zweiter Laden mit anderem `POST_BESITZER`.** Der Agent und der Verlauf dort sehen nie Mails eines anderen Besitzers. Abgedeckt durch Test in Task 1.
4. **Mail ohne echte Message-ID** (`message_id_ersatz`). Erwartung: Der Abgleich sucht nicht im Gesendet-Ordner (ein Platzhalter beweist nichts), prüft nur `\Answered` und Entwürfe. Abgedeckt durch Test in Task 4.
5. **Absender mit Namen und Großbuchstaben** („Max <Max@Firma.de>“) gegenüber `leads.email = max@firma.de`. Die Zuordnung trifft trotzdem. Abgedeckt durch Test in Task 3.

---

### Task 1: Mails sieht nur ihr Besitzer

**Files:**
- Modify: `sales-mcp/post_struktur.py` (`Betrachter`/`BETREIBER_AGENT` ab Zeile 174, `sichtbar_sql` ab Zeile 204)
- Modify: `sales-mcp/ui_post.py:313-317` (`darf_korrigieren`)
- Test: `sales-mcp/tests/test_post_sichtbarkeit.py`, `sales-mcp/tests/test_ui_post.py`

**Interfaces:**
- Produces: `post_struktur.container_besitzer() -> str` (liest `POST_BESITZER` bei jedem Aufruf, `strip()`, sonst `""`).
- Produces: `post_struktur.mail_verlauf_erlaubt(name: str | None) -> bool`. Wahr genau dann, wenn `name` nicht leer ist und `container_besitzer()` gleich `name` ist.
- Produces: `sichtbar_sql(b)` mit neuer Bedeutung:
  - Menschen: `m.besitzer = b.name`, egal welcher Bereich.
  - Agent: `m.bereich = 'business' and m.sensibel is false and m.besitzer = <container_besitzer()>`.
  - Agent bei leerem `POST_BESITZER`: `false`.

- [ ] **Step 1: Failing Tests schreiben bzw. umschreiben** in `test_post_sichtbarkeit.py`:
  - Diese Tests drehen sich um, Erwartung jetzt „sieht nichts“:
    - `test_business_nach_abteilung` → `test_abteilung_sieht_fremde_business_nicht`
    - `test_leitung_sieht_alle_business` → `test_leitung_sieht_fremde_mails_nicht`
    - `test_unklar_nur_leitung_und_besitzer` und `test_sensible_business_mail_nur_besitzer_und_leitung`: Die Leitung sieht fremde Mails nicht mehr, der Besitzer sieht sie weiter.
  - Neu:
    - `test_agent_sieht_nur_business_des_container_besitzers`: monkeypatch `POST_BESITZER=t_anna`. Sichtbar ist annas Business-Mail, nicht bens Business-Mail.
    - `test_agent_ohne_container_besitzer_sieht_nichts`: `POST_BESITZER` leer → 0 Mails.
    - `test_mail_verlauf_erlaubt`: `("t_anna" mit POST_BESITZER=t_anna) → True`, `"t_ben" → False`, `None → False`, leerer Besitzer → False.
  - In `test_ui_post.py`: Tests, die Korrekturen oder Ziel-Setzen durch die Leitung (`t8_lea`) an fremder Post erwarten, erwarten jetzt 403. Den Docstring-Satz „Korrekturen darf nur Besitzer oder Leitung“ auf „nur Besitzer“ ändern.
- [ ] **Step 2: Laufen lassen, Fehlschlag prüfen** (Befehl aus Global Constraints, Dateien `tests/test_post_sichtbarkeit.py tests/test_ui_post.py`). Erwartet: Die neuen und umgedrehten Tests scheitern.
- [ ] **Step 3: Umsetzen.**
  - `sichtbar_sql` wie unter Interfaces.
  - `BETREIBER_AGENT` bleibt der Name des Agenten.
  - `darf_korrigieren` → `rolle(request) == "freigeben" and m["besitzer"] == b.name`.
  - Den Kommentar in `ziel_setzen` („die Leitung darf eine fremde Mail umlegen“) und die Fehlermeldung „… oder die Leitung“ anpassen.
  - `Betrachter.leitung`/`abteilungen` bleiben als Felder; `post_abteilung_faecher` wird für Mails nicht mehr abgefragt, die Tabelle bleibt.
- [ ] **Step 4: Tests grün** (dieselben Dateien plus `tests/test_post_*.py` gegen die Basis-Fehlerliste).
- [ ] **Step 5: Commit** `fix(post): Mails sieht nur ihr Besitzer, auch nicht die Leitung`.

### Task 2: Mail-Einträge im Kontakt-Verlauf nur für den Besitzer

**Files:**
- Modify: `sales-mcp/server.py` (`posteingang`, Abfrage ab ca. Zeile 4540)
- Modify: `sales-mcp/ui.py` (`_kontakt_verlauf` Zeile 7621, Aufruf in `kontakt_detail` Zeile 7822, `_posteingang_suche` Zeile 8077)
- Test: `sales-mcp/tests/test_ui.py` (oder die Datei, in der `kontakt_detail`/Posteingang schon getestet werden), `sales-mcp/tests/test_posteingang*.py` falls vorhanden

**Interfaces:**
- Consumes: `post_struktur.mail_verlauf_erlaubt(name)` (Task 1).
- Produces: `ui._kontakt_verlauf(lead_id, alle: bool, betrachter_name: str | None) -> str`.
- Produces: `server.posteingang()` liefert keine Zeilen mit `payload->>'kanal' = 'email'` mehr. Mails kommen ab Task 6 aus `post_mails`.
- **Festlegung:** `server.mail_beantworten` bleibt unverändert. Eine Antwort ist eine bewusste Handlung, und der Entwurf braucht eine `lead_id`. Deshalb darf dort weiter ein Kontakt entstehen. Die gebuchte `kundenantwort` (kanal email) schützt der Filter aus diesem Task. Automatisch entstehen Kontakte nur dort nicht, wo niemand handelt, also im Posteingang (Task 6).

- [ ] **Step 1: Failing Tests:**
  - `test_verlauf_email_nur_fuer_container_besitzer`: Ein Kontakt hat eine `kundenantwort` mit `{"kanal": "email", "text": "MAILTEXT-123"}` und eine WhatsApp-`kundenantwort` mit `"WA-456"`. `POST_BESITZER=t_anna`.
    - `/kontakte/<id>` als t_anna enthält „MAILTEXT-123“.
    - Als t_ben (freigeben) fehlt „MAILTEXT-123“, „WA-456“ ist da.
    - Ohne persönliche Anmeldung fehlt „MAILTEXT-123“.
  - `test_posteingang_werkzeug_ohne_email_zeilen`: `json.loads(server.posteingang())["eintraege"]` enthält den E-Mail-Eintrag nicht, den WhatsApp-Eintrag schon.
  - `test_posteingang_suche_findet_email_aktivitaet_nur_fuer_besitzer`: `/posteingang?q=MAILTEXT` als t_ben ohne Treffertext.
- [ ] **Step 2: Laufen lassen, Fehlschlag prüfen.**
- [ ] **Step 3: Umsetzen.**
  - In `server.posteingang` im CTE `fenster`: `and coalesce(a.payload->>'kanal','') <> 'email'`.
  - In `_kontakt_verlauf` und `_posteingang_suche`: Ist `mail_verlauf_erlaubt(betrachter_name)` falsch, kommt `and coalesce(payload->>'kanal','') <> 'email'` in das WHERE. Das gilt für alle Typen, also auch für ausgehende `versand`-Zeilen einer E-Mail.
  - `kontakt_detail` und `posteingang` geben `request.scope.get("benutzer_name")` weiter.
- [ ] **Step 4: Tests grün** (Basisvergleich wie Task 1).
- [ ] **Step 5: Commit** `fix(ui): Mail-Eintraege im Verlauf nur fuer den Postfach-Besitzer`.

### Task 3: Erledigt-Zustand und Liste offener Mails (`post_erledigt.py`)

**Files:**
- Modify: `db/post-sammelstelle.sql` (am Ende anhängen)
- Create: `sales-mcp/post_erledigt.py`
- Test: `sales-mcp/tests/test_post_erledigt.py` (Fixtures nach dem Vorbild von `tests/test_post_ordnen.py`: `db`, `_konto`, `_mail`)

**Interfaces:**
- Schema `post_mails`:
  - `erledigt_am timestamptz`
  - `erledigt_art text check (erledigt_art in ('beantwortet','bezahlt','erledigt'))`
  - `bezahlt_am timestamptz`
  - `abgeglichen_am timestamptz`
  - `abgleich_aus boolean not null default false`
  - Index `post_mails_offen_idx on (besitzer, ziel) where erledigt_am is null`
- Produces in `post_erledigt.py`:
  - `RECHNUNGEN = "Rechnungen"`, `ARTEN = ("erledigt", "bezahlt")`, `JE_SEITE = 50`
  - `offen_sql() -> str`: WHERE-Fragment für `post_mails m`, ohne Parameter. Bedingungen:
    - `m.ziel = 'posteingang'`
    - `m.status = 'eingeordnet'`
    - `m.erledigt_am is null`
    - `m.abgeglichen_am is not null`
    - `m.geloescht_am is null`
    - `m.datum >= '<post_ziel.ALTBESTAND_AB>'`. Ist `ALTBESTAND_AB == date.max`, liefert die Funktion `false`.
  - `stichtag_gesetzt() -> bool`
  - `mails_offen(b: Betrachter, suche: str = "", seite: int = 1) -> tuple[list[dict], int]`: Seite und Gesamtzahl. Die Zeilen haben die Spalten aus `post_struktur._spalten()` plus `kennung` (Konto) und `lead_id` (Kontakt mit gleicher Adresse oder `None`). Sortiert nach `datum asc` (am längsten wartend zuerst). `suche` nutzt `suchtext` wie `mails_suchen`.
  - `erledigen(b: Betrachter, mail_id: str, art: str) -> bool`:
    - `art` muss in `ARTEN` liegen.
    - `bezahlt` nur bei `fach == RECHNUNGEN`. Setzt dann `bezahlt_am` und `erledigt_art='bezahlt'`.
    - Nur der Besitzer (`mail_lesen(b, id)` und `m["besitzer"] == b.name`), nur wenn noch offen.
    - Rückgabe `False` statt Ausnahme.
  - `wieder_oeffnen(b: Betrachter, mail_id: str) -> bool`: Leert `erledigt_am`, `erledigt_art` und `bezahlt_am`, setzt `abgleich_aus = true`. Nur der Besitzer.
  - `kontakt_anlegen(b: Betrachter, mail_id: str) -> str | None`:
    - Gibt die `lead_id` zurück.
    - Gibt es schon einen Lead mit dieser Adresse (Vergleich `lower`), kommt dessen ID.
    - Sonst `insert into leads (name, email, source) values (<Anzeigename oder Teil vor @>, <adresse>, 'email')`.
    - `None` bei fremder Mail oder ohne Adresse.

- [ ] **Step 1: Failing Tests:**
  - `test_offen_nur_ab_stichtag_und_abgeglichen`: monkeypatch `post_ziel.ALTBESTAND_AB = date(2026,11,1)`. Diese drei Mails sind **nicht** in `mails_offen`:
    - Mail vom 31.10.
    - Mail vom 02.11. ohne `abgeglichen_am`
    - Mail vom 02.11. mit `ziel='zur_info'`
    Die Mail vom 02.11. mit `ziel='posteingang'` und `abgeglichen_am` ist drin.
  - `test_ohne_stichtag_keine_mails`: `ALTBESTAND_AB = date.max` → `([], 0)`, und `stichtag_gesetzt()` ist falsch.
  - `test_nur_eigene_mails`: Die offene Mail von t_ben erscheint bei t_anna nicht.
  - `test_erledigen_und_wieder_oeffnen`:
    - Nach `erledigen(anna, id, "erledigt")` ist die Mail weg, `erledigt_art == 'erledigt'`.
    - Nach `wieder_oeffnen` ist sie wieder da, `abgleich_aus` ist wahr.
  - `test_bezahlt_nur_bei_rechnungen`:
    - `erledigen(..., "bezahlt")` bei Fach „Kunden & Anfragen“ → `False`, nichts geändert.
    - Bei „Rechnungen“ → `True`, `bezahlt_am` gesetzt.
    - `erledigen(..., "erledigt")` bei Rechnungen lässt `bezahlt_am` leer.
  - `test_fremde_mail_nicht_erledigbar`: Ben erledigt annas Mail → `False`.
  - `test_kontakt_zuordnung_ohne_gross_klein`: Mail von „Max <Max@Firma.de>“, Lead `max@firma.de` → `lead_id` gesetzt.
  - `test_kontakt_anlegen`:
    - unbekannte Adresse → neue Lead-ID
    - zweiter Aufruf → dieselbe ID
    - fremde Mail → `None`
- [ ] **Step 2: Schema in `sales_test` einspielen, Tests laufen lassen, Fehlschlag prüfen.**
- [ ] **Step 3: Umsetzen** in `post_erledigt.py`. Die Absender-Adresse für den Kontakt-Vergleich kommt in SQL aus `lower(coalesce(substring(m.von from '<([^>]+)>'), trim(m.von)))`. Diesen Ausdruck als Konstante `ABSENDER_SQL` exportieren, Task 7 nutzt ihn wieder.
- [ ] **Step 4: Tests grün.**
- [ ] **Step 5: Commit** `feat(post): Erledigt-Zustand und Liste offener Mails`.

### Task 4: Antwort-Abgleich je Runde

**Files:**
- Modify: `sales-mcp/post_imap.py` (neue Lesefunktionen)
- Modify: `sales-mcp/post_erledigt.py` (`abgleich`)
- Modify: `sales-mcp/post_abholen.py:600-614` (`_aufraeumen`)
- Modify: `sales-mcp/tests/test_post_imap.py` (`FakeKasten`: `UID FETCH <uid> (FLAGS)` liefert `self.flags`)
- Test: `sales-mcp/tests/test_post_erledigt.py`, `sales-mcp/tests/test_post_imap.py`

**Interfaces:**
- Produces in `post_imap.py`:
  - `flags_lesen(kasten, ordner: str, uids: list[int]) -> dict[int, set[str]]`: öffnet nur lesend. Fehlt eine UID, ist sie nicht im Ergebnis. Fehlt der Ordner, wirft sie `Fehlt`.
  - `gesendet_ordner(kasten) -> str | None`: der Ordner mit Merkmal `\Sent` aus `postfach._ordner_liste`, sonst `None`.
  - `antwort_gesendet(kasten, ordner: str, message_id: str) -> bool`: Ordner lesend öffnen, dann `UID SEARCH HEADER In-Reply-To "<mid>"`. Ohne Treffer zusätzlich `HEADER References "<mid>"`. Leere `message_id` → `False`.
- Produces in `post_erledigt.py`: `abgleich(verbinden=None, je_konto: int = 50) -> dict`.
  - Rückgabe: Bilanz `{"geprueft", "beantwortet", "fehlt", "konten_fehler"}`.
  - Kandidaten je aktivem Konto mit `besitzer = container_besitzer()`:
    - `ziel = 'posteingang'`, `status = 'eingeordnet'`, `erledigt_am is null`
    - `not abgleich_aus`, `geloescht_am is null`
    - `datum >= ALTBESTAND_AB`
    - Reihenfolge: `abgeglichen_am nulls first`, dann älteste zuerst. Höchstens `je_konto`.
  - Ohne Stichtag oder Container-Besitzer → leere Bilanz ohne Verbindung.
  - Eine Mail gilt als beantwortet bei einem dieser drei Signale:
    1. `exists (select 1 from drafts d where d.status = 'sent' and d.antwort_auf = m.message_id)`, nur wenn nicht `message_id_ersatz`
    2. `\Answered` in `flags_lesen(ordner, uid)`. UID ist `imap_uid` bei `ordner = 'INBOX'`, sonst `ordner_uid`.
    3. `antwort_gesendet(...)`, nur wenn nicht `message_id_ersatz`.
  - Treffer → `erledigt_am = now(), erledigt_art = 'beantwortet'`.
  - Nicht gefundene UID → `ordner_stand = 'fehlt'`, die Mail bleibt offen.
  - Jede geprüfte Mail → `abgeglichen_am = now()`.
  - Ein Konto-Fehler zählt `konten_fehler`, danach geht es beim nächsten Konto weiter. Ins Log nur der Typ.

- [ ] **Step 1: Failing Tests** mit `FakeKasten` und `verbinden`-Ersatz (Muster `test_post_ordnen._verbinden`):
  - `test_flags_lesen_und_fehlende_uid` in `test_post_imap.py`. Dazu `test_gesendet_ordner_ueber_merkmal`: `merkmale={"Gesendet": "\\Sent"}` → `"Gesendet"`.
  - `test_antwort_gesendet_ueber_in_reply_to`: Der Gesendet-Ordner hat eine Mail, deren Rohtext `In-Reply-To: <m7@x>` enthält → `True`. Mit anderer ID → `False`.
  - `test_abgleich_answered_markiert_beantwortet`: Flag `\Answered` auf INBOX-UID 7 → `erledigt_art='beantwortet'`, `abgeglichen_am` gesetzt.
  - `test_abgleich_gesendet_bei_gmail` und `test_abgleich_entwurf_sent`: Entwurf in `drafts` mit `status='sent'` und `antwort_auf = message_id` → beantwortet, ohne IMAP-Treffer.
  - `test_abgleich_fehlende_mail_bleibt_offen`: UID fehlt → `ordner_stand='fehlt'`, `erledigt_am` leer.
  - `test_abgleich_ersatz_id_ohne_gesendet_suche`: Bei `message_id_ersatz` gibt es kein `SEARCH` im Protokoll.
  - `test_abgleich_ueberspringt_wieder_geoeffnete`: Mit `abgleich_aus=true` und `\Answered` bleibt die Mail offen.
  - `test_abgleich_ohne_stichtag_verbindet_nicht`.
  - `test_abgleich_schreibt_nie`: Kein `STORE`, `MOVE`, `COPY` oder `EXPUNGE` im Protokoll, alle `select` mit `readonly=True`.
- [ ] **Step 2: Fehlschlag prüfen.**
- [ ] **Step 3: Umsetzen.** In `post_abholen._aufraeumen` nach `ziele_aktualisieren`:

  ```python
  try:
      bilanz["abgleich"] = post_erledigt.abgleich()
  except Exception as e:  # noqa: BLE001
      LOG.warning("Abgleich fehlgeschlagen (%s)", type(e).__name__)
  ```

  Das läuft unabhängig von `POST_ORDNEN` und von der Tagesgrenze.
- [ ] **Step 4: Tests grün,** auch `tests/test_post_abholen.py`.
- [ ] **Step 5: Commit** `feat(post): Antworten erkennen (Answered, Gesendet, versandter Entwurf)`.

### Task 5: Knöpfe Erledigt, Bezahlt, Wieder öffnen und Kontakt anlegen

**Files:**
- Modify: `sales-mcp/ui_post.py` (Routen ab Zeile 877, Mail-Ansicht `mail`)
- Test: `sales-mcp/tests/test_ui_post.py`

**Interfaces:**
- Consumes: `post_erledigt.erledigen`, `wieder_oeffnen`, `kontakt_anlegen`, `RECHNUNGEN` (Task 3).
- Produces: diese POST-Routen, jeweils mit CSRF wie `ziel_setzen`:
  - `/post/mail/{mail_id}/erledigt` (Formfeld `art` aus `erledigt|bezahlt`)
  - `/post/mail/{mail_id}/wieder-offen`
  - `/post/mail/{mail_id}/kontakt`
  - Optionales Formfeld `zurueck`, erlaubt nur `"/posteingang"`, sonst die Mail-Ansicht.
  - Erfolg → 303 Redirect, `/kontakt` → `/kontakte/<lead_id>`.
  - Fremde Mail → 403. Ungültige `art` → 400.

- [ ] **Step 1: Failing Tests:**
  - `test_erledigt_knopf_nur_besitzer`: anna → 303 und die Mail ist erledigt. ben → 403.
  - `test_bezahlt_nur_bei_rechnungen_ui`: Bei „Kunden & Anfragen“ → 400. Die Mail-Ansicht einer Rechnung zeigt den Knopf „Bezahlt“, andere Mails zeigen ihn nicht.
  - `test_zurueck_nur_erlaubte_ziele`: `zurueck=https://evil.example` → Redirect auf `/post/mail/<id>`.
  - `test_wieder_oeffnen_zeigt_mail_wieder`.
  - `test_kontakt_anlegen_leitet_zum_kontakt`.
  - `test_aktionen_ohne_csrf_403`.
- [ ] **Step 2: Fehlschlag prüfen.**
- [ ] **Step 3: Umsetzen.** Die Mail-Ansicht zeigt den Erledigt-Zustand, etwa „Erledigt am … (beantwortet)“, und je nach Zustand die Knöpfe. Gestaltung wie die bestehenden Ziel-Knöpfe.
- [ ] **Step 4: Tests grün.**
- [ ] **Step 5: Commit** `feat(ui): Mails erledigen, als bezahlt markieren, wieder oeffnen, Kontakt anlegen`.

### Task 6: Gemeinsame Posteingang-Seite und Menü

**Files:**
- Modify: `sales-mcp/ui.py`: `_GRUPPEN` (Zeile 2040–2083), `posteingang` (Zeile 8002), `_mails_verweis` (Zeile 8068), `_posteingang_suche`
- Test: `sales-mcp/tests/test_ui_post.py` (Login-Welt) bzw. die bestehenden Posteingang-Tests in `tests/test_ui.py`

**Interfaces:**
- Consumes:
  - `post_erledigt.mails_offen`, `stichtag_gesetzt`, `JE_SEITE`, `RECHNUNGEN` (Task 3)
  - die Routen aus Task 5
  - `server.posteingang()` ohne E-Mail-Zeilen (Task 2)
- Produces:
  - Menü: Erste Gruppe `("Eingang", (("/posteingang", "Posteingang"), ("/post", "Mails")))`. Beide Einträge fallen aus „Analyse“.
  - `/posteingang?seite=n` blättert durch die Mails.

- [ ] **Step 1: Failing Tests:**
  - `test_menue_eingang_zuerst`: Die Seitenleiste nennt „Posteingang“ vor „Heute“. Unter „Analyse“ stehen weder „Posteingang“ noch „Mails“.
  - `test_posteingang_zeigt_chat_und_mail_gemischt`:
    - Aufbau: eine WhatsApp-`kundenantwort` (vor 3 Std.) und eine offene Mail von anna (vor 5 Std.), `ALTBESTAND_AB` gesetzt.
    - Als anna sind beide da, die Mail steht oben (wartet länger).
    - Abzeichen „E-Mail“ und die Konto-Kennung sind da.
    - Es gibt einen „Erledigt“-Knopf und bei Fach Rechnungen den Knopf „Bezahlt“.
  - `test_posteingang_ohne_persoenliche_anmeldung_zeigt_keine_mails`: Der Hinweistext „Mails nur mit persönlicher Anmeldung“ ist da, der Mailbetreff fehlt.
  - `test_posteingang_ohne_stichtag_hinweis`: Der Hinweis nennt `POST_AUFRAEUMEN_AB`.
  - `test_posteingang_fremde_mail_unsichtbar`: ben sieht annas Mail nicht.
  - `test_posteingang_sensible_mail_nur_kopf`: Der Text einer sensiblen Mail fehlt, der Betreff ist da.
  - `test_posteingang_unbekannter_absender_kontakt_anlegen` / `..._bekannter_absender_link`: ohne Kontakt der Knopf „Kontakt anlegen“, mit Kontakt ein Link auf `/kontakte/<id>`.
  - `test_posteingang_fehlt_hinweis`: Bei `ordner_stand='fehlt'` steht dort „im Postfach nicht mehr gefunden“.
  - `test_posteingang_suche_mails_des_besitzers`: `q` findet den Betreff von annas Mail bei anna, nicht bei ben.
- [ ] **Step 2: Fehlschlag prüfen.**
- [ ] **Step 3: Umsetzen.**
  - Seite 1 zeigt alle Chats aus `server.posteingang()` und die erste Seite Mails, gemischt nach Wartezeit. Bei Mails ist das `datum`, bei Chats `wartet_stunden`.
  - Folgeseiten zeigen nur Mails.
  - Überschrift: „Offen (<Chats + Mails gesamt>)“.
  - Der Mail-Eintrag verlinkt auf `/post/mail/<id>`. Knöpfe als Formulare mit `zurueck=/posteingang`.
  - `_mails_verweis` entfällt, ein Verweis auf „Zur Info“ unter `/post` bleibt.
  - Die Suche zeigt Chat-Treffer (Task 2) und `mails_offen`-unabhängige Mail-Treffer über `post_struktur.mails_suchen(b, suche, grenze=20)`.
- [ ] **Step 4: Tests grün,** auch die bestehenden Posteingang- und Heute-Tests.
- [ ] **Step 5: Commit** `feat(ui): ein Posteingang fuer Chats und Mails, ganz oben im Menue`.

### Task 7: Mails am Kontakt und Runbook

**Files:**
- Modify: `sales-mcp/ui.py` (`_kontakt_verlauf`)
- Modify: `docs/03_RUNBOOK.md` (neuer Abschnitt nach „Post aufraeumen … Einschalten“)
- Test: `sales-mcp/tests/test_ui_post.py`

**Interfaces:**
- Consumes:
  - `post_erledigt.ABSENDER_SQL` (Task 3)
  - `post_struktur.betrachter_laden`, `sichtbar_sql` (Task 1)
  - `betrachter_name` in `_kontakt_verlauf` (Task 2)

- [ ] **Step 1: Failing Tests:**
  - `test_verlauf_zeigt_mails_des_kontakts_nur_dem_besitzer`:
    - Aufbau: Lead `max@firma.de`, Mail von anna „Max <MAX@firma.de>“ mit Betreff „Angebot 42“.
    - anna sieht im Verlauf einen Abschnitt „E-Mails“ mit „Angebot 42“ und einem Link `/post/mail/<id>`.
    - ben und ein Zugang ohne persönliche Anmeldung sehen „Angebot 42“ nicht.
  - `test_verlauf_sensible_mail_nur_kopf`.
- [ ] **Step 2: Fehlschlag prüfen.**
- [ ] **Step 3: Umsetzen.**
  - Der Abschnitt „E-Mails“ steht über der Verlaufstabelle.
  - Er enthält höchstens 50 Mails, neueste zuerst, nur aus `sichtbar_sql(betrachter_laden(name))`.
  - Ohne Betrachter entfällt er.
  - Runbook-Abschnitt „Posteingang mit Mails: Einschalten“ in dieser Reihenfolge:
    1. Claim im Vault
    2. `db/post-sammelstelle.sql` in jedes Schema mit `post_mails`, mit `-v schema=…` wie im Abschnitt davor
    3. `update.sh`
    4. `POST_AUFRAEUMEN_AB` setzen (Felix' Entscheidung), `sales-post` einzeln neu erstellen
    5. warten, bis der erste Abgleich gelaufen ist (`abgeglichen_am`)
    6. Sichtprüfung `/posteingang` als Besitzer und als zweite Anmeldung
- [ ] **Step 4: Tests grün,** dann die ganze Post-Suite gegen die Basis-Fehlerliste vergleichen.
- [ ] **Step 5: Commit** `feat(ui): Mails am Kontakt fuer den Besitzer; Runbook Posteingang`.
