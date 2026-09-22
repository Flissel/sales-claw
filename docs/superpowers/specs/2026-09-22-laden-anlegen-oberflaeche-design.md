# Laden anlegen aus der Oberfläche

**Datum:** 2026-09-22
**Status:** Design, vom Betreiber abschnittsweise freigegeben (22.09.2026).
**Teil einer Zerlegung:** Der Betreiber wünscht eine Admin-Fähigkeit mit drei unabhängigen
Teilen — Tailscale-Einladungen automatisieren, Läden aus der Oberfläche anlegen, Systemmails
über die eigene Absenderadresse an fremde Postfächer. Das sind drei verschiedene
Vorhaben mit verschiedener Technik (fremde API, bestehende Skripte einwickeln, ein Eingriff
in die Datentrennung). Diese Spec deckt **nur den zweiten Teil**. Die anderen beiden folgen
als eigene Specs.
**Baut auf:** `2026-09-16-getrennte-laeden-design.md` und ihrem Plan — jeder Schritt hier
ruft bestehende, geprüfte Skripte auf, keine zweite Fassung der Logik.

---

## 1. Ausgangslage, gemessen

Am 22.09.2026 an der laufenden Anlage und am Quelltext gemessen.

### 1.1 Was heute von Hand passiert

Ein neuer Laden entsteht in fünf Schritten, alle über SSH: `deploy/laden-anlegen.sh <name>
<port-gateway> <port-ui> <port-openwa> <port-serve>` (fünf Pflichtargumente, seit
Schlussfix D — der Serve-Port wird nicht mehr aus `PORT_UI` geraten); `db/laden-anlegen.sql`
gegen `debian-supabase-db-1` als `supabase_admin`, Passwort über die Umgebung, nie über
`argv`; `docker compose --env-file deploy/laeden/<name>.env up -d --build <name>-mcp
<name>-ui` (namentlich, nie nacktes `up -d` — das würde `<name>-auto` mitstarten);
`deploy/benutzer-anlegen.sh <name>` (interaktiv: Name, Rolle, Passwort zweimal), das
zusätzlich `UI_SESSION_SECRET` setzt und `<name>-ui` neu startet.

Jeder dieser vier Schritte ist einzeln geprüft und bewährt (Ivans Laden läuft damit). Die
Aufgabe hier ist **nicht**, sie neu zu schreiben, sondern sie aus der Oberfläche heraus
auszulösen.

### 1.2 Der gefährlichste Fund beim Entwerfen

`./auftraege:/auftraege` (`docker-compose.yml:252`) ist ein schreibbarer Mount im Dienst
`sales-mcp:` — und **genau dieser Dienstblock läuft für jeden Laden**, nicht nur den
Basis-Laden. `ivan-mcp` hat also heute schon denselben Zugriff auf denselben Ordner wie
`sales-mcp`, und `deploy/auftrag-ausfuehren.sh` (vom Wirt aus, systemd-Pfad-Dienst) führt
aus, was dort liegt, **ohne zu unterscheiden, aus welchem Laden es kam**. Das war schon in
der Schlussprüfung des vorigen Plans als K5 notiert, dort für harmlosere Auftragstypen.

Eine neue Fähigkeit „Laden anlegen" auf demselben Weg würde eine erheblich mächtigere Tür
in dasselbe Schloss einbauen: Ivan könnte theoretisch einen Auftrag ablegen, der einen
weiteren Laden mit vollen Wirtsrechten erzeugt. Das wäre eine Rückkehr zu genau dem Fehler,
den K1 gerade geschlossen hat.

### 1.3 Warum die Datenbank die bessere Grenze ist — und keine neue Mount-Lösung nötig ist

`sales-ui` hat **keinen** Mount auf `/auftraege` — nur `sales-mcp`. Ein Ordner-Ansatz hätte
also einen zweiten, neuen Mount für `sales-ui` gebraucht, dazu eine Compose-Zusatzdatei
(wie `docker-compose.openwa.yml`), die bei **jedem** Update des Basis-Ladens mitgeführt
werden müsste — sonst verschwindet der Mount beim nächsten Neuerzeugen still, genau das
Muster, das den Notfall vom 16.09.2026 verursacht hat (K4).

Stattdessen: eine neue Tabelle **im Schema `sales`**. Ivans `ivan-mcp`/`ivan-ui` verbinden
als `sales_app_ivan`, der laut K1-Fix **kein** Recht auf das Schema `sales` hat — die
Datenbank verweigert den Zugriff von selbst, ohne dass diese Spec etwas Neues dafür bauen
muss. Dieselbe geprüfte Mauer trägt mit.

`ui.py` importiert bereits `server` und benutzt `server._q(...)` für alle Lese-/
Schreibzugriffe (siehe z. B. die Passwort-Reset-Route) — der Weg „Oberfläche schreibt eine
Zeile, ein Wirt-Skript liest sie ab" ist damit ohne neuen Code auf der `ui.py`-Seite offen.

### 1.4 Rollen-Tor, wie es heute funktioniert

`_pfad_erlaubt(rolle, pfad)` (`ui.py:520-525`) ist heute eine **Ausschlussliste**: Sie
lässt jede Rolle auf jeden Pfad, außer der schmalen Rolle `kalender`, die nur auf eine
kurze Liste beschränkt ist. Das neue Werkzeug braucht die **umgekehrte** Form — ein Pfad,
der für alle außer einer bestimmten Rolle gesperrt ist, und zusätzlich nur im Basis-Laden
existieren darf. Beide Enden dieses Tors — `AnmeldeWache.__call__` (`ui.py:566`, das echte
403) und `_seitenleiste` (blendet den Menüpunkt aus) — rufen heute dieselbe Funktion auf;
das neue Werkzeug braucht eine zweite, kleine Prüfung, die an beiden Stellen greift.

### 1.5 Kein JavaScript, aber ein bestehendes Muster für „warten auf ein Ergebnis"

Die ganze Oberfläche hat `default-src 'none'` — kein Skript kann selbstständig nachfragen.
`_seite(titel, rumpf, status, refresh=None)` (`ui.py:1311-1314`) unterstützt bereits ein
reines `<meta http-equiv="refresh" content="N">` — eingesetzt heute für die
WhatsApp-Statusseite. Genau dieses Muster trägt die neue Seite: `refresh=5`, solange der
Auftrag offen oder in Arbeit ist, `refresh=None`, sobald ein Ergebnis feststeht.

### 1.6 Ports, gemessen

Bestehende Läden: `sales` → 18894/8791/12785, Serve 443. `ivan` → 18895/8792/12786, Serve
8445 (8444 war durch einen fremden nginx belegt — der Serve-Port lässt sich **nicht** aus
einem festen Versatz ableiten, er muss geprüft werden, genau wie die drei anderen). Die
Prüfung selbst existiert bereits in `deploy/laden-anlegen.sh` (`ss -tlnH "sport = :$p"`) —
nur als Ablehnung bei Kollision, nicht als Suche. Die neue Komponente muss suchen, nicht
nur ablehnen.

---

## 2. Was gebaut wird

### 2.1 Eine neue Tabelle, nur im Basis-Schema

```sql
create table sales.admin_auftraege (
  id            uuid primary key default gen_random_uuid(),
  art           text not null check (art = 'laden_anlegen'),
  name          text not null check (name ~ '^[a-z][a-z0-9_]{0,30}$'),
  angefordert_von text not null,
  status        text not null default 'offen'
                check (status in ('offen','laeuft','erfolg','fehler')),
  ergebnis      jsonb,
  fehler        text,
  erstellt_am   timestamptz not null default now(),
  erledigt_am   timestamptz
);
```

Der `art`-CHECK ist bewusst auf einen einzigen Wert eng — dieselbe Tabelle für eine zweite
Auftragsart zu öffnen ist ein späterer, bewusster Schritt, kein Vorgriff hier. `sales_app`
(die Kennung, mit der `sales-mcp`/`sales-ui` verbinden) bekommt `select, insert` — **kein
update, kein delete**: die Oberfläche legt einen Auftrag an, sie ändert ihn nicht mehr.
Nur der Wirt (als `supabase_admin`, über `docker exec`) setzt `status`/`ergebnis`/`fehler`.

### 2.2 Die neue Seite

Pfad `/team/laden-anlegen`. Sichtbar und betretbar **nur**, wenn beides gilt: die Rolle der
Anmeldung ist `freigeben`, **und** `server.SCHEMA == "sales"` — der zweite Teil ist der
Grund, warum dieser Knopf in Ivans Oberfläche nie existiert, selbst wenn er später die
Rolle `freigeben` bekäme: sein Prozess läuft mit `SCHEMA = "sales_ivan"`, die Bedingung
schlägt fehl, bevor die Rolle überhaupt geprüft wird.

**GET:** ein Formular mit einem Feld (Name, Muster `^[a-z][a-z0-9_]{0,30}$` — dasselbe wie
`server.SCHEMA_MUSTER` ohne das `sales`-Präfix), darunter eine Liste der letzten Aufträge
mit Status. Ein offener oder laufender Auftrag setzt `refresh=5`; ein erledigter (Erfolg
oder Fehler) `refresh=None`.

**POST:** prüft das Namensmuster serverseitig (die Prüfung im Formular ist keine
Zusicherung), fügt eine Zeile mit `status='offen'` ein — `angefordert_von` aus
`request.scope["benutzer_name"]`, derselben Quelle, die `_gesichert_seite` schon für jede
andere Seite befüllt — und leitet auf GET um.

Ein doppelt abgeschickter Name braucht **keine** eigene Sperre: `deploy/laden-anlegen.sh`
weigert sich bereits, eine bestehende `deploy/laeden/<name>.env` zu überschreiben (siehe
Plan vom 16.09.2026). Zwei Aufträge mit demselben Namen laufen also nacheinander durch
denselben Zeitgeber-Takt; der zweite scheitert an diesem bestehenden Schutz und landet mit
`status='fehler'`, nicht in einem stillen Doppelzustand.

**Ergebnisanzeige bei Erfolg:** Wegwerf-Passwort, der gewählte Serve-Port mit dem Hinweis,
dass `tailscale serve --https <port> http://127.0.0.1:<port-ui>` und die Zugriffsregel für
den neuen Menschen noch von Hand folgen (Teil des dritten Untervorhabens, hier nicht
gebaut). **Bei Fehler:** was bereits fertig wurde und was nicht — nie „erfolgreich", wenn
es das nicht war (siehe §2.4).

### 2.3 Der Wirt-Zeitgeber

Ein neuer, eigener systemd-Dienst (`sales-admin-auftraege.timer`/`.service`,
`OnUnitActiveSec=20s`) — **nicht** an `deploy/auftrag-ausfuehren.sh` (das bedient den
geteilten Ordner) und **nicht** an `deploy/wache.sh` (15 Minuten, zu träge für eine Aktion,
die der Betreiber bewusst auslöst und auf deren Ergebnis er wartet) angehängt.

Das Skript `deploy/admin-auftrag-ausfuehren.sh`:

1. `select id, name from sales.admin_auftraege where art='laden_anlegen' and
   status='offen' order by erstellt_am limit 1` — über `docker exec debian-supabase-db-1
   psql -U supabase_admin`, dieselbe Verbindung, die schon `db/laden-anlegen.sql` fährt.
2. Sofort `status='laeuft'` setzen, damit ein zweiter Zeitgeber-Durchlauf denselben
   Auftrag nicht doppelt aufgreift.
3. Vier freie Ports suchen — **Wiederverwendung** der Prüfschleife aus
   `deploy/laden-anlegen.sh`, nicht deren zweite Fassung: probieren ab dem nächsten
   bekannten Versatz, bei Kollision weiterzählen, bis vier freie gefunden sind.
4. Ein Kennwort erzeugen (dasselbe Muster wie bisher von Hand:
   `openssl rand -base64 24 | tr -d '/+=' | head -c 32`).
5. `deploy/laden-anlegen.sh <name> <gateway> <ui> <openwa> <serve>` aufrufen — **dasselbe
   Skript, unverändert**, keine Parallel-Implementierung.
6. Das erzeugte Passwort aus `deploy/laeden/<name>.env` lesen, `db/laden-anlegen.sql`
   ausführen (Passwort über die Umgebung, nie über `argv` — wie bisher).
7. `docker compose --env-file deploy/laeden/<name>.env up -d --build <name>-mcp
   <name>-ui` — **nur diese zwei Dienste**, aus demselben Grund wie bei Ivan: die übrigen
   sieben brauchen Zugangsdaten, die es für einen frisch angelegten Menschen noch nicht
   gibt.
8. Ein Wegwerf-Passwort erzeugen, `deploy/benutzer-anlegen.sh <name>` mit den Werten
   `<name>`, `freigeben`, Passwort zweimal über `stdin` füttern — **dasselbe Skript**,
   das auch Ivans Konto gesetzt hat.
9. `update sales.admin_auftraege set status='erfolg', ergebnis=<jsonb mit Passwort,
   Serve-Port, Hinweistext>, erledigt_am=now() where id=<id>`.

### 2.4 Fehlerbehandlung: die Meldung darf nie mehr behaupten als geschehen ist

Jeder der neun Schritte kann für sich scheitern. Das Skript hält nach jedem Schritt fest,
was **bereits** getan wurde (Schema angelegt? Container gestartet? Konto erzeugt?) und
schreibt bei einem Abbruch `status='fehler'` mit genau dieser Liste in `ergebnis` und der
Fehlermeldung in `fehler` — **nie** `status='erfolg'`, wenn auch nur ein Schritt fehlt.
Das ist dieselbe Lehre, die W6 aus dem vorigen Plan bereits gezogen hat
(„wiederhergestellt" durfte nicht mehr behaupten, als das Skript tatsächlich tat) und wird
hier von Anfang an eingebaut, nicht nachträglich gefunden.

Ein Auftrag, der schon `status='laeuft'` trägt, wenn das Skript abstürzt (z. B. durch einen
Neustart des Wirts mitten im Ablauf), bleibt dort stehen — ein Startwert `laeuft`, der
älter als eine bestimmte Schwelle ist (z. B. 10 Minuten), wird beim nächsten Durchlauf als
`status='fehler'` markiert statt endlos zu warten.

---

## 3. Entscheidungen und warum

| Frage | Entscheidung | Warum |
|---|---|---|
| Wie weit geht der Knopf? | **Bis zur Anmeldung** — Schema, Benutzer, zwei Container, Konto | Alles Weitere (Tailscale, vier Kanäle) braucht ein fremdes Gerät bzw. fremde Zugangsdaten und lässt sich nicht automatisieren |
| Ports und Kennwort? | **Vollautomatisch** | Portkollisionen (wie der fremde nginx auf 8444) hat schon einmal Zeit gekostet; weniger Eingabefläche ist weniger Fehlerfläche |
| Übergabestelle Oberfläche → Wirt? | **Datenbanktabelle im Basis-Schema**, nicht der geteilte Auftrags-Ordner | Der Ordner ist heute zwischen allen Läden geteilt (K5-Familie); die Datenbanktrennung ist bereits bewiesen und braucht keinen neuen Mount |
| Wie schnell reagiert der Wirt? | **Eigener 20-Sekunden-Zeitgeber**, nicht die 15-Minuten-Wache | Eine bewusst ausgelöste Aktion, auf deren Ergebnis der Betreiber wartet, verdient keine Viertelstunde Blindflug |
| Wer darf den Knopf sehen? | **Nur Rolle `freigeben`, nur im Basis-Laden** (`server.SCHEMA == "sales"`) | Eine neue Rolle für eine einzige Fähigkeit wäre mehr Aufwand, als sie heute einbringt; die Schema-Prüfung verhindert, dass der Knopf je in einem zweiten Laden auftaucht |

---

## 4. Nicht im Umfang

* **Tailscale-Einladung automatisieren** — eigene Spec, eigene Technik (fremde API).
* **Systemmails über die Absenderadresse des Betreibers an fremde Postfächer** — eigene
  Spec; berührt die Datentrennung und verdient eigene Sorgfalt.
* **Mehr als zwei Dienste beim Anlegen starten.** Die übrigen sieben Dienste eines neuen
  Ladens bleiben Handarbeit, sobald die vier Kanäle stehen (wie bei Ivan).
* **Eine engere Rolle als `freigeben` für dieses Werkzeug.** Kann bei Bedarf nachgezogen
  werden (§3), ist hier ausdrücklich nicht gebaut.
* **Automatische Ports für bereits laufende Läden ändern.** Diese Spec legt ausschließlich
  neue Läden an.

---

## 5. Prüfung

1. **Der Knopf existiert nicht in Ivans Oberfläche**, unabhängig von seiner Rolle — Tor:
   `server.SCHEMA` in seinem Prozess ist `sales_ivan`, die Bedingung schlägt fehl.
2. **Ivans `ivan-mcp` kann die Tabelle nicht einmal lesen.** Mit seiner Datenbankkennung
   `select * from sales.admin_auftraege` versuchen — erwartet: `permission denied for
   table admin_auftraege`, nicht ein leeres Ergebnis.
3. **Ein Auftrag mit vertipptem Namen** (z. B. Großbuchstaben, Bindestrich) wird von der
   Oberfläche **serverseitig** abgewiesen, bevor eine Zeile entsteht — nicht erst vom Wirt.
4. **Zwei aufeinanderfolgende Anläufe kollidieren nicht.** Ein zweiter Auftrag mit
   `status='laeuft'`, während der erste noch läuft, wird vom Zeitgeber übersprungen (nicht
   doppelt ausgeführt).
5. **Ein absichtlich kaputter Lauf** (z. B. Schema wird angelegt, dann der Container-Start
   künstlich zum Scheitern gebracht) endet mit `status='fehler'`, **nie** `'erfolg'`, und
   `ergebnis` nennt genau, was bereits stand.
6. **Der ganze Weg, einmal echt.** Ein Testlauf über die Oberfläche legt einen Laden an;
   danach: `db-identitaet <name> ok` in `deploy/smoke.sh`, eine echte Anmeldung mit dem
   ausgegebenen Wegwerf-Passwort, und — wie bei Ivan — die Gegenprobe, dass der neue Laden
   **keinen** Zugriff auf `sales` hat.
7. **Der Basis-Laden bleibt unberührt**, wenn ein Auftrag scheitert — `docker compose
   config` ohne gesetzte Variablen löst weiterhin exakt wie vorher auf.
