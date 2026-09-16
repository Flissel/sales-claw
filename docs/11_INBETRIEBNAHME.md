# Inbetriebnahme: Stufe 1 und Termin-Einladungen

**Stand:** 11.09.2026 · **Zweig:** `feat/stufe-1-fundament` · **Commits:** `9136fb4..de05453`
**Umfang:** 47 Commits aus zwei Vorhaben, 1640 Tests grün, bisher **nie in Betrieb**.

---

## 1. Wozu dieser Durchgang da ist

Die Testsuite beweist, dass der Code tut, was er soll. Sie kann **nicht** beweisen,
dass er es im ausgelieferten Stack tut — und genau dort saß der schwerwiegendste
Fehler dieses Vorhabens: `sales-mail` hatte keinen Zugriff auf den Ordner, aus dem er
die Kalenderdatei liest. Jede freigegebene Einladung wäre als fehlgeschlagen gebucht
worden, und alle 1640 Tests waren grün dabei, weil sie die Pfade auf ein
Testverzeichnis umbogen.

Die Lücke zwischen Code und Wirklichkeit schließt nur ein echter Durchgang. Dieser
hier prüft die ganze Kette in einem Stück:

> Entwurf → Freigabe → SMTP mit Anhang → fremdes Mailprogramm → Ablehnung mit
> Gegenvorschlag → IMAP → Auslesen → Verlauf und Wiedervorlage

Jedes Glied hat mindestens eine Fehlerart, die kein Test erreicht. Sie sind unten je
Schritt benannt.

---

## 2. Vor dem Einspielen

### 2.1 Die Entscheidung: `feat/stufe-1-fundament` nach GitHub

Die VM zieht ihren Stand von GitHub; `deploy/update.sh` macht einen **eigenen** Fetch.
Ohne Push passiert auf der VM nichts. Das hebt die stehende Anweisung „alles lokal
lassen" auf — bewusst, für diesen Durchgang.

```bash
git log --oneline origin/feat/stufe-1-fundament..HEAD   # was neu rausgeht
git push origin feat/stufe-1-fundament
```

**Nicht** den Gitlink im äußeren Repo anfassen. Der Durchgang prüft den Space, nicht
die Einbettung.

### 2.2 Welche Kerndienste laufen überhaupt?

`update.sh` fasst **nur an, was vorher lief** (bewusst so, seit dem Zwischenfall vom
30.08.). Läuft `sales-mail` gerade nicht, wird er nicht neu gebaut — **und der
K1-Fix greift nicht.** Dann ist der ganze Durchgang wertlos, ohne dass etwas rot wird.

```bash
for d in sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw; do
  printf '%-16s %s\n' "$d" "$(docker inspect -f '{{.State.Status}}' $d 2>/dev/null || echo FEHLT)"
done
```

Alle sechs müssen `running` sein. Sonst wird auch die Abnahme übersprungen
(`update.sh` prüft `KERN = KERN_ALLE`), und es gibt keine Rückfahrkarte.

### 2.3 Gehen Antworten in das Postfach, das gelesen wird?

Der `ORGANIZER` der Einladung ist `EMAIL_ABSENDER`. Dorthin schickt das Mailprogramm
des Empfängers die Zusage. Gelesen wird über `IMAP_USER` — und das fällt, wenn nicht
gesetzt, auf `SMTP_USER` zurück.

**Weichen die voneinander ab, landen alle Antworten in einem Postfach, das niemand
liest.** Kein Fehler, keine Meldung — es kommt einfach nie etwas an. Keine Testsuite
kann das finden, es ist reine Konfiguration.

```bash
grep -E '^(SMTP_USER|EMAIL_ABSENDER|IMAP_USER)=' .env
```

Die drei müssen dasselbe Postfach meinen. (`.env.example` Zeile 143 verlangt ohnehin,
dass `EMAIL_ABSENDER` zum Postfach von `SMTP_USER` passt — sonst weisen viele Server
die Mail zurück.)

### 2.4 Der Testkontakt

Der Selbsttest braucht einen Kontakt mit einer **Mailadresse, die du selbst liest** —
am besten bei einem anderen Anbieter, damit du siehst, was ein fremdes Mailprogramm
anzeigt.

Das Freigabe-Gate prüft die Einwilligung. Ohne sie wird der Entwurf abgelehnt — das
ist richtiges Verhalten, kein Fehler. Für den Testkontakt einmal
`einwilligung_erfassen` aufrufen.

### 2.5 Arbeitsbaum auf der VM sauber

`update.sh` bricht ab, sobald **nachgeführte** Dateien verändert sind (`.env`,
`media/`, `auftraege/` stören nicht). Vorher prüfen:

```bash
git status --porcelain --untracked-files=no    # muss leer sein
```

---

## 3. Einspielen

**Zuerst, VOR dem Stack-Neustart: `db/provision.sql` gegen die Produktionsdatenbank
fahren.** Dieser Durchgang bringt die Stufe „Kalenderquellen und Team-Sicht"
(`sales.kalender_quellen`, die erweiterte Rolle `kalender` auf `sales.benutzer`) — und
`provision.sql` läuft **nirgends automatisch**, `deploy/update.sh` ruft es nicht auf.
Befehl und DSN-Sicherheitsmuster (Host-Umgebungsvariable statt Kommandozeile) stehen in
[03_RUNBOOK.md](03_RUNBOOK.md), Abschnitt „Kollegen-Kalender". Ohne diesen Schritt legt
`benutzer_anlegen` für die neue Rolle keine Konten an (SQLSTATE 23514) — der Kollege
bekommt gar keinen Zugang. Die bestehende Terminbuchung bleibt davon unberührt
(`server.belegungen()` fängt eine fehlende Quellentabelle seit dieser Welle als Lücke ab,
kein Werkzeugausfall mehr — siehe 03_RUNBOOK.md für das Detail), aber die neue Team-Sicht
bleibt bis zum Lauf inaktiv.

```bash
cd ~/sales-claw && bash deploy/update.sh
```

**Nie vorher selbst pullen** — das Skript macht seinen eigenen Fetch und braucht den
alten Stand für die Rückfahrkarte.

Was dieser Durchgang auslöst, aus dem Skript abgelesen:

| Auslöser | Wirkung |
|---|---|
| `sales-mcp/` geändert | voller Kern-Neubau, **und** `sales-claw` wird neu gestartet (ein `sales-mcp`-Neustart trennt sonst stillschweigend die MCP-Verbindung des Gateways) |
| `docker-compose.yml` geändert | voller Kern-Neubau **plus** openwa-Neubau |
| Abnahme rot | automatischer Rückbau auf `vor-update`, erneute Abnahme |

Es wird also alles gebaut. Rechne mit mehreren Minuten.

---

## 4. Nach dem Einspielen: was die Tests nicht prüfen konnten

**Hängen die Ordner an `sales-mail`?** Das ist K1, der Fehler, der alles blockiert hätte:

```bash
docker inspect sales-mail --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
```

Erwartet: `/media` und `/media-erzeugt`, beide **read-only**. Fehlen sie, wurde der
Container nicht neu erzeugt — dann lief er vorher nicht (siehe 2.2), und der Rest des
Durchgangs ist sinnlos.

**Schreibt `sales-mcp` in `media-erzeugt`?** Dort legt `termin_einladen` die Datei ab;
dieser Mount muss **schreibbar** sein — nur bei `sales-mcp`, bei `sales-mail` und
`sales-dispatch` ausdrücklich nicht.

---

## 5. Der Selbsttest

### Schritt 1 — Einladung entwerfen

`termin_einladen` mit dem Testkontakt, einem Termin in etwa zwei Wochen und einem
Thema, das **einen Umlaut und ein `&` enthält** (damit die Escaping-Arbeit aus Stufe 1
im selben Durchgang mitgeprüft wird).

Erwartet: eine Antwort mit `uid`, `datei`, `wiedervorlage` — und ein Hinweistext, der
sagt, dass im Kalender nichts steht und auch nach einer Zusage nichts von selbst
entsteht.

*Geht schief:* „Die Einladung konnte nicht abgelegt werden" → der `media-erzeugt`-Mount
bei `sales-mcp` fehlt oder ist read-only.

### Schritt 2 — Freigeben

Auf `/freigaben` in der Oberfläche. Der Entwurf trägt die `.ics` als Anhang.

*Geht schief:* Entwurf geht auf `failed` → **K1 hat nicht gegriffen.** Genau der Fall,
den dieser Durchgang finden soll. Meldung in `docker logs sales-mail` nachsehen.

### Schritt 3 — Was beim Empfänger ankommt

Innerhalb von etwa zehn Sekunden (`MAIL_INTERVAL_S=10`). Im fremden Mailprogramm öffnen.

Erwartet: **Annehmen / Ablehnen / Vielleicht** als Knöpfe, nicht bloß eine
Dateianlage. Termin, Uhrzeit und Thema korrekt, Umlaute richtig, kein `&amp;`.

*Geht schief:*
- Keine Knöpfe, nur ein Anhang → `METHOD:REQUEST` fehlt oder `ORGANIZER` weicht vom
  `From:` ab. Beides ist der Kern der Stufe.
- Falsche Uhrzeit → Zeitzonenfehler. Genau nachrechnen, nicht „passt ungefähr".
- `&amp;` im Thema → bekannte Altlast in den Bestandsdaten, siehe Abschnitt 7.

### Schritt 4 — Ablehnen mit Gegenvorschlag

Im Mailprogramm ablehnen, einen **Grund** eintippen und einen **anderen Termin**
vorschlagen. Grund absichtlich lang machen (über 200 Zeichen), damit die Kürzung
in der Wiedervorlage mitgeprüft wird.

### Schritt 5 — Antwort einlesen

**Hier ist die bewusste Lücke dieser Stufe:** Es gibt keinen Abrufdienst. Die Antwort
wird erst erfasst, wenn du die Mail öffnest. `postfach_lesen` zeigt jetzt an, welche
Mails einen Kalenderteil tragen — diese mit `postfach_mail_lesen` öffnen.

*Geht schief:* Die Antwortmail taucht gar nicht auf → `EMAIL_ABSENDER` und der
IMAP-Zugang meinen verschiedene Postfächer (Abschnitt 2.3).

### Schritt 6 — Das Ergebnis prüfen

Auf `/kontakte/{id}`:

- Der Verlauf zeigt die Einladung **lesbar** mit Datum, Uhrzeit und Thema — nicht nur
  „Einladung entworfen" mit JSON dahinter.
- Die Ablehnung steht da, mit Grund.
- Eine Wiedervorlage nennt den Gegenvorschlag.

**Das ist die wichtigste einzelne Prüfung des ganzen Durchgangs:** Steht dort ein
Datum aus **1970**, ist K2 zurück. Der Fehler kam daher, dass jede zeitzonenbewusste
Kalenderdatei vor dem Termin einen Block mit Sommerzeit-Regeln trägt — und der hat
eigene Datumszeilen von 1970. Im Test gemessen: vorher `1970-03-29`, nachher
`2026-10-02`. Ein Gegenvorschlag aus einem echten Mailprogramm ist der einzige Weg,
das in der Wirklichkeit zu bestätigen.

---

## 6. Zwei Messungen für das nächste Vorhaben

Unabhängig vom Durchgang, aber derselbe Anlass — beides kann nur der Betreiber tun:

**Ein zweiter Kalender „Privat".** Heute liegt alles in einem Kalender. Volle Sicht im
Team ist damit unmöglich, ohne auch Privates freizugeben. Die Trennung ist
Voraussetzung, kein Detail.

**Eine Freigabe zwischen zwei Konten einrichten.** Damit klärt sich die Frage, an der
die gesamte Sichtbarkeits-Hälfte hängt: **Taucht ein freigegebener Kalender im Konto
des Empfängers überhaupt auf?** Der Server meldet `resource-sharing`,
`calendarserver-sharing` und `calendar-auto-schedule` — gemessen am 11.09. Ob die
Freigabe beim Empfänger als Kalender ankommt, ist damit noch nicht bewiesen.

---

## 7. Was nach dem Durchgang offen bleibt

**Die `&amp;`-Bestandsdaten.** Der Lesepfad ist korrigiert, die alten Einträge in
`activities.payload` nicht. Der Durchgang **macht sie sichtbar, er heilt sie nicht.**
Die Bereinigung ist eine Entscheidung über Produktionsdaten — und die trifft sich
besser mit einer Zahl als mit einem Bauchgefühl:

```bash
export SALES_DSN=$(grep '^SALES_DB_URL=' .env | sed 's/^SALES_DB_URL=//')
docker run --rm -e SALES_DSN -i postgres:17-alpine \
  sh -c 'psql "$SALES_DSN" -f -' < scripts/bestandsdaten-entities-zaehlen.sql
unset SALES_DSN
```

Die Datei liest nur — kein `UPDATE`, kein `DELETE`, kein `BEGIN`. Sie zeigt je Feld,
wie viele Zeilen betroffen sind, welche Aktivitätsarten es trifft, seit wann, und ein
paar Beispiele zum Ansehen. Die DSN steht dabei nie in einer Kommandozeile (Muster aus
`docs/03_RUNBOOK.md`, Abschnitt „psql-Gegenproben").

**Eine mögliche zweite Ursache auf `/freigaben`.** Bei Stufe 1 ließ sich nicht
ausschließen, dass dort neben dem behobenen Escaping-Fehler noch etwas anderes wirkt.
Das ist nur an der Produktionsdatenbank zu klären — also jetzt. Sieht `/freigaben`
nach der Bereinigung immer noch falsch aus, gibt es eine zweite Ursache.

**Zwei blinde Flecken im Umlaut-Wächter**, geparkt mit der Auflage, sie **vor Stufe 4**
zu schließen: Stufe 4 baut die Optik um und arbeitet genau in dem CSS-Block, in dem
der Wächter nicht hinsieht.

**Die Testsuite läuft gegen ein gemeinsames Datenbankschema.** Zwei gleichzeitige
Läufe zerstören einander. Nie zweimal parallel starten.

---

## 8. Rückfahrkarte

`update.sh` setzt vor jedem Einspielen das Tag `vor-update` und baut bei roter Abnahme
selbsttätig zurück. Von Hand:

```bash
git reset --hard vor-update
docker compose up -d --build sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw
docker restart sales-claw && sleep 30
bash deploy/smoke.sh
```

Meldet auch der Rückbau rot, schreibt das Skript `notfall` nach
`~/sales-betrieb/update-status.json` und hält an. Dann nicht weiterprobieren.

---

## 9. Die vier Kanäle eines neuen Ladens

**Anderer Anlass als die Abschnitte oben:** Abschnitte 1–8 begleiten die
Stufe-1-Termineinladungen des *bestehenden* Ladens. Dieser Abschnitt gehört
zu einem eigenen Vorhaben — einem *zweiten* Laden auf derselben Maschine
(Plan 2026-09-16-zweiter-laden-getrennt) — und beschreibt dessen Inbetriebnahme,
nachdem Container, Schema und Zugang bereits stehen
(`docs/03_RUNBOOK.md`, Abschnitte „Einen zweiten Laden anlegen" und „Zugang:
eigener Serve-Port und eigene Zugriffsregel").

Ein Laden ohne seine eigenen Kanäle ist nur eine leere Hülle: Container laufen,
aber niemand kann ihn benutzen — kein Postfach, kein Bot, kein LinkedIn-Zugang,
keine WhatsApp-Kopplung. Keines der vier kann ein Skript erzeugen (ein Postfach
beim Anbieter, ein Bot-Token beim BotFather, ein LinkedIn-Zugang, ein
WhatsApp-Pairing sind an eine Person gebunden). Diese Tabelle schreibt die
Reihenfolge auf: was anzulegen ist, wo der Wert hingehört, und wie man
**nachsieht**, dass er wirkt — statt nur zu behaupten, dass er es tut.

| Kanal | Anzulegen | Gehört nach | Nachweis |
|---|---|---|---|
| Mail | Postfach `<name>@vibemind.space` beim Anbieter | `deploy/laeden/<name>.env` (`SMTP_USER`, `EMAIL_ABSENDER` — beide auf dasselbe Postfach, siehe Abschnitt 2.3 oben) | Entwurf zustellen lassen, **im echten Postfach** den Absenderkopf prüfen — nicht im Log (Tor 8 der Spec, unten) |
| Telegram | Bot-Token beim BotFather | `deploy/laeden/<name>.env` (`TELEGRAM_BOT_TOKEN`) | `getMe` aus dem Container (unten) — der Bot-Name, nicht `@VibeMind_agent_bot` |
| LinkedIn | eigener Zugang | `deploy/laeden/<name>.env` | Anmeldung im Container zeigt das eigene Profil, nicht das des bestehenden Ladens |
| WhatsApp | Pairing mit eigener Nummer | **kein** Eintrag in der `.env` — eigenes Volume `<name>-claw-state` | neuer QR-Code im Log des neuen Containers, **kein** QR im Log des bestehenden (Tor 10, `docs/03_RUNBOOK.md`, Abschnitt „Einen zweiten Laden anlegen", Schritt 5) |

**Warum die WhatsApp-Zeile keine Umgebungsvariable nennt.** Die drei anderen
Kanäle sind ein Geheimnis, das einmal gesetzt wird und dann ruht (`.env`). Die
WhatsApp-Kopplung ist kein Geheimnis dieser Art, sondern ein laufender
Sitzungszustand, der sich mit jeder Nachricht verändert — er liegt im Volume
`<name>-claw-state`, nicht in einer Datei, die man einmal ausfüllt. Dasselbe
Volume ist es, das die Kopplung verliert, wenn es versehentlich neu angelegt
statt umkopiert wird (die Warnung zu `openwa-data` in `docs/03_RUNBOOK.md`,
Abschnitt „Einen zweiten Laden anlegen").

### Ein Wert geht nie über `argv`

**Jeder der drei Geheimwerte (Postfach-Zugang, Telegram-Token,
LinkedIn-Zugang) wird über `stdin` oder die Umgebung übergeben, nie über eine
Kommandozeile (`argv`).** Zwei unabhängige Gründe, beide gemessen:

- **Sichtbarkeit.** Ein Wert in `argv` steht in der Prozessliste des Hosts
  (`ps`, `docker inspect`) — sichtbar für jeden mit Zugriff auf die Maschine.
  Dasselbe Muster wie beim DSN in `docs/03_RUNBOOK.md`, Abschnitt
  „psql-Gegenproben": Umgebungsvariable setzen, **ohne Wert** an den
  Container durchreichen (`docker exec -e VAR ...`, kein `=wert`), Auflösung
  erst in der Container-Shell.
- **Unversehrtheit.** Am 12.09.2026 machte ein **mitgeschriebenes
  Zeilenende** einen Telegram-Token ungültig — er kam mit 47 statt der
  erwarteten 46 Zeichen an. Die Ursache war hier nicht `argv`, sondern ein
  Copy-Paste-Weg, der ein unsichtbares `\r` oder `\n` mit übernahm. Beim
  Einspielen eines neuen Tokens deshalb die Länge **nachmessen**, bevor er in
  die `.env` wandert:

  ```bash
  printf '%s' "$TOKEN" | wc -c
  # Telegram-Bot-Token: <Ziffern>:<35 Zeichen>, ueblich 46 — nicht die Zahl
  # aus dem Kopf uebernehmen, jeden Bot-Token einzeln nachmessen
  ```

  Ein Wert, der über `stdin` in ein Werkzeug läuft (z. B. `nano` beim
  Editieren der `.env`, oder ein `read -r TOKEN` an einem Prompt), trägt kein
  automatisch mitgeschriebenes Zeilenende — ein `echo`/Copy-Paste über eine
  Kommandozeile je nach Quelle schon.

### Telegram: `getMe` aus dem Container

```bash
docker exec ivan-telegram python -c "
import os, urllib.request, json
t = os.environ['TELEGRAM_BOT_TOKEN']
with urllib.request.urlopen(f'https://api.telegram.org/bot{t}/getMe') as a:
    print(json.load(a)['result']['username'])"
```

Erwartet: der Bot-Name **dieses** Ladens — ausdrücklich **nicht**
`@VibeMind_agent_bot` (der Bot des bestehenden Ladens). Zwei Läden mit
demselben Bot-Token wären derselbe Unfall wie zwei Läden mit derselben
Absenderadresse (siehe `deploy/smoke.sh`, Abschnitt „Absenderadressen sind je
Laden verschieden") — nur ohne automatische Prüfung dort: ein Bot-Token ist
ein Geheimnis und darf, anders als `EMAIL_ABSENDER` (kein Geheimnis, siehe
`docs/10_SECRETS_ROTATION.md`), nicht ausgelesen und über Läden hinweg
verglichen werden. Die Trennung bleibt hier auf die BotFather-Vergabe
angewiesen — je Mensch ein eigener Bot.

### Mail: Tor 8, am echten Postfach

```bash
docker exec ivan-mcp env | grep -E 'EMAIL_ABSENDER|SMTP_USER'
```

Erwartet: `ivan@vibemind.space` in beiden Zeilen. Das ist nur die
Konfigurationsprüfung — der eigentliche Nachweis ist danach ein Entwurf,
freigegeben und zugestellt, **geöffnet im echten Postfach des Empfängers**.
Warum nicht das Log genügt: am 12.09.2026 war die versendete Fassung einer
Datei kaputt (`\r\r\n`), während die archivierte Fassung richtig war — das
Log zeigt nur, was das Programm zu tun glaubte, nicht was tatsächlich ankam.
