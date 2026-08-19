# 08 — QR-Pairing-Anleitung für OpenWA

Eine einzige, nicht-automatisierbare Aktion trennt den Stack vom
tatsächlichen WhatsApp-Versand: das Koppeln der dedizierten `sales`-Nummer
mit OpenWA per QR-Code. Diese Anleitung ist für den Betreiber, dauert rund
zwei Minuten und ist der einzige nicht-autonome Schritt im gesamten
Stufe-3-Vorhaben (`docs/superpowers/plans/2026-08-18-sales-claw-stufe3-versand.md`).

**Stand zum Zeitpunkt dieser Doku: noch nicht ausgeführt.** Jeder bisher
belegte End-zu-End-Test endete erwartungsgemäß mit `OpenWA HTTP 409:
Session is not connected. The WhatsApp client is not ready.` bzw.
`status='failed'` in `drafts` — das ungepairte Gateway ist der getestete,
dokumentierte Normalzustand (Grundsatzentscheidung 2,
`docs/02_ARCHITECTURE.md`). Es wurde bislang **keine** Nachricht tatsächlich
zugestellt. Diese Anleitung ändert das erst, wenn sie tatsächlich
durchgeführt wird.

## 1. Dedizierte Nummer bereithalten

**Niemals die persönliche Nummer des Betreibers.** Diese Regel ist bindend
(Stufe-3-Plan, Grundsatzentscheidung 2) und aus gutem Grund: Die persönliche
Nummer hängt bereits an `sales-claw` (bzw. der lokalen OpenClaw-Installation)
als Baileys-Session. Meldet sich eine zweite WhatsApp-Web-Sitzung mit
denselben Credentials an, wertet WhatsApp das als Sitzungskonflikt und
**meldet das zuerst verknüpfte Gerät ab** — die bestehende Kopplung wäre weg
und nur durch erneutes QR-Pairing am gekoppelten Telefon wiederherstellbar
(`docs/05_DISASTER_RECOVERY.md`, Fall 1). OpenWA braucht eine eigene, allein
für den Vertriebs-Versand vorgesehene Nummer — vor diesem Schritt bereitlegen
(SIM oder eine für WhatsApp nutzbare Nummer, auf einem Telefon, mit dem sich
scannen lässt).

## 2. OpenWA starten, falls aus

```powershell
docker compose -f docker-compose.openwa.yml up -d --build
docker compose -f docker-compose.openwa.yml ps
# erwartet: openwa   Up ... (healthy)
```

Details und die `--remove-orphans`-Warnung: `docs/03_RUNBOOK.md`, Abschnitt
„Stufe 3: Versand mit Approval".

## 3. QR-Code neu ziehen

Die Session `sales` existiert bereits (angelegt in Task 1). Ihre ID steht in
`.env` als `OPENWA_SESSION_ID` (keine geheime, aber nicht öffentlich zu
verbreitende Information), der API-Key als `OPENWA_API_KEY`. Beide werden
unten **nur als Umgebungsvariable durchgereicht, nie angezeigt** — dasselbe
Muster wie bei der Datenbank-DSN in `docs/03_RUNBOOK.md`.

```powershell
$env:OPENWA_KEY = ((Select-String -Path .env -Pattern '^OPENWA_API_KEY=').Line -split '=', 2)[1]
$env:OPENWA_SESSION = ((Select-String -Path .env -Pattern '^OPENWA_SESSION_ID=').Line -split '=', 2)[1]

$antwort = Invoke-RestMethod -Uri "http://127.0.0.1:2785/api/sessions/$($env:OPENWA_SESSION)/qr" `
    -Headers @{ "X-API-Key" = $env:OPENWA_KEY }
$b64 = $antwort.qrCode -replace '^data:image/png;base64,', ''
[IO.File]::WriteAllBytes("$PWD\openwa-qr.png", [Convert]::FromBase64String($b64))

Remove-Item Env:OPENWA_KEY, Env:OPENWA_SESSION
```

Ergebnis: `openwa-qr.png` im Repo-Wurzelverzeichnis (gitignoriert), der
aktuelle QR-Code der Session. Die API liefert den Code als
`data:image/png;base64,…` (`GET /api/sessions/{id}/qr`, Feld `qrCode`); der
Block oben dekodiert genau das und schreibt eine PNG-Datei.

**Alternative (curl, z. B. unter WSL/Git-Bash mit `jq`):**

```bash
export OPENWA_KEY=$(grep '^OPENWA_API_KEY=' .env | cut -d= -f2-)
export OPENWA_SESSION=$(grep '^OPENWA_SESSION_ID=' .env | cut -d= -f2-)
curl -s -H "X-API-Key: $OPENWA_KEY" \
  "http://127.0.0.1:2785/api/sessions/$OPENWA_SESSION/qr" \
  | jq -r '.qrCode' | sed 's/^data:image\/png;base64,//' | base64 -d > openwa-qr.png
unset OPENWA_KEY OPENWA_SESSION
```

**Der QR-Code läuft nach wenigen Minuten ab.** Erscheint beim Scannen ein
Fehler oder reagiert nichts mehr, einfach den Block oben erneut ausführen —
das zieht einen frischen Code, ohne dass sonst irgendetwas nötig ist.

## 4. Mit WhatsApp scannen

Auf dem Telefon mit der **dedizierten** Nummer (Schritt 1):

WhatsApp → Einstellungen → **Verknüpfte Geräte** → **Gerät verknüpfen** →
`openwa-qr.png` scannen (die Datei am Bildschirm öffnen, z. B. mit dem
Standard-Bildbetrachter, und den Code vom Monitor abfotografieren lassen).

## 5. Prüfschritte

**a) Session-Status `ready`.** Wire-Werte laut OpenWA-API: `created |
initializing | qr_ready | authenticating | ready | disconnected |
action_required | failed`. Nach erfolgreichem Scan wird daraus `ready`:

```powershell
$env:OPENWA_KEY = ((Select-String -Path .env -Pattern '^OPENWA_API_KEY=').Line -split '=', 2)[1]
$env:OPENWA_SESSION = ((Select-String -Path .env -Pattern '^OPENWA_SESSION_ID=').Line -split '=', 2)[1]
(Invoke-RestMethod -Uri "http://127.0.0.1:2785/api/sessions/$($env:OPENWA_SESSION)" `
    -Headers @{ "X-API-Key" = $env:OPENWA_KEY }).status
# erwartet: ready
Remove-Item Env:OPENWA_KEY, Env:OPENWA_SESSION
```

**b) Ein freigegebener Test-Entwurf an die EIGENE dedizierte Nummer →
`sent`.** Über den Agenten (nicht per SQL): einen Testkontakt mit genau der
dedizierten Nummer anlegen (oder einen bestehenden mit
`kontakt_aktualisieren` korrigieren — Nummer mit Landesvorwahl, z. B.
`+49…`), einen WhatsApp-Entwurf erzeugen lassen, freigeben — Ablauf wie in
`docs/03_RUNBOOK.md`, Abschnitt „Freigabe-Ablauf (Betreibersicht)"
beschrieben. Danach:

```powershell
docker compose logs --tail 20 sales-dispatch
```

Erwartet: eine Logzeile `draft=… gesendet an …`, und `status='sent'` in
`drafts` (psql-Gegenprobe: `docs/03_RUNBOOK.md`, Abschnitt
„psql-Gegenproben für drafts"). **Erst nach diesem Nachweis gilt die
Kopplung als funktionsfähig demonstriert** — nicht schon am `ready`-Status
allein, und nicht am Ausbleiben eines Fehlers.

## 6. Warmup nicht überspringen

Die Nummer ist ab hier technisch einsatzbereit, aber **frisch**. Vor
echtem Vertriebsvolumen: `docs/03_RUNBOOK.md`, Abschnitt „Warmup-Regeln für
frische Nummern" — kurz zusammengefasst: erst ein bis zwei Wochen
menschlich wirkendes Verhalten (auch empfangen und antworten, nicht nur
senden), nicht am ersten Tag senden, wenige Nachrichten statt eines
Schwalls, keine identischen Textbausteine an viele Empfänger.

## 7. Bei Fehlschlag

| Beobachtung | Wahrscheinliche Ursache | Weiter mit |
|---|---|---|
| QR-Abruf liefert einen Fehler statt eines Codes | Session nicht im Zustand `qr_ready`, oder falsche/fehlende `OPENWA_SESSION_ID` | Session-Status prüfen (Schritt 5a); Session ggf. per `POST /api/sessions/{id}/start` neu starten |
| QR gescannt, aber Status bleibt `qr_ready`/`authenticating` | Code bereits abgelaufen (Schritt 3) | Neuen Code ziehen, zügig scannen |
| `401` beim Abruf | `OPENWA_API_KEY` in `.env` falsch oder leer | Vorhandensein/Länge prüfen, **nie den Wert ausgeben** (Muster wie im T1-Bericht: `bool()`/`len()` statt Klartext). Im Zweifel Key aus dem Volume neu prüfen: `docker exec openwa sh -lc 'wc -c < /app/data/.api-key'` gegen die Länge der `.env`-Zeile vergleichen |
| Nach erfolgreichem Pairing trotzdem `failed` beim Testversand | echter Fehlertext aus `drafts.error` lesen (`entwuerfe_offen` bzw. psql-Gegenprobe) — häufigste Ursache: Nummernformat ohne Landesvorwahl | Fehlertext wörtlich vorlesen lassen, dann gezielt beheben (Nummer mit `+`-Vorwahl über `kontakt_aktualisieren` korrigieren) statt zu raten; Nummern-Regeln: `docs/02_ARCHITECTURE.md` |
| Kopplung fällt nach einem Container-Neustart auf `qr_ready` zurück | bislang nicht beobachtet/getestet (Pairing steht ja noch aus) — bei Auftreten: prüfen, ob die Session-Dateien im Volume `openwa-data` den Neustart überstanden haben | ggf. neu koppeln (dieser Ablauf, ab Schritt 3) |

## Offene Punkte (ehrlich benannt)

- **QR-Pairing steht noch aus.** Der belegte Endzustand jedes bisherigen
  Tests ist `failed` an einem ungepairten Gateway — genau das ist der
  aktuelle, dokumentierte Stand. Diese Anleitung ist der einzige Weg, das
  zu ändern.
- **`bestaetigt=True` ist modellsetzbar.** Die Schutzkante gegen
  Doppelversand bei einem hängenden Claim (`entwurf_erneut_freigeben`,
  `docs/02_ARCHITECTURE.md`, Abschnitt „Claim-Mechanik") sitzt zwar in der
  Datenbank (WHERE-Klausel), aber der Parameter `bestaetigt=True` kann vom
  Agenten selbst gesetzt werden — es gibt keine zweite, modellunabhängige
  Bestätigungsstufe. Für den Prototyp akzeptiert (die dmPolicy-Allowlist
  lässt ohnehin nur den Betreiber an den Agenten heran). Manueller
  Alternativweg, falls dieses Risiko im Einzelfall vermieden werden soll —
  den Entwurf **ohne** den Agenten erneut freigeben, direkt per psql
  (DSN-Durchreichung wie in `docs/03_RUNBOOK.md` beschrieben, nie als Wert
  in einer sichtbaren Kommandozeile):
  ```sql
  update sales.drafts set status='approved', approved_by='betreiber',
    approved_at=now(), error=null
  where id='<draft_id>' and status='failed';
  ```
- **Kein Rate-Limit im Dispatcher selbst.** Nur eine 1-Sekunden-Pause
  zwischen zwei tatsächlichen Sendungen einer Runde
  (`DISPATCH_SENDE_PAUSE_S`), kein Tages- oder Stunden-Deckel auf unserer
  Seite. Für den Demo-Betrieb akzeptiert, vor echtem Volumenbetrieb
  ausbaufähig (`docs/03_RUNBOOK.md`, Abschnitt „Warmup-Regeln").
- **Fallback-Schwankung.** Primärmodell ist seit 19.08.2026
  `anthropic/claude-sonnet-5` (Abo-Token); nur wenn dessen Kontingent
  erschöpft ist, greift `openrouter/free` als Fallback
  (`docs/02_ARCHITECTURE.md`, Abschnitt „Modellanbieter"). Im
  Fallback-Fall schwanken Antwortzeiten und Regeltreue gemessen erheblich
  (34 s bis zu einem 600-s-Timeout in früheren Tasks). Bei
  Auffälligkeiten während der Prüfschritte oben: frischer Session-Key,
  wiederholen (`docs/03_RUNBOOK.md`, Abschnitt „Modellwahl").
