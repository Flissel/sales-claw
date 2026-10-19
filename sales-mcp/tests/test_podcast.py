"""Podcast-Seite im Marketing-Pult (19.10.2026). Der Client zur Marketing-API wird gefaelscht."""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


# --- Stand: Freigabe-Stand zu Mediendateien ----------------------------------

def _db():
    try:
        server._q("select 1")
    except Exception:
        pytest.skip("Test-DB aus")


@pytest.fixture(autouse=True)
def aufraeumen():
    yield
    try:
        server._q("delete from drafts where lead_id in (select id from leads where phone = '+491701230000')")
        server._q("delete from leads where phone = '+491701230000'")
    except Exception:
        pass


def _entwurf_mit_medien(status, media_ref):
    lead = server._q("insert into leads (name, phone, source) values ('Pod', '+491701230000', 'whatsapp') "
                     "returning id")[0]["id"]
    server._q("insert into drafts (lead_id, channel, recipient, body, status, media_ref) "
              "values (%s, 'linkedin', 'eigenes-profil', 'x', %s, %s)", (lead, status, media_ref))


def test_stand_weitester_gewinnt():
    _db()
    name = "pod-aaaaaaaa-weitester.mp3"
    _entwurf_mit_medien("rejected", name)
    _entwurf_mit_medien("approved", name)
    assert server.entwurf_staende_zu_medien([name]) == {name: "approved"}


def test_stand_exakter_name():
    _db()
    name = "pod-aaaaaaaa-x.mp3"
    _entwurf_mit_medien("sent", "pod-aaaaaaaa-x.mp3.bak")
    _entwurf_mit_medien("sent", "xpod-aaaaaaaa-x.mp3")
    _entwurf_mit_medien("pending", f"andere.png, {name}")
    assert server.entwurf_staende_zu_medien([name]) == {name: "pending"}


def test_stand_leere_liste_ohne_abfrage(monkeypatch):
    def nie(*a, **k):
        raise AssertionError("keine Abfrage erwartet")
    monkeypatch.setattr(server, "_q", nie)
    assert server.entwurf_staende_zu_medien([]) == {}
