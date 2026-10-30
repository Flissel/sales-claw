# Post-Sammelstelle: alle Postfächer einsortiert, Posteingang leer (Entwurf, 30.10.2026)

Status: Entwurf zur Freigabe durch den Betreiber (Felix). Entstanden im Gespräch am 30.10.2026.
Was der Betreiber gesagt hat, steht als seine Entscheidung; was ich (Claude) festgelegt habe,
ist als **[meine Entscheidung]** markiert und darf gekippt werden.

## 1. Absicht und Warum

Felix hat mehrere Postfächer (Namecheap-Geschäftspostfach, mehrere GMX-Konten, Gmail, später
Outlook). Heute liest Sales davon nur die letzten 25 Mails je Abruf (`postfach.ANZAHL_MAX`), und
nur der Bot im Chat kann das. Die Postfächer laufen voll (Gmail: 1.514 im Posteingang), die
Zählung „ungelesen“ ist bedeutungslos, und Suchen über alle Mails geht nicht.

Gewollt ist eine **Sammelstelle**: alle Mails aller angebundenen Postfächer kommen an einer
Stelle in Sales an, ein Agent liest jede Mail, ordnet sie in eine **vorher festgelegte**
Fächerstruktur ein (wie bei Gmail: Privat/Business, Rechnungen, Abos, …), und danach wird sie im
echten Postfach **archiviert**. Der Posteingang bleibt leer, die Zahl stimmt wieder.

Wozu: Die einsortierten Mails sollen später als Daten weiterverarbeitet werden (Analyse,
z. B. Rechnungen auswerten). **Im ersten Schritt reicht, dass jede Mail im richtigen Fach liegt
und durchsuchbar ist** – Herausziehen von Beträgen, Fristen usw. kommt danach.

Langfristig ist die Sammelstelle für ein Team gedacht: Mails werden über **Abteilungen** an die
zuständigen Mitarbeiter verteilt, die in ihrem Bereich automatisieren können, ohne die Daten der
anderen anzufassen. Die Leitung sieht alle Business-Mails sortiert, mit Abteilung.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

**Ziele**
1. Mehrere Postfächer je Anbieter (mehrere GMX-Konten), Postfach hinzufügen in der Oberfläche.
2. Jede Mail – neu und Altbestand – wird genau einem Fach zugeordnet, mit Markierung
   privat/Business und ggf. „sensibel“.
3. Nach erfolgreicher Einordnung wird die Mail im echten Postfach archiviert (nie gelöscht).
4. Ein Mail-Reiter in Sales: Sammelstelle mit Fächern, Suche über alle Mails, Filter.
5. Die Struktur für Abteilungen und Sichtbarkeit steht von Anfang an im Datenmodell, auch wenn
   heute nur Felix Daten hat.
6. Die Einordnung ist ein austauschbarer Baustein (heute Cloud-Modell, später lokales Modell).

**Nicht-Ziele (jetzt nicht)**
- Outlook (braucht OAuth bei Microsoft) – später.
- Analyse/Extraktion (Beträge, Fälligkeiten, PDF-Auswertung) – nächstes Vorhaben.
- Lokales Modell – später, der Baustein wird nur austauschbar gebaut.
- Der Einrichtungs-Assistent (WhatsApp-QR, Versand, Zugang) – eigenes Vorhaben danach; „Postfach
  hinzufügen“ aus diesem Entwurf wird sein erster Baustein.
- Mails beantworten aus dem Mail-Reiter – der bestehende Weg (Entwurf → Freigabe → Versand über
  sales-dispatch) bleibt der einzige Versandweg.

**Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)**
- Der Agent erfindet neue Fächer. Die Struktur ist fest; was nicht passt, kommt in „Unklar“.
- Eine Mail geht verloren oder wird gelöscht. Verschieben ja, Löschen nie.
- Private Mails landen im Geschäftssystem (CRM, Vertriebs-Agent, Business-Analysen) oder sind
  für andere Personen sichtbar.
- Inhalt einer sensiblen Mail (Login-Codes, Passwort-Links, Zugangsdaten) wird gespeichert,
  durchsuchbar gemacht oder einem Agenten gezeigt.
- Ein Mitarbeiter sieht Mails außerhalb seiner Abteilungen oder die privaten Mails anderer.
- Archiviert wird, bevor Felix den ersten Lauf über den Altbestand gesehen hat.

## 3. Begriffe

- **Konto**: ein angebundenes Postfach (Anbieter + Adresse + Zugang), gehört genau einer Person.
- **Sammelstelle**: der gemeinsame Posteingang in Sales, in dem alle Mails aller Konten ankommen.
  [meine Entscheidung] Kein zusätzliches echtes Postfach, keine Weiterleitungen.
- **Bereich**: privat oder Business (erste Ebene).
- **Fach**: zweite Ebene innerhalb eines Bereichs (feste Liste, Abschnitt 4).
- **Sensibel**: Markierung quer zu Bereich und Fach.
- **Abteilung**: Gruppe, der eine Menge Business-Fächer gehört; Mitarbeiter gehören zu
  Abteilungen.
- **Leitung**: Personen, die alle Business-Mails aller Konten sehen (CEO/CTO/CMO).

## 4. Die feste Fächerstruktur (vom Betreiber bestätigt)

| Bereich | Fächer |
|---|---|
| Privat | Familie & Freunde · Rechnungen · Käufe & Bestellungen · Abos & Newsletter · Soziale Netzwerke · Konten & Sicherheit · Behörden & Versicherung · Werbung |
| Business | Kunden & Anfragen · Partner & Netzwerk · Rechnungen · Tools & Dienste · Bewerbungen & Jobs · Newsletter & Branche · Werbung |
| beide | Unklar |

- Die Liste liegt als Daten vor (Tabelle oder Konfiguration), nicht im Prompt verstreut. Ein neues
  Fach legt ein Mensch bewusst an; der Agent darf nur aus der Liste wählen.
- „Unklar“ ist das Fach für alles, was der Agent nicht sicher zuordnen kann. Unklare Mails werden
  **nicht archiviert** und bleiben im echten Posteingang, bis ein Mensch sie zuordnet. Damit
  enthält der Posteingang im Endzustand nur noch die Unklaren. [meine Entscheidung]

## 5. Sensibel

Sensibel sind Mails mit Login-/Bestätigungscodes, Passwort-Rücksetzlinks, Zugangsdaten,
Kontoauszügen, Ausweis-/Gesundheitsdaten.

- Erkannt wird zuerst über **feste Regeln** (bekannte Absender/Betreffmuster, z. B. Google-
  Sicherheitscode, Bank, Namecheap-Login), danach über das Modell. [meine Entscheidung]
- Der Betreiber akzeptiert, dass das Cloud-Modell den Inhalt dafür **einmal** liest. Später
  übernimmt ein lokales Modell.
- Nach der Erkennung: in Sales nur Konto, Absender, Datum, Betreff, Fach und die Markierung –
  **kein Text, kein Auszug, nicht in der Volltextsuche, an keinen Agenten**.
- Im echten Postfach wird sie in einen Ordner „Sensibel“ verschoben (nicht im Archiv
  untergehen lassen, Posteingang trotzdem leer). [meine Entscheidung]

## 6. Privat, Business und Sichtbarkeit

- **Privat**: liegt in der privaten Ecke des Konto-Besitzers. Nur er sieht sie – auch die
  Leitung nicht. Private Mails fließen nicht ins CRM, nicht zum Vertriebs-Agenten (sales-claw
  Bot), nicht in Business-Analysen. In der privaten Ecke kann der Besitzer trotzdem suchen und
  später eigene Auswertungen fahren.
- **Business**: gehört der Abteilung, der ihr Fach zugeordnet ist (Abschnitt 7). Sichtbar für
  die Mitglieder dieser Abteilung, die Leitung und den Konto-Besitzer.
- **Sichtbarkeit wird in der Datenabfrage durchgesetzt**, nicht nur in der Anzeige: jede Abfrage
  (Seite, Suche, Agent-Werkzeug) läuft über eine zentrale Funktion „sichtbare Mails für Person
  X“. Tests beweisen, dass Person B die privaten Mails von A und Business-Mails fremder
  Abteilungen weder sieht noch findet.

## 7. Abteilungen (Struktur jetzt, Daten später)

- In der Team-Verwaltung bekommt ein Mitarbeiter eine oder mehrere Abteilungen.
- Jede Abteilung besitzt eine Menge Business-Fächer. Vorschlag zum Start (anpassbar in der
  Oberfläche):
  Vertrieb → Kunden & Anfragen, Partner & Netzwerk · Buchhaltung → Rechnungen (Business) ·
  Marketing → Newsletter & Branche, Werbung (Business) · Recruiting → Bewerbungen & Jobs ·
  Technik → Tools & Dienste.
- Ein Fach gehört höchstens einer Abteilung. [meine Entscheidung] Business-Fächer ohne Abteilung
  sieht nur die Leitung und der Konto-Besitzer.
- **Leitung** ist eine Eigenschaft der Person (nicht der Abteilung). Felix ist Leitung.
- Die Leitungsansicht zeigt alle Business-Mails aller Konten, sortiert nach Fach, an jeder Mail
  die Abteilung.
- „Jeder kann seinen Bereich automatisieren“: Die Abteilungszugehörigkeit ist die Grenze, an der
  spätere Agenten/Abläufe eines Mitarbeiters ansetzen. In diesem Vorhaben wird nur die Grenze
  gebaut (Datenmodell + sichtbare-Mails-Funktion), keine Automatisierungs-Oberfläche.
- Heute gibt es außer Felix nur einen Benutzer (Rolle `kalender`). Mit Daten gefüllt wird die
  Struktur zuerst nur mit Felix' Konten.

## 8. Ablauf

1. **Abholen** – ein Hintergrunddienst je Laden holt neue Mails aus dem Posteingang jedes Kontos
   (inkrementell, über UID/UIDVALIDITY) und beim ersten Lauf den **Altbestand** des Posteingangs.
   Gespeichert werden Kopfdaten, Text (gedeckelt wie heute `TEXT_MAX`), Message-ID, Anhang-Namen
   (nicht die Anhänge selbst). [meine Entscheidung] Dieselbe Mail in zwei Konten (gleiche
   Message-ID) wird als eine Mail mit zwei Fundorten geführt.
2. **Einordnen** – Regeln zuerst (Absender/Domain/Betreff → Bereich/Fach/sensibel), dann das
   Modell für den Rest. Das Modell bekommt die Fächerliste und muss genau einen Eintrag daraus
   wählen (strukturierte Antwort), plus privat/Business, sensibel ja/nein, kurze Begründung.
   Jede Einordnung speichert Quelle (Regel / Modell / Mensch) und Zeitpunkt.
3. **Korrigieren** – im Mail-Reiter kann ein Mensch Fach/Bereich/sensibel ändern. Die Korrektur
   wird gespeichert und gilt; [meine Entscheidung] sie wird nicht automatisch zur Regel, die
   Oberfläche kann aber „für diesen Absender immer so“ anbieten.
4. **Archivieren** – erst nach erfolgreicher Einordnung und nur für Fächer ≠ Unklar; sensible
   Mails nach „Sensibel“ (Abschnitt 5). Verschieben, nie löschen. Archivziel je Anbieter
   ermitteln (IMAP `\Archive`, sonst Ordner „Archiv“ anlegen; Gmail: aus INBOX entfernen).
5. **Altbestand in zwei Schritten** – erster Lauf ordnet nur ein, archiviert nichts. Felix sieht
   im Mail-Reiter die Zählung je Fach und Stichproben und gibt dann je Konto „Archivieren“
   frei. Danach archiviert der Dienst laufend neu Eingeordnetes automatisch (pro Konto
   abschaltbar).

## 9. Modell

- [meine Entscheidung] Haiku 5.5 (schnell, günstig, gemessen funktionsfähig in diesem Setup).
- [meine Entscheidung] Aufruf über das OpenClaw-Gateway des Ladens mit einem eigenen Agenten
  ohne Werkzeuge – dasselbe Muster wie sales-auto (`/v1/chat/completions`, Sitzungsschlüssel
  `agent:<id>:…`, Prüfung über `/v1/models`, festes `tool_choice`). Damit läuft es über das
  bestehende Abo/den bestehenden Schlüssel, und ein späteres lokales Modell ist nur ein
  Modellwechsel am Agenten. Die bekannten Fallen dieses Wegs stehen in
  `docs/superpowers/specs/2026-10-29-sales-auto-ueber-openclaw.md`.
- Alles aus der Mail ist Fremddatum; die Mail kann nie eine Anweisung an den Agenten sein.

## 10. Postfächer

- Ein Konto hat eine frei wählbare Kennung (z. B. `gmx-privat`, `gmx-firma`) und einen
  Anbieter (gmx, gmail, namecheap, später outlook). Heute ist Kennung = Anbieter
  (`postfach.ANBIETER`); das wird aufgetrennt, damit mehrere GMX-Konten gehen. Das bestehende
  Namecheap-Postfach (`HAUPT`) wird ein Konto wie die anderen.
- **Postfach hinzufügen** in der Oberfläche: Anbieter wählen, Adresse, Passwort/App-Passwort;
  vor dem Speichern Probe-Anmeldung IMAP und SMTP (wie `deploy/postfach-zugang.sh` heute).
  [meine Entscheidung] Die Zugangsdaten liegen verschlüsselt in der Datenbank (Schlüssel nur in
  der Umgebung des Abhol-Dienstes und von sales-mail), nicht mehr in der `.env` – sonst müsste
  jedes neue Konto einen Dienst neu erzeugen. Bestehende `.env`-Konten werden übernommen.
- Senden aus einem Konto (Antworten vom selben Postfach) bleibt wie seit 28.10. über sales-mail.
- Der Bot im Chat (`postfach_lesen`, `postfach_mail_lesen`) liest künftig aus der Sammelstelle
  statt live per IMAP: nur Business, nie sensibel, nie privat, mit Suche statt „letzte 25“.

## 11. Mail-Reiter in Sales

- Links die Fächer (mit Zahl), oben Bereich privat/Business, Filter nach Konto, Abteilung,
  Zeitraum, sensibel; in der Mitte die Liste; rechts die Mail.
- **Suche** über Absender, Betreff und Text aller sichtbaren Mails (Postgres-Volltext, deutsch)
  [meine Entscheidung]; sensible Mails nur über Absender/Betreff.
- Pro Konto: Stand des Altbestands (eingeordnet / unklar / archiviert) und der Knopf
  „Archivieren freigeben“.
- Gestaltung folgt den bestehenden Seiten (ohne JavaScript, CSRF, Schutzköpfe).

## 12. Rahmenbedingungen aus dem Bestand

- Ladenfest: alles liegt im Schema des Ladens; ein Laden sieht nie Mails eines anderen.
- Keine Geheimnisse und kein Mailinhalt in Logs.
- `postfach.py` war bisher „nur lesend, nie verändern“; seit 27.10. gibt es schon `verschieben`
  (Spam/Unwichtig). Dieses Vorhaben erweitert das bewusst um Archivieren und „Sensibel“ –
  Löschen bleibt ausgeschlossen.
- Tests zuerst, Feature-Branches, Ausrollen nur mit OK des Betreibers.

## 13. Stufen

1. Konten aufgetrennt (mehrere GMX), Postfach hinzufügen in der Oberfläche, Tabellen der
   Sammelstelle, Abhol-Dienst, Einordnung (Regeln + Modell), Mail-Reiter mit Suche – ohne
   Archivieren. Erster Lauf über GMX.
2. Archivieren (Freigabe je Konto), Ordner „Sensibel“, laufender Betrieb; danach Gmail und
   Namecheap. **Voraussetzung:** die bestehenden Leser des echten Posteingangs sind auf die
   Sammelstelle umgestellt (Abschnitt 14.1) – vorher wird in keinem Konto archiviert.
3. Abteilungen und Leitung in der Team-Verwaltung, sichtbare-Mails-Funktion für mehrere
   Personen, Bot-Werkzeug auf die Sammelstelle umgestellt.
4. Später: Outlook, Analyse/Extraktion, lokales Modell, Einrichtungs-Assistent.

## 14. Klärungen nach der Prüfung (30.10.2026)

1. **Bestehende Leser des Posteingangs.** Heute lesen `mail_dispatch.abmeldungen_pruefen()`
   (Newsletter-Abmeldung „Abmelden“, Double-Opt-in-Bestätigungen) und `postfach.lesen()`
   (Kalenderantworten REPLY/COUNTER) die letzten Mails im echten Posteingang. Würde vorher
   archiviert, ginge eine Abmeldung verloren – ein Rechtsproblem. [meine Entscheidung] Der
   Abhol-Dienst gibt jede neue Mail **aller Konten** zuerst an genau diese Prüfungen weiter und
   ordnet erst danach ein; archiviert wird erst, wenn sie gelaufen sind. Die beiden Funktionen
   lesen danach aus der Sammelstelle statt per IMAP. Tests beweisen: eine „Abmelden“-Mail führt
   zur Sperre, auch wenn sie sofort archiviert würde.
2. **Bestehendes Aufräumen (seit 27./28.10.).** [meine Entscheidung] Betrug/Phishing wandert wie
   heute sofort in den Spam-Ordner des Kontos – Spam ist kein Fach, sondern eine eigene
   Entscheidung vor dem Einordnen, und darf auch vor der Archiv-Freigabe laufen. Die Tabelle
   `postfach_mails` (33 Mails) wird durch die Sammelstelle **ersetzt**; ihre Einträge werden
   übernommen, die Werkzeuge `mail_einstufen`/`mail_aufraeumen_*` und die Seite `/posteingang`
   auf die Sammelstelle umgestellt. Heute liegen dort private GMX/Gmail-Mails ohne Besitzer und
   sind für den Bot sichtbar – mit Stufe 1 bekommen sie Besitzer und Bereich, private sind danach
   für den Bot gesperrt.
3. **Wer ist „die Person“.** [meine Entscheidung]
   - Der Mail-Reiter läuft nur mit Anmeldung. Ist `UI_SESSION_SECRET` nicht gesetzt (Übergangs-
     zustand ohne Login), ist der Reiter gesperrt (fail closed).
   - Rolle `lesen` sieht im Mail-Reiter nur ihre Abteilungen; alles andere regelt die
     Eigenschaft „Leitung“. Felix (`freigeben`) bekommt „Leitung“.
   - Bot und spätere Agenten handeln für den Betreiber: Business, nicht sensibel, alle Konten –
     nie privat.
4. **Gleiche Message-ID in zwei Konten.** [meine Entscheidung] Zusammengeführt wird nur innerhalb
   der Konten **desselben Besitzers** und nur bei gleichem Absender und Betreff; sonst zwei
   eigenständige Einträge. Eine gefälschte Message-ID kann so keine fremde Mail umdeuten.
5. **Modellmenge und Vorrang.** [meine Entscheidung] Die Einordnung läuft mit niedriger
   Priorität und gedrosselt über das Gateway; Kundenantworten (Chat, sales-auto) haben Vorrang –
   die Einordnung pausiert, solange dort ein Lauf aktiv ist. Eine Tagesgrenze an eingeordneten
   Mails ist einstellbar. Der Altbestand darf mehrere Tage im Hintergrund brauchen; Abnahme von
   Stufe 1 ist ein vollständig eingeordnetes GMX-Konto, nicht alle Konten.

## 15. Dem Bauenden überlassen

Tabellen- und Spaltennamen, Abholintervall, Stapelgrößen und Drosselung für den Altbestand,
Gestaltung der Regeln im Detail, Verschlüsselungsverfahren (Standardbibliothek/`cryptography`),
genaue Archiv-Erkennung je Anbieter, Aufteilung in Module.
