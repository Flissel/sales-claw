"""Smoke-Liste und Compose laufen nicht auseinander.

Rein (liest nur Dateien, braucht weder DB noch Docker). Hintergrund: am
09.11.2026 brach `deploy/update.sh` das Ausrollen von sales-kalender ab und
baute zurueck, weil `deploy/smoke.sh` (Abschnitt Compose-Aufloesung) eine
feste Liste erwarteter Container fuehrt und der neue Dienst darin fehlte.
Derselbe Fehler war kurz vorher beim freigabe-bote passiert. Die Docker-
gestuetzte Fassung (test_laden_parameter) laeuft im Container nicht mit,
darum dieser Vertrag ohne Docker.
"""
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]


def _lesen(rel: str) -> str:
    return (WURZEL / rel).read_text(encoding="utf-8")


def _container_ohne_profil() -> set[str]:
    """container_name jedes Dienstes in docker-compose.yml, der ohne
    `profiles:` startet, mit dem Vorgabe-Praefix aufgeloest (sales-...)."""
    text = _lesen("docker-compose.yml")
    dienste_teil = text[text.index("\nservices:") + 1:]
    dienste_teil = re.split(r"^\S", dienste_teil, flags=re.M)[1]  # bis zum naechsten Top-Level
    namen = set()
    for m in re.finditer(r"^  ([a-z][\w-]*):\s*\n(.*?)(?=^  \S|\Z)", dienste_teil, re.M | re.S):
        code = "\n".join(z for z in m.group(2).splitlines() if not z.lstrip().startswith("#"))
        if re.search(r"^\s+profiles:", code, re.M):
            continue
        cn = re.search(r"^\s+container_name:\s*(\S+)", code, re.M)
        assert cn, f"Dienst {m.group(1)} ohne container_name"
        namen.add(cn.group(1).replace("${LADEN_PRAEFIX:-sales}", "sales"))
    return namen


def _smoke_erwartet() -> set[str]:
    smoke = _lesen("deploy/smoke.sh")
    roh = re.search(r"erwartete_container = \{(.*?)\}", smoke, re.S).group(1)
    return set(re.findall(r'"([^"]+)"', roh))


def test_smoke_erwartet_genau_die_container_aus_compose():
    compose = _container_ohne_profil()
    assert "sales-kalender" in compose and "sales-ui" in compose
    assert _smoke_erwartet() == compose


def test_laden_parameter_kennt_dieselben_container():
    """Die Docker-gestuetzte Fassung muss dieselbe Liste tragen, sonst ist sie
    auf dem Host (CI host-suite) rot."""
    text = _lesen("sales-mcp/tests/test_laden_parameter.py")
    m = re.search(r'\{d\["container_name"\] for d in cfg\["services"\]\.values\(\)\} == \{(.*?)\}',
                  text, re.S)
    assert m
    assert set(re.findall(r'"([^"]+)"', m.group(1))) == _container_ohne_profil()
