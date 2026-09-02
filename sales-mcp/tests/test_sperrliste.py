"""Verbotsliste (F1) auf der sales-Seite: Kennungen wie Marketing bilden,
vor der Erstansprache fragen, bei Widerruf/Loeschantrag sperren.

Ohne Datenbank: die Abfrage wird als Funktion hereingereicht und
aufgezeichnet. So beweist der Test WAS gefragt wird (compliance.sperrliste,
nur aktive Sperren) und dass Sperren ueber compliance.sperren laeuft.
"""
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import sperrliste as sl  # noqa: E402


def test_kennungen_wie_marketing():
    assert sl.kennung_email(" Max@Example.DE ") == "email:max@example.de"
    assert sl.kennung_tel("+49 (0)171 / 123-4567") == "tel:+491711234567"
    assert sl.kennung_tel("491711234567@c.us") == "tel:+491711234567"
    assert sl.kennung_tel("0171 1234567") == "tel:+491711234567"
    assert sl.kennungen(email="a@x.de", phone="") == ["email:a@x.de"]
    assert sl.kennungen(email="", phone="0171 1234567") == ["tel:+491711234567"]
    assert sl.kennungen(email="", phone="") == []


def test_gesperrt_fragt_nur_aktive_sperren():
    gesehen = []

    def q(sql, params=()):
        gesehen.append((sql, params))
        return [{"kennung": "tel:+491711234567", "quelle": "marketing:unsubscribe", "grund": "abgemeldet"}]

    grund = sl.gesperrt(q, email="", phone="0171 1234567")
    assert grund is not None and "marketing:unsubscribe" in grund
    sql, params = gesehen[0]
    assert "compliance.sperrliste" in sql
    assert "aufgehoben_am is null" in sql.lower()
    assert params == (["tel:+491711234567"],)


def test_gesperrt_ohne_kennung_fragt_nicht():
    def q(sql, params=()):
        raise AssertionError("darf nicht fragen")
    assert sl.gesperrt(q, email="", phone="") is None


def test_sperren_ruft_die_funktion_je_kennung():
    gesehen = []

    def q(sql, params=()):
        gesehen.append((sql, params))
        return []

    n = sl.sperren(q, email="a@x.de", phone="0171 1234567", quelle="sales:widerruf", grund="am Telefon")
    assert n == 2
    assert all("compliance.sperren" in s for s, _ in gesehen)
    assert gesehen[0][1] == ("email:a@x.de", "sales:widerruf", "am Telefon")
