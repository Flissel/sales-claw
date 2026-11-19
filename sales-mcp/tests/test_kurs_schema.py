"""Kursmitschrift: Schema (Spalten, Tabellen, Loeschverhalten). Datenbank sales_test."""
import itertools
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

UID = "kurs-schema-0001@sales-claw"
BEGINN = datetime(2026, 11, 14, 9, 5, tzinfo=timezone.utc)
_nr = itertools.count(1)


def _zeile(uid):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


@pytest.fixture
def lead_mit_kapitel_und_mitschrift():
    server._q("delete from termin_akten where uid = %s returning uid", (UID,))
    lead = str(server._q(
        "insert into leads (name, phone, source, consent_status) "
        "values ('Schema Lernender', %s, 'whatsapp', 'existing_customer') returning id",
        (f"+4917099{next(_nr):05d}",))[0]["id"])
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs', 'fertig') returning uid",
              (UID, BEGINN, BEGINN + timedelta(hours=1)))
    server._q("insert into termin_mitschriften (uid, segmente, kurs_lead_id) "
              "values (%s, %s::jsonb, %s) returning id", (UID, json.dumps([]), lead))
    kap = server._q("insert into kurs_handbuch_kapitel (lead_id, titel, reihenfolge) "
                    "values (%s, 'Kapitel', 1) returning id", (lead,))[0]["id"]
    server._q("insert into kurs_handbuch_fassung (kapitel_id, text_md, quellen) "
              "values (%s, 'Text', %s) returning id", (kap, [UID]))
    server._q("insert into kurs_handbuch_quelle (lead_id, uid, beginn, stand, zuordnung) "
              "values (%s, %s, %s, 'x', '{}'::jsonb) returning uid", (lead, UID, BEGINN))
    server._q("insert into kurs_handbuch (lead_id) values (%s) returning lead_id", (lead,))
    yield lead
    server._q("delete from termin_akten where uid = %s returning uid", (UID,))
    server._q("delete from leads where id = %s returning id", (lead,))


def test_spalten_und_tabellen_da():
    spalten = {z["column_name"] for z in server._q(
        "select column_name from information_schema.columns where table_schema = current_schema() "
        "and table_name = 'termin_mitschriften'")}
    assert {"kurs_json", "kurs_stand", "kurs_status", "kurs_am", "kurs_versuche",
            "kurs_pfad", "kurs_pfad_lernend", "kurs_pdf", "kurs_lead_id"} <= spalten
    for t in ("kurs_handbuch_kapitel", "kurs_handbuch_fassung", "kurs_handbuch_quelle",
              "kurs_handbuch"):
        assert server._q("select to_regclass(%s) is not null as da", (t,))[0]["da"]


def test_kurs_versuche_standard_null(lead_mit_kapitel_und_mitschrift):
    assert _zeile(UID)["kurs_versuche"] == 0


def test_lead_loeschen_kaskadiert_und_setzt_null(lead_mit_kapitel_und_mitschrift):
    lead = lead_mit_kapitel_und_mitschrift
    server._q("delete from leads where id = %s returning id", (lead,))
    for t in ("kurs_handbuch_kapitel", "kurs_handbuch_quelle", "kurs_handbuch"):
        assert not server._q(f"select 1 from {t} where lead_id = %s", (lead,))
    assert not server._q("select 1 from kurs_handbuch_fassung")
    assert _zeile(UID)["kurs_lead_id"] is None
