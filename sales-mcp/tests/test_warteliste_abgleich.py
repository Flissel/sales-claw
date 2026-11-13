"""Wartelisten-Abgleich gegen die Datenbank (Schema sales_test).

Lesen und Planen ohne Datenbank: test_warteliste_abgleich_plan.py."""
import io
import json
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import server  # noqa: E402
import sperrliste  # noqa: E402
import warteliste_abgleich as wa  # noqa: E402

T1 = "2025-11-07T08:10:57+00:00"
T2 = "2026-03-01T12:00:00+00:00"
T3 = "2026-11-20T09:30:00+00:00"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"
    assert sperrliste.SCHEMA == "compliance_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
        conn.execute("delete from compliance_test.sperrliste where kennung like 'email:wl-%%'")
    yield
    with server.pool.connection() as conn:
        conn.execute("delete from compliance_test.sperrliste where kennung like 'email:wl-%%'")


def _zeile(email, created=T1, confirmed=None, source="legacy"):
    return {"email": email, "created_at": created, "confirmed_at": confirmed, "source": source}


def _dok(*zeilen):
    return {"generated_at": T3, "count": len(zeilen), "rows": list(zeilen)}


def _leads():
    return server._q("select id, name, email, source, consent_status, status, notes, "
                     "enrichment, created_at, updated_at from leads order by created_at, email")


def test_erster_lauf_legt_kontakte_ohne_freigabe_an():
    zahlen = wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org"),
                                           _zeile("wl-ben@example.org", T2, T3, "form")))
    assert zahlen["angelegt"] == 2 and zahlen["auf_der_liste"] == 2 and zahlen["trocken"] is False
    anna, ben = _leads()
    assert (anna["name"], anna["email"], anna["source"]) == ("wl-anna", "wl-anna@example.org", "waitinglist")
    assert anna["consent_status"] == "unknown" and anna["status"] == "new"
    assert anna["notes"].startswith("Waitinglist")
    assert anna["enrichment"]["art"] == "person"
    assert anna["enrichment"]["waitinglist"] == {
        "auf_liste": True, "angemeldet_am": T1, "bestaetigt_am": None, "herkunft": "legacy"}
    # Anlagedatum = Anmeldedatum: neue Wartelisten-Kontakte stehen nicht als
    # "zuletzt geaendert" vor der laufenden Arbeit.
    assert anna["created_at"].isoformat() == T1 and anna["updated_at"].isoformat() == T1
    assert ben["enrichment"]["waitinglist"]["bestaetigt_am"] == T3
    assert ben["enrichment"]["waitinglist"]["herkunft"] == "form"
    # keine Werbe-Grundlage gebucht, kein Protokolleintrag einer Einwilligung
    assert server._q("select 1 from activities") == []


def test_zweiter_lauf_legt_nichts_doppelt_an():
    dok = _dok(_zeile("wl-anna@example.org"))
    wa.abgleichen(server._q, dok)
    vorher = _leads()
    zahlen = wa.abgleichen(server._q, dok)
    assert zahlen["angelegt"] == 0 and zahlen["unveraendert"] == 1
    assert _leads() == vorher


def test_bestehender_kontakt_wird_nur_gekennzeichnet():
    alt = server._q("insert into leads (name, email, source, consent_status, notes, enrichment) "
                    "values ('Anna Alt', 'WL-Anna@Example.org', 'visitenkarte', 'opt_in', "
                    "'Messe', '{\"art\": \"person\", \"profil\": {\"x\": 1}}'::jsonb) returning id")[0]["id"]
    zahlen = wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org")))
    assert zahlen["gekennzeichnet"] == 1 and zahlen["angelegt"] == 0
    (lead,) = _leads()
    assert lead["id"] == alt
    assert (lead["name"], lead["email"], lead["source"]) == ("Anna Alt", "WL-Anna@Example.org", "visitenkarte")
    assert lead["consent_status"] == "opt_in" and lead["notes"] == "Messe"
    assert lead["enrichment"]["profil"] == {"x": 1}
    assert lead["enrichment"]["waitinglist"]["auf_liste"] is True


def test_adresse_auf_der_verbotsliste_wird_nicht_angelegt():
    sperrliste.sperren(server._q, email="wl-nein@example.org", quelle="test", grund="abgemeldet")
    zahlen = wa.abgleichen(server._q, _dok(_zeile("wl-nein@example.org"), _zeile("wl-ja@example.org")))
    assert zahlen["gesperrt"] == 1 and zahlen["angelegt"] == 1
    assert [z["email"] for z in _leads()] == ["wl-ja@example.org"]


def test_bestaetigung_wird_nachgetragen():
    wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org", source="form", confirmed=T2)))
    zahlen = wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org", source="form", confirmed=T3)))
    assert zahlen["aktualisiert"] == 1
    (lead,) = _leads()
    assert lead["enrichment"]["waitinglist"]["bestaetigt_am"] == T3
    assert lead["enrichment"]["art"] == "person"


def test_abgang_wird_ausgetragen_und_rueckkehr_neu_gekennzeichnet():
    wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org"), _zeile("wl-ben@example.org")))
    zahlen = wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org")))
    assert zahlen["ausgetragen"] == 1
    ben = [z for z in _leads() if z["email"] == "wl-ben@example.org"][0]
    merkmal = ben["enrichment"]["waitinglist"]
    assert merkmal["auf_liste"] is False and merkmal["ausgetragen_am"]
    assert merkmal["angemeldet_am"] == T1               # der Rest bleibt lesbar
    # ein weiterer Lauf traegt nicht noch einmal aus
    assert wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org")))["ausgetragen"] == 0
    # zurueck auf der Liste
    zahlen = wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org"), _zeile("wl-ben@example.org")))
    assert zahlen["aktualisiert"] == 1
    ben = [z for z in _leads() if z["email"] == "wl-ben@example.org"][0]
    assert ben["enrichment"]["waitinglist"] == {
        "auf_liste": True, "angemeldet_am": T1, "bestaetigt_am": None, "herkunft": "legacy"}


def test_trocken_schreibt_nichts():
    zahlen = wa.abgleichen(server._q, _dok(_zeile("wl-anna@example.org")), trocken=True)
    assert zahlen["angelegt"] == 1 and zahlen["trocken"] is True
    assert _leads() == []


def test_hoechstens_begrenzt_den_ersten_lauf():
    dok = _dok(*[_zeile(f"wl-{i}@example.org") for i in range(5)])
    zahlen = wa.abgleichen(server._q, dok, hoechstens=2)
    assert zahlen["angelegt"] == 2 and zahlen["zurueckgestellt"] == 3
    assert len(_leads()) == 2
    zahlen = wa.abgleichen(server._q, dok)
    assert zahlen["angelegt"] == 3 and zahlen["unveraendert"] == 2
    assert len(_leads()) == 5


def test_schwund_sperre_laesst_die_kennzeichnung_stehen(capsys):
    wa.abgleichen(server._q, _dok(*[_zeile(f"wl-{i}@example.org") for i in range(30)]))
    code = wa.main(["abgleichen"], io.StringIO(json.dumps(_dok(_zeile("wl-0@example.org")))))
    assert code == 4
    aus = capsys.readouterr()
    assert json.loads(aus.out)["austragen_gestoppt"] == 29
    assert "Schwund-Sperre" in aus.err
    assert all(z["enrichment"]["waitinglist"]["auf_liste"] is True for z in _leads())


def test_cli_gibt_nur_zahlen_aus(capsys):
    code = wa.main(["abgleichen", "--hoechstens", "1"], io.StringIO(json.dumps(
        _dok(_zeile("wl-anna@example.org"), _zeile("wl-ben@example.org", T2)))))
    assert code == 0
    aus = capsys.readouterr()
    zahlen = json.loads(aus.out)
    assert zahlen["angelegt"] == 1 and zahlen["zurueckgestellt"] == 1
    assert "@" not in aus.out and "@" not in aus.err


@pytest.mark.parametrize("eingabe", [
    "", "   \n", "kein json",
    json.dumps({"code": "42501", "message": "waitlist_export: not allowed"}),
    json.dumps({"count": 2, "rows": [_zeile("wl-anna@example.org")]}),
    json.dumps({"count": 1, "rows": [_zeile("kaputt")]}),
])
def test_unbrauchbare_eingabe_schreibt_nichts(eingabe, capsys):
    server._q("insert into leads (name, email, source, enrichment) values ('X', 'wl-x@example.org', "
              "'waitinglist', '{\"waitinglist\": {\"auf_liste\": true}}'::jsonb) returning id")
    assert wa.main(["abgleichen"], io.StringIO(eingabe)) == 2
    assert "nichts geaendert" in capsys.readouterr().err
    (lead,) = _leads()
    assert lead["enrichment"]["waitinglist"] == {"auf_liste": True}


def test_unbekanntes_argument_bricht_ab(capsys):
    assert wa.main(["abgleichen", "--loeschen"], io.StringIO(json.dumps(_dok(_zeile("wl-a@example.org"))))) == 2
    assert _leads() == []
