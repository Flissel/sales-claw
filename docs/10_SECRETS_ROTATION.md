# 10 — Secrets: Inventar und Rotation (F6)

Alle Geheimnisse leben in EINER Datei: `~/sales-claw/.env` auf der VM
(niemals in Git, niemals in Logs oder Kommandozeilen). Drei Dienste erben
die komplette Datei (`sales-mcp`, `sales-dispatch`, `sales-inbox` — die
Vertrauensdomäne), alle anderen bekommen nur namentlich verdrahtete
Schlüssel (T5a, siehe docker-compose.yml).

## Das Verfahren (immer gleich)

1. Neuen Wert beim Anbieter erzeugen (alten noch NICHT löschen).
2. Auf der VM `.env` editieren (`nano ~/sales-claw/.env`).
3. Betroffene Dienste neu aufsetzen — `restart` genügt NICHT, erst
   `up -d` liest die Umgebung neu:
   `cd ~/sales-claw && docker compose up -d <dienste>`
4. Abnahme: `bash ~/sales-claw/deploy/smoke.sh` — alles grün?
5. Erst jetzt den alten Wert beim Anbieter widerrufen.

Anlässe: konkreter Verdacht (sofort), Offboarding eines Menschen mit
Zugang (sofort), sonst jährlich. Nach jeder Rotation eine Zeile ins
private Betriebsprotokoll: Datum, Schlüssel, Anlass — ohne Werte.

## Inventar (Stand 31.08.2026)

| Schlüssel | Wozu / wo rotieren | Nach der Rotation neu aufsetzen |
|---|---|---|
| `SALES_DB_URL` | Kundendaten-DB (Passwort der DB-Rolle `sales_app`; ändern per `alter role` im DB-Container) | alle Kerndienste: `sales-mcp sales-dispatch sales-inbox sales-mail sales-ui sales-linkedin sales-kanaele` |
| `OPENROUTER_API_KEY` | Sprachmodell des Agenten — openrouter.ai | `sales-claw` |
| `OPENWA_API_KEY` | WhatsApp-Server-API (sendefähig!) — Wert selbst erzeugen, steht auch in der OpenWA-Konfiguration | `openwa` und Vertrauensdomäne + `sales-linkedin` |
| `OPENWA_VIEWER_KEY` | Nur-Lese-Schlüssel der /whatsapp-Seite | `openwa sales-ui` |
| `INBOX_WEBHOOK_SECRET` | OpenWA→Inbox-Webhook | `openwa sales-inbox` |
| `SMTP_USER` / `SMTP_PASSWORT` | E-Mail-Versand — beim Mail-Anbieter (GMX) | `sales-mail` und Vertrauensdomäne |
| `CALDAV_USER` / `CALDAV_PASSWORT` | Kalender — beim Kalender-Anbieter | Vertrauensdomäne |
| `APIFY_TOKEN` | Recherche — apify.com | Vertrauensdomäne |
| `LINKEDIN_CLIENT_ID` / `_CLIENT_SECRET` / `_ACCESS_TOKEN` | LinkedIn-App — developer.linkedin.com (Token läuft ohnehin ab; Erneuerungs-Ablauf in docs/05_LINKEDIN…) | `sales-linkedin` und Vertrauensdomäne |
| `UI_SESSION_SECRET` | Signatur der UI-Sitzungen — Rotation wirft ALLE angemeldeten Benutzer raus (gewollt bei Verdacht); neuen Wert erzeugt `deploy/benutzer-anlegen.sh`-Muster: `docker exec sales-mcp python -c 'import secrets; print(secrets.token_urlsafe(32))'` | `sales-ui` |
| `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` | Bluesky — App-Passwort unter bsky.app → Einstellungen → Datenschutz und Sicherheit → App-Passwörter. Rotation = neues App-Passwort erzeugen, am PC `kanal-zugang speichern bluesky` erneut, altes widerrufen | `sales-kanaele` (macht das Skript) |
| `MASTODON_INSTANCE` / `MASTODON_TOKEN` | Mastodon — auf der eigenen Instanz unter Einstellungen → Entwicklung → Neue Anwendung (Recht `write:statuses`, `write:media`). Rotation = Zugangstoken neu erzeugen, am PC `kanal-zugang speichern mastodon` erneut | `sales-kanaele` (macht das Skript) |
| `TELEGRAM_KANAL_ID` / `TELEGRAM_KANAL_BOT_TOKEN` | Telegram-Kanal — Bot bei @BotFather, als Admin mit Posting-Recht in den Kanal. Rotation = `/revoke` bei @BotFather, am PC `kanal-zugang speichern telegram_kanal` erneut | `sales-kanaele` (macht das Skript) |
| `DISCORD_ANKUENDIGUNG_WEBHOOK` | Discord — Servereinstellungen → Integrationen → Webhooks (die URL selbst ist das Geheimnis). Rotation = Webhook löschen, neu anlegen, am PC `kanal-zugang speichern discord` erneut | `sales-kanaele` (macht das Skript) |
| `DEVTO_API_KEY` | dev.to — Settings → Extensions → DEV Community API Keys. Rotation = neuen Schlüssel erzeugen, am PC `kanal-zugang speichern devto` erneut, alten widerrufen | `sales-kanaele` (macht das Skript) |
| `OPENAI_API_KEY` / `LLM_9ROUTER_API_KEY` | in der `.env` vorhanden, im Compose NICHT verdrahtet — Kandidaten zum ENTFERNEN statt Rotieren (erst prüfen, ob die OpenClaw-Konfiguration im Volume sie nutzt) | — |

Kein Geheimnis (nur Konfiguration): `TZ`, `SMTP_HOST/PORT`,
`EMAIL_ABSENDER`, `CALDAV_URL`, `UI_TAILSCALE_IP`, `OPENWA_SESSION_ID`,
`LINKEDIN_PERSON_URN`, `INBOX_UNBEKANNT_LEAD_ID`, `RECHERCHE_LEAD_ID`,
`LINKEDIN_POST_LEAD_ID`, `BLUESKY_PDS`. Handle, Instanz und Kanal-ID
(`BLUESKY_HANDLE`, `MASTODON_INSTANCE`, `TELEGRAM_KANAL_ID`) sind keine
Geheimnisse. Als Zugangswert erscheinen sie nie in UI oder Log (auch nicht
in Fehlertexten, die nennen nur den Namen). Ausnahme mit Absicht: die
öffentlichen Beleg-URLs der Beiträge (`https://bsky.app/profile/<handle>/…`,
die Mastodon-URL auf der Instanz, `https://t.me/<name>/…`) stehen im Verlauf
von `/freigaben` und auf der Statusseite `/einstellungen/kanaele` und
verraten damit Handle, Instanz bzw. Kanalnamen.

Eigene Kanäle (24.10.2026) weichen von Schritt 2–3 des Verfahrens ab. Die
Wahrheit ist der OpenFang-Tresor am PC (Referenzen `KANAL_<ENV-NAME>`), die
VM hält nur eine Kopie, damit sie auch bei ausgeschaltetem PC postet:

- Neu oder Rotation: am PC `kanal-zugang speichern <kanal>` (Vibemind_V1,
  `scripts/kanal-zugang.cmd`) — fragt verdeckt, speichert im Tresor und
  gleicht gleich ab.
- Nur abgleichen: `kanal-zugang abgleichen <kanal>` oder `--alle`.
- Der Abgleich reicht die Werte per ssh-stdin an
  `bash ~/sales-claw/deploy/kanal-zugang-eintragen.sh <kanal>` — das liest
  verdeckt, legt `.env.vor-<kanal>-<Zeitstempel>` (600) an und erzeugt nur
  `sales-kanaele` neu. Welche Namen ein Kanal braucht, liefert
  `kanal-zugang-eintragen.sh --namen <kanal>`.
- Notweg (PC aus): das Skript auf der VM von Hand aufrufen, danach den Wert
  am PC im Tresor speichern — sonst überschreibt der nächste Abgleich ihn.

Abnahme: `/einstellungen/kanaele`.

## Ausserhalb der .env

- **SSH-Schlüssel** (PC → VM, `sicherung-spiegel` VM → pve): Rotation =
  neues Schlüsselpaar, `authorized_keys` tauschen, alten Eintrag löschen.
- **Deploy-Key** (GitHub, nur Lesen): im Repo unter Settings → Deploy
  keys tauschen; auf der VM `~/.ssh` nachziehen.
- **Tailscale**: Geräte-Schlüssel rotieren sich selbst; ein verlorenes
  Gerät im Admin (login.tailscale.com) entfernen.
- **WhatsApp-Kopplungen** (openwa-Volume): kein Schlüssel im Sinne dieser
  Liste — Entkoppeln geht am Telefon (Verknüpfte Geräte).

## Ausbaustufe (bewusst offen)

Verschlüsselte Ablage der `.env` (sops/age) lohnt, sobald mehr als ein
Mensch die VM administriert. Bis dahin gilt: eine Datei, ein Rechner,
Dateirechte 600, Sicherungen enthalten die `.env` NICHT.
