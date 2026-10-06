# Kontext per Klick und Uploads im Chat – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Betreiber markiert Blöcke/Ebenen als Kontext und gibt dem Gestaltungs-Agenten Bilder und Dokumente mit; Claude sieht die Bilder selbst und liest die Dokumente.

**Architecture:** Editor hängt Chips (Auswahl + Anhänge) an die Chat-Nachricht (`kontext.auswahl`, `kontext.anhaenge`); Anhänge laufen über eine neue sales-ui-Route in die Medien. Der Chat-Arbeiter holt Bilder/Dokumente über die Arbeiter-Medienroute, schickt Bilder als OpenAI-Bildteile an den eigenen Marketing-Shim (der sie als Dateien ablegt und per `--add-dir` + `Read` freigibt) und Dokumenttext (pypdf/python-docx) als „Unterlage“.

**Tech Stack:** Python (http.server-Shim, FastAPI, Pillow, pypdf, python-docx), Starlette (sales-ui), React 18 + MUI + zustand, vitest.

**Spec:** `docs/superpowers/specs/2026-10-06-chat-kontext-und-uploads-design.md` (sales-claw)

## Repos und Arbeitsorte

- **MOS** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent` (master), Pfade relativ zu `spaces/marketing/`. NIE im Haupt-Checkout committen; fremde Dirty-Dateien nicht anfassen.
- **SC** = `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw` (`feat/stufe-1-fundament`); `.superpowers/` nie stagen. SC-HEAD enthält schon den Scroll-Fix `e2e47d3` (wird mit ausgeliefert).
- Vor jedem Commit toplevel + Branch prüfen; Git über PowerShell; kein stash/push.
- MOS-Tests: `$env:SALES_CLAW_DIR="<SC>"; C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest spaces/marketing/<pfad> -q -p no:cacheprovider` (bekannt unabhängig rot: test_integrations, test_send_paranoid, test_hand_bridge, test_cockpit_contract).
- SC-Tests: Postgres :55432 (bash `nohup pg_ctl … start`, danach `stop -m immediate`), `SALES_DB_SCHEMA=sales_test`, venv-sales; bekannt unabhängig rot: compliance_test.sperrliste fehlt (test_autonomie, test_medien_meta). Editor `npx vitest run`, `npx tsc --noEmit`, `npm run build` in `editor/`, Bundle mit-committen.
- Bekannte Falle: in SQL über `sync/_db` keinen Spaltennamen `t`.
- Keine Migration in diesem Plan.

## Global Constraints

- Kein Modell auf der VM; Claude nur über den Marketing-Shim :8117; :8114 unberührt.
- Chips: Auswahl ≤ 8 je Nachricht (`{art: "block"|"ebene", id, flaeche?, kurz}`), Anhänge ≤ 5 (`{name, art: "bild"|"dokument"}`); `kontext` ≤ 4 KB; Chips gelten für die nächste Nachricht und werden beim Vormerken mitgenommen.
- Uploads: je ≤ 15 MB; Bild `jpg jpeg png webp`, Dokument `pdf docx txt md`; Ablage = dieselbe Prüfung/derselbe Zielordner wie `/medien/hochladen`.
- An Claude: Bilder auf längste Kante 1568 px, ≤ 6 je Anfrage (Anhänge vor Chips), als `{"type":"image_url","image_url":{"url":"data:image/(png|jpeg|webp);base64,…"}}`; Dokumenttext zusammen ≤ 20 000 Zeichen je Nachricht, als „Unterlage: <name>“.
- Shim: Bildteile nur `data:image/(png|jpeg|webp);base64,`, je ≤ 10 MB dekodiert, ≤ 6 je Anfrage, sonst HTTP 400; Temp-Ordner je Anfrage, `--add-dir` + `Read`, Verweis im Transkript, Ordner immer gelöscht; ohne Bildteile unverändert.
- Fehler sind Hinweise im Chat, keine Abbrüche: fehlender Anhang, unlesbares Bild, Dokument ohne Text, > 6 Bilder, fehlendes markiertes Element; lehnt der Shim Bildteile ab ⇒ einmal ohne Bilder wiederholen mit Hinweis.

## Review Focus

1. Ein Upload mit Namen, der schon in den Medien liegt → eigener Name mit Suffix, das alte Bild bleibt unverändert (Test in Task 5).
2. Ein riesiges oder bösartiges Bild (Dekompressionsbombe, 9000×9000 PNG) als Anhang → Arbeiter überspringt es mit Hinweis, kein Absturz (Test in Task 3).
3. Ein verschlüsseltes oder kaputtes PDF/DOCX → Hinweis „hat keinen lesbaren Text“, kein Absturz (Test in Task 2).
4. Der Shim bekommt ein Bild, und die CLI scheitert → Temp-Ordner trotzdem gelöscht, Fehler wie bisher (Test in Task 1).
5. Markiertes Element wurde vom Agenten in derselben Sitzung gelöscht → Nachricht läuft, Hinweis nennt es (Test in Task 3).

---

### Task 1: Marketing-Shim nimmt Bildteile an (MOS)

**Files:** Modify `claw/shim/marketing_shim.py`; Test `claw/shim/tests/test_marketing_shim.py` (+ `falsche_cli.py` erweitern: gibt die empfangenen Argumente/Prompt-Text aus, damit Tests `--add-dir`/`Read`/Verweis sehen).

**Interfaces – Produces:**
- `bildteile_ablegen(messages: list[dict], ordner: str) -> tuple[list[dict], list[str]]` – ersetzt jeden `image_url`-Teil in `user`-Nachrichten durch einen Textteil `[Bild N: <absoluter pfad> – lies die Datei mit dem Read-Werkzeug]`, schreibt die dekodierten Bytes als `bild-N.<png|jpg|webp>` in `ordner`, gibt (neue messages, pfade) zurück; wirft `ShimEingabeFehler` (→ HTTP 400) bei anderem Schema, > 10 MB, > 6 Bildern, ungültigem Base64.
- Im Handler: nur wenn mindestens ein Bildteil existiert ⇒ `tempfile.mkdtemp(prefix="mshim-")`, `bildteile_ablegen`, Aufruf mit zusätzlich `--add-dir <ordner>` und `Read` in `--allowedTools` (bestehende allowedTools-Liste ergänzen, nicht ersetzen); `finally: shutil.rmtree(ordner, ignore_errors=True)`. `render_messages` muss Inhalt als Liste von Teilen (`type: text`) verstehen (heute nur String) – für Nachrichten ohne Bildteile identisch zu bisher.

- [ ] Failing tests: Bildteil ⇒ Datei liegt während des Aufrufs im Ordner (falsche CLI listet `--add-dir`-Ordnerinhalt), Aufruf enthält `--add-dir` und `Read`, Transkript enthält den Verweis, Ordner nach Antwort gelöscht; dito bei CLI-Exit ≠ 0 (Review Focus 4) und im Streaming-Pfad (`marketing_stream`); `image/gif` ⇒ 400; 7 Bilder ⇒ 400; Inhalt als Liste nur aus Text ⇒ wie String; ohne Bildteile ⇒ Aufruf-Argumente unverändert gegenüber heute.
- [ ] FAIL → implementieren → PASS (alle Shim-Tests).
- [ ] Commit `feat(marketing): Marketing-Shim nimmt Bilder an und gibt sie der CLI zu lesen`.

### Task 2: Dokumenttext lesen (MOS, rein)

**Files:** Create `claw/unterlagen.py`, Test `claw/tests/test_unterlagen.py` (+ kleine Beispieldateien im Test erzeugt: PDF mit pypdf/reportlab, DOCX mit python-docx).

**Interfaces – Produces:**
```python
MAX_ZEICHEN = 20_000
def text_aus(name: str, roh: bytes) -> str          # "" wenn kein lesbarer Text; wirft nie
def unterlagen_text(dateien: list[tuple[str, bytes]], max_zeichen: int = MAX_ZEICHEN) -> tuple[str, list[str]]
    # ("Unterlage: a.pdf\n…\n\nUnterlage: b.docx\n…", hinweise); anteilig gekürzt mit Vermerk „[gekürzt]“;
    # Datei ohne Text ⇒ Hinweis "<name> hat keinen lesbaren Text"
```
- PDF: `pypdf.PdfReader`, verschlüsselt ⇒ versuchen mit leerem Passwort, sonst ""; DOCX: Absätze + Tabellenzellen; TXT/MD: UTF-8, sonst latin-1; Whitespace normalisieren.
- [ ] Failing tests: PDF/DOCX/TXT/MD-Text; kaputtes PDF, verschlüsseltes PDF, leeres DOCX ⇒ "" + Hinweis (Review Focus 3); Kürzung anteilig bei drei Dateien, Gesamt ≤ 20 000 + Vermerke; unbekannte Endung ⇒ "".
- [ ] FAIL → implementieren → PASS. Commit `feat(marketing): Text aus Unterlagen fuer den Gestaltungs-Agenten`.

### Task 3: Arbeiter + Prompt – Auswahl, Bilder, Unterlagen (MOS)

**Files:** Modify `workers/chat_worker.py`, `claw/agent_prompt.py`; Tests `tests/test_chat_worker.py`, `claw/tests/test_agent_prompt.py`.

**Interfaces:**
- Consumes: Task 1 (Bildteile), Task 2 (`unterlagen_text`), `ChatApi.medium(aid, name)`, `bild_messen`/Pillow für Verkleinern.
- Produces:
  - `agent_prompt.nutzer_text(auftrag, medien, *, unterlagen: str = "", auswahl_text: str = "", hinweise: list[str] = ())` – fügt einen Abschnitt „Markiert (damit ist ‚das/hier/diese‘ gemeint):“ mit den markierten Blöcken/Ebenen vollständig als JSON und „Unterlagen:“ ein; SYSTEM ergänzt den Satz zu markierten Elementen und dass Bilder als Dateien vorliegen, die mit Read gelesen werden.
  - `chat_worker.anhaenge_vorbereiten(api, aid, auftrag) -> tuple[list[dict], str, str, list[str]]` → (bildteile, unterlagen, auswahl_text, hinweise): liest `kontext.anhaenge` und `kontext.auswahl` (auch Altform: `auswahl` als einzelne id/String), sammelt Bilder (Anhänge vor Chip-Bildern: Image-Block-`url` bzw. Bild-Ebene-`quelle`), max 6, holt per `api.medium`, verkleinert auf 1568 px (Pillow, `MAX_IMAGE_PIXELS`-Schutz; Bombe/unlesbar ⇒ überspringen + Hinweis), kodiert als data-URL; Dokumente ⇒ `unterlagen_text`; fehlende Elemente/Anhänge ⇒ Hinweise.
  - Die erste Nutzernachricht wird bei vorhandenen Bildern als Teil-Liste `[{"type":"text","text": nutzer_text(...)}, *bildteile]` gesendet (Streaming-Pfad unverändert sonst); Hinweise werden der Chat-Antwort vorangestellt (`antwort = "Hinweis: …\n\n" + antwort`).
  - Shim-400 wegen Bildteilen ⇒ einmal ohne Bilder wiederholen, Hinweis „Bilder konnten nicht übergeben werden“.
- [ ] Failing tests (Fake-Api/Fake-fragen_strom): Bild-Anhang ⇒ Bildteil im Request; 8 Bilder ⇒ 6 + Hinweis; Bombe ⇒ übersprungen + Hinweis (Review Focus 2); PDF-Anhang ⇒ „Unterlage:“ im Text; markierter Block ⇒ im Abschnitt „Markiert“; markierter, aber fehlender Block ⇒ Hinweis (Review Focus 5); Altform `auswahl: "id"` funktioniert; Shim-400 ⇒ Wiederholung ohne Bilder.
- [ ] FAIL → implementieren → PASS (+ alle bisherigen Arbeiter-/Prompt-Tests).
- [ ] Commit `feat(marketing): Gestaltungs-Agent bekommt Auswahl, Bilder und Unterlagen`.

### Task 4: Pult-API – Kontext prüfen, Dokumente ausliefern (MOS)

**Files:** Modify `api/chat.py`; Test `tests/test_chat_api.py`.

- `_MEDIEN_NAME` der Arbeiter-Medienroute um `pdf|docx|txt|md` erweitern (nur diese Route).
- Chat-Anlegen und Vormerken prüfen `kontext.auswahl` (Liste ≤ 8 aus Objekten mit `art` ∈ block|ebene, `id` `^[A-Za-z0-9_-]{1,64}$`, `flaeche` optional gleiche Regex, `kurz` ≤ 80; Altform String/None bleibt erlaubt) und `kontext.anhaenge` (≤ 5, `name` passt auf die Medien-Regex inkl. Dokumente, `art` ∈ bild|dokument) ⇒ sonst 422 mit Grund; `kontext` ≤ 4 KB bleibt.
- [ ] Failing tests: gültige/ungültige Auswahl und Anhänge (zu viele, falsche Art, Pfad mit `..`), Altform; Medienroute liefert `preise.pdf`, `../x.pdf` ⇒ 404.
- [ ] FAIL → implementieren → PASS. Commit `feat(marketing): Chat-Kontext mit Auswahl und Anhaengen pruefen`.

### Task 5: sales-ui – Anhang hochladen (SC)

**Files:** Modify `sales-mcp/ui_editor.py`, `sales-mcp/medien.py` (Endungen), Tests `sales-mcp/tests/test_editor_seite.py`, `sales-mcp/tests/test_medien_*.py`.

- `POST /marketing/editor/{iid}/anhang` (angemeldet, CSRF, multipart wie `/medien/hochladen`): gleiche Prüfung und gleicher Zielordner (Funktion aus ui.py `aktion_medien_hochladen` wiederverwenden bzw. in eine gemeinsame Funktion herausziehen – keine Kopie), zusätzlich Typ-Weißliste `jpg jpeg png webp pdf docx txt md`, ≤ 15 MB; Namenskollision ⇒ Suffix (Review Focus 1); Antwort `{name, art, groesse}`.
- `medien.ERLAUBT` um `.webp` (`send-image`, `image/webp`), `.docx` (`send-document`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`), `.txt` (`send-document`, `text/plain`), `.md` (`send-document`, `text/markdown`) ergänzen; prüfen, dass kein Bot-Weg dadurch etwas Unerwartetes verschickt (nur Endungs-Erlaubnis).
- Startdaten: `anhang_url`.
- [ ] Failing tests: Upload Bild/PDF ok; falscher Typ/zu groß ⇒ 422; ohne CSRF ⇒ 403; Kollision ⇒ neuer Name, alte Datei unverändert; Startdaten-Schlüssel.
- [ ] FAIL → implementieren → PASS. Commit `feat(ui): Anhaenge fuer den Gestaltungs-Chat hochladen`.

### Task 6: Editor – Kontext-Chips und Upload-Chips (SC)

**Files:** neu `editor/src/chatKontext.ts` (+ Test), Änderungen in `App/Chat/ChatLeiste.tsx`, Canvas-Blockrahmen (Alt+Klick, „+ Kontext“-Taste), `App/Gestaltung/EbenenListe.tsx`/`Flaeche.tsx` (Ebenen), `pultZustand.ts` (Chips im Store, mit Vormerken mitnehmen), `chat.ts` (`anhangHochladen(s, file, onProgress)` per XHR für Fortschritt), Paket-Test.

**Interfaces – Produces (`chatKontext.ts`, rein):** `type AuswahlChip = {art:'block'|'ebene'; id: string; flaeche?: string; kurz: string}`; `type AnhangChip = {name: string; art:'bild'|'dokument'; status:'laedt'|'fertig'|'fehler'; grund?: string; fortschritt: number; vorschau?: string}`; `chipHinzu(liste, chip)` (≤ 8, keine Doppelten), `kurzText(block|ebene)`, `dateiPruefen(file) → {art} | {grund}` (Typ/Größe), `kontextBauen(auswahl, anhaenge) → {auswahl, anhaenge}` (nur fertige Anhänge; ≤ 5), `sendenErlaubt(anhaenge)` (keiner `laedt`).
- Verhalten: Chips über dem Eingabefeld (Stil des Chats, Akzent für Auswahl, neutrale Fläche für Anhänge, ✕), Ablagefläche beim Ziehen, Strg+V für Bilder, Fortschrittsring am Chip; Chips nach Senden/Vormerken geleert; beim Vormerken in die Vormerkung übernommen (Karte zeigt Anzahl).
- [ ] Failing tests (vitest): Chip-Regeln, `dateiPruefen`, `kontextBauen`, `sendenErlaubt`; Store: Senden schickt `kontext.auswahl`/`anhaenge`, Vormerken auch; Paket-Test: `editor.js` enthält „+ Kontext“, „Datei anhängen“.
- [ ] FAIL → implementieren → vitest/tsc/build/Paket-Test PASS; Browser-Probe mit dem Fake-Pult aus `scratchpad\t7-live` (Alt+Klick erzeugt Chip, Bild-Upload-Chip mit Fortschritt, Senden-Payload enthält beide). Commit `feat(editor): Kontext per Klick und Anhaenge im Gestaltungs-Chat` (inkl. Bundle).

### Task 7: Ausliefern (STOPP – nur nach ausdrücklicher Freigabe des Betreibers)

- [ ] Claims (WORKBOARD + Vault), sofort committen; volle Tests.
- [ ] Reihenfolge (abwärtskompatibel prüfen): VM zuerst – MOS pushen, `update.sh` (marketing-api: neue Kontextprüfung + Medienroute). Dann PC: Haupt-Checkout `spaces/marketing` nachziehen (Hash-Vergleich vorher gegen `778543bc`), nur den Shim-Prozess :8117 und den Chat-Arbeiter :8134 neu starten (:8114, ComfyUI unberührt); Shim-Probe mit einem Bildteil. Dann SC pushen + `update.sh` (sales-ui + Editor, enthält auch den Scroll-Fix).
- [ ] Echter Lauf (Spec §4): Foto als Titelbild + Beschreibung; PDF-Preisliste übernehmen; Überschrift markieren + kürzen.
- [ ] Claims schließen, Memory, Rulings berichten, Workspace löschen.
