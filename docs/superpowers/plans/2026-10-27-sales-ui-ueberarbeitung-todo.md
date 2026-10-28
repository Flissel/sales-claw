# Sales-UI überarbeiten — TODO aus dem Seitenrundgang (27./28.10.2026)

Gemeinsamer Rundgang mit dem Betreiber durch die Sales-UI. Code: `sales-mcp/ui.py` (+ `server.py`,
`ui_struktur.py`, `ui_kalender.py`, `kalender_sicht.py`, `postfach.py`, `inbox.py`). Pro Seite: Wunsch des
Betreibers (**U**) und eigene Funde (**C**). Umgesetzt 28.10.2026 auf Branch `feat/sales-ui-todo`, Vertrags-
Tests in `sales-mcp/tests/test_ui_todo.py`.

**Vor dem Deploy:** `db/provision.sql` auf der VM einspielen (neue Tabellen `einstellungen`, `postfach_mails`),
dann `deploy/update.sh`. AGENTS.md geht mit (Rückfrage nach dem Termin, Postfach aufräumen).

## Allgemein

- [x] **U** Schrift größer (Grundschrift 17 px, Menü 1,05 rem, Gruppentitel, Meta-Zeilen).
- [x] **C** Login-Seite ohne Seitenleiste/Zähler, solange niemand angemeldet ist (`_ANGEMELDET`).

## Heute (`/`)

- [x] **U** Block „Termine ohne festes Datum“ raus; Kennzahl jetzt „Termine heute“ (→ Tagesansicht).
- [x] **U** Ursache abgestellt: die 8 Einträge waren Freitext-Notizen über `aktivitaet_loggen(typ='termin')`.
  Das Werkzeug lehnt `termin` jetzt ab (→ `termin_bestaetigen` oder `notiz`). Die 8 Altnotizen bleiben
  unverändert (append-only) und stehen nur noch im Kalender unter „Ohne festes Datum“.
- [x] **U** Posts bleiben.
- [x] **C** Einordnung-Zahl vereinheitlicht: Seite und Seitenleiste lasen nur die 25 jüngsten Kennungen,
  Heute bis 1000 — ältere offene Absender waren auf `/einordnung` unsichtbar. Jetzt überall dieselbe Grenze.

## Freigaben (`/freigaben`)

- [x] **U** Nur Offenes; Verläufe (je Kanal, Termine, Marketing, „Zuletzt entschieden“) → **Monitoring → Verlauf**
  (`/monitoring/verlauf`).
- [x] **C** Eine Zählregel (`_freigaben_zusatz`) für Seitenleiste, Heute und Seite.
- [x] **C** Termine sind keine Freigaben mehr.
- [x] Neu: Abschnitt „Mails aufräumen“ (Vorschläge des Agenten, s. Posteingang).

## Wiedervorlagen (`/wiedervorlagen`)

- [x] **U** Oben „Heute anstehende Termine“ je Termin mit Art (Termin 1/2), was gebraucht wird
  (Bedarfsanalyse-Bogen / Angebot, Firmen eigene Bedarfsanalyse) und welche Unterlagen schon beim Kontakt
  liegen (Link `/medien`).
- [x] **C** Bisherige Wiedervorlagen bleiben darunter als „Erinnerungen“.

## Einordnung (`/einordnung`)

- [x] **U** Letzte 3 Nachrichten je Absender mit Typ, **Audio-Spieler**, **Abschrift** und **Bild**. Bilder
  unbekannter Absender speichert `sales-inbox` jetzt (nur Sammelkontakt), `sales-ui` liest den Ordner nur.
- [x] **U** Spalten Profil/Nachrichten raus, **Beziehung** rein (direkt setzbar).
- [x] **C** Kennung lesbar (`+49 176 …`) mit Kanal-Zeichen.

## Kalender verbinden / Kalender

- [x] **U** GMX als Anbieter (iCal-Freigabelink). **Offen:** Klickweg am echten GMX-Konto prüfen; fehlt der
  Link im Tarif, GMX per CalDAV anbinden.
- [x] **C** CSP: `font-src 'self' data:` auf `/kalender` (Pfeil-Symbole).
- [x] **U** **Team-Ebenen** je Mitglied an/aus, nur „belegt“ (kein Titel/Ort — auch nicht an den Agenten);
  ausgeschaltete plant der Agent nicht mit (`team_kalender_aus`, `belegungen()`).

## Kontaktliste (`/kontakte`)

- [x] **U** Spalten nach der Papier-Namensliste: Name/Anschrift · Telefon · Alter/Fam./Kinder · Beruf & Hobbys ·
  Termine (bis 5) · Abschluss · Empf.-Zahl · Bemerkung FK/analysiert (+ Autonomie, Archiv). Felder je Kontakt
  unter „Bearbeiten“ (`enrichment.liste`); Alter/Beruf/Ort aus Empfehlungslisten als Vorbelegung.
- [x] **U** Empfehlungen zusammengelegt: Filter „empfohlen von …“; die Vordrucke/PDF bleiben unter `/empfehlungen`
  (Verweis oben), der Menüpunkt ist weg.
- [x] **U** Standard-Autonomie je Beziehung (Kasten auf `/kontakte`). Vorgabe: Kunde/Partner = halbauto,
  Mitarbeiter/Privat = manuell; `ignorieren` als Standard ausgeschlossen. Stufe am Kontakt geht vor.
- [x] **U** Suche tippfehlertolerant (pg_trgm, z. B. „Löfelman“ → „Löffelmann“). Echte Bedeutungssuche mit
  Embeddings bräuchte ein Modell (nicht auf der VM) — **offen**, falls die Trigramm-Suche nicht reicht.

## Newsletter-Einwilligung → Pipeline

- [x] **U** In die Pipeline: „Newsletter ✓“ je Karte + Filter ja/nein; Menüpunkt weg, Link/QR zur
  Selbst-Anmeldung aus der Pipeline verlinkt. Nachweis bleibt unverändert im Hintergrund.

## Pipeline (`/pipeline`)

- [x] **U** Reiter Kontakte · Firmen · Privat; Mitarbeiter in keiner.
- [x] **U** Phasen: neu → kontaktiert → Termin 1 · Aufnahme → Bedarfsanalyse → Termin 2 · Verkaufsgespräch →
  Abschluss → Empfehlung (+ verloren). **Ohne DB-Migration:** Phase in `enrichment.pipeline`, alte Stufen werden
  beim Lesen abgebildet (recherchiert/qualifiziert → neu, geantwortet → kontaktiert, termin → Termin 1,
  gewonnen → Abschluss). Phase je Karte setzbar.
- [x] **C** Suche, je Spalte 15 Karten + „weitere“.

## Ergebnisse (`/ergebnisse`)

- [x] **U** Nach Verkaufsgesprächen organisiert; oben „Wie lief der Termin?“ mit Antwortformular.
- [x] **U** Rückfrage: Werkzeuge `termin_rueckfragen` / `termin_ergebnis_speichern`, im Routinelauf
  (AGENTS.md). Fällig 30 min nach Terminende; Termin 1 → Bedarfsanalyse, Erfolg → Abschluss (mit „was“).
- Kanal der Rückfrage: der Chat des Agenten mit dem Betreiber (Routinelauf) + Formular auf `/ergebnisse`.

## Posteingang

- [x] **U** Ein Posteingang: unbeantwortete Chats (mit Kanal), Mails des Betreiber-Postfachs, Suche über beides.
- [x] **U** Betrug → sofort Spam-Ordner (`mail_einstufen(uid,'spam')`, IMAP verschieben, nie löschen);
  Spam-Ordner auf der Seite einsehbar.
- [x] **U** Unwichtiges nur als Vorschlag in Freigaben; verschoben erst nach Klick (`mail_aufraeumen_ausfuehren`).
- [x] **U** Mails durchsuchbar (deutscher Volltext mit Wortstämmen + Tippfehler-Toleranz).
- [x] **C** Wartezeit „14 Std.“, Knopf „Antworten“.
- [ ] **U** Weitere Quellen (Reddit, Benachrichtigungen anderer Dienste) — **offen**: Reddit hat keinen
  Zugang (Konto legt der Betreiber an, API gesperrt); landen solche Mails im Postfach, erscheinen sie schon.

## Struktur (`/team/struktur`)

- [x] **U** „Mein höherer Knoten“ (z. B. ivan) — steht über „Ich“; was an ihm hing, hängt unter dir.
- [x] **U** Drag and Drop: Eintrag auf Eintrag = umhängen, auf das Feld oben = höherer Knoten; mit Rückfrage.
  Ringe lehnt der Server ab. Formulare bleiben als Weg ohne Maus.

## Marketing

- [ ] **U** **Marke löschen** — **offen, braucht Entscheidung:** hart löschen oder ausblenden, und was mit
  Inhalten/Vorlagen der Marke passiert. Braucht eine Marketing-Migration in `vibemind-os`.
- [ ] **U** Kampagnen, Newsletter-Erstellung, Marke — **eigene Runden mit dem Betreiber** (so vereinbart).
- [ ] **U** Reels → Higgsfield über Laura — **offen:** Zugang/Kosten von Higgsfield.
- [ ] **U** Podcast → ElevenLabs — **offen:** API-Schlüssel + Budget (eigener Bezahldienst).

## Monitoring

- [x] **U** Kanäle von Admin nach Monitoring; neuer Punkt „Verlauf“.
- Antwort „per API bedienbar?“: Ja für Bluesky, Mastodon, Telegram-Kanal, Discord, dev.to (Entwurf), YouTube
  (Shorts, privat bis Audit) über `sales-kanaele` nach Freigabe; LinkedIn nur Profil; kein Weg für Instagram,
  Facebook, Threads, TikTok, WhatsApp-Kanal, Reddit, X.

## WhatsApp-Bot

- [x] **U** Geprüft 28.10. (nur lesend): **kein Fehler im Bot** — kein einziger Kontakt steht auf `auto`
  (553 Vorgabe manuell, 9 halbauto, 14 ignorieren, 1 manuell). Seit 22.09. antwortet der Bot nur bei `auto`.
  Mit den neuen Standardstufen je Beziehung lässt sich das jetzt gezielt einschalten.
- [ ] **C** Auffällig: Kevin schmidt und Klara Weindorf stehen auf `ignorieren`, erscheinen aber im Posteingang —
  prüfen, ob die Stufe nach den Nachrichten gesetzt wurde oder der Filter greift nicht.
- [ ] Live-Test per WhatsApp Web (Testnachricht an den Bot) — nach dem Deploy.
