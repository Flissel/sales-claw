"""Neu-Auswertung einer gespeicherten Mitschrift (scripts/neu_auswerten.py).

Datenbank sales_test; keine Dienste. Ausgaben nur Zaehler.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import neu_auswertung  # noqa: E402
import server  # noqa: E402

UID = "3c9afada-1111-2222-3333-444455556666@sales-claw"
UID2 = "3c9afada-9999-2222-3333-444455556666@sales-claw"


def _s(sprecher, sek, text):
    return {"sprecher": sprecher, "beginn": f"2099-01-09T12:{sek // 60:02d}:{sek % 60:02d}Z",
            "text": text, "sprache": "de"}


ROH = [_s("?", 0, "Untertitel im Auftrag des ZDF, 2017"),
       _s("felix", 10, "Hallo zusammen"),
       _s("felix", 12, "wir fangen an"),
       _s("Diana", 40, "ok")]


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    monkeypatch.delenv("BETREIBER_NAME", raising=False)
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.drafts, "
                     "sales_test.leads cascade")
    yield


def _akte(uid):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', now(), now() + interval '1 hour', 't', 'fertig') "
              "returning uid", (uid,))


def _mitschrift(uid=UID, entwurf=None, status="fertig"):
    _akte(uid)
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_md, auswertung_am, auswertung_versuche, entwurf_id) "
              "values (%s, %s::jsonb, %s, '{\"x\": 1}'::jsonb, 'alt', now(), 2, %s) returning id",
              (uid, json.dumps(ROH), status, entwurf))


def _entwurf(status):
    return str(server._q("insert into drafts (channel, recipient, body, status) "
                         "values ('email', 'k@example.test', 'b', %s) returning id",
                         (status,))[0]["id"])


def _mit(uid=UID):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def test_setzt_zurueck_und_bereinigt():
    _mitschrift()
    st = neu_auswertung.neu_auswerten(UID)
    m = _mit()
    assert m["auswertung_status"] == "offen"
    assert m["auswertung_versuche"] == 0
    assert m["auswertung_json"] is None and m["auswertung_md"] is None
    assert m["auswertung_am"] is None
    assert [s["text"] for s in m["segmente"]] == ["Hallo zusammen wir fangen an", "ok"]
    assert m["segmente"][0]["sprecher"] == "Felix Baumann"
    assert st["segmente_vorher"] == 4 and st["segmente_nachher"] == 2
    assert st["fragezeichen_vorher"] == 0.25 and st["fragezeichen_nachher"] == 0.0
    assert st["kurz_vorher"] == 0.5 and st["kurz_nachher"] == 0.5


def test_statistik_ohne_inhalte():
    _mitschrift()
    st = neu_auswertung.neu_auswerten(UID)
    assert all(isinstance(v, (int, float)) for v in st.values())


def test_eindeutiger_praefix_genuegt():
    _mitschrift()
    neu_auswertung.neu_auswerten(UID[:8])
    assert _mit()["auswertung_status"] == "offen"


def test_praefix_mehrdeutig_bricht_ab():
    _mitschrift(UID)
    _mitschrift(UID2)
    with pytest.raises(neu_auswertung.NeuAuswertenFehler):
        neu_auswertung.neu_auswerten(UID[:8])
    assert _mit(UID)["auswertung_status"] == "fertig"
    assert _mit(UID2)["auswertung_status"] == "fertig"


def test_zu_kurzer_praefix_und_unbekannt():
    _mitschrift()
    with pytest.raises(neu_auswertung.NeuAuswertenFehler):
        neu_auswertung.neu_auswerten("3c9afa")
    with pytest.raises(neu_auswertung.NeuAuswertenFehler):
        neu_auswertung.neu_auswerten("ffffffff-0000")
    assert _mit()["auswertung_status"] == "fertig"


@pytest.mark.parametrize("status", ["sent", "approved"])
def test_verschickter_entwurf_bricht_ab(status):
    _mitschrift(entwurf=_entwurf(status))
    with pytest.raises(neu_auswertung.NeuAuswertenFehler):
        neu_auswertung.neu_auswerten(UID)
    m = _mit()
    assert m["auswertung_status"] == "fertig" and m["auswertung_md"] == "alt"
    assert len(m["segmente"]) == 4


def test_offener_entwurf_erlaubt():
    _mitschrift(entwurf=_entwurf("pending"))
    neu_auswertung.neu_auswerten(UID)
    assert _mit()["auswertung_status"] == "offen"


def test_entwurf_nicht_auffindbar_bricht_ab():
    _mitschrift(entwurf="00000000-0000-0000-0000-000000000001")
    with pytest.raises(neu_auswertung.NeuAuswertenFehler):
        neu_auswertung.neu_auswerten(UID)
    assert _mit()["auswertung_status"] == "fertig"
