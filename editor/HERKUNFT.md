# Herkunft des Editors

Fork von `examples/vite-emailbuilder-mui` aus
[usewaypoint/email-builder-js](https://github.com/usewaypoint/email-builder-js),
Commit `ce3e610` („Fix directory name in README for local setup (#185)").
Lizenz: MIT, Originaltext in `LICENSE` (unverändert).

Gebaut wird mit `npm ci && npm run build` (Node 24). Das Ergebnis landet in
`../sales-mcp/static/editor/` (`editor.js`, `editor.css`, `MANIFEST.json` mit
SHA-256 der beiden Dateien). `tests/test_editor_paket.py` prüft Prüfsummen und
dass keine fremden Quellen (CDN, Google Fonts) enthalten sind.

## Änderungen gegenüber dem Original

- `package.json`: Name `sales-claw-editor`; Build-Skript ruft danach
  `manifest.mjs` auf. Abhängigkeiten unverändert (auch die nicht mehr
  benutzten `block-avatar`, `block-html`, `highlight.js`, `prettier` – sie
  landen durch Tree-Shaking nicht im Paket). `package-lock.json` neu erzeugt
  (das Beispiel hatte keines, es hing am Workspace-Lock des Monorepos).
- `tsconfig.json`: eigenständig statt `extends ../../tsconfig.json`.
- `vite.config.ts`: `base: /static/editor/`, Einstieg `src/main.tsx` (kein
  HTML im Ergebnis), ein einziges klassisches Skript (`format: iife`),
  Assets eingebettet, Ausgabe nach `../sales-mcp/static/editor`.
- `index.html`: nur noch für `npx vite`; `cdnjs`-Stylesheet (highlight.js),
  Favicons und Waypoint-Metadaten entfernt; enthält Beispiel-Startdaten.
  Das `<style>` für `#root` steht jetzt in `src/editor.css`.
- Entfernt: Vorlagen-Seitenleiste (`App/SamplesDrawer`), alle
  Beispielvorlagen (`getConfiguration/`), Reiter Vorschau/HTML/JSON,
  JSON-Import, JSON-Download, „Share", Favicons.
- Blöcke **Html** und **Avatar** entfernt (Hinzufügen-Menü, Block-Wörterbuch in
  `documents/editor/core.tsx`, Einstellungsfelder, `cloneDocumentBlock`).
  Die Prüfung im Pult nimmt nur Heading, Text, Button, Image, Divider,
  Spacer, Container, ColumnsContainer an.
- Neue Blöcke ohne fremde Adressen: Knopf-Link leer, Bild ohne Datei
  (Platzhalter als `data:`-SVG statt `placehold.co`).
- Neu `src/pult.ts`: Startdaten aus `<script type="application/json"
  id="editor-start">`, Speichern per `POST` mit `X-CSRF`, Medienliste,
  Umschreiben `medien:<datei>` ⇄ `/medien/datei/<datei>`.
- Neu `src/pultZustand.ts`, `src/App/PultLeiste.tsx`: Leiste mit Betreff,
  Vorschautext, Speichern, Vorschau Mail/Handy (nur ohne ungespeicherte
  Änderungen), Zurück zum Entwurf; Konflikt-Dialog (Neu laden / Als Kopie
  behalten); Fehlermeldungen mit dem Grund vom Pult.
- Bild-Einstellungen: freies URL-Feld ersetzt durch Auswahl „Aus den Medien"
  (nur png/jpg/jpeg/gif/webp mit erlaubtem Dateinamen).
- Link-Felder (Knopf, Bild) mit Platzhalter `https://…` und Hinweis;
  Text-Feld mit Hinweis „Erlaubt: **fett**, *kursiv*, [Link](https://…)".
- Oberfläche weitgehend deutsch (Block-Namen, Einstellungsfelder, Menüs).
