"""Wartelisten-Abgleich: Lesen und Planen - ohne Datenbank.

Die Datenbankseite steht in test_warteliste_abgleich.py."""
import pytest

import warteliste_abgleich as wa

T1 = "2025-11-07T08:10:57.123456+00:00"
T2 = "2026-03-01T12:00:00+00:00"
T3 = "2026-11-20T09:30:00+00:00"


def _zeile(email, created=T1, confirmed=None, source="legacy"):
    return {"email": email, "created_at": created, "confirmed_at": confirmed, "source": source}


def _dok(*zeilen):
    return {"generated_at": T3, "count": len(zeilen), "rows": list(zeilen)}


def _merkmal(created=T1, confirmed=None, source="legacy", auf_liste=True):
    return {"auf_liste": auf_liste, "angemeldet_am": wa._zeitpunkt(created),
            "bestaetigt_am": wa._zeitpunkt(confirmed), "herkunft": source}


def _kontakt(id_, email, merkmal=None, **weitere):
    e = dict(weitere)
    if merkmal is not None:
        e[wa.MERKMAL] = merkmal
    return {"id": id_, "email": email, "enrichment": e}


# --- Lesen ---------------------------------------------------------------------

def test_lesen_normalisiert_und_zaehlt_unbrauchbares():
    eintraege, unbrauchbar = wa.eintraege_lesen(_dok(
        _zeile("  Anna@Example.org "),
        _zeile("anna@example.org", created=T2),          # doppelt: zaehlt einmal, erste gewinnt
        _zeile("kein-at-zeichen"),
        _zeile("b@example.org", created="gestern"),
        _zeile("c@example.org", source="import"),
        _zeile("d@example.org", confirmed="irgendwann"),
        "keine Zeile",
        _zeile("e@example.org", created=T2, confirmed=T3, source="form")))
    assert sorted(eintraege) == ["anna@example.org", "e@example.org"]
    assert unbrauchbar == 5
    assert eintraege["anna@example.org"] == _merkmal()
    assert eintraege["e@example.org"] == _merkmal(T2, T3, "form")


def test_lesen_ohne_zone_ist_unbrauchbar():
    eintraege, unbrauchbar = wa.eintraege_lesen(_dok(_zeile("a@example.org", created="2025-11-07T08:10:57")))
    assert eintraege == {} and unbrauchbar == 1


@pytest.mark.parametrize("dokument", [
    None, [], {}, {"rows": "x"}, {"code": "42501", "message": "not allowed"},
    {"count": 3, "rows": [_zeile("a@example.org")]},      # abgeschnitten
    {"rows": [_zeile("a@example.org")]},                   # count fehlt
])
def test_lesen_weist_fremde_und_abgeschnittene_dokumente_ab(dokument):
    with pytest.raises(wa.EingabeFehler):
        wa.eintraege_lesen(dokument)


def test_name_und_notiz():
    assert wa.kontaktname("max.mustermann@example.org") == "max.mustermann"
    text = wa.notiz(_merkmal("2025-11-07T23:30:00+00:00"))
    assert text.startswith("Waitinglist")
    assert "08.11.2025" in text                # Berliner Datum, nicht UTC
    assert "keine Werbe-Einwilligung" in text


# --- Planen --------------------------------------------------------------------

def _plan(dokument, bestand=(), gesperrt=(), **kw):
    eintraege, _ = wa.eintraege_lesen(dokument)
    return wa.planen(eintraege, bestand, set(gesperrt), **kw)


def test_neue_adresse_wird_angelegt():
    plan = _plan(_dok(_zeile("a@example.org")))
    assert plan["anlegen"] == [("a@example.org", _merkmal())]
    assert plan["kennzeichnen"] == [] and plan["austragen"] == []
    assert plan["zahlen"]["angelegt"] == 1 and plan["zahlen"]["auf_der_liste"] == 1


def test_bekannte_adresse_wird_nur_gekennzeichnet():
    plan = _plan(_dok(_zeile("a@example.org")), [_kontakt("k1", "a@example.org", art="person")])
    assert plan["anlegen"] == []
    assert plan["kennzeichnen"] == [("k1", _merkmal())]
    assert plan["zahlen"]["gekennzeichnet"] == 1


def test_zweiter_lauf_aendert_nichts():
    plan = _plan(_dok(_zeile("a@example.org")), [_kontakt("k1", "a@example.org", _merkmal())])
    assert plan["anlegen"] == [] and plan["kennzeichnen"] == [] and plan["austragen"] == []
    assert plan["zahlen"]["unveraendert"] == 1


def test_bestaetigung_wird_nachgetragen():
    plan = _plan(_dok(_zeile("a@example.org", confirmed=T3)),
                 [_kontakt("k1", "a@example.org", _merkmal())])
    assert plan["kennzeichnen"] == [("k1", _merkmal(confirmed=T3))]
    assert plan["zahlen"]["aktualisiert"] == 1 and plan["zahlen"]["gekennzeichnet"] == 0


def test_gesperrte_adresse_wird_nicht_angelegt():
    plan = _plan(_dok(_zeile("a@example.org"), _zeile("b@example.org", created=T2)),
                 gesperrt={"a@example.org"})
    assert [a for a, _ in plan["anlegen"]] == ["b@example.org"]
    assert plan["zahlen"]["gesperrt"] == 1


def test_gesperrt_trifft_keinen_bestehenden_kontakt():
    """Die Verbotsliste verhindert das ANLEGEN. Ein Kontakt, den es schon gibt,
    behaelt seine Kennzeichnung - sie sagt nur, woher er kommt."""
    plan = _plan(_dok(_zeile("a@example.org")), [_kontakt("k1", "a@example.org")],
                 gesperrt={"a@example.org"})
    assert plan["kennzeichnen"] == [("k1", _merkmal())]
    assert plan["zahlen"]["gesperrt"] == 0


def test_hoechstens_legt_die_aeltesten_zuerst_an():
    plan = _plan(_dok(_zeile("c@example.org", created=T3), _zeile("a@example.org", created=T1),
                      _zeile("b@example.org", created=T2)), hoechstens=2)
    assert [a for a, _ in plan["anlegen"]] == ["a@example.org", "b@example.org"]
    assert plan["zahlen"]["angelegt"] == 2 and plan["zahlen"]["zurueckgestellt"] == 1


def test_hoechstens_bremst_das_kennzeichnen_nicht():
    plan = _plan(_dok(_zeile("a@example.org"), _zeile("b@example.org")),
                 [_kontakt("k1", "a@example.org")], hoechstens=0)
    assert plan["anlegen"] == [] and plan["kennzeichnen"] == [("k1", _merkmal())]
    assert plan["zahlen"]["zurueckgestellt"] == 1


def test_wer_die_liste_verlaesst_wird_ausgetragen_nicht_geloescht():
    plan = _plan(_dok(_zeile("a@example.org")),
                 [_kontakt("k1", "a@example.org", _merkmal()),
                  _kontakt("k2", "weg@example.org", _merkmal())])
    assert plan["austragen"] == ["k2"]
    assert plan["zahlen"]["ausgetragen"] == 1


def test_schon_ausgetragene_bleiben_in_ruhe():
    plan = _plan(_dok(_zeile("a@example.org")),
                 [_kontakt("k2", "weg@example.org", _merkmal(auf_liste=False))])
    assert plan["austragen"] == []


def test_rueckkehr_auf_die_liste_kennzeichnet_neu():
    plan = _plan(_dok(_zeile("a@example.org")),
                 [_kontakt("k1", "a@example.org", {**_merkmal(auf_liste=False), "ausgetragen_am": T2})])
    assert plan["kennzeichnen"] == [("k1", _merkmal())]
    assert plan["zahlen"]["aktualisiert"] == 1


def test_bei_doppelter_adresse_traegt_der_aelteste_kontakt_das_merkmal():
    plan = _plan(_dok(_zeile("a@example.org")),
                 [_kontakt("alt", "a@example.org"), _kontakt("jung", "a@example.org", _merkmal())])
    assert plan["kennzeichnen"] == [("alt", _merkmal())]
    assert plan["austragen"] == ["jung"]


def test_kontakt_ohne_adresse_stoert_nicht():
    plan = _plan(_dok(_zeile("a@example.org")), [_kontakt("k0", None), _kontakt("k1", None, art="firma")])
    assert [a for a, _ in plan["anlegen"]] == ["a@example.org"]
    assert plan["austragen"] == []


def test_schwund_sperre_traegt_niemanden_aus():
    bestand = [_kontakt(f"k{i}", f"p{i}@example.org", _merkmal()) for i in range(40)]
    plan = _plan(_dok(*[_zeile(f"p{i}@example.org") for i in range(15)]), bestand)
    assert plan["austragen"] == []
    assert plan["zahlen"]["austragen_gestoppt"] == 25 and plan["zahlen"]["ausgetragen"] == 0
    assert plan["zahlen"]["unveraendert"] == 15


def test_kleiner_schwund_ist_normal():
    bestand = [_kontakt(f"k{i}", f"p{i}@example.org", _merkmal()) for i in range(200)]
    plan = _plan(_dok(*[_zeile(f"p{i}@example.org") for i in range(175)]), bestand)
    assert len(plan["austragen"]) == 25                 # 12,5 % - unter der Schwelle
    assert plan["zahlen"]["austragen_gestoppt"] == 0


def test_wenige_abgaenge_loesen_die_sperre_nie_aus():
    bestand = [_kontakt(f"k{i}", f"p{i}@example.org", _merkmal()) for i in range(5)]
    plan = _plan(_dok(_zeile("p0@example.org")), bestand)
    assert len(plan["austragen"]) == 4 and plan["zahlen"]["austragen_gestoppt"] == 0
