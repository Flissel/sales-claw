"""deploy/update.sh baut jeden Build-Kontext GENAU EINMAL und nacheinander, und zwei Laeufe
schliessen sich per Sperre aus.

Anlass (11.11.2026): `docker compose up -d --build <viele Dienste>` startete fuer die ~14 Dienste
mit `build: ./sales-mcp` und demselben Image bis zu 12 IDENTISCHE Builds gleichzeitig; BuildKit
stuerzte dabei ab (`concurrent map iteration and map write`) und riss dockerd mit allen Containern
der VM um. Seitdem: je Kontext ein `docker compose <args> build <vertreter>` in einer Schleife, danach
`up -d --no-build <alle Dienste>`.

Rein: update.sh laeuft in einem Wegwerf-Ordner mit Attrappen fuer docker, git, sleep, python3 und
die Hilfsskripte (das sales-mcp-Image der CI hat kein git). Kein Docker-Daemon, kein Netz, keine
echte Umgebungsdatei."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
ECHTES_FLOCK = shutil.which("flock")

pytestmark = pytest.mark.skipif(BASH is None, reason="braucht bash")

# Attrappe fuer git: ein Stand alt0000 -> neu1111 liegt bereit, geaendert sind $FAKE_GEAENDERT.
_GIT = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GIT_LOG"
case "$1 ${2:-}" in
  "rev-parse --abbrev-ref") echo master ;;
  "rev-parse HEAD") echo alt0000 ;;
  "rev-parse origin/master") echo neu1111 ;;
  "diff --name-only") printf '%s\n' "$FAKE_GEAENDERT" ;;
esac
exit 0
"""

# Attrappe fuer docker: protokolliert jeden Aufruf, antwortet wie ein Stack, in dem alles laeuft.
# `compose ... config --format json <dienste>` liefert je Dienst einen Build-Abschnitt wie
# docker-compose.yml (sales-mcp-Familie teilt Kontext UND Image). `compose ... build` markiert
# Anfang und Ende, damit eine Ueberlappung zweier Builds im Protokoll sichtbar waere.
_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
case "$1" in
  inspect) echo running; exit 0 ;;
  run) echo inhalt; exit 0 ;;
  exec) echo ready; exit 0 ;;
  compose) ;;
  *) exit 0 ;;
esac
shift
while [ "$#" -gt 0 ]; do
  case "$1" in
    config)
      shift
      [ "${1:-}" = "--format" ] && shift 2
      printf '{"name":"x","services":{'
      sep=""
      for d in "$@"; do
        case "$d" in
          sales-claw) b='"image":"openclaw"' ;;
          sales-stt) b='"build":{"context":"/r/sales-stt","dockerfile":"Dockerfile"},"image":"sales-claw-sales-stt:local"' ;;
          sales-ki) b='"build":{"context":"/r/sales-ki","dockerfile":"Dockerfile"},"image":"sales-claw-sales-ki:local"' ;;
          sales-auge) b='"build":{"context":"/r/sales-mcp","dockerfile":"Dockerfile.auge"},"image":"sales-claw-sales-auge:local"' ;;
          openwa) b='"build":{"context":"/r/openwa/upstream","dockerfile":"Dockerfile"}' ;;
          *) b='"build":{"context":"/r/sales-mcp","dockerfile":"Dockerfile"},"image":"sales-claw-sales-mcp:local"' ;;
        esac
        printf '%s"%s":{%s}' "$sep" "$d" "$b"
        sep=","
      done
      printf '}}\n'
      exit 0 ;;
    build)
      shift
      echo "BAU-ANFANG $*" >> "$FAKE_LOG"
      [ -n "${FAKE_BAU_FEHLER:-}" ] && exit 1
      echo "BAU-ENDE $*" >> "$FAKE_LOG"
      exit 0 ;;
    up) exit 0 ;;
  esac
  shift
done
exit 0
"""


def _schreiben(pfad: Path, text: str, ausfuehrbar: bool = False) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(text, encoding="utf-8", newline="\n")
    if ausfuehrbar:
        pfad.chmod(0o755)


def _python3_attrappe(bin_: Path) -> None:
    """python3 = der Interpreter dieses Testlaufs. Unter Windows ist `python3` sonst ein
    pyenv-Shim (.bat), der das mehrzeilige `python3 -c` aus update.sh zerlegt; auf der VM und im
    CI ist es ohnehin ein echtes python3."""
    _schreiben(bin_ / "python3", f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n',
               ausfuehrbar=True)


def _posix_pfad(p: Path) -> str:
    """C:\\a\\b -> /c/a/b fuer den PATH der Git-Bash; unter POSIX unveraendert."""
    if os.name != "nt":
        return str(p)
    s = p.resolve().as_posix()
    return f"/{s[0].lower()}{s[2:]}" if len(s) > 1 and s[1] == ":" else s


class Aufbau:
    """Wegwerf-Checkout mit Attrappen-PATH; `aendern()` legt fest, was der neue Stand aendert."""

    def __init__(self, tmp: Path, flock: str | None = None):
        self.tmp = tmp
        self.betrieb_checkout = tmp / "checkout"
        self.betrieb = tmp / "betrieb"
        self.log = tmp / "docker.log"
        self.git_log = tmp / "git.log"
        self.bin = tmp / "bin"
        self.geaendert = ""
        a = self.betrieb_checkout
        _schreiben(a / "deploy" / "update.sh",
                   (WURZEL / "deploy" / "update.sh").read_text(encoding="utf-8").replace("\r\n", "\n"))
        for name, inhalt in {
            "smoke.sh": 'exit "${FAKE_SMOKE_RC:-0}"\n',
            "marketing-aktualisieren.sh": "exit 0\n",
            "chat-eingang-anlegen.sh": "exit 0\n",
            "fenster-netz-anlegen.sh": "exit 0\n",
        }.items():
            _schreiben(a / "deploy" / name, "#!/usr/bin/env bash\n" + inhalt, ausfuehrbar=True)
        for name in ("docker-compose.yml", "docker-compose.fenster.yml", "docker-compose.openwa.yml"):
            _schreiben(a / name, "services: {}\n")
        # Ein zweiter Laden mit Wegwerf-Umgebungsdatei.
        _schreiben(a / "deploy" / "laeden" / "zwei.env",
                   "LADEN_PRAEFIX=zwei\nMEDIEN_ORDNER=/x/zwei-medien\nMEDIEN_ERZEUGT_ORDNER=/x/zwei-erzeugt\n")
        _schreiben(self.bin / "docker", _DOCKER, ausfuehrbar=True)
        _schreiben(self.bin / "git", _GIT, ausfuehrbar=True)
        _schreiben(self.bin / "sleep", "#!/usr/bin/env bash\nexit 0\n", ausfuehrbar=True)
        _python3_attrappe(self.bin)
        if flock is not None:
            _schreiben(self.bin / "flock", f"#!/usr/bin/env bash\nexit {flock}\n", ausfuehrbar=True)
        self.log.write_text("", encoding="utf-8")
        self.git_log.write_text("", encoding="utf-8")

    def aendern(self, rel: str) -> None:
        self.geaendert = rel

    def lauf(self, **env_extra: str) -> subprocess.CompletedProcess:
        env = {**os.environ,
               "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
               "FAKE_LOG": str(self.log),
               "FAKE_GIT_LOG": str(self.git_log),
               "FAKE_GEAENDERT": self.geaendert,
               "SALES_BETRIEB": str(self.betrieb),
               "OPENWA_WARTE_S": "0",
               **env_extra}
        # Die Attrappen muessen VOR /usr/bin stehen: Git-Bash unter Windows setzt beim Start
        # /mingw64/bin:/usr/bin nach vorn (dort liegen git und sleep), deshalb PATH erst in der Shell.
        env["FAKE_BIN"] = _posix_pfad(self.bin)
        return subprocess.run([BASH, "-c", 'PATH="$FAKE_BIN:$PATH" exec bash deploy/update.sh'],
                              cwd=self.betrieb_checkout, env=env, capture_output=True, text=True,
                              timeout=120)

    def aufrufe(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


def _flock_fuer_attrappe() -> str | None:
    """Wo es kein echtes flock gibt (Git-Bash unter Windows), eine Attrappe, die die Sperre gibt."""
    return None if ECHTES_FLOCK else "0"


def _compose(aufrufe: list[str], unterbefehl: str) -> list[str]:
    return [z for z in aufrufe if z.startswith("compose ") and f" {unterbefehl} " in f" {z} "]


def _dienste_nach(zeile: str, wort: str) -> list[str]:
    teile = zeile.split()
    rest = teile[teile.index(wort) + 1:]
    return [t for t in rest if not t.startswith("-")]


def _pruefe_ein_bau_je_kontext(aufrufe: list[str]) -> None:
    builds = _compose(aufrufe, "build")
    ups = _compose(aufrufe, "up")
    assert ups, aufrufe
    for z in ups:
        assert "--build" not in z.split(), z           # nie mehr `up --build`
        assert "--no-build" in z.split(), z
    for z in builds:
        assert len(_dienste_nach(z, "build")) == 1, z  # ein Kontext je Aufruf, nie mehrere parallel
    # Je Laden-Argumentsatz hoechstens ein Build je Kontext.
    gesehen = set()
    for z in builds:
        args = z.split(" build ")[0]
        dienst = _dienste_nach(z, "build")[0]
        kontext = {"sales-ki": "ki", "sales-stt": "stt", "openwa": "openwa",
                   "sales-auge": "auge"}.get(dienst, "mcp")
        assert (args, kontext) not in gesehen, (z, builds)
        gesehen.add((args, kontext))
    # Nacheinander: jeder Build endet, bevor der naechste anfaengt.
    marken = [z.split()[0] for z in aufrufe if z.startswith("BAU-")]
    assert marken == ["BAU-ANFANG", "BAU-ENDE"] * (len(marken) // 2), aufrufe


def test_mcp_aenderung_baut_je_kontext_einmal_und_startet_ohne_build(tmp_path):
    a = Aufbau(tmp_path, flock=_flock_fuer_attrappe())
    a.aendern("sales-mcp/x")
    r = a.lauf()
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "merge --ff-only origin/master" in a.git_log.read_text(encoding="utf-8")
    assert "Update eingespielt und Abnahme gruen." in r.stdout
    aufrufe = a.aufrufe()
    _pruefe_ein_bau_je_kontext(aufrufe)
    builds = _compose(aufrufe, "build")
    ups = _compose(aufrufe, "up")
    # Basis-Laden: sales-mcp-Familie einmal, sales-ki und sales-auge (eigenes Image) je einmal;
    # zweiter Laden ebenso, mit --env-file.
    basis = [z for z in builds if "--env-file" not in z]
    zwei = [z for z in builds if "--env-file" in z]
    assert [_dienste_nach(z, "build") for z in basis] == [["sales-mcp"], ["sales-ki"], ["sales-auge"]], builds
    assert [_dienste_nach(z, "build") for z in zwei] == [["sales-mcp"], ["sales-ki"], ["sales-auge"]], builds
    assert len(ups) == 2
    # config, build und up eines Ladens tragen dieselben Argumente (nie ohne die Laden-Umgebung).
    for satz in (basis, zwei):
        args = satz[0].split(" build ")[0]
        assert any(z.startswith(args + " config ") for z in _compose(aufrufe, "config")), aufrufe
        assert any(z.startswith(args + " up ") for z in ups), aufrufe
    assert "zwei.env" in zwei[0]
    assert "docker-compose.fenster.yml" in basis[0] and "docker-compose.fenster.yml" not in zwei[0]
    # up bekommt weiter ALLE Dienste in der bisherigen Reihenfolge, auch die ohne build (sales-claw).
    up_basis = _dienste_nach([z for z in ups if "--env-file" not in z][0], "up")
    assert up_basis[:3] == ["sales-mcp", "sales-ui", "sales-inbox"] and "sales-claw" in up_basis
    # Erst bauen, dann starten - je Laden.
    assert aufrufe.index(basis[-1]) < aufrufe.index([z for z in ups if "--env-file" not in z][0])


def test_compose_aenderung_mit_roter_abnahme_baut_auch_openwa_und_rueckbau_je_kontext_einmal(tmp_path):
    a = Aufbau(tmp_path, flock=_flock_fuer_attrappe())
    a.aendern("docker-compose.yml")
    r = a.lauf(FAKE_SMOKE_RC="1")
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "Rueckbau" in r.stderr
    aufrufe = a.aufrufe()
    builds = _compose(aufrufe, "build")
    openwa = [z for z in builds if "docker-compose.openwa.yml" in z]
    assert [_dienste_nach(z, "build") for z in openwa] == [["openwa"], ["openwa"]], builds
    # Bau-Schleife und Rueckbau je fuer sich: ein Build je Kontext und Laden.
    rueck = max(i for i, z in enumerate(aufrufe) if "openwa.yml" in z and " up " in f" {z} ") + 1
    _pruefe_ein_bau_je_kontext(aufrufe[:rueck])
    _pruefe_ein_bau_je_kontext(aufrufe[rueck:])
    assert _compose(aufrufe[rueck:], "build"), "Rueckbau baut den alten Stand nicht neu"
    assert any("--no-build openwa" in z for z in _compose(aufrufe, "up"))


def test_gescheiterter_build_bricht_ab_ohne_up(tmp_path):
    a = Aufbau(tmp_path, flock=_flock_fuer_attrappe())
    a.aendern("sales-mcp/x")
    r = a.lauf(FAKE_BAU_FEHLER="1")
    assert r.returncode != 0
    aufrufe = a.aufrufe()
    assert len(_compose(aufrufe, "build")) == 1, aufrufe
    assert not _compose(aufrufe, "up"), aufrufe


def test_bauen_und_starten_gruppiert_nach_kontext_und_image(tmp_path):
    """Einheit: Dienste ohne build werden nie gebaut; gleicher Kontext mit anderem Image zaehlt
    eigens (sonst bliebe das zweite Image alt); ohne image ist jeder Dienst sein eigenes Image."""
    u = (WURZEL / "deploy" / "update.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(r"^bauen_und_starten\(\) \{.*?^\}$", u, re.M | re.S)
    assert m, "bauen_und_starten() fehlt"
    docker = (
        'docker() { printf "%s\\n" "$*" >> "$LOG"; case " $* " in\n'
        '  *" config "*) printf \'%s\' \'{"services":{'
        '"a":{"build":{"context":"/k1"},"image":"i1"},'
        '"b":{"build":{"context":"/k1"},"image":"i1"},'
        '"c":{"build":{"context":"/k1"},"image":"i2"},'
        '"d":{"image":"fertig"},'
        '"e":{"build":{"context":"/k2"}},"f":{"build":{"context":"/k2"}}}}\' ;;\n'
        "esac; }\n")
    log = tmp_path / "log"
    _python3_attrappe(tmp_path / "bin")
    skript = (f'set -euo pipefail\nLOG="{log.as_posix()}"\n{docker}{m.group(0)}\n'
              "bauen_und_starten --env-file x.env -f a.yml -- a b c d e f b\n")
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run([BASH, "-c", skript], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    zeilen = log.read_text(encoding="utf-8").splitlines()
    assert zeilen == [
        "compose --env-file x.env -f a.yml config --format json a b c d e f b",
        "compose --env-file x.env -f a.yml build a",
        "compose --env-file x.env -f a.yml build c",
        "compose --env-file x.env -f a.yml build e",
        "compose --env-file x.env -f a.yml build f",
        "compose --env-file x.env -f a.yml up -d --no-build a b c d e f b",
    ]


def test_update_sh_ruft_nirgends_mehr_up_mit_build():
    u = (WURZEL / "deploy" / "update.sh").read_text(encoding="utf-8")
    code = "\n".join(z for z in u.splitlines() if not z.lstrip().startswith("#"))
    assert "--build" not in code.replace("--no-build", "")
    assert "up -d --no-build" in code


# --- Sperre ------------------------------------------------------------------------------------------

def _pruefe_sperre_greift(a: Aufbau, r: subprocess.CompletedProcess) -> None:
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "laeuft bereits" in r.stderr, r.stderr
    assert a.aufrufe() == [], a.aufrufe()                       # kein einziger docker-Aufruf
    assert not (a.betrieb / "update-status.json").exists()      # Status des laufenden Updates unberuehrt
    assert a.git_log.read_text(encoding="utf-8") == ""          # kein fetch, kein merge, kein tag


def test_sperre_attrappe_zweiter_lauf_bricht_ab_ohne_docker(tmp_path):
    """Ueberall lauffaehig: flock meldet "Sperre belegt" (exit 1)."""
    a = Aufbau(tmp_path, flock="1")
    a.aendern("sales-mcp/x")
    _pruefe_sperre_greift(a, a.lauf())


@pytest.mark.skipif(ECHTES_FLOCK is None, reason="braucht echtes flock (util-linux)")
def test_sperre_echt_zweiter_lauf_bricht_ab_ohne_docker(tmp_path):
    a = Aufbau(tmp_path)
    a.aendern("sales-mcp/x")
    a.betrieb.mkdir(parents=True, exist_ok=True)
    import fcntl  # nur POSIX; ohne echtes flock ist dieser Test ohnehin uebersprungen
    # Der "erste Lauf" ist dieser Testprozess: er haelt dieselbe flock(2)-Sperre wie update.sh.
    with open(a.betrieb / "update.lock", "w") as halter:
        fcntl.flock(halter, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert subprocess.run([ECHTES_FLOCK, "-n", str(a.betrieb / "update.lock"), "true"]).returncode != 0
        _pruefe_sperre_greift(a, a.lauf())
    # Ist die Sperre frei, laeuft das Update normal.
    r = a.lauf()
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _compose(a.aufrufe(), "build")
