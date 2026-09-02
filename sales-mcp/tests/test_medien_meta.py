"""Verträge über den Schalter „Bot darf senden“ und die Herkunft je Datei —
Schritt 4 des UI-Plans (02.09.2026). Betreiber: „nicht alle Daten sind
wichtig, um den Bot sinnvoll zu bedienen.“

Ohne Zeile in medien_meta gilt wie bisher: darf senden, hochgeladen.
"""
import json

import pytest
from starlette.testclient import TestClient

import medien
import server
import ui

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads, sales_test.medien_meta "
            "cascade")
    yield


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    erzeugt = tmp_path / "erzeugt"
    erzeugt.mkdir()
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(media))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    (media / "a.pdf").write_bytes(b"%PDF-1.4 a")
    (media / "b.pdf").write_bytes(b"%PDF-1.4 b")
    (erzeugt / "termin-test-2026-09-04-1300.ics").write_bytes(b"BEGIN:VCALENDAR")
    return media, erzeugt


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _post(pfad, daten):
    return CLIENT.post(pfad, data=daten, headers={"host": HOST_OK},
                       follow_redirects=False)


def _lead_mit_grundlage(name="Max Testperson", phone="+491701234567"):
    lead = str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'kundenantwort', %s::jsonb, 'agent') returning id",
              (lead, '{"text": "Hallo, bitte melden"}'))
    return lead


def test_ohne_zeile_darf_der_bot_alles_senden(ordner):
    daten = json.loads(server.medien_liste())
    assert [d["name"] for d in daten["dateien"]] == [
        "a.pdf", "b.pdf", "termin-test-2026-09-04-1300.ics"]
    assert daten["gesperrt"] == []
    assert daten["dateien"][0]["herkunft"] == "hochgeladen"
    assert daten["dateien"][2]["herkunft"] == "system"


def test_gesperrte_datei_verschwindet_aus_der_bot_liste(ordner):
    server.medien_meta_setzen("b.pdf", bot_darf_senden=False)
    daten = json.loads(server.medien_liste())
    assert [d["name"] for d in daten["dateien"]] == [
        "a.pdf", "termin-test-2026-09-04-1300.ics"]
    assert daten["gesperrt"] == ["b.pdf"]


def test_entwurf_mit_gesperrtem_anhang_wird_abgewiesen(ordner):
    lead = _lead_mit_grundlage()
    server.kontakt_freigeben(lead)   # WhatsApp braucht die Kontakt-Freigabe
    server.medien_meta_setzen("b.pdf", bot_darf_senden=False)
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei die Unterlage.", medien_datei="b.pdf"))
    assert "fehler" in antwort
    assert "gesperrt" in antwort["fehler"]
    assert server._q("select count(*) n from drafts")[0]["n"] == 0
    # Die freigegebene Datei geht weiter durch.
    antwort = json.loads(server.entwurf_erstellen(
        lead, "whatsapp", "Anbei die Unterlage.", medien_datei="a.pdf"))
    assert "fehler" not in antwort


def test_schalter_in_der_oberflaeche_setzt_und_zeigt(ordner):
    seite = _get("/medien").text
    assert "Bot darf senden" in seite
    assert 'name="name" value="b.pdf"' in seite
    r = _post("/medien/bot", {"name": "b.pdf", "erlaubt": "nein",
                              "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303 and r.headers["location"] == "/medien"
    zeile = server._q("select bot_darf_senden, herkunft from medien_meta "
                      "where dateiname = 'b.pdf'")[0]
    assert zeile["bot_darf_senden"] is False
    assert zeile["herkunft"] == "hochgeladen"
    seite = _get("/medien").text
    b = seite[seite.index("b.pdf"):]
    assert "<b>Aus</b>" in b[:1200]
    a = seite[seite.index("a.pdf"):seite.index("b.pdf")]
    assert "<b>An</b>" in a
    # Wieder freigeben.
    r = _post("/medien/bot", {"name": "b.pdf", "erlaubt": "ja",
                              "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert server._q("select bot_darf_senden from medien_meta "
                     "where dateiname = 'b.pdf'")[0]["bot_darf_senden"] is True


def test_schalter_kennt_nur_dateien_die_es_gibt(ordner):
    r = _post("/medien/bot", {"name": "nix.pdf", "erlaubt": "nein",
                              "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 404
    r = _post("/medien/bot", {"name": "b.pdf", "erlaubt": "vielleicht",
                              "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    r = _post("/medien/bot", {"name": "b.pdf", "erlaubt": "nein"})
    assert r.status_code == 403


def test_herkunft_und_letzter_versand_stehen_in_der_tabelle(ordner):
    lead = _lead_mit_grundlage()
    server._q("insert into drafts (lead_id, channel, recipient, body, status, "
              "media_ref, sent_at) values (%s, 'whatsapp', '+491701234567', "
              "'Anbei', 'sent', 'a.pdf', now()) returning id", (lead,))
    seite = _get("/medien").text
    assert "Zuletzt gesendet" in seite
    a = seite[seite.index("a.pdf"):seite.index("b.pdf")]
    assert "—" not in a.split("</tr>")[0] or "Zuletzt" not in a
    assert "system" in seite[seite.index("termin-test"):]
