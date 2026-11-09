"""deploy/smoke.sh prueft den Herzschlag des Freigabe-Boten nur in der vollen Pruefung (M4).

Rein (liest nur Dateien). Der echte Beweis ist die Ausfall-Probe auf der VM:
Bote stoppen, Wache wird rot, Bote starten, Wache wird gruen.
"""
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]


def _abschnitt() -> str:
    smoke = (WURZEL / "deploy/smoke.sh").read_text(encoding="utf-8")
    start = smoke.index("# 21) Herzschlag des Freigabe-Boten")
    return smoke[start:smoke.index('echo "---"', start)]


def test_abschnitt_steht_vor_dem_schluss():
    smoke = (WURZEL / "deploy/smoke.sh").read_text(encoding="utf-8")
    assert smoke.index("# 21) Herzschlag") < smoke.rindex('exit "$ROT"')


def test_basis_modus_ueberspringt():
    a = _abschnitt()
    zweig = a[a.index('if [ "$MODUS" = "basis" ]'):a.index("elif")]
    assert "melde" in zweig and "fehl" not in zweig


def test_liest_die_pruefzeile_im_produktionsschema():
    a = _abschnitt()
    assert "SALES_DB_SCHEMA=sales " in a
    assert "fe.herzschlag_pruefzeile()" in a


def test_nur_ok_ist_gruen():
    a = _abschnitt()
    faelle = dict(re.findall(r"^\s*([^\n)]+)\) (gut|fehl) ", a, re.M))
    assert faelle == {r"ok\ *": "gut", r"still\ *|unbekannt\ *": "fehl", "*": "fehl"}
