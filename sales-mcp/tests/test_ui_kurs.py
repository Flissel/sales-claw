"""Oberflaeche Kurse und Handbuecher (Task 7). Datenbank sales_test; Ablage: tmp_path."""
import itertools
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kurs_handbuch  # noqa: E402
import kurs_pdf  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
BEGINN = datetime(2026, 11, 14, 9, 5, tzinfo=timezone.utc)
UID = "kurs-ui-0001@sales-claw"
_nr = itertools.count(1)
_LEADS: list[str] = []


@pytest.fixture(autouse=True)
def ablage(monkeypatch, tmp_path):
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(tmp_path / "ablage"))
    (tmp_path / "ablage").mkdir()
    angelegt = _LEADS
    angelegt.clear()
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield tmp_path / "ablage"
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    for lid in angelegt:
        server._q("delete from leads where id = %s returning id", (lid,))


@pytest.fixture
def scharf():
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _lead(name="Anna Lernend", privat=False):
    enr = {server.PRIVAT_SCHLUESSEL: {"privat": True}} if privat else {}
    lid = str(server._q(
        "insert into leads (name, email, phone, source, consent_status, enrichment) "
        "values (%s, %s, %s, 'whatsapp', 'existing_customer', %s::jsonb) returning id",
        (name, f"k{next(_nr)}@kurs-ui.example", f"+4917099{next(_nr):05d}",
         json.dumps(enr)))[0]["id"])
    _LEADS.append(lid)
    return lid


def _schreibe(ablage, rel, inhalt):
    ziel = ablage / rel
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(inhalt if isinstance(inhalt, bytes) else inhalt.encode("utf-8"))


def _kurs(ablage, uid=UID, rubrik="Kurse", lernender=None, status="fertig", dateien=True,
          tage=0):
    beginn = BEGINN + timedelta(days=tage)
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs Eins', 'fertig') returning uid",
              (uid, beginn, beginn + timedelta(hours=1)))
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_am, rubrik, kurs_lead_id, kurs_status) "
              "values (%s, '[]'::jsonb, 'fertig', '{}'::jsonb, now(), %s, %s, %s) returning id",
              (uid, rubrik, lernender, status))
    if dateien:
        _schreibe(ablage, f"{rubrik}/k_kurs-intern.html", "<p>FELIX-FASSUNG</p>")
        _schreibe(ablage, f"{rubrik}/k_kurs.html", "<p>LERNENDEN-FASSUNG</p>")
        _schreibe(ablage, f"{rubrik}/k_kurs.pdf", b"%PDF-1.4 kurs")
        server._q("update termin_mitschriften set kurs_pfad = %s, kurs_pfad_lernend = %s, "
                  "kurs_pdf = %s where uid = %s returning id",
                  (f"{rubrik}/k_kurs-intern.html", f"{rubrik}/k_kurs.html",
                   f"{rubrik}/k_kurs.pdf", uid))


def _z(uid=UID):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def _get(pfad, client=CLIENT):
    return client.get(pfad, headers={"host": HOST_OK}, follow_redirects=False)


def _post(pfad, csrf=True, client=CLIENT, **felder):
    if csrf:
        felder["csrf"] = ui.CSRF_TOKEN
    return client.post(pfad, data=felder, headers={"host": HOST_OK}, follow_redirects=False)


def _als(rolle):
    async def app(scope, receive, send):
        if scope["type"] == "http":
            scope["benutzer_name"], scope["benutzer_rolle"] = "lena", rolle
        await ui.app(scope, receive, send)
    return TestClient(app)


def _kapitel(lead, titel, reihenfolge, schale=False, quellen=(UID,)):
    kid = str(server._q(
        "insert into kurs_handbuch_kapitel (lead_id, titel, reihenfolge) values (%s, %s, %s) "
        "returning id", (lead, titel, reihenfolge))[0]["id"])
    if not schale:
        fid = server._q(
            "insert into kurs_handbuch_fassung (kapitel_id, text_md, quellen) "
            "values (%s, 'Text', %s) returning id", (kid, list(quellen)))[0]["id"]
        server._q("update kurs_handbuch_kapitel set aktuelle_fassung = %s where id = %s "
                  "returning id", (fid, kid))
    return kid


def _reihenfolge(lead):
    return [r["titel"] for r in server._q(
        "select titel from kurs_handbuch_kapitel where lead_id = %s "
        "order by reihenfolge, erstellt_am", (lead,))]


def _stand(lead):
    return server._q("select fassungen_stand from kurs_handbuch where lead_id = %s",
                     (lead,))[0]["fassungen_stand"]


@pytest.fixture
def handbuch(ablage):
    """Lernende mit zwei Kapiteln, einer Huelle und einer fertigen Ausgabe."""
    _kurs(ablage, dateien=False)
    lead = _lead("Anna Lernend")
    k1 = _kapitel(lead, "Erstes Kapitel", 1)
    k2 = _kapitel(lead, "Zweites Kapitel", 2)
    _kapitel(lead, "Huellen Kapitel", 3, schale=True)
    _schreibe(ablage, "_handbuecher/handbuch-x.html", "<p>HANDBUCH</p>")
    _schreibe(ablage, "_handbuecher/handbuch-x.pdf", b"%PDF-1.4 handbuch")
    server._q("insert into kurs_handbuch (lead_id, pfad, pdf, stand_am, fassungen_stand) "
              "values (%s, '_handbuecher/handbuch-x.html', '_handbuecher/handbuch-x.pdf', "
              "%s, now()) returning lead_id", (lead, BEGINN))
    return lead, k1, k2


# ---------- Kurse-Reiter ----------

def test_kurse_reiter_zeigt_kurslinks_und_status(ablage):
    _kurs(ablage)
    t = _get("/mitschriften?rubrik=Kurse").text
    q = quote(UID, safe="")
    assert "Kursmitschrift (Felix)" in t and "Kursmitschrift PDF" in t
    assert f"/mitschriften/kurs?uid={q}&amp;fassung=felix" in t
    assert f"/mitschriften/kurs.pdf?uid={q}" in t
    assert "Lernenden wählen" in t and "fertig" in t
    assert 'action="/mitschriften/kurs/lernender"' in t and 'action="/mitschriften/kurs/suche"' in t
    assert "Handbücher" in t


def test_status_texte(ablage):
    lead = _lead("Berta")
    _kurs(ablage, uid="a@x", status="fertig", lernender=lead, tage=0)
    _kurs(ablage, uid="b@x", status="fehler", lernender=lead, dateien=False, tage=1)
    _kurs(ablage, uid="c@x", status=None, lernender=lead, dateien=False, tage=2)
    t = _get("/mitschriften?rubrik=Kurse").text
    assert "Kurs: fertig" in t and "Kurs: Fehler" in t and "Kurs: wird erzeugt" in t
    assert "Lernenden wählen" not in t
    assert "Lernende/r: Berta" in t
    # nur fehlende Datei-Links, wenn nichts abgelegt ist
    assert t.count("Kursmitschrift (Felix)") == 1


def test_andere_rubrik_ohne_kursblock(ablage):
    _kurs(ablage, rubrik="Kundentermine", dateien=False)
    t = _get("/mitschriften?rubrik=Kundentermine").text
    assert "Lernenden wählen" not in t and "/mitschriften/kurs/lernender" not in t


def _sichtbar(html):
    return html[html.index(chr(34) + "reiter" + chr(34)):]


def test_keine_versand_knoepfe(ablage):
    _kurs(ablage)
    assert "Freigabe" not in _sichtbar(_get("/mitschriften?rubrik=Kurse").text)
    assert "Freigabe" not in _sichtbar(_get("/mitschriften/handbuecher").text)


def test_lernendenname_wird_escaped(ablage):
    lead = _lead("<b>Eve</b>")
    _kurs(ablage, lernender=lead)
    t = _get("/mitschriften?rubrik=Kurse").text
    assert "<b>Eve</b>" not in t and "&lt;b&gt;Eve&lt;/b&gt;" in t


# ---------- Dateirouten ----------

def test_kurs_html_ohne_anmeldung_umleitung(scharf, ablage):
    _kurs(ablage)
    for p in (f"/mitschriften/kurs?uid={quote(UID, safe='')}&fassung=felix",
              f"/mitschriften/kurs.pdf?uid={quote(UID, safe='')}",
              "/mitschriften/handbuecher", "/mitschriften/handbuch?lead=x",
              "/mitschriften/handbuch.pdf?lead=x"):
        a = _get(p)
        assert a.status_code in (302, 303) and a.headers["location"].startswith("/login")


def test_kurs_kopfzeilen_und_inhalt(ablage):
    _kurs(ablage)
    q = quote(UID, safe="")
    r = _get(f"/mitschriften/kurs?uid={q}&fassung=lernend")
    assert r.status_code == 200 and r.text == "<p>LERNENDEN-FASSUNG</p>"
    assert r.headers["cache-control"] == "private, no-store"
    csp = r.headers["content-security-policy"]
    assert csp.startswith("default-src 'none'")
    assert all(d.strip() == "script-src 'none'" for d in csp.split(";")
               if d.strip().startswith("script-src"))
    assert "content-disposition" not in r.headers
    f = _get(f"/mitschriften/kurs?uid={q}&fassung=felix&download=1")
    assert f.text == "<p>FELIX-FASSUNG</p>"
    assert f.headers["content-disposition"] == 'attachment; filename="k_kurs-intern.html"'


def test_kurs_pdf_download(ablage):
    _kurs(ablage)
    r = _get(f"/mitschriften/kurs.pdf?uid={quote(UID, safe='')}")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 kurs"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="Kursmitschrift_2026-11-14.pdf"'
    assert r.headers["cache-control"] == "private, no-store"


def test_unbekannte_fassung_und_fehlende_datei_404(ablage, tmp_path):
    _kurs(ablage)
    q = quote(UID, safe="")
    assert _get(f"/mitschriften/kurs?uid={q}&fassung=x").status_code == 404
    assert _get(f"/mitschriften/kurs?uid={q}").status_code == 404
    assert _get("/mitschriften/kurs?uid=unbekannt&fassung=felix").status_code == 404
    assert _get("/mitschriften/kurs.pdf?uid=unbekannt").status_code == 404
    (tmp_path / "x.html").write_text("AUSSEN-GEHEIM", encoding="utf-8")
    server._q("update termin_mitschriften set kurs_pfad = '../x.html' where uid = %s "
              "returning id", (UID,))
    a = _get(f"/mitschriften/kurs?uid={q}&fassung=felix")
    assert a.status_code == 404 and "AUSSEN-GEHEIM" not in a.text
    server._q("update termin_mitschriften set kurs_pdf = 'Kurse/weg.pdf' where uid = %s "
              "returning id", (UID,))
    assert _get(f"/mitschriften/kurs.pdf?uid={q}").status_code == 404


def test_kein_kurs_ohne_datei_404(ablage):
    _kurs(ablage, dateien=False)
    assert _get(f"/mitschriften/kurs?uid={quote(UID, safe='')}&fassung=felix").status_code == 404


# ---------- Lernender ----------

def test_lernender_setzen_braucht_csrf(ablage):
    _kurs(ablage)
    lead = _lead()
    r = _post("/mitschriften/kurs/lernender", csrf=False, uid=UID, lead_id=lead)
    assert r.status_code == 403 and _z()["kurs_lead_id"] is None


def test_lernender_setzen_privater_kontakt_und_entfernen(ablage):
    _kurs(ablage)
    privat = _lead("Privat Person", privat=True)
    r = _post("/mitschriften/kurs/lernender", uid=UID, lead_id=privat)
    assert r.status_code == 303 and r.headers["location"] == "/mitschriften?rubrik=Kurse"
    assert str(_z()["kurs_lead_id"]) == privat
    assert "Lernende/r: Privat Person" in _get("/mitschriften?rubrik=Kurse").text
    assert _post("/mitschriften/kurs/lernender", uid=UID, lead_id="").status_code == 303
    assert _z()["kurs_lead_id"] is None


def test_lernender_ungueltig(ablage):
    _kurs(ablage)
    assert _post("/mitschriften/kurs/lernender", uid=UID,
                 lead_id="00000000-0000-0000-0000-000000000000").status_code == 400
    assert _post("/mitschriften/kurs/lernender", uid=UID, lead_id="kein-uuid").status_code == 400
    assert _post("/mitschriften/kurs/lernender", uid="gibt-es-nicht",
                 lead_id="").status_code == 404
    assert _z()["kurs_lead_id"] is None


def test_lernender_rollen(ablage):
    _kurs(ablage)
    lead = _lead()
    for rolle in ("lesen", "kalender"):
        r = _post("/mitschriften/kurs/lernender", client=_als(rolle), uid=UID, lead_id=lead)
        assert r.status_code == 403
    assert _z()["kurs_lead_id"] is None
    t = _get("/mitschriften?rubrik=Kurse", _als("lesen")).text
    assert "Kursmitschrift (Felix)" in t and "/mitschriften/kurs/lernender" not in t


def test_suche_findet_private_und_escaped(ablage):
    _kurs(ablage)
    privat = _lead("Zora Suchtreffer", privat=True)
    _lead("Zora_<i>x</i>")
    r = _post("/mitschriften/kurs/suche", uid=UID, q="suchtreffer")
    assert r.status_code == 200 and "Zora Suchtreffer" in r.text and privat in r.text
    assert r.headers["cache-control"] == "private, no-store"
    assert "Zora_<i>" not in _post("/mitschriften/kurs/suche", uid=UID, q="Zora_").text
    assert "Kein Kontakt gefunden" in _post("/mitschriften/kurs/suche", uid=UID,
                                           q="%").text      # % ist wörtlich
    assert _post("/mitschriften/kurs/suche", csrf=False, uid=UID, q="Zora").status_code == 403
    assert _post("/mitschriften/kurs/suche", client=_als("lesen"), uid=UID,
                 q="Zora").status_code == 403


def _loeschantrag(lid):
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "%s, %s::jsonb, true) where id = %s returning id",
              ([server.LOESCH_SCHLUESSEL], json.dumps({"am": "2026-11-19", "quelle": "test"}),
               lid))


def test_lernender_mit_loeschantrag_400(ablage):
    # I3: ein Kontakt mit Loeschantrag wird nicht (wieder) Lernender
    _kurs(ablage)
    lead = _lead("Geloescht Werden")
    _loeschantrag(lead)
    r = _post("/mitschriften/kurs/lernender", uid=UID, lead_id=lead)
    assert r.status_code == 400 and "Löschantrag" in r.text
    assert _z()["kurs_lead_id"] is None


def test_lernender_gesperrt_400(ablage, monkeypatch):
    import sperrliste
    _kurs(ablage)
    lead = _lead("Gesperrt Person")
    email = server._q("select email from leads where id = %s", (lead,))[0]["email"]
    monkeypatch.setattr(sperrliste, "gesperrt", lambda q, email="", phone="", z=email:
                        "marketing: abgemeldet" if email == z else None)
    r = _post("/mitschriften/kurs/lernender", uid=UID, lead_id=lead)
    assert r.status_code == 400 and "Sperre" in r.text
    assert _z()["kurs_lead_id"] is None


def test_suche_ohne_loeschantrag_und_gesperrte(ablage, monkeypatch):
    import sperrliste
    _kurs(ablage)
    da = _lead("Yvo Suchbar")
    weg = _lead("Yvo Loeschantrag")
    _loeschantrag(weg)
    gesperrt = _lead("Yvo Gesperrt")
    email = server._q("select email from leads where id = %s", (gesperrt,))[0]["email"]
    monkeypatch.setattr(sperrliste, "gesperrt", lambda q, email="", phone="", z=email:
                        "marketing: abgemeldet" if email == z else None)
    t = _post("/mitschriften/kurs/suche", uid=UID, q="Yvo").text
    assert da in t and weg not in t and gesperrt not in t


def test_lernender_setzen_laeuft_im_thread(ablage, monkeypatch):
    # Minor 10: DB-Arbeit (Sperren, Rueckbau) nicht auf der Ereignisschleife
    import asyncio
    import kurs_mitschrift
    _kurs(ablage)
    lead = _lead()
    echt = asyncio.to_thread
    gerufen = []

    async def to_thread(fn, *a, **kw):
        gerufen.append(getattr(fn, "__name__", ""))
        return await echt(fn, *a, **kw)

    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    assert _post("/mitschriften/kurs/lernender", uid=UID, lead_id=lead).status_code == 303
    assert kurs_mitschrift.lernender_setzen.__name__ in gerufen
    assert str(_z()["kurs_lead_id"]) == lead


def test_vorschlaege_im_auswahlfeld(ablage):
    _kurs(ablage)
    lead = _lead("Vorschlag Vera")
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id) "
              "values (%s, 'v@x', 'V', 'gast', %s) returning uid", (UID, lead))
    t = _get("/mitschriften?rubrik=Kurse").text
    assert f'<option value="{lead}">Vorschlag Vera</option>' in t


# ---------- Handbuecher ----------

def test_handbuecher_liste_und_pdf(handbuch):
    lead, _k1, _k2 = handbuch
    t = _get("/mitschriften/handbuecher").text
    assert "Anna Lernend" in t and "Stand: 14.11.2026" in t and "1 Sitzung" in t
    assert f"/mitschriften/handbuch?lead={lead}" in t and "Handbuch öffnen" in t
    assert f"/mitschriften/handbuch.pdf?lead={lead}" in t and "PDF herunterladen" in t
    assert "Erstes Kapitel" in t and "1 Fassung" in t and "aus Sitzungen vom 14.11.2026" in t
    h = _get(f"/mitschriften/handbuch?lead={lead}")
    assert h.status_code == 200 and h.text == "<p>HANDBUCH</p>"
    assert h.headers["cache-control"] == "private, no-store"
    assert h.headers["content-security-policy"].startswith("default-src 'none'")
    p = _get(f"/mitschriften/handbuch.pdf?lead={lead}")
    assert p.content == b"%PDF-1.4 handbuch" and p.headers["content-type"] == "application/pdf"
    assert p.headers["content-disposition"] == 'attachment; filename="Kurs-Handbuch_2026-11-14.pdf"'
    assert _get("/mitschriften/handbuch?lead=kein-uuid").status_code == 404
    assert _get(f"/mitschriften/handbuch.pdf?lead={_lead('Ohne')}").status_code == 404


def test_huelle_ohne_knoepfe_markiert(handbuch):
    t = _get("/mitschriften/handbuecher").text
    teil = t[t.index("Huellen Kapitel"):]
    teil = teil[:teil.index("</li>")]
    assert "wird neu aufgebaut" in teil and "<form" not in teil and "<button" not in teil
    assert t.count('name="aktion" value="umbenennen"') == 2     # nur die beiden echten Kapitel


def test_handbuecher_lesen_ohne_formulare(handbuch):
    t = _get("/mitschriften/handbuecher", _als("lesen")).text
    assert "Anna Lernend" in t and "<form" not in t


def test_kapitel_umbenennen(handbuch):
    lead, k1, _k2 = handbuch
    r = _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k1,
              aktion="umbenennen", titel="  Neuer Titel  ")
    assert r.status_code == 303 and r.headers["location"] == "/mitschriften/handbuecher"
    assert _reihenfolge(lead)[0] == "Neuer Titel"
    assert _stand(lead) is None
    assert "Neuer Titel" in _get("/mitschriften/handbuecher").text


@pytest.mark.parametrize("titel", ["", "   ", "x" * 81])
def test_kapitel_titel_ungueltig(handbuch, titel):
    lead, k1, _k2 = handbuch
    r = _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k1,
              aktion="umbenennen", titel=titel)
    assert r.status_code == 400
    assert _reihenfolge(lead)[0] == "Erstes Kapitel" and _stand(lead) is not None
    ok = _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k1,
               aktion="umbenennen", titel="x" * 80)
    assert ok.status_code == 303


def test_kapitel_hoch_runter_und_rand(handbuch):
    lead, k1, k2 = handbuch
    _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k2, aktion="hoch")
    assert _reihenfolge(lead) == ["Zweites Kapitel", "Erstes Kapitel", "Huellen Kapitel"]
    assert _stand(lead) is None
    server._q("update kurs_handbuch set fassungen_stand = now() where lead_id = %s "
              "returning lead_id", (lead,))
    r = _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k2, aktion="hoch")
    assert r.status_code == 303                                  # Rand: kein Fehler ...
    assert _reihenfolge(lead)[0] == "Zweites Kapitel" and _stand(lead) is not None  # ... kein Effekt
    _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k2, aktion="runter")
    assert _reihenfolge(lead) == ["Erstes Kapitel", "Zweites Kapitel", "Huellen Kapitel"]


def test_kapitel_gleiche_reihenfolge_wird_getauscht(handbuch):
    lead, k1, k2 = handbuch
    server._q("update kurs_handbuch_kapitel set reihenfolge = 1 where lead_id = %s "
              "returning id", (lead,))
    server._q("update kurs_handbuch_kapitel set erstellt_am = now() - interval '1 hour' "
              "where id = %s returning id", (k1,))
    _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k2, aktion="hoch")
    assert _reihenfolge(lead)[0] == "Zweites Kapitel"


def test_kapitel_eines_anderen_leads_nicht_aenderbar(handbuch):
    lead, k1, _k2 = handbuch
    fremd = _lead("Fremde Person")
    for aktion, titel in (("umbenennen", "Gekapert"), ("hoch", ""), ("runter", "")):
        r = _post("/mitschriften/handbuch/kapitel", lead=fremd, kapitel_id=k1,
                  aktion=aktion, titel=titel)
        assert r.status_code == 404
    assert _reihenfolge(lead) == ["Erstes Kapitel", "Zweites Kapitel", "Huellen Kapitel"]
    assert _stand(lead) is not None


def test_huellen_kapitel_nicht_aenderbar(handbuch):
    lead, _k1, _k2 = handbuch
    huelle = str(server._q("select id from kurs_handbuch_kapitel where lead_id = %s "
                           "and aktuelle_fassung is null", (lead,))[0]["id"])
    r = _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=huelle,
              aktion="umbenennen", titel="Neu")
    assert r.status_code == 409
    assert _reihenfolge(lead)[-1] == "Huellen Kapitel"


def test_kapitel_csrf_und_ungueltige_ids(handbuch):
    lead, k1, _k2 = handbuch
    assert _post("/mitschriften/handbuch/kapitel", csrf=False, lead=lead, kapitel_id=k1,
                 aktion="hoch").status_code == 403
    assert _post("/mitschriften/handbuch/kapitel", lead="x", kapitel_id="y",
                 aktion="hoch").status_code == 404
    assert _post("/mitschriften/handbuch/kapitel", lead=lead, kapitel_id=k1,
                 aktion="loeschen").status_code == 400


def test_rolle_lesen_darf_nicht_umbenennen(handbuch):
    lead, k1, _k2 = handbuch
    for rolle in ("lesen", "kalender"):
        r = _post("/mitschriften/handbuch/kapitel", client=_als(rolle), lead=lead,
                  kapitel_id=k1, aktion="umbenennen", titel="Gekapert")
        assert r.status_code == 403
    assert _reihenfolge(lead)[0] == "Erstes Kapitel"
    assert _post("/mitschriften/handbuch/ausgeben", client=_als("lesen"),
                 lead=lead).status_code == 403


def test_ausgeben_ruft_modul_und_leitet_um(handbuch, monkeypatch):
    lead, _k1, _k2 = handbuch
    aufrufe = []
    monkeypatch.setattr(kurs_handbuch, "ausgeben", lambda lid: aufrufe.append(lid))
    r = _post("/mitschriften/handbuch/ausgeben", lead=lead)
    assert r.status_code == 303 and r.headers["location"] == "/mitschriften/handbuecher"
    assert aufrufe == [lead]
    assert _post("/mitschriften/handbuch/ausgeben", csrf=False, lead=lead).status_code == 403
    assert aufrufe == [lead]


def test_ausgeben_fehler_ohne_stacktrace(handbuch, monkeypatch, caplog):
    lead, _k1, _k2 = handbuch

    def pdf_kaputt(_lid):
        raise kurs_pdf.PdfFehler("Die PDF-Erzeugung ist nicht eingerichtet.")
    monkeypatch.setattr(kurs_handbuch, "ausgeben", pdf_kaputt)
    r = _post("/mitschriften/handbuch/ausgeben", lead=lead)
    assert r.status_code == 502 and "PDF-Erzeugung" in r.text and "Traceback" not in r.text

    def anders(_lid):
        raise RuntimeError("/geheim/pfad Anna Lernend")
    monkeypatch.setattr(kurs_handbuch, "ausgeben", anders)
    r = _post("/mitschriften/handbuch/ausgeben", lead=lead)
    assert r.status_code == 500 and "geheim" not in r.text and "Traceback" not in r.text
    log = "\n".join(m.getMessage() for m in caplog.records)
    assert "RuntimeError" in log and "geheim" not in log and "Anna" not in log
    assert _post("/mitschriften/handbuch/ausgeben", lead="kein-uuid").status_code == 404


def test_ausgeben_button_text(handbuch):
    assert "Handbuch neu ausgeben" in _get("/mitschriften/handbuecher").text


def test_ausgeben_fehlerarten(handbuch, monkeypatch):
    lead, _k1, _k2 = handbuch
    unbekannt = "00000000-0000-0000-0000-000000000000"
    assert _post("/mitschriften/handbuch/ausgeben", lead=unbekannt).status_code == 404

    def pfad_kaputt(_lid):
        raise ValueError("Ablagepfad ungueltig")
    monkeypatch.setattr(kurs_handbuch, "ausgeben", pfad_kaputt)
    r = _post("/mitschriften/handbuch/ausgeben", lead=lead)
    assert r.status_code == 500 and "gibt es nicht" not in r.text


def test_lernender_nach_rubrikwechsel_409(ablage, monkeypatch):
    import kurs_mitschrift
    _kurs(ablage)
    lead = _lead()
    monkeypatch.setattr(kurs_mitschrift, "lernender_setzen", lambda uid, lid: False)
    r = _post("/mitschriften/kurs/lernender", uid=UID, lead_id=lead)
    assert r.status_code == 409 and "Kurse" in r.text
    assert _post("/mitschriften/kurs/lernender", uid=UID,
                 lead_id="00000000-0000-0000-0000-000000000000").status_code == 400


def test_kapitel_aendern_wartet_auf_kapitelsperre_ohne_deadlock(handbuch):
    """A haelt (wie _zurueckrollen) die Kapitel-Zeilen und nimmt danach die Handbuch-Sperre;
    B (kapitel_aendern) darf in dieser Zeit nicht die Handbuch-Sperre halten und auf die
    Kapitel warten (AB/BA). Beide enden ohne DeadlockDetected, B sieht den neuen Stand."""
    import threading
    import time
    lead, k1, _k2 = handbuch
    ergebnis = {}

    def b():
        try:
            ergebnis["r"] = kurs_handbuch.kapitel_aendern(lead, k1, "umbenennen", "Von B")
        except Exception as err:  # noqa: BLE001
            ergebnis["fehler"] = type(err).__name__

    with server.pool.connection() as a:
        a.execute("select id from kurs_handbuch_kapitel where lead_id = %s order by id "
                  "for update", (lead,)).fetchall()
        t = threading.Thread(target=b)
        t.start()
        time.sleep(1.0)                      # B wartet jetzt auf die Kapitel-Zeilen
        kurs_handbuch._handbuch_sperren(a, lead)
        a.execute("update kurs_handbuch_kapitel set titel = 'Von A' where id = %s", (k1,))
        a.execute("update kurs_handbuch set fassungen_stand = now() where lead_id = %s",
                  (lead,))
    t.join(30)
    assert not t.is_alive()
    assert ergebnis == {"r": "ok"}
    assert _reihenfolge(lead)[0] == "Von B" and _stand(lead) is None


def test_kapitel_aendern_oeffentlich(handbuch):
    lead, k1, _k2 = handbuch
    assert kurs_handbuch.kapitel_aendern(lead, k1, "umbenennen", "Neu") == "ok"
    assert kurs_handbuch.kapitel_aendern(lead, "kein-uuid", "hoch") == "fehlt"
    assert kurs_handbuch.gueltige_id("kein-uuid") is None
