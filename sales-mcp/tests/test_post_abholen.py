"""Dienst sales-post: Abholen (nur lesend) und Einordnen mit niedriger Prioritaet.

DB-Tests nur gegen sales_test. IMAP ist eine Attrappe, die jeden schreibenden
Befehl (store/copy/move/expunge/append) als Testfehler meldet und `select`
nur mit readonly=True annimmt - Stufe 1 veraendert das echte Postfach nie.
Das Modell wird nie gerufen: der Gateway-Aufruf von `einordnen` ist per autouse-Fixture gesperrt.
"""
import os
import re
import shutil
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway  # noqa: E402
import post_abholen  # noqa: E402
import post_einordnung  # noqa: E402
import post_struktur  # noqa: E402
import server  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
TEST_QUELLE = "test_post_abholen"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' - erlaubt ist nur 'sales_test'.")


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_konten cascade")
        conn.execute("delete from sales_test.activities where payload->>'quelle' = %s",
                     (TEST_QUELLE,))
        # Andere Testdateien lassen kundenantwort-Aktivitaeten (< 120 s) und Modell-
        # Einordnungen von heute in sales_test zurueck; beides steuert die Pause und
        # die Tagesgrenze. Nur das Testschema, darum hier ausdruecklich geleert.
        conn.execute("delete from sales_test.activities where type = 'kundenantwort'")
        conn.execute("truncate sales_test.post_mails")


@pytest.fixture(autouse=True)
def saubere_tabellen():
    _aufraeumen()
    yield
    _aufraeumen()


@pytest.fixture(autouse=True)
def kein_modell(monkeypatch):
    """Ein echter Modellaufruf waere ein Testfehler. pytest.fail ist keine
    Exception-Unterklasse und rutscht deshalb durch den breiten Fang."""
    def verboten(*a, **k):
        pytest.fail("Modell darf im Test nicht gerufen werden")
    # `einordnen(..., aufruf=gateway.funktion_aufrufen)` bindet den Standardwert beim
    # Definieren: Das Modulattribut zu patchen reichte nicht, der Default wird ersetzt.
    monkeypatch.setattr(post_einordnung.einordnen, "__defaults__", (verboten,))
    monkeypatch.setattr(gateway, "funktion_aufrufen", verboten)
    monkeypatch.setattr(post_abholen, "_STOPP", post_abholen.threading.Event())


# --- IMAP-Attrappe ---------------------------------------------------------

class Attrappe:
    def __init__(self, mails: dict, uidvalidity: int = 1):
        self.mails = dict(mails)
        self.uidvalidity = uidvalidity
        self.selects = []
        self.geholt = []
        self.verboten = []
        self.ablehnen = set()      # UIDs, deren naechster Abruf mit NO endet

    def select(self, mailbox="INBOX", readonly=False):
        if readonly is not True:
            pytest.fail("select ohne readonly=True - Stufe 1 darf nichts veraendern")
        self.selects.append((mailbox, readonly))
        return "OK", [str(len(self.mails)).encode()]

    def response(self, code):
        if code == "UIDVALIDITY":
            return code, [str(self.uidvalidity).encode()]
        return code, [None]

    def uid(self, befehl, *args):
        befehl = befehl.lower()
        if befehl == "search":
            m = re.fullmatch(r"UID (\d+):\*", args[-1])
            assert m, args
            start = int(m.group(1))
            uids = sorted(u for u in self.mails if u >= start)
            # Echtes IMAP: "n:*" mit n > hoechster UID liefert die hoechste UID.
            if not uids and self.mails:
                uids = [max(self.mails)]
            return "OK", [" ".join(map(str, uids)).encode()]
        if befehl == "fetch":
            uid = int(args[0])
            self.geholt.append(uid)
            if uid in self.ablehnen:
                self.ablehnen.discard(uid)
                return "NO", [b"Server busy"]
            if self.mails.get(uid) is None:
                return "OK", [None]
            return "OK", [(f"1 (UID {uid} RFC822 {{1}}".encode(), self.mails[uid]), b")"]
        self._verboten(f"uid {befehl}")

    def _verboten(self, was):
        self.verboten.append(was)
        pytest.fail(f"schreibender IMAP-Befehl: {was}")

    def store(self, *a, **k):
        self._verboten("store")

    def copy(self, *a, **k):
        self._verboten("copy")

    def move(self, *a, **k):
        self._verboten("move")

    def expunge(self, *a, **k):
        self._verboten("expunge")

    def append(self, *a, **k):
        self._verboten("append")

    def logout(self):
        return "BYE", [b""]


def _mail(message_id="<m1@example.org>", von="Anna Beispiel <anna@example.org>",
          betreff="Angebot", text="Guten Tag, anbei das Angebot.", anhang=None,
          datum="Mon, 02 Nov 2026 10:00:00 +0100") -> bytes:
    m = EmailMessage()
    m["From"] = von
    m["To"] = "felix@example.org"
    m["Subject"] = betreff
    if datum:
        m["Date"] = datum
    if message_id:
        m["Message-ID"] = message_id
    m.set_content(text)
    if anhang:
        m.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename=anhang)
    return m.as_bytes()


def _konto(besitzer="felix", kennung="gmx-test") -> dict:
    with server.pool.connection() as conn:
        conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
            "values (%s, %s, 'gmx', %s, 'ui')", (besitzer, kennung, f"{kennung}@gmx.de"))
    return _zeile(kennung)


def _zeile(kennung) -> dict:
    with server.pool.connection() as conn:
        return conn.execute("select * from post_konten where kennung = %s",
                            (kennung,)).fetchone()


def _mails(where="true", params=()) -> list:
    with server.pool.connection() as conn:
        return conn.execute(f"select * from post_mails where {where} order by imap_uid",
                            params).fetchall()


# --- Abholen ---------------------------------------------------------------

def test_holt_nur_neue_uids():
    _konto()
    kasten = Attrappe({1: _mail("<a@x>"), 2: _mail("<b@x>"), 3: _mail("<c@x>")})
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten) == 3
    zeile = _zeile("gmx-test")
    assert zeile["letzte_uid"] == 3 and zeile["altbestand_fertig"] is True
    assert zeile["uidvalidity"] == 1
    rows = _mails()
    assert [r["imap_uid"] for r in rows] == [1, 2, 3]
    assert {r["status"] for r in rows} == {"neu"}
    assert {r["besitzer"] for r in rows} == {"felix"}
    assert rows[0]["betreff"] == "Angebot" and rows[0]["von"].startswith("Anna")
    assert rows[0]["message_id"] == "a@x"
    assert rows[0]["datum"] is not None and rows[0]["auszug"].startswith("Guten Tag")

    kasten.mails[4] = _mail("<d@x>", anhang="rechnung.pdf")
    kasten.geholt.clear()
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten) == 1
    assert kasten.geholt == [4]
    assert _mails("imap_uid = 4")[0]["anhaenge"] == ["rechnung.pdf"]

    # Nichts Neues: "UID 5:*" liefert auf echtem IMAP die hoechste UID (4) -
    # die darf nicht erneut geholt werden.
    kasten.geholt.clear()
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten) == 0
    assert kasten.geholt == []
    assert len(_mails()) == 4


def test_altbestand_in_stapeln():
    _konto()
    kasten = Attrappe({u: _mail(f"<{u}@x>") for u in range(1, 6)})
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten, stapel=2) == 2
    assert _zeile("gmx-test")["altbestand_fertig"] is False
    assert _zeile("gmx-test")["letzte_uid"] == 2
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten, stapel=2) == 2
    assert _zeile("gmx-test")["altbestand_fertig"] is False
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten, stapel=2) == 1
    assert _zeile("gmx-test")["altbestand_fertig"] is True
    assert [r["imap_uid"] for r in _mails()] == [1, 2, 3, 4, 5]


def test_neue_uidvalidity_holt_neu_ohne_dubletten():
    _konto()
    a, b, c = _mail("<a@x>", betreff="A"), _mail("<b@x>", betreff="B"), _mail("<c@x>", betreff="C")
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: a, 2: b}, uidvalidity=7))
    # Das Postfach wurde neu nummeriert: B ist jetzt 1, A ist 2, C neu als 3.
    neu = Attrappe({1: b, 2: a, 3: c}, uidvalidity=8)
    assert post_abholen.konto_abholen(_zeile("gmx-test"), neu) == 1
    zeile = _zeile("gmx-test")
    assert zeile["uidvalidity"] == 8 and zeile["letzte_uid"] == 3
    assert neu.geholt == [1, 2, 3]
    rows = {r["betreff"]: r["imap_uid"] for r in _mails()}
    assert rows == {"B": 1, "A": 2, "C": 3}


def test_mail_ohne_message_id_bekommt_ersatz():
    _konto()
    kaputt = (b"From: x@example.org\r\nSubject: kaputt\r\n"
              b"Content-Type: text/plain; charset=x-gibt-es-nicht\r\n\r\n"
              b"Inhalt mit \xff\xfe Bytes und \x00 Nullzeichen\r\n")
    riesig = _mail(None, betreff="gross", text="<p>" + "x" * 50000 + "</p>")
    assert post_abholen.konto_abholen(_zeile("gmx-test"),
                                      Attrappe({7: kaputt, 8: riesig})) == 2
    rows = _mails()
    assert rows[0]["message_id"] == "gmx-test:7@sales-post"
    assert rows[1]["message_id"] == "gmx-test:8@sales-post"
    assert "Inhalt mit" in rows[0]["text"] and "\x00" not in rows[0]["text"]
    from postfach import AUSZUG_MAX, TEXT_MAX
    assert len(rows[1]["text"]) <= TEXT_MAX
    assert len(rows[1]["auszug"]) <= AUSZUG_MAX
    assert rows[0]["datum"] is None


def test_ersatz_message_id_ist_markiert():
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"),
                               Attrappe({1: _mail(None), 2: _mail("<echt@x>")}))
    rows = _mails()
    assert [r["message_id_ersatz"] for r in rows] == [True, False]


def test_ohne_message_id_nach_uidvalidity_wechsel_keine_dubletten():
    """M3: der Platzhalter enthaelt die alte UID - wiedererkannt wird ueber
    Konto + Absender + Betreff + Datum; verschiedene Mails bleiben getrennt."""
    _konto()
    a = _mail(None, betreff="Ohne ID A")
    b = _mail(None, betreff="Ohne ID B")
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: a, 2: b}, uidvalidity=7))
    neu = Attrappe({5: b, 6: a, 7: _mail(None, betreff="Ohne ID C")}, uidvalidity=8)
    assert post_abholen.konto_abholen(_zeile("gmx-test"), neu) == 1
    rows = {r["betreff"]: r for r in _mails()}
    assert set(rows) == {"Ohne ID A", "Ohne ID B", "Ohne ID C"}
    assert (rows["Ohne ID A"]["imap_uid"], rows["Ohne ID B"]["imap_uid"]) == (6, 5)
    # Der Platzhalter zieht mit der UID mit, die Markierung bleibt.
    assert rows["Ohne ID A"]["message_id"] == "gmx-test:6@sales-post"
    assert all(r["message_id_ersatz"] for r in rows.values())


def test_unlesbare_mails_werden_nie_zusammengelegt(monkeypatch):
    _konto()
    monkeypatch.setattr(post_abholen, "_mail_zerlegen",
                        lambda *a: (_ for _ in ()).throw(ValueError("kaputt")))
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail(), 2: _mail()},
                                                             uidvalidity=1))
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail(), 2: _mail()},
                                                             uidvalidity=2))
    assert len(_mails()) == 4 and all(r["message_id_ersatz"] for r in _mails())


def test_kalenderteil_wird_beim_abholen_gespeichert():
    """I1: ob eine Mail einen text/calendar-Teil traegt, steht in der Zeile -
    postfach_lesen zeigt es, postfach_mail_lesen wertet die Antwort aus."""
    _konto()
    m = EmailMessage()
    m["From"] = "ivan@example.org"
    m["Subject"] = "Angenommen"
    m["Message-ID"] = "<kal@x>"
    m.set_content("Siehe Anhang")
    m.add_attachment(b"BEGIN:VCALENDAR\r\nMETHOD:REPLY\r\nEND:VCALENDAR\r\n",
                     maintype="text", subtype="calendar", filename="r.ics")
    post_abholen.konto_abholen(_zeile("gmx-test"),
                               Attrappe({1: m.as_bytes(), 2: _mail("<ohne@x>")}))
    assert [r["kalenderteil"] for r in _mails()] == [True, False]


def test_message_id_fremder_besitzer_wird_nicht_zusammengelegt():
    _konto("felix", "gmx-felix")
    _konto("felix", "gmail-felix")
    _konto("anna", "gmx-anna")
    m = _mail("<gleich@x>")
    for kennung in ("gmx-felix", "gmail-felix", "gmx-anna"):
        post_abholen.konto_abholen(_zeile(kennung), Attrappe({1: m}))
    rows = _mails("message_id = 'gleich@x'")
    # Felix: eine Mail (zweites Konto desselben Besitzers legt keine an);
    # Anna: eigener Eintrag - eine Message-ID kann keine fremde Mail umdeuten.
    assert sorted(r["besitzer"] for r in rows) == ["anna", "felix"]
    # Gleiche Message-ID, anderer Betreff -> eigenstaendige Mail.
    post_abholen.konto_abholen(_zeile("gmail-felix"),
                               Attrappe({1: m, 2: _mail("<gleich@x>", betreff="Anders")}))
    assert len(_mails("message_id = 'gleich@x' and besitzer = 'felix'")) == 2


def test_select_ist_readonly():
    _konto()
    kasten = Attrappe({1: _mail()})
    post_abholen.konto_abholen(_zeile("gmx-test"), kasten)
    assert kasten.selects == [("INBOX", True)]
    assert kasten.verboten == []
    quelltext = (WURZEL / "sales-mcp" / "post_abholen.py").read_text(encoding="utf-8")
    code = "\n".join(z for z in quelltext.splitlines() if not z.lstrip().startswith("#"))
    for befehl in ("store", "copy", "move", "expunge", "append"):
        assert not re.search(rf"kasten\.{befehl}\(|uid\(\s*[\"']{befehl}[\"']", code, re.I), befehl
    assert "readonly=True" in code and "readonly=False" not in code


def test_konto_ohne_attrappe_wird_verbunden_und_abgemeldet(monkeypatch):
    _konto()
    kasten = Attrappe({1: _mail()})
    abgemeldet = []
    kasten.logout = lambda: abgemeldet.append(True)
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda zeile: kasten)
    assert post_abholen.konto_abholen(_zeile("gmx-test")) == 1
    assert abgemeldet == [True]


# --- Einordnen -------------------------------------------------------------

def _einordnung(sensibel=False, quelle="modell"):
    return post_einordnung.Einordnung("business", "Kunden & Anfragen", sensibel, quelle,
                                      "passt")


def test_sensibel_speichert_keinen_text(monkeypatch):
    _konto()
    code = _mail("<code@x>", von="security@bank.example", betreff="Ihr Sicherheitscode",
                 text="Code 482913", anhang="code.pdf")
    normal = _mail("<n@x>", betreff="Kontoauszug", text="Saldo 1.234,56 EUR", anhang="konto.pdf")
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: code, 2: normal}))
    # Sicherheitscode: festes Muster greift schon beim Speichern.
    r1 = _mails("imap_uid = 1")[0]
    assert r1["text"] is None and r1["auszug"] is None
    assert r1["an"] is None and r1["anhaenge"] == []
    gesehen = []

    def einordnen(mail, konto):
        gesehen.append(mail)
        if mail["betreff"] == "Kontoauszug":
            return _einordnung(sensibel=True)
        return post_einordnung.nach_regel(mail, konto)
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    assert post_abholen.einordnen_offene(10) == 2
    for r in _mails():
        assert r["sensibel"] is True and r["status"] == "eingeordnet"
        assert r["text"] is None and r["auszug"] is None
        assert r["an"] is None and r["anhaenge"] == []
    with server.pool.connection() as conn:
        assert conn.execute(
            "select count(*) as n from post_mails where suchtext @@ "
            "plainto_tsquery('german', 'Saldo')").fetchone()["n"] == 0


def test_einordnung_wird_gespeichert(monkeypatch):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))
    gesehen = []
    monkeypatch.setattr(post_einordnung, "einordnen",
                        lambda mail, konto: gesehen.append(mail) or _einordnung())
    assert post_abholen.einordnen_offene(5) == 1
    r = _mails()[0]
    assert (r["bereich"], r["fach"], r["sensibel"], r["einordnung_quelle"], r["status"]) == \
        ("business", "Kunden & Anfragen", False, "modell", "eingeordnet")
    assert r["eingeordnet_am"] is not None and r["text"]
    assert set(gesehen[0]) >= {"id", "von", "betreff", "datum", "text"}
    assert gesehen[0]["id"] == str(r["id"])


def test_transient_laesst_mail_neu(monkeypatch, caplog):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({
        1: _mail("<a@x>", betreff="Geheimer Betreff Eins"),
        2: _mail("<b@x>", betreff="Geheimer Betreff Zwei")}))
    for _ in range(post_abholen.VERSUCHE_MAX + 1):
        aufrufe = []

        def einordnen(mail, konto):
            aufrufe.append(mail["id"])
            raise gateway.GatewayTransient("Gateway nicht erreichbar")
        monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
        assert post_abholen.einordnen_offene(10) == 0
        assert len(aufrufe) == 1                     # Runde endet beim ersten
        # Transient zaehlt keinen Versuch: das Gateway, nicht die Mail ist schuld.
        assert {(r["status"], r["versuche"]) for r in _mails()} == {("neu", 0)}

    # Endgueltiger Fehler: diese Mail -> fehler/Zum Nachsehen, die naechste laeuft weiter.
    reihe = iter([gateway.GatewayFehler("Gateway HTTP 400: Geheimer Betreff Eins"),
                  _einordnung()])

    def gemischt(mail, konto):
        x = next(reihe)
        if isinstance(x, Exception):
            raise x
        return x
    monkeypatch.setattr(post_einordnung, "einordnen", gemischt)
    assert post_abholen.einordnen_offene(10) == 2
    r1, r2 = _mails()
    assert (r1["status"], r1["fach"]) == ("fehler", post_struktur.UNKLAR)
    assert "Geheim" not in (r1["fehler"] or "") and r1["fehler"]
    assert r2["status"] == "eingeordnet"
    assert "Geheim" not in caplog.text and "anna@example.org" not in caplog.text


def test_kaputte_mail_blockiert_die_einordnung_nicht(monkeypatch, caplog):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({
        1: _mail("<a@x>", betreff="Geheimer Betreff Eins"),
        2: _mail("<b@x>", betreff="Geheimer Betreff Zwei")}))
    aufrufe = []

    def einordnen(mail, konto):
        aufrufe.append(mail["betreff"])
        if mail["betreff"].endswith("Eins"):
            raise ValueError("Geheimer Betreff Eins kaputt")
        return _einordnung()
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    # Versuch 1 und 2: Runde endet bei der kaputten Mail, sie bleibt neu.
    for versuch in (1, 2):
        assert post_abholen.einordnen_offene(10) == 0
        r1, r2 = _mails()
        assert (r1["status"], r1["versuche"], r2["status"]) == ("neu", versuch, "neu")
    # Versuch 3: aufgegeben -> fehler/privat/Zum Nachsehen, und die naechste Mail laeuft.
    assert post_abholen.einordnen_offene(10) == 2
    r1, r2 = _mails()
    assert (r1["status"], r1["bereich"], r1["fach"], r1["versuche"]) == \
        ("fehler", "privat", post_struktur.UNKLAR, 3)
    assert r1["fehler"] and "Geheim" not in r1["fehler"]
    assert r2["status"] == "eingeordnet"
    assert len(aufrufe) == 4
    assert "Geheim" not in caplog.text and "ValueError" in caplog.text


def test_abgelehnter_abruf_wird_naechste_runde_wiederholt(caplog):
    _konto()
    kasten = Attrappe({1: _mail("<a@x>"), 2: _mail("<b@x>"), 3: _mail("<c@x>")})
    kasten.ablehnen = {2}
    with pytest.raises(Exception):
        post_abholen.konto_abholen(_zeile("gmx-test"), kasten)
    # Mail 1 ist da, Mail 2 nicht uebersprungen: letzte_uid steht vor ihr.
    assert _zeile("gmx-test")["letzte_uid"] == 1
    assert [r["imap_uid"] for r in _mails()] == [1]
    kasten.geholt.clear()
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten) == 2
    assert kasten.geholt == [2, 3]
    assert [r["imap_uid"] for r in _mails()] == [1, 2, 3]

    # OK ohne Daten = entfernt: weiter, mit Kennung und UID im Protokoll.
    kasten.mails[4] = None
    kasten.mails[5] = _mail("<e@x>")
    caplog.set_level("INFO")
    assert post_abholen.konto_abholen(_zeile("gmx-test"), kasten) == 1
    assert _zeile("gmx-test")["letzte_uid"] == 5
    assert "gmx-test" in caplog.text and "UID 4" in caplog.text


def test_gatewayfehler_zaehlt_zur_tagesgrenze(monkeypatch):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))

    def einordnen(mail, konto):
        raise gateway.GatewayFehler("Gateway HTTP 400")
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    assert post_abholen.einordnen_offene(5) == 1
    assert _mails()[0]["status"] == "fehler"
    assert post_abholen.modellaufrufe_heute() == 1


# --- Runde: Vorrang und Tagesgrenze ------------------------------------------

def _kundenantwort(vor_sekunden: int):
    with server.pool.connection() as conn:
        conn.execute(
            "insert into activities (type, payload, actor, created_at) values "
            "('kundenantwort', %s, 'human', now() - make_interval(secs => %s))",
            (server._json({"quelle": TEST_QUELLE}), vor_sekunden))


def _runde_vorbereiten(monkeypatch, n_mails=2):
    _konto()
    kasten = Attrappe({u: _mail(f"<{u}@x>") for u in range(1, n_mails + 1)})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda zeile: kasten)
    aufrufe = []
    monkeypatch.setattr(post_einordnung, "einordnen",
                        lambda mail, konto: aufrufe.append(mail["id"]) or _einordnung())
    return aufrufe


def test_pause_bei_kundenantwort(monkeypatch):
    aufrufe = _runde_vorbereiten(monkeypatch)
    _kundenantwort(vor_sekunden=10)
    assert post_abholen.kunde_aktiv() is True
    bilanz = post_abholen.eine_runde()
    assert bilanz["abgeholt"] == 2            # Abholen laeuft weiter, nur das Modell pausiert
    assert aufrufe == [] and bilanz.get("pause")
    assert {r["status"] for r in _mails()} == {"neu"}

    _aufraeumen()
    aufrufe = _runde_vorbereiten(monkeypatch)
    _kundenantwort(vor_sekunden=300)          # aelter als 120 s -> kein Vorrang mehr
    assert post_abholen.kunde_aktiv() is False
    assert post_abholen.eine_runde()["eingeordnet"] == 2
    assert len(aufrufe) == 2


def _alt_mail(konto_id, uid, quelle="modell", aufrufe=0, vorschau=None, heute=True):
    """Bereits eingeordnete Zeile fuer die Tageszaehlung; `heute=False` = gestern."""
    tag = "now()" if heute else "now() - interval '1 day'"
    vorschau_json = None if vorschau is None else server._json(vorschau)
    with server.pool.connection() as conn:
        conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, status, "
            "einordnung_quelle, eingeordnet_am, modellaufrufe, vorschau, vorschau_am, vorschau_aufrufe) "
            f"values (%s, %s, %s, 'felix', 'eingeordnet', %s, {tag}, %s, %s::jsonb, "
            f"case when %s::jsonb is null then null else {tag} end, %s)",
            (konto_id, uid, f"alt{uid}@x", quelle, aufrufe, vorschau_json, vorschau_json,
             int((vorschau or {}).get("aufrufe", 0))))


def test_tagesgrenze(monkeypatch):
    aufrufe = _runde_vorbereiten(monkeypatch, n_mails=4)
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 5)
    konto_id = _zeile("gmx-test")["id"]
    _alt_mail(konto_id, 101, aufrufe=2)
    _alt_mail(konto_id, 102, aufrufe=1)
    _alt_mail(konto_id, 103, quelle="regel", aufrufe=0)      # feste Regel: kein Aufruf
    _alt_mail(konto_id, 104, aufrufe=2, heute=False)         # gestern zaehlt nicht
    assert post_abholen.modellaufrufe_heute() == 3
    # rest = 2 -> hoechstens eine Mail (jede kann 2 Aufrufe kosten).
    bilanz = post_abholen.eine_runde()
    assert len(aufrufe) == 1 and bilanz["eingeordnet"] == 1
    # Die Attrappe meldet aufrufe=0, es bleibt bei rest = 2; mit echtem Zaehler ist Schluss.
    _alt_mail(konto_id, 105, aufrufe=2)
    assert post_abholen.eine_runde().get("tagesgrenze") is True
    assert len(aufrufe) == 1

    # Die Grenze von einordnen_offene selbst: hoechstens `grenze` Mails.
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 500)
    aufrufe.clear()
    assert post_abholen.einordnen_offene(2) == 2 and len(aufrufe) == 2


def test_tagesgrenze_zaehlt_aufrufe_und_vorschau():
    konto_id = _konto()["id"]
    _alt_mail(konto_id, 201, aufrufe=2)
    _alt_mail(konto_id, 202, quelle="mensch", aufrufe=0, vorschau={"aufrufe": 2})
    assert post_abholen.modellaufrufe_heute() == 4


def test_restbudget_unter_zwei_aufrufen_stoppt_die_runde(monkeypatch):
    aufrufe = _runde_vorbereiten(monkeypatch, n_mails=2)
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 3)
    _alt_mail(_zeile("gmx-test")["id"], 301, aufrufe=2)       # rest = 1 < 2
    bilanz = post_abholen.eine_runde()
    assert bilanz.get("tagesgrenze") is True and aufrufe == []


def test_speichert_unterfach_vorschlaege_aufrufe_version(monkeypatch):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))
    vorschlaege = {"sortierer": {"bereich": "business", "fach": "Rechnungen", "unterfach": None},
                   "pruefer": {"bereich": "privat", "fach": "Werbung", "unterfach": None}}
    monkeypatch.setattr(
        post_einordnung, "einordnen",
        lambda mail, konto: post_einordnung.Einordnung(
            "privat", post_struktur.UNKLAR, False, "modell", "pruefer:uneins", None,
            aufrufe=2, vorschlaege=vorschlaege))
    assert post_abholen.einordnen_offene(5) == 1
    r = _mails()[0]
    assert (r["unterfach"], r["modellaufrufe"], r["einordnung_version"]) == (None, 2, 3)
    assert r["vorschlaege"] == vorschlaege and r["status"] == "eingeordnet"

    # Mit Unterfach, ohne Vorschlaege.
    _aufraeumen()
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<b@x>")}))
    monkeypatch.setattr(
        post_einordnung, "einordnen",
        lambda mail, konto: post_einordnung.Einordnung(
            "privat", "Konten & Sicherheit", True, "katalog", "katalog:modell-sensibel",
            "Instagram", aufrufe=1))
    assert post_abholen.einordnen_offene(5) == 1
    r = _mails()[0]
    assert (r["unterfach"], r["modellaufrufe"], r["einordnung_version"], r["vorschlaege"]) == \
        ("Instagram", 1, 3, None)
    assert r["text"] is None                                  # sensibel: Text weg
    assert (r["aufmerksamkeit"], r["werbung_sicher"]) == (False, False)

    # Aufmerksamkeit und werbung_sicher werden mitgeschrieben.
    _aufraeumen()
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<c@x>")}))
    monkeypatch.setattr(
        post_einordnung, "einordnen",
        lambda mail, konto: post_einordnung.Einordnung(
            "privat", "Werbung", False, "pruefer", "x", None, aufrufe=2,
            aufmerksamkeit=True, werbung_sicher=True))
    assert post_abholen.einordnen_offene(5) == 1
    r = _mails()[0]
    assert (r["aufmerksamkeit"], r["werbung_sicher"], r["einordnung_version"]) == (True, True, 3)


def test_konto_kontext_wird_uebergeben(monkeypatch):
    _konto()
    with server.pool.connection() as conn:
        conn.execute("update post_konten set standard_bereich = 'privat' "
                     "where kennung = 'gmx-test'")
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))
    gesehen = []

    def einordnen(mail, konto):
        gesehen.append(konto)
        return _einordnung()
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    assert post_abholen.einordnen_offene(5) == 1
    assert gesehen[0]["standard_bereich"] == "privat" and gesehen[0]["kennung"] == "gmx-test"


def test_pruefer_fehler_bleibt_neu_dann_nach_drei_zum_nachsehen(monkeypatch, caplog):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({
        1: _mail("<a@x>", betreff="Geheimer Betreff Eins"),
        2: _mail("<b@x>", betreff="Geheimer Betreff Zwei")}))

    def einordnen(mail, konto):
        if mail["betreff"].endswith("Eins"):
            raise post_einordnung.PrueferFehlgeschlagen(post_einordnung.Einordnung(
                "business", "Rechnungen", False, "modell", "Geheime Begruendung", "Eingang",
                aufrufe=1))
        return _einordnung()
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    # Versuch 1: Mail 1 bleibt neu, die Runde macht mit Mail 2 weiter.
    assert post_abholen.einordnen_offene(10) == 1
    r1, r2 = _mails()
    assert (r1["status"], r1["versuche"], r2["status"]) == ("neu", 1, "eingeordnet")
    assert r1["fehl_aufrufe"] == 2 and r1["modellaufrufe"] == 0   # Fehlversuch-Kosten: eigene Spalte
    assert post_abholen.einordnen_offene(10) == 0
    assert _mails()[0]["versuche"] == 2
    # Versuch 3: Vorschlag des Sortierers bleibt als Vorschlag, die Mail liegt zum Nachsehen.
    assert post_abholen.einordnen_offene(10) == 1
    r1 = _mails()[0]
    assert (r1["status"], r1["bereich"], r1["fach"], r1["einordnung_quelle"]) == \
        ("eingeordnet", "privat", post_struktur.UNKLAR, "modell")
    assert r1["vorschlaege"] == {"sortierer": {
        "bereich": "business", "fach": "Rechnungen", "unterfach": "Eingang",
        "begruendung": "Geheime Begruendung"}}
    # Kosten der drei Fehlversuche stehen auf fehl_aufrufe, nichts doppelt auf modellaufrufe.
    assert (r1["einordnung_version"], r1["fehl_aufrufe"], r1["modellaufrufe"], r1["sensibel"]) == (3, 6, 0, False)
    assert "Geheim" not in caplog.text


def test_pruefer_fehler_sensibel_speichert_keine_begruendung(monkeypatch):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))

    def einordnen(mail, konto):
        raise post_einordnung.PrueferFehlgeschlagen(post_einordnung.Einordnung(
            "privat", "Konten & Sicherheit", True, "modell", "modell:sensibel", "Sonstige",
            aufrufe=1))
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    for _ in range(post_abholen.VERSUCHE_MAX):
        post_abholen.einordnen_offene(10)
    r = _mails()[0]
    assert r["status"] == "eingeordnet" and r["sensibel"] is True and r["text"] is None
    assert r["vorschlaege"] == {"sortierer": {
        "bereich": "privat", "fach": "Konten & Sicherheit", "unterfach": "Sonstige"}}


def test_fehler_in_einem_konto_haelt_die_anderen_nicht_auf(monkeypatch, caplog):
    _konto("felix", "gmx-kaputt")
    _konto("felix", "gmx-gut")

    def verbinden(zeile):
        if zeile["kennung"] == "gmx-kaputt":
            raise OSError("Passwort-Geheim-4711 abgelehnt")
        return Attrappe({1: _mail()})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", verbinden)
    monkeypatch.setattr(post_einordnung, "einordnen", lambda mail, konto: _einordnung())
    bilanz = post_abholen.eine_runde()
    assert bilanz["abgeholt"] == 1 and bilanz["konten_fehler"] == 1
    assert "Passwort-Geheim-4711" not in caplog.text and "OSError" in caplog.text


def test_ohne_besitzer_startet_der_dienst_nicht(monkeypatch):
    aufgerufen = []
    monkeypatch.setattr(post_abholen, "POST_BESITZER", "")
    monkeypatch.setattr(post_abholen, "_logging_einrichten", lambda: None)
    monkeypatch.setattr(post_abholen.signal, "signal", lambda *a: None)
    zeitgrenzen = []
    monkeypatch.setattr(post_abholen.socket, "setdefaulttimeout", zeitgrenzen.append)
    monkeypatch.setattr(post_abholen.post_konten, "env_konten_uebernehmen",
                        lambda b: aufgerufen.append(("env", b)) or 0)
    monkeypatch.setattr(post_abholen, "eine_runde", lambda: aufgerufen.append("runde") or {})
    assert post_abholen.main() != 0
    assert aufgerufen == []

    monkeypatch.setattr(post_abholen, "POST_BESITZER", "felix")
    monkeypatch.setattr(post_abholen, "POST_ONCE", True)
    assert post_abholen.main() == 0
    assert aufgerufen == [("env", "felix"), "runde"]
    # IMAP verbindet ohne eigene Zeitgrenze - main setzt die Vorgabe fuer Sockets.
    assert zeitgrenzen and set(zeitgrenzen) == {post_abholen.IMAP_TIMEOUT_S}


# --- Compose / Deploy ------------------------------------------------------

def _compose_abschnitt(dienst):
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    m = re.search(rf"^  {re.escape(dienst)}:\n(.*?)(?=^  \S|^\S|\Z)", text, re.M | re.S)
    assert m, dienst
    return "\n".join(z for z in m.group(1).splitlines() if not z.lstrip().startswith("#"))


def _dienste():
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    dienste_teil = text[text.index("\nservices:"):]
    dienste_teil = re.split(r"^\S", dienste_teil[1:], flags=re.M)[1]   # bis zum naechsten Top-Level
    return re.findall(r"^  ([a-z][\w-]*):\s*$", dienste_teil, re.M)


def _code(text):
    return "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))


def test_compose_sales_post_ladenfest():
    a = _compose_abschnitt("sales-post")
    assert "container_name: ${LADEN_PRAEFIX:-sales}-post" in a
    assert "image: sales-claw-sales-mcp:local" in a
    assert "command: python post_abholen.py" in a
    assert "restart: unless-stopped" in a
    assert "<<: *sales_mcp_umgebung" in a
    assert "OPENCLAW_URL: http://${LADEN_PRAEFIX:-sales}-claw:18894" in a
    assert "OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:-}" in a
    assert "POST_SCHLUESSEL_PRIVAT: ${POST_SCHLUESSEL_PRIVAT:-}" in a
    assert "POST_BESITZER: ${POST_BESITZER:-}" in a
    assert re.search(r"POST_TAGESGRENZE: \$\{POST_TAGESGRENZE:-500\}", a)
    assert "POST_INTERVAL_S: 120" in a
    assert "env_file" not in a
    assert "ports:" not in a                  # kein Host-Port

    update = (WURZEL / "deploy" / "update.sh").read_text(encoding="utf-8")
    kern = re.search(r'^KERN_ALLE="([^"]*)"', update, re.M).group(1).split()
    optional = re.search(r'^KERN_OPTIONAL="([^"]*)"', update, re.M).group(1).split()
    assert "sales-post" in optional and "sales-post" not in kern
    smoke = (WURZEL / "deploy" / "smoke.sh").read_text(encoding="utf-8")
    assert '"sales-post"' in re.search(r"erwartete_container = \{(.*?)\}", smoke, re.S).group(1)
    # Muss nicht laufen: der Betreiber startet ihn erst, wenn POST_BESITZER steht.
    schleife = re.search(r"^for c in (sales-mcp [^;]*);", smoke, re.M).group(1).split()
    assert "sales-post" not in schleife


def test_schluessel_nur_bei_sales_post():
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    anker = text[text.index("x-sales-mcp-umgebung"):text.index("\nservices:")]
    assert "POST_SCHLUESSEL_PRIVAT" not in anker
    assert "OPENCLAW_GATEWAY_TOKEN" not in anker
    dienste = _dienste()
    assert "sales-post" in dienste and "sales-ui" in dienste and len(dienste) >= 10
    for dienst in dienste:
        abschnitt = _compose_abschnitt(dienst)
        if dienst != "sales-post":
            assert "POST_SCHLUESSEL_PRIVAT" not in abschnitt, dienst
        if dienst not in ("sales-auto", "sales-post"):
            assert "OPENCLAW_GATEWAY_TOKEN" not in abschnitt, dienst
    # Ausserhalb von sales-post steht der private Schluessel nirgends im Code der Datei.
    im_dienst = _compose_abschnitt("sales-post").count("POST_SCHLUESSEL_PRIVAT")
    assert im_dienst > 0 and _code(text).count("POST_SCHLUESSEL_PRIVAT") == im_dienst
    for datei in WURZEL.glob("docker-compose*.yml"):
        if datei.name != "docker-compose.yml":
            assert "POST_SCHLUESSEL_PRIVAT" not in datei.read_text(encoding="utf-8"), datei


def test_post_kontext_nur_bei_sales_post():
    """I3: post_einordnung liest POST_KONTEXT aus der Umgebung - Compose muss es dem
    Dienst sales-post durchreichen (leer erlaubt), sonst kommt es nie an."""
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    anker = text[text.index("x-sales-mcp-umgebung"):text.index("\nservices:")]
    assert "POST_KONTEXT" not in anker
    assert "POST_KONTEXT: ${POST_KONTEXT:-}" in _compose_abschnitt("sales-post")
    for dienst in _dienste():
        if dienst != "sales-post":
            assert "POST_KONTEXT" not in _compose_abschnitt(dienst), dienst
    # Der veraltete Kommentar (v2: Regeltreffer kosten einen Sensibel-Aufruf) ist weg.
    assert "Regel-Treffer zaehlen nicht" not in text
    beispiel = (WURZEL / "deploy" / "laeden" / "beispiel.env").read_text(encoding="utf-8")
    assert re.search(r"^POST_KONTEXT=$", beispiel, re.M)


def test_oeffentlicher_schluessel_nur_bei_sales_ui():
    """Ruling R5: die Oberflaeche versiegelt neue Zugaenge und braucht dafuer
    nur den oeffentlichen Schluessel; den privaten bekommt sie nie."""
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    anker = text[text.index("x-sales-mcp-umgebung"):text.index("\nservices:")]
    assert "POST_SCHLUESSEL_OEFFENTLICH" not in anker
    ui_teil = _compose_abschnitt("sales-ui")
    assert ("- POST_SCHLUESSEL_OEFFENTLICH=${POST_SCHLUESSEL_OEFFENTLICH:-}"
            in ui_teil)
    assert "POST_SCHLUESSEL_PRIVAT" not in ui_teil
    assert "env_file" not in ui_teil
    for dienst in _dienste():
        if dienst != "sales-ui":
            assert "POST_SCHLUESSEL_OEFFENTLICH" not in _compose_abschnitt(dienst), dienst
    assert _code(text).count("POST_SCHLUESSEL_OEFFENTLICH") == ui_teil.count(
        "POST_SCHLUESSEL_OEFFENTLICH")


def _update_logik() -> str:
    """Die Teile von deploy/update.sh, die entscheiden, was laeuft und ob die
    Abnahme (mit automatischem Rueckbau) laeuft - woertlich ausgeschnitten."""
    update = (WURZEL / "deploy" / "update.sh").read_text(encoding="utf-8")
    teile = [re.search(rf'^{n}="[^"]*"$', update, re.M).group(0)
             for n in ("KERN_ALLE", "KERN_OPTIONAL")]
    for f in ("ohne_optionale", "containername", "laufende_kerndienste"):
        teile.append(re.search(rf"^{f}\(\) \{{.*?^\}}$", update, re.M | re.S).group(0))
    bedingung = re.search(r'^if (\[ .*"\$KERN_ALLE" \]); then$', update, re.M)
    assert bedingung, "Abnahme-Bedingung nicht gefunden"
    teile.append('KERN_BASIS="$(laufende_kerndienste sales)"\necho "LAEUFT:$KERN_BASIS"\n'
                 f"if {bedingung.group(1)}; then echo ABNAHME; else echo UEBERSPRUNGEN; fi")
    return "\n".join(teile)


@pytest.mark.skipif(shutil.which("bash") is None, reason="braucht bash")
@pytest.mark.parametrize("gestoppt, erwartet, post_laeuft", [
    ("sales-post", "ABNAHME", False),        # sales-post aus: volle Abnahme + Rueckbau
    ("", "ABNAHME", True),                   # alles an: ebenso, sales-post wird mitgebaut
    ("sales-post sales-mail", "UEBERSPRUNGEN", False),   # echter Teilstack
])
def test_update_abnahme_auch_ohne_sales_post(gestoppt, erwartet, post_laeuft):
    attrappe = ('docker() { case " %s " in *" $4 "*) echo exited ;; *) echo running ;; esac; }\n'
                % gestoppt)
    ergebnis = subprocess.run(["bash", "-c", attrappe + _update_logik()],
                              capture_output=True, text=True, timeout=30)
    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ergebnis.stdout.strip().endswith(erwartet), ergebnis.stdout
    laeuft = ergebnis.stdout.split("LAEUFT:")[1].splitlines()[0].split()
    assert ("sales-post" in laeuft) is post_laeuft


def test_fehlversuche_einer_neuen_mail_zaehlen_zur_tagesgrenze(monkeypatch):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))

    def einordnen(mail, konto):
        raise post_einordnung.PrueferFehlgeschlagen(post_einordnung.Einordnung(
            "business", "Rechnungen", False, "modell", "x", None, aufrufe=1))
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    assert post_abholen.modellaufrufe_heute() == 0
    post_abholen.einordnen_offene(10)
    r = _mails()[0]
    assert r["status"] == "neu" and r["eingeordnet_am"] is None and r["fehl_am"] is not None
    assert post_abholen.modellaufrufe_heute() == 2          # Sortierer + Pruefer, obwohl noch neu
    # Ein Fehlversuch von gestern zaehlt heute nicht.
    with server.pool.connection() as conn:
        conn.execute("update post_mails set fehl_am = now() - interval '1 day'")
    assert post_abholen.modellaufrufe_heute() == 0


def test_pruefer_voruebergehend_bucht_sortierer_und_pausiert(monkeypatch):
    """I1: fehlt post-pruefer im Gateway (oder 429/5xx), hat der Sortierer schon
    gekostet. Ohne Buchung liefe dieselbe Mail alle 120 s ungezaehlt erneut."""
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({
        1: _mail("<a@x>"), 2: _mail("<b@x>")}))
    aufrufe = []

    def einordnen(mail, konto):
        aufrufe.append(mail["id"])
        raise post_einordnung.PrueferVoruebergehend(1)
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    for runde in (1, 2):
        assert post_abholen.einordnen_offene(10) == 0
        assert len(aufrufe) == runde                  # Pause: die Runde endet bei der ersten Mail
        r1, r2 = _mails()
        # Kein Versuch gezaehlt (der Pruefer, nicht die Mail ist schuld), aber die Kosten.
        assert (r1["status"], r1["versuche"], r1["fehl_aufrufe"], r1["modellaufrufe"]) == ("neu", 0, runde, 0)
        assert r1["fehl_am"] is not None and r1["eingeordnet_am"] is None
        assert (r2["status"], r2["fehl_aufrufe"]) == ("neu", 0)
        assert post_abholen.modellaufrufe_heute() == runde      # die Tagesgrenze waechst


def test_zum_nachsehen_wird_immer_privat_gespeichert(monkeypatch):
    """I2c: was auch immer `einordnen` liefert - Zum Nachsehen liegt privat, und ein
    ungueltiges Fach wird privat/Zum Nachsehen (nie unter business)."""
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({
        1: _mail("<a@x>"), 2: _mail("<b@x>")}))
    reihe = iter([
        post_einordnung.Einordnung("business", post_struktur.UNKLAR, False, "modell", "x"),
        post_einordnung.Einordnung("business", "Erfunden", False, "modell", "x", "Irgendwas")])
    monkeypatch.setattr(post_einordnung, "einordnen", lambda mail, konto: next(reihe))
    assert post_abholen.einordnen_offene(10) == 2
    for r in _mails():
        assert (r["bereich"], r["fach"], r["unterfach"]) == ("privat", post_struktur.UNKLAR, None)


def test_pruefer_fehler_dann_gatewayfehler_summiert_die_aufrufe(monkeypatch):
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))
    reihe = iter([post_einordnung.PrueferFehlgeschlagen(post_einordnung.Einordnung(
        "business", "Rechnungen", False, "modell", "x", None, aufrufe=1)),
        gateway.GatewayFehler("Gateway HTTP 400")])

    def einordnen(mail, konto):
        raise next(reihe)
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    post_abholen.einordnen_offene(10)       # Pruefer aus: 2 Aufrufe, bleibt neu
    post_abholen.einordnen_offene(10)       # Sortierer endgueltig: +1
    r = _mails()[0]
    assert r["status"] == "fehler" and (r["fehl_aufrufe"], r["modellaufrufe"]) == (2, 1)
    assert post_abholen.modellaufrufe_heute() == 3


def test_pruefer_ausfall_ueber_mitternacht_zaehlt_nicht_doppelt(monkeypatch):
    """Jeder Modellaufruf zaehlt genau einmal, an dem Tag, an dem er anfiel: Die
    Fehlversuche von gestern duerfen heute weder beim neuen Fehlversuch noch bei der
    endgueltigen Einordnung erneut mitzaehlen."""
    _konto()
    post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<a@x>")}))
    with server.pool.connection() as conn:       # gestern: 3 Fehlversuch-Aufrufe
        conn.execute("update post_mails set fehl_aufrufe = 3, "
                     "fehl_am = now() - interval '1 day'")
    assert post_abholen.modellaufrufe_heute() == 0
    reihe = iter([post_einordnung.PrueferVoruebergehend(1), post_einordnung.Einordnung(
        "business", "Kunden & Anfragen", False, "modell", "passt", None, aufrufe=2)])

    def einordnen(mail, konto):
        e = next(reihe)
        if isinstance(e, Exception):
            raise e
        return e
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    post_abholen.einordnen_offene(10)            # heute: 1 weiterer Fehlversuch
    assert post_abholen.modellaufrufe_heute() == 1
    post_abholen.einordnen_offene(10)            # heute endgueltig, 2 Aufrufe
    r = _mails()[0]
    assert (r["status"], r["fehl_aufrufe"], r["modellaufrufe"]) == ("eingeordnet", 1, 2)
    assert post_abholen.modellaufrufe_heute() == 3
