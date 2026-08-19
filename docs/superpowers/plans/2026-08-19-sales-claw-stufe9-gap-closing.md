# sales-claw Stufe 9 — Gap-Closing (Termin/ICS, E-Mail, Newsletter)

> Auftrag des Betreibers (2026-08-19): „mach ein gap closing" — Abgleich mit
> der Feature-Liste eines Konkurrenz-Agenten. Geschlossen werden die drei
> schliessbaren Luecken: Kalender-Eintrag, E-Mail-Bestaetigung,
> Newsletter-Status; die Terminerinnerung an Kunden bleibt hinter der
> Freigabe (Produktentscheidung, kein Mangel) und wird ueber Auto-
> Wiedervorlage + Digest angebahnt. Telefonie und „Bestellungen" sind
> bewusst aussen vor (anderes Produkt bzw. §34d-Gebiet der Beraterin).

## Bindende Grundsätze (unverändert)

- Freigabe-Gate ist die DB: NICHTS verlässt das System ohne approved —
  auch nicht per E-Mail. Der Mail-Weg bekommt EXAKT dieselbe Konstruktion
  wie WhatsApp (atomarer Claim, Fehlerbuchung, at-most-once).
- `media/` bleibt `:ro` für alle Container — was anhängbar ist, legt ein
  Mensch ab. ICS-Dateien entstehen deshalb in `/reports` (beschreibbar,
  gehärteter Schreiber existiert); wer sie versenden will, kopiert sie von
  Hand nach `media\` (dokumentierter Weg, kein neuer Mount).
- Sicherheitsregeln wie immer: `.env` nie lesen, `docker compose config`
  verboten, `--remove-orphans` tabu, Secrets nie in argv/Output/Logs,
  sales_test-Wache, functools.wraps, MSYS_NO_PATHCONV, TimeZone=UTC.

## Bausteine

### G1 — `termin_bestaetigen` + ICS (server.py, medien.py)

Werkzeug `termin_bestaetigen(lead_id, datum, uhrzeit, dauer_minuten=60,
thema='Erstgespraech', ort='')`:

- Validierung: `datum` ISO (YYYY-MM-DD, nicht Vergangenheit), `uhrzeit`
  HH:MM, `dauer_minuten` 15..480 gekappt, `thema`/`ort` Freitext gekürzt.
- Erzeugt eine RFC-5545-ICS (VCALENDAR/VEVENT: UID `uuid4@sales-claw`,
  DTSTAMP jetzt UTC, DTSTART/DTEND mit `TZID=Europe/Berlin` und
  eingebettetem VTIMEZONE-Block für Europe/Berlin — OHNE VTIMEZONE lehnen
  Outlook-Varianten TZID-Referenzen ab; MESSEN heisst hier: die erzeugte
  Datei in einem Kalender-Programm des Hosts öffnen ist nicht möglich,
  also gegen die RFC bauen und per Text-Assertions testen). SUMMARY
  `<thema> — <Kontaktname>`, LOCATION optional, DESCRIPTION neutral
  (KEINE Bedarfsdaten — die ICS wandert ggf. zum Kunden!).
- Ablage nach `/reports` über den gehärteten Schreiber
  (`recherche.report_schreiben`, Slug wie bei der Übergabe:
  `termin-<slug(name)>-<datum>.ics`); `ueberschrieben` wird durchgereicht.
- `activities` typ `termin` am Lead (payload: datum, uhrzeit, thema, pfad).
- **Auto-Wiedervorlage „Terminerinnerung"** einen Tag vor dem Termin
  (`max(heute, termin-1)`, via `_wiedervorlage_anlegen`) — sie taucht im
  Digest auf; die Erinnerungs-NACHRICHT an den Kunden entsteht wie immer
  als Entwurf + Freigabe. KEIN zweiter Termin-Duplikat-Schutz nötig über
  das hinaus, was die Rückgabe sagt (`ueberschrieben` + gleiche Datei).
- Rückgabe: `pfad`, `ueberschrieben`, `bestaetigungstext` (fertiger
  kurzer WhatsApp-Text mit Datum/Uhrzeit/Ort — der Betreiber lässt daraus
  auf Zuruf einen Entwurf machen), `wiedervorlage` (wie vertrag_speichern),
  `hinweis` (ICS liegt in reports\; zum Mitsenden nach media\ kopieren).
- **medien.py:** `.ics` in die Whitelist (`("send-document",
  "text/calendar")`). Bestehende Whitelist-Tests prüfen und RELATIV
  anpassen (Fehlertexte zählen `sorted(ERLAUBT)` dynamisch auf — Tests,
  die die Liste wörtlich zitieren, nachziehen).

### G1b — CalDAV-Eintrag (optional aktiv, gleiche Inert-Bauart wie G2)

Der Betreiber nutzt Namecheap PrivateEmail; dessen CalDAV-Server ist
`dav.privateemail.com` (gemessen am Konfigurationsdialog des Anbieters,
Konto `felix@vibemind.space`). Damit kann `termin_bestaetigen` den Termin
ZUSAETZLICH direkt in den echten Kalender schreiben:

- Konfiguration aus `.env`: `CALDAV_URL` (Kalender-Kollektion, z. B.
  `https://dav.privateemail.com/dav.php/calendars/<user>/<kalender>/`),
  `CALDAV_USER`, `CALDAV_PASSWORT`. FEHLT eine der drei → das Werkzeug
  erzeugt nur die ICS-Datei und sagt im `hinweis`, dass kein Kalender
  konfiguriert ist. Kein Fehler, keine Ueberraschung.
- Push per HTTP `PUT <CALDAV_URL><uid>.ics` (urllib, Basic-Auth,
  `Content-Type: text/calendar`, Timeout 20 s, If-None-Match: * gegen
  stilles Ueberschreiben eines fremden Eintrags). 201/204 = eingetragen;
  alles andere → sprechender Fehlertext in der Rueckgabe (`kalender`:
  eingetragen/fehlgeschlagen+Grund), die ICS-Datei entsteht TROTZDEM.
- MESSEN ZUERST: die exakte Kollektions-URL beim ersten Live-Versuch per
  PROPFIND ermitteln bzw. dokumentieren, welche URL der Betreiber aus dem
  Panel kopieren muss (Thunderbird-Link im Anbieter-Dialog). Zugangsdaten
  nie in argv/Logs; Fehlerrumpf durch denselben Geheimnisfilter wie SMTP.
- Egress-Hinweis fuers Review: das ist ein NEUER ausgehender HTTP-Pfad —
  Ziel ausschliesslich die konfigurierte CALDAV_URL aus `.env`
  (Betreiber-Konfiguration, kein Fremddaten-Ziel; KEINE URL aus
  Lead-/Kundendaten). Kein Bezug zu drafts/Freigabe: ein Kalendereintrag
  ist Selbstorganisation des Betreibers, keine Kundenkommunikation.
- Tests: Stub-HTTP-Server (Muster vorhanden), unkonfiguriert→nur Datei,
  201→eingetragen, 401/5xx→Fehlertext + Datei bleibt, Geheimnis nie im
  Fehlertext.

### G2 — E-Mail-Versand (`sales-mcp/mail_dispatch.py` + Compose-Dienst `sales-mail`)

Der Zwilling des WhatsApp-Dispatchers, gleiche Konstruktion:

- Liest AUSSCHLIESSLICH `drafts(status='approved', channel='email')`,
  atomarer Claim wie dispatch.py (approved→failed-Marke→sent). Die
  Claim-/Buchungs-Helfer aus `dispatch.py` IMPORTIEREN statt kopieren
  (`import dispatch` — kein Zirkel: mail_dispatch→dispatch→server), wo die
  Signaturen es hergeben; wo sie WhatsApp-spezifisch sind (Nummern),
  eigene schlanke Varianten mit derselben Semantik. Empfängerprüfung:
  `drafts.recipient` muss wie eine E-Mail aussehen (genau ein `@`, keine
  Leerzeichen, ≤254 Zeichen, Domain mit Punkt) — sonst `failed` mit
  sprechendem Grund, wie unzustellbare Nummern.
- Versand per `smtplib` + STARTTLS. Konfiguration aus `.env`:
  `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORT`,
  `EMAIL_ABSENDER`. `subject` aus `drafts.subject`, Fallback
  „Nachricht von unserem Haus"; Rumpf = `drafts.body` als text/plain
  (UTF-8). KEINE Anhänge in v1 (dokumentieren; media_ref bei email wird
  wie bisher als Merkposten ignoriert — im Code kommentieren).
- **Ohne Konfiguration bleibt der Dienst stumm:** fehlt `SMTP_HOST` o. ä.,
  beendet er sich beim Start mit klarer Meldung (Exit 0, restart "no" —
  gleicher Demo-Modus wie alle Dienste). So ist der Kanal gebaut und
  getestet, aber inert, bis der Betreiber Zugangsdaten einträgt
  (`.env.example` + Runbook: GMX = mail.gmx.net:587, App-Passwort nötig —
  BETREIBER-AKTION, niemals selbst Zugangsdaten erfinden).
- Compose: Dienst `sales-mail` (gleiches Image, `command: python
  mail_dispatch.py`, restart "no", env_file .env, stop_grace_period 45s,
  Logging wie die anderen). SMTP-Passwort nie in argv/Logs; Fehlertexte
  über einen `_ohne_geheimnis`-Filter (SMTP-Antworten können den Login
  spiegeln — gleiche Klasse wie `_ohne_token`).
- Tests: SMTP-Stub (lokaler `smtpd`-Ersatz — `aiosmtpd` ist NICHT
  installiert, also eigener Mini-SMTP-Stub auf socketserver-Basis ODER
  smtplib gegen einen Thread-Server; messen, was die Standardbibliothek
  im Container hergibt), Claim-Semantik (nur approved+email, WhatsApp
  bleibt liegen), Empfängerprüfung, Fehlerbuchung, unkonfiguriert→sauberer
  Exit. Dispatcher-Tests von WhatsApp dürfen nicht brechen.
- `entwuerfe_offen`: prüfen, wie `_zielangabe` email darstellt — der
  Betreiber muss vor der Freigabe die Zieladresse sehen (falls nicht:
  ergänzen, mit Test).

### G3 — Newsletter-/Marketing-Status (Konvention, kein Schema)

Kein neues Feld, keine neue Tabelle: `profil_aktualisieren(lead_id,
'newsletter', 'ja'|'nein')` ist der Weg (existiert). Zu bauen ist nur:

- AGENTS.md: Abschnitt-Ergänzung — auf Kundenwunsch („tragen Sie mich
  aus") SOFORT setzen und bestätigen; NIE ungefragt auf 'ja'; der Status
  ist von `consent_status` GETRENNT (consent = WhatsApp-Ansprache
  überhaupt, newsletter = Marketing-Verteiler).
- docs/03: drei Sätze dazu.

### G4 — Doku, Zähler, Abnahme

- Zähler-Tests RELATIV +1 (`termin_bestaetigen` → 28; `sales-mail` ist
  KEIN MCP-Werkzeug).
- AGENTS.md: „Termine": nach mündlicher Einigung `termin_bestaetigen`
  aufrufen, Bestätigungstext als Entwurf anbieten, auf die automatische
  Erinnerungs-Wiedervorlage hinweisen. Deploy per compose cp + MD5.
- docs/03: Abschnitte „Termine & ICS" (inkl. Kopier-Weg reports→media
  fürs Mitsenden) und „E-Mail-Versand einrichten" (Betreiber-Aktion,
  GMX-Hinweis). docs/02: kurzer Architektur-Absatz sales-mail =
  Dispatcher-Zwilling.
- Live-Abnahme: `termin_bestaetigen` einmal gegen sales_test — Datei
  entsteht, Inhalt RFC-konform (Assertions); E-Mail NUR Stub (keine
  Zugangsdaten vorhanden — nichts erfinden). GESAMTE Suite grün.

## Reihenfolge

G1→G4 in EINEM Task (ein Umsetzer, opus), Review danach. Start erst,
wenn der Container-Claim der nav-Session frei ist (Board).
