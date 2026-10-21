"""Bewerbungs-Pult-Client (Spec 2026-10-20-hermes-pruefer-design.md §5.3) und der
gemeinsame HTTP-Kern `pult_http`. Gegenstelle ist die Zentrale des Bewerbungs-Bots
(`/api/pult`, Kopf `X-Pult-Key`, Fehler als `{"detail": "<text>"}`), also derselbe Vertrag
wie beim Marketing-Pult. Gefaelscht wird nur `urlopen`; die Umleitungsprobe laeuft gegen
echte lokale Server."""
import http.client
import importlib.util
import io
import json
import threading
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import bewerbung_pult
import marketing_pult
import pult_http

SCHLUESSEL = "geheim-bw-123"
BASIS = "http://zentrale.test"


class _Antwort:
    def __init__(self, inhalt: bytes, typ: str = "application/json", lesefehler: Exception | None = None):
        self._inhalt = inhalt
        self._lesefehler = lesefehler          # gesetzt: der Rumpf bricht beim Lesen ab
        self.headers = {"Content-Type": typ}

    def read(self):
        if self._lesefehler is not None:
            raise self._lesefehler
        return self._inhalt

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Netz:
    def __init__(self):
        self.anfragen = []            # (Request, timeout)
        self.antwort = _Antwort(b"{}")
        self.fehler = None            # gesetzt: urlopen wirft ihn


@pytest.fixture
def netz(monkeypatch):
    """Der echte Client, nur das Netz ist gefaelscht."""
    n = _Netz()

    def urlopen(req, timeout=None):
        n.anfragen.append((req, timeout))
        if n.fehler is not None:
            raise n.fehler
        return n.antwort

    monkeypatch.setattr(bewerbung_pult, "URL", BASIS)
    monkeypatch.setattr(bewerbung_pult, "KEY", SCHLUESSEL)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return n


def _http_fehler(code: int, detail) -> urllib.error.HTTPError:
    koerper = json.dumps({"detail": detail}).encode()
    return urllib.error.HTTPError(f"{BASIS}/api/pult/x", code, "x", {}, io.BytesIO(koerper))


def _sichtbar(fehler: BaseException) -> str:
    """Alles, was ein Fehler preisgibt: str/repr/args (und bei PultFehler art/grund/koerper)
    jeder Ausnahme der __cause__/__context__-Kette, dazu der formatierte Traceback."""
    texte, offen, gesehen = [], [fehler], set()
    while offen:
        e = offen.pop()
        if e is None or id(e) in gesehen:
            continue
        gesehen.add(id(e))
        texte += [str(e), repr(e), repr(e.args)]
        if isinstance(e, pult_http.PultFehler):
            texte += [e.art, e.grund, repr(e.koerper)]
        offen += [e.__cause__, e.__context__]
    texte.append("".join(traceback.format_exception(fehler)))
    return "\n".join(texte)


# --- eingerichtet() -----------------------------------------------------------

@pytest.mark.parametrize("url,key,erwartet", [
    ("http://zentrale.test", "k", True),
    ("http://zentrale.test", "aB3-_.~+/=:xYz", True),        # uebliche Schluesselzeichen
    ("", "k", False),
    ("http://zentrale.test", "", False),
    ("", "", False),
])
def test_eingerichtet_braucht_url_und_schluessel(monkeypatch, url, key, erwartet):
    monkeypatch.setattr(bewerbung_pult, "URL", url)
    monkeypatch.setattr(bewerbung_pult, "KEY", key)
    assert bewerbung_pult.eingerichtet() is erwartet


@pytest.mark.parametrize("key", [
    "geheim\nzwei", "geheim\r\nzwei", "geheim\tzwei", "geheim zwei", "geheim\x00", "geheim\x7f",
    "geheim zwei", "geheim zwei", "geheimä", "geheim€",
])
def test_unbrauchbarer_schluessel_gilt_als_nicht_eingerichtet(netz, monkeypatch, key):
    # Steuerzeichen, Leerraum und Nicht-ASCII liessen http.client den Kopf ablehnen
    # (ValueError mit dem ganzen Schluessel im Text) - also gar nicht erst senden.
    monkeypatch.setattr(bewerbung_pult, "KEY", key)
    assert bewerbung_pult.eingerichtet() is False
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("GET", "/bewerbungen")
    assert f.value.art == "nicht_verbunden"
    assert netz.anfragen == []
    assert "geheim" not in _sichtbar(f.value)


def test_ohne_einrichtung_geht_nichts_ins_netz(netz, monkeypatch):
    monkeypatch.setattr(bewerbung_pult, "KEY", "")
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("GET", "/bewerbungen")
    assert f.value.art == "nicht_verbunden" and "BEWERBUNG_PULT" in f.value.grund
    assert netz.anfragen == []


def _frisch_geladen():
    """bewerbung_pult noch einmal laden (unter anderem Namen), um das Lesen der Umgebung
    zu pruefen, ohne das Modul der anderen Tests zu beruehren."""
    spec = importlib.util.spec_from_file_location("bewerbung_pult_frisch", bewerbung_pult.__file__)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_adresse_und_schluessel_kommen_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("BEWERBUNG_PULT_URL", "  http://zentrale.test:8450/  ")
    monkeypatch.setenv("BEWERBUNG_PULT_KEY", "  k  ")
    m = _frisch_geladen()
    assert m.URL == "http://zentrale.test:8450" and m.KEY == "k"
    assert m.eingerichtet() is True


def test_marketing_umgebung_macht_den_bewerbungs_client_nicht_einsatzbereit(monkeypatch):
    # Der Marketing-Schluessel darf nie an die Zentrale gehen.
    monkeypatch.delenv("BEWERBUNG_PULT_URL", raising=False)
    monkeypatch.delenv("BEWERBUNG_PULT_KEY", raising=False)
    monkeypatch.setenv("MARKETING_PULT_URL", "http://marketing.test")
    monkeypatch.setenv("MARKETING_PULT_KEY", "marketing-geheim")
    m = _frisch_geladen()
    assert m.URL == "" and m.KEY == "" and m.eingerichtet() is False


def test_bewerbung_und_marketing_teilen_dieselbe_fehlerklasse():
    assert marketing_pult.PultFehler is pult_http.PultFehler
    assert bewerbung_pult.PultFehler is pult_http.PultFehler


# --- Anfrage: URL, Kopf, Rumpf, Zeitlimit -------------------------------------

def test_url_hat_das_praefix_api_pult(netz):
    bewerbung_pult.anfrage("GET", "/bewerbungen?status=offen")
    req, _ = netz.anfragen[-1]
    assert req.full_url == "http://zentrale.test/api/pult/bewerbungen?status=offen"
    assert req.get_method() == "GET" and req.data is None


def test_post_schickt_json_im_rumpf(netz):
    netz.antwort = _Antwort(json.dumps({"status": "freigegeben", "kommando": "c-1"}).encode())
    r = bewerbung_pult.anfrage("POST", "/bewerbungen/b-1/freigeben",
                               {"fassung": 3, "bindung": "sha256:ab", "von": "felix"})
    assert r == {"status": "freigegeben", "kommando": "c-1"}
    req, _ = netz.anfragen[-1]
    assert req.full_url == "http://zentrale.test/api/pult/bewerbungen/b-1/freigeben"
    assert req.get_method() == "POST"
    assert json.loads(req.data) == {"fassung": 3, "bindung": "sha256:ab", "von": "felix"}
    assert req.headers.get("Content-type") == "application/json"


def test_schluessel_steht_im_unredirected_kopf(netz):
    bewerbung_pult.anfrage("GET", "/bewerbungen")
    req, _ = netz.anfragen[-1]
    assert req.unredirected_hdrs.get("X-pult-key") == SCHLUESSEL
    assert "X-pult-key" not in req.headers          # urllib gibt headers bei 30x weiter


class _Aufzeichner(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.gesehen.append(self.headers.get("X-Pult-Key"))
        if self.server.ziel:
            self.send_response(302)
            self.send_header("Location", self.server.ziel)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            koerper = b'{"angekommen": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(koerper)))
            self.end_headers()
            self.wfile.write(koerper)

    def log_message(self, *a):
        pass


@pytest.fixture
def zwei_server():
    """(erster, zweiter): der erste leitet per 302 auf den zweiten (anderer Port) um."""
    server = []
    for _ in range(2):
        s = ThreadingHTTPServer(("127.0.0.1", 0), _Aufzeichner)
        s.gesehen, s.ziel = [], None
        threading.Thread(target=s.serve_forever, daemon=True).start()
        server.append(s)
    server[0].ziel = f"http://127.0.0.1:{server[1].server_port}/api/pult/ziel"
    yield server
    for s in server:
        s.shutdown()
        s.server_close()


def test_schluessel_geht_nicht_an_das_ziel_einer_umleitung(zwei_server, monkeypatch):
    erster, zweiter = zwei_server
    # Hermetisch: kein Proxy aus der Umgebung dazwischen. urlopen merkt sich seinen Opener
    # (und damit die Proxy-Umgebung vom ersten Aufruf) - ihn zuruecksetzen; monkeypatch stellt ihn her.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(urllib.request, "_opener", None)
    monkeypatch.setattr(bewerbung_pult, "URL", f"http://127.0.0.1:{erster.server_port}")
    monkeypatch.setattr(bewerbung_pult, "KEY", SCHLUESSEL)
    assert bewerbung_pult.anfrage("GET", "/start") == {"angekommen": True}
    assert erster.gesehen == [SCHLUESSEL]            # die Zentrale bekommt ihn
    assert zweiter.gesehen == [None]                 # das Umleitungsziel nicht


def test_standardzeitlimit_sind_acht_sekunden(netz):
    assert bewerbung_pult.ZEITLIMIT_S == 8
    bewerbung_pult.anfrage("GET", "/bewerbungen")
    assert netz.anfragen[-1][1] == 8


def test_zeitlimit_pro_aufruf_und_aus_dem_modul(netz, monkeypatch):
    bewerbung_pult.anfrage("GET", "/bewerbungen", zeitlimit=30)
    assert netz.anfragen[-1][1] == 30
    monkeypatch.setattr(bewerbung_pult, "ZEITLIMIT_S", 3)        # wird beim Aufruf gelesen
    bewerbung_pult.anfrage("GET", "/bewerbungen")
    assert netz.anfragen[-1][1] == 3


def test_kern_nimmt_adresse_schluessel_und_zeitlimit_vom_aufrufer(netz):
    pult_http.anfrage("http://anders.test", "anderer-schluessel", "GET", "/x")
    req, zeitlimit = netz.anfragen[-1]
    assert req.full_url == "http://anders.test/api/pult/x"
    assert req.unredirected_hdrs.get("X-pult-key") == "anderer-schluessel"
    assert zeitlimit == 8
    pult_http.anfrage("http://anders.test", "k", "GET", "/x", zeitlimit=2.5)
    assert netz.anfragen[-1][1] == 2.5


@pytest.mark.parametrize("basis", ["http://anders.test/", "http://anders.test//"])
def test_kern_ignoriert_schraegstriche_am_ende_der_adresse(netz, basis):
    pult_http.anfrage(basis, "k", "GET", "/x")
    assert netz.anfragen[-1][0].full_url == "http://anders.test/api/pult/x"


def test_kern_laesst_einen_query_string_im_pfad_zu(netz):
    pult_http.anfrage("http://anders.test", "k", "GET", "/bewerbungen?status=entschieden&limit=10")
    assert netz.anfragen[-1][0].full_url == "http://anders.test/api/pult/bewerbungen?status=entschieden&limit=10"


@pytest.mark.parametrize("pfad", ["bewerbungen", "", "?status=offen", "/x#anker", "/x?a=1#anker"])
def test_kern_weist_ungueltige_pfade_ab_ohne_ins_netz_zu_gehen(netz, pfad):
    with pytest.raises(pult_http.PultFehler) as f:
        pult_http.anfrage("http://anders.test", "k", "GET", pfad)
    assert (f.value.art, f.value.grund) == ("unbekannt", "Pfad ungueltig")
    assert netz.anfragen == []


# --- Antworten ----------------------------------------------------------------

def test_roh_gibt_pdf_bytes_und_inhaltstyp(netz):
    netz.antwort = _Antwort(b"%PDF-1.7 ...", "application/pdf")
    inhalt, typ = bewerbung_pult.anfrage("GET", "/bewerbungen/b-1/anschreiben.pdf?fassung=3", roh=True)
    assert (inhalt, typ) == (b"%PDF-1.7 ...", "application/pdf")


def test_leere_antwort_ist_leeres_objekt(netz):
    netz.antwort = _Antwort(b"")
    assert bewerbung_pult.anfrage("GET", "/bewerbungen") == {}


def test_200_ohne_json_ist_pultfehler(netz):
    netz.antwort = _Antwort(b"<html>Proxy-Seite</html>", "text/html")
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("GET", "/bewerbungen")
    assert f.value.art == "unbekannt"


# --- Fehlerabbildung (Vertrag: task-3-report, HTTP-Vertrag) --------------------

FEHLER = [
    (401, "unauthorized", "nicht_verbunden", "401"),
    (503, "misconfigured: BEWERBUNG_PULT_KEY", "nicht_verbunden", "503"),
    (503, "datenbank_nicht_erreichbar", "nicht_erreichbar", "503"),
    (404, "unbekannt", "abgelehnt", "unbekannt"),
    (409, "fassung_veraltet", "abgelehnt", "fassung_veraltet"),
    (409, "schon_entschieden", "abgelehnt", "schon_entschieden"),
    (409, "wartet_auf_durchsicht", "abgelehnt", "wartet_auf_durchsicht"),
    (409, "nicht_offen", "abgelehnt", "nicht_offen"),
    (422, "eingabe_ungueltig", "abgelehnt", "eingabe_ungueltig"),
    (500, "fehler", "unbekannt", "500"),
]


@pytest.mark.parametrize("roh", [False, True])
@pytest.mark.parametrize("code,detail,art,grund", FEHLER)
def test_http_fehler_werden_auf_pultfehler_abgebildet(netz, code, detail, art, grund, roh):
    netz.fehler = _http_fehler(code, detail)
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("POST", "/bewerbungen/b-1/freigeben", {"fassung": 1}, roh=roh)
    assert (f.value.art, f.value.grund) == (art, grund)
    # Bei "nicht_verbunden" (Schluessel fehlt/passt nicht) traegt der Fehler keinen API-Koerper.
    assert f.value.koerper == (None if art == "nicht_verbunden" else {"detail": detail})


def test_409_schon_entschieden_ist_abgelehnt_mit_dem_code(netz):
    netz.fehler = _http_fehler(409, "schon_entschieden")
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("POST", "/bewerbungen/b-1/nicht-bewerben", {"fassung": 1})
    assert f.value.art == "abgelehnt" and f.value.grund == "schon_entschieden"


def test_validierungsliste_wird_zu_einem_text(netz):
    netz.fehler = _http_fehler(422, [{"loc": ["body", "fassung"], "msg": "x"}])
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("POST", "/bewerbungen/b-1/freigeben", {})
    assert f.value.art == "abgelehnt" and f.value.grund == "Eingabe ungueltig"


def test_fehler_ohne_json_rumpf(netz):
    netz.fehler = urllib.error.HTTPError(f"{BASIS}/api/pult/x", 502, "x", {}, io.BytesIO(b"<html>Bad Gateway"))
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("GET", "/bewerbungen")
    assert (f.value.art, f.value.grund) == ("unbekannt", "502")


@pytest.mark.parametrize("fehler", [
    TimeoutError("timed out"),
    urllib.error.URLError(TimeoutError("timed out")),
    urllib.error.URLError(ConnectionRefusedError(111, "refused")),
    ConnectionResetError(104, "reset"),
])
def test_zeitueberschreitung_und_netzfehler_sind_nicht_erreichbar(netz, fehler):
    netz.fehler = fehler
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("POST", "/bewerbungen/b-1/freigeben", {"fassung": 1})
    assert f.value.art == "nicht_erreichbar" and f.value.grund == type(fehler).__name__


@pytest.mark.parametrize("fehler", [
    http.client.IncompleteRead(b"%PDF-1.7 ab", 4096),
    http.client.BadStatusLine(""),
    http.client.RemoteDisconnected("Remote end closed connection without response"),
    http.client.InvalidURL("nonnumeric port: 'x'"),
])
def test_abbruch_im_protokoll_ist_nicht_erreichbar(netz, fehler):
    # http.client.HTTPException ist KEIN OSError und darf trotzdem nie roh herauskommen:
    # bei einem POST heisst das fuer den Aufrufer "Ergebnis unklar".
    netz.fehler = fehler
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("POST", "/bewerbungen/b-1/freigeben", {"fassung": 1})
    assert f.value.art == "nicht_erreichbar" and f.value.grund == type(fehler).__name__


def test_rumpf_bricht_beim_lesen_ab(netz):
    netz.antwort = _Antwort(b"", "application/pdf", lesefehler=http.client.IncompleteRead(b"%PDF", 4096))
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("GET", "/bewerbungen/b-1/anschreiben.pdf?fassung=3", roh=True)
    assert (f.value.art, f.value.grund) == ("nicht_erreichbar", "IncompleteRead")


class _AbbrechenderRumpf(io.BytesIO):
    def read(self, *a):
        raise http.client.IncompleteRead(b'{"detail": "schon', 4096)


def test_fehlerrumpf_bricht_beim_lesen_ab(netz):
    netz.fehler = urllib.error.HTTPError(f"{BASIS}/api/pult/x", 409, "x", {}, _AbbrechenderRumpf())
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("POST", "/bewerbungen/b-1/freigeben", {"fassung": 1})
    # Der Status 409 ist angekommen, nur der Grund fehlt: abgelehnt mit dem Statuscode.
    assert (f.value.art, f.value.grund) == ("abgelehnt", "409")


@pytest.mark.parametrize("schluessel,teile", [
    ("GEHEIM-ALPHA\nBETA", ["GEHEIM-ALPHA", "BETA"]),
    ("GEHEIM-ALPHA\r\nBETA", ["GEHEIM-ALPHA", "BETA"]),
    ("GEHEIM-ALPHA€BETA", ["GEHEIM-ALPHA", "BETA"]),        # nicht latin-1: UnicodeEncodeError
])
def test_kopf_mit_unzulaessigem_schluessel_wird_ein_pultfehler_ohne_schluesseltext(schluessel, teile):
    # Echtes urlopen gegen einen Host, den es nie gibt: http.client lehnt den Kopf ab (ValueError
    # mit dem ganzen Schluessel im Text), bevor irgendetwas verbunden wird.
    with pytest.raises(pult_http.PultFehler) as f:
        pult_http.anfrage("http://pult.invalid", schluessel, "GET", "/bewerbungen")
    assert (f.value.art, f.value.grund) == ("unbekannt", "Anfrage ungueltig")
    assert f.value.__cause__ is None and f.value.__context__ is None
    sichtbar = _sichtbar(f.value)
    for teil in [*teile, repr(schluessel)]:
        assert teil not in sichtbar


def test_marketing_client_bekommt_dieselbe_haertung(monkeypatch):
    monkeypatch.setattr(marketing_pult, "URL", "http://pult.invalid")
    monkeypatch.setattr(marketing_pult, "KEY", "GEHEIM-ALPHA\nBETA")
    with pytest.raises(marketing_pult.PultFehler) as f:
        marketing_pult.anfrage("GET", "/uebersicht")
    assert (f.value.art, f.value.grund) == ("unbekannt", "Anfrage ungueltig")
    assert "GEHEIM-ALPHA" not in _sichtbar(f.value)


@pytest.mark.parametrize("fehler", [
    _http_fehler(401, "unauthorized"),
    _http_fehler(409, "schon_entschieden"),
    _http_fehler(500, "fehler"),
    TimeoutError("timed out"),
    urllib.error.URLError("refused"),
    http.client.IncompleteRead(b"%PDF", 4096),
    http.client.BadStatusLine(""),
])
def test_schluessel_steht_in_keinem_fehler(netz, fehler):
    netz.fehler = fehler
    with pytest.raises(bewerbung_pult.PultFehler) as f:
        bewerbung_pult.anfrage("GET", "/bewerbungen")
    assert SCHLUESSEL not in _sichtbar(f.value)
