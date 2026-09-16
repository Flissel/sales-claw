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
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]

ohne_docker = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="braucht Docker; laeuft zusaetzlich in deploy/smoke.sh")

# Diese Variablen parametrisiert genau dieser Plan (2026-09-16). Sie muessen
# aus der Umgebung jedes Aufrufs entfernt werden, bevor `umgebung` ueberlagert
# wird — sonst koennte ein auf der Testmaschine zufaellig gesetzter Wert
# (z.B. ein exportiertes LADEN_PRAEFIX aus einer anderen Sitzung) das
# Ergebnis verfaelschen, und der Test waere gruen, ohne etwas zu pruefen.
_LADEN_VARIABLEN = (
    "LADEN_PRAEFIX", "LADEN_PROJEKT", "PORT_GATEWAY", "PORT_UI",
    "PORT_OPENWA", "UI_TAILSCALE_IP",
)


def _aufgeloest(datei: str, umgebung: dict | None = None) -> dict:
    """`docker compose config` mit der eigenen Umgebung, bereinigt um die
    Laden-Variablen, plus dem ausdruecklich Uebergebenen.

    KORREKTUR ZUM BRIEF (Vorab-Abgleich 16.09.2026): der Brief sah eine fest
    verdrahtete POSIX-Liste vor (`env={"PATH": "/usr/bin:/bin:/usr/local/bin",
    ...}`). Auf Windows liegt `docker.exe` an einem Windows-Pfad — mit dieser
    Liste faende `subprocess.run` kein `docker` und JEDER Test schluege mit
    `FileNotFoundError`/Exit!=0 fehl, unabhaengig vom eigentlichen Verhalten.
    Der Zweck bleibt derselbe wie im Brief (kein zufaellig gesetztes
    LADEN_PRAEFIX darf das Ergebnis faelschen): wir uebernehmen deshalb die
    tatsaechliche Prozessumgebung (PATH inklusive) und entfernen daraus
    gezielt nur die Variablen, die dieser Plan einfuehrt.
    """
    basis = dict(os.environ)
    for k in _LADEN_VARIABLEN:
        basis.pop(k, None)
    roh = subprocess.run(
        ["docker", "compose", "-f", datei, "config", "--format", "json"],
        cwd=WURZEL, capture_output=True, text=True,
        env={**basis, **(umgebung or {})})
    assert roh.returncode == 0, roh.stderr
    return json.loads(roh.stdout)


def _hostports(dienst: dict) -> set[str]:
    """Host-IP+Port eines Dienstes aus `docker compose config --format json`.

    KORREKTUR ZUM BRIEF: der Brief nahm die Feldnamen `host_ip`/`published`
    an, ohne das gegen echten Output geprueft zu haben. Verifiziert am
    16.09.2026 mit `docker compose version` (Docker 29.7.2 / Compose v5.5.1)
    per echtem `docker compose -f docker-compose.yml config --format json`:
    ein Ports-Eintrag sieht so aus wie
    `{"mode": "ingress", "host_ip": "127.0.0.1", "target": 18894,
      "published": "18894", "protocol": "tcp"}` — die Feldnamen aus dem
    Brief stimmen fuer diese Compose-Version tatsaechlich. `published` ist
    dabei ein STRING, kein int; das ist fuer den f-String-Vergleich hier
    unerheblich, aber wer diese Funktion fuer numerische Vergleiche
    weiterverwendet, sollte das wissen.
    """
    return {f"{p.get('host_ip', '')}:{p['published']}"
            for p in dienst.get("ports", [])}


@ohne_docker
def test_ohne_umgebung_bleibt_alles_wie_heute():
    """Der gemessene Stand vom 16.09.2026, wortwoertlich.

    Kaputte Fassung, die dieser Test faengt: JEDE Aenderung an
    docker-compose.yml, die den bestehenden Laden ohne gesetzte
    Umgebungsvariablen anders auifloesen laesst als heute — allen voran ein
    Vorgabewert, der nicht exakt "sales"/"sales-claw"/"18894"/"8791" ist.
    Dieser Test muss ueber den GANZEN Plan hinweg gruen bleiben.
    """
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
    Aenderung — er ist vor Schritt 3/4 also rot, und das ist richtig so.
    Das Volume wird NICHT von diesem Lauf umkopiert (Korrektur zum Brief,
    Vorab-Abgleich 16.09.2026): das ist ein Eingriff in den produktiven
    Container und bleibt Betreiber-Sache.

    Kaputte Fassung, die dieser Test faengt: ein vergessener oder
    vertippter container_name/Volume-name in docker-compose.openwa.yml.
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

    Kaputte Fassung, die dieser Test faengt: irgendein container_name,
    Volume-Name (ausser sales-stt-modelle) oder Host-Port, der NICHT von
    LADEN_PRAEFIX/LADEN_PROJEKT/PORT_* abhaengt und deshalb beim zweiten
    Laden mit dem ersten kollidiert.
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
