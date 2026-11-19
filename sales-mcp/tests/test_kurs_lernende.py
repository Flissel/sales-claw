"""Kursmitschrift: Lernenden-Wahl und Stand. Datenbank sales_test; keine Dienste."""
import itertools
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kurs_mitschrift as km  # noqa: E402
import server  # noqa: E402

UID = "kurs-lernende-0001@sales-claw"
UID2 = "kurs-lernende-0002@sales-claw"
BEGINN = datetime(2026, 11, 14, 9, 5, tzinfo=timezone.utc)
_nr = itertools.count(1)


@pytest.fixture(autouse=True)
def sauber():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    angelegt = []
    yield angelegt
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    for lid in angelegt:
        server._q("delete from leads where id = %s returning id", (lid,))


@pytest.fixture
def lead(sauber):
    return _lead(sauber, "Anna Lernend", "anna.lernend@kurs-test.example")


def _lead(sauber, name, email=None, privat=False):
    enr = {server.PRIVAT_SCHLUESSEL: {"privat": True}} if privat else {}
    lid = str(server._q(
        "insert into leads (name, email, phone, source, consent_status, enrichment) "
        "values (%s, %s, %s, 'whatsapp', 'existing_customer', %s::jsonb) returning id",
        (name, email, f"+4917088{next(_nr):05d}", json.dumps(enr)))[0]["id"])
    sauber.append(lid)
    return lid


def _mitschrift(uid=UID, rubrik="Kurse", lernender=None, am=0):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs', 'fertig') returning uid",
              (uid, BEGINN, BEGINN + timedelta(hours=1)))
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_am, rubrik, kurs_lead_id, geholt_am) "
              "values (%s, '[]'::jsonb, 'fertig', '{}'::jsonb, now(), %s, %s, %s) returning id",
              (uid, rubrik, lernender, BEGINN + timedelta(days=am)))


def _teilnehmer(uid, adresse, rolle="gast", lead_id=None, name=None):
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id) "
              "values (%s, %s, %s, %s, %s) returning uid", (uid, adresse, name, rolle, lead_id))


def _gewaehlt(uid):
    return server._q("select kurs_lead_id from termin_mitschriften where uid = %s",
                     (uid,))[0]["kurs_lead_id"]


def test_vorschlag_aus_teilnehmer_mit_lead(lead):
    _mitschrift()
    _teilnehmer(UID, "irgendwer@kurs-test.example", lead_id=lead)
    v = km.vorschlaege(UID)
    assert [x["lead_id"] for x in v] == [lead]
    assert v[0]["name"] == "Anna Lernend"


def test_vorschlag_ueber_adresse(lead):
    _mitschrift()
    _teilnehmer(UID, "Anna.Lernend@kurs-test.example")
    assert [x["lead_id"] for x in km.vorschlaege(UID)] == [lead]


def test_unbekannte_adresse_kein_vorschlag():
    _mitschrift()
    _teilnehmer(UID, "fremd@kurs-test.example")
    assert km.vorschlaege(UID) == []


def test_organisator_kein_vorschlag(lead):
    _mitschrift()
    _teilnehmer(UID, "anna.lernend@kurs-test.example", rolle="organisator", lead_id=lead)
    assert km.vorschlaege(UID) == []


def test_zuletzt_gewaehlte_werden_vorgeschlagen(sauber, lead):
    diana = _lead(sauber, "Diana Lernend")
    _mitschrift(UID, lernender=diana, am=0)
    _mitschrift(UID2, am=1)
    _teilnehmer(UID2, "anna.lernend@kurs-test.example")
    ids = [x["lead_id"] for x in km.vorschlaege(UID2)]
    assert ids == [lead, diana]


def test_zuletzt_gewaehlte_hoechstens_fuenf_und_eindeutig(sauber):
    ids = [_lead(sauber, f"Lernend {i}") for i in range(7)]
    for i, lid in enumerate(ids):
        _mitschrift(f"kurs-viele-{i}@sales-claw", lernender=lid, am=i)
    _mitschrift("kurs-viele-8@sales-claw", lernender=ids[6], am=9)
    _mitschrift(UID2, am=20)
    v = [x["lead_id"] for x in km.vorschlaege(UID2)]
    assert len(v) == 5 and len(set(v)) == 5
    assert v[0] == ids[6]


def test_privater_kontakt_waehlbar(sauber):
    privat = _lead(sauber, "Privat Lernend", privat=True)
    _mitschrift()
    assert km.lernender_setzen(UID, privat)
    assert str(_gewaehlt(UID)) == privat


def test_lernender_wieder_entfernen(lead):
    _mitschrift(lernender=lead)
    assert km.lernender_setzen(UID, None)
    assert _gewaehlt(UID) is None


def test_unbekannter_lead_abgelehnt():
    _mitschrift()
    assert not km.lernender_setzen(UID, "00000000-0000-0000-0000-000000000000")
    assert not km.lernender_setzen(UID, "kein-uuid")


def test_nur_fuer_kurse(lead):
    _mitschrift(rubrik="Notizen")
    assert not km.lernender_setzen(UID, lead)
    assert _gewaehlt(UID) is None
    assert not km.lernender_setzen("gibt-es-nicht@sales-claw", lead)


def _loeschantrag(lid):
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "%s, %s::jsonb, true) where id = %s returning id",
              ([server.LOESCH_SCHLUESSEL], json.dumps({"am": "2026-11-19", "quelle": "test"}),
               lid))


def _sperre_fuer(monkeypatch, email):
    import sperrliste
    monkeypatch.setattr(sperrliste, "gesperrt",
                        lambda q, email="", phone="", ziel=email.lower():
                        "marketing: abgemeldet" if (email or "").lower() == ziel else None)


def test_lead_mit_loeschantrag_nicht_waehlbar(lead):
    _mitschrift()
    _loeschantrag(lead)
    assert km.lernender_gesperrt(lead)
    assert not km.lernender_setzen(UID, lead)
    assert _gewaehlt(UID) is None


def test_gesperrter_lead_nicht_waehlbar(lead, monkeypatch):
    _mitschrift()
    _sperre_fuer(monkeypatch, "anna.lernend@kurs-test.example")
    assert km.lernender_gesperrt(lead)
    assert not km.lernender_setzen(UID, lead)
    assert _gewaehlt(UID) is None
    assert km.lernender_setzen(UID, None)        # entfernen bleibt moeglich


def test_loeschantrag_nicht_vorgeschlagen_auch_nicht_ueber_adresse(sauber, lead):
    # so laesst der Loeschantrag die Teilnehmer-Zeile zurueck: lead_id null, Adresse bleibt
    _mitschrift()
    _loeschantrag(lead)
    server._q("insert into termin_teilnehmer (uid, adresse, rolle, lead_id, grund) "
              "values (%s, 'anna.lernend@kurs-test.example', 'gast', null, 'gesperrt') "
              "returning uid", (UID,))
    zweite = _lead(sauber, "Zweite Lernend", "zweite@kurs-test.example")
    _loeschantrag(zweite)
    _teilnehmer(UID, "z@kurs-test.example", lead_id=zweite)
    assert km.vorschlaege(UID) == []


def test_gesperrt_ueber_adresse_ohne_loeschantrag_nicht_vorgeschlagen(lead):
    # Teilnehmer-Zeile "gesperrt" (lead_id null) wird nicht ueber die Adresse aufgeloest
    _mitschrift()
    server._q("insert into termin_teilnehmer (uid, adresse, rolle, lead_id, grund) "
              "values (%s, 'anna.lernend@kurs-test.example', 'gast', null, 'gesperrt') "
              "returning uid", (UID,))
    assert km.vorschlaege(UID) == []


def test_gesperrte_zuletzt_gewaehlte_nicht_vorgeschlagen(sauber, lead, monkeypatch):
    diana = _lead(sauber, "Diana Lernend", "diana@kurs-test.example")
    _mitschrift(UID, lernender=diana, am=0)
    _mitschrift(UID2, lernender=lead, am=1)
    _sperre_fuer(monkeypatch, "diana@kurs-test.example")
    assert [x["lead_id"] for x in km.vorschlaege("kurs-andere@sales-claw")] == [lead]


def test_ist_kurs():
    assert km.ist_kurs("kurse") and km.ist_kurs("Kurse")
    assert not km.ist_kurs("Notizen") and not km.ist_kurs(None)


def test_konstanten():
    assert (km.RUBRIK_KURSE, km.MAX_VERSUCHE, km.MAX_BILDER_ABSCHNITT, km.BILD_KANTE,
            km.BILD_QUALITAET) == ("Kurse", 3, 6, 800, 60)
    assert km.NEUVERSUCH_NACH == timedelta(hours=1)


def test_kurs_stand_aendert_sich_mit_rubrik_und_auswertung():
    assert km.kurs_stand("gibt-es-nicht@sales-claw") is None
    _mitschrift()
    s1 = km.kurs_stand(UID)
    assert s1 and s1 == km.kurs_stand(UID)
    server._q("update termin_mitschriften set rubrik = 'Notizen' where uid = %s returning uid",
              (UID,))
    s2 = km.kurs_stand(UID)
    assert s2 != s1
    server._q("update termin_mitschriften set rubrik = 'Kurse', "
              "auswertung_am = auswertung_am + interval '1 minute' where uid = %s "
              "returning uid", (UID,))
    assert km.kurs_stand(UID) not in (s1, s2)
