"""Termin-Akte abgleichen und lesen (Meeting-Mittelpunkt Task 5)."""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender  # noqa: E402
import kalender_sicht  # noqa: E402
import mail_dispatch  # noqa: E402
import server  # noqa: E402
import sperrliste  # noqa: E402
import termin_akte  # noqa: E402
import teilnehmer  # noqa: E402

JETZT = datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc)
BEGINN = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)
MEET = "https://meet.google.com/abc-defg-hij"


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.activities, "
                     "sales_test.leads, sales_test.kalender_quellen, "
                     "sales_test.post_konten, sales_test.kalender_konten cascade")
        conn.execute("truncate compliance_test.sperrliste")
    monkeypatch.setenv("POST_BESITZER", "felix")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "")
    monkeypatch.setenv("JITSI_HOSTS", "meet.ffmuc.net")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "")
    monkeypatch.setattr(mail_dispatch, "SMTP_USER", "")
    monkeypatch.setattr(teilnehmer.postfach, "IMAP_USER", "")
    monkeypatch.setattr(kalender, "termine_lesen", lambda z=7, v=60: ([], None))
    monkeypatch.setattr(kalender, "eintragen", lambda uid, ics: (kalender.NICHT_KONFIGURIERT, None))
    monkeypatch.setattr(kalender, "loeschen", lambda uid: (kalender.NICHT_KONFIGURIERT, None))
    yield


def _gast(adresse, name="", art="individual", rolle="gast"):
    return {"adresse": adresse, "name": name, "rolle": rolle, "art": art}


def _quelle(bereich="business", besitzer="felix", name="Q", aktiv=True):
    qid = server.kalenderquelle_speichern(name, f"https://example.test/{name}.ics",
                                          besitzer, bereich)
    if not aktiv:
        server._q("update kalender_quellen set aktiv = false where id = %s returning id", (qid,))
    return qid


def _termin(uid="k1", beginn=BEGINN, titel="Besprechung", teilnehmer=None, konferenz=MEET,
            anzahl=None, beschreibung=None, ort=None):
    t = teilnehmer if teilnehmer is not None else [_gast("kunde@firma.de", "Kunde")]
    return {"uid": uid, "beginn": beginn, "ende": beginn + timedelta(hours=1),
            "titel": titel, "ort": ort, "beschreibung": beschreibung,
            "teilnehmer": t, "teilnehmer_anzahl": anzahl if anzahl is not None else len(t),
            "konferenz": konferenz}


def _ersetzen(qid, termine, details=True):
    server.kalendertermine_ersetzen(qid, termine, details)


def _akten():
    return server._q("select * from termin_akten order by uid")


def _lead(email="kunde@firma.de", name="Kunde"):
    return str(server._q("insert into leads (name, email) values (%s, %s) returning id",
                         (name, email))[0]["id"])


def _salesclaw(lead, uid="sc-1", datum="2099-01-10", uhrzeit="10:00", ort=MEET,
               dauer=45, **extra):
    payload = {"datum": datum, "uhrzeit": uhrzeit, "dauer_minuten": dauer,
               "thema": "Beratung", "ort": ort, "uid": uid, **extra}
    return str(server._q("insert into activities (lead_id, type, payload) "
                         "values (%s, 'termin', %s::jsonb) returning id",
                         (lead, json.dumps(payload)))[0]["id"])


def test_salesclaw_termin_ergibt_akte():
    lead = _lead("kunde@firma.de", "Kunde")
    antwort = json.loads(server.termin_bestaetigen(lead, "2099-01-10", "10:00",
                                                   ort="https://meet.ffmuc.net/R1"))
    uid = antwort["termin"]["uid"]
    assert termin_akte.abgleichen(JETZT) == {"neu": 1, "geaendert": 0, "abgesagt": 0}
    akte = termin_akte.lesen(uid)
    assert akte["herkunft"] == "sales-claw"
    assert akte["beitreten"]["plattform"] == "jitsi"
    assert akte["beitreten"]["link"] == "https://meet.ffmuc.net/R1"
    assert [t["adresse"] for t in akte["teilnehmer"]] == ["kunde@firma.de"]
    assert akte["teilnehmer"][0]["lead_id"] == lead
    assert akte["status"] == "geplant"
    # 10:00 Berlin im Januar = 09:00 UTC, Dauer 60 (Vorgabe)
    assert akte["beginn"] == datetime(2099, 1, 10, 9, 0, tzinfo=timezone.utc)
    assert akte["ende"] - akte["beginn"] == timedelta(minutes=60)
    assert server._q("select termin_activity_id from termin_akten")[0]["termin_activity_id"]
    # zweiter Lauf aendert nichts
    assert termin_akte.abgleichen(JETZT) == {"neu": 0, "geaendert": 0, "abgesagt": 0}


def test_kalendertermin_mit_externem_ergibt_akte_und_kontakt():
    _ersetzen(_quelle(), [_termin()])
    assert termin_akte.abgleichen(JETZT)["neu"] == 1
    akte = termin_akte.lesen("k1")
    assert akte["herkunft"] == "kalender"
    assert akte["beitreten"]["plattform"] == "google_meet"
    assert akte["titel"] == "Besprechung"
    assert akte["teilnehmer"][0]["lead_id"]
    lead = server._q("select source, email from leads")[0]
    assert lead["email"] == "kunde@firma.de" and lead["source"] == "aus Kalender"


def test_nur_team_und_webinar_keine_akte(monkeypatch):
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "ivan@haus.de")
    viele = [_gast(f"g{i}@firma.de") for i in range(11)]
    _ersetzen(_quelle(), [
        _termin("team", teilnehmer=[_gast("ivan@haus.de")]),
        _termin("webinar", teilnehmer=viele),
        _termin("ohne", teilnehmer=[]),
    ])
    assert termin_akte.abgleichen(JETZT) == {"neu": 0, "geaendert": 0, "abgesagt": 0}
    assert _akten() == []
    assert server._q("select count(*) as n from leads")[0]["n"] == 0


def test_private_quelle_keine_akte():
    _ersetzen(_quelle(bereich="privat"), [_termin()])
    assert termin_akte.abgleichen(JETZT)["neu"] == 0
    assert _akten() == []
    assert server._q("select count(*) as n from leads")[0]["n"] == 0


def test_inaktive_quelle_keine_akte():
    _ersetzen(_quelle(name="aus"), [_termin()])
    server._q("update kalender_quellen set aktiv = false returning id")
    assert termin_akte.abgleichen(JETZT)["neu"] == 0


def test_ausserhalb_des_fensters_keine_akte():
    _ersetzen(_quelle(), [_termin("spaet", beginn=JETZT + timedelta(days=31)),
                          _termin("alt", beginn=JETZT - timedelta(days=2))])
    assert termin_akte.abgleichen(JETZT)["neu"] == 0


def test_verschoben_zieht_zeit_nach():
    _ersetzen(_quelle(), [_termin()])
    termin_akte.abgleichen(JETZT)
    server._q("update termin_akten set briefing_stand = 'alt', briefing_md = 'x' returning uid")
    neu = BEGINN + timedelta(hours=2)
    _ersetzen(server.kalenderquellen_lesen()[0]["id"], [_termin(beginn=neu)])
    assert termin_akte.abgleichen(JETZT) == {"neu": 0, "geaendert": 1, "abgesagt": 0}
    zeile = server._q("select * from termin_akten")[0]
    assert zeile["beginn"] == neu
    assert zeile["briefing_stand"] is None
    assert zeile["geaendert_am"] > zeile["erstellt_am"]


def test_verschoben_laesst_briefing_nach_start_stehen():
    _ersetzen(_quelle(), [_termin()])
    termin_akte.abgleichen(JETZT)
    server._q("update termin_akten set status = 'fertig', briefing_stand = 'alt' returning uid")
    _ersetzen(server.kalenderquellen_lesen()[0]["id"],
              [_termin(beginn=BEGINN + timedelta(hours=1))])
    termin_akte.abgleichen(JETZT)
    zeile = server._q("select * from termin_akten")[0]
    assert zeile["status"] == "fertig" and zeile["briefing_stand"] == "alt"


def test_verschwunden_wird_abgesagt():
    _ersetzen(_quelle(), [_termin()])
    termin_akte.abgleichen(JETZT)
    _ersetzen(server.kalenderquellen_lesen()[0]["id"], [])
    assert termin_akte.abgleichen(JETZT) == {"neu": 0, "geaendert": 0, "abgesagt": 1}
    assert server._q("select abgesagt_am from termin_akten")[0]["abgesagt_am"] is not None
    assert termin_akte.lesen("k1")["abgesagt"] is True
    # nur einmal zaehlen
    assert termin_akte.abgleichen(JETZT)["abgesagt"] == 0


def test_pausierte_quelle_sagt_nicht_ab():
    qid = _quelle()
    _ersetzen(qid, [_termin()])
    termin_akte.abgleichen(JETZT)
    server._q("update kalender_quellen set aktiv = false where id = %s returning id", (qid,))
    assert termin_akte.abgleichen(JETZT)["abgesagt"] == 0


def test_salesclaw_absage_sagt_akte_ab():
    lead = _lead()
    uid = json.loads(server.termin_bestaetigen(lead, "2099-01-10", "10:00",
                                               ort=MEET))["termin"]["uid"]
    termin_akte.abgleichen(JETZT)
    server.termin_absagen(lead, uid, "krank")
    assert termin_akte.abgleichen(JETZT) == {"neu": 0, "geaendert": 0, "abgesagt": 1}
    assert termin_akte.lesen(uid)["abgesagt"] is True


def test_doppelt_ergibt_eine_akte():
    lead = _lead()
    _salesclaw(lead, uid="dup-1", datum="2099-01-10", uhrzeit="10:00")
    gast = [_gast("kunde@firma.de")]
    _ersetzen(_quelle(name="A"), [_termin("dup-1", teilnehmer=gast)])
    _ersetzen(_quelle(name="B", besitzer="ivan", bereich="business"),
              [_termin("dup-1", teilnehmer=gast)])
    assert termin_akte.abgleichen(JETZT)["neu"] == 1
    akten = _akten()
    assert len(akten) == 1
    assert akten[0]["herkunft"] == "sales-claw"
    assert akten[0]["termin_activity_id"] is not None
    assert server._q("select count(*) as n from termin_teilnehmer")[0]["n"] == 1


def test_doppelt_nur_kalender_zwei_quellen_eine_akte():
    gast = [_gast("kunde@firma.de")]
    _ersetzen(_quelle(name="A"), [_termin("dup-2", teilnehmer=gast)])
    _ersetzen(_quelle(name="B", besitzer="ivan"), [_termin("dup-2", teilnehmer=gast)])
    assert termin_akte.abgleichen(JETZT)["neu"] == 1
    assert len(_akten()) == 1


def test_ohne_link_kein_link_status():
    _ersetzen(_quelle(), [_termin(konferenz=None)])
    termin_akte.abgleichen(JETZT)
    akte = termin_akte.lesen("k1")
    assert akte["status"] == "kein_link"
    assert akte["beitreten"]["link"] is None


def test_link_nachgetragen_wird_geplant():
    qid = _quelle()
    _ersetzen(qid, [_termin(konferenz=None)])
    termin_akte.abgleichen(JETZT)
    _ersetzen(qid, [_termin(konferenz=None, beschreibung=f"Bitte hier: {MEET}")])
    assert termin_akte.abgleichen(JETZT)["geaendert"] == 1
    akte = termin_akte.lesen("k1")
    assert akte["status"] == "geplant"
    assert akte["beitreten"]["plattform"] == "google_meet"


def test_lesen_ohne_gesperrte():
    sperrliste.sperren(server._q, email="nein@firma.de", quelle="test", grund="x")
    _ersetzen(_quelle(), [_termin(teilnehmer=[
        _gast("kunde@firma.de", "Kunde"), _gast("nein@firma.de", "Nein")])])
    termin_akte.abgleichen(JETZT)
    akte = termin_akte.lesen("k1")
    assert [t["adresse"] for t in akte["teilnehmer"]] == ["kunde@firma.de"]
    assert "nein@firma.de" not in json.dumps(akte, default=str)
    assert "passcode" in akte["beitreten"]
    assert set(akte) >= {"uid", "herkunft", "beginn", "ende", "zeitzone", "titel", "thema",
                         "beschreibung", "beitreten", "teilnehmer", "status", "status_grund",
                         "kein_bot", "will_zusammenfassung", "abgesagt", "briefing",
                         "mitschrift", "vorschlaege"}
    assert akte["briefing"] is None and akte["mitschrift"] is None
    assert akte["vorschlaege"] == []
    assert termin_akte.lesen("gibt-es-nicht") is None


def test_hat_gesperrte_prueft_live():
    _ersetzen(_quelle(), [_termin()])
    termin_akte.abgleichen(JETZT)
    assert termin_akte.hat_gesperrte("k1") is False
    # Sperre NACH dem Verknuepfen: die Zeile steht noch ohne grund 'gesperrt'
    sperrliste.sperren(server._q, email="kunde@firma.de", quelle="test", grund="x")
    assert server._q("select grund from termin_teilnehmer")[0]["grund"] is None
    assert termin_akte.hat_gesperrte("k1") is True
    assert termin_akte.hat_gesperrte("gibt-es-nicht") is False


def test_hat_gesperrte_zeile_mit_grund_gesperrt():
    _ersetzen(_quelle(), [_termin()])
    termin_akte.abgleichen(JETZT)
    server._q("update termin_teilnehmer set grund = 'gesperrt' returning uid")
    assert termin_akte.hat_gesperrte("k1") is True


def test_status_setzen():
    _ersetzen(_quelle(), [_termin()])
    termin_akte.abgleichen(JETZT)
    termin_akte.status_setzen("k1", "wartet_auf_einlass", "Bot gestartet",
                              vexa_meeting_id=7, kein_bot=True)
    z = server._q("select * from termin_akten")[0]
    assert (z["status"], z["status_grund"], z["vexa_meeting_id"], z["kein_bot"]) == (
        "wartet_auf_einlass", "Bot gestartet", 7, True)
    with pytest.raises(ValueError):
        termin_akte.status_setzen("k1", "fertig", nope=1)
    with pytest.raises(ValueError):
        termin_akte.status_setzen("k1", "fertig", erstellt_am=None)


def test_akten_eines_leads():
    _ersetzen(_quelle(), [_termin("a", beginn=BEGINN + timedelta(days=1)), _termin("b")])
    termin_akte.abgleichen(JETZT)
    lead = server._q("select id from leads")[0]["id"]
    assert termin_akte.akten_eines_leads(lead) == ["b", "a"]
    assert termin_akte.akten_eines_leads(str(lead)) == ["b", "a"]


def test_kein_log_mit_adresse_name_passcode(caplog):
    _ersetzen(_quelle(), [_termin(
        konferenz="https://zoom.us/j/123456789?pwd=geheimpw",
        titel="Vertrag Mueller", teilnehmer=[_gast("gerda@firma.de", "Gerda Geheim")])])
    with caplog.at_level(logging.DEBUG):
        termin_akte.abgleichen(JETZT)
        termin_akte.lesen("k1")
        termin_akte.hat_gesperrte("k1")
        termin_akte.status_setzen("k1", "laeuft")
    text = caplog.text.lower()
    for verboten in ("gerda", "firma.de", "geheimpw", "mueller", "zoom.us"):
        assert verboten not in text


def test_kundenzeilen_ueberspringt_aus_kalender():
    lead = _lead()
    _salesclaw(lead, uid="normal")
    _salesclaw(lead, uid="aus-kalender", aus_kalender=True)
    uids = [z["payload"]["uid"] for z in kalender_sicht.kundenzeilen()[0]]
    assert uids == ["normal"]


def test_herkunft_bleibt_salesclaw_wenn_zeile_unlesbar_wird():
    lead = _lead()
    aid = _salesclaw(lead, uid="dup-h")
    _ersetzen(_quelle(), [_termin("dup-h")])
    termin_akte.abgleichen(JETZT)
    assert _akten()[0]["herkunft"] == "sales-claw"
    server._q("update activities set payload = jsonb_set(payload, '{uhrzeit}', '\"kaputt\"') "
              "where id = %s returning id", (aid,))
    termin_akte.abgleichen(JETZT)
    z = _akten()[0]
    assert z["herkunft"] == "sales-claw"
    assert str(z["termin_activity_id"]) == aid


def test_wiederkehrende_akte_ist_nicht_mehr_abgesagt():
    qid = _quelle()
    _ersetzen(qid, [_termin()])
    termin_akte.abgleichen(JETZT)
    _ersetzen(qid, [])
    assert termin_akte.abgleichen(JETZT)["abgesagt"] == 1
    _ersetzen(qid, [_termin()])
    termin_akte.abgleichen(JETZT)
    assert server._q("select abgesagt_am from termin_akten")[0]["abgesagt_am"] is None
    assert termin_akte.lesen("k1")["abgesagt"] is False


def test_vergangene_akte_wird_nicht_abgesagt():
    qid = _quelle()
    _ersetzen(qid, [_termin()])
    termin_akte.abgleichen(JETZT)
    _ersetzen(qid, [])
    spaeter = BEGINN + timedelta(hours=3)
    assert termin_akte.abgleichen(spaeter)["abgesagt"] == 0
    assert server._q("select abgesagt_am from termin_akten")[0]["abgesagt_am"] is None


def test_salesclaw_dauer_bestimmt_ende():
    _salesclaw(_lead(), uid="dauer-1", dauer=45)
    termin_akte.abgleichen(JETZT)
    akte = termin_akte.lesen("dauer-1")
    assert akte["ende"] - akte["beginn"] == timedelta(minutes=45)


def test_aktive_quelle_ohne_zeilen_sagt_zukuenftige_akte_ab():
    # beabsichtigt: eine erfolgreich gelesene, nun leere Quelle heisst "abgesagt"
    qid = _quelle()
    _ersetzen(qid, [_termin()])
    termin_akte.abgleichen(JETZT)
    server.kalenderquelle_stand_setzen(qid, 0, None)
    _ersetzen(qid, [])
    assert termin_akte.abgleichen(JETZT)["abgesagt"] == 1


def test_sperre_nach_verknuepfen_verschwindet_aus_lesen():
    qid = _quelle()
    _ersetzen(qid, [_termin(teilnehmer=[_gast("kunde@firma.de"), _gast("zweiter@firma.de")])])
    termin_akte.abgleichen(JETZT)
    assert len(termin_akte.lesen("k1")["teilnehmer"]) == 2
    sperrliste.sperren(server._q, email="kunde@firma.de", quelle="test", grund="x")
    termin_akte.abgleichen(JETZT)
    assert [t["adresse"] for t in termin_akte.lesen("k1")["teilnehmer"]] == ["zweiter@firma.de"]
