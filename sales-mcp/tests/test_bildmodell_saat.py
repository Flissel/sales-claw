"""Bildmodell in der Saat (30.10.2026).

Ohne agents.defaults.imageModel fiel das Bild-Werkzeug auf die eingebaute
Vorgabe anthropic/claude-opus-4-8 zurueck, die es nicht gibt ('Unknown
model') - Fotos im WhatsApp-Chat blieben unlesbar. Das Bildmodell muss in
models.providers eingetragen sein und Bilder als Eingabe erlauben, sonst
gilt es als reines Textmodell.
"""
import json
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]


def _saat():
    return json.loads((WURZEL / "config" / "openclaw.json").read_text(encoding="utf-8"))


def test_bildmodell_ist_gesetzt_und_eingetragen():
    c = _saat()
    ref = c["agents"]["defaults"]["imageModel"]
    anbieter, modell = ref.split("/", 1)
    eintraege = {m["id"]: m for m in c["models"]["providers"][anbieter]["models"]}
    assert modell in eintraege, ref
    assert "image" in eintraege[modell].get("input", []), ref
