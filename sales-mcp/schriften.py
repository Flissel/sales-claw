"""Eigene OFL-Schriften fuer die Newsletter-Vorlagen (kein Google, DSGVO).

REGISTER gleicht dem des Marketing-Renderers (MOS): gleiche IDs, Familien,
Gewichte. Die Dateien liegen in static/schriften/ (scripts/schriften_holen.py).
"""
from __future__ import annotations

import re
from pathlib import Path

REGISTER: dict[str, dict] = {
    "cormorant": {"familie": "Cormorant Garamond", "slug": "cormorant-garamond",
                  "dateien": [(400, "normal"), (400, "italic")]},
    "dm-sans": {"familie": "DM Sans", "slug": "dm-sans",
                "dateien": [(400, "normal"), (700, "normal")]},
    "playfair": {"familie": "Playfair Display", "slug": "playfair-display",
                 "dateien": [(900, "normal")]},
    "poppins": {"familie": "Poppins", "slug": "poppins",
                "dateien": [(400, "normal"), (600, "normal"), (700, "normal")]},
    "young-serif": {"familie": "Young Serif", "slug": "young-serif",
                    "dateien": [(400, "normal")]},
    "manrope": {"familie": "Manrope", "slug": "manrope",
                "dateien": [(300, "normal"), (400, "normal"), (700, "normal")]},
    "bodoni": {"familie": "Bodoni Moda", "slug": "bodoni-moda",
               "dateien": [(500, "normal"), (500, "italic")]},
    "montserrat": {"familie": "Montserrat", "slug": "montserrat",
                   "dateien": [(400, "normal"), (600, "normal")]},
    "josefin": {"familie": "Josefin Sans", "slug": "josefin-sans",
                "dateien": [(300, "normal"), (700, "normal")]},
    "oxanium": {"familie": "Oxanium", "slug": "oxanium",
                "dateien": [(600, "normal"), (700, "normal")]},
    "rajdhani": {"familie": "Rajdhani", "slug": "rajdhani",
                 "dateien": [(500, "normal"), (600, "normal")]},
}

ORDNER = Path(__file__).resolve().parent / "static" / "schriften"
_DATEI = re.compile(r"^([a-z-]+)-(\d{3})-(normal|italic)\.woff2$")


def datei_ok(name: str) -> bool:
    m = _DATEI.match(name or "")
    return bool(m) and m.group(1) in REGISTER \
        and (int(m.group(2)), m.group(3)) in REGISTER[m.group(1)]["dateien"] \
        and (ORDNER / name).is_file()


def css() -> str:
    teile = []
    for sid, s in REGISTER.items():
        for gewicht, stil in s["dateien"]:
            teile.append(f"@font-face {{ font-family: '{s['familie']}'; font-style: {stil}; "
                         f"font-weight: {gewicht}; font-display: swap; "
                         f"src: url({sid}-{gewicht}-{stil}.woff2) format('woff2'); }}")
    return "\n".join(teile) + "\n"
