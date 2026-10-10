# Bilder: FLUX.2 klein, gezielt ändern, eigene Fotos einbauen — Design

Stand: 2026-10-10 · Status: in drei Abschnitten vom Betreiber freigegeben

## Ziel

Der Newsletter-Agent soll Bilder **besser und schneller erzeugen**, ein vorhandenes Bild **gezielt
ändern** („Himmel abendrot, Rest bleibt“) und **eigene Fotos einbauen** (Produktfoto, Person, Ort aus
den Medien oder aus einem Chat-Anhang). Grundlage ist FLUX.2 [klein] 4B (Apache 2.0, kommerziell
nutzbar). **Alles läuft über den Agenten**; das Bildfeld im Editor verliert seine KI-Knöpfe.

## Entscheidungen des Betreibers

| Frage | Antwort |
|---|---|
| Reihenfolge der drei Bild-Blöcke | FLUX.2 klein zuerst; Maske/Inpainting und Video später als eigene Blöcke |
| Umfang Bearbeiten | Gezielt ändern **und** eigene Fotos einbauen |
| Weg | A: FLUX.2 klein für Erzeugen und Ändern, FLUX.1 bleibt als Rückfall per Schalter |
| Bedienung | Alles über den Agenten; keine Bild-KI-Knöpfe mehr im Bildfeld |

## Ausgangslage (gemessen 10.10.)

- PC: RTX 3060 12 GB. ComfyUI 0.26.0 auf :8188 kennt bereits `EmptyFlux2LatentImage`,
  `Flux2Scheduler` und `ReferenceLatent` – kein Update, kein Neustart (ComfyUI wird nie beendet).
- Heute: `bilder/flux_schnell_api.json` (FLUX.1-schnell GGUF Q4, 4 Schritte),
  `flux_schnell_img2img_api.json` (Überarbeiten mit Stärke = denoise), `freistellen_api.json`.
  Bild-Arbeiter :8133: Phase 1 Ollama (Ausgangsbild beschreiben, englischen Prompt schreiben,
  `keep_alive 0`), Phase 2 ComfyUI, danach Schönheits-/Farbprüfung und Einsetzen als neue Fassung.
- Agent-Werkzeuge heute: `bild_erzeugen` (platz, hinweis), `bild_freistellen`, `bild_aus_medien`.
  Ändern eines vorhandenen Bildes kann nur das Bildfeld von Hand (Stärke-Regler).

## 1. Modell und Bild-Arbeiter (PC)

### Modelle

In den ComfyUI-Modellordner (zusammen rund 12 GB Platte), aus den Comfy-Org-Paketen:

- `diffusion_models/flux-2-klein-4b-fp8.safetensors` (destilliert, schnell)
- `text_encoders/qwen_3_4b.safetensors`
- `vae/flux2-vae.safetensors`

Die FLUX.1-Dateien bleiben liegen (Rückfall).

### Abläufe (`spaces/marketing/bilder/`)

- `flux2_klein_api.json` – neues Bild, Text→Bild; optional 1–3 Vorlagen als Referenz-Latents.
- `flux2_klein_aendern_api.json` – Ausgangsbild als Referenz 1 plus Anweisung; optional bis zu 2
  weitere Vorlagen.
- Höchstens **3 Referenzbilder je Auftrag** (12 GB VRAM).
- Die Abläufe werden aus den Comfy-Org-Vorlagen abgeleitet. Der Code setzt Prompt, Maße, Seed und
  Referenzbilder über feste Knoten-IDs, wie heute.

### Bild-Arbeiter :8133

- Modi: `neu`, `aendern` (ersetzt `ueberarbeiten`), `freistellen` (unverändert).
- Ollama schreibt weiter den englischen Prompt aus Hinweis bzw. Anweisung.
- Bei `aendern` entfällt der Schritt „Ausgangsbild beschreiben“, denn FLUX.2 sieht die Referenz
  selbst.
- **Vorlagen** sind Mediennamen. Der Arbeiter lädt sie wie heute die Quelle (`quelle_normalisieren`,
  zu Große werden verkleinert), lädt sie zu ComfyUI hoch und setzt sie als Referenzen ein.
- Maße, Schönheitsprüfung, Farbprüfung und Einsetzen bleiben wie heute.
- **Rückfall:** `MARKETING_BILDMODELL=flux1`:
  - `neu` nutzt `flux_schnell_api.json`;
  - `aendern` nutzt das alte Bild-zu-Bild mit fester Stärke 55;
  - Vorlagen werden ignoriert, mit dem Hinweis „Vorlagen nur mit FLUX.2“.
- Vorgabe ist `flux2`, aber **erst nach dem Messlauf und dem Ok des Betreibers**. Bis dahin ist
  der Schalter am PC auf `flux1` gesetzt.

### Messlauf (vor der Umstellung)

- Drei echte Newsletter-Motive (Kopfbild, Thema, Ausblick) auf FLUX.1 und FLUX.2, je mit
  Kaltstart- und Warmzeit.
- Dazu ein Änderungsbeispiel („Himmel abendrot“) und ein Einbau mit einer Vorlage.
- Die Bilder werden dem Betreiber zum Vergleich hingelegt.

### Datenbank – Migration 068

- `bild_auftraege.vorlagen jsonb NOT NULL DEFAULT '[]'`: Liste von Mediennamen (Texte), höchstens 3.
- Modus `aendern` neu zugelassen. `ueberarbeiten` bleibt in der Prüfregel erlaubt, damit alte
  Zeilen lesbar bleiben; neue Aufträge nutzen es nicht mehr.
- `staerke` bleibt für den Rückfall und wird bei `aendern` nicht gesetzt (Vorgabe).
- Die Anlege-Funktion bekommt `p_vorlagen`. Sie prüft Liste, Texte, Anzahl und dass `aendern`
  nur auf einen Platz mit Bild zielt.
- Additiv und idempotent; `verify_068`.

## 2. Agent und Chat

### Werkzeuge des Editor-Agenten

- **`bild_erzeugen`** (`platz`*, `hinweis`*, neu `vorlagen`: bis zu 3 Mediennamen).
- **`bild_aendern`** (neu; `platz`*, `anweisung`*, `vorlagen`: bis zu 2 Mediennamen).
  - Der Platz muss ein echtes Bild tragen.
  - Leerer Platzhalter: Das Werkzeug lehnt ab mit „Hier ist noch kein Bild – nimm bild_erzeugen“.
  - Die Anweisung hat höchstens 500 Zeichen, wie der Hinweis.
- **`bild_freistellen`** und **`bild_aus_medien`** bleiben unverändert.
- Vorlagen werden geprüft wie heute `quelle`:
  - nur Namen aus der Medienliste des Mandanten;
  - keine erfundenen Namen;
  - keine fremden Mandanten.
- Höchstens 3 Bildaufträge je Runde, wie bisher.

### So arbeitet der Betreiber

- Ein Bild markieren und „mach den Himmel abendrot“ sagen: `bild_aendern` für genau diesen Platz.
- Ein Foto im Chat anhängen und „bau das ins Titelbild ein“ sagen: Der Anhang liegt bereits in den
  Medien; `bild_erzeugen` oder `bild_aendern` nutzt ihn als Vorlage.
- „Nimm unser Produktfoto“ ohne eindeutigen Treffer: Der Agent fragt nach und ändert nichts
  (`"aenderungen": []`).

### Prompt-Regeln (Editor-Agent)

- **Logos und Schrift nie über das Bildmodell.** FLUX verzerrt Logos und erfindet Buchstaben. Ein
  Logo gehört als eigener Bild- bzw. Logo-Block auf die Fläche, nicht als Vorlage.
- **Ändern vor neu Erzeugen,** wenn nur ein Teil des Bildes anders werden soll.
- **Bildaufträge sind asynchron.** Der Agent sagt „wird erzeugt, kommt als neue Fassung“ und
  behauptet kein fertiges Ergebnis.

### Zusammenspiel mit vorhandenen Abläufen

- **Parallele Runden:** Beim Nachspielen werden Bildaufträge über die Platzzuordnung nachgezogen,
  die Vorlagen reisen mit. Fehlt der Platz, wird der Auftrag mit Hinweis verworfen.
- **Gescheiterte Bildaufträge** erscheinen wie heute als Hinweis an der beauftragenden Runde
  („Bild für <Platz> nicht erzeugt: <Befund>“).
- **Gestaltungsfenster (Flächen):** gleicher Umfang wie heute; wo dort `bild_erzeugen` geht, gibt es
  jetzt auch `bild_aendern` und Vorlagen.

## 3. Oberfläche, Fehlerfälle, Tests

### Editor (sales-claw)

- Das Bildfeld verliert Hinweis, Stärke-Regler, „Ganz neu erzeugen“, „Erzeugen/Überarbeiten“ und
  „Freistellen“.
- Es behält Medienwahl, Alternativtext, Link, Breite/Höhe, Ausrichtung und Schwarz-weiß.
- Neue Zeile: „Bild erzeugen, ändern oder freistellen: Bild markieren und den Assistenten fragen“.
- Die Stand-Anzeige am Platz (wartet / läuft / Fehler) bleibt.
- sales-ui: Die Weiterleitung für Bildaufträge von Hand entfällt (404). Die Marketing-API behält
  ihre Route, denn der Chat-Arbeiter beauftragt darüber.

### Fehlerfälle

Jeder Fehler wird als Hinweis an der Runde gemeldet. Es gibt keinen stillen Rückfall auf FLUX.1.

| Fall | Verhalten |
|---|---|
| Modelldatei fehlt am PC | Befund „Bildmodell FLUX.2 fehlt am PC“ |
| Vorlage gelöscht / kein Bild | Befund mit dem Namen der Vorlage |
| Vorlage zu groß | wird verkleinert wie heute |
| Grafikspeicher reicht nicht | Befund „Zu viele Vorlagen für die Grafikkarte – mit weniger Vorlagen noch einmal“ |
| Kaltstart von der HDD | Abfragen läuft bis zum Gesamtlimit (seit 09.10.) |
| `bild_aendern` auf leeren Platz | Werkzeug lehnt ab, kein Auftrag |
| Rückfall `flux1` mit Vorlagen | Auftrag läuft ohne Vorlagen, mit Hinweis |

### Tests

- **DB:**
  - `verify_068`, zweifach anwendbar.
  - `vorlagen` ist eine Liste von höchstens 3 Texten.
  - Modus `aendern` geht; alte `ueberarbeiten`-Zeilen bleiben gültig.
  - `aendern` auf einen leeren Platz wird abgelehnt.
- **Arbeiter (Fake-ComfyUI):**
  - `neu` ohne Vorlagen und `neu` mit 3 Vorlagen;
  - `aendern` mit Ausgangsbild als Referenz 1, ohne Beschreibungsschritt;
  - fehlende Vorlage gibt einen Befund;
  - Rückfall `flux1`;
  - Knoten-IDs und Eingänge beider Ablauf-Dateien existieren.
- **Agent-Werkzeuge:**
  - Vorlagen nur aus der Medienliste, höchstens 3 bzw. 2;
  - `bild_aendern` auf einen leeren Platz wird abgelehnt;
  - das Nachspielen zieht die Vorlagen mit.
- **Prompt:** Logo-Regel, Ändern vor neu Erzeugen, Asynchronität.
- **Editor:** Das Bildfeld hat keine KI-Knöpfe mehr; die Stand-Anzeige bleibt.
- **Messlauf:** wie in Abschnitt 1.
- **Echter Lauf (Probe-Entwurf):**
  - Bild markieren, „Himmel abendrot“: kommt als neue Fassung.
  - Foto anhängen, „ins Titelbild einbauen“: kommt als neue Fassung.

### Grenzen

- Höchstens 3 Referenzbilder je Auftrag (`aendern`: Ausgangsbild + höchstens 2).
- Höchstens 3 Bildaufträge je Runde.
- Kein Modell auf der VM; alles läuft im PC-Arbeiter.

## Nicht Teil dieses Blocks

- Maske/Inpainting (eigener Block danach).
- Video (Wan 2.2 / FramePack; eigener Block).
- Marken-Chat.
- Löschen der FLUX.1-Dateien.
- Modelle auf der VM.
