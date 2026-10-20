# Entwurfsbilder der Gestaltungsflaechen (gs-<hash12>.jpg): unsichtbar in den
# Listen und als Anhang, aber von `pruefe` weiter anzeigbar (der Editor zeigt
# Flaechen ueber /medien/datei/). DB-frei.
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import medien  # noqa: E402

GS = "gs-0123456789ab.jpg"
JPEG = bytes([0xFF, 0xD8]) + b"x" * 64


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    menschen, erzeugt = tmp_path / "media", tmp_path / "erzeugt"
    menschen.mkdir()
    erzeugt.mkdir()
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(menschen))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    (erzeugt / GS).write_bytes(JPEG)
    (erzeugt / "nl-12345678-x.jpg").write_bytes(JPEG)
    return erzeugt


@pytest.mark.parametrize("nur_anhaenge", [False, True])
def test_liste_laesst_entwurfsbilder_weg(ordner, nur_anhaenge):
    namen = [n for n, _ in medien.liste(nur_anhaenge)]
    assert namen == ["nl-12345678-x.jpg"]


def test_pruefe_anhang_lehnt_entwurfsbild_ab(ordner):
    basis, fehler = medien.pruefe_anhang(GS)
    assert basis is None and "Entwurfsbild" in fehler
    assert medien.pruefe_anhang("nl-12345678-x.jpg")[1] is None


def test_pruefe_liefert_entwurfsbild_weiter_aus(ordner):
    assert medien.pruefe(GS) == (GS, None)


@pytest.mark.parametrize("name", ["gs-0123456789AB.jpg", "gs-0123456789a.jpg", "gs-0123456789ab.png",
                                  "xgs-0123456789ab.jpg"])
def test_nur_die_exakte_form_ist_entwurf(name):
    assert not medien.ENTWURF_MUSTER.match(name)


# Bildstuecke der Collage-Mail (Freie Flaeche Stufe 4): ms-<inhalt 8 hex>-<fassung>-<nr>.jpg im
# Erzeugt-Ordner. Der Versand liest sie wie die Export-Bilder; die Vorschau zeigt sie.
MS = "ms-0c80e26a-2-01.jpg"


def test_collage_stueck_ist_anzeigbar(ordner):
    (ordner / MS).write_bytes(JPEG)
    assert medien.pruefe_anzeige(MS) == (MS, None)


def test_newsletter_bilder_liest_collage_stueck_aus_media_erzeugt(ordner):
    import mail_dispatch
    (ordner / MS).write_bytes(JPEG)
    bilder, fehler = mail_dispatch.newsletter_bilder([{"name": MS, "cid": MS}])
    assert fehler is None and bilder == [(MS, JPEG, "jpeg")]
