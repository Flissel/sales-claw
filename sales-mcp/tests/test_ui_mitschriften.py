"""Hauptpunkt „Mitschriften“ (Mitschriften-Ablage, Task 5): Reiter, Liste, Bericht, Verschieben.

Datenbank sales_test; Ablage: tmp_path (MITSCHRIFTEN_PFAD)."""
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import mitschrift_bericht as mb  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"
BEGINN = datetime(2026, 11, 14, 9, 5, tzinfo=timezone.utc)
SEG = [{"sprecher": "Diana", "beginn": "2026-11-14T09:06:00Z", "text": "Hallo", "sprache": "de"}]


@pytest.fixture(autouse=True)
def ablage(monkeypatch, tmp_path):
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(tmp_path / "ablage"))
    (tmp_path / "ablage").mkdir()
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield tmp_path / "ablage"


@pytest.fixture
def scharf():
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-diese-datei"
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    yield
    ui.UI_SESSION_SECRET = vorher
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})


def _mit(uid, titel="Kurs Eins", rubrik="Kurse", tage=0, bericht=True, kurz="Kurzfassung",
         beteiligte=("Diana", "Felix")):
    beginn = BEGINN + timedelta(days=tage)
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, %s, 'fertig') returning uid",
              (uid, beginn, beginn + timedelta(hours=1), titel))
    aj = {"kurzfassung": kurz, "beteiligte": list(beteiligte), "verlauf": []}
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_md, auswertung_am, rubrik) "
              "values (%s, %s::jsonb, 'fertig', %s::jsonb, '## E', now(), %s) returning id",
              (uid, json.dumps(SEG), json.dumps(aj), rubrik))
    if bericht:
        assert mb.ablegen(uid)


def _z(uid):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def _get(pfad, client=CLIENT):
    return client.get(pfad, headers={"host": HOST_OK}, follow_redirects=False)


def _post(csrf=True, client=CLIENT, **felder):
    if csrf:
        felder["csrf"] = ui.CSRF_TOKEN
    return client.post("/mitschriften/verschieben", data=felder,
                       headers={"host": HOST_OK}, follow_redirects=False)


def _anmelden(name, rolle, passwort="mitschrift-passwort-9"):
    import benutzer_anlegen
    assert benutzer_anlegen.anlegen(name, rolle, passwort).startswith("OK")
    client = TestClient(ui.app)
    a = client.post("/login", data={"name": name, "passwort": passwort, "csrf": ui.CSRF_TOKEN},
                    headers={"host": HOST_OK}, follow_redirects=False)
    assert a.status_code == 303
    return client


def test_liste_reiter_mit_anzahl():
    _mit("a@x", titel="Alt", rubrik="Kurse", tage=0, kurz="K" * 300)
    _mit("b@x", titel="Neu", rubrik="Kurse", tage=3)
    _mit("c@x", titel="Kunde", rubrik="Kundentermine", tage=1)
    _mit("d@x", titel="Rest", rubrik="Unsortiert", tage=1)
    s = _get("/mitschriften?rubrik=Kurse")
    assert s.status_code == 200
    t = s.text
    assert "Kurse" in t and "Kundentermine" in t
    reiter = t[t.index('class="reiter"'):]
    reiter = reiter[:reiter.index("</nav>")]
    assert '<span class="zahl">2</span>' in reiter
    assert reiter.index("Kundentermine") < reiter.index("Unsortiert")
    assert reiter.index("Kurse") < reiter.index("Unsortiert")
    assert t.index("Neu") < t.index("Alt")          # neueste zuerst
    assert "Diana" in t and "Felix" in t
    assert "14.11.2026" in t
    assert "K" * 240 in t and "K" * 241 not in t
    assert "Bericht öffnen" in t and "HTML herunterladen" in t and "Akte" in t
    assert f'href="/termine/{quote("a@x", safe="")}"' in t
    assert f"/mitschriften/bericht?uid={quote('a@x', safe='')}" in t
    assert "Rest" not in t.split("</nav>", 1)[1]    # andere Rubrik nicht in der Liste


def test_ohne_rubrik_gilt_erster_reiter():
    _mit("a@x", titel="Alpha", rubrik="Kundentermine")
    _mit("c@x", titel="Beta", rubrik="Kurse")
    t = _get("/mitschriften").text
    assert "Alpha" in t and "Beta" not in t


def test_leere_ablage():
    assert _get("/mitschriften").status_code == 200


def test_ohne_bericht_hinweis():
    _mit("a@x", bericht=False)
    t = _get("/mitschriften?rubrik=Kurse").text
    assert "Bericht wird erstellt" in t
    assert "Bericht öffnen" not in t and "/mitschriften/bericht" not in t


def test_bericht_ausliefern():
    _mit("a@x")
    pfad = mb.sicherer_pfad(_z("a@x")["bericht_pfad"])
    a = _get("/mitschriften/bericht?uid=" + quote("a@x", safe=""))
    assert a.status_code == 200
    assert a.headers["content-type"].startswith("text/html")
    assert a.headers["cache-control"] == "private, no-store"
    csp = a.headers["content-security-policy"]
    assert csp == ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
                   "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    assert "script-src" not in csp
    assert a.text == pfad.read_text(encoding="utf-8")


def test_bericht_download():
    _mit("a@x")
    name = os.path.basename(_z("a@x")["bericht_pfad"])
    a = _get("/mitschriften/bericht?download=1&uid=" + quote("a@x", safe=""))
    assert a.status_code == 200
    assert a.headers["content-disposition"] == f'attachment; filename="{name}"'


def test_bericht_fehlt_404(ablage, tmp_path):
    uid = quote("a@x", safe="")
    _mit("a@x")
    assert _get("/mitschriften/bericht?uid=unbekannt").status_code == 404
    assert _get("/mitschriften/bericht").status_code == 404
    außen = tmp_path / "x.html"
    außen.write_text("AUSSEN-GEHEIM", encoding="utf-8")
    server._q("update termin_mitschriften set bericht_pfad = '../x.html' where uid = 'a@x' "
              "returning id")
    a = _get("/mitschriften/bericht?uid=" + uid)
    assert a.status_code == 404 and "AUSSEN-GEHEIM" not in a.text
    server._q("update termin_mitschriften set bericht_pfad = 'Kurse/weg.html' where uid = 'a@x' "
              "returning id")
    assert _get("/mitschriften/bericht?uid=" + uid).status_code == 404


def test_verschieben(ablage):
    _mit("a@x", rubrik="Unsortiert")
    alt = mb.sicherer_pfad(_z("a@x")["bericht_pfad"])
    assert alt.is_file()
    a = _post(uid="a@x", rubrik="Kurse", neue_rubrik="")
    assert a.status_code == 303
    assert parse_qs(urlsplit(a.headers["location"]).query)["rubrik"] == ["Kurse"]
    z = _z("a@x")
    assert z["rubrik"] == "Kurse" and z["rubrik_manuell"] is True
    assert z["bericht_pfad"].split("/")[0] == "Kurse"
    assert mb.sicherer_pfad(z["bericht_pfad"]).is_file() and not alt.exists()
    assert (ablage / "Kurse").is_dir()


def test_verschieben_neue_rubrik_trotz_zwoelf(ablage):
    for i in range(12):
        _mit(f"r{i}@x", titel=f"T{i}", rubrik=f"Rubrik {i}", bericht=False)
    _mit("a@x", rubrik="Rubrik 0")
    a = _post(uid="a@x", rubrik="Rubrik 0", neue_rubrik="Workshops")
    assert a.status_code == 303
    assert _z("a@x")["rubrik"] == "Workshops"
    assert _z("a@x")["bericht_pfad"].startswith("Workshops/")
    # Schreibweise wird an eine vorhandene angeglichen
    b = _post(uid="a@x", rubrik="x", neue_rubrik="rubrik 3")
    assert b.status_code == 303 and _z("a@x")["rubrik"] == "Rubrik 3"


def test_verschieben_ungueltig(ablage):
    _mit("a@x")
    vorher = _z("a@x")
    a = _post(uid="a@x", rubrik="Kurse", neue_rubrik="../..")
    assert a.status_code == 400
    z = _z("a@x")
    assert z["rubrik"] == vorher["rubrik"] and z["bericht_pfad"] == vorher["bericht_pfad"]
    assert z["rubrik_manuell"] is False
    assert _post(uid="gibt-es-nicht", rubrik="Kurse").status_code == 404


def test_verschieben_ablegen_fehler(monkeypatch):
    _mit("a@x", rubrik="Unsortiert")

    def kaputt(uid):
        raise OSError("/geheim/pfad")
    monkeypatch.setattr(mb, "ablegen", kaputt)
    a = _post(uid="a@x", rubrik="Kurse")
    assert a.status_code == 303
    assert _z("a@x")["rubrik"] == "Kurse" and _z("a@x")["rubrik_manuell"] is True


def _unveraendert(uid="a@x"):
    z = _z(uid)
    assert z["rubrik"] == "Unsortiert" and z["rubrik_manuell"] is False


def test_verschieben_csrf_im_handler(scharf):
    """Angemeldet mit schreibender Rolle: die Pruefung des Handlers greift, nicht die Wache."""
    _mit("a@x", rubrik="Unsortiert")
    frei = _anmelden("fred", "freigeben")
    a = _post(csrf=False, client=frei, uid="a@x", rubrik="Kurse")
    assert a.status_code == 403 and "CSRF" in a.text
    _unveraendert()
    b = frei.post("/mitschriften/verschieben",
                  data={"uid": "a@x", "rubrik": "Kurse", "csrf": "falsches-token"},
                  headers={"host": HOST_OK}, follow_redirects=False)
    assert b.status_code == 403 and "CSRF" in b.text
    _unveraendert()
    assert _post(client=frei, uid="a@x", rubrik="Kurse").status_code == 303   # Gegenprobe


def test_verschieben_rolle_lesen_im_handler():
    """Die Wache ist hier offen; nur die Rollenpruefung des Handlers haelt Lesen ab."""
    _mit("a@x", rubrik="Unsortiert")

    async def als_lesen(scope, receive, send):
        if scope["type"] == "http":
            scope["benutzer_name"], scope["benutzer_rolle"] = "lena", "lesen"
        await ui.app(scope, receive, send)
    client = TestClient(als_lesen)
    a = _post(client=client, uid="a@x", rubrik="Kurse")
    assert a.status_code == 403 and "Nur Lesen" in a.text
    _unveraendert()


def test_verschieben_rechte(scharf):
    _mit("a@x", rubrik="Unsortiert")
    assert _post(csrf=False, uid="a@x", rubrik="Kurse").status_code == 403
    lesen = _anmelden("lena", "lesen")
    assert _post(client=lesen, uid="a@x", rubrik="Kurse").status_code == 403
    _unveraendert()
    t = _get("/mitschriften?rubrik=Unsortiert", lesen)
    assert t.status_code == 200 and "Bericht öffnen" in t.text
    assert "/mitschriften/verschieben" not in t.text
    kal = _anmelden("kai", "kalender")
    assert not ui._pfad_erlaubt("kalender", "/mitschriften")
    assert not ui._pfad_erlaubt("kalender", "/mitschriften/bericht")
    assert _get("/mitschriften", kal).status_code == 403
    assert _get("/mitschriften/bericht?uid=a%40x", kal).status_code == 403
    assert _post(client=kal, uid="a@x", rubrik="Kurse").status_code == 403
    assert "/mitschriften" not in {p for _, e in ui._menue_gruppen("kalender") for p, _ in e}


def test_schreibende_rolle_sieht_formular():
    _mit("a@x")
    t = _get("/mitschriften?rubrik=Kurse").text
    assert 'action="/mitschriften/verschieben"' in t
    assert 'name="neue_rubrik"' in t and f'name="csrf" value="{ui.CSRF_TOKEN}"' in t


def test_ohne_anmeldung(scharf):
    _mit("a@x")
    for pfad in ("/mitschriften", "/mitschriften/bericht?uid=a%40x"):
        a = _get(pfad)
        assert a.status_code in (302, 303)
        assert a.headers["location"].startswith("/login")


def test_menue():
    t = _get("/mitschriften").text
    assert "Mitschriften" in t and 'href="/mitschriften"' in t
    namen = [g for g, _ in ui._GRUPPEN]
    assert namen.index("Analyse") < namen.index("Mitschriften") < namen.index("Daten")
