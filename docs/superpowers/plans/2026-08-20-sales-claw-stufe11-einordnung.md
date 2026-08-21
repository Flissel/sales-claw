# Stufe 11: Eingehende Nachrichten einordnen — statt automatisch antworten

Betreiber-Entscheidung 20.08.2026: **Der Assistent antwortet Kunden nicht mehr
von sich aus.** Eine eingehende Nachricht wird *erfasst, aufgelöst und dem
richtigen Kontakt zugeordnet*; ist der Absender unbekannt, **fragt der Bot den
Betreiber**, wie er einzuordnen ist. Antworten bleibt Handarbeit über den
bestehenden Weg (`entwurf_erstellen` → Freigabe → Dispatcher).

Damit kehrt das Produkt zu seinem Kernversprechen zurück: **keine Nachricht
ohne menschliche Freigabe** — und nicht nur „keine Nachricht an einen nicht
freigegebenen Kontakt".

## Sofort erledigt (20.08., vor diesem Plan)

* `channels.whatsapp.allowFrom` auf die beiden Betreiber-Nummern
  zurückgesetzt → OpenClaw beantwortet keine Kundenchats mehr.
  Die Erfassung läuft davon unberührt weiter (OpenWA-Webhook →
  `sales-inbox`, gemessen unabhängig von `allowFrom`).
* Kontakt-Freigaben (Christine, Moritz, Lisa Probekunde) bleiben bestehen —
  sie steuern weiterhin, ob der **Dispatcher** an diesen Kontakt zustellen
  darf. Nur die Auto-Antwort ist weg.

## Ausgangslage (gemessen 20.08.)

* 16 verschiedene Absender im CRM, **3 auflösbar** über OpenWAs
  `lid_mappings` (Sophie, Moritz Baumann, Christine), 13 waren Mock-Daten.
* `lid_mappings` liegt in `/app/data/openwa.sqlite` (Container `openwa`),
  ist global/sitzungsübergreifend und trägt einen Index auf `phone` —
  **beide Richtungen** sind vorgesehen.
* `RESOLVE_LID_TO_PHONE` ist aus; die Tabelle füllt sich deshalb nur, wenn
  etwas aktiv auflöst.
* `sales-mcp` hat **keinen** Zugriff auf `openwa.sqlite` (anderer Container,
  kein geteiltes Volume) — die Mappings müssen über einen definierten Weg
  herüberkommen.

## Aufgaben

### T1 — Mappings verfügbar machen

Entscheidung zwischen zwei Wegen, **vor der Umsetzung messen**:

1. **OpenWA-API**: prüfen, ob ein Endpunkt die Auflösung anbietet
   (`resolveContactPhone` existiert im whatsapp-web-js-Adapter;
   `core/agent-tools/tools/contact.tools.ts` ruft es auf). Wenn ja: Abruf
   über HTTP mit `X-Api-Key`, wie `dispatch.py` es schon tut — kein neues
   Vertrauensverhältnis.
2. **Read-only-Mount** von `openwa.sqlite` in `sales-mcp` (`:ro`), falls
   kein Endpunkt existiert. Nachteil: Kopplung an OpenWAs internes Schema;
   dann mit Schema-Wächter absichern (Tabelle/Spalten prüfen, bei
   Abweichung inert bleiben statt raten).

Ergebnis in beiden Fällen: eine Tabelle `sales.lid_zuordnung`
(`lid` PK, `telefon`, `quelle`, `gesehen_am`) — die Spiegelung in Postgres,
damit `inbox.py` und die Werkzeuge ohne Container-Grenze arbeiten.

### T2 — Eingehende Nachrichten auflösen

`inbox.py`: Bei `@lid`-Absender ohne `senderPhone` erst `sales.lid_zuordnung`
befragen, dann erst den Sammelkontakt nehmen. Reihenfolge bleibt:
`senderPhone` (OpenWA) → Spiegel-Tabelle → Sammelkontakt.

`RESOLVE_LID_TO_PHONE=true` in `docker-compose.openwa.yml` setzen, **damit
sich die Tabelle künftig selbst füllt**. Der alte Einwand (nur
Eingangsrichtung) entfällt, weil T3 die Gegenrichtung über dieselbe
Zuordnung löst.

### T3 — Ausgehende Richtung konsistent halten

Die absenderscharfe Beantwortet-Prüfung am Sammelkontakt vergleicht
`absender` (eingehend) mit `empfaenger`/`chat_id` (ausgehend). Beide Seiten
müssen dieselbe Kennung tragen: vor dem Vergleich über
`sales.lid_zuordnung` normalisieren (LID → Telefonnummer), sodass ein Paar
auch dann gefunden wird, wenn die eine Seite als LID und die andere als
Rufnummer gespeichert ist.

### T4 — Rückfrage bei unbekanntem Absender

Neues Werkzeug `eingang_einordnen(...)` bzw. Erweiterung des Digests: Für
jede **neue** Absenderkennung ohne Zuordnung erzeugt der Bot **eine**
Rückfrage an den Betreiber („Von 4915… kam eine Nachricht: … — wer ist das?
Anlegen als Kontakt, ignorieren, oder zuordnen zu einem bestehenden
Kontakt?"). Regeln:

* **Höchstens eine Rückfrage je Absender** (Anspruch als Aktivität, wie beim
  Dispatcher-Claim), nicht je Nachricht.
* Antwortet der Betreiber „ignorieren", wird der Absender dauerhaft als
  `ignoriert` vermerkt und taucht im Posteingang nicht mehr auf — **das ist
  auch der Weg, die Mock-Altlast loszuwerden**, ohne die Append-only-Regel
  zu verletzen (kein `DELETE`, ein Gegen-Ereignis).
* Die Rückfrage geht in den Betreiber-Chat, nie an den Absender.

### T5 — Privatsphäre: was gespeichert wird

Betreiber-Entscheidung umsetzen: **nur eingehende Nachrichten** werden
verarbeitet, und Nachrichteninhalte von Absendern, die der Betreiber als
`ignoriert` markiert hat, werden **nicht mehr** gespeichert (nur die Tatsache
„von dieser Kennung kam etwas", ohne Text). Damit landen private
Freundschaftschats nicht dauerhaft in der Vertriebsdatenbank.

## Nicht in dieser Stufe

* Keine automatischen Antworten — weder über OpenClaw (`allowFrom`) noch über
  `sales-auto`. `sales-auto` bleibt inert (kein `ANTHROPIC_API_KEY`), und
  `scripts/sync-allowlist.ps1` **darf nicht mehr laufen**, solange dieser
  Betriebsmodus gilt: es würde freigegebene Kontakte wieder in `allowFrom`
  eintragen und damit die Auto-Antwort reaktivieren. Warnhinweis gehört in
  den Skriptkopf und ins Runbook.

## Abnahme

1. Sophies 107 Nachrichten wandern vom Sammelkontakt zu ihrem Lead
   (bzw. zu dem Lead, der ihre Nummer trägt) — vorher/nachher gezählt.
2. Eine neue Nachricht von einer unbekannten Nummer erzeugt **genau eine**
   Rückfrage im Betreiber-Chat, nicht mehrere.
3. „Ignorieren" räumt den Absender aus dem Posteingang, ohne `DELETE`.
4. Kein Kundenchat bekommt eine automatische Antwort (Gegenprobe:
   `allowFrom` enthält nur Betreiber-Nummern).
5. Volle Suite grün, Ein-Läufer-Betrieb eingehalten.
