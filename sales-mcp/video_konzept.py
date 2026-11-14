"""Pruefung des Videokonzept-Blocks, den Rowboat an die Auftragsannahme schickt (reine Funktionen).

Nachbau der Grenzen von `checkVideoKonzept` im Rowboat-Fork (packages/shared/src/konzept.ts): Thema
3 bis 300 Zeichen, 3 bis 5 Minuten, hoechstens 8 Stufen, 8 bis 15 Szenen, `kurz` hoechstens 300,
`bildart` aus vier Werten, Block hoechstens 20 000 Zeichen. Sales sieht nur den Block, nicht die
Datei; die Pruefung hier ist die zweite Schranke hinter der des Dienstes.
"""
from __future__ import annotations

import hashlib
import json
import re

BLOCK_MAX = 20_000                     # Zeichen des kompakten JSON ohne auftrag/pfad/name
BILDARTEN = ("slide", "avatar_slide", "avatar_gross", "clip")
STUFEN_MAX = 8
SZENEN_MIN, SZENEN_MAX = 8, 15
KURZ_MAX = 300
# Felder, die nicht zum Inhalt des Konzepts gehoeren: der Hash bleibt gleich, wenn sich nur sie aendern
# (die Auftragsnummer wird nach der Uebergabe in die Datei geschrieben).
_OHNE_HASH = ("auftrag", "pfad", "name")
_HEX8 = re.compile("[0-9a-f]{8}")


def _text(wert, kleinst: int, groesst: float) -> bool:
    return isinstance(wert, str) and len(wert.strip()) >= kleinst and len(wert) <= groesst


def _inhalt(konzept: dict) -> dict:
    return {k: v for k, v in konzept.items() if k not in _OHNE_HASH}


def _kanonisch(konzept: dict) -> str:
    return json.dumps(_inhalt(konzept), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def block_hash(konzept: dict) -> str:
    """sha256 (hex) ueber das kanonische JSON ohne `auftrag`, `pfad`, `name`."""
    return hashlib.sha256(_kanonisch(konzept).encode("utf-8")).hexdigest()


def pruefen(konzept) -> str | None:
    """Der erste Fehlersatz, oder None, wenn das Konzept gueltig ist."""
    if not isinstance(konzept, dict):
        return "Das Videokonzept fehlt oder ist kein Objekt."
    if not _text(konzept.get("thema"), 3, 300):
        return "Das Thema des Konzepts muss 3 bis 300 Zeichen lang sein."
    if not _text(konzept.get("zielgruppe"), 1, float("inf")):
        return "Die Zielgruppe des Konzepts fehlt."
    minuten = konzept.get("minuten")
    if isinstance(minuten, bool) or not isinstance(minuten, (int, float)) or not 3 <= minuten <= 5:
        return "Die Länge des Konzepts muss zwischen 3 und 5 Minuten liegen."
    for feld, satz in (("hook", "Der Hook des Konzepts fehlt."),
                       ("kernaussage", "Die Kernaussage des Konzepts fehlt."),
                       ("abschluss", "Der Abschluss des Konzepts fehlt.")):
        if not _text(konzept.get(feld), 1, float("inf")):
            return satz
    auftrag = konzept.get("auftrag")
    if auftrag is not None and not (isinstance(auftrag, str) and _HEX8.fullmatch(auftrag)):
        return "Die Auftragsnummer des Konzepts muss leer sein oder aus 8 Hex-Zeichen bestehen."
    for feld in ("firma", "pfad", "name"):
        wert = konzept.get(feld)
        if wert is not None and (not isinstance(wert, str) or len(wert) > 500):
            return f"Das Feld {feld} des Konzepts muss ein kurzer Text sein."
    stufen = konzept.get("stufen")
    if not isinstance(stufen, list):
        return "Die Stufen des Konzepts fehlen oder sind keine Liste."
    if len(stufen) > STUFEN_MAX:
        return f"Das Konzept darf höchstens {STUFEN_MAX} Stufen haben."
    szenen_gesamt = 0
    for s in stufen:
        if not isinstance(s, dict) or not isinstance(s.get("name"), str) or not isinstance(s.get("szenen"), list):
            return "Jede Stufe braucht einen Namen und eine Liste von Szenen."
        for sz in s["szenen"]:
            szenen_gesamt += 1
            if not isinstance(sz, dict):
                return "Jede Szene muss ein Objekt sein."
            if not isinstance(sz.get("kurz"), str) or len(sz["kurz"]) > KURZ_MAX:
                return f"Jede Szene braucht eine Kurzbeschreibung mit höchstens {KURZ_MAX} Zeichen."
            if sz.get("bildart") not in BILDARTEN:
                return "Die Bildart jeder Szene muss slide, avatar_slide, avatar_gross oder clip sein."
            if "notiz" in sz and not isinstance(sz["notiz"], str):
                return "Die Notiz einer Szene muss ein Text sein."
    if not SZENEN_MIN <= szenen_gesamt <= SZENEN_MAX:
        return (f"Das Konzept braucht insgesamt {SZENEN_MIN} bis {SZENEN_MAX} Szenen, "
                f"gefunden wurden {szenen_gesamt}.")
    if len(_kanonisch(konzept)) > BLOCK_MAX:
        return f"Das Konzept ist größer als {BLOCK_MAX} Zeichen."
    return None
