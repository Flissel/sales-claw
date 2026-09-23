# Terminkarten — Vorlage aus einem Foto, ausgefüllt je Termin

**Stand 24.09.2026. Mit dem Betreiber Abschnitt für Abschnitt besprochen und
freigegeben. Diese Datei ist die schriftliche Fassung zur Durchsicht.**

Erstes von drei Vorhaben aus dem Betreiber-Auftrag vom 23.09.2026. Die beiden
anderen — die Grundausstattung je Laden (Mitglieder-, Kontakt-, Firmenliste,
Newsletter, Leitfäden Fiko und BAV) und das Fiko-Heft — bekommen je eine eigene
Spezifikation. Das Fiko-Heft baut auf dem Mechanismus auf, der hier entsteht.

---

## 1. Was eine Terminkarte ist

Ein **gedrucktes Arbeitsblatt für den Teamleiter**. Wer einen Termin vereinbart
hat, gibt ihm eine Karte mit den Eckdaten von Kunde und Termin in die Hand.

Die Karte geht **nicht** an den Kunden und wird **nicht** automatisch an den
Teamleiter geschickt. Sie geht an das Mitglied, und das druckt sie aus.

Mit dem Betreiber festgelegt:

| Frage | Antwort |
|---|---|
| Wofür | Für den Teamleiter, zum Drucken |
| Woher kommt die Vorlage | Es gibt die Karte auf Papier; ein **Foto** davon wird nachgebaut |
| Eine oder viele | **Eine Teamkarte** für alle Mitglieder; ausgefüllt wird sie je Kunde und dort abgelegt |
| Wann entsteht eine ausgefüllte Karte | **Auf Zuruf** („mach die Terminkarte für Müller"), nicht automatisch |
| Wie wird nachgebaut | **Nachbau als eigene Druckvorlage** (Ansatz A), nicht das Foto als Hintergrund |

## 2. Grundsatz

**Musterblatt und jede ausgefüllte Karte entstehen aus demselben Programm.** Sonst
gäbe der Betreiber ein Musterblatt frei und druckte etwas anderes. Dieselbe Regel
trägt im Haus schon die Empfängernummern (`nummern.py`) und die Mail-Links
(`verlinken.py`).

Daraus folgt die Arbeitsteilung:

| Wer | Tut | Warum dort |
|---|---|---|
| **Marketing** (PC des Betreibers) | liest das Foto und liefert den **Entwurf** der Karte: Felder, Aufbau, Aussehen, als Daten | Nur hier braucht es das Foto und ein Sprachmodell. |
| **Sales** (VM) | setzt **das Musterblatt und jede Karte** mit einem Programm, direkt in den Ordner des eigenen Ladens | Läuft rund um die Uhr; Kundendaten verlassen die VM nie. |

Der Betreiber hatte „Marketing lädt in die Medien hoch" beschrieben. Am Ergebnis
ändert die Aufteilung nichts. Sie verhindert zweierlei: dass es **keine Karten
gibt, wenn der PC aus ist**, und dass jede Datei per SSH in den richtigen
Ladenordner reisen muss.

## 3. Ablauf

### Teil 1 — Vorlage bestellen (einmalig, mit Schleife)

1. Das Mitglied schickt seinem Sales-Bot das **Foto einer unausgefüllten Karte**.
   Der Bot legt einen Vorlagen-Auftrag an (§4.2).
2. Marketing liest das Foto, erkennt Felder und Aufbau und legt eine Vorlage der
   Art `formular` an (§4.1). Jedem Feld ordnet es eine **Datenquelle** aus dem
   Katalog (§4.3) zu, oder `frei`.
3. Sales setzt daraus das **Musterblatt** mit Beispieldaten, legt es im Ordner
   des bestellenden Ladens ab und fragt das Mitglied im Chat:
   **„Passt die Terminkarte so?"**
   - **Ja:** Die Vorlage ist `freigegeben` und gilt fürs ganze Team.
   - **Nein, und was stört:** Der Auftrag geht mit der Anmerkung auf
     `nachbessern`, Marketing bessert nach, und die Frage kommt erneut.

   **Wann gefragt wird:** in der bestehenden Postfach-Durchsicht (fünfmal
   täglich, 09–21 Uhr) und sofort, wenn das Mitglied selbst nachfragt. Es
   entsteht **kein** neuer Routinelauf. Das hält die Betreiber-Entscheidung
   vom 22.09.2026 ein, die Routineläufe knapp zu halten, und kostet bis zu drei
   Stunden Wartezeit. Diese Wartezeit ist der Preis und steht hier, damit sie
   niemanden überrascht.

### Teil 2 — Terminkarte erstellen (je Termin, auf Zuruf)

4. „Mach die Terminkarte für Müller": Der Bot holt Kontakt und Termin und füllt
   die Felder aus dem Katalog.
5. **Was fehlt, fragt er nach**: nachtragen, oder **leer lassen zum Ausfüllen
   von Hand**. Eine leere Linie ist auf Papier ein gültiges Ergebnis, eine
   erfundene Angabe nicht.
6. Die Karte wird gesetzt (ohne Sprachmodell, in Sekunden), **beim Kunden
   abgelegt** (§4.4) und dem Mitglied zum Ausdrucken in den Chat geschickt.

## 4. Daten

### 4.1 Vorlage — Erweiterung von `marketing.layout_vorlagen`

Es entsteht kein neues Vorlagen-System. Die bestehende Tabelle (Migration 044)
mit dem Status `vorschlag` → `freigegeben` bekommt:

- eine neue Spalte **`art`** (`text not null default 'layout'`), erlaubt sind
  `layout` (die heutigen Newsletter-Vorlagen, unverändert) und `formular`;
- eine neue Spalte **`fassung`** (`integer not null default 1`);
- für `art = 'formular'` in `gestalt` das Seitenformat und eine Liste
  **`felder`**, je Feld `name`, `beschriftung`, `art` (`text`, `datum`,
  `uhrzeit`, `telefon`, `mehrzeilig`), `quelle` (§4.3) und `platz`.

`platz` ist ein Rechteck in Millimetern, gemessen von der linken oberen Ecke der
Seite: `{x, y, breite, hoehe}`. Das Seitenformat (`breite_mm`, `hoehe_mm`) liest
Marketing aus dem Seitenverhältnis des Fotos; wo das nicht eindeutig ist, gilt
DIN A6 quer.

**Eine freigegebene Fassung ist unveränderlich.** Jede spätere Änderung ist eine
neue Fassung und braucht eine neue Freigabe. Das erzwingt die Datenbank, nicht
der Aufrufer.

### 4.2 Vorlagen-Auftrag — neue Tabelle `marketing.vorlagenauftraege`

Das Gegenstück zu `marketing.versandauftraege` (Migration 043), die heute in die
andere Richtung läuft.

| Spalte | Inhalt |
|---|---|
| `laden` | bestellender Laden (Präfix, geprüft gegen `^[a-z][a-z0-9_]{0,30}$`) |
| `art` | `terminkarte` (später `fiko_heft`) |
| `bild` | Dateiname des Fotos im Ordner des bestellenden Ladens |
| `anmerkung` | was das Mitglied beim Bestellen dazu sagt |
| `vorlage` | Name der entstehenden Vorlage |
| `runde` | beginnt bei 1, erhöht sich bei jedem `nachbessern` |
| `rueckmeldungen` | `jsonb`-Liste aller Runden: Runde, Urteil, Anmerkung, Zeitpunkt |
| `status` | siehe unten |

Erlaubte Übergänge:

| von | nach | ausgelöst durch |
|---|---|---|
| `neu` | `in_arbeit` | Marketing übernimmt |
| `in_arbeit` | `vorgelegt` | Marketing liefert den Entwurf |
| `vorgelegt` | `freigegeben` | Mitglied sagt ja |
| `vorgelegt` | `nachbessern` | Mitglied sagt nein, mit Anmerkung |
| `nachbessern` | `in_arbeit` | Marketing übernimmt die nächste Runde |

Alle anderen Übergänge weist die Datenbank ab. Die Rückmeldungen **aller**
Runden bleiben erhalten: Marketing weiß in Runde 3 noch, was in Runde 1 gestört
hat.

### 4.3 Datenkatalog — woraus die Felder befüllt werden

Eine feste Liste, gepflegt in Sales. Marketing wählt je Feld eine Quelle daraus
oder `frei`:

| Quelle | Herkunft |
|---|---|
| `kunde.name`, `kunde.telefon`, `kunde.email`, `kunde.firma` | `leads` |
| `termin.datum`, `termin.uhrzeit`, `termin.dauer`, `termin.thema`, `termin.ort` | letzte Aktivität `termin` des Kontakts |
| `mitglied.name` | neue Variable `MITGLIED_NAME` in der Umgebung des Ladens; `laden-anlegen.sh` fragt sie ab |
| `frei` | wird im Chat erfragt oder leer gelassen |

Welche Felder die Karte tatsächlich hat, steht **erst mit dem Foto** fest. Diese
Spezifikation legt sie bewusst nicht fest.

### 4.4 Ausgefüllte Karte — am Kunden

- Aktivität `terminkarte` am Kontakt mit Dateiname, Vorlage, **Fassung**,
  Termin-UID, den eingesetzten Werten und den leer gelassenen Feldern.
- Datei in `media-erzeugt` **des eigenen Ladens**, benannt wie die
  Termindateien: `terminkarte-<kunde>-<datum>.pdf`.
- Die Vorlage gibt es einmal fürs Team; Musterblätter und Karten liegen je
  Laden. Ivan sieht die Karten des Betreibers nicht, und umgekehrt.

## 5. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Das Modell kann das Foto nicht lesen (Messschritt 0 scheitert) | Rückfall: Das Mitglied nennt die Felder einmal im Chat, Marketing setzt daraus die Vorlage. |
| Der PC des Betreibers ist aus | Der Vorlagen-Auftrag wartet, und der Bot sagt es („liegt bei Marketing"). Das **Ausfüllen** ist nicht betroffen. |
| Es gibt keine freigegebene Vorlage | „Mach die Terminkarte" wird mit Auskunft abgelehnt. Es wird **nie** auf einer ungeprüften Vorlage gedruckt. |
| Daten fehlen | Der Bot nennt die leeren Felder: nachtragen oder leer lassen. |
| Der Kontakt hat keinen Termin | Der Bot fragt nach dem Termin, statt ohne zu setzen. |
| Ein Löschantrag ist vermerkt (`loeschantrag_vermerken`) | Keine neue Karte für diesen Kontakt, wie bei Entwürfen. |
| Drei abgelehnte Runden | Der Bot schlägt den Handweg vor, statt weiterzudrehen. |
| Eine Anweisung im Foto oder in einer Nachricht | Sie ist Inhalt, kein Befehl. Dieselbe Regel gilt für Mails. |
| Wer darf freigeben | Nur das bestellende Mitglied, in seinem eigenen Chat. |

## 6. Datenschutz

- **Kundendaten verlassen die VM nie.** Marketing sieht nur das Foto einer
  **leeren** Karte, und der Bot bittet ausdrücklich darum. Ausgefüllt wird auf
  der VM.
- Die Karte geht nur an das Mitglied. Die Weitergabe an den Teamleiter
  geschieht auf Papier, durch das Mitglied.
- **Auskunft (Art. 15):** `kontakt_auskunft` listet die Terminkarten des
  Kontakts.
- **Löschung (Art. 17):** Die physische Löschung bleibt der Menschen-Schritt aus
  `docs/06_DSGVO.md`. Die Anleitung dort nennt die Terminkarten-Dateien
  ausdrücklich.
- Die Sicherung erfasst `media-erzeugt` je Laden (seit 23.09.2026).

## 7. Neue Abhängigkeit

`sales-mcp` hat heute keine PDF-Bibliothek. **`reportlab`** kommt hinzu,
dieselbe Bibliothek, die Marketing für seine PDFs benutzt
(`spaces/marketing/claw/pdf.py`). Das Setzprogramm selbst wird für Sales neu
geschrieben: Marketings `pdf.py` setzt Fließtext für Newsletter, eine
Terminkarte ist ein Formular mit festen Feldplätzen.

## 8. Tests

0. **Messschritt 0, vor allem anderen.** Ein Marketing-Werkzeug ruft
   `claude -p` auf dem Abo auf und gibt ihm Lesezugriff auf genau eine
   Bilddatei. Der Hintergrund: Der Shim
   (`~/.local/bin/claude_code_openai_shim.py`) verwirft die Bildteile einer
   Nachricht und gibt der CLI keine eingebauten Werkzeuge; der Agent selbst
   sieht also kein Foto. Ergebnis mit Messwerten an einem Beispielfoto:
   erkannte Felder gegen die tatsächlichen, dazu die Laufzeit. Scheitert der
   Schritt, gilt der Rückfall aus §5.
1. **Setzprogramm:** Felder am Platz; lange Werte werden umbrochen oder
   verkleinert, nie abgeschnitten; Umlaute; leere Felder als Linie;
   Seitenformat.
2. **Ein Programm:** Musterblatt und Karte entstehen nachweislich aus demselben
   Aufruf, nur mit anderen Werten.
3. **Auftragsablauf:** nur erlaubte Übergänge; die Runden werden gezählt; die
   Rückmeldungen aller Runden bleiben erhalten; eine freigegebene Fassung ist
   unveränderlich.
4. **Ladentrennung:** Ivans Bestellung und seine Karten landen bei Ivan, die des
   Betreibers beim Betreiber.
5. **Datenschutz:** Ein Löschantrag sperrt neue Karten; die Auskunft listet die
   Karten.
6. **Durchstich auf der VM** mit einem Testkontakt: bestellen, ablehnen,
   nachbessern, freigeben, ausfüllen, beim Kunden ablegen.

## 9. Nicht Teil dieses Vorhabens

- Die Grundausstattung je Laden (Listen, Newsletter, Leitfäden) bekommt eine
  eigene Spezifikation.
- Das Fiko-Heft bekommt eine eigene Spezifikation und benutzt
  `art = 'formular'` von hier.
- Eine automatische Karte bei `termin_bestaetigen` ist ausdrücklich nicht
  gewollt.
- Ein Versand an den Teamleiter ist nicht gewollt; die Karte geht auf Papier.
