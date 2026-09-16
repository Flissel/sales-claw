# Plan 1: Der zweite Laden steht und ist getrennt

> **Für agentische Arbeiter:** ERFORDERLICHE UNTER-FERTIGKEIT: `superpowers:subagent-driven-development` (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen. Schritte benutzen Kästchen (`- [ ]`) zur Verfolgung.

**Ziel:** Ein zweiter Mensch bekommt einen eigenen sales-claw-Laden auf derselben VM — eigenes Schema, eigener Datenbankbenutzer, eigene Container, eigene Volumes, eigene Oberfläche auf eigenem Port — ohne dass der bestehende Laden sich in irgendeiner Weise ändert.

**Architektur:** Der Instanzname wird ein Compose-Parameter (`${LADEN_PRAEFIX:-sales}`), was Projektname, Containernamen, Volumes und Host-Ports ableitbar macht. Die Trennung der Daten liegt in der Datenbank: ein Schema und ein Benutzer je Laden, ohne Rechte auf das fremde Schema. Geteilt bleiben nur `compliance` (die Sperrliste) und `sales-stt-modelle` (ein Modell-Download, keine Daten).

**Tech Stack:** Docker Compose (Variablensubstitution), PostgreSQL/Supabase, Python 3.12 + psycopg, pytest, Bash, Tailscale Serve.

**Spec:** `docs/superpowers/specs/2026-09-16-getrennte-laeden-design.md` — insbesondere §2.1, §2.2, §2.6, §5 (Tore 1, 2, 8, 10, 11, 12, 13) und §7 (dieser Plan ist dort „Plan 1").

## Global Constraints

Jede Aufgabe muss diese Punkte einhalten. Die Werte sind wörtlich aus der Spec bzw. aus der am 16.09.2026 gemessenen Anlage übernommen.

* **Der bestehende Laden darf sich nicht ändern.** Nach jeder Aufgabe muss `docker compose config` ohne gesetzte Umgebungsvariablen **exakt** dieselben Werte auflösen wie heute: Projektname `sales-claw`; Container `sales-claw`, `sales-mcp`, `sales-dispatch`, `sales-inbox`, `sales-mail`, `sales-telegram`, `sales-linkedin`, `sales-auto`, `sales-stt`, `sales-ui`, `openwa`; Volumes `sales-claw-state`, `sales-claw-keys`, `sales-sprachnachrichten`, `sales-stt-modelle`, `openwa-data`; Host-Ports `18894`, `8791`, `12785`.
* **`sales-claw-state` trägt die WhatsApp-Anmeldung.** Ein falsch aufgelöster Name heißt: der Gateway hängt an einem leeren Volume und zeigt wieder einen QR-Code — ohne Fehlermeldung.
* **`sales-stt-modelle` wird GETEILT, nicht vervielfacht** (300-MB-Download, Modell statt Daten). Es bleibt wörtlich benannt und wird **nicht** parametrisiert.
* **`compliance` bleibt gemeinsam.** Wer Werbung widerspricht, hat allen widersprochen.
* **Die Rolle je Laden bekommt kein DDL und kein DELETE** — wie `sales_app` heute (`db/provision.sql:198-204`).
* **Keine Geheimnisse ins Git.** Die Umgebungsdatei eines Ladens enthält den DSN samt Passwort und gehört in `.gitignore`; committet wird nur eine Vorlage.
* **Zu jedem Test gehört die Frage: welche kaputte Fassung fängt er?** Diese Woche waren fünfzehn Tests grün, die auch ohne die Änderung grün gewesen wären. Jeder neue Test in diesem Plan trägt die Antwort als Kommentar.
* **Am laufenden System messen.** Viermal in dieser Woche war der Code richtig und die Suite grün, während die ausgelieferte Umgebung kaputt war. Tests, die Docker brauchen, gehören zusätzlich in `deploy/smoke.sh`.
* **Nie `git add -A`.** Nur die eigenen Dateien der jeweiligen Aufgabe stagen — dieses Repository wird von mehreren Sitzungen gleichzeitig bespielt.
* **Vor jeder Aufgabe `git fetch`.** Der Zweig `feat/stufe-1-fundament` wird parallel bespielt.

---

## Dateien, die dieser Plan anfasst

| Datei | Verantwortung | Aufgabe |
|---|---|---|
| `docker-compose.yml` | zehn Dienste, vier Volumes, zwei Host-Ports — Instanzname wird Parameter | 1 |
| `docker-compose.openwa.yml` | die WhatsApp-Schnittstelle `openwa` — derselbe Parameter | 1 |
| `deploy/laeden/beispiel.env` | **neu** — Vorlage für die Umgebungsdatei eines Ladens | 1 |
| `.gitignore` | `deploy/laeden/*.env` außer der Vorlage | 1 |
| `sales-mcp/tests/test_laden_parameter.py` | **neu** — beweist, dass der bestehende Laden unverändert auflöst | 1 |
| `sales-mcp/server.py:81-83` | die Schema-Wache prüft nach Muster statt nach Liste | 2 |
| `sales-mcp/tests/test_schema_wache.py` | **neu** — erlaubte und verbotene Schemanamen | 2 |
| `db/laden-anlegen.sql` | **neu** — Schema, Tabellen, Benutzer, Rechte für einen Laden | 3 |
| `db/pruefe-laden.sql` | **neu** — Nachweis, dass die Trennung hält | 3 |
| `deploy/laden-anlegen.sh` | **neu** — führt SQL und Umgebungsdatei zusammen | 4 |
| `deploy/update.sh` | erfasst alle Läden statt nur den einen | 5 |
| `deploy/sicherung.sh` | sichert alle Läden | 5 |
| `deploy/wiederherstellen.sh` | stellt **einen** Laden wieder her | 5 |
| `deploy/smoke.sh` | die Tore, die Docker brauchen | 1, 6, 7 |
| `docs/03_RUNBOOK.md` | Abschnitt „Einen zweiten Laden anlegen" | 4, 6, 7 |
| `docs/11_INBETRIEBNAHME.md` | die vier Kanäle eines neuen Ladens | 7 |

---

## Task 1: Der Instanzname wird ein Parameter

**Files:**
- Modify: `docker-compose.yml` (Zeile 14 `name:`, zehn `container_name:`, Volume-Block ab Zeile 637, Ports Zeile 70 und 630-631)
- Modify: `docker-compose.openwa.yml` (Zeile 30 `name:`, Zeile 37 `container_name:`, Zeile 189-190 Volume, Ports ab Zeile 148)
- Create: `deploy/laeden/beispiel.env`
- Modify: `.gitignore`
- Test: `sales-mcp/tests/test_laden_parameter.py`
- Modify: `deploy/smoke.sh`

**Interfaces:**
- Produces: die Umgebungsvariablen `LADEN_PRAEFIX` (Vorgabe `sales`), `LADEN_PROJEKT` (Vorgabe `sales-claw`), `PORT_GATEWAY` (Vorgabe `18894`), `PORT_UI` (Vorgabe `8791`), `PORT_OPENWA` (Vorgabe `12785`). Aufgabe 4 schreibt sie in `deploy/laeden/<name>.env`.

- [ ] **Step 1: Den Test schreiben, der den bestehenden Laden schützt**

Neue Datei `sales-mcp/tests/test_laden_parameter.py`:

```python
"""Der Instanzname ist ein Parameter — und der bestehende Laden merkt nichts.

WARUM DIESER TEST DER WICHTIGSTE DIESES PLANS IST
-------------------------------------------------------------------------
In `sales-claw-state` liegt die WhatsApp-Anmeldung des Betreibers. Loest die
Parametrisierung den Volume-Namen auch nur um ein Zeichen anders auf, haengt
der Gateway an einem LEEREN Volume und zeigt wieder einen QR-Code — ohne
Fehlermeldung, ohne Absturz. Niemand merkt es, bis ein Kunde nicht antwortet.

WELCHE KAPUTTE FASSUNG FAENGT DIESER TEST?
-------------------------------------------------------------------------
* `${LADEN_PRAEFIX}` ohne Vorgabewert -> loest zu `-claw-state` auf (leer + Rest)
* ein vertippter Vorgabewert (`${LADEN_PRAEFIX:-sale}`)
* `sales-stt-modelle` versehentlich mitparametrisiert — das Modell-Volume
  wird GETEILT, nicht vervielfacht (Spec §2.6)
* ein vergessener `container_name`, der beim zweiten Laden kollidieren wuerde
* ein vergessener Host-Port, der beim zweiten Laden kollidieren wuerde

Der Test braucht Docker. Er wird uebersprungen, wo keins ist — und steht
deshalb ZUSAETZLICH in `deploy/smoke.sh`, damit er auf der VM wirklich
laeuft. Ein uebersprungener Test ist kein gruener Test.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]

ohne_docker = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="braucht Docker; laeuft zusaetzlich in deploy/smoke.sh")


def _aufgeloest(datei: str, umgebung: dict | None = None) -> dict:
    """`docker compose config` mit LEERER Umgebung ausser dem Uebergebenen.

    `env=` statt `os.environ` ist der Punkt: erbte der Aufruf die Umgebung
    der Testmaschine, koennte ein dort zufaellig gesetztes LADEN_PRAEFIX das
    Ergebnis faelschen — und der Test waere gruen, ohne etwas zu pruefen.
    """
    roh = subprocess.run(
        ["docker", "compose", "-f", datei, "config", "--format", "json"],
        cwd=WURZEL, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **(umgebung or {})})
    assert roh.returncode == 0, roh.stderr
    return json.loads(roh.stdout)


def _hostports(dienst: dict) -> set[str]:
    return {f"{p.get('host_ip', '')}:{p['published']}"
            for p in dienst.get("ports", [])}


@ohne_docker
def test_ohne_umgebung_bleibt_alles_wie_heute():
    """Der gemessene Stand vom 16.09.2026, wortwoertlich."""
    cfg = _aufgeloest("docker-compose.yml")
    assert cfg["name"] == "sales-claw"
    assert set(cfg["services"]) == {
        "sales-claw", "sales-mcp", "sales-dispatch", "sales-inbox",
        "sales-mail", "sales-telegram", "sales-linkedin", "sales-auto",
        "sales-stt", "sales-ui"}
    assert {d["container_name"] for d in cfg["services"].values()} == {
        "sales-claw", "sales-mcp", "sales-dispatch", "sales-inbox",
        "sales-mail", "sales-telegram", "sales-linkedin", "sales-auto",
        "sales-stt", "sales-ui"}
    assert {v["name"] for v in cfg["volumes"].values()} == {
        "sales-claw-state", "sales-claw-keys",
        "sales-sprachnachrichten", "sales-stt-modelle"}
    assert _hostports(cfg["services"]["sales-claw"]) == {"127.0.0.1:18894"}
    assert _hostports(cfg["services"]["sales-ui"]) == {"127.0.0.1:8791"}


@ohne_docker
def test_ohne_umgebung_bleibt_openwa_beim_ersten_laden():
    """ACHTUNG: Container und Volume werden in Schritt 4 UMBENANNT.

    Heute heissen sie `openwa` / `openwa-data`, danach `sales-openwa` /
    `sales-openwa-data`. Dieser Test beschreibt den Stand NACH der
    Aenderung — er ist in Schritt 2 also rot, und das ist richtig so.
    Das Volume wird in Schritt 4 umkopiert, damit die Anmeldung bleibt.
    """
    cfg = _aufgeloest("docker-compose.openwa.yml")
    assert cfg["name"] == "sales-claw"
    assert cfg["services"]["openwa"]["container_name"] == "sales-openwa"
    assert {v["name"] for v in cfg["volumes"].values()} == {"sales-openwa-data"}
    assert _hostports(cfg["services"]["openwa"]) == {"127.0.0.1:12785"}


@ohne_docker
def test_zweiter_laden_kollidiert_in_nichts():
    """Kein Name und kein Port darf sich mit dem ersten Laden ueberschneiden.

    Das ist die eigentliche Behauptung des Plans. Ohne diesen Test koennte
    ein vergessener `container_name` erst beim Hochfahren auffallen — mit
    einem halb gestarteten zweiten Laden.
    """
    u = {"LADEN_PRAEFIX": "ivan", "LADEN_PROJEKT": "ivan-claw",
         "PORT_GATEWAY": "18895", "PORT_UI": "8792", "PORT_OPENWA": "12786"}
    erst = _aufgeloest("docker-compose.yml")
    zweit = _aufgeloest("docker-compose.yml", u)
    erst_wa = _aufgeloest("docker-compose.openwa.yml")
    zweit_wa = _aufgeloest("docker-compose.openwa.yml", u)

    assert zweit["name"] == "ivan-claw"

    def namen(c):
        return {d["container_name"] for d in c["services"].values()}

    def volumes(c):
        return {v["name"] for v in c["volumes"].values()}

    def ports(c):
        return {p for d in c["services"].values() for p in _hostports(d)}

    assert not (namen(erst) | namen(erst_wa)) & (namen(zweit) | namen(zweit_wa))
    assert not ports(erst) & ports(zweit)
    assert not ports(erst_wa) & ports(zweit_wa)

    # sales-stt-modelle ist die AUSNAHME: geteilt, nicht vervielfacht.
    gemeinsam = volumes(erst) & volumes(zweit)
    assert gemeinsam == {"sales-stt-modelle"}, (
        "genau ein Volume darf geteilt sein — das Modellverzeichnis")
```

- [ ] **Step 2: Test laufen lassen, er muss fehlschlagen**

Run: `cd sales-mcp && python -m pytest tests/test_laden_parameter.py -v`
Erwartet, genau zwei rote Tests:

* `test_zweiter_laden_kollidiert_in_nichts` — ohne Parametrisierung liefern beide Aufrufe dieselben Namen, die Schnittmenge ist nicht leer.
* `test_ohne_umgebung_bleibt_openwa_beim_ersten_laden` — er beschreibt den Stand **nach** der Umbenennung (`sales-openwa` statt `openwa`).

Grün ist bereits `test_ohne_umgebung_bleibt_alles_wie_heute` — er beschreibt den Ist-Zustand und muss über den ganzen Plan hinweg grün **bleiben**. Wird er rot, ist der bestehende Laden beschädigt.

- [ ] **Step 3: `docker-compose.yml` parametrisieren**

Zeile 14:
```yaml
name: ${LADEN_PROJEKT:-sales-claw}
```

Alle zehn `container_name:`-Zeilen nach diesem Muster (Zeilen 19, 89, 160, 215, 271, 332, 394, 451, 517, 538):
```yaml
    container_name: ${LADEN_PRAEFIX:-sales}-claw
    container_name: ${LADEN_PRAEFIX:-sales}-mcp
    container_name: ${LADEN_PRAEFIX:-sales}-dispatch
    container_name: ${LADEN_PRAEFIX:-sales}-inbox
    container_name: ${LADEN_PRAEFIX:-sales}-mail
    container_name: ${LADEN_PRAEFIX:-sales}-telegram
    container_name: ${LADEN_PRAEFIX:-sales}-linkedin
    container_name: ${LADEN_PRAEFIX:-sales}-auto
    container_name: ${LADEN_PRAEFIX:-sales}-stt
    container_name: ${LADEN_PRAEFIX:-sales}-ui
```

Zeile 70 (Gateway-Port) — nur die HOST-Seite, der Container-Port bleibt:
```yaml
      - "127.0.0.1:${PORT_GATEWAY:-18894}:18894"
```

Zeilen 630-631 (UI-Ports):
```yaml
      - "127.0.0.1:${PORT_UI:-8791}:8791"
      - "${UI_TAILSCALE_IP:-127.0.0.1}:${PORT_UI:-8791}:8791"
```

Volume-Block ab Zeile 637 — **`sales-stt-modelle` bleibt wörtlich**:
```yaml
volumes:
  # Explizite name:-Angabe, sonst prefixt Compose mit dem Projektnamen.
  # Der Praefix ist seit 16.09.2026 ein Parameter (Spec 2026-09-16 §2.6);
  # ohne gesetzte Variable loest er auf die bisherigen Namen auf — daran
  # haengt die WhatsApp-Anmeldung des bestehenden Ladens.
  sales-claw-state:
    name: ${LADEN_PRAEFIX:-sales}-claw-state
  sales-claw-keys:
    name: ${LADEN_PRAEFIX:-sales}-claw-keys
  sales-sprachnachrichten:
    name: ${LADEN_PRAEFIX:-sales}-sprachnachrichten
  # AUSNAHME, bewusst NICHT parametrisiert: ein 300-MB-Modelldownload ist
  # kein Kundeninhalt. Alle Laeden teilen ihn (Spec §2.6).
  sales-stt-modelle:
    name: sales-stt-modelle
```

- [ ] **Step 4: `docker-compose.openwa.yml` parametrisieren**

Zeile 30:
```yaml
name: ${LADEN_PROJEKT:-sales-claw}
```

Zeile 37 — der **Dienstschlüssel `openwa` bleibt unverändert**, nur der Containername wird abgeleitet. Das ist der Grund, warum `OPENWA_URL=http://openwa:2785` in `docker-compose.yml` unverändert bleiben kann: Compose vergibt den Netzwerk-Alias nach dem Dienstschlüssel, nicht nach `container_name`.
```yaml
    container_name: ${LADEN_PRAEFIX:-sales}-openwa
```

**Achtung — Abweichung vom Ist-Zustand:** der Container heißt heute `openwa`, nicht `sales-openwa`. Er muss deshalb **einmalig** umbenannt werden. Das Volume `openwa-data` bleibt wörtlich erhalten, die Anmeldung geht also nicht verloren. Passe den erwarteten Wert in `test_ohne_umgebung_bleibt_openwa_wie_heute` auf `sales-openwa` an und notiere den Schritt im Runbook (Aufgabe 4).

Ports ab Zeile 148:
```yaml
      - "127.0.0.1:${PORT_OPENWA:-12785}:2785"
```

Volume Zeile 189-190:
```yaml
  openwa-data:
    name: ${LADEN_PRAEFIX:-sales}-openwa-data
```

**Achtung, zweite Abweichung:** das Volume heißt heute `openwa-data`, nach der Änderung `sales-openwa-data`. Ein neues, leeres Volume bedeutet **Verlust der openwa-WhatsApp-Anmeldung**. Deshalb vor dem ersten Start umbenennen:

```bash
docker volume create sales-openwa-data
docker run --rm -v openwa-data:/alt -v sales-openwa-data:/neu alpine \
  sh -c 'cp -a /alt/. /neu/'
```

Das alte Volume bleibt als Sicherung liegen und wird erst gelöscht, wenn der Laden nachweislich ohne erneutes Pairing läuft.

- [ ] **Step 5: Vorlage und `.gitignore`**

Neue Datei `deploy/laeden/beispiel.env`:
```bash
# Vorlage fuer einen Laden. Kopieren nach deploy/laeden/<name>.env und
# ausfuellen. Die ausgefuellte Datei enthaelt den Datenbank-DSN samt
# Passwort und ist per .gitignore ausgeschlossen — sie gehoert NICHT ins
# Repository.
#
# Der bestehende Laden braucht KEINE solche Datei: alle Vorgabewerte in
# den Compose-Dateien loesen auf seinen bisherigen Stand auf.

LADEN_PRAEFIX=ivan
LADEN_PROJEKT=ivan-claw

# Host-Ports. Muessen sich von jedem anderen Laden unterscheiden —
# sales: 18894 / 8791 / 12785
PORT_GATEWAY=18895
PORT_UI=8792
PORT_OPENWA=12786

# Datenbank: eigenes Schema, eigener Benutzer (Aufgabe 3).
SALES_DB_SCHEMA=sales_ivan
SALES_DB_URL=postgresql://sales_app_ivan:PASSWORT@192.168.178.65:54322/postgres

# Die Tailscale-Adresse dieses Rechners, damit die Oberflaeche erreichbar
# ist. Leer lassen heisst: nur ueber Loopback.
UI_TAILSCALE_IP=100.67.177.45
```

An `.gitignore` anhängen:
```gitignore
# Umgebungsdateien der Laeden tragen DSN samt Passwort (Spec 2026-09-16).
# Nur die Vorlage gehoert ins Repository.
deploy/laeden/*.env
!deploy/laeden/beispiel.env
```

- [ ] **Step 6: Tests laufen lassen**

Run: `cd sales-mcp && python -m pytest tests/test_laden_parameter.py -v`
Erwartet: 3 passed.

Run: `cd sales-mcp && python -m pytest -q`
Erwartet: EXIT 0, keine Regression (Ausgangswert 1738 passed).

- [ ] **Step 7: Den Test in `deploy/smoke.sh` verankern**

Am Ende von `deploy/smoke.sh` anfügen:
```bash
# Die Compose-Aufloesung wird NUR hier wirklich geprueft: in der Suite
# ueberspringt der Test sich, wo kein Docker ist (Plan 2026-09-16, T1).
echo "== Compose-Aufloesung =="
( cd "$WURZEL/sales-mcp" && python -m pytest tests/test_laden_parameter.py -q ) \
  || { echo "FEHLER: Compose loest nicht wie erwartet auf"; exit 1; }
```

- [ ] **Step 8: Committen**

```bash
git add docker-compose.yml docker-compose.openwa.yml .gitignore \
        deploy/laeden/beispiel.env deploy/smoke.sh \
        sales-mcp/tests/test_laden_parameter.py
git commit -m "feat: Instanzname als Compose-Parameter, Vorgaben halten den bestehenden Laden"
```

---

## Task 2: Die Schema-Wache prüft nach Muster statt nach Liste

**Files:**
- Modify: `sales-mcp/server.py:81-83`
- Test: `sales-mcp/tests/test_schema_wache.py`

**Interfaces:**
- Consumes: nichts aus Aufgabe 1.
- Produces: `SALES_DB_SCHEMA` darf jeden Wert annehmen, der `^sales(_[a-z][a-z0-9_]{0,30})?$` erfüllt. Aufgabe 3 und 4 verlassen sich darauf.

**Abweichung von der Spec, bewusst:** Spec §6 Schritt 3 verlangt, die Wache „um den neuen Namen zu erweitern". Ein Muster erspart diesen Schritt bei jedem weiteren Menschen und ist gegen Einschleusung genauso streng — der Schemaname wird in `options=-c search_path=...` eingesetzt, das Muster lässt weder Leerzeichen noch Anführungszeichen noch Semikola zu. Schritt 3 der Checkliste in §6 entfällt damit.

- [ ] **Step 1: Den Test schreiben**

Neue Datei `sales-mcp/tests/test_schema_wache.py`:

```python
"""Welche Schemanamen die Wache durchlaesst — und welche nicht.

WELCHE KAPUTTE FASSUNG FAENGT DIESER TEST?
-------------------------------------------------------------------------
Der Schemaname wird in die Verbindungsoption `-c search_path=<name>`
eingesetzt. Ein Muster, das zu viel erlaubt, ist eine Einschleusungsluecke:
`sales -c log_statement=all` oder `public, sales` waeren zwei Beispiele, die
kein Fehler aufhalten wuerde. Ein Muster, das zu wenig erlaubt, macht jeden
neuen Laden unmoeglich. Beide Haelften stehen deshalb hier.

Die Wache laeuft auf MODULEBENE (server.py:81). Sie laesst sich nicht
aufrufen, also pruefen wir die Regel selbst — und halten mit dem letzten
Test fest, dass die Regel wirklich DIE ist, die server.py benutzt.
"""
import re
from pathlib import Path

import pytest

import server

ERLAUBT = ["sales", "sales_test", "sales_ivan", "sales_a", "sales_b2",
           "sales_lange_aber_zulaessige_kennung"]

VERBOTEN = [
    "",                        # leer
    "public",                  # fremdes Schema
    "Sales",                   # Grossbuchstaben
    "sales_",                  # Unterstrich ohne Namen
    "sales_1",                 # Ziffer als erstes Zeichen des Namens
    "sales-ivan",              # Bindestrich
    "sales ivan",              # Leerzeichen
    "sales_ivan; drop schema sales cascade",
    "sales -c log_statement=all",
    "public, sales",
    "sales_" + "x" * 31,       # zu lang
]


@pytest.mark.parametrize("name", ERLAUBT)
def test_erlaubte_namen(name):
    assert server.SCHEMA_MUSTER.fullmatch(name), name


@pytest.mark.parametrize("name", VERBOTEN)
def test_verbotene_namen(name):
    assert not server.SCHEMA_MUSTER.fullmatch(name), name


def test_die_wache_benutzt_wirklich_dieses_muster():
    """Sonst prueften die Tests oben eine Regel, die niemand anwendet.

    Genau diese Falle ist in dieser Woche mehrfach aufgetreten: ein Test,
    der eine Hilfsfunktion prueft, waehrend der Aufrufer eine andere
    benutzt. Der Quelltext haelt die Kopplung fest.
    """
    quelle = (Path(server.__file__)).read_text(encoding="utf-8")
    assert "if not SCHEMA_MUSTER.fullmatch(SCHEMA):" in quelle
```

- [ ] **Step 2: Test laufen lassen, er muss fehlschlagen**

Run: `cd sales-mcp && python -m pytest tests/test_schema_wache.py -v`
Erwartet: alle FAIL mit `AttributeError: module 'server' has no attribute 'SCHEMA_MUSTER'`.

- [ ] **Step 3: Die Wache umbauen**

`sales-mcp/server.py`, Zeilen 81-83 ersetzen:

```python
SCHEMA = os.environ.get("SALES_DB_SCHEMA", "sales")
# Ein Muster statt einer Liste (Plan 2026-09-16, T2): jeder weitere Laden
# heisst `sales_<kennung>`, und niemand muss diese Zeile dafuer anfassen.
# Streng bleibt es trotzdem — der Name wird unten in
# `options=-c search_path={SCHEMA}` eingesetzt, und das Muster laesst weder
# Leerzeichen noch Anfuehrungszeichen, Kommata oder Semikola zu.
SCHEMA_MUSTER = re.compile(r"sales(_[a-z][a-z0-9_]{0,30})?")
if not SCHEMA_MUSTER.fullmatch(SCHEMA):
    raise SystemExit(
        f"Unzulaessiges Schema '{SCHEMA}' — erlaubt: sales, sales_test "
        f"oder sales_<kennung> (Kleinbuchstaben, Ziffern, Unterstrich)")
```

Sicherstellen, dass `import re` oben in `server.py` steht (prüfen mit `grep -n '^import re' sales-mcp/server.py`; fehlt es, alphabetisch zu den übrigen `import`-Zeilen hinzufügen).

- [ ] **Step 4: Tests laufen lassen**

Run: `cd sales-mcp && python -m pytest tests/test_schema_wache.py -v`
Erwartet: 18 passed.

Run: `cd sales-mcp && python -m pytest -q`
Erwartet: EXIT 0.

- [ ] **Step 5: Committen**

```bash
git add sales-mcp/server.py sales-mcp/tests/test_schema_wache.py
git commit -m "feat: Schema-Wache prueft nach Muster, damit jeder Laden ohne Codeaenderung dazukommt"
```

---

## Task 3: Einen Laden in der Datenbank anlegen

**Files:**
- Create: `db/laden-anlegen.sql`
- Create: `db/pruefe-laden.sql`

**Interfaces:**
- Consumes: das Muster aus Aufgabe 2 (`sales_<kennung>`).
- Produces: Schema `sales_<kennung>` mit denselben sieben Tabellen wie `sales`, Rolle `sales_app_<kennung>` mit Rechten **nur** darauf und auf `compliance`. Aufgabe 4 ruft beide Dateien auf.

**Warum `create table ... (like ... including all)` und keine Kopie von `provision.sql`:** Eine zweite Fassung der Tabellendefinitionen würde beim nächsten Schemawechsel auseinanderlaufen. `like ... including all` übernimmt Spalten, Vorgabewerte, CHECKs und Indizes aus dem bestehenden Schema — Fremdschlüssel allerdings **nicht**, die werden unten ausdrücklich gesetzt.

- [ ] **Step 1: `db/laden-anlegen.sql` schreiben**

```sql
-- Einen Laden anlegen: Schema, Tabellen, Benutzer, Rechte.
--
-- Aufruf (als supabase_admin, NICHT mit der Laufzeit-Kennung — die hat
-- bewusst kein DDL; gemessen 15.09.2026: "permission denied for schema
-- sales"):
--
--   LADEN_PASSWORT=... psql -v laden=ivan -f db/laden-anlegen.sql
--
-- Das Passwort kommt ueber die Umgebung, nicht ueber argv — es stuende
-- sonst in der Prozessliste. Braucht psql 14+ (`\getenv`).
--
-- Idempotent: ein zweiter Lauf aendert nichts.
\set ON_ERROR_STOP on

\set schema 'sales_':laden
\set rolle 'sales_app_':laden

-- Die Tabellen entstehen als Abzug des bestehenden Schemas. Eine zweite
-- Fassung der Definitionen wuerde beim naechsten Schemawechsel auseinander-
-- laufen; `including all` uebernimmt Spalten, Vorgaben, CHECKs und Indizes.
-- Fremdschluessel deckt `including all` NICHT ab — sie stehen unten.
create schema if not exists :"schema";

create table if not exists :"schema".leads            (like sales.leads            including all);
create table if not exists :"schema".activities       (like sales.activities       including all);
create table if not exists :"schema".drafts           (like sales.drafts           including all);
create table if not exists :"schema".personas         (like sales.personas         including all);
create table if not exists :"schema".benutzer         (like sales.benutzer         including all);
create table if not exists :"schema".medien_meta      (like sales.medien_meta      including all);
create table if not exists :"schema".kalender_quellen (like sales.kalender_quellen including all);

-- Die zwei Fremdschluessel, INNERHALB des neuen Schemas. Zeigten sie auf
-- sales.leads, waere die Trennung schon hier gebrochen.
--
-- WARUM KEIN `do $$ ... $$`-BLOCK: psql ersetzt :'schema' NICHT innerhalb
-- dollar-gequoteter Zeichenketten — der Block bekaeme den Doppelpunkt
-- woertlich und schluege fehl. Drop-dann-Add ist ebenso idempotent und
-- benutzt nur Bezeichner, die psql wirklich einsetzt.
alter table :"schema".activities drop constraint if exists activities_lead_id_fkey;
alter table :"schema".activities add constraint activities_lead_id_fkey
  foreign key (lead_id) references :"schema".leads(id) on delete cascade;

alter table :"schema".drafts drop constraint if exists drafts_lead_id_fkey;
alter table :"schema".drafts add constraint drafts_lead_id_fkey
  foreign key (lead_id) references :"schema".leads(id) on delete set null;

-- Der Benutzer dieses Ladens. Kein DDL, kein DELETE — wie sales_app
-- (db/provision.sql:198-204).
--
-- Das Passwort kommt aus der UMGEBUNG, nicht aus argv: ein `-v passwort=...`
-- stuende in der Prozessliste, und am 12.09.2026 hat genau diese Art von
-- Uebergabe schon einmal einen Token beschaedigt. `\getenv` braucht psql 14
-- oder neuer — pruefen mit `psql --version`, bevor dieses Skript laeuft.
\getenv passwort LADEN_PASSWORT
\if :{?passwort}
\else
\echo 'FEHLER: Umgebungsvariable LADEN_PASSWORT ist nicht gesetzt.'
\quit 1
\endif

select not exists (select 1 from pg_roles where rolname = :'rolle') as fehlt \gset
\if :fehlt
create role :"rolle" login nosuperuser nocreatedb nocreaterole noinherit
  password :'passwort';
\else
alter role :"rolle" password :'passwort';
\endif

grant usage on schema :"schema" to :"rolle";
grant select, insert, update on :"schema".leads            to :"rolle";
grant select, insert         on :"schema".activities       to :"rolle";
grant select, insert, update on :"schema".drafts           to :"rolle";
grant select, insert, update on :"schema".personas         to :"rolle";
grant select, insert, update on :"schema".benutzer         to :"rolle";
grant select, insert, update on :"schema".medien_meta      to :"rolle";
grant select, insert, update on :"schema".kalender_quellen to :"rolle";

-- Die Sperrliste ist GEMEINSAM (Spec §2.1): wer Werbung widerspricht, hat
-- allen widersprochen.
grant usage on schema compliance to :"rolle";
grant select, insert, update on all tables in schema compliance to :"rolle";

-- Und ausdruecklich NICHTS auf dem fremden Schema. Das ist der Kern der
-- Trennung: sie liegt in der Datenbank, nicht im Code.
revoke all on schema sales from :"rolle";
revoke all on all tables in schema sales from :"rolle";
```

- [ ] **Step 2: `db/pruefe-laden.sql` schreiben — Tor 1 der Spec**

```sql
-- Haelt die Trennung? Aufruf MIT DER KENNUNG DES NEUEN LADENS:
--
--   psql "postgresql://sales_app_ivan:...@.../postgres" \
--        -v laden=ivan -f db/pruefe-laden.sql
--
-- Der entscheidende Unterschied, den dieses Skript pruefen soll:
-- "permission denied" ist etwas anderes als "leeres Ergebnis". Ein leeres
-- Ergebnis hiesse, die Zeilen sind nur gerade nicht da.
\set ON_ERROR_STOP off

\set schema 'sales_':laden

\echo '=== 1. Der eigene Laden ist lesbar (muss eine Zahl liefern) ==='
select count(*) as eigene_leads from :"schema".leads;

\echo ''
\echo '=== 2. Der fremde Laden ist es NICHT (muss permission denied sagen) ==='
select count(*) as fremde_leads from sales.leads;

\echo ''
\echo '=== 3. Die gemeinsame Sperrliste ist lesbar ==='
select count(*) as sperrliste from compliance.sperrliste;

\echo ''
\echo '=== 4. Kein DELETE, auch nicht im eigenen Laden ==='
delete from :"schema".leads where false;

\echo ''
\echo 'ERWARTET: 1 Zahl, 2 permission denied, 3 Zahl, 4 permission denied.'
\echo 'Liefert 2 eine Zahl — auch die 0 —, ist die Trennung GEBROCHEN.'
```

- [ ] **Step 3: Gegen die Testdatenbank ausführen**

Die Testdatenbank ist der Container `sales-testdb` im Netz `sales-test-net` (Port 55432). Dort zuerst, nicht auf der Produktion:

```bash
LADEN_PASSWORT='probe-geheim' \
  psql "postgresql://postgres:postgres@127.0.0.1:55432/postgres" \
       -v laden=probe -f db/laden-anlegen.sql
```
Erwartet: keine Fehler; ein zweiter Lauf ebenfalls nicht (Idempotenz).

Vorher einmal `psql --version` prüfen — `\getenv` braucht psql 14 oder neuer.
Ist es älter, bricht das Skript mit `\getenv: unrecognized` ab, **nicht** mit
einem stillschweigend leeren Passwort.

- [ ] **Step 4: Die Prüfung ausführen**

```bash
psql "postgresql://sales_app_probe:probe-geheim@127.0.0.1:55432/postgres" \
     -v laden=probe -f db/pruefe-laden.sql
```
Erwartet, wörtlich: Abschnitt 1 eine Zahl, **Abschnitt 2 `ERROR: permission denied for table leads`**, Abschnitt 3 eine Zahl, Abschnitt 4 `ERROR: permission denied`.

Liefert Abschnitt 2 eine Zahl, ist die Aufgabe nicht fertig — dann greift das `revoke` nicht, weil `sales_app_probe` die Rechte über `public` oder eine geerbte Rolle bekommt.

- [ ] **Step 5: Spaltengleichheit nachweisen**

```bash
psql "postgresql://postgres:postgres@127.0.0.1:55432/postgres" -tAc "
select table_name, string_agg(column_name, ',' order by ordinal_position)
from information_schema.columns
where table_schema in ('sales','sales_probe')
group by table_schema, table_name order by table_name, table_schema"
```
Erwartet: zu jedem Tabellennamen **zwei identische Spaltenlisten**. Unterscheiden sie sich, hat `like ... including all` etwas nicht übernommen.

- [ ] **Step 6: Committen**

```bash
git add db/laden-anlegen.sql db/pruefe-laden.sql
git commit -m "feat: einen Laden anlegen und die Trennung an der Datenbank nachweisen"
```

---

## Task 4: Der zweite Laden läuft

**Files:**
- Create: `deploy/laden-anlegen.sh`
- Modify: `docs/03_RUNBOOK.md`

**Interfaces:**
- Consumes: `deploy/laeden/beispiel.env` (T1), `db/laden-anlegen.sql` und `db/pruefe-laden.sql` (T3), das Schema-Muster (T2).
- Produces: `deploy/laeden/<name>.env` und einen laufenden Satz Container. Aufgabe 5 liest das Verzeichnis `deploy/laeden/`.

- [ ] **Step 1: `deploy/laden-anlegen.sh` schreiben**

```bash
#!/usr/bin/env bash
# Einen weiteren Laden anlegen und starten.
#
#   deploy/laden-anlegen.sh ivan 18895 8792 12786
#
# Das Datenbank-Passwort wird erzeugt und NUR in die Umgebungsdatei
# geschrieben — es erscheint nicht auf dem Bildschirm und nicht in der
# Prozessliste (deshalb `psql -v` ueber eine Datei und nicht ueber argv).
set -euo pipefail

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:?Aufruf: laden-anlegen.sh <name> <port-gateway> <port-ui> <port-openwa>}"
PORT_GATEWAY="${2:?}"; PORT_UI="${3:?}"; PORT_OPENWA="${4:?}"

if ! [[ "$NAME" =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "FEHLER: '$NAME' passt nicht zum Schema-Muster aus server.py" >&2
  exit 1
fi

ENVDATEI="$WURZEL/deploy/laeden/$NAME.env"
if [ -e "$ENVDATEI" ]; then
  echo "FEHLER: $ENVDATEI existiert bereits — nichts geaendert." >&2
  exit 1
fi

# Kollidierende Ports abfangen, bevor Container halb hochkommen.
for p in "$PORT_GATEWAY" "$PORT_UI" "$PORT_OPENWA"; do
  if ss -tlnH "sport = :$p" | grep -q .; then
    echo "FEHLER: Port $p ist belegt." >&2
    exit 1
  fi
done

PASSWORT="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"

mkdir -p "$WURZEL/deploy/laeden"
umask 077
cat > "$ENVDATEI" <<EOF
LADEN_PRAEFIX=$NAME
LADEN_PROJEKT=$NAME-claw
PORT_GATEWAY=$PORT_GATEWAY
PORT_UI=$PORT_UI
PORT_OPENWA=$PORT_OPENWA
SALES_DB_SCHEMA=sales_$NAME
SALES_DB_URL=postgresql://sales_app_$NAME:$PASSWORT@192.168.178.65:54322/postgres
UI_TAILSCALE_IP=${UI_TAILSCALE_IP:-127.0.0.1}
EOF

echo "Umgebungsdatei geschrieben: $ENVDATEI (nur fuer den Eigentuemer lesbar)"
echo
echo "NAECHSTER SCHRITT — von Hand, als supabase_admin auf der VM."
echo "Das Passwort steht in $ENVDATEI und wird ueber die UMGEBUNG"
echo "uebergeben, damit es nicht in der Prozessliste landet:"
echo
echo "  PW=\$(sed -n 's#.*sales_app_$NAME:\\([^@]*\\)@.*#\\1#p' $ENVDATEI)"
echo "  docker exec -i -e LADEN_PASSWORT=\"\$PW\" debian-supabase-db-1 \\"
echo "    psql -U supabase_admin -d postgres -v laden=$NAME \\"
echo "    < $WURZEL/db/laden-anlegen.sql"
echo "  unset PW"
echo
echo "Danach:"
echo "  docker compose --env-file $ENVDATEI up -d --build"
echo "  docker compose --env-file $ENVDATEI -f docker-compose.openwa.yml up -d --build openwa"
```

**Warum das Anlegen in der Datenbank nicht automatisch geschieht:** Dafür bräuchte das Skript die Kennung von `supabase_admin`. Die liegt bewusst nirgends im Repository und wurde am 15.09.2026 ausdrücklich nicht gelesen, angezeigt oder transportiert.

`chmod +x deploy/laden-anlegen.sh`

- [ ] **Step 2: Den Laden anlegen**

```bash
deploy/laden-anlegen.sh ivan 18895 8792 12786
```
Erwartet: die Umgebungsdatei entsteht, die nächsten Schritte werden ausgegeben.

- [ ] **Step 3: Schema und Benutzer in der Produktion anlegen**

Den ausgegebenen `psql`-Aufruf ausführen. Danach die Prüfung:

```bash
docker exec -i debian-supabase-db-1 psql \
  "postgresql://sales_app_ivan:<passwort>@127.0.0.1:5432/postgres" \
  -v laden=ivan < db/pruefe-laden.sql
```
Erwartet: 1 Zahl, **2 permission denied**, 3 Zahl, 4 permission denied. Das ist **Tor 1 der Spec**.

- [ ] **Step 4: Die Container starten**

```bash
docker compose --env-file deploy/laeden/ivan.env up -d --build
docker compose --env-file deploy/laeden/ivan.env \
  -f docker-compose.openwa.yml up -d --build openwa
```

Nachmessen:
```bash
docker ps --format '{{.Names}}' | grep '^ivan-' | sort
```
Erwartet, zehn Zeilen: `ivan-claw`, `ivan-dispatch`, `ivan-inbox`, `ivan-linkedin`, `ivan-mail`, `ivan-mcp`, `ivan-openwa`, `ivan-stt`, `ivan-telegram`, `ivan-ui`.

(`ivan-auto` läuft **nicht** — `sales-auto` wird auch im bestehenden Laden nie durch ein nacktes `up -d` gestartet, siehe `deploy/update.sh:17`.)

- [ ] **Step 5: Tor 10 — getrennte WhatsApp-Anmeldungen**

```bash
docker volume ls --format '{{.Name}}' | grep -E 'claw-state|openwa-data' | sort
```
Erwartet: `ivan-claw-state`, `ivan-openwa-data`, `sales-claw-state`, `sales-openwa-data` — vier verschiedene.

Dann der eigentliche Nachweis: `ivan-claw` zeigt beim ersten Start einen **neuen QR-Code**, während der bestehende Laden **ohne erneutes Pairing** weiterläuft:
```bash
docker logs sales-claw --since 5m | grep -ci 'qr' || echo "0 — richtig"
docker logs ivan-claw  --since 5m | grep -ci 'qr'
```
Erwartet: beim bestehenden Laden `0`, beim neuen `>0`.

- [ ] **Step 6: Tor 11 — die gemeinsame Sperrliste wirkt in beiden**

```bash
docker exec ivan-mcp python -c "
import sperrliste
print('Schema der Sperrliste:', sperrliste.SCHEMA)"
```
Erwartet: `compliance` — **nicht** `compliance_test` und nicht `compliance_ivan`.

- [ ] **Step 7: Runbook ergänzen**

In `docs/03_RUNBOOK.md` einen Abschnitt „Einen zweiten Laden anlegen" einfügen mit: dem Aufruf von `deploy/laden-anlegen.sh`, dem `psql`-Schritt als `supabase_admin`, den beiden `docker compose`-Aufrufen, den drei Nachmessungen aus Schritt 4-6 — und dem einmaligen Umzug von `openwa-data` nach `sales-openwa-data` aus Aufgabe 1, Schritt 4.

- [ ] **Step 8: Committen**

```bash
git add deploy/laden-anlegen.sh docs/03_RUNBOOK.md
git commit -m "feat: deploy/laden-anlegen.sh legt einen weiteren Laden an"
```

---

## Task 5: Update, Sicherung und Wiederherstellung erfassen alle Läden

**Files:**
- Modify: `deploy/update.sh`
- Modify: `deploy/sicherung.sh`
- Modify: `deploy/wiederherstellen.sh`

**Interfaces:**
- Consumes: `deploy/laeden/*.env` aus Aufgabe 4.
- Produces: nichts, worauf spätere Aufgaben sich stützen.

**Nebenbefund, der hier mitbehoben wird:** `deploy/update.sh:19` führt `KERN_ALLE="sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw"` — **sechs** Dienste. `sales-telegram`, `sales-linkedin` und `sales-stt` fehlen, obwohl sie seit dem 12.09.2026 laufen. Ein Update hat sie bisher übersprungen.

- [ ] **Step 1: Die Liste in `update.sh` richtigstellen**

Zeile 19 ersetzen:
```bash
# Alle Dienste, die ein Update erfassen muss. NIEMALS nacktes
# `docker compose up -d`: das wuerde sales-auto mitstarten.
# telegram/linkedin/stt fehlten hier bis zum 16.09.2026 — ein Update hat
# sie stillschweigend uebersprungen.
KERN_ALLE="sales-mcp sales-ui sales-inbox sales-dispatch sales-mail sales-claw sales-telegram sales-linkedin sales-stt"
```

Die Dienstschlüssel bleiben `sales-*`, denn sie sind vom `container_name` unabhängig (Aufgabe 1, Schritt 4).

- [ ] **Step 2: Über die Läden schleifen**

In `update.sh` vor dem ersten `docker compose`-Aufruf einfügen:
```bash
# Jeder Laden hat eine Umgebungsdatei; der erste (Vorgabewerte) hat keine.
# Die leere Zeichenkette steht fuer ihn.
LAEDEN=("")
for e in "$WURZEL"/deploy/laeden/*.env; do
  [ -e "$e" ] || continue
  [ "$(basename "$e")" = "beispiel.env" ] && continue
  LAEDEN+=("--env-file $e")
done
```

Und jeden `docker compose`-Aufruf (Zeilen 132, 146, 149) in eine Schleife setzen:
```bash
for L in "${LAEDEN[@]}"; do
  # shellcheck disable=SC2086
  docker compose $L up -d --build $KERN
done
```

- [ ] **Step 3: Tor 12 messen**

```bash
deploy/update.sh
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E '^(sales|ivan)-' | sort
```
Erwartet: beide Sätze mit frischem `Up`-Zeitstempel, in **einem** Lauf, ohne dass ein Befehl je Person wiederholt wurde.

- [ ] **Step 4: `sicherung.sh` über die Läden schleifen**

In `deploy/sicherung.sh` die feste Zeile `VOLUMES="openwa-data sales-claw-state sales-claw-keys sales-sprachnachrichten"` und den `openwa`-Block ersetzen:

```bash
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ein Laden je Praefix. Der bestehende heisst "sales" und hat keine
# Umgebungsdatei — seine Werte sind die Vorgaben in den Compose-Dateien.
PRAEFIXE="sales"
for e in "$WURZEL"/deploy/laeden/*.env; do
  [ -e "$e" ] || continue
  [ "$(basename "$e")" = "beispiel.env" ] && continue
  PRAEFIXE="$PRAEFIXE $(sed -n 's/^LADEN_PRAEFIX=//p' "$e")"
done

# Jedes gestoppte openwa kommt am Ende IMMER wieder hoch, auch wenn tar
# scheitert. Eine Liste statt einer Variablen, weil es jetzt mehrere sind.
GESTOPPT=""
neustarten() { for c in $GESTOPPT; do docker start "$c" >/dev/null || true; done; }
trap neustarten EXIT

for P in $PRAEFIXE; do
  UNTERORDNER="$ORDNER/$P"
  mkdir -p "$UNTERORDNER"

  # openwa fuer die Dauer der Sicherung stoppen: ein live getartes
  # Chromium-Profil ist die Beschaedigungsklasse, die am 26.08.2026 die
  # WhatsApp-Session gekostet hat.
  if [ "$(docker inspect -f '{{.State.Status}}' "$P-openwa" 2>/dev/null || true)" = "running" ]; then
    GESTOPPT="$GESTOPPT $P-openwa"
    docker stop "$P-openwa" >/dev/null
  fi

  # sales-stt-modelle fehlt hier BEWUSST: 300 MB Modell, jederzeit neu
  # ladbar, und es ist ohnehin fuer alle Laeden dasselbe Volume.
  for vol in "$P-openwa-data" "$P-claw-state" "$P-claw-keys" "$P-sprachnachrichten"; do
    docker volume inspect "$vol" >/dev/null 2>&1 || continue
    docker run --rm -v "$vol":/quelle:ro -v "$UNTERORDNER":/ziel alpine \
      tar czf "/ziel/$vol.tar.gz" -C /quelle .
  done

  # Das Datenbankschema dieses Ladens.
  docker exec debian-supabase-db-1 pg_dump -U supabase_admin -d postgres \
    --schema="sales${P:+_}${P#sales}" --no-owner \
    | gzip > "$UNTERORDNER/schema.sql.gz"
done
```

**Zu der Schemazeile:** für den Laden `sales` soll `--schema=sales` herauskommen, für `ivan` `--schema=sales_ivan`. Der Implementierer prüft das mit `echo` **vor** dem ersten echten Lauf; ist der Ausdruck unklar, ersetzt er ihn durch ein schlichtes `if [ "$P" = sales ]; then S=sales; else S="sales_$P"; fi`. Lieber vier Zeilen als ein Einzeiler, den niemand liest.

Die Prüfsummenzeile am Ende muss die Unterordner erfassen:
```bash
( cd "$ORDNER" && find . -name '*.tar.gz' -o -name '*.sql.gz' | sort | xargs sha256sum > MANIFEST.sha256 )
```

- [ ] **Step 5: `wiederherstellen.sh` auf genau einen Laden begrenzen**

`deploy/wiederherstellen.sh` bekommt ein zweites Pflichtargument und fasst nichts an, was nicht zu diesem Laden gehört:

```bash
QUELLE="${1:?Aufruf: wiederherstellen.sh <sicherungsordner> <laden>}"
LADEN="${2:?Aufruf: wiederherstellen.sh <sicherungsordner> <laden>}"

# Ohne Ladennamen wird NICHT geraten: eine Wiederherstellung, die den
# falschen Laden trifft, ist genau der Schaden, den Tor 13 ausschliesst.
if ! [[ "$LADEN" =~ ^[a-z][a-z0-9_]{0,30}$ ]]; then
  echo "ABBRUCH: '$LADEN' ist kein gueltiger Ladenname." >&2
  exit 1
fi

UNTERORDNER="$QUELLE/$LADEN"
[ -d "$UNTERORDNER" ] || { echo "ABBRUCH: $UNTERORDNER fehlt." >&2; exit 1; }

# sales-sprachnachrichten wurde bisher GESICHERT, aber nie
# WIEDERHERGESTELLT (gefunden 16.09.2026: sicherung.sh sichert vier
# Volumes, wiederherstellen.sh kannte nur drei). Kundeninhalt gehoert in
# beide Listen.
VOLUMES="$LADEN-openwa-data $LADEN-claw-state $LADEN-claw-keys $LADEN-sprachnachrichten"

for c in "$LADEN-openwa" "$LADEN-claw"; do
  if [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || true)" = "running" ]; then
    echo "ABBRUCH: $c laeuft. Erst stoppen: docker stop $LADEN-openwa $LADEN-claw" >&2
    exit 1
  fi
done

( cd "$UNTERORDNER" && sha256sum -c <(grep "./$LADEN/" "$QUELLE/MANIFEST.sha256" | sed "s#\./$LADEN/##") )

for vol in $VOLUMES; do
  [ -f "$UNTERORDNER/$vol.tar.gz" ] || continue
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/ziel -v "$UNTERORDNER":/quelle:ro alpine \
    sh -c "find /ziel -mindepth 1 -delete && tar xzf /quelle/$vol.tar.gz -C /ziel"
done

echo "Laden '$LADEN' wiederhergestellt aus $UNTERORDNER."
echo "Kein anderer Laden wurde angefasst."
```

**Nebenbefund, der hier mit behoben wird:** `sicherung.sh` sichert vier Volumes, `wiederherstellen.sh` kannte bisher nur drei — `sales-sprachnachrichten` (Kundeninhalt) wäre bei einer Wiederherstellung verloren gewesen, ohne dass es jemandem auffällt.

- [ ] **Step 6: Tor 13 messen**

Eine Sicherung ziehen, in `sales_ivan.leads` eine Zeile ändern, den Laden `ivan` wiederherstellen und nachsehen:
```bash
# Nach der Wiederherstellung:
#  - sales_ivan.leads ist auf dem Stand der Sicherung
#  - sales.leads ist UNVERAENDERT (Zeilenzahl und updated_at vorher notieren)
```
Erwartet: der eine Laden zurückgesetzt, der andere unberührt.

- [ ] **Step 7: Committen**

```bash
git add deploy/update.sh deploy/sicherung.sh deploy/wiederherstellen.sh
git commit -m "fix: Update/Sicherung erfassen alle Laeden; fehlende Dienste in KERN_ALLE ergaenzt"
```

---

## Task 6: Zugang — eigener Port, eigene Regel

**Files:**
- Modify: `docs/03_RUNBOOK.md`
- Modify: `deploy/smoke.sh`

**Interfaces:**
- Consumes: `PORT_UI` aus der Umgebungsdatei (T1/T4).
- Produces: eine erreichbare Oberfläche je Laden unter einer eigenen Adresse.

- [ ] **Step 1: Die zweite Oberfläche über Tailscale anbieten**

```bash
sudo tailscale serve --bg --https 8444 http://127.0.0.1:8792
tailscale serve status
```
Erwartet: zwei Einträge, beide `(tailnet only)` — 443 auf `127.0.0.1:8791`, 8444 auf `127.0.0.1:8792`.

- [ ] **Step 2: Die Zugriffsregel umstellen**

In der Tailscale-Verwaltung den Grant für Ivan von `tcp:443` auf `tcp:8444` ändern und den `tests`-Block mitziehen:
```json
{ "src": ["ivan.gasparik161@gmail.com"], "dst": ["vibemind-offload-1"], "ip": ["tcp:8444"] }
```
```json
"tests": [
  { "src": "ivan.gasparik161@gmail.com",
    "accept": ["100.67.177.45:8444"],
    "deny":   ["100.67.177.45:443", "100.67.177.45:54322",
               "100.67.177.45:54323", "100.67.177.45:22"] }
]
```
Das Speichern schlägt fehl, wenn eine dieser Behauptungen nicht stimmt — die Prüfung läuft also, bevor jemand sie umgehen kann.

- [ ] **Step 3: Tor 2 messen — von Ivans Gerät aus**

```
1) https://vibemind-offload-1.tail6c7d61.ts.net:8444/   -> Anmeldung erscheint
2) https://vibemind-offload-1.tail6c7d61.ts.net/        -> KEIN Verbindungsaufbau
3) http://100.67.177.45:54323/                          -> KEIN Verbindungsaufbau
```
Punkt 2 ist der eigentliche Nachweis: nicht „403", sondern **gar keine Antwort**. Ein 403 hieße, er kommt hin und wird abgewiesen — das wäre eine Regel im Code statt einer im Netz.

- [ ] **Step 4: Die Messung in `deploy/smoke.sh` verankern**

```bash
echo "== Oberflaechen je Laden =="
for e in "$WURZEL"/deploy/laeden/*.env; do
  [ -e "$e" ] || continue
  [ "$(basename "$e")" = "beispiel.env" ] && continue
  ( . "$e"
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT_UI/login")
    [ "$code" = "200" ] || { echo "FEHLER: $LADEN_PRAEFIX-ui antwortet $code"; exit 1; }
    echo "  $LADEN_PRAEFIX-ui auf $PORT_UI: $code" )
done
```

- [ ] **Step 5: Runbook ergänzen und committen**

Im Runbook-Abschnitt aus Aufgabe 4 die drei Punkte aus Schritt 3 als Abnahme für den neuen Menschen aufnehmen — wörtlich zum Weiterschicken.

```bash
git add docs/03_RUNBOOK.md deploy/smoke.sh
git commit -m "feat: eigener Serve-Port je Laden, Zugriffsregel auf den eigenen Port begrenzt"
```

---

## Task 7: Die vier Kanäle und die Abnahme

**Files:**
- Modify: `docs/11_INBETRIEBNAHME.md`
- Modify: `deploy/smoke.sh`

**Interfaces:**
- Consumes: den laufenden Laden aus Aufgabe 4, den Zugang aus Aufgabe 6.
- Produces: nichts — dies ist die Abnahme.

**Warum hier kein Code steht:** Ein Postfach beim Anbieter, ein Bot-Token beim BotFather, ein LinkedIn-Zugang und ein WhatsApp-Pairing kann kein Skript erzeugen. Diese Aufgabe schreibt die Reihenfolge auf und **misst das Ergebnis**.

- [ ] **Step 1: `docs/11_INBETRIEBNAHME.md` um die vier Kanäle erweitern**

Ein Abschnitt „Die vier Kanäle eines neuen Ladens" mit je: was anzulegen ist, wo der Wert hingehört, und wie man nachsieht, dass er wirkt.

| Kanal | Anzulegen | Gehört nach | Nachweis |
|---|---|---|---|
| Mail | Postfach `<name>@vibemind.space` | `deploy/laeden/<name>.env` (`SMTP_USER`, `EMAIL_ABSENDER`) | Tor 8, Schritt 3 |
| Telegram | Bot-Token beim BotFather | `deploy/laeden/<name>.env` (`TELEGRAM_BOT_TOKEN`) | `getMe` aus dem Container |
| LinkedIn | eigener Zugang | `deploy/laeden/<name>.env` | Anmeldung im Container |
| WhatsApp | Pairing mit eigener Nummer | Volume `<name>-claw-state` | QR im Log, Tor 10 |

**Der Token wird über `stdin` übergeben, nie über `argv`** — am 12.09.2026 machte ein mitgeschriebenes Zeilenende den Telegram-Token ungültig (Länge 47 statt 46), und ein Wert in `argv` steht in der Prozessliste.

- [ ] **Step 2: Tor 8 messen — die Absenderadresse**

Aus Ivans Laden einen Entwurf erzeugen, freigeben, zustellen lassen — und **im echten Postfach** nachsehen, nicht im Log:

```bash
docker exec ivan-mcp env | grep -E 'EMAIL_ABSENDER|SMTP_USER'
```
Erwartet: `ivan@vibemind.space` in beiden. Danach die zugestellte Nachricht öffnen und den Absender im Kopf prüfen.

**Warum nicht das Log genügt:** Am 12.09.2026 war die versendete Fassung einer Datei kaputt (`\r\r\n`), während die archivierte richtig war. Das Log zeigt, was das Programm zu tun glaubte.

- [ ] **Step 3: Die Telegram-Kennung prüfen**

```bash
docker exec ivan-telegram python -c "
import os, urllib.request, json
t = os.environ['TELEGRAM_BOT_TOKEN']
with urllib.request.urlopen(f'https://api.telegram.org/bot{t}/getMe') as a:
    print(json.load(a)['result']['username'])"
```
Erwartet: Ivans Bot-Name — **nicht** `@VibeMind_agent_bot` (das ist der des bestehenden Ladens).

- [ ] **Step 4: Die Kanalprüfung in `deploy/smoke.sh` verankern**

```bash
echo "== Absenderadressen sind je Laden verschieden =="
ABSENDER="$(docker ps --format '{{.Names}}' | grep -- '-mail$' | while read -r c; do
  docker exec "$c" printenv EMAIL_ABSENDER
done | sort)"
DOPPELT="$(echo "$ABSENDER" | uniq -d)"
[ -z "$DOPPELT" ] || { echo "FEHLER: zwei Laeden teilen einen Absender: $DOPPELT"; exit 1; }
echo "$ABSENDER" | sed 's/^/  /'
```

- [ ] **Step 5: Die ganze Suite und der Rauchtest**

Run: `cd sales-mcp && python -m pytest -q`
Erwartet: EXIT 0, mindestens 1738 + die neuen Tests aus Aufgabe 1 und 2.

Run: `deploy/smoke.sh`
Erwartet: EXIT 0, mit den drei neuen Abschnitten.

- [ ] **Step 6: Committen**

```bash
git add docs/11_INBETRIEBNAHME.md deploy/smoke.sh
git commit -m "docs: die vier Kanaele eines neuen Ladens, mit Nachweis statt Behauptung"
```

---

## Was dieser Plan ausdrücklich NICHT tut

Damit niemand danach sucht — das ist Plan 2 (Spec §7):

* `sales_geteilt` mit `firmen_in_arbeit` und `medien_geteilt`
* die Seite „Heute (Team)" und die Firmenwarnung
* der Medien-Schalter `kollegen_sehen` samt Freigabe-Abfrage
* das Werkzeug `freie_zeiten`
* das Entfernen des Posteingangs

Nach diesem Plan arbeitet der zweite Mensch eigenständig — mit eigenen Kontakten, eigenem Bot und eigener Oberfläche, aber **ohne** geteilte Sicht. Die Termine sieht er schon, sobald beide Kalender gegenseitig abonniert sind (Spec §2.1); das ist gebaut und braucht keinen Code aus diesem Plan.
