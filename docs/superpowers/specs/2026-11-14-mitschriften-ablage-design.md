# Mitschriften-Ablage: KI-sortierte HTML-Berichte – Design

Stand 14.11.2026. Entscheider: Felix. Baut auf der Bildauswertung (Spec `2026-11-13-bildauswertung-live-design.md`, PR #28/#33) auf.

## Absicht und Warum

Nach jedem Termin mit Mitschrift soll es **einen lesbaren Bericht als HTML-Datei** geben (Auswertung, Bilder je Thema, bereinigtes Transkript) – so wie die zwei Einmal-Berichte vom 14.11. Diese Dateien sollen **ordentlich einsortiert** sein: eine KI liest die Mitschrift und entscheidet die Rubrik, z. B. „Kurse“ (die Termine mit Diana sind Kurs-Sitzungen, keine Verkaufsgespräche). In sales-ui gibt es dafür einen **neuen Hauptpunkt „Mitschriften“**; jede Rubrik ist dort ein Reiter.

Felix' Worte: „dynamisch bestimmen an der Mitschrift und dann einsortieren“, „ein Agent entscheidet das“, „Output-Format HTML, diese HTML-Files müssen ordentlich eingeordnet werden“. Ablage-Weg: **C – echte Dateien in Ordnern, ein Ordner je Rubrik** (Felix' Wahl).

## Ziele

1. **Bericht-Datei je Mitschrift:** Sobald eine Auswertung `fertig` ist, entsteht eine eigenständige HTML-Datei (Bilder eingebettet, ohne externe Abhängigkeiten, druckbar als PDF). Inhalt wie der Einmal-Bericht (`bericht.py`, Vorlage im Anhang): Kopf (Titel, Datum, Plattform, Anzahl Segmente/Bilder/übersprungene heikle Bildschirme), Auswertung (auswertung_md), Bilder je Thema (höchstens 6 je Verlaufseintrag, verkleinert auf max. 1000 px, JPEG q70, nur Bilder mit `beschreibung_status = 'fertig'`), Transkript (Uhrzeit Berlin, Sprecher, Text). Kennzeichnung oben: „Intern – enthält Kundendaten, nicht weitergeben“.
2. **KI-Einordnung:** Ein eigener kleiner Schritt nach der Auswertung (gleiche KI wie die Auswertung: sales-ki über `ollama.chat`, kein neues Modell) wählt die Rubrik. Eingabe: Titel, Kurzfassung, Beteiligte, „art“ aus der Auswertung, Liste der vorhandenen Rubriken mit Anzahl. Ausgabe JSON `{"rubrik": "...", "neu": true|false}`. Regeln im Prompt: vorhandene Rubrik bevorzugen; neue nur, wenn keine passt; Name 1–3 Wörter, Mehrzahl, deutsch (z. B. „Kurse“, „Kundentermine“, „Interne Besprechungen“).
3. **Ablage als Ordner:** je Laden ein Ordner `MITSCHRIFTEN_ORDNER` (Muster wie `MEDIEN_ORDNER`, z. B. `./laeden-daten/<laden>/mitschriften`), darin ein Unterordner je Rubrik, darin die Dateien `JJJJ-MM-TT_HHMM_<titel-kurz>_<uid8>.html`.
4. **Hauptpunkt „Mitschriften“ in sales-ui:** Reiter = Rubriken (mit Anzahl), Liste je Reiter neueste zuerst: Datum, Titel, Beteiligte, Kurzfassung (gekürzt). Je Eintrag: „Bericht öffnen“ (im Browser), „HTML herunterladen“, „Akte“ (bestehende Termin-Akte), „Verschieben nach …“ (andere Rubrik oder neue).
5. **Bestand einordnen:** einmalig alle vorhandenen Mitschriften mit fertiger Auswertung berichten und einordnen. Die zwei Diana-Termine (`3c9afada…`, `54ac1821…`) müssen unter „Kurse“ landen (falls die KI anders entscheidet: von Hand verschieben, siehe Ziel 4).

## Nicht-Ziele (dieses Vorhabens)

- **Kundenfassung und Versand an den Kunden** (Felix: „dann auch an den Kunden … freigeben über Sales Claw“): eigener Folgeschritt mit eigener Spec – Fassung ohne interne Teile (Einwände, Painpoints, CRM-Vorschläge, Heikel-Zähler), als Anhang am bestehenden Zusammenfassungs-Entwurf (Freigaben → Nachrichten → E-Mail). Dieses Vorhaben legt nur die interne Datei an.
- Sprechererkennung (Vexa-Diarisierung), Rückwirkendes Nachbearbeiten der Transkripte.
- PDF-Erzeugung auf dem Server (PDF = Drucken im Browser).

## Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)

- Eine Bericht-Datei überlebt die Löschung ihrer Mitschrift (DSGVO).
- Berichte sind ohne Anmeldung erreichbar oder werden gecacht.
- Ein Bericht enthält ein ungeprüftes oder heikles Bild.
- Rubriken wuchern (jede Mitschrift eine eigene Rubrik) oder die KI überschreibt eine Einordnung, die Felix von Hand gesetzt hat.
- Kundeninhalte (Titel, Namen, Text) in Logs.

## Randbedingungen

- **Dateien sind die Ablage, die Datenbank führt Buch:** `termin_mitschriften` bekommt `rubrik text`, `rubrik_manuell bool not null default false`, `bericht_pfad text` (relativ zu `MITSCHRIFTEN_ORDNER`), `bericht_am timestamptz`. Die Oberfläche listet aus der Datenbank und liefert den Inhalt aus der Datei. Schreiben immer: Datei schreiben (temporär + umbenennen), dann Datenbank; alte Datei bei Verschieben/Neu-Erzeugen entfernen.
- **Löschen:** Jeder Weg, der eine Mitschrift löscht (`termin_akte` ~Z. 454 „Mitschrift verwerfen“, `server._mitschriften_abraeumen` bei Lead-Löschung, ggf. weitere – Builder sucht alle `delete from termin_mitschriften`), löscht die Datei mit. Zusätzlich ein Abgleich (im Taktgeber, höchstens stündlich): Dateien ohne Mitschrift werden gelöscht, Mitschriften mit fehlender Datei neu erzeugt. Log nur Anzahlen.
- **Neu erzeugen** bei: Auswertung neu fertig (auch nach `neu_auswerten`), Verschieben, und wenn nach Berichtserstellung Bilder gelöscht wurden (Schicht B / 24-h-Aufräumen) – einfache Regel: Bericht wird neu erzeugt, wenn `bericht_am` älter ist als die jüngste Änderung an Auswertung oder Bildbestand der Akte (Builder wählt die Erkennung).
- **Sicherung:** `deploy/sicherung.sh` sichert `MITSCHRIFTEN_ORDNER` je Laden wie `MEDIEN_ORDNER`; `wiederherstellen.sh` entsprechend.
- **Dienste:** Erzeugen und Einordnen im Taktgeber (`sales-termine`, Ordner rw). sales-ui braucht den Ordner für Ausliefern, Verschieben und Löschen (rw). Ordner-Rechte passend zu den Nicht-root-Benutzern der Container.
- **Rubrik-Namen** werden vor der Ablage normalisiert (Leerraum, Groß/Klein-Vergleich gegen vorhandene; nur Buchstaben inkl. Umlaute, Ziffern, Leerzeichen, Bindestrich; max. 40 Zeichen) und als Ordnername genutzt. Höchstens 12 Rubriken je Laden: ist die Grenze erreicht, muss die KI eine vorhandene wählen.
- **Ausliefern:** nur angemeldet, `Cache-Control: private, no-store`; Download mit `Content-Disposition: attachment` und dem Dateinamen.
- **Fehler:** KI-Einordnung scheitert → Rubrik „Unsortiert“, später erneut versuchen (Backoff wie bei der Auswertung). Bericht-Erzeugung scheitert → kein halber Bericht; erneut im nächsten Durchlauf.
- **Mehrere Läden:** jeder Laden eigener Ordner und eigene Rubriken (Schema je Laden).
- Logs nur gekürzte uid, Anzahlen, Fehlerart.

## Ansätze (betrachtet)

- **A – Einordnung in der bestehenden Auswertung, Bericht in der Datenbank:** kein Zusatzaufruf; Umsortieren nur über Neu-Auswertung. Nicht gewählt.
- **B – eigener Einordnungs-Schritt, Bericht in der Datenbank:** billig umsortierbar, keine Dateien neben der DB. Von Claude empfohlen, nicht gewählt.
- **C – echte HTML-Dateien in Ordnern je Rubrik (gewählt von Felix):** entspricht wörtlich „Dateien ordentlich einsortiert“; dafür muss Sicherung und Löschung der Dateien eigens gebaut werden (oben). Die Einordnung selbst läuft wie in B als eigener kleiner KI-Schritt (Claudes Wahl – erlaubt Umsortieren ohne Neu-Auswertung und das Einordnen des Bestands).

## Festlegungen nach Builder-Prüfung (Claudes Calls)

- **`MITSCHRIFTEN_ORDNER` ist Pflicht, ohne gemeinsame Vorgabe:** Der Basis-Laden bekommt `./laeden-daten/sales/mitschriften` als Vorgabe nur für sich (wie die bestehende Sonderregel für den Basis-Laden); jeder weitere Laden muss ihn setzen – `deploy/laden-anlegen.sh` schreibt ihn, `deploy/update.sh` weist einen Laden ohne ihn ab (wie bei `MEDIEN_ORDNER`), `deploy/laeden/beispiel.env` nennt ihn.
- **Der stündliche Abgleich ist vorsichtig:** Er löscht nur Dateien, die auf `*_<uid8>.html` in einem Rubrik-Unterordner passen und deren uid in diesem Laden keine Mitschrift mehr hat; er läuft nicht, wenn der Ordner fehlt, nicht beschreibbar ist oder keine einzige erwartete Datei enthält (Zeichen für einen falsch eingehängten Ordner) – dann nur Warnung im Log. Fremde Dateien bleiben unberührt. Er fängt auch Löschungen per Datenbank-Kaskade (Akte gelöscht) ab.
- **Rubrik-Grenze 12 bindet nur die KI:** Felix darf beim Verschieben jederzeit eine neue Rubrik anlegen. „Unsortiert“ zählt nicht mit. Gezählt wird aus der Datenbank (Rubriken mit mindestens einer Mitschrift); eine geleerte Rubrik zählt nicht mehr, ihr leerer Ordner wird beim Abgleich entfernt.
- **Bestand einordnen** läuft nacheinander mit derselben Regel; erreicht er die Grenze, wählt die KI vorhandene Rubriken.

## Vom Builder zu entscheiden

Modul-Schnitt (z. B. `bericht.py`, `einordnung.py`), wie die HTML-Vorlage im Code liegt, wie „Bildbestand geändert“ erkannt wird, Sortierung/Seitenaufteilung der Liste, genaue Menü-Position des Hauptpunkts (eigene Gruppe „Mitschriften“ oder Eintrag in einer bestehenden Gruppe – sichtbar als Hauptpunkt), Tests.

## Anhang: Vorlage Einmal-Bericht

Das Skript, mit dem am 14.11. die zwei internen Berichte erzeugt wurden, liegt bei: `docs/superpowers/specs/2026-11-14-mitschriften-ablage-bericht-vorlage.py` (nur lesend, im Container `sales-termine` lauffähig).
