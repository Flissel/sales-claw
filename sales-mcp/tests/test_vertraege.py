"""Vertragstests fuer Vertraege + Ablauf-Wiedervorlagen gegen sales_test.

Ein Vertrag ist eine vom Kunden GENANNTE Tatsache (Dokumentation, keine
Beratung — §34d bleibt unberuehrt). Er liegt in leads.enrichment.vertraege
(jsonb-Array); mit Ablaufdatum entsteht automatisch eine Wiedervorlage
90 Tage vorher ueber das bestehende Ereignis-Muster.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")


def _heute():
    """UTC, nicht date.today() — und das ist hier keine Kosmetik.

    Der Container laeuft mit TZ=Europe/Berlin, die Werkzeugschicht rechnet
    durchgehend in UTC (`datetime.now(timezone.utc).date()`, so schon in
    wiedervorlage_setzen). Zwischen 00:00 und 02:00 Berliner Zeit laufen
    beide Datumsbegriffe einen Tag auseinander — ein Test mit date.today()
    ist in genau diesem Fenster rot, sonst gruen. Gleiches Muster wie
    `_heute()` in test_werkzeuge.py.
    """
    return datetime.now(timezone.utc).date()


def _lead():
    return server._q(
        "insert into leads (name, phone, source) values "
        "('Max Bestand', '+491701234567', 'whatsapp') returning id")[0]["id"]


def test_vertrag_landet_im_enrichment_array():
    lead = _lead()
    ablauf = (_heute() + timedelta(days=200)).isoformat()
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", ablauf=ablauf,
        gesellschaft="Beispiel AG", notiz="vom Kunden genannt"))
    assert antwort["vertrag"]["sparte"] == "BU"
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]["enrichment"]
    assert len(e["vertraege"]) == 1
    assert e["vertraege"][0]["ablauf"] == ablauf
    # Zweiter Vertrag haengt sich AN, ueberschreibt nicht.
    json.loads(server.vertrag_speichern(lead_id=str(lead), sparte="Haftpflicht"))
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]["enrichment"]
    assert [v["sparte"] for v in e["vertraege"]] == ["BU", "Haftpflicht"]


def test_ablauf_erzeugt_wiedervorlage_90_tage_vorher():
    lead = _lead()
    ablauf = _heute() + timedelta(days=200)
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", ablauf=ablauf.isoformat()))
    erwartet = (ablauf - timedelta(days=90)).isoformat()
    assert antwort["wiedervorlage"]["faellig_am"] == erwartet
    wv = server._q("select payload from activities where type='wiedervorlage'")
    assert len(wv) == 1 and wv[0]["payload"]["faellig_am"] == erwartet
    assert "BU" in wv[0]["payload"]["notiz"]


def test_naher_ablauf_wird_nicht_in_die_vergangenheit_gelegt():
    lead = _lead()
    ablauf = _heute() + timedelta(days=10)   # 90 Tage vorher waere vorbei
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="KFZ", ablauf=ablauf.isoformat()))
    assert antwort["wiedervorlage"]["faellig_am"] == _heute().isoformat()


def test_ohne_ablauf_keine_wiedervorlage_und_vergangenheit_nur_hinweis():
    lead = _lead()
    antwort = json.loads(server.vertrag_speichern(lead_id=str(lead), sparte="Hausrat"))
    assert antwort["wiedervorlage"] is None
    alt = (_heute() - timedelta(days=5)).isoformat()
    antwort = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="Reise", ablauf=alt))
    assert antwort["wiedervorlage"] is None
    assert "Vergangenheit" in antwort["hinweis"]
    assert server._q("select count(*) as n from activities "
                     "where type='wiedervorlage'")[0]["n"] == 0


def test_kaputtes_datum_und_leere_sparte_ergeben_fehler():
    lead = _lead()
    assert "fehler" in json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", ablauf="31.12.2027"))
    assert "fehler" in json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="  "))
    e = server._q("select enrichment from leads where id = %s", (lead,))[0]["enrichment"]
    assert "vertraege" not in (e or {})


def test_profil_lesen_zeigt_vertraege():
    lead = _lead()
    server.vertrag_speichern(lead_id=str(lead), sparte="BU")
    profil = json.loads(server.profil_lesen(str(lead)))
    assert profil["vertraege"][0]["sparte"] == "BU"


def test_vertraege_ablaufend_filtert_fenster_und_sortiert():
    lead = _lead()
    for sparte, tage in (("BU", 30), ("Hausrat", 80), ("KFZ", 200)):
        server.vertrag_speichern(
            lead_id=str(lead), sparte=sparte,
            ablauf=(_heute() + timedelta(days=tage)).isoformat())
    antwort = json.loads(server.vertraege_ablaufend(tage=90))
    assert [v["sparte"] for v in antwort["vertraege"]] == ["BU", "Hausrat"]
    assert antwort["anzahl"] == 2


def test_signaturen_ueberleben_den_dekorator():
    import inspect
    assert list(inspect.signature(server.vertrag_speichern).parameters) == [
        "lead_id", "sparte", "ablauf", "gesellschaft", "notiz"]
    assert list(inspect.signature(server.vertraege_ablaufend).parameters) == ["tage"]
    assert server.vertrag_speichern in server.WERKZEUGE
    assert server.vertraege_ablaufend in server.WERKZEUGE


# ---------------------------------------------------------------------------
# Nachbesserungen aus dem Abschluss-Review (Befunde B1, B2, B3, B8)
# ---------------------------------------------------------------------------

def test_fremddaten_kippen_vertraege_ablaufend_nicht():
    """B1+B2: EINE kaputte Zeile irgendwo in leads darf das Werkzeug nicht
    fuer alle Kontakte unbrauchbar machen — weder ein Nicht-Array-Knoten
    (case-Wache), noch Nicht-Objekt-Elemente, noch ein nicht-datumsfoermiger
    ablauf (der fruehere ::date-Cast warf SQLSTATE 22007/22008)."""
    gut = _lead()
    server.vertrag_speichern(
        lead_id=str(gut), sparte="BU",
        ablauf=(_heute() + timedelta(days=30)).isoformat())
    kaputte = ['"kein-array"',
               '[42, "nur-string", null]',
               '[{"sparte": "KFZ", "ablauf": "31.12.2027"}]',
               '[{"sparte": "Hausrat", "ablauf": "2027-13-45"}]',
               '[{"sparte": "Reise", "ablauf": "nicht-datum"}]']
    for knoten in kaputte:
        kaputt_lead = _lead()
        server._q("update leads set enrichment = jsonb_set(enrichment, "
                  "'{vertraege}', %s::jsonb, true) where id = %s returning id",
                  (knoten, kaputt_lead))
    antwort = json.loads(server.vertraege_ablaufend(tage=90))
    assert "fehler" not in antwort
    assert antwort["anzahl"] == 1
    assert antwort["vertraege"][0]["sparte"] == "BU"


def test_identischer_vertrag_wird_nicht_doppelt_angelegt():
    """B3 — dasselbe Gesetz wie die Dedup-Kante in kontakt_anlegen: ein
    Modell, das denselben Vertrag im Verlauf erneut nennt, darf keinen
    zweiten Eintrag und vor allem keine ZWEITE Wiedervorlage erzeugen."""
    lead = _lead()
    ablauf = (_heute() + timedelta(days=200)).isoformat()
    erst = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", gesellschaft="Beispiel AG",
        ablauf=ablauf))
    assert erst["angelegt"] is True
    zweit = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="  bu ", gesellschaft="BEISPIEL AG",
        ablauf=ablauf, notiz="andere Notiz aendert den Vertrag nicht"))
    assert zweit["angelegt"] is False
    assert zweit["wiedervorlage"] is None
    e = server._q("select enrichment from leads where id = %s",
                  (lead,))[0]["enrichment"]
    assert len(e["vertraege"]) == 1
    assert server._q("select count(*) as n from activities "
                     "where type='wiedervorlage'")[0]["n"] == 1
    dritt = json.loads(server.vertrag_speichern(
        lead_id=str(lead), sparte="BU", gesellschaft="Beispiel AG",
        ablauf=(_heute() + timedelta(days=400)).isoformat()))
    assert dritt["angelegt"] is True


def test_db_session_rechnet_utc():
    """B8: die Uebereinstimmung von current_date (DB) und
    datetime.now(timezone.utc).date() (Python) war eine Umgebungseigenschaft
    — jetzt ist sie per Pool-Option zugesichert, und dieser Test haelt sie."""
    assert server._q("show timezone")[0]["TimeZone"] == "UTC"
