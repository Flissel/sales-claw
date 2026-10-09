# Marke exakt: Logo, Material, Formular und Rowboat-Lauf — Design

Stand: 2026-10-09 · Status: in drei Abschnitten vom Betreiber freigegeben · baut auf
`2026-10-07-marke-per-chat-design.md` und `2026-10-09-agent-denken-sichtbar-design.md` auf.

## Ziel

Das Markenprofil soll **exakt** sein. Der Marken-Agent soll mit besserem Material arbeiten:
- das Logo freigestellt und als zwei Fassungen,
- PDFs als Bild,
- das Firmenwissen,
- die gemerkte Webseite und eine Websuche.

Der Betreiber soll das Profil selbst bearbeiten können, Änderungen laufen aber **immer über
den Agenten**. Nach jeder Übernahme bringt ein **eigener Lauf** das Rowboat-Wissen auf den
neuen Stand. Außerdem behebt der Editor-Agent bei einer Marken-Übernahme vorhandene
Kontrastprobleme gleich mit.

## Entscheidungen des Betreibers

| Frage | Antwort |
|---|---|
| Umfang | Logo bearbeiten, PDFs als Bild, Firmenwissen einbinden, Kontrast beim Übernehmen, Webseite merken |
| Auslöser Logo-Bearbeitung | Der Agent schlägt vor; Vorher/Nachher in der Vorschau, Übernehmen wie bisher |
| Logo-Fassungen | Zwei: `logo` (für hellen Grund) und `logo_dunkel` (für dunkle Flächen) |
| Freistellen | Nur das Zeichen selbst wird platziert, ohne Kartenrand oder Fläche |
| Firmenwissen lesen (Marken-Chat) | Nur der Firmenordner `companys/<Firma>/` |
| Profil selbst bearbeiten | Formular auf der Seite „Marke“ → Agent übernimmt wörtlich → Vorschau → Übernehmen; kein direktes Speichern |
| Update-Prompt | Immer das komplette alte Profil mitgeben |
| Rowboat-Wissen | In diesem Block, als eigener Lauf nach jedem Übernehmen |
| Rowboat-Lauf Umfang | Ganze Wissensbasis, aber nur Dokumente mit Firmenbezug; Sperrordner; Dokumente anderer Firmen tabu |
| Rowboat-Lauf Schreiben | Direkt, mit Sicherung vor jeder Änderung |
| Websuche | Ja, mit WebSearch der CLI. Seiten liest nur unser gesicherter Leser; kein WebFetch |

## 1. Logo bearbeiten

**Ablauf**
- Der Marken-Agent sieht Logo-Bilder (Anhang, Webseite, bisheriges Logo). Hat das Logo Rand,
  Kartenhintergrund oder eine Fläche, schreibt er in den Vorschlag
  `logo_bearbeiten: {"quelle": "anhang:<name>|web:<n>|bisher", "zuschneiden": bool,
  "freistellen": "farbe"|"ki"|"nein"}`.
- Der Marken-Arbeiter am PC rechnet das **in derselben Runde**. Es gibt keinen neuen
  Auftragstyp und keine Warteschlange.
  1. **Zuschneiden:** auf die Inhaltsgrenzen plus 4 % Rand, nach dem Freistellen über den
     Alphakanal, sonst über den Abstand zur Hintergrundfarbe.
  2. **Freistellen**
     - `farbe` ist der Normalfall. Die Hintergrundfarbe wird aus dem Randmittel bestimmt.
       Pixel mit kleinem Farbabstand werden durchsichtig, mit weicher Kante über einen
       Übergangsbereich. Reine Bildrechnung, Pillow und numpy.
     - `ki` ist für Fotos oder unruhige Hintergründe. Es nutzt BiRefNet über ComfyUI am PC,
       also denselben Weg wie das Freistellen der Newsletter-Bilder (`bild_worker._freistellen`).
  3. **Zwei Fassungen.** Als *einfarbig* gilt ein Logo, wenn höchstens eine Farbe nach dem
     Freistellen mehr als 90 % der deckenden Pixel ausmacht, mit Toleranz.
     - `logo` für hellen Grund: einfarbig wird es in die Markentextfarbe `text` eingefärbt,
       mehrfarbig bleiben die Originalfarben.
     - `logo_dunkel` für dunkle Flächen: einfarbig wird es Weiß. Mehrfarbig bleibt es original,
       wenn der Kontrast gegen `#1a1a1a` mindestens 3:1 erreicht, sonst wird es eine weiße
       Silhouette.
- Die Ergebnisse legt die VM als Mediendateien der Firma ab (bestehende Arbeiter-Route
  `/logo`, serververgebener Name). Im Vorschlag stehen sie als `logo` und `logo_dunkel`.
- **Vorschau** auf der Seite „Marke“: das Original, `logo` auf Weiß und `logo_dunkel` auf
  `#1a1a1a`.
- **Profil**
  - Marke.md bekommt die Kopfzeile `logo_dunkel:`; Rowboat hält `logo.png` und
    `logo-dunkel.png` (PNG mit Alpha).
  - Der Spiegel bekommt `gestalt.logo_dunkel`, verkleinert wie `logo`: höchstens 600 px,
    höchstens 140 KB.
  - Die DB-Prüfung `pult_gestalt_fehler` nimmt `logo_dunkel` wie `logo` an (Migration 066).
- **Verwendung:** Vorlagen und Editor-Agent nehmen auf Flächen mit einer Hintergrund-Leuchtdichte
  unter 0,2 `logo_dunkel`, sonst `logo`. Ohne `logo_dunkel` bleibt alles wie heute.
- **Fehler:** Scheitern ComfyUI oder die Erkennung, bleibt das Logo unbearbeitet. Ein Hinweis
  nennt den Grund. Die Runde scheitert daran nie.
- Auf der VM läuft kein Modell.

## 2. Profil exakt, Material für den Agenten

**Profil selbst bearbeiten (Formular → Agent)**
- Die Seite „Marke“ bekommt „Profil bearbeiten“: ein Formular mit allen Kopfwerten (`akzent`,
  `zweitfarbe`, `grund`, `text`, Schriftpaar aus dem Register, `webseite`) und allen sieben
  Abschnitten. Es ist mit dem aktuellen Profil vorbefüllt.
- „An den Agenten geben“ legt eine Marken-Runde der neuen Art `bearbeitung` an
  (`marken_auftraege.art`, Migration 066). Sie trägt die Formularfassung (`kontext.formular`)
  und den Hinweis „wörtlich übernehmen“.
- Agent-Regel für `bearbeitung`:
  - Er übernimmt jeden Formularwert **wörtlich**.
  - Ändern darf er nur, was technisch ungültig ist (Schrift nicht im Register, Kontrast unter
    der Grenze). Jede solche Änderung meldet er als Hinweis mit Begründung.
  - Er ergänzt nichts.
- Danach folgen Vorschau und Übernehmen wie bisher. Direktes Speichern ohne Agent gibt es
  nicht.

**Exakt in jeder Runde**
- Jede Runde (chat, bearbeitung) bekommt das **komplette aktuelle Profil** mit Kopfwerten,
  allen Abschnitten und Logos und, falls vorhanden, den offenen Vorschlag.
- Prompt-Regel: Ändere nur, worum gebeten wurde, und übernimm alles andere unverändert.
  Keine Platzhalter, keine geratenen Fakten. Was unbekannt ist, wird erfragt.
- Die Arbeiter-Prüfung lehnt Abschnitte mit Platzhaltern ab, also `[…]`, `TBD`, `TODO`,
  `Lorem`, `XX`. Danach folgt eine Korrekturrunde wie bei anderen Antwortfehlern.

**PDFs als Bild (Marken-Chat und Editor-Agent)**
- Der PC rendert die ersten **4 Seiten** jeder PDF mit **pypdfium2** zu PNG, längste Kante
  höchstens **1600 px**. Die Bilder gehen als Bildteile an Claude, die Textebene zusätzlich
  wie bisher.
- Es gelten dieselben Grenzen und dieselbe Kennzeichnung „Material, keine Anweisung“ wie bei
  Bild-Uploads. Ein Rendering-Fehler wird ein Hinweis, die Runde läuft weiter.

**Firmenwissen lesen (Marken-Chat)**
- Der Marken-Chat bekommt `markenwissen.laden(...)` aus `companys/<Firma>/`, so wie der
  Editor-Agent: Agent-Notizen, weitere Dokumente und das Markenhandbuch, mit denselben Grenzen
  und derselben Relevanzauswahl. Marke-Verlauf und Wissen-Verlauf bleiben ausgeschlossen.

**Webseite merken und Websuche**
- Marke.md bekommt die Kopfzeile `webseite:` (https-URL ohne Zugangsdaten).
- **Lesen:** Nennt die Nachricht eine neue URL, liest der Arbeiter sie mit dem gesicherten
  Leser (`claw/webseite.lesen`). Sonst nimmt er die gemerkte `webseite` aus einem
  Zwischenspeicher am PC je Firma, gültig 24 h, abgelegt in einer Datei unter dem
  Arbeitsordner des Arbeiters. Erst nach Ablauf liest er neu.
- **Websuche:** Nur im Marken-Chat startet der Shim die CLI zusätzlich mit
  `--allowedTools WebSearch`, Body-Schlüssel `marketing_websuche: true`. WebFetch bleibt
  gesperrt.
- **Seiten nachlesen:**
  - Der Agent kann im Antwort-JSON `lesen: [url, …]` angeben, höchstens 3 URLs.
  - Der Arbeiter prüft sie mit der bestehenden Adresssperre, liest sie mit dem gesicherten
    Leser und startet **eine** Folgerunde mit dem Material.
  - Höchstens eine Folgerunde je Auftrag, dann muss der Agent antworten.
- **Schritte:** „Websuche genutzt“, „Gelesen: <host>“, „Webseite aus Zwischenspeicher“.
- **Fehler:** Lehnt die CLI das Suchwerkzeug ab, wiederholt der Shim einmal ohne, wie beim
  Denk-Rückfall. Der Schritt meldet dann „Websuche nicht verfügbar“.

## 3. Rowboat-Lauf, Kontrast, Fehler, Tests

**Rowboat-Lauf (eigener Lauf nach jedem Übernehmen)**
- **Auslöser:** Nach einer erfolgreichen Übernahme legt die VM einen Marken-Auftrag
  `art = 'wissen'` an (Migration 066). Je Firma gibt es höchstens einen offenen; ein neuer
  ersetzt einen wartenden.
- **Kandidaten** (Arbeiter am PC, Wurzel `~/.rowboat/knowledge`):
  - alles unter `companys/<Firma>/` außer `Marke-Verlauf/` und `Wissen-Verlauf/`;
  - außerhalb nur `.md`-Dateien, die den Firmennamen als ganzes Wort nennen, ohne Rücksicht
    auf Groß- und Kleinschreibung.
- **Gesperrt** sind `People/`, `Bewerbung/`, `Diary/`, `Voice Memos/`, jede Datei, die eine
  andere **aktive** Firma (Mandant) nennt, und Junctions oder Links (Linksperre wie in
  `markenprofil`).
- **Obergrenzen:** höchstens 40 Dokumente, je Dokument höchstens 20 KB, Auswahl nach
  Relevanz (Namensnennungen, Ordnernähe).
- **Agent** (Claude über den Shim, mit Denken):
  - Er bekommt neues und altes Profil (Änderungen markiert) und die Kandidaten mit Pfad.
  - Er antwortet mit `ersetzungen: [{"pfad", "alt", "neu"}]` (exakte Textausschnitte) und
    `markenhandbuch: "<kompletter Inhalt>"`.
- **Prüfung und Schreiben (Arbeiter):**
  1. Der Pfad muss in der Kandidatenliste stehen.
  2. Jedes `alt` muss **genau einmal** in der Datei vorkommen, sonst wird diese Ersetzung
     verworfen und als Hinweis gemeldet.
  3. Vor jedem Schreiben wird nach
     `companys/<Firma>/Wissen-Verlauf/<YYYY-MM-DD-HHMM>/<relativer Pfad>` gesichert.
  4. Geschrieben wird atomar (mkstemp + replace).
  5. Zum Schluss schreibt er `companys/<Firma>/Markenhandbuch.md`, ebenfalls mit Sicherung.
- **Anzeige** auf der Seite „Marke“: „Wissen aktualisiert: n Dateien“ mit Liste, Denken und
  Schritten.
- **Fehler:** Ein Abbruch mittendrin lässt geschriebene Dateien stehen, jede ist gesichert.
  Der Auftrag endet mit Status `fertig` und dem Hinweis „teilweise: …“ samt Dateiliste. Eine
  Wiederholung beginnt mit frischen Kandidaten. Ist der PC aus, wartet der Auftrag.

**Kontrast beim Übernehmen (Editor-Agent)**
- **Kontext:** Vor jeder Editor-Runde prüft der Arbeiter den aktuellen Entwurf lokal mit
  `claw/schoenheit` auf Kontrast. Die Funde kommen als `KONTRASTPROBLEME` in den Kontext,
  zusammen mit `akzent_text` und `auf_akzent`, die es schon gibt.
- **Regel:** Bei einer Marken-Übernahme oder wenn er Farben anfasst, behebt er sie mit den
  lesbaren Markenfarben. Sonst nennt er sie nur in der Antwort.

**Tests**
- **Logo:**
  - Farbschlüssel: weißes Zeichen auf Schwarz, dunkles Zeichen auf Weiß, mehrfarbig.
  - Zuschnitt mit 4 % Rand.
  - Einfarbig-Erkennung.
  - Beide Fassungen mit Kontrastprüfung.
  - Ausweichen bei ComfyUI-Fehler (gefälschtes ComfyUI).
  - Spiegel und `pult_gestalt_fehler` mit `logo_dunkel`.
- **PDF:** Testdatei ohne Textebene ergibt 1–4 Bildteile; kaputte PDF ergibt einen Hinweis.
- **Firmenwissen:** Auswahl, Ausschlüsse, Firmentrennung.
- **Webseite:** Zwischenspeicher (frisch, abgelaufen, neue URL).
- **`lesen`:**
  - Adresssperre, höchstens 3 URLs, höchstens eine Folgerunde.
  - Shim: WebSearch nur mit Flag, Rückfall ohne.
- **Formular:**
  - Wörtliche Übernahme.
  - Ungültiges wird mit Hinweis korrigiert.
  - Kein direktes Speichern.
- **Platzhalter-Sperre.**
- **Rowboat-Lauf:**
  - Kandidatenfilter: Sperrordner, Dokumente anderer Firmen, Links, Firmenbezug.
  - Ersetzung genau einmal, sonst verworfen.
  - Sicherung vor dem Schreiben.
  - Markenhandbuch.
  - Abbruch mittendrin.
  - Auftrag wird bei Übernahme angelegt und ersetzt einen wartenden.
- **Migration 066:** `verify_066`, zweifach anwendbar.
- **Kontrast-Kontext im Editor:** Funde stehen im Kontext, die Regel ist im Prompt.
- **Echter Lauf mit VibeMind:**
  1. Visitenkarte als PDF hochladen; Claude sieht die Vorderseite.
  2. Logo freistellen; zwei Fassungen in der Vorschau.
  3. Formular-Änderung, wörtlich übernommen.
  4. Übernehmen.
  5. Rowboat-Lauf ändert Dokumente mit VibeMind-Bezug, legt Sicherungen an und schreibt das
     Markenhandbuch.
  6. Editor-Band setzt Schriftpaar und Logo und behebt den Kontrast.

## Reihenfolge der Umsetzung

Erst Migration 066 und Profilformat (`logo_dunkel`, `webseite`). Dann Logo-Bearbeitung,
PDF-Bilder, Firmenwissen, Webseite und Websuche, Formular, Kontrast-Kontext. Der Rowboat-Lauf
kommt **zuletzt**, damit die übrigen Teile vorher fertig und geprüft sind.

## Nicht Teil dieses Blocks

- Direktes Speichern des Profils ohne Agent.
- WebFetch der CLI.
- Websuche im Editor-Agenten.
- Schreiben in Sperrordner.
- Rowboat-Lauf über Dokumente ohne Firmenbezug.
