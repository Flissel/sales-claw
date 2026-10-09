# Editor: mehrere Runden gleichzeitig, breiterer Chat, Markierungen — Design

Stand: 2026-10-09 · Status: in drei Abschnitten vom Betreiber freigegeben

## Ziel

Der Betreiber soll dem Newsletter-Agenten **gleich die nächste Bitte** geben können, ohne zu
warten, auch für **denselben Entwurf**. Die Chat-Leiste im Editor wird **breiter und ziehbar**.
Zwei Funde aus der Log-Analyse vom 09.10. werden mit behoben:

- Eine liegengebliebene Markierung reiste unbemerkt mit der nächsten Nachricht mit. Dadurch
  verstand der Agent „das aber nicht“ falsch.
- Gescheiterte Bildaufträge verschwanden still.

## Entscheidungen des Betreibers

| Frage | Antwort |
|---|---|
| Welcher Chat größer | Editor-Chat (rechts) |
| „Gleich wieder verfügbar“ | Mehrere Runden gleichzeitig, auch im selben Entwurf |
| Zusammenführung | A: Nachspielen der Änderungsliste auf die neueste Fassung |
| Grenzen | 3 je Entwurf, 3 insgesamt (Editor-Plätze im Arbeiter) |
| Anzeige | Je Runde eigene Zeile; die Fläche aktualisiert sich erst beim Fertigwerden |
| Markierungs-Fix | Teil dieses Blocks |

## 1. Datenbank und Arbeiter

### Migration 067

- Der Index `chat_auftraege_ein_laufender` (höchstens eine `offen`/`in_arbeit`-Runde je
  Inhalt) entfällt. Neu gelten:
  - höchstens **3** Runden `offen`/`in_arbeit` je Inhalt;
  - eine Warteschlange von höchstens **5** Runden `wartet` je Inhalt.
  - Die Anlege-Funktion setzt beides unter Sperre der Inhaltszeile durch. Darüber hinaus
    gibt sie die Meldung „Bitte warten, bis eine Runde fertig ist“ zurück.
- Die bisherige Vormerkung (`wartet`, höchstens eine je Inhalt) geht in dieser
  Warteschlange auf. Eine `wartet`-Runde rückt automatisch nach, sobald ein Platz frei wird.
  Auslöser ist das Ende einer Runde in der DB-Funktion, also ohne Arbeiter-Logik.
- Die Vergabe an den PC erfolgt älteste zuerst, bis zu 3 gleichzeitig. Der Arbeiter holt so
  lange, wie er freie Plätze hat.
- **Stopp:** Er bleibt pro Auftrags-ID wie heute.

### Arbeiter (`workers/chat_worker.py`)

**Plätze:** Der Editor-Faden wird ein Pool mit **3** Plätzen, also 3 Threads. Marken-Faden
und Wissens-Faden bleiben unverändert.

**Start einer Runde:** wie heute von der neuesten Fassung beim Beginn (`fassung_vorher`).

**Nachspielen beim Fertigwerden**, wenn die neueste Fassung neuer ist als `fassung_vorher`:

1. Die aktuelle Fassung (Blöcke) von der VM holen.
2. Die Änderungsliste der Runde (`aenderungen`) einzeln mit `agent_werkzeuge.anwenden` auf
   diese Fassung anwenden, mit denselben Prüfungen wie heute.
3. Übersprungene Änderungen melden. Eine Änderung wird übersprungen, wenn ihr Ziel fehlt
   oder sie sonst ungültig ist. Der Hinweis lautet „Übersprungen, weil eine andere Runde
   inzwischen … geändert hat: <schritt>“.
4. Neu angelegte Flächen bekommen neue IDs (`neu:<n>` auflösen).
5. Danach folgen Schönheitsprüfung (`pruefen`) und Speichern mit `fassung_vorher` = die
   Fassung, auf die nachgespielt wurde.
6. Verliert das Speichern das Rennen, weil eine noch neuere Fassung kam, wird erneut
   nachgespielt, **höchstens 3-mal**. Danach wird die Runde zurückgegeben mit „Zu viele
   gleichzeitige Änderungen – bitte noch einmal senden“.

**Bildaufträge:** Platzbezüge werden über dieselbe Zuordnung nachgezogen. Fehlt ein Platz,
wird der Auftrag mit Hinweis verworfen.

**Rückgängig:** nur für die Runde, deren Fassung noch die **neueste** ist. Sonst würde es
fremde Arbeit zurückdrehen.

**Kosten:**
- Bis zu 3 Editor-Claude-Prozesse plus Marken-Chat und Wissens-Lauf laufen gleichzeitig über
  den Shim. Der Budget-Wächter zählt jede Runde.
- Bei widersprüchlichen Bitten gewinnt die zuletzt fertige Runde, mit Hinweis.

## 2. Editor-Oberfläche (sales-claw `editor/`)

### Breiterer Chat

- Die Chat-Leiste startet mit **440 px**. Am linken Rand ist sie ziehbar, zwischen
  **360 px** und **50 %** der Fensterbreite.
- Die Breite liegt pro Browser in `localStorage` (Schlüssel `vibemind.editor.chatbreite`).
  Jeder Zugriff steht in try/catch; ohne Speicher gilt die Vorgabe.
- Das Eingabefeld wächst mit dem Text, bis 8 Zeilen.

### Mehrere Runden

- Der Knopf heißt immer **„Senden“**, auch während Runden laufen. „Vormerken“ entfällt.
  - Ist eine 4. Runde abgeschickt, steht sie im Verlauf als „wartet auf freien Platz“.
  - Ab der 6. kommt die Meldung „Bitte warten, bis eine Runde fertig ist“.
- Jede laufende Runde hat ihren eigenen Verlaufseintrag mit „Denkt nach …“, Schritten
  (Denkspur) und eigenem Stopp-Knopf.
- Die Fläche wechselt erst beim Fertigwerden einer Runde auf die neue Fassung.
  Live-Zwischenstände der Blöcke auf der Fläche entfallen, sobald mehr als eine Runde läuft.
  Bei genau einer laufenden Runde bleibt der Live-Zwischenstand wie heute.
- Übersprungene Änderungen stehen als Hinweise am Eintrag der Runde.
- Solange irgendeine Runde läuft, ist der Entwurf für Handbearbeitung gesperrt. Lesen und
  Scrollen gehen weiter.
- **Rückgängig** erscheint nur an der Runde, deren Fassung die neueste ist.

### Markierungen (Log-Fund 1)

- Der Editor schickt nur Auswahl-Chips mit, die seit dem letzten Senden **neu gesetzt oder
  angeklickt** wurden. Eine liegengebliebene Markierung erscheint ausgegraut mit
  „aus der letzten Nachricht“ und geht nur mit, wenn man sie anklickt.
- **Prompt-Regel für den Editor-Agenten:** Ohne Markierung beziehen sich Verweise wie „das“
  oder „so nicht“ auf die eigene letzte Runde. Ist der Bezug nicht eindeutig, fragt er kurz
  nach und ändert nichts.

### Gescheiterte Bildaufträge (Log-Fund 2)

- Ein Bildauftrag, der mit `fehler` endet, erscheint im Verlauf der Runde, die ihn
  beauftragt hat, als Hinweis: „Bild für <Platz> nicht erzeugt: <Befund>“.
- Der Bild-Arbeiter-Fix gegen Abbrüche beim Kaltladen ist bereits ausgeliefert
  (vibemind-os `f9b92176`).

## 3. Fehlerfälle, Grenzen, Tests

### Fehlerfälle

- **Keine Änderung passt mehr:** Die Runde endet als „fertig, nichts umgesetzt“ mit der
  Liste der übersprungenen Änderungen. Es entsteht keine Fassung.
- **Schönheitsprüfung schlägt nach dem Nachspielen an:** Korrekturrunde wie heute. Sie
  startet von der neuesten Fassung.
- **Speichern verliert dreimal das Rennen:** Rückgabe mit „Zu viele gleichzeitige
  Änderungen – bitte noch einmal senden“.
- **Stopp einer Runde:** Er wirkt nur auf diese Runde. „Behalten“ spielt ihre gültigen
  Änderungen nach demselben Verfahren nach.
- **Entwurf eingereicht oder freigegeben, während Runden laufen:** Sie enden wie heute ohne
  Fassung, mit Hinweis.
- **PC aus:** offene und wartende Runden verfallen nach der bestehenden Frist.

### Grenzen

- Höchstens 3 laufende Runden je Entwurf.
- Höchstens 3 Editor-Plätze im Arbeiter.
- Höchstens 5 wartende Runden je Entwurf.
- Chat-Breite 360 px bis 50 % des Fensters, Start 440 px.

### Tests

- **DB:**
  - `verify_067`, zweifach anwendbar.
  - 3 laufende Runden erlaubt, die 4. wartet, die 6. wird abgelehnt.
  - Ein frei werdender Platz startet die nächste wartende Runde.
  - Stopp wirkt pro Runde.
- **Arbeiter:**
  - Nachspielen auf eine neuere Fassung, wenn ein Block gelöscht wurde: Hinweis.
  - Nachspielen mit neuer Fläche: neue IDs.
  - Verlorenes Rennen: Wiederholung, nach 3 Versuchen Rückgabe.
  - 3 parallele Plätze.
  - Spur und Denken bleiben je Runde getrennt.
  - Bildaufträge mit fehlendem Platz werden verworfen.
- **Editor (vitest/Render):**
  - mehrere laufende Einträge;
  - Senden während laufender Runden;
  - „wartet auf freien Platz“;
  - Rückgängig nur an der neuesten Fassung;
  - ziehbarer Chat mit gemerkter Breite (auch ohne Speicher);
  - veraltete Markierung ausgegraut und nicht mitgesendet;
  - gescheiterter Bildauftrag als Hinweis.
- **Prompt:** Bezugsregel für „das/so nicht“ ohne Markierung.
- **Echter Lauf:** zwei Bitten kurz hintereinander an denselben Entwurf, die verschiedene
  Blöcke betreffen. Beide werden umgesetzt, keine überschreibt die andere. Danach eine
  dritte Bitte, die einen von der zweiten gelöschten Block betrifft: Hinweis statt Fehler.

## Nicht Teil dieses Blocks

- Parallele Runden im Marken-Chat.
- Handbearbeitung des Entwurfs während laufender Runden.
- Live-Zwischenstände mehrerer Runden auf der Fläche.
- Ein Drei-Wege-Zusammenführen ganzer Fassungen.
