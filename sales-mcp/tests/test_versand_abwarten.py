"""Vertraege fuer `versand_abwarten` (Sales-Agent Block A, Task 5, 13.10.2026):
nach einer Freigabe warten, bis der Versanddienst den Entwurf verschickt hat.
Versendet selbst nichts."""
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


def _draft(status="approved", channel="whatsapp", error=None):
    lead = server._q(
        "insert into leads (name, phone) values ('Abwarten Test', '+490000099001') "
        "returning id")[0]["id"]
    empf = "abwarten@example.org" if channel == "email" else "+490000099001"
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, subject, body, status, error) "
        "values (%s, %s, %s, 'Betreff', 'Text', %s, %s) returning id",
        (lead, channel, empf, status, error))[0]["id"])


def test_sofort_sent():
    d = _draft(status="sent")
    assert json.loads(server.versand_abwarten(d))["ergebnis"] == "sent"


def test_failed_mit_grund():
    d = _draft(status="failed", error="SMTP 550")
    a = json.loads(server.versand_abwarten(d))
    assert a["ergebnis"] == "failed" and "550" in a["fehler"]


def test_pending_sofort(monkeypatch):
    d = _draft(status="pending")
    schlaefe = []
    monkeypatch.setattr(server, "_SCHLAF", schlaefe.append)
    assert json.loads(server.versand_abwarten(d))["ergebnis"] == "nicht_freigegeben" and schlaefe == []


def test_wartet_bis_frist(monkeypatch):
    d = _draft(status="approved", channel="whatsapp")
    t = [0.0]
    monkeypatch.setattr(server, "_UHR", lambda: t[0])
    monkeypatch.setattr(server, "_SCHLAF", lambda s: t.__setitem__(0, t[0] + s))
    assert json.loads(server.versand_abwarten(d, max_s=10))["ergebnis"] == "wartet"


def test_wird_waehrend_des_wartens_sent(monkeypatch):
    d = _draft(status="approved", channel="whatsapp")

    def schlaf(s):
        server._q("update drafts set status = 'sent' where id = %s returning id", (d,))
    monkeypatch.setattr(server, "_SCHLAF", schlaf)
    assert json.loads(server.versand_abwarten(d))["ergebnis"] == "sent"


def test_mail_ohne_kundenpostfach(monkeypatch):
    # mail_dispatch importiert server -> in server.py nur lazy importierbar;
    # der Test patcht darum das Modul selbst.
    import mail_dispatch
    d = _draft(status="approved", channel="email")
    monkeypatch.setattr(mail_dispatch, "kunden_identitaet",
                        lambda: type("I", (), {"brauchbar": lambda self: False})())
    a = json.loads(server.versand_abwarten(d))
    assert a["ergebnis"] == "wartet" and "bleibt liegen, bis das Postfach eingetragen ist" in a["hinweis"]


def test_vorgabe_30_sekunden():
    import inspect
    assert inspect.signature(server.versand_abwarten).parameters["max_s"].default == 30


def test_claim_marke_ist_noch_unterwegs(monkeypatch):
    # Final-Review I1: der Dispatcher setzt beim Claim status='failed' mit
    # error='in Zustellung seit …', waehrend er noch zustellt.
    import dispatch
    d = _draft(status="failed", error=dispatch.CLAIM_PRAEFIX + "2026-10-13T22:07:00Z (dispatcher a32f55d2)")

    def schlaf(s):
        server._q("update drafts set status = 'sent', error = null where id = %s returning id", (d,))
    monkeypatch.setattr(server, "_SCHLAF", schlaf)
    assert json.loads(server.versand_abwarten(d))["ergebnis"] == "sent"


def test_claim_marke_bis_frist_wartet(monkeypatch):
    import dispatch
    d = _draft(status="failed", error=dispatch.CLAIM_PRAEFIX + "2026-10-13T22:07:00Z (dispatcher a32f55d2)")
    t = [0.0]
    monkeypatch.setattr(server, "_UHR", lambda: t[0])
    monkeypatch.setattr(server, "_SCHLAF", lambda s: t.__setitem__(0, t[0] + s))
    a = json.loads(server.versand_abwarten(d, max_s=10))
    assert a["ergebnis"] == "wartet" and "Warteschlange" in a["hinweis"]
    assert "in Zustellung" in a["hinweis"]
