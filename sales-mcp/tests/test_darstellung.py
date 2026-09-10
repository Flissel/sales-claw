"""Vertragstests der Darstellung (Stufe 1): Escaping, Umlaute, Kuerzung, Zaehlungen.

Diese Datei prueft nicht, WAS die Oberflaeche kann, sondern ob das, was sie
zeigt, stimmt: ein kaufmaennisches Und bleibt ein kaufmaennisches Und, ein
Umlaut bleibt ein Umlaut, ein Satz endet nicht mitten im Wort.
"""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import ui  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

CLIENT = TestClient(ui.app)
HOST_OK = "127.0.0.1:8791"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", (
        f"Testsuite laeuft gegen Schema '{server.SCHEMA}' — erlaubt ist nur "
        f"'sales_test'.")


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")
    yield


def _get(pfad, host=HOST_OK):
    return CLIENT.get(pfad, headers={"host": host})


def _post(pfad, daten, host=HOST_OK):
    return CLIENT.post(pfad, data=daten, headers={"host": host},
                       follow_redirects=False)


def _lead(name="Max Bestand"):
    return str(server._q(
        "insert into leads (name, phone, source) values "
        "(%s, '+491701234567', 'whatsapp') returning id", (name,))[0]["id"])


def _termin_aktivitaet(lead_id, datum="2026-09-05", uhrzeit="19:00",
                       thema="Video Call mit Sophie & Stephane", ort=""):
    server._q(
        "insert into activities (lead_id, type, payload) "
        "values (%s, 'termin', %s::jsonb)",
        (lead_id, json.dumps(
            {"datum": datum, "uhrzeit": uhrzeit, "thema": thema, "ort": ort,
             "uid": f"test-{datum}-{uhrzeit}"})))


def test_kaufmaennisches_und_erscheint_einmal_escapet():
    """`&` im Termin-Thema wird genau einmal escapet — nie `&amp;amp;`."""
    _termin_aktivitaet(_lead("Stephane B."))
    seite = _get("/kalender").text
    assert "&amp;amp;" not in seite, "doppelt escapet"
    assert "&amp;amp\\;" not in seite, "dreifach escapet"
    assert "Sophie &amp; Stephane" in seite, (
        "das kaufmaennische Und fehlt oder ist falsch escapet")


# Wortliste statt Regex auf `ae|oe|ue`: ein Muster wuerde bei jedem
# englischen Wort und jeder E-Mail-Adresse anschlagen. Diese Liste
# enthaelt nur Woerter, die in der laufenden Oberflaeche gemessen wurden.
#
# Fix-Runde 2 (10.09.2026): ganze Woerter allein liessen Wortformen wie
# 'geaendert'/'unveraendert' oder 'ausgefuehrt' durchrutschen — keines der
# damaligen 25 Woerter ist Teilstring davon. Die untere Zeile ergaenzt
# Wortstaemme, die mehrere Formen auf einmal fangen, geprueft gegen echte
# Bezeichner in ui.py (Formularfeld-Namen, Routen), damit kein Stamm einen
# Bezeichner faelschlich trifft: 'bestaetig' etwa kollidiert mit
# `name="bestaetigt"`/`name="name_bestaetigt"` und bleibt deshalb draussen —
# 'Bestaetigung' (Grossschreibung, laengere Form) faengt denselben Fehler,
# ohne das Formularfeld zu treffen.
WOERTER_ASCII = [
    "aelteste", "naechste", "oeffnen", "Entwuerfe", "Entwuerfen",
    "Oberflaeche", "laedt", "Aendern", "aendern", "Groesse", "Loeschen",
    "loeschen", "gehoert", "klaert", "noetig", "moeglich", "zurueck",
    "Verlaeufe", "heisst", "Eingaenge", "Faellig", "Rueckruf",
    "Begruendung", "ausdruecklich", "Schluessel",
    # Wortstaemme (Fix-Runde 2): fangen Wortformen, die die Woerter oben
    # nicht als Teilstring enthalten.
    "aender", "Aender", "gueltig", "waehl", "staendig", "pruef",
    "ausgefuehr", "Bestaetigung",
]

SEITEN = ["/", "/freigaben", "/einordnung", "/kalender", "/kontakte",
          "/pipeline", "/ergebnisse", "/posteingang", "/medien", "/whatsapp"]


@pytest.mark.parametrize("pfad", SEITEN)
def test_seite_zeigt_echte_umlaute(pfad):
    """Keine ASCII-Umschreibung erreicht den Browser."""
    lead = _lead("Ena Ottenschläger")
    _termin_aktivitaet(lead)
    seite = _get(pfad).text
    gefunden = [w for w in WOERTER_ASCII if w in seite]
    assert not gefunden, (
        f"{pfad} zeigt ASCII-Umschreibungen: {gefunden}")


def test_csrf_fehlerseite_zeigt_echte_umlaute():
    """Der meisterreichte Fehlerpfad der ganzen Oberflaeche — ein POST ohne
    gueltiges CSRF-Token — steht auf keiner der zehn GET-Seiten und blieb
    deshalb in Fix-Runde 1 unentdeckt ASCII (Fix-Runde 2, 10.09.2026)."""
    antwort = _post("/aktion/freigeben",
                    {"draft_id": "00000000-0000-0000-0000-000000000000",
                     "csrf": "falsch"})
    seite = antwort.text
    gefunden = [w for w in WOERTER_ASCII if w in seite]
    assert not gefunden, (
        f"CSRF-Fehlerseite zeigt ASCII-Umschreibungen: {gefunden}")


def test_whatsapp_seite_nennt_aktive_und_archivierte_getrennt():
    """Zwei Zahlen, zwei Namen — nicht zweimal 'Kontakte'.

    Der Archiv-Schluessel ist verschachtelt (`enrichment -> ARCHIV_SCHLUESSEL
    -> 'archiviert'`, siehe `server._archiv_sql`/`server.ARCHIV_SCHLUESSEL`),
    nicht der flache `{"archiviert": true}` aus der ersten Fassung dieses
    Tests — der schrieb am Merkmal vorbei und zaehlte den Kontakt weiterhin
    als aktiv. `archiviert` ist hier ein echter jsonb-Boolean (`true`), keine
    Zeichenkette, damit die `jsonb_typeof`-Pruefung in `_archiv_sql` greift."""
    _lead("Aktiv Eins")
    archiv = _lead("Archiviert Eins")
    server._q(
        "update leads set enrichment = coalesce(enrichment, '{}'::jsonb) || "
        "jsonb_build_object(%s::text, jsonb_build_object('archiviert', true)) "
        "where id = %s", (server.ARCHIV_SCHLUESSEL, archiv))
    seite = _get("/whatsapp").text
    assert "1 aktive Kontakte" in seite or "1 aktiver Kontakt" in seite, (
        "die WhatsApp-Seite benennt die aktiven Kontakte nicht")
    assert "1 archiviert" in seite, (
        "die archivierten Kontakte werden nicht getrennt ausgewiesen")


def test_pipeline_hat_genau_eine_ueberschrift():
    seite = _get("/pipeline").text
    assert seite.count("<h1") == 1, (
        f"{seite.count('<h1')} h1-Elemente auf /pipeline, erwartet 1")


def test_favicon_wird_beantwortet():
    """Kein 404 bei jedem Seitenaufruf."""
    antwort = _get("/favicon.ico")
    assert antwort.status_code in (200, 204), (
        f"/favicon.ico antwortet mit {antwort.status_code}")


# ---------------------------------------------------------------------------
# Aufgabe 7: Texte an Wortgrenzen kuerzen (10.09.2026) — Karten- und
# Verlaufstexte brachen hart nach einer festen Zeichenzahl ab, mitten im
# Wort: auf der Startseite endete ein Termin mit „… Thema Vibe ·", im
# Monatsgitter stand „Kennenlernen Förderini". `ui._kurz` schneidet nur an
# einer Wortgrenze und markiert das Abschneiden sichtbar.
# ---------------------------------------------------------------------------

def test_kuerzung_bricht_nicht_mitten_im_wort():
    lang = ("Martin bestätigt per WhatsApp Interesse und Termin Donnerstag "
            "14 Uhr; der Betreiber trägt 14:30 im Kalender ein")
    kurz = ui._kurz(lang, 60)
    assert kurz.endswith("…"), "gekuerzter Text sagt nicht, dass er gekuerzt ist"
    assert len(kurz) <= 61, f"zu lang: {len(kurz)}"
    rumpf = kurz[:-1].rstrip()
    assert lang.startswith(rumpf), "der Anfang stimmt nicht mehr"
    assert not rumpf or lang[len(rumpf):len(rumpf) + 1] in ("", " "), (
        f"mitten im Wort abgeschnitten: …{rumpf[-15:]}")


def test_kurzer_text_bleibt_unveraendert():
    assert ui._kurz("Optimal", 60) == "Optimal"


def test_terminkarte_auf_startseite_zeigt_vollen_text_als_title():
    """Die Terminkarte auf '/' (Termine ohne festes Datum) kuerzt sichtbar
    an einer Wortgrenze und traegt den vollen Text als title-Attribut —
    escaped, denn ein Kundentext gehoert nie roh in ein Attribut."""
    lang = ("Martin bestätigt per WhatsApp Interesse & Termin Donnerstag "
            "14 Uhr <script>boese()</script>; der Betreiber trägt 14:30 "
            "im Kalender ein, Thema Vibe · Förderung")
    lead = _lead("Karla Karte")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'termin', %s::jsonb)",
        (lead, json.dumps({"inhalt": lang})))
    seite = _get("/").text
    assert "<script>boese()</script>" not in seite, "ungekuerztes Skript im Markup"
    assert f'title="{ui._e(lang)}"' in seite, (
        "der volle Text steht nicht escaped als title im Markup")
    assert ui._e(ui._kurz(lang, 160)) in seite, (
        "der sichtbare, gekuerzte Text fehlt")


def test_verlaufszeile_termin_auf_freigaben_kuerzt_an_wortgrenze():
    lang_thema = ("Kennenlernen Förderinitiative für kleine Betriebe mit "
                  "vielen Details, die eigentlich niemand lesen will")
    lead = _lead("Ver Lauf")
    _termin_aktivitaet(lead, datum="2026-09-05", uhrzeit="10:00",
                       thema=lang_thema)
    seite = _get("/freigaben").text
    assert ui._kurz(lang_thema, 120) in seite
    assert f'title="{ui._e(lang_thema)}"' in seite


def test_monatsgitter_titel_kuerzt_an_wortgrenze_und_traegt_titel():
    lang_thema = "Kennenlernen Förderinitiative für kleine Betriebe"
    lead = _lead("Monat Gitter")
    _termin_aktivitaet(lead, datum="2026-09-05", uhrzeit="10:00",
                       thema=lang_thema)
    seite = _get("/kalender?monat=2026-09").text
    assert ui._kurz(lang_thema, 22) in seite
    assert f'title="{ui._e(lang_thema)}"' in seite


# ---------------------------------------------------------------------------
# Nachtrag (10.09.2026, Koordinator-Rueckmeldung): dieselbe Fehlerklasse
# (Fließtext, hart abgeschnitten, keine Wortgrenze) steckte an drei weiteren
# Anzeigestellen, die der urspruengliche Auftrag nicht namentlich aufzaehlte,
# aber die Spec allgemein verlangt (§3.5: kein Anzeigetext endet mitten im
# Wort). Alle drei liegen in ui.py und wurden nachgezogen.
# ---------------------------------------------------------------------------

def test_entwurfsvorschau_kuerzt_an_wortgrenze_und_traegt_titel():
    """Die zugeklappte Entwurfskarte auf /freigaben (und /) zeigte bisher
    eine Vorschau, die hart bei 90 Zeichen abbrach — OHNE jedes Kuerzungs-
    zeichen, ein Entwurf wirkte einfach mittendrin zu Ende."""
    lang = ("Hallo Herr Beispiel, vielen Dank fuer Ihr Interesse an unserer "
            "Beratung — wann passt Ihnen ein kurzer Rueckruf diese Woche?")
    lead = _lead("Ella Entwurf")
    server._q(
        "insert into drafts (lead_id, channel, recipient, body, status) "
        "values (%s, 'whatsapp', '+491701234567', %s, 'pending')",
        (lead, lang))
    seite = _get("/freigaben").text
    assert ui._e(ui._kurz(lang, ui.ENTWURF_VORSCHAU)) in seite
    assert f'title="{ui._e(lang)}"' in seite
    assert "…" in seite


def test_ergebnisse_begruendung_kuerzt_an_wortgrenze_und_traegt_titel():
    lang = ("Kontakt hat sich nach mehrfacher Rueckfrage endgueltig gegen "
            "eine Zusammenarbeit entschieden, Gruende privat, nicht Preis")
    lead = _lead("Gustav Gewonnen")
    server._q("update leads set status = 'won' where id = %s", (lead,))
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'stufenwechsel', %s::jsonb)",
        (lead, json.dumps({"begruendung": lang})))
    seite = _get("/ergebnisse").text
    assert ui._e(ui._kurz(lang, 160)) in seite
    assert f'title="{ui._e(lang)}"' in seite


def test_firmenrecherche_text_kuerzt_an_wortgrenze_und_traegt_titel():
    lang = ("Wir sind ein inhabergefuehrter Betrieb mit langjaehriger "
            "Erfahrung in der Beratung kleiner und mittlerer Unternehmen " * 3)
    lead = _lead("Firma Recherche")
    server._q(
        "update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'), "
        "'{firma}', %s::jsonb, true) where id = %s",
        (json.dumps({"website": "https://beispiel.de",
                     "seiten": [{"url": "https://beispiel.de/ueber",
                                "typ": "ueber", "titel": "Über uns",
                                "text": lang}]}), lead))
    seite = _get(f"/kontakte/{lead}").text
    text_normalisiert = " ".join(lang.split())
    assert ui._e(ui._kurz(text_normalisiert, 300)) in seite
    assert f'title="{ui._e(text_normalisiert)}"' in seite


# ---------------------------------------------------------------------------
# Aufgabe 8 (10.09.2026): „Heute" zaehlt ehrlich — `termine_offen` stand
# bereits bereit (fuer die Anzeige der Termin-Kacheln), fehlte aber in der
# Summe `offen`. Gemessen: Kopfzeile „1 Entscheidung wartet auf dich. Alles
# andere laeuft.", waehrend zwei Terminanfragen ohne Datum darunter standen.
# ---------------------------------------------------------------------------

def test_heute_zaehlt_terminanfragen_mit():
    """Eine Terminanfrage ohne Datum zaehlt als offener Posten.

    Gemessen 10.09.2026: die Kopfzeile sagte „1 Entscheidung wartet auf
    dich. Alles andere laeuft.", waehrend darunter ZWEI Terminanfragen
    ohne Datum standen — `termine_offen` fehlte in der Summe.
    """
    lead = _lead("Offen Eins")
    _termin_aktivitaet(lead, datum="", uhrzeit="",
                       thema="Donnerstag 16 Uhr — welcher?")
    _termin_aktivitaet(lead, datum="", uhrzeit="",
                       thema="Freitag vormittags?")
    seite = _get("/").text
    assert "1 Entscheidung" not in seite, (
        "zwei Terminanfragen wurden als eine gezaehlt")
    assert "2 " in seite, "die Kopfzeile nennt die zwei Anfragen nicht"


def test_heute_behauptet_keine_ruhe_wenn_etwas_offen_ist():
    """„Alles andere laeuft" darf nicht neben offenen Posten stehen."""
    lead = _lead("Offen Zwei")
    _termin_aktivitaet(lead, datum="", uhrzeit="", thema="Wann genau?")
    seite = _get("/").text
    assert "Alles andere läuft" not in seite and "Alles andere laeuft" not in seite


def test_heute_meldet_ruhe_bei_leerer_datenbank():
    seite = _get("/").text
    assert "Nichts wartet auf dich" in seite


def test_heute_chips_und_satz_stammen_aus_derselben_rechnung():
    """Zeigt der Termine-Chip eine Zahl > 0, darf „Keine offenen
    Entwuerfe" nicht mehr erscheinen — Chips und Satz duerfen sich nicht
    mehr widersprechen koennen (gemessen 10.09.2026: Chip „Termine 2" neben
    „Keine offenen Entwuerfe").
    """
    lead = _lead("Chip Konsistenz")
    _termin_aktivitaet(lead, datum="", uhrzeit="", thema="Welcher Tag?")
    seite = _get("/").text
    assert '<span class="badge termin">Termine</span><b>1</b>' in seite
    assert "Keine offenen Entwürfe" not in seite
