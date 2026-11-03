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
