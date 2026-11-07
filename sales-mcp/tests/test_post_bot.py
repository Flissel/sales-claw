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
def welt(monkeypatch):
    # Ein Container = ein Nutzer: der Bot sieht nur die Mails des Besitzers
    # dieses Containers (POST_BESITZER).
    monkeypatch.setenv("POST_BESITZER", "t9_anna")
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


def test_bot_sieht_keine_mail_eines_anderen_besitzers(monkeypatch):
    mid = _mail(betreff="Annas Geschaeft")
    monkeypatch.setenv("POST_BESITZER", "t9_ben")
    assert _lesen()["mails"] == []
    assert json.loads(server.postfach_mail_lesen(f"post:{mid}")) == {
        "fehler": "nicht verfuegbar"}
    monkeypatch.setenv("POST_BESITZER", "")
    assert _lesen()["mails"] == []


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


def test_bot_sieht_das_unterfach():
    """M5 (v2): Liste und Einzelmail nennen neben dem Fach das Unterfach."""
    mid = _mail(fach="Tools & Dienste")
    server._q("update post_mails set unterfach = 'GitHub' where id = %s", (mid,))
    ohne = _mail(betreff="Ohne Unterfach")
    liste = {m["uid"]: m for m in _lesen()["mails"]}
    assert liste[f"post:{mid}"]["unterfach"] == "GitHub"
    assert liste[f"post:{ohne}"]["unterfach"] is None
    einzeln = json.loads(server.postfach_mail_lesen(f"post:{mid}"))
    assert (einzeln["fach"], einzeln["unterfach"]) == ("Tools & Dienste", "GitHub")


def _lesen_spion(monkeypatch, mid=None):
    geholt = []
    monkeypatch.setattr(server.postfach, "eingerichtet", lambda uid="": True)
    monkeypatch.setattr(server.postfach, "lesen",
                        lambda uid, protokollieren=True: geholt.append(uid) or {
                            "uid": uid, "von": "k@kunde.de", "betreff": "Hi",
                            "text": "t", "message_id": mid or "<m@x>",
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
        (konto_id, imap_uid, "m@x" if bereich == "business" else f"t9r{imap_uid}", bereich,
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


def _zaehler_aktionen():
    return (server._q("select count(*) n from drafts")[0]["n"],
            server._q("select count(*) n from activities")[0]["n"])


def test_falsche_message_id_tut_nichts(monkeypatch):
    # UIDVALIDITY-Wechsel: die Nummer zeigt auf eine andere Mail.
    geholt = _lesen_spion(monkeypatch, mid="<ANDERE@x>")
    verschoben = []
    monkeypatch.setattr(server.postfach, "verschieben",
                        lambda uid, art: verschoben.append(uid) or "Spam")
    mid = _mail_in(_env_konto("haupt", "env"), 17)
    vorher = _zaehler_aktionen()
    for r in (server.mail_beantworten(f"post:{mid}", "Danke"),
              server.mail_einstufen(f"post:{mid}", "spam", "g"),
              server.mail_einstufen(f"post:{mid}", "unwichtig", "g")):
        assert json.loads(r) == {"fehler": "nicht verfuegbar"}
    assert geholt == ["17", "17", "17"]       # gelesen, aber nichts getan
    assert verschoben == [] and _zaehler_aktionen() == vorher


def test_passende_message_id_normalisiert(monkeypatch):
    _lesen_spion(monkeypatch, mid="  <M@X> ")
    mid = _mail_in(_env_konto("haupt", "env"), 17)
    assert "fehler" not in json.loads(server.mail_beantworten(f"post:{mid}", "ok"))


def test_ersatz_message_id_passt_nie(monkeypatch):
    """M3: der ECHTE Platzhalter (wie post_abholen ihn fuer Mails ohne
    Message-ID schreibt). Liegt unter der Nummer inzwischen eine Mail, deren
    Message-ID zufaellig/gefaelscht genau so lautet, darf sie trotzdem nicht als
    dieselbe gelten - die post:-uid wird vor jedem IMAP-Zugriff abgelehnt."""
    geholt = _lesen_spion(monkeypatch, mid="<haupt:17@sales-post>")
    konto = _env_konto("haupt", "env")
    mid = str(server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, message_id_ersatz, "
        "besitzer, von, betreff, bereich, fach, sensibel, datum) values (%s, 17, "
        "'haupt:17@sales-post', true, 't9_anna', 'k@kunde.de', 'x', 'business', "
        "'Kunden & Anfragen', false, now()) returning id", (konto,))[0]["id"])
    vorher = _zaehler_aktionen()
    for r in (server.mail_beantworten(f"post:{mid}", "x"),
              server.mail_einstufen(f"post:{mid}", "spam", "g")):
        assert "keine Message-ID" in json.loads(r)["fehler"]
    assert geholt == [] and _zaehler_aktionen() == vorher


def test_alte_gmx_uids_auch_bei_leerer_sammelstelle_gesperrt(monkeypatch):
    """M1 / R15: GMX/Gmail nie live - auch nicht ueber Antworten/Aufraeumen,
    solange die Sammelstelle leer ist. Das Hauptpostfach bleibt erreichbar."""
    geholt = _lesen_spion(monkeypatch)
    assert server._sammelstelle_leer()
    for uid in ("gmx:12", "gmail:3", " gmx:4 "):
        assert json.loads(server.mail_beantworten(uid, "x")) == {
            "fehler": "nicht verfuegbar"}, uid
        assert json.loads(server.mail_einstufen(uid, "unwichtig", "g")) == {
            "fehler": "nicht verfuegbar"}, uid
    assert geholt == []
    server.mail_einstufen("42", "unwichtig", "Werbung")
    assert geholt == ["42"]


# --- I1/M2: Kalenderantworten aus der Sammelstelle --------------------------

class _Kasten:
    """IMAP-Attrappe fuer postfach.lesen: nur select(readonly) und fetch."""

    def __init__(self, mails):
        self.mails = mails

    def select(self, ordner, readonly=False):
        assert readonly is True
        return "OK", [b"1"]

    def uid(self, befehl, *args):
        assert befehl == "fetch", befehl
        roh = self.mails.get(args[0])
        return ("OK", [(args[0] + b" (RFC822 ...)", roh)]) if roh else ("NO", [None])

    def logout(self):
        return "BYE", []


def _kalender_mail(message_id, von="Ivan Beispiel <ivan@t9.example>"):
    import email.message
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
           "UID:t9-termin-1\r\nSEQUENCE:0\r\n"
           "ATTENDEE;PARTSTAT=ACCEPTED:mailto:ivan@t9.example\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    n = email.message.EmailMessage()
    n["From"] = von
    n["To"] = "buero@t9.example"
    n["Subject"] = "Angenommen: Erstgespraech"
    n["Message-ID"] = f"<{message_id}>"
    n.set_content("Siehe Anhang.")
    n.add_attachment(ics.encode(), maintype="text", subtype="calendar", filename="r.ics")
    return n.as_bytes()


@pytest.fixture
def kalender_welt(monkeypatch):
    """Hauptpostfach als env-Konto, Ivan als Kontakt, IMAP als Attrappe mit
    einer Kalenderantwort unter Nummer 17."""
    pf = server.postfach
    monkeypatch.setattr(pf, "IMAP_HOST", "imap.t9.invalid")
    monkeypatch.setattr(pf, "IMAP_USER", "buero@t9.example")
    kasten = _Kasten({})
    monkeypatch.setattr(pf, "_verbinden", lambda: kasten)
    with server.pool.connection() as conn:
        conn.execute("delete from activities where lead_id in (select id from leads "
                      "where email = 'ivan@t9.example')")
        conn.execute("delete from leads where email = 'ivan@t9.example'")
    lead = str(server._q("insert into leads (name, email, source) values "
                         "('Ivan T9', 'ivan@t9.example', 'email') returning id")[0]["id"])
    konto = _env_konto("haupt", "env")
    mail_id = str(server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, "
        "betreff, text, bereich, fach, sensibel, datum, kalenderteil) values "
        "(%s, 17, 't9-antwort@x', 't9_anna', 'Ivan Beispiel <ivan@t9.example>', "
        "'Angenommen: Erstgespraech', 'Siehe Anhang.', 'business', "
        "'Kunden & Anfragen', false, now(), true) returning id", (konto,))[0]["id"])
    yield {"kasten": kasten, "lead": lead, "mail": mail_id, "konto": konto}
    with server.pool.connection() as conn:
        conn.execute("delete from activities where lead_id = %s", (lead,))
        conn.execute("delete from leads where id = %s", (lead,))
        conn.execute("delete from postfach_mails where message_id = 't9-antwort@x'")


def _antworten(lead):
    return server._q("select payload from activities where lead_id = %s and "
                     "type = 'einladung_antwort'", (lead,))


def test_kalenderantwort_aus_der_sammelstelle_wird_festgehalten(kalender_welt):
    w = kalender_welt
    w["kasten"].mails[b"17"] = _kalender_mail("t9-antwort@x")
    liste = _lesen()["mails"]
    assert [m["kalenderteil"] for m in liste] == [True]
    r = json.loads(server.postfach_mail_lesen(f"post:{w['mail']}"))
    assert r["kalenderteil"] is True and r["text"] == "Siehe Anhang."
    assert r["kalender_antwort"]["status"] == "ACCEPTED"
    assert "protokollierfehler" not in r and "kalender_hinweis" not in r
    zeilen = _antworten(w["lead"])
    assert len(zeilen) == 1 and zeilen[0]["payload"]["uid"] == "t9-termin-1"
    # Erneutes Oeffnen legt keine zweite Aktivitaet an (Dedup in postfach).
    server.postfach_mail_lesen(f"post:{w['mail']}")
    assert len(_antworten(w["lead"])) == 1


def test_kalenderantwort_fremde_mail_unter_der_nummer_haelt_nichts_fest(kalender_welt):
    """M2: nach einem UIDVALIDITY-Wechsel liegt unter 17 eine ANDERE
    Kalenderantwort - sie darf nicht festgehalten werden, weder beim Oeffnen
    noch beim Antworten oder Aufraeumen (vorher hielt postfach.lesen sie fest,
    bevor die Message-ID geprueft war)."""
    w = kalender_welt
    w["kasten"].mails[b"17"] = _kalender_mail("ANDERE@x")
    r = json.loads(server.postfach_mail_lesen(f"post:{w['mail']}"))
    assert "kalender_antwort" not in r and "kalender_hinweis" in r
    assert r["betreff"] == "Angenommen: Erstgespraech"          # Anzeige aus der Sammelstelle
    for fn in (lambda: server.mail_beantworten(f"post:{w['mail']}", "Danke"),
               lambda: server.mail_einstufen(f"post:{w['mail']}", "unwichtig", "g")):
        assert json.loads(fn()) == {"fehler": "nicht verfuegbar"}
    assert _antworten(w["lead"]) == []


def test_antworten_auf_kalenderantwort_haelt_sie_nach_der_pruefung_fest(kalender_welt):
    w = kalender_welt
    w["kasten"].mails[b"17"] = _kalender_mail("t9-antwort@x")
    r = json.loads(server.mail_einstufen(f"post:{w['mail']}", "unwichtig", "Info"))
    assert r.get("vorgeschlagen") is True
    assert len(_antworten(w["lead"])) == 1


def test_kalenderteil_ohne_live_zugang_gibt_hinweis(kalender_welt, monkeypatch):
    w = kalender_welt
    server._q("update post_konten set quelle = 'ui' where id = %s returning 1",
              (str(w["konto"]),))
    monkeypatch.setattr(server.postfach, "lesen",
                        lambda *a, **k: pytest.fail("kein IMAP fuer ui-Konten"))
    r = json.loads(server.postfach_mail_lesen(f"post:{w['mail']}"))
    assert "kalender_hinweis" in r and r["text"] == "Siehe Anhang."
    # Ohne Kalenderteil wird nie live gelesen.
    server._q("update post_mails set kalenderteil = false where id = %s returning 1",
              (w["mail"],))
    r = json.loads(server.postfach_mail_lesen(f"post:{w['mail']}"))
    assert r["kalenderteil"] is False and "kalender_hinweis" not in r


def test_inaktives_konto_ohne_imap(monkeypatch):
    geholt = _lesen_spion(monkeypatch)
    konto = _env_konto("haupt", "env")
    mid = _mail_in(konto, 17)
    server._q("update post_konten set aktiv = false where id = %s returning 1",
              (str(konto),))
    for r in (server.mail_beantworten(f"post:{mid}", "x"),
              server.mail_einstufen(f"post:{mid}", "spam", "g")):
        assert "fehler" in json.loads(r)
    assert geholt == []


def test_sammelstelle_liest_nur_konten_des_container_besitzers(monkeypatch):
    """I8: Konten anderer Besitzer sind fuer den Bot unsichtbar - auch ihre Kennungen
    tauchen in keiner Fehlermeldung auf; ohne Besitzer verhaelt er sich wie ohne Konten."""
    _mail(kennung="annas-konto", betreff="Annas Geschaeft")
    server._q("insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
              "values ('t9_ben', 'bens-geheimes-konto', 'gmx', 'b@b.de', 'ui') returning id")
    r = _lesen(postfach="bens-geheimes-konto")
    assert "fehler" in r and "bens-geheimes-konto" in r["fehler"]      # der angefragte Name
    assert "annas-konto" in r["fehler"]                                  # eigene Liste
    r = _lesen(postfach="nirgends")
    assert "bens-geheimes-konto" not in r["fehler"] and "annas-konto" in r["fehler"]
    assert _lesen(postfach="bens-geheimes-konto")["fehler"].count("bens-geheimes-konto") == 1
    monkeypatch.setenv("POST_BESITZER", "")
    r = _lesen(postfach="annas-konto")
    assert "fehler" in r and "annas-konto" not in r["fehler"].split("eingerichtet:")[-1]
