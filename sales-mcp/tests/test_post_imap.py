"""IMAP-Befehle zum Aufraeumen (Spec 2026-11-06 §11): nie mehr als die gemeinte UID.

Rein, ohne Datenbank und ohne Netz. Grundlage ist `FakeKasten`: Faehigkeiten,
Ordner als dict[str, dict[int, bytes]], Flags und ein Protokoll jedes Befehls.
`expunge()` ohne UID wird protokolliert UND wirkt wie auf einem echten Server
(entfernt jede \\Deleted-Mail des Ordners), damit ein Rueckfall auffaellt.
`test_post_ordnen.py` nutzt dieselbe Attrappe.
"""
import email
import re
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))
import post_imap  # noqa: E402
import postfach  # noqa: E402


def mail(message_id: str | None, betreff="Hallo") -> bytes:
    m = EmailMessage()
    m["From"] = "Shop <news@shop.example>"
    m["To"] = "felix@example.org"
    m["Subject"] = betreff
    if message_id:
        m["Message-ID"] = f"<{message_id}>"
    m.set_content("Text")
    return m.as_bytes()


def mail_mit_anhang(message_id: str | None, *teile) -> bytes:
    """Mail mit Anhaengen; je Teil (maintype, subtype, dateiname|None, disposition|None)."""
    m = EmailMessage()
    m["From"] = "Shop <news@shop.example>"
    m["Subject"] = "Angebot"
    if message_id:
        m["Message-ID"] = f"<{message_id}>"
    m.set_content("Text")
    for haupt, unter, name, disposition in teile:
        if (haupt, unter) == ("message", "rfc822"):
            innen = EmailMessage()
            innen["Subject"] = "weitergeleitet"
            innen.set_content("innen")
            m.add_attachment(innen)
            continue
        m.add_attachment(b"\x00\x01daten", maintype=haupt, subtype=unter)
        teil = m.get_payload()[-1]
        del teil["Content-Disposition"]
        if disposition:
            teil["Content-Disposition"] = (disposition + (f'; filename="{name}"' if name else ""))
    return m.as_bytes()


def _bodystructure(roh: bytes) -> str:
    """Vereinfachte, aber formgerechte BODYSTRUCTURE (RFC 3501) der Mail `roh`."""
    def zitat(s) -> str:
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def teil(t) -> str:
        if t.get_content_maintype() == "multipart":
            kinder = "".join(teil(x) for x in t.get_payload())
            return f"({kinder} {zitat(t.get_content_subtype())} NIL NIL NIL NIL)"
        haupt, unter = t.get_content_maintype(), t.get_content_subtype()
        kopf = f"({zitat(haupt)} {zitat(unter)} NIL NIL NIL \"7bit\" 10"
        if haupt == "text":
            kopf += " 1"
        elif (haupt, unter) == ("message", "rfc822"):
            kopf += ' NIL ("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 5 1) 1'
        art, name = t.get_content_disposition(), t.get_filename()
        dsp = "NIL" if not art else (
            f"({zitat(art)} " + (f'("filename" {zitat(name)})' if name else "NIL") + ")")
        return kopf + f" NIL {dsp} NIL NIL)"

    return teil(email.message_from_bytes(roh))


def _name(roh) -> str:
    """'"Zur Info"' -> 'Zur Info' (post_imap zitiert jeden Ordnernamen)."""
    roh = roh.decode() if isinstance(roh, bytes) else str(roh)
    if roh.startswith('"') and roh.endswith('"'):
        roh = roh[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return roh


class FakeKasten:
    """IMAP-Attrappe mit Ordnern, Flags, COPYUID und Aufrufprotokoll."""

    def __init__(self, ordner=None, capabilities=("IMAP4REV1", "MOVE", "UIDPLUS"),
                 uidvalidity=1, merkmale=None):
        self.capabilities = tuple(capabilities)
        self.ordner = {"INBOX": {}}
        self.ordner.update({n: dict(m) for n, m in (ordner or {}).items()})
        self.merkmale = dict(merkmale or {})          # Ordner -> z. B. "\\Trash"
        self.uidvalidity = {n: uidvalidity for n in self.ordner}
        self.naechste = {n: max(m, default=0) + 1 for n, m in self.ordner.items()}
        self.flags = {}                                # (ordner, uid) -> set
        self.protokoll = []
        self.gewaehlt = None
        self.antworten = {}
        self.nein = set()                              # Befehle, die mit NO enden

    # --- Verbindung ---
    def capability(self):
        self.protokoll.append(("capability",))
        return "OK", [" ".join(self.capabilities).encode()]

    def select(self, ordner="INBOX", readonly=False):
        name = _name(ordner)
        self.protokoll.append(("select", name, readonly))
        if name not in self.ordner:
            return "NO", [b"Mailbox does not exist"]
        self.gewaehlt = name
        self.antworten = {"UIDVALIDITY": [str(self.uidvalidity[name]).encode()]}
        return "OK", [str(len(self.ordner[name])).encode()]

    def response(self, code):
        return code, self.antworten.pop(code, [None])

    def list(self):
        zeilen = []
        for n in self.ordner:
            zeilen.append(f'(\\HasNoChildren {self.merkmale.get(n, "")}) "/" "{n}"'.encode())
        return "OK", zeilen

    def create(self, ordner):
        name = _name(ordner)
        self.protokoll.append(("create", name))
        if "create" in self.nein:
            return "NO", [b"nope"]
        self.ordner.setdefault(name, {})
        self.uidvalidity.setdefault(name, 1)
        self.naechste.setdefault(name, 1)
        return "OK", [b""]

    def expunge(self):
        # Nacktes EXPUNGE: entfernt ALLE \Deleted-Mails des Ordners - genau die Gefahr.
        self.protokoll.append(("expunge",))
        for uid in list(self.ordner[self.gewaehlt]):
            if "\\Deleted" in self.flags.get((self.gewaehlt, uid), set()):
                del self.ordner[self.gewaehlt][uid]
        return "OK", [b""]

    def logout(self):
        self.protokoll.append(("logout",))
        return "BYE", [b""]

    # --- UID-Befehle ---
    def _ablegen(self, ziel: str, uid: int) -> int:
        neu = self.naechste[ziel]
        self.naechste[ziel] += 1
        self.ordner[ziel][neu] = self.ordner[self.gewaehlt][uid]
        self.antworten.setdefault("COPYUID", []).append(
            f"{self.uidvalidity[ziel]} {uid} {neu}".encode())
        return neu

    def uid(self, befehl, *args):
        befehl = befehl.upper()
        args = tuple(a.decode() if isinstance(a, bytes) else a for a in args)
        self.protokoll.append(("uid", befehl) + args)
        if befehl in self.nein:
            return "NO", [b"abgelehnt"]
        inhalt = self.ordner[self.gewaehlt]
        if befehl == "FETCH":
            uid = int(args[0])
            if uid not in inhalt:
                return "OK", [None]
            if "BODYSTRUCTURE" in str(args[1]).upper():
                # Nur die Struktur, nie Inhalt - so wie post_imap es anfragt.
                return "OK", [f"1 (UID {uid} BODYSTRUCTURE {_bodystructure(inhalt[uid])})"
                              .encode()]
            kopf = b""
            for zeile in inhalt[uid].split(b"\n"):
                if zeile.lower().startswith(b"message-id:"):
                    kopf = zeile.rstrip(b"\r") + b"\r\n"
            return "OK", [(f"1 (UID {uid} BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(kopf) + 2}}}"
                           .encode(), kopf + b"\r\n"), b")"]
        if befehl == "SEARCH":
            gesucht = _name(args[-1])
            treffer = [u for u, roh in inhalt.items() if gesucht.encode() in roh]
            return "OK", [" ".join(map(str, sorted(treffer))).encode()]
        if befehl in ("MOVE", "COPY"):
            uid, ziel = int(args[0]), _name(args[1])
            if uid not in inhalt or ziel not in self.ordner:
                return "OK", [None]
            self._ablegen(ziel, uid)
            if befehl == "MOVE":
                del inhalt[uid]
            return "OK", [None]
        if befehl == "STORE":
            uid = int(args[0])
            if uid in inhalt:
                self.flags.setdefault((self.gewaehlt, uid), set()).add("\\Deleted")
            return "OK", [None]
        if befehl == "EXPUNGE":
            uid = int(args[0])
            if "\\Deleted" in self.flags.get((self.gewaehlt, uid), set()):
                inhalt.pop(uid, None)
            return "OK", [None]
        raise AssertionError(f"unbekannter Befehl {befehl}")

    # Hilfen fuer Tests
    def befehle(self, name: str) -> list:
        return [p for p in self.protokoll if p[:2] == ("uid", name)]

    def nackt_expunged(self) -> bool:
        return ("expunge",) in self.protokoll


def _kasten(**kw) -> FakeKasten:
    return FakeKasten(ordner={"INBOX": {7: mail("m7@x"), 8: mail("m8@x")},
                              "Zur Info": {}}, **kw)


# --- verschieben ---------------------------------------------------------------

def test_move_wenn_vorhanden():
    k = _kasten()
    neu = post_imap.verschieben(k, "INBOX", 7, "Zur Info")
    moves = k.befehle("MOVE")
    assert len(moves) == 1 and moves[0][:3] == ("uid", "MOVE", "7")
    assert _name(moves[0][3]) == "Zur Info"
    assert not k.befehle("EXPUNGE") and not k.nackt_expunged()
    assert neu == 1 and 7 not in k.ordner["INBOX"] and 8 in k.ordner["INBOX"]
    assert k.ordner["Zur Info"][1] == mail("m7@x")


def test_copy_store_uid_expunge_ohne_move():
    k = _kasten(capabilities=("IMAP4REV1", "UIDPLUS"))
    # Eine fremde, schon geloescht markierte Mail im selben Ordner darf nicht mitgehen.
    k.flags[("INBOX", 8)] = {"\\Deleted"}
    neu = post_imap.verschieben(k, "INBOX", 7, "Zur Info")
    assert [p[:3] for p in k.befehle("COPY")] == [("uid", "COPY", "7")]
    assert [p[:3] for p in k.befehle("STORE")] == [("uid", "STORE", "7")]
    assert k.befehle("EXPUNGE") == [("uid", "EXPUNGE", "7")]
    assert not k.nackt_expunged() and not k.befehle("MOVE")
    assert neu == 1 and 7 not in k.ordner["INBOX"] and 8 in k.ordner["INBOX"]


def test_ohne_move_und_uidplus_nicht_unterstuetzt():
    k = _kasten(capabilities=("IMAP4REV1",))
    with pytest.raises(post_imap.NichtUnterstuetzt):
        post_imap.verschieben(k, "INBOX", 7, "Zur Info")
    with pytest.raises(post_imap.NichtUnterstuetzt):
        post_imap.loeschen(k, "INBOX", 7, "gmx", message_id="m7@x")
    # Nichts angefasst: kein Kopieren, kein Flag, kein Expunge.
    assert not [p for p in k.protokoll if p[0] in ("uid", "expunge")]
    assert set(k.ordner["INBOX"]) == {7, 8}


def test_verschieben_ohne_copyuid_gibt_none():
    k = _kasten()
    k._ablegen_orig = k._ablegen

    def ohne_copyuid(ziel, uid):
        neu = k._ablegen_orig(ziel, uid)
        k.antworten.pop("COPYUID", None)
        return neu
    k._ablegen = ohne_copyuid
    assert post_imap.verschieben(k, "INBOX", 7, "Zur Info") is None


def test_alte_copyuid_wird_nicht_als_neue_uid_gelesen():
    k = _kasten()
    k.antworten["COPYUID"] = [b"1 7 99"]                # Rest eines frueheren Befehls
    assert post_imap.verschieben(k, "INBOX", 7, "Zur Info") == 1


def test_fehlende_uid_ist_fehlt_und_nichts_passiert():
    k = _kasten()
    with pytest.raises(post_imap.Fehlt):
        post_imap.verschieben(k, "INBOX", 9, "Zur Info")
    with pytest.raises(post_imap.Fehlt):
        post_imap.verschieben(k, "INBOX", 0, "Zur Info")
    assert not k.befehle("MOVE") and set(k.ordner["INBOX"]) == {7, 8}


def test_falsche_message_id_unter_der_uid_ist_fehlt():
    k = _kasten()
    with pytest.raises(post_imap.Fehlt):
        post_imap.verschieben(k, "INBOX", 7, "Zur Info", message_id="andere@x")
    with pytest.raises(post_imap.Fehlt):
        post_imap.loeschen(k, "INBOX", 7, "gmx", message_id="andere@x")
    assert not k.befehle("MOVE") and not k.befehle("STORE") and not k.befehle("EXPUNGE")
    assert set(k.ordner["INBOX"]) == {7, 8}


def test_abgelehnter_befehl_wirft_imapfehler():
    k = _kasten()
    k.nein.add("MOVE")
    with pytest.raises(post_imap.ImapFehler):
        post_imap.verschieben(k, "INBOX", 7, "Zur Info")


def test_quellordner_fehlt_ist_fehlt():
    k = _kasten()
    with pytest.raises(post_imap.Fehlt):
        post_imap.verschieben(k, "To-Review", 7, "Zur Info")


# --- loeschen ------------------------------------------------------------------

def test_gmx_loeschen_mit_uid_expunge():
    k = _kasten()
    k.flags[("INBOX", 8)] = {"\\Deleted"}
    post_imap.loeschen(k, "INBOX", 7, "gmx", message_id="m7@x")
    assert [p[:3] for p in k.befehle("STORE")] == [("uid", "STORE", "7")]
    assert k.befehle("EXPUNGE") == [("uid", "EXPUNGE", "7")]
    assert not k.nackt_expunged()
    assert set(k.ordner["INBOX"]) == {8}


def test_loeschen_ohne_uidplus_nicht_unterstuetzt():
    k = _kasten(capabilities=("IMAP4REV1", "MOVE"))
    with pytest.raises(post_imap.NichtUnterstuetzt):
        post_imap.loeschen(k, "INBOX", 7, "gmx", message_id="m7@x")
    assert not k.befehle("STORE") and set(k.ordner["INBOX"]) == {7, 8}


def test_loeschen_nur_mit_message_id():
    k = _kasten()
    with pytest.raises(ValueError):
        post_imap.loeschen(k, "INBOX", 7, "gmx", message_id="")
    assert not k.befehle("STORE")


def test_gmail_loeschen_ueber_papierkorb_und_uid_expunge():
    k = FakeKasten(ordner={"INBOX": {7: mail("m7@x"), 8: mail("m8@x")},
                           "[Gmail]/Papierkorb": {3: mail("alt@x")}},
                   merkmale={"[Gmail]/Papierkorb": "\\Trash"})
    k.flags[("[Gmail]/Papierkorb", 3)] = {"\\Deleted"}     # fremde Leiche im Papierkorb
    post_imap.loeschen(k, "INBOX", 7, "gmail", message_id="m7@x")
    moves = k.befehle("MOVE")
    assert len(moves) == 1 and moves[0][:3] == ("uid", "MOVE", "7")
    assert _name(moves[0][3]) == "[Gmail]/Papierkorb"
    # Im Papierkorb nur die neue UID (4) markiert und per UID EXPUNGE entfernt.
    assert [p[:3] for p in k.befehle("STORE")] == [("uid", "STORE", "4")]
    assert k.befehle("EXPUNGE") == [("uid", "EXPUNGE", "4")]
    assert not k.nackt_expunged()
    assert set(k.ordner["INBOX"]) == {8}
    assert set(k.ordner["[Gmail]/Papierkorb"]) == {3}


def test_gmail_loeschen_ohne_papierkorb_nicht_unterstuetzt():
    k = _kasten()
    with pytest.raises(post_imap.NichtUnterstuetzt):
        post_imap.loeschen(k, "INBOX", 7, "gmail", message_id="m7@x")
    assert not k.befehle("MOVE") and set(k.ordner["INBOX"]) == {7, 8}


def test_gmail_loeschen_ohne_neue_uid_nicht_unterstuetzt():
    k = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}, "[Gmail]/Trash": {}},
                   merkmale={"[Gmail]/Trash": "\\Trash"})
    original = k._ablegen

    def ohne_copyuid(ziel, uid):
        neu = original(ziel, uid)
        k.antworten.pop("COPYUID", None)
        return neu
    k._ablegen = ohne_copyuid
    with pytest.raises(post_imap.NichtUnterstuetzt):
        post_imap.loeschen(k, "INBOX", 7, "gmail", message_id="m7@x")
    assert not k.befehle("STORE") and not k.befehle("EXPUNGE")


# --- Anhaenge per BODYSTRUCTURE (I7) ----------------------------------------------

@pytest.mark.parametrize("teile,erwartet", [
    ((), False),
    ((("image", "png", "bild.png", "attachment"),), False),
    ((("image", "jpeg", None, "attachment"),), False),           # Bild ohne Namen: erlaubt
    ((("image", "gif", None, None),), False),
    ((("application", "pdf", "angebot.pdf", "attachment"),), True),
    ((("application", "octet-stream", None, None),), True),       # ohne Namen, ohne Disposition
    ((("application", "pdf", None, "inline"),), True),
    ((("text", "plain", None, "attachment"),), True),             # Disposition attachment
    ((("message", "rfc822", None, None),), True),
    ((("image", "png", "a.png", "attachment"), ("application", "zip", None, None)), True),
], ids=["ohne", "bild", "bild-ohne-name", "bild-inline", "pdf", "octet-ohne-name",
        "pdf-inline", "text-attachment", "rfc822", "bild-und-zip"])
def test_anhang_ausser_bildern(teile, erwartet):
    k = FakeKasten(ordner={"INBOX": {7: mail_mit_anhang("m7@x", *teile)}})
    post_imap.waehlen(k, "INBOX")
    assert post_imap.anhang_ausser_bildern(k, 7) is erwartet
    # Nur die Struktur, kein Inhalt, nichts Schreibendes.
    abrufe = k.befehle("FETCH")
    assert [p[3] for p in abrufe] == ["(BODYSTRUCTURE)"]
    assert not [p for p in k.protokoll if p[:2] in (("uid", "STORE"), ("uid", "MOVE"))]


def test_anhang_ausser_bildern_fehlende_uid_ist_fehlt():
    k = _kasten()
    post_imap.waehlen(k, "INBOX")
    with pytest.raises(post_imap.Fehlt):
        post_imap.anhang_ausser_bildern(k, 9)


def test_anhang_ausser_bildern_liest_literal_und_fremde_antworten():
    """imaplib liefert Literale als Tupel; ungefragte FETCH-Antworten anderer UIDs zaehlen nicht."""
    class Kasten:
        def uid(self, befehl, *args):
            return "OK", [
                b'2 (UID 8 BODYSTRUCTURE ("application" "pdf" NIL NIL NIL "base64" 9 NIL NIL NIL NIL))',
                (b'1 (UID 7 BODYSTRUCTURE (("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 4 1 '
                 b'NIL NIL NIL NIL)("image" "png" ("name" {9}', b'bild).png'),
                b') NIL NIL "base64" 10 NIL ("attachment" NIL) NIL NIL) "mixed" NIL NIL NIL NIL))']
    assert post_imap.anhang_ausser_bildern(Kasten(), 7) is False


def test_anhang_ausser_bildern_unlesbar_ist_imapfehler():
    class Kasten:
        def uid(self, befehl, *args):
            return "OK", [b'1 (UID 7 BODYSTRUCTURE ("text" "plain"']
    with pytest.raises(post_imap.ImapFehler):
        post_imap.anhang_ausser_bildern(Kasten(), 7)


# --- Ordner, Suche, Faehigkeiten ------------------------------------------------

def test_ordner_sicherstellen_legt_nur_fehlende_an():
    k = _kasten()
    assert post_imap.ordner_sicherstellen(k, "Zur Info") == '"Zur Info"'
    assert post_imap.ordner_sicherstellen(k, "To-Review") == '"To-Review"'
    assert [p for p in k.protokoll if p[0] == "create"] == [("create", "To-Review")]


def test_ordner_nicht_anlegbar_ist_nicht_unterstuetzt():
    k = _kasten()
    k.nein.add("create")
    with pytest.raises(post_imap.NichtUnterstuetzt):
        post_imap.ordner_sicherstellen(k, "To-Review")


def test_suchen_findet_genau_die_message_id():
    k = FakeKasten(ordner={"Zur Info": {3: mail("abc@x"), 4: mail("xabc@x"), 5: mail("q@x")}})
    post_imap.waehlen(k, "Zur Info")
    assert post_imap.suchen(k, "abc@x") == 3            # Teiltreffer 4 zaehlt nicht
    with pytest.raises(post_imap.Fehlt):
        post_imap.suchen(k, "fehlt@x")
    with pytest.raises(post_imap.Fehlt):
        post_imap.suchen(k, 'mit"anfuehrung@x')        # nicht sicher suchbar


def test_faehigkeiten_nach_der_anmeldung_neu_gelesen():
    # imaplib liest CAPABILITY nur vor dem Login; Gmail nennt MOVE/UIDPLUS erst danach.
    k = _kasten()
    k.capabilities = ("IMAP4REV1",)
    k.capability = lambda: ("OK", [b"IMAP4rev1 MOVE UIDPLUS"])
    post_imap.faehigkeiten_auffrischen(k)
    assert {"MOVE", "UIDPLUS"} <= set(k.capabilities)


# --- Regression: kein nacktes expunge ----------------------------------------------

def test_postfach_verschieben_ruft_kein_nacktes_expunge(monkeypatch):
    k = FakeKasten(ordner={"INBOX": {7: mail("m7@x"), 8: mail("m8@x")},
                           "Spamverdacht": {}},
                   capabilities=("IMAP4REV1", "UIDPLUS"),
                   merkmale={"Spamverdacht": "\\Junk"})
    k.flags[("INBOX", 8)] = {"\\Deleted"}               # vom Handy markiert, nicht von uns
    monkeypatch.setattr(postfach, "oeffnen", lambda kennung: k)
    assert postfach.verschieben("7", "spam") == "Spamverdacht"
    assert not k.nackt_expunged()
    assert k.befehle("EXPUNGE") == [("uid", "EXPUNGE", "7")]
    assert set(k.ordner["INBOX"]) == {8}                # die fremde Mail lebt
    assert ("logout",) in k.protokoll


def test_postfach_verschieben_unwichtig_legt_ordner_an(monkeypatch):
    k = FakeKasten(ordner={"INBOX": {7: mail("m7@x")}})
    monkeypatch.setattr(postfach, "oeffnen", lambda kennung: k)
    assert postfach.verschieben("7", "unwichtig") == postfach.UNWICHTIG_ORDNER
    assert ("create", postfach.UNWICHTIG_ORDNER) in k.protokoll
    assert not k.nackt_expunged() and 7 not in k.ordner["INBOX"]


_NACKT = re.compile(r"\.expunge\s*\(")


@pytest.mark.parametrize("datei", ["postfach.py", "post_imap.py", "post_ordnen.py"])
def test_kein_nacktes_expunge_im_quelltext(datei):
    """Spec §11: `expunge()` entfernt jede \\Deleted-Mail des Ordners, nicht nur die eine."""
    quelltext = (WURZEL / datei).read_text(encoding="utf-8")
    assert not _NACKT.search(quelltext), f"nacktes expunge() in {datei}"
