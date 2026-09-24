# Systemmails aller Läden über die Adresse des Betreibers

**Datum:** 2026-09-24
**Status:** Design, vom Betreiber abschnittsweise freigegeben (24.09.2026).
**Teil einer Zerlegung:** dritter und letzter Teil der Admin-Fähigkeit. Teil 1
(Tailscale-Einladungen, `2026-09-22-tailscale-einladung-design.md`) und Teil 2 (Laden anlegen,
`2026-09-22-laden-anlegen-oberflaeche-design.md`) sind gebaut und live.
**Baut auf:** der Konto-Mail-Brücke vom 17.09.2026 (`benutzer_mails`, `mail_dispatch.verarbeite_kontomail`,
`passwort_reset.py`) und dem Orchestrator aus Teil 2 (`deploy/admin-auftrag-ausfuehren.sh`).

---

## 1. Ausgangslage, gemessen (23./24.09.2026)

### 1.1 Was schon funktioniert

„Passwort vergessen" funktioniert im Basis-Laden. Die Oberfläche legt nur einen Zettel in `benutzer_mails`
(`db/provision.sql:256-266`, in **jedem** Laden-Schema). Abgeholt wird er von `mail_dispatch.py` im Dienst
`<laden>-mail`: `verarbeite_kontomail` (`sales-mcp/mail_dispatch.py:649-741`) erzeugt den Token selbst, speichert nur
seinen Hash und schickt den Link an `benutzer.email` eines bestehenden, aktiven Kontos. Der Text ist fest. Schlägt der
Versand fehl, wird der Token sofort entwertet und die Bremse zurückgesetzt. Live gemessen: Basis-Laden 2/2 aktive Konten
mit Adresse, `sales_ivan` 1/1.

### 1.2 Die Lücke

Ivans Laden (und jeder weitere) hat **keinen** Mail-Dienst. Gemessen: `docker ps` zeigt nur `sales-mail`. Sein Zettel
bleibt für immer auf `offen`. Der Orchestrator aus Teil 2 startet für einen neuen Laden nur `sales-mcp` und `sales-ui`.

### 1.3 Die Falle, die die naheliegende Lösung verbietet

`mail_dispatch` erledigt in **einer** Schleife mit **einer** SMTP-Identität (`SMTP_*`, `EMAIL_ABSENDER`,
`mail_dispatch.py:100-110`) beides: freigegebene Kundenentwürfe (`eine_runde`, `:746-755`) und Konto-Zettel
(`:761-768`). Ein `ivan-mail` mit den Zugangsdaten des Betreibers würde **auch Ivans Kundenmails von
felix@vibemind.space** verschicken, sobald Ivan Entwürfe freigibt. Das darf nicht passieren.

### 1.4 Warum nicht zentral

Ein zentraler Versender für alle Läden bräuchte Datenbankzugriff über alle Schemata hinweg (Admin-Rechte oder eine neue
Rolle). Dem Basis-Dienst Rechte auf fremde Tabellen zu geben, scheidet aus: `sales_app` teilen sich `sales-mail` und
der Web-Container `sales-ui`, eine kompromittierte Oberfläche könnte dann Konten anderer Läden lesen.

---

## 2. Was gebaut wird

### 2.1 Zwei Identitäten im Mail-Dienst

`mail_dispatch.py` kennt künftig zwei Identitäten:

| | Kundenentwürfe (`drafts`) | Konto-Zettel (`benutzer_mails`) |
|---|---|---|
| Identität | nur `SMTP_*`, `EMAIL_ABSENDER` | `SYSTEM_SMTP_HOST/_PORT/_USER/_PASSWORT`, `SYSTEM_ABSENDER`, wenn vollständig gesetzt, sonst Rückfall auf `SMTP_*` |
| fehlt die Identität | Entwürfe werden **übersprungen** (bleiben `approved` liegen, gehen raus, sobald `SMTP_*` eingetragen ist) | Zettel wird wie heute mit `fehler` geschlossen |

Regeln:

- Ein Entwurf wird **nie** über die System-Identität verschickt. Diese Regel steht im Code, nicht nur in der
  Konfiguration, und ein Test prüft sie.
- Der Basis-Laden setzt keine `SYSTEM_*`. Er fällt auf `SMTP_*` zurück, sein Verhalten bleibt unverändert.
- Startprüfung (`_fehlende_konfiguration`, `:801`): Der Dienst startet, sobald **mindestens eine** Identität
  vollständig ist, und protokolliert beim Start, welche aktiv sind. Heute verweigert er den Start ohne `SMTP_*`.
- `senden()` bekommt die Identität als Parameter, statt die globalen `SMTP_*` zu lesen. `_ohne_geheimnis` maskiert
  beide Passwörter.
- Systemmails werden nicht im IMAP-Gesendet-Ordner des Ladens abgelegt. `verarbeite_kontomail` ruft `_sent_ablegen`
  schon heute nicht auf, und dabei bleibt es.

### 2.2 Willkommensmail

- **Formular:** „Laden anlegen" (`/team/laden-anlegen`) bekommt ein optionales Feld *private E-Mail-Adresse des neuen
  Menschen*. Die serverseitige Prüfung übernimmt das bestehende `mailadresse.pruefe`.
- **Tabelle:** `admin_auftraege.email` gibt es seit Teil 1. Der CHECK wird so erweitert, dass eine Adresse bei
  `art = 'laden_anlegen'` entweder `NULL` ist oder dasselbe Muster erfüllt wie bei `tailscale_einladen`.
  `benutzer_mails.art` wird um `'willkommen'` erweitert (idempotent, per `drop constraint if exists` + `add constraint`,
  wie überall in `provision.sql`).
- **Orchestrator** (`deploy/admin-auftrag-ausfuehren.sh`, Zweig `laden_anlegen`): Wurde eine Adresse angegeben, trägt
  er sie nach dem Anlegen des Kontos in `sales_<name>.benutzer.email` ein und legt im **Schema des neuen Ladens** einen
  Zettel `art = 'willkommen'` ab (als `supabase_admin`, Werte über `\getenv`, nie über Argv).
- **Versand:** `verarbeite_kontomail` behandelt `willkommen` wie `passwort_reset`, mit derselben Token-Mechanik
  (Klartext entsteht im Versender, nur der Hash landet in der Datenbank) und demselben Link auf `/passwort-neu` des
  eigenen Ladens. Unterschiede: **Gültigkeit 7 Tage** statt 30 Minuten, weil ein neuer Mensch die Mail vielleicht
  erst am nächsten Tag liest. Eigener fester Betreff und Text in `passwort_reset.py` („Für dich wurde ein Zugang
  eingerichtet, Benutzername …, hier legst du dein Passwort fest"). Kein freier Parameter.
- **Wegwerf-Passwort:** Mit Adresse erscheint auf der Ergebnisseite **kein** Passwort. Das Konto bekommt trotzdem ein
  zufälliges, das niemand kennt. Ohne Adresse bleibt alles wie heute.

### 2.3 Rollout

- **Neue Läden:** Der Orchestrator startet `sales-mcp sales-ui sales-mail` (wörtliche Dienstnamen, nie ein nacktes
  `up -d`). `deploy/laden-anlegen.sh` schreibt `SYSTEM_SMTP_*`/`SYSTEM_ABSENDER` in die neue `deploy/laeden/<name>.env`
  und kopiert sie dafür aus `SMTP_*`/`EMAIL_ABSENDER` der Basis-`.env`. Die Datei ist bereits `umask 077`.
  `SMTP_*` des neuen Ladens bleiben leer, bis dessen eigenes Postfach eingerichtet ist.
- **Compose:** `docker-compose.yml` reicht `SYSTEM_*` ausschließlich an `sales-mail` durch, nie an `sales-ui` oder
  `sales-mcp` (T5a).
- **Ivan nachziehen** (Produktionsschritt, nur mit Freigabe): `SYSTEM_*`-Zeilen in `deploy/laeden/ivan.env`, dann
  `docker compose --env-file deploy/laeden/ivan.env up -d --build sales-mail`.

### 2.4 Rückmeldung an den Betreiber

Die Admin-Seite im Basis-Laden darf `sales_<name>` nicht lesen (Trennung). Der Orchestrator läuft als `supabase_admin`
auf dem Host und wartet deshalb nach dem Anlegen des Zettels **bis zu 60 Sekunden** auf dessen Status. Das Ergebnis
schreibt er in `admin_auftraege.ergebnis`: `verschickt`, `fehlgeschlagen: <grund>` oder `noch unterwegs`. Die Seite
zeigt es an. Eine fehlgeschlagene Mail macht den Laden nicht ungeschehen: Status bleibt `erfolg`, der Mailstatus steht
daneben.

---

## 3. Entscheidungen und warum

| Frage | Entscheidung | Warum |
|---|---|---|
| Welche Mails? | Passwort vergessen (alle Läden) + Willkommensmail beim Laden anlegen | Vom Betreiber gewählt, ersetzt das Weiterreichen des Wegwerf-Passworts von Hand |
| Wo liegt die Sendemacht? | Im Mail-Dienst jedes Ladens, mit getrennter System-Identität (Weg A) | Datentrennung bleibt unangetastet, bestehender Code bleibt, der Link zeigt automatisch auf die richtige Oberfläche |
| Kundenmails eines Ladens ohne eigenes Postfach? | Werden übersprungen, nie über die Betreiber-Identität | Sonst schriebe der Betreiber im Namen eines anderen Menschen an dessen Kunden |
| Gültigkeit des Willkommens-Links | 7 Tage | Ein neuer Mensch liest die Mail nicht zwingend sofort. Passwort-vergessen bleibt bei 30 Minuten |
| Rückmeldung | Orchestrator wartet bis 60 s und schreibt das Ergebnis | Die Oberfläche darf das fremde Schema nicht lesen, der Host-Orchestrator schon |

---

## 4. Nicht im Umfang

- Laden anlegen, Tailscale-Einladung und Willkommensmail in **einem** Knopf zusammenlegen.
- Weitere Arten von Systemmails (Kontosperrung, Rollenwechsel …).
- Ein eigenes Postfach für Ivans Kundenmails einrichten. Die Weiche macht es möglich, eingerichtet wird es nicht.
- DMARC für vibemind.space (bekannt fehlend, unabhängige Aufgabe).

---

## 5. Prüfung

1. **Die Weiche:** Ohne `SMTP_*` wird ein freigegebener Entwurf nicht versendet und bleibt `approved`. Mit gesetzter
   `SYSTEM_*`-Identität geht ein Konto-Zettel über sie raus, ein Entwurf **nie**. Beide Tests werden rot, wenn jemand die
   Weiche „vereinfacht".
2. **Startprüfung:** startet mit nur `SYSTEM_*`, mit nur `SMTP_*`, mit beiden, und verweigert den Start ohne beide.
3. **Willkommens-Zettel:** fester Text, Gültigkeit 7 Tage, Link auf die eigene `UI_BASIS_URL`, Klartext-Token nie in
   der Datenbank.
4. **Formular und CHECK:** Eine ungültige Adresse wird serverseitig abgewiesen. Ohne Adresse verhält sich der Ablauf wie
   heute.
5. **Orchestrator:** mit Attrappen geprüft. Adresse und Zettel landen im **neuen** Schema, kein Wert erscheint im
   Argv, und der 60-Sekunden-Wartepfad liefert alle drei Ausgänge.
6. **Echter Probelauf (nur mit Freigabe):** Ein Wegwerf-Laden mit einer Adresse, die der Betreiber kontrolliert. Die
   Mail kommt von felix@vibemind.space an, über den Link wird ein Passwort gesetzt, die Anmeldung gelingt. Danach wird
   alles abgebaut.
7. **Ivan:** Nach dem Nachziehen läuft `ivan-mail` und meldet beim Start nur die System-Identität als aktiv.
