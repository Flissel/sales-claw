"""Vertragstests: der Antwort-Kontext liegt dem Bot bei (03.09.2026).

Betreiber: „die Entwuerfe koennten besser sein — koennen wir die letzten 10
Nachrichten dafuer als Kontext injizieren?" Gemessen: `chat_verlauf` liefert
aufsteigend mit Limit, bei langen Chats also die AELTESTEN Nachrichten, und
der Aufruf war fuer den Bot optional. Seitdem traegt jeder Eintrag von
`antworten_faellig` seinen `verlauf`: die letzten 10 Nachrichten beider
Richtungen, aelteste zuerst, Sprachnachrichten als Text, lange Texte gekuerzt.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _wartender(name="Wanda Wartend", phone="+491702223344"):
    lead = str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, %s, 'whatsapp') returning id", (name, phone))[0]["id"])
    server.kontakt_freigeben(lead)
    server.kontakt_autonomie_setzen(lead, "halbauto")
    return lead


def _nachricht(lead, typ, payload, vor_minuten):
    server._q(
        "insert into activities (lead_id, type, payload, actor, created_at) "
        "values (%s, %s, %s::jsonb, 'agent', now() - (%s || ' minutes')::interval) "
        "returning id", (lead, typ, json.dumps(payload), str(vor_minuten)))


def _gespraech(lead):
    """14 Zeilen in Zeitreihenfolge: N1..N10 abwechselnd, dann eine
    Sprachnachricht mit Transkription, dann N11 (ausgehend), N12 (eingehend)."""
    minute = 140
    for i in range(1, 11):
        typ = "kundenantwort" if i % 2 else "nachricht_ausgehend"
        _nachricht(lead, typ, {"text": f"N{i}"}, minute)
        minute -= 10
    _nachricht(lead, "kundenantwort",
               {"text": "", "audio_datei": "abc.ogg", "message_id": "m-v"}, 40)
    _nachricht(lead, "transkription",
               {"message_id": "m-v", "text": "Gesprochen: bitte Freitag"}, 39)
    _nachricht(lead, "nachricht_ausgehend", {"text": "N11"}, 30)
    _nachricht(lead, "kundenantwort", {"text": "N12"}, 20)


def test_jeder_faellige_eintrag_traegt_die_letzten_zehn_nachrichten():
    lead = _wartender()
    _gespraech(lead)
    daten = json.loads(server.antworten_faellig())
    assert daten["anzahl"] == 1
    assert daten["verlauf_limit"] == 10
    eintrag = daten["eintraege"][0]
    verlauf = eintrag["verlauf"]
    assert len(verlauf) == 10
    # Aelteste zuerst, die juengste Nachricht ganz unten — so liest man einen Chat.
    assert verlauf[0]["text"] == "N5"
    assert verlauf[-1]["text"] == "N12"
    assert verlauf[-1]["richtung"] == "eingehend"
    assert verlauf[-2]["text"] == "N11"
    assert verlauf[-2]["richtung"] == "ausgehend"
    assert all(v["richtung"] in ("eingehend", "ausgehend") and v["wann"]
               for v in verlauf)
    # Die Sprachnachricht steht als Text drin, nicht als Luecke.
    gesprochen = [v for v in verlauf if v.get("art") == "sprachnachricht"]
    assert gesprochen and gesprochen[0]["text"] == "Gesprochen: bitte Freitag"
    assert gesprochen[0]["richtung"] == "eingehend"
    assert "Sprachnachricht" in verlauf[-4]["text"]     # die stumme Zeile davor
    # Der Hinweis fuehrt zum mitgelieferten Verlauf, nicht mehr zuerst zu
    # chat_verlauf.
    assert "verlauf" in daten["hinweis"]


def test_lange_texte_werden_gekuerzt_und_kurze_chats_ganz_geliefert():
    lead = _wartender()
    _nachricht(lead, "nachricht_ausgehend", {"text": "x" * 900}, 30)
    _nachricht(lead, "kundenantwort", {"text": "kurz"}, 20)
    daten = json.loads(server.antworten_faellig())
    verlauf = daten["eintraege"][0]["verlauf"]
    assert len(verlauf) == 2
    assert verlauf[0]["text"].endswith("…")
    assert len(verlauf[0]["text"]) == server.ANTWORT_TEXT_MAX + 1
    assert verlauf[1]["text"] == "kurz"


def test_chat_verlauf_bleibt_wie_er_ist():
    """Der Report-Ablauf (aelteste zuerst, Grenze wandert mit) haengt an
    chat_verlauf — der Antwort-Kontext ist ein eigener Weg daneben."""
    lead = _wartender()
    _gespraech(lead)
    alt = json.loads(server.chat_verlauf(lead, limit=3))
    assert [n["text"] for n in alt["nachrichten"]] == ["N1", "N2", "N3"]
