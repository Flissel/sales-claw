"""sales-auge POST /pdf: Auftraege laufen ueber eine Warteschlange im Hauptthread.

Der Browser ist eine Attrappe (new_context/new_page/set_content/pdf); Playwright
muss nicht installiert sein.
"""
import http.client
import queue
import threading
import time
import urllib.error
import urllib.request

import pytest

import auge


class Seite:
    def __init__(self, browser):
        self.b = browser

    def set_default_timeout(self, ms):
        self.b.timeout_ms = ms

    def set_content(self, html, **kw):
        self.b.html = html

    def pdf(self, **kw):
        self.b.pdf_args = kw
        self.b.thread = threading.get_ident()
        if self.b.fehler:
            raise RuntimeError("Seite kaputt")
        return b"%PDF-1.7 " + self.b.html.encode("utf-8")

    def close(self):
        self.b.zu.append("seite")


class Kontext:
    def __init__(self, browser):
        self.b = browser

    def new_page(self):
        return Seite(self.b)

    def route(self, muster, handler):
        self.b.routen.append(muster)

    def close(self):
        self.b.zu.append("kontext")


class FakeBrowser:
    def __init__(self, fehler=False):
        self.fehler = fehler
        self.kontext_args = None
        self.pdf_args = None
        self.html = None
        self.thread = None
        self.timeout_ms = None
        self.zu = []
        self.routen = []

    def new_context(self, **kw):
        self.kontext_args = kw
        return Kontext(self)


class Attrappe:
    pass


@pytest.fixture
def dienst():
    lauf = {"ok": True}
    q = queue.Queue()
    srv = auge.http_dienst(Attrappe(), "127.0.0.1", 0,
                           lambda: {"ok": lauf["ok"]}, pdf_auftraege=q)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", q, lauf
    srv.shutdown()
    srv.server_close()


def _post_pdf(url, html="<p>x</p>"):
    anfrage = urllib.request.Request(
        url + "/pdf", data=html.encode("utf-8"), method="POST",
        headers={"Content-Type": "text/html; charset=utf-8"})
    with urllib.request.urlopen(anfrage, timeout=20) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def _im_hintergrund(url, html="<p>x</p>"):
    ergebnis = {}

    def lauf():
        try:
            ergebnis["ok"] = _post_pdf(url, html)
        except urllib.error.HTTPError as e:
            ergebnis["code"] = e.code

    t = threading.Thread(target=lauf)
    t.start()
    return t, ergebnis


def test_auftrag_wird_im_hauptthread_erledigt(dienst):
    url, q, _ = dienst
    browser = FakeBrowser()
    t, erg = _im_hintergrund(url, "<p>ä</p>")
    while t.is_alive():
        auge.pdf_warten_und_arbeiten(q, browser, 0.05)
    t.join()
    status, typ, daten = erg["ok"]
    assert status == 200 and typ == "application/pdf"
    assert daten.startswith(b"%PDF") and "ä".encode("utf-8") in daten
    assert browser.thread == threading.get_ident()       # Hauptthread, nicht HTTP-Thread
    assert browser.kontext_args["java_script_enabled"] is False
    assert browser.pdf_args["format"] == "A4" and browser.pdf_args["print_background"] is True
    assert browser.pdf_args["margin"] == {"top": "15mm", "right": "15mm",
                                          "bottom": "15mm", "left": "15mm"}
    assert browser.timeout_ms == auge.PDF_RENDER_TIMEOUT_MS == 30_000
    assert browser.zu == ["seite", "kontext"]
    assert browser.routen                                 # keine Netzzugriffe aus dem HTML


def test_seite_wird_auch_bei_fehler_geschlossen_und_gibt_500(dienst):
    url, q, _ = dienst
    browser = FakeBrowser(fehler=True)
    t, erg = _im_hintergrund(url)
    while t.is_alive():
        auge.pdf_warten_und_arbeiten(q, browser, 0.05)
    t.join()
    assert erg == {"code": 500}
    assert browser.zu == ["seite", "kontext"]


def test_browser_weg_gibt_503(dienst):
    url, q, lauf = dienst
    lauf["ok"] = False
    with pytest.raises(urllib.error.HTTPError) as e:
        _post_pdf(url)
    assert e.value.code == 503
    assert q.empty()


def test_ohne_warteschlange_503():
    srv = auge.http_dienst(Attrappe(), "127.0.0.1", 0, lambda: {})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            _post_pdf(f"http://127.0.0.1:{srv.server_address[1]}")
        assert e.value.code == 503
    finally:
        srv.shutdown()
        srv.server_close()


def test_zeitlimit_gibt_504_und_auftrag_wird_verworfen(dienst, monkeypatch):
    url, q, _ = dienst
    monkeypatch.setattr(auge, "PDF_ZEIT_S", 0.3)
    with pytest.raises(urllib.error.HTTPError) as e:
        _post_pdf(url)
    assert e.value.code == 504
    browser = FakeBrowser()
    auge.pdf_warten_und_arbeiten(q, browser, 0.05)   # verspaetet: nicht mehr rendern
    assert browser.kontext_args is None


def test_zu_gross_gibt_413(dienst, monkeypatch):
    url, q, _ = dienst
    monkeypatch.setattr(auge, "PDF_MAX_BYTES", 10)
    with pytest.raises(urllib.error.HTTPError) as e:
        _post_pdf(url, "x" * 11)
    assert e.value.code == 413
    assert q.empty()


def test_zu_gross_laut_kopfzeile_ohne_rumpf_413(dienst):
    url, q, _ = dienst
    host, port = url.rsplit("//", 1)[1].split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=10)
    c.putrequest("POST", "/pdf")
    c.putheader("Content-Length", str(20 * 1024 * 1024 + 1))
    c.endheaders()
    assert c.getresponse().status == 413
    c.close()


def test_leer_gibt_400(dienst):
    url, _, _ = dienst
    with pytest.raises(urllib.error.HTTPError) as e:
        _post_pdf(url, "")
    assert e.value.code == 400


def test_abweisen_beantwortet_wartende_mit_503(dienst):
    url, q, _ = dienst
    t, erg = _im_hintergrund(url)
    frist = time.monotonic() + 10
    while q.empty():
        assert time.monotonic() < frist, "Auftrag wurde nicht eingereiht"
        threading.Event().wait(0.01)
    auge.pdf_abweisen(q)
    t.join()
    assert erg == {"code": 503}


def test_warten_ohne_auftrag_kehrt_nach_takt_zurueck():
    q = queue.Queue()
    assert auge.pdf_warten_und_arbeiten(q, FakeBrowser(), 0.05) == 0


def test_hoechstens_ein_auftrag_je_aufruf():
    q = queue.Queue()
    a1, a2 = auge.PdfAuftrag("<p>1</p>"), auge.PdfAuftrag("<p>2</p>")
    q.put(a1)
    q.put(a2)
    browser = FakeBrowser()
    assert auge.pdf_warten_und_arbeiten(q, browser, 0.05) == 1
    assert a1.fertig.is_set() and not a2.fertig.is_set()
    assert q.qsize() == 1                               # zweiter wartet auf die naechste Runde
    assert auge.pdf_warten_und_arbeiten(q, browser, 0.05) == 1
    assert a2.fertig.is_set()


def test_veralteter_auftrag_wird_uebersprungen_der_naechste_gedruckt():
    q = queue.Queue()
    alt, neu = auge.PdfAuftrag("<p>alt</p>"), auge.PdfAuftrag("<p>neu</p>")
    alt.eingereicht = time.monotonic() - auge.PDF_ZEIT_S - 1
    q.put(alt)
    q.put(neu)
    browser = FakeBrowser()
    assert auge.pdf_warten_und_arbeiten(q, browser, 0.05) == 1
    assert not alt.fertig.is_set() and alt.abgebrochen   # nicht gerendert
    assert neu.fertig.is_set() and neu.status == 200
    assert browser.html == "<p>neu</p>"


def test_nur_veralteter_auftrag_wird_nicht_gerendert():
    q = queue.Queue()
    alt = auge.PdfAuftrag("<p>alt</p>")
    alt.eingereicht = time.monotonic() - auge.PDF_ZEIT_S - 1
    q.put(alt)
    browser = FakeBrowser()
    assert auge.pdf_warten_und_arbeiten(q, browser, 0.05) == 0
    assert browser.kontext_args is None
