"""Bericht je Mitschrift erzeugen und in der Rubrik-Ablage ablegen (Mitschriften-Ablage, Task 2).

Datenbank sales_test; keine Dienste. Ablage: tmp_path (MITSCHRIFTEN_PFAD).
"""
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import mitschrift_bericht as mb  # noqa: E402
import server  # noqa: E402

UID = "bericht-0001@sales-claw"
UID2 = "bericht-0002@sales-claw"
T0 = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)
BEGINN = datetime(2026, 11, 14, 9, 5, tzinfo=timezone.utc)


def _seg(minute, text, sprecher="Diana"):
    return {"sprecher": sprecher, "beginn": (T0 + timedelta(minutes=minute)).isoformat(),
            "text": text, "sprache": "de"}


SEG = [_seg(0, "Hallo zusammen"), _seg(10, "Zweiter Teil")]
AJ = {"verlauf": [{"thema": "Erstes Thema", "von": 0, "bis": 0}]}


@pytest.fixture(autouse=True)
def ablage(monkeypatch, tmp_path):
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(tmp_path))
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield tmp_path


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 10, 10)).save(out, "JPEG")
    return out.getvalue()


def _mitschrift(uid=UID, titel="Kurs Eins", rubrik="Kurse", segmente=None, status="fertig"):
    server._q("insert into termin_akten (uid, herkunft, beginn, ende, titel, status) "
              "values (%s, 'sales-claw', %s, %s, %s, 'fertig') returning uid",
              (uid, BEGINN, BEGINN + timedelta(hours=1), titel))
    server._q("insert into termin_mitschriften (uid, segmente, auswertung_status, "
              "auswertung_json, auswertung_md, auswertung_am, rubrik) "
              "values (%s, %s::jsonb, %s, %s::jsonb, '## Ergebnis\n- Punkt', now(), %s) "
              "returning id",
              (uid, json.dumps(SEG if segmente is None else segmente), status,
               json.dumps(AJ), rubrik))


def _bild(uid=UID, minute=1, status="fertig"):
    z = server._q(
        "insert into termin_bilder (uid, aufgenommen_am, bild, breite, hoehe, dhash, "
        "beschreibung, beschreibung_status) values (%s, %s, %s, 64, 48, %s, 'Folie', %s) "
        "returning id", (uid, T0 + timedelta(minutes=minute), _jpeg(), minute, status))
    return str(z[0]["id"])


def _mit(uid=UID):
    return server._q("select * from termin_mitschriften where uid = %s", (uid,))[0]


def test_rubrik_normalisieren():
    n = mb.rubrik_normalisieren
    assert n("  interne   Besprechungen ") == "interne Besprechungen"
    assert n("../Kurse/x") == "Kurse x"
    assert n("Übungen-Ä 2") == "Übungen-Ä 2"
    assert n("!!!") is None
    assert n(None) is None
    lang = n("a" * 200)
    assert lang == "a" * 40
    z = n("ab " * 30)
    assert len(z) <= 40 and z == z.rstrip()


def test_rubrik_angleichen():
    assert mb.rubrik_angleichen("kurse", ["Kurse"]) == "Kurse"
    assert mb.rubrik_angleichen("Neu", ["Kurse"]) == "Neu"


def test_dateiname():
    name = mb.dateiname("Kurs: Übung/1 – Teil", BEGINN, "abc")
    assert name == f"2026-11-14_1005_kurs-uebung-1-teil_{mb.uid8('abc')}.html"
    assert mb.dateiname("", BEGINN, "abc") == f"2026-11-14_1005_termin_{mb.uid8('abc')}.html"
    kurz = mb.dateiname("x" * 300, BEGINN, "abc")
    assert len(kurz.split("_")[2]) <= 40
    assert mb.dateiname("T", BEGINN, "a") != mb.dateiname("T", BEGINN, "b")
    assert "abc" not in mb.dateiname("T", BEGINN, "abc").replace(mb.uid8("abc"), "")


def test_bericht_nur_gepruefte_bilder():
    _mitschrift()
    _bild(minute=1, status="fertig")
    _bild(minute=2, status="offen")
    assert mb.bericht_html(UID).count("<img") == 1


def test_bericht_ohne_fertige_auswertung():
    _mitschrift(status="offen")
    with pytest.raises(ValueError):
        mb.bericht_html(UID)


def test_bericht_maskiert_und_kennzeichnet():
    _mitschrift(titel="<script>x</script>", segmente=[_seg(0, "<b>fett</b>")])
    html = mb.bericht_html(UID)
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "&lt;b&gt;fett&lt;/b&gt;" in html
    assert "Intern – enthält Kundendaten, nicht weitergeben" in html
    assert "<script" not in html and "<b>" not in html


def test_ablegen_schreibt_datei_und_bucht(ablage):
    _mitschrift()
    pfad = mb.ablegen(UID)
    name = mb.dateiname("Kurs Eins", BEGINN, UID)
    assert pfad == f"Kurse/{name}"
    assert (ablage / "Kurse" / name).is_file()
    m = _mit()
    assert m["bericht_pfad"] == pfad and m["bericht_am"] is not None
    assert m["bericht_stand"] == mb.stand(UID)
    assert list(ablage.rglob("*.tmp")) == []


def test_ablegen_ohne_rubrik(ablage):
    _mitschrift(rubrik=None)
    assert mb.ablegen(UID) is None
    assert list(ablage.rglob("*.html")) == []


def test_ablegen_verschiebt_alte_datei(ablage):
    _mitschrift()
    alt = mb.ablegen(UID)
    server._q("update termin_mitschriften set rubrik = 'Intern' where uid = %s returning id",
              (UID,))
    neu = mb.ablegen(UID)
    assert neu != alt and neu.startswith("Intern/")
    assert not (ablage / alt).exists()
    assert (ablage / neu).is_file()
    assert _mit()["bericht_pfad"] == neu


def test_ablegen_mitschrift_inzwischen_geloescht(ablage, monkeypatch):
    _mitschrift()
    echt = mb.bericht_html

    def loeschend(uid):
        html = echt(uid)
        server._q("delete from termin_mitschriften where uid = %s returning id", (uid,))
        return html

    monkeypatch.setattr(mb, "bericht_html", loeschend)
    assert mb.ablegen(UID) is None
    assert list(ablage.rglob("*.html")) == []


def test_ablegen_ordner_nicht_beschreibbar(tmp_path, monkeypatch):
    datei = tmp_path / "keinordner"
    datei.write_text("x")
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(datei))
    _mitschrift()
    with pytest.raises(OSError):
        mb.ablegen(UID)
    assert _mit()["bericht_pfad"] is None


def test_stand_aendert_sich_bei_bildloeschung():
    _mitschrift()
    bid = _bild()
    vorher = mb.stand(UID)
    server._q("delete from termin_bilder where id = %s returning id", (bid,))
    assert mb.stand(UID) != vorher


def test_sicherer_pfad(ablage):
    assert mb.sicherer_pfad("../x.html") is None
    p = mb.sicherer_pfad("Kurse/a.html")
    assert p is not None and p.is_relative_to(ablage.resolve())


def test_datei_entfernen(ablage):
    (ablage / "Kurse").mkdir()
    f = ablage / "Kurse" / "a.html"
    f.write_text("x")
    mb.datei_entfernen("Kurse/a.html")
    assert not f.exists()
    mb.datei_entfernen("Kurse/a.html")  # fehlt: still
    mb.datei_entfernen(None)
    aussen = ablage.parent / "aussen.html"
    aussen.write_text("x")
    mb.datei_entfernen("../aussen.html")
    assert aussen.exists()


# ---------- Abgleich (Task 4) ----------

def _alt(pfad):
    """Datei aelter als die Schonfrist des Abgleichs machen."""
    t = time.time() - 3600
    os.utime(pfad, (t, t))
    return pfad


def test_abgleich_loescht_waisen_und_erzeugt_fehlende(ablage, caplog):
    caplog.set_level("INFO")
    _mitschrift(UID)
    gebucht = mb.ablegen(UID)
    _mitschrift(UID2, titel="Kurs Zwei")
    fehlt = mb.ablegen(UID2)
    (ablage / fehlt).unlink()
    waise = ablage / "Kurse" / "X_deadbeef.html"
    waise.write_text("x")
    _alt(waise)
    (ablage / "Alt").mkdir()
    waise_alt = ablage / "Alt" / "2026-01-01_1000_geheimer-titel_0badc0de.html"
    waise_alt.write_text("x")
    _alt(waise_alt)
    notiz = ablage / "Kurse" / "notiz.txt"
    notiz.write_text("bleibt")
    _alt(notiz)
    oben = ablage / "Y_deadbeef.html"          # kein Rubrikordner: unangetastet
    oben.write_text("x")
    _alt(oben)
    jung = ablage / "Kurse" / "Z_cafebabe.html"   # gerade geschrieben: Schonfrist
    jung.write_text("x")
    vorher = (ablage / gebucht).stat().st_mtime_ns

    assert mb.abgleichen() == {"geloescht": 2, "neu": 1, "ordner_entfernt": 1}
    assert not waise.exists() and not waise_alt.exists() and not (ablage / "Alt").exists()
    assert notiz.exists() and oben.exists() and jung.exists()
    assert (ablage / fehlt).is_file() and _mit(UID2)["bericht_pfad"] == fehlt
    assert (ablage / gebucht).stat().st_mtime_ns == vorher
    for geheim in ("deadbeef", "0badc0de", "geheimer-titel", "Kurse", str(ablage)):
        assert geheim not in caplog.text, geheim
    # zweiter Lauf: nichts mehr zu tun
    assert mb.abgleichen() == {"geloescht": 0, "neu": 0, "ordner_entfernt": 0}


def test_abgleich_ueberspringt_ohne_erwartete_datei(ablage, monkeypatch):
    _mitschrift(UID)
    pfad = mb.ablegen(UID)
    (ablage / pfad).unlink()                   # Ordner leer, Datenbank hat Buchungen
    waise = ablage / "Kurse" / "X_deadbeef.html"
    waise.write_text("x")
    _alt(waise)
    r = mb.abgleichen()
    assert set(r) == {"uebersprungen"}
    assert waise.exists() and not (ablage / pfad).exists()
    # Ordner fehlt
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(ablage / "fehlt"))
    assert set(mb.abgleichen()) == {"uebersprungen"}
    assert not (ablage / "fehlt").exists()
    # "Ordner" ist eine Datei
    datei = ablage / "datei"
    datei.write_text("x")
    monkeypatch.setenv("MITSCHRIFTEN_PFAD", str(datei))
    assert set(mb.abgleichen()) == {"uebersprungen"}
    assert _mit()["bericht_pfad"] == pfad and waise.exists()


def test_abgleich_ohne_buchung_loescht_nichts(ablage):
    (ablage / "Kurse").mkdir()
    waise = ablage / "Kurse" / "X_deadbeef.html"
    waise.write_text("x")
    _alt(waise)
    assert set(mb.abgleichen()) == {"uebersprungen"}
    assert waise.exists()
