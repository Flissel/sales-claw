# Marken-Chat neu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Marken-Seite wird ein Chat wie in Claude Code. Das Markenprofil bekommt sieben neue Abschnitte. Reine Textänderungen gelten sofort und lassen sich rückgängig machen. Die Websuche des Agenten zeigt ihre Quellen.

**Architecture:** Der bestehende Weg bleibt erhalten: Chat-Auftrag, Vorschlag, Übernahme-Auftrag, `markenprofil.schreiben`, Spiegel und Wissens-Lauf. „Text sofort“ heißt, dass der Arbeiter einen Vorschlag, der nur Abschnitte ändert, mit `direkt: true` ablegt. Die API nimmt ihn dann sofort über die vorhandene SQL-Funktion `pult_marke_uebernehmen` an. Damit gibt es keinen zweiten Schreibweg. „Rückgängig“ ist ein neuer, sofort angenommener Gegenvorschlag, den eine SQL-Funktion anlegt. Quellen bekommen eine eigene Spalte in `marken_auftraege`. Die Seite bleibt ohne JavaScript, mit Reitern als Links, einer festen Eingabe per CSS-`sticky` und einem Sprunganker.

**Tech Stack:** Python 3.12, FastAPI (Marketing-API), Starlette (sales-ui), PostgreSQL/Supabase (Schema `marketing`), pytest.

**Spec:** Mit dem Betreiber im Chat am 20.10.2026 abgestimmt. Grundlage ist `docs/superpowers/plans/2026-10-19-klaerung-reels-marke-struktur.md` (Thema 2). Die Antworten des Betreibers:
- M1: „Könnte schöner wie in Claude Code sein. Die History ist ganz aufgelistet, sie könnte unter dem Chat wachsen. Prinzipiell sieht das noch messy aus.“
- M2: alle drei Nutzungen.
- M3: „Ja, Text sofort“.
- M4: „Ja, mit Quellen“. Es gibt keinen Tavily-Schlüssel. Gesucht wird mit der eingebauten WebSearch der CLI über die Shim, die es schon gibt.
- Das Profil wird um die Tabelle aus dem Chat erweitert. Der Betreiber hat mit „Sub“ freigegeben.

## Entscheidungen (E1–E12)

- **E1 – Neue Abschnitte und Reihenfolge.** `markenprofil.ABSCHNITT_REIHENFOLGE` lautet künftig genau so:
  `("Kurz gesagt", "Wer wir sind", "Menschen", "Zielgruppe", "Ton", "Wörter", "Angebote", "Abgrenzung", "Do & Don'ts", "Fakten und Zahlen", "Bildstil", "Kanäle", "Kontakt und Impressum", "Stimme")`.
  Alle Abschnitte sind Freitext in `Marke.md`. Strukturierte Felder wie Fotos, eine Stimmen-Auswahl oder eine Kanal-Liste sind **nicht** Teil dieses Plans (YAGNI). Ihre Verbraucher, etwa der Newsletter-Fuß oder die Stimme für Reels, sind ein Folgeplan. Für die Namen braucht die DB keine Migration, denn sie liegen in der jsonb-Textkarte.
- **E2 – Eine Quelle für die Abschnittsnamen.** `api/marke.py` setzt `ABSCHNITTE = markenprofil.ABSCHNITT_REIHENFOLGE` und kopiert nicht mehr. `GET /api/pult/marke` liefert zusätzlich `"abschnitt_namen": [...]`. sales-claw `ui_marke.py` streicht seine Kopie und nimmt die Namen aus der Antwort. Formularfelder heißen `abschnitt::<Name>` und nicht mehr positionsbezogen `ab0..abN`.
- **E3 – Fähigkeiten an einer Stelle.** `claw/marken_prompt.py` bekommt `FAEHIGKEITEN: tuple[str, ...] = ("Webseiten lesen, die du nennst oder die ich finde", "im Web suchen (mit Quellen)", "PDFs und Bilder lesen", "Logo freistellen und verkleinern", "Farben, Schriften und Texte vorschlagen")` und `GRENZEN: tuple[str, ...] = ("keine Beiträge veröffentlichen oder Mails senden", "keine Seiten hinter Logins lesen")`. Beide gehen in den SYSTEM-Prompt („Sag nie, dass du etwas kannst, das hier nicht steht“) und über `GET /marke` als `"faehigkeiten": {"kann": [...], "nicht": [...]}` auf die Seite.
- **E4 – Was „Text“ ist (sofort gültig).** Ein Vorschlag gilt **direkt**, wenn seine Schlüssel nach `vorschlag_pruefen` eine Teilmenge von `{"abschnitte", "mustertext"}` sind und `abschnitte` nicht leer ist. Das gilt für den Chat genauso wie für das Formular „Profil bearbeiten“. Alles andere (Farben, Schriften, Logo, `webseite`) bleibt ein Vorschlag mit „Übernehmen“.
- **E5 – Änderungsliste.** Der Arbeiter berechnet `aenderungen: list[{"feld": str, "vorher": str, "nachher": str}]`, nur für geänderte Felder. `feld` ist der Abschnittsname oder der Werte-Schlüssel, zum Beispiel `akzent`. `vorher` ist `""`, wenn der Abschnitt fehlte. `nachher` ist `""`, wenn er gelöscht wird. Die Liste wird im gespeicherten Vorschlag unter `"aenderungen"` abgelegt, zusammen mit `"direkt": true|false`. Ist der gespeicherte Vorschlag als JSON größer als 60 000 Byte, gilt er **nicht** direkt, und `aenderungen` wird weggelassen (Review Focus 3).
- **E6 – Direkt annehmen.** Die Route `POST /api/marke/arbeiter/{aid}/vorschlag` nimmt das zusätzliche Feld `direkt: bool` an. Ist es `true`, ruft die API nach `pult_marke_vorschlag` die Funktion `pult_marke_uebernehmen(vid, 'Agent (direkt)', mandant)` auf, mit genau der Signatur aus `066`. Scheitert dieser zweite Aufruf, bleibt der Vorschlag `offen`, der Betreiber kann ihn von Hand übernehmen, und die Route antwortet trotzdem 200 mit `"direkt": false`. Dadurch laufen Verlauf-Sicherung, Spiegel, Newsletter-Markierung und Wissens-Lauf genau wie heute.
- **E7 – Rückgängig.** Migration `078` legt `marketing.pult_marke_rueckgaengig(p_vid uuid, p_von text, p_mandant text) returns uuid` an. Die Funktion gibt die ID des neuen Übernahme-Auftrags zurück und prüft unter einer Mandantensperre (Muster wie `pult_marke_uebernehmen`):
  1. Der Vorschlag gehört `p_mandant`, ist `angenommen` und hat `vorschlag->>'direkt' = 'true'`.
  2. Es gibt **keinen** späteren `angenommen`-Vorschlag dieses Mandanten. Sonst: `raise exception 'Inzwischen gibt es eine neuere Änderung – Rückgängig geht nur für die letzte.'`
  3. Es läuft kein Marken-Auftrag außer `wissen`. Sonst: `'Der Assistent arbeitet gerade'`, wörtlich wie bei `pult_marke_anlegen`.

  Danach legt sie einen Vorschlag mit `{"abschnitte": {feld: vorher}, "aenderungen": [vertauscht], "direkt": true, "rueckgaengig_von": p_vid}` an, mit dem Status `angenommen`, `entschieden_von = p_von` und demselben `auftrag` wie das Original. Dazu kommt der Übernahme-Auftrag, genauso, wie `pult_marke_uebernehmen` ihn anlegt. Ein leerer `vorher` löscht den Abschnitt, weil `markenprofil.text` leere Abschnitte überspringt.

  Die Pult-Route ist `POST /api/pult/marke/vorschlaege/{vid}/rueckgaengig` mit dem Körper `{von, mandant}` und gibt `{"auftrag": id}` zurück. Bei einer DB-Ausnahme antwortet sie mit 422 und der Meldung.
- **E8 – Quellen.** Migration `078` fügt `marketing.marken_auftraege.quellen jsonb` hinzu, mit `check (quellen is null or (jsonb_typeof(quellen)='array' and jsonb_array_length(quellen) <= 12))`. Dazu kommt die Funktion `marketing.pult_marke_quellen(p_aid uuid, p_quellen jsonb) returns boolean`. Sie gibt `false` zurück, wenn der Auftrag nicht `in_arbeit` ist oder die Sperre abgelaufen ist (Muster `pult_marke_denken`, `065`). Jede Quelle ist `{"titel": str<=120, "url": str<=500, "art": "gelesen"|"websuche"}`, und die URL beginnt mit `https://` oder `http://`. Die Prüfung steht in SQL **und** in der API.

  Die Arbeiter-Route ist `POST /api/marke/arbeiter/{aid}/quellen` mit `{quellen: [...]}`. Sie gibt `{"ok": bool}` zurück.

  Woher die Quellen kommen:
  - **gelesen:** die Startseite aus `fund` und jede per `lesen` tatsächlich geholte Seite. Das sind echte Abrufe über `webseite.py`.
  - **websuche:** das neue Antwortfeld `quellen` des Modells, höchstens 5 Einträge, geprüft durch `marken_prompt.quellen_pruefen`.

  Es gibt keine Durchleitung von Werkzeug-Ergebnissen in der Shim. Die Shim bleibt unverändert.
- **E9 – Was `GET /api/pult/marke` zusätzlich liefert.**
  - `abschnitt_namen` (E2) und `faehigkeiten` (E3).
  - `runden_gesamt: int`.
  - Parameter `alle: bool = False`: Bei `true` ist die Grenze 100 statt 10.
  - Je Eintrag in `auftraege` die Felder `quellen` (Liste oder `[]`) und `art`, außerdem `aenderung: {"vid", "status", "direkt", "aenderungen", "rueckgaengig_moeglich"}|None`. Das kommt aus einem Join auf `marken_vorschlaege` über `auftraege.vorschlag`. `rueckgaengig_moeglich` ist genau dann wahr, wenn der Vorschlag `direkt` und `angenommen` ist und der jüngste angenommene Vorschlag des Mandanten ist.

  Die vorhandenen Schlüssel bleiben unverändert.
- **E10 – Seite: Reiter.** `?reiter=chat` ist die Vorgabe, `?reiter=profil` der zweite Reiter. Die Reiter laufen über `ui_muster.reiter([("chat", "Chat", None), ("profil", "Profil", None)], aktiv, url)`.
  - **Profil:** Alle Abschnitte aus `abschnitt_namen` stehen als Karten in dieser Reihenfolge. Leere Abschnitte zeigen „Noch leer – frag den Agenten“. Die Farben stehen als Muster, das helle Logo auf `--flaeche`, das dunkle Logo auf `--schrift`. Darunter steht „Profil bearbeiten“ (E2-Felder).
  - **Chat:**
    1. Oben eine Zeile mit den Fähigkeiten, eingeklappt in `<details>`.
    2. Dann der Verlauf, das Älteste oben. Ist `runden_gesamt > len(auftraege)`, steht ganz oben der Link „Ältere anzeigen“ mit `?reiter=chat&alle=1`.
    3. Je Runde eine Blase „Du“ rechts und eine Blase „Agent“ links, jeweils mit Uhrzeit. Bei `bearbeitung`-Runden steht statt der Du-Blase die Systemzeile „Profil von Hand bearbeitet“.
    4. Unter jeder Agent-Antwort ein `<details class="schritte">`. Die Summary ist eine einzige Zeile, zum Beispiel „▸ 4 Schritte · Websuche · 2 Quellen“; „Websuche“ steht nur, wenn ein Schritt „Websuche genutzt“ heißt. Darin stehen die Schritte, die Quellen als `<a href rel="noopener noreferrer" target="_blank">` mit Titel und Art und die Gedanken, wie heute in `spur_html`.
    5. Bei `aenderung.direkt` steht eine Änderungskarte „Geändert: Ton, Wörter“. Je Feld steht dort ein `<details>` mit „vorher“ und „nachher“. Bei `rueckgaengig_moeglich` steht ein CSRF-Formular mit dem Knopf „Rückgängig“.
    6. Bei einem offenen, nicht direkten Vorschlag steht die heutige Vorschlagskarte mit Vorschau, Häkchen, Übernehmen und Verwerfen **in der Runde, zu der sie gehört**, nicht unter der Eingabe.
    7. Die laufende Runde zeigt „Denkt nach …“ wie heute `live_html`.
    8. Dann die Eingabe als `<form class="chat-eingabe" id="ende">` mit `position: sticky; bottom: 0`.
    9. Ganz unten eine Statuszeile „Firmenwissen: aktuell / wird aufgefrischt / Fehler“, deren Details eingeklappt sind.
  - Rohtexte wie „Obergrenze 40“ oder „N Dateien“ erscheinen nur in den Details.
- **E11 – Sprung ans Ende ohne JavaScript.** Jede Weiterleitung nach einem POST geht auf `/marketing/layouts?reiter=chat#ende`. Der Meta-Refresh bekommt die Ziel-URL mit Anker: `ui._seite(..., refresh=...)` erweitert den Parameter so, dass er `refresh: int | tuple[int, str] | None` annimmt, und `(5, url)` erzeugt `content="5;url=<url>"`. Die Ruling R7 bleibt gültig: Ein laufender Wissens-Lauf löst **keinen** Refresh aus.
- **E12 – Migrationsnummer.** Die Migration heißt `078_marke_chat.sql` mit `verify_078.sql`, denn `077_seite.sql` gibt es auf `origin/master` schon. Vor dem Anlegen wird mit `git fetch` und `git ls-tree origin/master spaces/marketing/db/` geprüft, ob 078 noch frei ist. Ist sie belegt, wird die nächste freie Nummer genommen und das im Report vermerkt.

## Global Constraints

- **Repos:**
  - **MOS** ist der vibemind-os-Worktree `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/.worktrees/setup-agent` auf `master`. Vor dem Start `git pull --ff-only` ausführen, weil der Worktree hinter `origin/master` steht. Niemals im Haupt-Checkout `vibemind-os/` committen.
  - **SC** ist `C:/Users/User/Desktop/Vibemind_V1/vibemind-os/spaces/sales-claw` auf dem Branch `feat/stufe-1-fundament`.
  - In beiden Repos wird direkt auf dem Branch gearbeitet. Vor jedem Commit `git status` und `git pull --no-rebase` (MOS: `--ff-only`, falls möglich). Nur eigene Dateien stagen, **nie** `.superpowers/`.
- **Commits:** Conventional Commits. Die letzte Zeile lautet `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Git läuft über PowerShell. Keine Hooks umgehen, kein Force-Push, kein Stash.
- **MOS-Tests** laufen aus dem MOS-Wurzelverzeichnis: `python -m pytest spaces/marketing/<pfad> -q --basetemp C:/Temp/pt-marke`. Das `--basetemp` muss auf C: liegen, auf E: werden die Tests etwa 60-mal langsamer. Die API-Tests nutzen `FalscheDB` und die Fixture `umg` aus `tests/test_marke_api.py`. Neue Pult-Routen kommen in `PULT_ROUTEN`, neue Arbeiter-Routen in `ARBEITER_ROUTEN` (`tests/test_marke_api.py:75–97`).
- **Migration:** idempotent, eine Transaktion, Kopfkommentar mit RUNBOOK, dazu `verify_078.sql` nach dem Muster `verify_065.sql`. Geprüft wird **nur** per Rollback-Probe:
  `$env:SUPABASE_SSH_HOST='offload-vm'; $env:SUPABASE_DB_CONTAINER='debian-supabase-db-1'; python -m spaces.marketing.scripts.migration_probe spaces/marketing/db/078_marke_chat.sql spaces/marketing/db/verify_078.sql`.
  Die Probe muss mit `verify_078: ok` enden. Echt eingespielt wird erst in Task 6.
- **API-Routen schreiben nur über SQL-Funktionen**, ohne rohes `INSERT` oder `UPDATE` in Python (Muster `api/marke.py`).
- **SC-Tests** (PowerShell, aus `sales-mcp`) laufen gegen den vorhandenen DB-Klon `sales_struktur` im Container `sales-testdb` auf `127.0.0.1:55600`:
  `$env:SALES_DB_URL='postgresql://postgres:ci@127.0.0.1:55600/sales_struktur'; $env:SALES_DB_SCHEMA='sales_test'; & E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/venv-sales/Scripts/python.exe -m pytest tests/<datei> -q`.
  Im Folgenden heißt das kurz **`PYTEST tests/<datei>`**. Die bekannte Basis der Vollsuite sind 39 alte Fehlschläge in belegungen, editor_seite, kalenderquellen, kollision, laden_parameter, recherche, termin_einladen, thema_entitaeten und werkzeuge. Neue Fehlschläge darüber hinaus sind nicht erlaubt.
- **sales-ui:**
  - Kein JavaScript; die CSP-Prüfung in `test_marke_seite.py` bleibt grün und unverändert.
  - Farben nur über `:root`-Variablen.
  - Touch-Ziele mindestens 44 px.
  - Jeder Fremdwert geht durch `ui._e`. Quellen-URLs werden nur als `href` gesetzt, wenn sie mit `https://` oder `http://` beginnen; sonst erscheinen sie nur als Text.
  - Anzeigetexte haben echte Umlaute, und das gilt auch für Bezeichner im HTML (`tests/test_darstellung.py`, Stämme wie `aender`, `zurueck`). Die Klasse heißt deshalb `chat-eingabe` und nicht etwa `eingabe-aendern`, und der Formularpfad ist `/marketing/marke/rueckgaengig`.
- **Kein Deploy ohne Betreiber-OK.** Task 6 ist der Deploy.

## Review Focus

1. **Rückgängig nach einer neueren Änderung.** A ändert den Ton direkt, danach ändert B die Wörter direkt. „Rückgängig“ an A wird abgewiesen, mit der Meldung aus E7, und das Profil bleibt unverändert. In der Antwort von `GET /marke` hat nur B `rueckgaengig_moeglich = true`. Tests: `test_rueckgaengig_nur_fuer_den_juengsten` in `verify_078.sql` und `test_stand_rueckgaengig_nur_juengster` (Task 3).
2. **Gemischter Vorschlag.** Ändert eine Antwort Ton **und** Akzentfarbe, gilt nichts davon direkt. Es entsteht ein normaler Vorschlag mit „Übernehmen“, und auch der Ton wartet. Test: `test_gemischter_vorschlag_nicht_direkt` (Task 4).
3. **Riesige Änderung.** Schreibt der Agent alle 14 Abschnitte mit je 4 000 Zeichen um, darf der gespeicherte Vorschlag nicht an der 64-KB-Grenze scheitern. Er gilt dann nicht direkt und kommt ohne `aenderungen`. Test: `test_grosse_aenderung_faellt_auf_vorschlag_zurueck` (Task 4).
4. **Erfundene oder gefährliche Quellen.** `javascript:alert(1)`, `data:`, URLs mit Zugangsdaten, mehr als 5 Einträge oder Titel mit `<script>` werden im Arbeiter verworfen oder gekürzt, in API und SQL abgelehnt und auf der Seite escaped; nur `http(s)` wird zum Link. Tests: `test_quellen_pruefen_verwirft_gefaehrliche` (Task 4), `test_quellen_route_lehnt_ab` (Task 3), `test_quelle_javascript_wird_kein_link` (Task 5).
5. **Altes Profil mit unbekannten oder umbenannten Abschnitten.** Eine `Marke.md` mit nur den sieben alten Abschnitten und einem eigenen Abschnitt „Notizen“ lädt ohne Fehler. Die Seite zeigt 14 Karten, die neuen leer, und „Notizen“ geht nicht verloren, denn `markenprofil.text` behält unbekannte Abschnitte. Tests: `test_altes_profil_behaelt_unbekannte_abschnitte` (Task 1) und `test_profil_reiter_zeigt_leere_neue_abschnitte` (Task 5).

---

### Task 1: Profil um sieben Abschnitte erweitern, eine Quelle für Namen und Fähigkeiten (MOS)

**Files:**
- Modify: `spaces/marketing/claw/markenprofil.py:41-42` (ABSCHNITT_REIHENFOLGE)
- Modify: `spaces/marketing/api/marke.py:42` (Kopie streichen), `marke_stand` (`abschnitt_namen`, `faehigkeiten`)
- Modify: `spaces/marketing/claw/marken_prompt.py` (FAEHIGKEITEN, GRENZEN, SYSTEM-Text: neue Abschnitte und wann der Agent sie füllt)
- Modify: `spaces/marketing/claw/markenwissen.py:44-51` (`_VORLAGE_ABSCHNITTE`: alle 14 Abschnitte, „Bildstil“ ergänzt, je ein Hilfekommentar)
- Modify: `spaces/marketing/claw/wissen_prompt.py:28` (Aufzählung)
- Test: `spaces/marketing/claw/tests/test_markenprofil.py`, `claw/tests/test_marken_prompt.py`, `tests/test_markenwissen.py`, `tests/test_marke_api.py`

**Interfaces:**
- Produces: `markenprofil.ABSCHNITT_REIHENFOLGE` (14 Namen, E1), `marken_prompt.FAEHIGKEITEN`, `marken_prompt.GRENZEN` (E3). `GET /api/pult/marke` liefert zusätzlich `abschnitt_namen: list[str]` und `faehigkeiten: {"kann": list[str], "nicht": list[str]}`.

- [ ] **Step 1: Failing Tests schreiben.**
  - `test_markenprofil.py::test_reihenfolge_vierzehn_abschnitte`: Das Tupel entspricht exakt dem aus E1.
  - `test_markenprofil.py::test_altes_profil_behaelt_unbekannte_abschnitte`: Eine `Marke.md` mit den alten sieben Abschnitten plus `## Notizen` wird mit `aus_text` gelesen und mit `text` neu geschrieben. Danach ist „Notizen“ noch da, und die alten sieben stehen in der neuen Reihenfolge davor.
  - `test_marke_api.py::test_stand_liefert_abschnitt_namen_und_faehigkeiten`: `r.json()["abschnitt_namen"] == list(markenprofil.ABSCHNITT_REIHENFOLGE)` und `r.json()["faehigkeiten"] == {"kann": list(marken_prompt.FAEHIGKEITEN), "nicht": list(marken_prompt.GRENZEN)}`.
  - `test_marke_api.py`: Das Literal bei `:1018` wird auf die 14 Namen angepasst.
  - `test_marken_prompt.py::test_system_nennt_faehigkeiten_und_neue_abschnitte`: Jeder Eintrag aus FAEHIGKEITEN und GRENZEN und jeder der sieben neuen Namen kommt in `SYSTEM` vor.
  - `test_markenwissen.py`: Die Vorlage enthält alle 14 Überschriften.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3: Umsetzen.**
  - `api/marke.py`: `ABSCHNITTE = markenprofil.ABSCHNITT_REIHENFOLGE`.
  - Der SYSTEM-Prompt bekommt einen Absatz: Beim Aufsetzen aus einer Webseite füllt der Agent auch „Kurz gesagt“, „Menschen“, „Kanäle“ (eine Zeile je Kanal: `Name: URL`), „Kontakt und Impressum“ (aus der Impressum-Seite, nichts erfinden) und „Abgrenzung“. Was er nicht findet, lässt er leer und nennt es in `antwort`.
  - Die Fähigkeitenliste kommt in den SYSTEM-Prompt, zusammen mit dem Satz „Sag nie, dass du etwas kannst, das nicht in dieser Liste steht.“
- [ ] **Step 4:** Laufen lassen: `python -m pytest spaces/marketing/claw spaces/marketing/tests/test_marke_api.py spaces/marketing/tests/test_markenwissen.py spaces/marketing/tests/test_marken_arbeiter.py -q --basetemp C:/Temp/pt-marke`. Erwartet: alles PASS. Literale in anderen Tests, die die sieben Namen aufzählen, werden angepasst.
- [ ] **Step 5: Commit.** `feat(marke): Profil mit vierzehn Abschnitten, Faehigkeiten an einer Stelle`

### Task 2: Migration 078 – Quellen-Spalte, Quellen-Funktion, Rückgängig (MOS)

**Files:**
- Create: `spaces/marketing/db/078_marke_chat.sql`, `spaces/marketing/db/verify_078.sql`

**Interfaces:**
- Produces:
  - Die Spalte `marketing.marken_auftraege.quellen jsonb` (E8).
  - `marketing.pult_marke_quellen(p_aid uuid, p_quellen jsonb) returns boolean` (E8).
  - `marketing.pult_marke_rueckgaengig(p_vid uuid, p_von text, p_mandant text) returns uuid` (E7).
  - Die Rechte folgen den Grants der Nachbarfunktionen in `066`.

- [ ] **Step 0:** E12 prüfen (ist 078 frei?). Dann `064_marke.sql` lesen (Tabellen) und `066_marke_exakt.sql` lesen: `pult_marke_uebernehmen`, `pult_marke_vorschlag`, `pult_marke_anlegen`, die Sperrmuster und die Grants.
- [ ] **Step 1: `verify_078.sql` zuerst schreiben.** Der Ablauf läuft mit Probe-Mandant `probe_078` im Muster `verify_065.sql`, und jeder Fall endet mit `raise exception 'verify_078: …'`, wenn er scheitert:
  - (a) Die Spalte existiert und der Check lehnt 13 Quellen ab.
  - (b) `pult_marke_quellen` auf einen `in_arbeit`-Auftrag mit gültiger Sperre gibt `true` und speichert. Auf einen `fertig`-Auftrag gibt sie `false`. Eine Quelle mit `url = 'javascript:x'` oder `titel` über 120 Zeichen führt zur Ausnahme.
  - (c) Für `test_rueckgaengig_nur_fuer_den_juengsten` werden zwei direkt angenommene Vorschläge A und B angelegt. Rückgängig an A wirft die Ausnahme mit „neuere Änderung“. Rückgängig an B legt einen angenommenen Vorschlag mit vertauschten `aenderungen` und `rueckgaengig_von = B` an, dazu einen `uebernehmen`-Auftrag.
  - (d) Rückgängig an einem nicht direkten Vorschlag wirft eine Ausnahme.
  - (e) Rückgängig, während ein `chat`-Auftrag offen ist, wirft „Der Assistent arbeitet gerade“.
  - Am Ende `raise notice 'verify_078: ok'`.
- [ ] **Step 2:** Probe mit nur `verify_078.sql`. Erwartet: FAIL (Funktion oder Spalte fehlt).
- [ ] **Step 3:** `078_marke_chat.sql` schreiben: idempotent (`add column if not exists`, `create or replace function`), `security definer` und `search_path` wie in den Nachbarn, eine Transaktion.
- [ ] **Step 4:** Probe mit `078` und `verify_078` (Kommando in den Global Constraints). Erwartet: `verify_078: ok`. Danach noch einmal mit `064 … 066` und `078` samt ihren verify-Dateien zusammen, laut RUNBOOK-Hinweis in `064`, damit Wiederholungen sicher sind.
- [ ] **Step 5: Commit.** `feat(marke): Migration 078 Quellen und Rueckgaengig fuer Marken-Chat`

### Task 3: API – Quellen, direkt annehmen, Rückgängig, erweiterter Stand (MOS)

**Files:**
- Modify: `spaces/marketing/api/marke.py`
- Test: `spaces/marketing/tests/test_marke_api.py`

**Interfaces:**
- Consumes: SQL aus Task 2 und `pult_marke_uebernehmen` (`066`).
- Produces:
  - `POST /api/marke/arbeiter/{aid}/quellen` → `{"ok": bool}`
  - `POST /api/marke/arbeiter/{aid}/vorschlag` mit dem Körper `{vorschlag, antwort, hinweise, direkt?: bool}` → wie bisher plus `"direkt": bool`
  - `POST /api/pult/marke/vorschlaege/{vid}/rueckgaengig` mit dem Körper `{von, mandant}` → `{"auftrag": id}`, bei einer DB-Ausnahme 422 mit deren Meldung
  - `GET /api/pult/marke?mandant=&alle=` mit den zusätzlichen Schlüsseln aus E9

- [ ] **Step 1: Failing Tests schreiben.**
  - `test_quellen_route_speichert`: Gültige Liste, die SQL-Funktion `pult_marke_quellen` wird aufgerufen.
  - `test_quellen_route_lehnt_ab`, parametrisiert, jeweils 422 ohne SQL-Aufruf: `javascript:`-URL, mehr als 12 Einträge, ein fehlender `titel`, eine `art` außerhalb von `gelesen` und `websuche`, kein Array.
  - `test_vorschlag_direkt_nimmt_sofort_an`: Die Funktion `pult_marke_uebernehmen` wird mit `'Agent (direkt)'` und dem Mandanten aufgerufen, und die Antwort enthält `"direkt": true`.
  - `test_vorschlag_direkt_scheitert_bleibt_offen`: Der zweite SQL-Aufruf wirft. Die Antwort ist 200 mit `"direkt": false`.
  - `test_rueckgaengig_route`: Erfolg führt zu `{"auftrag": …}`. Eine DB-Ausnahme führt zu 422 mit der Meldung.
  - `test_stand_rueckgaengig_nur_juengster`: Die FalscheDB liefert zwei Runden mit direkten, angenommenen Vorschlägen. Nur die jüngste hat `rueckgaengig_moeglich: true`.
  - `test_stand_alle_hebt_grenze`: `alle=1` führt im SQL zu `limit 100`, sonst `limit 10`, und `runden_gesamt` wird geliefert.
  - `test_stand_runde_hat_quellen_und_art`: Die Felder `quellen` und `art` sind da.
  - Die neuen Routen kommen in `PULT_ROUTEN` und `ARBEITER_ROUTEN`, wodurch auch der 401-Test sie prüft.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3: Umsetzen.**
  - Die Quellen-Prüfung steht als reine Funktion `quellen_pruefen(roh: object) -> list[dict]` in `api/marke.py`. Sie wirft `HTTPException(422)` und hält dieselben Grenzen ein wie SQL.
  - Die Abfrage für den Stand bekommt einen `left join marketing.marken_vorschlaege v on v.id = a.vorschlag`.
  - `rueckgaengig_moeglich` wird in Python aus der ID des jüngsten angenommenen Vorschlags bestimmt, über eine eigene kleine Abfrage `select id from marketing.marken_vorschlaege where mandant=%s and status='angenommen' order by entschieden_am desc limit 1`.
- [ ] **Step 4:** `python -m pytest spaces/marketing/tests/test_marke_api.py -q --basetemp C:/Temp/pt-marke`. Erwartet: PASS.
- [ ] **Step 5: Commit.** `feat(marke): API fuer Quellen, direkte Uebernahme und Rueckgaengig`

### Task 4: Arbeiter – Text sofort, Änderungsliste, Quellen sammeln (MOS)

**Files:**
- Modify: `spaces/marketing/claw/marken_prompt.py`
  - Neues optionales Antwortfeld `quellen`.
  - `quellen_pruefen(roh) -> list[dict]`.
  - `aenderungen(alt: markenprofil.Profil, vorschlag: dict) -> list[dict]`.
  - `ist_direkt(vorschlag: dict) -> bool`.
- Modify: `spaces/marketing/workers/marken_arbeiter.py`
  - `MarkenApi.quellen(aid, quellen) -> bool`.
  - In `_chat_mit_spur` die Quellen sammeln, `aenderungen` und `direkt` in den gespeicherten Vorschlag schreiben und `direkt` an die API geben.
- Test: `spaces/marketing/claw/tests/test_marken_prompt.py`, `spaces/marketing/tests/test_marken_arbeiter.py`

**Interfaces:**
- Consumes: die Arbeiter-Routen aus Task 3 und `ABSCHNITT_REIHENFOLGE` aus Task 1.
- Produces: Der gespeicherte Vorschlag enthält `aenderungen` und `direkt` nach E5. Die Quellen landen über `/quellen`.

- [ ] **Step 1: Failing Tests schreiben.**
  - `test_quellen_pruefen_verwirft_gefaehrliche`: `javascript:`, `data:`, eine URL mit `user:pw@`, eine URL ohne Schema und ein leerer Titel werden **verworfen**, ohne Ausnahme, denn ein Modellfehler soll nicht die ganze Antwort kosten. Mehr als 5 Einträge werden auf 5 gekürzt, ein Titel auf 120 Zeichen. Gültige Einträge bekommen `art="websuche"`.
  - `test_aenderungen_nur_geaenderte_felder`: Gleicher Text ergibt keinen Eintrag. Ein neuer Abschnitt ergibt `vorher=""`, ein leerer Abschnitt im Vorschlag `nachher=""`. `akzent` erscheint als `feld="akzent"`.
  - `test_ist_direkt`: Nur `abschnitte` ergibt True, `abschnitte` plus `mustertext` ergibt True, `abschnitte` plus `akzent` ergibt False, leere `abschnitte` ergeben False.
  - `test_text_aenderung_gilt_direkt`: Der Arbeiter mit einem gefälschten Strom antwortet mit einem reinen Ton-Vorschlag. `api.vorschlag` bekommt `direkt=True`, und der gespeicherte Vorschlag enthält `aenderungen` mit vorher und nachher.
  - `test_gemischter_vorschlag_nicht_direkt`: Ton und Akzent zusammen ergeben `direkt=False`.
  - `test_grosse_aenderung_faellt_auf_vorschlag_zurueck`: 14 Abschnitte mit je 4 000 Zeichen und ein altes Profil mit anderen 14 mal 4 000 Zeichen ergeben `direkt=False` und keine `aenderungen`.
  - `test_formular_text_gilt_direkt`: Bei der Art `bearbeitung` mit nur Abschnitten ist `direkt=True`.
  - `test_quellen_gelesen_und_websuche`: Die Startseite aus `fund` plus eine `lesen`-Seite plus zwei Modellquellen ergeben `api.quellen` mit 2 Einträgen `gelesen` und 2 Einträgen `websuche`, aufgerufen **vor** `api.vorschlag` oder `api.fertig`.
  - `test_quellen_api_false_bricht_nicht_ab`: Liefert `api.quellen` den Wert False, läuft der Auftrag trotzdem zu Ende.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3: Umsetzen.**
  - Das SYSTEM-Format bekommt `"quellen": [{"titel","url"}]` (optional, höchstens 5) mit der Anweisung „Hast du WebSearch benutzt, nenne hier die Seiten, aus denen deine Aussagen stammen.“
  - `vorschlag_pruefen` bleibt streng. `quellen` steht in der Antwort neben `vorschlag`, nicht darin.
  - `aenderungen` vergleicht `alt.abschnitte` und `alt.werte` mit dem Vorschlag, wobei leere Abschnitte nicht zählen.
  - Für die Größenregel aus E5 wird mit `len(json.dumps(gespeichert, ensure_ascii=False).encode())` gemessen.
- [ ] **Step 4:** `python -m pytest spaces/marketing/claw spaces/marketing/tests/test_marken_arbeiter.py spaces/marketing/tests/test_chat_worker.py -q --basetemp C:/Temp/pt-marke`. Erwartet: PASS.
- [ ] **Step 5: Commit.** `feat(marke): Textaenderungen gelten sofort, Aenderungsliste und Quellen`

### Task 5: Seite Marke neu – Reiter, Chat wie Claude Code, Profil vollständig (SC)

**Files:**
- Modify: `sales-mcp/ui_marke.py`
  - `ABSCHNITTE`-Kopie streichen.
  - Neu: `chat_html(d, alle)`, `runde_html(a, d)`, `schritte_html(a)`, `aenderung_html(a)`, `profil_html(d)`, `faehigkeiten_html(d)`, `wissen_zeile_html(d)`.
  - Neuer Handler `rueckgaengig(request)` mit der Route `POST /marketing/marke/rueckgaengig`.
  - `bearbeiten_html` und `bearbeiten` mit den Feldern `abschnitt::<Name>`.
  - Alle Weiterleitungen nach E11.
- Modify: `sales-mcp/ui.py`: `_seite(refresh=…)` nach E11, außerdem CSS für `.chat-verlauf`, `.blase-du`, `.blase-agent`, `.systemzeile`, `.schritte`, `.aenderung`, `.chat-eingabe` (sticky) und `.profil-karten`, nur mit Variablen.
- Test: `sales-mcp/tests/test_marke_seite.py`

**Interfaces:**
- Consumes: der erweiterte `GET /marke` (E9), `POST /marke/vorschlaege/{vid}/rueckgaengig` und `ui_muster.reiter(eintraege, aktiv, url)`.

- [ ] **Step 1: Failing Tests schreiben.** `Falsch.zustand` bekommt `abschnitt_namen`, `faehigkeiten`, `runden_gesamt`, und die Runden bekommen `quellen`, `art` und `aenderung`.
  - `test_reiter_chat_ist_vorgabe`: Ohne Parameter ist „Chat“ mit `aria-current` markiert. `?reiter=profil` zeigt die Karten.
  - `test_profil_reiter_zeigt_leere_neue_abschnitte`: 14 Karten, die leeren zeigen „Noch leer – frag den Agenten“.
  - `test_dunkles_logo_auf_dunkler_flaeche`: Das dunkle Logo steht in einem Element mit der Klasse `logo-dunkel-flaeche`.
  - `test_verlauf_aelteste_oben_eingabe_unten`: Im HTML steht die Runde 1 vor Runde 2 und vor `id="ende"`. Die Eingabe steht nach dem Verlauf.
  - `test_aeltere_anzeigen_link`: Bei `runden_gesamt=14` und 10 Runden gibt es einen Link auf `alle=1`, und der GET-Aufruf an die API enthält `alle=1`.
  - `test_schritte_eine_zeile`: Die Summary enthält „4 Schritte · Websuche · 2 Quellen“.
  - `test_quelle_javascript_wird_kein_link`: Eine Quelle mit `javascript:alert(1)` erzeugt kein `href="javascript`. Ein Titel mit `<script>` wird escaped.
  - `test_aenderung_mit_rueckgaengig`: `aenderung.direkt` mit `rueckgaengig_moeglich` ergibt eine Karte „Geändert: Ton“ mit vorher und nachher und ein Formular auf `/marketing/marke/rueckgaengig`. Ohne `rueckgaengig_moeglich` gibt es kein Formular.
  - `test_rueckgaengig_post`: Mit CSRF wird `POST /marke/vorschlaege/<vid>/rueckgaengig` mit `{von, mandant}` aufgerufen, danach 303 auf `…?reiter=chat#ende`. Ohne CSRF kommt 403. Ein API-422 zeigt die Meldung.
  - `test_offener_vorschlag_in_seiner_runde`: Die Vorschlagskarte steht vor `id="ende"`, in der Runde mit der passenden `vorschlag`-ID.
  - `test_bearbeitung_als_systemzeile`: „Profil von Hand bearbeitet“ steht da, ohne Du-Blase.
  - `test_refresh_mit_anker`: Läuft ein Auftrag, enthält die Seite `content="5;url=/marketing/layouts?reiter=chat#ende"`. Läuft nur der Wissens-Lauf, gibt es keinen Refresh.
  - `test_bearbeiten_felder_nach_namen`: Das Formular hat die Felder `abschnitt::Kurz gesagt` und so weiter. Der POST schickt `abschnitte` mit den Namen.
  - Vorhandene Tests werden an den neuen Aufbau angepasst. Ihre Aussage (CSRF, Threadpool, kein JavaScript, CSP, Häkchen-Pflicht, Konfliktmeldung) bleibt erhalten.
- [ ] **Step 2:** `PYTEST tests/test_marke_seite.py`. Erwartet: die neuen FAIL.
- [ ] **Step 3:** Umsetzen nach E10 und E11.
- [ ] **Step 4: Prüfen.**
  - `PYTEST tests/test_marke_seite.py tests/test_darstellung.py tests/test_laden_marke_ui.py` muss PASS ergeben. Danach die Vollsuite: Erlaubt sind nur die 39 Basis-Fehlschläge.
  - Dazu Bildschirmfotos der Seite mit einem gefälschten Zustand von 12 Runden: Quellen, eine direkte Änderung, ein offener Farb-Vorschlag, ein laufender Auftrag. Aufgenommen wird bei 1440 px hell und dunkel und bei 390 px, beide Reiter. Die Bilder liegen im SDD-Arbeitsordner. Werkzeug: Playwright gegen die lokal gestartete sales-ui mit gefälschtem Pult, nach dem Muster der Bildschirmfotos aus den Vorplänen.
- [ ] **Step 5: Commit.** `feat(marke): Marken-Seite als Chat mit Reitern, Profil vollstaendig, Rueckgaengig`

### Task 6: Ausliefern (nur nach Betreiber-OK)

- [ ] **Step 1:** Rollback-Probe von `078` mit `verify_078` gegen die Live-DB. Erwartet: `verify_078: ok`.
- [ ] **Step 2:** `078` echt einspielen: `_db._run_psql(sql, None, streng=True)` aus `spaces.marketing.sync`, dann `verify_078` noch einmal als Probe.
- [ ] **Step 3:** Auf MOS `git push origin master`. Auf der VM die Marketing-API aktualisieren (über `ssh offload-vm 'cd ~/sales-claw && bash deploy/update.sh'`, das die VM-Marketing-API mitzieht).
- [ ] **Step 4: PC nachziehen.**
  - Jede geänderte MOS-Datei im Haupt-Checkout `vibemind-os/spaces/marketing` wird gegen den Commit-Verlauf als alt, neu oder FREMD eingeordnet. Bei FREMD wird abgebrochen.
  - Dann `git restore --source=<sha> --worktree -- <dateien>`.
  - Danach Marketing-API `:5510` und Chat-Arbeiter `:8134` neu starten, über `marketing-dienste-starten.ps1 -Nur`.
- [ ] **Step 5:** SC pushen und `update.sh` laufen lassen. Erwartet: „ALLE PRUEFUNGEN GRUEN“.
- [ ] **Step 6: Echter Lauf im Basis-Laden.**
  1. Im Chat „Mach den Ton etwas lockerer“ schreiben. Erwartet: Die Änderung gilt nach Sekunden ohne Häkchen, die Karte „Geändert: Ton“ erscheint.
  2. „Rückgängig“ drücken. Erwartet: Der alte Ton ist zurück.
  3. Eine Frage stellen, die eine Suche braucht, zum Beispiel „Welche Social-Media-Kanäle hat VibeMind?“. Erwartet: Unter der Antwort stehen Quellen.
  4. Der Reiter „Profil“ zeigt 14 Karten.

  Von jedem Schritt gibt es ein Bildschirmfoto.
- [ ] **Step 7:** Den WORKBOARD-Claim `cc-marken-chat` schließen. Memory und MEMORY.md ergänzen. Im Klärungsdokument „Antworten des Betreibers“ für M1–M4 nachtragen.

## Self-Review (erledigt)

- **Abdeckung:** neue Abschnitte → T1. Seite wie Claude Code (Reiter, Verlauf eingeklappt, Eingabe unten, Schritte als eine Zeile, Wissen als Statuszeile) → T5. Text sofort → T4 und T3 (E6). Rückgängig → T2, T3 und T5. Websuche mit Quellen → T2, T3, T4 und T5. Ehrliche Fähigkeiten → T1 und T5.
- **Typen:** `quellen` ist überall `{titel, url, art}`. `aenderungen` ist überall `{feld, vorher, nachher}`. `direkt` ist ein bool im gespeicherten Vorschlag und im Körper der Vorschlag-Route. Die Signatur von `pult_marke_rueckgaengig(uuid, text, text)` ist in T2 und T3 gleich.
- **Offen gelassen:** Die Verbraucher der neuen Abschnitte (Newsletter-Fuß, Reel-Stimme) und Fotos unter „Menschen“ gehören in einen Folgeplan.
