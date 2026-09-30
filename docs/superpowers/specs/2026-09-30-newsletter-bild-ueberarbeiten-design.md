# Newsletter-Bilder überarbeiten: sehen, Prompt zusammensetzen, Bild-zu-Bild

**Stand 30.09.2026. Abschnitt für Abschnitt mit dem Betreiber besprochen und
freigegeben. Baut auf `2026-09-29-newsletter-bilder-und-gestaltung-design.md`
(ausgeliefert 30.09.) auf.**

## 0. Änderung 30.09.2026 nach Messung (Betreiber-Entscheid „Neu mit Motiv")

Gemessen am Hochhaus-Bild mit deutlichem Prompt („warm golden amber, plain
facades, no signs"): FLUX.1-schnell Bild-zu-Bild hat eine **Kante zwischen 85
und 90 %** — darunter bleiben Farben und (neue Fantasie-)Schrift erhalten
(70/80/85 %: kühl, Schrift da), darüber entsteht ein **ganz neues** Bild (90 %:
warm, ohne Leuchtschrift, anderer Aufbau). Einen Bereich „Aufbau bleibt,
Stimmung ändert sich" gibt es nicht. CLIP misst dabei das **Thema**, nicht den
Aufbau (90 %-Bild: 0,84; fremdes Motiv: 0,69).

Deshalb gilt, und ersetzt §2 „Art der Überarbeitung"/„Stärke", §4.5, den
Regler in §5 und die Bild-zu-Bild-Zeile in §7:

- **Überarbeiten = neu mit Motiv:** Sehmodell beschreibt das Motiv (ohne
  Schrift) → Prompt aus Motiv + Wunsch → **FLUX Text-zu-Bild** in den Maßen des
  Platzes. Das Ausgangsbild dient nur zum Sehen und Messen. Der Bild-zu-Bild-Code
  bleibt getestet im Repo, wird aber nicht angesteuert.
- **Statt Regler zwei Stufen:** „nah am Original" (Stärke 35: Prompt hält Motiv,
  Umgebung und Bildaufbau der Beschreibung fest) und „freier" (Stärke 75: nur
  das Thema bleibt), plus „ganz neu" (100: ohne Beschreibung). DB/API behalten
  die Zahl 0–100; die Oberfläche bietet nur diese drei Werte.
- **Messung** heißt in der Oberfläche **„Themen-Ähnlichkeit"**; bei „nah"
  (Stärke ≤ 60) gilt weiter: < 0,75 → neuer Versuch, nach 3 das beste.

## 1. Ziel

Ein vorhandenes Newsletter-Bild wird gezielt überarbeitet statt neu gewürfelt:
das System erkennt, **was zu sehen ist**, verbindet das mit dem, **was sich
ändern soll**, zu einem Prompt und überarbeitet **dieses** Bild mit FLUX
(Bild-zu-Bild). Die Wirkung wird mit CLIP-Vektoren **gemessen** (wie bei Laura),
nicht vom Modell behauptet. Neue Bilder erscheinen in Editor und Pult von selbst.

Erfolg: Hochhaus-Bild mit Fantasie-Leuchtschrift, Hinweis „keine Leuchtschrift,
wärmeres Licht", Stärke 55 % → Bildaufbau bleibt, Schrift weg, Licht wärmer;
angezeigt „82 % ähnlich zum Original"; der Editor zeigt es ohne Neuladen.

## 2. Entscheidungen des Betreibers

| Frage | Entscheid |
|---|---|
| Art der Überarbeitung | **Bild-zu-Bild mit FLUX.1-schnell** (Ausgangsbild + Prompt, Stärke = denoise). FLUX Kontext verworfen (Lizenz nicht kommerziell) |
| Stärke | **freier Regler 0–100 %**, Standard 55 % |
| Sehen | Sehmodell beschreibt das Bild; CLIP-Vektoren (wie Laura) als Messung |
| Erscheinen | Editor lädt automatisch, wenn nichts ungespeichert ist; Pult-Seite lädt alle 20 s neu, solange Aufträge offen sind |
| Agent | ob marketing-openclaw alles bedienen kann: **nach der Abnahme** prüfen und ggf. nachziehen |
| Wo laufen Modelle | **Nur auf dem PC.** Auf dem Proxmox-Mini-PC (VM) läuft **kein** Modell — weder Sehmodell, Textmodell, FLUX noch CLIP. Die VM hält nur Datenbank, Marketing-API und Dateien; jede Modellanfrage erledigt der Bild-Arbeiter am PC. |

## 3. Gemessen (30.09.2026)

- Laura: CLIP `Qdrant/clip-ViT-B-32-vision`/`-text` über fastembed (ONNX, CPU),
  512 dim, nur Vektoren (`spaces/video/laura/services/local-api/src/laura/analysis/visual_embed.py`).
  Beschreibungen gibt es dort nicht; ein Sehmodell (Ollama) bewertet nur Schnitte.
- `qwen2.5vl:7b` mit Ollama-Standardkontext: 500 „requires 37,6 GiB". Mit
  **`num_ctx 4096`**: `qwen2.5vl:3b` 53 s, `7b` 110 s (inkl. Laden von HDD E:);
  beide beschreiben Motiv, Farben, Licht **und sichtbare Schrift** korrekt.
- FLUX: Rechnen ~6 s/Bild, Modell-Laden ~118 s von HDD — Modelle je Auftrag einmal laden.
- Im Repo gibt es keinen Bild-zu-Bild-Arbeitsablauf; ComfyUI nur `bild_comfy.py` (Text-zu-Bild).

## 4. Ablauf

1. **Auslösen** (Editor-Bildfeld, Pult-Formular, Agent-Werkzeug): Hinweis,
   Stärke 0–100 (Standard 55), Häkchen „ganz neu erzeugen" (= 100 %, ohne
   Ausgangsbild). Leerer Platz → immer neu.
2. **Quelle**: der Arbeiter holt das aktuelle Bild des Platzes von der VM.
3. **Sehen**: `qwen2.5vl:3b` (`num_ctx 4096`, Zeitlimit 180 s) beschreibt Motiv,
   Umgebung, Farben, Licht, sichtbare Schrift.
4. **Prompt**: Textmodell verbindet Beschreibung + Hinweis: was bleibt,
   übernehmen; was sich ändern soll, einarbeiten; immer „no text, no letters,
   no words, no logos, no watermark".
5. **Bild-zu-Bild**: Ausgangsbild per `/upload/image` an ComfyUI; Arbeitsablauf
   `bilder/flux_schnell_img2img_api.json` (LoadImage → VAEEncode → KSampler
   `denoise = staerke/100`, 8 Schritte → VAEDecode → SaveImage) in den Maßen des Platzes.
6. **Messen** (CLIP wie Laura, fastembed, CPU):
   `aehnlich_original` = cos(Bild alt, Bild neu);
   `naeher_am_hinweis` = cos(Hinweistext, neu) − cos(Hinweistext, alt).
   Bei Stärke ≤ 60 % muss `aehnlich_original` ≥ 0,75 sein, sonst neuer Versuch
   (anderer Seed, höchstens 3); danach das beste Bild mit Befund.
7. **Ergebnis**: neue Fassung (Urheber agent), Messwerte im Auftrag; „Mensch
   gewinnt" und Vergabe unverändert; altes Bild bleibt in den Medien.

Reihenfolge je Auftrag: erst alle Beschreibungen und Prompts (Ollama,
`keep_alive 0`), dann alle Bilder am Stück (FLUX einmal geladen, `/free` am
Ende), dann die Messung.

## 5. Bedienung und Erscheinen

**Editor (Bildfeld):** Hinweis, Regler „Stärke der Überarbeitung" 0–100 %
(Standard 55, Erklärung „niedrig = Aufbau bleibt, hoch = fast neu"), Häkchen
„Ganz neu erzeugen"; Knopf „Bild überarbeiten" bzw. „Bild erzeugen" (leerer
Platz). Stand am Platz: „wartet (PC muss laufen)" → „wird überarbeitet" →
fertig/fehlgeschlagen mit Grund. **Fertig und nichts ungespeichert:** neue
Fassung wird automatisch geladen, Platz kurz hervorgehoben, Hinweis „Neues
Bild vom Agenten – 82 % ähnlich zum Original". **Ungespeichert:** bisheriger
Konflikt-Weg (laden / als Kopie behalten), Bild liegt schon in den Medien.

**Pult (Entwurfsseite, ohne Skript):** Formular mit Stärke (0–100) und Häkchen
„ganz neu"; solange ein Auftrag `offen`/`in_arbeit` ist, `<meta
http-equiv="refresh" content="20">`, sonst nicht; Auftragsliste zeigt die Messung.

## 6. Daten und Schnittstellen

**Migration 057 (additiv):** `bild_auftraege` + `staerke int NOT NULL DEFAULT
55 CHECK (0..100)`, `modus text NOT NULL DEFAULT 'ueberarbeiten' CHECK (modus IN
('neu','ueberarbeiten'))`, `messung jsonb NOT NULL DEFAULT '{}'`.
`pult_bild_auftrag` neue Überladung mit `p_staerke int, p_modus text`; die
5-Argument-Form bleibt (ruft die neue mit 55/'ueberarbeiten'; der
System-Auftrag aus „Neu aus Vorlage" nutzt `neu`). `pult_bild_naechster`
liefert `staerke`, `modus`. `pult_bild_einsetzen` nimmt ein optionales
`p_messung jsonb` (Platz → Werte) und speichert es.

**API:** Pult- und Agent-Routen: `staerke` (ganze Zahl 0–100) und `modus`
geprüft, sonst 422; Auftragsliste enthält `staerke`, `modus`, `messung`.
Neu: `GET /api/bilder/arbeiter/{auftrag}/quelle?platz=<id>` (X-Bild-Key; nur
Plätze des Auftrags in Arbeit; Datei aus `media-erzeugt/` oder `media/` des
Basis-Ladens, nur Bildendungen, ohne Pfadtricks). `fertig` nimmt `messung`.

**Arbeiter:** neue Module `claw/bild_sehen.py` (Beschreibung, `num_ctx 4096`),
`claw/bild_messen.py` (CLIP, fastembed); `bild_comfy.ueberarbeiten(...)`;
alle Ollama-Aufrufe mit `num_ctx 4096`. Selbstprüfung bleibt standardmäßig aus.

**Agent:** `newsletter_bild_beauftragen(..., staerke=55, modus="ueberarbeiten")`.

## 7. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Quellbild fehlt in den Medien | neu erzeugen (100 %), Befund nennt Grund |
| Sehmodell scheitert/Zeitlimit | Prompt aus alt + Kontext + Hinweis, Bild-zu-Bild läuft, Befund „ohne Bildbeschreibung" |
| Upload zu ComfyUI scheitert | Auftrag zurück (nicht endgültig) |
| Ähnlichkeit zu gering (Stärke ≤ 60 %) | neuer Versuch, nach 3 das beste mit Befund |
| CLIP fehlt/scheitert | Bild eingesetzt, Messung „nicht gemessen" |
| Mensch belegt Platz inzwischen | unverändert: Mensch gewinnt |
| Stärke außerhalb 0–100 | 422 |

## 8. Tests

- DB (`migration_probe`, ROLLBACK): Stärke/Modus, leerer Platz → neu, alte
  Signatur, Messung übernommen.
- API: Stärke-Grenzen, Quellen-Route (Schlüssel, fremder Platz, Pfadtricks), Messung bei `fertig`.
- Arbeiter (Fakes): Reihenfolge, einmal Laden, Wiederholung bei geringer
  Ähnlichkeit, Rückfälle, `num_ctx` in jedem Ollama-Aufruf.
- **Echter Lauf am PC**: Hochhaus-Bild, „keine Leuchtschrift, wärmeres Licht",
  55 % — Dauer, beide Messwerte, Bild angesehen.
- Editor: Regler, Häkchen, Knopftext, automatisches Laden. Pult: Neuladen nur
  bei offenen Aufträgen, Formularfelder.

## 9. Nicht Teil dieser Spec

Selbstprüfung dauerhaft einschalten; Modelle auf SSD verlagern (eigene
Entscheidung); Masken/Teilbereiche übermalen (Inpainting); FLUX Kontext.
Die Prüfung, ob marketing-openclaw alles bedienen kann, folgt **nach der
Abnahme** als eigener Schritt.
