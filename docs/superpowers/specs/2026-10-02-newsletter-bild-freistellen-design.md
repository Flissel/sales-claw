# Newsletter-Bilder freistellen (Baustein B)

Stand: 02.10.2026 · Status: Entwurf zur Freigabe durch den Betreiber
Repos: sales-claw (`feat/stufe-1-fundament`) und vibemind-os (`spaces/marketing`, master)
Vorgänger: Baustein A (`2026-10-01-newsletter-vorlagen-profi-design.md`), Bilder überarbeiten (`2026-09-30-newsletter-bild-ueberarbeiten-design.md`)

## 0. Worum es geht

Der Betreiber will „auf einem Bild nur die Person zeigen“ – cleveres Ausschneiden wie in
Photoshop. Ein Klick im Editor stellt das Hauptmotiv eines Bildplatzes frei; das Ergebnis ist
ein PNG mit Transparenz.

Betreiber-Entscheide (02.10.):
- **Ergebnis: beides.** Das freigestellte Bild ersetzt das Bild im Bildplatz (neue Fassung) und
  liegt als eigene Datei in den Medien – für andere Newsletter und später die freie
  Gestaltungsfläche (Baustein C). Das Original bleibt; Rückweg über die vorige Fassung.
- **Auswahl: automatisch das Hauptmotiv** (BiRefNet). Keine Text-Auswahl („nur die Frau
  links“) in diesem Baustein.
- **Kein Modell auf der VM**: Freistellen läuft im Bild-Arbeiter am PC über ComfyUI.

## 1. Modell

- ComfyUI (`E:\ComfyUI`, Stand 23.06.2026) bringt eingebaute Knoten mit:
  `LoadBackgroundRemovalModel` (Ordner `background_removal`) und `RemoveBackground`
  (liefert eine Maske). Der Lader erkennt BiRefNet am Schlüssel
  `bb.layers.1.blocks.0.attn.relative_position_index`.
- Datei: `model.safetensors` aus `ZhengPeng7/BiRefNet` (MIT-Lizenz, ≈ 0,9 GB), abgelegt als
  `C:\ComfyUI-Modelle\background_removal\birefnet.safetensors` (SSD). `E:\ComfyUI\extra_model_paths.yaml`
  bekommt `background_removal: background_removal/` im Abschnitt `ssd_flux`.
- Einmaliger Download am PC; nie auf der VM.

## 2. Ablauf

1. **Editor:** Im Bild-Panel eines Bildplatzes, der ein echtes Bild trägt (kein Platzhalter,
   keine erzeugte Grafik), steht der Knopf **„Freistellen“**. Er schickt
   `POST /marketing/editor/{iid}/bild` mit `freistellen: true` (statt Stärke/neu).
2. **sales-ui → Pult-API:** Auftrag mit `modus = 'freistellen'` für genau diesen Platz.
3. **DB (Migration 059):** `bild_auftraege.modus` erlaubt `freistellen`;
   `pult_bild_auftrag` nimmt den Modus an (Stärke bleibt bedeutungslos, 0 gespeichert).
4. **Bild-Arbeiter (PC):** holt den Auftrag; für `freistellen`: Quelle über die bestehende Route
   (`/arbeiter/{aid}/quelle`, normalisiert wie beim Überarbeiten), ComfyUI-Ablauf
   `bilder/freistellen_api.json`: LoadImage → LoadBackgroundRemovalModel(`birefnet.safetensors`)
   → RemoveBackground → JoinImageWithAlpha → SaveImage (PNG). Ergebnis in **Originalgröße**
   (kein Zuschnitt – der Bildplatz behält sein Seitenverhältnis). Kein Sehmodell, kein Prompt,
   kein FLUX.
5. **Qualitätsregel:** Anteil der Vordergrundpixel (Alpha > 128) < 2 % oder > 98 % ⇒ kein
   klares Motiv: Auftrag `zurueck` mit Befund „Kein klares Motiv gefunden“, Bildplatz bleibt.
6. **Ablage:** Upload über die bestehende Route `/arbeiter/{aid}/bild?platz=…`, die zusätzlich
   PNG annimmt (§3). Dateiname `nl-<auftrag8>-<platz>-frei.png` in `MARKETING_BILD_ORDNER`
   (media-erzeugt) – erscheint damit in der Medienbibliothek.
7. **Einsetzen:** `fertig` wie bisher; der Platz bekommt `medien:nl-<auftrag8>-<platz>-frei.png`
   als neue Fassung (Urheber agent). Der Editor lädt die neue Fassung von selbst (bestehender
   Mechanismus).

## 3. Upload-Route: PNG

- `arbeiter_bild` prüft heute nur JPEG (`_jpeg_pruefen`, ≤ 1 MB, Name `.jpg`).
- Neu: Anfrage-Parameter `format=png` (Standard `jpg`). Für PNG: Signatur `\x89PNG`, mit
  Pillow lesbar, Modus mit Alpha (`RGBA`/`LA`), ≤ 4 MB; Name `nl-<auftrag8>-<platz>-frei.png`.
  JPEG-Weg unverändert.
- `pult_bild_datei_fehler` und Löschsperre greifen unverändert (Dateiname im Platz).

## 4. Darstellung

- Renderer: unverändert – ein PNG mit Transparenz steht auf der Fläche des Blocks bzw. Abschnitts.
- **Schwarz-Weiß-Auslieferung** (sales-ui `?sw=1`) erhält künftig den Alphakanal (Graustufen
  `LA` für Bilder mit Transparenz, PNG bleibt PNG). Behebt den aufgeschobenen Befund aus Baustein A.
- Die Medienbibliothek zeigt die freigestellte Datei wie jede andere (Kachel); Löschen mit der
  bestehenden Sperre.

## 5. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Modelldatei fehlt / ComfyUI meldet Fehler | Auftrag `zurueck` mit Befund „Freistellen nicht verfügbar: …“; Platz bleibt |
| Quelle fehlt oder unlesbar | wie beim Überarbeiten: Befund, Platz bleibt |
| kein klares Motiv (§2.5) | Befund „Kein klares Motiv gefunden“ |
| PNG > 4 MB | Arbeiter verkleinert vor dem Upload auf längste Kante 1600 px; danach noch zu groß ⇒ Befund |
| Platz ist Platzhalter oder Grafik | Knopf erscheint nicht; API lehnt mit 422 ab |

## 6. Tests und Abnahme

- Arbeiter: Freistell-Zweig mit gefälschtem ComfyUI (Ablauf-JSON gefüllt, PNG mit Alpha
  zurück), Qualitätsregel (leer / voll / normal), Fehler ⇒ zurück.
- API: PNG-Upload (gültig, kein Alpha, zu groß, falsche Signatur), Name `-frei.png`, JPEG
  unverändert; Auftrag mit `modus=freistellen`.
- Migration 059: Probe mit ROLLBACK + `verify_059.sql`.
- sales-ui: `freistellen: true` erzeugt den richtigen Auftrag; Platzhalter-Platz ⇒ 422;
  `?sw=1` behält Alpha.
- Editor: Knopf nur bei echtem Bild; Paket-Test.
- **Echter Lauf:** ein hochgeladenes Personenfoto und ein FLUX-Bild freistellen, Ergebnis ansehen.

## 7. Nicht in diesem Baustein

Text-gesteuerte Auswahl (GroundingDINO + SAM), Kanten nachbearbeiten (Weichzeichnen, Rand,
Schatten), Freistellen von Container-Hintergründen, Agent-Werkzeug (Baustein D),
freie Platzierung (Baustein C).
