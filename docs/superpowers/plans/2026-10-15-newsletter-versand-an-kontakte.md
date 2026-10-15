# Newsletter-Versand an die sales-claw-Kontakte (mit Vorname) — Plan zur Abstimmung

Stand 15.10.2026. Noch nichts gebaut. Beim Bauen und Testen wird nichts verschickt (nur `sales_test`).

## Ausgangslage (gemessen)

- Ein freigegebener Block-Newsletter endet heute in **JPEG-Screenshots** (`workers/export_worker.py`). Er erreicht
  niemanden. Das gerenderte HTML wird nirgends gespeichert.
- Der einzige Versandweg ist sales-claw: **ein Entwurf je Empfänger**, Freigabe durch einen Menschen
  (`/aktion/freigeben` → `aktion_freigeben`, ui.py:2732), danach `mail_dispatch`. Dieser verschickt **nur Text**;
  `drafts` hat kein HTML-Feld.
- `leads` hat nur `name` (kein Vorname). Die Termin-Mails nehmen das erste Wort (server.py:7286).
- `{abmeldelink}` wird nie echt ersetzt, überall steht `[Abmeldelink]`.
- sales-ui, Marketing-API und Bild-Links sind **nur im Tailnet** erreichbar; Bild-Tokens laufen nach 15 min ab.
  Externe Empfänger könnten weder Bilder laden noch einen Abmelde-Link öffnen.
- `mail_dispatch` prüft beim Senden **weder Sperrliste noch Einwilligung** erneut — nur beim Entwurf.

## Ablauf (Ziel)

1. Newsletter wird wie heute im Editor gestaltet und freigegeben.
2. Auf der Freigabe-Seite neu: **„An Kontakte senden …“** → Liste der Kontakte, die dürfen (siehe Regeln),
   alle vorausgewählt, abwählbar, Anzahl sichtbar.
3. „Entwürfe anlegen“ → **je Kontakt ein Entwurf** (Kanal email) mit HTML, Textfassung, eingesetztem Vornamen
   und Abmelde-Hinweis. Nichts geht raus.
4. Freigabe wie bisher durch einen Menschen (einzeln oder — Entscheidung E3 — gesammelt je Newsletter).
5. `mail_dispatch` sendet HTML + Text, Bilder eingebettet, prüft vorher Sperrliste und Einwilligung erneut.

## Regeln für Empfänger (Vorschlag)

- `consent_status` ∈ `opt_in`, `existing_customer`, `betreiber_auftrag` (`EINWILLIGUNG_ARTEN`, server.py:6755).
  **Nicht** `inbound` und nicht „hat selbst geschrieben“ — ein Newsletter ist Werbung, keine Antwort (§7 UWG).
- E-Mail vorhanden, nicht auf `compliance.sperrliste`, kein Löschantrag, nicht privat/archiviert.
- Höchstens ein offener Newsletter-Entwurf je Kontakt und Newsletter (doppelt anlegen geht nicht).
- Obergrenze je Lauf (Vorschlag 50), damit ein Fehler klein bleibt.

## Vorname und Anrede

- Neues Feld `leads.vorname` (nullable, im Kontakt pflegbar). Ist es leer, wird vorgeschlagen:
  erstes Wort von `name`, ohne Titel/Anrede (Dr., Prof., Herr, Frau), nicht wenn `name` = Firma.
- Im Newsletter steht der Platzhalter **`{vorname}`** (Editor-Abschnitt „Brief“: `Hallo {vorname},`).
  Vorschau und Export zeigen `[Vorname]`. Marketing sieht nie einen Namen — ersetzt wird erst in sales-claw.
- Ohne Vornamen: `Hallo {vorname},` → `Hallo,` (Platzhalter samt Leerzeichen davor fällt weg).

## Bilder und Abmelden ohne öffentlichen Host

- **Bilder eingebettet** (CID, `multipart/related`): `mail_dispatch` hängt die Medien an und ersetzt die
  `src`-Adressen. Kein öffentlicher Host nötig, keine ablaufenden Links. (Anhänge bis 8 MB gibt es schon.)
- **Abmelden per Antwort** (Vorschlag): Abmelde-Zeile „Keine Newsletter mehr? Antworte mit ‚Abmelden‘“ +
  `mailto:`-Link, dazu Kopfzeile `List-Unsubscribe: <mailto:…?subject=Abmelden>`. Das Postfach liest sales-claw
  schon (Postfach-Check); eine Antwort „Abmelden“ setzt den Kontakt auf die Sperrliste und `consent_status`
  zurück. Alternative siehe E2.

## Umsetzung (Reihenfolge, je Schritt TDD)

1. **DB (sales*, alle Schemas, provision.sql):** `leads.vorname`, `drafts.body_html`, `drafts.newsletter`
   (Inhalt-ID), Eindeutigkeit (lead, newsletter) für offene Entwürfe.
2. **Vorname:** Ermittlung + Pflege im Kontakt (UI), Tests für Titel/Firma/leer.
3. **Marketing:** Platzhalter `{vorname}` und `{abmeldelink}` bleiben im gerenderten HTML für den Versand
   erhalten (neuer Modus `fuer_versand=True` in `rendern`), Vorschau zeigt weiter `[Vorname]`/`[Abmeldelink]`;
   Textfassung aus den Blöcken. Route für sales-ui (X-Pult-Key, wie die Vorschau).
4. **sales-ui:** Empfängerliste + „Entwürfe anlegen“ auf der Freigabe-Seite; legt Entwürfe über dieselben Tore
   an wie `entwurf_erstellen` (Sperre, Löschantrag, UWG — mit der strengeren Newsletter-Regel).
5. **mail_dispatch:** HTML-Teil, eingebettete Bilder, `List-Unsubscribe`, **Sperrliste + Einwilligung beim
   Senden erneut prüfen** (fehlt heute generell — gilt dann für alle Mails).
6. **Abmelden:** Postfach-Erkennung „Abmelden“ → Sperrliste + Einwilligung zurück, Tätigkeit protokolliert.
7. Abnahme: Suite gegen `sales_test`, Probelauf an **eine** Betreiber-Adresse nach ausdrücklichem OK.

Grobe Größe: 2–3 Arbeitstage. Berührt sales-claw (DB, UI, mail_dispatch, server.py-Tore) und Marketing (Renderer).
Braucht eine Migration in allen `sales*`-Schemas (eigene Freigabe wie bei 068).

## Entscheidungen (Betreiber, 15.10.2026)

- **E1 Empfänger:** nur `consent_status = 'opt_in'` (ausdrückliche Einwilligung). Nicht `existing_customer`,
  nicht `betreiber_auftrag`, nicht `inbound`.
- **E2 Abmelden:** per Antwort „Abmelden“ (`mailto`-Link + `List-Unsubscribe: <mailto:…>`), Postfach-Erkennung.
- **E3 Freigabe:** „Immer mit Freigabe“ — jeder Entwurf wird von einem Menschen freigegeben; die Liste erlaubt
  Mehrfachauswahl (anhaken → „Ausgewählte freigeben“). Nie automatisch.
- **E4 Laden ↔ Firma:** fest je Laden (`MARKETING_MANDANT` in der Laden-Konfiguration).
- **E5 Obergrenze:** 50 Empfänger je Durchgang.
