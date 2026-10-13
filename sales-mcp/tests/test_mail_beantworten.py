"""Vertragstests: mail_beantworten (Sales-Agent Block A, Task 3).

Antwort auf eine Postfach-Mail wird ein E-Mail-Entwurf (pending) im selben
Mailverlauf. Kontakt wird ueber die Absenderadresse gefunden oder angelegt,
die Eingangsmail einmal als 'kundenantwort' gebucht. Versendet wird nichts.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


MAIL = {"uid": "7", "von": "Leo W <Leo.W@Example.com>", "an": "ich@vibemind.space", "betreff": "Kurze Frage",
        "datum": "Tue, 13 Oct 2026 07:00:00 +0200", "text": "Hallo, ...", "message_id": "m-7@example.com"}


def _postfach(monkeypatch, mail):
    monkeypatch.setattr(server.postfach, "konfiguriert", lambda: True)
    monkeypatch.setattr(server.postfach, "lesen", lambda uid: mail if mail and uid == mail["uid"] else None)


def test_neuer_kontakt_entwurf_im_verlauf(monkeypatch):
    _postfach(monkeypatch, MAIL)
    a = json.loads(server.mail_beantworten("7", "Hallo Leo, danke!"))
    assert a["status"] == "pending" and a["neuer_kontakt"] is True and a["betreff"] == "Re: Kurze Frage"
    d = server._q("select channel, recipient, subject, antwort_auf, status from drafts where id = %s", (a["draft_id"],))[0]
    assert (d["channel"], d["recipient"], d["antwort_auf"], d["status"]) == ("email", "leo.w@example.com", "m-7@example.com", "pending")
    l = server._q("select source, consent_status from leads where id = %s", (a["lead_id"],))[0]
    assert l["source"] == "email"
    assert server._hat_selbst_geschrieben(a["lead_id"])


def test_vorhandener_kontakt_kein_duplikat(monkeypatch):
    lead = str(server._q("insert into leads (name, email, source) values ('Leo', 'leo.w@example.com', 'email') returning id")[0]["id"])
    _postfach(monkeypatch, MAIL)
    a = json.loads(server.mail_beantworten("7", "Hallo"))
    assert a["lead_id"] == lead and a["neuer_kontakt"] is False
    assert server._q("select count(*) n from leads")[0]["n"] == 1


def test_eingang_einmal_gebucht(monkeypatch):
    _postfach(monkeypatch, MAIL)
    a = json.loads(server.mail_beantworten("7", "Eins"))
    server._q("update drafts set status = 'rejected' where id = %s returning id", (a["draft_id"],))
    json.loads(server.mail_beantworten("7", "Zwei"))
    n = server._q("select count(*) n from activities where type = 'kundenantwort' and payload->>'message_id' = 'm-7@example.com'")[0]["n"]
    assert n == 1


@pytest.mark.parametrize("betreff,erwartet", [("Re: Thema", "Re: Thema"), ("AW: Thema", "AW: Thema"),
                                              ("RE: Re: Thema", "RE: Re: Thema"), ("Thema", "Re: Thema"), ("", "Re: (ohne Betreff)")])
def test_betreff(monkeypatch, betreff, erwartet):
    _postfach(monkeypatch, {**MAIL, "betreff": betreff})
    assert json.loads(server.mail_beantworten("7", "x"))["betreff"] == erwartet


def test_ohne_message_id(monkeypatch):
    _postfach(monkeypatch, {**MAIL, "message_id": ""})
    a = json.loads(server.mail_beantworten("7", "x"))
    assert server._q("select antwort_auf from drafts where id = %s", (a["draft_id"],))[0]["antwort_auf"] is None


def test_mail_weg(monkeypatch):
    _postfach(monkeypatch, None)
    assert json.loads(server.mail_beantworten("9", "x"))["fehler"].startswith("Mail nicht mehr im Postfach")


@pytest.mark.parametrize("von", ["noreply@shop.de", "No-Reply <no-reply@x.org>", "MAILER-DAEMON@mx.de"])
def test_noreply_rueckfrage(monkeypatch, von):
    _postfach(monkeypatch, {**MAIL, "von": von})
    a = json.loads(server.mail_beantworten("7", "x"))
    assert "frage" in a and server._q("select count(*) n from drafts")[0]["n"] == 0


def test_registriert():
    assert server.mail_beantworten in server.WERKZEUGE
