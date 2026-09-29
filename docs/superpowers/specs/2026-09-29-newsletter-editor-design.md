# Newsletter-Editor im Marketing-Pult

**Stand 29.09.2026. Abschnitt für Abschnitt mit dem Betreiber besprochen und
freigegeben. Baut auf `2026-09-29-marketing-pult-design.md` (Stufe 1 ausgeliefert)
auf und kommt vor deren Stufe 2 (Rückmeldung).**

## 1. Ziel

Der Betreiber baut Newsletter selbst in einem Baukasten-Editor aus hochwertigen
Vorlagen, und **der Marketing-Agent bedient denselben Editor** — über dasselbe
Blockformat. Beide arbeiten am selben Newsletter; jede Änderung ist eine Fassung
im Pult mit Vorschau und Freigabe.

Erfolg: Vorlage wählen → Blöcke ziehen, Texte und Bilder ändern → Vorschau zeigt
exakt die Mail, die verschickt würde → freigeben. Die Mail sieht in Gmail, Outlook
und am Handy gut aus.

## 2. Entscheidungen des Betreibers

| Frage | Entscheid |
|---|---|
| Editor und Agent | **ein Format für beide**; der Agent bedient den Editor über Block-Werkzeuge |
| Vorlagen | 4–5 fertige zum Start **und** eigene Vorbilder (Screenshot/Link), aus denen der Agent Vorlagen baut |
| Bauweg | **Email Builder JS** (usewaypoint) als Editor; dessen JSON-Blockformat als Fassung; Rendern auf dem Server über **MJML** (`mjml-python`) in der Marketing-API |
| Umfang | zuerst nur **Newsletter**; Posts und Material behalten das Feldformat |

## 3. Aufbau

### 3.1 Editor-Seite (sales-ui)

- Einstieg: Knopf **„Im Editor öffnen"** an jedem Newsletter-Entwurf; in der
  Pult-Übersicht **„Neuer Newsletter aus Vorlage"** (Vorlage wählen → Editor).
- Seite `/marketing/editor/{id}`: links Blöcke zum Ziehen, Mitte Newsletter,
  rechts Einstellungen des gewählten Blocks. Oben *Speichern* (neue Fassung),
  *Vorschau Mail / Handy*, *Zurück zum Entwurf*.
- **Vorschau kommt vom Server**: die Seite schickt das Blockdokument an sales-ui,
  sales-ui an die Marketing-API, die rendert über MJML. Der Editor-eigene
  Renderer wird für die Vorschau nicht benutzt.
- **Bilder**: Hochladen in die Medien des Ladens, im Editor aus den Medien wählen;
  im Dokument als feste Adresse (keine eingebetteten Bilder). Öffentliche
  Erreichbarkeit für Empfänger: Stufe 3 (Versand); bis dahin in Vorschau und
  Freigabe sichtbar.
- Unter 768 px Breite: Hinweis „Der Editor braucht einen größeren Bildschirm";
  Vorschau und Freigabe gehen am Handy wie bisher.

### 3.2 Sicherheit — die eine Skript-Ausnahme

- sales-ui ist sonst skriptfrei (`default-src 'none'`). **Nur** die Route
  `/marketing/editor/{id}` erlaubt ein Skript: das **eingebaute Editor-Paket**,
  ausgeliefert von sales-ui selbst (`script-src` mit Hash oder `'self'` nur auf
  dieser Route). Kein Nachladen aus dem Netz.
- Das Paket wird einmal gebaut und als Datei ins Repo gelegt, mit Version und
  Prüfsumme; ein Update ist ein bewusster Commit.
- Der Editor spricht nur mit sales-ui (CSRF-geschützt), nie direkt mit der
  Marketing-API. Rolle `freigeben` im Basis-Laden wie das ganze Pult.

### 3.3 Format

- Eine Newsletter-Fassung trägt ein **Blockdokument** (Email-Builder-JSON):
  Wurzel-Container (Hintergrund, Breite, Schrift) mit Blöcken **Überschrift, Text
  (fett, kursiv, Links), Bild, Knopf, Trenner, Abstand, Spalten (2–3), Container**.
  Jeder Block hat eine feste ID.
- Betreff und Vorschautext bleiben eigene Felder der Fassung.
- `inhalt_fassungen` bekommt `format` (`felder` | `bloecke`); Posts und Material
  bleiben `felder`.
- **Prüfung in der Datenbank** vor jedem Speichern: nur bekannte Blocktypen, Links
  nur `https:`, Bilder nur von erlaubten Adressen (Medien des Ladens), Grenzen für
  Größe und Verschachtelung; kein roher HTML-Block. Ablehnung mit deutschem Grund.
- Die 4 bestehenden Newsletter-Entwürfe werden als neue Fassung ins Blockformat
  übernommen (Abschnitte → Überschrift + Text, Knopf → Knopf).

### 3.4 Rendern (eine Stelle)

- Marketing-API: Übersetzer Blöcke → MJML, dann `mjml-python` → HTML.
- Pflichtteil des Mandanten (Impressum, Abmeldelink) wird **fest angehängt**;
  kein Block kann ihn entfernen. Fehlt das Impressum: sichtbarer Hinweis wie heute.
- Alle Texte escaped; Links nur `https:`.
- Die bestehenden **Layouts** werden **Voreinstellungen**: „Neu aus Vorlage" mit
  einem Layout setzt dessen Farben/Schrift/Rundung/Logo als Startwerte. Die
  Layout-Galerie mit Reglern bleibt.

### 3.5 Vorlagen

- Neue Tabelle `newsletter_vorlagen` (Name, Mandant, Beschreibung, Blockdokument,
  Status `vorschlag|freigegeben`, Fassungen wie die Layouts).
- **Start:** 5 Vorlagen — Newsletter, Ankündigung, Einladung, Produkt-Neuheit,
  kurzer Hinweis — einmalig nach Open-Source-Vorbildern im Blockformat gebaut, in
  VibeMind-Farben, freigegeben.
- **Aus Vorbildern:** In der Vorlagen-Galerie Screenshot hochladen oder Link
  angeben → der Agent baut ein Blockdokument (Muster Terminkarten: abgeschotteter
  `claude -p`, fremder Inhalt nur Material, nie Anweisung) → erscheint als
  *Vorschlag*; freigeben oder im Editor nachbessern.

### 3.6 Der Agent bedient den Editor

Werkzeuge des Marketing-Agenten; jede Änderung = neue Fassung, Urheber *agent*,
geprüft wie Editor-Speicherungen:

- `newsletter_lesen(id)` — neueste Fassung als Blockdokument mit Block-IDs.
- `newsletter_aus_vorlage(vorlage, titel, kampagne=None)`
- `block_einfuegen(id, nach_block, block)`, `block_aendern(id, block_id, aenderungen)`,
  `block_verschieben(id, block_id, nach_block)`, `block_loeschen(id, block_id)`
- `betreff_setzen(id, betreff, vorschautext)`
- `vorlage_aus_vorbild(bild_oder_link, name)`

Die Werkzeuge ändern Blöcke, nie Rohtext des Dokuments. Stufe 2 (Rückmeldung) der
Pult-Spec nutzt später dieselben Werkzeuge.

### 3.7 Gleichzeitiges Arbeiten

Der Editor merkt sich die Fassung, auf der er aufsetzt. Gibt es beim Speichern
eine neuere, lehnt die Datenbank ab: „Der Agent hat inzwischen Fassung N
gespeichert – neu laden oder als Kopie behalten." *Neu laden* zeigt seine
Fassung; *Als Kopie behalten* speichert deine Version als neueste, seine bleibt in
der Liste. Nichts wird still überschrieben.

## 4. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Ungültiges Blockdokument (Agent oder Editor) | nicht gespeichert, deutscher Grund |
| Marketing-API nicht erreichbar | Editor: „Speichern gerade nicht möglich", Änderungen bleiben im Editor |
| PC aus | Agent-Werkzeuge gehen nicht; Editor und Vorschau laufen (VM) |
| MJML-Render scheitert | Vorschau zeigt den Grund, keine kaputte Mail |
| Veraltete Grundlage beim Speichern | Ablehnung mit „neu laden / als Kopie behalten" |

## 5. Tests

- DB-Proben: unbekannter Blocktyp, `javascript:`-Link, fremde Bildadresse, zu tiefe
  Verschachtelung, roher HTML-Block → abgelehnt; veraltete Grundlage → abgelehnt.
- Übersetzer: jeder Blocktyp → erwartetes MJML; jede Startvorlage rendert
  fehlerfrei; `<script>` im Text bleibt Text; Pflichtteil immer am Ende.
- MJML-Validierung jeder Vorlage; gerendertes HTML als Datei zum Öffnen in
  Outlook und Gmail.
- Editor-Seite: nur diese Route erlaubt Skripte, nur das eingebaute Paket,
  Prüfsumme stimmt; alle anderen Seiten skriptfrei.
- Agent-Werkzeuge: je Operation eine gültige neue Fassung; veraltete Grundlage
  abgelehnt.
- Echter Browser-Durchlauf (Betreiber angemeldet): Vorlage → Block ziehen → Text
  ändern → Vorschau → Speichern → Agent ändert per Chat einen Block → neue Fassung
  sichtbar.

## 6. Pläne

- **E1 — Editor und Format:** Blockformat mit DB-Prüfung, Übersetzer + MJML,
  Editor-Seite mit Skript-Ausnahme, Bilder aus den Medien, 5 Startvorlagen,
  „Neu aus Vorlage", Übernahme der 4 Newsletter-Entwürfe.
- **E2 — Agent bedient den Editor:** Block-Werkzeuge, „Vorlage aus Vorbild".

## 7. Geprüft am 29.09.2026 (Download und Funktionstest im Scratchpad)

- **Email Builder JS** (github.com/usewaypoint/email-builder-js, Stand `ce3e610`,
  09.02.2026): **MIT**. Die Blöcke und `document-core`/`email-builder` sind Pakete;
  der **Editor selbst ist nur eine Beispiel-App** (`examples/vite-emailbuilder-mui`:
  Vite, React 18, MUI, zustand, zod). Wir übernehmen ihn als eigenen Build.
  Beim Übernehmen: das CDN-Stylesheet (highlight.js) aus `index.html` entfernen;
  MUI/emotion setzt Inline-Styles → die Editor-Route braucht `style-src
  'unsafe-inline'` zusätzlich zur Skript-Ausnahme; der Block `html` wird im
  Editor nicht angeboten und von der DB-Prüfung abgewiesen; Text-Blöcke können
  Markdown (`markdown: true`) — der Übersetzer behandelt es.
- **mjml-python 1.4.2** (MIT): Wrapper um MRML (Rust-Port von MJML). Fertige
  Pakete (abi3) für **Linux x86_64** (VM: x86_64, glibc 2.36 passt) und
  **Windows** — kein Rust-Build nötig. Funktionstest: `mjml.mjml2html(src)` rendert
  `mj-section`, `mj-column` (2 Spalten), `mj-text`, `mj-image`, `mj-button`,
  `mj-divider`, `mj-spacer`, `mj-attributes`/`mj-all`; Outlook-Sonderblöcke (`mso`)
  vorhanden; `&lt;script&gt;` bleibt Text.
- **Folge für die Vorschau:** Newsletter-Bilder kommen aus den Medien des Ladens;
  die Vorschau-CSP (heute `img-src data:`) muss für diese Vorschau Bilder von
  sales-ui selbst erlauben (`img-src 'self' data:`).

## 8. Nicht Teil dieser Spec

Versand an Empfänger und öffentliche Bild-Adressen (Pult-Stufe 3); Posts und
Material im Editor; fin2gether-Vorlagen; eigener HTML-Block.
