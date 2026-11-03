"""Der Bot liest aus der Post-Sammelstelle (Task 9, Spec §14.3).

Verteidigt: der Bot sieht nie Privates, nie Sensibles; Suche geht ueber alle
Konten; `post:<id>` wird gelesen, Unsichtbares antwortet wie Unbekanntes; ohne
jede Sammelstellen-Zeile bleibt der alte IMAP-Weg - nur fuers Hauptpostfach.
"""
import json
import os
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

AGENTS_MD = Path(__file__).resolve().parents[2] / "config" / "workspace" / "AGENTS.md"
_zaehler = [0]


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def welt():
    _leeren()
    yield
    _leeren()


def _leeren():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_mails, sales_test.post_konten cascade")


def _konto(kennung):
    return server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
        "values ('t9_anna', %s, 'gmx', 'a@b.de', 'ui') "
        "on conflict (kennung) do update set besitzer = excluded.besitzer "
        "returning id", (kennung,))[0]["id"]


def _mail(kennung="haupt", bereich="business", fach="Kunden & Anfragen",
          sensibel=False, betreff="Angebot", text="Hallo Welt"):
    _zaehler[0] += 1
    return str(server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, "
        "betreff, text, auszug, bereich, fach, sensibel, datum) values "
        "(%s, %s, %s, 't9_anna', 'x@y.de', %s, %s, %s, %s, %s, %s, now()) "
        "returning id",
        (_konto(kennung), _zaehler[0], f"t9m{_zaehler[0]}", betreff, text,
         text[:20], bereich, fach, sensibel))[0]["id"])


def _lesen(**kw):
    return json.loads(server.postfach_lesen(**kw))


def test_bot_sieht_keine_private_mail():
    privat = _mail(bereich="privat", fach="Familie & Freunde", betreff="Geheimprivat")
    _mail(betreff="Geschaeft")
    uids = {m["uid"] for m in _lesen()["mails"]}
    assert f"post:{privat}" not in uids and len(uids) == 1
    assert _lesen(suche="Geheimprivat")["mails"] == []
    assert json.loads(server.postfach_mail_lesen(f"post:{privat}")) == {
        "fehler": "nicht verfuegbar"}


def test_bot_sieht_keine_sensible_mail():
    sens = _mail(sensibel=True, betreff="Kontoauszug", text="IBAN DE89 geheim")
    assert _lesen()["mails"] == []
    assert _lesen(suche="IBAN")["mails"] == []
    assert json.loads(server.postfach_mail_lesen(f"post:{sens}")) == {
        "fehler": "nicht verfuegbar"}


def test_bot_sucht_ueber_alle_konten():
    _mail(kennung="haupt", betreff="Rechnung Telekom")
    _mail(kennung="gmx", betreff="Rechnung Strom")
    _mail(kennung="gmx", betreff="Hallo")
    r = _lesen(suche="Rechnung")
    assert {m["postfach"] for m in r["mails"]} == {"haupt", "gmx"}
    assert r["anzahl"] == 2
    nur = _lesen(postfach="gmx")
    assert {m["postfach"] for m in nur["mails"]} == {"gmx"} and nur["anzahl"] == 2
    assert set(r["mails"][0]) >= {"uid", "von", "betreff", "datum", "auszug", "postfach"}
    assert "fehler" in _lesen(postfach="nirgends")


def test_post_uid_wird_gelesen():
    mid = _mail(betreff="Angebot Q4", text="Volltext hier")
    m = json.loads(server.postfach_mail_lesen(f"post:{mid}"))
    assert m["uid"] == f"post:{mid}" and m["text"] == "Volltext hier"
    assert m["betreff"] == "Angebot Q4" and m["postfach"] == "haupt"
    for kaputt in ("post:", "post:kein-uuid",
                   "post:00000000-0000-0000-0000-000000000000"):
        assert json.loads(server.postfach_mail_lesen(kaputt)) == {
            "fehler": "nicht verfuegbar"}


def _lesen_spion(monkeypatch):
    geholt = []
    monkeypatch.setattr(server.postfach, "eingerichtet", lambda uid="": True)
    monkeypatch.setattr(server.postfach, "lesen",
                        lambda uid: geholt.append(uid) or {
                            "uid": uid, "von": "k@kunde.de", "betreff": "Hi",
                            "text": "t", "message_id": "<m@x>",
                            "postfach": "haupt"})
    return geholt


def test_alte_uids_nur_bei_leerer_sammelstelle(monkeypatch):
    geholt = _lesen_spion(monkeypatch)
    assert json.loads(server.postfach_mail_lesen("42"))["uid"] == "42"
    assert geholt == ["42"]
    _mail()                                    # Sammelstelle hat Zeilen
    geholt.clear()
    for uid in ("42", "gmx:12", "gmail:3", "-5", "haupt:-1", "abc"):
        assert json.loads(server.postfach_mail_lesen(uid)) == {
            "fehler": "nicht verfuegbar"}
        assert json.loads(server.mail_beantworten(uid, "x")) == {
            "fehler": "nicht verfuegbar"}
        assert json.loads(server.mail_einstufen(uid, "unwichtig", "g")) == {
            "fehler": "nicht verfuegbar"}
    assert geholt == []                        # nie per IMAP angefasst


def _env_konto(kennung, quelle):
    return server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
        "values ('t9_anna', %s, 'gmx', 'a@b.de', %s) "
        "on conflict (kennung) do update set quelle = excluded.quelle "
        "returning id", (kennung, quelle))[0]["id"]


def _mail_in(konto_id, imap_uid, bereich="business", sensibel=False,
             fach="Kunden & Anfragen"):
    return str(server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, "
        "betreff, bereich, fach, sensibel, datum) values (%s, %s, %s, 't9_anna', "
        "'k@kunde.de', 'Anfrage', %s, %s, %s, now()) returning id",
        (konto_id, imap_uid, f"t9r{imap_uid}{bereich}{sensibel}", bereich,
         fach if bereich == "business" else "Familie & Freunde", sensibel))[0]["id"])


def test_post_uid_wird_fuer_antworten_uebersetzt(monkeypatch):
    geholt = _lesen_spion(monkeypatch)
    mid = _mail_in(_env_konto("haupt", "env"), 17)
    r = json.loads(server.mail_beantworten(f"post:{mid}", "Danke"))
    assert geholt == ["17"] and "fehler" not in r
    gmx = _mail_in(_env_konto("gmx", "env"), 5)
    server.mail_einstufen(f"post:{gmx}", "unwichtig", "Werbung")
    assert geholt[-1] == "gmx:5"


def test_post_uid_ohne_antwortrecht_ruft_nie_imap(monkeypatch):
    geholt = _lesen_spion(monkeypatch)
    env = _env_konto("haupt", "env")
    ui = _env_konto("ui-konto", "ui")
    faelle = {
        "privat": _mail_in(env, 1, bereich="privat"),
        "sensibel": _mail_in(env, 2, sensibel=True),
        "ui": _mail_in(ui, 3),
        "negativ": _mail_in(env, -4),
        "unbekannt": "00000000-0000-0000-0000-000000000000",
    }
    for name, mid in faelle.items():
        for r in (server.mail_beantworten(f"post:{mid}", "x"),
                  server.mail_einstufen(f"post:{mid}", "spam", "g")):
            assert "fehler" in json.loads(r), name
    assert geholt == []
    assert "Stufe 2" in json.loads(
        server.mail_beantworten(f"post:{faelle['ui']}", "x"))["fehler"]


def test_fehlende_tabelle_gilt_als_leer(monkeypatch):
    import psycopg

    def kaputt(*a, **k):
        raise psycopg.errors.UndefinedTable("post_mails")
    monkeypatch.setattr(server, "_q", kaputt)
    assert server._sammelstelle_leer() is True


def test_rueckfall_ohne_sammelstelle(monkeypatch):
    gerufen = []

    def liste(anzahl, kennung):
        gerufen.append(kennung)
        return [{"uid": "7", "von": "a@b.de", "betreff": "Alt", "datum": "x",
                 "auszug": "", "postfach": "haupt"}]
    monkeypatch.setattr(server.postfach_modul, "eingerichtet", lambda uid="": True)
    monkeypatch.setattr(server.postfach_modul, "kennungen", lambda: ["haupt", "gmx"])
    monkeypatch.setattr(server.postfach_modul, "liste", liste)
    monkeypatch.setattr(server, "_postfach_merken", lambda m: None)
    r = _lesen()
    assert r["mails"][0]["uid"] == "7" and gerufen == ["haupt"]
    # GMX/Gmail: nie live, auch nicht bei leerer Sammelstelle.
    assert _lesen(postfach="gmx")["mails"] == [] and gerufen == ["haupt"]
    # Sobald die Sammelstelle Zeilen hat, ist der IMAP-Weg zu.
    _mail()
    _lesen()
    assert gerufen == ["haupt"]


def test_agents_md_unter_grenze():
    text = AGENTS_MD.read_text(encoding="utf-8")
    assert len(text) < 100000
    assert "post:<id>" in text and "Sammelstelle" in text
