# sales-claw Stufe 5 — Analysen & Recherche (Apify)

> Auftrag des Betreibers (2026-08-18): Marktanalysen und B2B-Lead-Recherche für
> den WWK-Strukturvertrieb, Apify-Free-Plan ($5/Monat Guthaben, Token liegt
> verifiziert in `.env` als `APIFY_TOKEN`, Konto Free-Plan). Passt auf zwei
> Aufgaben der Stellenanzeige: „Markt- und Wettbewerbsanalysen" und mittelbar
> die B2B-Schiene (bAV als Aufhänger).

## Bindende Grundsätze

- **Kein Personen-Scraping.** Nur Firmendaten aus öffentlichen Quellen
  (Google-Suche, Google Maps). Kein LinkedIn, keine Privatpersonen.
- **Recherche-Leads werden nie automatisch angeschrieben.** Sie entstehen mit
  `consent_status='unknown'`, `source='recherche'`; die bestehende
  Freigabe-Anzeige zeigt den Consent-Status ohnehin. Zusätzlich AGENTS-Regel:
  für Recherche-Leads keine WhatsApp-Entwürfe vorschlagen — Erstkontakt macht
  der Mensch auf legalem Weg (UWG). LinkedIn-/Brief-Entwürfe als Text sind
  zulässig (Handversand).
- Budget-Respekt: Free-Plan. Jeder Werkzeugaufruf mit hartem `limit`
  (Vorgabe 20, Maximum 50) und einem Guthaben-Check-Fehlerpfad (Apify-4xx bei
  erschöpftem Guthaben → sprechender Fehlertext).
- Alle bisherigen Grundsätze unverändert (kein DDL, `.env` nie lesen,
  `docker compose config` verboten, `--remove-orphans` tabu, Tests nur gegen
  `sales_test`, Secrets nie ausgeben).

## Bausteine

### R1 — Apify-Anbindung + `marktanalyse(thema, region='Regensburg')`

- **Messen zuerst:** Apify-REST (`POST /v2/acts/<actorId>/run-sync-get-dataset-items?token=…`)
  gegen einen passenden Store-Actor für Google-Maps-Suche (z. B.
  `compass/crawler-google-places` — Verfügbarkeit und Input-Schema am Store
  messen, nicht raten; Alternativ-Actor dokumentieren). Kostenpunkt je Lauf im
  Bericht festhalten (Actor-Preismodell!).
- Neues Modul `sales-mcp/recherche.py` (eigene Datei — `server.py` ist groß
  genug): Apify-Client (urllib, Timeout 120 s, Token aus env `APIFY_TOKEN`,
  fehlt er → Fehlertext „kein APIFY_TOKEN konfiguriert"), Actor-Aufruf,
  Ergebnis-Normalisierung (Name, Adresse, Telefon, Website, Kategorie,
  Bewertung).
- Werkzeug `marktanalyse(thema, region)`: Maps-Daten zu Wettbewerbern
  (z. B. „Versicherungsmakler", „Finanzberatung") in der Region einsammeln
  (limit), zu einem **Markdown-Report** verdichten (Anzahl, Cluster nach
  Kategorie, Top-Bewertete, Auffälligkeiten, Quellenzeile mit Datum) und nach
  `/reports/<slug>-<datum>.md` schreiben. Rückgabe: Pfad + Kurzfassung
  (5 Zeilen) für den Chat. `activities`-Log an einen festen „Recherche"-Lead
  (analog Sammel-Lead-Muster aus F1, `RECHERCHE_LEAD_ID` in `.env`).
- **Compose:** neues beschreibbares Bind `./reports:/reports` NUR an
  `sales-mcp` (dispatch/inbox brauchen es nicht). `media/` bleibt `:ro`.

### R2 — `b2b_leads(branche, region='Regensburg', limit=20)`

- Gleicher Maps-Actor, andere Auswertung: je Treffer mit Telefonnummer einen
  Lead anlegen — **über die bestehende `kontakt_anlegen`-Logik** (damit greift
  die Dedup-Kante!), `source='recherche'`, `notes` mit Adresse/Website/
  Kategorie, `consent` bleibt `unknown`. Firmenname als `name`,
  `company`-Spalte ebenfalls füllen. Treffer ohne Telefonnummer: nur im
  Rückgabe-Report, kein Lead (ohne Kanal kein Nutzen).
- Rückgabe: angelegt/übersprungen(Dublette)/ohne-Nummer als Zahlen plus die
  ersten fünf Namen. `activities`-Log (`typ='recherche'`) am Sammel-Lead mit
  Suchparametern und Zählern — Nachvollziehbarkeit, welche Suche welche Leads
  erzeugte.
- **AGENTS.md:** Abschnitt „Recherche": beide Werkzeuge erklären; die
  UWG-Regel (Recherche-Leads nie per WhatsApp anschreiben, keine
  Kalt-Entwürfe vorschlagen; bAV-B2B-Kontext); Reports liegen unter
  /reports und können auf Zuruf zusammengefasst werden.

### R3 — Tests + Live-Abnahme

- **Stub-Tests** (Apify-HTTP-Stub wie beim OpenWA-Stub): Actor-Antwort →
  Report-Datei entsteht mit erwarteten Abschnitten; b2b_leads legt Leads mit
  consent=unknown an, Dubletten (gleiche Nummer) übersprungen, ohne Nummer
  kein Lead; fehlender Token → Fehlertext ohne HTTP; Apify-4xx →
  Guthaben-Fehlertext; limit-Kappung bei >50. Pfad-Härtung für den
  Report-Slug (basename, kein Traversal).
- **Live-Abnahme (eine echte Apify-Ausführung, Free-Guthaben):**
  `marktanalyse('Versicherungsmakler', 'Regensburg')` mit limit 10 —
  Report entsteht mit echten Daten, Kosten im Bericht dokumentieren.
  `b2b_leads` live NUR mit limit 5 und **in `sales`** (das ist der Sinn —
  echte Leads für den Betreiber), Zähler + Namen im Bericht. Beides einmal.

## Reihenfolge

Nach F4 (gleiche Dateien). R1 → R2 → R3 in einem Task (ein Umsetzer, opus —
externe API + Schreiben in `sales`), ein Review danach. Anschließend
Gesamtabschluss Stufe 4+5: Doku, Push, Statusbericht.
