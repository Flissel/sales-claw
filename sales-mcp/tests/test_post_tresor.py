"""Versiegelte Postfach-Zugaenge (post_tresor): rein, ohne Datenbank."""
import base64
import re
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_tresor  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def schluessel():
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    privat = k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    oeffentlich = k.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return privat, oeffentlich


@pytest.mark.parametrize("kaputt", [None, b"abc", 42, ""])
def test_oeffnen_ohne_text_bleibt_tresorfehler(schluessel, kaputt):
    # post_konten faengt nur TresorFehler; zugang_versiegelt darf NULL sein.
    privat, _ = schluessel
    with pytest.raises(post_tresor.TresorFehler):
        post_tresor.oeffnen(kaputt, privat)


def test_hin_und_zurueck(schluessel):
    privat, oeffentlich = schluessel
    v = post_tresor.versiegeln("geheimes-Passwort äö", oeffentlich)
    assert "geheimes" not in v
    assert post_tresor.oeffnen(v, privat) == "geheimes-Passwort äö"


def test_umgebung_base64_pem(schluessel, monkeypatch):
    privat, oeffentlich = schluessel
    monkeypatch.setenv("POST_SCHLUESSEL_OEFFENTLICH", base64.b64encode(oeffentlich.encode()).decode())
    monkeypatch.setenv("POST_SCHLUESSEL_PRIVAT", base64.b64encode(privat.encode()).decode())
    assert post_tresor.oeffnen(post_tresor.versiegeln("pw")) == "pw"


def test_tresor_mit_eigenem_schluesselpaar(schluessel, monkeypatch):
    """env_name: ein zweites Paar (Kalender) neben dem der Post, ohne Vermischung."""
    privat, oeffentlich = schluessel
    monkeypatch.setenv("KALENDER_SCHLUESSEL_OEFFENTLICH", base64.b64encode(oeffentlich.encode()).decode())
    monkeypatch.setenv("KALENDER_SCHLUESSEL_PRIVAT", base64.b64encode(privat.encode()).decode())
    monkeypatch.delenv("POST_SCHLUESSEL_OEFFENTLICH", raising=False)
    monkeypatch.delenv("POST_SCHLUESSEL_PRIVAT", raising=False)
    v = post_tresor.versiegeln("1//refresh", env_name="KALENDER_SCHLUESSEL_OEFFENTLICH")
    assert "refresh" not in v
    assert post_tresor.oeffnen(v, env_name="KALENDER_SCHLUESSEL_PRIVAT") == "1//refresh"
    with pytest.raises(post_tresor.TresorFehler):       # Vorgabe bleibt das Paar der Post
        post_tresor.oeffnen(v)
    with pytest.raises(post_tresor.TresorFehler):
        post_tresor.versiegeln("x")


def test_ohne_privaten_schluessel_tresorfehler(schluessel, monkeypatch):
    _, oeffentlich = schluessel
    monkeypatch.delenv("POST_SCHLUESSEL_PRIVAT", raising=False)
    v = post_tresor.versiegeln("pw", oeffentlich)
    with pytest.raises(post_tresor.TresorFehler):
        post_tresor.oeffnen(v)


def test_fehlermeldung_enthaelt_kein_geheimnis(schluessel):
    privat, oeffentlich = schluessel
    andere = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    falsch = andere.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    v = post_tresor.versiegeln("SehrGeheim123", oeffentlich)
    for aufruf in (
        lambda: post_tresor.oeffnen(v, falsch),
        lambda: post_tresor.oeffnen("kein-base64!!", privat),
        lambda: post_tresor.versiegeln("SehrGeheim123", "PEM-Muell"),
    ):
        with pytest.raises(post_tresor.TresorFehler) as e:
            aufruf()
        text = str(e.value)
        assert "SehrGeheim123" not in text
        assert "BEGIN" not in text and "PRIVATE" not in text and "PUBLIC" not in text


def test_zu_langes_passwort_wird_abgelehnt(schluessel):
    _, oeffentlich = schluessel
    with pytest.raises(post_tresor.TresorFehler):
        post_tresor.versiegeln("x" * 301, oeffentlich)


def test_skript_gibt_keinen_schluessel_aus_und_hat_kein_set_x():
    skript = (WURZEL / "deploy" / "post-schluessel.sh").read_text(encoding="utf-8")
    code = "\n".join(z for z in skript.splitlines() if not z.lstrip().startswith("#"))
    assert not re.search(r"set -[a-z]*x", code)
    assert not re.search(r"echo[^\n]*\$\{?(PRIVAT|OEFFENTLICH|PRIV|PUB)", code)
    assert "POST_SCHLUESSEL_PRIVAT" in code and "POST_SCHLUESSEL_OEFFENTLICH" in code
    assert "umask 077" in code and "chmod 600" in code and "mktemp" in code
    assert "schon vorhanden" in code


def test_lang_512_bytes_hin_und_zurueck(schluessel, monkeypatch):
    privat, oeffentlich = schluessel
    monkeypatch.setenv("KALENDER_SCHLUESSEL_OEFFENTLICH", base64.b64encode(oeffentlich.encode()).decode())
    monkeypatch.setenv("KALENDER_SCHLUESSEL_PRIVAT", base64.b64encode(privat.encode()).decode())
    token = "1//" + "aB-_" * 127 + "x"          # 512 Bytes
    assert len(token.encode()) == 512
    v = post_tresor.versiegeln_lang(token, env_name="KALENDER_SCHLUESSEL_OEFFENTLICH")
    assert v.startswith("v2:") and "aB-_" not in v
    assert post_tresor.oeffnen(v, env_name="KALENDER_SCHLUESSEL_PRIVAT") == token
    # kurze Klartexte und Umlaute gehen ebenso, die Grenze liegt bei 4096 Bytes
    assert post_tresor.oeffnen(post_tresor.versiegeln_lang("äö", oeffentlich), privat) == "äö"
    grenze = "x" * 4096
    assert post_tresor.oeffnen(post_tresor.versiegeln_lang(grenze, oeffentlich), privat) == grenze
    with pytest.raises(post_tresor.TresorFehler) as e:
        post_tresor.versiegeln_lang("x" * 4097, oeffentlich)
    assert str(e.value) == "Geheimnis zu lang (hoechstens 4096 Bytes)" and "Passwort" not in str(e.value)


def test_altes_format_oeffnet_unveraendert(schluessel):
    privat, oeffentlich = schluessel
    alt = post_tresor.versiegeln("altes-pw", oeffentlich)
    assert not alt.startswith("v2:")
    assert post_tresor.oeffnen(alt, privat) == "altes-pw"


def test_manipuliertes_v2_gibt_festen_tresorfehler(schluessel):
    privat, oeffentlich = schluessel
    v = post_tresor.versiegeln_lang("GanzGeheim-1234", oeffentlich)
    kopf, rest = v.split(".", 1)
    roh = bytearray(base64.b64decode(rest))
    roh[-1] ^= 0x01                                   # GCM-Tag kippen
    kaputt = [kopf + "." + base64.b64encode(bytes(roh)).decode(),
              "v2:" + "kein-base64", "v2:" + kopf[3:], v[:-6]]
    for text in kaputt:
        with pytest.raises(post_tresor.TresorFehler) as e:
            post_tresor.oeffnen(text, privat)
        assert str(e.value) == "Oeffnen fehlgeschlagen (Schluessel passt nicht oder Daten defekt)"
        assert "GanzGeheim" not in str(e.value)


@pytest.mark.parametrize("kaputt", [
    "kein base64!!",
    base64.b64encode(b"-----BEGIN PRIVATE KEY-----\nMuell\n-----END PRIVATE KEY-----\n").decode(),
])
def test_gesetzter_aber_kaputter_schluessel_ist_schluessel_unbrauchbar(
        schluessel, monkeypatch, kaputt):
    """T8-Nachtrag: eigene Art fuer den Betreiber; Post-Aufrufer fangen weiter
    TresorFehler. Daten-/Passt-nicht-Fehler bleiben der allgemeine Text."""
    privat, oeffentlich = schluessel
    v2 = post_tresor.versiegeln_lang("pw", oeffentlich)
    alt = post_tresor.versiegeln("pw", oeffentlich)
    monkeypatch.setenv("KALENDER_SCHLUESSEL_PRIVAT", kaputt)
    monkeypatch.setenv("KALENDER_SCHLUESSEL_OEFFENTLICH", kaputt)
    for aufruf in (
            lambda: post_tresor.oeffnen(v2, env_name="KALENDER_SCHLUESSEL_PRIVAT"),
            lambda: post_tresor.oeffnen(alt, env_name="KALENDER_SCHLUESSEL_PRIVAT"),
            lambda: post_tresor.versiegeln_lang("x", env_name="KALENDER_SCHLUESSEL_OEFFENTLICH"),
            lambda: post_tresor.versiegeln("x", env_name="KALENDER_SCHLUESSEL_OEFFENTLICH")):
        with pytest.raises(post_tresor.SchluesselUnbrauchbar) as e:
            aufruf()
        assert isinstance(e.value, post_tresor.SchluesselFehlt)
        assert isinstance(e.value, post_tresor.TresorFehler)
        assert "Muell" not in str(e.value) and "BEGIN" not in str(e.value)
    # Ein anderer, gueltiger Schluessel ist KEIN unbrauchbarer Schluessel.
    andere = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    falsch = andere.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()
    with pytest.raises(post_tresor.TresorFehler) as e:
        post_tresor.oeffnen(v2, falsch)
    assert not isinstance(e.value, post_tresor.SchluesselFehlt)


def test_v2_ohne_privaten_schluessel_ist_schluessel_fehlt(schluessel, monkeypatch):
    _, oeffentlich = schluessel
    monkeypatch.delenv("KALENDER_SCHLUESSEL_PRIVAT", raising=False)
    v = post_tresor.versiegeln_lang("pw", oeffentlich)
    with pytest.raises(post_tresor.SchluesselFehlt):
        post_tresor.oeffnen(v, env_name="KALENDER_SCHLUESSEL_PRIVAT")
