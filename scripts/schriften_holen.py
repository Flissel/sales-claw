"""Laedt die OFL-Schriften einmalig von jsDelivr (fontsource) nach
sales-mcp/static/schriften/. Schreibt nichts doppelt, bricht bei HTTP-Fehler
mit dem Namen der Datei ab.

  python scripts/schriften_holen.py
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL / "sales-mcp"))
import schriften  # noqa: E402

FONT_URL = "https://cdn.jsdelivr.net/fontsource/fonts/{slug}@latest/latin-{gewicht}-{stil}.woff2"
LIZENZ_URL = "https://cdn.jsdelivr.net/npm/@fontsource/{slug}/LICENSE"


def _holen(url: str, ziel: Path, magic: bytes | None = None) -> bool:
    if ziel.exists():
        return False
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            daten = r.read()
    except urllib.error.URLError as e:
        raise SystemExit(f"FEHLER {ziel.name}: {url}: {e}")
    if magic and daten[:len(magic)] != magic:
        raise SystemExit(f"FEHLER {ziel.name}: {url}: keine woff2-Datei")
    ziel.write_bytes(daten)
    return True


def main() -> None:
    schriften.ORDNER.mkdir(parents=True, exist_ok=True)
    neu = 0
    for sid, s in schriften.REGISTER.items():
        for gewicht, stil in s["dateien"]:
            neu += _holen(FONT_URL.format(slug=s["slug"], gewicht=gewicht, stil=stil),
                          schriften.ORDNER / f"{sid}-{gewicht}-{stil}.woff2", b"wOF2")
        neu += _holen(LIZENZ_URL.format(slug=s["slug"]), schriften.ORDNER / f"OFL-{sid}.txt")
    print(f"{neu} neue Dateien in {schriften.ORDNER}")


if __name__ == "__main__":
    main()
