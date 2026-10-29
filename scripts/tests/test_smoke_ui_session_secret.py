"""deploy/smoke.sh Abschnitt 15 ("UI_SESSION_SECRET je laufender Oberflaeche").

Befund 14.10.2026: auf der VM laeuft das fremde Compose-Projekt
`bewerbung-bot` mit dem Container `bewerbung-zentrale-ui` (Dienst
`zentrale-ui`, bewusst ohne UI_SESSION_SECRET). Die Pruefung nahm jeden
laufenden `*-ui`-Container und meldete ihn rot — in der vollen Abnahme und
damit in deploy/wache.sh alle 15 Minuten. Der Fehlalarm verdeckte echte
Befunde.

Die Tests fahren das ECHTE Skript (Kopie in tmp_path, damit
deploy/laeden/ kontrolliert ist) gegen Attrappen fuer docker, curl und
python3 und lesen nur die Zeilen von Abschnitt 15. Alle anderen Abschnitte
fallen dabei erwartungsgemaess rot und werden nicht betrachtet.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "deploy" / "smoke.sh"
ABSCHNITT = "== UI_SESSION_SECRET je laufender Oberflaeche =="

# Attrappe fuer die Docker-CLI. Zustand: eine Zeile je LAUFENDEM Container,
# "name|compose-projekt|compose-dienst|UI_SESSION_SECRET". Versteht nur, was
# smoke.sh braucht; jede unbekannte Vorlage in `ps --format` bricht laut ab,
# damit ein geaendertes Format nicht still eine leere Liste liefert.
FAKE_DOCKER = r"""#!/usr/bin/env bash
zustand="$FAKE_DOCKER_STATE"
case "${1:-}" in
  ps)
    shift
    fmt=""
    filter=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --format) fmt="$2"; shift 2 ;;
        --filter) filter="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    [ -n "$fmt" ] || fmt='{{.Names}}'
    while IFS='|' read -r name projekt dienst geheim; do
      [ -n "$name" ] || continue
      case "$filter" in
        "") ;;
        label=com.docker.compose.service=*) [ "$dienst" = "${filter#label=com.docker.compose.service=}" ] || continue ;;
        label=com.docker.compose.project=*) [ "$projekt" = "${filter#label=com.docker.compose.project=}" ] || continue ;;
        *) echo "attrappe: unbekannter Filter $filter" >&2; exit 97 ;;
      esac
      zeile="${fmt//'{{.Names}}'/$name}"
      zeile="${zeile//'{{.Label "com.docker.compose.project"}}'/$projekt}"
      zeile="${zeile//'{{.Label "com.docker.compose.service"}}'/$dienst}"
      case "$zeile" in
        *'{{'*) echo "attrappe: unbekannte Vorlage $fmt" >&2; exit 98 ;;
      esac
      printf '%s\n' "$zeile"
    done < "$zustand"
    ;;
  inspect)
    name="${*: -1}"
    grep -q "^$name|" "$zustand" && echo running && exit 0
    echo "Error: No such object: $name" >&2
    exit 1
    ;;
  exec)
    name="$2"
    if [ "${3:-}" = "printenv" ] && [ "${4:-}" = "UI_SESSION_SECRET" ]; then
      zeile="$(grep "^$name|" "$zustand")" || { echo "Error: No such container: $name" >&2; exit 1; }
      geheim="${zeile##*|}"
      [ -n "$geheim" ] || exit 1
      printf '%s\n' "$geheim"
      exit 0
    fi
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
"""

FAKE_CURL = "#!/usr/bin/env bash\nprintf '000'\nexit 7\n"
FAKE_PYTHON3 = "#!/usr/bin/env bash\nexit 1\n"


def _bash() -> str:
    """Git Bash statt des WSL-Starters in System32 (Windows-Betreibermaschine)."""
    if sys.platform == "win32":
        for kandidat in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin" / "bash.exe",
        ):
            if kandidat.exists():
                return str(kandidat)
    gefunden = shutil.which("bash")
    if gefunden is None:
        pytest.skip("braucht bash")
    return gefunden


def _schreibe_ausfuehrbar(pfad: Path, inhalt: str) -> None:
    pfad.write_text(inhalt, encoding="utf-8", newline="\n")
    pfad.chmod(0o755)


def _abschnitt_15(
    tmp_path: Path,
    container: list[tuple[str, str, str, str]],
    laeden: dict[str, str] | None = None,
) -> dict[str, str]:
    """Faehrt smoke.sh gegen die Attrappen; liefert {pruefung: ergebnis} aus Abschnitt 15."""
    wurzel = tmp_path / "wurzel"
    (wurzel / "deploy" / "laeden").mkdir(parents=True)
    shutil.copyfile(SMOKE, wurzel / "deploy" / "smoke.sh")
    (wurzel / "deploy" / "laeden" / "beispiel.env").write_text(
        "LADEN_PRAEFIX=beispiel\nPORT_UI=8799\n", encoding="utf-8", newline="\n"
    )
    for name, inhalt in (laeden or {}).items():
        (wurzel / "deploy" / "laeden" / f"{name}.env").write_text(
            inhalt, encoding="utf-8", newline="\n"
        )

    attrappen = tmp_path / "bin"
    attrappen.mkdir()
    _schreibe_ausfuehrbar(attrappen / "docker", FAKE_DOCKER)
    _schreibe_ausfuehrbar(attrappen / "curl", FAKE_CURL)
    _schreibe_ausfuehrbar(attrappen / "python3", FAKE_PYTHON3)
    zustand = tmp_path / "docker-zustand"
    zustand.write_text(
        "".join("|".join(c) + "\n" for c in container), encoding="utf-8", newline="\n"
    )

    env = dict(os.environ)
    env["PATH"] = f"{attrappen}{os.pathsep}{env['PATH']}"
    env["FAKE_DOCKER_STATE"] = zustand.as_posix()
    lauf = subprocess.run(
        [_bash(), (wurzel / "deploy" / "smoke.sh").as_posix()],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert "attrappe:" not in lauf.stderr, lauf.stderr
    zeilen = lauf.stdout.splitlines()
    assert ABSCHNITT in zeilen, lauf.stdout + lauf.stderr
    ergebnis: dict[str, str] = {}
    for zeile in zeilen[zeilen.index(ABSCHNITT) + 1 :]:
        if zeile == "---":
            break
        treffer = re.match(r"^(ui_session_secret (?:je laden|\S+))\s+(.*)$", zeile)
        assert treffer, f"unerwartete Zeile in Abschnitt 15: {zeile!r}"
        ergebnis[treffer.group(1)] = treffer.group(2)
    return ergebnis


IVAN_ENV = "LADEN_PRAEFIX=ivan\nLADEN_PROJEKT=ivan-claw\nPORT_UI=8792\n"
FREMD = ("bewerbung-zentrale-ui", "bewerbung-bot", "zentrale-ui", "")


def test_foreign_ui_container_is_not_checked(tmp_path: Path) -> None:
    """Der Fall der VM seit 14.10.2026: Laeden gesund, fremdes *-ui ohne Secret."""
    ergebnis = _abschnitt_15(
        tmp_path,
        [
            ("sales-ui", "sales-claw", "sales-ui", "geheim-basis"),
            ("ivan-ui", "ivan-claw", "sales-ui", "geheim-ivan"),
            FREMD,
        ],
        {"ivan": IVAN_ENV},
    )
    assert ergebnis == {
        "ui_session_secret sales-ui": "ok",
        "ui_session_secret ivan-ui": "ok",
    }


def test_only_foreign_ui_running_counts_as_no_shop_ui(tmp_path: Path) -> None:
    ergebnis = _abschnitt_15(tmp_path, [FREMD])
    assert list(ergebnis) == ["ui_session_secret je laden"]
    assert ergebnis["ui_session_secret je laden"].startswith("uebersprungen")


def test_shop_ui_without_secret_stays_red(tmp_path: Path) -> None:
    """Die Einschraenkung darf die echten Laeden nicht lockerer pruefen."""
    ergebnis = _abschnitt_15(
        tmp_path,
        [
            ("sales-ui", "sales-claw", "sales-ui", ""),
            ("ivan-ui", "ivan-claw", "sales-ui", ""),
            FREMD,
        ],
        {"ivan": IVAN_ENV},
    )
    assert set(ergebnis) == {"ui_session_secret sales-ui", "ui_session_secret ivan-ui"}
    assert ergebnis["ui_session_secret sales-ui"].startswith("ROT: leer")
    assert ergebnis["ui_session_secret ivan-ui"].startswith("ROT: leer")
    assert "deploy/benutzer-anlegen.sh ivan" in ergebnis["ui_session_secret ivan-ui"]


def test_shop_ui_from_our_compose_service_is_checked_without_env_file(tmp_path: Path) -> None:
    """Ein Laden aus unserem docker-compose.yml (Dienst sales-ui), dessen
    Umgebungsdatei in deploy/laeden/ fehlt (verwaist, oder von Hand mit einer
    Datei anderswo gestartet), laeuft trotzdem ohne Anmeldung -> rot."""
    ergebnis = _abschnitt_15(
        tmp_path,
        [("probe-ui", "probe-claw", "sales-ui", "")],
    )
    assert list(ergebnis) == ["ui_session_secret probe-ui"]
    assert ergebnis["ui_session_secret probe-ui"].startswith("ROT: leer")


def test_shop_ui_by_name_is_checked_without_compose_labels(tmp_path: Path) -> None:
    """Ein Laden-Container ohne Compose-Etiketten (z. B. per docker run
    nachgestellt) wird ueber das Namensschema <praefix>-ui erkannt."""
    ergebnis = _abschnitt_15(
        tmp_path,
        [("sales-ui", "", "", ""), ("ivan-ui", "", "", "")],
        {"ivan": IVAN_ENV},
    )
    assert set(ergebnis) == {"ui_session_secret sales-ui", "ui_session_secret ivan-ui"}
    assert all(v.startswith("ROT: leer") for v in ergebnis.values())
