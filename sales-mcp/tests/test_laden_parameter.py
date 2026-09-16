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
import ast
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]
SALES_MCP_DIR = WURZEL / "sales-mcp"

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
    # KORREKTUR Schlussfix E (16.09.2026): das Entfernen der Variablen oben
    # bereinigt nur die PROZESSUMGEBUNG. `docker compose` liest zusaetzlich,
    # unabhaengig davon, immer die Datei `.env` im Projektverzeichnis selbst
    # (WURZEL) — auf einem Entwicklungsrechner mit einer `.env`, die z. B.
    # UI_TAILSCALE_IP traegt, waere dieser Test rot gewesen, obwohl nichts
    # kaputt ist (derselbe Befund wie in deploy/smoke.sh Abschnitt 10,
    # gemessen auf der Produktions-VM: zwei Host-Bindungen statt einer).
    # Fix: `docker compose` eine LEERE Umgebungsdatei mitgeben. `--env-file`
    # ERSETZT die projekteigene `.env` als Interpolationsquelle vollstaendig
    # (sie wird nicht zusaetzlich gelesen) — was danach noch zaehlt, ist
    # ausschliesslich `basis`/`umgebung` oben, also genau das, was dieser
    # Test ausdruecklich steuert. Uebrig bleiben Interpolations-Warnungen auf
    # stderr (z. B. "SALES_DB_URL is not set") fuer Variablen ohne
    # `:-Vorgabewert` — die sind erwartet und harmlos: `docker compose` gibt
    # dafuer trotzdem Exit 0, und einzig roh.returncode wird unten geprueft.
    leere_umgebungsdatei = tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", delete=False)
    leere_umgebungsdatei.close()
    try:
        roh = subprocess.run(
            ["docker", "compose", "--env-file", leere_umgebungsdatei.name,
             "-f", datei, "config", "--format", "json"],
            cwd=WURZEL, capture_output=True, text=True,
            env={**basis, **(umgebung or {})})
    finally:
        os.unlink(leere_umgebungsdatei.name)
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


# ---------------------------------------------------------------------------
# Waechter gegen den naechsten K1 (Schlussfix D, 16.09.2026).
#
# K1 (16.09.2026) ersetzte `env_file: .env` bei sales-mcp/sales-dispatch/
# sales-inbox/sales-auto durch den namentlichen Anker `x-sales-mcp-umgebung`
# in docker-compose.yml — richtig, weil `env_file:` einen festen Dateinamen
# traegt, den `--env-file <laden>.env` nicht ersetzt. Beim Aufzaehlen ging
# dabei CALDAV_URL/-USER/-PASSWORT verloren: kalender.py wertet einen
# fehlenden Wert lautlos als "nicht konfiguriert" (NICHT_KONFIGURIERT bzw.
# `[], None`) — kein Log, kein Fehler, kein Absturz. Ein Anker mit einer
# reinen Namensliste laeuft GENAUSO wieder auseinander, sobald irgendein
# Modul dieser vier Dienste eine neue Variable aus der Umgebung liest, ohne
# dass jemand daran denkt, den Anker nachzuziehen.
#
# UMFANG DES SCANS — bewusst NICHT "ganz sales-mcp/*.py":
# server.py/dispatch.py/inbox.py/auto.py sind die vier Dienste, die den
# Anker per `<<: *sales_mcp_umgebung` bekommen (dispatch.py/inbox.py/
# auto.py: "import server" -- Kommentar im Anker selbst). Was diese vier
# beim AUSFUEHREN tatsaechlich erreichen koennen, ist der
# Modul-Erreichbarkeitsgraph ab genau diesen vier Dateien — BFS ueber JEDE
# lokale `import`/`from ... import`-Anweisung im Baum, auch innerhalb einer
# Funktion (`ast.walk` sieht beide gleich): server.py:1678 importiert
# `mail_dispatch` z.B. erst BEIM AUFRUF der Kalendermail-Funktion, nicht am
# Dateikopf (Begruendung dort: Ringschluss-Vermeidung) — trotzdem laeuft
# dieser Code in denselben vier Containern, sobald der Pfad genommen wird,
# und seine Modul-Ebene (SMTP_*, MAIL_ONCE, ...) muss deshalb hier
# mitgezaehlt werden, nicht nur der eine Aufruf. Reiner UI-/Webhook-Code wie
# ui.py/telegram_dispatch.py/linkedin_dispatch.py/benutzer_anlegen.py/
# passwort_reset.py bleibt trotzdem draussen: server.py/dispatch.py/inbox.py/
# auto.py importieren KEINEN von ihnen, auch nicht lazy — docker-compose.yml
# begruendet an jedem dieser Dienste einzeln (T5a), warum er die breite
# Vertrauensdomaene nicht erbt, und dieser Scan widerspricht dem nicht,
# er BEOBACHTET nur, was server.py & Co tatsaechlich importieren.
_VIER_DIENSTE_EINSTIEGE = ("server", "dispatch", "inbox", "auto")


def _erreichbare_module(einstiege: tuple[str, ...]) -> set[str]:
    """BFS ueber lokale Importe ab `einstiege` (Modulnamen ohne `.py`).

    Nur Module, die als `sales-mcp/<name>.py` tatsaechlich existieren, zaehlen
    als "lokal" und werden weiterverfolgt — Fremdpakete (psycopg, yaml,
    mcp.server.mcpserver, ...) haben keine gleichnamige Datei hier und fallen
    dadurch von selbst heraus, ohne eine Ausschlussliste pflegen zu muessen.
    """
    gesehen: set[str] = set()
    warteschlange = list(einstiege)
    while warteschlange:
        name = warteschlange.pop()
        if name in gesehen:
            continue
        pfad = SALES_MCP_DIR / f"{name}.py"
        if not pfad.is_file():
            continue
        gesehen.add(name)
        baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Import):
                for alias in knoten.names:
                    kandidat = alias.name.split(".")[0]
                    if (SALES_MCP_DIR / f"{kandidat}.py").is_file():
                        warteschlange.append(kandidat)
            elif isinstance(knoten, ast.ImportFrom):
                if knoten.module and knoten.level == 0:
                    kandidat = knoten.module.split(".")[0]
                    if (SALES_MCP_DIR / f"{kandidat}.py").is_file():
                        warteschlange.append(kandidat)
    return gesehen


def _ist_leerer_vorgabewert(knoten: ast.AST | None) -> bool:
    """True nur fuer einen WOERTLICHEN leeren Vorgabewert (`""`/`None`) oder
    fehlenden Vorgabewert — genau die Form, unter der `os.environ.get(...)`
    lautlos zu "nicht konfiguriert" wird, wenn die Umgebung die Variable
    nicht traegt (die CALDAV-Bauart).

    Ein anderer woertlicher Vorgabewert (Port, Pfad, Zeitlimit, eine feste
    Kennung wie `CALDAV_USER_AGENT`s eigene) haelt den Dienst beim Fehlen
    bereits in einem bekannten, sicheren Zustand — solche Variablen muessen
    nicht durch den Anker laufen, um sicher zu sein, und werden hier
    absichtlich NICHT verlangt. Ein BERECHNETER Vorgabewert (z.B.
    `os.environ.get("SMTP_HOST", "")` als Rueckfall fuer IMAP_HOST in
    postfach.py, oder sperrliste.py's Schema-Ternary) zaehlt ebenfalls nicht
    als leer: er faellt auf eine ANDERE, bereits gepruefte Variable zurueck,
    und dieser Test wuerde deren Fehlen ohnehin an ihrer eigenen Stelle
    melden.
    """
    if knoten is None:
        return True
    if isinstance(knoten, ast.Constant):
        return knoten.value == "" or knoten.value is None
    return False


def _gelesene_variablen(modulnamen: set[str]) -> dict[str, list[str]]:
    """{Variablenname: ["datei.py:zeile", ...]} fuer jeden Fund von
    `os.environ["X"]` (kein Vorgabewert moeglich, also immer verlangt) oder
    `os.environ.get("X", ...)`/`os.getenv("X", ...)` MIT leerem/fehlendem
    Vorgabewert (siehe `_ist_leerer_vorgabewert`) in den uebergebenen
    Modulen.
    """
    fundstellen: dict[str, list[str]] = {}

    def _merke(name: str, pfad: Path, zeile: int) -> None:
        fundstellen.setdefault(name, []).append(f"{pfad.name}:{zeile}")

    for modul in modulnamen:
        pfad = SALES_MCP_DIR / f"{modul}.py"
        baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
        for knoten in ast.walk(baum):
            # os.environ["X"] — Subscript auf os.environ, kein Vorgabewert.
            if (isinstance(knoten, ast.Subscript)
                    and isinstance(knoten.value, ast.Attribute)
                    and knoten.value.attr == "environ"
                    and isinstance(knoten.value.value, ast.Name)
                    and knoten.value.value.id == "os"):
                schluessel = knoten.slice
                if isinstance(schluessel, ast.Constant) and isinstance(schluessel.value, str):
                    _merke(schluessel.value, pfad, knoten.lineno)
                continue
            if not isinstance(knoten, ast.Call):
                continue
            ziel = knoten.func
            ist_environ_get = (
                isinstance(ziel, ast.Attribute) and ziel.attr == "get"
                and isinstance(ziel.value, ast.Attribute)
                and ziel.value.attr == "environ"
                and isinstance(ziel.value.value, ast.Name)
                and ziel.value.value.id == "os")
            ist_getenv = (
                isinstance(ziel, ast.Attribute) and ziel.attr == "getenv"
                and isinstance(ziel.value, ast.Name) and ziel.value.id == "os")
            if not (ist_environ_get or ist_getenv):
                continue
            if not knoten.args or not isinstance(knoten.args[0], ast.Constant):
                continue
            name = knoten.args[0].value
            if not isinstance(name, str):
                continue
            vorgabe = knoten.args[1] if len(knoten.args) >= 2 else next(
                (kw.value for kw in knoten.keywords if kw.arg == "default"), None)
            if _ist_leerer_vorgabewert(vorgabe):
                _merke(name, pfad, knoten.lineno)
    return fundstellen


# Namentliche, begruendete Ausnahmen (Auftrag Schlussfix D, Punkt 2): Werte,
# die dieser Scan als "leerer Vorgabewert" findet, aber DIE ABSICHTLICH NICHT
# ueber den Anker laufen sollen. Jede Zeile ist eine Entscheidung, keine
# Luecke — wer eine neue hinzufuegt, tut das hier, nicht durch Stillschweigen.
_ANKER_AUSNAHMEN = {
    "DISPATCH_ONCE": (
        "dispatch.py: Demo/Einzeltest-Schalter, dokumentiert in .env.example "
        "als manuelles `docker compose run -e DISPATCH_ONCE=1 ...` fuer EINEN "
        "Aufruf — kein Wert, der dauerhaft in der Umgebungsdatei eines "
        "Ladens stuende."),
    "AUTO_ONCE": (
        "auto.py: derselbe Demo/Einzeltest-Schalter wie DISPATCH_ONCE, "
        "gleiche Begruendung."),
    "MAIL_ONCE": (
        "mail_dispatch.py: derselbe Demo/Einzeltest-Schalter wie "
        "DISPATCH_ONCE/AUTO_ONCE — erreichbar ueber server.py's lazy "
        "'import mail_dispatch' (Kalendermail-Versand, server.py:1678), "
        "gleiche Begruendung wie die beiden Geschwister."),
    "FIRMA_PRIVATE_ZIELE": (
        "recherche.py: NUR fuer die Testsuite (server_stub-Fixture, "
        "monkeypatch) — MUSS in Produktion immer leer/aus bleiben. Ein "
        "Ankereintrag waere hier keine Bequemlichkeit, sondern schaltete die "
        "SSRF-Zielpruefung in jedem Laden ab."),
    "KALENDERQUELLEN_PRIVATE_ZIELE": (
        "kalenderquellen.py: dasselbe Testsuite-only-Muster und dieselbe "
        "Begruendung wie FIRMA_PRIVATE_ZIELE (recherche.py)."),
}


@ohne_docker
def test_anker_deckt_alle_gelesenen_caldav_und_verwandten_variablen_ab():
    """Der eigentliche Waechter gegen den naechsten K1 (siehe Kommentarblock
    oben). Ohne ihn haette K1 selbst nicht gemerkt, dass CALDAV_* fehlt — die
    drei bestehenden Tests in dieser Datei pruefen Container/Volume/Port-
    Namen und die Vertrauensgrenze zwischen zwei Laeden, aber keiner davon
    fragt, ob die Anker-LISTE noch zum CODE passt, der sie liest.

    KAPUTTE FASSUNG, DIE DIESER TEST FAENGT: jede Variable, die server.py
    oder ein von ihm importiertes Modul mit einem leeren/fehlenden
    Vorgabewert aus `os.environ` liest, aber in KEINEM der vier Dienste
    sales-mcp/sales-dispatch/sales-inbox/sales-auto im aufgeloesten
    `environment:` auftaucht — der exakte Fehlermodus von K1.

    GEGENPROBE (von Hand gefuehrt, nicht Teil des automatischen Laufs):
    eine der fuenf CALDAV_*-Zeilen aus dem Anker in docker-compose.yml
    entfernt -> genau dieser Test schlaegt fehl, mit der entfernten Variable
    in der Fehlermeldung samt Fundstelle(n) im Code.
    """
    gelesen = _gelesene_variablen(_erreichbare_module(_VIER_DIENSTE_EINSTIEGE))

    cfg = _aufgeloest("docker-compose.yml")
    verfuegbar: set[str] = set()
    for dienst in ("sales-mcp", "sales-dispatch", "sales-inbox", "sales-auto"):
        verfuegbar |= set(cfg["services"][dienst]["environment"])

    fehlend = {
        name: stellen for name, stellen in gelesen.items()
        if name not in verfuegbar and name not in _ANKER_AUSNAHMEN
    }
    assert not fehlend, (
        "Diese Variablen liest server.py (oder ein importiertes Modul) mit "
        "leerem/fehlendem Vorgabewert, stehen aber in KEINEM der vier "
        "Dienste im aufgeloesten environment: " +
        ", ".join(f"{n} ({'/'.join(stellen)})" for n, stellen in sorted(fehlend.items())) +
        " — entweder in x-sales-mcp-umgebung nachtragen (docker-compose.yml) "
        "oder hier in _ANKER_AUSNAHMEN mit Begruendung eintragen.")

    # Gegenprobe zur Gegenprobe: CALDAV_URL selbst MUSS von diesem Scan
    # gefunden werden (kalender.py:472, leerer Vorgabewert) — schlaegt diese
    # Zusicherung fehl, scannt die Funktion oben etwas anderes als gedacht
    # (z.B. weil kalender.py nicht mehr im Erreichbarkeitsgraphen liegt) und
    # der Waechter waere nur scheinbar scharf.
    assert "CALDAV_URL" in gelesen, (
        "Der Scan findet CALDAV_URL nicht mehr in kalender.py — pruefen, ob "
        "kalender.py noch ueber server.py erreichbar ist (server.py: "
        "'import kalender').")


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


@ohne_docker
def test_zweiter_laden_bekommt_eigene_db_und_nicht_die_kanal_zugangsdaten_des_ersten():
    """Schlussprüfung K1 (16.09.2026), als Regressionswache.

    Vier Dienste (sales-mcp, sales-dispatch, sales-inbox, sales-auto) trugen
    `env_file: - .env` — ein FESTER Dateiname, den `docker compose
    --env-file <laden>.env` NICHT ersetzt (das steuert nur die
    `${...}`-Interpolation). Gemessen: ein zweiter Laden liefe mit
    `SALES_DB_URL`/`SALES_DB_SCHEMA` des BASIS-Ladens (voller Zugriff auf
    dessen Kundendaten) und erbte woertlich dessen OPENWA_API_KEY. Der Fix
    ersetzt `env_file:` durch den Anker `x-sales-mcp-umgebung`, der dieselben
    Namen per `${...}` setzt — und DAS reagiert auf `--env-file`.

    Dieser Test braucht kein echtes `deploy/laeden/*.env`: er setzt die
    Interpolationsquelle direkt in der Prozessumgebung des
    `docker compose config`-Aufrufs — fuer die Variablen-Aufloesung ist das
    ununterscheidbar von `--env-file` (beides fuellt denselben Namensraum,
    aus dem `${VAR}` liest). Vor dem Fix war `environment:` bei diesen vier
    Diensten schlicht LEER (nur `env_file:` stand da) — solche Ueberschreibungen
    haetten also gar nichts bewirkt, egal wie sie ankamen.

    KAPUTTE FASSUNG, DIE DIESER TEST FAENGT: `env_file: - .env` statt eines
    `${...}`-interpolierten `environment:`-Eintrags fuer irgendeinen der
    vier Dienste — dann zeigt `docker compose config` fuer diesen Dienst
    entweder den WERT AUS DER LOKALEN `.env` (nicht den hier gesetzten) oder
    (falls die Datei den Schluessel gar nicht kennt) GAR KEINEN Eintrag,
    statt des erwarteten `sales_ivan`/der Ivan-DSN — verifiziert per
    Handprobe: mit `env_file:` statt Anker schlaegt genau diese Zusicherung
    fehl (siehe schluss-fix-a-report.md, Abschnitt K1).
    """
    GEHEIMNIS_ERSTER_LADEN = "BASIS-OPENWA-SCHLUESSEL-TESTWERT"
    DSN_ZWEITER_LADEN = (
        "postgresql://sales_app_ivan:testpw@192.168.178.65:54322/postgres")

    erst = _aufgeloest("docker-compose.yml", {
        "OPENWA_API_KEY": GEHEIMNIS_ERSTER_LADEN,
    })
    zweit = _aufgeloest("docker-compose.yml", {
        "SALES_DB_URL": DSN_ZWEITER_LADEN,
        "SALES_DB_SCHEMA": "sales_ivan",
        # Ivan hat bewusst KEINEN eigenen OpenWA-Schluessel gesetzt — genau
        # der Fall aus deploy/laeden/beispiel.env heute. Er darf NICHT den
        # des Betreibers bekommen.
    })

    VIER_DIENSTE = ("sales-mcp", "sales-dispatch", "sales-inbox", "sales-auto")
    for dienst in VIER_DIENSTE:
        umg_zweit = zweit["services"][dienst]["environment"]
        assert umg_zweit.get("SALES_DB_URL") == DSN_ZWEITER_LADEN, (
            f"{dienst}: SALES_DB_URL folgt nicht der Umgebungsdatei des "
            f"Ladens — env_file: statt Anker?")
        assert umg_zweit.get("SALES_DB_SCHEMA") == "sales_ivan", (
            f"{dienst}: SALES_DB_SCHEMA folgt nicht der Umgebungsdatei des "
            f"Ladens — Ivan liefe auf einem fremden Schema.")
        assert umg_zweit.get("OPENWA_API_KEY") != GEHEIMNIS_ERSTER_LADEN, (
            f"{dienst}: hat den OPENWA_API_KEY des BASIS-Ladens geerbt — "
            f"genau der Befund aus K1.")

    # Gegenprobe zur Gegenprobe: der ERSTE Laden bekommt weiterhin seinen
    # EIGENEN gesetzten Wert (der Anker unterdrueckt ihn nicht einfach nur).
    for dienst in VIER_DIENSTE:
        umg_erst = erst["services"][dienst]["environment"]
        assert umg_erst.get("OPENWA_API_KEY") == GEHEIMNIS_ERSTER_LADEN, (
            f"{dienst}: bekommt nicht einmal seinen EIGENEN Schluessel — "
            f"der Anker liest environment: nicht mehr aus?")
