"""Ursprüngliche Adresse weitergeleiteter Mails (Spec 2026-11-06 §8, Task 6).

Reine Tests (Kopfzeilen, Einordnung, Stichprobe) und DB-Tests für `nachtragen`
(nur sales_test). IMAP ist eine Attrappe, die nur Kopfzeilen kennt und jeden
anderen Abruf als Fehler meldet; die Sperre in conftest bleibt.
"""
import email
import os
import sys
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_herkunft  # noqa: E402
import post_einordnung as pe  # noqa: E402
from test_post_imap import FakeKasten  # noqa: E402

EIGENE = "felixbaumann404@gmail.com"
BLUEBATCH = "felix@bluebatch.example"


def _nachricht(**kopf) -> email.message.Message:
    zeilen = [f"{k.replace('_', '-')}: {v}" for k, v in kopf.items()]
    return email.message_from_string("\n".join(zeilen) + "\n\nText")


# --- urspruenglich ---------------------------------------------------------

def test_x_forwarded_to_gewinnt_vor_delivered_to():
    n = _nachricht(Delivered_To="zustellung@andere.example", X_Forwarded_To="Felix <FELIX@Bluebatch.example>")
    assert post_herkunft.urspruenglich(n, EIGENE) == BLUEBATCH


def test_eigene_kontoadresse_zaehlt_nicht():
    n = _nachricht(X_Forwarded_To=EIGENE.upper(), Delivered_To=EIGENE, X_Original_To=BLUEBATCH)
    assert post_herkunft.urspruenglich(n, EIGENE) == BLUEBATCH
    assert post_herkunft.urspruenglich(_nachricht(Delivered_To=EIGENE), EIGENE) is None


def test_ohne_kopfzeilen_none():
    assert post_herkunft.urspruenglich(_nachricht(Subject="Hallo"), EIGENE) is None


def test_nur_oberstes_vorkommen_je_kopfzeile_zaehlt():
    n = email.message_from_string(
        f"X-Forwarded-To: {BLUEBATCH}\nX-Forwarded-To: chef@business.example\n\nText")
    assert post_herkunft.urspruenglich(n, EIGENE) == BLUEBATCH
    # Oberstes ist die eigene Adresse: das gefaelschte tiefere Vorkommen zaehlt nicht.
    n = email.message_from_string(
        f"X-Forwarded-To: {EIGENE}\nX-Forwarded-To: chef@business.example\n\nText")
    assert post_herkunft.urspruenglich(n, EIGENE) is None


# --- ist_business ----------------------------------------------------------

def test_ist_business_genau_und_domain(monkeypatch):
    monkeypatch.setattr(post_herkunft, "BUSINESS_ADRESSEN", ("chef@firma.example", "bluebatch.example"))
    assert post_herkunft.ist_business("CHEF@firma.example")
    assert not post_herkunft.ist_business("anderer@firma.example")       # "@" = genaue Adresse
    assert post_herkunft.ist_business(BLUEBATCH)
    assert post_herkunft.ist_business("x@mail.bluebatch.example")
    assert not post_herkunft.ist_business("x@evilbluebatch.example")     # Domain-Ende, kein Suffix-Text
    assert not post_herkunft.ist_business(None) and not post_herkunft.ist_business("")


def test_ohne_einstellung_ist_nichts_business(monkeypatch):
    monkeypatch.setattr(post_herkunft, "BUSINESS_ADRESSEN", ())
    assert not post_herkunft.ist_business(BLUEBATCH)


# --- Einordnung ------------------------------------------------------------

PRIVAT = {"kennung": "gmail-felix404", "standard_bereich": "privat"}


@pytest.fixture
def _ohne_regeln(monkeypatch):
    monkeypatch.setattr(pe, "_regeln_laden", lambda: [])
    monkeypatch.setattr(pe.post_werbung, "geschuetzt", lambda besitzer, von: False)
    monkeypatch.setattr(post_herkunft, "BUSINESS_ADRESSEN", (BLUEBATCH,))


def _urteil(bereich, fach, **kw):
    u = {"bereich": bereich, "fach": fach, "unterfach": "", "sensibel": False,
         "sicher": True, "begruendung": "x", "aufmerksamkeit": False}
    u.update(kw)
    return u


def _aufruf(urteil):
    def aufruf(agent, schluessel, system, auftrag, funktion, **kw):
        return urteil
    return aufruf


def _mail(**kw):
    m = {"id": "11111111-1111-1111-1111-111111111111", "von": "a@example.org",
         "betreff": "Hallo", "datum": "2026-11-03", "text": "Inhalt", "besitzer": "felix"}
    m.update(kw)
    return m


def test_business_adresse_zieht_bereich_business(_ohne_regeln):
    urteil = _urteil("privat", "Rechnungen", aufmerksamkeit=True)
    e = pe.einordnen(_mail(urspruengliche_adresse=BLUEBATCH), PRIVAT, _aufruf(urteil))
    assert (e.bereich, e.fach) == ("business", "Rechnungen")
    assert e.aufmerksamkeit is True and e.quelle == "pruefer" and e.aufrufe == 2
    # Ohne die Adresse bleibt es privat.
    ohne = pe.einordnen(_mail(), PRIVAT, _aufruf(urteil))
    assert (ohne.bereich, ohne.fach) == ("privat", "Rechnungen")


def test_business_adresse_laesst_werbung_sicher_und_quelle(_ohne_regeln, monkeypatch):
    monkeypatch.setattr(pe.post_katalog, "treffer", lambda von: ("Werbung", None))
    monkeypatch.setattr(pe.post_werbung, "bleibt_immer_absender", lambda b, v: False)
    e = pe.einordnen(_mail(urspruengliche_adresse=BLUEBATCH), PRIVAT, _aufruf(_urteil("privat", "Werbung")))
    assert (e.bereich, e.fach, e.quelle, e.werbung_sicher) == ("business", "Werbung", "katalog", True)


def test_sensible_mail_wird_nie_business(_ohne_regeln):
    e = pe.einordnen(_mail(urspruengliche_adresse=BLUEBATCH), PRIVAT,
                     _aufruf(_urteil("privat", "Konten & Sicherheit", sensibel=True)))
    assert e.sensibel and e.bereich == "privat"
    fest = pe.einordnen(_mail(betreff="Ihr Sicherheitscode", urspruengliche_adresse=BLUEBATCH), PRIVAT,
                        _aufruf(None))
    assert fest.sensibel and fest.bereich == "privat"


def test_rein_privates_fach_und_zum_nachsehen_bleiben_privat(_ohne_regeln):
    e = pe.einordnen(_mail(urspruengliche_adresse=BLUEBATCH), PRIVAT,
                     _aufruf(_urteil("privat", "Gesundheit")))
    assert (e.bereich, e.fach) == ("privat", "Gesundheit")
    unklar = pe.einordnen(_mail(urspruengliche_adresse=BLUEBATCH), PRIVAT,
                          _aufruf(_urteil("privat", "Zum Nachsehen", sicher=False)))
    assert (unklar.bereich, unklar.fach) == ("privat", "Zum Nachsehen")


def test_fremde_urspruengliche_adresse_aendert_nichts(_ohne_regeln):
    e = pe.einordnen(_mail(urspruengliche_adresse="jemand@privat.example"), PRIVAT,
                     _aufruf(_urteil("privat", "Rechnungen")))
    assert e.bereich == "privat"


# --- Attrappe nur fuer Kopfzeilen ------------------------------------------

def _roh(message_id, **kopf):
    zeilen = [f"Message-ID: <{message_id}>", "From: Fremder <fremd@geheim.example>",
              "Subject: GEHEIMER BETREFF"]
    zeilen += [f"{k.replace('_', '-')}: {v}" for k, v in kopf.items()]
    return ("\r\n".join(zeilen) + "\r\n\r\nGEHEIMER INHALT").encode()


class KopfKasten(FakeKasten):
    """Liefert nur die ANGEFRAGTEN Kopfzeilen; jeder andere Abruf ist ein Fehler im Test."""

    def uid(self, befehl, *args):
        befehl = befehl.upper()
        args = tuple(a.decode() if isinstance(a, bytes) else a for a in args)
        self.protokoll.append(("uid", befehl) + args)
        inhalt = self.ordner[self.gewaehlt]
        if befehl == "SEARCH":
            assert args == (None, "ALL"), args
            return "OK", [" ".join(str(u) for u in sorted(inhalt)).encode()]
        assert befehl == "FETCH", befehl
        uid, was = int(args[0]), args[1]
        assert was.startswith("(BODY.PEEK[HEADER.FIELDS (") and "RFC822" not in was, was
        if uid not in inhalt:
            return "OK", [None]
        gewollt = {f.lower() for f in was[len("(BODY.PEEK[HEADER.FIELDS ("):].split(")")[0].split()}
        kopf = b""
        for zeile in inhalt[uid].split(b"\r\n\r\n")[0].split(b"\r\n"):
            if zeile.split(b":")[0].decode().lower() in gewollt:
                kopf += zeile + b"\r\n"
        return "OK", [(f"1 (UID {uid} BODY[HEADER.FIELDS] {{{len(kopf) + 2}}}".encode(),
                       kopf + b"\r\n"), b")"]


def test_stichprobe_gibt_nur_haeufigkeiten_aus():
    kasten = KopfKasten(ordner={"INBOX": {
        1: _roh("a@x", X_Forwarded_To="FELIX@bluebatch.example", Delivered_To=EIGENE),
        2: _roh("b@x", X_Forwarded_To="chef@bluebatch.example", Delivered_To=EIGENE),
        3: _roh("c@x", Delivered_To="jemand.fremdes@privat-domain.example"),
        4: _roh("d@x")}})
    # Konto-Zeile ohne Datenbank: die Stichprobe selbst braucht nur die Adresse.
    zaehler = post_herkunft.stichprobe({"adresse": EIGENE}, kasten, 30)
    text = post_herkunft.tabelle(zaehler)
    assert zaehler[("X-Forwarded-To", "bluebatch.example")] == 2
    assert zaehler[("Delivered-To", EIGENE)] == 2          # die eigene Kontoadresse darf voll stehen
    assert zaehler[("Delivered-To", "privat-domain.example")] == 1
    assert zaehler[("(keine der Kopfzeilen)", "-")] == 1
    # Nichts Fremdes in der Ausgabe: weder volle Fremdadressen noch Betreff, Absender, Inhalt.
    for verboten in ("felix@bluebatch", "chef@", "jemand.fremdes", "GEHEIMER", "fremd@geheim", "Subject", "From"):
        assert verboten.lower() not in text.lower(), verboten
    # Und der Abruf holte keine anderen Kopfzeilen als die Adress-Zeilen.
    for p in kasten.protokoll:
        if p[:2] == ("uid", "FETCH"):
            assert "SUBJECT" not in p[3].upper() and "FROM" not in p[3].upper()


def test_cli_stichprobe_ueber_verbinden_und_nur_n_neueste(monkeypatch):
    import post_konten
    monkeypatch.setattr(post_konten, "aktive_konten", lambda: [
        {"kennung": "gmail-felix404", "adresse": EIGENE}])
    kasten = KopfKasten(ordner={"INBOX": {
        u: _roh(f"{u}@x", X_Forwarded_To="a@bluebatch.example") for u in range(1, 6)}})
    ausgabe = []
    zaehler = post_herkunft.cli_stichprobe("gmail-felix404", 2, verbinden=lambda z: kasten,
                                           ausgabe=ausgabe.append)
    assert sum(zaehler.values()) == 2 and "bluebatch.example" in ausgabe[0]
    assert ("logout",) in kasten.protokoll
    with pytest.raises(SystemExit):
        post_herkunft.cli_stichprobe("gibt-es-nicht", verbinden=lambda z: kasten, ausgabe=ausgabe.append)


# --- nachtragen (Datenbank, nur sales_test) --------------------------------

@pytest.fixture
def db():
    import server
    assert server.SCHEMA == "sales_test", "Test laeuft nicht gegen sales_test"

    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_konten cascade")
    leeren()
    yield server
    leeren()


def _konto(server):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle, uidvalidity) "
            "values ('felix', 'gmail-felix404', 'gmail', %s, 'ui', 1) returning id",
            (EIGENE,)).fetchone()["id"]


def _mail_zeile(server, konto_id, uid, mid, ordner="INBOX", ordner_uid=None, sensibel=False,
                ersatz=False, adresse=None):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, status, "
            "message_id_ersatz, ordner, ordner_uid, sensibel, urspruengliche_adresse) "
            "values (%s, %s, %s, 'felix', 'x@y.example', 'eingeordnet', %s, %s, %s, %s, %s) "
            "returning id", (konto_id, uid, mid, ersatz, ordner, ordner_uid, sensibel,
                             adresse)).fetchone()["id"]


def _adresse(server, mail_id):
    return server._q("select urspruengliche_adresse as a from post_mails where id = %s",
                     (mail_id,))[0]["a"]


def test_nachtragen_holt_nur_kopfzeilen(db):
    k = _konto(db)
    konto_zeile = {"id": k, "kennung": "gmail-felix404", "adresse": EIGENE}
    inbox = _mail_zeile(db, k, 7, "m7@x")
    zur_info = _mail_zeile(db, k, 8, "m8@x", ordner="Zur Info", ordner_uid=3)
    platzhalter = _mail_zeile(db, k, -2, "m9@x")                 # UIDVALIDITY-Platzhalter
    ohne_uid = _mail_zeile(db, k, 11, "m11@x", ordner="Zur Info", ordner_uid=None)
    sensibel = _mail_zeile(db, k, 12, "m12@x", sensibel=True)
    schon = _mail_zeile(db, k, 13, "m13@x", adresse="alt@x.example")
    fremde_uid = _mail_zeile(db, k, 14, "gehoert-anders@x")      # UID zeigt auf eine andere Mail
    weg = _mail_zeile(db, k, 15, "m15@x")                        # UID gibt es nicht mehr
    kasten = KopfKasten(ordner={
        "INBOX": {7: _roh("m7@x", X_Forwarded_To=BLUEBATCH, Delivered_To=EIGENE),
                  12: _roh("m12@x", X_Forwarded_To=BLUEBATCH),
                  14: _roh("m14@x", X_Forwarded_To=BLUEBATCH)},
        "Zur Info": {3: _roh("m8@x", Delivered_To=EIGENE)}})
    n = post_herkunft.nachtragen(konto_zeile, kasten)
    assert n == {"verarbeitet": 4, "gefunden": 1, "uebersprungen": 0, "offen": 0}
    assert _adresse(db, inbox) == BLUEBATCH
    assert _adresse(db, zur_info) == ""                          # geprueft, keine Adresse
    assert _adresse(db, platzhalter) is None and _adresse(db, ohne_uid) is None
    assert _adresse(db, sensibel) is None                        # sensibel: nie anfassen
    assert _adresse(db, schon) == "alt@x.example"
    assert _adresse(db, fremde_uid) == "" and _adresse(db, weg) == ""
    abrufe = [p for p in kasten.protokoll if p[0] == "uid"]
    assert abrufe and all(p[1] == "FETCH" and p[3].startswith("(BODY.PEEK[HEADER.FIELDS (") for p in abrufe)
    assert not any("RFC822" in str(p) or "TEXT" in str(p) for p in kasten.protokoll)
    assert all(p[2] is True for p in kasten.protokoll if p[0] == "select")   # nur lesend
    # Zweite Runde: nichts mehr offen, kein Abruf.
    kasten.protokoll.clear()
    assert post_herkunft.nachtragen(konto_zeile, kasten) == {
        "verarbeitet": 0, "gefunden": 0, "uebersprungen": 0, "offen": 0}
    assert not [p for p in kasten.protokoll if p[0] == "uid"]


def test_nachtragen_beachtet_grenze(db):
    k = _konto(db)
    ids = [_mail_zeile(db, k, u, f"m{u}@x") for u in (1, 2, 3)]
    kasten = KopfKasten(ordner={"INBOX": {
        u: _roh(f"m{u}@x", X_Forwarded_To=BLUEBATCH) for u in (1, 2, 3)}})
    assert post_herkunft.nachtragen({"id": k, "kennung": "gmail-felix404", "adresse": EIGENE},
                                    kasten, grenze=2) == {
        "verarbeitet": 2, "gefunden": 2, "uebersprungen": 0, "offen": 1}
    assert sum(1 for i in ids if _adresse(db, i) is None) == 1


def test_nachtragen_zeilen_ohne_uid_verbrauchen_die_grenze_nicht(db):
    """I8: Platzhalter (INBOX, UID <= 0) und Ordner-Zeilen ohne UID stehen in der Sortierung
    vorn. Sie duerfen den Lauf nicht fuellen, sonst endete er ohne Fortschritt."""
    k = _konto(db)
    for u in (-1, -2, -3):
        _mail_zeile(db, k, u, f"p{u}@x")
    _mail_zeile(db, k, 20, "o20@x", ordner="To-Review", ordner_uid=None)
    gut = _mail_zeile(db, k, 21, "m21@x", ordner="Zur Info", ordner_uid=3)
    kasten = KopfKasten(ordner={"Zur Info": {3: _roh("m21@x", X_Forwarded_To=BLUEBATCH)}})
    zeile = {"id": k, "kennung": "gmail-felix404", "adresse": EIGENE}
    assert post_herkunft.nachtragen(zeile, kasten, grenze=3) == {
        "verarbeitet": 1, "gefunden": 1, "uebersprungen": 0, "offen": 0}
    assert _adresse(db, gut) == BLUEBATCH


def test_nachtragen_meldet_uebersprungene_und_offene(db, monkeypatch):
    import post_konten
    k = _konto(db)
    _mail_zeile(db, k, 7, "m7@x")
    _mail_zeile(db, k, 8, "m8@x", ordner="Gibt-es-nicht", ordner_uid=4)
    kasten = KopfKasten(ordner={"INBOX": {7: _roh("m7@x")}})
    monkeypatch.setattr(post_konten, "aktive_konten", lambda: [
        {"id": k, "kennung": "gmail-felix404", "adresse": EIGENE}])
    ausgabe = []
    n = post_herkunft.cli_nachtragen("gmail-felix404", verbinden=lambda z: kasten,
                                     ausgabe=ausgabe.append)
    assert n == {"verarbeitet": 1, "gefunden": 0, "uebersprungen": 1, "offen": 1}
    # Dieselbe Bezeichnung wie im Runbook (Schritt nachtragen).
    assert ausgabe == ["Verarbeitet: 1 (Adresse gefunden: 0, uebersprungen: 1), noch offen: 1"]


def test_neue_mail_bekommt_adresse_beim_abholen(db):
    import post_abholen
    n = email.message_from_bytes(_roh("neu@x", X_Forwarded_To=BLUEBATCH, Delivered_To=EIGENE))
    assert post_abholen._mail_zerlegen(n, "gmail-felix404", 5, EIGENE)["urspruengliche_adresse"] == BLUEBATCH
    ohne = email.message_from_bytes(_roh("neu2@x"))
    assert post_abholen._mail_zerlegen(ohne, "gmail-felix404", 6, EIGENE)["urspruengliche_adresse"] == ""
    code = email.message_from_string(
        f"Message-ID: <c@x>\nSubject: Ihr Sicherheitscode\nX-Forwarded-To: {BLUEBATCH}\n\n123456")
    assert post_abholen._mail_zerlegen(code, "gmail-felix404", 7, EIGENE)["urspruengliche_adresse"] is None


def test_speichern_schreibt_adresse_und_einordnen_offene_reicht_sie_weiter(db, monkeypatch):
    import post_abholen
    k = _konto(db)
    zeile = {"id": k, "besitzer": "felix", "kennung": "gmail-felix404", "adresse": EIGENE}
    n = email.message_from_bytes(_roh("neu@x", X_Forwarded_To=BLUEBATCH))
    mail = post_abholen._mail_zerlegen(n, "gmail-felix404", 5, EIGENE)
    assert post_abholen._speichern(zeile, 5, mail) is True
    assert db._q("select urspruengliche_adresse as a from post_mails where imap_uid = 5")[0]["a"] == BLUEBATCH
    gesehen = []

    def fake(mail, konto, aufruf=None):
        gesehen.append(mail.get("urspruengliche_adresse"))
        return pe.Einordnung("business", "Rechnungen", False, "katalog", "x")
    monkeypatch.setattr(post_abholen.post_einordnung, "einordnen", fake)
    assert post_abholen.einordnen_offene(5) == 1
    assert gesehen == [BLUEBATCH]
