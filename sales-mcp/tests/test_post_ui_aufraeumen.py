"""Mail-Reiter Aufmerksamkeit, Zur Info, To-Review und Aufräumen (Spec 2026-11-06 §6.1,
§6.3, §7) gegen sales_test. Anmeldung, Personen und Hilfen kommen aus test_ui_post.py.
"""
import math
import os
import re

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402
import server  # noqa: E402
import post_struktur as ps  # noqa: E402
from test_ui_post import (HOST, _client, _get, _mail, _post, _zeile,  # noqa: E402,F401
                          schema_wache, welt)  # noqa: F401


@pytest.fixture(autouse=True)
def freigaben_leer():
    # `welt` leert Mails, Konten und Regeln, nicht die Freigaben.
    def leeren():
        with server.pool.connection() as conn:
            conn.execute("truncate sales_test.post_loeschfreigaben")
    leeren()
    yield
    leeren()


def _ziel(mail_id, ziel, **spalten):
    sets = ["ziel = %s"] + [f"{k} = %s" for k in spalten]
    with server.pool.connection() as conn:
        conn.execute(f"update post_mails set {', '.join(sets)} where id = %s",
                     (ziel, *spalten.values(), mail_id))
    return mail_id


def _werbung(von, jahr=2025, betreff="Angebot", besitzer="t8_anna"):
    m = _mail(besitzer, "privat", "Werbung", von=von, betreff=betreff)
    return _ziel(m, "loeschen", datum=f"{jahr}-06-15 12:00+00")


def _post_liste(name, pfad, daten, csrf=True):
    """Formular mit mehrfach vorkommenden Feldern (absender, loeschen)."""
    if csrf:
        daten = {**daten, "csrf": ui_token()}
    return _client(name).post(pfad, data=daten, headers=HOST, follow_redirects=False)


def ui_token():
    import ui
    return ui.CSRF_TOKEN


def _regeln(art="nie_werbung", besitzer="t8_anna"):
    return server._q("select muster from post_regeln where art = %s and besitzer = %s",
                     (art, besitzer))


# --- Reiter ---------------------------------------------------------------

def test_standardansicht_ist_aufmerksamkeit():
    _ziel(_mail(betreff="Im Posteingang"), "posteingang")
    _mail(betreff="Noch ohne Ziel")
    _ziel(_mail(betreff="Nur zur Info"), "zur_info")
    _ziel(_mail(betreff="Wird geprueft"), "to_review")
    _ziel(_mail(betreff="Schon weg"), "posteingang", status="geloescht")
    seite = _get("t8_anna", "/post").text
    assert "Im Posteingang" in seite and "Noch ohne Ziel" in seite
    assert "Nur zur Info" not in seite and "Wird geprueft" not in seite
    assert "Schon weg" not in seite
    assert 'class="reiter"' in seite
    for reiter in ("Aufmerksamkeit", "Zur Info", "To-Review", "Aufräumen"):
        assert reiter in seite
    # Unbekannte Ansicht fällt auf die Vorgabe zurück, kein 500.
    assert "Im Posteingang" in _get("t8_anna", "/post?ansicht=quatsch").text
    # Geloeschtes erscheint in keinem Reiter.
    for ansicht in ("zur_info", "to_review"):
        assert "Schon weg" not in _get("t8_anna", f"/post?ansicht={ansicht}").text


def test_zur_info_reiter_zeigt_faecher():
    _ziel(_mail("t8_anna", "privat", "Rechnungen", betreff="Rechnung A"), "zur_info")
    _ziel(_mail("t8_anna", "privat", "Familie & Freunde", betreff="Ausflug"), "posteingang")
    seite = _get("t8_anna", "/post?ansicht=zur_info").text
    assert 'class="faecher"' in seite
    assert "Rechnung A" in seite and "Ausflug" not in seite
    # Die Fächer-Links bleiben im Reiter und zählen nur dessen Mails.
    assert "ansicht=zur_info" in seite and "fach=Rechnungen" in seite
    assert "fach=Familie" not in seite
    gefiltert = _get("t8_anna", "/post?ansicht=zur_info&bereich=privat&fach=Rechnungen").text
    assert "Rechnung A" in gefiltert


def test_to_review_nennt_loeschdatum():
    _ziel(_mail(betreff="Fest verschoben"), "to_review", ordner_am="2026-10-01 12:00+00")
    _ziel(_mail(betreff="Noch nicht verschoben"), "to_review")
    seite = _get("t8_anna", "/post?ansicht=to_review").text
    assert "wird gelöscht am 31.10.2026" in seite
    # Ohne ordner_am gibt es kein erfundenes Datum.
    assert seite.count("wird gelöscht am") == 1
    assert "noch nicht im Ordner" in seite


# --- Aufräumen ------------------------------------------------------------

def test_aufraeumen_zeigt_jahre_und_resttage():
    _werbung("Shop <news@shop.example>", jahr=2025)
    _werbung("Shop <news@shop.example>", jahr=2024)
    for _ in range(3):
        _mail("t8_anna", None, None, status="neu")
    konto = server._q("select id from post_konten where besitzer = 't8_anna'")[0]["id"]
    server._q("update post_konten set ordnen_aus = 'UIDVALIDITY geaendert' where id = %s "
              "returning id", (konto,))
    seite = _get("t8_anna", "/post/aufraeumen").text
    assert "/post/aufraeumen/2025" in seite and "/post/aufraeumen/2024" in seite
    assert "Modellaufrufe heute" in seite and "/ 500" in seite
    assert f"<b>{math.ceil(3 * 2 / 500)}</b> Tage Rest" in seite
    assert "ruht: UIDVALIDITY geaendert" in seite
    assert "Ordnungsmodus" in seite


def test_vorschau_formular_ein_knopf_und_haken_je_absender():
    for i in range(2):
        _werbung("Shop <news@shop.example>", betreff=f"Sale {i}")
    _werbung("Andere <info@andere.example>", betreff="Aktion")
    seite = _get("t8_anna", "/post/aufraeumen/2025").text
    # Ein Formular, ein Knopf für die Freigabe (der Seitenrahmen hat eigene Formulare).
    assert seite.count('action="/post/aufraeumen/2025"') == 1
    assert seite.count('class="primaer"') == 1
    assert "Jahr 2025 löschen freigeben" in seite
    haken = re.findall(r'<input type="checkbox" name="loeschen"[^>]*>', seite)
    assert len(haken) == 2 and all(" checked" in h for h in haken)
    assert len(re.findall(r'type="hidden" name="absender"', seite)) == 2
    assert "news@shop.example" in seite and "Sale" in seite


def test_abgewaehlter_absender_wird_ausgenommen():
    a = _werbung("Shop <news@shop.example>")
    b = _werbung("Andere <info@andere.example>")
    r = _post_liste("t8_anna", "/post/aufraeumen/2025", {
        "absender": ["news@shop.example", "info@andere.example"],
        "loeschen": ["news@shop.example"]})
    assert r.status_code == 303 and r.headers["location"].startswith("/post/aufraeumen")
    zeile = server._q("select ausgenommen from post_loeschfreigaben "
                      "where besitzer = 't8_anna' and jahr = 2025")[0]
    assert zeile["ausgenommen"] == ["info@andere.example"]
    assert len(_regeln()) == 1 and "andere" in _regeln()[0]["muster"]
    assert _zeile(a)["ziel"] == "loeschen" and _zeile(b)["ziel"] == "zur_info"
    # Zweiter Klick auf dasselbe Jahr: Hinweis statt Absturz.
    zweit = _post_liste("t8_anna", "/post/aufraeumen/2025", {
        "absender": ["news@shop.example"], "loeschen": ["news@shop.example"]})
    assert zweit.status_code == 303
    assert zweit.headers["location"] == "/post/aufraeumen?hinweis=schon"
    assert "schon freigegeben" in _get("t8_anna", zweit.headers["location"]).text


def test_freigabe_post_ohne_csrf_403_und_ohne_wirkung():
    _werbung("Shop <news@shop.example>")
    r = _post_liste("t8_anna", "/post/aufraeumen/2025",
                    {"absender": ["news@shop.example"]}, csrf=False)
    assert r.status_code == 403
    assert server._q("select count(*) n from post_loeschfreigaben")[0]["n"] == 0


def test_freigabe_rolle_lesen_403():
    _werbung("Shop <news@shop.example>", besitzer="t8_leser")
    r = _post_liste("t8_leser", "/post/aufraeumen/2025",
                    {"absender": ["news@shop.example"]})
    assert r.status_code == 403
    assert server._q("select count(*) n from post_loeschfreigaben")[0]["n"] == 0
    # Die Vorschau zeigt dem Leser keinen Freigabe-Knopf.
    assert "löschen freigeben" not in _get("t8_leser", "/post/aufraeumen/2025").text


def test_jahr_muss_plausibel_sein():
    for jahr in ("abc", "1", "99999"):
        assert _get("t8_anna", f"/post/aufraeumen/{jahr}").status_code == 404
        assert _post_liste("t8_anna", f"/post/aufraeumen/{jahr}", {}).status_code == 404


def test_ohne_anmeldung_403():
    for pfad in ("/post/aufraeumen", "/post/aufraeumen/2025"):
        assert _get(None, pfad).status_code in (302, 303, 401, 403)


# --- Ziel ändern ----------------------------------------------------------

def test_aus_to_review_holen_schuetzt_absender():
    m = _ziel(_mail(von="Shop <news@shop.example>"), "to_review")
    r = _post("t8_anna", f"/post/mail/{m}/ziel", {"ziel": "posteingang"})
    assert r.status_code == 303
    z = _zeile(m)
    assert z["ziel"] == "posteingang" and z["ziel_manuell"] is True
    assert len(_regeln()) == 1
    # Von Zur Info in den Posteingang: nur diese Mail, keine Regel.
    n = _ziel(_mail(von="Bank <info@bank.example>"), "zur_info")
    assert _post("t8_anna", f"/post/mail/{n}/ziel", {"ziel": "posteingang"}).status_code == 303
    assert _zeile(n)["ziel"] == "posteingang" and _zeile(n)["ziel_manuell"] is True
    assert len(_regeln()) == 1


def test_ziel_nur_posteingang_oder_zur_info_und_mit_csrf():
    m = _ziel(_mail(), "to_review")
    for ziel in ("loeschen", "to_review", "quatsch", ""):
        assert _post("t8_anna", f"/post/mail/{m}/ziel", {"ziel": ziel}).status_code == 400
    assert _post("t8_anna", f"/post/mail/{m}/ziel", {"ziel": "posteingang"},
                 csrf=False).status_code == 403
    z = _zeile(m)
    assert z["ziel"] == "to_review" and z["ziel_manuell"] is False and not _regeln()
    # Die Mail-Seite bietet die zwei Knöpfe an.
    assert f"/post/mail/{m}/ziel" in _get("t8_anna", f"/post/mail/{m}").text


def test_ziel_fremde_mail_und_leser():
    privat = _ziel(_mail("t8_anna", "privat", "Familie & Freunde"), "zur_info")
    assert _post("t8_ben", f"/post/mail/{privat}/ziel",
                 {"ziel": "posteingang"}).status_code in (403, 404)
    assert _zeile(privat)["ziel"] == "zur_info"
    eigene = _ziel(_mail("t8_leser", "privat", "Familie & Freunde"), "zur_info")
    assert _post("t8_leser", f"/post/mail/{eigene}/ziel",
                 {"ziel": "posteingang"}).status_code == 403
    assert _zeile(eigene)["ziel"] == "zur_info"


# --- Isolation ------------------------------------------------------------

def test_fremde_freigabe_nicht_moeglich():
    _werbung("Shop <news@shop.example>", besitzer="t8_anna", betreff="Annas Werbung")
    _werbung("Mehr <x@mehr.example>", jahr=2023, besitzer="t8_ben")
    for name in ("t8_ben", "t8_lea"):
        seite = _get(name, "/post/aufraeumen").text
        assert "k-t8-anna" not in seite and "/post/aufraeumen/2025" not in seite
    assert "/post/aufraeumen/2023" in _get("t8_ben", "/post/aufraeumen").text
    # Annas Jahr gibt es für Ben nicht; ein Freigabe-Post trifft nur Bens eigene Daten.
    assert _get("t8_ben", "/post/aufraeumen/2025").status_code == 404
    assert "Annas Werbung" not in _get("t8_lea", "/post/aufraeumen/2025").text
    _post_liste("t8_lea", "/post/aufraeumen/2025", {"absender": ["news@shop.example"]})
    assert server._q("select count(*) n from post_loeschfreigaben "
                     "where besitzer = 't8_anna'")[0]["n"] == 0
    # Einen Besitzer-Parameter gibt es nicht: er wird ignoriert.
    assert "/post/aufraeumen/2025" not in _get(
        "t8_ben", "/post/aufraeumen?besitzer=t8_anna").text
