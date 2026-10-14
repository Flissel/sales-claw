"""Vertraege ueber `medien_aus_chat_uebernehmen` (14.10.2026).

Live gemessen: ein Bild, das der Betreiber an sich selbst schickt, kam NIE
in den Medien an. OpenWA (whatsapp-web.js) laedt EIGENE Medien nicht herunter
("Own-send media download failed; emitting echo without media"), der Webhook
traegt also keine Bytes, und sales-inbox verwirft die Nachricht. Der Agent
(openclaw) bekommt das Bild dagegen sehr wohl — als
`[media attached: /home/node/.openclaw/workspace/media/inbound/.../<uuid>.jpg]`,
dieselbe Datei liegt im Gateway-Volume unter media/inbound/<uuid>.jpg. Dieser
Unterordner haengt NUR LESEND an sales-mcp (/chat-eingang); das Werkzeug
kopiert daraus in den erzeugten Medienordner, Herkunft "chat".
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import medien  # noqa: E402
import server  # noqa: E402

JPG = b"\xff\xd8\xff\xe0" + b"bild" * 100
STAGED = ("/home/node/.openclaw/workspace/media/inbound/openclaw-staged-"
          "1111/abcd-1234.jpg")


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def ordner(monkeypatch, tmp_path):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.medien_meta cascade")
    eingang = tmp_path / "chat-eingang"
    eingang.mkdir()
    erzeugt = tmp_path / "erzeugt"
    erzeugt.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(medien, "CHAT_EINGANG_VERZEICHNIS", str(eingang))
    monkeypatch.setattr(medien, "ERZEUGT_VERZEICHNIS", str(erzeugt))
    monkeypatch.setattr(medien, "MEDIA_VERZEICHNIS", str(media))
    return eingang, erzeugt


def _rufe(datei, name=""):
    return json.loads(server.medien_aus_chat_uebernehmen(datei, name))


def test_bild_aus_dem_chat_landet_in_den_medien(ordner):
    eingang, erzeugt = ordner
    (eingang / "abcd-1234.jpg").write_bytes(JPG)
    antwort = _rufe(STAGED)
    assert antwort == {"medien_datei": "abcd-1234.jpg", "bytes": len(JPG)}
    assert (erzeugt / "abcd-1234.jpg").read_bytes() == JPG
    assert not list(erzeugt.glob("*.teil"))
    zeile = server._q("select herkunft from medien_meta "
                      "where dateiname = 'abcd-1234.jpg'")[0]
    assert zeile["herkunft"] == "chat"
    liste = json.loads(server.medien_liste())
    assert any(d["name"] == "abcd-1234.jpg" and d["herkunft"] == "chat"
               for d in liste["dateien"])
    # Die Quelle bleibt unangetastet (der Mount ist ohnehin nur lesend).
    assert (eingang / "abcd-1234.jpg").exists()


def test_eigener_name_bekommt_die_endung_der_quelle(ordner):
    eingang, erzeugt = ordner
    (eingang / "abcd-1234.jpg").write_bytes(JPG)
    antwort = _rufe("abcd-1234.jpg", name="linkedin-team-foto")
    assert antwort["medien_datei"] == "linkedin-team-foto.jpg"
    assert (erzeugt / "linkedin-team-foto.jpg").read_bytes() == JPG


def test_windows_schreibweise_wird_auf_den_namen_reduziert(ordner):
    eingang, erzeugt = ordner
    (eingang / "abcd-1234.jpg").write_bytes(JPG)
    antwort = _rufe("C:\\irgendwo\\abcd-1234.jpg")
    assert antwort["medien_datei"] == "abcd-1234.jpg"


def test_gleicher_name_wird_nie_ueberschrieben(ordner):
    eingang, erzeugt = ordner
    (eingang / "abcd-1234.jpg").write_bytes(JPG)
    (erzeugt / "foto.jpg").write_bytes(b"alt")
    antwort = _rufe("abcd-1234.jpg", name="foto.jpg")
    assert antwort["medien_datei"] == "foto-2.jpg"
    assert (erzeugt / "foto.jpg").read_bytes() == b"alt"
    assert (erzeugt / "foto-2.jpg").read_bytes() == JPG


def test_fehlende_datei_wird_klar_benannt(ordner):
    antwort = _rufe(STAGED)
    assert "fehler" in antwort
    assert "erneut" in antwort["fehler"]


@pytest.mark.parametrize("datei", ["../geheim.jpg", "/etc/geheim.jpg",
                                   "..\\geheim.jpg"])
def test_pfade_ausserhalb_des_eingangs_kommen_nicht_durch(ordner, tmp_path,
                                                         datei):
    eingang, erzeugt = ordner
    # Liegt direkt NEBEN dem Eingang — genau das Ziel von "../".
    (tmp_path / "geheim.jpg").write_bytes(JPG)
    antwort = _rufe(datei)
    assert "fehler" in antwort
    assert list(erzeugt.iterdir()) == []


@pytest.mark.parametrize("datei", ["", "   ", ".", "..", "/", ".versteckt.jpg",
                                   "eingang/"])
def test_leere_und_versteckte_namen_werden_abgelehnt(ordner, datei):
    eingang, erzeugt = ordner
    (eingang / ".versteckt.jpg").write_bytes(JPG)
    antwort = _rufe(datei)
    assert "fehler" in antwort
    assert list(erzeugt.iterdir()) == []


def test_symlink_nach_draussen_wird_abgelehnt(ordner, tmp_path):
    eingang, erzeugt = ordner
    draussen = tmp_path / "draussen.jpg"
    draussen.write_bytes(JPG)
    try:
        os.symlink(draussen, eingang / "link.jpg")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks hier nicht anlegbar (Windows ohne Recht)")
    antwort = _rufe("link.jpg")
    assert "fehler" in antwort
    assert list(erzeugt.iterdir()) == []


def test_unerlaubter_typ_wird_abgelehnt(ordner):
    eingang, erzeugt = ordner
    (eingang / "tabelle.xlsx").write_bytes(b"PK\x03\x04")
    antwort = _rufe("tabelle.xlsx")
    assert "fehler" in antwort
    assert list(erzeugt.iterdir()) == []


def test_name_mit_anderer_endung_als_die_quelle_wird_abgelehnt(ordner):
    eingang, erzeugt = ordner
    (eingang / "abcd-1234.jpg").write_bytes(JPG)
    antwort = _rufe("abcd-1234.jpg", name="angebot.pdf")
    assert "fehler" in antwort
    assert list(erzeugt.iterdir()) == []


def test_name_mit_pfad_wird_abgelehnt(ordner):
    eingang, erzeugt = ordner
    (eingang / "abcd-1234.jpg").write_bytes(JPG)
    antwort = _rufe("abcd-1234.jpg", name="../foto.jpg")
    assert "fehler" in antwort
    assert list(erzeugt.iterdir()) == []


def test_zu_grosse_und_leere_datei_werden_abgelehnt(ordner, monkeypatch):
    eingang, erzeugt = ordner
    monkeypatch.setattr(medien, "MAX_BYTES", 100)
    (eingang / "gross.jpg").write_bytes(b"x" * 101)
    (eingang / "leer.jpg").write_bytes(b"")
    assert "fehler" in _rufe("gross.jpg")
    assert "fehler" in _rufe("leer.jpg")
    assert list(erzeugt.iterdir()) == []


def test_ordner_als_quelle_wird_abgelehnt(ordner):
    eingang, erzeugt = ordner
    (eingang / "unter.jpg").mkdir()
    assert "fehler" in _rufe("unter.jpg")


def test_werkzeug_ist_fuer_den_agenten_registriert():
    import inspect
    assert server.medien_aus_chat_uebernehmen in server.WERKZEUGE
    assert server.medien_aus_chat_uebernehmen in server.aktive_werkzeuge()
    parameter = inspect.signature(server.medien_aus_chat_uebernehmen).parameters
    assert list(parameter) == ["datei", "name"]
    assert parameter["name"].default == ""
