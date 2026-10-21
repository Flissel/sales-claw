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


# Bildstuecke sind wie Entwurfsbilder kein Medium (Gesamtpruefung Stufe 4): unsichtbar in Listen und im
# Picker, nie Kundenanhang, als Name reserviert - Anzeige und Versand lesen sie weiter.
@pytest.mark.parametrize("nur_anhaenge", [False, True])
def test_liste_laesst_collage_stuecke_weg(ordner, nur_anhaenge):
    for n in (MS, "ms-0c80e26a-2-01-2.jpg"):
        (ordner / n).write_bytes(JPEG)
    assert [n for n, _ in medien.liste(nur_anhaenge)] == ["nl-12345678-x.jpg"]


def test_pruefe_anhang_lehnt_collage_stueck_ab(ordner):
    (ordner / MS).write_bytes(JPEG)
    basis, fehler = medien.pruefe_anhang(MS)
    assert basis is None and "Bildstück" in fehler


def test_collage_stueck_ist_reserviert(ordner):
    assert medien.pruefe_neuen_namen(MS)[0] is None
    assert medien.pruefe_neuen_namen(GS)[0] is None
    assert medien.pruefe_neuen_namen("ms-urlaub.jpg") == ("ms-urlaub.jpg", None)
    stamm, endung = medien.anhang_name(MS)
    assert stamm + endung != MS and not medien.verborgen(stamm + endung)


@pytest.mark.parametrize("name", ["ms-0C80E26A-2-01.jpg", "ms-0c80e26a-2-1.jpg", "ms-0c80e26a-2-01.png",
                                  "xms-0c80e26a-2-01.jpg", "ms-0c80e26a.jpg"])
def test_nur_die_exakte_form_ist_mailstueck(name):
    assert not medien.mailstueck(name)


# Reels (Reels Stufe 1): Vorschaubild vid-<id8>-<slug>.jpg und Reel vid-<id8>-<slug>.mp4 im Erzeugt-Ordner.
# Beide stehen nicht in /medien und nicht im Anhang-Picker, die Namen sind reserviert; die Reels-Seiten
# zeigen sie ueber /medien/datei (pruefe/pruefe_anzeige). Das Vorschaubild geht nie als Anhang; das Reel-MP4
# darf weiter in einen Beitrag (Reels-Seite "Als LinkedIn-Post vorbereiten" -> pruefe_anhang).
VID_JPG, VID_MP4 = "vid-0123abcd-herbst-reel.jpg", "vid-0123abcd-herbst-reel.mp4"
MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64


@pytest.mark.parametrize("nur_anhaenge", [False, True])
def test_liste_laesst_reel_dateien_weg(ordner, nur_anhaenge):
    (ordner / VID_JPG).write_bytes(JPEG)
    (ordner / VID_MP4).write_bytes(MP4)
    assert [n for n, _ in medien.liste(nur_anhaenge)] == ["nl-12345678-x.jpg"]


def test_reel_dateien_bleiben_anzeigbar(ordner):
    (ordner / VID_JPG).write_bytes(JPEG)
    (ordner / VID_MP4).write_bytes(MP4)
    for n in (VID_JPG, VID_MP4):
        assert medien.pruefe(n) == (n, None)
        assert medien.pruefe_anzeige(n) == (n, None)


def test_reel_vorschaubild_nie_als_anhang(ordner):
    (ordner / VID_JPG).write_bytes(JPEG)
    basis, fehler = medien.pruefe_anhang(VID_JPG)
    assert basis is None and "Vorschaubild" in fehler


def test_reel_mp4_bleibt_fuer_den_beitrag(ordner):
    (ordner / VID_MP4).write_bytes(MP4)
    assert medien.pruefe_anhang(VID_MP4) == (VID_MP4, None)


def test_reel_namen_sind_reserviert(ordner):
    for n in (VID_JPG, VID_MP4):
        assert medien.pruefe_neuen_namen(n)[0] is None and medien.verborgen(n)
    stamm, endung = medien.anhang_name(VID_JPG)
    assert stamm + endung != VID_JPG and not medien.verborgen(stamm + endung)
    assert medien.pruefe_neuen_namen("vid-urlaub.jpg") == ("vid-urlaub.jpg", None)


@pytest.mark.parametrize("name", ["vid-0123ABCD-x.jpg", "vid-0123abc-x.jpg", "vid-0123abcd-x.png",
                                  "xvid-0123abcd-x.jpg", "vid-0123abcd-.jpg", "vid-0123abcd-X.mp4",
                                  "vid-0123abcd-" + "a" * 41 + ".jpg"])
def test_nur_die_exakte_form_ist_reeldatei(name):
    assert not medien.reeldatei(name)
