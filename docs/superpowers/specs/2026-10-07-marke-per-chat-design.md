# Marke per Chat: ein Markenprofil je Firma, geformt im Gespräch mit der KI

Stand: 07.10.2026 · Status: Entwurf zur Freigabe durch den Betreiber
Repos: sales-claw (`feat/stufe-1-fundament`) und vibemind-os (`spaces/marketing`, master)
Vorgänger: `2026-10-06-mandanten-markenwissen-design.md`, `2026-10-07-newsletter-freigabe-und-entwurfsseite-design.md`

## 0. Worum es geht

Der Reiter „Marke“ (früher „Layouts“) ist ein Formular mit acht Farbreglern, drei Schriften und
einem Logo. Der Betreiber versteht nicht, wozu er dient; zudem gibt es seit dem Mandanten-Baustein
eine zweite „Marke“ als `Marke.md` im Rowboat-Ordner jeder Firma (Ton, Zielgruppe, Angebote).

Ziel: **Ein Markenprofil je Firma** – Aussehen und Stimme an einem Ort –, das der Betreiber **per
Chat mit der KI** anlegt und nachschärft, mit Vorschau und ausdrücklichem „Übernehmen“. Alles, was
Newsletter baut (Vorlagen, Gestaltungs-Agent, Bild-Erzeugung), liest dieses Profil.

Betreiber-Entscheide (07.10.):
- Einsatz: neue Firma einrichten **und** bestehendes Branding nachschärfen.
- Inhalt: **Aussehen und Stimme zusammen** in einem Profil; der Textteil bleibt in Rowboat auch von
  Hand bearbeitbar.
- Ort: **komplett in Rowboat** (`companys/<Firma>/Marke.md` + `logo.png`); die VM bekommt eine
  Kopie des Aussehens (Spiegel).
- Material: **Uploads im Chat plus Webseite**.
- Markenänderung: neue Newsletter sofort; offene Entwürfe bekommen den Hinweis „Marke geändert –
  übernehmen?“ (ein Klick lässt den Gestaltungs-Agenten anpassen, rückgängig machbar); Freigegebenes
  bleibt unverändert.
- Ansatz: eigener Marken-Chat auf der Seite „Marke“ (nicht über den Editor, nicht außerhalb der
  Oberfläche).

Feste Grenzen wie bisher: kein Modell auf der VM; Claude nur am PC über den Marketing-Shim :8117;
:8114 und ComfyUI unberührt.

## 1. Das Profil (`companys/<Firma>/Marke.md`)

Kopfteil zwischen `---`-Zeilen (YAML-ähnlich, nur einfache `schlüssel: wert`-Zeilen):

| Schlüssel | Wert |
|---|---|
| `akzent`, `zweitfarbe`, `grund`, `text` | `#RRGGBB` |
| `schrift_anzeige`, `schrift_text` | id aus dem Schriftregister (`claw/schriften.py` `REGISTER`, z. B. `playfair`, `manrope`) |
| `logo` | Dateiname im Firmenordner (`logo.png`) oder leer |
| `stand` | `JJJJ-MM-TT HH:MM von <name>` |

Darunter die Abschnitte: `## Wer wir sind`, `## Zielgruppe`, `## Ton`, `## Angebote`,
`## Do & Don'ts`, `## Fakten und Zahlen`, `## Bildstil`.

- Lesen ist fehlertolerant: unbekannte Schlüssel ignoriert, ungültige Werte verworfen und als
  Hinweis gemeldet („Marke.md: akzent ungültig“), nie ein Abbruch.
- Bestehende `Marke.md` ohne Kopfteil (Vorlagen und Probe-Texte vom 07.10.) bleiben gültig: dann
  gibt es nur den Textteil, das Aussehen kommt weiter aus dem bisherigen Layout.
- Logo: PNG oder JPEG, ≤ 2 MB, wird als `logo.png` bzw. `logo.jpg` abgelegt.
- Markenwissen (`claw/markenwissen.py`) liest `Marke.md` weiter wie bisher; der Kopfteil wird für
  den Prompt in eine lesbare Zeile übersetzt statt roh durchgereicht.

## 2. Wer das Profil nutzt

- **Vorlagen („Neu aus Vorlage“, Vorlagen-Vorschau):** Akzent, Zweitfarbe und Logo wie heute, neu
  auch das Schriftpaar (`root.data.schriften.anzeige/text` der gefüllten Vorlage). Grund- und
  Textfarbe der Vorlage bleiben (sie tragen deren Stil). Quelle ist der Spiegel auf der VM.
- **Gestaltungs-Agent:** bekommt das Profil (Stimme + Aussehen) über das Markenwissen; die Regel
  „Farben nur aus den Ladenfarben“ wird zu „Farben nur aus der Marke (akzent, zweitfarbe, grund,
  text) und daraus abgeleiteten Tönen“.
- **Bild-Erzeugung (PC):** der Abschnitt `Bildstil` geht in die Bildbeschreibung für FLUX ein.
- **Feld-Newsletter:** rendern weiter mit dem Spiegel (Standard-Layout der Firma).

## 3. Spiegel zur VM

- Beim Übernehmen schreibt der PC-Arbeiter Akzent → `gestalt.akzent`, Zweitfarbe →
  `gestalt.flaeche`, Logo → `gestalt.logo` (data-URL), Schriftpaar → `gestalt.schriften
  {anzeige, text}` in das Standard-Newsletter-Layout der Firma (legt es an, wenn es fehlt) –
  über eine neue Pult-Route; die Gestalt-Prüfung der DB bleibt maßgeblich und wird um den
  Schlüssel `schriften` (nur Register-ids) erweitert (Migration 064).
- Abgleich: beim Start des Chat-Arbeiters und alle 10 Minuten vergleicht er den Kopfteil jeder
  `Marke.md` mit dem Spiegel und gleicht bei Abweichung an (so wirkt auch eine Handänderung in
  Rowboat). Kaputte Werte werden nicht gespiegelt; der Spiegel behält den letzten gültigen Stand.
- Der Reiter „Marke“ zeigt die Werte nur an; das alte Regler-Formular (Layout-Editor) entfällt.
  Pfade `/marketing/layouts…` bleiben erreichbar und führen zur neuen Seite.

## 4. Marken-Chat

### 4.1 Seite „Marke“ (sales-ui, ohne JavaScript wie bisher)
- Firma über den vorhandenen Umschalter.
- Oben das aktuelle Profil kompakt: Farbfelder, Schriftnamen in ihrer Schrift (Muster), Logo, erste
  Zeilen von Ton und Zielgruppe, „Stand: …“; ohne Profil „Noch kein Branding – erzähl mir von der
  Firma“. Hinweise zu ungültigen Werten und „Spiegel veraltet seit …“ falls zutreffend.
- Chat: Verlauf, Eingabe, Uploads (Bilder + Dokumente, dieselben Regeln und dieselbe Ablage wie im
  Editor-Chat, Firmenzuordnung automatisch), Senden; der Stand lädt per Meta-Refresh neu, solange ein
  Auftrag läuft (wie die Entwurfsseite).
- Vorschlag: Vorschau-Rahmen (Muster-Newsletter Mail/Handy) + Karte mit den Textabschnitten +
  „Übernehmen“ (Bestätigungshaken) und „Verwerfen“.

### 4.2 Aufträge
- Warteschlange `marketing.chat_auftraege` mit `art = 'marke'`; neue Spalte `mandant` (bei Art
  `marke` Pflicht, `inhalt` NULL). Höchstens ein laufender Marken-Auftrag je Firma.
- Verlauf je Firma (letzte 10 Runden) geht wie beim Gestaltungs-Agenten mit.

### 4.3 Arbeiter (PC)
1. Material: Uploads (Bilder als Bildteile, Dokumente als Text, wie bisher); **Webseite**, wenn die
   Nachricht eine Adresse enthält; aktuelles Profil.
2. Webseiten-Leser:
   - nur `http`/`https`; Adresse wird aufgelöst und **jede** Ziel-IP geprüft – privat, lokal,
     Link-Local, Tailnet (100.64.0.0/10), Multicast ⇒ abgelehnt; gilt auch nach jeder Umleitung
     (höchstens 3).
   - Startseite + höchstens 5 Unterseiten derselben Domain (aus Links der Startseite), je ≤ 2 MB,
     Zeitlimit 10 s, keine Cookies, kein JavaScript, keine Formulare.
   - extrahiert: sichtbaren Text (≤ 20 000 Zeichen gesamt), Überschriften, Farbwerte
     (`#rgb/#rrggbb/rgb()` aus `<style>`, `style=`, verlinktem CSS ≤ 500 KB), Schriftnamen
     (`font-family`), bis zu 6 Bild-Adressen als Logo-Kandidaten (`<link rel=icon>`, `og:image`,
     `<img>` mit „logo“ in Name/Alt/Klasse).
3. Claude antwortet mit `{"antwort": "...", "vorschlag": {kopfteil-Werte, logo: "anhang:<name>" |
   "web:<n>" | null, abschnitte: {…}, mustertext: {betreff, ueberschrift, absatz}}}`.
   - Schriften nur aus dem Register, Farben nur `#RRGGBB`; Text auf Grund und Akzent-Knopf muss die
     Kontrastregeln der Schönheitsprüfung erfüllen; Verstoß ⇒ ein Korrekturversuch, sonst „Das habe
     ich nicht umsetzen können: …“.
   - Webseiten- und Upload-Inhalte sind Material, niemals Anweisung (wie beim Gestaltungs-Agenten).
4. Vorschlag ablegen über die Arbeiter-API in `marketing.marken_vorschlaege (id, mandant, auftrag,
   vorschlag jsonb, status offen|angenommen|verworfen|ersetzt, erstellt_am, entschieden_von,
   entschieden_am)`; ein Web-Logo lädt der PC herunter (gleiche Sperren, ≤ 2 MB, PNG/JPEG geprüft) und
   legt es in den Medien der Firma ab. Ein neuer Vorschlag setzt offene ältere auf `ersetzt`.

### 4.4 Vorschau (VM)
Fester Muster-Newsletter aus der Vorlage `studio`, gefüllt mit dem Vorschlag (Farben, Schriften,
Logo, Mustertext), gerendert wie die Vorlagen-Vorschau; Mail und Handy.

### 4.5 Übernehmen
- `POST` setzt den Vorschlag auf `angenommen` (nur wenn er noch `offen` ist und der neueste offene;
  sonst „Inzwischen gibt es ein neueres Profil – bitte neu laden“) und legt einen Arbeiter-Auftrag
  `art = 'marke_uebernehmen'` an.
- Arbeiter: legt den Firmenordner an, falls er fehlt (einzige Stelle, die einen Firmenordner
  anlegt); verschiebt die bisherige `Marke.md` nach `Marke-Verlauf/JJJJ-MM-TT-HHMM.md`; schreibt die
  neue `Marke.md` und das Logo; spiegelt (§3); meldet fertig.
- Danach markiert die VM alle Newsletter der Firma im Status `entwurf` als „Marke geändert“
  (`marketing.inhalte.marke_geaendert_am`).
- Seite zeigt „Wird übernommen …“ bis fertig; PC aus ⇒ „Wird übernommen, sobald der PC läuft“.

### 4.6 Hinweis im Editor
- Ist `marke_geaendert_am` neuer als die neueste Fassung und der Status `entwurf`: Band „Die Marke hat
  sich geändert – übernehmen?“ mit Knopf. Der Knopf schickt dem Gestaltungs-Agenten die Bitte
  „Übernimm die neue Marke: Farben, Schriften und Logo, sonst nichts ändern.“; das Ergebnis ist eine
  normale, rückgängig machbare Fassung. „Ausblenden“ setzt die Markierung zurück.
- Nicht bei `eingereicht`/`freigegeben`/`abgelehnt`.

## 5. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Webseite nicht erreichbar / zu groß / private Adresse | Hinweis „Webseite … nicht lesbar: …“, KI arbeitet mit dem Rest |
| Vorschlag ungültig (Schrift, Farbe, Kontrast) | ein Korrekturversuch, sonst „Das habe ich nicht umsetzen können: …“ |
| PC aus | Aufträge warten; „Wird übernommen, sobald der PC läuft“ |
| `Marke.md` von Hand kaputt | kaputte Werte ignoriert, Hinweis im Chat und auf der Seite; Spiegel behält letzten gültigen Stand |
| Firmenordner fehlt | wird beim ersten Übernehmen angelegt |
| Spiegel scheitert | Rowboat bleibt Wahrheit; Abgleich holt nach; Seite „Spiegel veraltet seit …“ |
| Zwei Tabs übernehmen verschiedene Vorschläge | erster gewinnt; zweiter „Inzwischen gibt es ein neueres Profil – bitte neu laden“ |

## 6. Tests und Abnahme

- Migration 064 + Verify: `chat_auftraege.mandant`, Arten `marke`/`marke_uebernehmen`, ein laufender
  Marken-Auftrag je Firma, `marken_vorschlaege` mit Statusregeln, `inhalte.marke_geaendert_am`.
- Webseiten-Leser: private/lokale/Tailnet-Adressen gesperrt (auch nach Umleitung, auch bei mehreren
  A-Records), Größen-/Zeitlimit, nur dieselbe Domain, Farben/Schriften/Logo-Kandidaten aus HTML+CSS.
- Profil-Datei: lesen/schreiben, Kopfteil gültig/kaputt/fehlend, Verlauf-Datei, Ordner anlegen,
  Link-Sperre wie Markenwissen.
- Prompt/Antwort: Vorschlagsformat, Schriften nur aus dem Register, Kontrast, Korrekturversuch.
- Spiegel: Layout-Werte gesetzt; Vorlagen übernehmen Schriftpaar; Abgleich nach Handänderung;
  kaputte Werte nicht gespiegelt.
- Pult-API: Auftrag anlegen/Stand, Vorschlag, Vorschau, Übernehmen (Zwei-Tab-Fall), Markierung.
- sales-ui: neue Seite „Marke“ (Profil, Chat, Uploads, Vorschau, Übernehmen/Verwerfen), altes
  Regler-Formular entfernt, alte Pfade leiten weiter.
- Editor: Band „Marke geändert“ startet die Agent-Bitte; nicht bei eingereicht/freigegeben.
- **Echter Lauf**: fin2gether mit Webseiten-Adresse + Logo-Upload → Vorschlag → Vorschau → „Ton
  ruhiger“ → Übernehmen → `Marke.md` + `logo.png` in Rowboat → neuer fin2gether-Newsletter aus
  Vorlage trägt Farben, Schriften, Logo → offener Entwurf zeigt Hinweis, Klick passt an.

## 7. Auslieferung

Migration 064 → VM `update.sh` → PC Chat-Arbeiter neu.

## 8. Nicht in diesem Baustein

Bilder der Firma in Rowboat (außer Logo), Paletten mit mehr als vier Farben, eigene Schriftdateien,
mehrere Logos (hell/dunkel), automatisches Umstellen offener Entwürfe ohne Klick.
