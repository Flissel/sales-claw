"""Kontaktseite mit Kopfkarte und Reitern (Design-Review S3, Plan
2026-10-19-design-s3-s4.md Task 3, E7-E9).

Die Seite war rund 27 000 px lang. Sie hat jetzt eine Kopfkarte und sechs
Reiter als Links (`?reiter=`). Jede Aktion landet nach dem Absenden auf dem
Reiter, auf dem man sie ausgelöst hat.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402
import ui_muster  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _get(pfad, host=HOST_OK):
    return CLIENT.get(pfad, headers={"host": host})


def _post(pfad, daten, host=HOST_OK):
    return CLIENT.post(pfad, data=daten, headers={"host": host},
                       follow_redirects=False)


def _lead(name="Max Testperson", phone="+491701234567"):
    return str(server._q(
        "insert into leads (name, phone, source) values (%s, %s, 'whatsapp') "
        "returning id", (name, phone))[0]["id"])


def _aktivitaet(lead, typ, payload):
    server._q("insert into activities (lead_id, type, actor, payload) "
              "values (%s, %s, 'agent', %s::jsonb) returning id",
              (lead, typ, json.dumps(payload)))


# --- Baustein und Kopfkarte ----------------------------------------------------

def test_reiter_baustein():
    h = ui_muster.reiter([("a", "Überblick", None), ("b", "Verlauf", 3)], "a", lambda k: f"/x?reiter={k}")
    assert '<a href="/x?reiter=a" aria-current="page">Überblick</a>' in h
    assert '<a href="/x?reiter=b">Verlauf <span class="zahl">3</span></a>' in h


def test_kontakt_reiter_reihenfolge_und_ziel():
    assert [k for k, _ in ui.KONTAKT_REITER] == [
        "ueberblick", "verlauf", "vertraege", "termine", "recherche", "einstellungen"]
    lid = "11111111-1111-1111-1111-111111111111"
    assert ui._kontakt_ziel(lid) == f"/kontakte/{lid}"
    assert ui._kontakt_ziel(lid, "ueberblick", "wiedervorlage") == \
        f"/kontakte/{lid}?reiter=ueberblick#wiedervorlage"
    assert ui._kontakt_ziel(lid, "einstellungen", "stufe") == \
        f"/kontakte/{lid}?reiter=einstellungen#stufe"
    assert ui._kontakt_ziel(lid, "vertraege") == f"/kontakte/{lid}?reiter=vertraege"


def test_kopfkarte_und_sechs_reiter():
    lead = _lead(name="Klara Weindorf")
    s = _get(f"/kontakte/{lead}").text
    assert '<section class="karte kopfkarte">' in s and "<h1>Klara Weindorf</h1>" in s
    assert s.count("<h1>") == 1 and '<span class="initialen">KW</span>' in s
    for name in ("Überblick", "Verlauf", "Verträge &amp; Projekte", "Termine", "Recherche", "Einstellungen"):
        assert name in s
    assert f'href="/kontakte/{lead}" aria-current="page">Überblick' in s


def test_kopfkarte_ohne_senden_und_ohne_tel_mailto():
    """E8: keine WhatsApp-/E-Mail-Knöpfe, Hauptaktionen sind Links."""
    lead = _lead()
    s = _get(f"/kontakte/{lead}").text
    kopf = s[s.index('<section class="karte kopfkarte">'):s.index('<nav class="reiter"')]
    assert "tel:" not in kopf and "mailto:" not in kopf and "<form" not in kopf
    assert f'href="/kontakte/{lead}?reiter=ueberblick#wiedervorlage"' in kopf
    assert f'href="/kontakte/{lead}?reiter=termine"' in kopf
    assert f'href="/kontakte/{lead}?reiter=einstellungen"' in kopf


def test_sammelkontakt_kopfkarte_ohne_bearbeiten_und_wiedervorlage():
    vorher = server.UNBEKANNT_LEAD_ID
    try:
        lead = _lead(name="Unbekannte Eingaenge", phone=None)
        server.UNBEKANNT_LEAD_ID = lead
        s = _get(f"/kontakte/{lead}").text
        kopf = s[s.index('<section class="karte kopfkarte">'):s.index('<nav class="reiter"')]
        assert "#wiedervorlage" not in kopf and "reiter=einstellungen" not in kopf
    finally:
        server.UNBEKANNT_LEAD_ID = vorher


def test_reiterzahlen_verlauf_vertraege_termine():
    lead = _lead()
    _aktivitaet(lead, "notiz", {"text": "a"})
    _aktivitaet(lead, "termin", {"datum": "2099-01-02", "uhrzeit": "10:00", "thema": "x"})
    s = _get(f"/kontakte/{lead}").text
    nav = s[s.index('<nav class="reiter"'):]
    nav = nav[:nav.index("</nav>")]
    assert 'Verlauf <span class="zahl">2</span>' in nav
    assert 'Termine <span class="zahl">1</span>' in nav
    assert 'Projekte <span class="zahl">0</span>' in nav


def test_ueberblick_ist_kurz_und_ohne_formulare_der_einstellungen():
    lead = _lead()
    s = _get(f"/kontakte/{lead}").text
    assert "<th>Stufe</th><td>neu</td>" in s and 'action="/wiedervorlagen/setzen"' in s
    assert 'action="/kontakte/bearbeiten"' not in s and 'action="/kontakte/stufe"' not in s


def test_ueberblick_zeigt_letzte_kontakte_mit_link_zum_verlauf():
    lead = _lead()
    s = _get(f"/kontakte/{lead}").text
    assert '<div class="zwei">' in s and 'id="wiedervorlage"' in s
    assert "Letzte Kontakte" in s and 'id="profil"' in s
    assert f'href="/kontakte/{lead}?reiter=verlauf"' in s
    # Inhalte anderer Reiter laufen hier nicht mit.
    assert "Recherche (Firma)" not in s and 'id="abschluss"' not in s
    assert "<h2>Verlauf (" not in s


def test_einstellungen_traegt_die_pflege():
    lead = _lead()
    s = _get(f"/kontakte/{lead}?reiter=einstellungen").text
    for a in ("/kontakte/bearbeiten", "/kontakte/stufe", "/kontakte/privat", "/kontakte/freigeben"):
        assert f'action="{a}"' in s
    assert 'action="/kontakte/archivieren"' in s and 'id="einordnung"' in s
    assert 'aria-current="page">Einstellungen' in s


def test_jeder_reiter_zeigt_nur_seinen_inhalt():
    lead = _lead()
    v = _get(f"/kontakte/{lead}?reiter=verlauf").text
    assert 'id="historie"' in v and "<h2>Verlauf (" in v and 'action="/wiedervorlagen/setzen"' not in v
    t = _get(f"/kontakte/{lead}?reiter=termine").text
    assert "<h2>Termine (0)</h2>" in t and 'id="historie"' not in t
    r = _get(f"/kontakte/{lead}?reiter=recherche").text
    assert "Recherche (Firma)" in r and "<h2>Termine (" not in r
    k = _get(f"/kontakte/{lead}?reiter=vertraege").text
    assert 'id="abschluss"' in k and "Recherche (Firma)" not in k


@pytest.mark.parametrize("wert", ["<script>x</script>", "ALLES", "", "verlauf'"])
def test_unbekannter_reiter_ist_ueberblick(wert):
    lead = _lead()
    r = CLIENT.get(f"/kontakte/{lead}", params={"reiter": wert}, headers={"host": HOST_OK})
    assert r.status_code == 200 and "<script>x" not in r.text
    assert 'aria-current="page">Überblick' in r.text
    if wert:
        assert ui._e(wert) not in r.text


def test_initialen_und_name_escaped():
    lead = _lead(name='<img src=x onerror="a()"> Bob')
    s = _get(f"/kontakte/{lead}").text
    assert "<img src=x" not in s and "&lt;img" in s


def test_hinweise_stehen_ueber_jedem_reiter():
    lead = _lead()
    for reiter in ("verlauf", "einstellungen"):
        s = _get(f"/kontakte/{lead}?reiter={reiter}&gespeichert=telefon").text
        assert "Telefonnummer geändert" in s
        assert s.index("Telefonnummer geändert") < s.index('<nav class="reiter"')


# --- E9: Aktionen landen auf ihrem Reiter --------------------------------------

def test_aktionen_landen_auf_ihrem_reiter():
    lead = _lead()
    r = _post("/kontakte/stufe", {"lead_id": lead, "stufe": "kontaktiert", "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen#stufe"


def test_wiedervorlage_setzen_landet_im_ueberblick():
    lead = _lead()
    r = _post("/wiedervorlagen/setzen", {"lead_id": lead, "faellig_am": "2099-01-01",
                                         "notiz": "Rückruf", "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=ueberblick#wiedervorlage"


def test_freigabe_setzen_und_entziehen_landen_in_einstellungen():
    lead = _lead()
    r = _post("/kontakte/freigeben", {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen#freigabe"
    r = _post("/kontakte/freigabe-entziehen", {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen#freigabe"


def test_einordnen_landet_in_einstellungen():
    lead = _lead()
    r = _post("/kontakte/einordnen", {"lead_id": lead, "art": "person", "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen#einordnung"


def test_vertrag_landet_in_vertraegen():
    lead = _lead()
    r = _post("/kontakte/vertrag", {"lead_id": lead, "art": "eigen", "bezeichnung": "Haftpflicht",
                                    "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=vertraege#abschluss"


def test_bearbeiten_landet_in_einstellungen():
    lead = _lead()
    r = _post("/kontakte/bearbeiten", {"lead_id": lead, "name": "Max Testperson",
                                       "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen"
    r = _post("/kontakte/bearbeiten", {"lead_id": lead, "name": "Max Neu",
                                       "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen"
    r = _post("/kontakte/bearbeiten", {"lead_id": lead, "name": "Max Neu",
                                       "phone": "+491709999999", "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen&gespeichert=telefon"


def test_privat_setzen_und_aufheben_landen_in_einstellungen():
    lead = _lead()
    warn = _post("/kontakte/privat", {"lead_id": lead, "csrf": ui.CSRF_TOKEN}).text
    assert f'href="/kontakte/{lead}?reiter=einstellungen"' in warn
    r = _post("/kontakte/privat-bestaetigen", {"lead_id": lead, "name_bestaetigt": "Max Testperson",
                                               "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen#privat"
    r = _post("/kontakte/privat-entziehen", {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen#privat"


def test_archivieren_und_wiederherstellen_landen_in_einstellungen():
    lead = _lead()
    warn = _post("/kontakte/archivieren", {"lead_id": lead, "csrf": ui.CSRF_TOKEN}).text
    assert f'href="/kontakte/{lead}?reiter=einstellungen"' in warn
    r = _post("/kontakte/archivieren-bestaetigen", {"lead_id": lead, "name_bestaetigt": "Max Testperson",
                                                    "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen"
    r = _post("/kontakte/wiederherstellen", {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=einstellungen"


def test_profil_anfordern_bleibt_im_ueberblick():
    lead = _lead()
    r = _post("/kontakte/profil-anfordern", {"lead_id": lead, "csrf": ui.CSRF_TOKEN})
    assert r.headers["location"] == f"/kontakte/{lead}#profil"


def test_freigabe_verweis_der_autonomie_zeigt_auf_einstellungen():
    lead = _lead()
    server.kontakt_autonomie_setzen(lead, "auto")
    s = _get("/kontakte").text
    assert f'href="/kontakte/{lead}?reiter=einstellungen#freigabe"' in s


def test_historie_alle_link_bleibt_im_verlauf():
    lead = _lead()
    for i in range(25):
        server._q("insert into drafts (lead_id, channel, recipient, body, status, thema, sent_at) "
                  "values (%s, 'whatsapp', '+49170', 'x', 'sent', %s, now()) returning id",
                  (lead, f"Thema {i}"))
    s = _get(f"/kontakte/{lead}?reiter=verlauf").text
    assert 'href="?reiter=verlauf&amp;historie=alle#historie"' in s


# --- Fix-Runde 1 (Review Task 3) ------------------------------------------------

def _wiedervorlage(lead):
    server.wiedervorlage_setzen(lead_id=lead, faellig_am="2099-01-01", notiz="Rückruf")
    return str(server._q("select id from activities where lead_id = %s and type = 'wiedervorlage'",
                         (lead,))[0]["id"])


def test_erledigt_im_ueberblick_fuehrt_zurueck_zum_kontakt():
    lead = _lead()
    wv = _wiedervorlage(lead)
    s = _get(f"/kontakte/{lead}").text
    assert f'name="danach" value="/kontakte/{lead}?reiter=ueberblick"' in s
    r = _post("/wiedervorlagen/erledigt", {"lead_id": lead, "aktivitaets_id": wv,
                                           "danach": f"/kontakte/{lead}?reiter=ueberblick",
                                           "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert r.headers["location"] == f"/kontakte/{lead}?reiter=ueberblick#wiedervorlage"


@pytest.mark.parametrize("danach", [
    "//boese.de", "https://boese.de", "/kontakte", "/kontakte/x?reiter=ueberblick",
    "/kontakte/{anderer}?reiter=ueberblick", "/kontakte/{lead}?reiter=einstellungen",
    "/kontakte/{lead}?reiter=ueberblick#x", "/kontakte/{lead}?reiter=ueberblick&a=b",
    "/kontakte/{LEAD}?reiter=ueberblick", " /kontakte/{lead}?reiter=ueberblick"])
def test_erledigt_kontaktziel_nur_nach_festem_muster(danach):
    lead = _lead()
    anderer = _lead(name="Andere Person", phone="+491709999999")
    wv = _wiedervorlage(lead)
    wert = danach.format(lead=lead, anderer=anderer, LEAD=lead.upper())
    r = _post("/wiedervorlagen/erledigt", {"lead_id": lead, "aktivitaets_id": wv,
                                           "danach": wert, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303 and r.headers["location"] == "/wiedervorlagen"


def test_erledigt_von_wiedervorlagen_und_heute_unveraendert():
    lead = _lead()
    for danach, ziel in (("/", "/"), ("/wiedervorlagen", "/wiedervorlagen"), (None, "/wiedervorlagen")):
        wv = _wiedervorlage(lead)
        daten = {"lead_id": lead, "aktivitaets_id": wv, "csrf": ui.CSRF_TOKEN}
        if danach is not None:
            daten["danach"] = danach
        assert _post("/wiedervorlagen/erledigt", daten).headers["location"] == ziel
    # Die Liste /wiedervorlagen trägt weiter kein Rücksprungfeld.
    wv = _wiedervorlage(lead)
    assert wv and 'name="danach"' not in _get("/wiedervorlagen").text


def test_letzte_kontakte_fehler_bricht_ueberblick_nicht(monkeypatch):
    lead = _lead()

    def kaputt(_):
        raise ui.psycopg.Error("weg")
    monkeypatch.setattr(ui.historie, "kontakt_historie", kaputt)
    r = _get(f"/kontakte/{lead}")
    assert r.status_code == 200
    teil = r.text.split("<h2>Letzte Kontakte</h2>")[1]
    assert "Gerade nicht lesbar." in teil and "Ganzer Verlauf" in teil


def test_kontakt_ziel_haengt_abfrage_sauber_an():
    lid = "11111111-1111-1111-1111-111111111111"
    assert ui._kontakt_ziel(lid, "einstellungen", gespeichert="telefon") == \
        f"/kontakte/{lid}?reiter=einstellungen&gespeichert=telefon"
    assert ui._kontakt_ziel(lid, gespeichert="telefon") == f"/kontakte/{lid}?gespeichert=telefon"
    assert ui._kontakt_ziel(lid, "einstellungen", "stufe", gespeichert="telefon") == \
        f"/kontakte/{lid}?reiter=einstellungen&gespeichert=telefon#stufe"
