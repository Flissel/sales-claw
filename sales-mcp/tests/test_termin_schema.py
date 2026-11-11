"""Schema der Termin-Akte (Meeting-Mittelpunkt, Task 1): vier Tabellen und
drei neue Spalten in kalender_termine, nur gegen sales_test."""
import os

import psycopg
import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

SPALTEN = {
    "termin_akten": {
        "uid", "herkunft", "quelle_id", "termin_activity_id", "beginn", "ende",
        "zeitzone", "titel", "thema", "beschreibung", "link", "plattform",
        "passcode", "einwahl", "status", "status_grund", "kein_bot",
        "will_zusammenfassung", "abgesagt_am", "vexa_meeting_id",
        "vexa_plattform", "vexa_native_id", "bot_geschickt_am", "briefing_md",
        "briefing_stand", "briefing_mit_ki", "briefing_am",
        "hinweis_gesendet_am", "erstellt_am", "geaendert_am"},
    "termin_teilnehmer": {"uid", "adresse", "name", "rolle", "lead_id", "grund"},
    "termin_mitschriften": {
        "id", "uid", "segmente", "geholt_am", "auswertung_status",
        "auswertung_json", "auswertung_md", "auswertung_am", "modell",
        "entwurf_id", "auswertung_versuche"},
    "termin_vorschlaege": {
        "id", "mitschrift_id", "art", "lead_id", "daten", "status",
        "erstellt_am", "erledigt_am"},
}


@pytest.fixture(autouse=True)
def leer():
    server._q("truncate sales_test.termin_akten cascade")
    yield
    server._q("truncate sales_test.termin_akten cascade")


def _akte(uid="u1", status="geplant"):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, status) "
        "values (%s, 'sales-claw', now(), now() + interval '1 hour', %s)",
        (uid, status))


def _mitschrift(uid="u1"):
    return server._q(
        "insert into termin_mitschriften (uid, segmente) "
        "values (%s, '[]'::jsonb) returning id", (uid,))[0]["id"]


def _zeilen(tabelle):
    return server._q(f"select count(*) as n from {tabelle}")[0]["n"]


def test_tabellen_und_spalten_da():
    for tabelle, erwartet in SPALTEN.items():
        da = {z["column_name"] for z in server._q(
            "select column_name from information_schema.columns "
            "where table_schema='sales_test' and table_name=%s", (tabelle,))}
        assert erwartet <= da, (tabelle, erwartet - da)
    kt = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema='sales_test' and table_name='kalender_termine'")}
    assert {"beschreibung", "teilnehmer", "konferenz"} <= kt


def test_status_check_lehnt_unbekanntes_ab():
    with pytest.raises(psycopg.errors.CheckViolation):
        _akte(status="läuft")
    _akte(status="laeuft")


def test_mitschrift_loescht_vorschlaege_mit():
    _akte()
    mid = _mitschrift()
    server._q(
        "insert into termin_vorschlaege (mitschrift_id, art, daten) "
        "values (%s, 'feld', '{}'::jsonb)", (mid,))
    assert _zeilen("termin_vorschlaege") == 1
    server._q("delete from termin_mitschriften")
    assert _zeilen("termin_vorschlaege") == 0


def test_akte_loeschen_kaskadiert():
    _akte()
    server._q(
        "insert into termin_teilnehmer (uid, adresse, rolle) "
        "values ('u1', 'a@example.org', 'gast')")
    _mitschrift()
    server._q("delete from termin_akten where uid='u1'")
    assert _zeilen("termin_teilnehmer") == 0
    assert _zeilen("termin_mitschriften") == 0
