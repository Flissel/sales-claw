"""PDF-Erzeugung fuer Kursmitschrift und Kurs-Handbuch.

`pdf_aus_html` laesst sales-auge (`AUGE_URL/pdf`, Chromium im Compose-Netz) ein
A4-PDF drucken. `schreiben` legt Dateien atomar unter dem Mitschriften-Ordner ab.

LOGS/FEHLER: nur Groessen und Statuscodes, nie HTML oder Inhalte.
"""
from __future__ import annotations

import os
import pathlib
import urllib.error
import urllib.request

import mitschrift_bericht

ZEITLIMIT_STANDARD_S = 90      # laenger als das Limit in sales-auge (60 s)


class PdfFehler(Exception):
    """sales-auge ist nicht erreichbar oder liefert kein PDF. Der Text ist fest
    und traegt nie den Inhalt."""


def pdf_aus_html(html: str, zeitlimit_s: float = ZEITLIMIT_STANDARD_S) -> bytes:
    basis = os.environ.get("AUGE_URL", "").strip().rstrip("/")
    if not basis:
        raise PdfFehler("Die PDF-Erzeugung ist nicht eingerichtet.")
    anfrage = urllib.request.Request(
        basis + "/pdf", data=html.encode("utf-8"), method="POST",
        headers={"Content-Type": "text/html; charset=utf-8"})
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit_s) as antwort:
            status = getattr(antwort, "status", 200)
            daten = antwort.read()
    except urllib.error.HTTPError as e:
        raise PdfFehler(f"PDF-Erzeugung fehlgeschlagen (HTTP {e.code}).") from None
    except Exception:   # Netz, Zeit: alles wird zur festen Meldung
        raise PdfFehler("Die PDF-Erzeugung ist gerade nicht erreichbar.") from None
    if status != 200 or not daten.startswith(b"%PDF"):
        raise PdfFehler("Die PDF-Erzeugung lieferte kein PDF.")
    return daten


def schreiben(ziel: pathlib.Path, inhalt: bytes | str) -> None:
    """Atomar: tmp im selben Ordner, dann `os.replace`. Ordner werden angelegt.
    `ziel` muss unter `mitschrift_bericht.ordner()` liegen, sonst `ValueError`."""
    wurzel = pathlib.Path(mitschrift_bericht.ordner()).resolve()
    ziel = pathlib.Path(ziel).resolve()      # normalisiert "..", loest Links auf
    if ziel == wurzel or wurzel not in ziel.parents:
        raise ValueError("Ziel liegt nicht im Mitschriften-Ordner.")
    daten = inhalt.encode("utf-8") if isinstance(inhalt, str) else bytes(inhalt)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name(f".{ziel.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(daten)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ziel)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
