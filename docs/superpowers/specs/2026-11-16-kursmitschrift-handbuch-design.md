# Kursmitschrift und Kurs-Handbuch – Design

Stand 19.11.2026 (Fassung 2). Entscheider: Felix. Baut auf der Mitschriften-Ablage auf (Spec `2026-11-14-mitschriften-ablage-design.md`, PR #38, Prod 67adc61).

## Absicht und Warum

Termine in der Rubrik **„Kurse“** sind Kurssitzungen: Felix bringt Diana etwas bei, meist mit geteiltem Bildschirm. Der interne Bericht (Auswertung, Bilder je Thema, Rohtranskript) ist dafür das falsche Format. Felix will daraus zusätzlich eine **Kursmitschrift** – „Bilder mit Summary bzw. den restlichen Daten sinnvoll“.

Wozu (Felix' Worte): für Diana „wiederholen und Handbuch, falls sie was vergisst“; für Felix „Nachbereitungsmaterial“.

Daraus zwei Erzeugnisse (Felix: „A, B gleich mitplanen“, Weg B1 „Okay“):

- **A – Kursmitschrift je Kurstermin:** ein Skript dieser Sitzung zum Wiederholen.
- **B – Kurs-Handbuch je Lernender (B1, Kapitel wachsen mit):** ein Nachschlagewerk nach Themen, das nach jeder Kurssitzung ergänzt wird. Bereits Bekanntes bleibt stehen; nur was neu ist oder anders erklärt wurde, ändert sich.

**Versand:** Felix 19.11.: „noch nicht versenden, ich mach das diesmal manuell“. sales-claw legt **keine Entwürfe** an und verschickt nichts; Felix lädt die PDFs in sales-ui herunter und schickt sie selbst. Hintergrund: Dianas Kontakt trägt den Vermerk „privat“ – sales-claw lehnt Entwürfe an private Kontakte ab, und der Bot nimmt Termine mit privaten Teilnehmern nicht auf. Kurstermine mit Diana hängen deshalb an einem anderen (Test-)Kontakt; der **Lernende wird je Kurstermin von Felix gewählt**.

## Ziele

1. **Kursmitschrift erzeugen (A).** Sobald eine Mitschrift in der Rubrik „Kurse“ eine fertige Auswertung und einen abgelegten Bericht hat, erzeugt der Taktgeber die Kursmitschrift. Ein KI-Auftrag je Termin mit Transkript (Segmente mit Zeit) und den geprüften Bildern samt Zeitfenster (`aufgenommen_am`–`bis`, `beschreibung`) liefert JSON:
   ```json
   {"ueberblick": "3–5 Sätze",
    "abschnitte": [{"titel": "sprechend, z. B. 'Termin anlegen'",
                    "bilder": [{"bild_id": "…", "zu_sehen": "1 Satz", "erklaert": "Zusammenfassung",
                                "schritte": ["Oben rechts auf … klicken", "…"]}],
                    "merken": ["1–3 Sätze"]}],
    "offen": ["Fragen der Lernenden / Stellen, an denen sie hing / Nacharbeit für Felix"]}
   ```
   Je Bild fasst die KI zusammen, was gesprochen wurde, während das Bild zu sehen war. `schritte` nur, wo etwas vorgeführt wurde (sonst leer). Sprache: spricht die Lernende direkt an (Du), ohne Fachjargon. Bildauswahl wie beim Bericht: nur geprüfte, nicht heikle Bilder (`bildschirm.bilder`), höchstens 6 je Abschnitt, gleichmäßig ausgedünnt; die KI darf ein Bild weglassen. Die Kursmitschrift braucht **keinen** Lernenden.
2. **Zwei Fassungen der Kursmitschrift:**
   - **Lernenden-Fassung:** Kopf (Kurs, Titel, Datum), Inhaltsverzeichnis, Überblick, Abschnitte mit Bild + „Zu sehen“ + „Erklärt“ + nummerierte Schritte + Kasten „Merken“. **Kein** Rohtranskript, **kein** Teil „Offen“, keine internen Teile (Einwände, Painpoints, CRM, Heikel-Zähler).
   - **Felix-Fassung:** wie oben plus Teil „Offen / nachfragen“ am Ende. Kennzeichnung „Intern“.
   Beide als eigenständiges HTML (Bilder eingebettet, druckbar), die Lernenden-Fassung zusätzlich als **PDF** (serverseitig erzeugt).
3. **Lernender je Kurstermin.** Felix wählt im Reiter „Kurse“ je Termin den Lernenden (einen Kontakt, auch einen privaten). Vorschläge: Teilnehmer des Termins mit Kontakt und zuletzt gewählte Lernende. Ohne Wahl entsteht die Kursmitschrift trotzdem, fließt aber nicht ins Handbuch; Hinweis „Lernenden wählen“. Wechselt die Wahl, wird der Termin aus dem alten Handbuch entfernt und ins neue eingearbeitet.
4. **Kurs-Handbuch (B1).** Je Lernendem ein Handbuch aus **Kapiteln**. Nach jeder neuen Kursmitschrift ordnet ein KI-Auftrag deren Abschnitte den Kapiteln zu – je Abschnitt eine Entscheidung: `ergaenzen` (Kapitel X), `neu` (neues Kapitel mit Titel), `ersetzen` (Teil von Kapitel X ist überholt, weil Felix es jetzt anders erklärt hat). Danach wird **je betroffenem Kapitel** ein Auftrag „Kapitel fortschreiben“ ausgeführt (alter Kapiteltext + neue Abschnitte → neuer Kapiteltext), unveränderte Kapitel bleiben wortgleich. Kapitel speichern Titel, Text (Markdown mit Schritten/Merken), Bild-Verweise und **Quellen** (welche Sitzungen). Jede Änderung legt eine neue Fassung an (alte bleiben lesbar). Reihenfolge-Feld; neue Kapitel hinten, Felix kann umsortieren.
   Ausgabe: HTML + PDF mit Inhaltsverzeichnis, Kapiteln, „Stand: <Datum>, <n> Sitzungen“, je Kapitel „aus Sitzung(en) vom …“. Kein „Offen“.
5. **Oberfläche (sales-ui, Hauptpunkt „Mitschriften“).** Reiter „Kurse“: je Eintrag zusätzlich „Kursmitschrift (Felix)“ öffnen, „Kursmitschrift PDF herunterladen“, Lernenden wählen/ändern, Status (wird erzeugt / fertig / Fehler / Lernenden wählen). Neuer Reiter **„Handbücher“**: je Lernendem das aktuelle Handbuch (HTML öffnen, PDF herunterladen), Kapitelliste mit Quellen und Fassungen, Kapitel umbenennen und umsortieren (CSRF), „Handbuch neu ausgeben“.
6. **Bestand.** Die vorhandenen Kurs-Termine (`3c9afada…`, `54ac1821…`, dazu der Kurs vom 19.11.) bekommen Kursmitschriften; sobald Felix Diana als Lernende wählt, entsteht ihr Handbuch in zeitlicher Reihenfolge.

## Nicht-Ziele

- Versand durch sales-claw (Entwürfe, Mail, WhatsApp) – späterer eigener Schritt, falls Felix ihn will.
- Änderungen am Privat-Vermerk oder an den Sperrregeln für Bot und Entwürfe.
- Allgemeine Kundenfassung des Terminberichts für Nicht-Kurs-Rubriken.
- Ein gemeinsames Handbuch über mehrere Lernende; Bearbeiten von Kapiteltexten von Hand (nur Titel/Reihenfolge).
- Neues KI-Modell oder API-Budget (gleiche KI wie die Auswertung: `ollama.chat` → sales-ki).

## Anti-Ziele (Fehlschlag, auch wenn es technisch läuft)

- sales-claw verschickt irgendetwas davon oder legt einen Entwurf an.
- Die Lernenden-Fassung oder das Handbuch enthält Rohtranskript, den Teil „Offen“, interne Auswertungsteile oder ein ungeprüftes/heikles Bild.
- Das Handbuch formuliert bei jeder Sitzung alles neu, sodass Diana ihr Nachschlagewerk nicht wiedererkennt.
- Inhalte eines Lernenden landen im Handbuch eines anderen.
- Kursmitschrift, Handbuch-Teile oder PDFs überleben die Löschung ihrer Mitschrift bzw. des Lernenden-Kontakts (DSGVO).
- Kundeninhalte (Titel, Namen, Text) in Logs.

## Randbedingungen

- **Auslöser:** Mitschrift mit `rubrik` = „Kurse“ (Groß/Klein egal), `auswertung_status = 'fertig'`, Bericht abgelegt. Wird eine Mitschrift **aus** „Kurse“ wegverschoben, werden Kursmitschrift-Dateien gelöscht und ihre Abschnitte aus dem Handbuch entfernt (siehe „Quelle entfernen“). Wird eine Mitschrift **nach** „Kurse“ verschoben, läuft sie wie neu.
- **Neu-Auswertung:** Ändert sich Auswertung, geprüfter Bildbestand oder Rubrik (wie `bericht_stand`), wird die Kursmitschrift neu erzeugt und die Handbuch-Kapitel dieser Quelle werden neu eingearbeitet.
- **Lernender:** je Mitschrift `kurs_lead_id` (Verweis auf `leads`, beim Löschen des Kontakts `null`). Nur Felix setzt ihn (UI, CSRF; nicht Rollen `lesen`/`kalender`). Private Kontakte sind erlaubt – das Handbuch ist interne Ablage, kein Versand.
- **Quelle entfernen (Verschieben aus „Kurse“, Löschen, Neu-Auswertung, Lernenden-Wechsel):** Die Zuordnung je Sitzung wird gespeichert. Betroffene Kapitel werden auf die letzte Fassung **vor** dieser Quelle zurückgesetzt, danach werden die späteren Quellen in Datumsfolge erneut eingearbeitet; Fassungen, die Inhalt der entfernten Quelle tragen, werden gelöscht (DSGVO). Nicht betroffene Kapitel bleiben wortgleich.
- **Reihenfolge:** Das Handbuch arbeitet Sitzungen in der Reihenfolge ihres Termin-Beginns ein. Eine Sitzung mit Status „Fehler“ wird übersprungen; kommt eine ältere Sitzung nachträglich dazu, wird sie an ihrer Datumsstelle eingefügt (Rücksetzen + erneutes Einarbeiten der späteren). `ersetzen` nur durch eine jüngere Sitzung.
- **Ablage:** Kursmitschrift-HTML und -PDF im Mitschriften-Ordner im Unterordner der Rubrik (Namensmuster wie Bericht mit Zusatz `_kurs-intern.html`, `_kurs.html`, `_kurs.pdf`); Handbuch unter `MITSCHRIFTEN_ORDNER/_handbuecher/handbuch-<lead8>.html|.pdf`. Datenbank führt Buch (Spalten/Tabellen in `provision.sql`, alle Laden-Schemata). Gesichert wird alles mit dem Mitschriften-Ordner.
- **PDF:** serverseitig per Headless-Chromium (`page.pdf`, A4, Bilder eingebettet) über einen neuen internen Endpunkt in `sales-auge` (Chromium steckt dort schon); kein neues Fremdwerkzeug. Bilder in HTML/PDF höchstens 800 px, JPEG q60; im Handbuch höchstens 3 Bilder je Kapitel (die jüngsten).
- **Fremde Daten im Text (Felix: „a“):** Kein Prüf- oder Maskierschritt für Texte; Felix liest vor dem eigenen Versand. Bilder bleiben gefiltert.
- **Taktgeber:** neuer Schritt nach `ablage`; je Runde höchstens **ein** KI-Auftrag (Kursmitschrift, Zuordnung oder ein Kapitel), nicht wenn ein Termin ansteht oder die KI nicht erreichbar ist. Fehler → bis zu 3 Versuche im Stundenabstand, danach Status „Fehler“ in der UI.
- **Löschen:** Wer eine Mitschrift löscht, löscht Kursmitschrift-Dateien mit und entfernt ihre Quelle aus dem Handbuch. Lead-Löschung/Löschantrag löscht das ganze Handbuch samt Dateien. Der stündliche Abgleich räumt Waisen auf (wie beim Bericht).
- **Sicherheit/Auslieferung:** wie beim Bericht – nur angemeldet, `Cache-Control: private, no-store`, eigene CSP ohne Skripte, Pfade nur aus der DB und nur unter dem Ordner.
- **Tests/Betrieb:** Testläufe nur in `~/meeting-test` (DB `meeting_test`, Schema `sales_test`); Ausrollen gezielt per `update.sh`, nur mit Felix' OK.

## Wege (Approaches)

**Kursmitschrift (A):** ein KI-Auftrag je Termin mit strukturierter JSON-Antwort, daraus HTML/PDF – gleiches Muster wie der Bericht. Ein Auftrag je Bild vervielfacht die KI-Last und verliert den Zusammenhang; reines Umformatieren ohne KI liefert keine Zusammenfassungen.

**Handbuch (B):**
- **B1 – Kapitel wachsen mit (gewählt, Felix „Okay“).** Zuordnung, dann nur betroffene Kapitel fortschreiben, Fassungen gespeichert. Stabil fürs Nachschlagen; mehr Bauaufwand.
- B2 – Handbuch nach jeder Sitzung komplett neu. Wechselnde Formulierungen, wachsender Aufwand. Verworfen.

**Zustellung:** (A, gewählt 19.11.) PDFs herunterladen, Felix verschickt selbst; (B) Privat-Vermerk entfernen und über Freigaben versenden – nicht jetzt.

## Von Felix entschieden

- Kursmitschrift für Termine unter „Kurse“, mit Bildern und Zusammenfassung je Bild.
- Empfänger: Diana und Felix; Zweck Wiederholen/Nachschlagen (Diana), Nachbereitung (Felix).
- A und B zusammen planen; Handbuch nach B1.
- Fremde Daten im Text: kein Maskieren (Variante A).
- Kein Versand durch sales-claw; Felix verschickt die PDFs diesmal selbst. Dianas Kontakt bleibt privat.

## Calls des Planers (zum Gegenlesen)

- Teil „Offen / nachfragen“ nur in Felix' Fassung.
- Lernender wird von Felix je Kurstermin gewählt (keine automatische Erkennung – die Termine hängen an einem Test-Kontakt); Vorschläge aus Teilnehmern und letzter Wahl.
- Handbuch je Lernendem (Kontakt), private Kontakte erlaubt.
- Kapiteltexte nicht von Hand bearbeitbar (nur Titel/Reihenfolge).
- Quelle entfernen = Kapitel auf Fassung vor der Quelle zurücksetzen, spätere Sitzungen neu einarbeiten, Fassungen mit Inhalt der Quelle löschen.
- Fehlgeschlagene Sitzungen überspringen; ältere, nachträgliche Sitzungen an ihrer Datumsstelle einfügen.
- PDFs liegen im Mitschriften-Ordner (kein Medienordner, da kein Anhang an Entwürfe).

## Dem Builder überlassen

- Genaue Prompts, Spalten-/Tabellennamen, Warteschlange für die PDF-Erzeugung in sales-auge.
- Erkennung „Kursmitschrift veraltet“ (analog `bericht_stand`).
- Gestaltung von HTML/PDF im Stil des bestehenden Berichts.
