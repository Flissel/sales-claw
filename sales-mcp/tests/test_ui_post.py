"""Mail-Reiter /post und „Postfach hinzufügen“ /post/konten (Post-Sammelstelle
Stufe 1, Spec §11/§14.3) gegen sales_test.

Diese Suite verteidigt: der Reiter zeigt nur, was die zentrale Sichtbarkeit
(post_struktur) erlaubt; sensible Mails erscheinen ohne Inhalt; Korrekturen
darf nur der Besitzer; ein eingegebenes Passwort kommt nie zurück;
ohne Anmeldung gibt es nichts (fail closed).
"""
import base64
import os
import re
import time

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402
import post_struktur as ps  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

HOST = {"host": "127.0.0.1:8791"}
NAMEN = ("t8_anna", "t8_ben", "t8_lea", "t8_leser")
GEHEIM = "Sehr-Geheim-Passwort-0815"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_mails, sales_test.post_konten, "
                     "sales_test.post_regeln cascade")
        conn.execute("delete from sales_test.benutzer_abteilungen where "
                     "benutzer = any(%s)", (list(NAMEN),))
        conn.execute("delete from sales_test.benutzer where name = any(%s)",
                     (list(NAMEN),))


@pytest.fixture(autouse=True)
def welt():
    """Anmeldung scharf (wie test_login.py), vier Personen: anna und ben
    ohne Leitung (ben im Vertrieb), lea mit Leitung, leser mit Rolle lesen."""
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-t8"
    _aufraeumen()
    with server.pool.connection() as conn:
        for n, rolle, leit in (("t8_anna", "freigeben", False),
                               ("t8_ben", "freigeben", False),
                               ("t8_lea", "freigeben", True),
                               ("t8_leser", "lesen", False)):
            conn.execute(
                "insert into sales_test.benutzer (name, rolle, passwort_hash, "
                "aktiv, leitung) values (%s, %s, 'x', true, %s)",
                (n, rolle, leit))
        conn.execute("insert into sales_test.benutzer_abteilungen values "
                     "('t8_ben', 'Vertrieb')")
    yield
    ui.UI_SESSION_SECRET = vorher
    _aufraeumen()


def _client(name=None):
    c = TestClient(ui.app)
    if name:
        c.cookies.set(ui.SITZUNG_COOKIE,
                      ui._sitzung_bauen(name, time.time() + 3600))
    return c


def _get(name, pfad):
    return _client(name).get(pfad, headers=HOST, follow_redirects=False)


def _post(name, pfad, daten, csrf=True):
    if csrf:
        daten = {**daten, "csrf": ui.CSRF_TOKEN}
    return _client(name).post(pfad, data=daten, headers=HOST,
                              follow_redirects=False)


_zaehler = [0]


def _mail(besitzer="t8_anna", bereich="business", fach="Kunden & Anfragen",
          sensibel=False, betreff="Angebot", text="Hallo Welt",
          von="kunde@firma.de", anhaenge=(), an=None, status="eingeordnet"):
    _zaehler[0] += 1
    konto = server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, "
        "quelle) values (%s, %s, 'gmx', %s, 'ui') "
        "on conflict (kennung) do update set besitzer = excluded.besitzer "
        "returning id",
        (besitzer, f"k-{besitzer.replace('_', '-')}", f"{besitzer}@gmx.de"))[0]["id"]
    return str(server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, "
        "von, betreff, text, auszug, bereich, fach, sensibel, anhaenge, an, "
        "status, einordnung_quelle) values "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'modell') "
        "returning id",
        (konto, _zaehler[0], f"t8-m{_zaehler[0]}", besitzer, von, betreff,
         text, text[:20], bereich, fach, sensibel, list(anhaenge), an,
         status))[0]["id"])


def _zeile(mail_id):
    return server._q("select * from post_mails where id = %s", (mail_id,))[0]


# ---------------------------------------------------------------------------
# Ohne Anmeldung: nichts (fail closed)
# ---------------------------------------------------------------------------

def test_ohne_anmeldung_403():
    m = _mail()
    # Uebergangszustand ohne UI_SESSION_SECRET: die Wache ist durchlaessig,
    # der Reiter muss trotzdem zu sein.
    ui.UI_SESSION_SECRET = ""
    for pfad in ("/post", "/post?q=Angebot", f"/post/mail/{m}", "/post/konten"):
        r = _get(None, pfad)
        assert r.status_code == 403, pfad
        assert "Angebot" not in r.text
    for pfad, daten in ((f"/post/mail/{m}/korrigieren",
                         {"bereich": "business", "fach": "Rechnungen"}),
                        ("/post/konten", {"anbieter": "gmx", "kennung": "gmx-x",
                                          "adresse": "a@gmx.de",
                                          "passwort": GEHEIM})):
        assert _post(None, pfad, daten).status_code == 403, pfad
    assert _zeile(m)["fach"] == "Kunden & Anfragen"
    assert server._q("select count(*) n from post_konten "
                     "where kennung = 'gmx-x'")[0]["n"] == 0


def test_scharf_ohne_sitzung_kommt_nicht_rein():
    m = _mail()
    r = _get(None, f"/post/mail/{m}")
    assert r.status_code in (303, 403)
    assert "Angebot" not in r.text


# ---------------------------------------------------------------------------
# Liste, Faecher, Suche
# ---------------------------------------------------------------------------

def test_liste_zeigt_nur_sichtbare():
    privat = _mail("t8_anna", "privat", "Familie & Freunde",
                   betreff="Annas Geburtstag")
    kunde = _mail("t8_anna", "business", "Kunden & Anfragen",
                  betreff="Anfrage Kunde Meier")
    rechnung = _mail("t8_anna", "business", "Rechnungen",
                     betreff="Rechnung Lieferant")
    ben = _get("t8_ben", "/post")
    assert ben.status_code == 200
    assert "Anfrage Kunde Meier" not in ben.text      # Vertrieb: fremde Mail
    assert "Annas Geburtstag" not in ben.text         # privat von anna
    assert "Rechnung Lieferant" not in ben.text       # Buchhaltung
    assert f"/post/mail/{privat}" not in ben.text
    lea = _get("t8_lea", "/post").text
    assert "Anfrage Kunde Meier" not in lea and "Rechnung Lieferant" not in lea
    assert "Annas Geburtstag" not in lea              # auch Leitung nicht
    anna = _get("t8_anna", "/post").text
    for betreff in ("Annas Geburtstag", "Anfrage Kunde Meier",
                    "Rechnung Lieferant"):
        assert betreff in anna, betreff
    # Faecher mit Zahl: jeder zaehlt nur, was er sieht (Besitzer: seine).
    for fremder in (ben.text, lea):
        leiste = _faecherleiste(fremder)
        assert 'Kunden &amp; Anfragen <span class="zaehler">' not in leiste
        assert 'Rechnungen <span class="zaehler">' not in leiste
        assert 'Familie &amp; Freunde <span class="zaehler">' not in leiste
    anna_leiste = _faecherleiste(anna)
    assert 'Kunden &amp; Anfragen <span class="zaehler">1</span>' in anna_leiste
    assert 'Rechnungen <span class="zaehler">1</span>' in anna_leiste
    # Fremde Mail-Seite: wie nicht vorhanden.
    for fremder in ("t8_ben", "t8_lea"):
        for mail in (privat, rechnung, kunde):
            assert _get(fremder, f"/post/mail/{mail}").status_code == 404
    assert _get("t8_anna", f"/post/mail/{kunde}").status_code == 200


def _faecherleiste(seite):
    m = re.search(r'<nav class="faecher".*?</nav>', seite, re.S)
    assert m, "Faecherleiste fehlt"
    return m.group(0)


def test_filter_und_seitenzahl_kaputt_ist_kein_500():
    _mail(betreff="Anfrage Kunde Meier")
    for q in ("?seite=abc", "?seite=-3", "?seite=99999999999999999999",
              "?bereich=geheim", "?fach=Gibtsnicht", "?konto=kein-uuid",
              "?q=%22%26%3A*", "?bereich=business&fach=Familie+%26+Freunde"):
        r = _get("t8_anna", "/post" + q)
        assert r.status_code == 200, q
    assert "Anfrage Kunde Meier" in _get(
        "t8_anna", "/post?bereich=business&fach=Kunden+%26+Anfragen").text
    assert "Anfrage Kunde Meier" not in _get(
        "t8_anna", "/post?bereich=business&fach=Rechnungen").text


def test_seiten_zu_je_50():
    for i in range(51):
        _mail(betreff=f"Serienmail {i:03d}")
    erste = _get("t8_anna", "/post").text
    assert erste.count('href="/post/mail/') == 50
    assert "seite=2" in erste
    zweite = _get("t8_anna", "/post?seite=2").text
    assert zweite.count('href="/post/mail/') == 1


def test_suche_findet_business_text():
    treffer = _mail(betreff="Monatsabschluss", text="Rechnung Nummer 4711 anbei")
    _mail(betreff="Etwas anderes", text="nichts")
    fremd = _mail("t8_ben", "privat", "Familie & Freunde",
                  betreff="Bens Privates", text="auch 4711")
    r = _get("t8_anna", "/post?q=4711").text
    assert "Monatsabschluss" in r and "Etwas anderes" not in r
    assert "Bens Privates" not in r
    assert "Monatsabschluss" not in _get("t8_anna", "/post?q=gibtsnicht").text
    # Lea (Leitung) findet weder Annas Business-Mail noch Bens private.
    lea = _get("t8_lea", "/post?q=4711").text
    assert "Monatsabschluss" not in lea and f"/post/mail/{fremd}" not in lea


def test_stand_je_konto_nur_eigene():
    _mail("t8_anna", "business", ps.UNKLAR, betreff="Unklar 1")
    _mail("t8_anna", None, None, status="neu", betreff="Neu 1")
    _mail("t8_anna", "business", "Rechnungen", betreff="Fertig 1")
    _mail("t8_ben", "privat", "Familie & Freunde", betreff="Bens Post")
    anna = _get("t8_anna", "/post").text
    stand = re.search(r'<section class="kontostand".*?</section>', anna, re.S)
    assert stand, "Stand je Konto fehlt"
    assert "k-t8-anna" in stand.group(0)
    assert "k-t8-ben" not in stand.group(0)


# ---------------------------------------------------------------------------
# Einzelne Mail
# ---------------------------------------------------------------------------

def test_sensible_mail_ohne_inhalt():
    m = _mail("t8_anna", "privat", "Konten & Sicherheit", sensibel=True,
              betreff="Ihr Anmeldecode", text="Ihr Code lautet 987654",
              anhaenge=["Kontoauszug_DE89.pdf"], an="anna@privat.de")
    seite = _get("t8_anna", f"/post/mail/{m}")
    assert seite.status_code == 200
    assert "Ihr Anmeldecode" in seite.text
    assert "987654" not in seite.text
    assert "Kontoauszug_DE89" not in seite.text
    assert "anna@privat.de" not in seite.text
    assert "sensibel" in seite.text.lower()
    liste = _get("t8_anna", "/post").text
    assert "Ihr Anmeldecode" in liste and "987654" not in liste
    # Auch die Suche nach dem Code findet sie nicht.
    assert "Ihr Anmeldecode" not in _get("t8_anna", "/post?q=987654").text


def test_mail_zeigt_text_und_anhaenge():
    m = _mail(betreff="Angebot Q4", text="Sehr geehrte Damen und Herren",
              anhaenge=["angebot.pdf"], an="vertrieb@laden.de")
    seite = _get("t8_anna", f"/post/mail/{m}").text
    assert "Sehr geehrte Damen und Herren" in seite
    assert "angebot.pdf" in seite and "vertrieb@laden.de" in seite
    assert "kein-uuid" not in _get("t8_anna", "/post/mail/kein-uuid").text
    assert _get("t8_anna", "/post/mail/kein-uuid").status_code == 404


def test_mailinhalt_escaped():
    m = _mail(betreff="<script>alert(1)</script>",
              text='Hallo"><img src=x onerror=alert(2)><script>x()</script>',
              von='"Boese" <x@y.de><script>alert(3)</script>',
              anhaenge=["<svg onload=alert(4)>.pdf"])
    for pfad in ("/post", f"/post/mail/{m}", "/post?q=Hallo"):
        seite = _get("t8_anna", pfad).text
        assert "<script" not in seite, pfad
        assert "<img" not in seite and "<svg" not in seite, pfad
    seite = _get("t8_anna", f"/post/mail/{m}").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in seite


# ---------------------------------------------------------------------------
# Korrektur
# ---------------------------------------------------------------------------

def test_korrektur_setzt_quelle_mensch():
    m = _mail("t8_anna", "business", ps.UNKLAR)
    r = _post("t8_anna", f"/post/mail/{m}/korrigieren",
              {"bereich": "business", "fach": "Rechnungen"})
    assert r.status_code == 303
    assert r.headers["location"] == f"/post/mail/{m}"
    z = _zeile(m)
    assert (z["bereich"], z["fach"]) == ("business", "Rechnungen")
    assert z["einordnung_quelle"] == "mensch" and z["einordnung_version"] == 3
    assert z["status"] == "eingeordnet" and z["eingeordnet_am"] is not None
    assert z["sensibel"] is False


def test_korrektur_ungueltig_400():
    m = _mail("t8_anna", "business", ps.UNKLAR)
    for daten in ({"bereich": "privat", "fach": "Tools & Dienste"},
                  {"bereich": "geheim", "fach": "Rechnungen"},
                  {"bereich": "business", "fach": "Erfunden"},
                  {"bereich": "business"}):
        r = _post("t8_anna", f"/post/mail/{m}/korrigieren", daten)
        assert r.status_code == 400, daten
    ohne_csrf = _post("t8_anna", f"/post/mail/{m}/korrigieren",
                      {"bereich": "business", "fach": "Rechnungen"}, csrf=False)
    assert ohne_csrf.status_code == 403
    z = _zeile(m)
    assert z["fach"] == ps.UNKLAR and z["einordnung_quelle"] == "modell"


def test_korrektur_sensibel_loescht_inhalt():
    m = _mail("t8_anna", "business", "Tools & Dienste", text="Code 123456",
              anhaenge=["zugang.pdf"], an="a@b.de")
    r = _post("t8_anna", f"/post/mail/{m}/korrigieren",
              {"bereich": "privat", "fach": "Konten & Sicherheit",
               "sensibel": "ja"})
    assert r.status_code == 303
    z = _zeile(m)
    assert z["sensibel"] is True
    assert z["text"] is None and z["auszug"] is None and z["an"] is None
    assert z["anhaenge"] == []


def test_korrektur_fremder_mail_403():
    privat = _mail("t8_anna", "privat", "Familie & Freunde")
    kunde = _mail("t8_anna", "business", "Kunden & Anfragen")
    ziel = {"bereich": "business", "fach": "Rechnungen"}
    # Leitung sieht private Post nicht - also auch keine Korrektur.
    assert _post("t8_lea", f"/post/mail/{privat}/korrigieren",
                 ziel).status_code == 403
    # Ben (Vertrieb) und die Leitung sehen die Kundenmail nicht: 403.
    assert _post("t8_ben", f"/post/mail/{kunde}/korrigieren",
                 ziel).status_code == 403
    assert _post("t8_ben", "/post/mail/kein-uuid/korrigieren",
                 ziel).status_code == 403
    assert _zeile(privat)["fach"] == "Familie & Freunde"
    assert _zeile(kunde)["fach"] == "Kunden & Anfragen"
    # Auch die Leitung darf fremde Business-Post nicht korrigieren.
    assert _post("t8_lea", f"/post/mail/{kunde}/korrigieren",
                 ziel).status_code == 403
    assert _zeile(kunde)["fach"] == "Kunden & Anfragen"
    # Der Besitzer darf.
    assert _post("t8_anna", f"/post/mail/{kunde}/korrigieren",
                 ziel).status_code == 303
    assert _zeile(kunde)["fach"] == "Rechnungen"


def test_korrektur_mit_regel_legt_regel_an():
    von = "Max Muster <max+news@firma.de>"
    m = _mail("t8_anna", "business", ps.UNKLAR, von=von)
    r = _post("t8_anna", f"/post/mail/{m}/korrigieren",
              {"bereich": "business", "fach": "Newsletter & Branche",
               "regel": "ja"})
    assert r.status_code == 303
    regeln = server._q("select muster, feld, bereich, fach, sensibel, "
                       "angelegt_von, besitzer from post_regeln")
    assert len(regeln) == 1
    g = regeln[0]
    assert g["muster"] == (r'(^|[<\s"])' + re.escape("max+news@firma.de")
                           + r'($|[>\s"])')
    assert g["feld"] == "von"
    assert (g["bereich"], g["fach"], g["sensibel"]) == (
        "business", "Newsletter & Branche", False)
    assert g["angelegt_von"] == "t8_anna"
    assert g["besitzer"] == "t8_anna"
    assert re.search(g["muster"], von, re.IGNORECASE)
    assert not re.search(g["muster"], "max-news@firma.de", re.IGNORECASE)
    # Die Einordnung wendet die neue Regel auf Annas naechste Mail an.
    import post_einordnung as pe
    e = pe.nach_regel({"id": "x", "besitzer": "t8_anna", "von": von,
                       "betreff": "Neu", "datum": "", "text": ""})
    assert (e.bereich, e.fach, e.quelle) == ("business", "Newsletter & Branche",
                                             "regel")
    # Ohne Haken: keine Regel.
    m2 = _mail("t8_anna", "business", ps.UNKLAR, von="b@c.de")
    _post("t8_anna", f"/post/mail/{m2}/korrigieren",
          {"bereich": "business", "fach": "Rechnungen"})
    assert server._q("select count(*) n from post_regeln")[0]["n"] == 1


def test_regel_trifft_genau_die_adresse():
    """Ruling R12: die Regel fuer a@x.de trifft keine laengere Adresse."""
    import post_einordnung as pe
    m = _mail("t8_anna", "business", ps.UNKLAR, von="a@x.de")
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "business", "fach": "Rechnungen",
                  "regel": "ja"}).status_code == 303

    def treffer(von):
        e = pe.nach_regel({"id": "x", "besitzer": "t8_anna", "von": von,
                           "betreff": "b", "datum": "", "text": ""})
        return e is not None and e.fach == "Rechnungen"

    assert treffer("Anna <a@x.de>")
    assert treffer("a@x.de")
    assert treffer("A@X.DE")
    assert not treffer("ba@x.de")
    assert not treffer("a@x.de.evil.com")
    assert not treffer("Anna <ba@x.de>")


def test_regel_gilt_nicht_fuer_fremde_konten(monkeypatch):
    """Ruling R13: Annas „immer so“ fuer Absender X ordnet nur Annas Post ein,
    nie Bens Mail von X - auch nicht ueber den Abholdienst."""
    import post_abholen
    import post_einordnung as pe
    m = _mail("t8_anna", "business", ps.UNKLAR, von="X <x@absender.de>")
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "privat", "fach": "Abos & Newsletter",
                  "regel": "ja"}).status_code == 303

    def kopf(besitzer):
        d = {"id": "x", "von": "X <x@absender.de>", "betreff": "b",
             "datum": "", "text": ""}
        if besitzer is not None:
            d["besitzer"] = besitzer
        return d

    eigen = pe.nach_regel(kopf("t8_anna"))
    assert (eigen.bereich, eigen.fach) == ("privat", "Abos & Newsletter")
    assert pe.nach_regel(kopf("t8_ben")) is None
    assert pe.nach_regel(kopf(None)) is None          # fail closed
    assert pe.nach_regel(kopf("")) is None

    # Ende zu Ende ueber den Abholdienst: zwei neue Mails von X.
    # Nutzerregel zuerst (ohne Modell, `nach_regel`), sonst die Modell-Attrappe.
    monkeypatch.setattr(pe, "einordnen", lambda mail, konto: pe.nach_regel(mail, konto)
                        or pe.Einordnung("business", ps.UNKLAR, False, "modell", "attrappe"))
    annas = _mail("t8_anna", None, None, status="neu", von="X <x@absender.de>")
    bens = _mail("t8_ben", None, None, status="neu", von="X <x@absender.de>")
    assert post_abholen.einordnen_offene(10) == 2
    a, b = _zeile(annas), _zeile(bens)
    assert (a["bereich"], a["fach"], a["einordnung_quelle"]) == (
        "privat", "Abos & Newsletter", "regel")
    # Die Attrappe sagt business - Zum Nachsehen liegt trotzdem privat (I2c, zentral).
    assert (b["bereich"], b["fach"], b["einordnung_quelle"]) == (
        "privat", ps.UNKLAR, "modell")


def test_leitung_korrigiert_fremde_mail_nicht_und_legt_keine_regel_an():
    """Ein Container = ein Nutzer: die Leitung sieht Bens Mail nicht, kann sie
    nicht korrigieren und keine Regel in Bens Namen anlegen - auch nicht mit
    selbstgebautem Formular."""
    m = _mail("t8_ben", "business", ps.UNKLAR, von="y@lieferant.de")
    assert _get("t8_lea", f"/post/mail/{m}").status_code == 404
    assert _post("t8_lea", f"/post/mail/{m}/korrigieren",
                 {"bereich": "business", "fach": "Rechnungen",
                  "regel": "ja"}).status_code == 403
    assert _zeile(m)["fach"] == ps.UNKLAR                    # unveraendert
    assert server._q("select count(*) n from post_regeln")[0]["n"] == 0
    # Der Besitzer selbst sieht den Haken.
    eigene = _mail("t8_lea", "business", ps.UNKLAR, von="z@lieferant.de")
    assert 'name="regel"' in _get("t8_lea", f"/post/mail/{eigene}").text


def test_regel_traegt_nie_sensibel():
    """R18: auch mit Haken „sensibel“ bekommt die Regel nur Bereich und Fach;
    die Mail selbst wird sensibel."""
    m = _mail("t8_anna", "business", ps.UNKLAR, von="bank@bank.example", text="IBAN")
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "privat", "fach": "Rechnungen", "sensibel": "ja",
                  "regel": "ja"}).status_code == 303
    assert _zeile(m)["sensibel"] is True
    g = server._q("select sensibel, bereich, fach from post_regeln")[0]
    assert (g["sensibel"], g["bereich"], g["fach"]) == (False, "privat", "Rechnungen")


# ---------------------------------------------------------------------------
# Postfach hinzufuegen
# ---------------------------------------------------------------------------

@pytest.fixture
def schluessel(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    oeffentlich = k.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setenv("POST_SCHLUESSEL_OEFFENTLICH",
                       base64.b64encode(oeffentlich.encode()).decode())


def test_konto_anlegen_formular_zeigt_kein_passwort_zurueck(schluessel,
                                                             monkeypatch):
    seite = _get("t8_anna", "/post/konten")
    assert seite.status_code == 200
    feld = re.search(r'<input[^>]*name="passwort"[^>]*>', seite.text).group(0)
    assert 'type="password"' in feld and 'autocomplete="off"' in feld
    assert '<option value="gmx"' in seite.text
    assert '<option value="gmail"' in seite.text
    daten = {"anbieter": "gmx", "kennung": "gmx-t8anna",
             "adresse": "anna@gmx.de", "passwort": GEHEIM}
    # Probe scheitert (conftest: keine echte IMAP-Verbindung) -> Fehlerseite
    # mit Formular, aber ohne Passwort.
    fehler = _post("t8_anna", "/post/konten", daten)
    assert fehler.status_code == 400
    assert GEHEIM not in fehler.text
    assert "gmx-t8anna" in fehler.text           # Kennung bleibt stehen
    assert server._q("select count(*) n from post_konten")[0]["n"] == 0
    # Probe gelingt -> Konto mit Besitzer = angemeldete Person.
    import post_konten
    monkeypatch.setattr(post_konten, "_probe_imap", lambda konto: None)
    ok = _post("t8_anna", "/post/konten", daten)
    assert ok.status_code == 303 and GEHEIM not in ok.text
    z = server._q("select besitzer, anbieter, adresse, quelle, "
                  "zugang_versiegelt from post_konten")[0]
    assert (z["besitzer"], z["anbieter"], z["quelle"]) == ("t8_anna", "gmx", "ui")
    assert GEHEIM not in (z["zugang_versiegelt"] or "")
    liste = _get("t8_anna", "/post/konten").text
    assert "gmx-t8anna" in liste and "anna@gmx.de" in liste
    assert GEHEIM not in liste and z["zugang_versiegelt"] not in liste
    # Fremde Konten stehen nicht in Annas Liste.
    assert "gmx-t8anna" not in _get("t8_ben", "/post/konten").text


def test_konten_nur_rolle_freigeben():
    assert _get("t8_leser", "/post/konten").status_code == 403
    r = _post("t8_leser", "/post/konten",
              {"anbieter": "gmx", "kennung": "gmx-l", "adresse": "l@gmx.de",
               "passwort": GEHEIM})
    assert r.status_code == 403 and GEHEIM not in r.text
    ohne_csrf = _post("t8_anna", "/post/konten",
                      {"anbieter": "gmx", "kennung": "gmx-c",
                       "adresse": "c@gmx.de", "passwort": GEHEIM}, csrf=False)
    assert ohne_csrf.status_code == 403 and GEHEIM not in ohne_csrf.text
    assert server._q("select count(*) n from post_konten")[0]["n"] == 0


def test_rolle_lesen_sieht_reiter_ohne_korrektur():
    m = _mail("t8_leser", "privat", "Familie & Freunde", betreff="Lesers Post")
    seite = _get("t8_leser", f"/post/mail/{m}")
    assert seite.status_code == 200 and "Lesers Post" in seite.text
    assert "/korrigieren" not in seite.text


# ---------------------------------------------------------------------------
# Menue
# ---------------------------------------------------------------------------

def test_menue_fuehrt_zum_mail_reiter():
    seite = _get("t8_anna", "/post").text
    menue = re.search(r'<nav class="seite".*?</nav>', seite, re.S).group(0)
    assert '<a class="aktiv" href="/post">' in menue
    assert "Mails" in menue


def test_posteingang_bleibt_chatseite_mit_verweis():
    """Ruling R10: keine Umleitung; /posteingang bleibt die Chat-Seite und
    verweist fuer Mails auf /post. Im Menue steht Mails direkt danach."""
    r = _get("t8_anna", "/posteingang")
    assert r.status_code == 200
    assert "Unbeantwortet" in r.text
    assert '<a href="/post">Mails →</a>' in r.text
    menue = re.search(r'<nav class="seite".*?</nav>', r.text, re.S).group(0)
    assert menue.index('href="/posteingang"') < menue.index('href="/post"')
    links = re.findall(r'href="(/[^"]*)"', menue)
    assert links[links.index("/posteingang") + 1] == "/post"


def test_konten_formular_hat_standardbereich_mit_business_vorgewaehlt():
    seite = _get("t8_anna", "/post/konten")
    sel = re.search(r'<select[^>]*name="standard_bereich"[^>]*>(.*?)</select>',
                    seite.text, re.S)
    assert sel, "Feld standard_bereich fehlt"
    assert re.search(r'<option value="business"[^>]* selected', sel.group(1))
    assert '<option value="privat"' in sel.group(1)
    assert "selected" not in re.search(r'<option value="privat"[^>]*>', sel.group(1)).group(0)


# ---------------------------------------------------------------------------
# Mail-Eintraege im Kontakt-Verlauf / Posteingang nur fuer den Besitzer
# (Plan "Ein Posteingang fuer Chats und Mails", Task 2)
# ---------------------------------------------------------------------------

MAILTEXT = "MAILTEXT-123"
WATEXT = "WA-456"


@pytest.fixture
def kontakt_mit_mail(monkeypatch):
    """Ein Kontakt mit einer Mail- und einer WhatsApp-Kundenantwort;
    Besitzer dieses Containers ist t8_anna."""
    import json
    monkeypatch.setenv("POST_BESITZER", "t8_anna")
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")
    lead = str(server._q(
        "insert into leads (name, source) values ('Mailkontakt T2', 'email') "
        "returning id")[0]["id"])
    for kanal, text, mid in (("email", MAILTEXT, "t2-mail"),
                             ("whatsapp", WATEXT, "t2-wa")):
        server._q(
            "insert into activities (lead_id, type, payload, actor, created_at)"
            " values (%s, 'kundenantwort', %s, 'human', now() - interval '1 hour')"
            " returning id",
            (lead, json.dumps({"kanal": kanal, "text": text,
                               "richtung": "eingehend", "message_id": mid})))
    yield lead
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.personas, sales_test.leads cascade")


def test_verlauf_email_nur_fuer_container_besitzer(kontakt_mit_mail):
    pfad = f"/kontakte/{kontakt_mit_mail}?reiter=verlauf"
    anna = _get("t8_anna", pfad)
    assert anna.status_code == 200
    assert MAILTEXT in anna.text and WATEXT in anna.text
    ben = _get("t8_ben", pfad)
    assert ben.status_code == 200
    assert MAILTEXT not in ben.text
    assert WATEXT in ben.text
    # Ohne persoenliche Anmeldung (Sitzung scharf): nie der Mailtext.
    assert MAILTEXT not in _get(None, pfad).text


def test_posteingang_werkzeug_ohne_email_zeilen(kontakt_mit_mail):
    import json
    # Zweiter Kontakt nur mit Mail: darf gar nicht auftauchen.
    nur_mail = str(server._q(
        "insert into leads (name, source) values ('Nur Mail T2', 'email') "
        "returning id")[0]["id"])
    server._q(
        "insert into activities (lead_id, type, payload, actor) values "
        "(%s, 'kundenantwort', %s, 'human') returning id",
        (nur_mail, json.dumps({"kanal": "email", "text": "NURMAIL-789"})))
    daten = json.loads(server.posteingang())
    texte = " ".join(e["text_kurz"] for e in daten["eintraege"])
    assert MAILTEXT not in texte and "NURMAIL-789" not in texte
    assert WATEXT in texte
    assert all(e["kanal"] != "email" for e in daten["eintraege"])


def test_posteingang_suche_findet_email_aktivitaet_nur_fuer_besitzer(
        kontakt_mit_mail):
    assert MAILTEXT in _get("t8_anna", "/posteingang?q=MAILTEXT").text
    ben = _get("t8_ben", "/posteingang?q=MAILTEXT")
    assert ben.status_code == 200
    assert MAILTEXT not in ben.text
