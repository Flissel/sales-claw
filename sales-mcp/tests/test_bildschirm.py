"""Bildschirm-Standbilder erfassen, ablegen, lesen (Bildauswertung live, Task 2)."""
import io
import os
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image, ImageDraw

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import bildschirm  # noqa: E402
import server  # noqa: E402

T0 = datetime(2099, 1, 10, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten cascade")
    yield


def _jpeg(muster="links", groesse=(320, 200)):
    bild = Image.new("RGB", groesse, (255, 255, 255))
    d = ImageDraw.Draw(bild)
    b, h = groesse
    if muster == "links":
        d.rectangle([0, 0, b // 2, h], fill=(0, 0, 0))
    elif muster == "oben":
        d.rectangle([0, 0, b, h // 2], fill=(0, 0, 0))
    elif muster == "diagonal":
        for i in range(0, b, 20):
            d.rectangle([i, 0, i + 9, h], fill=(0, 0, 0))
    out = io.BytesIO()
    bild.save(out, "JPEG")
    return out.getvalue()


def _akte(uid="a1", schalter=True, plattform="jitsi", status="laeuft", abgesagt=False,
          kein_bot=False, vexa=7):
    server._q(
        "insert into termin_akten (uid, herkunft, beginn, ende, plattform, status, "
        "bildschirm_auswerten, abgesagt_am, kein_bot, vexa_meeting_id) "
        "values (%s, 'kalender', %s, %s, %s, %s, %s, %s, %s, %s) returning uid",
        (uid, T0, T0 + timedelta(hours=1), plattform, status, schalter,
         T0 if abgesagt else None, kein_bot, vexa))


def test_dhash_gleich_bei_gleichem_bild():
    assert bildschirm.dhash(_jpeg("links")) == bildschirm.dhash(_jpeg("links"))
    assert -2**63 <= bildschirm.dhash(_jpeg("diagonal")) < 2**63


def test_dhash_weit_bei_anderem_bild():
    a, b = bildschirm.dhash(_jpeg("links")), bildschirm.dhash(_jpeg("diagonal"))
    assert bildschirm.abstand(a, b) > bildschirm.SCHWELLE


def test_abstand_auf_signierten_werten():
    assert bildschirm.abstand(-1, 0) == 64
    assert bildschirm.abstand(-2**63, 2**63 - 1) == 64
    assert bildschirm.abstand(5, 5) == 0


def test_soll_aufnehmen():
    s = bildschirm.soll_aufnehmen
    spaet = T0 + timedelta(seconds=5)
    assert s(None, 0, None, T0, 0) is True
    assert s(0, 0xFFFFFFFFFFFF, T0, T0 + timedelta(seconds=4), 1) is False
    assert s(0, (1 << 10) - 1, T0, spaet, 1) is False           # Abstand 10
    assert s(0, (1 << 11) - 1, T0, spaet, 1) is True            # Abstand 11
    assert s(0, (1 << 20) - 1, T0, spaet, 150) is False         # Abstand 20 an Obergrenze
    assert s(0, (1 << 25) - 1, T0, spaet, 150) is True          # Abstand 25 (stark)


def test_beobachtung_soll_filter():
    _akte("ok")
    _akte("aus", schalter=False)
    _akte("teams", plattform="teams")
    _akte("geplant", status="geplant")
    _akte("abgesagt", abgesagt=True)
    _akte("keinbot", kein_bot=True)
    _akte("ohnevexa", vexa=None)
    r = bildschirm.beobachtung_soll()
    assert [x["uid"] for x in r] == ["ok"]
    assert "link" in r[0]
    assert bildschirm.ist_soll("ok") and not bildschirm.ist_soll("aus")
    assert not bildschirm.ist_soll("gibtsnicht")


def test_bild_ablegen_verkleinert_und_setzt_bis():
    _akte()
    gross = _jpeg("links", (3200, 1800))
    id1 = bildschirm.bild_ablegen("a1", gross, T0, "  Anna  ")
    assert id1
    id2 = bildschirm.bild_ablegen("a1", _jpeg("oben"), T0 + timedelta(seconds=30), "Anna")
    assert id2 and id2 != id1
    liste = bildschirm.bilder("a1")
    assert [str(x["id"]) for x in liste] == [id1, id2]
    assert all("bild" not in x and "vektor_bild" not in x and "vektor_text" not in x
               for x in liste)
    assert liste[0]["breite"] == bildschirm.MAX_BREITE and liste[0]["hoehe"] == 900
    assert liste[0]["bis"] == T0 + timedelta(seconds=30)
    assert liste[1]["bis"] is None
    assert liste[0]["geteilt_von"] == "Anna"
    daten = bildschirm.bild_daten("a1", id1)
    assert Image.open(io.BytesIO(daten)).size == (bildschirm.MAX_BREITE, 900)
    assert liste[0]["dhash"] == bildschirm.dhash(daten)
    bildschirm.freigabe_ende("a1", T0 + timedelta(minutes=5))
    assert bildschirm.bilder("a1")[1]["bis"] == T0 + timedelta(minutes=5)
    assert bildschirm.bild_daten("a1", id1) and bildschirm.bild_daten("x", id1) is None
    assert bildschirm.bild_loeschen("a1", id1) is True
    assert bildschirm.bild_loeschen("a1", id1) is False
    assert len(bildschirm.bilder("a1")) == 1


def test_wechsel_des_teilenden_setzt_bis():
    """R9b: ein Bild endet nur mit dem naechsten Bild DESSELBEN Teilenden (null-sicher)
    oder per quelle_ende/freigabe_ende - nicht mit dem Bild eines anderen."""
    _akte()
    bildschirm.bild_ablegen("a1", _jpeg("links"), T0, "Anna")
    bildschirm.bild_ablegen("a1", _jpeg("links"), T0 + timedelta(seconds=20), "Ben")
    a, b = bildschirm.bilder("a1")
    assert a["geteilt_von"] == "Anna" and b["geteilt_von"] == "Ben"
    assert a["bis"] is None and b["bis"] is None          # Ben schliesst Anna nicht
    bildschirm.quelle_ende("a1", "  Anna ", T0 + timedelta(seconds=25))
    a, b = bildschirm.bilder("a1")
    assert a["bis"] == T0 + timedelta(seconds=25) and b["bis"] is None


def test_bis_je_teilendem_null_sicher():
    _akte()
    bildschirm.bild_ablegen("a1", _jpeg("links"), T0, None)
    bildschirm.bild_ablegen("a1", _jpeg("oben"), T0 + timedelta(seconds=10), "Anna")
    bildschirm.bild_ablegen("a1", _jpeg("diagonal"), T0 + timedelta(seconds=20), None)
    erst, anna, zweit = bildschirm.bilder("a1")
    assert erst["bis"] == T0 + timedelta(seconds=20)       # naechstes Bild ohne Namen
    assert anna["bis"] is None and zweit["bis"] is None
    bildschirm.quelle_ende("a1", None, T0 + timedelta(seconds=30))
    erst, anna, zweit = bildschirm.bilder("a1")
    assert zweit["bis"] == T0 + timedelta(seconds=30) and anna["bis"] is None
    bildschirm.freigabe_ende("a1", T0 + timedelta(seconds=40))
    assert bildschirm.bilder("a1")[1]["bis"] == T0 + timedelta(seconds=40)


def test_ablegen_verweigert_wenn_nicht_mehr_soll():
    _akte(schalter=False)
    assert bildschirm.bild_ablegen("a1", _jpeg(), T0, None) is None
    assert bildschirm.bilder("a1") == []
    _akte("a2")
    assert bildschirm.bild_ablegen("a2", _jpeg(), T0, None)
    server._q("update termin_akten set abgesagt_am = %s where uid = 'a2' returning uid", (T0,))
    assert bildschirm.bild_ablegen("a2", _jpeg("oben"), T0 + timedelta(seconds=9), None) is None
    assert len(bildschirm.bilder("a2")) == 1


def test_bilder_zeilen_nur_fertige():
    _akte()
    a = bildschirm.bild_ablegen("a1", _jpeg("links"), T0, "A")
    b = bildschirm.bild_ablegen("a1", _jpeg("oben"), T0 + timedelta(minutes=1), "A")
    bildschirm.bild_ablegen("a1", _jpeg("diagonal"), T0 + timedelta(minutes=2), "A")
    server._q("update termin_bilder set beschreibung = 'Folie A', "
              "beschreibung_status = 'fertig' where id = %s returning id", (a,))
    server._q("update termin_bilder set beschreibung = 'kaputt', "
              "beschreibung_status = 'fehler' where id = %s returning id", (b,))
    assert bildschirm.bilder_zeilen("a1") == [(T0, "Folie A")]
    assert bildschirm.bilder_zeilen("nix") == []


def test_bilder_zu_abschnitt():
    seg = [{"beginn": (T0 + timedelta(minutes=m)).isoformat()} for m in (0, 2, 4, 6)]
    liste = [{"id": "x", "aufgenommen_am": T0 + timedelta(minutes=1)},
             {"id": "y", "aufgenommen_am": T0 + timedelta(minutes=3)},
             {"id": "z", "aufgenommen_am": T0 + timedelta(minutes=7)},
             {"id": "v", "aufgenommen_am": T0 - timedelta(minutes=1)}]
    f = bildschirm.bilder_zu_abschnitt
    assert f(seg, 1, 1, liste) == ["y"]          # 2..4 Min
    assert f(seg, 0, 1, liste) == ["x", "y"]
    assert f(seg, 3, 3, liste) == ["z"]          # letztes Segment: offenes Ende
    assert f(seg, 2, 9, liste) == ["z"]          # bis ausserhalb: begrenzt
    assert f([{"beginn": ""}], 0, 0, liste) == []
