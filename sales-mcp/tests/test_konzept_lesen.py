"""Der gemeinsame Pruefer `konzept_lesen.py` und seine eingefrorenen Pruefvektoren (reine Funktionen, keine Datenbank).

`konzept_lesen.py` und `tests/konzept_vektoren.json` stammen aus vibemind-os
(`spaces/rowboat/deploy/headless/auftraege/konzept_lesen.py`, Commit 7ff9cc48, und `spaces/rowboat/tests/`). Sie sind hier
BYTE-GLEICH vendort und werden NIE in diesem Repo bearbeitet: Aenderungen nur in vibemind-os, danach neu kopieren und
den Hash unten nachziehen. So sind sich Sales, der MCP-Dienst und Rowboat immer einig, was ein gueltiges Konzept ist.
"""
import hashlib
import json
from pathlib import Path

import pytest

import konzept_lesen as kl

HIER = Path(__file__).resolve().parent
PRUEFER = HIER.parent / "konzept_lesen.py"
VEKTOREN = HIER / "konzept_vektoren.json"

# Herkunft: vibemind-os 7ff9cc48 -- nie hier aendern.
SHA_PRUEFER = "b6d2343e05dd73c3a621f6a736f550eece5b92d502b722a708c4658f394ee210"
SHA_VEKTOREN = "bcc2557e31d83f0a0365e12cfecbe26620ea9c4f42c73c9022ab72bdf07311a2"
# Sales nimmt am Draht ein Konzept ohne `auftrag` und mit `firma: null` weiter wie bisher an (angleichen), der
# gemeinsame Pruefer lehnt beides ab: genau diese beiden Vektoren weichen bewusst ab.
NACHSICHT = ("ungueltig_firma_null", "ungueltig_auftrag_fehlt")
FAELLE = json.loads(VEKTOREN.read_text(encoding="utf-8"))["faelle"]


def test_pruefer_ist_byte_gleich_gepinnt():
    assert hashlib.sha256(PRUEFER.read_bytes()).hexdigest() == SHA_PRUEFER


def test_pruefer_ist_reines_ascii_ohne_zeilenenden_umbau():
    roh = PRUEFER.read_bytes()
    assert roh.isascii() and b"\r" not in roh


def test_vektoren_sind_byte_gleich_gepinnt():
    assert hashlib.sha256(VEKTOREN.read_bytes()).hexdigest() == SHA_VEKTOREN


def test_vektoren_vollzaehlig():
    assert len(FAELLE) == 236 and len({f["name"] for f in FAELLE}) == 236


def streng_gleich(a, b) -> bool:
    """Gleichheit wie JSON: true ist nicht 1, 4 und 4.0 sind dieselbe Zahl."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and a == b
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(streng_gleich(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(streng_gleich(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


@pytest.mark.parametrize("fall", FAELLE, ids=[f["name"] for f in FAELLE])
def test_vektor_pruefer(fall):
    daten, satz = kl.lesen(fall["html"])
    fehler = satz if daten is None else kl.video_pruefen(daten)
    assert (daten is not None and fehler is None) is fall["gueltig"], (satz, fehler)
    if fall["gueltig"]:
        assert satz is None
        assert streng_gleich(daten["video"], fall["video"]), daten["video"]
    elif isinstance(fall["fehler_enthaelt"], str):
        assert isinstance(fehler, str) and fall["fehler_enthaelt"] in fehler, fehler
    else:
        assert fall["fehler_enthaelt"] is None
        assert daten is None and satz is None
    if "video" in fall and not fall["gueltig"]:
        assert daten is not None and streng_gleich(daten["video"], fall["video"])


@pytest.mark.parametrize("fall", FAELLE, ids=[f["name"] for f in FAELLE])
def test_vektor_sales_einstieg_pruefen(fall):
    """Sales bekommt das schon gelesene Konzept als JSON (`konzept` im Rumpf): `video_konzept.pruefen` urteilt
    ueber jedes geparste `video` wie der gemeinsame Pruefer und wie `gueltig` im Vektor."""
    import video_konzept
    daten, _ = kl.lesen(fall["html"])
    if daten is None or "video" not in daten:
        pytest.skip("kein geparstes video in diesem Fall")
    satz = video_konzept.pruefen(daten["video"])
    if fall["name"] in NACHSICHT:         # bewusste Abweichung auf dem Sales-Draht (Entscheid des Controllers)
        assert kl.video_pruefen(daten) is not None and satz is None
        assert video_konzept.pruefen(video_konzept.bereinigen(daten["video"])) is None
        return
    assert satz == kl.video_pruefen(daten) or (satz is not None and kl.video_pruefen(daten) is None), satz
    if "video" in fall:
        assert (satz is None) is fall["gueltig"], satz
        if satz is None:
            assert video_konzept.pruefen(video_konzept.bereinigen(daten["video"])) is None   # Neuaufbau bleibt gueltig
            video_konzept.block_hash(video_konzept.bereinigen(daten["video"]))               # und ist hashbar
