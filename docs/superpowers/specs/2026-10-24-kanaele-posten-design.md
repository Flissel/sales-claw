# Beiträge auf weitere Kanäle: Bluesky, Mastodon, Telegram-Kanal, Discord, dev.to

Stand: 24.10.2026. Betrifft vor allem sales-claw (`sales-mcp/`, `db/provision.sql`, `docker-compose.yml`, `deploy/`), dazu kleine Änderungen in vibemind-os (`spaces/marketing`).

## Absicht

VibeMind bekommt eigene Kanäle. Die Setup-Prompts liegen in `C:\Users\User\Desktop\VibeMind-Kanaele-Prompts.md`, eingerichtet werden die Kanäle vom Betreiber. Bisher kann sales-claw nur auf das eigene LinkedIn-Profil posten. Der Betreiber will, dass Sales-Beiträge auch auf den neuen Kanälen erscheinen, und dass alles bereitsteht, bevor er die Zugänge einträgt („du machst alles für die Kanäle bereit“).

sales-claw bleibt der einzige Versandweg (Betreiberentscheid vom 12.09.). Marketing liefert Inhalte, versendet aber nichts.

## Ziele

1. **Fünf neue Kanäle für eigene Beiträge** (ohne Empfänger, wie heute der LinkedIn-Post):
   - Bluesky
   - Mastodon
   - Telegram-Kanal
   - Discord (Ankündigungskanal per Webhook)
   - dev.to (Artikel, zunächst als Entwurf bei dev.to)
2. **Gleicher Ablauf wie bei LinkedIn:**
   - Entwurf → Freigabe in `/freigaben` → Versand durch einen Dienst.
   - Höchstens einmal zugestellt, kein automatischer Neuversuch bei ungewissem Ausgang.
   - Beleg in `activities`, Kadenz je Kanal.
3. **Ein Beitrag, mehrere Kanäle:** Der Agent schreibt aus einem Thema (oder aus einem Reel bzw. Newsletter) je Kanal eine passende Fassung mit Längengrenze, Ton und Hashtags. Für jeden Kanal entsteht ein eigener Entwurf, der einzeln freigegeben wird.
4. **„Noch nicht verbunden“ statt Fehler:**
   - Ohne Zugangsdaten für einen Kanal gibt es dafür keine Entwürfe.
   - Eine Seite zeigt je Kanal, ob er verbunden ist. Sie zeigt nur verbunden ja/nein, nie die Werte.
5. **Zugangsdaten sicher eintragen:** Ein Skript auf der VM fragt die Werte verdeckt ab und schreibt sie in `~/sales-claw/.env`. Sie erscheinen nie im Chat, im Log oder in einer Ausgabe.

## Nicht-Ziele

- Instagram, Threads, YouTube, X, TikTok und LinkedIn-Unternehmensseite. Sie folgen, sobald die Freigaben der Anbieter da sind. Die Bauweise (Adapter je Kanal) soll sie aber ohne Umbau aufnehmen.
- Kein automatisches Posten ohne Freigabe, kein Zeitplan-Posten (Kampagnenplan-Kopplung später).
- Kein Umbau des LinkedIn-Wegs. Er bleibt, wie er ist.
- Kein Wiederbeleben des alten, gesperrten Marketing-Versandwegs (`broadcast_proposals`, `channel_config`).

## Anti-Ziele

- Ein Beitrag geht ohne Freigabe raus, oder ein Beitrag geht doppelt raus.
- Ein Zugangsschlüssel steht in einem Log, einer Fehlermeldung, im Chat oder im Repo.
- Ein Kanal ohne Zugangsdaten bricht die Freigaben-Seite oder andere Kanäle.
- Ein Kanal-Ausfall (Anbieter down) hält die anderen Kanäle auf.

## Ausgangslage (gemessen)

- LinkedIn-Weg: `post_entwurf_erstellen` legt `drafts` mit `channel='linkedin'`, `recipient='eigenes-profil'` an. `linkedin_dispatch.py` ist ein Dauerdienst mit Claim → Medien → Beitrag, Beleg vor Buchung, höchstens ein Beitrag pro Tag und Frischegrenze 7 Tage. Fehler werden als `dauerhaft` oder `ungewiss` eingeordnet.
- Es gibt keine Kanal-Registry. Jeder Kanal hat einen eigenen Dispatcher. Gemeinsam nutzen sie nur `_claim_marke`, `_als_gesendet_buchen` und `_als_fehler_buchen` aus `dispatch.py`.
- Neue Kanäle müssen an mehreren fest verdrahteten Stellen nachgetragen werden:
  - CHECK `drafts_channel_check` (provision.sql, per drop+add)
  - `server.entwurf_erstellen`, `historie._KANAL`
  - `ui.FREIGABE_ARTEN`, `_ZEILE_KANAELE`, Badge-CSS
  - `lead_fluss.POST_KANAL`
  - `update.sh` `KERN_ALLE`, `smoke.sh`
  - auf der Marketing-Seite CHECK 043 und `VERSANDKANAELE`
- Geheimnisse kommen per Compose-Interpolation aus `~/sales-claw/.env` bzw. `deploy/laeden/<laden>.env`. Den OpenFang-Tresor nutzt sales-claw nicht. Die Setup-Prompts sagen bisher „im OpenFang-Tresor speichern“. Das wird auf das neue Eintrage-Skript umgestellt (siehe unten).

## Entwurf (meine Wahl, für den Builder verbindlich)

**Kanalwerte in `drafts.channel`:** `bluesky`, `mastodon`, `telegram_kanal`, `discord`, `devto`. Für alle gilt `recipient='eigenes-profil'`, analog LinkedIn: kein Empfänger, eigener Kanal. `telegram_kanal` ist bewusst getrennt vom bestehenden `telegram` (Direktnachrichten).

**Ein Dienst für alle neuen Kanäle:** `sales-kanaele` mit `kanal_dispatch.py`, einem Dauerdienst. Darin eine kleine Registry `KANAELE = {name: Adapter}`. Ein Adapter hat:
- `name`
- `env_namen` (Pflicht-Variablen)
- `verbunden() -> bool`
- `max_zeichen`
- `medien` (erlaubte Typen und Anzahl)
- `kadenz_pro_tag`
- `senden(text, medien, titel) -> beleg` (`beleg` = URL oder ID des Beitrags)

Fehler werden wie bei LinkedIn eingeordnet:
- `KanalFehler(dauerhaft|ungewiss)`
- `ungewiss` sperrt jede Wiederholung.

Claim, Beleg und Buchung kommen aus `dispatch.py`, wie bei `linkedin_dispatch.py`. Die Runde läuft je Kanal getrennt. Eine Ausnahme in einem Adapter wird für diesen Kanal gebucht und hält die anderen nicht auf.

**Adapter (Bibliotheken nur, wenn schlank; sonst `urllib`):**

| Kanal | Zugang (Env) | Grenze | Medien | Kadenz/Tag |
|---|---|---|---|---|
| bluesky | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | 300 Zeichen | bis 4 Bilder | 3 |
| mastodon | `MASTODON_INSTANCE`, `MASTODON_TOKEN` | 500 Zeichen | bis 4 Bilder oder 1 Video | 3 |
| telegram_kanal | `TELEGRAM_KANAL_ID`, `TELEGRAM_KANAL_BOT_TOKEN` | 4096 Text, 1024 als Bildunterschrift | 1 Bild oder 1 Video | 3 |
| discord | `DISCORD_ANKUENDIGUNG_WEBHOOK` | 2000 Zeichen | 1 Bild oder Video als Anhang | 3 |
| devto | `DEVTO_API_KEY` | Artikel (Titel + Markdown) | Titelbild nur als URL, sonst ohne | 1 |

Bei dev.to legt der Versand den Artikel nur als **Entwurf bei dev.to** an (`published: false`). Veröffentlicht wird dort von Hand. Der Grund: Ein öffentlicher Artikel ist schwer zurückzunehmen, und die API kann ihn nicht wirklich löschen.

**Entwürfe anlegen:**
- Neues MCP-Werkzeug `kanal_post_entwurf(kanal, text, titel?, medien_dateien?, trotzdem?)`. Es prüft Kanal, Längen- und Mediengrenze, `verbunden()` (sonst klare Ablehnung „Kanal X ist noch nicht verbunden“) und Doppel-Thema wie bei LinkedIn.
- Neuer Skill `config/workspace/skills/kanal-post/SKILL.md`. Er führt Kanalwahl, je Kanal eine eigene Fassung mit passender Länge, Ton und Hashtags (Bluesky/Mastodon mit Hashtags, Discord und Telegram ohne), wortgleiche Vorschau aller Fassungen und das Anlegen erst nach Ok. Er nennt den bestehenden `linkedin-post`-Skill für LinkedIn.
- **Reels-Seite:** Neben „Als LinkedIn-Post vorbereiten“ kommt „Auf Kanälen teilen“. Das legt je verbundenem Kanal mit passenden Medien einen Entwurf an. Text: Reel-Titel plus Link, gekürzt auf die Grenze.
- **Marketing:** `versand_beauftragen` und der CHECK in 043 bekommen die neuen Kanalwerte (Migration mit nächster freier Nummer). `versandauftrag_uebernehmen` in sales-claw ruft für sie `kanal_post_entwurf` auf.

**Freigabe:**
- `FREIGABE_ARTEN` um die fünf Kanäle (Namen deutsch: Bluesky, Mastodon, Telegram-Kanal, Discord, dev.to), Badges und Verlauf.
- Freigegeben heißt veröffentlichen. Bei dev.to steht der Hinweis „wird als Entwurf bei dev.to angelegt“.
- Kein Direkt-Freigeben in der Zeile.

**Kanal-Status:** Neue Seite `/einstellungen/kanaele` (Admin) mit einer Tabelle je Kanal:
- verbunden ja/nein (nur ob die Env-Namen gesetzt sind)
- letzter Beitrag mit Link (aus `activities`)
- Kadenz und Grenze
- bei „nein“ die nötigen Env-Namen und der Hinweis aufs Eintrage-Skript

**Zugangsdaten eintragen:** `deploy/kanal-zugang-eintragen.sh <kanal>`:
- fragt die Env-Namen des Kanals per `read -s` ab (verdeckt)
- schreibt bzw. ersetzt sie in `~/sales-claw/.env` (Rechte 600, vorher Sicherung `.env.vor-<kanal>-<zeit>`, die Sicherung ebenfalls 600)
- startet nur `sales-kanaele` neu
- gibt nie einen Wert aus, auch nicht gekürzt

`.env.example` und `docs/10_SECRETS_ROTATION.md` nennen die neuen Namen. Die Setup-Prompts in der Desktop-Datei werden angepasst: statt „im OpenFang-Tresor speichern“ heißt es „im Passwort-Manager notieren und mit dem Eintrage-Skript auf die VM bringen“.

**Compose:** Dienst `sales-kanaele`. Er bekommt nur `SALES_DB_URL`, die Kanal-Variablen (alle mit leerer Vorgabe `${VAR:-}`, damit fehlende Kanäle nicht blockieren), die Medienordner nur lesend, `TZ` und die Mindestrechte wie `sales-linkedin`. Eintrag in `update.sh` `KERN_ALLE` und in `smoke.sh` (der Dienst läuft, Kanäle ohne Zugang gelten nicht als Fehler).

**Datenbank:** `drafts_channel_check` per drop+add um die fünf Werte erweitern (provision.sql, idempotent). `historie._KANAL` und `lead_fluss.POST_KANAL` werden ergänzt.

**Läden:** Gilt zunächst für den Haupt-Laden (VibeMind, `~/sales-claw/.env`). Für andere Läden (Ivan) gibt es keine Kanäle, solange ihre Env-Datei keine Zugänge hat. Das ergibt sich von selbst über `verbunden()`.

## Abnahme

- Ohne Zugangsdaten:
  - `/einstellungen/kanaele` zeigt alle fünf als „nicht verbunden“.
  - Das Werkzeug lehnt mit klarer Meldung ab.
  - Die Freigaben-Seite und der LinkedIn-Weg laufen unverändert.
  - Smoke ist grün.
- Mit Test-Zugang: Ein Kanal, den der Betreiber zuerst einrichtet (Bluesky oder Mastodon), bekommt einen Probe-Beitrag mit dem Text „Test – bitte ignorieren“. Ablauf: anlegen → freigeben → erscheint → Beleg-Link in Verlauf und Statusseite → Beitrag von Hand gelöscht. Erst nach seinem Ok.
- Unit-Tests je Adapter gegen gefälschte HTTP-Antworten:
  - Erfolg, 4xx dauerhaft, Timeout ungewiss
  - kein Schlüssel im Fehlertext
- Doppelversand ist durch Claim und Beleg ausgeschlossen (Test).

## Dem Builder überlassen

- Genaue Texte in UI und Skill.
- Bluesky-Medien-Upload (blob) und Mastodon-Medien-Upload im Detail.
- Reihenfolge der Tasks.

## Präzisierungen nach Builder-Check (meine Wahl, verbindlich)

1. **„Verbunden“ ohne Geheimnisse in anderen Diensten:** Nur `sales-kanaele` kennt die Zugänge. Er schreibt bei Start und in jeder Runde je Kanal eine Zeile in die neue Tabelle `kanal_status(kanal text primary key, verbunden boolean, geprueft_am timestamptz, letzter_fehler text)` (provision.sql, je Laden-Schema wie `drafts`). `letzter_fehler` ist ohne Werte und Kopfzeilen. `kanal_post_entwurf` und `/einstellungen/kanaele` lesen nur diese Tabelle. Fehlt eine Zeile, gilt der Kanal als „nicht verbunden“. Das Eintrage-Skript startet deshalb nur `sales-kanaele` neu.
2. **Sammelkontakt:** Alle neuen Kanäle hängen am bestehenden Sammelkontakt `LINKEDIN_POST_LEAD_ID` („eigene Beiträge“). Es gibt keine neue Env-Variable. Kadenz und „letzter Beitrag“ zählen über `activities.type='versand'` mit `payload.kanal`.
3. **Frischegrenze und Kadenz wie LinkedIn:** Freigaben, die älter als 7 Tage sind, bleiben liegen (Hinweis in der Freigabe). Die Kadenz zählt Kalendertage in DB-Zeit über `versand`-Belege, auch `ungewiss`.
4. **Claim je Kanalwert:** Je Kanal gibt es ein eigenes Claim-SQL mit `channel=<wert> AND recipient='eigenes-profil'` als Sicherheitskante. Importiert werden nur `_claim_marke`, `_als_gesendet_buchen` und `_als_fehler_buchen` aus `dispatch.py`. `bereits_veroeffentlicht` gilt je Kanal wie bei LinkedIn.
5. **Nur der Haupt-Laden:** `sales-kanaele` läuft nur im Compose-Projekt des Haupt-Ladens (VibeMind), nicht in `deploy/laeden/*.env`. Die Läden-Schleife in `update.sh` startet ihn nicht. Der CHECK und die Tabelle `kanal_status` kommen trotzdem in alle Schemas, damit der Code einheitlich bleibt.
6. **Auftragskanäle im Marketing:** `bluesky_post`, `mastodon_post`, `telegram_kanal_post`, `discord_post`, `devto_post`. `lead_fluss.POST_KANAL` wird zu einer Zuordnung `{auftragskanal: drafts-kanal}`. Die Marketing-Migration bekommt die nächste freie Nummer (heute 092, vorher prüfen).
7. **Betreff und Doppel-Thema:** Der Betreff ist `Post: <thema>`, bei dev.to der Artikeltitel. `drafts.thema` = Thema. Die Doppel-Prüfung gilt je Kanal.
8. **Medien:** dev.to zunächst ohne Titelbild, weil Bilder nur als öffentliche URL gehen. Bluesky und Mastodon bekommen leeren Alt-Text, bis es ein Alt-Text-Feld gibt.
9. **Dauerdienst ohne Zugänge:** `sales-kanaele` läuft auch ohne jeden Zugang weiter. Er meldet dann alle Kanäle als „nicht verbunden“ und beendet sich nicht.
10. **Beleg:** `activities.payload` enthält `{draft_id, kanal, weg:'kanal-dispatcher', empfaenger:'eigenes-profil', beitrag:<id>, url:<öffentliche URL>, medienart}`. Die Statusseite verlinkt `url`.

## Nachtrag 25.10.2026: YouTube-Shorts als sechster Kanal

- **Kanalwert** `youtube` (CHECK in `provision.sql`), `recipient='eigenes-profil'` wie die übrigen.
- **Zugang:** `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` und `YOUTUBE_CHANNEL_ID` (Kanal VibeMind @vibemindos). Geheim sind Secret und Refresh-Token. Den Refresh-Token erzeugt am PC einmalig `scripts\youtube-oauth.cmd` (Vibemind_V1, Desktop-OAuth, Rechte `youtube.upload` und `youtube.readonly`). Das Skript gibt die Werte nur an `kanal-zugang` weiter, nie an argv, Log oder Chat.
- **Beitrag:** genau ein Video, Titel Pflicht (höchstens 100 Zeichen, = Betreff wie bei dev.to), Text = Beschreibung (5000). `<` und `>` werden durch `‹ ›` ersetzt, weil YouTube sie ablehnt. Kadenz 2 pro Tag (Kontingent: ein Upload kostet viel).
- **Short-Prüfung im Adapter** an den MP4-Eckdaten (moov/mvhd, tkhd): höchstens 180 s, nicht quer. Sonst dauerhaft abgelehnt, nichts hochgeladen.
- **Ablauf:** Token per Refresh-Token, dann `channels?mine=true` (gehört der Zugang zu `YOUTUBE_CHANNEL_ID`? Sonst Abbruch ohne Upload), dann resumable Upload starten (`videos.insert`) und das Video in einem PUT hochladen. Nur der PUT veröffentlicht. Er ist bei fehlender Antwort `ungewiss`, alles davor ist `dauerhaft`. YouTube kennt keinen Idempotenzschlüssel, die Sperre gegen Doppel liegt allein im Dienst.
- **Sichtbarkeit:** `YOUTUBE_SICHTBARKEIT` (nur `sales-kanaele`, kein Geheimnis), `private` (Vorgabe), `unlisted` oder `public`. Ein leerer oder unbekannter Wert ergibt `private`. Hinweis: Google hält Uploads aus ungeprüften API-Projekten ohnehin privat, bis das Projekt das YouTube-API-Audit bestanden hat. `containsSyntheticMedia=true` (die Reels sprechen mit KI-Stimme), `selfDeclaredMadeForKids=false`.
- **Reels teilen:** Der Knopf „Auf Kanälen teilen“ gibt YouTube das Thema als Titel (gekürzt auf 100).
- **Nicht enthalten:** Auftragskanal `youtube_post` im Marketing (bräuchte eine Marketing-Migration). Bis dahin entstehen YouTube-Entwürfe über das Werkzeug oder die Reels-Seite.
