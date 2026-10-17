"""Oberflaeche /empfehlungen (C4, Task 5)."""
import os
from datetime import date

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import empfehlungen as em  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
HOST = {"host": "127.0.0.1:8791"}


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.empfehlungslisten, sales_test.activities, "
                     "sales_test.drafts, sales_test.personas, sales_test.leads, "
                     "sales_test.benutzer cascade")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")


def _liste(**kw):
    a = dict(art="pole_position", empfohlen_von_name="Klaus <b>Kunde</b>",
             datum=date.today().isoformat(), berater_name="Felix", struktur="Nord",
             zeilen=[{"vorname": "Anna", "name": "Beispiel <script>x</script>",
                      "telefon": "+491701234567", "beruf": "Ärztin"}])
    a.update(kw)
    return em.liste_anlegen(**a)


def _get(p, client=CLIENT):
    return client.get(p, headers=HOST)


def _post(p, d, client=CLIENT):
    return client.post(p, data=d, headers=HOST, follow_redirects=False)


def test_uebersicht_und_liste_escaped():
    r = _liste()
    u = _get("/empfehlungen").text
    assert "Pole Position" in u and "&lt;b&gt;Kunde&lt;/b&gt;" in u and "<b>Kunde</b>" not in u
    s = _get(f"/empfehlungen/{r['liste_id']}")
    assert s.status_code == 200
    assert "&lt;script&gt;" in s.text and "<script>x" not in s.text
    for spalte in ("Name", "Vorname", "Beruf", "Alter", "Ort", "Telefon", "Termin", "Ergebnis"):
        assert spalte in s.text
    assert "/kalender?neu=kunde&amp;lead_id=" in s.text
    assert f"{date.today():%d.%m.%Y}" in s.text


def test_zeile_speichern_und_csrf():
    r = _liste()
    lid = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    d = {"lead_id": lid, "liste_id": r["liste_id"], "ergebnis": "nicht_erreicht",
         "notiz": "Mailbox", "einwilligung": "1"}
    assert _post("/empfehlungen/zeile", d).status_code == 403
    a = _post("/empfehlungen/zeile", {**d, "csrf": ui.CSRF_TOKEN})
    assert a.status_code == 303
    z = em.liste(r["liste_id"])["zeilen"][0]
    assert z["ergebnis"] == "nicht_erreicht" and z["notiz"] == "Mailbox" and z["einwilligung"]
    bad = _post("/empfehlungen/zeile", {**d, "csrf": ui.CSRF_TOKEN, "ergebnis": "quatsch"})
    assert bad.status_code == 422


def test_zeile_hinzufuegen_ui():
    r = _liste()
    a = _post(f"/empfehlungen/{r['liste_id']}/zeile",
              {"csrf": ui.CSRF_TOKEN, "vorname": "Neu", "name": "Mensch", "telefon": ""})
    assert a.status_code == 303 and len(em.liste(r["liste_id"])["zeilen"]) == 2
    assert _post(f"/empfehlungen/{r['liste_id']}/zeile",
                 {"csrf": ui.CSRF_TOKEN, "vorname": "", "name": ""}).status_code == 422


def test_pdf_route_und_404():
    r = _liste()
    p = _get(f"/empfehlungen/{r['liste_id']}/pdf")
    assert p.status_code == 200 and p.headers["content-type"].startswith("application/pdf")
    assert p.content[:4] == b"%PDF"
    assert _get("/empfehlungen/00000000-0000-0000-0000-000000000000").status_code == 404
    assert _get("/empfehlungen/kaputt").status_code == 404
    assert _get("/empfehlungen/00000000-0000-0000-0000-000000000000/pdf").status_code == 404


def test_nav_und_rolle_kalender_kein_zugriff():
    assert ui._pfad_erlaubt("kalender", "/empfehlungen") is False
    assert "/empfehlungen" in _get("/kontakte").text


def _anmelden(name, rolle, passwort="lesen-passwort-9"):
    import benutzer_anlegen
    assert benutzer_anlegen.anlegen(name, rolle, passwort).startswith("OK")
    client = TestClient(ui.app)
    a = client.post("/login", data={"name": name, "passwort": passwort, "csrf": ui.CSRF_TOKEN},
                    headers=HOST, follow_redirects=False)
    assert a.status_code == 303
    return client


def test_rolle_lesen_ohne_formulare():
    r = _liste()
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    try:
        client = _anmelden("leser", "lesen")
        s = _get(f"/empfehlungen/{r['liste_id']}", client)
        assert s.status_code == 200 and "Beispiel" in s.text
        assert 'action="/empfehlungen/zeile"' not in s.text
        assert "Zeile hinzufügen" not in s.text
    finally:
        ui.UI_SESSION_SECRET = vorher
        ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def test_fremde_zeile_ist_schreibgeschuetzt():
    erste = _liste()
    zweite = _liste(empfohlen_von_name="Zweite", datum="2026-01-05")
    z = em.liste(zweite["liste_id"])["zeilen"][0]
    assert z["fremd"]
    s = _get(f"/empfehlungen/{zweite['liste_id']}").text
    assert f"schon bekannt (Liste vom {date.today():%d.%m.%Y})" in s
    assert 'action="/empfehlungen/zeile"' not in s
    assert f'/kontakte/{z["lead_id"]}' in s
    # Direkt-POST mit der falschen Liste wird abgelehnt
    d = {"csrf": ui.CSRF_TOKEN, "lead_id": z["lead_id"], "liste_id": zweite["liste_id"],
         "ergebnis": "abschluss"}
    assert _post("/empfehlungen/zeile", d).status_code == 422
    assert em.liste(erste["liste_id"])["zeilen"][0]["ergebnis"] == "offen"


def test_hinweis_nach_widerruf_fremder_einwilligung_escaped():
    r = _liste()
    lead = em.liste(r["liste_id"])["zeilen"][0]["lead_id"]
    server.einwilligung_erfassen(lead, "opt_in", "Telefonat <i>x</i>")
    em.zeile_setzen(lead, einwilligung=True, liste_id=r["liste_id"])
    a = _post("/empfehlungen/zeile", {"csrf": ui.CSRF_TOKEN, "lead_id": lead,
                                      "liste_id": r["liste_id"], "ergebnis": "offen"})
    assert a.status_code == 303 and "hinweis=" in a.headers["location"]
    s = _get(a.headers["location"]).text
    assert "anderer Quelle" in s and 'class="hinweis"' in s
    h = _get(f"/empfehlungen/{r['liste_id']}?hinweis=%3Cscript%3Ex%3C/script%3E").text
    assert "&lt;script&gt;x" in h and "<script>x" not in h
