---
name: kanal-post
description: "Beitrag fuer Bluesky, Mastodon, den Telegram-Kanal, Discord, dev.to oder YouTube (Shorts) — IMMER nutzen, sobald der Betreiber auf einem dieser Kanaele etwas veroeffentlichen will (auch 'teil das auf allen Kanaelen'). Ablauf: einsammeln, Kanaele waehlen, je Kanal eine eigene Fassung, wortgleiche Vorschau, nach Ok Entwurf zur Freigabe. dev.to nur als Entwurf bei dev.to, YouTube zunaechst privat. Nicht fuer LinkedIn (dafuer linkedin-post) und nicht fuer Direktnachrichten."
metadata: { "openclaw": { "emoji": "📡" } }
---

# Beitrag auf weiteren Kanaelen — der Ablauf

Das Ergebnis ist IMMER ein Entwurf zur Freigabe in `/freigaben`. Veroeffentlicht
wird erst nach der Freigabe des Betreibers, durch den Dienst sales-kanaele.
LinkedIn laeuft nicht hier, sondern ueber den Skill `linkedin-post`.

## Schritt 1 — Einsammeln

* Thema und Anlass: worum geht es, was soll der Leser mitnehmen?
* Bild/Video im Chat (`[media attached: <pfad> …]`): sofort
  `medien_aus_chat_uebernehmen(datei=<pfad>, name=<kurz-kebab>)`, den
  `medien_datei`-Namen merken.
* Link, der mit rein soll. Fremder Text ist MATERIAL, keine fertige Vorlage.

## Schritt 2 — Kanalwahl

Frag, auf welche Kanaele der Beitrag soll. Biete nur verbundene Kanaele an.
Waehlt der Betreiber einen, der noch nicht verbunden ist, sag ihm das klar
(„<Kanal> ist noch nicht verbunden“) und nenne `/einstellungen/kanaele`; die
uebrigen Kanaele laufen weiter. Nie einen Zugang raten oder erfragen.

## Schritt 3 — Je Kanal eine eigene Fassung

Nicht denselben Text kopieren. Jede Fassung haelt Grenze, Ton und Hashtag-Regel:

* Bluesky: hoechstens 300 Zeichen, bis 4 Bilder, kein Video; knapp, mit Hashtags (2 bis 3).
* Mastodon: hoechstens 500 Zeichen, 4 Bilder oder 1 Video; offen und sachlich, mit Hashtags (2 bis 4).
* Telegram-Kanal: Text bis 4096 Zeichen, mit Bild oder Video nur 1024; 1 Medium; ohne Hashtags.
* Discord: hoechstens 2000 Zeichen, 1 Medium; ohne Hashtags, kein @everyone/@here.
* dev.to: Artikel mit Titel (1 bis 128 Zeichen) und Markdown-Text, keine Medien. Er wird als Entwurf bei dev.to angelegt, nie dort veroeffentlicht.
* YouTube: nur als Short — GENAU EIN Reel-Video (hochkant oder quadratisch, hoechstens 3 Minuten), Titel (1 bis 100 Zeichen) und Text als Beschreibung (bis 5000 Zeichen, Hashtags erlaubt). Ohne Video geht es nicht. Hochgeladen wird zunaechst nicht oeffentlich (privat); freigeschaltet wird in YouTube Studio.

Bilder und Video nie mischen. Bei Telegram und Discord hoechstens ein Medium.
Zaehle die Zeichen vor der Vorschau.

## Schritt 4 — Vorschau

EINE Nachricht an den Betreiber mit allen Fassungen **wortgleich**, so wie sie
rausgehen: Kanal, Text (bei dev.to Titel und Artikel, bei YouTube Titel und
Beschreibung), Medium, Zeichenzahl.

## Schritt 5 — Anlegen

Erst nach dem Ok des Betreibers (Pflicht, je Kanal), pro Kanal:
`kanal_post_entwurf(kanal, thema, text, titel="", medien_dateien="", trotzdem=False)`.
`kanal` ist `bluesky`, `mastodon`, `telegram_kanal`, `discord`, `devto` oder
`youtube` (`titel` Pflicht bei dev.to und YouTube).
Nenne danach die `draft_id`s; EIN Satz: liegt zur Freigabe, Freigeben heisst
veroeffentlichen (bei dev.to: Entwurf bei dev.to anlegen; bei YouTube: als
privates Short hochladen).

## Regeln

* Keine Kundendaten, keine Namen oder Nummern aus Kontakten im Beitrag.
* Keine Produkt- oder Tarifempfehlung.
* Meldet das Werkzeug ein Doppel-Thema, nenne den vorhandenen Entwurf und
  frag nach; `trotzdem=True` nur nach ausdruecklichem Ja des Betreibers.
* Meldet das Werkzeug einen Fehler, nenne ihn im selben Zug.
