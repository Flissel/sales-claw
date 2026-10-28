# Newsletter-Runde mit dem Betreiber (28.10.2026) — TODO

Rundgang im Browser, Seite für Seite (wie der Sales-UI-Rundgang vom 27./28.10.).
Nach Startseite, Editor und Prüfen hat der Betreiber gestoppt: „erst umsetzen“.
Offen ist noch der Rest des Rundgangs (Vorlagen, Entwürfe-Liste, Freigabe, Versand).

## 1. Newsletter-Startseite (`/marketing`)

- [x] Alte Entwürfe aufgeräumt: die vier vom 04.09. verworfen, darunter die Agenten-Absage
      „VibeMind – kurze Info“ und ein Entwurf mit Platzhaltern. Grund steht jeweils dabei.
- [ ] Start per Gespräch: ein Feld „Worum soll es gehen?“, der Agent baut daraus den Entwurf.
      Hängt am Punkt „Ein Agent für alles“ (unten).
- Nicht gewählt (bleibt): drei Einstiege, Ansprache je Marke.

## 2. Editor (`/marketing/editor/<id>`)

- [ ] **Ein Agent für alles** (Betreiber-Wunsch). Heute gibt es vier getrennte Gesprächspartner:
      Editor-Assistent (`workers/chat_worker.py`, 3 Plätze), Marken-Agent (`marken_arbeiter.py`),
      Telegram-Bot (Kampagnen, `telegram_bot.py`) und Video-Claw. Ziel: ein Agent mit gemeinsamem
      Gedächtnis (Marke, Kampagnen, Entscheidungen). Editor, Markenseite, Plan und Telegram sind nur
      Fenster zu ihm, die Spezialisten werden seine Werkzeuge. Braucht ein eigenes Design vor dem Bau.
- [x] Impressum im Editor: fester, nicht verschiebbarer Fuß unter der Seite, wie in Übersicht und
      PDF (`editor/src/App/Seite/SeitenFuss.tsx`; die Marketing-API liefert den Pflichtteil in
      `GET /inhalte/{iid}`). Ohne Impressum steht dort rot „Impressum fehlt“.
- [x] Scheitern sichtbar: endet die letzte Nachbesserung ohne „fertig“, steht das als erste Zeile
      der Antwort (`chat_worker.NICHT_FERTIG`).
- [x] Keine leeren Versprechen: im Prompt steht, nur anzukündigen, was in dieser Antwort beauftragt
      wird, und offen zu sagen, was nicht klappt.
- [x] Vorschautext: ist er leer, nimmt die Mail den ersten Satz des obersten Fließtexts, ohne
      Anrede und Links (`seite_mail.vorschau_aus_seite`).
- Gestrichen: „rechte Spalte abgeschnitten“. Das war ein Fehler der Bildschirmfotos (Windows-Skalierung
  110 %), im Browser ragt nichts hinaus (gemessen).
- Gestrichen: „Titel uneinheitlich“. Der Betreff heißt tatsächlich „VIbemind“, das ist ein Tippfehler
  im Entwurf, kein Programmfehler.

## 3. Prüfen

- [x] **Kontakte im Markenwissen** (Datenschutz): 557 der 569 Dateien im Markenordner waren
      Kontaktdateien aus dem Geschäftsdaten-Lauf. Sie verdrängten das echte Markenwissen und trugen
      Personendaten in den Prompt. Jetzt nie mehr Markenwissen (`markenwissen._KONTAKTE`). Gemessen
      danach: 4 Dokumente, 5.906 Zeichen, kein Kürzungshinweis.
- [x] Anrede-Befund geklärt: korrekt. Die Mail schneidet die Seite in waagerechte Streifen, ein Streifen
      mit Bild geht als Bild hinaus, und Text neben dem Bild wird eingebacken („{vorname}“ bleibt stehen).
      Ursache der ständig gescheiterten Runden: die Grundformen „Split“ und „Versetztes Bildpaar“
      schickten den Text selbst neben das Bild. Prompt korrigiert (Text unter das Bild).
- [ ] Echte Spalten in der Mail (Bild neben echtem Text, MJML `mj-column`). Erst nötig, wenn der
      Betreiber geteilte Aufbauten mit Text daneben wirklich will.
- [ ] Prüfen legte einmal eine Fassung an (Höhe 730 → 726), ohne dass etwas geändert wurde. Seitdem
      nicht nachstellbar; beim sauberen Entwurf speichert Prüfen laut Code nicht. Beobachten.
