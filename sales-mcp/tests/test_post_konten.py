"""Mehrere Postfaecher je Anbieter (post_konten). DB-Tests nur gegen sales_test."""
import os
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_konten  # noqa: E402
import postfach  # noqa: E402
import server  # noqa: E402

GEHEIM = "Sehr-Geheim-Passwort-4711"
# Beim Import, bevor die conftest-Wache (_keine_echten_zusatzpostfaecher) es ersetzt.
_ECHT_OEFFNEN = postfach._imap_oeffnen


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' - erlaubt ist nur 'sales_test'.")


@pytest.fixture(autouse=True)
def saubere_tabelle():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_konten cascade")
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_konten cascade")


@pytest.fixture(scope="module")
def schluessel():
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    privat = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    oeffentlich = k.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return privat, oeffentlich


@pytest.fixture(autouse=True)
def schluessel_env(schluessel, monkeypatch):
    import base64
    privat, oeffentlich = schluessel
    monkeypatch.setenv("POST_SCHLUESSEL_PRIVAT", base64.b64encode(privat.encode()).decode())
    monkeypatch.setenv("POST_SCHLUESSEL_OEFFENTLICH", base64.b64encode(oeffentlich.encode()).decode())


def _ok(konto):
    return None


def _zeilen():
    with server.pool.connection() as conn:
        return conn.execute("select * from sales_test.post_konten order by kennung").fetchall()


def test_zwei_gmx_konten_nebeneinander():
    a = post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "a@gmx.de", GEHEIM, probe=_ok)
    b = post_konten.konto_anlegen("b1", "gmx-firma", "gmx", "f@gmx.de", GEHEIM, probe=_ok)
    assert "konto_id" in a and "konto_id" in b and a["konto_id"] != b["konto_id"]
    zeilen = _zeilen()
    assert [z["kennung"] for z in zeilen] == ["gmx-firma", "gmx-privat"]
    assert {z["anbieter"] for z in zeilen} == {"gmx"}
    assert {z["quelle"] for z in zeilen} == {"ui"}
    assert len(post_konten.aktive_konten()) == 2


def test_kennung_doppelt_wird_abgelehnt():
    post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "a@gmx.de", GEHEIM, probe=_ok)
    r = post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "x@gmx.de", GEHEIM, probe=_ok)
    assert "fehler" in r and GEHEIM not in r["fehler"]
    assert len(_zeilen()) == 1


def test_ungueltige_kennung():
    r = post_konten.konto_anlegen("b1", "GMX privat", "gmx", "a@gmx.de", GEHEIM, probe=_ok)
    assert "fehler" in r
    assert _zeilen() == []


def test_unzulaessiger_anbieter_aus_der_ui():
    for anbieter in ("namecheap", "yahoo"):
        r = post_konten.konto_anlegen("b1", "mein-konto", anbieter, "a@x.de", GEHEIM, probe=_ok)
        assert "fehler" in r
    assert _zeilen() == []


def test_abgelehnte_probe_speichert_nichts():
    def probe(konto):
        raise RuntimeError(f"Anmeldung abgelehnt fuer {konto.passwort}")

    r = post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "a@gmx.de", GEHEIM, probe=probe)
    assert "fehler" in r
    assert GEHEIM not in r["fehler"]      # auch nicht, wenn die Probe es selbst nennt
    assert _zeilen() == []


def test_probe_bekommt_konto_mit_anbieter():
    gesehen = []
    post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "a@gmx.de", GEHEIM,
                              probe=gesehen.append)
    assert gesehen[0].anbieter["imap"] == "imap.gmx.net"
    assert gesehen[0].kennung == "gmx-privat" and gesehen[0].anbieter_id == "gmx"


def test_passwort_steht_nirgends_im_klartext():
    r = post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "a@gmx.de", GEHEIM, probe=_ok)
    assert GEHEIM not in repr(r)
    zeile = _zeilen()[0]
    assert GEHEIM not in repr(zeile)
    assert zeile["zugang_versiegelt"]
    assert GEHEIM not in repr(post_konten.aktive_konten())


def test_env_konten_uebernehmen_ist_idempotent(monkeypatch):
    monkeypatch.setattr(postfach, "IMAP_HOST", "mail.example.org")
    monkeypatch.setattr(postfach, "IMAP_USER", "laden@example.org")
    monkeypatch.setenv("POSTFACH_GMX_ADRESSE", "o@gmx.de")
    monkeypatch.setenv("POSTFACH_GMX_PASSWORT", GEHEIM)
    monkeypatch.delenv("POSTFACH_GMAIL_ADRESSE", raising=False)
    monkeypatch.delenv("POSTFACH_GMAIL_PASSWORT", raising=False)
    assert post_konten.env_konten_uebernehmen("b1") == 2
    assert post_konten.env_konten_uebernehmen("b1") == 0
    zeilen = {z["kennung"]: z for z in _zeilen()}
    assert set(zeilen) == {"haupt", "gmx"}
    assert zeilen["haupt"]["anbieter"] == "namecheap" and zeilen["haupt"]["adresse"] == "laden@example.org"
    assert zeilen["gmx"]["anbieter"] == "gmx" and zeilen["gmx"]["adresse"] == "o@gmx.de"
    assert all(z["quelle"] == "env" and z["zugang_versiegelt"] is None for z in zeilen.values())


def test_konto_repr_ohne_passwort():
    k = postfach.Konto("gmx-privat", "a@gmx.de", GEHEIM, anbieter_id="gmx")
    assert GEHEIM not in repr(k)
    assert k.anbieter["imap"] == "imap.gmx.net"
    assert postfach.Konto("gmx", "a@gmx.de", GEHEIM).anbieter["name"] == "GMX"


def test_namecheap_ist_kein_eigenes_zusatzpostfach(monkeypatch):
    monkeypatch.setattr(postfach, "IMAP_HOST", "")
    for n in ("GMX", "GMAIL", "NAMECHEAP"):
        monkeypatch.delenv(f"POSTFACH_{n}_ADRESSE", raising=False)
    assert "namecheap" in postfach.ANBIETER
    assert "namecheap" not in postfach.kennungen()


def test_verbinden_ui_oeffnet_versiegeltes_passwort(monkeypatch):
    post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "a@gmx.de", GEHEIM, probe=_ok)
    gesehen = []
    monkeypatch.setattr(postfach, "_imap_oeffnen", lambda k: gesehen.append(k) or "VERBINDUNG")
    assert post_konten.verbinden(post_konten.aktive_konten()[0]) == "VERBINDUNG"
    k = gesehen[0]
    assert (k.kennung, k.adresse, k.passwort, k.anbieter_id) == ("gmx-privat", "a@gmx.de", GEHEIM, "gmx")


def test_env_kennungen_sind_reserviert():
    # M4: ein UI-Konto "gmx" verdraengte still das Env-Konto gleichen Namens.
    for kennung in ("haupt", "gmx", "gmail"):
        r = post_konten.konto_anlegen("b1", kennung, "gmx", "a@gmx.de", GEHEIM, probe=_ok)
        assert "reserviert" in r.get("fehler", ""), kennung
    assert _zeilen() == []
    assert "konto_id" in post_konten.konto_anlegen("b1", "gmx-privat", "gmx", "a@gmx.de",
                                                    GEHEIM, probe=_ok)


def test_probe_mit_eigener_zeitgrenze_ohne_prozessweiten_default(monkeypatch):
    # M6: die Probe laeuft in sales-ui - ein haengender Anbieter darf die Anfrage
    # nicht ewig halten, aber auch nicht jeden anderen Socket des Prozesses begrenzen.
    import socket
    gesehen = []

    class Kasten:
        def __init__(self, host, port, **kw):
            gesehen.append((host, port, kw))

        def login(self, adresse, passwort):
            pass

        def logout(self):
            pass
    vorher = socket.getdefaulttimeout()
    # conftest sperrt _imap_oeffnen; hier gilt das echte, nur IMAP4_SSL ist Attrappe.
    monkeypatch.setattr(postfach, "_imap_oeffnen", _ECHT_OEFFNEN)
    monkeypatch.setattr(postfach.imaplib, "IMAP4_SSL", Kasten)
    post_konten._probe_imap(postfach.Konto("gmx-x", "a@gmx.de", GEHEIM, anbieter_id="gmx"))
    host, port, kw = gesehen[0]
    assert host == "imap.gmx.net" and port == 993
    assert kw["timeout"] == post_konten.PROBE_TIMEOUT_S == 30
    assert socket.getdefaulttimeout() == vorher
    assert "setdefaulttimeout" not in Path(post_konten.__file__).read_text(encoding="utf-8")


def test_verbinden_env_nutzt_postfach_oeffnen(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(postfach, "oeffnen", lambda kennung: aufrufe.append(kennung) or "V")
    assert post_konten.verbinden({"quelle": "env", "kennung": "gmx"}) == "V"
    assert aufrufe == ["gmx"]
