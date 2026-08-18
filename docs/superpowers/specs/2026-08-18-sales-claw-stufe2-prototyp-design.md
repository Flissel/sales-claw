# sales-claw — Stufe 2: Prototyp Vertriebsassistenz (WhatsApp + LinkedIn-Entwürfe)

**Datum:** 2026-08-18
**Status:** Entwurf zur Freigabe
**Baut auf:** Stufe 1 (2026-08-17-sales-claw-fundament-design.md) — Container läuft,
WhatsApp gekoppelt, Modell antwortet, Backup/Restore gehärtet.

## 1. Zweck und Zuschnitt

Ein **Prototyp** der Vertriebsassistenz für MH Consulting, vorführbar auf der
WhatsApp-Nummer des Betreibers. Er zeigt den Kern des späteren Werkzeugs:

1. Der Bot führt das Kundengespräch auf WhatsApp (Demo: Selbst-Chat).
2. Er erkennt Kontakte, protokolliert jede Interaktion und baut ein
   strukturiertes Kundenprofil auf.
3. Er führt eine Bedarfsanalyse nach einem Leitfaden für den
   Privatkunden-Finanzvertrieb.
4. Er erzeugt daraus **Beispiel-Nachrichten** für LinkedIn und WhatsApp in eine
   Entwurfs-Queue.
5. Er liefert auf Zuruf eine Zusammenfassung der offenen Aktionen.

### Die Produktgrenze — ausdrücklich

**Es wird nichts versendet.** Kein LinkedIn-Versand, kein WhatsApp-Outbound über
den Demo-Chat hinaus. Entwürfe enden mit Status `pending` in der Tabelle
`drafts`; der Versand wird später von einer **anderen App** übernommen, die
genau diese Tabelle liest. Der LinkedIn-Dev-Account des Betreibers dient nur als
Absender-Persona der Beispiele.

Damit entfällt für den Prototyp: jede LinkedIn-ToS-Frage (kein API-Zugriff,
kein Scraping, kein Auto-Outreach), jedes Outbound-Risiko der Art des
Hotel-Incidents, und die Approval-Mechanik kann später scharf geschaltet
werden, ohne die Architektur zu ändern.

### Nicht Gegenstand von Stufe 2

- Kein Versand irgendeines Kanals (siehe oben)
- Keine echten Kundendaten — Testdaten und der Betreiber selbst. Echte Daten
  erst nach Klärung von AVV/Einwilligung (offener Punkt aus Stufe 1, §12.1)
- Keine Dokumenten-/Vertragsverarbeitung (bleibt Stufe 4)
- Kein Multi-Nutzer, kein Auth-Ausbau
- Keine Übernahme des 42-Agenten-Schwarms aus aisalesorgcore

## 2. Herkunft der Bausteine

| Baustein | Quelle | Status |
|---|---|---|
| Datenmodell (`leads`, `activities`, `drafts`, `personas`) | `aisalesorgcore/supabase/schema.sql` | übernehmen, minimal anpassen |
| Deterministisches Scoring (`score_lead`) | `aisalesorgcore/src/tools.py` | Formel übernehmen, Kriterien neu |
| Qualifizierungs-Denkstruktur | `aisalesorgcore` Agent-Prompts | Gerüst ja, Inhalt neu (deutsch, Privatkunde) |
| Gespräch, Gedächtnis, WhatsApp | OpenClaw (`sales-claw`, Stufe 1) | läuft |
| Provisionierungs-Muster | `secondbrain-mcp/docs/bizplan-provision.sql` | als Blaupause |

**Nicht übernommen:** Schwarm, Sub-Teams, Mock-Tools (`enrich_contact`,
`fetch_linkedin_profile`, `analyze_intent_signals`), `claude_code` auf Agenten,
Org-API (`server.py`) — der Prototyp braucht keinen zweiten Agenten-Runner.

## 3. Architektur

```text
WhatsApp (Nummer des Betreibers, Selbst-Chat-Demo)
        │
        ▼
┌──────────────────────────────┐        ┌─────────────────────────────────┐
│ Container sales-claw         │  MCP   │ Container sales-mcp (NEU)       │
│ OpenClaw 2026.7.1            │◄──────►│ Python, Werkzeugdienst          │
│ Agent "main"                 │        │ kontakt_*, aktivitaet_*,        │
│ + Bedarfsanalyse-Leitfaden   │        │ profil_*, bedarf_*, entwurf_*,  │
│   (Agent-Instruktionen)      │        │ digest                          │
└──────────────────────────────┘        └───────────────┬─────────────────┘
                                                        │ SQL (Rolle sales_app,
                                                        │ kein DDL)
                                                        ▼
                                        Supabase-Postgres, Proxmox-VM .65:54322
                                        Schema `sales` (+ `sales_test`)
                                        Eigentümer: supabase_admin
```

### Warum ein eigener Werkzeugdienst (sales-mcp) statt OpenClaw-Skills

Bereits in der Stufe-1-Diskussion festgelegt, hier bindend: Die Fachlogik lebt
in einem eigenen MCP-Dienst, weil er (a) unabhängig von OpenClaw testbar ist,
(b) OpenClaw-Updates überlebt, (c) aus Claude Code heraus mitbenutzbar ist —
dasselbe Muster wie die bestehenden MCP-Server des Betreibers — und (d) die
spätere Versand-App gegen dieselbe Datenbank arbeitet, nicht gegen OpenClaw.

Der Dienst läuft als zweiter Container im selben Compose. Wie OpenClaw ihn
anspricht (stdio im Container vs. HTTP), wird bei der Umsetzung am laufenden
System verifiziert — die OpenClaw-MCP-Fähigkeiten der Version 2026.7.1 sind
nicht dokumentiert genug, um das vorab festzulegen.

### Werkzeuge des sales-mcp (Schnittstellenvertrag)

| Werkzeug | Zweck |
|---|---|
| `kontakt_suchen(text)` / `kontakt_anlegen(...)` | Erkennen oder Anlegen; Rückgabe immer mit `lead_id` |
| `aktivitaet_loggen(lead_id, typ, inhalt)` | Jede Interaktion in `activities`; `actor='agent'` |
| `profil_lesen(lead_id)` / `profil_aktualisieren(lead_id, feld, wert)` | Kundenprofil in `leads.enrichment` (jsonb), kumulativ |
| `bedarf_speichern(lead_id, frage_id, antwort)` | Antworten des Leitfadens strukturiert ablegen |
| `bedarf_offen(lead_id)` | Welche Leitfaden-Punkte fehlen noch |
| `entwurf_erstellen(lead_id, kanal, betreff?, text)` | Draft mit `status='pending'`; `kanal` ∈ whatsapp/linkedin/email |
| `digest()` | Offene Entwürfe, fällige Follow-ups, letzte Aktivitäten |

Alle Werkzeuge deutsch benannt (die Nutzerin ist deutschsprachig, die
Agent-Instruktionen sind deutsch); Tabellennamen bleiben englisch (Übernahme
aus aisalesorgcore, spätere Versand-App liest dieselben Namen).

## 4. Datenbank: Schema `sales` auf der VM-Supabase

Verifiziert am 2026-08-18: Postgres von dieser Maschine erreichbar
(`192.168.178.65:54322` offen), SSH-Zugang über Alias `offload-vm`
funktioniert, Container `debian-supabase-db-1` läuft.

Provisionierung **nach dem bizplan-Muster** (dieselbe Instanz trägt bereits
`bizplan`/`bizplan_test` nach diesem Muster):

- Schema `sales` (Produktion/Demo) und `sales_test` (Testsuite, voll berechtigt
  inkl. TRUNCATE)
- Rolle `sales_app`: `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`,
  **keine DDL-Rechte**; Eigentümer aller Objekte ist `supabase_admin`
- **`activities` ist append-only als Datenbank-Garantie**: `sales_app` erhält
  nur SELECT/INSERT. Die Historie „was wurde mit dem Kunden getan" kann damit
  auch durch einen Bug oder kompromittierten Agenten nicht nachträglich
  verändert werden — dieselbe Härtung wie `bizplan.audit_events`
- `drafts`: SELECT/INSERT/UPDATE (Statusübergänge), kein DELETE
- `leads`, `personas`: SELECT/INSERT/UPDATE
- DSN in `sales-claw/.env` (gitignoriert), niemals in Config oder Repo
- DDL-Skript im Repo (`db/provision.sql`), angewandt als Admin-Migration über
  `offload-vm`, nie durch die Anwendungsrolle
- **Vor der VM-Arbeit: Claim in `002_Koordination_Live.md`**, sofort committen

Schema-Anpassungen gegenüber aisalesorgcore (minimal):
- `leads.source` um `whatsapp`/`linkedin` erweitern (freies Textfeld, nur Doku)
- `drafts.channel`-Check um `linkedin` erweitern
- `deals` und `runs` werden **nicht** provisioniert (Prototyp braucht sie nicht;
  nachrüstbar ohne Umbau)
- `personas.embedding` bleibt, wird im Prototyp aber nicht befüllt (kein
  Embedding-Modell konfiguriert; Textsuche reicht)

### Netzabhängigkeit — definiertes Verhalten

Die Demo hängt am LAN zur VM. Ist die Datenbank nicht erreichbar, antwortet der
Bot weiter (Gespräch läuft), sagt aber ausdrücklich, dass Protokoll und Profil
gerade nicht gespeichert werden — **kein stilles Weiterarbeiten mit
Gedächtnisverlust.** Der sales-mcp liefert dafür klare Fehlertexte statt
Timeouts.

## 5. Bedarfsanalyse-Leitfaden

Gerüst aus der aisalesorgcore-Qualifizierungsstruktur (Stufen, Scoring,
Lückenerkennung), Inhalt neu für den deutschen Privatkunden-Finanzvertrieb:

| Feld | Beispiele |
|---|---|
| Lebenssituation | Alter, Familienstand, Kinder, Beruf, Angestellt/Selbstständig |
| Einkommen & Haushalt | Nettoeinkommen, Fixkosten, Sparquote |
| Bestehendes | Versicherungen, Verträge, Anlagen — was ist schon da |
| Absicherung | BU, Haftpflicht, Risikoleben — Lücken |
| Vorsorge | Renteninformation, bAV, private Vorsorge |
| Ziele & Horizont | wofür, bis wann, Prioritäten |
| Risikoneigung | Selbsteinschätzung, Erfahrung mit Anlagen |
| Consent | Newsletter/Kontaktkanal-Einwilligung → `leads.consent_status` |

Der Bot arbeitet die Felder **adaptiv** ab (fragt nur, was fehlt; `bedarf_offen`
liefert die Lücken), fasst am Ende zusammen und legt alles strukturiert ab.

**Kennzeichnung:** Dieser Katalog ist ein Platzhalter aus Branchenwissen. Der
fachliche Feinschliff (Reihenfolge, Pflichtfelder, Formulierungen) braucht
Input von MH Consulting und ist ein ausgewiesener offener Punkt — der Prototyp
soll genau dieses Gespräch ermöglichen.

**Grenze (bindend):** Der Bot gibt **keine Produktempfehlungen** und keine
Aussagen zu Rendite, Steuern oder Konditionen. Auf solche Fragen: aufnehmen,
als offenen Punkt loggen, an die Beraterin verweisen. Das steht wörtlich in den
Agent-Instruktionen.

## 6. Beispiel-Nachrichten (LinkedIn + WhatsApp)

Auf Zuruf („mach mir einen LinkedIn-Erstkontakt für Herrn X") oder nach
abgeschlossener Bedarfsanalyse erzeugt der Bot Entwürfe:

- **LinkedIn**: Erstansprache/Follow-up, aus Profilfeldern personalisiert,
  Absender-Persona = Dev-Account des Betreibers. Landet als
  `drafts(channel='linkedin', status='pending')`. **Wird nie versendet.**
- **WhatsApp**: Follow-up-/Terminvorschlagstexte, gleicher Weg,
  `channel='whatsapp'`.

Der Demo-Chat selbst (Bot antwortet im Gespräch) ist davon unberührt — das ist
Konversation, kein Outbound.

## 7. Abnahme (Demo-Drehbuch = Abnahmetest)

Nachgewiesen heißt: ausgeführt, Ausgabe gesehen — Datenbankinhalt per SQL
gegengeprüft, nicht nur Chatverlauf gelesen.

1. **Kaltstart:** Unbekannter Name schreibt (Demo: Betreiber nennt eine
   Testperson) → Bot legt Kontakt an, `leads`-Zeile existiert.
2. **Protokoll:** Jede Nachricht erzeugt eine `activities`-Zeile mit
   `actor='agent'`; append-only nachgewiesen (UPDATE als `sales_app` scheitert
   mit 42501).
3. **Bedarfsanalyse:** Über mindestens 6 Nachrichten hinweg; Bot fragt nur
   Fehlendes, `bedarf_offen` schrumpft, Antworten stehen strukturiert in
   `leads.enrichment`.
4. **Gedächtnis über Sitzungen:** Container-Neustart mitten im Gespräch → Bot
   kennt den Stand danach noch (Profil kommt aus der DB, nicht nur aus dem
   Chat-Kontext).
5. **Entwürfe:** Je ein LinkedIn- und ein WhatsApp-Entwurf in `drafts`,
   `status='pending'`, personalisiert aus dem Profil. **Kein Versand:** die
   Zeilen bleiben `pending`, nichts verlässt das System.
6. **Digest:** `digest()` nennt offene Entwürfe und letzte Aktivitäten korrekt.
7. **Netzausfall:** VM-Route gekappt (oder sales-mcp gestoppt) → Bot sagt
   ausdrücklich, dass nicht gespeichert wird; kein stiller Datenverlust.
8. **Keine Beratung:** Auf eine Produktfrage („was soll ich kaufen?") verweist
   der Bot an die Beraterin und loggt einen offenen Punkt.

## 8. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| OpenClaw 2026.7.1 spricht MCP anders als erwartet | Bei der Umsetzung zuerst verifizieren; Rückfallweg: sales-mcp als HTTP-Dienst + OpenClaw-Skill |
| VM nicht erreichbar während Demo | Definiertes Fehlverhalten (§4); Demo-Drehbuch Punkt 7 testet es |
| Prompt-Injection über Kundennachrichten | Prototyp hat keine Send-Rechte — die gefährliche Kombination (liest Fremdtext + darf senden) existiert nicht. Vor Scharfschaltung des Versands neu bewerten (geerbter Punkt aus Stufe 1, §12.8) |
| Leitfaden fachlich unvollständig | Ausgewiesener Platzhalter; Freigabe durch MH Consulting ist Teil von Stufe 3 |
| Kundendaten beim Modellanbieter | Prototyp: nur Testdaten. Echtbetrieb braucht AVV — unverändert offen (Stufe 1 §12.1) |
| Zwei Sessions provisionieren gleichzeitig auf der VM | Claim-Protokoll im Koordinations-Board |

## 9. Offene Punkte

1. **Fachlicher Leitfaden**: Input von MH Consulting (Reihenfolge, Pflichtfelder).
2. **Eigene Nummer für sales-claw**: Für den Prototyp reicht die
   Betreiber-Nummer im Demo-Betrieb (`restart: "no"`); vor jedem Einsatz mit
   Dritten braucht es die eigene Nummer (Stufe-1-Erkenntnis, unverändert).
3. **Versand-App**: liest später `drafts` — Schnittstelle ist die Tabelle;
   wer sie baut und wann, ist offen. **Kandidat (geprüft 2026-08-18):**
   [OpenWA](https://github.com/rmyndharis/OpenWA) — selbstgehostetes
   WhatsApp-REST-Gateway (Multi-Session, Webhooks mit HMAC, Rate-Limiter).
   Einordnung: für eine Pilot-Phase mit dedizierter Nummer geeignet, und der
   `whatsapp-web.js`-Motor gilt als sperr-risikoärmer als Baileys; die eigene
   Compliance-Doku von OpenWA erklärt es für Finanz-/EU-regulierte Umgebungen
   aber ausdrücklich für „not approved" und verweist auf Metas offizielle
   Cloud API — für den Echtbetrieb bei MH Consulting bleibt der offizielle
   Weg gesetzt.
4. **Stufe-1-Rest**: Task 6 (Wiederherstellungsprobe, jetzt mit ~42 s
   Wartungsfenster) und Task 7 (Serverartefakte) bleiben offen und sind
   unabhängig von Stufe 2 nachholbar.
5. **Embedding/Wissensbasis**: `personas` bleibt leer, bis eine kuratierte
   Wissensbasis (Stufe 4) und ein Embedding-Weg entschieden sind.
6. **Consent-Heuristik härten (vor Stufe 3 zwingend).** `bedarf_speichern`
   erkennt Einwilligung per Präfix-Match („ja", „gern", „ok", „einverstanden").
   Empirisch belegt (Task-3-Review): „Ja, aber bitte nicht per WhatsApp",
   „Jain", „ja nicht" werden **fälschlich als `opt_in`** gewertet. Im
   Prototyp folgenlos (nichts wird versendet, keine echten Kunden) — vor dem
   ersten Echtkontakt muss die Erkennung Negationen verstehen oder die
   Normalisierung an das Modell ausgelagert werden. Consent ist im
   Finanzvertrieb kein kosmetisches Feld; die Hotel-Lehre (793 Mails) gilt.
7. **Entwurfs-Empfänger vor Versand-App-Anbindung klären.** Ein
   WhatsApp-/E-Mail-Entwurf ohne hinterlegte Nummer/Adresse fällt auf den
   Namen als `recipient` zurück. Die spätere Versand-App muss damit rechnen —
   oder `entwurf_erstellen` lehnt kanalunpassende Empfänger ab, sobald echte
   Zustellung existiert.
