"""Entwuerfe im Freigabe-Eingang (Plan 2026-11-08, Task 11): drafts -> freigabe_eintraege."""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402

import freigabe_bote as fb  # noqa: E402
import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402

BASIS = "https://s"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.freigabe_eintraege cascade")
        conn.execute("delete from sales_test.drafts where body like 'GEHEIMER TEXT%'")
        conn.execute("delete from sales_test.leads where source = 'entwuerfe-test'")


@pytest.fixture(autouse=True)
def leer():
    _aufraeumen()
    yield
    _aufraeumen()


def lead(name="Anna Beispiel", company="Beispiel GmbH"):
    return str(server._q("insert into leads (name, company, source) values (%s,%s,'entwuerfe-test') "
                         "returning id", (name, company))[0]["id"])


def draft(lead_id, kanal="email", betreff="Unser Angebot", status="pending", thema=None):
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, subject, thema, body, body_html, status) "
        "values (%s,%s,'anna@example.org',%s,%s,'GEHEIMER TEXT',"
        "'<p>GEHEIMER TEXT</p>',%s) returning id",
        (lead_id, kanal, betreff, thema, status))[0]["id"])


def eintraege():
    return server._q("select * from freigabe_eintraege order by erstellt_am")


def test_pending_entwurf_wird_eintrag():
    d = draft(lead())
    assert fe.entwuerfe_spiegeln(BASIS) == 1
    (e,) = eintraege()
    assert e["art"] == "entwurf" and e["herkunft"] == "sales"
    assert e["quelle_ref"] == d and str(e["draft_id"]) == d and e["status"] == "offen"
    assert e["link"] == f"{BASIS}/freigaben"
    assert "email" in e["titel"].lower() and "Anna Beispiel" in e["titel"]
    assert "Unser Angebot" in e["titel"]
    alles = str(e["titel"]) + str(e["details"]) + str(e["link"])
    assert "GEHEIMER TEXT" not in alles and "anna@example.org" not in alles


def test_gesendet_schliesst():
    d = draft(lead())
    fe.entwuerfe_spiegeln(BASIS)
    server._q("update drafts set status = 'sent' where id = %s returning id", (d,))
    fe.entwuerfe_spiegeln(BASIS)
    (e,) = eintraege()
    assert e["status"] == "ausgefuehrt" and e["geschlossen_am"] is not None


def test_verworfen_schliesst():
    d = draft(lead())
    fe.entwuerfe_spiegeln(BASIS)
    server._q("update drafts set status = 'rejected' where id = %s returning id", (d,))
    fe.entwuerfe_spiegeln(BASIS)
    (e,) = eintraege()
    assert e["status"] == "verworfen"


def test_zweimal_ein_eintrag():
    draft(lead())
    assert fe.entwuerfe_spiegeln(BASIS) == 1
    assert fe.entwuerfe_spiegeln(BASIS) == 0
    assert len(eintraege()) == 1


def test_ohne_lead_titel_ohne_namen():
    draft(None, kanal="linkedin", betreff="Post: Neuigkeiten")
    fe.entwuerfe_spiegeln(BASIS)
    (e,) = eintraege()
    assert " an " not in e["titel"]
    assert e["titel"].lower().startswith("linkedin: ")
    assert "Post: Neuigkeiten" in e["titel"]


def test_thema_statt_betreff():
    draft(lead(), betreff=None, thema="Sommerfest")
    fe.entwuerfe_spiegeln(BASIS)
    assert "Sommerfest" in eintraege()[0]["titel"]


def test_firma_wenn_kein_name():
    draft(lead(name="", company="Muster AG"))
    fe.entwuerfe_spiegeln(BASIS)
    assert "Muster AG" in eintraege()[0]["titel"]


def test_kein_at_im_titel():
    draft(lead(name="Max @rowboat"), betreff="Hi @agent, bitte")
    fe.entwuerfe_spiegeln(BASIS)
    assert "@" not in eintraege()[0]["titel"]


def test_nicht_pending_wird_nicht_gespiegelt():
    draft(lead(), status="approved")
    draft(lead(), status="sent")
    assert fe.entwuerfe_spiegeln(BASIS) == 0
    assert eintraege() == []


def test_geschlossener_eintrag_kommt_nicht_wieder():
    d = draft(lead())
    fe.entwuerfe_spiegeln(BASIS)
    server._q("update freigabe_eintraege set status = 'verworfen' where draft_id = %s "
              "returning id", (d,))
    assert fe.entwuerfe_spiegeln(BASIS) == 0


def test_durchgang_spiegelt_zuerst_und_ueberlebt_fehler(monkeypatch):
    monkeypatch.setenv("UI_BASIS_URL", BASIS)
    gesehen = []
    monkeypatch.setattr(fb, "_stand_lesen",
                        lambda: gesehen.append("rowboat") or fb.RowboatStand())
    monkeypatch.setattr(fb, "_rpc", lambda kanal, body: {"added": []})

    def kaputt(basis):
        gesehen.append(("spiegeln", basis))
        raise RuntimeError("geheim")
    monkeypatch.setattr(fe, "entwuerfe_spiegeln", kaputt)
    assert fb.durchgang() == 0
    assert gesehen == [("spiegeln", BASIS), "rowboat"]
