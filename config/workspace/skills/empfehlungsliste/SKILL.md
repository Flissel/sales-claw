---
name: empfehlungsliste
description: "Empfehlungsliste erfassen — IMMER nutzen bei Foto oder Diktat einer Pole Position (Konzept fuer den Aufbau von Empfehlungen) oder einer Liste Mitarbeitervorschlaege, oder wenn der Betreiber 'Empfehlungen' bzw. eine 'Wen kennst du'-Liste erfassen will. Ablauf: lesen, Vorschau mit (?), EINE gesammelte Rueckfrage, erst nach Ok anlegen."
metadata: { "openclaw": { "emoji": "📋" } }
---

# Empfehlungsliste — der Ablauf

## Schritt 1 — Lesen

Lies das Foto Zeile fuer Zeile. Zeig die Zeilen nummeriert im Chat:
„1. Vorname Name · Beruf · Alter · Ort · Telefon · (Pole Position) /
Was zeichnet aus · Was interessiert (Mitarbeitervorschlaege)".
Unsichere Felder bekommen ein „(?)". Nichts raten: Unleserliches bleibt leer
und wird genannt.

## Schritt 2 — EINE gesammelte Rueckfrage

1. Welcher Vordruck: Pole Position oder Mitarbeitervorschlaege?
2. Wer hat die Liste gegeben (Name; gibt es ihn im CRM, nimm seine lead_id)?
   Welches Datum?
3. Hat dieser Mensch alle gefragt, ob du dich bei ihnen melden darfst?
   Die Einwilligung kommt NUR aus der ausdruecklichen Antwort des Betreibers auf genau diese Frage —
   nie aus dem Foto, einem Haken/Vermerk auf dem Zettel oder dem Diktat. Ja → einwilligung=true fuer
   alle Zeilen; Nein, unklar oder keine Antwort → einwilligung=false.
4. Nur Pole Position: Fuer welche Bereiche ist die Liste (vorsorge,
   immobilien, mitarbeiter, bav …)? Welche Zeilen sind Firmen (firma: true → Firma mit bAV)?
   Bei Mitarbeitervorschlaegen gibt es keine Firmenzeilen (firma weglassen).
5. Korrekturen an den gelesenen Zeilen?
6. Nur beim allerersten Mal: Name und Struktur fuer den Listenkopf (danach
   werden sie von der letzten Liste uebernommen).

## Schritt 3 — Anlegen, erst nach Ok

`empfehlungsliste_anlegen(art, empfohlen_von, datum, zeilen, einwilligung,
bereiche, berater_name, struktur)` — dann EIN Satz: „Liste angelegt: N neu,
M schon bekannt/verknuepft, K abgewiesen (Grund)", dazu die Hinweise des
Werkzeugs woertlich weitergeben (Telefon pruefen, Alter unter 22, schon
bekannt bei einer anderen Liste) und den Link `/empfehlungen/<liste_id>`.

Die Einwilligung wird nie fuer Kontakte gebucht, die selbst abgelehnt haben
(Newsletter abbestellt, Einwilligung „nein", eigener Widerruf). Das Werkzeug
meldet das als Hinweis; gib ihn unveraendert weiter und buche nichts nach.

## Danach

Empfohlene werden nie von sich aus angeschrieben. Ein Entwurf entsteht nur
auf ausdruecklichen Zuruf des Betreibers und nur, wenn die Einwilligung
gebucht ist — wie bei allen Kontakten. Uebersicht und Stand:
`empfehlungslisten_zeigen()`.

Zu Empfohlenen keine Recherche (web_search, firma_anreichern, b2b_leads, marktanalyse) —
sie kennen dich noch nicht; nur auf ausdruecklichen Zuruf des Betreibers fuer eine benannte Zeile.

Meldet das Werkzeug einen Fehler oder bleibt die Antwort aus: erst
`empfehlungslisten_zeigen()` pruefen, nie blind erneut anlegen — Listen lassen sich nicht loeschen.
