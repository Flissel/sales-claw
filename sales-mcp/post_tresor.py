"""Versiegelte Postfach-Zugaenge (Post-Sammelstelle, Stufe 1).

Die Web-Oberflaeche kennt nur den OEFFENTLICHEN Schluessel: ein Passwort, das dort
eingegeben wird, wird sofort versiegelt (RSA-3072, OAEP mit SHA-256) und so
gespeichert. Nur der Abholdienst haelt den PRIVATEN Schluessel und kann es oeffnen.
Wer die Datenbank oder die UI-Umgebung liest, bekommt kein Klartext-Passwort.

Beide Schluessel liegen in der Umgebung als base64 des PEM (eine Zeile, .env-tauglich).
Fehlermeldungen nennen nie Klartext oder Schluessel - TresorFehler traegt nur den Grund.
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENV_OEFFENTLICH = "POST_SCHLUESSEL_OEFFENTLICH"
ENV_PRIVAT = "POST_SCHLUESSEL_PRIVAT"
PREFIX_V2 = "v2:"          # Hybrid: RSA-OAEP um einen AES-256-GCM-Schluessel
MAX_LANG_BYTES = 4096     # laengste Klartexte fuer versiegeln_lang
MAX_ZEICHEN = 300  # Postfach-Passwoerter sind kurz; OAEP-3072 fasst ohnehin nur 318 Bytes


class TresorFehler(Exception):
    """Versiegeln/Oeffnen gescheitert. Die Meldung enthaelt nie Geheimnisse."""


class SchluesselFehlt(TresorFehler):
    """Der Schluessel ist in der Umgebung nicht gesetzt (Betreiber-Aufgabe)."""


def _oaep() -> padding.OAEP:
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    )


def _pem(pem: str | None, env_name: str, was: str) -> bytes:
    """PEM-Bytes: aus dem Argument (Klartext-PEM) oder base64 aus der Umgebung."""
    if pem:
        return pem.encode("utf-8")
    roh = (os.environ.get(env_name) or "").strip()
    if not roh:
        raise SchluesselFehlt(f"{was} fehlt ({env_name} nicht gesetzt)")
    try:
        return base64.b64decode(roh, validate=True)
    except ValueError:
        raise TresorFehler(f"{was} ist nicht lesbar (kein base64)") from None


def versiegeln(klartext: str, oeffentlich_pem: str | None = None,
               env_name: str = ENV_OEFFENTLICH) -> str:
    daten = klartext.encode("utf-8")
    if len(klartext) > MAX_ZEICHEN or len(daten) > 318:
        raise TresorFehler(f"Passwort zu lang (hoechstens {MAX_ZEICHEN} Zeichen)")
    try:
        schluessel = serialization.load_pem_public_key(
            _pem(oeffentlich_pem, env_name, "oeffentlicher Schluessel")
        )
        return base64.b64encode(schluessel.encrypt(daten, _oaep())).decode("ascii")
    except TresorFehler:
        raise
    except Exception:
        raise TresorFehler("Versiegeln fehlgeschlagen (Schluessel unbrauchbar)") from None


def versiegeln_lang(klartext: str, oeffentlich_pem: str | None = None,
                    env_name: str = ENV_OEFFENTLICH) -> str:
    """Wie `versiegeln`, aber fuer lange Geheimnisse (bis MAX_LANG_BYTES, z. B.
    Refresh-Token): ein zufaelliger AES-256-GCM-Schluessel verschluesselt den
    Klartext, RSA-OAEP verpackt den Schluessel.
    Format: "v2:" + b64(verpackter Schluessel) + "." + b64(Nonce(12) + Chiffre).
    `oeffnen` erkennt das Praefix; das alte Format bleibt unveraendert."""
    daten = klartext.encode("utf-8")
    if len(daten) > MAX_LANG_BYTES:
        raise TresorFehler(f"Geheimnis zu lang (hoechstens {MAX_LANG_BYTES} Bytes)")
    try:
        schluessel = serialization.load_pem_public_key(
            _pem(oeffentlich_pem, env_name, "oeffentlicher Schluessel")
        )
        aes = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        chiffre = AESGCM(aes).encrypt(nonce, daten, None)
        verpackt = schluessel.encrypt(aes, _oaep())
    except TresorFehler:
        raise
    except Exception:
        raise TresorFehler("Versiegeln fehlgeschlagen (Schluessel unbrauchbar)") from None
    return (PREFIX_V2 + base64.b64encode(verpackt).decode("ascii") + "."
            + base64.b64encode(nonce + chiffre).decode("ascii"))


def _oeffnen_v2(versiegelt: str, privat_pem: str | None, env_name: str) -> str:
    try:
        schluessel = serialization.load_pem_private_key(
            _pem(privat_pem, env_name, "privater Schluessel"), password=None
        )
        verpackt, rest = versiegelt[len(PREFIX_V2):].split(".", 1)
        aes = schluessel.decrypt(base64.b64decode(verpackt, validate=True), _oaep())
        roh = base64.b64decode(rest, validate=True)
        return AESGCM(aes).decrypt(roh[:12], roh[12:], None).decode("utf-8")
    except TresorFehler:
        raise
    except Exception:
        raise TresorFehler("Oeffnen fehlgeschlagen (Schluessel passt nicht oder Daten defekt)") from None


def oeffnen(versiegelt: str, privat_pem: str | None = None,
            env_name: str = ENV_PRIVAT) -> str:
    if versiegelt.startswith(PREFIX_V2):
        return _oeffnen_v2(versiegelt, privat_pem, env_name)
    try:
        schluessel = serialization.load_pem_private_key(
            _pem(privat_pem, env_name, "privater Schluessel"), password=None
        )
        roh = base64.b64decode(versiegelt, validate=True)
        return schluessel.decrypt(roh, _oaep()).decode("utf-8")
    except TresorFehler:
        raise
    except Exception:
        raise TresorFehler("Oeffnen fehlgeschlagen (Schluessel passt nicht oder Daten defekt)") from None
