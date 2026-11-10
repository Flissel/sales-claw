"""Anbindung an pm-claw (Projektaufnahme anstossen, 29.10.2026).

Rein (liest nur Dateien, braucht weder DB noch Docker). Sales Claw ist nur die
Tuerklingel: zwei Werkzeuge von pm-mcp, Netz pm-claw_default nur fuer das
Gateway, der Token nie in Git oder in der Dienst-Umgebung.
"""
import json
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
ZWEI = ["aufnahme_anstossen", "aufnahme_status"]


def _lesen(rel: str) -> str:
    return (WURZEL / rel).read_text(encoding="utf-8")


def _compose_abschnitt(dienst: str) -> str:
    m = re.search(rf"^  {re.escape(dienst)}:\n(.*?)(?=^  \S|^\S|\Z)", _lesen("docker-compose.yml"), re.M | re.S)
    assert m, dienst
    return m.group(1)


def _code(text: str) -> str:
    return "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))


def test_saat_kennt_pm_mit_genau_zwei_werkzeugen_und_ohne_token():
    c = json.loads(_lesen("config/openclaw.json"))
    pm = c["mcp"]["servers"]["pm"]
    assert pm["url"] == "http://pm-mcp:8765/mcp"
    assert pm["transport"] == "streamable-http"
    assert (pm["connectionTimeoutMs"], pm["requestTimeoutMs"]) == (30000, 60000)
    assert pm["toolFilter"]["include"] == ZWEI
    assert "headers" not in pm                       # der Token kommt nur per Skript ins Volume
    assert not re.search(r"Bearer\s+[A-Za-z0-9_.\-]{16,}", _lesen("config/openclaw.json"))


def test_nur_das_gateway_tritt_dem_pm_netz_bei_und_behaelt_default():
    gateway = _code(_compose_abschnitt("sales-claw"))
    assert re.search(r"networks:\n\s+- default\n\s+- pm-claw\b", gateway)
    for dienst in ("sales-mcp", "sales-dispatch", "sales-mail", "sales-ui", "sales-inbox"):
        assert "pm-claw" not in _code(_compose_abschnitt(dienst)), dienst
    text = _code(_lesen("docker-compose.yml"))
    assert re.search(r"^networks:\n  pm-claw:\n    external: true\n    name: pm-claw_default", text, re.M)
    assert "PM_TOKEN" not in text                    # nie in einen environment:-Block


def test_anbinde_skript_liest_nur_den_token_und_siebt():
    skript = _lesen("deploy/pm-anbinden.sh")
    code = _code(skript)
    assert "grep -E '^PM_TOKEN_SALES='" in code
    assert '-e PM_TOKEN_SALES=' in code             # nur per -e in den Container
    assert '"mcp", "set", "pm"' in code
    assert "sieb()" in code and "| sieb" in code
    assert not re.search(r"set -[a-z]*x", code)
    assert "for w in aufnahme_anstossen aufnahme_status; do" in code and '"pm__$w"' in code
    assert '[ "$ANZAHL" != "2" ]' in code             # nicht mehr als die zwei


def test_agentenregel_klingel_und_tabu():
    text = _lesen("config/workspace/AGENTS.md")
    i = text.index("## Projektaufnahme bei pm-claw anstoßen")
    assert i < text.index("## Verbote — ohne Ausnahme")
    abschnitt = text[i:text.index("\n## ", i + 1)]
    for satz in ("„mach Projektaufnahme mit X“", "`herkunft`: immer `sales-claw`",
                 "`externe_ref`: die `lead_id` des Kontakts", "`schick <id8>`",
                 "Andere pm-claw-Werkzeuge gibt es für dich nicht"):
        assert satz in abschnitt, satz
    tabu_anfang = text.index("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
    tabu = text[tabu_anfang:text.find("\n- ", tabu_anfang + 1)]
    for w in ZWEI:
        assert f"`{w}`" in tabu, w


def test_smoke_prueft_pm_nur_mit_token():
    smoke = _lesen("deploy/smoke.sh")
    assert "PM_TOKEN_SALES" in smoke and "pm__aufnahme_status" in smoke
    assert "uebersprungen" in smoke[smoke.index("PM_TOKEN_SALES"):smoke.index("PM_TOKEN_SALES") + 1500]
