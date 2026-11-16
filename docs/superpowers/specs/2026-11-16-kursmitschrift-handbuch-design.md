# Kursmitschrift und Kurs-Handbuch – Design

Stand 16.11.2026. Entscheider: Felix. Baut auf der Mitschriften-Ablage auf (Spec `2026-11-14-mitschriften-ablage-design.md`, PR #38, Prod 67adc61).

## Absicht und Warum

Termine in der Rubrik **„Kurse“** sind Kurssitzungen: Felix bringt Diana etwas bei, meist mit geteiltem Bildschirm. Der interne Bericht (Auswertung, Bilder je Thema, Rohtranskript) ist dafür das falsche Format. Felix will daraus zusätzlich eine **Kursmitschrift** – „Bilder mit Summary bzw. den restlichen Daten sinnvoll“.

Wozu (Felix' Worte): für Diana „wiederholen und Handbuch, falls sie was vergisst“; für Felix „Nachbereitungsmaterial“.

Daraus zwei Erzeugnisse (Felix: „A, B gleich mitplanen“, Weg B1 „Okay“):

- **A – Kursmitschrift je Kurstermin:** ein Skript dieser Sitzung zum Wiederholen.
- **B – Kurs-Handbuch je Lernender (B1, Kapitel wachsen mit):** ein Nachschlagewerk nach Themen, das nach jeder Kurssitzung ergänzt wird. Bereits Bekanntes bleibt stehen; nur was neu ist oder anders erklärt wurde, ändert sich.

Beides geht **nur nach Felix' Freigabe** per Mail mit **PDF im Anhang** an Diana (frühere Vorgaben: Versand an Kunden nur nach Freigabe in sales-claw; Mails mit Unterlagen nur mit angehängtem PDF).

## Ziele

1. **Kursmitschrift erzeugen (A).** Sobald eine Mitschrift in der Rubrik „Kurse“ eine fertige Auswertung und einen abgelegten Bericht hat, erzeugt der Taktgeber die Kursmitschrift. Ein KI-Auftrag je Termin mit Transkript (Segmente mit Zeit) und den geprüften Bildern samt Zeitfenster (`aufgenommen_am`–`bis`, `beschreibung`) liefert JSON:
   ```json
   {"ueberblick": "3–5 Sätze",
    "abschnitte": [{"titel": "sprechend, z. B. 'Termin anlegen'",
                    "bilder": [{"bild_id": "…", "zu_sehen": "1 Satz", "erklaert": "Zusammenfassung",
                                "schritte": ["Oben rechts auf … klicken", "…"]}],
                    "merken": ["1–3 Sätze"]}],
    "offen": ["Fragen von Diana / Stellen, an denen sie hing / Nacharbeit für Felix"]}
   ```
   Je Bild fasst die KI zusammen, was gesprochen wurde, während das Bild zu sehen war. `schritte` nur, wo etwas vorgeführt wurde (sonst leer). Sprache: duzt bzw. spricht Diana direkt an, ohne Fachjargon. Bildauswahl wie beim Bericht: nur geprüfte, nicht heikle Bilder (`bildschirm.bilder`), höchstens 6 je Abschnitt, gleichmäßig ausgedünnt; die KI darf ein Bild weglassen (dann erscheint es nicht).
2. **Zwei Fassungen der Kursmitschrift:**
   - **Diana-Fassung:** Kopf (Kurs, Titel, Datum), Inhaltsverzeichnis, Überblick, Abschnitte mit Bild + „Zu sehen“ + „Erklärt“ + nummerierte Schritte + Kasten „Merken“. **Kein** Rohtranskript, **kein** Teil „Offen“, keine internen Teile (Einwände, Painpoints, CRM, Heikel-Zähler).
   - **Felix-Fassung:** wie Diana-Fassung plus Teil „Offen / nachfragen“ am Ende. Kennzeichnung „Intern“.
   Beide als eigenständiges HTML (Bilder eingebettet, druckbar) und die Diana-Fassung zusätzlich als **PDF** (serverseitig erzeugt).
3. **Kurs-Handbuch (B1).** Je Lernendem (Lead, siehe Randbedingungen) ein Handbuch aus **Kapiteln**. Nach jeder neuen Kursmitschrift ordnet ein KI-Auftrag deren Abschnitte den Kapiteln zu – je Abschnitt eine Entscheidung: `ergaenzen` (Kapitel X), `neu` (neues Kapitel mit Titel), `ersetzen` (Teil von Kapitel X ist überholt, weil Felix es jetzt anders erklärt hat). Danach wird **je betroffenem Kapitel** ein Auftrag „Kapitel fortschreiben“ ausgeführt (alter Kapiteltext + neue Abschnitte → neuer Kapiteltext), unveränderte Kapitel bleiben wortgleich. Kapitel speichern Titel, Text (Markdown mit Schritten/Merken), Bild-Verweise und **Quellen** (welche Sitzungen). Jede Änderung legt eine neue Fassung des Kapitels an (alte bleiben lesbar). Kapitel sind nach Themen sortiert (Reihenfolge-Feld; neue Kapitel hinten, Felix kann umsortieren – siehe Ziel 5).
   Handbuch-Ausgabe: HTML + PDF mit Inhaltsverzeichnis, Kapiteln, „Stand: <Datum>, <n> Sitzungen“, je Kapitel „aus Sitzung(en) vom …“.
4. **Versand nach Freigabe.** Nach erfolgreicher Erzeugung legt der Taktgeber **zwei Entwürfe** in `drafts` an (Kanal E-Mail, Empfänger = Diana, `status` wie bei bestehenden Entwürfen „wartet auf Freigabe“):
   - „Kursmitschrift <Titel> vom <Datum>“ mit der Diana-Fassung als PDF (`media_ref`),
   - „Dein Kurs-Handbuch, Stand <Datum>“ mit dem Handbuch-PDF.
   Kurzer Mailtext je Entwurf (fester Baustein, keine KI). Die Entwürfe erscheinen in den bestehenden Freigaben; Felix gibt frei oder verwirft. Der bestehende Versand (`mail_dispatch`) verschickt mit Anhang. Felix bekommt **keine** Kopie per Mail – seine Fassung liegt in sales-ui.
5. **Oberfläche (sales-ui, Hauptpunkt „Mitschriften“, Reiter „Kurse“).** Je Eintrag zusätzlich: „Kursmitschrift (Felix)“ öffnen, „Kursmitschrift (Diana) PDF“, Status (wird erzeugt / fertig / Fehler / zur Freigabe / versendet). Neuer Unterpunkt bzw. Reiter **„Handbücher“**: je Lernendem das aktuelle Handbuch (HTML/PDF), Kapitelliste mit Quellen und Fassungen, Kapitel umbenennen und umsortieren (CSRF), „Handbuch jetzt neu zur Freigabe“ (legt nur einen neuen Entwurf an).
6. **Bestand.** Für die zwei vorhandenen Kurs-Termine (`3c9afada…`, `54ac1821…`) entstehen die Kursmitschriften und das erste Handbuch in zeitlicher Reihenfolge (älterer Termin zuerst). Die daraus entstehenden Entwürfe gehen ganz normal in die Freigabe – nichts wird ohne Felix verschickt.

## Nicht-Ziele

- Allgemeine Kundenfassung des Terminberichts für Nicht-Kurs-Rubriken (bleibt eigener Folgeschritt).
- Automatischer Versand ohne Freigabe, Versand über WhatsApp.
- Handbuch über mehrere Lernende hinweg (ein gemeinsames Handbuch); Bearbeiten von Kapiteltexten von Hand (nur Titel/Reihenfolge).
- Neues KI-Modell oder API-Budget (gleiche KI wie die Auswertung: `ollama.chat` → sales-ki).

## Anti-Ziele (Fehlschlag, auch wenn es technisch läuft)

- Irgendetwas geht ohne Felix' Freigabe an Diana, oder eine Mail geht ohne das PDF raus.
- Die Diana-Fassung oder das Handbuch enthält Rohtranskript, den Teil „Offen“, interne Auswertungsteile oder ein ungeprüftes/heikles Bild.
- Das Handbuch formuliert bei jeder Sitzung alles neu, sodass Diana ihr Nachschlagewerk nicht wiedererkennt.
- Inhalte eines Lernenden landen im Handbuch eines anderen.
- Kursmitschrift, Handbuch-Teile oder PDFs überleben die Löschung ihrer Mitschrift bzw. des Leads (DSGVO).
- Kundeninhalte (Titel, Namen, Text) in Logs.

## Randbedingungen

- **Auslöser:** Mitschrift mit `rubrik = 'Kurse'` (Vergleich wie im Code für Rubriken, Groß/Klein egal), `auswertung_status = 'fertig'`, Bericht abgelegt. Wird eine Mitschrift **aus** „Kurse“ wegverschoben, bleiben schon versendete Dinge versendet, aber noch nicht freigegebene Entwürfe dieser Mitschrift werden verworfen und ihre Abschnitte aus dem Handbuch entfernt (Kapitel fortschreiben ohne diese Quelle; Kapitel ohne Quelle entfällt). Wird eine Mitschrift **nach** „Kurse“ verschoben, läuft sie wie neu.
- **Neu-Auswertung:** Ändert sich die Auswertung oder der geprüfte Bildbestand (wie `bericht_stand`), wird die Kursmitschrift neu erzeugt und die Handbuch-Kapitel dieser Quelle werden fortgeschrieben; offene Entwürfe werden durch neue ersetzt.
- **Lernender:** die Teilnehmer des Termins aus `termin_teilnehmer` ohne eigene Adressen (Postfächer des Ladens), deren `lead_id` gesetzt ist **oder** deren Adresse (Groß/Klein egal) genau einem Lead (`leads.email`) gehört. Stand 16.11.: Bei beiden Diana-Terminen ist `lead_id` leer, die Gast-Adresse gehört aber zu einem Lead – der Adressabgleich ist also nötig. Genau einer → das ist der Lernende (Handbuch-Schlüssel = `lead_id`, Empfänger = seine Adresse). Keiner → Kursmitschrift entsteht, aber kein Handbuch und kein Entwurf; Hinweis im Reiter „Kurse“ („Kein Lernender zugeordnet“). Mehrere → je Lernendem ein Handbuch und eigene Entwürfe.
- **Ablage:** Kursmitschrift-HTML im Mitschriften-Ordner (Unterordner der Rubrik, Namensmuster wie Bericht mit Zusatz `_kurs`/`_kurs-intern`); Handbuch-HTML unter `MITSCHRIFTEN_ORDNER/_handbuecher/`. Die PDFs, die an Entwürfe gehen, im Ordner für erzeugte Unterlagen (`MEDIEN_ERZEUGT_ORDNER`), denn nur von dort löst `media_ref` auf; Name `kurs-<uid8>.pdf` bzw. `handbuch-<lead8>-<stand>.pdf`, damit `medien.pruefe_anhang` sie als Anhang zulässt. Datenbank führt Buch (neue Spalten/Tabellen in `provision.sql`, alle Laden-Schemata).
- **Datenmodell (Vorschlag, Builder darf anpassen):** `termin_mitschriften` + `kurs_json jsonb`, `kurs_stand text`, `kurs_status text`, `kurs_am timestamptz`, `kurs_versuche int`; Tabelle `kurs_handbuch_kapitel(id, lead_id, titel, reihenfolge, aktuelle_fassung)`, `kurs_handbuch_fassung(id, kapitel_id, text_md, bild_ids, quellen uid[], erstellt_am)`, `kurs_entwuerfe(uid|lead_id, draft_id, art)` zur Verknüpfung mit `drafts`.
- **PDF:** serverseitig per Headless-Chromium (`page.pdf`, A4, Bilder eingebettet). Chromium steckt bereits im Image von `sales-auge`; Builder entscheidet, ob die PDF-Erzeugung als Auftrag dort läuft oder ein vorhandener Renderer genutzt wird – kein neues Fremdwerkzeug.
- **Quelle entfernen (Verschieben aus „Kurse“, Löschen, Neu-Auswertung):** Die Zuordnung je Sitzung (welche Abschnitte in welches Kapitel, mit welcher Entscheidung) wird gespeichert. Betroffene Kapitel werden auf die letzte Fassung **vor** dieser Quelle zurückgesetzt, danach werden die späteren Quellen in Datumsfolge erneut eingearbeitet; Fassungen, die Inhalt der entfernten Quelle tragen, werden gelöscht (DSGVO). Nicht betroffene Kapitel bleiben wortgleich. Bei Neu-Auswertung wird die Quelle anschließend wieder eingearbeitet.
- **Reihenfolge:** Das Handbuch arbeitet Kurs-Sitzungen in der Reihenfolge ihres Termin-Beginns ein, jeweils sobald ihre Kursmitschrift fertig ist. Eine Sitzung mit Status „Fehler“ wird übersprungen (das Handbuch läuft weiter); kommt eine ältere Sitzung nachträglich dazu, wird sie wie unter „Quelle entfernen“ an ihrer Datumsstelle eingefügt (Rücksetzen + erneutes Einarbeiten der späteren). Die KI bekommt die Sitzungsdaten mit; `ersetzen` nur durch eine jüngere Sitzung.
- **Größe:** Anhänge dürfen höchstens `medien.MAX_BYTES` (15 MB) groß sein. Bilder im PDF höchstens 800 px, JPEG q60; im Handbuch höchstens 3 Bilder je Kapitel (die jüngsten). Ist ein PDF trotzdem zu groß, entsteht kein Entwurf und der Reiter zeigt „PDF zu groß“ – nie Versand ohne PDF.
- **Offene Entwürfe:** Ein neuer Handbuch-Entwurf ersetzt einen noch nicht freigegebenen älteren desselben Lernenden (der ältere wird verworfen). Freigegebene, in Versand befindliche oder versendete Entwürfe werden nie angefasst. Beim Bestand (Ziel 6) entsteht deshalb im Ergebnis nur ein Handbuch-Entwurf (nach der letzten Sitzung); die Kursmitschrift-Entwürfe je Sitzung bleiben einzeln.
- **Schreibrecht für PDFs:** Der Dienst, der die PDFs in `MEDIEN_ERZEUGT_ORDNER` schreibt, braucht dort einen rw-Mount; heute haben `sales-termine` und `sales-auge` keinen. Der Plan ändert Compose und den Vertrag in `test_proxmox_compose.py` ausdrücklich mit (Dispatcher bleiben `:ro`).
- **Taktgeber:** neuer Schritt nach `ablage`; je Runde höchstens **ein** KI-Auftrag (Kursmitschrift, Zuordnung oder ein Kapitel), nicht wenn ein Termin ansteht oder die KI nicht erreichbar ist (gleiche Regeln wie Einordnung). Fehler → bis zu 3 Versuche im Stundenabstand, danach Status „Fehler“ in der UI.
- **Löschen:** Wer eine Mitschrift löscht, löscht Kursmitschrift-Dateien, PDF und noch nicht versendete Entwürfe mit und schreibt die Handbuch-Kapitel ohne diese Quelle fort (bzw. entfernt die Fassungsbezüge). Lead-Löschung löscht das ganze Handbuch samt Dateien. Der stündliche Abgleich räumt Waisen auf (wie beim Bericht).
- **Sicherung:** `_handbuecher/` liegt im Mitschriften-Ordner und wird damit schon gesichert; die PDFs in `MEDIEN_ERZEUGT_ORDNER` wie bisher.
- **Fremde Daten im Text (Felix: „a“):** Kein eigener Prüf- oder Maskierschritt für Texte. Einziger Schutz ist Felix' Freigabe: Er liest das PDF vor dem Versand und verwirft bei Bedarf. Bilder bleiben wie bisher gefiltert (nur geprüfte, nicht heikle). Die Entwurfs-Vorschau in den Freigaben muss das PDF deshalb vollständig öffnen lassen.
- **Sicherheit/Auslieferung:** wie beim Bericht – nur angemeldet, `Cache-Control: private, no-store`, eigene CSP ohne Skripte, Pfade nur aus der DB.
- **Tests/Betrieb:** Testläufe nur in `~/meeting-test` (DB `meeting_test`, Schema `sales_test`); Ausrollen gezielt per `update.sh`, nur mit Felix' OK.

## Wege (Approaches)

**Kursmitschrift (A):** ein KI-Auftrag je Termin mit strukturierter JSON-Antwort, daraus HTML/PDF – gleiches Muster wie der Bericht. Alternativen nicht sinnvoll: ein Auftrag je Bild vervielfacht die KI-Last und verliert den Zusammenhang; reines Umformatieren des Berichts ohne KI liefert keine Zusammenfassungen.

**Handbuch (B):**
- **B1 – Kapitel wachsen mit (gewählt, Felix „Okay“).** Zuordnung der neuen Abschnitte zu Kapiteln, dann nur betroffene Kapitel fortschreiben, Fassungen gespeichert. Stabil fürs Nachschlagen, Aufwand je Sitzung klein; mehr Bauaufwand.
- B2 – Handbuch nach jeder Sitzung komplett neu aus allen Kursmitschriften. Einfach, aber wechselnde Formulierungen, wachsender Aufwand, irgendwann zu groß für einen Auftrag. Verworfen.

## Von Felix entschieden

- Kursmitschrift für Termine unter „Kurse“, mit Bildern und Zusammenfassung je Bild.
- Empfänger: Diana und Felix; Zweck Wiederholen/Nachschlagen (Diana), Nachbereitung (Felix).
- A und B zusammen planen; Handbuch nach B1.
- Versand nur nach Freigabe in sales-claw, Mails mit Unterlagen nur mit PDF-Anhang (frühere Vorgaben).
- Fremde Daten im gesprochenen Text: kein Maskieren, die Freigabe ist der Schutz (Variante A).

## Calls des Planers (zum Gegenlesen)

- Teil „Offen / nachfragen“ nur in Felix' Fassung, nicht bei Diana.
- Zwei getrennte Entwürfe (Kursmitschrift, Handbuch) statt einer Mail mit zwei Anhängen – ein Entwurf trägt heute genau einen Anhang (`media_ref`).
- Felix bekommt keine Mail-Kopie; seine Fassung liegt in sales-ui.
- Handbuch je Lernendem (Lead), nicht je Laden.
- Kapiteltexte nicht von Hand bearbeitbar (nur Titel/Reihenfolge) – sonst überschreibt die KI beim Fortschreiben Felix' Änderungen.
- Lernender auch über Adressabgleich mit `leads.email` (bei Diana nötig, `lead_id` am Teilnehmer ist leer).
- Quelle entfernen = Kapitel auf Fassung vor der Quelle zurücksetzen und spätere Sitzungen neu einarbeiten; Fassungen mit Inhalt der Quelle werden gelöscht.
- Fehlgeschlagene Sitzungen werden übersprungen; nachträglich ältere Sitzungen werden an ihrer Datumsstelle eingefügt.
- PDF-Größe: Bilder ≤ 800 px q60, Handbuch ≤ 3 Bilder je Kapitel; zu groß → kein Entwurf, Hinweis „PDF zu groß“.
- Neuer Handbuch-Entwurf ersetzt einen noch nicht freigegebenen älteren; beim Bestand entsteht nur ein Handbuch-Entwurf.
- PDF-schreibender Dienst bekommt rw auf `MEDIEN_ERZEUGT_ORDNER`, Compose-Vertrag wird mit angepasst.

## Dem Builder überlassen

- Genaue Prompts, Spalten-/Tabellennamen, Ort der PDF-Erzeugung (innerhalb der Vorgaben).
- Erkennung „Kursmitschrift veraltet“ (analog `bericht_stand`).
- Gestaltung von HTML/PDF im Stil des bestehenden Berichts.
