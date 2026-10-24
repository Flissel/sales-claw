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


# --- Task 4: Werkzeuge mit Thema, Doppel-Warnung, Historie lesen ---------

import inspect  # noqa: E402


def _kunde_mit_freigabe():
    """Tore oeffnen wie in tests/test_werkzeuge.py (_wa_freigeben/_anlegen):
    WhatsApp-Freigabe direkt in enrichment, Einwilligung opt_in."""
    lead = _lead()
    server._q("update leads set consent_status = 'opt_in', enrichment = jsonb_set("
              "coalesce(enrichment, '{}'::jsonb), '{whatsapp_freigabe}', "
              "'{\"freigegeben\": true}'::jsonb, true) where id = %s returning id", (lead,))
    return lead


def _bestaetigt():
    return server._q("select count(*) n from activities where type='doppelt_bestaetigt'")[0]["n"]


def test_entwurf_mit_thema_warnt_bei_doppelt_und_trotzdem_legt_an():
    lead = _kunde_mit_freigabe()
    r1 = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo 1", thema="bAV Erstansprache"))
    assert "draft_id" in r1, r1
    assert server._q("select thema from drafts where id=%s", (r1["draft_id"],))[0]["thema"] == "bAV Erstansprache"
    r2 = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo 2", thema="bav  erstansprache"))
    assert "draft_id" not in r2 and r2["doppelt"] and r2["hinweis"].endswith("Dann trotzdem=True.")
    assert r2["doppelt"][0]["draft_id"] == str(r1["draft_id"])
    r3 = json.loads(server.entwurf_erstellen(lead, "whatsapp", "Hallo 3", thema="bav erstansprache",
                                             trotzdem=True))
    assert "draft_id" in r3
    assert _bestaetigt() == 1
    p = server._q("select payload from activities where type='doppelt_bestaetigt'")[0]["payload"]
    assert p["draft_id"] == str(r3["draft_id"]) and p["thema"] == "bav erstansprache"


def test_trotzdem_ohne_treffer_bucht_nichts():
    lead = _kunde_mit_freigabe()
    assert "draft_id" in json.loads(server.entwurf_erstellen(lead, "whatsapp", "A", thema="neu",
                                                             trotzdem=True))
    assert _bestaetigt() == 0


def test_ohne_thema_keine_pruefung():
    lead = _kunde_mit_freigabe()
    assert "draft_id" in json.loads(server.entwurf_erstellen(lead, "whatsapp", "A"))
    assert "draft_id" in json.loads(server.entwurf_erstellen(lead, "whatsapp", "B"))


def test_thema_wird_auf_200_zeichen_begrenzt():
    lead = _kunde_mit_freigabe()
    r = json.loads(server.entwurf_erstellen(lead, "whatsapp", "A", thema="x" * 300))
    assert len(server._q("select thema from drafts where id=%s", (r["draft_id"],))[0]["thema"]) == 200


def test_antwort_entwerfen_prueft_einmal_und_bucht_einmal():
    lead = _kunde_mit_freigabe()
    _draft(lead, "Angebot Homelab", status="pending")
    r = json.loads(server.antwort_entwerfen(lead, "Hallo", auftrag_betreiber=True, thema="angebot homelab"))
    assert "draft_id" not in r and r["doppelt"]
    r = json.loads(server.antwort_entwerfen(lead, "Hallo", auftrag_betreiber=True, thema="angebot homelab",
                                            trotzdem=True))
    assert "draft_id" in r, r
    assert server._q("select thema from drafts where id=%s", (r["draft_id"],))[0]["thema"] == "angebot homelab"
    assert _bestaetigt() == 1


def test_mail_beantworten_prueft_und_speichert_thema(monkeypatch):
    mail = {"uid": "7", "von": "Leo <leo@example.com>", "betreff": "Frage", "text": "Hallo",
            "message_id": "m-7@example.com"}
    monkeypatch.setattr(server.postfach, "konfiguriert", lambda: True)
    monkeypatch.setattr(server.postfach, "lesen", lambda uid: mail)
    a = json.loads(server.mail_beantworten("7", "Hallo Leo", thema="bAV Angebot"))
    assert server._q("select thema from drafts where id=%s", (a["draft_id"],))[0]["thema"] == "bAV Angebot"
    b = json.loads(server.mail_beantworten("7", "Nochmal", thema="bav angebot"))
    assert "draft_id" not in b and b["doppelt"]
    c = json.loads(server.mail_beantworten("7", "Nochmal", thema="bav angebot", trotzdem=True))
    assert "draft_id" in c and _bestaetigt() == 1


def test_signaturen():
    assert list(inspect.signature(server.entwurf_erstellen).parameters) == [
        "lead_id", "kanal", "text", "betreff", "medien_datei", "auftrag_betreiber", "thema", "trotzdem"]
    assert list(inspect.signature(server.antwort_entwerfen).parameters) == [
        "lead_id", "text", "medien_datei", "auftrag_betreiber", "thema", "trotzdem"]
    assert list(inspect.signature(server.mail_beantworten).parameters) == ["uid", "text", "thema", "trotzdem"]
    assert list(inspect.signature(server.kontakt_historie_lesen).parameters) == ["lead_id"]
    assert server.kontakt_historie_lesen in server.WERKZEUGE


def test_profil_und_historie_werkzeug():
    lead = _lead()
    _draft(lead, "Homelab-Angebot", tage_alt=4)
    p = json.loads(server.profil_lesen(lead))
    assert p["zuletzt_angeschrieben"]["text"] == "Homelab-Angebot" and len(p["historie_kurz"]) == 1
    h = json.loads(server.kontakt_historie_lesen(lead))
    assert h["historie"][0]["text"] == "Homelab-Angebot"


def test_profil_ohne_historie():
    p = json.loads(server.profil_lesen(_lead()))
    assert p["zuletzt_angeschrieben"] is None and p["historie_kurz"] == []


def test_newsletter_und_post_tragen_thema(monkeypatch):
    lead = _lead()
    server._q("update leads set consent_status='opt_in', email='a@example.com' where id=%s returning id", (lead,))
    monkeypatch.setattr(server.newsletter_text, "einsetzen", lambda h, t, v, a: (h, t))
    r = server._newsletter_entwurf(lead, "6f1c1d6e-0000-4000-8000-000000000001", "Herbst", "<p>x</p>", "x", [])
    assert "draft_id" in r, r
    assert server._q("select thema from drafts where id=%s", (r["draft_id"],))[0]["thema"] == "Newsletter: Herbst"
    assert r["draft_id"] in [str(t["draft_id"]) for t in hi.doppelt_pruefen(lead, "newsletter: herbst")]


def test_post_traegt_thema(monkeypatch):
    sammel = str(server._q("insert into leads (name, source) values ('LINKEDIN (Eigenes Profil)', 'system') "
                           "returning id")[0]["id"])
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", sammel)
    r = json.loads(server.post_entwurf_erstellen("bAV im Handwerk", "Text"))
    assert server._q("select thema from drafts where id=%s", (r["draft_id"],))[0]["thema"] == "bAV im Handwerk"


def test_absage_per_whatsapp_traegt_thema_termin():
    lead = _kunde_mit_freigabe()
    server.kunde_benachrichtigen(lead, {"datum": "2026-11-02", "uhrzeit": "10:00", "thema": "Beratung"}, None)
    assert [z["thema"] for z in server._q("select thema from drafts where lead_id=%s", (lead,))] == ["termin"]


def test_einladung_traegt_thema_termin_und_wird_nie_geprueft(monkeypatch):
    import mail_dispatch
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "buero@vibemind.space")
    lead = str(server._q("insert into leads (name, email, phone, source, consent_status) values "
                         "('Ivan', 'ivan@vibemind.space', '+491701234567', 'whatsapp', "
                         "'existing_customer') returning id")[0]["id"])
    for tag in ("2099-11-02", "2099-11-03"):
        a = json.loads(server.termin_einladen(lead, tag, "14:30", thema="Erstgespräch"))
        assert "fehler" not in a, a
    assert [z["thema"] for z in server._q("select thema from drafts where lead_id=%s", (lead,))] == \
        ["termin", "termin"]


# --- Schluss-Fix (Final Review 17.10.2026) ------------------------------

import logging  # noqa: E402

import psycopg  # noqa: E402


def _ohne_thema_spalte(monkeypatch):
    """Simuliert eine Datenbank ohne drafts.thema (provision.sql fehlt)."""
    echt = server._q

    def _q(sql, params=()):
        if "thema" in sql:
            raise psycopg.errors.UndefinedColumn('column "thema" does not exist')
        return echt(sql, params)
    monkeypatch.setattr(server, "_q", _q)


def test_doppelt_ohne_thema_spalte_leer_mit_warnung(monkeypatch, caplog):
    lead = _lead()
    _ohne_thema_spalte(monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert hi.doppelt_pruefen(lead, "bAV Erstansprache") == []
    assert any("thema" in r.getMessage() or "Historie" in r.getMessage()
               for r in caplog.records if r.levelno >= logging.WARNING)


def test_historie_ohne_thema_spalte_laeuft_ohne_entwuerfe_weiter(monkeypatch):
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values (%s,'termin',%s) returning id",
              (lead, json.dumps({"datum": "2026-10-20", "uhrzeit": "10:00", "thema": "Erstgespräch"})))
    _ohne_thema_spalte(monkeypatch)
    h = hi.kontakt_historie(lead)
    assert [e["art"] for e in h] == ["termin"]
    assert hi.zuletzt(lead)["art"] == "termin"


def test_profil_lesen_ohne_thema_spalte(monkeypatch):
    lead = _lead()
    _ohne_thema_spalte(monkeypatch)
    p = json.loads(server.profil_lesen(lead))
    assert "fehler" not in p, p
    assert p["zuletzt_angeschrieben"] is None and p["historie_kurz"] == []
    assert json.loads(server.kontakt_historie_lesen(lead)) == {"historie": []}


def test_thema_vergleich_nbsp_wie_leerzeichen():
    lead = _lead()
    _draft(lead, "bAV\u00a0Erstansprache", tage_alt=2)
    assert len(hi.doppelt_pruefen(lead, "bAV Erstansprache")) == 1
    lead2 = _lead()
    _draft(lead2, "bAV Erstansprache", tage_alt=2)
    assert len(hi.doppelt_pruefen(lead2, "bAV\u00a0Erstansprache")) == 1


def test_thema_vergleich_umlaut_gross_klein():
    lead = _lead()
    _draft(lead, "ÜBERPRÜFUNG bAV", tage_alt=2)
    assert len(hi.doppelt_pruefen(lead, "überprüfung bav")) == 1


def test_handy_summe_wortlaut():
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s,'nachricht_ausgehend','{\"text\":\"hi\"}') returning id", (lead,))
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s,'nachricht_ausgehend','{\"text\":\"du\"}') returning id", (lead,))
    handy = [e for e in hi.kontakt_historie(lead) if e["art"] == "handy"]
    assert len(handy) == 1
    import re
    assert re.fullmatch(r"2 gesendete WhatsApp-Nachrichten \(Handy oder System\) im \d{2}/\d{4}",
                        handy[0]["text"]), handy[0]["text"]


def test_kanal_namen_der_beitragskanaele():
    assert hi._KANAL["telegram_kanal"] == "Telegram-Kanal"
    assert hi._KANAL["devto"] == "dev.to"
    assert hi._KANAL["bluesky"] == "Bluesky"
