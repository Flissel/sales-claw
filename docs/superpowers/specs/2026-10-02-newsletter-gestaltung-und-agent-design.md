# Newsletter: Gestaltungsfläche und Gestaltungs-Agent (Bausteine C + D)

Stand: 02.10.2026 · Status: Entwurf zur Freigabe durch den Betreiber
Repos: sales-claw (`feat/stufe-1-fundament`) und vibemind-os (`spaces/marketing`, master)
Vorgänger: Baustein A (`2026-10-01-newsletter-vorlagen-profi-design.md`, §9 Anforderungen an D),
Baustein B (`2026-10-02-newsletter-bild-freistellen-design.md`)

## 0. Worum es geht

Der Betreiber will einen **Baukasten wie Framer**: Bilder (auch freigestellte) und Texte frei auf
eine Fläche legen, per Drag verschieben, per Scrollrad skalieren – und einen **Agenten im Chat**,
der den ganzen Newsletter bedient, „damit die Seite schön bleibt“ (Chat statt Knöpfe).

Betreiber-Entscheide (02.10.):
- **C und D zusammen** in einem Baustein (eine Spec; der Plan hat zwei Teile, ausgeliefert wird erst gemeinsam).
- Fläche trägt **Bilder + Text** (keine Formen).
- **Feste Formate**: Quer 3:2, Quadrat 1:1, Hoch 4:5, Banner 3:1.
- **Flachrechnen auf dem Server mit Pillow** (Ebenen bleiben als Daten bearbeitbar; Agent braucht keinen Browser).
- Editorfenster **wie Framer** (Ebenen links, Fläche Mitte, Eigenschaften + Chat rechts).
- Agent-Modell: **Claude über den Marketing-Shim :8117 am PC** (Abo, kein API-Budget).
- Agent bearbeitet den **ganzen Newsletter**, nicht nur Flächen.
- **Export: beides** (Newsletter je Gerät + Flächen je Geräteformat) – **nur nach ausdrücklicher
  Bestätigung im Editor**. Nichts landet von selbst in den Medien („damit nicht Müll in Sales landet“).
- **„Von Anfang an schön“**: Gestaltungsqualität ist Abnahmekriterium, nicht Nacharbeit.

Feste Grenzen: Kein Modell auf der VM (Proxmox-Mini-PC hält nur DB/API/Dateien). Pillow ist kein
Modell und läuft auf der VM wie die Tech-Grafiken aus A. Claude und Playwright laufen am PC.

## 1. Datenmodell: Fläche = Image-Block mit Ebenen

**Kein neuer Blocktyp.** Eine Gestaltungsfläche ist ein `Image`-Block mit `props.gestaltung`.
`props.url` zeigt auf das flachgerechnete Bild. Renderer, Validator, Bildplätze, Löschsperre,
Schwarz-Weiß-Auslieferung und Handy-Darstellung bleiben unverändert gültig.

```
Image-Block
  props.url          = "medien:gs-<hash12>.jpg"
  props.width/height = 600 × (600 / Seitenverhältnis), gerundet
  props.alt          = vom Betreiber/Agenten gesetzter Alternativtext (Pflicht, ≤ 200 Zeichen)
  props.gestaltung   = {
    version: 1,
    format: "quer" | "quadrat" | "hoch" | "banner",        // 3:2 | 1:1 | 4:5 | 3:1
    hintergrund: "#RRGGBB",                                  // Vorgabe: Layout-Fläche
    ebenen: [ ≤ 20, unterste zuerst; je Ebene eindeutige id (≤ 32 Zeichen [A-Za-z0-9_-]) ]
  }
Bild-Ebene: { id, art: "bild", quelle: "medien:<datei>", x, y, breite, drehung }
Text-Ebene: { id, art: "text", text, schrift, gewicht, kursiv, groesse, farbe,
              ausrichtung: "links"|"mitte"|"rechts", zeilenabstand, x, y, drehung }
```

- Koordinaten in der **600er-Newslettereinheit** (Fläche 600 × H). `x, y` = Mittelpunkt der
  Ebene; `breite` (Bild) in Einheiten, Höhe folgt dem Bildverhältnis; `drehung` in Grad −180…180.
  Ebenen dürfen über den Rand ragen (Anschnitt ist ein Gestaltungsmittel).
- Text: Umbruch **nur** an `\n` (keine automatische Umbrechung), ≤ 200 Zeichen, ≤ 6 Zeilen;
  `schrift` ∈ die 11 Vorlagenschrift-IDs aus A, `gewicht`/`kursiv` nur in den vorhandenen Schnitten;
  `groesse` 10–160; `farbe` `#RRGGBB`; `zeilenabstand` 0,8–2,0.
- Validierung an drei Stellen mit gleichen Regeln: zod im Editor, Python in `claw/gestaltung.py`,
  SQL-Grobprüfung in `pult_bloecke_fehler` (Migration 060: `gestaltung` muss Objekt mit
  `version`=1, gültigem `format`, ≤ 20 Ebenen sein; Feinprüfung macht Python vor dem Rechnen).
- Bildplätze: `bildplaetze.finde` überspringt Blöcke mit `gestaltung` (sonst überschriebe FLUX die
  Komposition); der Editor zeigt dort weder Freistellen noch Neu/Überarbeiten.

## 2. Medien: Entwurfsbilder vs. Export

- Flachgerechnete Bilder heißen `gs-<hash12>.jpg` (hash = sha256 über die kanonische JSON-Form von
  `gestaltung` + Renderer-Version) und liegen in `MARKETING_BILD_ORDNER`. Gleiche Gestaltung ⇒
  gleiche Datei (Doppelklick erzeugt nichts doppelt).
- **Entwurfsbilder sind unsichtbar**: Medienbibliothek, Editor-Kacheln und Bildauswahl blenden
  `gs-*` aus. Aufräumen: `gs-*` ohne Verweis aus irgendeiner Fassung und älter als 7 Tage wird
  gelöscht (gleiche Verweisprüfung wie die Löschsperre; läuft beim Rechnen nebenbei, höchstens
  einmal je Stunde).
- **Sichtbar wird nur, was exportiert ist** (§6).

## 3. Editorfenster (Framer-Stil)

Ein Klick auf eine Gestaltungsfläche oder „+ Gestaltungsfläche“ (Blockauswahl) öffnet ein
Vollbildfenster:

- **Kopfleiste**: „← Zurück zum Newsletter“, Format-Auswahl, Hintergrundfarbe, „Exportieren…“.
- **Links – Ebenen**: Liste (oberste zuerst), Drag zum Umsortieren, Auge/Löschen je Ebene;
  „+ Bild“ (Medienbibliothek, freigestellte Bilder zuerst), „+ Text“ (Vorlagenschrift des Newsletters).
- **Mitte – Fläche**: auf Fensterhöhe gezoomt; Auswahl mit Rahmen und Griffen.
  Ziehen = verschieben; **Scrollrad = Größe** der ausgewählten Ebene; **Shift+Scroll = Drehung**;
  Pfeiltasten 1 px, Shift 10 px; Entf löscht; Doppelklick auf Text bearbeitet direkt.
  Einrasten an Mitte und Rändern der Fläche und anderer Ebenen mit Hilfslinien.
  Hinweise unter der Fläche (Handy-Warnung, Kontrast, Anschnitt).
- **Rechts – Eigenschaften** der Auswahl (Schrift, Schnitt, Größe, Farbe mit Ladenfarben als
  Vorschlag, Ausrichtung, Zeilenabstand, Drehung, Position), darunter **Chat** (§4).
- Rückgängig/Wiederholen (Strg+Z / Strg+Y) innerhalb der Sitzung.
- „Zurück zum Newsletter“ speichert: Server rechnet (§5), neue Fassung, Editor zeigt das Serverbild.

**Schön von Anfang an** (Abnahmekriterium): dunkles ruhiges Gerüst (die Fläche ist das Hellste
am Schirm), 8-px-Raster, eine UI-Schrift, weiche Übergänge (≤ 150 ms), klare Griffe, sichtbarer
Fokus, keine Layout-Sprünge beim Auswählen. Fläche und Vorschau zeigen dieselben Schriften
(selbst ausgelieferte WOFF2 aus A).

Der **Chat steht auch im normalen Newsletter-Editor** (rechte Seitenleiste, unter den Block-
Eigenschaften einklappbar).

## 4. Gestaltungs-Agent

### 4.1 Ablauf
1. Editor: `POST /marketing/editor/{iid}/chat {nachricht, kontext}` – `kontext` = offenes Fenster
   (`newsletter` | `flaeche:<block-id>`) und Auswahl (Block-/Ebenen-id).
2. sales-ui → Pult-API `POST /api/pult/inhalte/{iid}/chat`: legt `marketing.chat_auftraege` an
   (Migration 060: id, inhalt, mandant, nachricht ≤ 2000 Zeichen, kontext jsonb, status
   `offen|in_arbeit|fertig|fehler`, antwort, aenderungen jsonb, fassung_vorher, fassung_nachher,
   vergeben_bis, erstellt_am) und **sperrt den Newsletter** (ein offener/in-Arbeit-Auftrag je
   Inhalt; Handspeichern antwortet 409 „Der Assistent arbeitet gerade“).
   `GET …/chat` liefert Verlauf + Stand; der Editor fragt alle 2 s, solange etwas offen ist.
3. **Chat-Arbeiter am PC** (`workers/chat_worker.py`, Gesundheitsport **8134**, Start über
   `marketing-dienste-starten.ps1`, gleicher Schlüssel-/Routenstil wie der Bild-Arbeiter unter
   `/api/marketing/chat_arbeiter/…`): holt Auftrag + aktuelle Fassung + Layoutfarben + Schriften +
   Medienliste (ohne `gs-*`) + letzte 10 Chatnachrichten; fragt Claude über `http://127.0.0.1:8117/v1`
   (OpenAI-kompatibel, ohne tool_calls); erwartet **genau ein JSON** `{antwort, aenderungen:[…]}`.
4. Arbeiter prüft jede Änderung gegen das Werkzeug-Schema (§4.2) und wendet sie auf eine Kopie der
   Blöcke an. Ungültig ⇒ **ein** Korrekturversuch mit der Fehlermeldung; danach `fehler` mit
   „Das habe ich nicht umsetzen können: <Grund>“.
5. Arbeiter schickt `{antwort, bloecke, notiz}` an `…/fertig`. VM: `pult_bloecke_fehler`,
   geänderte Flächen rechnen (§5), **neue Fassung mit Urheber `agent`**, Sperre fällt.
6. Editor zeigt Antwort + „Rückgängig“ (legt die vorige Fassung als neue Fassung wieder an –
   nichts wird gelöscht) und lädt die Fassung.

### 4.2 Werkzeuge (Änderungsarten)
| Bereich | Werkzeug | Kern-Parameter |
|---|---|---|
| Newsletter | `block_einfuegen` | typ, nach (Block-id), daten |
| | `block_aendern` | id, props/style (Teilmenge) |
| | `block_verschieben` | id, nach |
| | `block_loeschen` | id |
| | `farben_setzen` | Rolle → Farbe (nur aus Ladenfarben oder abgeleiteten Tönen) |
| Fläche | `flaeche_anlegen` | nach, format, hintergrund |
| | `ebene_hinzufuegen` / `ebene_aendern` / `ebene_loeschen` | flaeche, ebene (§1) |
| | `ebene_reihenfolge` | flaeche, ids (unten → oben) |
| | `format_setzen` / `hintergrund_setzen` | flaeche, wert |
| Bilder | `bild_erzeugen` | platz, hinweis (Bild-Arbeiter-Auftrag `neu`) |
| | `bild_freistellen` | platz (Auftrag `freistellen`) |
| | `bild_aus_medien` | platz oder flaeche+ebene, quelle |
| Abschluss | `entwurf_speichern` | notiz (Fassung mit Notiz) |
| | `export_vorschlagen` | was (§6) – **nur Vorschlag**: Editor zeigt Knopf, Agent exportiert nie selbst |

Bildaufträge laufen über den bestehenden Bild-Arbeiter; der Agent meldet „Bild wird erzeugt –
kommt als neue Fassung“ und wartet nicht.

### 4.3 Gestaltungsregeln im Systemprompt (schön von Anfang an)
Hierarchie (eine dominante Aussage je Fläche), großzügiger Weißraum, höchstens zwei Schriften
(Vorlagenpaar), Farben nur aus Ladenfarben, Text auf Bild nur mit ausreichendem Kontrast, Handy
zuerst denken (Text ≥ 22 Einheiten auf Flächen), kurze Texte. Nach dem Anwenden läuft die
bestehende **Schönheitsprüfung** (`claw/schoenheit.py`) über die Fassung; Befunde gehen als
Hinweis in die Chatantwort, blockieren aber nur, wo `schoenheit` heute schon blockiert.

### 4.4 Fehlerfälle
| Fall | Verhalten |
|---|---|
| Shim antwortet nicht | Wiederholen bis 3 min, dann `fehler` „Der Assistent ist gerade nicht erreichbar“, Sperre fällt |
| PC aus (kein Abholen in 2 min) | `fehler` „Der Assistent läuft am PC und ist gerade aus“, Sperre fällt |
| Vergabe läuft ab (5 min) | Auftrag zurück auf `offen` (einmal), danach `fehler` |
| Antwort kein gültiges JSON / ungültige Änderung | ein Korrekturversuch, dann `fehler` mit Grund |
| Validator lehnt Blöcke ab | `fehler` mit Validator-Grund, keine Fassung |
| Fassung inzwischen geändert | nicht möglich (Sperre); falls doch: `fehler` „Newsletter wurde inzwischen geändert“ |

## 5. Flachrechnen (VM, Pillow)

`claw/gestaltung.py`:
- Leinwand **1200 px** breit × Höhe aus Format (Faktor 2 zur 600er-Einheit), Hintergrund füllen.
- Bild-Ebene: Datei aus `MARKETING_MEDIEN_ORDNER` / `MARKETING_BILD_ORDNER` (gleiche Auflösung wie
  `pult_bild_datei_fehler`), LANCZOS skalieren, mit Alpha drehen (`expand=True`), mittig auf (x, y)
  einsetzen.
- Text-Ebene: eigene RGBA-Ebene, Zeilen mit `ImageFont.truetype(<woff2>, groesse×2)`, Ausrichtung,
  Zeilenabstand, dann drehen und einsetzen.
- Ausgabe JPEG Qualität 88, ≤ 1 MB (sonst Qualität in 6er-Schritten bis 64, danach Fehler).
- **Schriften**: die 22 WOFF2-Dateien kommen nach `spaces/marketing/claw/schriften/`; ein Test
  vergleicht ihre sha256 mit `sales-claw/sales-mcp/static/schriften/` (SALES_CLAW_DIR).
- **Hinweise** (keine Fehler): Ebene zu > 15 % außerhalb; Text < 22 Einheiten („am Handy unter
  12 px“); Kontrast Text gegen mittleren Untergrund < 3:1.
- Route `POST /api/pult/inhalte/{iid}/gestaltung {block, gestaltung}` → `{url, width, height, hinweise}`.
  422 mit Grund bei fehlender Quelle, unbekannter Schrift, ungültiger Gestaltung.
- Editor-Vorschau: DOM mit denselben Schriften und derselben Mathematik (Ebenenmitte, Drehung um
  die Mitte, Skalierung). Nach dem Speichern zeigt der Editor das Serverbild.

## 6. Export (nur nach Bestätigung)

- „Exportieren…“ (Kopfleiste oder Knopf aus `export_vorschlagen`) öffnet einen Dialog:
  Auswahl **Newsletter** (Handy 375 / Tablet 768 / PC 1200 px Breite, ganze Länge) und/oder
  **Flächen** (je Fläche Handy 4:5, Tablet 1:1, PC 3:2), Dateinamen-Vorschau
  (`<titel-slug>-<gerät>.jpg`, `<titel-slug>-<flaeche>-<gerät>.jpg`), Knopf „In Medien exportieren“.
- Flächen in anderen Formaten: Ebenen werden **neu angeordnet, nicht beschnitten** – Positionen
  relativ zur Flächenmitte, Größen nach der kürzeren Seite skaliert; der Dialog zeigt die drei
  Varianten als Vorschau (vom Server gerechnet), der Betreiber kann sie im Fenster nachziehen.
- Newsletter-Bilder: Export-Auftrag in derselben Warteschlange (`art = export`); der **PC-Arbeiter**
  rendert das HTML aus dem bestehenden Renderer mit **Playwright** in den drei Breiten (volle Höhe,
  JPEG ≤ 4 MB, sonst Qualität senken) und lädt sie hoch. Kein Browser auf der VM.
- Exportierte Dateien liegen sichtbar in den Medien; bestehende Namen bekommen `-2`, `-3` …

## 7. Tests und Abnahme

- Python (`gestaltung.py`): Pixelproben an festen Stellen für Bild/Text/Drehung/Alpha,
  Schriftgröße, Hash-Stabilität, Formate, Hinweise, alle 422-Fälle, Schrift-Gleichstand mit sales-claw.
- Migration 060: Probe mit ROLLBACK + `verify_060.sql` (Grobprüfung `gestaltung`, Chat-Tabelle,
  Sperre, Ablauf).
- Chat-Arbeiter mit gefälschtem Shim: gültige Antwort, ungültiges JSON, ungültiges Werkzeug +
  Korrekturversuch, jedes Werkzeug einmal, Sperre/Ablauf/PC-aus, Export-Auftrag mit gefälschtem Browser.
- API: Chat-Routen, Sperre (409 beim Handspeichern), Rückgängig, Gestaltungs-Route.
- sales-ui: Chat-/Export-Durchreichung, `gs-*` ausgeblendet in Medienliste und Bildauswahl.
- Editor (vitest): Zoom-/Koordinaten-Mathematik, Scroll-Skalierung, Einrasten, Ebenenliste,
  Rückgängig, Handy-Warnung, zod-Schema; Paket-Test; `tsc --noEmit` im Paketordner.
- **Echter Lauf**: Fläche von Hand bauen (freigestellte Person + Titel); dieselbe per Chat bauen
  lassen; Newsletter per Chat umformulieren und Rückgängig; Export bestätigen und in den Medien ansehen.
  Bildschirmfotos des Fensters gehen zur Sichtabnahme an den Betreiber („schön“ ist Kriterium).

## 8. Nicht in diesem Baustein

Formen/Flächen als Ebenen, automatischer Textumbruch, Animationen, gleichzeitiges Bearbeiten durch
mehrere Personen, Spracheingabe, Agent ohne PC (Modell auf der VM ist ausgeschlossen).
