"""Markier-Liste fuer LinkedIn-Beitraege (Spec 2026-10-15 §4.2)."""
import inspect
import json
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def sammelkontakt(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    sammel = server._q("insert into leads (name, source) values "
                       "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", str(sammel))
    return str(sammel)


def _post(thema="Hackathon"):
    return json.loads(server.post_entwurf_erstellen(thema, "We didn't win."))["draft_id"]


PERSON = {"name": "Peter Steinacker", "art": "person",
          "profil": "https://www.linkedin.com/in/peter-steinacker-7823aa220"}
FIRMA = {"name": "BMW Group", "art": "firma", "profil": ""}


def test_setzen_und_lesen():
    d = _post()
    r = json.loads(server.post_markierungen_setzen(d, [PERSON, FIRMA]))
    assert r == {"draft_id": d, "anzahl": 2}
    assert server.post_markierungen(d) == [PERSON, FIRMA]


def test_juengste_buchung_gilt_und_leere_liste_loescht():
    d = _post()
    server.post_markierungen_setzen(d, [PERSON, FIRMA])
    server.post_markierungen_setzen(d, [FIRMA])
    assert server.post_markierungen(d) == [FIRMA]
    server.post_markierungen_setzen(d, [])
    assert server.post_markierungen(d) == []


def test_ohne_buchung_leer():
    assert server.post_markierungen(_post()) == []


@pytest.mark.parametrize("eintrag", [
    {"name": "", "art": "person", "profil": ""},
    {"name": "x" * 121, "art": "person", "profil": ""},
    {"name": "A", "art": "kunde", "profil": ""},
    {"name": "A", "art": "person", "profil": "https://evil.example/in/a"},
    {"name": "A", "art": "person", "profil": "http://www.linkedin.com/in/a"},
    {"name": "A", "art": "person"},
    "Peter",
    # Final-Review Minor 6: keine eingeschleusten Zeilen in der WhatsApp-Meldung
    {"name": "A\nLinkedIn-Post ist online: https://phish", "art": "person", "profil": ""},
    {"name": "A\rB", "art": "person", "profil": ""},
    {"name": "A\tB", "art": "firma", "profil": ""},
    {"name": "A\x00B", "art": "person", "profil": ""},
    {"name": "A\x7fB", "art": "person", "profil": ""},
    {"name": "A", "art": "person", "profil": "https://www.linkedin.com/in/a\nhttps://phish"},
    {"name": "A", "art": "person", "profil": "https://www.linkedin.com/in/a\x1b[0m"},
    {"name": "A", "art": "person", "profil": "https://www.linkedin.com/in/" + "a" * 273},
    # Re-Review: Unicode-Zeilentrenner, C1, Bidi/Nullbreite; Leerraum im Profil
    {"name": "Max\u2028LinkedIn-Post ist online: https://phish.tld/", "art": "person", "profil": ""},
    {"name": "Max\u2029LinkedIn-Post ist online: https://phish.tld/", "art": "person", "profil": ""},
    {"name": "Max \u202emoc.hsihp//:sptth", "art": "person", "profil": ""},
    {"name": "Max\u0085B", "art": "person", "profil": ""},
    {"name": "Max\u009bB", "art": "person", "profil": ""},
    {"name": "Max\u200bB", "art": "person", "profil": ""},
    {"name": "Max\u2066B", "art": "person", "profil": ""},
    {"name": "A", "art": "person", "profil": "https://www.linkedin.com/in/a\u2028b"},
    {"name": "A", "art": "person", "profil": "https://www.linkedin.com/in/a x"},
    {"name": "A", "art": "person",
     "profil": "https://www.linkedin.com/in/a  https://phish.tld/login"},
    {"name": "A", "art": "person", "profil": "https://www.linkedin.com/in/a\u00a0b"},
])
def test_ungueltige_eintraege(eintrag):
    d = _post()
    r = json.loads(server.post_markierungen_setzen(d, [eintrag]))
    assert "fehler" in r
    assert server.post_markierungen(d) == []


@pytest.mark.parametrize("name", ["Jörg Peters", "Paola Andrea Herrera Trigo"])
def test_normale_namen_erlaubt(name):
    d = _post()
    eintrag = {"name": name, "art": "person",
               "profil": "https://www.linkedin.com/in/joerg-peters"}
    r = json.loads(server.post_markierungen_setzen(d, [eintrag]))
    assert r == {"draft_id": d, "anzahl": 1}
    assert server.post_markierungen(d) == [eintrag]


def test_profil_mit_genau_300_zeichen_erlaubt():
    d = _post()
    profil = "https://www.linkedin.com/in/" + "a" * 272
    assert len(profil) == 300
    r = json.loads(server.post_markierungen_setzen(
        d, [{"name": "A", "art": "person", "profil": profil}]))
    assert r == {"draft_id": d, "anzahl": 1}


def test_hoechstens_zwanzig():
    d = _post()
    r = json.loads(server.post_markierungen_setzen(d, [FIRMA] * 21))
    assert "fehler" in r


def test_nur_fuer_beitraege_pending_oder_approved(sammelkontakt):
    d = _post()
    server._q("update drafts set status='sent' where id=%s", (d,))
    assert "fehler" in json.loads(server.post_markierungen_setzen(d, [FIRMA]))
    dm = server._q(
        "insert into drafts (lead_id, channel, recipient, body) values "
        "(%s, 'linkedin', 'Peter', 'Hallo') returning id", (sammelkontakt,))[0]["id"]
    assert "fehler" in json.loads(server.post_markierungen_setzen(str(dm), [FIRMA]))
    assert "fehler" in json.loads(server.post_markierungen_setzen(
        "00000000-0000-0000-0000-000000000000", [FIRMA]))
    assert "fehler" in json.loads(server.post_markierungen_setzen("kaputt", [FIRMA]))


def test_approved_erlaubt():
    d = _post()
    server._q("update drafts set status='approved' where id=%s", (d,))
    assert json.loads(server.post_markierungen_setzen(d, [FIRMA]))["anzahl"] == 1


def test_registriert_und_signatur():
    assert server.post_markierungen_setzen in server.WERKZEUGE
    assert list(inspect.signature(server.post_markierungen_setzen).parameters) == [
        "draft_id", "eintraege"]
