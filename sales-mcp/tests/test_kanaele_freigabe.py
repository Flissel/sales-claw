"""Freigaben-Seite kennt die fuenf Kanaele (Beitraege auf weitere Kanaele,
Task 7, 24.10.2026) gegen sales_test.

Bluesky, Mastodon, Telegram-Kanal, Discord und dev.to sind eigene Beitraege
(recipient 'eigenes-profil', Lead = Sammelkontakt). Ein Block erscheint nur,
wenn es etwas zu sehen gibt oder der Kanal verbunden ist; die Karte sagt,
was mit einer Freigabe passiert.
"""
import json
import os

import pytest
from starlette.testclient import TestClient

# HART, nicht setdefault (wie test_ui.py).
os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kanaele  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def sammelkontakt(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.drafts, sales_test.activities, "
            "sales_test.leads, sales_test.kanal_status cascade")
    sammel = server._q(
        "insert into leads (name, source) values "
        "('LINKEDIN (Eigenes Profil)', 'system') returning id")[0]["id"]
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", str(sammel))
    return str(sammel)


def _get(pfad):
    return CLIENT.get(pfad, headers={"host": HOST_OK})


def _entwurf(lead, kanal, text="Hallo aus dem Herbst #KI", status="pending",
             approved_vor_tagen=None):
    zeile = server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, subject, thema) "
        "values (%s, %s, 'eigenes-profil', %s, %s, 'Post: Herbst', 'Herbst') "
        "returning id", (lead, kanal, text, status))[0]
    if status in ("approved", "sent"):
        tage = approved_vor_tagen or 0
        server._q(
            "update drafts set approved_by = 'betreiber-ui', "
            "approved_at = now() - make_interval(days => %s), "
            "sent_at = case when status = 'sent' then now() else sent_at end "
            "where id = %s returning id", (tage, zeile["id"]))
    return str(zeile["id"])


def _beleg(lead, draft_id, url):
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'versand', %s::jsonb) returning id",
        (lead, json.dumps({"draft_id": draft_id, "kanal": "bluesky",
                           "weg": "kanal-dispatcher",
                           "empfaenger": "eigenes-profil", "beitrag": "x",
                           "url": url, "medienart": None})))


def test_freigaben_zeigt_offenen_bluesky_entwurf(sammelkontakt):
    _entwurf(sammelkontakt, "bluesky", text="Grüße vom Bluesky-Test")
    seite = _get("/freigaben").text
    assert 'class="badge bluesky">Bluesky<' in seite
    assert "Grüße vom Bluesky-Test" in seite


def test_leere_unverbundene_kanaele_ohne_block():
    antwort = _get("/freigaben")
    assert antwort.status_code == 200
    for kanal in kanaele.KANAELE:
        assert f'class="badge {kanal}"' not in antwort.text
    assert "Mastodon</h2>" not in antwort.text
    # Die alten drei Arten bleiben immer sichtbar.
    assert '<span class="badge linkedin">linkedin</span> LinkedIn' in antwort.text


def test_verbundener_kanal_hat_block():
    kanaele.status_schreiben(server._q, "mastodon", True, None)
    seite = _get("/freigaben").text
    kopf = '<h2><span class="badge mastodon">Mastodon</span> Mastodon'
    assert kopf in seite
    block = seite.split(kopf, 1)[1].split("</section>", 1)[0]
    assert "Nichts offen." in block


def test_kein_direkt_freigeben_in_der_zeile(sammelkontakt):
    did = _entwurf(sammelkontakt, "discord", text="x" * 50)
    z = server._q("select d.*, l.name, l.consent_status from drafts d "
                  "left join leads l on l.id = d.lead_id where d.id = %s",
                  (did,))[0]
    assert ui._direkt_freigebbar(z) is False
    seite = _get("/").text
    assert f'id="f-{did}"' in seite
    assert f'id="fz-{did}"' not in seite


def test_devto_hinweis_entwurf_bei_devto(sammelkontakt):
    _entwurf(sammelkontakt, "devto", text="# Artikel\n\nText")
    seite = _get("/freigaben").text
    assert ("Freigeben legt den Artikel als Entwurf bei dev.to an – "
            "veröffentlicht wird dort von Hand.") in seite


def test_freigegeben_nicht_verbunden_hinweis(sammelkontakt):
    _entwurf(sammelkontakt, "discord", status="approved")
    seite = _get("/freigaben").text
    assert ("Kanal nicht verbunden – bleibt liegen, bis der Zugang "
            "eingetragen ist.") in seite


def test_freigegeben_verbunden_hinweis_mit_kadenz(sammelkontakt):
    kanaele.status_schreiben(server._q, "devto", True, None)
    _entwurf(sammelkontakt, "devto", status="approved")
    seite = _get("/freigaben").text
    assert ("Der Dienst sales-kanaele veröffentlicht den Beitrag (höchstens 1 "
            "pro Tag). Freigaben, die älter als 7 Tage sind, bleiben liegen."
            ) in seite
    assert "wird als Entwurf bei dev.to angelegt" in seite
    assert "Älter als 7 Tage" not in seite


def test_freigegeben_zu_alt_hinweis(sammelkontakt):
    kanaele.status_schreiben(server._q, "bluesky", True, None)
    _entwurf(sammelkontakt, "bluesky", status="approved", approved_vor_tagen=8)
    seite = _get("/freigaben").text
    assert ("Älter als 7 Tage freigegeben – wird nicht mehr automatisch "
            "veröffentlicht.") in seite


def test_verlauf_verlinkt_beleg(sammelkontakt):
    gut = _entwurf(sammelkontakt, "bluesky", text="erster", status="sent")
    _beleg(sammelkontakt, gut, "https://bsky.app/profile/x/post/1")
    boese = _entwurf(sammelkontakt, "bluesky", text="zweiter", status="sent")
    _beleg(sammelkontakt, boese, "javascript:alert(1)")
    antwort = _get("/freigaben/verlauf/bluesky")
    assert antwort.status_code == 200
    assert ('<a href="https://bsky.app/profile/x/post/1" rel="noopener">'
            'Beitrag ansehen</a>') in antwort.text
    assert "javascript:alert(1)" not in antwort.text
    assert antwort.text.count("Beitrag ansehen") == 1


def test_verlauf_unbekannte_art_nennt_neue():
    antwort = _get("/freigaben/verlauf/foo")
    assert antwort.status_code == 404
    assert "bluesky" in antwort.text
    assert "devto" in antwort.text


def test_ohne_kanal_status_tabelle_kein_absturz(sammelkontakt, monkeypatch):
    monkeypatch.setattr(kanaele, "status_lesen", lambda q: {})
    _entwurf(sammelkontakt, "mastodon", status="approved")
    antwort = _get("/freigaben")
    assert antwort.status_code == 200
    assert "Kanal nicht verbunden" in antwort.text


def test_heute_chip_nur_mit_offenen(sammelkontakt):
    chip = '<span class="art"><span class="badge telegram_kanal">'
    assert chip not in _get("/").text
    _entwurf(sammelkontakt, "telegram_kanal")
    seite = _get("/").text
    assert seite.count(chip) == 1
    assert (chip + "Telegram-Kanal</span><b>1</b>") in seite


def test_badge_zeigt_anzeigenamen():
    assert ui._badge("devto") == '<span class="badge devto">dev.to</span>'
    assert ui._badge("whatsapp") == '<span class="badge whatsapp">whatsapp</span>'
    assert ui._ZEILE_KANAELE == ("whatsapp", "email")
    assert [a for a, _ in ui.FREIGABE_ARTEN] == [
        "whatsapp", "linkedin", "email", "bluesky", "mastodon",
        "telegram_kanal", "discord", "devto"]
