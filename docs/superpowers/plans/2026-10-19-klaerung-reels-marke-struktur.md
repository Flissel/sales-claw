# Klärung: Reels, Marken-Chat, Struktur-Graph (19.10.2026)

> **Kein Implementierungsplan.** Klärungsdokument für drei Wünsche, die laut Wunschliste
> (`C:/Users/User/Desktop/Vibemind_V1/tasks/2026-10-19-ui-marketing-wunschliste.md`, B und D) als **[gross]**
> gelten. Je Thema: Ist-Stand aus dem Code, Schwächen, Lösungsansätze, Empfehlung, Fragen an den
> Betreiber, grobe Task-Skizze. Aus den Antworten entsteht je Thema ein eigener Plan (writing-plans).
>
> Repos: **SC** = `vibemind-os/spaces/sales-claw` (Branch `feat/stufe-1-fundament`, Stand `9684fb4`),
> **MOS** = `vibemind-os/.worktrees/setup-agent/spaces/marketing` (master, Stand `6a2b0abc`).
> Screenshots (Ist, 19.10.): `E:/Temp/claude/c--Users-User-Desktop-Vibemind-V1/09346339-4318-4647-a968-36a3579400b7/scratchpad/design/`
> (`marketing_reels_d.png`, `marketing_reels_m.png`, `marketing_layouts_d.png`, `marketing_layouts_m.png`).
> Die Screenshots stammen aus der Zeit VOR S2 (noch braun/grün) – die Farbe ist inzwischen VibeMind,
> der Aufbau ist unverändert.
>
> Gemeinsame Grenzen für alle drei Themen (gelten auch für die Folgepläne): sales-ui-Seiten ohne
> JavaScript (CSP `default-src 'none'`, `ui.py:438`), deutsche Texte mit echten Umlauten
> (`tests/test_darstellung.py`), Farben nur über `:root`-Variablen, keine `<img` mit Fremddaten ohne
> Blick in die XSS-Tests, Tabellen über `_tabelle` (`ui.py:1755`), Deploy erst nach Betreiber-OK
> (Migration → API → Arbeiter).

---

## Thema 1: Reels

### 1.1 Ist-Stand (Code)

Kette (live seit 18.10.):
`/marketing/reels` (SC `sales-mcp/ui_reels.py`) oder Marketing-Agent-Werkzeug `reel_beauftragen`
(MOS `claw/werkzeuge.py`, `claw/server.py`) → Marketing-API `POST /api/pult/video` (MOS `api/video.py:171`,
Briefing-Prüfung `briefing_pruefen` `api/video.py:68`) → Tabelle `marketing.video_auftraege`
(MOS `db/072_video_auftraege.sql`, Status `offen/in_arbeit/fertig/fehler/abgebrochen`, `protokoll` jsonb,
höchstens 2 Versuche) → PC-Arbeiter `workers/video_claw.py` (:8136, ein Auftrag zur Zeit) → Claude über
eigene Shim :8118 mit System-Prompt = `video_claw/AGENTS.md` + Skill je Art
(`video_claw/skills/{reel-aus-bildern,reel-aus-material,kurzfassung}/SKILL.md`) und Werkzeugen
`video_claw/werkzeuge.py` (u. a. `material_suchen`, `transkript`, `standbild`, `titelkarte`, `reel_bauen`
`:245`) → Laura rendert → API holt MP4 (`aus-laura`) → `media-erzeugt/vid-<id>-<titel>.mp4`.

Seite (`ui_reels.py`):
- Eine Tabelle „Reel | Status | (Inhalt)“ (`:151`); je Zeile Titel, Zeit, Art, „Agent/Betreiber“, die
  letzten 4 Protokoll-Notizen, Befund, `<video width="270">` und das Formular „Als LinkedIn-Post
  vorbereiten“ (`:96-107`). Abbrechen nur bei offen/in Arbeit (`:110`).
- Bestellformular (`:129-149`): Art-Auswahl, Titel, Thema, Sprechertext, Einstieg, Länge, Stimme (Freitext
  `standard`), Fieldset „Aus Bildern“ (Dateinamen **mit Komma getrennt**, Logo-Dateiname, Farben als
  Hex-Text) und Fieldset „Aus Videomaterial“ (Laura-**IDs** als Text) – beide Fieldsets immer sichtbar.
- Meta-Refresh 30 s, solange etwas läuft (`:152`).
- Posten nur für die eigene Firma des Ladens (`MARKETING_MANDANT`, `:98`, `:193-205`), Weg über
  `post_entwurf_erstellen` → Freigaben.
- API-Liste: `pult_liste` liefert bis 50 Aufträge, neueste zuerst (`api/video.py:164`, `_liste` `:141`).

### 1.2 Was heute schwach ist

Belegt mit `marketing_reels_d.png` (Seite 3 663 px hoch bei 8 Aufträgen):
1. **Tabelle statt Galerie.** Hochformat-Videos in 270 px breiten Zellen, Status-Spalte so schmal, dass
   „fertig“/„Fehler“ umbrachen (S1 hat den Umbruch entschärft, die Form bleibt). Fehlgeschlagene
   Probeläufe stehen gleichwertig zwischen den fertigen; es gibt kein Ausblenden/Archiv.
2. **Entwickler-Sprache im Protokoll.** Die Notizen des Claws (z. B. „Originalton 76–91 s“,
   „Frame 327–738“, „zoom_rein/schwenk/zoom_raus“, `reel_bauen` „clipped to asset end“) und rohe
   ffmpeg-Fehler im Befund („Abholung: Render fehlgeschlagen: r code -22 (Invalid argument) …“) stehen
   ungefiltert vor dem Betreiber.
3. **Bestellen verlangt Wissen über Interna.** Dateinamen aus den Medien abtippen, Laura-Video-IDs
   kennen, Hexfarben eintippen, Stimmenname raten. Beide Fieldsets immer sichtbar, unabhängig von der Art.
4. **Marke wird nicht genutzt.** Ohne eingetippte Farben nimmt der Skill „dunkles Petrol `#0f2422`“
   (`video_claw/skills/reel-aus-bildern/SKILL.md:19`) – das Markenprofil (Akzent `#5b3fd6`, Logo) der
   Firma fließt nicht automatisch ein; `api/video.py` liest kein Profil.
5. **Kein Nachbessern.** Nach „fertig“ gibt es nur Posten; nach „Fehler“ nichts. Kein „Nochmal mit
   Änderung“, kein „Neu versuchen“, kein Bezug zwischen Fassungen.
6. **Nur LinkedIn.** Kein Weg zu Instagram/Reels-Kanälen, kein Herunterladen-Hinweis, keine Verbindung
   zum Kampagnenplan (Art „Video“ existiert dort, `sales-mcp/ui_plan.py:21`).
7. **Datenschutz-Falle bleibt unsichtbar.** Laura-Aufnahmen zeigen teils reale Kontakte (Memory
   „Video-Claw“); der Claw notiert das nur als Text im Protokoll, die Seite hebt es nicht hervor.

### 1.3 Lösungsansätze

**A – Galerie + geführte Bestellung (Formulare in Schritten, ohne JS)**
- Übersicht als Karten-Raster im 9:16-Format (Titel, Status-Chip, Länge, Art), Reiter „Fertig · In Arbeit
  · Fehlgeschlagen · Archiv“. Detailseite `/marketing/reels/<id>` mit großem Video, Sprechertext,
  Post-Formular und ausklappbarem „Was der Claw gemacht hat“ (Protokoll, übersetzt/gekürzt).
- Bestellung als 3 Schritte (GET-Parameter tragen den Zwischenstand): 1. Art wählen (drei Karten),
  2. Material wählen (Medien-Raster mit Kontrollkästchen bzw. Laura-Liste mit Titel/Länge statt IDs),
  3. Thema, Text, Länge, Stimme (Auswahlliste) → Bestellen. Farben/Logo kommen **automatisch** aus dem
  Markenprofil (API liest den Spiegel `marke` der Firma, Feld nur noch „abweichend“).
- „Nochmal mit Änderung“: neuer Auftrag mit `briefing.vorher = <id>` + Änderungswunsch-Text.
  „Neu versuchen“ bei Fehler. „Archivieren“ blendet aus.
- Fehlertexte: Befund-Übersetzung in der API (bekannte Muster → Satz), Rohtext nur im Ausklapper.
- Vorteile: bleibt im sales-ui-Muster, kein JS, kleine Schritte, nutzt vorhandene Kette unverändert.
  Nachteile: Schritt-Formulare ohne JS sind etwas umständlich (Seitenwechsel je Schritt); Galerie braucht
  ein Vorschaubild (Poster) für schnelle Übersicht – sonst lädt jede Karte ein Video (`preload=metadata`).

**B – Reel-Chat (wie Marke/Editor: „Mach ein Reel über X“)**
- Seite = Galerie + Chat mit dem Marketing-Agenten, der `reel_beauftragen` schon kann.
- Vorteile: kein Formularwissen nötig; Agent sucht Material selbst. Nachteile: übernimmt alle Schwächen
  des Marken-Chats (Thema 2), schwer nachvollziehbar, was bestellt wurde; Chat ohne JS = Meta-Refresh.

**C – Reels aus dem Kampagnenplan heraus**
- Plan-Eintrag der Art „Video“ bekommt „Reel bauen lassen“ (Thema/Termin aus dem Eintrag); die Reels-Seite
  wird reine Galerie/Ablage.
- Vorteile: Reels entstehen dort, wo geplant wird. Nachteile: hängt am Kampagnenplan-Umbau (Wunschliste B),
  ersetzt die freie Bestellung nicht.

**Empfehlung: A**, mit dem Hook aus C als späterer Zusatz (ein Link „Reel bauen lassen“ aus dem Plan-Eintrag
öffnet Schritt 1 mit vorbefülltem Thema). B nicht, solange der Marken-Chat nicht überzeugt.

### 1.4 Fragen an den Betreiber

R1. Wofür sind die Reels vor allem?
  (a) LinkedIn-Posts der Firma · (b) Instagram/TikTok/YouTube Shorts · (c) Website/Präsentation beim
  Kunden · (d) Mehreres – dann bitte Reihenfolge.
R2. Woraus entstehen sie meistens?
  (a) eigene Bilder aus den Medien · (b) Laura-Aufnahmen (Bildschirm/Kamera) · (c) Kurzfassung eines
  langen Videos · (d) KI-Bilder, die eigens erzeugt werden (FLUX, ~2 min/Bild) – neu.
R3. Wie willst du nachbessern?
  (a) neuer Lauf mit Änderungswunsch als Satz („kürzer, anderer Einstieg“) · (b) Sätze/Szenen einzeln
  ändern (Schnittliste bearbeiten, deutlich größer) · (c) reicht „nochmal bauen“.
R4. Stimme: (a) eine feste Markenstimme je Firma · (b) Auswahl aus einer Liste je Reel · (c) eigene Stimme
  klonen (Hinweis „Stimme: KI“ bleibt).
R5. Farben/Logo: (a) immer aus dem Markenprofil, nicht änderbar · (b) Markenprofil vorbelegt, je Reel
  änderbar.
R6. Soll der Marketing-Agent weiter selbst Reels bestellen dürfen (Budget 10/Tag)? (a) ja · (b) nur
  Vorschläge, du bestellst.

### 1.5 Task-Skizze (Variante A)

| # | Task | Dateien |
|---|------|---------|
| R-T1 | Befund-Übersetzung + Archiv-Feld (`archiviert boolean`) und Bezug `vorher uuid` in `video_auftraege`; Funktionen `video_archivieren`, `video_neu_versuchen` | MOS `db/0NN_reels_galerie.sql` + `verify_0NN.sql` (Nummer bei Umsetzung frei prüfen, 074 ist evtl. schon reserviert), `api/video.py`, `api/tests/test_video*.py` |
| R-T2 | Markenprofil ins Briefing: API füllt `farben`/`logo` aus dem Marken-Spiegel, wenn leer; Skill-Rückfall Petrol entfällt | MOS `api/video.py`, `api/marke.py` (Lesehelfer), `video_claw/skills/reel-aus-bildern/SKILL.md`, Tests |
| R-T3 | Poster je Reel (erstes Bild als JPG beim Abholen, `vid-…-poster.jpg`) – nur wenn R1/Galerie bestätigt | MOS `api/video.py` (`_speichern`), SC `sales-mcp/medien.py` (Namensmuster), Tests |
| R-T4 | Galerie-Übersicht mit Reitern + Detailseite `/marketing/reels/<id>` | SC `sales-mcp/ui_reels.py`, `ui.py` (CSS-Klassen Raster), `tests/test_reels.py`, `tests/test_darstellung.py` |
| R-T5 | Bestellung in 3 Schritten (Art → Material-Auswahl aus Medien/Laura-Liste → Text/Stimme) | SC `ui_reels.py`; MOS `api/video.py` (Laura-Materialliste für das Pult, z. B. `GET /api/pult/video/material`), `video_claw/laura_api.py` |
| R-T6 | „Nochmal mit Änderung“, „Neu versuchen“, „Archivieren“ | SC `ui_reels.py`; MOS `api/video.py`, `workers/video_claw.py` (`nutzer_nachricht` mit Änderungswunsch + Vorgänger-Protokoll) |
| R-T7 | Deploy (nur nach Betreiber-OK): Migration → API VM/PC → Video-Arbeiter neu | – |

---

## Thema 2: Marken-Chat (Seite „Marke“, `/marketing/layouts`)

### 2.1 Ist-Stand (Code)

- Seite SC `sales-mcp/ui_marke.py` (581 Z.), Route `SEITE = "/marketing/layouts"` (`:29`). Aufbau in
  `marke()` (`:387-421`), Reihenfolge fest: Firmen-Umschalter → Erklärsatz → **Profil-Karte**
  (`profil_html` `:208`: Akzent/Fläche/Grund/Text, Schriftmuster, Logo hell + dunkel als data-URL, nur
  „Ton“ und „Zielgruppe“ gekürzt auf 2 Zeilen/160 Zeichen `:32`) → Link „Profil bearbeiten“ →
  Übernahme-Status → Live-Spur → „Letzte Übernahme“ → **Wissens-Lauf** (`wissen_html` `:300`) →
  **Chat** (`chat_html` `:324`) → **Eingabe** (`formular_html` `:344`, Nachricht + bis 5 Dateien) →
  **Vorschlag** mit iframe-Vorschau Mail/Handy und „Übernehmen“ (Häkchen Pflicht) / „Verwerfen“
  (`vorschlag_html` `:356`).
- „Profil bearbeiten“ (`?bearbeiten=1`, `bearbeiten_html` `:168`) schickt das Formular **an den Agenten**
  (Art `bearbeitung`, `:536`) – es gibt bewusst keinen direkten Schreibweg (Spec 2026-10-07 §2).
- Meta-Refresh 5 s solange Chat/Bearbeitung/Übernahme läuft (`REFRESH_S` `:34`, `:411-419`); der
  Wissens-Lauf lädt nie neu (Ruling R7).
- API MOS `api/marke.py`: `GET /api/pult/marke` liefert die **letzten 10** Chat-/Bearbeitungs-Aufträge
  (`:119`), offenen Vorschlag, Spiegel, Profil, Wissens-Stand. `POST /marke/chat` (`:179`),
  `/marke/bearbeiten` (`:212`), `/marke/vorschlaege/{vid}/uebernehmen|verwerfen` (`:225`, `:238`).
- Arbeiter MOS `workers/marken_arbeiter.py` (763 Z.): Chat → Claude über Shim :8117 **ohne Werkzeuge**
  (Docstring `:3-4`), liest Webseite (erste URL), Uploads, PDFs (`pdf_bilder`), Firmenwissen
  (`claw/markenwissen.laden` `:423`, bis 200 Dateien/30 000 Zeichen Budget `markenwissen.py:27`),
  Logo-Bearbeitung (`claw/logo_bearbeiten.py`) → Vorschlag. Übernehmen schreibt
  `~/.rowboat/knowledge/companys/<Firma>/Marke.md` (+ `logo.png`, `logo-dunkel.png`, `Marke-Verlauf/`),
  spiegelt nach `marketing` (Migrationen `064_marke.sql`, `065_denken.sql`, `066_marke_exakt.sql`) und stößt
  den Wissens-Lauf (`workers/wissen_arbeiter.py`, Rowboat) an. Abgleich Marke.md ↔ Spiegel alle 10 min.
- Firmenwissen heute: `companys/VibeMind/` (Marke.md, Markenhandbuch.md, Agent-Notizen/, Marke-Verlauf/,
  Logos), `companys/fin2gether/` (Marke.md, Logo, Agent-Notizen/, Marke-Verlauf/).

### 2.2 Was heute schwach ist

Belegt mit `marketing_layouts_d.png` (2 116 px; Chat mit 8 Runden):
1. **Reihenfolge gegen den Lesefluss.** Eingabe steht unter dem ganzen Verlauf, der **Vorschlag** (das
   eigentliche Ergebnis) steht noch **darunter** – man muss nach jeder Antwort ganz nach unten scrollen
   und das Ergebnis hinter dem Eingabefeld suchen.
2. **Chat ohne Chat-Optik.** Frage und Antwort sind zwei kaum unterscheidbare Blöcke (Klassen
   `chat-du`/`chat-agent`), kein Absender, keine Zeit; „Profil bearbeitet (Formular)“ erscheint als
   Nachricht des Betreibers, obwohl er nichts geschrieben hat.
3. **Jargon und Innereien.** „Wissen aktualisiert: 0 Dateien“, „Wissen-Lauf: 40 von 291 Dokumenten
   (Obergrenze 40)“, „Markenhandbuch: companys/VibeMind/Markenhandbuch.md“, „Gedanken & Schritte“ an jeder
   Antwort, Seitentitel „Marke“ unter URL `layouts`.
4. **Agent widerspricht sich / Fähigkeiten unklar.** Im Verlauf sagt er erst „Freistellen kann ich leider
   nicht“, zwei Runden später „Mach ich: … farbbasierte Freistellung“. Er „sucht im Web“, obwohl der
   Arbeiter ohne Werkzeuge läuft – die Antwort kann erfunden sein (die Seite zeigt nicht, ob eine Quelle
   wirklich gelesen wurde). Für den Betreiber ist nicht erkennbar, was der Agent kann.
5. **Zu viele Schritte für Kleinigkeiten.** Jede Änderung (auch ein Satz im Ton) = Nachricht → warten (PC
   muss laufen) → Vorschlag → Häkchen + Übernehmen → warten → Wissens-Lauf. Kein „Was ändert sich?“ –
   der Vorschlag zeigt das ganze Profil, nicht den Unterschied zum aktuellen.
6. **Profil nur zur Hälfte sichtbar.** „Wer wir sind“, „Angebote“, „Do & Don’ts“, „Fakten“, „Bildstil“
   sieht man nur im Bearbeiten-Formular; die Karte zeigt Ton/Zielgruppe gekürzt.
7. **Logo-Darstellung.** Die dunkle Fassung wird auf weißem Grund gezeigt (schwarzes Quadrat mit weißen
   Wellen im Screenshot) – sie gehört auf eine dunkle Fläche (`logo_fassungen_html` `:144` macht es für
   den Vorschlag richtig, `profil_html` `:227-232` nicht).
8. **Verlauf abgeschnitten.** Nur die letzten 10 Runden (`api/marke.py:119`), ohne Hinweis.

### 2.3 Lösungsansätze

**A – Aufräumen im bestehenden Ablauf (Profil-Karte + Chat neu angeordnet)**
- Zwei Reiter: **„Profil“** (vollständig, alle 7 Abschnitte, Logo hell/dunkel auf passender Fläche,
  Stand) und **„Mit dem Agenten“** (Chat).
- Im Chat-Reiter: offener **Vorschlag als Karte ganz oben** mit „Das ändert sich“ (Unterschied je Feld/
  Abschnitt: vorher → nachher) + Übernehmen/Verwerfen; darunter Verlauf als Blasen (du rechts, Agent
  links, Zeit), **Eingabe direkt unter der letzten Nachricht** mit Anker `#eingabe`.
- Wissens-Lauf als eine Statuszeile („Firmenwissen ist aktuell“ / „wird aufgefrischt“), Details
  ausklappbar. „Gedanken & Schritte“ nur ausklappbar an der letzten Antwort.
- Fähigkeiten-Leiste über der Eingabe („Ich kann: Webseite lesen · PDFs lesen · Logo freistellen ·
  Farben/Schriften vorschlagen. Ich kann nicht: im Web suchen“), und der Prompt bekommt dieselbe Liste
  (gegen widersprüchliche Antworten).
- Vorteile: keine neue Technik, Kette und Tests bleiben; behebt 1–3, 5 (teils), 6–8. Nachteile: der
  Zwei-Schritt „Vorschlag → Übernehmen“ bleibt.

**B – Profil zuerst, Agent je Abschnitt („Ändern lassen“)**
- Profil als Karten je Feld/Abschnitt. Jede Karte hat „Selbst ändern“ (direktes Formular, schreibt
  über den Agenten wörtlich wie heute `bearbeitung`) und „Vom Agenten umschreiben lassen“ (kleines
  Feld: „lockerer“, „kürzer“). Freier Chat nur noch für Neues (Logo, Webseite, PDFs).
- Kleine Änderungen werden **ohne Häkchen-Schritt** übernommen (der Agent prüft nur), große (Logo,
  Farben, mehrere Abschnitte) weiterhin als Vorschlag.
- Vorteile: kürzester Weg für die häufigsten Änderungen, Ergebnis immer sichtbar. Nachteile: Änderung der
  Spec-Regel „kein direkter Schreibweg“ und der Übernahme-Logik (API + Arbeiter + Migration für eine Art
  `abschnitt`); mehr Arbeit.

**C – Marken-Chat ins Editor-Bundle (React, Live-Strom)**
- Gleiche Oberfläche wie der Newsletter-Assistent (Editor `editor/`, Strom `chat.json`), Antworten
  laufen live statt Meta-Refresh.
- Vorteile: modernes Chat-Gefühl, Denkspur live. Nachteile: zweite Seite mit JS-Bundle (Ausnahme von der
  No-JS-Regel), Build/Tests, Handy-Frage wie beim Editor offen; groß.

**Empfehlung: A jetzt, B als zweite Stufe**, wenn die Antworten auf M2/M3 zeigen, dass vor allem kleine
Text-Änderungen nerven. C nicht – der Gewinn (Live-Text) rechtfertigt die JS-Ausnahme nicht.

### 2.4 Fragen an den Betreiber

M1. Was stört dich am meisten? (mehrere möglich)
  (a) Aussehen/Übersicht (alles untereinander, Vorschlag ganz unten) · (b) der Agent antwortet falsch oder
  widersprüchlich · (c) zu viele Schritte bis eine Änderung drin ist · (d) der Teil „Wissen“ ist
  unverständlich · (e) etwas anderes: ___
M2. Wofür benutzt du den Chat meistens?
  (a) einmalig die Marke aufsetzen (Logo, Farben, Webseite) · (b) laufend Texte schärfen (Ton, Angebote) ·
  (c) Firmenwissen einspielen (PDFs, Unterlagen), auch über die Marke hinaus.
M3. Dürfen kleine Text-Änderungen **ohne** „Häkchen + Übernehmen“ direkt gelten?
  (a) ja, Text sofort, Farben/Logo weiter mit Vorschlag · (b) nein, alles weiter mit Vorschlag.
M4. Soll der Marken-Agent wirklich im Web suchen können (eigenes Werkzeug, Quellen werden gezeigt)?
  (a) ja · (b) nein – dann sagt er klar, dass er es nicht kann.
M5. Soll der Chat-Verlauf vollständig bleiben (mit „Ältere laden“) oder reichen die letzten 10?
  (a) vollständig · (b) letzte 10 reichen.

### 2.5 Task-Skizze (Variante A)

| # | Task | Dateien |
|---|------|---------|
| M-T1 | API liefert Unterschied Vorschlag ↔ aktuelles Profil (`aenderungen: [{feld, vorher, nachher}]`) und Gesamtzahl der Runden (+ optional `vor=<zeit>` zum Nachladen) | MOS `api/marke.py` (`marke_stand` `:101`), `api/tests/test_marke*.py` |
| M-T2 | Seite in zwei Reiter (`?reiter=profil|chat`), Profil vollständig (alle `ABSCHNITTE`), dunkles Logo auf dunkler Fläche | SC `sales-mcp/ui_marke.py` (`profil_html`, `marke`), `ui.py` (CSS Reiter/Logo-Fläche), `tests/test_marke_seite.py` |
| M-T3 | Chat-Reiter: Vorschlag-Karte oben mit „Das ändert sich“, Blasen mit Absender/Zeit, Eingabe unter der letzten Nachricht, Anker; „Formular“-Runden als Systemzeile | SC `ui_marke.py` (`chat_html`, `vorschlag_html`, `formular_html`), `ui.py` (CSS), Tests |
| M-T4 | Wissens-Lauf als eine Statuszeile, Details ausklappbar; Texte ohne Jargon | SC `ui_marke.py` (`wissen_html`, `letzte_html`), `tests/test_darstellung.py` |
| M-T5 | Fähigkeiten-Liste: eine Quelle (Konstante im Arbeiter), im Prompt und über die API auf der Seite | MOS `claw/marken_prompt.py`, `workers/marken_arbeiter.py`, `api/marke.py`; SC `ui_marke.py`; Tests |
| M-T6 | (je nach M4) Websuche als echtes Werkzeug mit Quellenangabe – sonst entfällt | MOS `claw/webseite.py`, `workers/marken_arbeiter.py` |
| M-T7 | Deploy (nur nach Betreiber-OK): API VM/PC → Chat-/Marken-Arbeiter neu → sales-ui | – |

---

## Thema 3: Struktur-Graph („wer hat wen eingeladen“)

### 3.1 Ist-Stand (Code)

- **Es gibt keine „eingeladen von“-Beziehung.** Nächstliegendes:
  - Empfehlungslisten (SC `sales-mcp/empfehlungen.py`, Tabelle `empfehlungslisten` in `db/provision.sql:240`):
    Kopf mit `empfohlen_von_lead` (uuid → `leads`), `empfohlen_von_name`, `berater_name`, **`struktur` (Freitext,
    nur ein Kopf-Feld des Vordrucks)**, `bereiche`. Jede Zeile wird ein Kontakt mit
    `enrichment.empfehlung = {liste_id, …, ergebnis}` (`empfehlungen.py:228`) und einer Aktivität
    `empfehlung` (`:235`). Vordruck „Mitarbeitervorschläge“ (`VORDRUCKE` `:36`, max 25, Alter ab 22) setzt
    Bereich `mitarbeiter` (`:258`).
  - Einordnung (SC `server.py:1166-1245`): `enrichment.art` (person/firma) und `enrichment.bereiche`
    (u. a. `mitarbeiter`), einziger Schreibweg `_einordnen`, jede Änderung als Aktivität `einordnung`,
    **ohne DDL** (alles in `leads.enrichment`).
  - Die Kontakte-Ansicht nennt `mitarbeiter` ausdrücklich **„Mitarbeiter-Kandidaten“** (`ui.py:3321`,
    Filter `:3343`) – also Bewerber, nicht Teammitglieder.
- Daraus lässt sich heute nur „Person X wurde von Y **empfohlen**“ ablesen (Empfehlungsgeber → Zeile),
  nicht „X ist Mitglied meiner Struktur und wurde von Y **eingeladen**“.
- Darstellung ohne JS ist möglich: Inline-`<svg>` im HTML ist kein nachgeladenes Objekt und fällt nicht
  unter `default-src 'none'`; Stile über `style-src 'unsafe-inline'` (`ui.py:438`), Links per `<a>` im SVG,
  Hinweise per `<title>` (Tooltip ohne JS). Ein eigenes Bundle ginge wie der Kalender
  (`ui_kalender.py:42` CSP-Zusätze `script-src 'self'`, `:272-275`, `:529`).
- Mehrere Läden haben je ein eigenes Schema (`provision.sql`, `sales`, `sales_<laden>`); eine Struktur
  gehört also natürlich zu einem Laden (fin2gether = Ivans Laden).

### 3.2 Was heute schwach ist / fehlt

1. Kein Datenmodell für Mitgliedschaft und Einladung; das Feld `struktur` ist nur Kopftext einer Liste.
2. „Mitarbeiter“ ist doppeldeutig (Kandidat vs. Mitglied).
3. Unklar, was „6 Level“ bedeutet (siehe Frage S1) – das ändert das Datenmodell grundlegend.
4. Keine Erfassung: weder Feld auf der Kontaktseite noch Agent-Werkzeug noch Import.
5. Keine Graph-Darstellung irgendwo in sales-ui (einziges SVG ist das Favicon, `ui.py:1677`).

### 3.3 Lösungsansätze

**Datenmodell**

| | D1 – `enrichment.eingeladen_von` (kein DDL) | D2 – eigene Tabelle `struktur` (empfohlen) | D3 – aus Empfehlungslisten ableiten |
|---|---|---|---|
| Form | `leads.enrichment.struktur = {mitglied: true, eingeladen_von: <lead_id>, stufe?: 1..6, seit}`, Schreibweg wie `_einordnen` | `struktur_mitglieder(lead_id PK → leads, eingeladen_von uuid null → leads, stufe smallint null check 1..6, seit date, aktiv bool, geaendert_am)` in `provision.sql`, Zyklus-Prüfung im Schreibweg, Ebene per `WITH RECURSIVE` | Kanten = `empfohlen_von_lead` → Zeilen der Mitarbeitervorschläge mit Ergebnis „Abschluss“ |
| Vorteile | keine Migration, Muster existiert, Aktivitäten-Historie gratis | Fremdschlüssel, Eindeutigkeit, Abfragen schnell und klar, löschfest (`on delete set null`) | sofort Daten, keine Erfassung |
| Nachteile | keine Integrität (gelöschter Einlader), rekursive Abfrage über jsonb, Zyklen nur im Code | DDL für alle Läden (`provision.sql` + `pruefe-laden.sql`), Grant je Laden | Empfehlung ≠ Einladung; deckt nur Neue ab, nicht den Bestand |

**Erfassung**
- E-a: Feld „Eingeladen von“ (Auswahl unter den Mitgliedern) + „Stufe“ auf der Kontaktseite `/kontakte/{id}`.
- E-b: Agent-Werkzeug `struktur_eintragen(lead_id, eingeladen_von, stufe)` – nur auf Zuruf, wie
  `kontakt_einordnen` (`server.py:1246`).
- E-c: Import einer Liste (CSV/Excel: Name, Eingeladen von, Stufe) mit Vorschau und Namensabgleich.
- E-d: Vorschlag aus Empfehlungslisten (D3) als „Übernehmen?“-Liste.

**Darstellung**

| | G1 – serverseitiges Inline-SVG (empfohlen) | G2 – eigenes Bundle wie Kalender | G3 – HTML-Baum (verschachtelte Liste mit CSS-Linien) |
|---|---|---|---|
| Wie | Python berechnet Ebenen-Layout (Zeile je Ebene 1–6, Knoten mit Zahl + Name, Kanten Einlader → Eingeladener), `<a href="/kontakte/<id>">` je Knoten, `?wurzel=<id>` zeigt einen Teilbaum | z. B. Cytoscape.js/d3 im Bundle `kalender/`-Muster, `static/struktur/`, Daten über `/struktur.json` | `<ul><li>` mit Einrückung je Ebene, Ebenenzahl als Chip |
| Vorteile | kein JS, CSP unverändert, testbar per String, druckbar, Links und Tooltips gehen | Zoomen, Ziehen, Suchen, große Netze | trivial, barrierearm, Handy-tauglich |
| Nachteile | kein Zoom/Ziehen; ab ~150 Knoten breit → Teilbaum-Links und `overflow-x:auto` nötig | zweite JS-Ausnahme, Build + Vitest + Paket-Test, Bundle-Pflege | ist kein „Graph“ im Sinne des Wunsches |

**Empfehlung: D2 + E-a/E-b (E-c, E-d später) + G1 mit G3 als Handy-/Listenansicht.** Ebenen werden
relativ zum Betreiber berechnet (Betreiber = Wurzel, von ihm direkt Eingeladene = Ebene 1, … bis 6;
tiefer wird nicht gezeigt bzw. als „6+“ gesammelt) – **sofern S1 die Ebenen als Einladungstiefe bestätigt**.
Sind die 6 Level Karrierestufen, bleibt D2, aber `stufe` wird Pflichtfeld und die Zahl am Knoten zeigt
die Stufe statt der Tiefe.

### 3.4 Fragen an den Betreiber

S1. Was sind die „6 Level“?
  (a) Einladungstiefe: 1 = von dir direkt eingeladen, 2 = von denen eingeladen, … bis 6 ·
  (b) Karrierestufen in der Struktur (z. B. Trainee … Direktor), unabhängig davon, wer wen eingeladen hat ·
  (c) beides – Zahl am Knoten = Stufe, Anordnung nach Einladungstiefe.
S2. Wer ist ein „Mitglied“?
  (a) ein Kontakt, den du ausdrücklich als Mitglied markierst (neues Kennzeichen, „Mitarbeiter-Kandidat“
  bleibt Kandidat) · (b) jeder Kontakt mit Bereich „Mitarbeiter“ · (c) eigene Personenliste außerhalb der
  Kontakte.
S3. Wie kommen die Beziehungen hinein? (mehrere möglich)
  (a) von Hand auf der Kontaktseite · (b) per Zuruf an den Sales-Agenten · (c) Import aus einer Liste,
  die es schon gibt (welches Format? Excel/CSV/PDF aus fin2gether?) · (d) aus den Mitarbeitervorschlägen,
  wenn Ergebnis „Abschluss“.
S4. Für welchen Laden und wie groß?
  (a) nur Ivans Laden (fin2gether) · (b) jeder Laden · Ungefähre Größe: (i) < 50 · (ii) 50–300 · (iii) mehr.
S5. Was soll der Graph können?
  (a) nur anschauen + auf ein Mitglied klicken (Kontaktseite) · (b) zusätzlich Teilbaum ab einem Mitglied ·
  (c) zusätzlich Zahlen je Mitglied (Abschlüsse, Termine) · (d) zoomen/ziehen wie eine Mindmap (dann
  eigenes JS-Bundle).

### 3.5 Task-Skizze (Empfehlung D2 + E-a/E-b + G1/G3)

| # | Task | Dateien |
|---|------|---------|
| S-T1 | Tabelle `struktur_mitglieder` in allen Läden (+ Grants, Prüfung) | SC `db/provision.sql`, `db/pruefe-laden.sql`, `db/laden-anlegen.sql`, `sales-mcp/tests/test_struktur_schema.py` (neu) |
| S-T2 | Modul `struktur.py`: eintragen/ändern/entfernen (Zyklus- und Tiefenprüfung, Aktivität `struktur`), `baum(wurzel=None)` mit Ebenen per `WITH RECURSIVE` | SC `sales-mcp/struktur.py` (neu), `sales-mcp/tests/test_struktur.py` (neu) |
| S-T3 | SVG-Layout rein in Python (Ebenen-Zeilen, Knoten mit Zahl + Name, Kanten, Links, `<title>`), Farben über CSS-Variablen per `class` | SC `sales-mcp/struktur_svg.py` (neu), `tests/test_struktur_svg.py` (neu, inkl. Escape-Test für Namen) |
| S-T4 | Seite `/struktur` (Graph + Listenansicht-Reiter, `?wurzel=`), Navigation unter „Kontakte“ | SC `sales-mcp/ui_struktur.py` (neu), `ui.py` (Navigation `:1452`, CSS, Route-Einbindung), `tests/test_darstellung.py`, `tests/test_ui.py` |
| S-T5 | Kontaktseite: Karte „Struktur“ (Mitglied ja/nein, Eingeladen von, Stufe) mit CSRF-Formular | SC `sales-mcp/ui.py` (Kontaktseite), `tests/test_kontaktprofil.py` |
| S-T6 | Agent-Werkzeug `struktur_eintragen` / `struktur_zeigen` (nur auf Zuruf, sendet nichts) + Regeln | SC `sales-mcp/server.py` (Werkzeugliste `:8794`), `tests/test_agents_regeln.py` |
| S-T7 | (je nach S3) Import mit Vorschau / Übernahme aus Mitarbeitervorschlägen | SC `sales-mcp/ui_struktur.py`, `struktur.py`, `empfehlungen.py` |
| S-T8 | Deploy (nur nach Betreiber-OK): `provision.sql` auf VM/Läden → sales-ui | – |

---

## Empfohlene Reihenfolge

1. **Struktur-Graph zuerst klären und bauen** – er ist neu, rein sales-claw (keine Marketing-Kette, kein
   PC-Arbeiter), und nach S1/S2 ist das Datenmodell eindeutig. Fragen S1–S3 entscheiden alles; der Rest
   ist mittlerer Umfang (S-T1 bis S-T6).
2. **Marken-Chat Variante A** – überwiegend Darstellung in `ui_marke.py` plus kleine API-Erweiterung;
   macht die Marke sichtbar „cool“ und liefert die vollständige Profil-Quelle, die Reels (R-T2) danach
   für Farben/Logo nutzen.
3. **Reels Variante A** – größter Umfang (Migration, API, Arbeiter, Seite), profitiert von 2 (Markenprofil)
   und am besten nach dem Kampagnenplan-Umbau (Wunschliste B), damit der „Reel bauen lassen“-Link aus
   dem Plan gleich mitkommen kann.

Alle drei warten auf die Antworten unten; kein Task startet vorher.

## Gesammelte Fragen an den Betreiber

**Reels:** R1 Zweck (LinkedIn / Insta-TikTok-Shorts / Website / mehreres) · R2 Quelle (eigene Bilder /
Laura-Aufnahmen / Kurzfassung / KI-Bilder) · R3 Nachbessern (Änderungswunsch-Satz / Szenen einzeln /
nur neu bauen) · R4 Stimme (fest je Firma / Auswahl / geklont) · R5 Farben/Logo (immer Markenprofil /
vorbelegt, änderbar) · R6 Agent darf weiter selbst bestellen (ja / nur Vorschläge).

**Marken-Chat:** M1 Was stört am meisten (Übersicht / falsche Antworten / zu viele Schritte / „Wissen“
unverständlich / anderes) · M2 Hauptnutzung (einmal aufsetzen / laufend Texte / Firmenwissen einspielen) ·
M3 kleine Textänderungen direkt ohne Übernehmen (ja / nein) · M4 echte Websuche für den Agenten (ja /
nein) · M5 Verlauf vollständig oder letzte 10.

**Struktur:** S1 Was sind die 6 Level (Einladungstiefe / Karrierestufe / beides) · S2 Wer ist Mitglied
(eigenes Kennzeichen / Bereich Mitarbeiter / eigene Liste) · S3 Erfassung (Kontaktseite / Agent / Import
– welches Format? / aus Mitarbeitervorschlägen) · S4 welcher Laden und wie groß · S5 Funktionen
(anschauen / Teilbaum / Kennzahlen / Zoomen-Ziehen → JS).
