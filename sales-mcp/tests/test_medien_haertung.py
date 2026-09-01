# Nachbesserungen aus dem F4-Review (Befunde B2/B3/B4). Bewusst eine eigene,
# DB-freie Datei: hier wird ausschliesslich das Modul `medien` geprueft, kein
# Werkzeug und kein Dispatcher — sie laeuft damit auch ohne SALES_DB_URL und
# kollidiert mit keiner Fixture der anderen Dateien.
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import medien  # noqa: E402

# Symlinks brauchen POSIX; die Suite laeuft ohnehin im Linux-Container.
nur_posix = pytest.mark.skipif(os.name != "posix", reason="braucht Symlinks")


@pytest.fixture
def medienordner(tmp_path, monkeypatch):
    ordner = tmp_path / "media"
    ordner.mkdir()
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(ordner))
    return ordner


@nur_posix
def test_symlink_nach_draussen_wird_am_realpath_abgefangen(medienordner, tmp_path):
    # B3: der einzige Zweig, der ein TATSAECHLICHES Entkommen verhindert —
    # alle anderen Traversal-Formen scheitern schon an der Namenspruefung.
    # Hier ist der Name voellig legitim, erst die Aufloesung zeigt nach
    # draussen.
    aussen = tmp_path / "aussen.pdf"
    aussen.write_bytes(b"%PDF-aussen")
    os.symlink(aussen, medienordner / "harmlos.pdf")

    basis, fehler = medien.pruefe("harmlos.pdf")
    assert basis is None
    assert "zeigt aus dem Medienordner heraus" in fehler


@nur_posix
def test_symlink_innerhalb_des_ordners_bleibt_erlaubt(medienordner):
    # Gegenprobe: realpath darf nur NACH DRAUSSEN zeigende Links ablehnen,
    # sonst waere die Regel strenger als ihre Begruendung.
    echt = medienordner / "original.pdf"
    echt.write_bytes(b"%PDF-echt")
    os.symlink(echt, medienordner / "alias.pdf")

    basis, fehler = medien.pruefe("alias.pdf")
    assert fehler is None
    assert basis == "alias.pdf"


def test_nul_byte_gibt_fehlertext_statt_ausnahme(medienordner):
    # B2: os.path.realpath wirft bei eingebettetem NUL einen ValueError —
    # `pruefe` verspricht aber (None, fehler) und haelt das jetzt auch hier.
    basis, fehler = medien.pruefe("datei\x00.pdf")
    assert basis is None
    assert fehler  # sprechender Text, keine Ausnahme


def test_liste_bietet_nur_an_was_die_pruefung_nimmt(medienordner, monkeypatch):
    # B4: die Liste ist ein Versprechen an den Agenten ("genau diese Namen
    # nimmt entwurf_erstellen") — sie darf nichts nennen, was die Pruefung
    # dann ablehnt.
    monkeypatch.setattr(medien, "MAX_BYTES", 100)

    (medienordner / "gut.pdf").write_bytes(b"%PDF-ok")
    (medienordner / "leer.pdf").write_bytes(b"")
    (medienordner / ".versteckt.pdf").write_bytes(b"%PDF-versteckt")
    (medienordner / "riesig.pdf").write_bytes(b"x" * 101)
    (medienordner / "notiz.txt").write_bytes(b"keine Whitelist-Endung")

    eintraege = medien.liste()
    assert eintraege == [("gut.pdf", 7)]
    # Property: alles, was die Liste nennt, nimmt die Pruefung auch an.
    for name, _ in eintraege:
        assert medien.pruefe(name)[1] is None


@nur_posix
def test_liste_verschweigt_nach_draussen_zeigende_symlinks(medienordner, tmp_path):
    aussen = tmp_path / "geheim.pdf"
    aussen.write_bytes(b"%PDF-geheim")
    os.symlink(aussen, medienordner / "koeder.pdf")
    (medienordner / "gut.pdf").write_bytes(b"%PDF-ok")

    assert medien.liste() == [("gut.pdf", 7)]

def test_erzeugte_datei_wird_gefunden(tmp_path, monkeypatch):
    erzeugt = tmp_path / "erzeugt"
    erzeugt.mkdir()
    (erzeugt / "termin-sabrina-2026-09-04.ics").write_text("BEGIN:VCALENDAR")
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    basis, fehler = medien.pruefe("termin-sabrina-2026-09-04.ics")
    assert fehler is None
    assert basis == "termin-sabrina-2026-09-04.ics"
    assert medien.pfad(basis) == str(erzeugt / basis)


def test_menschenordner_gewinnt_bei_namensgleichheit(tmp_path, monkeypatch):
    """Legt ein Mensch eine Datei mit demselben Namen ab, gilt seine —
    er ist die hoehere Instanz, nicht die Maschine."""
    mensch = tmp_path / "media"
    erzeugt = tmp_path / "erzeugt"
    mensch.mkdir()
    erzeugt.mkdir()
    (mensch / "doppelt.pdf").write_bytes(b"%PDF-mensch")
    (erzeugt / "doppelt.pdf").write_bytes(b"%PDF-maschine")
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(mensch))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    basis, fehler = medien.pruefe("doppelt.pdf")
    assert fehler is None
    assert medien.pfad(basis) == str(mensch / "doppelt.pdf")


def test_traversal_greift_auch_im_erzeugt_ordner(tmp_path, monkeypatch):
    erzeugt = tmp_path / "erzeugt"
    erzeugt.mkdir()
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    for boesartig in ("../geheim.pdf", "unterordner/x.ics", "..\\x.ics"):
        basis, fehler = medien.pruefe(boesartig)
        assert basis is None and fehler


def test_liste_nennt_beide_ordner(tmp_path, monkeypatch):
    mensch = tmp_path / "media"
    erzeugt = tmp_path / "erzeugt"
    mensch.mkdir()
    erzeugt.mkdir()
    (mensch / "checkliste.pdf").write_bytes(b"%PDF-1")
    (erzeugt / "termin-x-2026-09-04.ics").write_text("BEGIN:VCALENDAR")
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(mensch))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    namen = [name for name, _ in medien.liste()]
    assert "checkliste.pdf" in namen
    assert "termin-x-2026-09-04.ics" in namen
