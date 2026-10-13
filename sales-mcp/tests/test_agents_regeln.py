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


def _absatz(anfang: str) -> str:
    """Der Aufzaehlungspunkt, der mit `anfang` beginnt (bis zum naechsten Punkt)."""
    i = TEXT.index(anfang)
    j = TEXT.find("\n- ", i + 1)
    return " ".join(TEXT[i:j if j != -1 else len(TEXT)].split())


def test_keine_zweite_rueckfrage_vor_freigabe():
    assert "Rückfrage vor der Freigabe" not in TEXT
    assert "Rueckfrage vor der Freigabe" not in TEXT


def test_nicht_zustellbar_blockiert_freigabe():
    assert "nicht freigeben" in _absatz("- **Ziel und Einwilligung immer mitnennen.**")


def test_stufe_auto_ausnahme():
    assert "außer bei Kontakten, die der Betreiber ausdrücklich auf Stufe `auto` gestellt hat" in " ".join(TEXT.split())


def test_kundenchat_verbot_nennt_neue_werkzeuge():
    absatz = _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
    for name in ("mail_beantworten", "entwurf_bearbeiten", "versand_abwarten", "auftrag_betreiber"):
        assert name in absatz


def test_email_ankuendigung_durch_versand_abwarten_ersetzt():
    assert "ersetzt die Ankündigung" in _absatz("- **E-Mail ist kein Handversand mehr.**")


def test_versand_abwarten_nur_whatsapp_und_email():
    assert "bei WhatsApp und E-Mail" in _absatz("- **Nach jeder Freigabe")


def test_berichte_sind_keine_entwuerfe():
    text = " ".join(TEXT.split())
    assert "Berichte sind keine Entwürfe." in text
    assert "mit „Bericht:“ beginnt" in text
    assert "bezieht sich nie auf einen Bericht" in text
