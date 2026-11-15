"""Pruefung des Videokonzept-Blocks, den Rowboat an die Auftragsannahme schickt (reine Funktionen).

Die Regeln fuer das Konzept selbst stehen NICHT hier, sondern im gemeinsamen Pruefer `konzept_lesen.py`
(byte-gleich aus vibemind-os vendort, per Hash gepinnt): dieselbe Datei prueft in Sales, im MCP-Dienst
und fuer die Seite in Rowboat, damit sie nie auseinanderlaufen. Laengen zaehlen dort in UTF-16-Einheiten,
getrimmt wird wie in JavaScript (`js_trim`). Hier bleiben nur die Regeln fuer Sales' eigene Felder
(`firma`, `pfad`, `name`), die Groesse des gespeicherten Blocks, der Neuaufbau und der Hash.
"""
from __future__ import annotations

import hashlib
import json

from konzept_lesen import BILDARTEN, js_trim, utf16_laenge, video_pruefen_objekt  # noqa: F401 (BILDARTEN: Wiederausfuhr)

BLOCK_MAX = 20_000                     # UTF-16-Einheiten des kompakten JSON ohne auftrag/pfad/name
FELD_MAX = 500                         # firma, pfad, name
# Felder, die nicht zum Inhalt des Konzepts gehoeren: der Hash bleibt gleich, wenn sich nur sie aendern
# (die Auftragsnummer wird nach der Uebergabe in die Datei geschrieben).
_OHNE_HASH = ("auftrag", "pfad", "name")


SATZ_STUFE_NAME = "Jede Stufe braucht einen Namen."
SATZ_STUFE_LEER = "Jede Stufe braucht mindestens eine Szene."
SATZ_SZENE_KURZ = "Jede Szene braucht eine Kurzbeschreibung."


def _sichtbar(text: str) -> bool:
    """Bleibt nach JS-Trimmung (und ohne C0-Steuerzeichen, die die Werkbank ebenfalls entfernt) etwas uebrig?"""
    return bool("".join(z for z in js_trim(text) if ord(z) >= 0x20).strip())


def _minuten(wert):
    """4.0 ist dieselbe Zahl wie 4 (JSON kennt keinen Unterschied): ganze Zahlen werden int."""
    if isinstance(wert, float) and wert.is_integer():
        return int(wert)
    return wert


def _inhalt(konzept: dict) -> dict:
    inhalt = {k: v for k, v in konzept.items() if k not in _OHNE_HASH}
    if "minuten" in inhalt:
        inhalt["minuten"] = _minuten(inhalt["minuten"])
    return inhalt


def _kanonisch(konzept: dict) -> str:
    return json.dumps(_inhalt(konzept), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def block_hash(konzept: dict) -> str:
    """sha256 (hex) ueber das kanonische JSON ohne `auftrag`, `pfad`, `name` (`4` und `4.0` hashen gleich)."""
    return hashlib.sha256(_kanonisch(konzept).encode("utf-8")).hexdigest()


def bereinigen(konzept: dict) -> dict:
    """Das Konzept NUR aus den bekannten Feldern neu aufgebaut (unbekannte Felder fallen still weg; die
    Rowboat-Seite toleriert sie, gespeichert werden sie nie); `minuten` als ganze Zahl. Nur fuer ein Konzept,
    das `pruefen` bestanden hat."""
    sauber = {"thema": konzept["thema"], "zielgruppe": konzept["zielgruppe"], "minuten": _minuten(konzept["minuten"]),
              "hook": konzept["hook"], "kernaussage": konzept["kernaussage"], "stufen": [],
              "abschluss": konzept["abschluss"], "auftrag": konzept.get("auftrag")}
    for s in konzept["stufen"]:
        szenen = []
        for sz in s["szenen"]:
            neu = {"kurz": sz["kurz"], "bildart": sz["bildart"]}
            if "notiz" in sz:
                neu["notiz"] = sz["notiz"]
            szenen.append(neu)
        sauber["stufen"].append({"name": s["name"], "szenen": szenen})
    for feld in ("firma", "pfad", "name"):
        if konzept.get(feld) is not None:
            sauber[feld] = konzept[feld]
    return sauber


def beschreibung_aus(konzept: dict) -> str:
    """Die Beschreibung des Auftrags: Kernaussage, Leerzeile, Abschluss (je mit JS-Trimmung getrimmt)."""
    return js_trim(konzept["kernaussage"]) + "\n\n" + js_trim(konzept["abschluss"])


def angleichen(konzept):
    """Die nachsichtige Drahtform von Sales, VOR dem gemeinsamen Pruefer: fehlt `auftrag`, gilt `null`; `firma: null`
    gilt wie keine Firma (faellt weg). Ein vorhandener, ungueltiger `auftrag` bleibt unveraendert (der Pruefer lehnt ihn ab)."""
    if not isinstance(konzept, dict):
        return konzept
    neu = dict(konzept)
    neu.setdefault("auftrag", None)
    if neu.get("firma", 0) is None:
        del neu["firma"]
    return neu


def pruefen(konzept) -> str | None:
    """Der erste Fehlersatz, oder None, wenn das Konzept gueltig ist."""
    konzept = angleichen(konzept)
    satz = video_pruefen_objekt(konzept)                     # alle Regeln des Konzepts: der gemeinsame Pruefer
    if satz:
        return satz
    for feld in ("firma", "pfad", "name"):                   # Sales' eigene Felder
        wert = konzept.get(feld)
        if wert is not None and (not isinstance(wert, str) or utf16_laenge(wert) > FELD_MAX):
            return f"Das Feld {feld} des Konzepts muss ein kurzer Text sein."
    # Die Werkbank baut ihre erste Gliederung nur dann eins zu eins aus dem Konzept, wenn jede Stufe einen Namen und
    # jede Szene eine Kurzbeschreibung hat; der gemeinsame Pruefer verlangt das (noch) nicht. Stufen und Szenen sind
    # hier schon als Liste von Objekten geprueft. Die Obergrenze von 8 Stufen prueft der gemeinsame Pruefer.
    for stufe in konzept["stufen"]:
        if not _sichtbar(stufe["name"]):
            return SATZ_STUFE_NAME
        if not stufe["szenen"]:
            return SATZ_STUFE_LEER
        if any(not _sichtbar(sz["kurz"]) for sz in stufe["szenen"]):
            return SATZ_SZENE_KURZ
    if utf16_laenge(_kanonisch(bereinigen(konzept))) > BLOCK_MAX:
        return f"Das Konzept ist größer als {BLOCK_MAX} Zeichen."
    return None
