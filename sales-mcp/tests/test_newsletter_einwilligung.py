"""Newsletter-Einwilligung im Gespraech (Betreiber 20.10.2026, A2 a) und die Seite /newsletter/einwilligung.

Was diese Suite verteidigt:
1. Gefragt wird nur, wer schon im Gespraech ist (selbst geschrieben) oder eine Grundlage hat.
2. Die Frage ist ein ENTWURF (pending) - es geht nichts von selbst raus; hoechstens alle 30 Tage.
3. opt_in setzt nur ein Mensch, mit Quelle UND Wortlaut; die Leitfaden-Antwort allein setzt nichts.
4. Wer schon Nein gesagt hat, gesperrt ist oder einen Loeschantrag hat, taucht nicht auf."""
import os
import uuid
from urllib.parse import unquote

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import sperrliste  # noqa: E402
import ui  # noqa: E402
import ui_newsletter_einwilligung as une  # noqa: E402

CLIENT = TestClient(ui.app)
HOST = {"host": "127.0.0.1:8791"}


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, sales_test.leads cascade")
    monkeypatch.setattr(server, "UNBEKANNT_LEAD_ID", "")
    monkeypatch.setattr(server, "LINKEDIN_POST_LEAD_ID", "")
    monkeypatch.setenv("EMAIL_ABSENDER", "haus@example.org")


def _lead(name="Anna Weber", consent="unknown", geschrieben=True, email=None):
    email = email or f"anna-{uuid.uuid4().hex[:8]}@example.com"
    lid = str(server._q("insert into leads (name, email, consent_status) values (%s, %s, %s) returning id",
                        (name, email, consent))[0]["id"])
    if geschrieben:
        server._q("insert into activities (lead_id, type, payload) values (%s, 'kundenantwort', '{}'::jsonb) "
                  "returning id", (lid,))
    return lid


def _ids():
    return [k["id"] for k in server._newsletter_kandidaten()]


def _consent(lid):
    return server._q("select consent_status from leads where id = %s", (lid,))[0]["consent_status"]


def test_kandidat_nur_wer_schon_geschrieben_hat_oder_grundlage():
    im_gespraech = _lead()
    fremd = _lead(geschrieben=False)
    kunde = _lead(consent="existing_customer", geschrieben=False)
    schon = _lead(consent="opt_in")
    ohne_mail = str(server._q("insert into leads (name) values ('X') returning id")[0]["id"])
    ids = _ids()
    assert im_gespraech in ids and kunde in ids
    assert fremd not in ids and schon not in ids and ohne_mail not in ids


def test_nein_sperre_loeschantrag_fallen_raus():
    nein = _lead()
    server.bedarf_speichern(nein, "consent_kontakt", "nein, bitte nicht")
    gesperrt = _lead()
    email = server._q("select email from leads where id = %s", (gesperrt,))[0]["email"]
    sperrliste.sperren(server._q, email=email, quelle="test", grund="x")
    loesch = _lead()
    server._q("update leads set enrichment = %s::jsonb where id = %s returning id",
              (server._json({server.LOESCH_SCHLUESSEL: {"am": "2026-10-01"}}), loesch))
    ids = _ids()
    assert nein not in ids and gesperrt not in ids and loesch not in ids


def test_anfragen_legt_entwurf_an_und_pausiert_30_tage():
    lid = _lead()
    r = server._newsletter_einwilligung_anfragen(lid)
    assert "draft_id" in r
    d = server._q("select status, channel, subject, body from drafts where id = %s", (r["draft_id"],))[0]
    assert d["status"] == "pending" and d["channel"] == "email"
    assert "Newsletter" in d["body"] and d["subject"] == server.NEWSLETTER_FRAGE_BETREFF
    assert "fehler" in server._newsletter_einwilligung_anfragen(lid)          # nicht doppelt
    assert _consent(lid) == "unknown"                                          # Fragen ist kein Ja


def test_fremde_werden_nicht_gefragt():
    assert "fehler" in server._newsletter_einwilligung_anfragen(_lead(geschrieben=False))


def test_erfassen_braucht_quelle_und_wortlaut():
    lid = _lead()
    assert "fehler" in server._newsletter_einwilligung_erfassen(lid, "Erfunden", "ja gern")
    assert "fehler" in server._newsletter_einwilligung_erfassen(lid, "Telefonat", " ")
    assert _consent(lid) == "unknown"
    assert server._newsletter_einwilligung_erfassen(lid, "Telefonat", "Ja, gerne!") == {"consent_status": "opt_in"}
    assert _consent(lid) == "opt_in"
    p = server._q("select payload from activities where lead_id = %s and type = 'werbe_einwilligung'",
                  (lid,))[0]["payload"]
    assert p["quelle"] == "Newsletter-Einwilligung: Telefonat" and p["wortlaut"] == "Ja, gerne!"
    assert p["durch"] == "betreiber"


def test_erfassen_nicht_bei_sperre():
    lid = _lead()
    email = server._q("select email from leads where id = %s", (lid,))[0]["email"]
    sperrliste.sperren(server._q, email=email, quelle="test", grund="x")
    assert "fehler" in server._newsletter_einwilligung_erfassen(lid, "Telefonat", "ja")
    assert _consent(lid) == "unknown"


def test_leitfaden_antwort_setzt_nichts_aber_steht_als_vorschlag_da():
    lid = _lead()
    server.bedarf_speichern(lid, "newsletter_einwilligung", "Ja, schicken Sie ihn")
    assert _consent(lid) == "unknown"
    k = next(k for k in server._newsletter_kandidaten() if k["id"] == lid)
    assert k["leitfaden_antwort"] == "Ja, schicken Sie ihn"


# --- Seite ---------------------------------------------------------------

def test_seite_zeigt_liste_link_und_ist_escaped():
    _lead(name="Anna <script>x</script>")
    s = CLIENT.get("/newsletter/einwilligung", headers=HOST)
    assert s.status_code == 200
    assert "&lt;script&gt;" in s.text and "<script>x" not in s.text
    assert "mailto:haus@example.org?subject=Anmelden" in s.text
    assert "Anfragen" in s.text and "Ja erfassen" in s.text
    assert 'href="/newsletter/einwilligung"' in s.text                    # im Menue


def test_qr_code_ist_svg():
    r = CLIENT.get("/newsletter/einwilligung/qr.svg", headers=HOST)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text


def test_ohne_absender_kein_link(monkeypatch):
    monkeypatch.setenv("EMAIL_ABSENDER", "")
    assert une.anmelde_link() == ""
    assert CLIENT.get("/newsletter/einwilligung/qr.svg", headers=HOST).status_code == 404


def test_formulare_brauchen_csrf_und_wirken():
    lid = _lead()
    ohne = CLIENT.post("/newsletter/einwilligung/erfassen", headers=HOST, follow_redirects=False,
                       data={"lead_id": lid, "quelle": "Telefonat", "wortlaut": "ja"})
    assert ohne.status_code == 403 and _consent(lid) == "unknown"
    r = CLIENT.post("/newsletter/einwilligung/anfragen", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "lead_id": lid})
    assert r.status_code == 303 and "Freigabe" in unquote(r.headers["location"])
    r = CLIENT.post("/newsletter/einwilligung/erfassen", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "lead_id": lid, "quelle": "Telefonat",
                          "wortlaut": "ja, gerne"})
    assert r.status_code == 303 and _consent(lid) == "opt_in"


def _angemeldet(rolle):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer cascade")
    server._q("insert into benutzer (name, rolle, passwort_hash, aktiv) values (%s,%s,%s,true)",
              ("mira", rolle, ui._passwort_hashen("korrekt-pferd-9")))
    c = TestClient(ui.app)
    r = c.post("/login", data={"name": "mira", "passwort": "korrekt-pferd-9", "csrf": ui.CSRF_TOKEN},
               headers=HOST, follow_redirects=False)
    assert r.status_code == 303
    return c


def test_rolle_lesen_sieht_die_liste_aber_kann_nichts_aendern(monkeypatch):
    monkeypatch.setattr(ui, "UI_SESSION_SECRET", "test-geheimnis-nur-fuer-die-suite")
    ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
    try:
        lid = _lead(name="Lea Lesbar")
        c = _angemeldet("lesen")
        s = c.get("/newsletter/einwilligung", headers=HOST)
        assert s.status_code == 200 and "Lea Lesbar" in s.text and "Ja erfassen" not in s.text
        r = c.post("/newsletter/einwilligung/erfassen", headers=HOST, follow_redirects=False,
                   data={"csrf": ui.CSRF_TOKEN, "lead_id": lid, "quelle": "Telefonat", "wortlaut": "ja"})
        assert r.status_code == 403 and _consent(lid) == "unknown"
    finally:
        ui.ANMELDE_BREMSE.update({"fehler": 0, "gesperrt_bis": 0.0})
