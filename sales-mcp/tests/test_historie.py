import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import historie as hi  # noqa: E402
import server  # noqa: E402

PROVISION = (Path(__file__).resolve().parents[2] / "db" / "provision.sql").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")


def _lead():
    return str(server._q("insert into leads (name, phone) values ('K', '+491701234567') "
                         "returning id")[0]["id"])


def _draft(lead, thema, status="sent", tage_alt=1, kanal="whatsapp", subject=None, newsletter=None):
    t = datetime.now(timezone.utc) - timedelta(days=tage_alt)
    return str(server._q(
        "insert into drafts (lead_id, channel, recipient, body, status, thema, subject, "
        "newsletter, created_at, sent_at) values (%s,%s,'x','Text',%s,%s,%s,%s,%s,%s) returning id",
        (lead, kanal, status, thema, subject, newsletter, t, t if status == "sent" else None))[0]["id"])


def test_provision_hat_thema_spalte():
    assert "add column if not exists thema text" in PROVISION


def test_thema_norm():
    assert hi.thema_norm("  BAV   Erstansprache ") == hi.thema_norm("bav erstansprache")
    assert len(hi.thema_norm("x" * 200)) == 80
    assert hi.thema_norm(None) == ""


def test_doppelt_frist_status_termin():
    lead = _lead()
    _draft(lead, "bAV Erstansprache", tage_alt=10)
    _draft(lead, "bAV Erstansprache", status="rejected", tage_alt=5)
    _draft(lead, "Homelab", tage_alt=120)
    _draft(lead, "termin", tage_alt=1)
    assert len(hi.doppelt_pruefen(lead, "  BAV  erstansprache")) == 1
    assert hi.doppelt_pruefen(lead, "homelab") == []
    assert hi.doppelt_pruefen(lead, "termin") == []
    assert hi.doppelt_pruefen(lead, "") == []
    _draft(lead, "Homelab", status="pending", tage_alt=0)
    assert hi.doppelt_pruefen(lead, "Homelab")[0]["status"] == "pending"


def test_hinweis_wortlaut():
    lead = _lead()
    _draft(lead, "bAV Erstansprache", tage_alt=3)
    h = hi.doppelt_hinweis(hi.doppelt_pruefen(lead, "bAV Erstansprache"))
    assert h.startswith("Schon am ") and "per WhatsApp zum Thema bAV Erstansprache angeschrieben" in h
    assert h.endswith("trotzdem anlegen? Dann trotzdem=True.")


def test_historie_quellen_und_handy_summe():
    lead = _lead()
    _draft(lead, "bAV Erstansprache", tage_alt=3, kanal="email", subject="bAV für Ihr Team")
    _draft(lead, None, tage_alt=2, kanal="email", subject="Oktober-News",
           newsletter="00000000-0000-0000-0000-000000000001")
    server._q("insert into activities (lead_id, type, payload) values (%s,'termin',%s) returning id",
              (lead, json.dumps({"datum": "2026-10-20", "uhrzeit": "10:00", "thema": "Erstgespräch"})))
    with server.pool.connection() as c:
        c.execute("insert into sales_test.activities (lead_id, type, payload, created_at) "
                  "select %s, 'nachricht_ausgehend', '{\"text\":\"hi\"}', now() - (g || ' hours')::interval "
                  "from generate_series(1, 5000) g", (lead,))
    h = hi.kontakt_historie(lead)
    arten = [e["art"] for e in h]
    assert "entwurf" in arten and "newsletter" in arten and "termin" in arten and "handy" in arten
    handy = [e for e in h if e["art"] == "handy"]
    assert all("Nachrichten" in e["text"] for e in handy) and len(handy) <= 13
    assert h == sorted(h, key=lambda e: e["datum"], reverse=True)
    assert hi.zuletzt(lead)["art"] != "handy"


def test_thema_ueber_80_zeichen_unterscheidet_sich_erst_danach():
    lead = _lead()
    basis = "a" * 80
    _draft(lead, basis + " erste Variante", tage_alt=2)
    assert len(hi.doppelt_pruefen(lead, basis + " ganz anderer Schluss")) == 1
    assert len(hi.doppelt_pruefen(lead, "\t" + basis + "\n  x")) == 1


def test_thema_mit_tab_und_zeilenumbruch_stimmt_mit_sql_ueberein():
    lead = _lead()
    _draft(lead, "bAV\t Erst\nansprache", tage_alt=2)
    assert len(hi.doppelt_pruefen(lead, "bav erst ansprache")) == 1
    assert len(hi.doppelt_pruefen(lead, " BAV \t Erst\n ansprache ")) == 1
    assert hi.doppelt_pruefen(lead, "bav erstansprache") == []
