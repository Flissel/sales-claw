"""Dienst sales-kanaele: Compose, Update, Smoke, Eintrage-Skript, Doku.

Rein (liest nur Dateien, braucht weder DB noch Docker). Faengt vor allem
das Auseinanderlaufen der Env-Namen: kanaele.KANAELE ist die einzige
Quelle, Compose, Skript, .env.example und die Rotations-Doku muessen
dieselben Namen woertlich tragen — sonst kommt ein eingetragener Zugang
nie im Container an und der Kanal bleibt still "nicht verbunden".
"""
import re
from pathlib import Path

import kanaele

WURZEL = Path(__file__).resolve().parents[2]


def _lesen(rel: str) -> str:
    return (WURZEL / rel).read_text(encoding="utf-8")


def _alle_namen() -> list[str]:
    return [n for info in kanaele.KANAELE.values() for n in info.env_namen]


def _compose_abschnitt(dienst: str) -> str:
    text = _lesen("docker-compose.yml")
    m = re.search(rf"^  {re.escape(dienst)}:\n(.*?)(?=^  \S|^\S|\Z)",
                  text, re.M | re.S)
    assert m, f"Dienst {dienst} fehlt in docker-compose.yml"
    return m.group(1)


def test_compose_dienst_hat_alle_kanal_variablen_mit_leerer_vorgabe():
    abschnitt = _compose_abschnitt("sales-kanaele")
    for n in _alle_namen():
        assert f"{n}=${{{n}:-}}" in abschnitt, n
    assert "BLUESKY_PDS=${BLUESKY_PDS:-https://bsky.social}" in abschnitt
    # YouTube: ohne ausdrueckliche Wahl des Betreibers privat.
    assert "YOUTUBE_SICHTBARKEIT=${YOUTUBE_SICHTBARKEIT:-private}" in abschnitt
    assert "SALES_DB_URL=${SALES_DB_URL}" in abschnitt
    assert "KANAL_INTERVAL_S=60" in abschnitt
    assert "container_name: ${LADEN_PRAEFIX:-sales}-kanaele" in abschnitt
    assert "command: python kanal_dispatch.py" in abschnitt
    assert "stop_grace_period: 120s" in abschnitt
    assert ":/media:ro" in abschnitt and ":/media-erzeugt:ro" in abschnitt
    # nur Code-Zeilen pruefen, Kommentare duerfen env_file erwaehnen
    code = "\n".join(z for z in abschnitt.splitlines()
                     if not z.lstrip().startswith("#"))
    assert "env_file" not in code


def test_update_und_smoke_kennen_den_dienst():
    update = _lesen("deploy/update.sh")
    m = re.search(r'^KERN_ALLE="([^"]*)"', update, re.M)
    assert m and m.group(1).split()[-2:] == ["sales-linkedin", "sales-kanaele"]
    assert re.search(r"for _dienst in [^;]*\bsales-kanaele\b", update)

    smoke = _lesen("deploy/smoke.sh")
    schleife = re.search(r"^for c in (sales-mcp [^;]*);", smoke, re.M)
    assert schleife and "sales-kanaele" in schleife.group(1).split()
    erwartet = re.search(r"erwartete_container = \{(.*?)\}", smoke, re.S)
    assert erwartet and '"sales-kanaele"' in erwartet.group(1)


def test_nicht_in_laden_anlegen():
    # Praezisierung 5: nur im Basis-Laden
    assert "sales-kanaele" not in _lesen("deploy/laden-anlegen.sh")
    assert "sales-kanaele" not in _lesen("deploy/laeden/beispiel.env")


def test_eintrage_skript_kennt_dieselben_namen():
    skript = _lesen("deploy/kanal-zugang-eintragen.sh")
    for kanal, info in kanaele.KANAELE.items():
        m = re.search(rf"^\s*{re.escape(kanal)}\)(.*?);;", skript, re.M | re.S)
        assert m, f"case-Zweig {kanal}) fehlt"
        for n in info.env_namen:
            assert re.search(rf"\b{n}\b", m.group(1)), (kanal, n)
    code = "\n".join(z for z in skript.splitlines()
                     if not z.lstrip().startswith("#"))
    assert not re.search(r"set -[a-z]*x", code)
    assert "read -r -s" in skript


def test_env_example_nennt_namen():
    beispiel = _lesen(".env.example")
    doku = _lesen("docs/10_SECRETS_ROTATION.md")
    for n in _alle_namen() + ["BLUESKY_PDS", "YOUTUBE_SICHTBARKEIT"]:
        assert re.search(rf"^{n}=$", beispiel, re.M), n
        assert n in doku, n
    assert "kanal-zugang-eintragen.sh" in beispiel
    assert "kanal-zugang-eintragen.sh" in doku
