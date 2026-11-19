"""kurs_pdf: PDF ueber sales-auge (Client) und atomares Schreiben in die Ablage."""
import io
import urllib.error

import pytest

import kurs_pdf as kp


class _Antwort:
    def __init__(self, status, daten):
        self.status = status
        self._daten = daten

    def read(self):
        return self._daten

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch):
    monkeypatch.setenv("AUGE_URL", "http://auge.invalid:8790")


@pytest.fixture
def auge_liefert_pdf(monkeypatch):
    gesehen = {}

    def falsch(anfrage, timeout=None):
        gesehen["url"] = anfrage.full_url
        gesehen["body"] = anfrage.data
        gesehen["typ"] = anfrage.get_header("Content-type")
        gesehen["timeout"] = timeout
        return _Antwort(200, b"%PDF-1.7 test")

    monkeypatch.setattr(kp.urllib.request, "urlopen", falsch)
    return gesehen


@pytest.fixture
def auge_antwortet_503(monkeypatch):
    def falsch(anfrage, timeout=None):
        raise urllib.error.HTTPError(anfrage.full_url, 503, "weg", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(kp.urllib.request, "urlopen", falsch)


@pytest.fixture
def ablage(tmp_path, monkeypatch):
    ziel = tmp_path / "ablage"
    ziel.mkdir()
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(ziel))
    return ziel


def test_pdf_aus_html_liefert_bytes(auge_liefert_pdf):
    assert kp.pdf_aus_html("<p>xä</p>").startswith(b"%PDF")
    assert auge_liefert_pdf["url"] == "http://auge.invalid:8790/pdf"
    assert auge_liefert_pdf["body"] == "<p>xä</p>".encode("utf-8")
    assert auge_liefert_pdf["typ"] == "text/html; charset=utf-8"
    assert auge_liefert_pdf["timeout"] == 90


def test_auge_fehler_wird_pdffehler(auge_antwortet_503):
    with pytest.raises(kp.PdfFehler):
        kp.pdf_aus_html("<p>")


def test_netzfehler_wird_pdffehler(monkeypatch):
    def falsch(anfrage, timeout=None):
        raise OSError("Geheimer Titel im Fehlertext")

    monkeypatch.setattr(kp.urllib.request, "urlopen", falsch)
    with pytest.raises(kp.PdfFehler) as e:
        kp.pdf_aus_html("<p>Geheim</p>")
    assert "Geheim" not in str(e.value)


def test_kein_200_oder_kein_pdf_wird_pdffehler(monkeypatch):
    for antwort in (_Antwort(204, b"%PDF"), _Antwort(200, b"<html>")):
        monkeypatch.setattr(kp.urllib.request, "urlopen", lambda a, timeout=None, r=antwort: r)
        with pytest.raises(kp.PdfFehler):
            kp.pdf_aus_html("<p>")


def test_ohne_auge_url_pdffehler(monkeypatch):
    monkeypatch.delenv("AUGE_URL")
    with pytest.raises(kp.PdfFehler):
        kp.pdf_aus_html("<p>")


def test_schreiben_atomar(ablage):
    kp.schreiben(ablage / "Kurse" / "a_kurs.pdf", b"%PDF-1")
    assert (ablage / "Kurse" / "a_kurs.pdf").read_bytes() == b"%PDF-1"
    assert not list(ablage.rglob("*.tmp"))


def test_schreiben_text_und_ueberschreiben(ablage):
    kp.schreiben(ablage / "_handbuecher" / "h.html", "alt")
    kp.schreiben(ablage / "_handbuecher" / "h.html", "neu ä")
    assert (ablage / "_handbuecher" / "h.html").read_text(encoding="utf-8") == "neu ä"
    assert not list(ablage.rglob("*.tmp"))


def test_schreiben_ausserhalb_abgelehnt(ablage, tmp_path):
    with pytest.raises(ValueError):
        kp.schreiben(tmp_path.parent / "x.pdf", b"x")
    with pytest.raises(ValueError):
        kp.schreiben(ablage / ".." / "x.pdf", b"x")
    with pytest.raises(ValueError):
        kp.schreiben(ablage, b"x")
    assert not (tmp_path / "x.pdf").exists()


def test_schreiben_fehler_hinterlaesst_kein_tmp(ablage, monkeypatch):
    def falsch(*_a):
        raise OSError("voll")

    monkeypatch.setattr(kp.os, "replace", falsch)
    with pytest.raises(OSError):
        kp.schreiben(ablage / "Kurse" / "a.pdf", b"x")
    assert not list(ablage.rglob("*.tmp"))
    assert not (ablage / "Kurse" / "a.pdf").exists()
