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


def test_alte_uids_nur_fuers_hauptpostfach(monkeypatch):
    geholt = []
    monkeypatch.setattr(server.postfach, "eingerichtet", lambda uid="": True)
    monkeypatch.setattr(server.postfach, "lesen",
                        lambda uid: geholt.append(uid) or {"uid": uid})
    _mail()                                    # Sammelstelle hat Zeilen
    for uid in ("gmx:12", "gmail:3", "-5", "haupt:-1", "abc"):
        assert json.loads(server.postfach_mail_lesen(uid)) == {
            "fehler": "nicht verfuegbar"}
    assert geholt == []                        # nie per IMAP angefasst
    assert json.loads(server.postfach_mail_lesen("42")) == {"uid": "42"}
    assert geholt == ["42"]


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
