"""Google-Kalender: Client (`google_kalender`) und der Google-Zweig des Abgleichs.

Kein Netz: `_anfrage` wird in jedem Test ersetzt.
"""
import base64
import io
import json
import logging
import os
import re
import stat
import subprocess
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import google_kalender  # noqa: E402
import kalender_abgleich  # noqa: E402
import post_tresor  # noqa: E402
import server  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
VON = datetime(2030, 1, 1, tzinfo=timezone.utc)
BIS = VON + timedelta(days=30)
REFRESH = "1//REFRESH-GEHEIM-abc"
SECRET = "GOCSPX-CLIENT-GEHEIM"


@pytest.fixture(autouse=True)
def google_umgebung(monkeypatch):
    monkeypatch.setenv("GOOGLE_KALENDER_CLIENT_ID", "id-123.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_KALENDER_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("UI_BASIS_URL", "https://ui.example.test/")


def _ev(id_="e1", start="2030-01-02T09:00:00+01:00", ende="2030-01-02T10:00:00+01:00",
        **extra):
    ev = {"id": id_, "summary": "Zahnarzt", "location": "Praxis",
          "start": {"dateTime": start}, "end": {"dateTime": ende}}
    ev.update(extra)
    return ev


def _antwort(monkeypatch, *seiten):
    """_anfrage liefert nacheinander diese Seiten; gibt die Aufrufliste zurueck."""
    aufrufe = []
    liste = list(seiten)

    def falsch(methode, url, daten=None, token=None):
        aufrufe.append((methode, url, daten, token))
        return liste.pop(0)
    monkeypatch.setattr(google_kalender, "_anfrage", falsch)
    return aufrufe


def _http_fehler(code, body):
    return urllib.error.HTTPError("https://x.test", code, "Bad", {}, io.BytesIO(body))


# --- Client ------------------------------------------------------------------

def test_abgesagte_termine_fallen_raus(monkeypatch):
    _antwort(monkeypatch, {"items": [_ev("a"), _ev("b", status="cancelled")]})
    t = google_kalender.termine("tok", "primary", VON, BIS)
    assert [x["uid"] for x in t] == ["a"]


def test_ganztaegig_und_transparent(monkeypatch):
    _antwort(monkeypatch, {"items": [
        {"id": "g", "summary": "Geburtstag", "transparency": "transparent",
         "start": {"date": "2030-01-05"}, "end": {"date": "2030-01-06"}},
        _ev("n")]})
    t = {x["uid"]: x for x in google_kalender.termine("tok", "primary", VON, BIS)}
    assert t["g"]["ganztaegig"] is True and t["g"]["frei"] is True
    assert t["g"]["ende"] - t["g"]["beginn"] == timedelta(days=1)
    assert t["n"]["ganztaegig"] is False and t["n"]["frei"] is False
    assert t["n"]["titel"] == "Zahnarzt" and t["n"]["ort"] == "Praxis"
    assert t["n"]["beginn"] == datetime(2030, 1, 2, 8, tzinfo=timezone.utc)
    assert set(t["n"]) == {"beginn", "ende", "titel", "ort", "uid", "ganztaegig", "frei"}


def test_seiten_werden_alle_gelesen(monkeypatch):
    aufrufe = _antwort(
        monkeypatch,
        {"items": [_ev("a")], "nextPageToken": "S2"},
        {"items": [_ev("b", start="2030-01-03T09:00:00Z", ende="2030-01-03T10:00:00Z")]})
    t = google_kalender.termine("tok", "cal@example.test", VON, BIS)
    assert [x["uid"] for x in t] == ["a", "b"]
    assert len(aufrufe) == 2 and "pageToken=S2" in aufrufe[1][1]
    url = aufrufe[0][1]
    assert "singleEvents=true" in url and "maxResults=2500" in url
    assert "calendars/cal%40example.test/events" in url
    assert all(a[3] == "tok" for a in aufrufe)


def test_kalenderliste_alle_seiten(monkeypatch):
    _antwort(monkeypatch,
             {"items": [{"id": "a@x", "summary": "A", "primary": True}],
              "nextPageToken": "n"},
             {"items": [{"id": "b@x", "summary": "B", "summaryOverride": "Bb"}]})
    assert google_kalender.kalender_liste("tok") == [
        {"id": "a@x", "name": "A", "primaer": True},
        {"id": "b@x", "name": "Bb", "primaer": False}]


def test_anmelde_url_hat_scopes_offline_und_consent():
    u = google_kalender.anmelde_url("zustand-1")
    assert u.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in u and "prompt=consent" in u and "state=zustand-1" in u
    assert "calendar.calendarlist.readonly" in u and "calendar.events.readonly" in u
    assert "redirect_uri=https%3A%2F%2Fui.example.test%2Fteam%2Fkalender%2Fgoogle%2Fzurueck" in u
    assert SECRET not in u
    assert google_kalender.ruecksprung_url() == \
        "https://ui.example.test/team/kalender/google/zurueck"


def test_code_tauschen_und_fehlender_refresh_token(monkeypatch):
    aufrufe = _antwort(monkeypatch, {"refresh_token": "R", "access_token": "A"},
                       {"access_token": "A"})
    assert google_kalender.code_tauschen("c") == {"refresh_token": "R", "access_token": "A"}
    methode, _url, daten, token = aufrufe[0]
    assert methode == "POST" and token is None
    assert daten["code"] == "c" and daten["grant_type"] == "authorization_code"
    with pytest.raises(google_kalender.GoogleFehler) as e:
        google_kalender.code_tauschen("c")
    assert str(e.value) == "Google hat keinen dauerhaften Zugang geliefert"


def test_invalid_grant_wirft_zugang_abgelaufen(monkeypatch):
    def falsch(*a, **k):
        raise _http_fehler(400, b'{"error": "invalid_grant", "error_description": "Token revoked"}')
    monkeypatch.setattr(google_kalender, "_anfrage", falsch)
    with pytest.raises(google_kalender.GoogleFehler) as e:
        google_kalender.zugang_erneuern(REFRESH)
    assert str(e.value) == google_kalender.ZUGANG_ABGELAUFEN == \
        "Zugang abgelaufen – bitte neu verbinden"


def test_fehlertext_ohne_token(monkeypatch, caplog):
    body = json.dumps({"error": "invalid_request",
                       "error_description": f"bad {REFRESH} {SECRET} ya29.ZUGRIFF"}).encode()

    def falsch(*a, **k):
        raise _http_fehler(400, body)
    monkeypatch.setattr(google_kalender, "_anfrage", falsch)
    with caplog.at_level(logging.DEBUG):
        for aufruf in (lambda: google_kalender.zugang_erneuern(REFRESH),
                       lambda: google_kalender.code_tauschen("c"),
                       lambda: google_kalender.kalender_liste("ya29.ZUGRIFF"),
                       lambda: google_kalender.termine("ya29.ZUGRIFF", "primary", VON, BIS)):
            with pytest.raises(google_kalender.GoogleFehler) as e:
                aufruf()
            for geheim in (REFRESH, SECRET, "ya29", "bad "):
                assert geheim not in str(e.value) and geheim not in repr(e.value)
    for geheim in (REFRESH, SECRET, "ya29"):
        assert geheim not in caplog.text


def test_echtes_anfrage_wandelt_fehler_ohne_body(monkeypatch):
    """Die echte `_anfrage` (urllib gemockt) gibt nur feste Texte heraus."""
    def oeffnen(req, timeout=None):
        raise _http_fehler(403, f"secret {SECRET}".encode())
    monkeypatch.setattr(google_kalender.urllib.request, "urlopen", oeffnen)
    with pytest.raises(google_kalender.GoogleFehler) as e:
        google_kalender._anfrage("GET", "https://x.test/", token="ya29.T")
    assert SECRET not in str(e.value) and "ya29" not in str(e.value)


def test_token_anfrage_ist_form_kodiert(monkeypatch):
    gesehen = {}

    class Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return b'{"access_token": "A"}'

    def oeffnen(req, timeout=None):
        gesehen["req"] = req
        return Antwort()
    monkeypatch.setattr(google_kalender.urllib.request, "urlopen", oeffnen)
    assert google_kalender.zugang_erneuern(REFRESH) == "A"
    req = gesehen["req"]
    assert req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert b"grant_type=refresh_token" in req.data and REFRESH.encode() not in req.full_url.encode()
    assert SECRET not in req.full_url


# --- Schluesselpaar ---------------------------------------------------------------

def _paar():
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    privat = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    oeff = k.public_key().public_bytes(serialization.Encoding.PEM,
                                       serialization.PublicFormat.SubjectPublicKeyInfo)
    return (base64.b64encode(privat).decode(), base64.b64encode(oeff).decode())


# --- Abgleich (Datenbank sales_test) -------------------------------------------

@pytest.fixture
def db(monkeypatch):
    assert server.SCHEMA == "sales_test"
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
        conn.execute("truncate sales_test.kalender_konten cascade")
    privat, oeff = _paar()
    monkeypatch.setenv("KALENDER_SCHLUESSEL_PRIVAT", privat)
    monkeypatch.setenv("KALENDER_SCHLUESSEL_OEFFENTLICH", oeff)
    monkeypatch.setenv("POST_BESITZER", "felix")
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.kalender_quellen cascade")
        conn.execute("truncate sales_test.kalender_konten cascade")


def _konto(adresse="felix@example.test"):
    versiegelt = post_tresor.versiegeln(
        REFRESH, env_name="KALENDER_SCHLUESSEL_OEFFENTLICH")
    z = server._q(
        "insert into kalender_konten (besitzer, anbieter, adresse, zugang_versiegelt) "
        "values ('felix', 'google', %s, %s) returning id", (adresse, versiegelt))
    return str(z[0]["id"])


def _quelle(konto_id, name, google_id="primary"):
    z = server._q(
        "insert into kalender_quellen (anzeigename, besitzer, bereich, art, konto_id, "
        "google_id) values (%s, 'felix', 'privat', 'google', %s, %s) returning id",
        (name, konto_id, google_id))
    return next(q for q in server.kalenderquellen_lesen(False) if q["id"] == str(z[0]["id"]))


def _stand(qid):
    return server._q("select * from kalender_quellen where id = %s", (qid,))[0]


def test_google_quelle_wird_abgeglichen(db, monkeypatch):
    q = _quelle(_konto(), "G1")
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    aufrufe = _antwort(
        monkeypatch, {"access_token": "ya29.A"},
        {"items": [_ev("a", start=start.isoformat(),
                       ende=(start + timedelta(hours=1)).isoformat()),
                   _ev("b", status="cancelled")]})
    anzahl, fehler = kalender_abgleich.quelle_abgleichen(q)
    assert (anzahl, fehler) == (1, None)
    zeile = server._q("select * from kalender_termine where quelle_id = %s", (q["id"],))
    assert len(zeile) == 1 and zeile[0]["titel"] == "Zahnarzt"
    st = _stand(q["id"])
    assert st["letzter_fehler"] is None and st["zuletzt_gelesen"] is not None
    assert aufrufe[0][2]["refresh_token"] == REFRESH       # Tresor wirklich geoeffnet
    assert aufrufe[1][3] == "ya29.A"


def test_invalid_grant_wird_luecke(db, monkeypatch):
    q = _quelle(_konto(), "G2")

    def falsch(*a, **k):
        raise _http_fehler(400, b'{"error": "invalid_grant"}')
    monkeypatch.setattr(google_kalender, "_anfrage", falsch)
    anzahl, fehler = kalender_abgleich.quelle_abgleichen(q)
    assert anzahl is None and fehler == google_kalender.ZUGANG_ABGELAUFEN
    assert _stand(q["id"])["letzter_fehler"] == google_kalender.ZUGANG_ABGELAUFEN
    jetzt = datetime.now(timezone.utc)
    termine, luecken = server.kalendertermine_lesen(jetzt, jetzt + timedelta(days=2), "felix")
    assert termine == []
    assert [l["grund"] for l in luecken] == [google_kalender.ZUGANG_ABGELAUFEN]


def test_fehler_im_stand_ohne_google_text(db, monkeypatch, caplog):
    q = _quelle(_konto(), "G3")

    def falsch(*a, **k):
        raise _http_fehler(500, f"{REFRESH} {SECRET}".encode())
    monkeypatch.setattr(google_kalender, "_anfrage", falsch)
    with caplog.at_level(logging.DEBUG):
        kalender_abgleich.runde()
    fehler = _stand(q["id"])["letzter_fehler"]
    assert fehler == google_kalender.ABGELEHNT
    assert REFRESH not in caplog.text and SECRET not in caplog.text


def test_ein_access_token_je_konto_und_runde(db, monkeypatch):
    k1, k2 = _konto("a@example.test"), _konto("b@example.test")
    q = [_quelle(k1, "H1", "c1"), _quelle(k1, "H2", "c2"), _quelle(k2, "H3", "c3")]
    gesehen = []

    def falsch(methode, url, daten=None, token=None):
        gesehen.append((url, token))
        return {"access_token": f"tok{len(gesehen)}"} if url == google_kalender.TOKEN_URL \
            else {"items": []}
    monkeypatch.setattr(google_kalender, "_anfrage", falsch)
    bilanz = kalender_abgleich.runde()
    assert bilanz == {"quellen": 3, "fehler": 0}
    assert sum(1 for u, _ in gesehen if u == google_kalender.TOKEN_URL) == 2
    assert all(_stand(x["id"])["letzter_fehler"] is None for x in q)
    # naechste Runde fragt neu
    kalender_abgleich.runde()
    assert sum(1 for u, _ in gesehen if u == google_kalender.TOKEN_URL) == 4


def test_gescheiterter_token_wird_je_runde_nur_einmal_versucht(db, monkeypatch):
    k = _konto()
    _quelle(k, "J1", "c1")
    _quelle(k, "J2", "c2")
    zaehler = []

    def falsch(*a, **k):
        zaehler.append(1)
        raise _http_fehler(400, b'{"error": "invalid_grant"}')
    monkeypatch.setattr(google_kalender, "_anfrage", falsch)
    assert kalender_abgleich.runde() == {"quellen": 2, "fehler": 2}
    assert len(zaehler) == 1


def test_quelle_ohne_konto_ist_luecke(db):
    z = server._q(
        "insert into kalender_quellen (anzeigename, besitzer, bereich, art, google_id) "
        "values ('K0', 'felix', 'privat', 'google', 'primary') returning id")
    q = next(x for x in server.kalenderquellen_lesen(False) if x["id"] == str(z[0]["id"]))
    anzahl, fehler = kalender_abgleich.quelle_abgleichen(q)
    assert anzahl is None and fehler == kalender_abgleich.KONTO_FEHLT


def test_falscher_schluessel_ist_luecke_ohne_details(db, monkeypatch):
    q = _quelle(_konto(), "L1")
    monkeypatch.setenv("KALENDER_SCHLUESSEL_PRIVAT", _paar()[0])    # anderes Paar
    anzahl, fehler = kalender_abgleich.quelle_abgleichen(q)
    assert anzahl is None and fehler == kalender_abgleich.ZUGANG_UNLESBAR


def test_fremde_privat_google_quelle_speichert_keinen_titel(db, monkeypatch):
    k = _konto()
    z = server._q(
        "insert into kalender_quellen (anzeigename, besitzer, bereich, art, konto_id, "
        "google_id) values ('M1', 'ivan', 'privat', 'google', %s, 'primary') returning id", (k,))
    q = next(x for x in server.kalenderquellen_lesen(False) if x["id"] == str(z[0]["id"]))
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    _antwort(monkeypatch, {"access_token": "T"},
             {"items": [_ev("a", start=start.isoformat(),
                            ende=(start + timedelta(hours=1)).isoformat())]})
    assert kalender_abgleich.quelle_abgleichen(q)[0] == 1
    zeile = server._q("select titel, ort from kalender_termine where quelle_id = %s", (q["id"],))[0]
    assert zeile["titel"] is None and zeile["ort"] is None


# --- Deploy-Skripte (nur Aufbau; ausgefuehrt wird nur google-kalender-zugang auf Attrappen) --

def _code(pfad):
    text = (WURZEL / "deploy" / pfad).read_text(encoding="utf-8")
    return "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))


def test_kalender_schluessel_skript_aufbau():
    code = _code("kalender-schluessel.sh")
    assert not re.search(r"set -[a-z]*x", code)
    assert not re.search(r"echo[^\n]*\$\{?(PRIVAT|OEFFENTLICH)", code)
    assert "KALENDER_SCHLUESSEL_PRIVAT" in code and "KALENDER_SCHLUESSEL_OEFFENTLICH" in code
    assert "POST_SCHLUESSEL" not in code
    assert "umask 077" in code and "chmod 600" in code and "mktemp" in code
    assert "schon vorhanden" in code


def test_google_zugang_skript_traegt_ein_und_gibt_nichts_aus(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nGOOGLE_KALENDER_CLIENT_ID=alt\nB=2", encoding="utf-8")
    skript = WURZEL / "deploy" / "google-kalender-zugang.sh"
    code = _code("google-kalender-zugang.sh")
    assert not re.search(r"set -[a-z]*x", code) and "read -r -s" in code
    assert "docker" not in code                      # startet nichts neu
    r = subprocess.run(["bash", str(skript)], input=f"cid-1.apps\n{SECRET}\n", text=True,
                       capture_output=True, timeout=30,
                       env={**os.environ, "SALES_ENV_DATEI": str(env)})
    assert r.returncode == 0, r.stderr
    assert SECRET not in r.stdout + r.stderr and "cid-1" not in r.stdout + r.stderr
    text = env.read_text(encoding="utf-8")
    assert "GOOGLE_KALENDER_CLIENT_ID=cid-1.apps\n" in text
    assert f"GOOGLE_KALENDER_CLIENT_SECRET={SECRET}\n" in text
    assert "alt" not in text and "A=1\n" in text and "B=2\n" in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    # zweiter Lauf ersetzt, doppelt wird nichts
    subprocess.run(["bash", str(skript)], input="neu\nSEC\n", text=True,
                   capture_output=True, timeout=30,
                   env={**os.environ, "SALES_ENV_DATEI": str(env)})
    text = env.read_text(encoding="utf-8")
    assert text.count("GOOGLE_KALENDER_CLIENT_ID=") == 1 and "GOOGLE_KALENDER_CLIENT_ID=neu\n" in text
    r = subprocess.run(["bash", str(skript)], input="a b\nx\n", text=True,
                       capture_output=True, timeout=30,
                       env={**os.environ, "SALES_ENV_DATEI": str(env)})
    assert r.returncode == 3 and "GOOGLE_KALENDER_CLIENT_ID=neu\n" in env.read_text(encoding="utf-8")
