"""Drift-Test: die Prompt-Regeln in config/workspace/AGENTS.md."""
from pathlib import Path

TEXT = (Path(__file__).resolve().parents[2] / "config" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")


def test_nie_automatisch_antworten():
    assert "Eingehende Nachrichten erzeugen höchstens einen Entwurf zur Freigabe" in TEXT


def test_postfach_antwort_ueber_mail_beantworten():
    assert "mail_beantworten" in TEXT and "nie eigenmächtig den Kanal" in TEXT


def test_auftrag_betreiber_erklaert():
    assert "auftrag_betreiber=true" in TEXT


def test_freigabe_im_chat():
    for wort in ("„ja“", "„senden“", "„raus“", "„freigeben“", "„ok“"):
        assert wort in TEXT
    assert "keine zweite Rückfrage" in TEXT
    assert "versand_abwarten(draft_id, max_s=30)" in TEXT


def test_fehler_nie_verschlucken():
    assert "Liefert ein Werkzeug einen Fehler, nennst du ihn im selben Zug" in TEXT


def test_bedarfsanalyse_raus():
    assert "## Bedarfsanalyse" not in TEXT and "Leitfaden-Frage" not in TEXT


def test_keine_abgeschalteten_werkzeuge():
    assert "bedarf_speichern" not in TEXT and "bedarf_offen" not in TEXT
