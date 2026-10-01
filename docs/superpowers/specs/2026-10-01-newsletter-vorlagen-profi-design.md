# Newsletter-Vorlagen in Profi-Qualität (Baustein A)

Stand: 01.10.2026 · Status: Entwurf zur Freigabe durch den Betreiber
Repos: sales-claw (`feat/stufe-1-fundament`) und vibemind-os (`spaces/marketing`, master)

## 0. Worum es geht

Der Betreiber: „Die Newsletter sehen noch kacke aus.“ Die fünf heutigen Startvorlagen sind
alle im dunklen VibeMind-Grün fest verdrahtet, die Bilder versinken im Hintergrund, es gibt
keinen Masthead, nur einen Größensprung in der Typografie, und der Fuß geht unter.

Ziel von Baustein A: **sieben Vorlagen**, die so hochwertig wirken wie gute Canva-/Framer-
Vorlagen, die **Läden in sales-claw** an ihre Kunden schicken. Jede Vorlage hat ihren eigenen
Charakter (Aufbau + Schriftpaar); **Logo und Farben kommen vom Laden**.

Dieser Entwurf ist Teil einer Reihe (Betreiber-Entscheid 01.10., Reihenfolge A → B → C → D):

| | Baustein | In diesem Entwurf? |
|---|---|---|
| **A** | Vorlagen aus dem Musterkatalog, Ladenmarke automatisch | **ja** |
| B | Freistellen („nur die Person“), Auftrag im Bild-Arbeiter am PC | nein – eigener Entwurf |
| C | Freie Gestaltungsfläche (Drag & Drop, Größe per Scrollrad, wird beim Speichern zu einem Bild) | nein – eigener Entwurf |
| D | Agent bedient den Baukasten per Chat (Vorbild: Framer-Agent) | nein – eigener Entwurf; Anforderungen in §9 festgehalten |

Erfolg heißt: Ein Laden wählt eine der sieben Vorlagen, bekommt sofort einen Newsletter in
seinen Farben und mit seinem Logo, die Bildplätze werden passend gefüllt, und das Ergebnis
besteht neben einer guten Canva-Vorlage – am PC wie am Handy, in Gmail (mit Ersatzschriften)
wie in Apple Mail.

## 1. Vorbilder und Rechte

Untersucht wurden sieben öffentliche Canva-Vorlagen-Vorschauen (Beige Aesthetic Business
Studio, Orange and Cream Modern Company, Blue and Yellow Minimalist Business, Black and White
Minimal Elegant Business Tech, White and Brown Minimalist Photo Grid, Brown and Grey
Entrepreneur Email, Small Businesses Corporate Brown) sowie die Framer-Seite „AETHER / AI“
des Betreibers (Design-Spezifikation vom 01.10., Werte aus dem Framer-Eigenschaftenfeld).

**Keine Vorlage wird kopiert.** Canva-Vorlagen sind urheberrechtlich geschützt und dürfen laut
Nutzungsbedingungen nur in Canva verwendet werden; Massendownload ist untersagt. Übernommen
werden nur Gestaltungsmuster (Masthead-Typen, Abschnittstypen, Schriftpaarungen, Farbrollen),
die selbst nicht geschützt sind. Die Referenz-Screenshots bleiben Arbeitsmaterial auf dem PC
und gehen in kein Repo. Die Framer-Seite gehört dem Betreiber.

## 2. Musterkatalog (Ergebnis der Analyse)

**Masthead-Typen** – der stärkste Hebel:

| | Masthead | Vorbild |
|---|---|---|
| M1 | Schmale Leiste: Ausgabe links, Wortmarke in gesperrten Versalien mittig, Zeichen rechts, Haarlinie | Beige Studio |
| M2 | Riesiger Serifentitel in Akzentfarbe zwischen zwei Linien, Marke + Handle darüber | Orange & Cream |
| M3 | Farbblock mit großem Titel (Serife mit kursiven Wörtern), Datum/Ausgabe, Kontaktleiste darunter | Blue & Yellow, Harvest Herald |
| M4 | Riesiger dünner Grotesk-Titel über volle Breite, Linkzeile, fast schwarz-weiß | The Insights |
| M5 | Zentriert: Ausgabezeile mit Akzentbalken, kursive Didone, gesperrte Versal-Unterzeile | The Clippers |
| M6 | Foto als Kopf mit halbtransparentem Farbfeld, Titel darauf | Business Newsletter |
| M7 | Dunkel, Wortmarke + Lichtschein, Pill mit Punkt, nummerierte Dachzeilen | AETHER / AI (Framer) |

**Wiederkehrend:** geteilter Kopf (Foto | Überschrift), Überschrift links + Text rechts,
Fotostreifen aus drei Bildern, „Lernt das Team kennen“, Farbblock mit weißer Versal-Überschrift,
„In dieser Ausgabe“-Kasten, Tipp-Liste auf getöntem Feld, Zitat mit Pfeilsymbol, Fußband.
**Typografie:** immer ein Kontrastpaar (Anzeige-Schrift + Text-Schrift) und Meta-Text in kleinen,
weit gesperrten Versalien. **Farbe:** höchstens drei Rollen; ruhiger Grund, ein Akzent, optional
eine Zweitfarbe oder Tönung. **Raum:** breite Ränder, Haarlinien statt Kästen.

## 3. Die sieben Vorlagen

| Name | Masthead | Grund (fest) | Schriften (Anzeige / Text) | Kennzeichen |
|---|---|---|---|---|
| studio | M1 | Off-White `#faf7f2` | Cormorant Garamond / DM Sans | geteilter Kopf, Fotostreifen, Haarlinien |
| zeitung | M2 | Creme `#f8f1e6` | Playfair Display (900) / Poppins | Leitband, Farbblöcke, **Fotos schwarz-weiß** |
| firmenblatt | M3 | Weiß | Young Serif / Poppins | Kopf in Zweitfarbe, Kontaktleiste, Rubriken, getöntes Feld |
| minimal | M4 | Warmgrau `#f4f3ef` | Manrope (300/400/700) | Linkzeile, dünner Riesentitel, Akzent nur im Pfeil |
| klassik | M5 | Weiß | Bodoni Moda (kursiv) / Montserrat | zentriert, Bildreihe, Autorzeile, Fußband |
| bildkopf | M6 | Hellgrau `#efecea` | Josefin Sans (300/700) | Hintergrundbild-Kopf mit Farbfeld, Farbspalte, Tipp-Kasten |
| tech | M7 | Ink `#080B13` | Oxanium / Rajdhani | Lichtschein, Pill, nummerierte Dachzeilen, Signal-Grafik, Karten |

Gemeinsamer Inhaltsaufbau: Masthead · Hauptthema mit Bild · zwei Nebenthemen · Aktion/Angebot ·
Abschluss mit einem Knopf · Fuß. Platzhaltertexte sind für Läden geschrieben (nicht für VibeMind)
und als Platzhalter erkennbar. Alle Schriften stehen unter der SIL Open Font License.

### 3.1 „tech“ nach der Framer-Analyse

Feste Töne: Ink `#080B13` (Grund), Surface `#111725` (Karten, Kontaktblock), Line `#263044`
(Haarlinien, Kartenrahmen), Text `#F3F7FC`, Text leise `#9CAABE`. Der Akzent („Signal“, im
Original `#B5F750`) kommt vom Laden; die gedämpften Rahmen- und Ringtöne (Original `#49623D`,
`#668B63`, `#84B970`, `#365244`) werden aus dem Ladenakzent gemischt (Akzent mit Ink).

E-Mail-Fassung nach den Phone-Werten der Analyse: Ränder 32 px, H1 40 px (Oxanium 600,
Laufweite −1 px), H2 34 px (−1 px), Kartentitel 24 px, Dachzeile 12 px (+2 px, Versalien,
Akzent), Fließtext Rajdhani 500 20/29 px, Abschnitte 72 px oben/unten. Karten untereinander
(Surface, 1 px Line, Radius 12, Innenabstand 28). Knopf Akzent, Text Ink, Radius 8, Pfeil
„↗“ als Zeichen. Pill als Zelle mit 1-px-Rahmen und „●“ in Akzent. Navigation entfällt
(Anker sind in E-Mail unzuverlässig), Wortmarke bleibt. Signal-Grafik (Ringe 280/190 px,
Kern 100 px, Halo-Verlauf) und Lichtschein im Kopf werden als Bilder im Ladenakzent erzeugt
(§6), mit Ink als Ausweichfarbe. Dark-Mode: `color-scheme`-Meta und Hintergrundfarbe an
jeder Zelle.

## 4. Neue Gestaltungsmittel im Blockformat

Ansatz (Betreiber-Entscheid): **echte Felder im Blockformat**, die Editor, DB-Prüfung und
Renderer gleich verstehen – damit sie den Editor überleben (die Editor-Schemata verwerfen heute
unbekannte Felder beim Bearbeiten stillschweigend) und der Agent (Baustein D) sie später per
Werkzeug setzen kann.

| Feld | Blöcke | Werte | Wirkung |
|---|---|---|---|
| `style.fontFamily` | Heading, Text, Button | bisherige 9 Schlüssel **+ `ANZEIGE`, `TEXT`** | Rolle → Schriftpaar der Vorlage aus `root.data.schriften` |
| `style.letterSpacing` | Heading, Text | Zahl −2 … 8 (px) | Laufweite (Meta, Dachzeilen, enge Titel) |
| `style.textTransform` | Heading, Text | `none` \| `uppercase` | Versalien |
| `style.lineHeight` | Heading, Text | Zahl 0,9 … 2,0 | Zeilenhöhe |
| `props.text` mit `*kursiv*` | Heading | Markdown-Kursiv (nur Kursiv) | „Herbst*brief*“, „Der *Radhaus* Rundbrief“ |
| `props.url` + `props.width`/`props.height` | Container | `medien:<datei>`, 600 × 120–600 | Hintergrundbild des Abschnitts – derselbe Ort wie beim Bildblock, damit Bildplatz-Logik, Arbeiter, Quelle und Löschsperre unverändert greifen |
| `style.overlay` | Container | `{farbe: "#hex", deckkraft: 0–100}` | halbtransparentes Farbfeld über dem Bild (Outlook: Vollfarbe) |
| `props.grafik` | Image, Container | true/false | erzeugte Grafik (§6), kein Bildplatz für den Arbeiter |
| `props.sw` | Image | true/false | Auslieferung in Graustufen |
| `root.data.schriften` | EmailLayout | `{anzeige: <id>, text: <id>}` | Schriftpaar der Vorlage |
| `root.data.dunkel` | EmailLayout | true/false | Dark-Mode-Metadaten (tech) |

**Schriften:** Die OFL-Dateien (woff2) liegen in sales-claw und werden von sales-ui unter
`/marketing/schrift/<datei>` öffentlich ausgeliefert (wie die signierten Bilder ohne Anmeldung,
aber ohne Token – Schriften sind nicht geheim). **Kein Google Fonts**: das gäbe die IP-Adresse
jedes Empfängers an Google weiter (DSGVO). Jede Schrift-ID trägt ihren Ersatzstapel (Serifen →
Georgia, Grotesk → Arial/Helvetica, Rajdhani → „Arial Narrow“, Arial). Gmail und Outlook
(Windows) zeigen die Ersatzschrift; der Aufbau bleibt.

**Logo:** Bildblock mit `medien:logo-<laden>-<prüfsumme>.png` (siehe §5).

## 5. Ladenmarke und „Neu aus Vorlage“

1. Vorlagen enthalten **Farbrollen** statt Hexwerten: `{akzent}`, `{zweit}`, `{akzent_hell}`,
   `{auf_akzent}`, `{auf_zweit}`, `{akzent_text}`, dazu für tech `{akzent_ring1}`, `{akzent_ring2}`,
   `{akzent_rahmen}`. Neutrale Töne und Gründe stehen fest in der Vorlage.
2. Die Marketing-API füllt die Rollen beim Anlegen aus dem **Standard-Newsletter-Layout des
   Ladens** (`marketing.layout_vorlagen`, `standard = true`, `inhaltsart = 'newsletter'`):
   - `akzent` ← `gestalt.akzent`
   - `zweit` ← `gestalt.flaeche`; ist sie zu hell (Kontrast zu Weiß < 3:1) oder fehlt sie,
     wird ein dunkler Ton des Akzents berechnet
   - `akzent_hell` = Akzent zu 10 % auf Weiß (Tönung für Felder)
   - `auf_akzent` / `auf_zweit` = Weiß oder `#1a1a1a`, was den höheren Kontrast hat
   - `akzent_text` = Akzent, falls Kontrast zum Vorlagengrund ≥ 4,5:1, sonst schrittweise
     abgedunkelt bis 4,5:1 (gelbe Akzente bleiben als Text lesbar)
   - tech: Ring-/Rahmentöne = Akzent mit Ink gemischt (25 %, 40 %, 55 %)
   Ohne Standard-Layout: neutrale Ersatzpalette (Akzent `#2563eb`), damit „Neu“ nie scheitert.
3. **Logo:** Das Layout hält es als `data:`-Adresse (≤ 150 KB, PNG/JPEG); E-Mail-Programme
   blocken das. Beim Anlegen schreibt die API es einmalig als Datei
   `logo-<laden>-<sha256[:10]>.png|jpg` in den Ordner für erzeugte Medien (`MARKETING_BILD_ORDNER`, media-erzeugt) –
   gleiche Prüfsumme = gleiche Datei, neues Logo = neue Datei, alte Newsletter behalten ihres.
   Kein Logo: der Masthead zeigt den Ladennamen als Wortmarke in der Anzeige-Schrift.
4. Ablauf in der API: Vorlage + Layout lesen → Rollen füllen, Logo ablegen, Grafiken für tech
   erzeugen (§6) → fertiges Dokument an die DB-Funktion. **Migration 058:**
   `pult_inhalt_aus_vorlage` bekommt das fertige Dokument als Parameter (die Vorlagenprüfung
   „freigegeben + Mandant“ bleibt in der DB) und vermerkt das tatsächliche Standard-Layout statt
   des festen „dunkel“. Die Bildaufträge für leere Plätze entstehen weiter automatisch – jetzt
   mit der Layout-Palette (seit 01.10. live).
5. **Vorlagenliste:** Die sieben neuen Vorlagen werden einmal eingespielt und mit `fuer_alle = true` für jeden Laden freigegeben (heute ist der Vorlagenname der Schlüssel und an einen Mandanten gebunden).
   Die fünf alten verschwinden aus der Liste für neue Newsletter (Status zurückgezogen);
   bestehende Entwürfe bleiben unberührt.
6. **Kontaktleiste und Fuß:** Telefon · Website · @instagram stehen als bearbeitbarer
   Platzhaltertext in der Vorlage. Der Pflichtteil (Impressum, Abmelden) bleibt wie heute.

## 6. Erzeugte Grafiken (ohne Modell)

Für tech zeichnet die Marketing-API beim Anlegen mit Pillow (kein KI-Modell, darf auf der VM
laufen):
- `tech-signal-<akzent>.png` – 1072 × 760 (2×): Karte mit radialem Halo (Akzent gemischt mit
  Surface), Ringe 1 px in Ring-Tönen, gefüllter Kern im Akzent, Funkel-Zeichen in Ink.
- `tech-glow-<akzent>.jpg` – 1200 × 900 (2×): radialer Lichtschein rechts oben auf Ink.
Gleicher Akzent = gleiche Datei (Name enthält den Hexwert). Die Bildplätze dieser Grafiken sind
**keine** FLUX-Plätze (der Arbeiter fasst sie nicht an); erkennbar an `props.grafik = true`.

## 7. Auslieferung der Bilder

- **Schwarz-weiß:** Hat ein Bildblock `sw: true`, setzt der Renderer an die signierte Bild-URL
  `?sw=1`; sales-ui liefert dann eine Graustufen-Fassung (Pillow, mit Cache). Original bleibt farbig.
- **Container-Hintergrund:** Renderer setzt `mj-section background-url` + Hintergrundfarbe
  (Ausweichfarbe); das Farbfeld ist eine Spalte mit `rgba`-Hintergrund (Outlook: Vollfarbe).
  Der Bild-Arbeiter behandelt `props.url` eines Containers als Bildplatz (Maße aus `props.width` × `props.height`).

## 8. Editor

- Block-Schemata erweitert (Heading, Text, Button, Image, Container, EmailLayout) – nichts geht
  beim Bearbeiten mehr verloren.
- Neue Regler, bewusst wenige: Schrift „Vorlage – Anzeige / Text“; Schalter „Versalien gesperrt“
  (setzt uppercase + 2 px); Container „Hintergrundbild aus Medien“ + Farbfeld; Bild „Schwarz-weiß“.
- Die Arbeitsfläche lädt die Vorlagenschriften (CSP `font-src 'self'`), damit sie wie die Mail aussieht.

## 9. Festgehalten für Baustein D (nicht Teil von A)

Vorbild ist der Framer-Agent des Betreibers (Werkzeuge statt Code, wiederverwendbare Stile,
Vorschau prüfen, Änderungsliste, Veröffentlichen nur auf ausdrückliche Bitte). Anforderungen:
- **„Neu“ über den Chat statt über Knöpfe**, damit die Seite ruhig bleibt.
- Werkzeuge: Newsletter lesen (inkl. Bildschirmfoto), Blöcke/Stile ändern, Bilder suchen/erzeugen,
  Rückfragen stellen, **Entwurf speichern**; versendet wird nur nach Freigabe im Pult.
- **Nach jedem Speichern Export nach Medien:** fertige Vorschaubilder **Handy · Tablet · PC**
  (HTML → Bild, Browser-Engine am PC).
- Ansicht Desktop/Handy nebeneinander; Fassungen als Änderungsliste mit Rückgängig.

## 10. Tests und Abnahme

- Einheitentests: jedes neue Feld im Renderer, in `pult_bloecke_fehler` (Migration 058 mit
  `verify_058.sql`), im Editor-Schema (Paket-Test wie bisher).
- Rollenfüllung: Paletten gelb `#facc15`, fast schwarz `#111111`, mittel `#c2410c`, Grau `#9ca3af`,
  jeweils mit und ohne `flaeche`, mit und ohne Logo.
- **7 Vorlagen × 4 Paletten** rendern, bestehen `schoenheit.py` (blockiert hart), keine
  ungefüllte Rolle `{…}` im Ergebnis, Mail-HTML unter 102 KB (Gmail kürzt sonst).
- Grafiken: tech-Signal und -Lichtschein entstehen, gleicher Akzent ⇒ gleiche Datei.
- **Sichtabnahme:** alle 7 Vorlagen in 600 px und 380 px (Handy) im Begleiter nebeneinander;
  erst nach OK des Betreibers live.
- Auslieferung: Migration 058, VM `update.sh`, PC-Dienste – jeweils mit Freigabe; kein Modell
  auf der VM; Vorlagen je Laden eingespielt, alte zurückgezogen.

## 11. Nicht in diesem Entwurf

Freistellen (B), freie Gestaltungsfläche (C), Agent/Chat/Export (D), mehrspaltige Layouts über
zwei Spalten, Animationen, eigene Hausschrift je Laden (Betreiber-Entscheid: Schrift gehört zur
Vorlage), Anlass-Vorlagen (Einladung, Produktneuheit) – die sieben Stile decken zunächst den
allgemeinen Newsletter ab.
