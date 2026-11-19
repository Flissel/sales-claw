"""Taktgeber-Schritt `kurs`: Kursmitschrift, Zuordnung, Fortschreiben, Ausgabe, Bestand.
KI (ollama.chat) und sales-auge sind ersetzt. Datenbank sales_test."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kurs_handbuch as kh  # noqa: E402
import kurs_mitschrift as km  # noqa: E402
import kurs_pdf  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402
import termin_takt  # noqa: E402

JETZT = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
TAG = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
ECHT_CHAT = ollama.chat                     # vor jedem Ersetzen: zaehlt die KI-Auftraege
_zaehler = [0]
_LEADS: list[str] = []


class KI:
    def __init__(self):
        self.n = 0
        self.kurs = 0
        self.zeiten: list = []

    def chat(self, system, nutzer, **kw):
        self.n += 1
        self.zeiten.append(kw.get("timeout_s"))
        eingabe = json.loads(nutzer)
        if system == km.KURS_SYSTEM:
            self.kurs += 1
            return json.dumps({"ueberblick": "Du lernst den Kalender.", "offen": ["x"],
                               "abschnitte": [
                                   {"titel": "Termin anlegen", "bilder": [], "merken": ["a"]},
                                   {"titel": "Serien", "bilder": [], "merken": ["b"]}]})
        if system == kh.ZUORDNUNG_SYSTEM:
            return json.dumps({"zuordnung": [
                {"abschnitt": a["abschnitt"], "entscheidung": "neu", "kapitel_id": None,
                 "titel": a["titel"]} for a in eingabe["abschnitte"]]})
        if system == kh.KAPITEL_SYSTEM:
            neu = "\n\n".join(f"Neu: {a['titel']}" for a in eingabe["neue_abschnitte"])
            alt = eingabe["alter_text"]
            return json.dumps({"text_md": (alt + "\n\n" if alt else "") + neu, "bild_ids": []})
        raise AssertionError("unbekannter Auftrag")


@pytest.fixture
def ki(monkeypatch):
    k = KI()
    monkeypatch.setattr(ollama, "chat", k.chat)
    return k


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGE_URL", "http://auge.invalid:8790")
    ziel = tmp_path / "ablage"
    ziel.mkdir()
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(ziel))
    monkeypatch.setattr(termin_takt, "_zustand", {})
    monkeypatch.setattr(termin_takt, "_kurs_pause", {}, raising=False)
    monkeypatch.setattr(ollama, "erreichbar", lambda: True)
    monkeypatch.setattr(kurs_pdf, "pdf_aus_html", lambda html: b"%PDF-1.7 test")
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    _LEADS.clear()
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    for lid in _LEADS:
        server._q("delete from leads where id = %s returning id", (lid,))


def _lead(name="Anna Lernend"):
    _zaehler[0] += 1
    lid = str(server._q(
        "insert into leads (name, phone, source, consent_status) "
        "values (%s, %s, 'whatsapp', 'existing_customer') returning id",
        (name, f"+4917088{_zaehler[0]:05d}"))[0]["id"])
    _LEADS.append(lid)
    return lid


def _sitzung(uid, beginn=TAG, rubrik="Kurse", lead=None, kurs_json=False, **spalten):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs Kalender', 'fertig') returning uid",
              (uid, beginn, beginn + timedelta(hours=1)))
    werte = {"uid": uid, "segmente": json.dumps([{"text": "hallo"}]),
             "auswertung_status": "fertig", "auswertung_am": beginn, "rubrik": rubrik,
             "bericht_pfad": f"{rubrik}/{uid[:8]}.html", "kurs_lead_id": lead,
             "geholt_am": beginn, **spalten}
    if kurs_json:
        werte["kurs_json"] = json.dumps({"ueberblick": "u", "offen": [], "abschnitte": [
            {"titel": kurs_json if isinstance(kurs_json, str) else "Termin anlegen",
             "bilder": [], "merken": []}]})
    namen = list(werte)
    marken = ["%s::jsonb" if n in ("segmente", "kurs_json") else "%s" for n in namen]
    server._q(f"insert into termin_mitschriften ({', '.join(namen)}) values "
              f"({', '.join(marken)}) returning id", [werte[n] for n in namen])
    if kurs_json:
        server._q("update termin_mitschriften set kurs_stand = %s where uid = %s returning id",
                  (km.kurs_stand(uid), uid))


def _z(uid):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def _drafts():
    return server._q("select count(*) as n from drafts")[0]["n"]


def _runden(n, start=JETZT):
    for i in range(n):
        termin_takt._kurs(start + timedelta(minutes=i))


def test_hoechstens_ein_ki_auftrag_je_runde(ki):
    _sitzung("k-1")
    _sitzung("k-2", beginn=TAG + timedelta(days=1))
    termin_takt._kurs(JETZT)
    assert ki.n == 1
    assert _z("k-1")["kurs_status"] == "fertig"
    assert _z("k-2")["kurs_json"] is None
    assert ki.zeiten == [km.KURS_KI_TIMEOUT_S] == [600]


def test_kein_ki_wenn_termin_ansteht(ki):
    _sitzung("k-1")
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status, link) "
              "values ('bald', 'sales-claw', %s, %s, 'Bald', 'geplant', 'https://x.test/m') "
              "returning uid", (JETZT + timedelta(minutes=5), JETZT + timedelta(hours=1)))
    termin_takt._kurs(JETZT)
    assert ki.n == 0


def test_kein_ki_ohne_ollama(ki, monkeypatch):
    _sitzung("k-1")
    monkeypatch.setattr(ollama, "erreichbar", lambda: False)
    termin_takt._kurs(JETZT)
    assert ki.n == 0


def test_ablage_nicht_beschreibbar_nichts(ki, monkeypatch, tmp_path):
    _sitzung("k-1")
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(tmp_path / "gibt-es-nicht"))
    assert termin_takt._kurs(JETZT) == 0
    assert ki.n == 0


def test_ohne_lernenden_nur_kursmitschrift(ki):
    _sitzung("k-1")
    _runden(5)
    z = _z("k-1")
    assert z["kurs_status"] == "fertig" and z["kurs_pfad"] and z["kurs_pdf"]
    assert ki.n == 1
    assert not server._q("select 1 from kurs_handbuch_quelle")


def test_bestand_zwei_sitzungen_ein_handbuch(ki):
    diana = _lead("diana-fixture")
    _sitzung("k-frueh", beginn=TAG, lead=diana)
    _sitzung("k-spaet", beginn=TAG + timedelta(hours=6), lead=diana)
    _runden(30)
    assert len(server._q("select 1 from kurs_handbuch where lead_id = %s", (diana,))) == 1
    quellen = server._q("select uid, eingearbeitet_am from kurs_handbuch_quelle "
                        "where lead_id = %s order by beginn", (diana,))
    assert [q["uid"] for q in quellen] == ["k-frueh", "k-spaet"]
    assert all(q["eingearbeitet_am"] for q in quellen)
    assert set(ki.zeiten) == {600}
    h = server._q("select pfad, pdf from kurs_handbuch where lead_id = %s", (diana,))[0]
    ordner = os.environ["MITSCHRIFTEN_PFAD"]
    assert os.path.isfile(os.path.join(ordner, h["pfad"]))
    assert h["pdf"].endswith(".pdf") and os.path.isfile(os.path.join(ordner, h["pdf"]))


def test_aelteste_sitzung_zuerst_zugeordnet(ki):
    lead = _lead()
    _sitzung("k-spaet", beginn=TAG + timedelta(days=2), lead=lead, kurs_json=True,
             kurs_status="fertig")
    _sitzung("k-frueh", beginn=TAG, lead=lead, kurs_json=True, kurs_status="fertig")
    termin_takt._kurs(JETZT)
    assert [q["uid"] for q in server._q("select uid from kurs_handbuch_quelle")] == ["k-frueh"]
    assert ki.n == 1


def test_fehler_sitzung_wird_uebersprungen(ki):
    _sitzung("k-fehler", kurs_status="fehler", kurs_versuche=3)
    _sitzung("k-ok", beginn=TAG + timedelta(days=1))
    termin_takt._kurs(JETZT)
    assert ki.n == 1
    assert _z("k-fehler")["kurs_json"] is None and _z("k-fehler")["kurs_status"] == "fehler"
    assert _z("k-ok")["kurs_status"] == "fertig"


def test_neuauswertung_baut_neu(ki):
    lead = _lead()
    _sitzung("k-1", lead=lead)
    _runden(15)
    assert _z("k-1")["kurs_stand"] == km.kurs_stand("k-1")
    assert ki.kurs == 1
    alt = _z("k-1")["kurs_pfad"]
    server._q("update termin_mitschriften set auswertung_am = %s, kurs_versuche = 2 "
              "where uid = 'k-1' returning id", (JETZT,))
    _runden(15, start=JETZT + timedelta(hours=1))
    z = _z("k-1")
    assert ki.kurs == 2
    assert z["kurs_stand"] == km.kurs_stand("k-1") and z["kurs_status"] == "fertig"
    assert z["kurs_versuche"] == 0 and z["kurs_pfad"] == alt
    q = server._q("select eingearbeitet_am from kurs_handbuch_quelle where uid = 'k-1'")
    assert len(q) == 1 and q[0]["eingearbeitet_am"]


def test_veraltet_ohne_ki_auch_bei_anderer_rubrik(ki, monkeypatch):
    # Kursdaten, aber Rubrik inzwischen "Vertrieb": ohne KI entfernen, Zaehler zuruecksetzen
    _sitzung("k-1", rubrik="Vertrieb", kurs_json=True, kurs_status="fertig",
             kurs_pfad="Kurse/x.html", kurs_versuche=2, kurs_am=JETZT)
    # nie verarbeitet: bleibt unangetastet
    _sitzung("k-2", rubrik="Vertrieb", kurs_versuche=2, kurs_am=JETZT)
    termin_takt._kurs(JETZT)
    z = _z("k-1")
    assert z["kurs_json"] is None and z["kurs_pfad"] is None and z["kurs_status"] is None
    assert z["kurs_stand"] is None and z["kurs_versuche"] == 0 and z["kurs_am"] is None
    z2 = _z("k-2")
    assert z2["kurs_versuche"] == 2 and z2["kurs_am"] == JETZT
    assert ki.n == 0


def test_nicht_kurs_rubrik_wird_ignoriert(ki):
    _sitzung("k-1", rubrik="Vertrieb")
    _runden(3)
    assert ki.n == 0 and _z("k-1")["kurs_json"] is None


def test_ablegen_ohne_ki_wenn_pdf_vorher_scheiterte(ki):
    _sitzung("k-1", kurs_json=True)           # kurs_json da, kurs_status leer
    termin_takt._kurs(JETZT)
    assert ki.n == 0
    assert _z("k-1")["kurs_status"] == "fertig"


def test_ablegen_fehler_pause_ohne_zaehlung(ki, monkeypatch):
    _sitzung("k-1", kurs_json=True)
    aufrufe = []

    def kaputt(uid):
        aufrufe.append(uid)
        raise kurs_pdf.PdfFehler("weg")

    monkeypatch.setattr(km, "ablegen", kaputt)
    _runden(3)
    assert len(aufrufe) == 1
    z = _z("k-1")
    assert z["kurs_status"] is None and z["kurs_versuche"] == 0


def test_veraltet_aus_zuordnen_ist_kein_fehler(ki, monkeypatch):
    lead = _lead()
    _sitzung("k-1", lead=lead, kurs_json=True, kurs_status="fertig")

    def veraltet(lead_id, uid):
        raise kh.Veraltet("weg")

    monkeypatch.setattr(kh, "zuordnen", veraltet)
    _runden(5)
    z = _z("k-1")
    assert z["kurs_status"] == "fertig" and z["kurs_versuche"] == 0
    assert termin_takt._kurs_pause == {}


def test_veraltet_aus_fortschreiben_ist_kein_fehler(ki, monkeypatch):
    lead = _lead()
    _sitzung("k-1", lead=lead, kurs_json=True, kurs_status="fertig")
    termin_takt._kurs(JETZT)                  # Zuordnung
    assert server._q("select 1 from kurs_handbuch_quelle")

    def veraltet(lead_id, uid, ziel):
        raise kh.Veraltet("weg")

    monkeypatch.setattr(kh, "fortschreiben", veraltet)
    _runden(5, start=JETZT + timedelta(hours=2))
    z = _z("k-1")
    assert z["kurs_status"] == "fertig" and z["kurs_versuche"] == 0
    assert termin_takt._kurs_pause == {}


def test_zuordnen_fehler_dreimal_wird_fehler(ki, monkeypatch):
    lead = _lead()
    _sitzung("k-1", lead=lead, kurs_json=True, kurs_status="fertig")

    def kaputt(lead_id, uid):
        raise ValueError("kaputt")

    monkeypatch.setattr(kh, "zuordnen", kaputt)
    termin_takt._kurs(JETZT)
    termin_takt._kurs(JETZT + timedelta(minutes=5))       # Pause: kein zweiter Versuch
    assert _z("k-1")["kurs_versuche"] == 1 and _z("k-1")["kurs_status"] == "fertig"
    termin_takt._kurs(JETZT + timedelta(hours=2))
    termin_takt._kurs(JETZT + timedelta(hours=4))
    assert _z("k-1")["kurs_status"] == "fehler"


def test_ausgabe_fehler_pause_kein_fehlerstatus(ki, monkeypatch):
    lead = _lead()
    _sitzung("k-1", lead=lead)
    _runden(10)
    assert server._q("select 1 from kurs_handbuch where lead_id = %s", (lead,))
    # neue Fassung faellig machen: Ausgabe soll erneut laufen und scheitern
    server._q("update kurs_handbuch set fassungen_stand = null where lead_id = %s "
              "returning lead_id", (lead,))
    aufrufe = []

    def kaputt(lead_id):
        aufrufe.append(lead_id)
        raise kurs_pdf.PdfFehler("weg")

    monkeypatch.setattr(kh, "ausgeben", kaputt)
    _runden(3, start=JETZT + timedelta(hours=1))
    assert len(aufrufe) == 1
    assert _z("k-1")["kurs_status"] == "fertig"


def test_keine_drafts_im_ganzen_ablauf(ki):
    vorher = _drafts()
    lead = _lead()
    _sitzung("k-1", lead=lead)
    _runden(20)
    assert server._q("select 1 from kurs_handbuch where lead_id = %s", (lead,))
    assert _drafts() == vorher


def test_logs_ohne_klartext(ki, caplog):
    import logging
    caplog.set_level(logging.INFO)
    lead = _lead("GEHEIMNAME-Lernende")
    _sitzung("k-1", lead=lead)
    _runden(15)
    assert "GEHEIMNAME" not in caplog.text and "Kalender" not in caplog.text


def _zwei_sitzungen(lead):
    """Zwei zugeordnete, noch nicht eingearbeitete Sitzungen (so stehen sie z. B. nach dem
    Rueckrollen fuer eine aeltere Sitzung da). Der Taktgeber ordnet eine zweite Sitzung erst
    zu, wenn die erste eingearbeitet ist (Final-Fix I1), daher hier direkt."""
    _sitzung("k-s1", beginn=TAG, lead=lead, kurs_json="Kapitel-Eins", kurs_status="fertig")
    _sitzung("k-s2", beginn=TAG + timedelta(days=1), lead=lead, kurs_json="Kapitel-Zwei",
             kurs_status="fertig")
    kh.zuordnen(lead, "k-s1")
    kh.zuordnen(lead, "k-s2")
    assert len(server._q("select 1 from kurs_handbuch_quelle")) == 2


def test_fortschreiben_fehler_pause_zaehlung_reihenfolge(ki, monkeypatch):
    lead = _lead()
    _zwei_sitzungen(lead)
    echt = kh.fortschreiben
    aufrufe = []

    def kaputt(lead_id, uid, ziel):
        aufrufe.append(uid)
        if uid == "k-s1":
            raise ValueError("kaputt")
        return echt(lead_id, uid, ziel)

    monkeypatch.setattr(kh, "fortschreiben", kaputt)
    t = JETZT + timedelta(minutes=10)
    termin_takt._kurs(t)
    termin_takt._kurs(t + timedelta(minutes=5))               # pausiert: S2 nicht vorgezogen
    assert aufrufe == ["k-s1"]
    assert _z("k-s1")["kurs_versuche"] == 1 and _z("k-s1")["kurs_status"] == "fertig"
    assert (str(lead), "k-s1") in termin_takt._kurs_pause


def test_fortschreiben_dreimal_fehler_handbuch_geht_ohne_sitzung_weiter(ki, monkeypatch):
    lead = _lead()
    _zwei_sitzungen(lead)
    echt = kh.fortschreiben

    def kaputt(lead_id, uid, ziel):
        if uid == "k-s1":
            raise ValueError("kaputt")
        return echt(lead_id, uid, ziel)

    monkeypatch.setattr(kh, "fortschreiben", kaputt)
    for i in range(3):
        termin_takt._kurs(JETZT + timedelta(hours=2 * (i + 1)))
    assert _z("k-s1")["kurs_status"] == "fehler"
    assert not server._q("select 1 from kurs_handbuch_quelle where uid = 'k-s1'")
    _runden(30, start=JETZT + timedelta(hours=10))
    h = server._q("select pfad, pdf from kurs_handbuch where lead_id = %s", (lead,))
    assert len(h) == 1
    text = open(os.path.join(os.environ["MITSCHRIFTEN_PFAD"], h[0]["pfad"]),
                encoding="utf-8").read()
    assert "Kapitel-Zwei" in text and "Kapitel-Eins" not in text
    assert not server._q("select 1 from kurs_handbuch_fassung where 'k-s1' = any(quellen)")
    assert _z("k-s2")["kurs_status"] == "fertig"


def test_fortschreiben_ueberspringt_fehler_sitzung(ki, monkeypatch):
    lead = _lead()
    _zwei_sitzungen(lead)
    server._q("update termin_mitschriften set kurs_status = 'fehler' where uid = 'k-s1' "
              "returning id")
    echt = kh.fortschreiben
    aufrufe = []
    monkeypatch.setattr(kh, "fortschreiben",
                        lambda l, u, z: aufrufe.append(u) or echt(l, u, z))
    termin_takt._kurs(JETZT + timedelta(minutes=10))
    assert aufrufe == ["k-s2"]


def test_erfolg_setzt_versuche_zurueck(ki):
    lead = _lead()
    _sitzung("k-1", lead=lead, kurs_json=True, kurs_status="fertig", kurs_versuche=2,
             kurs_am=JETZT - timedelta(hours=2))
    termin_takt._kurs(JETZT)
    z = _z("k-1")
    assert server._q("select 1 from kurs_handbuch_quelle")
    assert z["kurs_versuche"] == 0 and z["kurs_am"] is None


def test_gespeicherter_fehlversuch_wartet_auch_ohne_pause(ki):
    lead = _lead()
    _sitzung("k-1", lead=lead, kurs_json=True, kurs_status="fertig", kurs_versuche=1,
             kurs_am=JETZT - timedelta(minutes=5))
    termin_takt._kurs(JETZT)                        # nach "Neustart": keine In-Memory-Pause
    assert ki.n == 0
    termin_takt._kurs(JETZT + timedelta(hours=2))
    assert ki.n == 1


def test_zuordnen_wartende_aeltere_sitzung_zieht_keine_juengere_vor(ki):
    lead = _lead()
    _sitzung("k-alt", beginn=TAG, lead=lead, kurs_json=True, kurs_status="fertig",
             kurs_versuche=1, kurs_am=JETZT - timedelta(minutes=5))
    _sitzung("k-neu", beginn=TAG + timedelta(days=1), lead=lead, kurs_json=True,
             kurs_status="fertig")
    termin_takt._kurs(JETZT)
    assert ki.n == 0 and not server._q("select 1 from kurs_handbuch_quelle")


def test_ausgabe_faellig_fehler_stoppt_andere_lernende_nicht(ki, monkeypatch):
    a, b = sorted([_lead("A-fixture"), _lead("B-fixture")])
    _sitzung("k-a", lead=a)
    _sitzung("k-b", beginn=TAG + timedelta(hours=3), lead=b)
    echt = kh.ausgabe_faellig

    def kaputt(lead_id):
        if lead_id == a:
            raise RuntimeError("kaputt")
        return echt(lead_id)

    monkeypatch.setattr(kh, "ausgabe_faellig", kaputt)
    _runden(40)
    assert server._q("select 1 from kurs_handbuch where lead_id = %s", (b,))
    assert not server._q("select 1 from kurs_handbuch where lead_id = %s", (a,))


def test_erzeugen_dreimal_fehler_bleibt_fehler_bis_neuer_stand(ki, monkeypatch):
    _sitzung("k-1")

    def kaputt(system, nutzer, **kw):
        ki.n += 1
        raise RuntimeError("ki weg")
    monkeypatch.setattr(ollama, "chat", kaputt)
    for i in range(3):
        with pytest.raises(RuntimeError):
            km.erzeugen("k-1", JETZT + timedelta(hours=i))
    z = _z("k-1")
    assert z["kurs_status"] == "fehler" and z["kurs_json"] is None
    assert z["kurs_stand"] == km.kurs_stand("k-1")
    # unveraendert: bleibt Fehler ueber mehrere Runden, keine KI
    vorher = ki.n
    _runden(5, start=JETZT + timedelta(hours=5))
    assert ki.n == vorher
    z = _z("k-1")
    assert z["kurs_status"] == "fehler" and z["kurs_versuche"] == 3
    # neue Auswertung: naechste Runde setzt zurueck, Pfad (a) versucht es wieder
    monkeypatch.setattr(ollama, "chat", ki.chat)
    server._q("update termin_mitschriften set auswertung_am = %s where uid = 'k-1' "
              "returning id", (JETZT + timedelta(days=1),))
    termin_takt._kurs(JETZT + timedelta(days=1, hours=1))
    z = _z("k-1")
    assert ki.kurs == 1
    assert z["kurs_status"] == "fertig" and z["kurs_json"] is not None
    assert z["kurs_versuche"] == 0 and z["kurs_stand"] == km.kurs_stand("k-1")


# ---------- Final-Fix-Welle ----------

class KIThema(KI):
    """Zuordnung wie ein Modell, das die vorhandenen Kapitel liest: gleiches Thema ->
    "ergaenzen" in das vorhandene Kapitel, sonst "neu"."""

    def chat(self, system, nutzer, **kw):
        if system != kh.ZUORDNUNG_SYSTEM:
            return super().chat(system, nutzer, **kw)
        self.n += 1
        self.zeiten.append(kw.get("timeout_s"))
        eingabe = json.loads(nutzer)
        kapitel = {k["titel"]: k["kapitel_id"] for k in eingabe["kapitel"]}
        return json.dumps({"zuordnung": [
            {"abschnitt": a["abschnitt"], "entscheidung": "ergaenzen",
             "kapitel_id": kapitel[a["titel"]], "titel": None} if a["titel"] in kapitel else
            {"abschnitt": a["abschnitt"], "entscheidung": "neu", "kapitel_id": None,
             "titel": a["titel"]} for a in eingabe["abschnitte"]]})


def test_bestand_gleiches_thema_ein_kapitel(monkeypatch):
    # I1: zweite Sitzung erst zuordnen, wenn die erste eingearbeitet ist - sonst sieht die
    # KI das Kapitel noch nicht und legt ein paralleles an
    k = KIThema()
    monkeypatch.setattr(ollama, "chat", k.chat)
    lead = _lead()
    _sitzung("k-frueh", beginn=TAG, lead=lead, kurs_json=True, kurs_status="fertig")
    _sitzung("k-spaet", beginn=TAG + timedelta(days=1), lead=lead, kurs_json=True,
             kurs_status="fertig")
    _runden(10)
    kapitel = server._q(
        "select k.titel, f.quellen from kurs_handbuch_kapitel k "
        "join kurs_handbuch_fassung f on f.id = k.aktuelle_fassung where k.lead_id = %s",
        (lead,))
    assert [(z["titel"], list(z["quellen"])) for z in kapitel] == [
        ("Termin anlegen", ["k-frueh", "k-spaet"])]
    quellen = server._q("select eingearbeitet_am from kurs_handbuch_quelle where lead_id = %s",
                        (lead,))
    assert len(quellen) == 2 and all(q["eingearbeitet_am"] for q in quellen)
    assert server._q("select 1 from kurs_handbuch where lead_id = %s", (lead,))


def test_offene_quelle_haelt_nur_den_eigenen_lernenden_an(ki):
    # I1: Anna hat eine offene Quelle (wartet mit der Zuordnung von k-a2), Bert wird trotzdem
    # zugeordnet; danach wird Annas Kapitel fortgeschrieben (niemand verhungert)
    anna, bert = _lead("Anna-fixture"), _lead("Bert-fixture")
    _sitzung("k-a1", beginn=TAG, lead=anna, kurs_json=True, kurs_status="fertig")
    _sitzung("k-a2", beginn=TAG + timedelta(days=1), lead=anna, kurs_json=True,
             kurs_status="fertig")
    _sitzung("k-b1", beginn=TAG + timedelta(days=2), lead=bert, kurs_json=True,
             kurs_status="fertig")
    kh.zuordnen(anna, "k-a1")
    termin_takt._kurs(JETZT)
    assert sorted(q["uid"] for q in server._q("select uid from kurs_handbuch_quelle")) == [
        "k-a1", "k-b1"]
    _runden(20, start=JETZT + timedelta(minutes=1))
    quellen = server._q("select uid, eingearbeitet_am from kurs_handbuch_quelle order by uid")
    assert [q["uid"] for q in quellen] == ["k-a1", "k-a2", "k-b1"]
    assert all(q["eingearbeitet_am"] for q in quellen)


def _bald(beginn):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status, link) "
              "values ('bald', 'sales-claw', %s, %s, 'Bald', 'geplant', 'https://x.test/m') "
              "returning uid", (beginn, beginn + timedelta(hours=1)))


def test_ki_sperre_mit_frischer_uhrzeit(ki, monkeypatch):
    # I2: die Runde begann 20 Minuten vor dem Termin; bis zum Kurs-Schritt sind 10 Minuten
    # vergangen (Briefing, Auswertung) - jetzt beginnt der Termin in 10 Minuten
    _sitzung("k-1")
    _bald(JETZT + timedelta(minutes=20))
    monkeypatch.setattr(termin_takt, "_uhr", lambda: JETZT + timedelta(minutes=10),
                        raising=False)
    termin_takt._kurs(JETZT)
    assert ki.n == 0
    monkeypatch.setattr(termin_takt, "_uhr", lambda: JETZT, raising=False)
    termin_takt._kurs(JETZT)
    assert ki.n == 1


def test_kein_kurs_ki_wenn_die_runde_schon_ki_nutzte(ki, monkeypatch):
    # I2: ein frueherer Schritt der Runde (hier: Auswertung) hat die KI schon benutzt
    _sitzung("k-1")
    monkeypatch.setattr(ollama, "_anfrage",
                        lambda *a, **k: json.dumps({"message": {"content": "{}"}}).encode())

    def auswerten_mit_ki(jetzt):
        ECHT_CHAT("system", "nutzer")
        return 1

    monkeypatch.setattr(termin_takt, "SCHRITTE", (("auswerten", auswerten_mit_ki),
                                                  ("kurs", termin_takt._kurs)))
    termin_takt.runde(JETZT)
    assert ki.n == 0
    monkeypatch.setattr(termin_takt, "SCHRITTE", (("auswerten", lambda j: 0),
                                                  ("kurs", termin_takt._kurs)))
    termin_takt.runde(JETZT + timedelta(minutes=1))
    assert ki.n == 1


def test_pdf_wartet_wenn_termin_ansteht(ki, monkeypatch):
    # Minor 8: Ablegen (PDF) und Handbuch-Ausgabe nicht waehrend eines Termins mit Bot
    # (sales-auge druckt im selben Prozess, der den Bildschirm des Kurses aufnimmt)
    lead = _lead()
    _sitzung("k-1", kurs_json=True)                           # Ablegen faellig
    _sitzung("k-2", beginn=TAG + timedelta(days=1), lead=lead)
    _runden(15, start=JETZT - timedelta(days=1))
    assert _z("k-2")["kurs_status"] == "fertig"
    server._q("update termin_mitschriften set kurs_status = null where uid = 'k-1' "
              "returning id")
    server._q("update kurs_handbuch set fassungen_stand = null where lead_id = %s "
              "returning lead_id", (lead,))
    pdfs = []
    monkeypatch.setattr(kurs_pdf, "pdf_aus_html", lambda html: pdfs.append(1) or b"%PDF-1.7")
    _bald(JETZT + timedelta(minutes=20))
    monkeypatch.setattr(termin_takt, "_uhr", lambda: JETZT + timedelta(minutes=10),
                        raising=False)
    termin_takt._kurs(JETZT)
    assert pdfs == [] and _z("k-1")["kurs_status"] is None
    assert termin_takt._kurs_pause == {}                      # kein Fehlversuch
    monkeypatch.setattr(termin_takt, "_uhr", lambda: JETZT + timedelta(hours=3),
                        raising=False)
    _runden(2, start=JETZT + timedelta(hours=3))
    assert _z("k-1")["kurs_status"] == "fertig"
    assert server._q("select fassungen_stand from kurs_handbuch where lead_id = %s",
                     (lead,))[0]["fassungen_stand"] is not None


def _loeschantrag(lead):
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "%s, %s::jsonb, true) where id = %s returning id",
              ([server.LOESCH_SCHLUESSEL], json.dumps({"am": "2026-11-19", "quelle": "test"}),
               lead))


def test_kein_handbuch_fuer_lernenden_mit_loeschantrag(ki):
    # I3 (Verteidigung in der Tiefe): kurs_lead_id steht noch, der Kontakt hat aber einen
    # Loeschantrag - weder zuordnen noch fortschreiben noch ausgeben
    weg, da = _lead("Weg-fixture"), _lead("Da-fixture")
    _sitzung("k-weg", lead=weg, kurs_json=True, kurs_status="fertig")
    _sitzung("k-offen", beginn=TAG + timedelta(days=1), lead=weg, kurs_json=True,
             kurs_status="fertig")
    _sitzung("k-da", beginn=TAG + timedelta(days=2), lead=da, kurs_json=True,
             kurs_status="fertig")
    kh.zuordnen(weg, "k-weg")                 # offene Quelle (fortschreiben faellig)
    n = ki.n
    _loeschantrag(weg)
    _runden(15)
    assert ki.n - n > 0                       # Da wird bearbeitet
    assert server._q("select 1 from kurs_handbuch where lead_id = %s", (da,))
    assert [q["uid"] for q in server._q(
        "select uid from kurs_handbuch_quelle where lead_id = %s", (weg,))] == ["k-weg"]
    assert not server._q("select 1 from kurs_handbuch_kapitel where lead_id = %s", (weg,))
    assert not server._q("select 1 from kurs_handbuch where lead_id = %s", (weg,))


def test_keine_ausgabe_fuer_gesperrten_lernenden(ki, monkeypatch):
    # I3: Sperre (Verbotsliste) wie Loeschantrag - auch keine Ausgabe mehr
    import sperrliste
    lead = _lead()
    _sitzung("k-1", lead=lead, kurs_json=True, kurs_status="fertig")
    _runden(5)
    assert server._q("select 1 from kurs_handbuch where lead_id = %s", (lead,))
    server._q("update kurs_handbuch set fassungen_stand = null where lead_id = %s "
              "returning lead_id", (lead,))
    telefon = server._q("select phone from leads where id = %s", (lead,))[0]["phone"]
    kennung = sperrliste.kennung_tel(telefon)
    monkeypatch.setattr(sperrliste, "gesperrt",
                        lambda q, email="", phone="": "test: gesperrt"
                        if sperrliste.kennung_tel(phone) == kennung else None)
    aufrufe = []
    monkeypatch.setattr(kh, "ausgeben", lambda lid: aufrufe.append(lid))
    _runden(3, start=JETZT + timedelta(hours=1))
    assert aufrufe == []
