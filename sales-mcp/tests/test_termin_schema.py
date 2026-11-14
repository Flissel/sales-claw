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
        "hinweis_gesendet_am", "erstellt_am", "geaendert_am",
        "bildschirm_auswerten", "bilder_uebersprungen"},
    "termin_teilnehmer": {"uid", "adresse", "name", "rolle", "lead_id", "grund"},
    "termin_mitschriften": {
        "id", "uid", "segmente", "geholt_am", "auswertung_status",
        "auswertung_json", "auswertung_md", "auswertung_am", "modell",
        "entwurf_id", "auswertung_versuche"},
    "termin_vorschlaege": {
        "id", "mitschrift_id", "art", "lead_id", "daten", "status",
        "erstellt_am", "erledigt_am"},
    "termin_bilder": {
        "id", "uid", "aufgenommen_am", "bis", "geteilt_von", "bild", "breite",
        "hoehe", "dhash", "beschreibung", "beschreibung_status",
        "beschreibung_versuche", "vektor_bild", "vektor_text", "erstellt_am",
        "versucht_am"},
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


def _bild(uid="u1"):
    return server._q(
        "insert into termin_bilder (uid, aufgenommen_am, bild, breite, hoehe, dhash) "
        "values (%s, now(), %s, 2, 2, 7) returning id", (uid, b"\x01"))[0]["id"]


def test_termin_bilder_spalten_exakt_und_schalter():
    da = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns "
        "where table_schema='sales_test' and table_name='termin_bilder'")}
    assert da == SPALTEN["termin_bilder"]
    z = server._q(
        "select data_type, is_nullable, column_default from information_schema.columns "
        "where table_schema='sales_test' and table_name='termin_akten' "
        "and column_name='bildschirm_auswerten'")[0]
    assert (z["data_type"], z["is_nullable"]) == ("boolean", "NO")
    assert z["column_default"] == "false"


def test_termin_bilder_standardwerte():
    _akte()
    _bild()
    z = server._q("select beschreibung_status, beschreibung_versuche, bis, versucht_am, "
                  "vektor_bild, vektor_text from termin_bilder")[0]
    assert (z["beschreibung_status"], z["beschreibung_versuche"]) == ("offen", 0)
    assert z["versucht_am"] is None
    assert z["bis"] is None and z["vektor_bild"] is None and z["vektor_text"] is None
    with pytest.raises(psycopg.errors.CheckViolation):
        server._q("update termin_bilder set beschreibung_status = 'x' returning id")


def test_akte_loeschen_loescht_bilder():
    _akte()
    _akte("u2")
    _bild()
    _bild("u2")
    server._q("delete from termin_akten where uid='u1'")
    assert _zeilen("termin_bilder") == 1


def test_termin_akten_bilder_uebersprungen_zaehler():
    z = server._q(
        "select data_type, is_nullable, column_default from information_schema.columns "
        "where table_schema='sales_test' and table_name='termin_akten' "
        "and column_name='bilder_uebersprungen'")[0]
    assert (z["data_type"], z["is_nullable"]) == ("integer", "NO")
    assert z["column_default"] == "0"
