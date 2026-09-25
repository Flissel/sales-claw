# Schalter Sales ↔ Marketing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Betreiber wechselt mit einem Klick zwischen Sales-Oberfläche und Marketing-Seite und zurück; die Marketing-Seite läuft dafür zusätzlich auf der VM.

**Architecture:** `sales-mcp/ui.py` bekommt einen Schalter in Seitenleiste und Handy-Tableiste, gesteuert von `MARKETING_URL` und der Rolle `freigeben` im Basis-Laden. Die Marketing-Seite (`spaces/marketing/mockup/`) bekommt den Gegen-Schalter; die Prüfung des Rückwegs liegt in einer kleinen, mit node testbaren Datei `schalter.js`. Auf der VM läuft eine zweite Instanz der Marketing-API als systemd-Dienst aus einem schlanken vibemind-os-Checkout, per `tailscale serve` nur im Tailnet.

**Tech Stack:** Python 3.11/3.12, Starlette/FastAPI, pytest, node (nur für den JS-Test), bash, systemd, Tailscale.

**Spec:** `docs/superpowers/specs/2026-09-25-marketing-schalter-design.md` (sales-claw)

## Global Constraints

- `MARKETING_URL` leer = kein Schalter. Gesetzt nur in der Haupt-`.env` des Basis-Ladens auf der VM (zweite Läden starten mit `--env-file`, das die Haupt-`.env` ersetzt).
- Schalter nur für Rolle `freigeben` UND `server.SCHEMA in ("sales", "sales_test")` — dieselbe Sperre wie `_ADMIN_BASIS_PFADE`.
- Rückweg (`zurueck`) nur `https://` mit Hostname auf `.ts.net`.
- Marketing-API auf der VM: `MARKETING_HTTP_BIND=127.0.0.1`, `MARKETING_HTTP_PORT=5510`, `SUPABASE_SSH_HOST` leer (Modus B), `SUPABASE_DB_CONTAINER=debian-supabase-db-1`.
- Tailnet-Adresse: `https://vibemind-offload-1.tail6c7d61.ts.net:8446` → `http://127.0.0.1:5510`, tailnet only, kein Funnel.
- Schlüssel nur in `/home/debian/marketing-api.env` (Rechte 600), nie in argv, nie im Repo.
- **Abweichung von Spec §3.1, bewusst:** die VM-Instanz bekommt **kein** `OPENFANG_URL`/`OPENFANG_API_KEY`. Die OpenFang-Benachrichtigung entsteht beim Anlegen von Vorschlägen durch die Agenten — die nutzen die PC-Instanz. Die Brücke ist ohnehin nicht fatal (`urlopen(..., timeout=5)` in `try/except`, `api/server.py:2656-2675`). So wandert kein weiterer Schlüssel auf die VM.
- Commits: nur eigene Pfade, explizit, per PowerShell. sales-claw auf `feat/stufe-1-fundament`; vibemind-os nur im Worktree `vibemind-os/.worktrees/setup-agent` (Zweig `master`). Kein Push vor Task 4.
- sales-Tests auf dem Host (Docker ist unzuverlässig): `E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\venv-sales\Scripts\python.exe E:\Temp\claude\c--Users-User-Desktop-Vibemind-V1\09346339-4318-4647-a968-36a3579400b7\scratchpad\test_host.py C:\Users\User\Desktop\Vibemind_V1\vibemind-os\spaces\sales-claw <testdatei>` — pro Datei. Eine andere Session testet gegen dieselbe Test-DB: rote Tests in NICHT berührten Dateien einmal wiederholen, vorher-Stand vergleichen.

## Review Focus

1. **Handy:** `nav.seite .marke` ist unter 768 px verborgen (`ui.py:865`) — ein Schalter nur neben dem Logo wäre am Handy unsichtbar. Erwartet: Marketing ist zusätzlich ein Reiter in der Tableiste unten. Test in Task 1.
2. **`UI_BASIS_URL` leer oder `http://`:** dann wäre `zurueck` eine Container-Adresse, die die Marketing-Seite ohnehin ablehnt. Erwartet: der Link hat dann gar keinen `zurueck`-Parameter. Test in Task 1.
3. **`MARKETING_URL` mit Schrägstrich am Ende oder mit Anführungszeichen:** kein `//mockup/`, kein Ausbruch aus dem `href`. Test in Task 1.
4. **Doppelgänger-Domains für `zurueck`:** `https://x.ts.net.boese.de`, `https://boese.de/?x.ts.net`, `https://boese.de#.ts.net`, `https://ts.net` (ohne Teilnetz) werden abgewiesen. Test in Task 2.
5. **`localStorage` wirft** (privates Fenster): die Seite rendert trotzdem, der Schalter zeigt nur keinen gemerkten Rückweg. Test in Task 2.

---

### Task 1: Schalter in der Sales-Oberfläche

**Files:**
- Modify: `sales-mcp/ui.py` — neue Einstellung und Funktion hinter `_BASIS_URL` (Zeile ~234), CSS-Regeln bei `nav.seite .marke` (Zeile ~802) und im Handy-Block (Zeile ~865), `_seitenleiste` (Zeile ~1240)
- Modify: `docker-compose.yml` — Dienst `sales-ui`, Umgebung neben `UI_BASIS_URL` (Zeile ~782)
- Modify: `deploy/beispiel.env` — Eintrag `MARKETING_URL=` mit Kommentar
- Create: `sales-mcp/tests/test_marketing_schalter.py`

**Interfaces:**
- Produces: `ui.MARKETING_URL: str` (ohne Schrägstrich am Ende), `ui._marketing_link(rolle: str) -> str` (leer = kein Schalter)

- [ ] **Step 1: Failing tests schreiben** — `sales-mcp/tests/test_marketing_schalter.py`:

```python
"""Schalter Sales <-> Marketing (Spec docs/superpowers/specs/
2026-09-25-marketing-schalter-design.md). Zwei Huerden: MARKETING_URL
gesetzt UND Rolle freigeben im Basis-Laden."""
import urllib.parse

import pytest

import server
import ui

MKT = "https://vibemind-offload-1.tail6c7d61.ts.net:8446"
SALES = "https://vibemind-offload-1.tail6c7d61.ts.net"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture
def gesetzt(monkeypatch):
    monkeypatch.setattr(ui, "MARKETING_URL", MKT)
    monkeypatch.setattr(ui, "_BASIS_URL", SALES)


def _leiste(rolle):
    token = ui._AKTIVE_ROLLE.set(rolle)
    try:
        return ui._seitenleiste("")
    finally:
        ui._AKTIVE_ROLLE.reset(token)


def test_ohne_adresse_kein_schalter(monkeypatch):
    monkeypatch.setattr(ui, "MARKETING_URL", "")
    assert ui._marketing_link("freigeben") == ""
    assert "Marketing" not in _leiste("freigeben")


@pytest.mark.parametrize("rolle", ["", "lesen", "kalender"])
def test_andere_rolle_kein_schalter(gesetzt, rolle):
    assert ui._marketing_link(rolle) == ""
    assert "Marketing" not in _leiste(rolle)


def test_anderer_laden_kein_schalter(gesetzt, monkeypatch):
    monkeypatch.setattr(server, "SCHEMA", "sales_ivan")
    assert ui._marketing_link("freigeben") == ""


def test_link_traegt_rueckweg_kodiert(gesetzt):
    link = ui._marketing_link("freigeben")
    teile = urllib.parse.urlsplit(link)
    assert f"{teile.scheme}://{teile.netloc}{teile.path}" == MKT + "/mockup/"
    assert urllib.parse.parse_qs(teile.query) == {"zurueck": [SALES]}


def test_schalter_in_seitenleiste_und_tableiste(gesetzt):
    leiste = _leiste("freigeben")
    href = ui._e(ui._marketing_link("freigeben"))
    assert '<div class="schalter">' in leiste
    # einmal oben (Desktop), einmal in der Tableiste (Handy — die .marke
    # ist dort verborgen)
    assert leiste.count(f'href="{href}"') == 2
    tabs = leiste[leiste.index('<nav class="tabs">'):]
    assert f'href="{href}"' in tabs


@pytest.mark.parametrize("basis", ["", "http://127.0.0.1:8791"])
def test_ohne_https_basis_kein_rueckweg(gesetzt, monkeypatch, basis):
    monkeypatch.setattr(ui, "_BASIS_URL", basis)
    assert ui._marketing_link("freigeben") == MKT + "/mockup/"


def test_schraegstrich_und_anfuehrungszeichen(monkeypatch):
    monkeypatch.setattr(ui, "_BASIS_URL", "")
    monkeypatch.setattr(ui, "MARKETING_URL",
                        ui._marketing_url_lesen('https://x.ts.net:8446/"x/'))
    assert "//mockup" not in ui._marketing_link("freigeben").split("://", 1)[1]
    leiste = _leiste("freigeben")
    assert '"x' not in leiste.replace("&quot;x", "")
```

- [ ] **Step 2: Laufen lassen, rot sehen**

Run: host runner mit `sales-mcp/tests/test_marketing_schalter.py`
Expected: FAIL — `AttributeError: module 'ui' has no attribute 'MARKETING_URL'`

- [ ] **Step 3: Implementieren** — in `sales-mcp/ui.py` direkt hinter `_BASIS_URL = …` (Zeile ~234):

```python
# Schalter Sales <-> Marketing (25.09.2026, Spec docs/superpowers/specs/
# 2026-09-25-marketing-schalter-design.md). Leer = kein Schalter. Gesetzt
# NUR in der Haupt-.env des Basis-Ladens — zweite Laeden starten mit
# --env-file, das die Haupt-.env ersetzt (deploy/laden-anlegen.sh).
def _marketing_url_lesen(roh: str) -> str:
    return roh.strip().rstrip("/")


MARKETING_URL = _marketing_url_lesen(os.environ.get("MARKETING_URL", ""))


def _marketing_link(rolle: str) -> str:
    """Ziel des Marketing-Schalters oder "" (kein Schalter). Zwei Huerden:
    die Adresse ist gesetzt UND die Rolle ist `freigeben` im Basis-Laden —
    dieselbe Sperre wie das Admin-Menue (_pfad_erlaubt), damit eine falsch
    gesetzte Umgebung den Schalter nie in einem fremden Laden zeigt.

    Den Rueckweg (`zurueck`) gibt es nur mit einer https-Basisadresse: die
    Marketing-Seite nimmt ohnehin nur https://…ts.net an."""
    if not MARKETING_URL:
        return ""
    if rolle != "freigeben" or server.SCHEMA not in ("sales", "sales_test"):
        return ""
    ziel = f"{MARKETING_URL}/mockup/"
    if _BASIS_URL.startswith("https://"):
        ziel += "?" + urllib.parse.urlencode({"zurueck": _BASIS_URL})
    return ziel
```

In `_seitenleiste` die Zeilen

```python
    teile = ['<nav class="seite"><div class="marke">'
             '<span class="logo">S</span><span>sales-claw</span></div>']
```

ersetzen durch

```python
    marketing = _marketing_link(rolle)
    teile = ['<nav class="seite"><div class="marke">'
             '<span class="logo">S</span><span>sales-claw</span></div>']
    if marketing:
        teile.append('<div class="schalter"><span class="aktiv">Sales</span>'
                     f'<a href="{_e(marketing)}">Marketing</a></div>')
```

und vor dem abschließenden `teile.append("</nav>")` der Tableiste (das letzte `</nav>` der Funktion):

```python
    if marketing:
        teile.append(f'<a class="tab" href="{_e(marketing)}">'
                     '<span>Marketing</span></a>')
```

CSS hinter der Regel `nav.seite .logo { … }`:

```css
nav.seite .schalter { display: flex; gap: .2rem; padding: 0 .5rem;
                      font-size: .8rem; }
nav.seite .schalter span, nav.seite .schalter a {
  min-height: 0; padding: .2rem .6rem; border-radius: 999px; }
nav.seite .schalter .aktiv { background: var(--aktiv); color: var(--gut);
                             font-weight: 700; }
```

Im Handy-Block (`@media (max-width: 767px)` mit `nav.seite .marke, .gruppenname { display: none; }`) die Zeile ergänzen zu `nav.seite .marke, nav.seite .schalter, .gruppenname { display: none; }`.

`docker-compose.yml`, Dienst `sales-ui`, direkt unter `- UI_BASIS_URL=${UI_BASIS_URL:-}`:

```yaml
      # Schalter Sales <-> Marketing (25.09.2026): tailscale-serve-Adresse
      # der Marketing-API auf der VM. NUR in der Haupt-.env setzen — zweite
      # Laeden (--env-file) bekommen sie so nie. Leer = kein Schalter.
      - MARKETING_URL=${MARKETING_URL:-}
```

`deploy/beispiel.env`: Zeile `MARKETING_URL=` mit Kommentar „nur Basis-Laden; https://vibemind-offload-1.tail6c7d61.ts.net:8446".

- [ ] **Step 4: Grün sehen** — host runner mit `sales-mcp/tests/test_marketing_schalter.py`, dann `sales-mcp/tests/test_seitenleiste.py` und `sales-mcp/tests/test_laden_anlegen_seite.py`. Erwartet: neue Datei grün; die beiden anderen wie vorher (test_seitenleiste hatte vorher 2 bekannte Rote — Vergleich mit `git stash`-freiem Vorher-Lauf: vorher die Ausgabe auf dem Ausgangsstand festhalten).

- [ ] **Step 5: Commit** (PowerShell, sales-claw):

```powershell
git add -- sales-mcp/ui.py sales-mcp/tests/test_marketing_schalter.py docker-compose.yml deploy/beispiel.env
git commit -m "feat(ui): Schalter Sales/Marketing fuer freigeben im Basis-Laden"
```

---

### Task 2: Gegen-Schalter auf der Marketing-Seite

Arbeitsort: Worktree `C:\Users\User\Desktop\Vibemind_V1\vibemind-os\.worktrees\setup-agent`, Pfade unter `spaces/marketing/`. Vorher `git status`; fremde Änderungen an `mockup/index.html` → STOP.

**Files:**
- Create: `spaces/marketing/mockup/schalter.js`
- Modify: `spaces/marketing/mockup/index.html` — Kopf (`<header>`, Zeile ~43-52)
- Create: `spaces/marketing/tests/test_schalter.py`

**Interfaces:**
- Produces: `schalter.js` exportiert (für node) `rueckwegPruefen(roh) -> string|""` und `rueckwegBestimmen(search, speicher) -> string|""`; im Browser `window.MarketingSchalter` mit denselben Funktionen plus `einsetzen()`.

- [ ] **Step 1: Failing test** — `spaces/marketing/tests/test_schalter.py`:

```python
"""Gegen-Schalter Marketing -> Sales (sales-claw Spec 2026-09-25-marketing-
schalter-design.md §3.3). Die Pruefung laeuft in node gegen die echte
Datei, die der Browser laedt — kein Nachbau in Python."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "mockup" / "schalter.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node fehlt")


def _node(ausdruck: str):
    skript = (f"const s = require({json.dumps(str(JS))});"
              f"process.stdout.write(JSON.stringify({ausdruck}));")
    r = subprocess.run([NODE, "-e", skript], capture_output=True,
                       text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("gut", [
    "https://vibemind-offload-1.tail6c7d61.ts.net",
    "https://vibemind-offload-1.tail6c7d61.ts.net:8445/kontakte",
])
def test_tailnet_https_wird_angenommen(gut):
    assert _node(f"s.rueckwegPruefen({json.dumps(gut)})") == gut


@pytest.mark.parametrize("schlecht", [
    "", "http://x.tail6c7d61.ts.net", "javascript:alert(1)",
    "https://x.ts.net.boese.de", "https://boese.de/?x.ts.net",
    "https://boese.de#.ts.net", "https://ts.net", "https://boese.de",
    "//x.ts.net", "nicht mal eine adresse",
])
def test_alles_andere_wird_abgewiesen(schlecht):
    assert _node(f"s.rueckwegPruefen({json.dumps(schlecht)})") == ""


def test_parameter_schlaegt_gemerkten_wert_und_wird_gemerkt():
    ausdruck = """(() => { const m = {};
      const sp = {getItem: k => m[k] ?? null, setItem: (k, v) => { m[k] = v; }};
      sp.setItem('sales_rueckweg', 'https://alt.tail6c7d61.ts.net');
      const r = s.rueckwegBestimmen('?zurueck=' +
        encodeURIComponent('https://neu.tail6c7d61.ts.net'), sp);
      return [r, m.sales_rueckweg]; })()"""
    assert _node(ausdruck) == ["https://neu.tail6c7d61.ts.net"] * 2


def test_ohne_parameter_gilt_der_gemerkte():
    ausdruck = """s.rueckwegBestimmen('', {getItem: () =>
      'https://alt.tail6c7d61.ts.net', setItem: () => {}})"""
    assert _node(ausdruck) == "https://alt.tail6c7d61.ts.net"


def test_gemerkter_boeser_wert_zaehlt_nicht():
    ausdruck = """s.rueckwegBestimmen('', {getItem: () =>
      'https://boese.de', setItem: () => {}})"""
    assert _node(ausdruck) == ""


def test_werfender_speicher_bricht_nichts():
    ausdruck = """s.rueckwegBestimmen('?zurueck=' +
      encodeURIComponent('https://neu.tail6c7d61.ts.net'),
      {getItem: () => { throw new Error('privat'); },
       setItem: () => { throw new Error('privat'); }})"""
    assert _node(ausdruck) == "https://neu.tail6c7d61.ts.net"


def test_seite_bindet_schalter_ein():
    html = (JS.parent / "index.html").read_text(encoding="utf-8")
    assert '<script src="schalter.js"></script>' in html
    assert 'id="schalter-sales"' in html
```

- [ ] **Step 2: Rot sehen**

Run (Worktree-Wurzel): `C:\Users\User\Desktop\Vibemind_V1\.venv\Scripts\python.exe -m pytest spaces\marketing\tests\test_schalter.py -q`
Expected: FAIL — node meldet `Cannot find module …schalter.js`

- [ ] **Step 3: Implementieren** — `spaces/marketing/mockup/schalter.js`:

```javascript
// Schalter Marketing -> Sales (sales-claw Spec 2026-09-25-marketing-
// schalter-design.md §3.3). Der Rueckweg kommt aus ?zurueck= und gilt nur
// als https-Adresse im Tailnet (*.ts.net) — sonst waere die Seite eine
// offene Umleitung. Der letzte gueltige Wert wird gemerkt; ein Speicher,
// der wirft (privates Fenster), darf nichts kaputt machen.
(function (wurzel) {
  "use strict";
  var SCHLUESSEL = "sales_rueckweg";

  function rueckwegPruefen(roh) {
    if (typeof roh !== "string" || roh.indexOf("https://") !== 0) return "";
    var u;
    try { u = new URL(roh); } catch (e) { return ""; }
    if (u.protocol !== "https:" || u.username || u.password) return "";
    var host = u.hostname.toLowerCase();
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net$/.test(host)) return "";
    if (host.split(".").length < 3) return "";
    return roh;
  }

  function rueckwegBestimmen(search, speicher) {
    var neu = "";
    try { neu = new URLSearchParams(search || "").get("zurueck") || ""; }
    catch (e) { neu = ""; }
    neu = rueckwegPruefen(neu);
    if (neu) {
      try { speicher.setItem(SCHLUESSEL, neu); } catch (e) { /* egal */ }
      return neu;
    }
    try { return rueckwegPruefen(speicher.getItem(SCHLUESSEL) || ""); }
    catch (e) { return ""; }
  }

  function einsetzen() {
    var a = document.getElementById("schalter-sales");
    if (!a) return;
    var speicher;
    try { speicher = window.localStorage; } catch (e) { speicher = null; }
    var ziel = rueckwegBestimmen(window.location.search,
      speicher || { getItem: function () { return null; },
                    setItem: function () {} });
    if (ziel) { a.href = ziel; a.hidden = false; }
  }

  var api = { rueckwegPruefen: rueckwegPruefen,
              rueckwegBestimmen: rueckwegBestimmen, einsetzen: einsetzen };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    wurzel.MarketingSchalter = api;
    if (document.readyState === "loading")
      document.addEventListener("DOMContentLoaded", einsetzen);
    else einsetzen();
  }
})(typeof window !== "undefined" ? window : globalThis);
```

`index.html`: im Kopf direkt nach dem Logo-Block (`<div class="flex items-center gap-3"> … </div>`, vor `<nav class="flex items-center gap-1 ml-4 flex-wrap">`):

```html
    <!-- Schalter Sales <-> Marketing (25.09.2026): der Sales-Link erscheint
         nur mit gueltigem Rueckweg (schalter.js). -->
    <div class="flex items-center gap-1 text-xs rounded-full border border-white/10 p-0.5">
      <a id="schalter-sales" hidden class="px-2.5 py-1 rounded-full text-slate-300 hover:text-white" href="#">Sales</a>
      <span class="px-2.5 py-1 rounded-full bg-white/10 text-white font-semibold">Marketing</span>
    </div>
```

und vor `</body>`: `<script src="schalter.js"></script>`.

- [ ] **Step 4: Grün sehen** — derselbe Befehl, alle Tests PASS. Dann einmal `-m pytest spaces\marketing\tests -q` (Cockpit-Vertrag unverändert grün). Sichtprüfung: `http://127.0.0.1:5510/mockup/?zurueck=https%3A%2F%2Fvibemind-offload-1.tail6c7d61.ts.net` im Browser — Sales-Link sichtbar; ohne Parameter in einem privaten Fenster — kein Sales-Link, keine Konsolenfehler.

- [ ] **Step 5: Commit** (PowerShell, im Worktree):

```powershell
git add -- spaces/marketing/mockup/schalter.js spaces/marketing/mockup/index.html spaces/marketing/tests/test_schalter.py
git commit -m "feat(marketing): Gegen-Schalter zur Sales-Oberflaeche mit Tailnet-Rueckweg"
```

---

### Task 3: Betriebsbausteine für die VM-Instanz (sales-claw)

**Files:**
- Create: `deploy/systemd/marketing-api.service`
- Create: `deploy/marketing-aktualisieren.sh`
- Modify: `deploy/update.sh` — am Ende, nach `status_schreiben …`, nicht fatal
- Modify: `docs/04_BETRIEB_MINIPC.md` — neuer Abschnitt `## Marketing-Seite auf der VM (seit 25.09.2026)`
- Create: `deploy/tests/test_marketing_aktualisieren.sh` (erster Shell-Test im Repo; gemessen 25.09.: es gibt kein `tests/`-Verzeichnis und keine Tests für Deploy-Skripte)

**Interfaces:**
- Produces: `deploy/marketing-aktualisieren.sh` mit Umgebungsvariablen `MARKETING_OS` (Vorgabe `$HOME/marketing-os`) und `SYSTEMCTL` (Vorgabe `sudo systemctl`, im Test `echo`); Rückgabe 0 auch wenn der Checkout fehlt (Meldung „nicht eingerichtet").

- [ ] **Step 1: Failing Shell-Test** — `test_marketing_aktualisieren.sh`:

```bash
#!/usr/bin/env bash
# Prueft deploy/marketing-aktualisieren.sh gegen ein lokales Wegwerf-Repo.
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/arbeit" 2>/dev/null
( cd "$T/arbeit" && git checkout -q -b master && mkdir -p spaces/marketing \
  && echo a > spaces/marketing/x && git add . && git -c user.name=t \
  -c user.email=t@t commit -qm eins && git push -q origin master )
git clone -q -b master "$T/origin.git" "$T/marketing-os"

# 1) fehlt der Checkout: 0 und Hinweis
out="$(MARKETING_OS="$T/fehlt" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh")"
echo "$out" | grep -q "nicht eingerichtet"

# 2) nichts Neues: kein Neustart
out="$(MARKETING_OS="$T/marketing-os" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh")"
! echo "$out" | grep -q "restart marketing-api"

# 3) neuer Stand unter spaces/marketing: vorspulen und Neustart
( cd "$T/arbeit" && echo b > spaces/marketing/x && git -c user.name=t \
  -c user.email=t@t commit -qam zwei && git push -q origin master )
out="$(MARKETING_OS="$T/marketing-os" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh")"
echo "$out" | grep -q "restart marketing-api"
[ "$(cat "$T/marketing-os/spaces/marketing/x")" = b ]

# 4) lokale Aenderung: Abbruch mit Nicht-Null, nichts ueberschrieben
echo lokal > "$T/marketing-os/spaces/marketing/x"
if MARKETING_OS="$T/marketing-os" SYSTEMCTL=echo bash "$WURZEL/deploy/marketing-aktualisieren.sh"; then
  echo "FEHLER: lokale Aenderung nicht erkannt"; exit 1; fi
[ "$(cat "$T/marketing-os/spaces/marketing/x")" = lokal ]
echo "OK marketing-aktualisieren"
```

- [ ] **Step 2: Rot sehen** — `bash deploy/tests/test_marketing_aktualisieren.sh` (git-bash auf dem PC ist für Nicht-Commit-Befehle in Ordnung). Erwartet: Abbruch, Skript fehlt.

- [ ] **Step 3: Implementieren** — `deploy/marketing-aktualisieren.sh`:

```bash
#!/usr/bin/env bash
# deploy/marketing-aktualisieren.sh — zieht den schlanken vibemind-os-
# Checkout der Marketing-Seite nach und startet marketing-api neu, wenn sich
# unter spaces/marketing etwas geaendert hat (Spec 2026-09-25-marketing-
# schalter-design.md §3.1). Aufgerufen am Ende von update.sh, NICHT fatal
# fuer den Sales-Laden: ein Fehler hier rollt Sales nie zurueck.
set -euo pipefail
export LC_ALL=C
MARKETING_OS="${MARKETING_OS:-$HOME/marketing-os}"
SYSTEMCTL="${SYSTEMCTL:-sudo systemctl}"

if [ ! -d "$MARKETING_OS/.git" ]; then
  echo "Marketing-Seite: nicht eingerichtet ($MARKETING_OS fehlt) - uebersprungen."
  exit 0
fi
cd "$MARKETING_OS"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ABBRUCH Marketing-Seite: lokale Aenderungen in $MARKETING_OS." >&2
  exit 1
fi
ALT="$(git rev-parse HEAD)"
git fetch origin master --quiet
git merge --ff-only --quiet origin/master
NEU="$(git rev-parse HEAD)"
if [ "$ALT" = "$NEU" ]; then
  echo "Marketing-Seite: aktuell ($NEU)."
  exit 0
fi
if git diff --name-only "$ALT" "$NEU" | grep -qE '^spaces/(__init__\.py|marketing/)'; then
  $SYSTEMCTL restart marketing-api
  echo "Marketing-Seite: $ALT -> $NEU, neu gestartet."
else
  echo "Marketing-Seite: $ALT -> $NEU, nichts Relevantes geaendert."
fi
```

`deploy/systemd/marketing-api.service`:

```ini
[Unit]
Description=Marketing-API (zweite Instanz fuer die Marketing-Seite, nur 127.0.0.1)
After=docker.service network-online.target
Wants=network-online.target

[Service]
User=debian
WorkingDirectory=/home/debian/marketing-os
# Schluessel (MARKETING_PROPOSAL_API_KEY, MARKETING_N8N_API_KEY,
# MARKETING_UNSUB_SECRET) nur hier, Rechte 600. KEIN OPENFANG_* — die
# Benachrichtigung laeuft ueber die PC-Instanz (Plan, Global Constraints).
EnvironmentFile=/home/debian/marketing-api.env
Environment=MARKETING_HTTP_BIND=127.0.0.1
Environment=MARKETING_HTTP_PORT=5510
Environment=SUPABASE_SSH_HOST=
Environment=SUPABASE_DB_CONTAINER=debian-supabase-db-1
ExecStart=/home/debian/marketing-os/.venv/bin/python -m spaces.marketing.api.server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`SUPABASE_DB_USER`/`SUPABASE_DB_NAME` bleiben absichtlich ungesetzt: `sync/_db.py:127-128` nimmt dann `supabase_admin`/`postgres` — genau wie die PC-Instanz, deren `.env` beide nicht setzt (gemessen 25.09.).

`deploy/update.sh`, ganz am Ende:

```bash
# Marketing-Seite (25.09.2026): eigener Checkout, eigener Dienst. Ein Fehler
# dort darf den eingespielten Sales-Stand NICHT zuruecknehmen.
bash "$WURZEL/deploy/marketing-aktualisieren.sh" || \
  echo "HINWEIS: Marketing-Seite nicht aktualisiert (s. oben)."
```

Runbook-Abschnitt in `docs/04_BETRIEB_MINIPC.md`: die Einrichtungsbefehle aus Task 4 Schritt 2-6 wörtlich, dazu „Aktualisieren: läuft mit update.sh mit; von Hand `bash deploy/marketing-aktualisieren.sh`".

- [ ] **Step 4: Grün sehen** — `bash deploy/tests/test_marketing_aktualisieren.sh` → `OK marketing-aktualisieren`; `bash -n deploy/update.sh deploy/marketing-aktualisieren.sh`; `systemd-analyze verify` erst auf der VM in Task 4.

- [ ] **Step 5: Commit** (PowerShell, sales-claw):

```powershell
git add -- deploy/marketing-aktualisieren.sh deploy/systemd/marketing-api.service deploy/update.sh docs/04_BETRIEB_MINIPC.md deploy/tests/test_marketing_aktualisieren.sh
git commit -m "feat(deploy): Marketing-API als zweite Instanz auf der VM"
```

---

### Task 4: Ausliefern (NUR nach ausdrücklichem Go des Betreibers)

Deploy, neuer GitHub-Schlüssel und Tailscale-Änderung brauchen request-spezifische Freigabe. Vorher WORKBOARD-Claim `cc-marketing-schalter` eintragen und committen.

- [ ] **Step 1: Push.** sales-claw `feat/stufe-1-fundament`, vibemind-os `master` aus dem Worktree. Vorher `git status` und `git log origin/<zweig>..HEAD` — nur eigene und bereits freigegebene Commits.
- [ ] **Step 2: Leseschlüssel für vibemind-os** auf der VM:

```bash
ssh offload-vm 'ssh-keygen -t ed25519 -N "" -f ~/.ssh/marketing-os-deploy -C offload-vm-marketing-os && cat >> ~/.ssh/config <<EOF

Host github.com-marketing
  HostName github.com
  User git
  IdentityFile ~/.ssh/marketing-os-deploy
  IdentitiesOnly yes
EOF'
```

Öffentlichen Teil als **schreibgeschützten** Deploy-Key an `Flissel/vibemind-os` hängen (`gh repo deploy-key add … --title offload-vm-marketing-os`, Konto Flissel — Zwei-Konten-Falle beachten).
- [ ] **Step 3: Schlanker Checkout + venv:**

```bash
ssh offload-vm 'git clone --filter=blob:none --no-checkout --branch master git@github.com-marketing:Flissel/vibemind-os.git ~/marketing-os && cd ~/marketing-os && git sparse-checkout set spaces/marketing && git checkout master && python3 -m venv .venv && .venv/bin/pip install -q fastapi uvicorn'
```

Dann `ssh offload-vm 'cd ~/marketing-os && .venv/bin/python -c "import spaces.marketing.api.server"'` — fehlt ein Modul, genau dieses nachinstallieren und im Runbook ergänzen.
- [ ] **Step 4: Schlüsseldatei** `/home/debian/marketing-api.env` (600) mit `MARKETING_PROPOSAL_API_KEY`, `MARKETING_N8N_API_KEY`, `MARKETING_UNSUB_SECRET` — Werte per Datei-Übertragung aus der PC-`.env` (scp einer Scratchpad-Datei, danach dort löschen), nie im Befehl.
- [ ] **Step 5: Dienst:** Unit nach `/etc/systemd/system/` kopieren, `systemd-analyze verify`, `daemon-reload`, `enable --now marketing-api`. Beweis: `curl -s http://127.0.0.1:5510/api/stats` auf der VM == `curl -s http://127.0.0.1:5510/api/stats` auf dem PC (gleiche Zahlen).
- [ ] **Step 6: Tailnet:** `ssh offload-vm 'sudo tailscale serve --bg --https=8446 http://127.0.0.1:5510 && tailscale serve status'` → `:8446 (tailnet only)`.
- [ ] **Step 7: Ivan-Prüfung:** `tailscale debug netmap` bzw. die wirksame Paketregel für Ivans Knoten — erreicht er `vibemind-offload-1:8446`? Wenn ja: STOP, `tailscale serve` für 8446 wieder abschalten, Betreiber fragen.
- [ ] **Step 8: Sales:** `MARKETING_URL=https://vibemind-offload-1.tail6c7d61.ts.net:8446` in `~/sales-claw/.env` (Haupt-.env), dann `bash deploy/update.sh` (macht den Pull selbst; vorher NICHT pullen). Falls sales-ui nicht neu erstellt wurde: `docker compose up -d sales-ui` (namentlich). `docker exec sales-ui env | grep MARKETING_URL` gesetzt; `docker exec ivan-ui env | grep MARKETING_URL` leer.
- [ ] **Step 9: Echter Klick:** PC-Browser und Handy — Sales → Marketing → Sales; Sales-Link auf der Marketing-Seite zeigt auf die Sales-Adresse; im Ivan-Laden kein Schalter. WORKBOARD-Claim schließen.

---

## Self-Review (erledigt)

- Spec-Abdeckung: §3.1 → Task 3+4; §3.2 → Task 1; §3.3 → Task 2; §4 → Task 4 Step 6-7; §5 → Tests in Task 1-3, Absturz via `Restart=on-failure`; §6.1 → Task 1; §6.2 → Task 2; §6.3 → Task 4 Step 5; §6.4 → Task 4 Step 6-9.
- Einzige Abweichung (OPENFANG auf der VM) steht in den Global Constraints mit Begründung.
- Namen konsistent: `MARKETING_URL`, `_marketing_url_lesen`, `_marketing_link`, `schalter.js`, `rueckwegPruefen`, `rueckwegBestimmen`, `marketing-api`, `marketing-aktualisieren.sh`, `MARKETING_OS`, `SYSTEMCTL`.
