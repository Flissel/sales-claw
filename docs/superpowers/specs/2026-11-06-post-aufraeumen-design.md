# Post-Sammelstelle: Postfächer aufräumen und sauber halten — Design

Stand 06.11.2026. Entstanden im Gespräch mit Felix (Betreiber). Baut auf der
Post-Sammelstelle Stufe 1 (`2026-10-30-post-sammelstelle-design.md`) und der
Einordnung v2 (`2026-11-04-post-einordnung-v2-design.md`) auf.

Markierung: **[Felix]** = von Felix entschieden. **[Claude]** = meine Festlegung,
von Felix nicht ausdrücklich bestätigt. Unmarkiertes ist Bestand oder Folge daraus.

## 1. Absicht

Felix hat rund 11.000 Mails in vier Postfächern, viele davon unnötig. Er will
einen Posteingang, in dem **nur steht, was seine Aufmerksamkeit braucht**. Alles
andere soll geordnet griffbereit sein, Werbung soll verschwinden. Das soll
**einmal für den Altbestand** passieren und danach **von selbst** für jede neue
Mail gelten, ohne dass er Mails einzeln anfassen muss.

Warum jetzt: Alle Postfächer sind seit 03.11. angebunden, die Einordnung läuft.
Sie verschiebt im Postfach aber nichts, die Handy-App bleibt so voll wie vorher.

## 2. Bestand (gemessen 06.11.2026, Schema `sales`)

| Kennung | Adresse | Art | Mails | eingeordnet | Jahre |
|---|---|---|---|---|---|
| gmx-felix | felixbaumann4@gmx.de | privat, steht fälschlich auf `business` | 7.943 | 857 | 2020–2026 (2023: 295, 2024: 1.376, 2025: 3.406, 2026: 2.859) |
| gmail-felix404 | felixbaumann404@gmail.com | privat + weitergeleitete Bluebatch-Post | 3.223 | 0 | 2025–2026 |
| gmx-unity | unit-y-ai@gmx.de | business | 402 | 400 | 2025–2026 |
| haupt | felix@vibemind.space | business | 419 | 406 | 2026 |

Von 1.663 eingeordneten Mails liegen **851 in „Zum Nachsehen“**: Sortierer und
Prüfer sind sich dort uneins. Tagesgrenze heute: 500 Modellaufrufe, also etwa
250 Mails pro Tag. Im Postfach wird heute nur verschoben, was der alte
Mail-Aufräumer als Spam oder unwichtig vorschlug (`postfach.verschieben`).

## 3. Ziele

1. **Posteingang = Aufmerksamkeit.** Im IMAP-Posteingang jedes Postfachs stehen
   nur Mails, die Handeln brauchen (§5). **[Felix]**
2. **Zur Info.** Alles andere, das bleibt, verlässt den Posteingang. In der
   Sales-UI steht es unter Mails im Reiter **„Zur Info“**, nach Fächern. **[Felix]**
   Im Postfach liegt es im Ordner „Zur Info“. **[Claude]** Der Ordner ist nötig,
   sonst bleibt die App voll.
3. **Werbung weg.** Werbung im Altbestand wird **endgültig gelöscht**, in **allen
   vier** Postfächern. **[Felix]** Neue Werbung landet im Ordner **„To-Review“**,
   was dort liegt, darf weg. **[Felix]**
4. **Altbestand einmal durcharbeiten**, gestaffelt **nach Jahr**. **[Felix]**
5. **Danach dauerhaft**: Jede neue Mail läuft denselben Weg. **[Felix]**
6. **Bluebatch-Mails** sind Business, erkennbar an der ursprünglichen Adresse,
   an die sie gingen. Diese Adresse wird mitgeführt. **[Felix]**
7. **„Zum Nachsehen“ wird selten.** Ziel: unter 10 % der Mails. **[Claude]**
   Sonst bleibt die Hälfte an Felix hängen, und autonom ist nichts.

## 4. Was mit welcher Mail passiert **[Felix]**

| Art | Wohin | Bleibt? |
|---|---|---|
| Werbung: Kaltakquise, Gewinnspiele, Rabattaktionen | Altbestand: löschen. Neu: Ordner „To-Review“ | nein |
| Newsletter (selbst abonniert) | Fach „Newsletter“, Zur Info | ja |
| Benachrichtigungen sozialer Netzwerke | Fach Soziale Netzwerke, Zur Info (später Feedback-Analyse) | ja |
| Rechnungen, Verträge, Abos, Kündigungen, Bank, Versicherung, Behörden, Steuer, Logins, Sicherheitscodes | eigenes Fach; Posteingang oder Zur Info nach §5 | **immer** |
| Alles von echten Menschen | Posteingang oder Zur Info nach §5 | **immer** |

**[Claude]** Zur Abgrenzung:
- Rabatt- und Werbemails eines Dienstes, den Felix nutzt (z. B. Amazon-Deals),
  zählen als Werbung.
- Produkt- und Kontomitteilungen desselben Dienstes bleiben unter „Tools & Dienste“.
- Die heutige Beschreibung von „Tools & Dienste“ („auch deren Werbung“) wird dafür
  geändert.
- „Abos & Newsletter“ (privat) und „Newsletter & Branche“ (business) bleiben die
  Newsletter-Fächer. Ein neues Fach braucht es nicht.

**Werbung wird nie gelöscht, wenn** eine dieser Bedingungen zutrifft **[Claude]**:
- Der Absender ist ein bekannter Kontakt (`leads`, auch archiviert).
- Die Mail hat einen Anhang außer Bildern.
- Sie liegt in „Zum Nachsehen“.
- Sortierer und Prüfer waren sich nicht einig.

Gelöscht wird nur, was sicher Werbung ist: Absender-Regel oder Katalog sagt
Werbung, oder beide Modelle sagen übereinstimmend Werbung.

**Gemischte Absender [Claude]:** Gelöscht wird immer **je Mail**, nie „alles von
Absender X“.
- Hat ein Absender auch nur eine Mail in einem Fach aus „Bleibt immer“
  (Rechnungen, Käufe & Bestellungen, Konten & Sicherheit, Behörden & Versicherung,
  Gesundheit, Familie & Freunde, Kunden & Anfragen, Partner & Netzwerk), dann:
  - bekommt er **keine** Absender-Regel „Werbung“;
  - werden seine Werbemails nur gelöscht, wenn beide Modelle übereinstimmen.

  Beispiel: Amazon-Deals gehen, Amazon-Rechnungen bleiben.
- Eine Absender-Regel „Werbung“ entsteht nur für Absender ohne eine einzige solche
  Mail. Bekommt so ein Absender später doch eine, gilt die Regel für ihn nicht mehr.
  Diese Mail wird normal eingeordnet.

## 5. Aufmerksamkeit **[Felix, Tabelle bestätigt]**

| Aufmerksamkeit (Posteingang) | Zur Info |
|---|---|
| echte Menschen, die eine Antwort erwarten | echte Menschen ohne Frage („Danke, passt“, CC) |
| Rechnungen zum Selbst-Überweisen, Mahnungen, Fristen | abgebuchte Rechnungen, Bestellbestätigungen, Versand |
| Behörden, Steuer, Bank, Versicherung mit Handlungsbedarf | Kontoauszüge, Infos ohne Handlungsbedarf |
| Sicherheitswarnungen („Neue Anmeldung von …“) | Login-Codes älter als ein Tag |
| Vertragsänderungen, Kündigungsbestätigungen | Abo-Verlängerung ohne Preisänderung |

**[Claude]** Im Altbestand gilt Aufmerksamkeit nur für Mails der letzten **90 Tage**.
Was älter ist, geht nach Zur Info, auch wenn es damals Handeln brauchte.
Gelöscht wird es nicht.

**[Claude]** Zu den Fristen:
- Die 90 Tage zählen ab dem **Datum der Mail**.
- Sie gelten nur beim Durcharbeiten des Altbestands. Eine Mail, die im
  Posteingang alt wird, bleibt dort, bis Felix sie bearbeitet.
- Die einzige laufende Alterung sind Login-Codes nach einem Tag. Die verschiebt
  ein täglicher Durchgang auch im Postfach. Das sind wenige Mails am Tag.

**[Claude]** „Zum Nachsehen“ bleibt im Posteingang: Was unklar ist, darf nicht
unbemerkt verschwinden.

Aufmerksamkeit ist eine **zweite Angabe neben Bereich/Fach**, keine neue
Fachebene. Sortierer und Prüfer liefern sie mit. Ein Login-Code bekommt die
Angabe zeitabhängig: Nach einem Tag wandert er von selbst nach Zur Info.

## 6. Ablauf

### 6.1 Altbestand, Jahr für Jahr

Reihenfolge: **neuestes Jahr zuerst** **[Claude]**, damit der aktuelle
Posteingang schnell sauber wird. Ein Jahr gilt über alle vier Postfächer
gemeinsam, erst dann kommt das nächste. Je Jahr und Postfach:

1. **Ohne Modell zuerst:** feste Muster, Nutzerregeln und Absender-Katalog
   (`post_katalog.py`). Werbung kommt meist von wenigen Absendern in großer Zahl.
   Eine Regel je Absender trifft Hunderte Mails ohne Modellaufruf. Erst der Rest
   geht an Sortierer und Prüfer.
2. **Modell** für den Rest, innerhalb der Tagesgrenze. Die bleibt bei 500
   Aufrufen. **[Felix 06.11.]** Er hat dem langsamen Weg zugestimmt, der im
   schlechtesten Fall rund 6 Wochen dauert. Eine vorübergehend höhere Grenze
   ist nicht gewünscht. Gibt die Absender-Stufe zu wenig her, wird das sichtbar
   (§7), nicht still die Grenze erhöht.
3. **Vorschau Löschen:** Je Jahr eine Liste der Absender mit der Zahl der Mails,
   die als Werbung gelöscht würden, mit Beispielbetreffen. **Felix gibt einmal je
   Jahr frei** (in der Sales-UI). Ohne Freigabe wird nichts gelöscht.
   **[Claude]** Die Freigabe gilt für alle vier Postfächer gemeinsam.
   - **Ein Klick je Jahr.** Je Absender gibt es einen Haken, vorgewählt. Felix nimmt
     nur einzelne Absender heraus, er muss keine einzeln bestätigen.
   - Je Absender stehen bis zu drei Beispielbetreffe da.
   - Ein herausgenommener Absender bekommt eine Schutzregel „nie Werbung“.
   - Mails, die nach der Freigabe eines Jahres noch als Werbung eingeordnet werden
     (z. B. aus „Zum Nachsehen“), gehen den Weg neuer Mails nach „To-Review“.
   - Vor der Freigabe gehören sie in die Vorschau ihres Jahres.
4. **Ausführen:** löschen, was freigegeben ist; den Rest im Postfach nach
   „Zur Info“ verschieben oder im Posteingang lassen.

### 6.2 Neue Mails

Sie laufen im normalen Abholzyklus von `sales-post` durch:
- einordnen, Aufmerksamkeit bestimmen;
- Werbung nach „To-Review“;
- Zur Info nach „Zur Info“;
- Aufmerksamkeit bleibt im Posteingang.

Keine Freigabe je Mail.

**[Claude]** Was länger als **30 Tage** in „To-Review“ liegt, wird gelöscht. Das ist
Felix' „was da liegt, darf weg“ mit einer Frist, in der er hineinschauen kann.

### 6.3 Korrekturen

Verschiebt Felix in der Sales-UI eine Mail, zum Beispiel von Zur Info in den
Posteingang oder aus To-Review heraus, zieht das Postfach nach. Aus der Korrektur
entsteht wie heute eine Absender-Regel. Verschiebt er im Postfach selbst, muss
die Sammelstelle das nicht nachbilden **[Claude]**.

**[Claude]** Was das für Regeln heißt:
- Holt Felix eine Mail aus To-Review heraus, bekommt der Absender die Schutzregel
  „nie Werbung“.
- Holt er eine Mail aus Zur Info in den Posteingang, gilt das nur für diese Mail.
  Für den Absender entsteht keine Regel, weil Aufmerksamkeit von der einzelnen
  Mail abhängt.

## 7. Sales-UI

Unter Mails (`/post`) gibt es diese Reiter **[Felix: Reiter Zur Info; Rest Claude]**:
- **Aufmerksamkeit**
- **Zur Info**, gegliedert nach Fächern
- **To-Review**, mit Frist bis zum Löschen
- **Aufräumen**: Fortschritt je Postfach und Jahr, Vorschau und Freigabe nach
  §6.1, Zahl der Modellaufrufe und geschätzte Resttage.

Die Sichtbarkeit bleibt bei `post_struktur.sichtbar_sql`. Privates sieht nur der
Besitzer, der Bot nur Business.

## 8. Konten

- **gmx-felix** wird auf `standard_bereich = privat` gesetzt.
- Der Auftrag an Sortierer und Prüfer hängt von der Art des Postfachs ab. Im
  privaten Postfach gehören Abos, Rechnungen und Käufe nach privat (offener
  Punkt aus v2).
- **gmail-felix404:** Ist die Mail eine Bluebatch-Weiterleitung, gilt business.
  Die ursprüngliche Empfängeradresse wird in einer neuen Spalte gespeichert.
- **Erkundung für den Builder:** In welcher Kopfzeile die ursprüngliche Adresse
  steht (z. B. `X-Forwarded-To`, `Delivered-To`, `X-Original-To`, `Received …
  for`) und wie die Bluebatch-Adresse lautet, ist noch nicht gemessen. Heute
  speichert `post_mails.an` nur `felixbaumann404@gmail.com`. Der Builder prüft
  das an einer Stichprobe, nur an Kopfzeilen, nie am Inhalt.
  - Findet sich kein verlässliches Merkmal, fragt der Builder Felix nach der
    Bluebatch-Adresse und stoppt diesen Teil, bis die Antwort da ist.

## 9. „Zum Nachsehen“ senken

Voraussetzung für Ziel 7, und sie kommt **vor** dem Altbestand-Lauf.

Ursachen aus der ersten v2-Runde:
- Ein privates Postfach steht als business.
- Der Sortierer (Haiku) legt nach privat, der Prüfer (Sonnet) nach business.
- Werbung und Tools & Dienste sind unscharf getrennt.

Die Lösung bleibt dem Builder überlassen. Gefordert ist:
- gemessen an einer Stichprobe von mindestens 100 Mails aus allen vier Postfächern;
- danach die bestehende Neu-Sortierung (`deploy/post-neu-einordnen.sh
  vorschau|bericht|anwenden`) mit Felix' OK.

## 10. Nicht-Ziele

- Die Übersicht aller Abos und Rechnungsdienste. Die baut Felix später über das
  Bluebatch-Gateway. Hier nur keine Hürde dafür schaffen: Anbieter je Mail
  bleibt stabil benannt.
- Outlook, weitere Postfächer, Archivieren nach Stufe 2 im Sinne „Sensibel“-Ordner.
- Abmelden von Newslettern.
- Der zweite Laden (Ivan): unberührt; nichts hier bucht auf Schema oder IDs des
  Betreibers um.

## 11. Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)

- Eine Rechnung, ein Vertrag, ein Behördenbrief, ein Code oder eine Mail eines
  echten Menschen wird gelöscht.
- Der Posteingang ist danach so voll wie vorher, oder die Hälfte liegt in „Zum Nachsehen“.
- Felix muss Hunderte Mails einzeln freigeben.
- Private Post wird für andere oder für den Bot sichtbar.
- Ein IMAP-Befehl löscht mehr als die gemeinte Mail.
  - Achtung: `postfach.verschieben` ruft `expunge()` auf. Das entfernt alle als
    gelöscht markierten Mails der INBOX, nicht nur die eine.
  - Neu: `UID MOVE` oder `UID EXPUNGE`, wenn der Server sie kann, sonst Abbruch
    statt Rundumschlag.
  - **[Claude]** Abbruch heißt: Für dieses Postfach ruhen Verschieben und Löschen.
    Einordnen läuft weiter. Die Sales-UI zeigt den Grund unter „Aufräumen“.
  - **[Claude]** „Endgültig gelöscht“ in Gmail heißt: in den Papierkorb
    verschieben und dort per `UID EXPUNGE` entfernen. Nur verschieben genügt
    nicht, weil der Papierkorb die Mail 30 Tage behält.

## 12. Leitplanken

- Löschen ist unumkehrbar: Altbestand nur nach Freigabe je Jahr (§6.1); jede
  Löschung protokolliert (Postfach, UID, Message-ID, Absender, Betreff, Fach).
  **[Claude]** Die Zeile in `post_mails` bleibt mit Status `geloescht` und
  Kopfdaten, Text wird geleert.
- Deploy und Start des Altbestand-Laufs nur mit Felix' OK; `sales-auto` nie starten.
- Keine Geheimnisse und kein Mailinhalt in Logs.
- Testsuite: keine echten Postfächer (Sperre in `tests/conftest.py`, auch für die
  neuen IMAP-Befehle).
- Maschinenweite Arbeit auf der VM vorher im Vault claimen.

## 13. Erfolg

- Nach dem Altbestand-Lauf liegen je Postfach im Posteingang nur
  Aufmerksamkeits-Mails: Dutzende, nicht Tausende.
- Werbung ist aus allen vier Postfächern gelöscht. Keine Mail aus „Bleibt immer“
  ist darunter (Stichprobe von Felix).
- „Zum Nachsehen“ unter 10 %.
- Neue Mails landen ohne Zutun im richtigen Ordner.

## 14. Dem Builder überlassen

- Prompt- und Katalogänderungen, um „Zum Nachsehen“ zu senken.
- Datenmodell für Aufmerksamkeit, Postfach-Ordnerstand und Freigaben.
- IMAP-Details: Ordner anlegen, `MOVE` gegenüber `COPY`+`UID EXPUNGE`, je Anbieter
  (GMX, Gmail, Namecheap).
  - Gmail-Labels: „Verschieben“ heißt dort Label wechseln und `INBOX` entfernen.
- Wie die 90-Tage- und 1-Tag-Fristen technisch laufen.
- Reihenfolge der Bauschritte (sinnvoll: §9 → Datenmodell und IMAP → neue Mails →
  Altbestand mit UI).
