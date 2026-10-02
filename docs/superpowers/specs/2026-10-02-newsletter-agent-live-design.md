# Newsletter-Agent live: eigener Marketing-Shim, Zwischenstände, Vormerken, Stopp

Stand: 02.10.2026 · Status: Entwurf zur Freigabe durch den Betreiber
Repos: vibemind-os (`spaces/marketing`, master) und sales-claw (`feat/stufe-1-fundament`)
Vorgänger: `2026-10-02-newsletter-gestaltung-und-agent-design.md` (Bausteine C+D, ausgeliefert 02.10.)

## 0. Worum es geht

Der Gestaltungs-Agent arbeitet heute 20–60 s still und liefert dann das Ergebnis auf einmal.
Der Betreiber will **zusehen, wie der Agent Schritt für Schritt baut**, und währenddessen
**schon weiterdenken** – die nächste Anweisung vorbereiten.

Betreiber-Entscheide (02.10.):
- **Echt live mitschreiben**: Claude streamt, jede fertige Änderung wird sofort sichtbar.
- **Nächste Nachricht vormerken** während des Laufs, dazu ein **Stopp**-Knopf.
- **Unabhängig**: Marketing ist ein eigener Space mit eigenem Claw (wie sales-claw). Der
  Marketing-Claw bekommt seine **eigene Modell-Tür**; der geteilte Shim von Hermes/Captain
  (`~/.local/bin/claude_code_openai_shim.py`, :8114) wird nicht angefasst.

Feste Grenzen wie bisher: kein Modell auf der VM; Claude nur am PC über die CLI im Abo.

## 1. Eigene Modell-Tür des Marketing-Claws

- Neuer Code `spaces/marketing/claw/shim/marketing_shim.py` – Ausgangspunkt ist eine Kopie des
  heutigen Shims; ab dann gehört er Marketing und wird nur dort weiterentwickelt (Kopfkommentar
  nennt die Herkunft und das Datum der Kopie).
- Läuft weiter auf **:8117**; `marketing-dienste-starten.ps1` startet ihn aus dem Marketing-Repo
  statt aus `~/.local/bin`. Alle heutigen :8117-Nutzer (Marketing-Agent, Chat-Arbeiter)
  bleiben kompatibel (gleiche Routen `/v1/models`, `/v1/chat/completions`, gleiches Verhalten
  ohne `stream`).
- **Echtes Streaming**: bei `stream: true` startet er die CLI mit
  `--output-format stream-json --include-partial-messages --verbose`, liest die Zeilen,
  reicht jedes `content_block_delta`/`text_delta` sofort als OpenAI-SSE-Chunk
  (`chat.completion.chunk`, `delta.content`) weiter und schließt mit `finish_reason: "stop"` und
  `[DONE]`. Fehler der CLI ⇒ ein letzter Chunk mit `finish_reason: "error"` und Meldung.
- Übernommen bleiben: bereinigte Umgebung (keine Root-.env), `SHIM_NEUTRALIZE_DOUBLE_BRACKETS`,
  `SHIM_EXTRA_MCP_CONFIG` (`claw/shim/marketing-mcp.json`), Zeitlimit, Modellauflösung.
- Tests mit gefälschter CLI (Skript, das stream-json-Zeilen ausgibt): Chunks kommen einzeln und
  in Reihenfolge an, ohne `stream` bleibt die Antwort wie heute, CLI-Fehler ⇒ Fehler-Chunk.

## 2. Live-Zwischenstände

### 2.1 Chat-Arbeiter (PC)
- Fragt den eigenen Shim mit `stream: true`; liest SSE-Chunks.
- **Inkrementeller Leser**: erkennt im wachsenden Text das Antwortobjekt und darin jedes
  *vollständige* Element von `aenderungen` (Klammer- und Stringzählung, robust gegen
  zerschnittene Chunks, Codezäune und Text davor).
- Jede Änderung trägt ein Feld **`schritt`** (≤ 80 Zeichen, deutsch, was der Agent gerade tut);
  der Prompt verlangt es; `agent_werkzeuge` akzeptiert und ignoriert es beim Anwenden.
- Jede vollständige Änderung wird sofort auf eine Arbeitskopie angewendet. Ungültig ⇒ wie heute
  genau ein Korrekturversuch (der Live-Stand bleibt auf dem letzten gültigen Stand, Schritt
  „korrigiere …“).
- Zwischenstand an die VM: `POST /api/chat/arbeiter/{aid}/zwischenstand {bloecke, schritt, nr}`
  höchstens 1× pro Sekunde (der letzte Stand vor `fertig` wird immer gesendet). Der Aufruf
  verlängert die Vergabe; Antwort `{weiter: true}` oder `{weiter: false, grund: "stopp"}`.
- Ende wie heute: `pruefen` → `fertig` → genau eine neue Fassung.

### 2.2 VM
- Migration **061**: `chat_auftraege` + `zwischenstand jsonb`, `schritt text`, `schritt_nr int`,
  `zwischen_am timestamptz`, `stopp text NULL CHECK (stopp IN ('behalten','verwerfen'))`,
  Status zusätzlich `wartet`.
- Zwischenstand überschreibt (keine Versionierung); nach `fertig`/`fehler`/Stopp geleert.
- `GET /api/pult/inhalte/{iid}/chat` liefert zusätzlich für den laufenden Auftrag
  `{zwischenstand, schritt, schritt_nr}` und eine vorgemerkte Nachricht `vorgemerkt`.
- Zwischenstand wird **nicht** mit `pult_bloecke_fehler` geprüft (nur Größe ≤ 256 KB und
  Objekt); er wird nie gespeichert.

### 2.3 Editor
- Während eines Laufs fragt er den Stand **jede Sekunde** ab (sonst wie heute nur bei Bedarf).
- Zeigt den Zwischenstand **live im normalen Canvas**, schreibgeschützt (Sperre wie heute).
  Der zuletzt geänderte Block leuchtet kurz in Akzentfarbe auf (≤ 600 ms, ruhig), sanfter
  Scroll dorthin, falls außerhalb der Sicht. Flächen erscheinen live als DOM-Vorschau
  (gleiche Darstellung wie im Gestaltungsfenster); das Serverbild kommt mit der Fassung.
- Chat-Leiste: „Schritt 3 · Titel links oben setzen“ mit dezenter Fortschritts-Animation.
- Nach `fertig` lädt er die echte Fassung wie heute.

## 3. Vormerken und Stopp

### 3.1 Vormerken
- Während eines Laufs bleibt das Eingabefeld aktiv; der Knopf heißt „Vormerken“.
- Auf der VM: Auftrag mit Status `wartet` – **höchstens einer je Newsletter**; erneutes Vormerken
  ersetzt den Text. Bis zum Start änderbar und löschbar.
- Nach `fertig` des laufenden Auftrags gibt die VM die vorgemerkte Nachricht frei
  (`wartet` → `offen`); der Arbeiter holt sie normal ab und baut auf der neuen Fassung auf.
- Endet der Lauf mit `fehler` oder Stopp, wird die Vormerkung **nicht** automatisch gestartet:
  sie bleibt mit „Starten“ / „Verwerfen“ stehen.
- `wartet` sperrt das Handspeichern nicht.

### 3.2 Stopp
- „Stopp“ in der Chat-Leiste fragt: **„Bisherige Schritte behalten“** oder **„Verwerfen“**.
- VM setzt `stopp`; der Arbeiter erfährt es beim nächsten Zwischenstand (`weiter: false`),
  beendet den Claude-Lauf und meldet ab.
- **Behalten**: letzter Zwischenstand wird Fassung (Urheber `agent`, Notiz „gestoppt nach
  Schritt N“) – mit Flächen-Rechnen und Validator wie bei `fertig`; ist er ungültig ⇒ wie
  Verwerfen, mit Hinweis im Chat.
- **Verwerfen**: keine neue Fassung.
- Meldet sich der Arbeiter nicht binnen **15 s** nach dem Stopp, schließt die VM den Auftrag
  selbst ab (Behalten ⇒ aus dem letzten Zwischenstand).

## 4. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Shim streamt nicht / bricht ab | Arbeiter fällt auf die bisherige Wiederholungslogik zurück (bis 3 min), Live-Stand bleibt beim letzten gültigen Schritt |
| Zwischenstand-Aufruf scheitert | nicht fatal; nächster Versuch beim nächsten Schritt; Vergabe-Keepalive läuft weiter |
| Stopp während Korrekturversuch | Stopp gewinnt |
| Vormerkung, Newsletter wird inzwischen entschieden | Vormerkung `fehler` „Newsletter wurde entschieden“ |
| Editor verliert Verbindung | zeigt „Verbindung …“, Sperre bleibt bis zum nächsten Stand |

## 5. Tests und Abnahme

- Marketing-Shim: Streaming mit gefälschter CLI; Nicht-Streaming unverändert; Fehler-Chunk.
- Arbeiter: inkrementeller Leser (zerschnittene Chunks, Klammern in Strings, Codezaun, zwei
  Änderungen in einem Chunk); Drosselung 1/s mit letztem Stand; Stopp-Antwort beendet den Lauf;
  Korrektur während des Streams.
- Migration 061: Probe mit ROLLBACK + `verify_061` (Vormerken/Ersetzen/Freigabe nach fertig,
  keine Freigabe nach fehler/Stopp, Stopp behalten/verwerfen, 15-s-Abschluss, Zwischenstand
  geleert, `wartet` sperrt nicht).
- API + sales-ui: Zwischenstand-Route (Schlüssel, Größe, Vergabe), Vormerken/Ändern/Löschen,
  Stopp, erweiterte Stand-Antwort.
- Editor (vitest): Live-Darstellung und Hervorhebung, 1-s-Takt nur im Lauf, Vormerken,
  Stopp-Dialog; Paket-Test; tsc.
- **Echter Lauf**: Umbau per Chat live verfolgen und dabei die nächste Nachricht vormerken;
  einmal stoppen + behalten, einmal stoppen + verwerfen; Bildschirmaufnahmen an den Betreiber.

## 6. Nicht in diesem Baustein

Eingreifen in den laufenden Agenten (Korrektur mitten im Lauf), mehrere Vormerkungen,
Streaming für andere Marketing-Agenten (der Shim kann es, genutzt wird es hier nur vom
Chat-Arbeiter), Live-Serverbilder für Flächen während des Laufs.
