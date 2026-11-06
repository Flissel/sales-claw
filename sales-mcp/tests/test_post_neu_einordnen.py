"""Neu-Sortierung des Altbestands: Vorschau, Bericht, Anwenden.

DB-Tests nur gegen sales_test. `einordnen` ist durch eine Attrappe ersetzt - das
Modell wird nie gerufen.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import post_abholen  # noqa: E402
import post_einordnung  # noqa: E402
import post_neu_einordnen as neu  # noqa: E402
import post_struktur  # noqa: E402
import post_werbung  # noqa: E402
import server  # noqa: E402
from gateway import GatewayFehler  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' - erlaubt ist nur 'sales_test'.")


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_konten cascade")
        conn.execute("delete from sales_test.activities where type = 'kundenantwort'")
        conn.execute("truncate sales_test.post_mails")


@pytest.fixture(autouse=True)
def sauber():
    _aufraeumen()
    yield
    _aufraeumen()


@pytest.fixture
def konto_id():
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
            "values ('felix', 'gmx-test', 'gmx', 'gmx-test@gmx.de', 'ui') returning id"
        ).fetchone()["id"]


def _mail(konto, uid, *, von="Shop <info@shop-test.example>", betreff="Hallo", quelle="modell",
          version=1, sensibel=False, bereich="business", fach="Sonstiges", aufrufe=1,
          status="eingeordnet", text="Mailtext", datum=None):
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, betreff, text, "
            "auszug, an, anhaenge, status, bereich, fach, sensibel, einordnung_quelle, "
            "einordnung_version, modellaufrufe, eingeordnet_am, datum) "
            "values (%s, %s, %s, 'felix', %s, %s, %s, 'Auszug', 'felix@x', '{a.pdf}', %s, %s, %s, "
            "%s, %s, %s, %s, now() - interval '3 days', %s::timestamptz) returning id",
            (konto, uid, f"m{uid}@x", von, betreff, text, status, bereich, fach, sensibel,
             quelle, version, aufrufe, datum)).fetchone()["id"]


def _zeile(mail_id):
    with server.pool.connection() as conn:
        return conn.execute("select * from post_mails where id = %s", (mail_id,)).fetchone()


def _fake(ergebnis=None, aufrufe=1, gesehen=None):
    ergebnis = ergebnis or {}

    def einordnen(mail, konto):
        if gesehen is not None:
            gesehen.append(mail)
        return post_einordnung.Einordnung(
            ergebnis.get("bereich", "privat"), ergebnis.get("fach", "Rechnungen"),
            ergebnis.get("sensibel", False), ergebnis.get("quelle", "pruefer"),
            ergebnis.get("begruendung", "neu"), ergebnis.get("unterfach"),
            aufrufe=aufrufe, vorschlaege=ergebnis.get("vorschlaege"),
            aufmerksamkeit=ergebnis.get("aufmerksamkeit", False),
            werbung_sicher=ergebnis.get("werbung_sicher", False))
    return einordnen


@pytest.fixture(autouse=True)
def grenze_hoch(monkeypatch):
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 500)


def test_vorschau_aendert_echte_spalten_nicht(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, betreff="Rechnung", fach="Sonstiges")
    vorher = _zeile(mid)
    gesehen = []
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(gesehen=gesehen))
    assert neu.vorschau(10) == 1
    nachher = _zeile(mid)
    assert nachher["vorschau"]["fach"] == "Rechnungen" and nachher["vorschau_am"] is not None
    assert nachher["vorschau"]["aufrufe"] == 1
    for spalte in ("bereich", "fach", "unterfach", "sensibel", "einordnung_quelle", "begruendung",
                   "einordnung_version", "status", "text", "auszug", "an", "anhaenge",
                   "modellaufrufe", "eingeordnet_am", "vorschlaege"):
        assert nachher[spalte] == vorher[spalte], spalte
    # Die Mail wird so gebaut wie im Betrieb.
    assert gesehen[0]["betreff"] == "Rechnung" and gesehen[0]["besitzer"] == "felix"


def test_vorschau_ueberspringt_mensch_und_version_3(monkeypatch, konto_id):
    mensch = _mail(konto_id, 1, quelle="mensch")
    v3 = _mail(konto_id, 2, version=3)
    offen = _mail(konto_id, 3, status="fehler", fach="Zum Nachsehen", bereich="privat")
    monkeypatch.setattr(post_einordnung, "einordnen", _fake())
    assert neu.vorschau(10) == 1
    assert _zeile(mensch)["vorschau"] is None and _zeile(v3)["vorschau"] is None
    assert _zeile(offen)["vorschau"] is not None
    # Ohne --alle keine zweite Vorschau; mit --alle wieder.
    assert neu.vorschau(10) == 0
    assert neu.vorschau(10, alle=True) == 1


def test_vorschau_haelt_tagesgrenze(monkeypatch, konto_id):
    for uid in range(1, 6):
        _mail(konto_id, uid)
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 3)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(aufrufe=2))
    bearbeitet = neu.vorschau(10)
    assert bearbeitet <= 2 and bearbeitet >= 1
    # Die Vorschau-Aufrufe zaehlen in der Tagesbilanz.
    assert post_abholen.modellaufrufe_heute() == 2 * bearbeitet
    assert post_abholen.modellaufrufe_heute() <= 3


def test_anwenden_uebernimmt_vorschau_ohne_modell(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, aufrufe=1)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"bereich": "privat", "fach": "Rechnungen", "unterfach": None, "quelle": "pruefer",
         "begruendung": "grund"}, aufrufe=2))
    neu.vorschau(10)

    def verboten(*a, **k):
        pytest.fail("anwenden darf das Modell nicht rufen")
    monkeypatch.setattr(post_einordnung, "einordnen", verboten)
    assert neu.anwenden() == 1
    z = _zeile(mid)
    assert (z["bereich"], z["fach"], z["einordnung_quelle"], z["begruendung"]) == (
        "privat", "Rechnungen", "pruefer", "grund")
    assert z["einordnung_version"] == 3 and z["vorschau"] is None and z["status"] == "eingeordnet"
    assert z["modellaufrufe"] == 1            # nicht doppelt gezaehlt
    assert z["text"] == "Mailtext"            # nicht sensibel: Inhalt bleibt
    assert neu.anwenden() == 0                # wiederholbar


def test_anwenden_laesst_zwischenzeitliche_korrektur_unberuehrt(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, fach="Sonstiges")
    monkeypatch.setattr(post_einordnung, "einordnen", _fake())
    neu.vorschau(10)
    with server.pool.connection() as conn:
        conn.execute("update post_mails set einordnung_quelle = 'mensch' where id = %s", (mid,))
    vorher = _zeile(mid)
    assert neu.anwenden() == 0
    nachher = _zeile(mid)
    assert nachher["fach"] == "Sonstiges" and nachher["einordnung_quelle"] == "mensch"
    assert nachher["einordnung_version"] == 1 and nachher["vorschau"] == vorher["vorschau"]


def test_anwenden_macht_sensible_nie_unsensibel(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, sensibel=True, text=None)
    # Alte Zeile war sensibel, hatte aber noch Reste in an/auszug/anhaenge (Fail-closed-Probe).
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"sensibel": False, "begruendung": "geheimer freitext",
         "vorschlaege": {"sortierer": {"fach": "x", "begruendung": "frei"},
                         "pruefer": {"fach": "y", "begruendung": "frei"}}}))
    neu.vorschau(10)
    v = _zeile(mid)["vorschau"]
    assert "frei" not in str(v["vorschlaege"]) and "geheimer" not in str(v)
    assert neu.anwenden() == 1
    z = _zeile(mid)
    assert z["sensibel"] is True
    assert z["text"] is None and z["auszug"] is None and z["an"] is None and z["anhaenge"] == []
    assert "geheimer" not in (z["begruendung"] or "") and "frei" not in str(z["vorschlaege"])


def test_anwenden_leert_urspruengliche_adresse_bei_neu_sensibel(konto_id):
    sensibel = _mail(konto_id, 1)
    harmlos = _mail(konto_id, 2)
    with server.pool.connection() as conn:
        conn.execute("update post_mails set urspruengliche_adresse = 'a@b.example'")
    basis = {"bereich": "privat", "fach": "Rechnungen", "unterfach": None, "quelle": "modell",
             "begruendung": "b", "vorschlaege": None, "aufrufe": 1, "aufmerksamkeit": True,
             "werbung_sicher": False}
    _vorschau_setzen(sensibel, {**basis, "sensibel": True})
    _vorschau_setzen(harmlos, {**basis, "sensibel": False})
    assert neu.anwenden() == 2
    assert _zeile(sensibel)["urspruengliche_adresse"] is None
    assert _zeile(harmlos)["urspruengliche_adresse"] == "a@b.example"


def test_anwenden_leert_neu_sensible(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, sensibel=False)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"sensibel": True, "fach": "Konten & Sicherheit", "begruendung": "modell:sensibel",
         "vorschlaege": {"sortierer": {"fach": "x", "begruendung": "frei"}}}))
    neu.vorschau(10)
    neu.anwenden()
    z = _zeile(mid)
    assert z["sensibel"] is True and z["text"] is None and z["auszug"] is None
    assert z["an"] is None and z["anhaenge"] == []
    assert "frei" not in str(z["vorschlaege"])


def test_pruefer_ausfall_wird_zum_nachsehen(monkeypatch, konto_id):
    mid = _mail(konto_id, 1)

    def ausfall(mail, konto):
        raise post_einordnung.PrueferFehlgeschlagen(post_einordnung.Einordnung(
            "business", "Sonstiges", False, "modell", "sortierer-grund", None, aufrufe=1))
    monkeypatch.setattr(post_einordnung, "einordnen", ausfall)
    assert neu.vorschau(10) == 1
    v = _zeile(mid)["vorschau"]
    assert (v["bereich"], v["fach"], v["aufrufe"]) == ("privat", post_struktur.UNKLAR, 2)
    assert v["vorschlaege"]["sortierer"]["begruendung"] == "sortierer-grund"


def test_bericht_enthaelt_keine_betreffs(monkeypatch, konto_id):
    _mail(konto_id, 1, betreff="GEHEIM-123", von="Max Muster <max@mystery-test.example>")
    _mail(konto_id, 2, betreff="GEHEIM-456", von="x@instagram.com")
    _mail(konto_id, 3, betreff="GEHEIM-789")                  # bleibt offen
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"quelle": "katalog", "fach": "Soziale Netzwerke", "unterfach": "Instagram"}))
    neu.vorschau(2)
    b = neu.bericht()
    text = str(b)
    assert "GEHEIM" not in text and "max@" not in text
    assert b["offen"] == 1
    assert sum(b["alt"].values()) == 2 and sum(b["neu"].values()) == 2
    assert ("instagram.com", "Soziale Netzwerke", "Instagram", 1) in b["katalog"]
    assert ("mystery-test.example", 1) in b["ohne_katalog"]


def test_fehler_wird_gezaehlt_und_nicht_wiederholt(monkeypatch, konto_id):
    mid = _mail(konto_id, 1, sensibel=True, text=None)
    ruf = []

    def kaputt(mail, konto):
        ruf.append(1)
        raise GatewayFehler("x")
    monkeypatch.setattr(post_einordnung, "einordnen", kaputt)
    vorher = post_abholen.modellaufrufe_heute()
    assert neu.vorschau(10) == 1
    assert post_abholen.modellaufrufe_heute() > vorher
    v = _zeile(mid)["vorschau"]
    assert (v["fach"], v["begruendung"], v["sensibel"]) == (post_struktur.UNKLAR, "vorschau:fehler", True)
    assert neu.vorschau(10) == 0 and len(ruf) == 1


def test_fehler_senkt_rest_der_tagesgrenze(monkeypatch, konto_id):
    for uid in range(1, 6):
        _mail(konto_id, uid)
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 4)

    def kaputt(mail, konto):
        raise RuntimeError("x")
    monkeypatch.setattr(post_einordnung, "einordnen", kaputt)
    # M3: der Rest kommt vor jeder Mail aus der Datenbank. Jeder Fehlschlag bucht
    # einen Aufruf; die naechste Mail startet nur, solange noch 2 Aufrufe frei sind.
    assert neu.vorschau(10) == 3          # Rest 4, 3, 2 -> drei Mails; bei 1 Schluss
    assert post_abholen.modellaufrufe_heute() == 3


def test_tagesgrenze_wird_vor_jeder_mail_neu_gelesen(monkeypatch, konto_id):
    """M3: sales-post ordnet parallel ein und verbraucht dieselbe Tagesgrenze -
    die Vorschau darf nicht mit dem Stand vom Start weiterrechnen."""
    for uid in range(1, 6):
        _mail(konto_id, uid)
    parallel = _mail(konto_id, 99, version=3, aufrufe=0)   # gehoert sales-post, kein Altbestand
    with server.pool.connection() as conn:
        conn.execute("update post_mails set eingeordnet_am = now() where id = %s", (parallel,))
    monkeypatch.setattr(post_abholen, "TAGESGRENZE", 6)
    innen = _fake(aufrufe=1)

    def einordnen_und_parallel(mail, konto):
        # Waehrend jeder Vorschau-Mail bucht sales-post zwei Aufrufe.
        with server.pool.connection() as conn:
            conn.execute("update post_mails set modellaufrufe = modellaufrufe + 2 "
                         "where id = %s", (parallel,))
        return innen(mail, konto)
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen_und_parallel)
    # Mail 1 bei 0 verbraucht; danach 1 + 2 = 3 -> Mail 2; danach 6 -> Schluss.
    # Mit dem einmal gelesenen Rest liefen alle fuenf (6 - 1 je Mail).
    assert neu.vorschau(10) == 2
    assert post_abholen.modellaufrufe_heute() == 6


def test_pruefer_voruebergehend_bucht_vorschau_kosten(monkeypatch, konto_id):
    """I1: Pruefer voruebergehend weg - der bezahlte Sortierer zaehlt zur Tagesgrenze,
    die Vorschau bleibt leer (die Mail kommt beim naechsten Lauf wieder), Pause."""
    a = _mail(konto_id, 1)
    b = _mail(konto_id, 2)
    ruf = []

    def weg(mail, konto):
        ruf.append(mail["id"])
        raise post_einordnung.PrueferVoruebergehend(1)
    monkeypatch.setattr(post_einordnung, "einordnen", weg)
    for lauf in (1, 2):
        assert neu.vorschau(10) == 0
        assert len(ruf) == lauf                       # Pause nach der ersten Mail
        za, zb = _zeile(a), _zeile(b)
        assert za["vorschau"] is None and zb["vorschau"] is None
        assert za["vorschau_aufrufe"] == lauf and zb["vorschau_aufrufe"] == 0
        assert za["modellaufrufe"] == 1               # die echte Spalte bleibt
        assert post_abholen.modellaufrufe_heute() == lauf


def _vorschau_setzen(mail_id, vorschau: dict):
    with server.pool.connection() as conn:
        conn.execute("update post_mails set vorschau = %s::jsonb, vorschau_am = now() "
                     "where id = %s", (server._json(vorschau), mail_id))


def test_anwenden_zum_nachsehen_immer_privat_und_nur_feste_faecher(konto_id):
    """I2d: anwenden prueft die Vorschau gegen die feste Liste - Zum Nachsehen
    liegt privat, ein unbekanntes Fach wird privat/Zum Nachsehen ohne Unterfach."""
    nachsehen = _mail(konto_id, 1)
    erfunden = _mail(konto_id, 2)
    falscher_bereich = _mail(konto_id, 3)
    gut = _mail(konto_id, 4)
    basis = {"sensibel": False, "quelle": "modell", "begruendung": "b", "vorschlaege": None,
             "aufrufe": 2}
    _vorschau_setzen(nachsehen, {**basis, "bereich": "business", "fach": post_struktur.UNKLAR,
                                 "unterfach": None})
    _vorschau_setzen(erfunden, {**basis, "bereich": "business", "fach": "Erfunden",
                                "unterfach": "Irgendwas"})
    _vorschau_setzen(falscher_bereich, {**basis, "bereich": "privat", "fach": "Tools & Dienste",
                                        "unterfach": "GitHub"})
    _vorschau_setzen(gut, {**basis, "bereich": "business", "fach": "Tools & Dienste",
                           "unterfach": "GitHub"})
    assert neu.anwenden() == 4
    for mid in (nachsehen, erfunden, falscher_bereich):
        z = _zeile(mid)
        assert (z["bereich"], z["fach"], z["unterfach"]) == ("privat", post_struktur.UNKLAR, None)
    z = _zeile(gut)
    assert (z["bereich"], z["fach"], z["unterfach"]) == ("business", "Tools & Dienste", "GitHub")


def _abholfehler(konto, uid):
    """Zeile wie post_abholen._unlesbar: schon beim Abholen kaputt, nie einsortiert."""
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, status, fehler, "
            "bereich, fach, message_id_ersatz) values (%s, %s, %s, 'felix', 'fehler', %s, "
            "'privat', %s, true) returning id",
            (konto, uid, f"gmx-test:{uid}@sales-post",
             f"{post_abholen.ABHOLFEHLER} (ValueError)", post_struktur.UNKLAR)).fetchone()["id"]


def test_abholfehler_bleiben_unberuehrt(monkeypatch, konto_id):
    """M6: eine Mail, die schon beim Abholen kaputt war, wird nicht neu sortiert -
    sonst verdeckte `anwenden` (status eingeordnet, fehler null) den Abholfehler.
    Sortier-Fehler dagegen kommen in die Neu-Sortierung."""
    kaputt = _abholfehler(konto_id, 1)
    sortierfehler = _mail(konto_id, 2, status="fehler", bereich="privat",
                          fach=post_struktur.UNKLAR)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake())
    assert neu.vorschau(10) == 1
    assert _zeile(kaputt)["vorschau"] is None and _zeile(sortierfehler)["vorschau"] is not None
    assert neu.bericht()["offen"] == 0             # der Abholfehler zaehlt nicht als offen
    # Auch eine (von Hand oder frueher) gesetzte Vorschau wendet anwenden nicht an.
    _vorschau_setzen(kaputt, {"bereich": "privat", "fach": "Rechnungen", "unterfach": None,
                              "sensibel": False, "quelle": "modell", "begruendung": "b",
                              "vorschlaege": None, "aufrufe": 1})
    assert neu.anwenden() == 1
    z = _zeile(kaputt)
    assert (z["status"], z["fach"], z["einordnung_version"]) == ("fehler", post_struktur.UNKLAR, 1)
    assert z["fehler"].startswith(post_abholen.ABHOLFEHLER)
    assert _zeile(sortierfehler)["status"] == "eingeordnet"


def test_vorschau_kosten_ueberleben_anwenden(monkeypatch, konto_id):
    _mail(konto_id, 1)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(aufrufe=2))
    neu.vorschau(10)
    nach_vorschau = post_abholen.modellaufrufe_heute()
    assert nach_vorschau == 2
    neu.anwenden()
    assert post_abholen.modellaufrufe_heute() == nach_vorschau


def test_vorschau_alle_zaehlt_aufsummiert(monkeypatch, konto_id):
    _mail(konto_id, 1)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(aufrufe=2))
    neu.vorschau(10)
    erste = post_abholen.modellaufrufe_heute()
    neu.vorschau(10, alle=True)
    assert post_abholen.modellaufrufe_heute() == erste + 2


# ---------------------------------------------------------------------------
# Task 8: Altbestand v2, Stichprobe je Konto, Anteil Zum Nachsehen, neue Felder
# ---------------------------------------------------------------------------

def _zweites_konto():
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
            "values ('felix', 'web-test', 'gmx', 'web-test@gmx.de', 'ui') returning id"
        ).fetchone()["id"]


def test_v2_einordnungen_zaehlen_als_altbestand(monkeypatch, konto_id):
    v2 = _mail(konto_id, 1, version=2)
    v3 = _mail(konto_id, 2, version=3)
    mensch_v2 = _mail(konto_id, 3, version=2, quelle="mensch")
    monkeypatch.setattr(post_einordnung, "einordnen", _fake())
    assert neu.vorschau(10) == 1
    assert _zeile(v2)["vorschau"] is not None
    assert _zeile(v3)["vorschau"] is None
    # Eine Handkorrektur wird auch mit Version 2 nie angefasst.
    assert _zeile(mensch_v2)["vorschau"] is None
    assert neu.anwenden() == 1
    assert _zeile(v2)["einordnung_version"] == 3
    assert neu.anwenden() == 0            # danach nicht mehr im Altbestand: keine Endlosschleife


def test_vorschau_je_konto_n(monkeypatch, konto_id):
    web = _zweites_konto()
    alt = [_mail(konto_id, uid, datum=f"2024-01-0{uid}T10:00:00Z") for uid in (1, 2, 3)]
    web_alt = [_mail(web, uid, datum=f"2023-05-0{uid}T10:00:00Z") for uid in (1, 2)]
    ohne_datum = _mail(konto_id, 9)          # kein Datum: gilt als aeltestes
    gesehen = []
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(gesehen=gesehen))
    assert neu.vorschau(100, je_konto=2) == 4
    mit = {m for m in alt + web_alt + [ohne_datum] if _zeile(m)["vorschau"] is not None}
    # Je Konto die zwei neuesten (hoechste Tage), nicht die ohne Datum.
    assert mit == {alt[1], alt[2], web_alt[0], web_alt[1]}
    # Zweiter Lauf zieht keine weiteren nach: die Stichprobe bleibt gleich gross.
    assert neu.vorschau(100, je_konto=2) == 0
    # Ohne je_konto sind die uebrigen dran.
    assert neu.vorschau(100) == 2
    # Ungueltiges N: nichts.
    assert neu.vorschau(100, alle=True, je_konto=0) == 0


def test_bericht_nennt_unklar_anteil_je_konto(monkeypatch, konto_id, capsys):
    web = _zweites_konto()
    for uid in (1, 2, 3, 4):
        _mail(konto_id, uid)
    _mail(web, 1)
    _mail(web, 2)

    def einordnen(mail, konto):
        # Nur die Mails des Kontos web-test landen bei Zum Nachsehen: genau eine von zwei.
        unklar = konto["kennung"] == "web-test" and mail["id"] == erste_web["id"]
        return post_einordnung.Einordnung(
            "privat", post_struktur.UNKLAR if unklar else "Rechnungen", False, "modell", "b",
            aufrufe=1)
    with server.pool.connection() as conn:
        erste_web = {"id": str(conn.execute(
            "select id from post_mails where konto_id = %s and imap_uid = 1", (web,)
        ).fetchone()["id"])}
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    assert neu.vorschau(10) == 6
    b = neu.bericht()
    assert b["unklar_anteil"] == {"gmx-test": 0.0, "web-test": 0.5}
    assert b["zum_nachsehen"] == 1
    neu._bericht_drucken(b)
    ausgabe = capsys.readouterr().out
    assert "Zum Nachsehen je Konto" in ausgabe
    assert "  0.50  web-test" in ausgabe and "  0.00  gmx-test" in ausgabe


def test_bericht_ohne_vorschau_hat_keinen_unklar_anteil(konto_id):
    _mail(konto_id, 1)
    assert neu.bericht()["unklar_anteil"] == {}


def test_vorschau_speichert_aufmerksamkeit_und_werbung_sicher(monkeypatch, konto_id):
    mid = _mail(konto_id, 1)
    monkeypatch.setattr(post_einordnung, "einordnen", _fake(
        {"fach": "Werbung", "aufmerksamkeit": False, "werbung_sicher": True}))
    neu.vorschau(10)
    v = _zeile(mid)["vorschau"]
    assert v["aufmerksamkeit"] is False and v["werbung_sicher"] is True


def test_anwenden_uebernimmt_neue_felder(monkeypatch, konto_id):
    werbung = _mail(konto_id, 1)
    handeln = _mail(konto_id, 2)
    monkeypatch.setattr(post_werbung, "regel_vorschlagen", lambda b, v: False)
    basis = {"bereich": "privat", "sensibel": False, "quelle": "modell", "begruendung": "b",
             "vorschlaege": None, "aufrufe": 1, "unterfach": None}
    _vorschau_setzen(werbung, {**basis, "fach": "Werbung", "aufmerksamkeit": False,
                               "werbung_sicher": True})
    _vorschau_setzen(handeln, {**basis, "fach": "Rechnungen", "aufmerksamkeit": True,
                               "werbung_sicher": False})
    assert neu.anwenden() == 2
    z = _zeile(werbung)
    assert (z["aufmerksamkeit"], z["werbung_sicher"], z["einordnung_version"]) == (False, True, 3)
    z = _zeile(handeln)
    assert (z["aufmerksamkeit"], z["werbung_sicher"], z["einordnung_version"]) == (True, False, 3)


def test_anwenden_nachsehen_und_ungueltiges_paar_sind_aufmerksam(konto_id):
    nachsehen = _mail(konto_id, 1)
    ungueltig = _mail(konto_id, 2)
    basis = {"sensibel": False, "quelle": "modell", "begruendung": "b", "vorschlaege": None,
             "aufrufe": 1, "unterfach": None, "aufmerksamkeit": False, "werbung_sicher": True}
    _vorschau_setzen(nachsehen, {**basis, "bereich": "privat", "fach": post_struktur.UNKLAR})
    _vorschau_setzen(ungueltig, {**basis, "bereich": "business", "fach": "Erfunden"})
    assert neu.anwenden() == 2
    for mid in (nachsehen, ungueltig):
        z = _zeile(mid)
        assert z["aufmerksamkeit"] is True and z["werbung_sicher"] is False


def test_anwenden_sensibel_ist_nie_werbung_sicher(konto_id):
    neu_sensibel = _mail(konto_id, 1)
    alt_sensibel = _mail(konto_id, 2, sensibel=True)
    basis = {"bereich": "privat", "fach": "Werbung", "unterfach": None, "quelle": "modell",
             "begruendung": "b", "vorschlaege": None, "aufrufe": 1, "aufmerksamkeit": False,
             "werbung_sicher": True}
    _vorschau_setzen(neu_sensibel, {**basis, "sensibel": True})
    _vorschau_setzen(alt_sensibel, {**basis, "sensibel": False})
    assert neu.anwenden() == 2
    for mid in (neu_sensibel, alt_sensibel):
        assert _zeile(mid)["werbung_sicher"] is False


def test_anwenden_aeltere_vorschau_ohne_neue_schluessel_bleibt_sichtbar(konto_id):
    mid = _mail(konto_id, 1)
    _vorschau_setzen(mid, {"bereich": "privat", "fach": "Werbung", "unterfach": None,
                           "sensibel": False, "quelle": "modell", "begruendung": "b",
                           "vorschlaege": None, "aufrufe": 1})
    assert neu.anwenden() == 1
    z = _zeile(mid)
    assert z["aufmerksamkeit"] is True and z["werbung_sicher"] is False


def test_anwenden_schlaegt_werberegel_je_absender_einmal_vor(monkeypatch, konto_id):
    aufrufe = []
    monkeypatch.setattr(post_werbung, "regel_vorschlagen",
                        lambda besitzer, von: aufrufe.append((besitzer, von)) or True)
    basis = {"bereich": "privat", "fach": "Werbung", "unterfach": None, "sensibel": False,
             "quelle": "modell", "begruendung": "b", "vorschlaege": None, "aufrufe": 1,
             "aufmerksamkeit": False}
    for uid in (1, 2):
        _vorschau_setzen(_mail(konto_id, uid, von="Shop <news@shop-test.example>"),
                         {**basis, "werbung_sicher": True})
    _vorschau_setzen(_mail(konto_id, 3, von="Andere <a@andere.example>"),
                     {**basis, "werbung_sicher": False})
    assert neu.anwenden() == 3
    assert aufrufe == [("felix", "Shop <news@shop-test.example>")]


def test_anwenden_bricht_bei_fehler_im_regelvorschlag_nicht_ab(monkeypatch, konto_id):
    def kaputt(besitzer, von):
        raise RuntimeError("Zeile mit Mailinhalt GEHEIM")
    monkeypatch.setattr(post_werbung, "regel_vorschlagen", kaputt)
    mid = _mail(konto_id, 1)
    _vorschau_setzen(mid, {"bereich": "privat", "fach": "Werbung", "unterfach": None,
                           "sensibel": False, "quelle": "modell", "begruendung": "b",
                           "vorschlaege": None, "aufrufe": 1, "aufmerksamkeit": False,
                           "werbung_sicher": True})
    assert neu.anwenden() == 1
    assert _zeile(mid)["werbung_sicher"] is True


def test_je_konto_argument_wird_durchgereicht(monkeypatch, capsys):
    """Die Befehlszeile (deploy/post-neu-einordnen.sh reicht alle Argumente durch)."""
    gesehen = []
    monkeypatch.setattr(neu, "vorschau", lambda g, a=False, j=None: gesehen.append((g, a, j)) or 0)
    monkeypatch.setattr(neu, "bericht", lambda: {"alt": {}, "neu": {}, "zum_nachsehen": 0,
                                                 "offen": 0, "katalog": [], "ohne_katalog": [],
                                                 "unklar_anteil": {}})
    assert neu.main(["vorschau", "--je-konto", "50"]) == 0
    assert gesehen == [(1000, False, 50)]
    skript = (Path(__file__).resolve().parents[2] / "deploy" / "post-neu-einordnen.sh").read_text(
        encoding="utf-8")
    assert "--je-konto N" in skript and '"$@"' in skript
