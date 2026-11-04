import post_katalog as k
import post_struktur as ps


def test_subdomain_trifft():
    assert k.treffer("Instagram <security@mail.instagram.com>") == ("Soziale Netzwerke", "Instagram")
    assert k.treffer("noreply@github.com") == ("Tools & Dienste", "GitHub")
    assert k.treffer("x@calendar.luma-mail.com") == ("Veranstaltungen", None)

def test_fremddomain_trifft_nicht():
    assert k.treffer("Instagram <x@evil.io>") is None
    assert k.treffer("a@instagram.com.evil.io") is None
    assert k.treffer("a@notinstagram.com") is None
    assert k.treffer("a@box.com") is None          # x.com darf nicht auf box.com passen
    assert k.treffer("kein absender") is None and k.treffer("") is None

def test_katalog_nur_gueltige_faecher():
    for endung, fach, unter in k.KATALOG:
        assert endung == endung.lower() and not endung.startswith(".")
        assert any(ps.fach_gueltig(br, fach) for br in ps.BEREICHE)
        assert ps.unterfach_gueltig(fach, unter)
    assert len({e for e, _, _ in k.KATALOG}) == len(k.KATALOG)
