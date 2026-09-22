# Tailscale-Einladungen aus der Oberfläche

**Datum:** 2026-09-22
**Status:** Design, vom Betreiber abschnittsweise freigegeben (22.09.2026).
**Teil einer Zerlegung:** Der Betreiber wünscht eine Admin-Fähigkeit mit drei unabhängigen
Teilen — Tailscale-Einladungen automatisieren, Läden aus der Oberfläche anlegen, Systemmails
über die eigene Absenderadresse an fremde Postfächer. Das sind drei verschiedene
Vorhaben mit verschiedener Technik (fremde API, bestehende Skripte einwickeln, ein Eingriff
in die Datentrennung). Der zweite Teil ("Laden anlegen aus der Oberfläche") ist bereits
gebaut, geprüft und live (`docs/superpowers/specs/2026-09-22-laden-anlegen-oberflaeche-design.md`).
Diese Spec deckt **den ersten Teil**. Der dritte folgt als eigene Spec.
**Baut auf:** der Infrastruktur aus dem zweiten Teil — `sales.admin_auftraege`, der
20-Sekunden-Zeitgeber, das Rollen-Tor. Keine zweite Fassung dieser Mechanik.

---

## 1. Ausgangslage, gemessen

Am 22.09.2026 gegen den laufenden Code und Tailscales öffentliche API-Dokumentation
gemessen.

### 1.1 Was heute von Hand passiert

Ein neuer Mensch bekommt Zugriff in zwei getrennten Schritten (`docs/03_RUNBOOK.md`,
Abschnitt „Zugang: eigener Serve-Port und eigene Zugriffsregel"):

1. **Tailscale-Einladung.** Heute über die Tailscale-Verwaltung (Web-Oberfläche), per
   E-Mail-Adresse. Der Mensch nimmt an, wird Mitglied des Tailnet — ohne jede weitere
   Berechtigung, solange keine ACL-Regel auf seine Adresse verweist (Default-Deny).
2. **Zugriffsregel.** Eine JSON-Policy-Änderung in derselben Verwaltung, die genau diesen
   Menschen auf genau einen Serve-Port beschränkt, mit einem `tests`-Block, der vor dem
   Speichern geprüft wird. Fehleranfällig genug, dass am 22.09.2026 ein einziges Zeichen
   (Punkt in einer Gmail-Adresse) eine Regel wirkungslos gemacht hat.

Diese Spec automatisiert **nur Schritt 1**. Schritt 2 bleibt Handarbeit — siehe §3 für die
Begründung.

### 1.2 Tailscales API, recherchiert (22.09.2026)

* Ein Einladungs-Endpunkt existiert wirklich: `POST /api/v2/tailnet/{tailnet}/user-invites`,
  Felder `email` und `role` (`member`, `admin`, `it-admin`, `network-admin`,
  `billing-admin`, `auditor`). Die Antwort enthält, wenn vorhanden, eine `inviteUrl` — ein
  Link, der sich auch ohne funktionierenden E-Mail-Versand von Hand weitergeben lässt.
* **Wichtig, ändert die Architektur:** Einladungen erzeugen verlangt einen
  **personengebundenen** API-Schlüssel eines Owner/Admin/IT-Admin des Tailnet — kein
  OAuth-Client-Token (das austauschbare, eng scopebare Maschinen-Credential, das für die
  übrigen Tailscale-API-Operationen üblich wäre). Das ist dieselbe Güteklasse Geheimnis wie
  ein persönliches Passwort, nicht wie ein Dienst-Schlüssel.
* Ob sich ein persönlicher Schlüssel in der Tailscale-Oberfläche auf ausschließlich
  `user-invites` eng scopen lässt (so wie es bei OAuth-Clients zweifelsfrei geht), ließ sich
  aus der Dokumentation nicht abschließend klären — wird bei der Umsetzung gegen die echte
  Tailnet-Verwaltung geprüft, nicht angenommen.
* Unbenutzte Einladungen laufen nach 30 Tagen ab (Tailscale-eigenes Verhalten, keine
  eigene Logik nötig).

Quellen: `tailscale.com/docs/features/sharing/how-to/invite-team-members`,
`tailscale.com/docs/reference/trust-credentials`,
`github.com/reviforks/tailscale-tailscale/blob/main/publicapi/userinvites.md`.

### 1.3 Bestehende Infrastruktur, die weiterverwendet wird

* `sales.admin_auftraege` (`db/provision.sql:359-374`) — heute `art text not null check
  (art = 'laden_anlegen')`, `name` mit einer Regex-CHECK für Ladennamen, `sales_app` mit
  `select, insert`, kein `update`/`delete`.
* `deploy/admin-auftrag-ausfuehren.sh` — systemd-Zeitgeber `sales-admin-auftraege.timer`,
  `OnUnitActiveSec=20s`, bereits live auf der VM. Liest den nächsten `status='offen'`-Auftrag,
  setzt `'laeuft'`, führt aus, schreibt `'erfolg'`/`'fehler'` — inklusive einer
  Selbstheilung für liegengebliebene `'laeuft'`-Zeilen älter als 10 Minuten (Schritt 0).
* `_pfad_erlaubt(rolle, pfad)` (`ui.py:520`) — das Rollen-Tor: `/team/laden-anlegen` nur für
  `freigeben` im Basis-Laden (`server.SCHEMA in ("sales", "sales_test")`).
* `_GRUPPEN` (`ui.py:1172`) — die Menüstruktur, „Admin"-Gruppe existiert bereits mit einem
  Eintrag.
* `_seite(titel, rumpf, status, refresh=None)` — das `<meta http-equiv="refresh">`-Muster
  für „auf ein Ergebnis warten" ohne JavaScript (die Oberfläche fährt `default-src 'none'`).
* Das T5a-Prinzip aus `docker-compose.yml` (Dienst `sales-ui`): sensible externe
  API-Schlüssel (`OPENWA_API_KEY`, `SMTP_*`, `CALDAV_*` — dort namentlich ausgeschlossen)
  bekommt der Web-Container nicht. Ein kompromittierter `sales-ui`-Container darf keinen
  Schlüssel besitzen, mit dem er selbst Schaden anrichten könnte.

---

## 2. Was gebaut wird

### 2.1 Tabellenänderung — ein neues `art`, eine neue Spalte, keine neue Tabelle

```sql
alter table sales.admin_auftraege
  drop constraint admin_auftraege_art_check,
  add constraint admin_auftraege_art_check
      check (art in ('laden_anlegen', 'tailscale_einladen')),
  alter column name drop not null,
  add column email text,
  add constraint admin_auftraege_name_check
      check (art <> 'laden_anlegen' or name ~ '^[a-z][a-z0-9_]{0,30}$'),
  add constraint admin_auftraege_email_check
      check (art <> 'tailscale_einladen'
             or email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$');
```

(Die genaue Umsetzung — `alter table` gegen die bestehende Tabelle vs. Anpassung des
`create table`-Blocks in `db/provision.sql`, der `if not exists` nutzt — klärt der Plan;
`provision.sql` ist additiv und idempotent, ein reiner `create table if not exists` reicht
für eine bereits bestehende Tabelle nicht, hier braucht es echte `alter`-Anweisungen mit
eigener Idempotenz-Prüfung.)

Kein `update`/`delete` für `sales_app` ändert sich — die neue Auftragsart schreibt genau wie
die bestehende nur über `insert`, der Wirt liest/ändert über `supabase_admin`.

### 2.2 Die neue Seite

Pfad `/team/tailscale-einladen`. Gleiches Tor wie `/team/laden-anlegen`:
`_pfad_erlaubt` bekommt einen weiteren Pfad mit derselben Bedingung (`freigeben`,
`server.SCHEMA in ("sales", "sales_test")`). Neuer Eintrag in der bestehenden
„Admin"-Gruppe in `_GRUPPEN`, neben „Laden anlegen".

**GET:** ein Formular mit einem Feld (E-Mail-Adresse), darunter eine Liste der letzten
Einladungs-Aufträge mit Status — dieselbe Liste-Komponente wie bei „Laden anlegen"
(`_tabelle`), gefiltert auf `art='tailscale_einladen'`. Kein Rollen-Auswahlfeld: die Rolle
ist serverseitig immer `member`.

**POST:** prüft das E-Mail-Format serverseitig (Verteidigung in der Tiefe — die
eigentliche Prüfung ist Tailscales, nicht unsere), fügt eine Zeile mit
`art='tailscale_einladen'`, `status='offen'` ein, `angefordert_von` wie überall aus
`request.scope["benutzer_name"]`.

**Ergebnisanzeige bei Erfolg:** Bestätigung, dass die Einladung verschickt wurde, plus die
`inviteUrl` aus der Tailscale-Antwort (falls vorhanden) als manueller Fallback-Link zum
Weitergeben. Hinweis, dass die Zugriffsregel weiterhin von Hand folgt (siehe
`docs/03_RUNBOOK.md`, Abschnitt „Zugang: eigener Serve-Port"). **Bei Fehler:** Tailscales
eigene Fehlermeldung (falsche/bereits eingeladene Adresse, Schlüssel ungültig, Ratenlimit
o. ä.) — nie eine erfundene Ursache.

### 2.3 Der Wirt-Zeitgeber — zweiter Zweig in derselben Datei

`deploy/admin-auftrag-ausfuehren.sh` bekommt einen zweiten Pfad nach dem Abholen des
nächsten offenen Auftrags: `art='laden_anlegen'` läuft wie bisher, `art='tailscale_einladen'`
tut Folgendes:

1. E-Mail-Adresse aus der abgeholten Zeile lesen.
2. Einen HTTPS-Aufruf gegen `https://api.tailscale.com/api/v2/tailnet/{tailnet}/user-invites`
   mit `email` und `role=member` im JSON-Rumpf.
3. **Geheimnis-Handhabung:** der persönliche API-Schlüssel liegt ausschließlich in der
   Prozessumgebung des Wirt-Skripts (wie `debian-supabase-db-1`s `supabase_admin`-Zugriff
   heute schon), niemals in einem Container. Der Bearer-Token geht **nicht** über
   `curl -H`, dessen Wert im eigenen Argv sichtbar wäre (dieselbe Klasse Leck wie
   `LADEN_PASSWORT`/`ERGEBNIS` im vorigen Teil, dort zweimal gefunden und behoben) — sondern
   über eine kleine `curl`-Konfigurationszeile, per stdin an `curl -K -` übergeben:
   `printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl -K - ...`. Der Wert
   erscheint an keiner Stelle als Kommandozeilenargument.
4. Der `curl`-Aufruf bekommt ein hartes Zeitlimit (`--max-time 15`) — ein hängender
   Netzwerkaufruf darf die Warteschlange nicht auf unbestimmte Zeit blockieren, anders als
   die bisherigen, rein lokalen `docker exec`/`psql`-Aufrufe.
5. Bei Erfolg: `status='erfolg'`, `ergebnis` mit der `inviteUrl` (falls die Antwort eine
   enthält) und einem Bestätigungstext. Bei Fehler: `status='fehler'`, Tailscales
   Fehlermeldung aus der Antwort in `fehler`.

### 2.4 Die Selbstheilung wird auftragsart-übergreifend

Schritt 0 des bestehenden Skripts (liegengebliebene `'laeuft'`-Zeilen älter als 10 Minuten
zurückstufen) filtert heute hart auf `art = 'laden_anlegen'`. Diese Spec verlangt, dass die
Bedingung auf **beide** Auftragsarten wirkt — sonst würde ein hängender Tailscale-Aufruf
(z. B. durch das neue `--max-time`, das genau diesen Fall erzeugen soll) nie zurückgesetzt.

---

## 3. Entscheidungen und warum

| Frage | Entscheidung | Warum |
|---|---|---|
| Wie weit geht der Knopf? | **Nur die Einladung selbst** | Die Zugriffsregel ändert die Netzwerk-Policy des GESAMTEN Tailnet, nicht nur eines Ladens — eine falsch erzeugte Regel hat einen anderen, größeren Blastradius als eine falsch erzeugte Einladung (die ohne ACL-Eintrag standardmäßig nirgends Zugriff gibt) |
| Wessen Schlüssel? | **Der eigene, persönliche Schlüssel des Betreibers** | Tailscale erzwingt ohnehin einen personengebundenen Schlüssel eines Owner/Admin/IT-Admin für diese Operation; ein zweites Tailscale-Konto nur für diese Automatisierung wäre zusätzliche Pflege ohne echten Sicherheitsgewinn, solange der Schlüssel eng scopebar ist |
| Übergabestelle Oberfläche → Wirt? | **Dieselbe Tabelle, zweite Auftragsart** | `art` ist als Unterscheidungsmerkmal genau dafür angelegt; eine zweite Tabelle/Zeitgeber/systemd-Einheit für eine strukturell identische Aufgabe (geschützter, protokollierter, vom Wirt ausgeführter Auftrag) wäre Doppelung ohne Nutzen |
| Welche Tailscale-Rolle bekommt der Eingeladene? | **Immer `member`, keine Auswahl** | Geringstes Privileg; eine Rollenauswahl in der Oberfläche wäre eine Tür zu versehentlicher Rechteausweitung ohne echten Bedarf |
| Zeitüberschreitung beim API-Aufruf? | **`--max-time 15`**, plus auftragsart-übergreifende Selbstheilung | Der einzige Schritt dieser Spec, der über das lokale Netz hinausgeht — anders als alle bisherigen `docker exec`/`psql`-Aufrufe kann er wirklich hängen |

---

## 4. Nicht im Umfang

* **Die Zugriffsregel (ACL-Policy) automatisch setzen.** Eigener, deutlich größerer
  Eingriff (Netzwerk-Policy des gesamten Tailnet) — ausdrücklich zurückgestellt, siehe §3.
* **`tailscale serve` für einen Laden einrichten.** Gehört zum zweiten Untervorhaben
  („Laden anlegen"), nicht hierher.
* **Einladungen zurückziehen/stornieren.** Kein Rückbau-Knopf, wie schon beim zweiten
  Untervorhaben bewusst nicht gebaut — Tailscales eigene 30-Tage-Ablauffrist genügt.
* **Eine Übersicht offener Einladungen über das hinaus, was `sales.admin_auftraege`
  ohnehin protokolliert.** Tailscales eigene Verwaltung zeigt das bereits vollständig.
* **Eine Rolle außer `member` über diese Oberfläche vergeben.**

---

## 5. Prüfung

1. **Der Knopf existiert nicht in Ivans Oberfläche**, unabhängig von seiner Rolle — exakt
   dieselbe Schema-Bedingung wie bei „Laden anlegen".
2. **Eine ungültige E-Mail-Adresse** wird serverseitig abgewiesen, bevor eine Zeile
   entsteht.
3. **Ein absichtlich hängender Tailscale-Aufruf** (Attrappe mit künstlicher Verzögerung
   über 15 Sekunden) löst `--max-time` aus, endet mit `status='fehler'` — und eine
   nachgestellte, über 10 Minuten alte `'laeuft'`-Zeile mit `art='tailscale_einladen'`
   wird vom Schritt-0-Update ebenso zurückgesetzt wie eine mit `art='laden_anlegen'`.
4. **Der Bearer-Token erscheint nirgends im Argv** — nachgemessen wie beim vorigen
   Untervorhaben (Argv-Attrappe während eines echten Laufs).
5. **Der ganze Weg, einmal echt, mit Freigabe:** eine Einladung an eine selbst
   kontrollierte Wegwerf-Adresse auslösen, den Eingang der E-Mail bestätigen, die
   Einladung danach über die Tailscale-Verwaltung von Hand zurückziehen.
