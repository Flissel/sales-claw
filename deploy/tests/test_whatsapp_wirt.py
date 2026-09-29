"""Tests fuer deploy/whatsapp_wirt.py — ohne Docker, ohne Netz, ohne DB.

Laeuft ohne Abhaengigkeiten:  python3 deploy/tests/test_whatsapp_wirt.py
"""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import whatsapp_wirt as w  # noqa: E402

SCHLUESSEL = "owa_k1_" + "ab" * 32


class FalscheWelt(w.Welt):
    def __init__(self, laeuft=False, sitzung_status=("qr_ready",),
                 webhooks=None, tabelle=True, anfrage="1234abcd-0000"):
        self.aufrufe = []
        self.laeuft = laeuft
        self.status = list(sitzung_status)
        self.webhooks = webhooks or []
        self.tabelle = tabelle
        self.anfrage = anfrage
        self.zeilen = []
        self.sessions_post = (201, {"id": "sitz-1"})

    def docker(self, *args, eingabe=None, umgebung=None):
        self.aufrufe.append(("docker", args))
        if args[0] == "inspect":
            if "Running" in args[2]:
                return "true" if self.laeuft else "false"
            return "healthy"
        if args[:1] == ("exec",) and "cat" in args:
            return SCHLUESSEL + "\n"
        return ""

    def compose(self, laden, *args):
        self.aufrufe.append(("compose", args))
        if "openwa" in args:
            self.laeuft = True

    def openwa(self, laden, methode, pfad, schluessel, rumpf=None):
        assert schluessel == SCHLUESSEL
        self.aufrufe.append(("openwa", methode, pfad, rumpf))
        if (methode, pfad) == ("POST", "/api/sessions"):
            return self.sessions_post
        if (methode, pfad) == ("GET", "/api/sessions"):
            return 200, [{"id": "alt-9", "name": "laden-ivan"}]
        if pfad == "/api/auth/api-keys":
            return 201, {"apiKey": "owa_k1_" + "cd" * 32}
        if pfad.endswith("/start"):
            return 200, {}
        if pfad.endswith("/webhooks"):
            return 200, self.webhooks
        if pfad.endswith("/qr"):
            return 200, {"qrCode": "data:image/png;base64,QUJD"}
        if pfad.startswith("/api/sessions/"):
            s = self.status.pop(0) if len(self.status) > 1 else self.status[0]
            return 200, {"status": s}
        raise AssertionError(pfad)

    def sql(self, sql, variablen=None, geheim=None):
        self.aufrufe.append(("sql", sql, variablen, geheim))
        if "whatsapp_kopplung" in sql and sql.startswith("select"):
            if not self.tabelle:
                raise RuntimeError('relation "x.whatsapp_kopplung" does not exist')
            return (self.anfrage or "") + "\n"
        if sql.startswith("update"):
            self.zeilen.append((variablen["status"], geheim["QR"],
                                geheim["FEHLER"]))
        if sql.startswith("insert into"):
            return "lead-77\n"
        return ""

    def bash(self, *args):
        self.aufrufe.append(("bash", args))
        return ""

    def schlafen(self, s):
        pass


def laden(inhalt="LADEN_PRAEFIX=ivan\nSALES_DB_SCHEMA=sales_ivan\n"
                 "PORT_OPENWA=12786\nOPENWA_API_KEY=\nOPENWA_SESSION_ID=\n"
                 "OPENWA_VIEWER_KEY=\n"):
    d = Path(tempfile.mkdtemp())
    p = d / "ivan.env"
    p.write_text(inhalt, encoding="utf-8")
    os.chmod(p, 0o600)
    return w.Laden("ivan", p, "sales_ivan", 12786)


class Einrichten(unittest.TestCase):
    def test_frischer_laden_bekommt_alles(self):
        l, welt = laden(), FalscheWelt()
        self.assertTrue(w.einrichten(welt, l))
        werte = w.env_lesen(l.envdatei)
        self.assertEqual(werte["OPENWA_API_KEY"], SCHLUESSEL)
        self.assertEqual(werte["OPENWA_SESSION_ID"], "sitz-1")
        self.assertTrue(werte["OPENWA_VIEWER_KEY"].startswith("owa_k1_cd"))
        # Leere Platzhalter ersetzt, nicht doppelt angehaengt.
        self.assertEqual(l.envdatei.read_text().count("OPENWA_API_KEY="), 1)
        self.assertEqual(stat.S_IMODE(l.envdatei.stat().st_mode), 0o600)
        compose = [a[1] for a in welt.aufrufe if a[0] == "compose"]
        self.assertIn(("-f", "docker-compose.openwa.yml", "up", "-d",
                       "--build", "openwa"), compose)
        self.assertIn(("up", "-d", "sales-ui"), compose)
        viewer = [a for a in welt.aufrufe if a[0] == "openwa"
                  and a[2] == "/api/auth/api-keys"][0]
        self.assertEqual(viewer[3]["role"], "viewer")
        self.assertEqual(viewer[3]["allowedSessions"], ["sitz-1"])

    def test_zweiter_lauf_aendert_nichts(self):
        l, welt = laden(), FalscheWelt()
        w.einrichten(welt, l)
        welt2 = FalscheWelt(laeuft=True)
        self.assertFalse(w.einrichten(welt2, l))
        self.assertFalse([a for a in welt2.aufrufe if a[0] == "compose"])
        self.assertFalse([a for a in welt2.aufrufe if a[0] == "openwa"])

    def test_vorhandene_sitzung_wird_wiederverwendet(self):
        l, welt = laden(), FalscheWelt()
        welt.sessions_post = (409, {"message": "exists"})
        w.einrichten(welt, l)
        self.assertEqual(w.env_lesen(l.envdatei)["OPENWA_SESSION_ID"], "alt-9")

    def test_sitzungsname_erfuellt_openwas_regeln(self):
        self.assertEqual(w.Laden("a_b", Path("x"), "s", 1).sitzungsname,
                         "laden-a-b")


class Koppeln(unittest.TestCase):
    def test_ohne_anfrage_passiert_nichts(self):
        l, welt = laden(), FalscheWelt(anfrage="")
        w.koppeln_laden(welt, l)
        self.assertFalse([a for a in welt.aufrufe if a[0] != "sql"])

    def test_ohne_tabelle_passiert_nichts(self):
        l, welt = laden(), FalscheWelt(tabelle=False)
        w.koppeln_laden(welt, l)
        self.assertEqual(welt.zeilen, [])

    def test_qr_dann_verbunden(self):
        l = laden()
        welt = FalscheWelt(sitzung_status=("qr_ready", "qr_ready", "ready"))
        w.koppeln_laden(welt, l)
        self.assertEqual([z[0] for z in welt.zeilen], ["qr", "qr", "verbunden"])
        self.assertEqual(welt.zeilen[0][1], "data:image/png;base64,QUJD")
        # Der QR-Code geht per \getenv, nicht als -v auf argv.
        upd = [a for a in welt.aufrufe if a[0] == "sql"
               and a[1].startswith("update")][0]
        self.assertNotIn("qr", upd[2])
        self.assertIn(("up", "-d", "sales-inbox", "sales-dispatch"),
                      [a[1] for a in welt.aufrufe if a[0] == "compose"])
        self.assertEqual(w.env_lesen(l.envdatei)["INBOX_UNBEKANNT_LEAD_ID"],
                         "lead-77")
        self.assertIn(("deploy/webhook-anbinden.sh", "ivan", "--wirklich"),
                      [a[1] for a in welt.aufrufe if a[0] == "bash"])

    def test_bestehender_webhook_wird_nicht_verdoppelt(self):
        l = laden()
        welt = FalscheWelt(sitzung_status=("ready",),
                           webhooks=[{"url": "http://ivan-inbox:8790/webhook"}])
        w.koppeln_laden(welt, l)
        self.assertFalse([a for a in welt.aufrufe if a[0] == "bash"])
        self.assertEqual(welt.zeilen[-1][0], "verbunden")

    def test_ohne_scan_laeuft_es_ab(self):
        l, welt = laden(), FalscheWelt()
        w.koppeln_laden(welt, l)
        self.assertEqual(welt.zeilen[-1][0], "abgelaufen")
        self.assertEqual(welt.zeilen[-1][2], w.ABGELAUFEN_TEXT)
        self.assertFalse([a for a in welt.aufrufe if a[0] == "bash"])

    def test_fehler_landet_auf_der_seite_ohne_schluessel(self):
        l = laden()

        class Kaputt(FalscheWelt):
            def bash(self, *args):
                raise RuntimeError("webhook scheiterte mit " + SCHLUESSEL)
        welt = Kaputt(sitzung_status=("ready",))
        w.koppeln_laden(welt, l)
        status, _, fehler = welt.zeilen[-1]
        self.assertEqual(status, "fehler")
        self.assertNotIn(SCHLUESSEL, fehler)
        self.assertIn("<schluessel>", fehler)


class EnvDatei(unittest.TestCase):
    def test_haengt_an_wenn_schluessel_fehlt(self):
        l = laden("LADEN_PRAEFIX=ivan\n")
        w.env_setzen(l.envdatei, "NEU", "1")
        self.assertEqual(w.env_lesen(l.envdatei)["NEU"], "1")


if __name__ == "__main__":
    unittest.main(verbosity=1)
