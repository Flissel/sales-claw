# Newsletter in den Sales-Freigaben, Entwurfsseite, Marke, Vorlagen

Stand: 07.10.2026 · Status: Entwurf zur Freigabe durch den Betreiber
Repos: sales-claw (`feat/stufe-1-fundament`) und vibemind-os (`spaces/marketing`, master)
Vorgänger: `2026-10-06-mandanten-markenwissen-design.md`

## 0. Worum es geht

Der Betreiber will alle Freigaben an einem Ort: Newsletter-Entwürfe sollen in den Sales-Freigaben
neben WhatsApp, E-Mail und LinkedIn erscheinen. Freigeben legt den Newsletter in die Medien, damit
Sales ihn nutzen kann. Zurückgeben geht mit Kommentar zurück in Arbeit; wer den Entwurf als
Nächstes bearbeitet (Mensch oder Gestaltungs-Agent), bekommt das Feedback gleich mit.

Dazu drei kleinere Punkte: Die Entwurfsseite sieht unfertig aus (linke Spalte am Rand
abgeschnitten, ungeordnete Bedienung), der Reiter „Layouts“ ist missverständlich benannt, die
Vorlagen-Galerie lädt alle Vorschauen sofort.

Betreiber-Entscheide (07.10.):
- In die Freigaben nur nach ausdrücklichem **„Zur Freigabe einreichen“**.
- Freigeben legt **den Newsletter als Bild je Gerät und jede Gestaltungsfläche einzeln** in die
  Medien (kein HTML-Mailversand).
- Zurückgeben: Feedback steht offen im Editor und auf der Entwurfsseite und geht bei jeder Bitte
  an den Agenten mit; **der Agent wird nicht von selbst tätig**.
- Ansatz: Status lebt im Marketing (`marketing.inhalte`), die Sales-Freigaben lesen über die
  Pult-API mit; kein Spiegeln in `sales.drafts` (dort heißt Freigeben „senden“).

Feste Grenzen wie bisher: kein Modell auf der VM; Claude nur am PC über den Marketing-Shim :8117.

## 1. Zustände und Übergänge

`marketing.inhalte.status`: `entwurf` (in Arbeit) · **`eingereicht`** (neu) · `freigegeben` ·
`abgelehnt` (Anzeige „verworfen“, endgültig).

| Von | Aktion | Nach | Wer / Wo |
|---|---|---|---|
| entwurf | Zur Freigabe einreichen | eingereicht | Editor-Leiste, Entwurfsseite |
| entwurf, eingereicht | Verwerfen (Grund Pflicht) | abgelehnt | Entwurfsseite |
| eingereicht | Zurückziehen | entwurf (ohne Rückmeldung) | Editor-Band, Entwurfsseite |
| eingereicht | Zurückgeben (Kommentar Pflicht, ≤ 2000 Zeichen) | entwurf + Rückmeldung | Sales-Freigaben |
| eingereicht | Freigeben | freigegeben + Export | Sales-Freigaben |

- Einreichen nimmt die **neueste Fassung**; die eingereichte Fassung wird am Inhalt vermerkt
  (`eingereichte_fassung`, `eingereicht_am`, `eingereicht_von`).
- Einreichen ist abgelehnt, solange ein Chat-/Export-Auftrag offen oder in Arbeit ist
  („Der Assistent arbeitet gerade“).
- Freigeben gilt nur für die eingereichte Fassung; gibt es eine neuere ⇒ „Inzwischen gibt es
  Fassung n – bitte neu laden“. Schon entschieden ⇒ „Schon entschieden (…)“.
- Im Zustand `eingereicht` lehnt die DB Speichern, Chat-Aufträge und Bildaufträge ab mit
  „Liegt zur Freigabe – erst zurückziehen“.
- Beim (erneuten) Einreichen werden alle offenen Rückmeldungen des Inhalts als erledigt markiert.

## 2. Daten (Migration 063)

- `marketing.inhalte`: Status-Regel um `eingereicht` erweitert; neue Spalten
  `eingereichte_fassung int`, `eingereicht_am timestamptz`, `eingereicht_von text`.
- Neue Tabelle `marketing.rueckmeldungen (id uuid PK, inhalt uuid FK, fassung int, text text
  CHECK 1..2000, von text, am timestamptz DEFAULT now(), erledigt_am timestamptz NULL)`.
- DB-Funktionen (Regeln dort, API nur Formen): `pult_einreichen(inhalt, von)`,
  `pult_zurueckziehen(inhalt, von)`, `pult_zurueckgeben(inhalt, fassung, von, text)`;
  `pult_entscheiden` erlaubt `freigeben` aus `eingereicht` (für die eingereichte Fassung) und
  `ablehnen` (= Verwerfen) aus `entwurf` und `eingereicht`.
- Sperre in `pult_bloecke_speichern`, `pult_chat_anlegen` (Chat) und `pult_bild_auftrag` für
  `eingereicht`. `pult_chat_anlegen` erlaubt Art `export` zusätzlich für `freigegeben`.
- Verify-Skript prüft jeden erlaubten und jeden verbotenen Übergang.

## 3. Pult-API (VM)

- `POST /inhalte/{iid}/einreichen {von}`, `POST /inhalte/{iid}/zurueckziehen {von}`,
  `POST /inhalte/{iid}/zurueckgeben {fassung, von, text}`.
- `POST /inhalte/{iid}/freigeben {fassung, von}`: `pult_entscheiden(freigeben)`, danach
  Flächen-Export aller Gestaltungsflächen der freigegebenen Fassung in drei Formaten
  (bestehende Export-Logik inkl. Firmenzuordnung) und Anlage eines Newsletter-Export-Auftrags
  (`art=export`). Antwort `{status, flaechen: [namen], export_auftrag: id|null, export_fehler:
  str|null}`; scheitert ein Export-Teil, bleibt die Freigabe gültig und der Fehler steht in der
  Antwort.
- `POST /inhalte/{iid}/export_nachholen {}`: nur für `freigegeben`, stößt fehlende Exporte erneut an.
- `GET /freigaben?status=eingereicht|entschieden&limit=` (alle Mandanten): je Inhalt id, mandant,
  mandant_name, titel, betreff, eingereichte_fassung, eingereicht_am/von, letzte Rückmeldungen
  (erledigt), bei entschiedenen Status/Urteil/Zeit/Exportstand.
- `GET /inhalte/{iid}` liefert zusätzlich `rueckmeldungen` (neueste zuerst) und die
  Einreich-Felder.
- Chat-Auftrag (`/arbeiter/naechster`) trägt `rueckmeldungen_offen: [{text, von, am, fassung}]`.

## 4. Sales-Freigaben (sales-ui)

- Neuer Abschnitt **„Newsletter“** in `/freigaben` (Zähler wie die anderen Arten, auch im
  Seitenleisten-Zähler `/freigaben`).
- Karte je eingereichtem Newsletter: Firmen-Etikett, Titel, Betreff, Fassung, „eingereicht von …
  vor …“; Vorschau Mail/Handy (umschaltbar, gesandboxter Rahmen wie auf der Entwurfsseite); Link
  „Im Editor ansehen“ (lesend); frühere erledigte Rückmeldungen kurz.
- Aktionen: **Freigeben** (Bestätigungshaken, wie bei den anderen Arten) und **Zurückgeben**
  (Kommentar Pflicht). CSRF wie alle Freigabe-Formulare.
- Verlauf je Abschnitt: freigegeben (Medien: n Flächen, Newsletter-Bilder bzw. „Export läuft“ /
  „Export offen – erneut anstoßen“), zurückgegeben (mit Kommentar), verworfen.
- Marketing-API nicht erreichbar ⇒ im Abschnitt „Marketing gerade nicht erreichbar“, Rest der
  Seite unverändert.

## 5. Editor, Entwurfsseite, Agent

- Editor-Leiste: „Zur Freigabe einreichen“ (speichert vorher ungespeicherte Änderungen; gesperrt
  mit Grund, solange der Agent arbeitet). Bei `eingereicht`: Editor nur lesend, Band „Liegt zur
  Freigabe seit … – Zurückziehen“. Startdaten tragen Status, Einreich-Felder, Rückmeldungen.
- Feedback-Band (Editor + Entwurfsseite), solange offene Rückmeldungen existieren: neueste
  ausgeklappt („Zurückgegeben von … am …: ‚…‘“), ältere einklappbar.
- Agent: Prompt-Abschnitt „Offenes Feedback aus der Freigabe (vom Betreiber, bitte
  berücksichtigen):“ mit allen offenen Rückmeldungen — anders als Unterlagen/Notizen eine echte
  Vorgabe des Betreibers. SYSTEM nennt den Abschnitt. Keine automatische Überarbeitung.
- Marketing-Übersicht und Entwurfsliste zeigen Status in Worten: in Arbeit, zurückgegeben (offenes
  Feedback), zur Freigabe, freigegeben, verworfen; Zähler entsprechend. Der Knopf „Freigeben
  (ablegen)“ auf der Entwurfsseite entfällt; „Ablehnen“ heißt „Verwerfen“ (Grund Pflicht).

## 6. Entwurfsseite, Marke, Vorlagen

- **Entwurfsseite** (links Bedienung, rechts Vorschau):
  - Kopf: Titel, Firmen-Etikett, Status-Pill, „Fassung n“; darunter das Feedback-Band.
  - Aktionskarte: „Im Editor öffnen“ (Hauptknopf), „Zur Freigabe einreichen“ bzw. „Zurückziehen“;
    „Verwerfen“ abgesetzt, klein, rot, Grundfeld klappt erst beim Klick auf.
  - Karte „Bilder“: Auftragsstand als Liste mit Status-Punkten; Überarbeiten-Bedienung (Platz,
    Stärke, Hinweis, Knopf) als saubere Zeile mit Beschriftungen über den Feldern.
  - Karte „Fassungen“: Zeitleiste mit Urheber (du/Agent), freigegebene Fassung markiert.
  - Ursache des abgeschnittenen linken Rands finden und beheben; fester Innenabstand; mobil
    Vorschau unter der Bedienung.
- **„Layouts“ → „Marke“**: Reitername, Seitentitel und Texte; Einleitungssatz „Diese
  Einstellungen (Farben, Schrift, Logo, Kopf- und Fußzeile) füllen neue Newsletter aus Vorlagen.“
  Pfade bleiben (`/marketing/layouts…`), damit Lesezeichen weiter gehen.
- **Vorlagen-Galerie**: Vorschau-Rahmen mit `loading="lazy"`, Platzhalter mit Vorlagennamen, feste
  Kartenhöhe.

## 7. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Einreichen während Agent arbeitet | Knopf gesperrt mit Grund; DB lehnt ab |
| Freigeben bei neuerer Fassung | „Inzwischen gibt es Fassung n – bitte neu laden“ |
| Zwei Tabs entscheiden gleichzeitig | Erster gewinnt, zweiter „Schon entschieden (…)“ |
| Flächen-Export scheitert | Freigabe gültig; Verlauf „Export offen – erneut anstoßen“ |
| Newsletter-Export am PC läuft nicht | Auftrag wartet; Verlauf „Export läuft“ |
| Zurückgeben ohne Kommentar | „Bitte sag kurz, was fehlt“ |
| Speichern/Chat/Bild bei `eingereicht` | „Liegt zur Freigabe – erst zurückziehen“ |
| Marketing-API weg | Abschnitt Newsletter: „Marketing gerade nicht erreichbar“, Rest normal |

## 8. Tests und Abnahme

- Migration 063 + `verify_063`: jeder erlaubte und verbotene Übergang, Sperren bei `eingereicht`,
  Export-Auftrag für `freigegeben`, Rückmeldungen erledigt beim Einreichen.
- Pult-API: einreichen/zurückziehen/zurückgeben (Kommentar Pflicht)/freigeben (Flächen + Auftrag,
  Teilfehler), export_nachholen, `/freigaben`, `/inhalte/{iid}` mit Rückmeldungen.
- Chat-Arbeiter/Prompt: offenes Feedback im Prompt, ohne Feedback kein Abschnitt.
- sales-ui: Newsletter-Abschnitt (Zähler, Karte, Aktionen, CSRF, Verlauf, API-Ausfall),
  Entwurfsseite (Status-Pill, Band, Aktionen, kein „Freigeben (ablegen)“), „Marke“, Lazy-Rahmen.
- Editor (vitest): lesend bei `eingereicht`, Einreichen-Knopf (Sperre bei laufendem Agenten),
  Feedback-Band.
- **Echter Lauf**: Probe-Newsletter einreichen → in den Freigaben → zurückgeben „Überschrift
  kürzer“ → Band im Editor, Agent nimmt Feedback auf → erneut einreichen → freigeben → Flächen und
  Newsletter-Bilder in den Medien der Firma.

## 9. Auslieferung

Migration 063 → VM `update.sh` (marketing-api + sales-ui) → PC Chat-Arbeiter neu. Reihenfolge
sicher: der alte Arbeiter ignoriert das neue Feld.

## 10. Nicht in diesem Baustein

HTML-Mail-Versand, automatische Überarbeitung nach dem Zurückgeben, mehrere Freigabe-Personen,
Rückmeldungen per Telegram/Mail.
