# Marketing-Pult in der Sales-Oberfläche

**Stand 29.09.2026. Abschnitt für Abschnitt mit dem Betreiber besprochen und
freigegeben. Diese Datei ist die schriftliche Fassung zur Durchsicht.**

## 1. Ziel und Ausgangslage

Der Betreiber öffnet Marketing vor allem, um **freizugeben und nachzubessern,
was der Agent vorschlägt**. Marketing baut die Inhalte, Sales verteilt sie.

Gemessen am 29.09.2026 (Browser, Marketing-Seite auf `:8446`):

- Die Seite ist ein englischer Brevo-Nachbau mit elf Reitern. Nur Audiences,
  Proposals, Entwürfe und Audit lesen echte Daten (die Fußzeile sagt es selbst).
  Dashboard und Templates sind fest eingebaute Beispiele.
- Die **echten Layouts** (`marketing.layout_vorlagen`, Art `layout`: `dunkel`
  freigegeben, `hell` und `warm-sand` Vorschlag) zeigt die Seite nicht.
- Die 7 **Entwürfe** (`broadcast_proposals`) stehen als Textblöcke untereinander,
  ohne Vorschau, nicht bearbeitbar, nicht sortiert.
- Alle Entwürfe und Schaufenster-Ergebnisse handeln von **VibeMind**
  (Early Access für Solo-Gründer).
- Der Agent hat bereits die Werkzeuge (`claw/werkzeuge.py`): `kampagne_entwerfen`,
  `kampagne_pruefen`, `ad_texte_entwerfen`, `layout_entwerfen`, `pdf_erstellen`,
  `pdf_aus_entwurf`, `post_ablegen`, `wissen_fragen`, `versand_beauftragen`, dazu
  Schönheitsprüfung (`schoenheit.py`) und Schaufenster. **Es fehlt die Oberfläche,
  nicht die Maschine.**

## 2. Entscheidungen des Betreibers

| Frage | Entscheid |
|---|---|
| Wofür das Pult | Freigeben und nachbessern, was der Agent vorschlägt |
| Inhaltsarten | alle drei: Newsletter, kurze Posts/Nachrichten, Team-Material (PDF) |
| Ort | eigener Bereich „Marketing" in der Sales-Oberfläche (eine Anmeldung, ein Aussehen) |
| Mandanten | zuerst **VibeMind**; danach **fin2gether** (Vertriebsgesellschaft, erster Kunde von VibeMind; eigene Spec) |
| Layout anpassen | Regler **und** Gespräch mit dem Agenten; Regler zuerst gebaut |
| Verteilung VibeMind | nur über den Laden des Betreibers (er baut VibeMind); nie über Ivans Laden, nie unter fin2gether |
| Rendern | Sales-Oberfläche zeigt, **die Marketing-API rendert** (eine Quelle für Vorschau und Ergebnis) |
| Kampagnen | bleiben, mit Zeitleiste und dem, was rausging |
| Kanäle | wandern in die Sales-Oberfläche, nur was wirklich senden kann |
| Rückmeldung | an Entwurf und Kampagne, als Verlauf an den Agenten |

## 3. Aufbau

### 3.1 Menüpunkt „Marketing" (sales-ui)

Nur für Rolle `freigeben` im Basis-Laden (dieselbe Sperre wie `_ADMIN_BASIS_PFADE`).
Ersetzt den Schalter Sales ↔ Marketing vom 25.09. Fünf Seiten:

1. **Übersicht „Was steht an"** — Mandanten-Wahl (VibeMind aktiv, fin2gether
   ausgegraut „kommt"); Karten *Zur Freigabe · In Arbeit · Bereit zum Versand ·
   Verschickt*; Knopf **„Neuen Inhalt anstoßen"** (Art, Thema, Hinweis,
   optional Kampagne).
2. **Entwürfe** — Liste nach Art und Status, Filter, Vorschaubild je Zeile.
   Entwurfsansicht: links Felder (Betreff, Vorschautext, Abschnitte, Knopf-Text
   und -Link), rechts Live-Vorschau *Mail · Handy · PDF*; Aktionen *Speichern*
   (neue Fassung), *Layout wechseln*, *Agent überarbeiten lassen*, *Ablehnen*,
   *Freigeben* (Verteiler wählen oder „nur ablegen").
3. **Kampagnen** — Ziel, Zeitraum, Mandant, zugehörige Inhalte; Zeitleiste
   *geplant → freigegeben → verschickt*; je verschicktem Inhalt das Ergebnis aus
   Sales (Anzahl, zugestellt/fehlgeschlagen, Antworten; Öffnungen nur, wo der Kanal
   sie liefert). Die 3 bestehenden Kampagnen werden VibeMind zugeordnet.
4. **Layouts** — Galerie mit echter Vorschau, gruppiert nach Art (Newsletter-Gerüst,
   Post-Kachel, PDF-Gewand); Layout-Editor mit Reglern und Live-Vorschau;
   *Als neue Fassung speichern*, *Als Standard für diese Art*.
5. **Verlauf** — was wann freigegeben und über welchen Laden verteilt wurde.

Am Handy dieselben Seiten; im Entwurf und Layout-Editor Umschaltung
*Bearbeiten | Vorschau* statt zwei Spalten.

### 3.2 Rückmeldung an den Agenten

- Am Entwurf und an der Kampagne ein **Rückmelde-Verlauf**; Rückmeldung auch zu
  einem markierten Abschnitt.
- *An den Agenten schicken* legt einen Überarbeitungs-Auftrag an; der Entwurf
  zeigt „wird überarbeitet …".
- Neue Fassung erscheint **neben der alten**, Änderungen markiert, beide mit
  Vorschau; übernehmen, behalten oder weiter rückmelden. Alle Fassungen bleiben.
- Rückmeldung auf ein Versandergebnis wird **Stil-Notiz des Mandanten**; der Agent
  liest die Notizen bei jedem Entwurf mit. Notizen sind im Pult sicht- und
  bearbeitbar.
- **Überarbeitungs-Arbeiter** auf dem PC, Muster Vorlagen-Arbeiter
  (`workers/vorlagen_worker.py`): holt Aufträge aus der DB, **ein** Modellaufruf
  über `claude -p` mit derselben Abschottung wie `claw/formular_entwurf.py`
  (Werkzeug-Allowlist, Zufallsmarker). Eingaben: Fassung, Rückmeldung,
  Stil-Notizen, Wissen des Mandanten. Ergebnis durch die Schönheitsprüfung, dann
  neue Fassung.
- Text des Betreibers ist **Auftrag**; Text aus Wissen oder Antworten ist nur
  **Material**, nie Anweisung.
- PC aus: Auftrag wartet; das Pult zeigt „wartet auf den Marketing-Rechner".

### 3.3 Daten (Schema `marketing`, nur Ergänzungen)

- `mandanten` — `vibemind`, `fin2gether`; erlaubte Verteiler je Mandant
  (VibeMind: nur Laden `sales`); Pflichtteil (Impressum, Abmeldelink; §34d/f-Angaben
  bei fin2gether).
- `inhalte` (Art `newsletter|post|material`, Mandant, Kampagne, Status) und
  `inhalt_fassungen` (Felder als JSON, Layout + Layout-Fassung, Urheber
  `agent|betreiber`, Zeitpunkt). Die 7 Entwürfe aus `broadcast_proposals` werden als
  Fassung 1 übernommen; `broadcast_proposals` bleibt unverändert.
- `rueckmeldungen` — Verlauf je Inhalt oder Kampagne; Überarbeitungs-Auftrag mit
  Status (`offen → in_arbeit → erledigt | gescheitert`).
- `stil_notizen` — je Mandant.
- `campaigns` — neue Spalten Mandant, Ziel, Zeitraum.
- `layout_vorlagen` — neue Spalten Mandant, Inhaltsart, Fassung. `dunkel`, `hell`,
  `warm-sand` werden VibeMind-Layouts. Terminkarten-Formulare (Art `formular`)
  bleiben unberührt.
- Die Grenze „VibeMind nur über Laden `sales`" und die Mandanten-Trennung
  (Layout und Wissen nie über Mandanten hinweg) prüft die **Datenbank**, nicht
  nur die Oberfläche.

### 3.4 Zugriff und Rendern

- sales-ui greift **nicht** direkt auf `marketing.*` zu. Sie ruft die Marketing-API
  auf der VM (`127.0.0.1:5510`, Dienst `marketing-api`) über neue Endpunkte für
  Lesen, Fassung speichern, Rendern (HTML, Handy, PDF), Layout speichern,
  Freigeben, Rückmeldung.
- Diese Endpunkte verlangen einen **eigenen Schlüssel** (`MARKETING_PULT_KEY`),
  der nur in der sales-ui-Umgebung des Basis-Ladens und in der Schlüsseldatei der
  VM-Instanz liegt, nie in argv oder im Repo.
- Wie sales-ui den Dienst auf dem VM-Host erreicht (host-gateway oder Tailnet-
  Adresse), wird im Plan von Stufe 1 gemessen und festgelegt.
- Layout = Gestalt als JSON; Regler ändern Farben (Grund, Text, Akzent), Schrift
  (feste, mail-taugliche Auswahl), Logo (Datei aus den Medien), Kopf-/Fußtexte,
  Abstände, Eckenrundung. Vorschau rendert bei jeder Änderung neu mit einem
  Beispielinhalt je Art. Der Pflichtteil kommt aus dem Mandanten, nicht aus den
  Reglern.

### 3.5 Verteilen und Einwilligung

- **Newsletter:** Freigabe im Pult legt über `marketing.versandauftraege` einen
  Auftrag an den Laden an, mit fertigem HTML und Text. **Empfänger wählt Sales**;
  Marketing sieht keine Kontaktdaten. In Sales erscheint unter *Freigaben* eine
  **Sammelfreigabe** („Newsletter ‚…' an 23 Kontakte", Liste, Vorschau, ein Klick).
  Pult-Freigabe = Inhalt; Sales-Freigabe = Versand an diese Menschen.
- **Posts:** Sales kann nicht auf Instagram/LinkedIn posten. Freigegebene Posts
  landen als Bild + Text in den **Medien** des Ladens, mit Kopieren/Teilen.
- **Team-Material:** PDF in den **Medien** des Ladens.
- **Einwilligung:** Newsletter nur an Kontakte mit dokumentierter
  Werbe-Einwilligung; die Sammelfreigabe nennt ausgelassene Kontakte
  („12 ohne Einwilligung"). Jeder Newsletter trägt den Abmeldelink; eine Abmeldung
  landet auf der gemeinsamen Sperrliste (`compliance.sperrliste`).

### 3.6 Kanäle in Sales

Neuer Punkt **Kanäle** unter *Monitoring* in sales-ui. Zeigt nur Kanäle, über die
Sales wirklich senden kann, je Laden mit Status *sendebereit / nicht eingerichtet
/ gestört*. Die genaue Prüfung jedes Kanals ist ein eigener späterer Baustein.

### 3.7 Was wegfällt

Das Brevo-Mockup (`spaces/marketing/mockup/`) mit Campaigns, Audiences, Proposals,
Channels, Inbox, Analytics, Settings und dem Phase-1-Balken; der Schalter vom 25.09.;
das offene Tailnet-Tor `:8446` (sobald das Pult läuft).

## 4. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Marketing-API auf der VM nicht erreichbar | Pult: „Marketing gerade nicht erreichbar"; Sales läuft normal |
| PC aus | Überarbeitung wartet, Anzeige „wartet auf den Marketing-Rechner" |
| Modell liefert Unbrauchbares / Schönheitsprüfung rot | keine neue Fassung; Grund im Verlauf; neu anstoßbar |
| Gleichzeitiges Speichern | jede Speicherung eigene Fassung, nichts überschrieben |
| Freigabe an nicht erlaubten Laden | DB lehnt ab, Pult zeigt den Grund |
| Kontakt ohne Einwilligung | ausgelassen und gezählt, nie verschickt |
| Schlüssel fehlt oder falsch | API antwortet 401, Pult zeigt „Marketing nicht verbunden" |

## 5. Tests

- DB-Proben für jede Sperre (`verify_0NN.sql`, PROBE-Sätze, BEGIN … ROLLBACK).
- API-Tests: Rendern, Fassungen, Schlüsselpflicht, Mandanten-Trennung.
- UI-Tests: Menüpunkt nur für `freigeben` im Basis-Laden; Vorschau vorhanden;
  Handy-Umschaltung.
- Arbeiter-Test mit gestelltem Modell; ein echter Modelllauf als Beleg.
- End-to-End: Newsletter anstoßen → Rückmeldung → neue Fassung → Freigabe →
  Sammelfreigabe in Sales an einen Test-Kontakt.

## 6. Stufen (je eigener Plan, jede läuft für sich)

1. **Pult-Grundgerüst** — Datenmodell, API-Endpunkte mit Schlüssel, Menüpunkt;
   *Entwürfe* mit Vorschau, Bearbeiten, Fassungen, Freigabe „nur ablegen";
   *Layouts* als Galerie mit Reglern.
2. **Rückmeldung** — Verlauf, Überarbeitungs-Arbeiter, Stil-Notizen.
3. **Kampagnen und Versand** — Kampagnen-Seite, Verlauf, Newsletter über
   Sammelfreigabe mit Einwilligungs-Filter.
4. **Neuen Inhalt anstoßen** — Newsletter, Posts, Team-Material auf Zuruf; Posts
   und Material in die Medien.
5. **Kanäle in Sales** — ehrliche Anzeige; danach Mockup und `:8446` abschalten.

## 7. Nicht Teil dieser Spec

- fin2gether als Mandant (eigene Spec mit CI- und Freigaberegeln der Gesellschaft).
- Layout-Anpassung im Gespräch mit dem Agenten (kommt in dieselbe Vorschau, nach Stufe 2).
- Ein eigener VibeMind-Laden.
- Automatisches Posten in soziale Netzwerke.
- Die genaue Prüfung jedes Kanals.
