# Mehrere sales-claw-Instanzen auf einem Wirt

**Datum:** 2026-09-11
**Status:** Design. Nachgelagertes Vorhaben — erst umzusetzen, wenn das Team tatsächlich
wächst.
**Auslöser:** Jedes Teammitglied soll eine eigene sales-claw-Instanz bekommen, alle auf der
VM `vibemind-offload-1` (Betreiber-Entscheidung 2026-09-10).

---

## 1. Der Befund: heute startet keine zweite Instanz

sales-claw ist Einbetreiber-Software. In `docs/01_OVERVIEW.md` und
`docs/02_ARCHITECTURE.md` kommen weder „Team" noch „Mandant" vor. Gemessen am
`docker-compose.yml`:

| Was | Wert | Folge bei einer zweiten Instanz |
|---|---|---|
| Projektname | `name: sales-claw` (fest) | Compose-Projekte kollidieren |
| Containernamen | **neun**, alle fest: `sales-claw`, `sales-mcp`, `sales-dispatch`, `sales-inbox`, `sales-mail`, `sales-linkedin`, `sales-auto`, `sales-stt`, `sales-ui` | Start scheitert sofort am ersten Namen |
| Volumes | `sales-claw-state`, `sales-claw-keys`, `sales-sprachnachrichten`, `sales-stt-modelle` — **literal benannt**, das Compose-Präfix ist ausdrücklich unterdrückt | **Die WhatsApp-Anmeldung würde geteilt** — zwei Instanzen an derselben Sitzung |
| Port | `127.0.0.1:18894` | belegt |

Der gefährlichste Punkt ist `sales-claw-state`: Dort liegt die WhatsApp-Anmeldung. Zwei
Instanzen, die sich dieses Volume teilen, greifen auf dieselbe Sitzung zu.

**Was bereits mehrfachtauglich ist:**

* `SALES_DB_SCHEMA` ist konfigurierbar (heute `sales` bzw. `sales_test`) — mehrere Schemas
  in einer Datenbank sind vorgesehen.
* Die `benutzer`-Tabelle mit Rollen (`lesen`, `freigeben`) existiert samt Anmeldung.
* Das `compliance`-Schema für die Sperrliste liegt **außerhalb** des Instanz-Schemas
  (`sperrliste.py` leitet es getrennt ab). Das ist ein Glücksfall: Eine Verbotsliste, die
  **alle** Instanzen teilen, ist genau richtig — wer Werbung widerspricht, hat sie bei
  jedem im Team widersprochen.

---

## 2. Was gebaut wird

**Ein Instanzname wird zum Parameter.** Aus `sales-claw` wird `sales-claw-<name>`:
Projektname, Containernamen, Volumes und Port leiten sich daraus ab. Eine Instanz ohne
Namen bleibt `sales-claw` — die bestehende Installation ändert sich nicht.

**Je Instanz ein Datenbankschema**, in derselben Datenbank. `compliance` bleibt gemeinsam.

**Je Instanz ein WhatsApp-Pairing.** Jeder schreibt von seiner eigenen Nummer, also braucht
jede Instanz ihr eigenes `state`-Volume und ihre eigene Anmeldung.

**Ein Einstiegspunkt für Menschen.** Statt neun Ports merkt sich niemand etwas: eine
Übersicht, die zu den Oberflächen der Instanzen führt, erreichbar über Tailscale wie heute.

**Betrieb bleibt beherrschbar:** Updates, Sicherung und Wiederherstellung müssen alle
Instanzen erfassen, ohne dass jemand neun Befehle je Person tippt. `deploy/update.sh` und
`deploy/sicherung.sh` werden instanzbewusst.

---

## 3. Offene Entscheidungen

* **Eine Datenbank oder je Instanz eine?** Ein Schema je Instanz in einer Datenbank ist
  billiger im Betrieb (eine Sicherung, ein Server); getrennte Datenbanken trennen sauberer,
  falls Instanzen später auf verschiedene Wirte ziehen.
* **Ressourcen.** Neun Dienste je Person, dazu Spracherkennung — bei acht Personen sind das
  über siebzig Container. Vor der Umsetzung ist zu messen, was eine Instanz im Leerlauf
  wirklich braucht, und ob geteilte Dienste (Spracherkennung, Modell-Volume) sinnvoll sind.
  `sales-stt-modelle` ist ein 300-MB-Download, der bewusst getrennt liegt — das ist ein
  Kandidat zum Teilen.
* **Wer darf was sehen?** Die `benutzer`-Tabelle ist heute je Instanz. Ob es eine
  instanzübergreifende Anmeldung braucht, entscheidet sich mit der Team-Sicht aus
  `2026-09-11-team-terminabstimmung-design.md`.

---

## 4. Nicht im Umfang

* **Mandantenfähigkeit in der Anwendung** (eine Instanz, mehrere Benutzer mit getrennten
  Daten). Das wäre ein Umbau der Anwendung statt des Deployments — deutlich größer, und
  für ein Team dieser Größe nicht nötig.
* **Verteilung auf mehrere Wirte.** Erst wenn eine VM nicht mehr reicht.

---

## 5. Prüfung

1. Zwei Instanzen laufen gleichzeitig, ohne dass ein Name, Volume oder Port kollidiert.
2. Jede hat ihre **eigene** WhatsApp-Anmeldung; ein erneutes Pairing der einen lässt die
   andere unberührt.
3. Eine Sperre in der gemeinsamen Verbotsliste wirkt in **beiden** Instanzen.
4. Ein Update erfasst beide, ohne dass jemand Befehle je Instanz wiederholt.
5. Die Sicherung enthält die Daten beider Instanzen, und eine Wiederherstellung stellt
   **eine** davon wieder her, ohne die andere anzufassen.
