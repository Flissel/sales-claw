"""Abschnitt "Eingang" auf /freigaben und seine Aktionen (Plan 2026-11-08, Task 6)."""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import freigabe_eingang as fe  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
# Freigaben in Reitern (09.11.2026): Debugger-PRs und Rueckfragen unter Technik, Kurse eigen.
TECHNIK = "/freigaben?tab=technik"
KURSE = "/freigaben?tab=kurse"
PR = "Flissel/vibemind-os#154"
RUECK = "Flissel/vibemind-os#77"
KURS = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        # Eine Anweisung, eintraege zuerst (Sperrreihenfolge, s. test_freigabe_eingang.py).
        conn.execute("truncate sales_test.freigabe_eintraege, "
                     "sales_test.freigabe_schluessel cascade")
        conn.execute("delete from sales_test.einstellungen where schluessel = 'freigabe_stufe2'")
    yield


def _anmelden(rolle: str) -> TestClient:
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", rolle, ui._passwort_hashen("korrekt-pferd-9")))
    c = TestClient(ui.app, headers=HOST)
    r = c.post("/login", data={"name": "mira", "passwort": "korrekt-pferd-9", "csrf": ui.CSRF_TOKEN},
               follow_redirects=False)
    assert r.status_code == 303
    return c


@pytest.fixture
def anmeldung(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis-nur-fuer-die-suite")
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield _anmelden
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


@pytest.fixture
def client(anmeldung):
    return anmeldung("freigeben")


@pytest.fixture
def client_lesen(anmeldung):
    return anmeldung("lesen")


def _abschnitt(c, pfad=TECHNIK) -> str:
    r = c.get(pfad)
    assert r.status_code == 200
    s = r.text[r.text.index('<section class="block" id="eingang">'):]
    return s[:s.index("</section>")]


def _post(c, aktion, kennung, csrf=True, **felder):
    daten = {"kennung": kennung, **felder}
    if csrf:
        daten["csrf"] = ui.CSRF_TOKEN
    return c.post(f"/aktion/{aktion}", data=daten, follow_redirects=False)


def _rueckfrage():
    return fe.eintragen("selbstbild", "selbstbild_rueckfrage", RUECK, "Ist das Absicht?",
                        "https://github.com/x/issues/77")[0]


def _kurs():
    return fe.eintragen("werkstatt", "kursfreigabe", "kurs-1", "Mathe 1", None,
                        {"course_id": KURS})[0]


def _auftraege():
    return server._q("select * from freigabe_auftraege order by erstellt_am")


def test_abschnitt_zeigt_herkunft_link_vermerk(client):
    k = fe.eintragen("debugger-claw", "debugger_pr", PR, "Fix für Mail-Schleife",
                     "https://github.com/Flissel/vibemind-os/pull/154", {"tests": "12 grün"})[0]
    fe.rowboat_stand_setzen(k, "angenommen")
    s = _abschnitt(client)
    assert f'id="{k}"' in s and k.startswith("fg-")
    assert "Debugger-Claw" in s and "Fix für Mail-Schleife" in s
    assert "in Rowboat angenommen" in s
    assert "auf GitHub ansehen" in s and "12 grün" in s
    assert "Merge" not in s


@pytest.mark.parametrize("stand,text", [
    ("ungesichtet", "noch nicht gesichtet"), ("vorgeschlagen", "noch nicht gesichtet"),
    ("abgelehnt", "in Rowboat abgelehnt"), ("abgehakt", "in Rowboat abgehakt")])
def test_vermerk_je_stand(client, stand, text):
    k = _rueckfrage()
    fe.rowboat_stand_setzen(k, stand)
    assert text in _abschnitt(client)


def test_label_knopf_legt_auftrag_an(client):
    k = _rueckfrage()
    s = _abschnitt(client)
    assert "kann weg" in s and "soll bleiben" in s and "wird benutzt" in s
    r = _post(client, "eingang-label", k, label="antwort:bleibt")
    assert r.status_code == 303
    a = _auftraege()
    assert len(a) == 1 and a[0]["art"] == "selbstbild_label"
    assert a[0]["nutzlast"] == {"repo": "Flissel/vibemind-os", "nummer": 77,
                                "label": "antwort:bleibt"}
    assert a[0]["angefordert_von"] == "mira"
    s = _abschnitt(client)
    assert "wartet auf PC" in s and "kann weg" not in s


def test_fehlgeschlagen_zeigt_fehler_und_knoepfe(client):
    k = _rueckfrage()
    _post(client, "eingang-label", k, label="antwort:weg")
    server._q("update freigabe_auftraege set status = 'fehler', fehler = 'Label fehlt' "
              "returning id")
    s = _abschnitt(client)
    assert "fehlgeschlagen: Label fehlt" in s and "kann weg" in s
    assert "wartet auf PC" not in s


def test_falsches_label_abgelehnt(client):
    k = _rueckfrage()
    assert _post(client, "eingang-label", k, label="antwort:egal").status_code == 422
    assert _auftraege() == []


def test_label_fuer_kursfreigabe_abgewiesen(client):
    k = _kurs()
    assert _post(client, "eingang-label", k, label="antwort:weg").status_code == 303
    assert _auftraege() == []


def test_kurs_knopf(client):
    k = _kurs()
    assert "Freigabe-Seite schicken" in _abschnitt(client, KURSE)
    assert _post(client, "eingang-kurs", k).status_code == 303
    a = _auftraege()
    assert len(a) == 1 and a[0]["art"] == "kurs_freigabe_zeigen"
    assert a[0]["nutzlast"] == {"course_id": KURS}
    assert "wartet auf PC" in _abschnitt(client, KURSE)


def test_doppelklick_nur_ein_auftrag(client):
    k = _kurs()
    _post(client, "eingang-kurs", k)
    _post(client, "eingang-kurs", k)
    assert len(_auftraege()) == 1


def test_verwerfen(client):
    k = _rueckfrage()
    r = _post(client, "eingang-verwerfen", k)
    assert r.status_code == 303
    z = server._q("select status, geschlossen_von from freigabe_eintraege where kennung = %s", (k,))
    assert z[0]["status"] == "verworfen" and z[0]["geschlossen_von"] == "mira"
    assert k not in _abschnitt(client)


def test_abgeschlossener_eintrag_kein_auftrag(client):
    k = _rueckfrage()
    fe.schliessen_kennung(k, "verworfen", "x")
    r = _post(client, "eingang-label", k, label="antwort:weg")
    assert r.status_code == 303 and "geschlossen" in r.headers["location"]
    assert _auftraege() == []
    assert "schon abgeschlossen" in client.get(r.headers["location"]).text


def test_lesen_darf_nicht(client_lesen):
    k = _rueckfrage()
    for aktion, extra in (("eingang-label", {"label": "antwort:weg"}), ("eingang-kurs", {}),
                          ("eingang-verwerfen", {}), ("eingang-stufe2", {})):
        assert _post(client_lesen, aktion, k, **extra).status_code == 403
    assert _auftraege() == []
    assert server._q("select status from freigabe_eintraege")[0]["status"] == "offen"
    s = _abschnitt(client_lesen)
    assert "verwerfen" not in s and "<form" not in s


def test_ohne_csrf_kein_auftrag(client):
    k = _rueckfrage()
    assert _post(client, "eingang-label", k, csrf=False, label="antwort:weg").status_code == 403
    assert _post(client, "eingang-verwerfen", k, csrf=False).status_code == 403
    assert _auftraege() == []
    assert server._q("select status from freigabe_eintraege")[0]["status"] == "offen"


def test_stufe2_gesperrt(client):
    s = _abschnitt(client)
    assert s.count("gesperrt, bis nur ein Klick des Betreibers zählt") == 4
    assert s.count("Annehmen in Rowboat führt aus") == 4
    assert s.count("disabled") == 4 and "checked" not in s
    vorher = fe.stufe2_lesen()
    r = _post(client, "eingang-stufe2", "", art="debugger_pr", an="1")
    assert r.status_code == 409
    assert fe.stufe2_lesen() == vorher == {a: False for a in fe.STUFE2_ARTEN}
    assert server._q("select 1 from einstellungen where schluessel = 'freigabe_stufe2'") == []


def test_entwurfskarte_mit_vermerk(client):
    lead = str(server._q("insert into leads (name, phone, source) values "
                         "('Frau Test', '+491701234567', 'whatsapp') returning id")[0]["id"])
    draft = str(server._q("insert into drafts (lead_id, channel, recipient, body, status) "
                          "values (%s, 'whatsapp', '+491701234567', 'Hallo', 'pending') "
                          "returning id", (lead,))[0]["id"])
    try:
        k = fe.eintragen("sales", "entwurf", draft, "Entwurf an Frau Test", None, {}, draft)[0]
        fe.rowboat_stand_setzen(k, "angenommen")
        seite = client.get("/freigaben").text
        assert f'id="{k}"' in seite and "Rowboat: in Rowboat angenommen" in seite
        assert f'id="{k}"' not in _abschnitt(client)       # nicht doppelt als Eingangskarte
    finally:
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.freigabe_eintraege cascade")
            conn.execute("delete from sales_test.drafts where id = %s", (draft,))
            conn.execute("delete from sales_test.leads where id = %s", (lead,))


def test_verwerfen_lehnt_entwurf_ab(client):
    """Final-Review Zeile 21: Entwuerfe werden nur ueber ihre Entwurfskarte verworfen."""
    k = fe.eintragen("sales", "entwurf", "entwurf-1", "Entwurf an Frau Test")[0]
    r = _post(client, "eingang-verwerfen", k)
    assert r.status_code == 303 and "abgewiesen" in r.headers["location"]
    z = server._q("select status, geschlossen_von from freigabe_eintraege where kennung = %s", (k,))
    assert z[0]["status"] == "offen" and z[0]["geschlossen_von"] is None
    assert "Nichts wurde getan" in client.get(r.headers["location"]).text


# --- Marketing-Video (Video-Werkbank) ----------------------------------------------------------------------

VIDEO = "marketing/werkbank/0123abcd-0000-4000-8000-000000000001/video"
VIDEOS = "/freigaben?tab=marketing&art=video"
VIDEO_AID = "0123abcd-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def video_buch(monkeypatch):
    """Das Auftragsbuch (Schema auftrag gibt es in keiner Test-DB): ein Video-Auftrag, Fassung 1, wartet auf die
    Freigabe. I6: "freigeben" prueft Stand und Fassung gegen diese Zeile."""
    import auftrag_buch
    buch = {"zeile": {"id": VIDEO_AID, "art": "video", "stand": "wartet_freigabe", "ergebnis": {"fassung": 1}},
            "staende": [], "fehler": None}

    def eigene(q, laden, staende):
        buch["staende"].append(list(staende))
        if buch["fehler"]:
            raise buch["fehler"]
        z = buch["zeile"]
        return [dict(z)] if z and z["stand"] in staende else []
    monkeypatch.setattr(auftrag_buch, "eigene", eigene)
    return buch


def _video():
    return fe.eintragen("marketing-video", "marketing_video", "0123abcd-0000-4000-8000-000000000001",
                        "Video: KI im Vertrieb", f"https://laden.example/{VIDEO}",
                        {"auftrag": "0123abcd-0000-4000-8000-000000000001", "dauer_s": 241, "fassung": 1})[0]


def test_video_karte_hat_ki_hinweis_und_freigeben_knopf(client):
    k = _video()
    s = _abschnitt(client, VIDEOS)
    assert f'id="{k}"' in s and "Marketing-Video" in s and "Video: KI im Vertrieb" in s
    assert "Ansehen und herunterladen" in s and f'href="https://laden.example/{VIDEO}"' in s
    assert "mit KI erstellt" in s
    assert 'action="/aktion/eingang-video-freigeben"' in s and ">freigeben<" in s
    assert 'action="/aktion/eingang-verwerfen"' in s and ">verwerfen<" in s
    assert "Videos" in client.get("/freigaben?tab=marketing").text      # eigener Unter-Reiter
    assert "Annehmen in Rowboat führt aus (Videos)" not in s            # kein Stufe-2-Kasten fuer Videos


def test_video_karte_ohne_ki_hinweis_nur_bei_videos(client):
    _rueckfrage()
    assert "mit KI erstellt" not in _abschnitt(client)


def test_freigeben_schliesst_als_erledigt(client):
    k = _video()
    r = _post(client, "eingang-video-freigeben", k)
    assert r.status_code == 303 and "eg_hinweis=freigegeben" in r.headers["location"]
    assert "tab=marketing" in r.headers["location"] and "art=video" in r.headers["location"]
    z = server._q("select status, geschlossen_von from freigabe_eintraege where kennung = %s", (k,))
    assert z[0]["status"] == "erledigt" and z[0]["geschlossen_von"] == "mira"
    assert "Video freigegeben." in client.get(r.headers["location"]).text
    assert k not in _abschnitt(client, VIDEOS)
    assert _auftraege() == []


def test_freigeben_zweimal_meldet_geschlossen(client):
    k = _video()
    _post(client, "eingang-video-freigeben", k)
    r = _post(client, "eingang-video-freigeben", k)
    assert r.status_code == 303 and "geschlossen" in r.headers["location"]


def test_freigeben_fuer_andere_art_abgewiesen(client):
    k = _rueckfrage()
    r = _post(client, "eingang-video-freigeben", k)
    assert r.status_code == 303 and "abgewiesen" in r.headers["location"]
    assert server._q("select status from freigabe_eintraege where kennung = %s", (k,))[0]["status"] == "offen"


def test_video_verwerfen_schliesst_als_verworfen(client):
    k = _video()
    r = _post(client, "eingang-verwerfen", k)
    assert r.status_code == 303 and "art=video" in r.headers["location"]
    assert server._q("select status from freigabe_eintraege where kennung = %s", (k,))[0]["status"] == "verworfen"


def test_video_freigeben_lesen_darf_nicht_und_csrf(client, client_lesen):
    k = _video()
    assert _post(client_lesen, "eingang-video-freigeben", k).status_code == 403
    assert _post(client, "eingang-video-freigeben", k, csrf=False).status_code == 403
    assert server._q("select status from freigabe_eintraege where kennung = %s", (k,))[0]["status"] == "offen"


NEU_GEBAUT = "Das Video wird gerade neu gebaut – bitte die neue Fassung freigeben."


@pytest.mark.parametrize("zeile", [
    {"id": VIDEO_AID, "art": "video", "stand": "werkbank", "ergebnis": {"fassung": 1}},          # wird neu gebaut
    {"id": VIDEO_AID, "art": "video", "stand": "erzeugt", "ergebnis": {"fassung": 2}},           # neue Fassung fertig
    {"id": VIDEO_AID, "art": "video", "stand": "wartet_freigabe", "ergebnis": {"fassung": 2}},   # Eintrag alt
    {"id": VIDEO_AID, "art": "video", "stand": "wartet_freigabe", "ergebnis": {}},
    None])
def test_freigeben_nur_fuer_die_aktuelle_fassung(client, video_buch, zeile):
    """I6: freigegeben wird nur, wenn der Auftrag auf die Freigabe wartet UND der Eintrag zur aktuellen Fassung
    gehoert; sonst ein Hinweis, und nichts aendert sich."""
    k = _video()
    video_buch["zeile"] = zeile
    r = _post(client, "eingang-video-freigeben", k)
    assert r.status_code == 303 and "eg_hinweis=neu_gebaut" in r.headers["location"]
    z = server._q("select status, geschlossen_von from freigabe_eintraege where kennung = %s", (k,))[0]
    assert z["status"] == "offen" and z["geschlossen_von"] is None
    assert video_buch["staende"] and all("wartet_freigabe" in s for s in video_buch["staende"])
    assert NEU_GEBAUT in client.get(r.headers["location"]).text


def test_freigeben_ohne_auftragsbuch_aendert_nichts(client, video_buch):
    k = _video()
    video_buch["fehler"] = RuntimeError("Datenbank weg")
    r = _post(client, "eingang-video-freigeben", k)
    assert r.status_code == 303 and "eg_hinweis=buch" in r.headers["location"]
    assert server._q("select status from freigabe_eintraege where kennung = %s", (k,))[0]["status"] == "offen"
    assert "Nichts wurde getan" in client.get(r.headers["location"]).text
