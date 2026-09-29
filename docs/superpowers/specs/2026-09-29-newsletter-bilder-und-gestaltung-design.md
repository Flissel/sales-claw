# Newsletter: Bilder vom Agenten, hochwertige Vorlagen, Editor im Pult-Stil

**Stand 29.09.2026. Abschnitt für Abschnitt mit dem Betreiber besprochen und
freigegeben. Baut auf `2026-09-29-newsletter-editor-design.md` (E1 ausgeliefert)
auf und zieht aus dessen E2 das Lesen und Ändern von Blöcken durch den Agenten
vor — beschränkt auf Bildplätze. „Vorlage aus Vorbild" bleibt in E2.**

## 1. Ziel

Newsletter sehen hochwertig aus und sind mit Bildern gefüllt. Die Bilder erzeugt
der Marketing-Agent mit einem **offenen Bildmodell auf dem eigenen PC**; er
findet selbst heraus, **wo im Layout Bilder vorgesehen sind und in welchem
Format**, und setzt sie genau dort ein. Der Editor sieht aus wie ein Teil des
Pults.

Erfolg: „Neu aus Vorlage" → nach kurzer Zeit (PC an) sind alle Bildplätze mit
passenden, stimmigen Bildern gefüllt → einzelne Plätze mit Hinweis neu erzeugen
lassen → freigeben. Kein kaputtes Bild in keiner Vorschau.

## 2. Entscheidungen des Betreibers

| Frage | Entscheid |
|---|---|
| Was sieht nicht gut aus | **Vorlagen und Editor** |
| Bildquelle | **offenes Modell** lokal — FLUX.1-schnell „oder Ähnliches" (austauschbar) |
| Wann entstehen Bilder | **beides**: automatisch beim Erstellen aus Vorlage **und** auf Knopf mit Hinweis |
| Wer erzeugt | **der Agent** über einen Skill `newsletter-bild`; er fragt das Layout ab und nutzt den vorgesehenen Platz |
| Aufteilung | **Ollama + Bildmodell auf dem PC, alles andere auf der VM** |

## 3. Vorhandenes (gemessen 29.09.)

- PC: RTX 3060 **12 GB**, E: > 1 TB frei.
- `E:\ComfyUI` (0.26.0, `.venv`), bisher für LTX-Video genutzt (`laura_gen.py`,
  API `127.0.0.1:8188`).
- `E:\huggingface_cache`: **FLUX.1-schnell** vollständig (inkl.
  `flux1-schnell-Q4_K_S.gguf` 6,3 GB), `flux_text_encoders`
  (`t5xxl_fp8_e4m3fn_scaled`), **SDXL base** und **SDXL-Turbo**.
  FLUX.1-schnell: Apache-2.0; SDXL: OpenRAIL++ — beide kommerziell nutzbar.
  **FLUX.1-dev liegt auch dort, ist nicht kommerziell nutzbar und wird nicht
  verwendet.**
- Ollama am PC: `qwen2.5:7b`, `qwen2.5vl:7b` (u. a.).
- Medien auf der VM: `media/` (Mensch, für Dienste nur lesbar) und
  `media-erzeugt/` (System schreibt; bei Namensgleichheit gewinnt `media/`).
  Dateinamen flach, ohne Pfad (`medien.pruefe_anhang`).
- Kein Logo vorhanden; Pitch-Deck-Bilder (`pitch-deck-2026/images/`) zeigen den
  VibeMind-Stil (dunkel, leuchtende Türkis-Netze) und dienen als Stilvorbild.

## 4. Bildplätze

- **Ein Bildplatz ist ein `Image`-Block mit `width` und `height`.** Daraus folgt
  das Seitenverhältnis. Kein neues Feld: der Editor verwirft beim Speichern
  unbekannte Props (zod-Schema).
- **Pixelmaße rechnet der Agent aus dem Layout:** Mail-Breite 600 px, abzüglich
  Innenabstände des Blocks und seiner Eltern, geteilt durch die Spaltenzahl
  (`ColumnsContainer` 2 oder 3, `columnsGap`); erzeugt wird in **doppelter
  Auflösung**, Seitenverhältnis aus `width:height`. Beispiele: Kopfbild volle
  Breite 2:1 → 1200×600; halbe Spalte 4:3 → 560×420.
- **Leer** heißt: `url` zeigt auf ein Platzhalterbild `medien:platzhalter-<b>x<h>.png`
  (einmalig gestaltet, liegt in `media-erzeugt/`, je Seitenverhältnis eines).
  Die Vorschau zeigt nie ein kaputtes Bild.
- `alt` ist zugleich inhaltlicher Hinweis für den Agenten.

## 5. Neue Vorlagen

Die fünf Startvorlagen werden neu gestaltet (gleiche Namen, neue Fassung),
mit mehr Weißraum, klarer Hierarchie (Überschrift, Unterzeile, Text),
hervorgehobenen Zahlen/Zitaten und sauberer Fußzeile:

| Vorlage | Bildplätze |
|---|---|
| Newsletter | Kopfbild 2:1, 2 Themenbilder 4:3 in Spalten, Ausblick-Bild 16:9 |
| Ankündigung | Kopfbild 2:1 volle Breite, Detailbild 16:9 |
| Einladung | Stimmungsbild 2:1, 3 kleine Bilder 1:1 zu „Was dich erwartet" |
| Produkt-Neuheit | Produktbild 16:9, 3 Spalten mit Symbolbildern 1:1 |
| Kurzer Hinweis | schmales Banner 3:1 |

- Oben **Schriftzug „VibeMind" als Text**, solange kein Logo existiert; das
  bisherige `medien:vibemind-logo.png` entfällt aus den Vorlagen.
- Jede Vorlage besteht die DB-Prüfung (`pult_bloecke_fehler`) und rendert
  fehlerfrei über `bloecke_mjml`.

## 6. Aufträge (VM)

### 6.1 Tabelle `marketing.bild_auftraege`

Spalten: `id`, `inhalt_id`, `platz` (Block-ID oder `NULL` = alle leeren),
`hinweis`, `grund_fassung` (Nummer), `status` (`offen|in_arbeit|fertig|fehler|verworfen`),
`versuche`, `vergeben_bis`, `befund`, `ergebnis` (Liste Platz → Dateiname),
`urheber` (`system|mensch|agent`), Zeitstempel.

- **Automatisch:** `pult_inhalt_aus_vorlage` legt für Newsletter einen Auftrag
  *alle leeren* an (Urheber `system`).
- **Knopf** im Pult und Editor: „Bild neu erzeugen" je Platz oder für alle, mit
  Hinweisfeld (Urheber `mensch`).
- **Chat:** der Agent legt über den Skill einen Auftrag an (Urheber `agent`).
- **Je Platz höchstens ein offener Auftrag**; ein neuer ersetzt den wartenden
  (`verworfen`).
- Für freigegebene Inhalte werden keine Aufträge angenommen; offene werden beim
  Freigeben `verworfen`.

### 6.2 Endpunkte der Marketing-API (VM)

Unter `/api/pult/bilder/*`, eigener Schlüssel `MARKETING_BILD_KEY` (Header
`X-Bild-Key`), erreichbar nur über die Tailnet-Adresse wie das Pult:

- `POST …/naechster` — vergibt den ältesten offenen Auftrag für **10 Minuten**
  (`vergeben_bis`); liefert Auftrag + neueste Fassung (Blockdokument) + Layout-Farben.
  Abgelaufene Vergaben werden wieder `offen`.
- `POST …/{auftrag}/bild?platz=<id>` — nimmt ein **JPEG ≤ 1 MB** an (Magic-Bytes
  geprüft, Platz muss zum Auftrag gehören), legt es als
  `nl-<inhalt8>-<platz>-<nr>.jpg` in `media-erzeugt/`.
- `POST …/{auftrag}/melden` — `fertig` oder `fehler` mit Befund. Bei `fertig`
  schreibt **die VM** die neue Fassung (Urheber *agent*): Bild in den Platz,
  `width`/`height` unverändert. Gibt es inzwischen eine neuere Fassung, wird
  auf **dieser** eingesetzt — **nur wenn der Platz dort noch leer ist oder noch
  das Bild aus der Grundfassung zeigt**. Sonst bleibt das Bild des Menschen,
  das neue liegt nur in den Medien, Befund „Platz inzwischen belegt".

Die Schreibrechte der Marketing-API auf `media-erzeugt/` der sales-claw-Ablage
auf der VM werden im Plan festgelegt und gemessen.

## 7. Arbeiter und Skill (PC)

### 7.1 Skill `newsletter-bild`

Liegt im Marketing-Space (`spaces/marketing/skills/newsletter-bild/SKILL.md` +
Python-Modul). Der Marketing-Agent nutzt ihn im Chat („mach das Kopfbild
wärmer") — das **legt nur einen Auftrag an**. Die Erzeugung passiert an genau
einer Stelle: im Arbeiter.

### 7.2 Arbeiter `bild_worker`

Geplante Aufgabe wie die übrigen Marketing-Dienste; je Auftrag:

1. **Layout lesen:** Fassung von der API, Plätze finden, Pixelmaße (§4).
2. **Prompt:** Ollama `qwen2.5:7b` aus Text um den Platz, `alt`, Hinweis,
   VibeMind-Stilvorgabe → englischer Bild-Prompt, immer mit „no text, no
   letters, no logos".
3. **Erzeugen:** ComfyUI + FLUX.1-schnell (GGUF Q4, 4 Schritte) im Format des
   Platzes. Das Modell steckt in einer Arbeitsablauf-Datei; SDXL oder ein
   anderes offenes Modell ist ein Tausch der Datei, kein Code.
4. **Selbstprüfung:** Ollama `qwen2.5vl:7b` bewertet das Bild (passt zum Prompt,
   keine Schrift, keine entstellten Gesichter). Durchgefallen → bis zu **2**
   neue Versuche, dann `fehler` mit Befund.
5. **Verkleinern** auf die berechneten Maße, JPEG ~150 KB, abliefern, melden.

- **Grafikspeicher:** Ollama und FLUX nie gleichzeitig — Ollama mit
  `keep_alive: 0`, ComfyUI danach `POST /free`.
- ComfyUI/Ollama nicht erreichbar → Startversuch; scheitert er, Auftrag zurück
  mit Befund; nach **3** Fehlversuchen `fehler`.

## 8. Editor im Pult-Stil

- **Eigenes MUI-Thema** mit Farben, Schrift, Rundungen und Abständen des Pults.
- **Pult-Leiste:** links Rückweg + Titel, Mitte Stand („Fassung 3 · gespeichert"
  / „ungespeicherte Änderungen"), rechts Vorschau Mail/Handy und *Speichern*.
- **Alles deutsch**; Reiter JSON/HTML entfallen, Vorschau weiter vom Server.
- **Links: Abschnitte** mit Mini-Vorschau zum Hineinziehen — Kopfbild mit Titel,
  Bild neben Text, 2 und 3 Spalten mit Bildern, Zitat, große Zahl, Knopfleiste,
  Fußgruß; jeder Abschnitt bringt Platzhalter mit. Darunter eingeklappt die
  Einzelbausteine.
- **Rechts:** Einstellungen gruppiert (*Inhalt*, *Gestaltung*, *Abstände*);
  Farben aus der Layout-Palette, freie Farbe unter „Weitere".
- **Bildfeld** bei Klick auf ein Bild: Vorschau + Format („2:1 · 1200×600"),
  **Aus Medien wählen** (Raster mit Vorschaubildern), **Bild erzeugen lassen**
  (Hinweisfeld → Auftrag, Stand am Platz: wartet auf PC / wird erzeugt /
  fehlgeschlagen mit Grund), Alternativtext. Neue Agenten-Fassung → Hinweis oben
  „Neue Fassung vom Agenten – laden" (bestehender Konfliktweg aus E1).
- Das Pult zeigt je Newsletter denselben Bildstand.
- Nebenbei behoben: Menü markiert auf `/marketing/vorlagen` „Übersicht".

## 9. Fehlerfälle

| Fall | Verhalten |
|---|---|
| PC aus | Aufträge `offen`, Platz zeigt „wartet auf PC"; alles andere läuft |
| ComfyUI/Ollama tot | Startversuch; sonst zurück mit Befund, nach 3 Versuchen `fehler` |
| Selbstprüfung durchgefallen | bis 2 neue Versuche, dann `fehler` mit Befund |
| Platz inzwischen vom Menschen belegt | Mensch gewinnt, Bild nur in Medien |
| Inhalt freigegeben | keine neuen Aufträge, offene `verworfen` |
| Falsche Datei (kein JPEG, > 1 MB, fremder Platz) | API lehnt ab, Auftrag `fehler` |
| Arbeiter-Absturz | nach 10 min wieder `offen` |
| Viele Knopfdrücke | ein offener Auftrag je Platz, der neueste gilt |

## 10. Tests

- Platz-Erkennung und Pixelmaße für feste Layouts (1/2/3 Spalten, Abstände);
  Platzhalter = leer, echtes Bild = belegt.
- DB: Anlegen, Vergabe, Ablauf nach 10 min, ein offener je Platz, Einsetzen auf
  neuerer Fassung (frei vs. belegt), freigegeben → abgelehnt. Live-DB nur mit
  `--single-transaction` + ROLLBACK.
- API: falscher Schlüssel 401, Dateiprüfung, Dateiname ohne Pfadtricks.
- Arbeiter mit nachgebautem ComfyUI/Ollama: Ablauf, Wiederholungen,
  Speicherfreigabe.
- **Echter Lauf am PC:** ein Bild mit FLUX, Dauer und Grafikspeicher gemessen.
- Jede neue Vorlage: DB-Prüfung + MJML-Render, HTML als Datei.
- Editor: bestehende Paket-Tests, neu Abschnitt einfügen und Bildfeld.
- Browser-Durchlauf: Neu aus Vorlage → automatisch gefüllt → im Pult sichtbar →
  ein Platz mit Hinweis neu → Freigabe.

## 11. Nicht Teil dieser Spec

„Vorlage aus Vorbild" und die übrigen Block-Werkzeuge des Agenten (E2);
Versand und öffentliche Bildadressen (Pult-Stufe 3); Bilder für Posts und
Material; Logo-Gestaltung; freies Umordnen am Handy.
