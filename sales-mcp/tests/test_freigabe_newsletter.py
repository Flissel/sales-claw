"""Eingereichte Marketing-Inhalte in den Sales-Freigaben (Plan 2026-10-07,
Task 4). Der Client zur Marketing-API wird gefaelscht (wie in
test_marketing_pult.py); es gibt kein JavaScript."""
import asyncio
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import marketing_pult  # noqa: E402
import server  # noqa: E402
import ui  # noqa: E402
import ui_freigabe_newsletter  # noqa: E402

CLIENT = TestClient(ui.app)
HOST = {"host": "127.0.0.1:8791"}
IID = "11111111-1111-1111-1111-111111111111"
IID2 = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    ui_freigabe_newsletter._cache_leeren()
    yield
    ui_freigabe_newsletter._cache_leeren()


EINGEREICHT = [
    {"id": IID, "mandant": "vibemind", "mandant_name": "VibeMind", "art": "newsletter",
     "titel": "Early Access", "betreff": "Dein Zugang", "status": "eingereicht",
     "eingereichte_fassung": 3, "eingereicht_am": "2026-10-07T08:00:00+00:00",
     "eingereicht_von": "agent", "entschieden_von": None, "entschieden_am": None, "grund": None,
     "rueckmeldungen": [{"text": "Betreff kuerzer", "von": "mira", "am": "x", "fassung": 2, "erledigt": True},
                        {"text": "Noch offener Punkt", "von": "mira", "am": "x", "fassung": 2, "erledigt": False}],
     "export": {"auftrag_status": None}},
    {"id": IID2, "mandant": "fin2gether", "mandant_name": "fin2gether", "art": "post",
     "titel": "Launch-Post", "betreff": "", "status": "eingereicht",
     "eingereichte_fassung": 1, "eingereicht_am": "2026-10-07T09:00:00+00:00",
     "eingereicht_von": "agent", "entschieden_von": None, "entschieden_am": None, "grund": None,
     "rueckmeldungen": [], "export": {"auftrag_status": None}},
]


def _verlauf(**kw):
    basis = {"id": "v", "mandant": "vibemind", "mandant_name": "VibeMind", "art": "newsletter",
             "titel": "Alt", "betreff": "b", "status": "freigegeben", "eingereichte_fassung": 1,
             "eingereicht_am": "2026-10-06T08:00:00+00:00", "eingereicht_von": "agent",
             "entschieden_von": "mira", "entschieden_am": "2026-10-06T09:00:00+00:00",
             "grund": None, "rueckmeldungen": [], "export": {"auftrag_status": "fertig"}}
    basis.update(kw)
    return basis


class Falsch:
    def __init__(self):
        self.aufrufe = []
        self.fehler = None
        self.im_loop = []
        self.eingereicht = list(EINGEREICHT)
        self.entschieden = []
        self.antwort_freigeben = {"status": "freigegeben", "flaechen": ["a", "b"],
                                  "export_auftrag": "x", "export_fehler": None}

    def anfrage(self, methode, pfad, daten=None, roh=False, zeitlimit=None):
        self.aufrufe.append((methode, pfad, daten))
        try:
            asyncio.get_running_loop()
            self.im_loop.append(pfad)
        except RuntimeError:
            pass
        if self.fehler:
            raise self.fehler
        if pfad.startswith("/freigaben?status=eingereicht"):
            return {"freigaben": self.eingereicht}
        if pfad.startswith("/freigaben?status=entschieden"):
            return {"freigaben": self.entschieden}
        if pfad.endswith("/freigeben"):
            return self.antwort_freigeben
        if pfad.endswith("/zurueckgeben"):
            return {"status": "entwurf", "rueckmeldung": "r"}
        if pfad.endswith("/export_nachholen"):
            return {"flaechen": [], "flaechen_uebersprungen": [], "export_auftrag": "x",
                    "auftrag_vorhanden": False, "export_fehler": None}
        return {}

    def aktionen(self):
        return [a for a in self.aufrufe if a[0] == "POST"]


@pytest.fixture
def pult(monkeypatch):
    f = Falsch()
    monkeypatch.setattr(marketing_pult, "anfrage", f.anfrage)
    monkeypatch.setattr(marketing_pult, "eingerichtet", lambda: True)
    return f


def _seite():
    return CLIENT.get("/freigaben", headers=HOST)


def test_abschnitt_zeigt_karten_mit_firmen_und_art_etikett(pult):
    r = _seite()
    s = r.text
    assert r.status_code == 200
    assert 'id="marketing"' in s
    assert "VibeMind" in s and "fin2gether" in s            # beide Firmen-Etiketten
    assert "Newsletter" in s and "Post" in s                 # Art-Etikett (R7)
    assert "Early Access" in s and "Dein Zugang" in s and "Launch-Post" in s
    assert "Fassung 3" in s and "agent" in s
    assert f'src="/marketing/entwurf/{IID}/vorschau?fassung=3&amp;format=mail"' in s
    assert 'href="/freigaben?nl_format=handy#marketing"' in s
    assert f'href="/marketing/entwurf/{IID}"' in s           # Im Editor ansehen
    assert "Betreff kuerzer" in s and '<details class="karte" open>' in s    # R11         # erledigte Rueckmeldung
    assert "Noch offener Punkt" not in s                      # offene nicht unter "erledigt"
    assert "<script" not in s
    assert "frame-src 'self'" in r.headers["content-security-policy"]


def test_handy_format_per_link(pult):
    s = CLIENT.get("/freigaben?nl_format=handy", headers=HOST).text
    assert f'src="/marketing/entwurf/{IID}/vorschau?fassung=3&amp;format=handy"' in s


def test_aktionsformulare(pult):
    s = _seite().text
    assert f'action="/freigaben/newsletter/{IID}/freigeben"' in s
    assert f'action="/freigaben/newsletter/{IID}/zurueckgeben"' in s
    assert 'name="bestaetigt"' in s
    assert '<textarea name="kommentar" required maxlength="2000"' in s
    assert f'name="csrf" value="{ui.CSRF_TOKEN}"' in s
    assert 'name="fassung" value="3"' in s


def test_verlauf(pult):
    pult.entschieden = [
        _verlauf(id="a", titel="Frei1", export={"auftrag_status": "in_arbeit"}),
        _verlauf(id="b", titel="Frei2", export={"auftrag_status": "fertig"}),
        _verlauf(id="c", titel="Frei3", export={"auftrag_status": None}),
        _verlauf(id="d", titel="Weg", status="abgelehnt", grund="Falsche Firma"),
        _verlauf(id="e", titel="Zurueck", status="entwurf",
                 rueckmeldungen=[{"text": "Bitte kuerzen", "von": "m", "am": "x", "fassung": 1,
                                  "erledigt": False}]),
    ]
    s = _seite().text
    assert "Export läuft" in s and "Newsletter-Bilder fertig" in s
    assert "Export offen – erneut anstoßen" in s
    assert "/freigaben/newsletter/c/export-nachholen" in s
    assert "Falsche Firma" in s and "Bitte kuerzen" in s
    assert ("GET", "/freigaben?status=entschieden&limit=10", None) in pult.aufrufe


def test_zaehler_addiert_nur_im_menue_nicht_in_heute(pult, monkeypatch):
    monkeypatch.setattr(server.medien, "liste", lambda *a, **k: [])   # Medienordner gibt es hier nicht
    assert ui_freigabe_newsletter._laden() == 2
    z = ui._zaehler_abfragen()
    assert z["/freigaben"] == 2
    assert z["/"] == z["/freigaben"] - 2 + z["/wiedervorlagen"] + z["/einordnung"]   # R10


def test_anzahl_offen_ist_nur_zwischenspeicher(pult):
    assert ui_freigabe_newsletter.anzahl_offen() == 0           # kalt: kein Abruf auf dem Render-Weg
    t = ui_freigabe_newsletter._laeuft["thread"]
    t.join(5)
    assert pult.im_loop == []
    assert ui_freigabe_newsletter.anzahl_offen() == 2           # Hintergrund hat aufgefrischt
    n = len(pult.aufrufe)
    assert ui_freigabe_newsletter.anzahl_offen() == 2
    assert len(pult.aufrufe) == n                               # frisch: kein weiterer Abruf


def test_laden_fehler_gibt_0(pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    assert ui_freigabe_newsletter._laden() == 0
    pult.fehler = RuntimeError("kaputt")
    assert ui_freigabe_newsletter._laden() == 0


def test_kalter_zaehler_blockiert_den_loop_nicht(pult, monkeypatch):
    monkeypatch.setattr(server.medien, "liste", lambda *a, **k: [])
    for pfad in ("/freigaben", "/"):
        ui_freigabe_newsletter._cache_leeren()
        assert CLIENT.get(pfad, headers=HOST).status_code == 200
        t = ui_freigabe_newsletter._laeuft["thread"]
        if t is not None:
            t.join(5)
        assert pult.im_loop == [], pfad


def test_tote_api_wird_nicht_bei_jedem_aufruf_neu_versucht(pult):
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "x")
    assert "Marketing gerade nicht erreichbar" in _seite().text
    n = len(pult.aufrufe)
    assert n == 1                                               # zweite Lesung entfaellt
    assert "Marketing gerade nicht erreichbar" in _seite().text
    assert len(pult.aufrufe) == n                               # < 60 s: sofort, ohne Abruf


def test_lese_zeitlimit_kurz(pult, monkeypatch):
    gesehen = []
    orig = pult.anfrage
    monkeypatch.setattr(marketing_pult, "anfrage",
                        lambda *a, **k: (gesehen.append(k.get("zeitlimit")), orig(*a, **k))[1])
    _seite()
    assert gesehen and all(z is not None and z <= 3 for z in gesehen)


def test_unerwarteter_fehler_ist_kein_500(pult):
    pult.fehler = RuntimeError("kaputt")
    r = _seite()
    assert r.status_code == 200 and "Marketing gerade nicht erreichbar" in r.text


def test_freigeben_schickt_pult_aufruf(pult):
    r = CLIENT.post(f"/freigaben/newsletter/{IID}/freigeben", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "fassung": "3", "bestaetigt": "ja"})
    assert r.status_code == 303 and r.headers["location"].endswith("#marketing")
    assert pult.aktionen() == [("POST", f"/inhalte/{IID}/freigeben", {"fassung": 3, "von": "betreiber-ui"})]
    assert pult.im_loop == []
    assert "Medien: 2 Flächen" in CLIENT.get(r.headers["location"], headers=HOST).text


def test_freigeben_ohne_haken_ruft_nichts(pult):
    r = CLIENT.post(f"/freigaben/newsletter/{IID}/freigeben", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "fassung": "3"})
    assert r.status_code == 400 and pult.aktionen() == []


def test_freigeben_export_fehler_redirect_mit_hinweis(pult):
    pult.antwort_freigeben = {"status": "freigegeben", "flaechen": [], "export_auftrag": None,
                              "export_fehler": "Bild-Dienst weg"}
    r = CLIENT.post(f"/freigaben/newsletter/{IID}/freigeben", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "fassung": "3", "bestaetigt": "ja"})
    assert r.status_code == 303
    s = CLIENT.get(r.headers["location"], headers=HOST).text
    assert "Export offen – erneut anstoßen" in s


def test_zurueckgeben_schickt_kommentar(pult):
    r = CLIENT.post(f"/freigaben/newsletter/{IID}/zurueckgeben", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN, "fassung": "3", "kommentar": "  Betreff fehlt  "})
    assert r.status_code == 303 and r.headers["location"] == "/freigaben#marketing"
    assert pult.aktionen() == [("POST", f"/inhalte/{IID}/zurueckgeben",
                                {"fassung": 3, "von": "betreiber-ui", "text": "Betreff fehlt"})]
    assert pult.im_loop == []


def test_zurueckgeben_ohne_kommentar_422_ohne_pult_aufruf(pult):
    for k in ("", "   "):
        r = CLIENT.post(f"/freigaben/newsletter/{IID}/zurueckgeben", headers=HOST,
                        data={"csrf": ui.CSRF_TOKEN, "fassung": "3", "kommentar": k})
        assert r.status_code == 422 and "Bitte sag kurz, was fehlt" in r.text
    assert pult.aktionen() == []


def test_export_nachholen(pult):
    r = CLIENT.post(f"/freigaben/newsletter/{IID}/export-nachholen", headers=HOST, follow_redirects=False,
                    data={"csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert pult.aktionen() == [("POST", f"/inhalte/{IID}/export_nachholen", {})]
    assert pult.im_loop == []


@pytest.mark.parametrize("pfad,daten", [
    ("freigeben", {"fassung": "3", "bestaetigt": "ja"}),
    ("zurueckgeben", {"fassung": "3", "kommentar": "x"}),
    ("export-nachholen", {}),
])
def test_ohne_csrf_403(pult, pfad, daten):
    r = CLIENT.post(f"/freigaben/newsletter/{IID}/{pfad}", headers=HOST, data=daten)
    assert r.status_code == 403 and pult.aktionen() == []


def test_abgelehnt_zeigt_fehlerseite_mit_grund(pult):
    pult.fehler = marketing_pult.PultFehler("abgelehnt", "Schon entschieden (freigegeben)")
    r = CLIENT.post(f"/freigaben/newsletter/{IID}/freigeben", headers=HOST,
                    data={"csrf": ui.CSRF_TOKEN, "fassung": "3", "bestaetigt": "ja"})
    assert r.status_code == 422 and "Schon entschieden (freigegeben)" in r.text


def test_api_weg_seite_bleibt(pult):
    lead = str(server._q("insert into leads (name, phone, source) values ('Max', '+491', 'whatsapp') "
                         "returning id")[0]["id"])
    server._q("insert into drafts (lead_id, channel, recipient, body, status) values "
              "(%s, 'whatsapp', '+491', 'Hallo Welt', 'pending') returning id", (lead,))
    pult.fehler = marketing_pult.PultFehler("nicht_erreichbar", "URLError")
    r = _seite()
    assert r.status_code == 200
    assert "Marketing gerade nicht erreichbar" in r.text
    assert "Hallo Welt" in r.text                              # Sales-Arten da
