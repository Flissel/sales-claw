---
name: linkedin-post
description: "LinkedIn-Beitrag fuer das eigene Profil — IMMER nutzen, sobald der Betreiber einen LinkedIn-Post will (neu, ueberarbeiten, 'mach daraus einen Post', mit Bild oder fremdem Text als Vorlage). Ablauf: Fragebogen in einer Nachricht, Markier-Liste klaeren, schreiben, wortgleiche Vorschau, Entwurf zur Freigabe. Nicht fuer LinkedIn-Direktnachrichten an Personen."
metadata: { "openclaw": { "emoji": "📣" } }
---

# LinkedIn-Beitrag — der Ablauf

Das Ergebnis ist IMMER ein Entwurf zur Freigabe. Veroeffentlicht wird erst
nach der Freigabe des Betreibers (Dienst sales-linkedin). @-Markierungen
gehen ueber die API nicht — der Betreiber setzt sie nach dem Posten in der
App; du lieferst ihm dafuer die Markier-Liste.

## Schritt 0 — Einsammeln

* Bild/Video im Chat (`[media attached: <pfad> …]`): sofort
  `medien_aus_chat_uebernehmen(datei=<pfad>, name=<kurz-kebab>)` und den
  zurueckgegebenen `medien_datei`-Namen merken.
* Mitgeschickter Text, Links, Post eines anderen: das ist MATERIAL, keine
  fertige Vorlage. Notiere, was daraus fuer den Fragebogen schon hervorgeht.

## Schritt 1 — Fragebogen (EINE Nachricht)

Schick genau diese vier Punkte, nummeriert. Was du schon weisst, setzt du
als „(erkannt: …)“ ein — der Betreiber bestaetigt oder korrigiert nur:

1. Anlass & Kernbotschaft — worum geht es, was soll der Leser mitnehmen?
2. Sprache & Ton — Deutsch oder Englisch? Persoenlich oder sachlich?
3. Personen & Firmen — wen soll ich zum Markieren vormerken?
4. Bild/Video, Links, Hashtags — was kommt mit rein?

Punkt 2 ist Pflicht und wird IMMER ausdruecklich bestaetigt, auch wenn das
Material eine Sprache nahelegt.
**Ohne bestaetigte Sprache wird nicht geschrieben.**
Fehlt nach der Antwort etwas, frag EINMAL gesammelt nur die
Luecken nach — Sprache zuerst.

## Schritt 2 — Markier-Liste klaeren

* Personen: `web_search` nach dem Profil (nur Personen, die der Betreiber
  fuer SEINEN Beitrag nennt — Regel in AGENTS.md). Mehrere Treffer: zeig die
  Kandidaten (Link + eine Zeile Ort/Firma) und lass waehlen. Nichts raten.
  Kein eindeutiger Treffer: Name ohne Link vormerken und das sagen.
* Firmen: Name vormerken; eine Firmenseite nur, wenn die Suche sie
  eindeutig liefert.
* **Der Betreiber selbst steht nie auf der Liste** und erscheint im Text nie
  als „einer der anderen“ — er ist der Erzaehler.

## Schritt 3 — Schreiben (in der Sprache aus Punkt 2)

1. `linkedin_historie()` lesen: Themen, die schon draussen sind, und die
   `bausteine` (verbrauchte Wendungen — anders formulieren oder weglassen).
2. Leser vor Produkt: Wer liest das, was verliert er heute, woran erkennt er
   sich in zwei Zeilen? Der Beitrag beginnt dort, nie mit „Wir haben X
   gebaut“.
3. Drei verschiedene erste Zeilen schreiben, die haerteste ehrliche nehmen;
   die anderen in der Vorschau mitnennen.
4. Ein Gedanke pro Beitrag, kurze Absaetze, Schluss mit einer konkreten
   Frage, hoechstens 3000 Zeichen.
5. Namen von der Markier-Liste stehen als Klartext genau dort, wo der
   Betreiber sie spaeter in der App markiert.
6. Selbstpruefung: keine Folge von sechs Woertern aus den `bausteine`n.

## Schritt 4 — Vorschau, dann Entwurf

Eine Nachricht an den Betreiber:

* den Endtext **wortgleich**, so wie er an LinkedIn geht,
* Sprache, Medium (`medien_datei`), die verworfenen Einstiege,
* die Markier-Liste (Name · Person/Firma · Profil-Link).

Erst auf sein Ok:

* neu: `post_entwurf_erstellen(thema, text, medien_datei=…)`,
  wartender Entwurf: `entwurf_bearbeiten(...)`;
* danach `post_markierungen_setzen(draft_id, eintraege)` mit der
  bestaetigten Liste (leer lassen, wenn niemand markiert wird).

Dann EIN Satz: Entwurf liegt zur Freigabe; nach dem Posten kommen Link und
Markier-Liste automatisch per WhatsApp. Die Freigabe entscheidet der
Betreiber, und Freigeben heisst schon veroeffentlichen: der Dienst
sales-linkedin holt den Beitrag binnen einer Minute (hoechstens einer pro
Tag). `linkedin_versand_anfordern()` nur, wenn der Betreiber ausdruecklich
will, dass der Beitrag sofort per Chat veroeffentlicht wird.
