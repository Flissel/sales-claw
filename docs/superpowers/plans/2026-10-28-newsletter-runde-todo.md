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

## 2b. Neuer Newsletter per Assistent (Rundgang, 28.10. abends)

- [x] Nach den Prompt-Fixes: neuer Entwurf „Beta Marketing Space – Rundgang 28.10.“ — Fließtext mit
      Anrede steht unter dem Bild, Runde 3/3 „Finale Prüfung bestanden“, Prüfen: **keine Befunde**, keine
      neue Fassung durch Prüfen. Vorschautext: der Assistent sagt ehrlich, dass er ihn nicht setzen kann
      (die Mail nimmt dann den ersten Satz).
- [x] Aufmacherbild: der Assistent HAT beim ersten Lauf ein Bild beauftragt (fertig 3 min später als
      neue Fassung, FLUX.2). Der „leere Platzhalter“ war nur zu früh angesehen — mein Fehlbefund.
      Ein zweites Bild (heller Arbeitsplatz) wurde nachgefordert und ist ebenfalls fertig.
- [x] Eingereicht (Fassung 5, Prüfung ohne Befund), in den Freigaben unter Marketing sichtbar,
      zurückgegeben mit „Betreff fehlt“.
- [ ] **Betreff = interner Titel**: niemand setzt ihn, die Mail ginge mit „Beta Marketing Space –
      Rundgang 28.10.“ als Betreff raus. Bestätigt: der Assistent kann Betreff/Vorschautext NICHT setzen
      (kein Werkzeug) und verweist falsch aufs „Versand-Tool“. Lösung: Werkzeug `betreff_setzen`
      (Betreff + Vorschautext) für den Collage-Agenten, oder Pflichtfeld beim Einreichen.
- [ ] **Das Betreff-Feld sieht aus wie ein Dateititel**: oben links im Editor, ohne sichtbare Beschriftung
      (nur aria-label „Betreff“), vorbelegt mit dem Arbeitstitel. Deshalb blieb der Betreff unbemerkt der
      interne Titel. Sichtbar „Betreff“ davorschreiben; beim Einreichen warnen, wenn Betreff == Titel.
      Für den Rundgang von Hand gesetzt (Fassung 8): „Dein Newsletter schreibt sich ab jetzt selbst“,
      Vorschautext „VibeMind startet in die Beta – 3 Monate kostenlos testen.“
- [ ] **Prüfrunden bauen um, obwohl nichts zu ändern war**: Rückgabe-Lauf f915337e sagte „Seite bleibt
      unverändert“, die Nachbesserung baute wegen „Abwechslung“ trotzdem auf Split um und endete unfertig
      (Fassung 6; Fassung 5 per Rückgängig holbar). Verglichen wurde korrekt mit dem ANDEREN Newsletter
      („VIbemind“, ähnlicher Aufbau) — `pult_seite_kompositionen` schließt den eigenen Entwurf aus
      (geprüft; meine erste Vermutung „vergleicht mit sich selbst“ war falsch). Fehler: der Prompt sagt
      „Soll nur etwas geändert werden, behalte den Aufbau“, die Prüfrunden wenden Abwechslung trotzdem an.
- [ ] **Kein Testversand**: nach dem Freigeben entstehen gleich Entwürfe für alle opt_in-Kontakte;
      eine Testmail nur an den Betreiber gibt es nicht.
- [ ] Gesundheitsanzeige des Chat-Arbeiters (:8134) meldet alle Plätze „leer“, während ein Lauf
      (f915337e, >11 min) aktiv Denkschritte an die API schickt — irreführend.

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
- [x] Gespeicherte Collage-Vorlagen (gemessen 28.10. mit `seite_mail._im_bild`): bei „Split“,
      „Versetztes Zwei-Bild-Raster“ und „Zitat-Bühne“ liegt JEDER Fließtext in einem Bildstreifen –
      eine Anrede dort scheitert immer an der Prüfung. Die übrigen fünf haben je mindestens einen freien
      Fließtext. Keine Vorlage enthält selbst eine Anrede. **Entscheidung des Betreibers (28.10.): die
      Vorlagen bleiben so**; der Agent achtet über den korrigierten Prompt selbst darauf.
- [x] Vorlagen-Seite: die Kartenbeschriftung ist jetzt eine Zeile „Collage · Fassung 2 · entschieden von …“,
      ohne technischen Kurznamen. Die Vorschauen laden weiter erst beim Scrollen, weil jede auf dem Server
      gerendert wird.
- [ ] Prüfen legte einmal eine Fassung an (Höhe 730 → 726), ohne dass etwas geändert wurde. Seitdem
      nicht nachstellbar; beim sauberen Entwurf speichert Prüfen laut Code nicht. Beobachten.
