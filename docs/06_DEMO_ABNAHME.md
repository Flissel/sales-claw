# 06 — Demo-Abnahme (Protokoll)

**Datum:** 2026-08-18, Abend · **Form:** Durchspiel auf Wunsch des Betreibers —
der Koordinator führte das Gespräch skriptgesteuert gegen den echten Agenten
(gleiche Werkzeuge, gleiche Datenbank, Session `agent:main:demo-durchspiel`,
kein `--deliver`). Die Live-Zustellung (Punkt „Versand") war bereits am selben
Abend real erfolgt (Entwurf `e86ebb28…`, `sent` 20:02:27, Zustellung auf das
Telefon des Betreibers bestätigt).

## Ergebnis je Abnahmepunkt (Spec Stufe 2, §7)

| # | Punkt | Ergebnis | Beleg |
|---|---|---|---|
| 1 | Kaltstart: unbekannter Kontakt wird angelegt | ✅ mit Befund B1 | Lead `8b869113…` „Lisa Probekunde" existiert; **Befund: doppelt angelegt** (zweiter Lead `3ddfc83b…`) |
| 2 | Jede Interaktion protokolliert, append-only | ✅ | 24 Aktivitäten (23 `bedarf`, 1 `nachricht`); 42501-Nachweis für UPDATE/DELETE aus Stufe-2-Abnahme |
| 3 | Bedarfsanalyse adaptiv, Antworten strukturiert | ✅ | **16/16 Leitfragen** in `leads.enrichment.bedarf`; Bot fragte je Zug genau eine Sache, fasste am Ende sauber zusammen; „Was fehlt noch?" → „Keine offenen Punkte", tabellarisch |
| 4 | Gedächtnis über Sitzungen | ✅ (konstruktiv) | Jeder Zug war ein eigener Prozess; Zug 5 las den Stand vollständig aus der DB. Container-Neustart-Festigkeit separat belegt (Stufe 1 T9, Stufe 3) |
| 5 | Entwürfe LinkedIn + WhatsApp, personalisiert, `pending` | ✅ | Je ein Draft auf dem Lead, personalisiert (Name, Terminrahmen), Consent `opt_in` in der Anzeige, nichts versendet |
| 6 | Digest nennt Offenes korrekt | ✅ mit Befund B1 | Digest listete 3 pending-Drafts mit IDs/Kanälen — der dritte hängt am Dubletten-Lead |
| 7 | Netzausfall-Verhalten | ✅ (aus Stufe-3-Tests) | `_gesichert`-Fehlertext-Nachweis Task 2; im Durchspiel nicht erneut provoziert |
| 8 | Keine Beratung, Verweis + offener Punkt | ✅ mit bekannter Einschränkung | Stufe-2-T5-Smokes: Werkzeugseite immer korrekt, Antworttext bei `openrouter/free` in 1 von 2 Läufen ohne Beraterin-Verweis (dokumentierte Modell-Varianz) |
| + | **Live-Zustellung nach Freigabe** (Stufe 3) | ✅ real | `approved` 20:02:19 → `sent` 20:02:27, Nachricht auf dem Telefon angekommen |

## Befunde aus dem Durchspiel

- **B1 — Dubletten-Anlage:** Der Agent legte „Lisa Probekunde" doppelt an,
  entgegen der Regel „erst suchen, dann anlegen" (Modell-Varianz). Folge:
  ein verwaister dritter Draft am Zweit-Lead. **Maßnahme (eingeplant):**
  Dubletten-Kante im Werkzeug `kontakt_anlegen` selbst — gleiche
  normalisierte Telefonnummer ⇒ bestehenden Lead zurückgeben statt neu
  anlegen. Das Gate gehört in die Datenbank-/Werkzeugschicht, nicht ins
  Modellverhalten (Projektprinzip).
- **B2 — Anrede:** Der Bot duzte die Kundin ungefragt („Hallo Lisa, … dich"),
  entgegen der AGENTS-Regel. Modell-Varianz; wird mit dem
  Verkäufer-Update der AGENTS.md erneut eingeschärft, bleibt aber
  Verhaltens-, nicht Konstruktionsgarantie.
- Latenz je Zug: Sekunden bis Minuten (`openrouter/free`, bekannte
  Betreiber-Entscheidung).

## Artefakte

Transkript: `.superpowers/demo/durchspiel.log` (unversioniert) ·
Muster-PDFs für F4: `media/checkliste-erstgespraech.pdf`,
`media/terminbestaetigung-muster.pdf`,
`media/bedarfsanalyse-zusammenfassung-muster.pdf` (alle als Demo
gekennzeichnet, ohne Bezug zu realen Firmen).
