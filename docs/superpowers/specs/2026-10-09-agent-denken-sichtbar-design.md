# Agent-Denken sichtbar machen — Design

Stand: 2026-10-09 · Status: vom Betreiber in drei Abschnitten freigegeben

## Ziel

Der Betreiber will sehen, was der Marketing-Agent **macht und denkt**, und zwar **beides**:
live mitlesen, während eine Runde läuft, und danach pro Runde aufklappbar nachvollziehen.
Das gilt für **beide Agenten**, den Editor-Agenten (Newsletter-Entwurf) und den Marken-Chat
(Seite „Marke“).

Entscheidungen des Betreibers:

| Frage | Antwort |
|---|---|
| Zweck | live mitlesen **und** danach nachvollziehen |
| Welcher Agent | Editor-Agent und Marken-Chat gleich |
| Was heißt „denkt“ | echtes Modell-Denken (Claudes zusammengefasstes Denken), keine selbst geschriebenen Begründungen |
| Sprache | Englisch, wie es kommt; keine Übersetzung, keine Denk-Anweisung |
| Transportweg | über die bestehenden Auftragszeilen (Weg A), kein eigener Live-Kanal |

## Machbarkeit (geprüft am 08.10.)

- `claude -p --output-format stream-json --include-partial-messages` liefert Denkblöcke ohne
  Inhalt: `thinking` ist leer, es kommen nur `estimated_tokens`. `showThinkingSummaries` und
  `alwaysThinkingEnabled` ändern daran nichts (vgl. Claude-Code-Issue #82896).
- Der undokumentierte CLI-Schalter **`--thinking-display summarized`** zusammen mit
  `--max-thinking-tokens <n>` liefert das zusammengefasste Denken als `thinking_delta`, live
  und über den Abo-Login. Im Probelauf kamen 52 Deltas mit Text. Den Schalter benutzt das
  Python-Agent-SDK intern (`claude_agent_sdk` 0.2.164, `subprocess_cli.py`).
- Weil der Schalter undokumentiert ist, kann er nach einem CLI-Update verschwinden. Daraus
  folgt die Rückfallregel in §5.

## 1. Datenfluss

1. **Marketing-Shim :8117** (`spaces/marketing/claw/shim/marketing_shim.py`):
   - Eine Anfrage fordert Denken mit dem Body-Schlüssel `"marketing_denken": true` an, so wie
     heute schon `marketing_ohne_werkzeuge`. Nur dann startet der Shim die CLI zusätzlich mit
     `--max-thinking-tokens 4000 --thinking-display summarized`.
   - `thinking_delta`-Texte gehen als `choices[0].delta.reasoning_content` in den Strom.
     `text_delta` bleibt unverändert `delta.content`. Andere Nutzer des Shims sehen nichts
     Neues.
   - Mit `MARKETING_DENKEN=0` in der Shim-Umgebung lässt der Shim die Schalter immer weg.
2. **Chat-Arbeiter :8134** (`workers/chat_worker.py`, Editor-Faden und Marken-Faden):
   - Er fordert für jede Agentenfrage Denken an.
   - Er sammelt `reasoning_content` pro Auftrag in einem Puffer und führt eine **Schrittliste**
     aus kurzen festen Satzbausteinen mit Uhrzeit (Beispiele unten).
   - Beides sendet er **gedrosselt (höchstens alle 2 s)** und am Ende der Runde an die VM.
   - Die Antwort-Auswertung (`agent_strom.StromLeser`, `marken_prompt`) sieht ausschließlich
     `content`.
3. **VM** (Marketing-API :5510, tailnet :8446):
   - Migration **065** legt in `marketing.chat_auftraege` und `marketing.marken_auftraege` je die
     Spalten `denken text` und `schritte jsonb` (Array von `{zeit, text}`) an. Dazu kommen
     DB-Funktionen, die nur bei gültiger Vergabe schreiben, wie `zwischenstand`.
   - Neue Arbeiter-Routen (Header `X-Bild-Key`):
     - `POST /api/chat/arbeiter/{aid}/denken` (Editor)
     - `POST /api/marke/arbeiter/{aid}/denken` (Marke)
     - Body: `{"denken": str, "schritte": [{"zeit": str, "text": str}]}`
     - Antwort `{"ok": true}`, bzw. `409` bei verlorener Vergabe.
   - Die Stand-Routen liefern die Felder pro Auftrag mit: Editor `GET /api/pult/inhalte/{iid}/chat`
     (Verlauf und laufender Auftrag), Marke `GET /api/pult/marke` (Liste `auftraege`, auch
     `uebernehmen`-Schritte über `letzte_uebernahme` und den laufenden Auftrag).
   - Gespeichert bleibt es so lange wie die Aufträge. Es gibt kein eigenes Löschen.

### Schritte (Satzbausteine)

- **Marken-Chat:**
  - „Webseite gelesen (n Seiten)“
  - „Webseite nicht lesbar“
  - „Logo-Kandidaten: n“
  - „Frage an Claude“
  - „Antwort geprüft: <Grund> – Korrekturrunde“
  - „Vorschlag abgelegt“
- **Übernahme:**
  - „Rowboat geschrieben“
  - „Logo verkleinert“
  - „Spiegel aktualisiert“
  - „Spiegel abgelehnt: <Grund>“
- **Editor:**
  - „Frage an Claude“
  - „Block <id> geändert“
  - „Block <id> neu“
  - „Bild beauftragt“
  - „Schönheitsprüfung: n Hinweise“
  - „Korrekturrunde“
  - „Fassung gespeichert“

Schritte enthalten nie Schlüssel, Umgebungswerte oder URLs mit Zugangsdaten. Eine URL
erscheint nur ohne Zugangsdaten, wie heute in den Hinweisen.

## 2. Oberfläche

**Editor (Chat-Leiste, `editor/src/App/Chat/ChatLeiste.tsx`):**
- **Während der Agent arbeitet:**
  - Unter der Fortschritts-Linie steht ein Feld „Denkt nach …“. Es zeigt die letzten Zeilen des
    Denkens, läuft mit und ist gedämpft in kleinerer Schrift gesetzt.
  - Darunter steht die Schrittliste mit Uhrzeit. Neue Schritte blenden weich ein, wie die
    Zwischenstände.
  - Der Schalter „Gedanken ausblenden“ klappt beides zu. Der Zustand liegt in `localStorage` und
    wird in try/catch gelesen und geschrieben.
- **Nach der Runde:** Jeder Verlaufseintrag hat unter Antwort und Hinweisen ein zugeklapptes
  „Gedanken & Schritte“ mit Schrittliste und ganzem Denken.
- **Kennzeichnung:** „Claudes Gedanken (zusammengefasst, englisch)“.

**Seite „Marke“ (`sales-mcp/ui_marke.py`):**
- **Während eine Runde läuft:** Unter der Statuszeile stehen die Schritte und der neueste
  Ausschnitt des Denkens (letzte ca. 600 Zeichen). Die Seite lädt sich wie heute alle 5 s neu.
- **Nach der Runde:** Jede Chat-Runde im Verlauf hat `<details>` „Gedanken & Schritte“.
- **Übernahme:** Sie zeigt ihre Schritte. Denken gibt es dabei nicht, weil kein Modell beteiligt ist.

**Sichtbarkeit:** Nur in der Betreiber-Oberfläche. Nichts geht in Newsletter, Exporte,
Vorschauen oder an Kunden.

## 3. Fehlerfälle

- **CLI kennt den Schalter nicht:** Der Shim erkennt den Abbruch an einer Fehlermeldung zur
  Option ohne jede Ausgabe und startet denselben Aufruf **einmal ohne** Denk-Schalter neu. Im
  Strom kommt dann ein `reasoning_content`-Hinweis „(Denken nicht verfügbar)“. Der Arbeiter
  übernimmt ihn als Schritt „Denken nicht verfügbar (CLI)“. Die Runde scheitert daran nie.
- **Schreiben an die VM scheitert** (Netz, 5xx): Der Arbeiter überspringt es und versucht es
  beim nächsten Takt erneut. Er wiederholt nicht pro Delta. Am Auftrag ändert das nichts.
- **Vergabe verloren (409):** Der Arbeiter schreibt für diesen Auftrag kein Denken mehr. Den
  Auftragsabbruch regelt der bestehende Halter.
- **Stopp / Abbruch / Fehler:** Das bis dahin Gesammelte bleibt stehen. Der Arbeiter sendet es
  vor der Abschlussmeldung ein letztes Mal.
- **Korrekturrunde:** Das Denken wird mit der Zeile `— Korrekturrunde —` angehängt.

## 4. Grenzen

- Denkbudget: `--max-thinking-tokens 4000` pro CLI-Aufruf.
- Gespeichertes Denken: höchstens 20 000 Zeichen pro Auftrag. Bei Überlauf bleibt das
  **Ende** erhalten; vorn steht dann „… gekürzt“.
- Höchstens 60 Schritte pro Auftrag, je höchstens 200 Zeichen. Die DB-Funktion setzt dieselben
  Grenzen noch einmal durch.
- Drossel: höchstens ein Schreibvorgang je 2 s pro Auftrag.

## 5. Tests

- **Shim:**
  - Die Schalter stehen nur bei `marketing_denken` in argv.
  - `MARKETING_DENKEN=0` lässt sie weg.
  - `thinking_delta` wird zu `reasoning_content`, `text_delta` bleibt `content`.
  - Bei abgelehntem Schalter folgt genau ein Neustart ohne Schalter, mit Hinweis.
- **Arbeiter:**
  - Sammeln, Drossel (Uhr injiziert), Kürzung am Anfang, Schrittgrenzen.
  - Trennzeile der Korrekturrunde.
  - `reasoning_content` stört `StromLeser` und `marken_prompt` nicht.
  - Ein Schreibfehler lässt den Auftrag nicht scheitern.
  - Endmeldung bei Stopp.
- **DB / API:**
  - `verify_065.sql`, zweifach anwendbar.
  - Fremde oder abgelaufene Vergabe → 409.
  - Grenzen werden in SQL durchgesetzt.
  - Stand-Routen liefern `denken` / `schritte`.
- **Oberfläche:**
  - Seite „Marke“ (pytest): Live-Ausschnitt und `<details>`.
  - Editor (vitest): Feld „Denkt nach …“, Ausblenden-Schalter, aufklappbarer Eintrag.
  - Ohne Denken (leer) erscheint nichts Leeres.
- **Echter Lauf:**
  - Eine Marken-Runde fin2gether: das Denken läuft auf der Seite mit und ist danach
    aufklappbar.
  - Eine Editor-Runde: das Feld „Denkt nach …“ läuft live mit, der Eintrag ist danach
    aufklappbar.

## Nicht Teil dieses Blocks

- Übersetzung des Denkens.
- Ein eigener Live-Kanal (SSE/WebSocket).
- Denken für andere Shim-Nutzer oder für OpenFang-Agenten.
- Die offenen Punkte aus „Marke per Chat“: Werkzeug für das Schriftpaar und die
  Akzent-Textfarbe im Editor-Agenten. Sie bekommen einen eigenen Block.
