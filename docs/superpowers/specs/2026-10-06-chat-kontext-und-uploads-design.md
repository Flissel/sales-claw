# Gestaltungs-Agent: Kontext per Klick und Uploads im Chat

Stand: 06.10.2026 · Status: Entwurf zur Freigabe durch den Betreiber
Repos: sales-claw (`feat/stufe-1-fundament`) und vibemind-os (`spaces/marketing`, master)
Vorgänger: `2026-10-02-newsletter-gestaltung-und-agent-design.md`, `2026-10-02-newsletter-agent-live-design.md`
Reihenfolge der nächsten Bausteine (Betreiber 06.10.): **dieser** → Bild-Embeddings (Messung wie Laura) → Rowboat-Anbindung.
Mit diesem Baustein wird auch der Scroll-Fix (sales-claw `e2e47d3`) ausgeliefert.

## 0. Worum es geht

Der Betreiber will dem Agenten genauer sagen können, *was* er meint, und ihm *Material* geben:
- **Kontext per Klick**: Blöcke im Newsletter bzw. Ebenen in einer Gestaltungsfläche markieren und
  als Kontext an die Nachricht hängen („mach das kürzer“).
- **Uploads im Chat**: Bilder und Dokumente in den Chat ziehen; der Agent setzt Bilder ein und
  übernimmt Inhalte aus Dokumenten (Flyer, Preisliste, Veranstaltungsinfo).

Betreiber-Entscheide (06.10.): Uploads = **Bilder + Dokumente**; Bildverständnis = **Claude sieht die
Bilder selbst** über den eigenen Marketing-Shim (kein zusätzliches Modell).

Machbarkeit geprüft (06.10.): `claude -p --add-dir <ordner> --allowedTools Read` liest eine Bilddatei
und beschreibt sie korrekt (ein zusätzlicher Werkzeug-Schritt).

Feste Grenzen wie bisher: kein Modell auf der VM; Claude nur am PC über den Marketing-Shim :8117;
geteilter Shim :8114 unberührt.

## 1. Kontext per Klick

- Editor: an jedem ausgewählten Block eine kleine Taste „+ Kontext“ sowie **Alt+Klick** auf einen
  Block; im Gestaltungsfenster dasselbe für Ebenen.
- Markierte Elemente erscheinen als **Chips** über dem Chat-Eingabefeld (Art-Symbol + Kurztext, z. B.
  „Überschrift · Goldener Herbst …“, „Bild · held_bild“, „Text-Ebene · Neu im Oktober“), mit ✕;
  höchstens **8** je Nachricht; doppelte werden nicht doppelt angehängt.
- Nachricht trägt `kontext.auswahl = [{art: "block"|"ebene", id, flaeche?: <block-id>, kurz}]`
  (bisheriges `kontext.auswahl` – eine einzelne id – bleibt für Altfälle lesbar).
- Prompt: „Mit ‚das‘, ‚hier‘, ‚diese‘ usw. sind die markierten Elemente gemeint.“ Der Kontext
  enthält die markierten Blöcke/Ebenen zusätzlich vollständig und hervorgehoben.
- Bild-Chips (Image-Block mit Bild, Bild-Ebene) nehmen das Bild mit (Abschnitt 2.3).
- Chips gelten nur für die nächste Nachricht; beim Vormerken werden sie mit vorgemerkt.
- Fehlt ein markiertes Element inzwischen (vom Agenten gelöscht) ⇒ Arbeiter ignoriert es und nennt
  es im Chat-Hinweis.

## 2. Uploads

### 2.1 Editor
- Büroklammer am Eingabefeld, Ziehen auf den Chat (Ablagefläche mit dezentem Akzent-Rahmen),
  Einfügen aus der Zwischenablage (Bilder).
- Höchstens **5** Dateien je Nachricht, je ≤ **15 MB**; erlaubt: `jpg jpeg png webp` (Bild),
  `pdf docx txt md` (Dokument).
- Jede Datei sofort als Chip mit Vorschaubild bzw. Dateisymbol und Fortschritt; Fehler (zu groß,
  falscher Typ, Upload gescheitert) am Chip mit Grund; Senden erst, wenn alle Uploads fertig sind.

### 2.2 Ablage (sales-ui)
- Neue Route `POST /marketing/editor/{iid}/anhang` (CSRF, angemeldet): nutzt dieselbe Prüfung und
  denselben Zielordner wie `/medien/hochladen` (Endung, Größe, kein Symlink, eindeutiger Name;
  bei Namensgleichheit Suffix). Antwort `{name, art, groesse}`.
- Die Endungsliste der Medien wird um `docx` und `md` ergänzt, falls noch nicht erlaubt (Dokumente
  bleiben normale Medien; `pruefe_anhang`-Regeln für Bot-Anhänge bleiben unverändert).
- Hochgeladene Bilder stehen damit auch in der Medienbibliothek und sind direkt einsetzbar.
- Nachricht trägt `kontext.anhaenge = [{name, art: "bild"|"dokument"}]` (≤ 5).

### 2.3 Arbeiter (PC)
- Holt Anhänge und Bilder aus Bild-Chips über die vorhandene Arbeiter-Route
  `/api/chat/arbeiter/{aid}/medien/{name}` (Pult-API lässt die Namen der Anhänge zu, siehe 2.5).
- **Bilder**: auf längste Kante **1568 px** verkleinern, als JPEG/PNG, und als OpenAI-Bildteil
  (`{"type":"image_url","image_url":{"url":"data:image/…;base64,…"}}`) in die Nutzernachricht;
  höchstens **6** Bilder je Anfrage (Anhänge vor Chips); Überzählige werden im Hinweis genannt.
- **Dokumente**: Text mit `pypdf` (PDF) bzw. `python-docx` (DOCX), TXT/MD direkt (UTF-8, sonst
  latin-1); zusammen höchstens **20 000** Zeichen je Nachricht (anteilig gekürzt, mit Vermerk);
  im Prompt als „Unterlage: <name>“. Kein lesbarer Text ⇒ Hinweis „<name> hat keinen lesbaren
  Text“, kein Fehler. Kein Modell.
- Streaming, Zwischenstände, Korrekturversuch, Stopp wie bisher.

### 2.4 Marketing-Shim
- Nimmt OpenAI-Bildteile in Nutzernachrichten an (Inhalt als Liste aus `text` und `image_url`;
  nur `data:image/(png|jpeg|webp);base64,`, je ≤ 10 MB dekodiert, ≤ 6 je Anfrage; anderes ⇒ 400).
- Legt die Bilder in einem eigenen Temp-Ordner je Anfrage ab, gibt ihn per `--add-dir` frei,
  ergänzt `Read` in den erlaubten Werkzeugen und ersetzt den Bildteil im Transkript durch einen
  Verweis („[Bild 1: <pfad> – lies die Datei]“); löscht den Ordner nach der Anfrage (auch bei
  Fehler/Abbruch).
- Anfragen ohne Bildteile laufen unverändert (auch das bisherige Streaming-Verhalten).

### 2.5 Pult-API (VM)
- Die Arbeiter-Medienroute liefert schon jede Datei aus den Medienordnern (Namen-Regex wie die
  DB-URL-Regex). Für Dokumente wird die Regex um `pdf|docx|txt|md` erweitert (nur diese Route).
- Chat-Anlegen/Vormerken prüfen `kontext.auswahl` (≤ 8, Form) und `kontext.anhaenge` (≤ 5, Namen
  nur aus den Medien, Art bild|dokument); `kontext` ≤ 4 KB bleibt.

## 3. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Upload zu groß / falscher Typ | Chip zeigt Grund, Datei wird nicht gesendet |
| Anhang inzwischen gelöscht | Hinweis „<name> fehlt in den Medien“, Nachricht läuft ohne ihn |
| Bild unlesbar / zu groß für den Shim | Hinweis, Bild wird übersprungen |
| Dokument ohne Text (Scan) | Hinweis „hat keinen lesbaren Text“ |
| Mehr als 6 Bilder | erste 6 (Anhänge vor Chips), Rest im Hinweis |
| Shim lehnt Bildteil ab | Arbeiter wiederholt einmal ohne Bilder, mit Hinweis |

## 4. Tests und Abnahme

- Shim: Bildteile mit gefälschter CLI (Ordner angelegt, `--add-dir`/`Read` im Aufruf, Verweis im
  Transkript, Ordner danach gelöscht, auch bei Fehler); ungültige Bildteile ⇒ 400; ohne Bildteile
  unverändert.
- Arbeiter: Bilder holen/verkleinern/als Bildteil; Grenze 6; Dokument-Text aus Beispiel-PDF/-DOCX/
  -TXT, Kürzung 20 000; fehlende Anhänge/markierte Elemente ⇒ Hinweise.
- Prompt: markierte Elemente hervorgehoben; Unterlagen eingebunden.
- Pult-API: Prüfung von `auswahl`/`anhaenge`; Medienroute liefert Dokumente.
- sales-ui: Anhang-Route (CSRF, Typ, Größe, Namenskollision).
- Editor (vitest): Chips (Block/Ebene, max 8, doppelt), Upload-Chips (Typ/Größe, Fortschritt,
  Senden erst nach Upload), Vormerken mit Chips; Paket-Test; tsc.
- **Echter Lauf**: Foto hochladen + „Setz das als Titelbild und beschreib es in der Einleitung“;
  PDF-Preisliste + „Übernimm die drei Angebote“; Überschrift markieren + „mach das kürzer“.

## 5. Nicht in diesem Baustein

Links/Webseiten lesen, OCR für Scans, Audio/Video, gemessene Bildbewertung (kommt mit dem
Baustein Bild-Embeddings), Rowboat.
