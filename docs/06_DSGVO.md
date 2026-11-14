# 06 — DSGVO-Handwerk

Stand 27.08.2026 (P2). Zwei definierte Abläufe; alles andere an
Datenschutz-Verhalten (Zustimmungs-Gate, Verschwiegenheit in Posts,
append-only-Protokoll) steht in AGENTS.md und den jeweiligen Werkzeugen.

## Auskunft (Art. 15)

Eine Person will wissen, was über sie gespeichert ist.

1. `kontakt_auskunft(lead_id)` — per Chat („erstell die Auskunft für X")
   oder durch Claude. Ergebnis: vollständiger Markdown-Export
   (Stammdaten, Anreicherung, jede Protokollzeile, jeder Entwurf) unter
   `reports/auskunft-<name>-<datum>.md`.
2. **Der Betreiber prüft und übergibt selbst** — der Export geht nie
   automatisch raus. Frist nach Art. 12: ein Monat.
3. Verlangt der Kontakt die Auskunft im Chat, sagt der Bot es dem
   Betreiber; er stellt den Export nie selbst in den Chat.

- **Mitschriften von Videotreffen** (Meeting-Mittelpunkt, seit 11.11.2026) stehen im
  Abschnitt `Termine` der Auskunft: je Termin des Kontakts Titel, Beginn, Status,
  Mitschrift-Segmente und Auswertung. Das ist der volle Wortlaut, auch mit Äußerungen
  und Sprechernamen anderer Teilnehmer: der Betreiber prüft und schwärzt Fremdes vor der
  Weitergabe (Art. 15 Abs. 4). Adressen anderer Teilnehmer stehen nicht darin.

- **Terminkarten** (seit 24.09.2026) stehen in der Auskunft als Aktivität `terminkarte`
  mit Dateiname, eingesetzten Werten und Fassung der Vorlage. Die Datei selbst liegt in
  `media-erzeugt` des Ladens (Basis-Laden: `media-erzeugt/`, weitere Läden:
  `laeden-daten/<laden>/media-erzeugt/`).

## Löschbegehren (Art. 17)

Eine Person will gelöscht werden.

**Schritt 1 — sofort: `loeschantrag_vermerken(lead_id, quelle, wortlaut)`.**
Wirkung (alles getestet, tests/test_dsgvo.py):

* Kontakt wird archiviert (verschwindet aus allen Listen);
* KEINE neuen Entwürfe mehr, kein Auto-Betrieb — `antwort_entwerfen` und
  `entwurf_erstellen` verweigern mit Verweis hierher;
* kein stilles Zurückholen: `kontakt_wiederherstellen` verweigert;
* der Vermerk selbst steht als `loeschantrag`-Zeile im Protokoll.

Der Bot darf den Vermerk selbst setzen, wenn ein Kontakt die Löschung im
Chat ausdrücklich verlangt (mit Quelle und Wortlaut) — der Vermerk ist
Schutz, kein Risiko. Er informiert den Betreiber sofort.

**Schritt 2 — binnen 30 Tagen: physische Löschung, Menschen-Schritt.**
Bewusst OHNE Werkzeug: die Dienst-Rolle hat kein DELETE, und ein
Lösch-Werkzeug wäre genau der Unfall-Hebel, den es nie geben soll.
Ablauf (Vier-Augen — Betreiber plus eine zweite Person):

1. Prüfen, ob gesetzliche Aufbewahrungspflichten entgegenstehen
   (Vertragsunterlagen: §257 HGB / §147 AO — dann Einschränkung statt
   Löschung, dem Antragsteller so mitteilen).
2. Auf der Datenbank-Maschine mit der OWNER-Rolle (nicht der
   Dienst-Rolle), `<LEAD>` ersetzt:

```sql
-- activities und drafts haengen mit ON DELETE CASCADE am Kontakt:
DELETE FROM sales.leads WHERE id = '<LEAD>';
```

3. Dateien nachziehen — physisch zu löschende Stellen:
   - `reports/` und `media/` auf Dateien zu dieser Person durchsehen und
     entfernen (auch die Auskunfts-Exporte).
   - **Terminkarten-Dateien** des Kontakts: `terminkarte-<kunde>-*.pdf` in `media-erzeugt`
     des Ladens — die Namen stehen in den Aktivitäten `terminkarte` des Kontakts. Gedruckte
     Karten beim Teamleiter sind Papier und gehören in die Rückfrage an ihn.
   - **Termin-Akten** (Meeting-Mittelpunkt): `termin_teilnehmer` hängt NICHT per
     Kaskade am Kontakt — die Zeilen mit seiner Adresse (`lower(adresse) =
     '<adresse>'`, nach dem Löschantrag `grund = 'gesperrt'`, Name schon leer)
     stehen weiter da; die Adresse bleibt bewusst, solange sie auf der
     Sperrliste steht (der Kalenderabgleich legt die Person sonst neu an).
     Zusätzlich `termin_akten.titel`/`thema`/`beschreibung` dieser Termine
     prüfen: nennen sie die Person (z. B. „Gespräch mit …“), Titel neutral
     setzen bzw. Beschreibung leeren. Mitschrift, Auswertung und Briefing hat
     der Löschantrag schon entfernt.
4. Sicherungen: die rotierenden Volume-Sicherungen (7 Tage) und
   DB-Sicherungen laufen aus; bis dahin gilt die Verarbeitung als
   eingestellt (Vermerk-Vollstopp). Nicht einzeln in Archive hineinoperieren.
5. Löschprotokoll führen OHNE Personenbezug: Datum, wer (beide Namen),
   Fundstellen geprüft ja/nein. Ablage beim Betreiber, nicht im Repo.

## Mitschriften von Videotreffen (Meeting-Mittelpunkt, seit 11.11.2026)

Checkliste für Transkripte:

- [ ] **Was gespeichert wird:** Mitschrift (Segmente mit Sprecher und Text),
      Auswertung (JSON und Markdown), Vorschläge und das Briefing in der Termin-Akte
      (`termin_mitschriften`, `termin_vorschlaege`, `termin_akten.briefing_*`). Nur im
      eigenen Schema des Ladens, nie in `activities` (die bleibt append-only; dort steht
      nur, was der Betreiber bestätigt).
- [ ] **Wo:** Mitschrift auf unseren eigenen Servern (Vexa auf der VM, Datenbank des
      Ladens). Kundentext geht nur an `OLLAMA_URL`. Die Einladung mit Videolink trägt
      einen Hinweis auf die Mitschrift.
- [ ] **Übergang seit 12.11.2026 (Betreiber-Entscheid, noch kein produktiver Betrieb):**
      `OLLAMA_URL` zeigt auf das KI-Tor `sales-ki`, also auf **Claude Code (Anthropic)**
      mit dem Abo des Betreibers. Briefing-Fakten und Mitschrift-Stücke gehen damit an
      einen Cloud-Anbieter. Vor echten Kundengesprächen klären: Auftragsverarbeitung mit
      Anthropic (AV-Vertrag, Drittland), Hinweis in der Einladung und in der
      Datenschutzerklärung. Der Satz „Die Mitschrift bleibt auf unseren eigenen Servern“
      ist deshalb aus der Einladung gestrichen. Zurück: `OLLAMA_URL` auf ein eigenes
      Modell, `sales-ki` stoppen, Satz wieder aufnehmen.
- [ ] **Kein Rohmitschnitt bei Vexa (Abnahme 12.11.2026):** Vexa legt ab Werk von jedem
      Meeting einen „captured-signal“-Mitschnitt (Signal, Spracherkennung, Mitschrift) als
      Testmaterial im eigenen Speicher ab (Bucket `vexa`, Präfix `signal/`, Budget 50 GB) und
      löscht ihn beim Löschen des Meetings **nicht**. `deploy/vexa-anbinden.sh` setzt deshalb
      bei jedem Lauf den Not-Aus `diagnostics.capture_signal=false`. Die vier Mitschnitte der
      Abnahme-Termine vom 12.11.2026 (nur Betreiber-Testgespräche) sind gelöscht. Prüfen nach
      jedem Vexa-Update: Speicher unter `signal/` bleibt leer (Runbook, Vexa-Betrieb).
- [ ] **Löschweg:** `loeschantrag_vermerken` räumt zuerst ab (scheitert das, kommt ein
      Fehler, der Kontakt wird nicht vermerkt, der Aufruf ist wiederholbar), dann der
      Vermerk. Es beendet einen anstehenden oder laufenden Bot (Status
      `ohne_aufnahme`; den Bot holt der Taktgeber `sales-termine` binnen einer Runde aus
      dem Termin — nur er spricht mit dem Transkriptionsdienst), löscht die Mitschriften
      **aller** Termine, an denen der Kontakt teilnahm (auch wo er schon entknüpft ist —
      Abgleich über seine E-Mail-Adresse), lehnt einen offenen Zusammenfassungs-Entwurf ab,
      leert das Briefing dieser Akten und löst den Kontakt aus der Teilnehmerliste
      (`grund = 'gesperrt'`, Name geleert, nur die Adresse bleibt). Das beim
      Transkriptionsdienst liegende Meeting löscht ebenfalls der Taktgeber.
      Sicherungen laufen wie oben aus.
- [ ] **Auskunft:** `kontakt_auskunft` enthält Abschnitt `Termine` mit Mitschrift und
      Auswertung. Die Mitschrift ist vollständig und enthält damit auch Äußerungen
      und Sprechernamen **anderer Teilnehmer**; Adressen anderer Teilnehmer stehen
      nicht darin. Der Betreiber prüft den Export und schwärzt Fremdes vor der
      Weitergabe (Art. 15 Abs. 4: Rechte Dritter).

## Standbilder geteilter Bildschirme (Bildauswertung, seit 13.11.2026)

Checkliste für den Dienst `sales-auge` („Laura (Bildschirm)“, Runbook: Abschnitt Bildauswertung):

- [ ] **Was gespeichert wird:** Standbilder des geteilten Bildschirms (JPEG, Breite höchstens 1600 px), eine
      Beschreibung je Bild und zwei Vektoren (`termin_bilder`, `vektor_bild`, `vektor_text`). Höchstens ein Bild alle
      5 s und nur bei spürbarer Änderung. Kein Video, keine Rohdatei.
- [ ] **Wo:** nur im eigenen Schema des Ladens (Datenbank auf unserem Server). Die Vektoren rechnet fastembed lokal
      im Container. Ein Bild geht nur an das KI-Tor `sales-ki` (siehe Übergang).
- [ ] **Nur interne Termine, nur per Schalter:** „Bildschirm auswerten“ in der Termin-Akte, vorbelegt aus, je Termin
      bewusst einzuschalten. Stufe 1 läuft in keinem Kundentermin.
- [ ] **Keine Kameras, kein Ton:** gelesen werden nur entfernte Bildschirm-Tracks (`screenshare`). Der Beobachter tritt
      stumm bei und sendet nichts. Wer teilt, ist egal; was die Kamera zeigt, wird nie erfasst.
- [ ] **Beschreibung über Anthropic (Übergang):** die Beschreibung entsteht über das KI-Tor `sales-ki`, im Übergang
      also bei **Claude Code (Anthropic)**; das Bild selbst geht dafür an diesen Cloud-Anbieter. Es gilt derselbe
      Vorbehalt wie im Absatz „Übergang seit 12.11.2026“ im Abschnitt Mitschriften (AV-Vertrag, Drittland, Hinweis;
      vor echten Kundengesprächen klären).
- [ ] **Heikle Bildschirme werden nicht gespeichert:** Anmelde-, Bezahl- und Postfach-Bildschirme sollen nicht in der
      Akte landen. Schicht A (lokale Bildprüfung vor dem Speichern, Schwelle `AUGE_HEIKEL_ABSTAND`) fängt nach der
      Kalibrierung vom 14.11.2026 nur **etwa 15 %** (Fehlalarme 1,4 %). Schicht B ist die eigentliche Absicherung: das
      Bildmodell meldet beim Beschreiben HEIKEL, dann wird die ganze Zeile gelöscht (Bild, Beschreibung, Vektoren).
      Beschreibt das Modell das Bild stattdessen, greift ein **Stichwort-Netz** (Passwort, Anmeldung, Login, Checkout,
      Zahlung, Kreditkarte, IBAN, Posteingang, Outlook, GMX u. ä. in der Beschreibung): das Bild wird ebenso gelöscht.
      **Nur geprüfte Bilder sind sichtbar (fail-closed):** solange ein Bild nicht fertig beschrieben ist (offen oder
      nach einem KI-Fehler), zeigen es weder die Akte noch die Vorschaubilder noch die Bildsuche (Oberfläche und
      MCP-Werkzeug) noch der Einzelabruf – für niemanden. Fällt die KI aus, wird ohne Obergrenze weiter versucht (30 s,
      danach alle 5 min); ein nach **24 Stunden** noch ungeprüftes Bild wird vollständig gelöscht (es geht dann verloren).
      **Ehrlich dazu:** ein heikles Bild liegt bis zur Beschreibung in der Datenbank – je nach Warteschlange **Minuten,
      nicht nur Sekunden** (bei KI-Ausfall bis zu 24 h) –, ist in dieser Zeit aber nicht abrufbar. Und es **ist für die
      Prüfung an das KI-Tor und damit im Übergang an Anthropic gegangen**; gelöscht wird es erst danach. Es gibt keinen
      Weg, das Bild vorher zu prüfen, ohne es zu sehen. Die Akte zeigt, wie viele Bildschirme nicht gespeichert wurden
      (Zähler `bilder_uebersprungen`, nur die Zahl). Bleibt trotzdem eines gespeichert, löscht der Betreiber es in der
      Akte („Löschen“). Vor Kundenterminen gehört das in den Einladungshinweis (siehe unten).
- [ ] **Mehrere Freigaben:** bis zu 3 gleichzeitig geteilte Bildschirme werden erfasst; Kameras und Ton nie.
- [ ] **Löschung mit der Mitschrift:** Bilder, Beschreibungen und Vektoren verschwinden auf jedem Löschweg der
      Mitschrift (`mitschrift_entfernen`, Sicherheitsnetz `_mitschriften_abraeumen`, `loeschantrag_vermerken`). Einzelne
      Bilder löscht der Betreiber in der Akte („Löschen“).
- [ ] **Agent bekommt keinen Bildinhalt:** das MCP-Werkzeug `termin_bilder_suchen` liefert dem Agenten (Cloud-Modell)
      nur Fundstellen (id, uid, Zeit, score, Link auf die Akte), **keine Beschreibung** und keine Bilddaten. Den Inhalt
      sieht nur der Betreiber in der Akte.
- [ ] **Auskunft:** `kontakt_auskunft` enthält **keine** Standbilder und keine Beschreibungen (nur Mitschrift und
      Auswertung). Bei einem Auskunftsersuchen prüft der Betreiber die Bilder der betroffenen Termine in der Akte und
      gibt sie von Hand mit, Bilder anderer Teilnehmer geschwärzt (Art. 15 Abs. 4). Offen: Export in
      `kontakt_auskunft` aufnehmen.
- [ ] **Offen, vor Kundenterminen:** Hinweis in der Einladung („bitte keine persönlichen Daten zeigen, sonst wird die
      Aufzeichnung gelöscht“) und Schalter auch dort. **Noch nicht umgesetzt**; bis dahin kein Kundentermin.

## Werbe-Einwilligung (§ 7 UWG, seit 31.08.2026)

Neben der DSGVO (Datenverarbeitung) gilt das UWG (Ansprache): elektronische
Werbung per WhatsApp/E-Mail braucht eine Einwilligung oder die
Bestandskunden-Ausnahme des § 7 Abs. 3 UWG.

- **Das Tor sitzt im Werkzeug:** `entwurf_erstellen` lehnt Erstansprachen
  (der Kontakt hat nie selbst geschrieben) ohne `consent_status`
  `opt_in`/`existing_customer` ab. Antworten auf eingehende Nachrichten
  und LinkedIn-Beiträge aufs eigene Profil bleiben frei.
- **Erfassen ist Menschensache:** `einwilligung_erfassen(lead_id, art,
  quelle, wortlaut)` — die Quelle ist Pflicht, alles landet als
  `werbe_einwilligung` im Protokoll (activities). Der Bot ruft es nur auf
  ausdrückliche Nennung durch den Betreiber auf, nie aus eigener Deutung.
- **Betreiber-Vorgabe (30.10.2026, ausdrückliche Entscheidung des
  Betreibers):** jeder Kontakt trägt die Grundlage `betreiber_auftrag` —
  neue bei `kontakt_anlegen`, eingeordnete per vorab gesetztem Haken,
  bestehende per einmaliger Sammelbestätigung. Das ist KEIN opt_in: der
  Eintrag dokumentiert, dass der Betreiber die Grundlage verantwortet; das
  Abmahnrisiko bei fehlender echter Einwilligung trägt er. Nie gebucht bei
  Löschantrag, Privat, Verbotsliste oder nach Widerruf
  (`server._grundlage_vorgabe`, Tests `test_einwilligung_vorgabe.py`).
- **Widerruf:** `einwilligung_widerrufen(lead_id, grund)` wirkt sofort;
  „keine Werbung mehr" im Chat zählt als Widerruf.
- **Abgrenzung:** die Zustimmung (`zustimmung_*`) erlaubt die automatische
  Antwort, die Einwilligung (`einwilligung_*`) die werbliche Ansprache
  überhaupt. Ein Löschantrag (oben) schlägt beides: Vollstopp.

Verträge: `sales-mcp/tests/test_uwg.py`.

## Kollegen-Kalender (Team-Sicht, seit 12.09.2026)

Ein Kollege kann seinen eigenen Kalender über eine geheime iCal-Adresse mit
`sales-claw` verbinden (`/team/kalender`), damit Terminvorschläge nicht mit
ihm kollidieren — Auslöser war der ausdrückliche Betreiber-Wunsch „dass
Ivans und meiner dann berücksichtigt wird".

**Wer sieht was, auf welcher Grundlage.**

- **Was verarbeitet wird:** Titel, Ort und Zeitraum jedes Termins im
  verbundenen Kalender des Kollegen — nicht mehr, als der Kalender selbst
  hergibt. Die Adresse (das Geheimnis, das den Zugriff trägt) wird
  gespeichert (`sales.kalender_quellen.url`), aber nie angezeigt oder
  geloggt (Spec §4, technisch durchgesetzt — siehe 08_TOMS.md).
- **Wer es sieht:** der Betreiber (Rolle `lesen`/`freigeben`) über
  `/kalender` — dort mit Kundenname, Thema und Ort, denn genau das braucht
  die Kollisionsprüfung und ist die vom Betreiber gewählte Sichtbarkeits-
  stufe „Alles — Kunde, Thema, Ort" (Spec §4). Der Kollege selbst (die
  eigens dafür geschaffene, schmale Rolle `kalender`) sieht denselben
  Kalender-Abschnitt — inklusive der Termine anderer Kollegen, denn die
  Kollisionsprüfung ist eine Team-Angelegenheit —, aber ausdrücklich
  **nicht** den übrigen Kundenstamm: `/kontakte`, `/posteingang` und
  innerhalb von `/kalender` auch offene Wiedervorlagen samt Notiz sowie
  rohe, noch nicht terminierte Anfragetexte bleiben ihr verborgen (W5,
  Schlussprüfung 13.09.2026 — das sind keine Termindaten). Vertrag:
  `sales-mcp/tests/test_kalender_verbinden.py::
  test_rolle_kalender_sieht_termine_aber_keine_wiedervorlagen_oder_anfragen`.
- **Rechtsgrundlage:** das Verbinden ist eine bewusste, selbst ausgeführte
  Handlung des Kollegen (er trägt die geheime Adresse selbst ein — kein
  automatischer Zugriff auf ein fremdes Konto), zum Zweck der internen
  Terminabstimmung zwischen Kollegen desselben Betriebs. Das trägt sich auf
  ein berechtigtes betriebliches Interesse (Art. 6 Abs. 1 lit. f DSGVO) an
  kollisionsfreier Terminplanung; eine betriebliche Anweisung/Einwilligung
  im Innenverhältnis ist die sauberere Grundlage, wo eine solche ohnehin
  vorliegt (z. B. Arbeitsvertrag, Betriebsvereinbarung) — das entscheidet
  der Betreiber, siehe „Grenze" unten.
- **Widerruf:** der Kollege setzt seine Adresse beim eigenen Anbieter
  jederzeit selbst zurück — der Zugriff endet damit sofort, ohne dass
  `sales-claw` etwas tun muss (die alte Adresse wird beim nächsten Abruf
  nur noch mit Fehler quittiert). Zusätzlich kann der Besitzer (oder die
  Rolle `freigeben`) jede Quelle über `/team/kalender` entfernen — seit
  08.11.2026 wird dabei die Quellenzeile samt Adresse bzw. Google-Zugang
  und alle abgeglichenen Termine **gelöscht** (siehe unten, Kalender
  verbinden).
- **Aufbewahrung:** eine entfernte Quelle hinterlässt keine Zeile mehr;
  die Löschung ist das Gegen-Ereignis.

### Kalender verbinden: Besitzer, Bereich und Google (seit 08.11.2026)

Jede Kalenderquelle hat einen **Besitzer** (die Person, die sie verbunden
hat) und einen **Bereich**: Business oder Privat. Bestehende iCal-Kalender
gehören nach der Umstellung dem Laden-Besitzer und sind Privat, bis er sie
auf `/team/kalender` einstuft.

- **Fremde Privat-Termine nur mit Zeit.** Für eine Quelle im Bereich Privat,
  die dem Betrachter nicht gehört (Betrachter ist der Laden-Besitzer,
  `POST_BESITZER`), werden Titel und Ort **gar nicht erst gespeichert** —
  auch nicht kurzzeitig, nicht in Logs, nicht in Fehlertexten. Gespeichert
  und angezeigt wird nur die Zeit, als Block „Privattermin“. Wechselt eine
  fremde Quelle von Business auf Privat, sind die gespeicherten Titel und
  Orte sofort gelöscht, nicht erst beim nächsten Abgleich. Der Name eines
  fremden Privat-Kalenders erscheint als „Privat (<Besitzer>)“.
- **Agent.** Er sieht fremde Privat-Termine ebenfalls nur als Zeitblock.
  Fehlt eine Quelle oder ist sie veraltet (älter als 15 Minuten) oder
  fehlerhaft, meldet er „unvollständig“, nie „frei“. Als „frei“ markierte
  Termine (z. B. Geburtstage) blockieren nicht.
- **Google-Zugang.** Verbindet ein Nutzer Google, erhält `sales-claw`
  ausschließlich Leserechte (Google zeigt „Kalender ansehen“; Scopes
  `calendar.calendarlist.readonly` und `calendar.events.readonly`). Der
  Refresh-Token wird nur **versiegelt** gespeichert (RSA-OAEP plus
  AES-GCM): die Oberfläche kennt nur den öffentlichen Schlüssel, der
  private liegt allein im Dienst `sales-kalender`. Im Klartext erscheint
  der Token weder in Anzeige noch Log noch Fehlertext.
- **Abgerufene Felder.** Nur Kennung, Status, Titel, Ort, Beginn, Ende und
  „frei/beschäftigt“ des Termins; abgesagte Termine werden verworfen.
  Abgleichfenster: 30 Tage zurück, 180 Tage voraus.
- **Löschung.** „Entfernen“ löscht Quelle und zugehörige Termine; entfernt
  man den letzten Kalender eines Google-Kontos, wird auch der gespeicherte
  Zugang vernichtet. Ein beim Verbinden nicht übernommener Zugang wird nach
  einer Stunde vernichtet. Den Zugriff beim Anbieter entzieht der Nutzer
  selbst unter myaccount.google.com/permissions.
- **Rechte.** Entfernen, Pausieren und Bereich ändern darf nur der Besitzer
  der Quelle oder die Rolle `freigeben`.
- **Altbestand.** Vor dieser Version wurde „Entfernen“ nur weich gelöscht:
  die Zeile blieb mit `aktiv = false` und `url = null` stehen (die Adresse
  war weg, Name und abgeglichene Termine nicht). Diese Zeilen gibt es noch.
  Einmalige Bereinigung, nur mit OK des Betreibers, je Schema (zuerst die
  Termine, dann die Quellen; nichts anderes wird berührt):

  ```sql
  delete from <schema>.kalender_termine where quelle_id in
    (select id from <schema>.kalender_quellen
      where art = 'ics' and aktiv = false and url is null);
  delete from <schema>.kalender_quellen
    where art = 'ics' and aktiv = false and url is null;
  ```

  Vorher mit `select count(*)` zählen. Dafür braucht es die Owner-Rolle
  (`supabase_admin`), die Dienst-Rolle löscht nur Quellen über die Oberfläche.

## Wartelisten-Kontakte (vibemind.space, seit 13.11.2026)

Der Wartelisten-Abgleich (`docs/03_RUNBOOK.md`) legt Menschen als Kontakte an,
die sich auf der Website auf die Warteliste gesetzt haben.

- **Was übernommen wird:** E-Mail-Adresse, Zeitpunkt der Anmeldung, Zeitpunkt
  der Bestätigung (falls vorhanden) und die Herkunft der Zeile. Sonst nichts;
  die Warteliste kennt keinen Namen, als Name steht der Teil vor dem @.
- **Wer übernommen wird:** die Einträge aus der Zeit vor dem Double-Opt-in
  und alle, die ihre Adresse seither bestätigt haben. Unbestätigte neue
  Anmeldungen kommen nicht an; die Website liefert sie nicht aus.
- **Keine Werbe-Einwilligung:** eine Wartelisten-Anmeldung ist keine
  Einwilligung in Werbung. Der Abgleich bucht deshalb NICHTS — der Kontakt
  bleibt auf `consent_status = 'unknown'`, das Tor oben verweigert die
  Erstansprache. Die Betreiber-Vorgabe vom 30.10.2026 gilt für
  `kontakt_anlegen`; der Abgleich geht bewusst nicht über dieses Werkzeug.
  Wer Wartelisten-Kontakte anschreiben will, entscheidet das als Betreiber
  je Kontakt oder per Sammelbestätigung und trägt die Grundlage selbst.
- **Verbotsliste:** vor dem Anlegen wird `compliance.sperrliste` gefragt.
  Wer sich abgemeldet, widerrufen oder Löschung verlangt hat, wird über die
  Warteliste nicht erneut erfasst.
- **Löschbegehren:** der Ablauf oben gilt unverändert. Zusätzlich muss die
  Zeile in der Warteliste der Website gelöscht werden — das ist ein eigener
  Bestand mit eigenem Schritt, den der Abgleich nicht anfasst (er schreibt
  nie zurück). Bleibt sie dort stehen, verhindert nur die Verbotsliste das
  Wiederanlegen.
- **Austragung:** wer die Warteliste verlässt, bleibt als Kontakt stehen
  (`enrichment.waitinglist.auf_liste = false`). Eine Löschfrist für
  Wartelisten-Kontakte, die nie Kunde wurden, ist noch nicht festgelegt —
  Entscheidung des Betreibers.
- **Zugang:** der Abholschlüssel darf bei der Website die Warteliste lesen
  und die Adressen abholen, die auf ihre Bestätigungsmail warten (nächster
  Abschnitt). Er liegt in der `.env` des Wirts, nicht im Container.

## Bestätigungsmails der Warteliste (vibemind.space, seit 13.11.2026)

Der Laden verschickt für die Website die Bestätigungsmail des Double-Opt-in
(`docs/03_RUNBOOK.md`).

- **Was verarbeitet wird:** die E-Mail-Adresse, die jemand ins Formular der
  Website eingetragen hat, und ein Einmal-Token. Beides nur für den Versand
  dieser einen Mail, im Arbeitsspeicher; gespeichert wird hier nichts, weder
  als Kontakt noch als Aktivität noch als Kopie im Gesendet-Ordner.
- **Zweck und Grundlage:** die Mail prüft, ob die Adresse dem gehört, der sie
  eingetragen hat. Sie enthält keinen Werbetext; eine Bestätigungsmail darf
  keinen enthalten.
- **Fremde Adressen:** das Formular ist offen, jemand kann eine Adresse
  eintragen, die ihm nicht gehört. Deren Inhaber bekommt dann höchstens eine
  Mail pro Stunde und drei in 24 Stunden; ohne Klick verfällt die Anmeldung
  bei der Website nach sieben Tagen und kommt nie als Kontakt hier an.
- **Verbotsliste:** wer sich abgemeldet, widerrufen oder Löschung verlangt
  hat, bekommt auch die Bestätigungsmail nicht.
- **Protokoll:** im Journal stehen Zahlen und verdeckte Adressen, nie eine
  vollständige Adresse und nie ein Token.
- **Empfänger der Daten:** der Mailanbieter des Ladens (`SMTP_HOST`), wie bei
  jeder anderen ausgehenden Mail.

## Grenze

Dieses Dokument ist Betriebsanleitung, keine Rechtsberatung. Bei
Streitfällen (Auskunftsumfang, Aufbewahrungsfristen, Reichweite der
Bestandskunden-Ausnahme) entscheidet der Betreiber mit rechtlicher
Beratung — nicht Claude, nicht der Bot.
