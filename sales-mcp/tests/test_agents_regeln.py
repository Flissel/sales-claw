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
    assert "zeigt keinen Entwurf zur Freigabe" in text


def test_ja_nur_direkt_nach_vollstaendiger_anzeige():
    # Final-Review C2: ein „ja“ gibt nur frei, wenn die unmittelbar vorige
    # eigene Nachricht genau diesen Entwurf vollständig zeigte.
    absatz = _absatz("- **Freigabe im Chat:**")
    assert "unmittelbar vorige eigene Nachricht" in absatz
    assert "gibst du nichts frei" in absatz
    assert "fragst du einmal kurz nach" in absatz


def test_bericht_ja_beantwortet_die_frage():
    absatz = _absatz("- **Berichte sind keine Entwürfe.**")
    assert "bezieht sich nie auf einen Bericht" not in absatz
    assert "zuletzt vollständig gezeigten Entwurf" not in absatz
    assert "beantwortet es diese Frage" in absatz
    assert "gibt keinen Entwurf frei" in absatz


def test_kundenchat_direkt_nur_bei_auto():
    # Final-Review I2 / Ruling: direkt antworten nur bei Stufe `auto` mit
    # Zustimmung; bei halbauto/manuell Entwurf per antwort_entwerfen, kein
    # eigenes Wort im Kundenchat.
    i = TEXT.index("## Kundenchats")
    kapitel = " ".join(TEXT[i:TEXT.index("\n## ", i + 1)].split())
    assert "ohne Entwurf und ohne Freigabe je Nachricht" not in kapitel
    assert "Nur bei Stufe `auto` mit dokumentierter Zustimmung" in kapitel
    assert "antwort_entwerfen" in kapitel
    assert "NO_REPLY" in kapitel


def test_freigabe_antworten_nennt_kundenchat_regel():
    i = TEXT.index("## Antworten nur mit Freigabe")
    kapitel = " ".join(TEXT[i:TEXT.index("\n## ", i + 1)].split())
    assert "Kontakt-Freigabe allein" in kapitel
    assert "halbauto" in kapitel and "manuell" in kapitel


def test_bild_aus_dem_chat_ueber_das_werkzeug():
    # 14.10.2026: von selbst landet nichts in den Medien (OpenWA liefert
    # eigene Medien nicht) — der Agent legt sie per Werkzeug ab.
    absatz = _absatz("- **Bild oder Datei aus dem Chat in die Medien.**")
    assert "medien_aus_chat_uebernehmen(datei=" in absatz
    assert "[media attached:" in absatz
    assert "medien_datei" in absatz and "post_entwurf_erstellen" in absatz
    assert "fragst du einmal kurz" in absatz
    text = " ".join(TEXT.split())
    assert "liegt sie danach in den Medien" not in text
    assert "medien_aus_chat_uebernehmen" in _absatz(
        "- **Betreiber-Werkzeuge sind im Kundenchat tabu")


def test_auto_betrieb_eigene_nummer_nur_bei_auto():
    absatz = _absatz("- Schreibt er an **deine eigene Nummer**")
    assert "Stufe `auto`" in absatz


def test_linkedin_posts_laufen_ueber_skill_und_nicht_mehr_von_hand():
    assert "Skill\n`linkedin-post`" in TEXT or "Skill `linkedin-post`" in TEXT
    assert "kopiert der Betreiber den Text selbst" not in TEXT


def test_markierungen_im_kundenchat_tabu():
    assert "`post_markierungen_setzen`" in _absatz(
        "- **Betreiber-Werkzeuge sind im Kundenchat tabu")


def test_websuche_personen_auf_die_markier_liste_nicht_in_den_text():
    # Final-Review I1 (15.10.2026): bestaetigte Personen/Firmen kommen auf die
    # Markier-Liste, im Beitragstext steht nur der Name — kein Profil-Link.
    assert "als normaler Link" not in TEXT
    absatz = _absatz("- **Bei Personen nie raten.**")
    assert "post_markierungen_setzen" in absatz
    assert "kein Profil-Link" in absatz


def test_einordnung_abschnitt():
    assert "## Einordnung (Art und Bereiche)" in TEXT
    abschnitt = TEXT.split("## Einordnung (Art und Bereiche)")[1].split("\n## ")[0]
    assert "kontakt_einordnen(" in abschnitt
    for b in ("bav", "mitarbeiter", "vorsorge", "immobilien", "it", "homelab"):
        assert f"`{b}`" in abschnitt
    assert "nie raten" in abschnitt.lower()


def test_einordnen_im_kundenchat_tabu():
    assert "`kontakt_einordnen`" in _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")


def test_empfehlungslisten_im_prompt_und_tabu():
    assert "Skill `empfehlungsliste`" in TEXT
    tabu = _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
    assert "`empfehlungsliste_anlegen`" in tabu and "`empfehlungslisten_zeigen`" in tabu


def test_vertraege_projekte_im_prompt():
    assert "abschluss_speichern(" in TEXT and "vertrag_speichern(" in TEXT
    assert "`abschluss_speichern`" in _absatz("- **Betreiber-Werkzeuge sind im Kundenchat tabu")
