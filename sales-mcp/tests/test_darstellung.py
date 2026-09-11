"""Vertragstests der Darstellung (Stufe 1): Escaping, Umlaute, Kuerzung, Zaehlungen.

Diese Datei prueft nicht, WAS die Oberflaeche kann, sondern ob das, was sie
zeigt, stimmt: ein kaufmaennisches Und bleibt ein kaufmaennisches Und, ein
Umlaut bleibt ein Umlaut, ein Satz endet nicht mitten im Wort.
"""
import ast
import json
import os
import re

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


# ---------------------------------------------------------------------------
# Fix-Runde 3 (10.09.2026, Schlusspruefung Mangel 1): der seitenbasierte
# Waechter oben hat zwei Luecken, beide in der Schlusspruefung gemessen:
# (a) er ist case-sensitiv — 'zurueck' klein in WOERTER_ASCII faengt
# 'Zurueck' gross im Code NICHT, darum blieb test_csrf_fehlerseite_... gruen,
# obwohl genau diese Seite "Zurueck" zeigte; (b) SEITEN oben deckt nur zehn
# GET-Seiten ab, nicht /kontakte/{id}, /wiedervorlagen,
# /freigaben/verlauf/{art} oder jede Warnseite — dort lag die Haelfte der
# Funde. Dieser Test prueft stattdessen JEDES String-Literal in ui.py direkt
# (per ast, siehe _ui_string_literale) — unabhaengig davon, ob und wo eine
# Seite es gerade rendert, und case-insensitiv. Der alte, seitenbasierte
# Test bleibt bestehen (er belegt zusaetzlich, dass beim Rendern nichts an
# den Literalen kaputtgeht), ist aber ab jetzt nicht mehr die tragende
# Absicherung — das ist dieser hier.
# ---------------------------------------------------------------------------

# Erweiterung von WOERTER_ASCII um Woerter, die in der Seiten-Liste oben
# BEWUSST fehlen, weil sie dort Bezeichner treffen wuerden (siehe Kommentar
# an WOERTER_ASCII: 'ueber', 'Empfaenger', 'traegt' u.ae. wuerden auf
# Seitenebene an CSS-Klassen/Routen/Feldnamen anschlagen). Auf Literal-Ebene
# mit Wortgrenzen (\b) ist das ungefaehrlich: ein Formularfeld wie
# 'empfaenger_bestaetigt' ist per Unterstrich zu einem einzigen \b-Wort
# verschmolzen und wird von \bempfaenger\b nicht getroffen — zusaetzlich
# faengt _ist_technisches_literal bare Bezeichner/Routen/SQL ohnehin vorher
# ab. Jedes Wort hier wurde gegen den aktuellen Stand von ui.py verifiziert
# (keine verbleibenden Bezeichner-Treffer ausser den zwei Routen unten).
LITERAL_WOERTER_ASCII = WOERTER_ASCII + [
    "spaeter", "ueberschreibung", "nachtraegt", "vergroessern",
    "geschaeftsverweise", "traegt", "entwurfszustaende", "fuellung",
    "farbunabhaengiges", "bloecken", "fuer", "hoehe",
    "entscheidungsknoepfe", "verdraengt", "muessen", "spaltenueberschrift",
    "ausschliesslich", "ueber", "gefaehrliche", "rueckt", "zusaetzlich",
    "faehrt", "haengen", "groesser", "haengt", "uebernimmt",
    "zustaendige", "haekchen", "empfaenger", "luege", "saehe",
    "vollzaehlig", "taeuschte", "aufraeumen", "laesst", "laeuft",
    "eintraege", "maerz", "zurueckholen", "geloescht", "aktivitaeten",
    "verstaendliches", "vertraege", "enthaelt",
]

_LITERAL_MUSTER = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in LITERAL_WOERTER_ASCII) + r")\b",
    re.IGNORECASE)

_ROUTE_RE = re.compile(r"^/[a-z0-9/_-]*$")
_BEZEICHNER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# ---------------------------------------------------------------------------
# Fix-Runde 4 (10.09.2026, Waechter-Fix): die Ausnahmeregeln pruefen bisher
# per Teilstring-Suche auf dem GANZEN Literal, statt zu pruefen, ob das
# Literal ALS GANZES technisch ist. Zwei belegte Folgen (siehe
# .superpowers/sdd/2026-09-10-sales-ui-stufe-1-wahrheit-und-fehler/
# waechter-fix-report.md):
#   (a) `_STIL` (ui.py:634) ist EIN einziges 23.545 Zeichen langes Literal
#       (Python verschmilzt die aneinandergehaengten Teile zu einem
#       ast.Constant). Die CSS-Regel 'select, input[type="text"] {'
#       (ui.py:1011/1059) enthaelt das Wort 'select' als CSS-Selektor —
#       `_SQL_RE.search()` stufte dadurch den GANZEN Block als technisch
#       ein und ueberspringt seither rund 19 deutsche CSS-Kommentare.
#   (b) `_EINGEBETTETE_ROUTEN` exemptierte ebenfalls per Teilstring: das
#       Literal bei ui.py:1664 enthaelt sowohl
#       `action="/medien/loeschen-bestaetigen"` als auch 312 Zeichen echten
#       Anzeigetext ("Das ist ein echtes Loeschen. ...") — der Anzeigetext
#       blieb dadurch ungeprueft mit-exemptiert.
#
# Fix, zwei Teile:
#   1. `_SQL_RE` erkennt SQL nur noch als PRAEFIX ('^select\b' o.ae.), und
#      `_technische_fragmente()` zerlegt jedes Literal in Zeilen und prueft
#      JEDE Zeile einzeln (`_ist_technisches_fragment`) statt das ganze
#      Literal auf einmal freizusprechen. Bei `_STIL` exemptiert eine
#      CSS-Selektor-Zeile, die mit 'select' BEGINNT, nur sich selbst, nicht
#      ihre ~800 Nachbarzeilen.
#   2. Damit faellt aber jede Zeile durch, die technischen UND
#      Anzeigetext-Anteil mischt — genau der Fall bei ui.py:1539/1664, wo
#      eine Route als `action="..."`-Attributwert oder ein Formularfeld
#      als `name="..."`-Attributwert MITTEN in einer sonst normalen
#      HTML-Zeile steht (belegt: ohne Maskierung meldet der Waechter
#      faelschlich 'loeschen' aus `action="/medien/loeschen"` und
#      'begruendung' aus `name="begruendung"` als ASCII-Fund, obwohl beide
#      Bezeichner/Routen sind, keine Prosa). `_ohne_technische_
#      attributwerte()` maskiert deshalb NUR den Wert eines `action=`- oder
#      `name=`-Attributs, und auch nur, wenn dieser Wert fuer sich genommen
#      Route oder Bezeichner ist (`_ROUTE_RE`/`_BEZEICHNER_RE`, dieselben
#      Pruefungen wie fuer ein eigenstaendiges Literal) — das ist strukturell
#      begruendet (HTML-Attributsyntax), keine Teilstring-Suche nach
#      irgendeinem Wort irgendwo.
#
# `_EINGEBETTETE_ROUTEN` entfaellt komplett: beide Routen sind an ihrer
# eigentlichen Stelle (ui.py:5231/5233, den Starlette-`Route(...)`-
# Konstanten) je ein eigenes, einzeiliges Literal, das `_ROUTE_RE` bereits
# direkt per Vollmatch erkennt; als eingebetteter Attributwert deckt sie
# jetzt `_ohne_technische_attributwerte` ab. Das Fragment bei ui.py:1664
# ist damit NICHT mehr blockweise exemptiert — nur sein `action=`-Anteil
# ist maskiert, sein Anzeigetext bleibt geprueft.
# ---------------------------------------------------------------------------
#
# Fix-Runde 5 (10.09.2026, Nachpruefung): Fix-Runde 4 exemptierte eine
# SQL-praefigierte Zeile noch immer als GANZES — dieselbe Verwechslungs-
# Klasse wie in Runde 4, nur eine Groessenordnung kleiner. Belegt: ein
# Kommentar ans Zeilenende der CSS-Selektor-Zeile gehaengt
# ('select, input[type="text"] { /* mindesthoehe ueberschreibung */')
# wurde NICHT gefangen, weil `_SQL_RE.match` am Zeilenanfang trifft und
# `_ist_technisches_fragment` die Zeile dann komplett ueberspringt — auch
# den Teil HINTER der Uebereinstimmung. Auf einer eigenen Zeile wird
# derselbe Kommentar korrekt gefangen (dort greift kein SQL-Praefix).
# Fix: `_ohne_sql_praefix` schneidet nur das technische STUECK ab, nicht
# die ganze Zeile — bei einer CSS-Regel bis zur ersten oeffnenden Klammer
# '{' (danach kann, wie hier belegt, ein Kommentar folgen), sonst (keine
# '{' auf der Zeile — jede echte SQL-Anweisung in ui.py, verifiziert)
# weiterhin bis zum Zeilenende. Der Rest hinter der Klammer wird wie jede
# andere Zeile geprueft (inkl. Attributwert-Maskierung).
# ---------------------------------------------------------------------------
_SQL_RE = re.compile(r"^(select|insert into|update|delete from)\b",
                     re.IGNORECASE)
_ATTR_WERT_RE = re.compile(r'((?:action|name)=")([^"]*)(")')


def _ist_technisches_fragment(s: str) -> bool:
    """True fuer ein Fragment — ein ganzes einzeiliges Literal ODER eine
    einzelne Zeile eines mehrzeiligen Literals (siehe
    `_technische_fragmente`) —, das ALS GANZES strukturell KEIN Anzeigetext
    ist, sondern Bezeichner oder Route: nie als Prosa an den Browser
    ausgeliefert, sondern als Formularfeld-Name, Payload-/Dict-Schluessel
    (z.B. 'eintraege', 'vertraege', 'begruendung' — Vertrag mit server.py,
    Umbenennen bricht gespeicherte Payloads) oder Routen-Pfad verwendet.
    Jede Pruefung bezieht sich auf das Fragment ALS GANZES (Vollmatch) —
    nie auf ein Vorkommen irgendwo darin (Fix-Runde 4). SQL/CSS-Selektor
    ist HIER bewusst NICHT geprueft: das technische Stueck kann kuerzer
    sein als die Zeile (Fix-Runde 5) — siehe `_ohne_sql_praefix`.
    Randbedingung: Bezeichner sind tabu."""
    kern = s.strip()
    if not kern:
        return True
    if _BEZEICHNER_RE.fullmatch(kern):
        return True
    if _ROUTE_RE.match(kern):
        return True
    return False


def _ohne_sql_praefix(kern: str) -> str | None:
    """Schneidet ein SQL-/CSS-Selektor-Praefix ab (`_SQL_RE`) und liefert
    NUR den Rest danach zurueck — nicht (wie bis Fix-Runde 4) die ganze
    Zeile. Das technische Stueck reicht bis zur ERSTEN oeffnenden Klammer
    '{' (der CSS-Regelkoerper, z.B. beim 'select'-Selektor in `_STIL`);
    danach kann im CSS ein Kommentar auf derselben Zeile folgen (Fix-Runde
    5, belegt) und muss geprueft werden. Ohne '{' auf der Zeile — jede
    echte SQL-Anweisung in ui.py, keine enthaelt eine '{' — bleibt die
    gesamte Zeile technisch. Liefert None, wenn `kern` gar nicht mit SQL
    beginnt (dann ist die Zeile normal zu behandeln)."""
    if not _SQL_RE.match(kern):
        return None
    klammer = kern.find("{")
    return kern[klammer + 1:] if klammer != -1 else ""


def _ohne_technische_attributwerte(zeile: str) -> str:
    """Maskiert `action="..."`/`name="..."`-Attributwerte, die fuer sich
    genommen Route oder Bezeichner sind (siehe Fix-Runde 4, Teil 2), bevor
    die Zeile auf ASCII-Umschreibungen geprueft wird. Nur der Wert in genau
    dieser Attributposition zaehlt, und nur wenn er selbst
    `_ROUTE_RE`/`_BEZEICHNER_RE` erfuellt — keine Teilstring-Suche nach dem
    Wort irgendwo in der Zeile.

    Bewusst NUR `action=`/`name=` (Fix-Runde 5, Rest 2): weitere
    Attribute wie `href=`, `value=`, `id=`, `class=` koennen ebenfalls
    Route-/Bezeichner-Werte tragen und wuerden von dieser Funktion GENAUSO
    sicher behandelt (die Absicherung ist der Wert selbst, nicht der
    Attributname) — sie fehlen hier nur, weil kein aktuelles `ui.py`-
    Vorkommen sie braucht (verifiziert: volle Suite gruen ohne sie). EIN
    Attribut ist bewusst NICHT hier und darf es auch nie werden:
    `placeholder=` traegt echten Anzeigetext (siehe ui.py:4168,
    `placeholder="Begründung (empfohlen)"`) und muss immer geprueft
    bleiben, selbst wenn ein Wert zufaellig identifier-foermig aussehen
    sollte. Falls die kommende Optik-Ueberarbeitung ein neues `href=`/
    `value=`/`id=`/`class=` mit Route- oder Bezeichner-Wert einfuehrt und
    dieser Test dadurch faelschlich anschlaegt (der SICHERE Fehlschlag —
    zu viele Meldungen, keine stillen Luecken): den Attributnamen zur
    Alternative in `_ATTR_WERT_RE` ergaenzen, NICHT `placeholder`."""
    def ersetze(treffer):
        praefix, wert, suffix = treffer.groups()
        if _ROUTE_RE.match(wert) or _BEZEICHNER_RE.fullmatch(wert):
            return praefix + suffix
        return treffer.group(0)
    return _ATTR_WERT_RE.sub(ersetze, zeile)


def _technische_fragmente(s: str):
    """Zerlegt ein Literal in seine Zeilen und liefert die NICHT
    rein-technischen zurueck: eine als GANZES technische Zeile (blank,
    Bezeichner, Route) faellt komplett weg; bei einer SQL-/CSS-Selektor-
    Zeile faellt nur ihr technisches Praefix weg (`_ohne_sql_praefix`,
    Fix-Runde 5) und der Rest wird — wie jede andere Zeile — um
    eingebettete technische Attributwerte bereinigt
    (`_ohne_technische_attributwerte`) und zurueckgegeben. Fuer ein
    einzeiliges Literal (der Regelfall) ist das gleichwertig zur alten,
    literal-weiten Pruefung. Fuer ein mehrzeiliges Literal — in ui.py nur
    `_STIL`, siehe Fix-Runde 4 — exemptiert eine technische Zeile nur sich
    selbst, nicht ihre Nachbarn."""
    for zeile in s.split("\n"):
        if _ist_technisches_fragment(zeile):
            continue
        kern = zeile.strip()
        rest = _ohne_sql_praefix(kern)
        if rest is not None:
            if not rest.strip():
                continue
            kern = rest
        yield _ohne_technische_attributwerte(kern)


def _ui_string_literale():
    """Alle String-Literale in ui.py ausserhalb von Docstrings, mit
    Zeilennummer — dieselbe ast-Technik, mit der die Schlussfixes die
    ASCII-Funde selbst aufgespuert haben. Echte Python-Kommentare (`#`) sind
    fuer ast ohnehin nie Literale und tauchen hier gar nicht erst auf."""
    quelltext = open(ui.__file__, encoding="utf-8").read()
    baum = ast.parse(quelltext)
    docstring_ids = set()
    for node in ast.walk(baum):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstring_ids.add(id(body[0].value))
    treffer = []
    for node in ast.walk(baum):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstring_ids and node.value):
            treffer.append((node.lineno, node.value))
    return treffer


def test_literale_zeigen_echte_umlaute():
    """Jedes Anzeigetext-Literal in ui.py, unabhaengig davon, ob/wo eine
    Seite es gerade rendert — schliesst die zwei Luecken des seitenbasierten
    Waechters oben (Gross-/Kleinschreibung, unvollstaendige Seitenliste).
    Ersetzt test_seite_zeigt_echte_umlaute NICHT (der bleibt als
    Rendering-Beleg stehen), ist aber ab Fix-Runde 3 die tragende
    Absicherung gegen ASCII-Umschreibungen (Schlusspruefung, 10.09.2026).

    Prueft je Literal jede Zeile einzeln (`_technische_fragmente`, siehe
    Fix-Runde 4) — bei einem mehrzeiligen Literal wie `_STIL` exemptiert
    eine technische Zeile nur sich selbst, nicht den ganzen Block."""
    funde = []
    for lineno, s in _ui_string_literale():
        for zeile in _technische_fragmente(s):
            treffer = sorted(set(_LITERAL_MUSTER.findall(zeile)))
            if treffer:
                funde.append((lineno, treffer, zeile.strip()[:80]))
    assert not funde, (
        "ui.py enthaelt ASCII-Umschreibungen in Anzeigetext-Literalen "
        "(Zeile: Woerter: Auszug): "
        + "; ".join(f"{z}: {w}: {s!r}" for z, w, s in funde))


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
    assert "1 aktiver Kontakt" in seite, (
        "die WhatsApp-Seite verwendet bei genau einem aktiven Kontakt nicht "
        "die grammatisch richtige Einzahl (bisher: '1 aktive Kontakte')")
    assert "1 aktive Kontakte" not in seite, (
        "die Mehrzahlform steht faelschlich bei genau einem aktiven Kontakt")
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


# ---------------------------------------------------------------------------
# Fix-Runde 3 (10.09.2026, Schlusspruefung Mangel 2): die feste Schwelle
# `laenge // 3 * 2` versagte bei kleinen `laenge`-Werten wie 22
# (Monatsgitter) — die Wortgrenze lag ausserhalb der Schwelle, der Schnitt
# fiel mitten ins Wort ("Kennenlernen Förderini…"). Diese Eigenschafts-
# pruefung laeuft ueber ALLE real vorkommenden `laenge`-Werte (22, 60, 80,
# 90, 120, 160, 300 — siehe die Aufrufstellen in ui.py) mit echten,
# real langen Anzeigetexten und behauptet nur EINE Eigenschaft: das Ergebnis
# endet nie mitten in einem Wort. Ergaenzt test_kuerzung_bricht_nicht_
# mitten_im_wort (der bleibt als konkreter Regressionsbeleg fuer den
# urspruenglich gemessenen Fall stehen).
# ---------------------------------------------------------------------------

_KUERZUNG_TEXTE = [
    ("Kennenlernen Förderinitiative für kleine Betriebe mit vielen "
     "Details, die eigentlich niemand lesen will", 22),
    ("Videogespräch Erstberatung zum Thema Fördermittel und Zeitplan für "
     "die naechsten Schritte", 22),
    ("Martin bestätigt per WhatsApp Interesse und Termin Donnerstag "
     "14 Uhr; der Betreiber trägt 14:30 im Kalender ein", 60),
    ("Hallo Herr Beispiel, vielen Dank für Ihr Interesse an unserer "
     "Beratung — wann passt Ihnen ein kurzer Rückruf diese Woche?", 80),
    ("Hallo Herr Beispiel, vielen Dank für Ihr Interesse an unserer "
     "Beratung — wann passt Ihnen ein kurzer Rückruf diese Woche?", 90),
    ("Diese Freigabe traegt keinen Stand des gelesenen Textes — Seite neu "
     "laden und aus der aktuellen Ansicht freigeben, sonst geht der "
     "falsche Text raus.", 120),
    ("Kontakt hat sich nach mehrfacher Rückfrage endgültig gegen eine "
     "Zusammenarbeit entschieden, Gründe privat, nicht Preis, und moechte "
     "auch in Zukunft nicht mehr kontaktiert werden.", 160),
    (("Wir sind ein inhabergeführter Betrieb mit langjähriger Erfahrung "
      "in der Beratung kleiner und mittlerer Unternehmen ") * 3, 300),
]


@pytest.mark.parametrize("lang,laenge", _KUERZUNG_TEXTE)
def test_kuerzung_bricht_nie_mitten_im_wort(lang, laenge):
    """Eigenschaftspruefung ueber alle real vorkommenden Laengen: das
    Zeichen direkt nach dem gekuerzten Rumpf ist im Original KEIN
    Wortzeichen (Buchstabe/Ziffer) mehr — nie mitten im Wort. `_kurz`
    strippt am Wortende bewusst auch Satzzeichen (` ,;:·-–—`), darum haengt
    z.B. nach „…freigeben" im Original noch ein Komma, was legitim ist und
    kein Wortabbruch — nur ein direkt anschliessender Buchstabe/eine Ziffer
    waere ein echter Fund."""
    kurz = ui._kurz(lang, laenge)
    assert kurz.endswith("…"), f"nicht als gekuerzt markiert: {kurz!r}"
    rumpf = kurz[:-1].rstrip()
    assert lang.startswith(rumpf), f"Anfang stimmt nicht: {rumpf!r}"
    rest = lang[len(rumpf):len(rumpf) + 1]
    assert not rumpf or not rest.isalnum(), (
        f"mitten im Wort abgeschnitten bei laenge={laenge}: …{rumpf[-20:]}")


def test_kuerzung_ohne_leerzeichen_schneidet_hart():
    """Eine lange URL ohne Leerzeichen hat keine Wortgrenze zum Schneiden —
    dort bleibt der harte Schnitt bewusst das kleinere Uebel (siehe
    Kommentar an `_kurz`), die obige Eigenschaftspruefung gilt hier NICHT."""
    lang = "https://beispiel.de/" + "x" * 300
    kurz = ui._kurz(lang, 60)
    assert kurz.endswith("…")
    assert len(kurz) <= 61
    assert lang.startswith(kurz[:-1])


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


# Die folgenden Tests heissen bewusst "...verwendet_kurz..." statt
# "...kuerzt_an_wortgrenze...": `assert ui._kurz(x, n) in seite` vergleicht
# die Ausgabe von `_kurz` mit sich selbst und waere auch gruen, wenn `_kurz`
# gar nicht kuerzte (Fix-Runde 3, Schlusspruefung Mangel 2). Ihr Zweck ist
# die VERDRAHTUNG: dass jede Seite `_kurz` mit dem richtigen `laenge`-Wert
# aufruft, den vollen Text escaped als `title` mitgibt und das Ergebnis auch
# tatsaechlich rendert. Die Wortgrenzen-EIGENSCHAFT selbst ist unabhaengig
# davon in test_kuerzung_bricht_nie_mitten_im_wort abgesichert (parametrisiert
# ueber dieselben `laenge`-Werte, die hier verwendet werden).

def test_verlaufszeile_termin_auf_freigaben_verwendet_kurz():
    lang_thema = ("Kennenlernen Förderinitiative für kleine Betriebe mit "
                  "vielen Details, die eigentlich niemand lesen will")
    lead = _lead("Ver Lauf")
    _termin_aktivitaet(lead, datum="2026-09-05", uhrzeit="10:00",
                       thema=lang_thema)
    seite = _get("/freigaben").text
    assert ui._kurz(lang_thema, 120) in seite
    assert f'title="{ui._e(lang_thema)}"' in seite


def test_monatsgitter_titel_verwendet_kurz_und_traegt_titel():
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

def test_entwurfsvorschau_verwendet_kurz_und_traegt_titel():
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


def test_ergebnisse_begruendung_verwendet_kurz_und_traegt_titel():
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


def test_firmenrecherche_text_verwendet_kurz_und_traegt_titel():
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


# ---------------------------------------------------------------------------
# Mangel 3 (Schlusspruefung, 10.09.2026): „N Posten warten auf dich" speiste
# sich aus gedeckelten Abfragen (`termine_offen` limit 5, `_offene_
# wiedervorlagen` limit 200, `server._einzuordnende` limit 25) — bei mehr
# als dem jeweiligen Deckel nennt „Heute" wieder eine zu kleine Zahl,
# dieselbe Unehrlichkeit wie in Aufgabe 8, nur an drei weiteren Stellen.
# Fix: echte Gesamtzahlen per Zaehlabfrage statt der gedeckelten
# Listenlaengen; die Kachel/Karten-Anzeige bleibt gedeckelt, zeigt das aber
# jetzt ("X von Y gezeigt").
# ---------------------------------------------------------------------------

def test_heute_zaehlt_mehr_als_fuenf_termine_ohne_datum_korrekt():
    """`termine_offen` zeigt (auf der Startseite) hoechstens 5 Karten, die
    Kopfzeile und der Termine-Chip muessen aber die ECHTE Zahl nennen —
    sieben Terminanfragen ohne Datum duerfen nicht als fuenf gezaehlt
    werden."""
    for i in range(7):
        lead = _lead(f"Sieben Termine {i}")
        _termin_aktivitaet(lead, datum="", uhrzeit="", thema=f"Frage {i}?")
    seite = _get("/").text
    assert '<span class="badge termin">Termine</span><b>7</b></span>' in seite, (
        "der Termine-Chip zeigt nicht die echte Zahl (7), sondern den "
        "Kartendeckel")
    assert "7 Terminanfragen" in seite, (
        "die Kopfzeile nennt nicht die echten sieben Terminanfragen")
    assert "5 von 7 gezeigt" in seite, (
        "kein Hinweis, dass die Kartenliste nur einen Teil der sieben zeigt")


def test_heute_zaehlt_mehr_als_einordnung_deckel_korrekt():
    """`server._einzuordnende` deckelt die Chat-/Anzeigefassung auf
    EINORDNUNG_LIMIT (25) Zeilen — mehr als 25 unbekannte Absender duerfen
    auf der Startseite trotzdem nicht als 25 gezaehlt werden."""
    assert server.EINORDNUNG_LIMIT == 25, (
        "Testannahme veraltet: EINORDNUNG_LIMIT hat sich geaendert")
    sammel = str(server._q(
        "insert into leads (name, source) values "
        "('Unbekannte Eingaenge', 'system') returning id")[0]["id"])
    vorher = server.UNBEKANNT_LEAD_ID
    server.UNBEKANNT_LEAD_ID = sammel
    try:
        anzahl = server.EINORDNUNG_LIMIT + 3
        for i in range(anzahl):
            absender = f"4917000{i:05d}@c.us"
            server._q(
                "insert into activities (lead_id, type, payload, actor) "
                "values (%s, 'kundenantwort', %s, 'human')",
                (sammel, json.dumps({
                    "text": f"Hallo, Nummer {i}?", "richtung": "eingehend",
                    "absender": absender,
                    "message_id": f"wa-{absender}-{i}"})))
        seite = _get("/").text
        assert f"{anzahl} Einordnungen" in seite, (
            f"die Kopfzeile zaehlt nicht die echten {anzahl} unbekannten "
            f"Absender, sondern hoechstens den Deckel "
            f"({server.EINORDNUNG_LIMIT})")
    finally:
        server.UNBEKANNT_LEAD_ID = vorher


# ---------------------------------------------------------------------------
# Aufgabe 6 (11.09.2026): der Einladungsstand im Kontakt-Verlauf. Die
# Aktivitaet `einladung_antwort` (Aufgabe 4/5) traegt den Rueckmeldestatus
# ROH aus der Kalenderantwort (ACCEPTED/DECLINED/TENTATIVE/NEEDS-ACTION) —
# die Seite uebersetzt ihn nur beim Rendern, wie es das bestehende Muster
# ZUSTAND_TITEL/TERMIN_TITEL fuer Entwuerfe und Termine bereits vormacht.
# ---------------------------------------------------------------------------

def test_einladungsstand_erscheint_am_kontakt():
    """Die zwei Assertions aus dem Brief woertlich — PLUS zwei staerkere
    (Fund beim RED-Lauf, 11.09.2026): `"abgesagt" in seite.lower()` ist auf
    JEDER /kontakte/{id}-Seite schon VOR jeder Aenderung wahr, weil `_STIL`
    (in jede Seite eingebettetes CSS) die Klasse `.badge.zustand.
    termin_abgesagt` enthaelt — als Teilstring genuegt das der brieftreuen
    Assertion, ohne dass mein Code je laeuft. Ebenso zeigte der bestehende
    Fallback (unbekannter Aktivitaetstyp -> rohe JSON-Nutzlast im
    aufklappbaren `<details>`) den Grund schon woertlich, bevor
    `einladung_antwort` eine eigene Behandlung bekam. Die zwei zusaetzlichen
    Assertions binden den Test an die tatsaechliche Uebersetzung
    (`<b>abgesagt</b>` als eigenes Element) und daran, dass der ROHE
    DB-Wert 'DECLINED' nirgends mehr auf der Seite steht."""
    lead = _lead("Ivan")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_antwort', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-123", "status": "DECLINED",
                           "grund": "Bin beim Kunden in München",
                           "teilnehmer": "ivan@vibemind.space"})))
    seite = _get(f"/kontakte/{lead}").text
    assert "abgesagt" in seite.lower()
    assert "Bin beim Kunden in München" in seite
    assert "<b>abgesagt</b>" in seite, (
        "der uebersetzte Stand steht nicht als eigenes Element im Verlauf")
    assert "DECLINED" not in seite, (
        "der rohe DB-Statuswert taucht noch unuebersetzt auf der Seite auf")


def test_zusage_erscheint_als_zugesagt():
    lead = _lead("Ivan")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_antwort', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-123", "status": "ACCEPTED",
                           "grund": "", "teilnehmer": "ivan@vibemind.space"})))
    seite = _get(f"/kontakte/{lead}").text
    assert "zugesagt" in seite.lower()


def test_vorbehalt_erscheint_unter_vorbehalt():
    """TENTATIVE — auch der Status eines Gegenvorschlags (METHOD:COUNTER,
    siehe postfach._antwort_festhalten) — wird uebersetzt, nicht roh
    gezeigt."""
    lead = _lead("Tanja Tentative")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_antwort', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-999", "status": "TENTATIVE",
                           "grund": "", "teilnehmer": "tanja@vibemind.space"})))
    seite = _get(f"/kontakte/{lead}").text
    assert "unter Vorbehalt" in seite
    assert "TENTATIVE" not in seite


def test_ablehnungsgrund_wird_gekuerzt_mit_vollem_text_im_title():
    """Der Ablehnungsgrund ist Fremdtext (der Antwortende schreibt ihn) und
    folgt demselben Kuerzungsmuster wie jeder andere lange Anzeigetext auf
    dieser Seite: gekuerzt in der Zeile, voll im `title`, beides ueber
    `_e`."""
    lang = ("Leider kann ich zu diesem Termin nicht, weil ich an diesem Tag "
            "bereits einen anderen wichtigen Kundentermin in München habe "
            "und die Anfahrt zu lang waere, um beides zu schaffen")
    lead = _lead("Lena Lang")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_antwort', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-777", "status": "DECLINED",
                           "grund": lang,
                           "teilnehmer": "lena@vibemind.space"})))
    seite = _get(f"/kontakte/{lead}").text
    gekuerzt = ui._kurz(lang, ui.EINLADUNG_GRUND_KURZ)
    assert gekuerzt != lang, (
        "Testannahme verletzt: der lange Grund muesste ueber "
        "EINLADUNG_GRUND_KURZ hinausgehen, sonst kuerzt _kurz gar nichts")
    assert ui._e(gekuerzt) in seite
    assert f'title="{ui._e(lang)}"' in seite


# ---------------------------------------------------------------------------
# W4 (Schlusspruefung, 11.09.2026): der vorgeschlagene Termin im Verlauf,
# bei der Aktivitaet `einladung_entworfen` (Aufgabe 3/5). Vorher gab
# `einladung_entworfen` der Aktivitaet nur einen Namen ("→ Einladung
# entworfen"), der vorgeschlagene Termin selbst stand nur als rohes JSON
# hinter der aufklappbaren Klappe — der Betreiber musste aufklappen, um zu
# erfahren, WANN.
# ---------------------------------------------------------------------------

def test_einladung_entworfen_zeigt_termin_lesbar_im_verlauf():
    """Datum, Uhrzeit und Thema stehen jetzt lesbar in der Verlaufszeile,
    nicht mehr nur hinter der Klappe — nach demselben Muster, das Aufgabe 6
    fuer `einladung_antwort` gebaut hat (uebersetzter/lesbarer Kern als
    eigenes Element, Rest hinter `<details>`)."""
    lead = _lead("Ivan")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_entworfen', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-555", "datum": "2026-10-01",
                           "uhrzeit": "14:30", "folge": 0,
                           "eingeladene": ["ivan@vibemind.space"],
                           "thema": "Erstgespräch"})))
    seite = _get(f"/kontakte/{lead}").text
    assert "2026-10-01 14:30" in seite
    assert "<b>2026-10-01 14:30</b>" in seite, (
        "Datum/Uhrzeit stehen nicht als eigenes Element in der Zeile — "
        "nur noch als Teil der rohen JSON-Nutzlast hinter der Klappe")
    assert "Erstgespräch" in seite


def test_einladung_entworfen_thema_wird_gekuerzt_mit_vollem_text_im_title():
    """`thema` ist Fremdtext (vom Betreiber im Werkzeugaufruf gesetzt, aber
    ungeprueft — kann Kundennamen o. Ae. tragen) — dasselbe
    Kuerzungsmuster wie der Ablehnungsgrund bei `einladung_antwort`
    (Aufgabe 6, siehe test_ablehnungsgrund_wird_gekuerzt_mit_vollem_text_im_title
    oben)."""
    lang = ("Erstgespräch zur betrieblichen Altersvorsorge mit ausführlicher "
            "Bedarfsanalyse und Besprechung der bestehenden Verträge sowie "
            "möglicher Ergänzungen für die nächsten Jahre")
    lead = _lead("Lena Lang")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_entworfen', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-556", "datum": "2026-10-01",
                           "uhrzeit": "14:30", "folge": 0,
                           "eingeladene": ["lena@vibemind.space"],
                           "thema": lang})))
    seite = _get(f"/kontakte/{lead}").text
    gekuerzt = ui._kurz(lang, ui.EINLADUNG_GRUND_KURZ)
    assert gekuerzt != lang, (
        "Testannahme verletzt: das lange Thema muesste ueber "
        "EINLADUNG_GRUND_KURZ hinausgehen, sonst kuerzt _kurz gar nichts")
    assert ui._e(gekuerzt) in seite
    assert f'title="{ui._e(lang)}"' in seite
