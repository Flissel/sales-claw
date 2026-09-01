"""Vertragstests fuer das Lead-Scoring (01.09.2026).

`leads.score` und `leads.score_breakdown` standen seit Stufe 1 im Schema
und wurden NIE benutzt — dasselbe Muster wie `consent_status` vor dem
UWG-Tor und `status` vor der Pipeline.

DREI SAETZE, DIE DIESE SUITE VERTEIDIGT:

1. Der Score ist RECHENBAR und NACHVOLLZIEHBAR: jede Teilpunktzahl
   steht mit Namen in `score_breakdown`. Eine Zahl ohne Herleitung
   waere eine Behauptung, keine Priorisierung.
2. Er misst NAEHE ZUM ABSCHLUSS aus vorhandenen Beweisen — Stufe,
   Gespraechslage, Bedarfsstand, Erreichbarkeit. Er erfindet nichts
   und ruft nichts Fremdes ab.
3. Er entscheidet NICHTS: kein Versand, keine Stufe, keine Freigabe
   haengt am Score. Er sortiert nur die Aufmerksamkeit des Betreibers.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def saubere_tabellen():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _lead(name="Pia Punktzahl", status="new", phone="+491701112233",
          email=None):
    return str(server._q(
        "insert into leads (name, phone, email, source, status) values "
        "(%s, %s, %s, 'whatsapp', %s) returning id",
        (name, phone, email, status))[0]["id"])


def _aktivitaet(lead, typ, payload=None):
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, %s, %s) returning id",
              (lead, typ, server._json(payload or {"text": "x"})))


def _punkte(lead):
    z = server._q("select score, score_breakdown from leads where id = %s",
                  (lead,))[0]
    return z["score"], z["score_breakdown"]


def _bewerten():
    return json.loads(server.scoring_abgleichen())


# ---------------------------------------------------------------------------
# Die Rechnung
# ---------------------------------------------------------------------------

def test_frischer_kontakt_hat_wenig_punkte():
    lead = _lead()
    _bewerten()
    punkte, herleitung = _punkte(lead)
    assert isinstance(punkte, int)
    assert punkte < 30
    assert isinstance(herleitung, dict)


def test_jede_teilpunktzahl_steht_mit_namen_in_der_herleitung():
    lead = _lead(status="meeting")
    _aktivitaet(lead, "kundenantwort")
    _bewerten()
    punkte, herleitung = _punkte(lead)
    assert set(herleitung) >= {"stufe", "gespraech", "bedarf",
                               "erreichbarkeit"}
    assert sum(int(v) for v in herleitung.values()) == punkte


def test_weiter_in_der_pipeline_gibt_mehr_punkte():
    frueh = _lead(name="Frueh", status="contacted")
    spaet = _lead(name="Spaet", status="meeting", phone="+491702223344")
    _bewerten()
    assert _punkte(spaet)[0] > _punkte(frueh)[0]


def test_wer_geantwortet_hat_zaehlt_mehr_als_wer_schweigt():
    still = _lead(name="Still", status="contacted")
    laut = _lead(name="Laut", status="contacted", phone="+491702223344")
    _aktivitaet(laut, "kundenantwort")
    _bewerten()
    assert _punkte(laut)[0] > _punkte(still)[0]


def test_bedarfsangaben_zaehlen():
    ohne = _lead(name="Ohne")
    mit = _lead(name="Mit", phone="+491702223344")
    server._q(
        "update leads set enrichment = jsonb_set(enrichment, '{bedarf}', "
        "%s::jsonb, true) where id = %s returning id",
        (server._json({"anlass": "Hauskauf", "termin": "Oktober"}), mit))
    _bewerten()
    assert _punkte(mit)[0] > _punkte(ohne)[0]


def test_erreichbarkeit_zaehlt():
    ohne = _lead(name="Ohne Kanal", phone=None)
    mit = _lead(name="Mit Kanal", phone="+491702223344",
                email="mit@beispiel.de")
    _bewerten()
    assert _punkte(mit)[0] > _punkte(ohne)[0]


def test_der_score_bleibt_in_seinen_grenzen():
    lead = _lead(status="meeting", email="a@b.de")
    _aktivitaet(lead, "kundenantwort")
    server._q(
        "update leads set consent_status = 'opt_in', enrichment = "
        "jsonb_set(enrichment, '{bedarf}', %s::jsonb, true) where id = %s "
        "returning id",
        (server._json({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}), lead))
    _bewerten()
    punkte, _ = _punkte(lead)
    assert 0 <= punkte <= 100


# ---------------------------------------------------------------------------
# Die Grenzen
# ---------------------------------------------------------------------------

def test_abgeschlossene_kontakte_werden_nicht_bewertet():
    """Gewonnen und verloren sind fertig — eine Priorisierung waere
    sinnlos und wuerde die Liste verstopfen."""
    gewonnen = _lead(name="Gewonnen", status="won")
    verloren = _lead(name="Verloren", status="lost",
                     phone="+491702223344")
    _bewerten()
    assert _punkte(gewonnen)[0] is None
    assert _punkte(verloren)[0] is None


def test_private_archivierte_und_systemkontakte_bleiben_unbewertet(
        monkeypatch):
    privat = _lead(name="Lisa Privat")
    server._q("update leads set enrichment = '{\"_privat\": {}}'::jsonb "
              "where id = %s returning id", (privat,))
    archiv = _lead(name="Alt", phone="+491702223344")
    server._q("update leads set enrichment = "
              "'{\"archiviert\": {\"archiviert\": true}}'::jsonb "
              "where id = %s returning id", (archiv,))
    system = _lead(name="LINKEDIN", phone="+491703334455")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", system)
    _bewerten()
    for lead in (privat, archiv, system):
        assert _punkte(lead)[0] is None


def test_zweiter_lauf_liefert_dasselbe():
    lead = _lead(status="replied")
    _aktivitaet(lead, "kundenantwort")
    _bewerten()
    erst = _punkte(lead)
    _bewerten()
    assert _punkte(lead) == erst


def test_der_lauf_meldet_die_bilanz():
    _lead(status="meeting")
    _lead(name="Zwei", phone="+491702223344")
    ergebnis = _bewerten()
    assert ergebnis["bewertet"] == 2
    assert len(ergebnis["spitzenreiter"]) <= 10
    assert ergebnis["spitzenreiter"][0]["punkte"] >= \
        ergebnis["spitzenreiter"][-1]["punkte"]


def test_scoring_aendert_niemals_die_stufe():
    lead = _lead(status="contacted")
    _aktivitaet(lead, "kundenantwort")
    _bewerten()
    assert server._q("select status from leads where id = %s",
                     (lead,))[0]["status"] == "contacted"


def test_der_digest_nennt_die_wichtigsten():
    lead = _lead(name="Wichtig", status="meeting")
    _aktivitaet(lead, "kundenantwort")
    _bewerten()
    d = json.loads(server.digest())
    assert "wichtigste_kontakte" in d
    assert d["wichtigste_kontakte"][0]["kontakt"] == "Wichtig"
    assert d["wichtigste_kontakte"][0]["punkte"] > 0


# ---------------------------------------------------------------------------
# Betriebsgroesse (01.09.2026): fuer die bAV ist die Mitarbeiterzahl DIE
# Kennzahl — 24 Mitarbeiter sind 24 moegliche Vertraege. Sie steht laengst
# im Profil (firma_anreichern liest sie aus dem Impressum), wurde aber nie
# fuer die Priorisierung benutzt.
# ---------------------------------------------------------------------------

def _mit_firma(lead, hinweise):
    server._q(
        "update leads set enrichment = jsonb_set(enrichment, '{firma}', "
        "%s::jsonb, true) where id = %s returning id",
        (server._json({"website": "https://x.de", "hinweise": hinweise}),
         lead))


def test_grosser_betrieb_schlaegt_kleinen():
    klein = _lead(name="Klein")
    gross = _lead(name="Gross", phone="+491702223344")
    _mit_firma(klein, {"mitarbeiter_genannt": "3"})
    _mit_firma(gross, {"mitarbeiter_genannt": "45"})
    _bewerten()
    assert _punkte(gross)[0] > _punkte(klein)[0]
    assert _punkte(gross)[1]["betrieb"] > _punkte(klein)[1]["betrieb"]


def test_ohne_mitarbeiterzahl_null_punkte_statt_raten():
    lead = _lead()
    _mit_firma(lead, {"vertretung": "Denis Mustermann"})
    _bewerten()
    assert _punkte(lead)[1]["betrieb"] == 0


def test_uneindeutige_mitarbeiterzahl_zaehlt_nicht():
    """`firma_anreichern` legt bei mehreren Fundstellen KANDIDATEN ab und
    nennt die Zahl ausdruecklich uneindeutig — darauf wird nicht
    priorisiert."""
    lead = _lead()
    _mit_firma(lead, {"mitarbeiter_kandidaten": ["12", "40"]})
    _bewerten()
    assert _punkte(lead)[1]["betrieb"] == 0


def test_unsinnige_zahl_wird_ignoriert():
    for wert in ("keine", "", "0", "999999", None):
        lead = _lead(name=f"X{wert}", phone=None)
        _mit_firma(lead, {"mitarbeiter_genannt": wert})
        _bewerten()
        assert _punkte(lead)[1]["betrieb"] == 0, wert


def test_die_herleitung_nennt_den_betrieb():
    lead = _lead()
    _mit_firma(lead, {"mitarbeiter_genannt": "24"})
    _bewerten()
    punkte, herleitung = _punkte(lead)
    assert "betrieb" in herleitung
    assert herleitung["betrieb"] > 0
    assert sum(int(v) for v in herleitung.values()) == punkte
