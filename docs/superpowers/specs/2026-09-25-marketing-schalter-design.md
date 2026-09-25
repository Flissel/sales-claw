# Schalter Sales ↔ Marketing

**Stand 25.09.2026. Mit dem Betreiber besprochen und freigegeben: verlinken
(Ansatz A), die Marketing-Seite läuft dafür zusätzlich auf der VM.**

## 1. Ziel

Der Betreiber wechselt mit einem Klick zwischen der Sales-Oberfläche und der
bestehenden Marketing-Oberfläche und wieder zurück, am PC wie am Handy.

| Frage | Antwort |
| --- | --- |
| Was steht im Marketing-Tab | Die **bestehende** Marketing-Seite, kein Nachbau in Sales |
| Wer sieht den Schalter | Nur der Betreiber (Rolle `freigeben` im Basis-Laden); Ivan nicht — „Marketing läuft über mich" |
| Wo | PC und Handy, beide im Tailnet |
| Wenn der PC aus ist | Die Seite bleibt erreichbar, weil sie auf der VM läuft |

## 2. Ausgangslage (gemessen 25.09.2026)

- Die Marketing-Oberfläche ist `GET /mockup/` der Marketing-API
  (`spaces/marketing/api/server.py`). Sie ruft ihre Daten über feste Pfade ab
  (`fetch("/api/…")`) und muss deshalb an der Wurzel ihrer eigenen Adresse liegen.
- Die Marketing-API läuft heute nur auf dem PC (`127.0.0.1:5510`). Die Datenbank
  erreicht sie über `sync/_db.py` in Modus A (`ssh offload-vm docker exec … psql`).
  `_db` kennt schon Modus B (lokales `docker exec`), der auf der VM ohne SSH greift.
- Vom PC braucht die API nur noch die Benachrichtigung an OpenFang (`OPENFANG_URL`,
  Vorgabe `localhost:4200`) bei neuen Freigabe-Vorschlägen.
- Auf der VM liegt `5510` frei. Die VM stellt ihre Oberflächen bereits per
  `tailscale serve` ins Tailnet: `/` → `:8791` (sales-ui), `:8443` → `:12785`,
  `:8445` → `:8792` (ivan-ui), jeweils „tailnet only".
- Die Sales-Oberfläche baut ihre Seitenleiste in `sales-mcp/ui.py`
  (`_seitenleiste` aus `_GRUPPEN`, jeder Eintrag über `_pfad_erlaubt` gefiltert).

## 3. Aufbau

### 3.1 Marketing-API auf der VM (zweite Instanz)

- Neuer Checkout von `vibemind-os` auf der VM unter
  `/home/debian/marketing-os/` (Stand `master`, ohne Submodule — `spaces/marketing` liegt direkt im Repo),
  eigenes venv.
- systemd-Dienst `marketing-api.service`, startet
  `python -m spaces.marketing.api.server` mit `MARKETING_HTTP_BIND=127.0.0.1`,
  `MARKETING_HTTP_PORT=5510`, `SUPABASE_SSH_HOST` **leer** (→ Modus B) und
  `SUPABASE_DB_CONTAINER=debian-supabase-db-1`. Neustart bei Absturz.
- Die Schlüssel (`MARKETING_*_API_KEY`, `MARKETING_UNSUB_SECRET`) kommen aus einer
  Umgebungsdatei mit Rechten `600`, dieselben Werte wie auf dem PC. Nie im
  Aufruf, nie im Repo.
- `OPENFANG_URL` zeigt über das Tailnet auf den PC. Ist der PC aus, fehlt nur
  diese Benachrichtigung; der Plan misst, ob die Route dabei trotzdem sauber
  antwortet (Zeitlimit statt Hänger).
- `tailscale serve --bg --https=8446 http://127.0.0.1:5510` → Adresse
  `https://vibemind-offload-1.tail6c7d61.ts.net:8446`, tailnet only, kein Funnel.
- Die PC-Instanz bleibt unverändert; die Marketing-Agenten und der Worker nutzen
  weiter sie. Beide Instanzen lesen und schreiben dieselbe Datenbank.
- Aktualisieren: `deploy/update.sh` von sales-claw zieht auch diesen Checkout
  nach und startet `marketing-api` neu, falls er sich geändert hat. Die Befehle
  stehen im Runbook.

### 3.2 Sales-Oberfläche (`sales-mcp/ui.py`)

- Neue Einstellung **`MARKETING_URL`** (Umgebung des Dienstes `sales-ui`, leerer
  Vorgabewert). Leer heißt: kein Schalter.
- Gesetzt wird sie **nur für den Basis-Laden** (`sales-ui`, nicht `ivan-ui`).
  Zusätzlich zeigt die Oberfläche den Schalter nur für die Rolle `freigeben`
  — dieselbe Sperre wie beim Admin-Menü. Zwei Hürden, weil eine falsch gesetzte
  Umgebung sonst den Schalter in einem fremden Laden zeigte.
- Der Schalter sitzt in der Seitenleiste neben dem Logo: **Sales | Marketing**.
  „Marketing" verlinkt auf
  `<MARKETING_URL>/mockup/?zurueck=<UI_BASIS_URL>` (URL-kodiert).

### 3.3 Marketing-Seite (`spaces/marketing/mockup/index.html`)

- Im Kopf (`<header>`) kommt derselbe Schalter **Sales | Marketing** dazu.
- „Sales" verlinkt auf den Parameter `zurueck` — aber **nur**, wenn er eine
  `https://`-Adresse auf einer Domain `*.ts.net` ist. Sonst erscheint der
  Schalter ohne Sales-Link. Damit taugt die Seite nicht als Umleitung auf fremde
  Adressen.
- Der zuletzt gültige Wert wird im Browser gemerkt (`localStorage`, Zugriff in
  `try/catch`), damit der Rückweg nach einem Neuladen ohne Parameter bleibt.

## 4. Schutz

- **Die Marketing-API hat für Lesen und Vorschläge keine eigene Anmeldung.** Ihr
  Schutz ist das Tailnet. Vor dem Freischalten wird an Ivans Gerät per
  `tailscale debug netmap` (die wirksame Paketregel, nicht die ACL-Datei)
  geprüft, dass es **VM-Port 8446 nicht** erreicht. Erreicht es ihn, wird nicht
  freigeschaltet, sondern zuerst die Tailscale-Regel angepasst.
- Die API bindet nur an `127.0.0.1`; ins Tailnet kommt sie ausschließlich über
  `tailscale serve`.
- Der PC wird nicht zusätzlich geöffnet.

## 5. Fehlerfälle

| Fall | Verhalten |
| --- | --- |
| `MARKETING_URL` leer | kein Schalter |
| Rolle nicht `freigeben` / Laden nicht Basis | kein Schalter |
| `marketing-api` auf der VM abgestürzt | systemd startet neu; bis dahin Fehlerseite von `tailscale serve` |
| PC aus | Seite geht; nur die OpenFang-Benachrichtigung bei neuen Vorschlägen fehlt |
| `zurueck` fehlt oder nicht `https://…ts.net` | kein Sales-Link (bzw. der gemerkte) |

## 6. Tests

1. Sales: Schalter erscheint nur mit gesetzter `MARKETING_URL` UND Rolle
   `freigeben`; fehlt bei leerer Adresse und anderer Rolle. Der Link trägt die
   Sales-Adresse korrekt kodiert in `zurueck`.
2. Marketing: die Prüffunktion für `zurueck` nimmt `https://x.ts.net/…` an und
   weist `http://…ts.net`, `javascript:`, `https://ts.net.boese.de` und fremde
   Domains ab.
3. VM-Instanz: `curl http://127.0.0.1:5510/api/stats` auf der VM liefert dieselben
   Zahlen wie auf dem PC (dieselbe Datenbank, Modus B belegt).
4. Betrieb: `tailscale serve status` zeigt `:8446` „tailnet only"; Ivans Netmap
   ohne Zugriff auf 8446; echter Klick hin und zurück am PC und am Handy; bei
   ausgeschaltetem PC-Dienst öffnet sich die Marketing-Seite weiter.

## 7. Nicht Teil dieses Vorhabens

- Eine eigene Anmeldung für die Marketing-API.
- Die Marketing-Agenten oder den Worker auf die VM verlegen.
- Marketing-Inhalte in die Sales-Oberfläche übernehmen (Ansatz B).
- Ein Schalter für Ivan.
