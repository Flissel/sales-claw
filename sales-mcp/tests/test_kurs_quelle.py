"""Kurs-Handbuch: Quelle entfernen (Rueckbau + erneutes Einarbeiten), Reihenfolge, Loeschen,
Verschieben, Lernenden-Wechsel, Loeschantrag und Abgleich. KI (ollama.chat) und sales-auge sind
ersetzt. Datenbank sales_test."""
import io
import itertools
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kurs_handbuch as kh  # noqa: E402
import kurs_mitschrift as km  # noqa: E402
import kurs_pdf  # noqa: E402
import mitschrift_bericht as mb  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402
import termin_akte  # noqa: E402

UID1 = "kurs-quelle-0001@sales-claw"
UID2 = "kurs-quelle-0002@sales-claw"
UID3 = "kurs-quelle-0003@sales-claw"
TAG1 = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
TAG2 = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
TAG3 = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
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
def auge(monkeypatch):
    def falsch(anfrage, timeout=None):
        return _Antwort(200, b"%PDF-1.7 test")

    monkeypatch.setattr(kurs_pdf.urllib.request, "urlopen", falsch)


def _lead(name="Anna Lernend", email=None):
    lid = str(server._q(
        "insert into leads (name, email, phone, source, consent_status) "
        "values (%s, %s, %s, 'whatsapp', 'existing_customer') returning id",
        (name, email, f"+4917077{next(_nr):05d}"))[0]["id"])
    _LEADS.append(lid)
    return lid


@pytest.fixture
def lernender():
    return _lead("Anna Lernend", "anna.lernend@kurs-quelle.example")


@pytest.fixture
def lernender_b():
    return _lead("Berta Fremd")


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (320, 180), (200, 10, 10)).save(out, "JPEG")
    return out.getvalue()


def _bild(uid, tag, minute):
    z = server._q(
        "insert into termin_bilder (uid, aufgenommen_am, bild, breite, hoehe, dhash, "
        "beschreibung, beschreibung_status) values (%s, %s, %s, 320, 180, %s, 'Folie', "
        "'fertig') returning id", (uid, tag + timedelta(minutes=minute), _jpeg(), next(_nr)))
    return str(z[0]["id"])


def _abschnitt(titel, bilder=()):
    return {"titel": titel,
            "bilder": [{"bild_id": b, "zu_sehen": "Eine Folie", "erklaert": "Felix erklaert.",
                        "schritte": ["Klick auf Neu"]} for b in bilder],
            "merken": [f"Merke {titel}."]}


def _sitzung(uid, beginn, titel, lernender=None, bilder=0):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, 'Kurs Kalender', 'fertig') returning uid",
              (uid, beginn, beginn + timedelta(hours=1)))
    ids = [_bild(uid, beginn, m) for m in range(1, bilder + 1)]
    ab = [_abschnitt(t) for t in titel]
    if ids:
        ab[0] = _abschnitt(titel[0], ids)
    kj = {"ueberblick": "Du lernst den Kalender.", "abschnitte": ab, "offen": ["Frage"]}
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_am, rubrik, kurs_json, kurs_status, kurs_lead_id) "
              "values (%s, '[]'::jsonb, 'fertig', '{}'::jsonb, now(), 'Kurse', %s::jsonb, "
              "'fertig', %s) returning id", (uid, json.dumps(kj), lernender))
    server._q("update termin_mitschriften set kurs_stand = %s where uid = %s returning id",
              (km.kurs_stand(uid), uid))
    return ids


class KI:
    """Zuordnung: Standard "neu" je Abschnitt; `ziele` = {Abschnittstitel: Kapiteltitel} macht
    daraus "ergaenzen" in das Kapitel mit diesem Titel. Kapiteltext: alter Text + "Neu: <titel>".
    `waehrend` = {system: Aufruf}: laeuft einmal mitten im KI-Auftrag (Felix handelt in der UI)."""

    def __init__(self, lead):
        self.lead = lead
        self.ziele: dict[str, str] = {}
        self.eingaben: list[dict] = []
        self.waehrend: dict[str, object] = {}

    def chat(self, system, nutzer, **kw):
        e = json.loads(nutzer)
        self.eingaben.append(e)
        if system in self.waehrend:
            self.waehrend.pop(system)()
        if system == kh.ZUORDNUNG_SYSTEM:
            kap = {k["titel"]: k["kapitel_id"] for k in e["kapitel"]}
            aus = []
            for a in e["abschnitte"]:
                ziel = self.ziele.get(a["titel"])
                if ziel in kap:
                    aus.append({"abschnitt": a["abschnitt"], "entscheidung": "ergaenzen",
                                "kapitel_id": kap[ziel], "titel": None})
                else:
                    aus.append({"abschnitt": a["abschnitt"], "entscheidung": "neu",
                                "kapitel_id": None, "titel": a["titel"]})
            return json.dumps({"zuordnung": aus})
        if system == kh.KAPITEL_SYSTEM:
            bilder = list(e.get("bild_ids_alt", []))
            for a in e["neue_abschnitte"]:
                bilder += [b["bild_id"] for b in a["bilder"]]
            neu = "\n\n".join(f"Neu: {a['titel']}" for a in e["neue_abschnitte"])
            alt = e["alter_text"]
            return json.dumps({"text_md": (alt + "\n\n" if alt else "") + neu,
                               "bild_ids": bilder})
        raise AssertionError("unbekannter Auftrag")


@pytest.fixture
def ki(monkeypatch, lernender):
    k = KI(lernender)
    monkeypatch.setattr(ollama, "chat", k.chat)
    return k


def _einarbeiten(lead):
    for _ in range(50):
        offen = kh.offene_auftraege(lead)
        if not offen:
            return
        kh.fortschreiben(lead, *offen[0])
    raise AssertionError("Einarbeiten endet nicht")


def _zuordnen(lead, uid):
    """Wie der Taktgeber: nur fuer den gewaehlten Lernenden (zuordnen prueft das)."""
    server._q("update termin_mitschriften set kurs_lead_id = %s where uid = %s returning uid",
              (lead, uid))
    return kh.zuordnen(lead, uid)


def _rein(lead, uid):
    _zuordnen(lead, uid)
    _einarbeiten(lead)


def _aktuell(lead, titel):
    z = server._q(
        "select f.* from kurs_handbuch_kapitel k join kurs_handbuch_fassung f "
        "on f.id = k.aktuelle_fassung where k.lead_id = %s and k.titel = %s", (lead, titel))
    return z[0] if z else None


def _titel(lead):
    return [z["titel"] for z in server._q(
        "select titel from kurs_handbuch_kapitel where lead_id = %s order by reihenfolge",
        (lead,))]


def _fassungen_mit(uid):
    return server._q("select 1 from kurs_handbuch_fassung where %s = any(quellen)", (uid,))


def _quelle(lead, uid):
    z = server._q("select * from kurs_handbuch_quelle where lead_id = %s and uid = %s",
                  (lead, uid))
    return z[0] if z else None


def _zeile(uid):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def _handbuch(lead):
    z = server._q("select * from kurs_handbuch where lead_id = %s", (lead,))
    return z[0] if z else None


def _alt(pfad):
    t = time.time() - 3600
    os.utime(pfad, (t, t))
    return pfad


def _kursdateien(ablage):
    """Kursmitschrift-Dateien (der Bericht von "Kurs Kalender" heisst auch "_kurs-...")."""
    return [p for p in ablage.rglob("*")
            if p.name.endswith(("_kurs.html", "_kurs-intern.html", "_kurs.pdf"))]


# ---------- Fixtures: Handbuecher ----------

@pytest.fixture
def handbuch_1_und_2(lernender, ki):
    """Sitzung 1: Termin anlegen, Kontakt suchen. Sitzung 2 ergaenzt "Termin anlegen"."""
    _sitzung(UID1, TAG1, ["Termin anlegen", "Kontakt suchen"])
    _rein(lernender, UID1)
    _sitzung(UID2, TAG2, ["Termin mit Serie"])
    ki.ziele = {"Termin mit Serie": "Termin anlegen"}
    _rein(lernender, UID2)


@pytest.fixture
def handbuch_1_2_3(handbuch_1_und_2, lernender, ki):
    """Sitzung 3 ergaenzt "Termin anlegen" und legt "Export" neu an."""
    _sitzung(UID3, TAG3, ["Termin verschieben", "Export"])
    ki.ziele = {"Termin verschieben": "Termin anlegen"}
    _rein(lernender, UID3)


# ---------- quelle_entfernen ----------

def test_quelle_entfernen_setzt_kapitel_zurueck(lernender, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen", "Kontakt suchen"])
    _rein(lernender, UID1)
    vorher = _aktuell(lernender, "Termin anlegen")
    kontakt = _aktuell(lernender, "Kontakt suchen")
    _sitzung(UID2, TAG2, ["Termin mit Serie"])
    ki.ziele = {"Termin mit Serie": "Termin anlegen"}
    _rein(lernender, UID2)
    assert _aktuell(lernender, "Termin anlegen")["quellen"] == [UID1, UID2]

    assert kh.quelle_entfernen(lernender, UID2) == 1
    nachher = _aktuell(lernender, "Termin anlegen")
    assert nachher["quellen"] == [UID1]
    assert nachher["id"] == vorher["id"] and nachher["text_md"] == vorher["text_md"]
    assert "Serie" not in nachher["text_md"]
    assert not _fassungen_mit(UID2)
    assert _quelle(lernender, UID2) is None and _quelle(lernender, UID1) is not None
    assert _aktuell(lernender, "Kontakt suchen") == kontakt          # wortgleich, gleiche Fassung
    assert not kh.offene_auftraege(lernender)


def test_kapitel_nur_aus_entfernter_quelle_verschwindet(lernender, handbuch_1_und_2, ki):
    _sitzung(UID3, TAG3, ["Export"])
    _rein(lernender, UID3)
    assert _titel(lernender) == ["Termin anlegen", "Kontakt suchen", "Export"]
    assert kh.quelle_entfernen(lernender, UID3) == 1
    assert _titel(lernender) == ["Termin anlegen", "Kontakt suchen"]
    assert not _fassungen_mit(UID3)


def test_quelle_entfernen_unbekannt_aendert_nichts(lernender, handbuch_1_und_2):
    vorher = server._q("select id from kurs_handbuch_fassung order by id")
    assert kh.quelle_entfernen(lernender, "gibt-es-nicht@sales-claw") == 0
    assert server._q("select id from kurs_handbuch_fassung order by id") == vorher


def test_quelle_entfernen_offene_zuordnung(lernender, handbuch_1_und_2, ki):
    _sitzung(UID3, TAG3, ["Export"])
    _zuordnen(lernender, UID3)                  # noch nicht eingearbeitet
    assert kh.quelle_entfernen(lernender, UID3) == 0
    assert _quelle(lernender, UID3) is None and not kh.offene_auftraege(lernender)


def test_juengere_quellen_werden_neu_eingearbeitet(lernender, handbuch_1_2_3):
    export = _aktuell(lernender, "Export")
    kontakt = _aktuell(lernender, "Kontakt suchen")
    assert kh.quelle_entfernen(lernender, UID2) == 1
    # "Termin anlegen" steht wieder auf Sitzung 1; Sitzung 3 ist fuer dieses Kapitel offen
    assert _aktuell(lernender, "Termin anlegen")["quellen"] == [UID1]
    assert sorted({u for u, _ in kh.offene_auftraege(lernender)}) == [UID3]
    kid = str(server._q("select id from kurs_handbuch_kapitel where titel = 'Termin anlegen' "
                        "and lead_id = %s", (lernender,))[0]["id"])
    assert kh.offene_auftraege(lernender) == [(UID3, kid)]
    assert _quelle(lernender, UID3)["eingearbeitet_am"] is None
    assert not _fassungen_mit(UID2)
    _einarbeiten(lernender)
    neu = _aktuell(lernender, "Termin anlegen")
    assert neu["quellen"] == [UID1, UID3]
    assert "Neu: Termin verschieben" in neu["text_md"] and "Serie" not in neu["text_md"]
    assert _aktuell(lernender, "Export") == export          # nicht betroffen: wortgleich
    assert _aktuell(lernender, "Kontakt suchen") == kontakt
    assert _quelle(lernender, UID3)["eingearbeitet_am"] is not None


def test_juengere_ergaenzung_eines_geloeschten_kapitels_wird_neu(lernender, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"])
    _rein(lernender, UID1)
    _sitzung(UID2, TAG2, ["Serien"])
    _rein(lernender, UID2)                                    # neues Kapitel "Serien"
    _sitzung(UID3, TAG3, ["Serien bearbeiten"])
    ki.ziele = {"Serien bearbeiten": "Serien"}
    _rein(lernender, UID3)                                    # ergaenzt "Serien"
    assert _aktuell(lernender, "Serien")["quellen"] == [UID2, UID3]

    assert kh.quelle_entfernen(lernender, UID2) == 1
    assert _titel(lernender) == ["Termin anlegen"]
    z = _quelle(lernender, UID3)["zuordnung"]
    assert z == [{"abschnitt": 0, "entscheidung": "neu", "kapitel_id": None,
                  "titel": "Serien bearbeiten", "erledigt": False}]
    assert kh.offene_auftraege(lernender) == [(UID3, "neu:0")]
    _einarbeiten(lernender)
    assert _titel(lernender) == ["Termin anlegen", "Serien bearbeiten"]
    f = _aktuell(lernender, "Serien bearbeiten")
    assert f["quellen"] == [UID3] and "Neu: Serien bearbeiten" in f["text_md"]
    assert not _fassungen_mit(UID2)


def test_offene_zuordnung_auf_geloeschtes_kapitel_wird_neu(lernender, ki):
    _sitzung(UID2, TAG2, ["Serien"])
    _rein(lernender, UID2)
    _sitzung(UID3, TAG3, ["Serien bearbeiten"])
    ki.ziele = {"Serien bearbeiten": "Serien"}
    _zuordnen(lernender, UID3)                              # zugeordnet, nicht eingearbeitet
    kh.quelle_entfernen(lernender, UID2)
    assert kh.offene_auftraege(lernender) == [(UID3, "neu:0")]
    _einarbeiten(lernender)
    assert _titel(lernender) == ["Serien bearbeiten"]


def test_rueckbau_ist_eine_transaktion(lernender, handbuch_1_2_3, monkeypatch):
    vorher = server._q("select id, quellen from kurs_handbuch_fassung order by id")
    q3 = _quelle(lernender, UID3)

    def kaputt(*_a, **_k):
        raise RuntimeError("Absturz mitten im Rueckbau")

    monkeypatch.setattr(kh, "_zuordnungen_oeffnen", kaputt)
    with pytest.raises(RuntimeError):
        kh.quelle_entfernen(lernender, UID2)
    assert server._q("select id, quellen from kurs_handbuch_fassung order by id") == vorher
    assert _quelle(lernender, UID2) is not None
    assert _quelle(lernender, UID3) == q3


# ---------- Ausgabe nach Rueckbau (Ruling 1) ----------

def test_rueckbau_nimmt_ausgabe_zurueck_und_macht_faellig(lernender, handbuch_1_2_3, ablage,
                                                         auge):
    kh.ausgeben(lernender)
    alt = _handbuch(lernender)
    assert "Serie" in (ablage / alt["pfad"]).read_text(encoding="utf-8")
    assert not kh.ausgabe_faellig(lernender)

    kh.quelle_entfernen(lernender, UID2)
    # Dateien mit dem Inhalt der Sitzung sind sofort weg, die Ausgabe ist faellig
    assert not (ablage / alt["pfad"]).exists() and not (ablage / alt["pdf"]).exists()
    z = _handbuch(lernender)
    assert (z["pfad"], z["pdf"], z["fassungen_stand"]) == (None, None, None)
    assert kh.offene_auftraege(lernender)
    assert kh.ausgabe_faellig(lernender)            # Zwischenstand trotz offener Auftraege
    kh.ausgeben(lernender)
    html = (ablage / _handbuch(lernender)["pfad"]).read_text(encoding="utf-8")
    assert "Serie" not in html and "Termin anlegen" in html
    assert not kh.ausgabe_faellig(lernender)        # jetzt erst nach dem Einarbeiten
    _einarbeiten(lernender)
    assert kh.ausgabe_faellig(lernender)
    kh.ausgeben(lernender)
    html = (ablage / _handbuch(lernender)["pfad"]).read_text(encoding="utf-8")
    assert "Termin verschieben" in html and "Serie" not in html


def test_rueckbau_ohne_restkapitel_entfernt_handbuch_sofort(lernender, ki, ablage, auge):
    _sitzung(UID1, TAG1, ["Termin anlegen"])
    _rein(lernender, UID1)
    kh.ausgeben(lernender)
    alt = _handbuch(lernender)
    kh.quelle_entfernen(lernender, UID1)
    assert _handbuch(lernender) is None
    assert not (ablage / alt["pfad"]).exists() and not (ablage / alt["pdf"]).exists()
    assert not kh.ausgabe_faellig(lernender)


def test_einfuegen_macht_ausgabe_faellig(lernender, ki, ablage, auge):
    _sitzung(UID2, TAG2, ["Termin anlegen"])
    _rein(lernender, UID2)
    _sitzung(UID3, TAG3, ["Export"])
    _rein(lernender, UID3)
    kh.ausgeben(lernender)
    pfad = _handbuch(lernender)["pfad"]
    _sitzung(UID1, TAG1, ["Grundlagen"])
    kh.einfuegen_vorbereiten(lernender, UID1, TAG1)
    # alles stammte aus juengeren Sitzungen: kein sichtbares Kapitel, Handbuch sofort weg
    assert not kh._kapitel_zeilen(lernender) and _handbuch(lernender) is None
    assert not (ablage / pfad).exists()


def test_quelle_entfernen_loescht_huelle_der_quelle(lernender, ki):
    """Eine Huelle (nach einfuegen_vorbereiten) traegt den Titel ihrer Sitzung: geht die Sitzung,
    geht das Kapitel mit - auch wenn eine aeltere Sitzung es inzwischen gefuellt hat."""
    _sitzung(UID2, TAG2, ["Serien"])
    _rein(lernender, UID2)
    _sitzung(UID1, TAG1, ["Termin anlegen"])
    kh.einfuegen_vorbereiten(lernender, UID1, TAG1)
    ki.ziele = {"Termin anlegen": "Serien"}
    _zuordnen(lernender, UID1)
    kh.fortschreiben(lernender, *kh.offene_auftraege(lernender)[0])   # UID1 fuellt die Huelle
    assert _aktuell(lernender, "Serien")["quellen"] == [UID1]
    assert kh.quelle_entfernen(lernender, UID2) == 1
    assert _titel(lernender) == []
    # UID1 verliert das Kapitel und bekommt ein eigenes
    assert kh.offene_auftraege(lernender) == [(UID1, "neu:0")]
    _einarbeiten(lernender)
    assert _titel(lernender) == ["Termin anlegen"]
    assert _aktuell(lernender, "Termin anlegen")["quellen"] == [UID1]


def test_einfuegen_mit_restkapiteln_setzt_nur_stand_zurueck(lernender, ki, ablage, auge):
    _sitzung(UID1, TAG1, ["Termin anlegen"])
    _rein(lernender, UID1)
    _sitzung(UID3, TAG3, ["Export"])
    _rein(lernender, UID3)
    kh.ausgeben(lernender)
    pfad = _handbuch(lernender)["pfad"]
    _sitzung(UID2, TAG2, ["Mitte"])
    kh.einfuegen_vorbereiten(lernender, UID2, TAG2)
    z = _handbuch(lernender)
    assert z["pfad"] == pfad and z["fassungen_stand"] is None
    assert (ablage / pfad).exists()


# ---------- Reihenfolge ----------

def test_aeltere_sitzung_wird_an_datumsstelle_eingefuegt(lernender, ki):
    _sitzung(UID2, TAG2, ["Termin mit Serie"])
    _rein(lernender, UID2)
    _sitzung(UID3, TAG3, ["Termin verschieben"])
    ki.ziele = {"Termin verschieben": "Termin mit Serie"}
    _rein(lernender, UID3)
    _sitzung(UID1, TAG1, ["Termin anlegen"])                  # aelter, kommt spaet dazu

    server._q("update kurs_handbuch_kapitel set titel = 'Serien (Felix)' where lead_id = %s "
              "returning id", (lernender,))                   # von Felix umbenannt
    kid = str(server._q("select id from kurs_handbuch_kapitel where lead_id = %s",
                        (lernender,))[0]["id"])

    kh.einfuegen_vorbereiten(lernender, UID1, TAG1)
    assert not server._q("select 1 from kurs_handbuch_fassung f join kurs_handbuch_kapitel k "
                         "on k.id = f.kapitel_id where k.lead_id = %s", (lernender,))
    assert _quelle(lernender, UID2)["eingearbeitet_am"] is None
    assert _quelle(lernender, UID3)["eingearbeitet_am"] is None
    # das Kapitel der juengeren Sitzung bleibt als leere Huelle (Titel, Reihenfolge), unsichtbar
    assert _titel(lernender) == ["Serien (Felix)"] and not kh._kapitel_zeilen(lernender)
    _zuordnen(lernender, UID1)
    offen = kh.offene_auftraege(lernender)
    assert [u for u, _ in offen][0] == UID1
    assert offen[1:] == [(UID2, kid), (UID3, kid)]
    _einarbeiten(lernender)
    assert _titel(lernender) == ["Serien (Felix)", "Termin anlegen"]   # neue Kapitel hinten
    assert _aktuell(lernender, "Serien (Felix)")["quellen"] == [UID2, UID3]
    assert _aktuell(lernender, "Serien (Felix)")["text_md"] == \
        "Neu: Termin mit Serie\n\nNeu: Termin verschieben"
    fassungen = server._q(
        "select f.quellen from kurs_handbuch_fassung f join kurs_handbuch_kapitel k "
        "on k.id = f.kapitel_id where k.lead_id = %s order by f.erstellt_am", (lernender,))
    assert [f["quellen"] for f in fassungen] == [[UID1], [UID2], [UID2, UID3]]


def test_huelle_von_aelterer_sitzung_gefuellt_schoepfer_ergaenzt(lernender, ki):
    _sitzung(UID2, TAG2, ["Serien"])
    _rein(lernender, UID2)
    _sitzung(UID1, TAG1, ["Termin anlegen"])
    kh.einfuegen_vorbereiten(lernender, UID1, TAG1)
    ki.ziele = {"Termin anlegen": "Serien"}
    _zuordnen(lernender, UID1)
    _einarbeiten(lernender)
    # UID2 legte "Serien" an; die Huelle hatte schon Text von UID1: KI soll ergaenzen
    assert [a["entscheidung"] for a in ki.eingaben[-1]["neue_abschnitte"]] == ["ergaenzen"]
    assert ki.eingaben[-1]["alter_text"] == "Neu: Termin anlegen"
    assert _titel(lernender) == ["Serien"]
    assert _aktuell(lernender, "Serien")["quellen"] == [UID1, UID2]


def test_einfuegen_ohne_juengere_quellen_aendert_nichts(lernender, handbuch_1_und_2):
    vorher = server._q("select id from kurs_handbuch_fassung order by id")
    _sitzung(UID3, TAG3, ["Spaeter"])
    kh.einfuegen_vorbereiten(lernender, UID3, TAG3)
    assert server._q("select id from kurs_handbuch_fassung order by id") == vorher
    assert not kh.offene_auftraege(lernender)


# ---------- Lernenden-Wechsel ----------

def test_lernenden_wechsel_verschiebt_quelle(lernender, lernender_b, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender)
    _rein(lernender, UID1)
    assert km.lernender_setzen(UID1, lernender_b)
    assert not server._q("select 1 from kurs_handbuch_quelle where lead_id = %s", (lernender,))
    assert not server._q("select 1 from kurs_handbuch_kapitel where lead_id = %s", (lernender,))
    assert not _fassungen_mit(UID1)
    assert str(_zeile(UID1)["kurs_lead_id"]) == lernender_b
    assert _zeile(UID1)["kurs_json"] is not None             # Kursmitschrift selbst bleibt


def test_lernenden_gleich_lassen_entfernt_nichts(lernender, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender)
    _rein(lernender, UID1)
    assert km.lernender_setzen(UID1, lernender)
    assert _quelle(lernender, UID1) is not None and _fassungen_mit(UID1)


def test_lernenden_entfernen_nimmt_quelle_raus(lernender, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender)
    _rein(lernender, UID1)
    assert km.lernender_setzen(UID1, None)
    assert _quelle(lernender, UID1) is None and not _fassungen_mit(UID1)


# ---------- Loeschen, Verschieben ----------

@pytest.fixture
def kurs_fertig_im_handbuch(lernender, ki, ablage, auge):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender, bilder=1)
    assert km.ablegen(UID1) == "fertig"
    _rein(lernender, UID1)
    kh.ausgeben(lernender)
    assert len(_kursdateien(ablage)) == 3
    return UID1


def test_kurs_mitschrift_entfernen(lernender, kurs_fertig_im_handbuch, ablage):
    km.entfernen(UID1)
    assert not _kursdateien(ablage)
    z = _zeile(UID1)
    assert (z["kurs_pfad"], z["kurs_pfad_lernend"], z["kurs_pdf"], z["kurs_json"]) == \
        (None, None, None, None)
    assert not _fassungen_mit(UID1) and _quelle(lernender, UID1) is None
    assert _handbuch(lernender) is None
    assert not any((ablage / "_handbuecher").iterdir())


def test_loeschen_raeumt_dateien_und_fassungen(lernender, kurs_fertig_im_handbuch, ablage):
    termin_akte.mitschrift_entfernen(UID1)
    assert not _kursdateien(ablage)
    assert not _fassungen_mit(UID1)
    assert not server._q("select 1 from kurs_handbuch_quelle where uid = %s", (UID1,))
    assert not server._q("select 1 from termin_mitschriften where uid = %s", (UID1,))
    assert not any((ablage / "_handbuecher").iterdir())


def test_verschieben_aus_kurse_raeumt_auf(lernender, kurs_fertig_im_handbuch, ablage):
    assert mb.verschieben(UID1, "Notizen") == "Notizen"
    z = _zeile(UID1)
    assert z["kurs_pfad"] is None and z["kurs_json"] is None
    assert not _kursdateien(ablage)
    assert not _fassungen_mit(UID1) and _quelle(lernender, UID1) is None


def test_verschieben_innerhalb_kurse_bleibt(lernender, kurs_fertig_im_handbuch, ablage):
    vorher = _zeile(UID1)["kurs_pfad"]
    mb.verschieben(UID1, "kurse")
    assert _zeile(UID1)["kurs_pfad"] == vorher
    assert _quelle(lernender, UID1) is not None


def test_verschieben_nach_kurse_entfernt_nichts(lernender, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"])
    server._q("update termin_mitschriften set rubrik = 'Notizen', kurs_json = null, "
              "kurs_status = null where uid = %s returning id", (UID1,))
    assert mb.verschieben(UID1, "Kurse") == "Kurse"
    assert _zeile(UID1)["rubrik"] == "Kurse"


# ---------- Loeschantrag ----------

def test_lead_loeschantrag_entfernt_handbuch(lernender, kurs_fertig_im_handbuch, ablage):
    assert any((ablage / "_handbuecher").iterdir())
    server._mitschriften_abraeumen(lernender)
    assert not (ablage / "_handbuecher").exists() or not any((ablage / "_handbuecher").iterdir())
    for tabelle in ("kurs_handbuch", "kurs_handbuch_kapitel", "kurs_handbuch_quelle"):
        assert not server._q(f"select 1 from {tabelle} where lead_id = %s", (lernender,))
    # Lernenden-Wahl geloest: der Takt baut das Handbuch nicht wieder auf
    assert _zeile(UID1)["kurs_lead_id"] is None


def test_loeschantrag_nimmt_sitzung_aus_fremdem_handbuch(lernender, lernender_b, ki, ablage,
                                                         auge):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender_b)
    km.ablegen(UID1)
    server._q("insert into termin_teilnehmer (uid, adresse, name, rolle, lead_id) "
              "values (%s, 'anna.lernend@kurs-quelle.example', 'Anna', 'gast', %s) "
              "returning uid", (UID1, lernender))
    _rein(lernender_b, UID1)
    server._mitschriften_abraeumen(lernender)
    assert not _kursdateien(ablage)
    assert not _fassungen_mit(UID1) and _quelle(lernender_b, UID1) is None


def test_alles_entfernen_ohne_handbuch_laesst_andere_stehen(lernender, lernender_b, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender_b)
    _rein(lernender_b, UID1)
    vorher = server._q("select id from kurs_handbuch_fassung order by id")
    kh.alles_entfernen(lernender)                 # hat kein Handbuch: kein Fehler
    kh.alles_entfernen("kein-uuid")
    assert server._q("select id from kurs_handbuch_fassung order by id") == vorher
    assert _quelle(lernender_b, UID1) is not None
    assert str(_zeile(UID1)["kurs_lead_id"]) == lernender_b


def test_entfernen_ist_wiederholbar(lernender, kurs_fertig_im_handbuch, ablage):
    km.entfernen(UID1)
    km.entfernen(UID1)
    km.entfernen("gibt-es-nicht@sales-claw")
    assert not _kursdateien(ablage) and not _fassungen_mit(UID1)
    assert _zeile(UID1)["kurs_json"] is None


# ---------- Nebenlaeufigkeit: Felix handelt waehrend eines KI-Auftrags ----------

def test_lernenden_wechsel_waehrend_zuordnung_bucht_nichts(lernender, lernender_b, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender)
    ki.waehrend[kh.ZUORDNUNG_SYSTEM] = lambda: km.lernender_setzen(UID1, lernender_b)
    with pytest.raises(kh.Veraltet):
        kh.zuordnen(lernender, UID1)
    assert _quelle(lernender, UID1) is None and not _fassungen_mit(UID1)
    assert str(_zeile(UID1)["kurs_lead_id"]) == lernender_b


def test_verschieben_waehrend_zuordnung_bucht_nichts(lernender, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender)
    ki.waehrend[kh.ZUORDNUNG_SYSTEM] = lambda: mb.verschieben(UID1, "Notizen")
    with pytest.raises(kh.Veraltet):
        kh.zuordnen(lernender, UID1)
    assert not server._q("select 1 from kurs_handbuch_quelle where uid = %s", (UID1,))


def test_neuer_bildbestand_waehrend_zuordnung_bucht_nichts(lernender, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender)
    ki.waehrend[kh.ZUORDNUNG_SYSTEM] = lambda: _bild(UID1, TAG1, 30)   # Stand aendert sich
    with pytest.raises(kh.Veraltet):
        kh.zuordnen(lernender, UID1)
    assert _quelle(lernender, UID1) is None


def test_zuordnung_ohne_gewaehlten_lernenden_wird_abgewiesen(lernender, lernender_b, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender_b)
    with pytest.raises(kh.Veraltet):
        kh.zuordnen(lernender, UID1)
    assert not ki.eingaben                               # kein KI-Auftrag verschwendet
    assert _quelle(lernender, UID1) is None


def test_lernenden_wechsel_waehrend_fortschreiben_bucht_nichts(lernender, lernender_b, ki):
    _sitzung(UID1, TAG1, ["Termin anlegen"], lernender=lernender)
    _zuordnen(lernender, UID1)
    ki.waehrend[kh.KAPITEL_SYSTEM] = lambda: km.lernender_setzen(UID1, lernender_b)
    with pytest.raises(kh.Veraltet):
        _einarbeiten(lernender)
    assert not _fassungen_mit(UID1) and _titel(lernender) == []
    assert not server._q("select 1 from kurs_handbuch_quelle where lead_id = %s", (lernender,))


def test_quelle_entfernen_waehrend_fortschreiben_bringt_sie_nicht_zurueck(lernender,
                                                                         handbuch_1_und_2, ki):
    # Kapitel "Termin anlegen": Fassungen aus [1] und [1, 2]; Sitzung 3 soll ergaenzen
    _sitzung(UID3, TAG3, ["Termin verschieben"])
    ki.ziele = {"Termin verschieben": "Termin anlegen"}
    _zuordnen(lernender, UID3)
    ((uid, kid),) = kh.offene_auftraege(lernender)
    ki.waehrend[kh.KAPITEL_SYSTEM] = lambda: kh.quelle_entfernen(lernender, UID2)
    with pytest.raises(kh.Veraltet):
        kh.fortschreiben(lernender, UID3, kid)       # KI-Text beruht auf Fassung [1, 2]
    assert not _fassungen_mit(UID2) and not _fassungen_mit(UID3)
    assert _aktuell(lernender, "Termin anlegen")["quellen"] == [UID1]
    assert kh.offene_auftraege(lernender) == [(UID3, kid)]     # naechste Runde, neue Grundlage
    _einarbeiten(lernender)
    f = _aktuell(lernender, "Termin anlegen")
    assert f["quellen"] == [UID1, UID3] and "Serie" not in f["text_md"]


def test_quelle_entfernen_waehrend_zuordnung_loescht_ziel(lernender, ki):
    _sitzung(UID2, TAG2, ["Serien"])
    _rein(lernender, UID2)                            # Kapitel "Serien" aus Sitzung 2
    _sitzung(UID3, TAG3, ["Serien bearbeiten"])
    ki.ziele = {"Serien bearbeiten": "Serien"}
    ki.waehrend[kh.ZUORDNUNG_SYSTEM] = lambda: kh.quelle_entfernen(lernender, UID2)
    with pytest.raises(kh.Veraltet):
        _zuordnen(lernender, UID3)
    assert _quelle(lernender, UID3) is None and _titel(lernender) == []
    _zuordnen(lernender, UID3)                        # naechste Runde: eigenes Kapitel
    _einarbeiten(lernender)
    assert _titel(lernender) == ["Serien bearbeiten"]


@pytest.mark.parametrize("schon_ausgegeben", [True, False])
def test_quelle_entfernen_waehrend_ausgabe_bucht_nichts_veraltetes(
        lernender, handbuch_1_2_3, ablage, auge, monkeypatch, schon_ausgegeben):
    if schon_ausgegeben:
        kh.ausgeben(lernender)
    echt = kurs_pdf.pdf_aus_html

    def pdf_waehrenddessen(html):
        assert "Serie" in html                     # gerendert mit Sitzung 2 ...
        kh.quelle_entfernen(lernender, UID2)       # ... die Felix jetzt entfernt
        return echt(html)

    monkeypatch.setattr(kurs_pdf, "pdf_aus_html", pdf_waehrenddessen)
    kh.ausgeben(lernender)
    hb = ablage / "_handbuecher"
    assert not hb.exists() or not any(hb.iterdir())     # nichts Veraltetes geschrieben
    z = _handbuch(lernender)
    if schon_ausgegeben:
        assert (z["pfad"], z["pdf"], z["fassungen_stand"]) == (None, None, None)
        assert kh.ausgabe_faellig(lernender)
    else:
        assert z is None
    monkeypatch.setattr(kurs_pdf, "pdf_aus_html", echt)
    _einarbeiten(lernender)
    assert kh.ausgabe_faellig(lernender)
    kh.ausgeben(lernender)
    assert "Serie" not in (ablage / _handbuch(lernender)["pfad"]).read_text(encoding="utf-8")


def test_verschieben_aus_kurse_scheitert_rubrik_bleibt(lernender, kurs_fertig_im_handbuch,
                                                       ablage, monkeypatch):
    vorher = _zeile(UID1)

    def kaputt(*_a, **_k):
        raise RuntimeError("Rueckbau scheitert")

    monkeypatch.setattr(kh, "_zurueckrollen", kaputt)
    with pytest.raises(RuntimeError):
        mb.verschieben(UID1, "Notizen")
    z = _zeile(UID1)
    assert z["rubrik"] == "Kurse" and z["kurs_pfad"] == vorher["kurs_pfad"]
    assert len(_kursdateien(ablage)) == 3
    assert _quelle(lernender, UID1) is not None and _fassungen_mit(UID1)


# ---------- Abgleich ----------

def test_handbuecher_ist_kein_rubrik_ordner(lernender, kurs_fertig_im_handbuch, ablage):
    assert mb.rubrik_normalisieren("_handbuecher") != "_handbuecher"
    assert kh.ORDNER_NAME == mb.HANDBUCH_ORDNER == "_handbuecher"
    assert "_handbuecher" not in [d.name for d in mb._unterordner(ablage)]


def test_abgleich_laesst_gebuchte_kursdateien_und_handbuch_stehen(lernender,
                                                                   kurs_fertig_im_handbuch,
                                                                   ablage):
    gebucht = [ablage / p for p in (*(_zeile(UID1)[k] for k in
                                      ("kurs_pfad", "kurs_pfad_lernend", "kurs_pdf")),
                                    _handbuch(lernender)["pfad"], _handbuch(lernender)["pdf"])]
    for p in gebucht:
        _alt(p)
    r = mb.abgleichen()
    assert r["geloescht"] == 0 and r["tmp_geloescht"] == 0
    assert all(p.exists() for p in gebucht)
    # auch ein leerer _handbuecher-Ordner ist kein Rubrikordner und bleibt
    assert (ablage / "_handbuecher").is_dir()


def test_abgleich_loescht_verwaiste_kursdatei_nach_schonfrist(lernender,
                                                              kurs_fertig_im_handbuch, ablage,
                                                              caplog):
    caplog.set_level(logging.INFO)
    kurse, hb = ablage / "Kurse", ablage / "_handbuecher"
    waisen = [kurse / "2026-01-01_0900_alt_deadbeef_kurs.pdf",
              kurse / "2026-01-01_0900_alt_deadbeef_kurs-intern.html",
              kurse / "2026-01-01_0900_alt_deadbeef_kurs.html",
              hb / "handbuch-0badc0de.html"]
    tmps = [kurse / ".2026-01-01_0900_alt_deadbeef_kurs.pdf.4711.tmp",
            hb / ".handbuch-0badc0de.pdf.4711.tmp"]
    jung = kurse / "2026-01-01_0900_neu_cafebabe_kurs.pdf"     # Schonfrist
    # kein Kurs-/Handbuchname, oder Berichtsname im Handbuch-Ordner: unangetastet
    bleibt = [hb / "notiz.txt", hb / "X_deadbeef.html", kurse / "notiz_kurs.txt"]
    for p in [*waisen, *tmps, jung, *bleibt]:
        p.write_text("x")
    for p in [*waisen, *tmps, *bleibt]:
        _alt(p)
    r = mb.abgleichen()
    assert r["geloescht"] == 4 and r["tmp_geloescht"] == 2
    assert not any(p.exists() for p in waisen + tmps)
    assert jung.exists() and all(p.exists() for p in bleibt)
    for geheim in ("deadbeef", "0badc0de", "_kurs", "handbuch-"):
        assert geheim not in caplog.text


# ---------- Logs ----------

def test_logs_ohne_titel_und_namen(lernender, lernender_b, handbuch_1_2_3, caplog):
    caplog.set_level(logging.DEBUG)
    kh.quelle_entfernen(lernender, UID2)
    _sitzung("kurs-quelle-0000@sales-claw", TAG1 - timedelta(days=1), ["Ganz frueh"])
    kh.einfuegen_vorbereiten(lernender, "kurs-quelle-0000@sales-claw", TAG1 - timedelta(days=1))
    kh.alles_entfernen(lernender)
    for geheim in ("Termin", "Kontakt", "Serie", "Export", "Anna", "Berta", "Neu:", UID2,
                   UID3, "kurs-quelle"):
        assert geheim not in caplog.text, geheim
    assert "lead=" in caplog.text
