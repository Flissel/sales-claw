"""Eingebautes Editor-Paket: Pruefsummen stimmen, keine fremden Quellen."""
import hashlib
import json
import pathlib

ORDNER = pathlib.Path(__file__).resolve().parents[1] / "static" / "editor"
FREMD = ("cdnjs.", "googleapis.", "gstatic.", "unpkg.", "jsdelivr.", "cloudfront.")


def test_manifest_stimmt():
    m = json.loads((ORDNER / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["quelle"] == "usewaypoint/email-builder-js@ce3e610"
    for name in ("editor.js", "editor.css"):
        assert hashlib.sha256((ORDNER / name).read_bytes()).hexdigest() == m["sha256"][name], name


def test_keine_fremden_quellen():
    for name in ("editor.js", "editor.css"):
        text = (ORDNER / name).read_text(encoding="utf-8", errors="replace")
        for f in FREMD:
            assert f not in text, (name, f)


def test_nur_zwei_dateien_ausgeliefert():
    assert sorted(p.name for p in ORDNER.iterdir()) == ["MANIFEST.json", "editor.css", "editor.js"]


def test_paket_ist_neu_gebaut_agent_konflikt_nennt_medien():
    # PultLeiste.tsx: Konflikt bei neuer Agenten-Fassung verweist auf die Medien
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    assert "Neue Bilder vom Agenten liegen auch in den Medien." in text


def test_paket_ist_neu_gebaut_bilder_loeschen():
    # ImageSidebarPanel.tsx/pult.ts (01.10.2026): Muelleimer auf den Medien-Kacheln
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    assert "Aus den Medien löschen" in text and "medien_loeschen_url" in text


def test_paket_kennt_vorlagenschriften():
    # Task 9 (2026-10-01 Vorlagen in Profi-Qualitaet): Vorlagenschriften, Versalien, Schrift-CSS
    text = (ORDNER / "editor.js").read_text(encoding="utf-8")
    assert "Vorlage – Anzeige" in text and "Versalien gesperrt" in text and "/marketing/schrift/schriften.css" in text
