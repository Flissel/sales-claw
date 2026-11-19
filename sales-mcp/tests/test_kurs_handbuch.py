"""Kurs-Handbuch (B1): Zuordnen, Fortschreiben, Ausgabe. KI (ollama.chat) und sales-auge sind
ersetzt. Datenbank sales_test."""
import io
import itertools
import json
import logging
import os
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kurs_handbuch as kh  # noqa: E402
import kurs_mitschrift as km  # noqa: E402
import kurs_pdf  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402

UID1 = "kurs-handbuch-0001@sales-claw"
UID2 = "kurs-handbuch-0002@sales-claw"
UID3 = "kurs-handbuch-0003@sales-claw"
TAG1 = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
TAG2 = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
TAG0 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
_nr = itertools.count(1)
_LEADS: list[str] = []


class _Antwort:
    def __init__(self, status, daten):
        self.status = status
        self._daten = daten

    def read(self):
        return self._daten

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGE_URL", "http://auge.invalid:8790")
    ziel = tmp_path / "ablage"
    ziel.mkdir()
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(ziel))
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    _LEADS.clear()
    yield
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    for lid in _LEADS:
        server._q("delete from leads where id = %s returning id", (lid,))


@pytest.fixture
def ablage(tmp_path):
    return tmp_path / "ablage"


@pytest.fixture
def auge_liefert_pdf(monkeypatch):
    def falsch(anfrage, timeout=None):
        return _Antwort(200, b"%PDF-1.7 test")

    monkeypatch.setattr(kurs_pdf.urllib.request, "urlopen", falsch)


@pytest.fixture
def auge_antwortet_503(monkeypatch):
    def falsch(anfrage, timeout=None):
        raise urllib.error.HTTPError(anfrage.full_url, 503, "weg", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(kurs_pdf.urllib.request, "urlopen", falsch)


def _lead(name="Anna Lernend"):
    lid = str(server._q(
        "insert into leads (name, phone, source, consent_status) "
        "values (%s, %s, 'whatsapp', 'existing_customer') returning id",
        (name, f"+4917099{next(_nr):05d}"))[0]["id"])
    _LEADS.append(lid)
    return lid


@pytest.fixture
def lernender():
    return _lead()


@pytest.fixture
def lernender_b():
    return _lead("Berta Fremd")


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (1600, 900), (200, 10, 10)).save(out, "JPEG")
    return out.getvalue()


def _bild(uid, tag, minute, status="fertig"):
    z = server._q(
        "insert into termin_bilder (uid, aufgenommen_am, bild, breite, hoehe, dhash, "
        "beschreibung, beschreibung_status) values (%s, %s, %s, 1600, 900, %s, 'Folie', %s) "
        "returning id", (uid, tag + timedelta(minutes=minute), _jpeg(), next(_nr), status))
    return str(z[0]["id"])


def _abschnitt(titel, bilder=(), merken="Das merken."):
    return {"titel": titel,
            "bilder": [{"bild_id": b, "zu_sehen": "Eine Folie", "erklaert": "Felix erklaert.",
                        "schritte": ["Klick auf Neu"]} for b in bilder],
            "merken": [merken]}


def _sitzung(uid, beginn, abschnitte, bilder=0, status="fertig"):
    """Kurs-Mitschrift mit kurs_json; die Abschnitte bekommen der Reihe nach `bilder` Bilder
    (nur fuer den ersten Abschnitt, falls angegeben). Gibt die Bild-Ids zurueck."""
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs Kalender', 'fertig') returning uid",
              (uid, beginn, beginn + timedelta(hours=1)))
    ids = [_bild(uid, beginn, m) for m in range(1, bilder + 1)]
    ab = [dict(a) for a in abschnitte]
    if ids and ab:
        ab[0] = _abschnitt(ab[0]["titel"], ids)
    kj = {"ueberblick": "Du lernst den Kalender.", "abschnitte": ab,
          "offen": ["GEHEIM-OFFEN Diana fragte nach Serien"]}
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_am, rubrik, kurs_json, kurs_status) "
              "values (%s, %s::jsonb, 'fertig', '{}'::jsonb, now(), 'Kurse', %s::jsonb, %s) "
              "returning id", (uid, json.dumps([{"text": "GEHEIM-ROHTRANSKRIPT"}]),
                               json.dumps(kj), status))
    km_stand = km.kurs_stand(uid)
    server._q("update termin_mitschriften set kurs_stand = %s where uid = %s returning id",
              (km_stand, uid))
    return ids



class KI:
    def __init__(self):
        self.aufrufe: list[tuple[str, dict]] = []
        self.zuordnung = lambda e: {"zuordnung": [
            {"abschnitt": a["abschnitt"], "entscheidung": "neu", "kapitel_id": None,
             "titel": a["titel"]} for a in e["abschnitte"]]}
        self.kapitel = self._text

    @staticmethod
    def _text(e):
        bilder = list(e.get("bild_ids_alt", []))
        for a in e["neue_abschnitte"]:
            bilder += [b["bild_id"] for b in a["bilder"]]
        neu = "\n\n".join(f"Neu: {a['titel']}" for a in e["neue_abschnitte"])
        alt = e["alter_text"]
        return {"text_md": (alt + "\n\n" if alt else "") + neu, "bild_ids": bilder}

    def chat(self, system, nutzer, **kw):
        assert kw.get("als_json") is True
        eingabe = json.loads(nutzer)
        self.aufrufe.append((system, eingabe))
        if system == kh.ZUORDNUNG_SYSTEM:
            antwort = self.zuordnung(eingabe)
        elif system == kh.KAPITEL_SYSTEM:
            antwort = self.kapitel(eingabe)
        else:
            raise AssertionError("unbekannter Auftrag")
        return antwort if isinstance(antwort, str) else json.dumps(antwort)


@pytest.fixture
def ki(monkeypatch):
    k = KI()
    monkeypatch.setattr(ollama, "chat", k.chat)
    return k


def _kapitel_id(lead, titel):
    z = server._q("select id from kurs_handbuch_kapitel where lead_id = %s and titel = %s",
                  (lead, titel))
    return str(z[0]["id"])


def _kapitel_titel(lead):
    return [z["titel"] for z in server._q(
        "select titel from kurs_handbuch_kapitel where lead_id = %s order by reihenfolge",
        (lead,))]


def _aktuell(lead, titel):
    return server._q(
        "select f.* from kurs_handbuch_kapitel k join kurs_handbuch_fassung f "
        "on f.id = k.aktuelle_fassung where k.lead_id = %s and k.titel = %s",
        (lead, titel))[0]


def _texte(lead):
    return {t: _aktuell(lead, t)["text_md"] for t in _kapitel_titel(lead)}


def _fassungen(lead, titel):
    return server._q(
        "select f.* from kurs_handbuch_fassung f join kurs_handbuch_kapitel k "
        "on k.id = f.kapitel_id where k.lead_id = %s and k.titel = %s "
        "order by f.erstellt_am", (lead, titel))


def _einarbeiten(lead):
    for uid, ziel in kh.offene_auftraege(lead):
        kh.fortschreiben(lead, uid, ziel)


def _zuordnen(lead, uid):
    """Wie der Taktgeber: nur fuer den gewaehlten Lernenden (zuordnen prueft das)."""
    server._q("update termin_mitschriften set kurs_lead_id = %s where uid = %s returning uid",
              (lead, uid))
    return kh.zuordnen(lead, uid)


@pytest.fixture
def sitzung1():
    return _sitzung(UID1, TAG1, [_abschnitt("Termin anlegen"), _abschnitt("Kontakt suchen")])


@pytest.fixture
def handbuch_nach_sitzung1(lernender, sitzung1, ki):
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)


def test_konstanten():
    assert kh.MAX_BILDER_KAPITEL == 3
    assert kh.ORDNER_NAME == "_handbuecher"
    for s in (kh.ZUORDNUNG_SYSTEM, kh.KAPITEL_SYSTEM):
        assert any(c in s for c in "äöüß")


def test_erste_sitzung_legt_kapitel_an(lernender, sitzung1, ki):
    _zuordnen(lernender, UID1)
    q = server._q("select * from kurs_handbuch_quelle where lead_id = %s", (lernender,))[0]
    assert q["uid"] == UID1 and q["eingearbeitet_am"] is None
    assert q["stand"] == km.kurs_stand(UID1) and q["beginn"] == TAG1
    assert kh.offene_auftraege(lernender) == [(UID1, "neu:0"), (UID1, "neu:1")]
    _einarbeiten(lernender)
    assert _kapitel_titel(lernender) == ["Termin anlegen", "Kontakt suchen"]
    assert not kh.offene_auftraege(lernender)
    q = server._q("select * from kurs_handbuch_quelle where lead_id = %s", (lernender,))[0]
    assert q["eingearbeitet_am"] is not None
    f = _aktuell(lernender, "Termin anlegen")
    assert f["quellen"] == [UID1] and "Neu: Termin anlegen" in f["text_md"]
    reihenfolge = [z["reihenfolge"] for z in server._q(
        "select reihenfolge from kurs_handbuch_kapitel where lead_id = %s order by reihenfolge",
        (lernender,))]
    assert reihenfolge == [1, 2]


def test_zuordnung_eingabe_enthaelt_kapitel_kurz_und_datum(lernender, handbuch_nach_sitzung1,
                                                            ki):
    _sitzung(UID2, TAG2, [_abschnitt("Mehr zum Termin")])
    _zuordnen(lernender, UID2)
    system, e = ki.aufrufe[-1]
    assert system == kh.ZUORDNUNG_SYSTEM
    kap = {k["titel"]: k for k in e["kapitel"]}
    assert set(kap) == {"Termin anlegen", "Kontakt suchen"}
    assert kap["Termin anlegen"]["kapitel_id"] == _kapitel_id(lernender, "Termin anlegen")
    assert len(kap["Termin anlegen"]["kurz"]) <= 400
    assert kap["Termin anlegen"]["juengste_quelle"].startswith("2026-11-14")
    assert [a["abschnitt"] for a in e["abschnitte"]] == [0]
    assert "2026-11-18" in e["datum"]


def test_ergaenzen_aendert_nur_betroffenes_kapitel(lernender, handbuch_nach_sitzung1, ki):
    vorher = _texte(lernender)
    _sitzung(UID2, TAG2, [_abschnitt("Termin mit Serie")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID2)
    assert kh.offene_auftraege(lernender) == [(UID2, kid)]
    assert kh.fortschreiben(lernender, UID2, kid) == kid
    nachher = _texte(lernender)
    assert nachher["Kontakt suchen"] == vorher["Kontakt suchen"]
    assert nachher["Termin anlegen"] != vorher["Termin anlegen"]
    assert nachher["Termin anlegen"].startswith(vorher["Termin anlegen"])
    assert len(_fassungen(lernender, "Termin anlegen")) == 2
    assert len(_fassungen(lernender, "Kontakt suchen")) == 1
    assert _aktuell(lernender, "Termin anlegen")["quellen"] == [UID1, UID2]
    # Eingabe des Kapitel-Auftrags: alter Text wortgleich, Entscheidung und Abschnitt
    system, e = ki.aufrufe[-1]
    assert system == kh.KAPITEL_SYSTEM
    assert e["alter_text"] == vorher["Termin anlegen"]
    assert [a["entscheidung"] for a in e["neue_abschnitte"]] == ["ergaenzen"]
    assert not kh.offene_auftraege(lernender)


def test_kapitel_eines_anderen_lernenden_wird_abgewiesen(lernender, lernender_b, ki):
    _sitzung(UID1, TAG1, [_abschnitt("Termin anlegen")])
    _sitzung(UID2, TAG2, [_abschnitt("Anderes")])
    _zuordnen(lernender_b, UID2)
    _einarbeiten(lernender_b)
    fremd = _kapitel_id(lernender_b, "Anderes")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": fremd, "titel": None}]}
    with pytest.raises(ValueError):
        _zuordnen(lernender, UID1)
    assert not server._q("select 1 from kurs_handbuch_quelle where lead_id = %s", (lernender,))


@pytest.mark.parametrize("antwort", [
    "Das ist kein JSON",
    {"zuordnung": "nein"},
    {"zuordnung": [{"abschnitt": 7, "entscheidung": "neu", "kapitel_id": None, "titel": "X"}]},
    {"zuordnung": [{"abschnitt": 0, "entscheidung": "loeschen", "kapitel_id": None,
                    "titel": "X"}]},
    {"zuordnung": [{"abschnitt": 0, "entscheidung": "neu", "kapitel_id": None, "titel": "X"},
                   {"abschnitt": 0, "entscheidung": "neu", "kapitel_id": None, "titel": "Y"}]},
    {"zuordnung": [{"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": "kein-uuid",
                    "titel": None}]},
])
def test_ungueltige_zuordnung_wird_abgewiesen(lernender, ki, antwort):
    _sitzung(UID1, TAG1, [_abschnitt("Termin anlegen")])
    ki.zuordnung = lambda e: antwort
    with pytest.raises(ValueError):
        _zuordnen(lernender, UID1)
    assert not server._q("select 1 from kurs_handbuch_quelle where lead_id = %s", (lernender,))


def test_fehlender_abschnitt_wird_neues_kapitel(lernender, ki):
    _sitzung(UID1, TAG1, [_abschnitt("Eins"), _abschnitt("Zwei")])
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 1, "entscheidung": "neu", "kapitel_id": None, "titel": "Zwei neu"}]}
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)
    assert sorted(_kapitel_titel(lernender)) == ["Eins", "Zwei neu"]


def test_ersetzen_durch_juengere_sitzung_bleibt_ersetzen(lernender, handbuch_nach_sitzung1, ki):
    _sitzung(UID2, TAG2, [_abschnitt("Termin neu erklaert")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ersetzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID2)
    z = server._q("select zuordnung from kurs_handbuch_quelle where uid = %s", (UID2,))[0]
    assert z["zuordnung"][0]["entscheidung"] == "ersetzen"
    kh.fortschreiben(lernender, UID2, kid)
    assert ki.aufrufe[-1][1]["neue_abschnitte"][0]["entscheidung"] == "ersetzen"


def test_ersetzen_durch_aeltere_sitzung_wird_ergaenzen(lernender, handbuch_nach_sitzung1, ki):
    _sitzung(UID3, TAG0, [_abschnitt("Aelterer Stoff")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ersetzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID3)
    z = server._q("select zuordnung from kurs_handbuch_quelle where uid = %s", (UID3,))[0]
    assert z["zuordnung"][0]["entscheidung"] == "ergaenzen"
    assert z["zuordnung"][0]["kapitel_id"] == kid


def test_ersetzen_gleichzeitige_sitzung_wird_ergaenzen(lernender, handbuch_nach_sitzung1, ki):
    _sitzung(UID3, TAG1, [_abschnitt("Gleicher Tag")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ersetzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID3)
    z = server._q("select zuordnung from kurs_handbuch_quelle where uid = %s", (UID3,))[0]
    assert z["zuordnung"][0]["entscheidung"] == "ergaenzen"


def test_offene_auftraege_in_datumsfolge(lernender, ki):
    _sitzung(UID2, TAG2, [_abschnitt("Spaeter")])
    _sitzung(UID1, TAG1, [_abschnitt("Frueher")])
    _zuordnen(lernender, UID2)
    _zuordnen(lernender, UID1)
    assert kh.offene_auftraege(lernender) == [(UID1, "neu:0"), (UID2, "neu:0")]


def test_zwei_abschnitte_ein_kapitel_ein_auftrag(lernender, handbuch_nach_sitzung1, ki):
    _sitzung(UID2, TAG2, [_abschnitt("A"), _abschnitt("B"), _abschnitt("C")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": kid, "titel": None},
        {"abschnitt": 1, "entscheidung": "ergaenzen", "kapitel_id": kid, "titel": None},
        {"abschnitt": 2, "entscheidung": "neu", "kapitel_id": None, "titel": "C-Kapitel"}]}
    _zuordnen(lernender, UID2)
    assert kh.offene_auftraege(lernender) == [(UID2, kid), (UID2, "neu:2")]
    kh.fortschreiben(lernender, UID2, kid)
    q = server._q("select eingearbeitet_am from kurs_handbuch_quelle where uid = %s", (UID2,))
    assert q[0]["eingearbeitet_am"] is None     # "neu:2" fehlt noch
    assert [a["abschnitt"] for a in ki.aufrufe[-1][1]["neue_abschnitte"]] == [0, 1]
    kh.fortschreiben(lernender, UID2, "neu:2")
    q = server._q("select eingearbeitet_am from kurs_handbuch_quelle where uid = %s", (UID2,))
    assert q[0]["eingearbeitet_am"] is not None
    assert _kapitel_titel(lernender) == ["Termin anlegen", "Kontakt suchen", "C-Kapitel"]


def test_hoechstens_drei_bilder_je_kapitel(lernender, ki):
    ids = _sitzung(UID1, TAG1, [_abschnitt("Termin anlegen")], bilder=5)
    ungeprueft = _bild(UID1, TAG1, 9, status="offen")
    ki.kapitel = lambda e: {"text_md": "Text", "bild_ids": ids + [ungeprueft, "erfunden"]}
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)
    gewaehlt = _aktuell(lernender, "Termin anlegen")["bild_ids"]
    assert len(gewaehlt) <= 3
    assert gewaehlt == ids[-3:]                 # die juengsten, geprueft
    assert ungeprueft not in gewaehlt and "erfunden" not in gewaehlt


def test_bild_ids_aus_alter_sitzung_bleiben_moeglich(lernender, ki):
    ids1 = _sitzung(UID1, TAG1, [_abschnitt("Termin anlegen")], bilder=2)
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)
    ids2 = _sitzung(UID2, TAG2, [_abschnitt("Mehr")], bilder=2)
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID2)
    kh.fortschreiben(lernender, UID2, kid)
    # KI-Standard: alte + neue Ids; 4 Ids -> die 3 juengsten (Sitzung 1: letztes, Sitzung 2: beide)
    assert _aktuell(lernender, "Termin anlegen")["bild_ids"] == [ids1[-1]] + ids2


def test_ungueltige_kapitel_antwort_speichert_nichts(lernender, handbuch_nach_sitzung1, ki):
    _sitzung(UID2, TAG2, [_abschnitt("Mehr")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID2)
    for schlecht in ("kein json", {"text_md": ""}, {"text_md": "x", "bild_ids": "a"}, [1]):
        ki.kapitel = lambda e, s=schlecht: s
        with pytest.raises(ValueError):
            kh.fortschreiben(lernender, UID2, kid)
    assert len(_fassungen(lernender, "Termin anlegen")) == 1
    q = server._q("select eingearbeitet_am from kurs_handbuch_quelle where uid = %s", (UID2,))
    assert q[0]["eingearbeitet_am"] is None
    assert kh.offene_auftraege(lernender) == [(UID2, kid)]


def test_fortschreiben_neues_kapitel_schlaegt_fehl_ohne_kapitel(lernender, sitzung1, ki):
    _zuordnen(lernender, UID1)
    ki.kapitel = lambda e: "kein json"
    with pytest.raises(ValueError):
        kh.fortschreiben(lernender, UID1, "neu:0")
    assert _kapitel_titel(lernender) == []


def test_fortschreiben_fremdes_oder_unbekanntes_ziel(lernender, lernender_b, sitzung1, ki):
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)
    fremd = _kapitel_id(lernender, "Termin anlegen")
    _sitzung(UID2, TAG2, [_abschnitt("Anderes")])
    _zuordnen(lernender_b, UID2)
    with pytest.raises(ValueError):
        kh.fortschreiben(lernender_b, UID2, fremd)
    with pytest.raises(ValueError):
        kh.fortschreiben(lernender_b, UID2, "neu:5")
    with pytest.raises(ValueError):
        kh.fortschreiben(lernender_b, UID1, "neu:0")


def test_handbuch_html_ohne_offen_mit_quellen(lernender, handbuch_nach_sitzung1):
    h = kh.handbuch_html(lernender)
    assert "aus Sitzung" in h and "14.11.2026" in h
    assert "Stand:" in h and "1 Sitzung" in h
    assert "Offen" not in h and "GEHEIM" not in h
    assert 'href="#k1"' in h and 'id="k1"' in h and "Inhalt" in h
    assert h.index("Termin anlegen") < h.index("Kontakt suchen")


def test_handbuch_html_zaehlt_sitzungen_und_folgt_reihenfolge(lernender,
                                                               handbuch_nach_sitzung1, ki):
    _sitzung(UID2, TAG2, [_abschnitt("Mehr")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID2)
    kh.fortschreiben(lernender, UID2, kid)
    server._q("update kurs_handbuch_kapitel set reihenfolge = 9 where id = %s returning id",
              (kid,))
    h = kh.handbuch_html(lernender)
    assert "2 Sitzungen" in h
    assert "14.11.2026, 18.11.2026" in h or ("14.11.2026" in h and "18.11.2026" in h)
    assert h.index("Kontakt suchen") < h.index("Termin anlegen")


def test_handbuch_html_escaped_text_und_bild(lernender, ki):
    ids = _sitzung(UID1, TAG1, [_abschnitt("<b>Termin</b>")], bilder=1)
    ki.kapitel = lambda e: {"text_md": "## Schritte\n\n1. Klick <script>x()</script>\n2. Weiter"
                                       "\n\n- **fett** Punkt", "bild_ids": ids}
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)
    h = kh.handbuch_html(lernender)
    assert "<script>" not in h and "&lt;script&gt;" in h
    assert "<b>Termin</b>" not in h
    assert "data:image/jpeg;base64," in h
    assert "<ol>" in h and "<ul>" in h and "<strong>fett</strong>" in h


def test_ausgeben_schreibt_html_und_pdf(lernender, handbuch_nach_sitzung1, ablage,
                                        auge_liefert_pdf):
    assert kh.ausgabe_faellig(lernender)
    kh.ausgeben(lernender)
    z = server._q("select * from kurs_handbuch where lead_id = %s", (lernender,))[0]
    assert z["pfad"] == f"_handbuecher/handbuch-{lernender[:8]}.html"
    assert z["pdf"] == f"_handbuecher/handbuch-{lernender[:8]}.pdf"
    assert (ablage / z["pfad"]).exists() and (ablage / z["pdf"]).exists()
    assert (ablage / z["pdf"]).read_bytes().startswith(b"%PDF")
    assert "Termin anlegen" in (ablage / z["pfad"]).read_text(encoding="utf-8")
    assert z["stand_am"] is not None
    jung = server._q("select max(f.erstellt_am) m from kurs_handbuch_fassung f join "
                     "kurs_handbuch_kapitel k on k.id = f.kapitel_id where k.lead_id = %s",
                     (lernender,))[0]["m"]
    assert z["fassungen_stand"] == jung
    assert not kh.ausgabe_faellig(lernender)


def test_ausgabe_faellig_nach_neuer_fassung_und_umbenennung(lernender, handbuch_nach_sitzung1,
                                                            auge_liefert_pdf, ki):
    kh.ausgeben(lernender)
    _sitzung(UID2, TAG2, [_abschnitt("Mehr")])
    kid = _kapitel_id(lernender, "Termin anlegen")
    ki.zuordnung = lambda e: {"zuordnung": [
        {"abschnitt": 0, "entscheidung": "ergaenzen", "kapitel_id": kid, "titel": None}]}
    _zuordnen(lernender, UID2)
    assert not kh.ausgabe_faellig(lernender)       # offener Auftrag: erst fortschreiben
    kh.fortschreiben(lernender, UID2, kid)
    assert kh.ausgabe_faellig(lernender)
    kh.ausgeben(lernender)
    assert not kh.ausgabe_faellig(lernender)
    server._q("update kurs_handbuch set fassungen_stand = null where lead_id = %s "
              "returning lead_id", (lernender,))
    assert kh.ausgabe_faellig(lernender)


def test_ausgeben_ohne_pdf_schreibt_nichts(lernender, handbuch_nach_sitzung1, ablage,
                                           auge_antwortet_503):
    server._q("insert into kurs_handbuch (lead_id, pfad, pdf, stand_am, fassungen_stand) "
              "values (%s, 'alt.html', 'alt.pdf', now(), null) returning lead_id", (lernender,))
    with pytest.raises(kurs_pdf.PdfFehler):
        kh.ausgeben(lernender)
    assert not (ablage / "_handbuecher").exists()
    z = server._q("select * from kurs_handbuch where lead_id = %s", (lernender,))[0]
    assert (z["pfad"], z["pdf"], z["fassungen_stand"]) == ("alt.html", "alt.pdf", None)


def test_ausgeben_ohne_kapitel_entfernt_dateien_und_zeile(lernender, handbuch_nach_sitzung1,
                                                          ablage, auge_liefert_pdf):
    kh.ausgeben(lernender)
    z = server._q("select * from kurs_handbuch where lead_id = %s", (lernender,))[0]
    server._q("delete from kurs_handbuch_kapitel where lead_id = %s returning id", (lernender,))
    assert kh.ausgabe_faellig(lernender)
    kh.ausgeben(lernender)
    assert not (ablage / z["pfad"]).exists() and not (ablage / z["pdf"]).exists()
    assert not server._q("select 1 from kurs_handbuch where lead_id = %s", (lernender,))
    assert not kh.ausgabe_faellig(lernender)
    kh.ausgeben(lernender)      # nichts da: kein Fehler


def test_ausgabe_nicht_faellig_ohne_kapitel_und_zeile(lernender):
    assert not kh.ausgabe_faellig(lernender)


def test_keine_entwuerfe_und_keine_kundentexte_im_log(lernender, sitzung1, ki, ablage,
                                                      auge_liefert_pdf, caplog):
    caplog.set_level(logging.DEBUG)
    vorher = server._q("select count(*) n from drafts")[0]["n"]
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)
    kh.ausgeben(lernender)
    assert server._q("select count(*) n from drafts")[0]["n"] == vorher
    log = caplog.text
    for geheim in ("Termin anlegen", "Kontakt suchen", "Anna", "Neu:", "GEHEIM", UID1):
        assert geheim not in log


def test_sitzung_ohne_kurs_json_ist_veraltet(lernender):
    """Ohne Kursmitschrift (noch nicht erzeugt oder entfernt) gehoert die Sitzung nicht ins
    Handbuch: Veraltet vor jedem KI-Auftrag (ollama ist hier nicht ersetzt), nichts gebucht."""
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs', 'fertig') returning uid",
              (UID1, TAG1, TAG1 + timedelta(hours=1)))
    server._q("insert into termin_mitschriften (uid, segmente, rubrik) "
              "values (%s, '[]'::jsonb, 'Kurse') returning id", (UID1,))
    with pytest.raises(kh.Veraltet):
        _zuordnen(lernender, UID1)
    assert not server._q("select 1 from kurs_handbuch_quelle where uid = %s", (UID1,))
