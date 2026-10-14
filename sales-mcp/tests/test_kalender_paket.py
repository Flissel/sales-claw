"""Eingebautes Kalender-Paket (kalender/ -> static/kalender): Pruefsummen stimmen,
nur die drei Dateien, keine fremden Quellen, Wortlaute aus der Spec im Paket."""
import hashlib
import json
import os
import pathlib

from starlette.testclient import TestClient

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import ui  # noqa: E402
import ui_kalender  # noqa: E402

ORDNER = pathlib.Path(__file__).resolve().parents[1] / "static" / "kalender"
FREMD = ("cdnjs.", "googleapis.", "gstatic.", "unpkg.", "jsdelivr.", "cloudfront.")


def _js() -> str:
    return (ORDNER / "kalender.js").read_text(encoding="utf-8")


def test_manifest_stimmt():
    m = json.loads((ORDNER / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["quelle"].startswith("fullcalendar@6.")
    for name in ("kalender.js", "kalender.css"):
        assert hashlib.sha256((ORDNER / name).read_bytes()).hexdigest() == m["sha256"][name], name


def test_nur_drei_dateien_ausgeliefert():
    assert sorted(p.name for p in ORDNER.iterdir()) == ["MANIFEST.json", "kalender.css", "kalender.js"]


def test_keine_fremden_quellen():
    for name in ("kalender.js", "kalender.css"):
        text = (ORDNER / name).read_text(encoding="utf-8", errors="replace")
        for f in FREMD:
            assert f not in text, (name, f)


def test_paket_kennt_die_wortlaute():
    text = _js()
    for s in ("Entwurf an Kunde angelegt – in Freigaben", "inzwischen geändert – neu laden",
              "nicht im Handy-Kalender", "unvollständig geprüft", "vibemind.kalender.ansicht"):
        assert s in text, s


def test_paket_braucht_kein_eval():
    # CSP der Seite erlaubt kein 'unsafe-eval' (ui_kalender.csp_kalender).
    text = _js()
    assert "new Function" not in text and "eval(" not in text


def test_statik_route_liefert_das_gebaute_paket():
    assert ui_kalender.STATIK == ORDNER
    client = TestClient(ui.app)
    for name, typ in (("kalender.js", "text/javascript"), ("kalender.css", "text/css")):
        r = client.get(f"/static/kalender/{name}", headers={"host": "127.0.0.1:8791"})
        assert r.status_code == 200, name
        assert r.headers["content-type"].startswith(typ), name
        assert r.content == (ORDNER / name).read_bytes(), name
    r = client.get("/static/kalender/MANIFEST.json", headers={"host": "127.0.0.1:8791"})
    assert r.status_code == 404
