"""KI-Einordnung der Mitschriften in Rubriken (Mitschriften-Ablage, Task 3).

Datenbank sales_test; ollama.chat wird ersetzt.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import mitschrift_einordnung as me  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402

UID = "einordnung-0001@sales-claw"
BEGINN = datetime(2026, 11, 14, 9, 5, tzinfo=timezone.utc)
TITEL = "Geheimtitel Zebra"
AJ = {"art": "kundentermin", "kurzfassung": "Kurzfassung Quokka",
      "beteiligte": ["Diana", "Felix"]}


@pytest.fixture(autouse=True)
def sauber():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield


def _mitschrift(uid=UID, rubrik=None, manuell=False, titel=TITEL):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, %s, 'fertig') returning uid",
              (uid, BEGINN, BEGINN + timedelta(hours=1), titel))
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_am, rubrik, rubrik_manuell) "
              "values (%s, '[]'::jsonb, 'fertig', %s::jsonb, now(), %s, %s) returning id",
              (uid, json.dumps(AJ), rubrik, manuell))


def _mit(uid=UID):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def _ki(monkeypatch, *antworten):
    aufrufe = []
    folge = list(antworten)

    def chat(system, nutzer, **kw):
        aufrufe.append((system, nutzer, kw))
        a = folge.pop(0) if len(folge) > 1 else folge[0]
        if isinstance(a, Exception):
            raise a
        return a if isinstance(a, str) else json.dumps(a)

    monkeypatch.setattr(ollama, "chat", chat)
    return aufrufe


EIN = {"titel": "T", "kurzfassung": "K", "beteiligte": ["A"], "art": "intern"}


def test_waehlt_vorhandene_bei_gleichem_namen(monkeypatch):
    _ki(monkeypatch, {"rubrik": "kurse", "neu": False})
    assert me.rubrik_waehlen(EIN, [("Kurse", 2)]) == "Kurse"


def test_neue_rubrik(monkeypatch):
    _ki(monkeypatch, {"rubrik": "Interne Besprechungen", "neu": True})
    assert me.rubrik_waehlen(EIN, [("Kurse", 2)]) == "Interne Besprechungen"


def test_grenze_erreicht_erzwingt_vorhandene(monkeypatch):
    vorh = [(f"Rubrik {i}", 1) for i in range(12)]
    aufrufe = _ki(monkeypatch, {"rubrik": "Ganz Neu", "neu": True},
                  {"rubrik": "rubrik 3", "neu": False})
    assert me.rubrik_waehlen(EIN, vorh) == "Rubrik 3"
    assert len(aufrufe) == 2
    assert "wähle eine vorhandene" in aufrufe[1][1].lower() or \
        "wähle eine vorhandene" in aufrufe[1][0].lower()


def test_grenze_zweite_antwort_unbrauchbar(monkeypatch):
    vorh = [(f"Rubrik {i}", 1) for i in range(12)]
    _ki(monkeypatch, {"rubrik": "Ganz Neu", "neu": True})
    with pytest.raises(ValueError):
        me.rubrik_waehlen(EIN, vorh)


def test_unsortiert_zaehlt_nicht():
    for i in range(12):
        _mitschrift(uid=f"einordnung-r{i}@sales-claw", rubrik=f"Rubrik {i}")
    _mitschrift(uid="einordnung-u@sales-claw", rubrik="Unsortiert")
    _mitschrift(uid="einordnung-n@sales-claw", rubrik=None)
    v = me.vorhandene_rubriken()
    assert len(v) == 12
    assert "Unsortiert" not in [n for n, _ in v]


def test_vorhandene_sortierung():
    _mitschrift(uid="e-1@sales-claw", rubrik="Beta")
    _mitschrift(uid="e-2@sales-claw", rubrik="Beta")
    _mitschrift(uid="e-3@sales-claw", rubrik="Alpha")
    _mitschrift(uid="e-4@sales-claw", rubrik="Zeta")
    _mitschrift(uid="e-5@sales-claw", rubrik="Zeta")
    assert me.vorhandene_rubriken() == [("Beta", 2), ("Zeta", 2), ("Alpha", 1)]


def test_einordnen_erfolg(monkeypatch):
    _mitschrift()
    _ki(monkeypatch, {"rubrik": "Kundentermine", "neu": True})
    assert me.einordnen(UID) == "Kundentermine"
    m = _mit()
    assert m["rubrik"] == "Kundentermine"
    assert m["einordnung_versuche"] == 1 and m["einordnung_am"] is not None


def test_ki_fehler_setzt_unsortiert(monkeypatch):
    _mitschrift()
    _ki(monkeypatch, TimeoutError("zu langsam"))
    assert me.einordnen(UID) == "Unsortiert"
    m = _mit()
    assert m["rubrik"] == "Unsortiert" and m["einordnung_versuche"] == 1


@pytest.mark.parametrize("antwort", ["kein json", {"rubrik": ""}, {"rubrik": "../.."},
                                     {"rubrik": "unsortiert"}, ["liste"]])
def test_unbrauchbare_antwort(monkeypatch, antwort):
    _mitschrift()
    _ki(monkeypatch, antwort)
    assert me.einordnen(UID) == "Unsortiert"
    assert _mit()["rubrik"] == "Unsortiert"


def test_manuelle_rubrik_bleibt(monkeypatch):
    _mitschrift(rubrik="Kurse", manuell=True)
    aufrufe = _ki(monkeypatch, {"rubrik": "Kundentermine", "neu": True})
    assert me.einordnen(UID) == "Kurse"
    assert _mit()["rubrik"] == "Kurse"
    assert aufrufe == []


def test_manuell_waehrend_ki_gesetzt(monkeypatch):
    _mitschrift()

    def chat(system, nutzer, **kw):
        server._q("update termin_mitschriften set rubrik='Kurse', rubrik_manuell=true "
                  "where uid=%s returning id", (UID,))
        return json.dumps({"rubrik": "Kundentermine", "neu": True})

    monkeypatch.setattr(ollama, "chat", chat)
    assert me.einordnen(UID) == "Kurse"
    assert _mit()["rubrik"] == "Kurse"


def test_prompt_inhalt(monkeypatch):
    _mitschrift()
    _mitschrift(uid="e-2@sales-claw", rubrik="Kurse")
    aufrufe = _ki(monkeypatch, {"rubrik": "Kurse", "neu": False})
    me.einordnen(UID)
    system, nutzer, kw = aufrufe[0]
    assert TITEL in nutzer and "Kurzfassung Quokka" in nutzer
    assert "Diana" in nutzer and "Felix" in nutzer and "kundentermin" in nutzer
    assert "Kurse (1)" in nutzer
    assert kw.get("als_json") is True and kw.get("timeout_s") == me.KI_TIMEOUT_S
    for s in ('{"rubrik": "...", "neu": true|false}', "vorhandene", "1–3 Wörter",
              "Mehrzahl", "deutsch", "Kurse", "Kundentermine", "Interne Besprechungen"):
        assert s.lower() in system.lower(), s


def test_prompt_kuerzt(monkeypatch):
    _mitschrift()
    server._q("update termin_mitschriften set auswertung_json=%s::jsonb where uid=%s "
              "returning id", (json.dumps({"art": "intern", "kurzfassung": "x" * 3000,
                                           "beteiligte": [f"P{i}" for i in range(20)]}), UID))
    aufrufe = _ki(monkeypatch, {"rubrik": "Kurse", "neu": True})
    me.einordnen(UID)
    nutzer = aufrufe[0][1]
    assert "x" * 1500 in nutzer and "x" * 1501 not in nutzer
    assert "P9" in nutzer and "P10" not in nutzer


def test_log_ohne_inhalt(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _mitschrift()
    _ki(monkeypatch, {"rubrik": "Geheimrubrik Yeti", "neu": True})
    me.einordnen(UID)
    _mitschrift(uid="e-2@sales-claw")
    _ki(monkeypatch, RuntimeError("Geheimtitel Zebra Geheimrubrik Yeti"))
    me.einordnen("e-2@sales-claw")
    text = caplog.text
    assert TITEL not in text and "Geheimrubrik" not in text and "Yeti" not in text
    assert UID not in text
