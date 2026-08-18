"""sales-mcp — Werkzeugdienst des sales-claw-Prototyps.

Zwanzig deutsche Werkzeuge über MCP (streamable-http). Kein Send-Werkzeug:
Entwürfe enden als drafts(status='pending') und werden über die
Freigabe-Werkzeuge nach 'approved'/'rejected' bewegt — den tatsächlichen
Versand macht ausschliesslich der Dispatcher (WhatsApp) bzw. quittiert der
Betreiber selbst (LinkedIn, entwurf_manuell_gesendet versendet nichts,
es protokolliert nur einen bereits erfolgten Handversand; Stufe-3-Plan
Grundsatzentscheidung 1+3). entwurf_erneut_freigeben ist der Retry-Weg für
einen an OpenWA gescheiterten WhatsApp-Entwurf (failed -> approved) — mit
einer Schutzkante gegen Doppelversand, siehe dort.

Die beiden jüngsten Werkzeuge (marktanalyse, b2b_leads) sprechen als einzige
mit einem kostenpflichtigen Fremddienst (Apify, Free-Plan mit $5 Monatsbudget)
und legen Kontakte OHNE Einwilligung an — beides steht unten bei ihnen und in
recherche.py ausführlich; die Regel „Recherche-Leads werden nie automatisch
angeschrieben" ist eine Rechtsfrage (UWG), keine Stilfrage.
"""
import functools
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
import yaml
# Brief-Abweichung (gemessen mit `python -c "import mcp...; inspect.signature(...)"`
# im Container, installierte Version mcp==2.0.0 statt der vom Brief angenommenen
# 1.x-Reihe): `mcp.server.fastmcp.FastMCP` existiert nicht mehr — die Klasse
# heisst jetzt `MCPServer` und liegt unter `mcp.server.mcpserver`. Zusaetzlich
# nimmt ihr Konstruktor kein `host`/`port` mehr entgegen; beides wandert zu
# `.run(transport=..., host=..., port=...)`. `transport="streamable-http"`
# selbst ist unveraendert. Die Werkzeug-Funktionen unten sind davon nicht
# betroffen und bleiben wortgleich zum Brief.
from mcp.server.mcpserver import MCPServer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Dieselbe Funktion, die der Dispatcher zum Versenden benutzt (nummern.py).
# entwuerfe_offen zeigt damit die Nummer an, an die tatsächlich zugestellt
# würde — Anzeige und Versand können nicht auseinanderlaufen. Ein eigenes
# Modul, weil `import dispatch` hier ein Zirkelimport wäre (dispatch.py
# importiert server.py).
from nummern import normalisiere_empfaenger

# Aus demselben Grund ein eigenes Modul: `medien.pruefe` entscheidet hier, ob
# ein Anhang überhaupt in einen Entwurf darf — und im Dispatcher ein zweites
# Mal, unmittelbar vor dem Senden. Import statt Kopie (siehe medien.py).
import medien
# Die Apify-Anbindung (Stufe 5). Ebenfalls ein eigenes Modul, und ebenfalls
# eines ohne Rückimport: recherche.py kennt weder Datenbank noch Werkzeuge,
# nur HTTP, Normalisierung und Markdown (Begründung im Moduldocstring).
import recherche

SCHEMA = os.environ.get("SALES_DB_SCHEMA", "sales")
if SCHEMA not in ("sales", "sales_test"):
    raise SystemExit(f"Unzulaessiges Schema '{SCHEMA}' — erlaubt: sales, sales_test")

LEITFADEN = yaml.safe_load(
    (Path(__file__).parent / "leitfaden.yaml").read_text(encoding="utf-8"))
ALLE_FRAGEN = {f["id"]: {"frage": f["frage"], "gruppe": g["titel"]}
               for g in LEITFADEN["gruppen"] for f in g["fragen"]}

pool = ConnectionPool(
    os.environ["SALES_DB_URL"], min_size=1, max_size=4, open=True,
    kwargs={"row_factory": dict_row, "options": f"-c search_path={SCHEMA}"})

DB_FEHLER = ("Datenbank nicht erreichbar — Protokoll und Profil werden gerade "
             "NICHT gespeichert. Sag das dem Gespraechspartner ausdruecklich "
             "und versuche es spaeter erneut.")

MCP_HOST = "0.0.0.0"
MCP_PORT = int(os.environ.get("MCP_PORT", "8765"))

mcp = MCPServer("sales-mcp")


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q(sql: str, params=()):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _gesichert(fn):
    """DB-Ausfall wird zur definierten Meldung, nie zum Traceback (Spec §4).

    functools.wraps ist hier KEIN Stil, sondern Funktionsvoraussetzung: die
    MCP-Registrierung baut das Werkzeug-Schema aus inspect.signature(). Ein
    Wrapper, der nur __name__/__doc__ kopiert, liefert (*a, **kw) — das
    Schema ist dann leer und KEIN Agent kann irgendein Werkzeug aufrufen.
    Genau so in Task 4 passiert: Anbindung stand, jeder Aufruf scheiterte.
    """
    @functools.wraps(fn)
    def innen(*a, **kw):
        try:
            return fn(*a, **kw)
        except psycopg.OperationalError:
            return _json({"fehler": DB_FEHLER})
        except psycopg.Error as e:
            return _json({"fehler": f"Datenbankfehler ({e.sqlstate}): "
                                    f"{str(e).splitlines()[0][:200]}"})
    return innen


@_gesichert
def kontakt_suchen(text: str) -> str:
    """Kontakt per Name, E-Mail oder Telefonnummer finden. Immer zuerst
    aufrufen, bevor ein Kontakt neu angelegt wird."""
    zeilen = _q(
        "select id, name, status, consent_status from leads "
        "where name ilike %s or email ilike %s or phone ilike %s "
        "order by updated_at desc limit 10",
        (f"%{text}%", f"%{text}%", f"%{text}%"))
    return _json({"kontakte": [
        {"lead_id": z["id"], "name": z["name"], "status": z["status"],
         "consent": z["consent_status"]} for z in zeilen]})


# Demo-Befund B1 (docs/06_DEMO_ABNAHME.md): der Agent legte "Lisa Probekunde"
# im Durchspiel doppelt an, entgegen der Regel "erst suchen, dann anlegen"
# (Modellvarianz). Die Kante gehoert deshalb in die Werkzeugschicht, nicht ins
# Modellverhalten (Projektprinzip) — kontakt_anlegen prueft selbst, bevor es
# einfuegt.
def _lead_mit_gleicher_nummer(chat_id: str):
    """Bestehender Lead mit dieser normalisierten Nummer, oder None.

    Gleiches Muster wie inbox.py:lead_zu_nummer — ein eigenes, kleines
    Duplikat statt eines Imports, denn inbox.py importiert bereits server.py
    ("import server"); ein Ruecksimport waere ein Zirkelimport (siehe die
    Begruendung oben bei nummern.py). SQL-Vorfilter ueber die letzten acht
    Ziffern (Schreibweisen unterscheiden sich vorne: '+49…', '0049…', nie
    hinten), die eigentliche Entscheidung faellt danach ueber
    normalisiere_empfaenger auf BEIDEN Seiten — derselben Funktion, die auch
    den Versand steuert.
    """
    ziffern = chat_id.split("@", 1)[0]
    schwanz = ziffern[-8:] if len(ziffern) >= 8 else ziffern
    zeilen = _q(
        "select id, phone from leads where phone is not null "
        "and regexp_replace(phone, '[^0-9]', '', 'g') like %s "
        "order by updated_at desc limit 500", (f"%{schwanz}",))
    treffer = [z for z in zeilen
               if normalisiere_empfaenger(z["phone"])[0] == chat_id]
    return treffer[0] if treffer else None


@_gesichert
def kontakt_anlegen(name: str, email: str = "", phone: str = "",
                    source: str = "whatsapp", notes: str = "") -> str:
    """Neuen Kontakt anlegen. Nur verwenden, wenn kontakt_suchen leer war.

    Dedup-Kante (Demo-Befund B1): traegt phone eine Nummer, die normalisiert
    (nummern.py) bereits zu einem bestehenden Lead gehoert — gleich in
    welcher Schreibweise (+49… vs. 0049… vs. …) —, wird KEIN zweiter Lead
    angelegt; zurueck kommt die bestehende lead_id mit angelegt=false. Ohne
    Telefonnummer, oder mit einer, die sich nicht normalisieren laesst
    (z. B. nationale Schreibweise), bleibt das bisherige Verhalten
    unveraendert: Namens-Dubletten sind legitim, zwei Max Mueller gibt es
    wirklich."""
    if phone.strip():
        chat_id, _fehler = normalisiere_empfaenger(phone)
        if chat_id is not None:
            bestehend = _lead_mit_gleicher_nummer(chat_id)
            if bestehend is not None:
                return _json({
                    "lead_id": bestehend["id"], "angelegt": False,
                    "hinweis": "Kontakt mit dieser Nummer existiert bereits"})
    zeilen = _q(
        "insert into leads (name, email, phone, source, notes) "
        "values (%s, nullif(%s,''), nullif(%s,''), %s, nullif(%s,'')) "
        "returning id", (name, email, phone, source, notes))
    return _json({"lead_id": zeilen[0]["id"], "angelegt": True})


# Stammdatenfelder, die korrigiert werden duerfen — buchstabengenau und
# abschliessend. Die Whitelist ist nicht Komfort, sondern die einzige Sicherung:
# psycopg kann Spaltennamen nicht als Parameter binden, der Name geht also per
# f-String in die Query. Wird hier je etwas gelockert, ist es eine
# SQL-Injection. Ausdruecklich NICHT enthalten: `consent_status` (Einwilligung
# entsteht aus einer Antwort des Kontakts, siehe bedarf_speichern, nicht aus
# einem Freitextaufruf), `status`, `score*`, `enrichment` (dafuer gibt es
# profil_aktualisieren) und `id`.
KONTAKT_FELDER = ("phone", "email", "name")


@_gesichert
def kontakt_aktualisieren(lead_id: str, feld: str, wert: str) -> str:
    """Stammdaten eines bestehenden Kontakts korrigieren oder nachtragen.
    Erlaubt sind ausschliesslich die Felder phone, email und name — etwa um
    eine fehlende Telefonnummer zu ergaenzen, ohne die ein WhatsApp-Entwurf
    nicht zugestellt werden kann. Telefonnummern immer MIT Landesvorwahl
    erfassen (+49…/+43…): einer national geschriebenen Nummer (0170…) wird
    nicht vertraut, sie gilt als nicht zustellbar. Profilangaben gehoeren
    nach profil_aktualisieren, nicht hierher."""
    if feld not in KONTAKT_FELDER:
        return _json({"fehler": f"Unzulaessiges Feld '{feld}'. Erlaubt: "
                                f"{', '.join(KONTAKT_FELDER)}. Profilangaben "
                                f"gehoeren nach profil_aktualisieren, die "
                                f"Einwilligung nach bedarf_speichern."})
    if feld == "name" and not wert.strip():
        return _json({"fehler": "Ein Kontakt ohne Namen ist nicht vorgesehen."})
    vorhanden = _q(f"select {feld} as alt from leads where id = %s", (lead_id,))
    if not vorhanden:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    _q(f"update leads set {feld} = nullif(%s,''), updated_at = now() "
       "where id = %s returning id", (wert.strip(), lead_id))
    _q("insert into activities (lead_id, type, payload) "
       "values (%s, 'korrektur', %s) returning id",
       (lead_id, _json({"feld": feld, "vorher": vorhanden[0]["alt"],
                        "wert": wert.strip()})))
    return _json({"gesetzt": {feld: wert.strip()}})


@_gesichert
def aktivitaet_loggen(lead_id: str, typ: str, inhalt: str) -> str:
    """Interaktion unveraenderlich protokollieren (nachricht, notiz, termin,
    offener_punkt, bedarf). Nach JEDER Kundeninteraktion aufrufen."""
    _q("insert into activities (lead_id, type, payload) values (%s, %s, %s) "
       "returning id", (lead_id, typ, json.dumps({"inhalt": inhalt},
                                                 ensure_ascii=False)))
    return _json({"geloggt": True})


@_gesichert
def wiedervorlage_setzen(lead_id: str, faellig_am: str, notiz: str) -> str:
    """Wiedervorlage fuer einen Kontakt setzen — erscheint ab Faelligkeit im
    Digest (Block faellige_wiedervorlagen), bis sie mit
    wiedervorlage_erledigt quittiert wird. faellig_am als ISO-Datum
    (YYYY-MM-DD), nicht in der Vergangenheit."""
    try:
        datum = date.fromisoformat(faellig_am.strip())
    except (ValueError, AttributeError):
        return _json({"fehler": f"Ungueltiges Datum '{faellig_am}' — "
                                f"erwartet ISO-Format YYYY-MM-DD."})
    heute = datetime.now(timezone.utc).date()
    if datum < heute:
        return _json({"fehler": f"faellig_am {datum.isoformat()} liegt in "
                                f"der Vergangenheit (heute: {heute.isoformat()})."})
    return _json({"aktivitaets_id": _wiedervorlage_anlegen(lead_id, datum, notiz),
                  "faellig_am": datum.isoformat()})


@_gesichert
def wiedervorlage_erledigt(lead_id: str, aktivitaets_id: str) -> str:
    """Eine offene Wiedervorlage quittieren. Append-only: es wird NICHTS
    geaendert, stattdessen ein Gegen-Ereignis geschrieben — offen bleibt eine
    Wiedervorlage genau solange, wie kein Gegen-Ereignis auf sie verweist.
    aktivitaets_id muss eine bestehende wiedervorlage-Aktivitaet DIESES Leads
    sein (z. B. aus wiedervorlage_setzen oder dem
    faellige_wiedervorlagen-Block von digest())."""
    zeilen = _q(
        "select id from activities where id = %s and lead_id = %s "
        "and type = 'wiedervorlage'", (aktivitaets_id, lead_id))
    if not zeilen:
        return _json({"fehler": f"Keine Wiedervorlage mit aktivitaets_id "
                                f"{aktivitaets_id} bei lead_id {lead_id}."})
    _q("insert into activities (lead_id, type, payload) values (%s, "
       "'wiedervorlage_erledigt', %s) returning id",
       (lead_id, _json({"wiedervorlage_id": str(aktivitaets_id)})))
    return _json({"erledigt": True, "wiedervorlage_id": str(aktivitaets_id)})


# ---------------------------------------------------------------------------
# Vertraege (Stufe 7) — Bestandspflege ohne DDL.
#
# Ein Vertrag ist eine vom Kunden GENANNTE Tatsache: Dokumentation seiner
# Angabe, keine Bewertung und keine Empfehlung (§34d bleibt unberuehrt, siehe
# AGENTS.md „Verbote"). Er liegt als Element in leads.enrichment.vertraege,
# einem jsonb-Array — kein neues Schema, kein DDL (sales_app kann keines).
# Der eigentliche Nutzen ist die Wiedervorlage: das Ablaufdatum ist der beste
# Terminanlass im Bestand, und er soll nicht davon abhaengen, dass jemand
# daran denkt.
# ---------------------------------------------------------------------------

WIEDERVORLAGE_VORLAUF_TAGE = 90


def _wiedervorlage_anlegen(lead_id, faellig: date, notiz: str) -> str:
    """Interner Kern von wiedervorlage_setzen — auch vertrag_speichern legt
    darueber an, damit es genau EIN Insert-Muster gibt."""
    zeilen = _q(
        "insert into activities (lead_id, type, payload) values (%s, "
        "'wiedervorlage', %s) returning id",
        (lead_id, _json({"faellig_am": faellig.isoformat(), "notiz": notiz})))
    return str(zeilen[0]["id"])


@_gesichert
def vertrag_speichern(lead_id: str, sparte: str, ablauf: str = "",
                      gesellschaft: str = "", notiz: str = "") -> str:
    """Einen vom Kunden GENANNTEN Vertrag am Kontakt festhalten —
    Dokumentation, keine Beratung. Mit `ablauf` (ISO YYYY-MM-DD) entsteht
    automatisch eine Wiedervorlage 90 Tage vor Ablauf (nie in der
    Vergangenheit; liegt der Ablauf selbst zurueck, nur ein Hinweis) —
    der beste Terminanlass im Bestand entsteht damit von selbst."""
    if not (sparte or "").strip():
        return _json({"fehler": "Keine Sparte angegeben."})
    datum = None
    if (ablauf or "").strip():
        try:
            datum = date.fromisoformat(ablauf.strip())
        except ValueError:
            return _json({"fehler": f"Ungueltiges Datum '{ablauf}' — "
                                    f"erwartet ISO-Format YYYY-MM-DD."})
    vertrag = {k: v for k, v in {
        "sparte": sparte.strip(), "gesellschaft": gesellschaft.strip(),
        "ablauf": datum.isoformat() if datum else "",
        "notiz": notiz.strip(),
        "erfasst": datetime.now(timezone.utc).date().isoformat(),
    }.items() if v}
    # EIN jsonb_set genuegt, obwohl profil_aktualisieren/bedarf_speichern
    # verschachteln muessen: `create_missing` legt nur das LETZTE Pfadelement
    # an, wenn dessen Elternobjekt existiert. Dort ist der Pfad zweistufig
    # ('{profil,feld}') und das Elternobjekt fehlt auf frischen Kontakten;
    # hier ist er einstufig ('{vertraege}') und das Elternobjekt ist die
    # Wurzel, laut db/provision.sql `not null default '{}'::jsonb`. Der
    # coalesce-Append haengt AN, statt zu ersetzen — ein Kontakt hat mehrere
    # Vertraege, und der zweite darf den ersten nicht loeschen.
    zeilen = _q(
        "update leads set enrichment = jsonb_set(enrichment, '{vertraege}', "
        "coalesce(enrichment->'vertraege', '[]'::jsonb) || %s::jsonb, true), "
        "updated_at = now() where id = %s returning id", (_json(vertrag), lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    heute = datetime.now(timezone.utc).date()
    wiedervorlage, hinweis = None, None
    if datum and datum < heute:
        hinweis = (f"Ablauf {datum.isoformat()} liegt in der Vergangenheit — "
                   f"keine Wiedervorlage angelegt.")
    elif datum:
        faellig = max(heute, datum - timedelta(days=WIEDERVORLAGE_VORLAUF_TAGE))
        wv_id = _wiedervorlage_anlegen(
            lead_id, faellig,
            f"Vertragsablauf {vertrag['sparte']} am {datum.isoformat()}")
        wiedervorlage = {"aktivitaets_id": wv_id,
                         "faellig_am": faellig.isoformat()}
    # `wiedervorlage` bleibt IMMER stehen, auch als null — sie ist der Zweck
    # dieses Werkzeugs, und „kein Schluessel" waere fuer den Aufrufer nicht
    # von „Schluessel vergessen" zu unterscheiden. _ohne_none greift nur auf
    # `hinweis`, also genau auf das Hinweisfeld, fuer das es gedacht ist.
    return _json({"vertrag": vertrag, "wiedervorlage": wiedervorlage,
                  **_ohne_none({"hinweis": hinweis})})


@_gesichert
def vertraege_ablaufend(tage: int = 90) -> str:
    """Welche Vertraege laufen in den naechsten `tage` Tagen ab? Quelle fuer
    proaktive Bestandsarbeit und den Wochenbericht."""
    try:
        fenster = max(1, min(int(tage), 365))
    except (TypeError, ValueError):
        fenster = 90
    # `jsonb_array_elements` wirft bei einem Nicht-Array ("cannot extract
    # elements from a scalar") — EIN kaputter Kontakt wuerde die ganze Liste
    # scheitern lassen. Die Wache steht deshalb im Argument selbst, nicht als
    # WHERE-Bedingung.
    #
    # Gemessen gegen sales_test (vertraege als "kein-array", 42, null und als
    # Objekt, gemischt mit gueltigen Zeilen): die WHERE-Variante des Plans
    # laeuft ebenfalls fehlerfrei — EXPLAIN zeigt, warum, naemlich
    # "Seq Scan on leads / Filter: jsonb_typeof(...) = 'array'" VOR dem
    # Function Scan. Das ist aber eine Eigenschaft der gewaehlten Planform,
    # keine Zusicherung: der Aufruf in der FROM-Liste ist ein implizites
    # LATERAL, und ob die Bedingung am Basis-Scan haengen bleibt, entscheidet
    # der Planer. `case ... else '[]'` braucht diese Entscheidung nicht —
    # das Argument ist dann nie etwas anderes als ein Array.
    zeilen = _q(
        "select l.id as lead_id, l.name, v->>'sparte' as sparte, "
        "       v->>'ablauf' as ablauf "
        "from leads l, jsonb_array_elements("
        "       case when jsonb_typeof(l.enrichment->'vertraege') = 'array' "
        "            then l.enrichment->'vertraege' else '[]'::jsonb end) v "
        "where v->>'ablauf' <> '' "
        "  and (v->>'ablauf')::date "
        "      between current_date and current_date + %s "
        "order by (v->>'ablauf')::date", (fenster,))
    return _json({"anzahl": len(zeilen), "fenster_tage": fenster,
                  "vertraege": zeilen})


@_gesichert
def profil_lesen(lead_id: str) -> str:
    """Kundenprofil samt der letzten Aktivitaeten lesen. Zu Gespraechsbeginn
    aufrufen, damit nichts doppelt gefragt wird.

    Bei Firmenkontakten steht unter `firma` ausserdem, was `firma_anreichern`
    von der Firmenwebsite gelesen hat — mit dem VOLLTEXT der gelesenen Seiten
    und dem `stand` (Datum des Abrufs). Das ist die Gespraechsvorbereitung
    fuer den bAV-Erstkontakt; ist der Stand alt, `firma_anreichern` erneut
    aufrufen (es kostet nichts)."""
    leads = _q("select id, name, status, consent_status, enrichment, notes "
               "from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    akt = _q("select type, payload, actor, created_at from activities "
             "where lead_id = %s order by created_at desc limit 10", (lead_id,))
    e = leads[0]["enrichment"] or {}
    return _json({"lead_id": leads[0]["id"], "name": leads[0]["name"],
                  "status": leads[0]["status"],
                  "consent": leads[0]["consent_status"],
                  "profil": e.get("profil", {}), "bedarf": e.get("bedarf", {}),
                  # Die vom Kunden genannten Vertraege (vertrag_speichern) —
                  # ohne diese Zeile laege der Bestand zwar in enrichment,
                  # tauchte aber in keiner Gespraechsvorbereitung auf.
                  "vertraege": e.get("vertraege", []),
                  # Ohne diese Zeile waere der Hinweis von firma_anreichern
                  # („profil_lesen zeigt den Volltext") schlicht falsch: der
                  # firma-Knoten laege in enrichment und wuerde nie angezeigt.
                  "firma": e.get("firma", {}),
                  "notes": leads[0]["notes"], "aktivitaeten": akt})


@_gesichert
def profil_aktualisieren(lead_id: str, feld: str, wert: str) -> str:
    """Ein Profilfeld setzen (kumulativ; bestehende Felder bleiben erhalten)."""
    # Brief-Abweichung: `jsonb_set(enrichment, '{profil,feld}', ..., true)` legt
    # den fehlenden Zwischenknoten `profil` NICHT an — `create_missing` erzeugt
    # laut Postgres-Doku nur das letzte Pfadelement, wenn dessen Elternobjekt
    # bereits existiert. `leads.enrichment` startet aber bei frischen Kontakten
    # als '{}'::jsonb (db/provision.sql), ohne `profil`-Schluessel — der Aufruf
    # aus dem Brief war damit auf frischen Kontakten ein stiller No-op (empirisch
    # gegen die DB geprueft: leeres Elternobjekt -> Ergebnis bleibt '{}'). Fix:
    # `profil` zuerst mit einem verschachtelten jsonb_set garantieren.
    zeilen = _q(
        "update leads set enrichment = jsonb_set("
        "jsonb_set(enrichment, '{profil}', coalesce(enrichment->'profil', '{}'::jsonb), true), "
        "%s, to_jsonb(%s::text), true) "
        "where id = %s returning id", (["profil", feld], wert, lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    return _json({"gesetzt": {feld: wert}})


@_gesichert
def bedarf_speichern(lead_id: str, frage_id: str, antwort: str) -> str:
    """Antwort auf eine Leitfaden-Frage strukturiert ablegen. frage_id muss
    aus bedarf_offen stammen."""
    if frage_id not in ALLE_FRAGEN:
        return _json({"fehler": f"Unbekannte frage_id '{frage_id}'. "
                                f"Gueltig: {sorted(ALLE_FRAGEN)}"})
    eintrag = {"antwort": antwort, "at": _jetzt()}
    # Verschachteltes jsonb_set — zwingend. Ein einfaches
    # jsonb_set(enrichment, '{bedarf,frage_id}', ..., true) legt den fehlenden
    # Zwischenknoten 'bedarf' NICHT an (create_missing erzeugt nur das letzte
    # Pfadelement) und ist auf frischen Kontakten ein stiller No-op. Exakt
    # dieser Fehler steckte in profil_aktualisieren und wurde in Task 2
    # empirisch belegt und behoben — dieses Muster spiegelt den Fix.
    zeilen = _q(
        "update leads set enrichment = jsonb_set(enrichment, '{bedarf}', "
        "jsonb_set(coalesce(enrichment->'bedarf', '{}'::jsonb), %s, %s::jsonb, true), "
        "true) where id = %s returning id",
        ([frage_id], json.dumps(eintrag, ensure_ascii=False), lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    if frage_id == "consent_kontakt":
        ja = antwort.strip().lower().startswith(("ja", "gern", "ok", "einverstanden"))
        _q("update leads set consent_status = %s where id = %s returning id",
           ("opt_in" if ja else "unknown", lead_id))
    _q("insert into activities (lead_id, type, payload) values (%s,'bedarf',%s) "
       "returning id",
       (lead_id, json.dumps({"frage_id": frage_id, "antwort": antwort},
                            ensure_ascii=False)))
    return _json({"gespeichert": frage_id})


@_gesichert
def bedarf_offen(lead_id: str) -> str:
    """Welche Leitfaden-Fragen sind noch offen? Vor jeder Frage aufrufen und
    nur Fehlendes fragen — nie etwas doppelt."""
    leads = _q("select enrichment from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    beantwortet = set((leads[0]["enrichment"] or {}).get("bedarf", {}))
    offen = [{"gruppe": g["titel"],
              "fragen": [f for f in g["fragen"] if f["id"] not in beantwortet]}
             for g in LEITFADEN["gruppen"]]
    offen = [g for g in offen if g["fragen"]]
    return _json({"anzahl_offen": sum(len(g["fragen"]) for g in offen),
                  "offen": offen})


@_gesichert
def entwurf_erstellen(lead_id: str, kanal: str, text: str,
                      betreff: str = "", medien_datei: str = "") -> str:
    """Beispiel-Nachricht in die Entwurfs-Queue legen. Kanaele: whatsapp,
    linkedin, email. Es wird NICHTS versendet — der Entwurf bleibt 'pending';
    den Versand uebernimmt spaeter eine andere App.

    `medien_datei` haengt optional eine Unterlage an: der blosse Dateiname
    einer Datei aus dem Medienordner (medien_liste zeigt, was dort liegt) —
    ohne jede Pfadangabe, Endung pdf/jpg/jpeg/png/mp3/ogg, hoechstens 15 MB.
    Passt etwas davon nicht, entsteht KEIN Entwurf und der Grund kommt als
    Fehlertext zurueck. Bei WhatsApp geht der Anhang zusammen mit dem Text in
    EINER Nachricht raus (der Text wird zur Bildunterschrift und darf deshalb
    hoechstens 1024 Zeichen haben); bei linkedin/email ist der Dateiname nur
    ein Merkposten fuer den Handversand — dort verschickt niemand automatisch
    etwas."""
    if kanal not in ("whatsapp", "linkedin", "email"):
        return _json({"fehler": f"Unzulaessiger Kanal '{kanal}'. "
                                f"Erlaubt: whatsapp, linkedin, email"})
    leads = _q("select name, phone, email from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    # Der Anhang wird VOR dem Insert geprueft: ein Entwurf, dessen Anhang nicht
    # zustellbar ist, soll gar nicht erst in der Freigabe-Queue auftauchen.
    basis = None
    if (medien_datei or "").strip():
        basis, fehler = medien.pruefe(medien_datei)
        if fehler:
            return _json({"fehler": fehler})
        # Gemessene Grenze des Media-Endpunkts (medien.py, Kopf): die
        # Bildunterschrift darf 1024 Zeichen haben, reiner Text 4096. Ein
        # laengerer Text wuerde erst beim Zustellen mit HTTP 400 auffallen —
        # also nach der Freigabe durch den Betreiber, was der schlechteste
        # Zeitpunkt dafuer ist.
        if kanal == "whatsapp" and len(text) > medien.CAPTION_MAXLAENGE:
            return _json({"fehler": (
                f"Mit Anhang darf der Text hoechstens "
                f"{medien.CAPTION_MAXLAENGE} Zeichen haben (er reist als "
                f"Bildunterschrift mit), hier sind es {len(text)}. Entweder "
                f"kuerzen oder den Anhang weglassen.")})
    empfaenger = (leads[0]["phone"] if kanal == "whatsapp" else
                  leads[0]["email"] if kanal == "email" else leads[0]["name"])
    zeilen = _q(
        "insert into drafts (lead_id, channel, recipient, subject, body, "
        "media_ref) values (%s, %s, %s, nullif(%s,''), %s, %s) "
        "returning id, status",
        (lead_id, kanal, empfaenger or leads[0]["name"], betreff, text, basis))
    return _json({"draft_id": zeilen[0]["id"], "status": zeilen[0]["status"],
                  "medien_datei": basis,
                  "hinweis": "Nicht versendet — wartet in der Queue."})


# Sammelkontakt "LINKEDIN (Eigenes Profil)" — an ihm haengen Post-Entwuerfe
# und ihre Aktivitaeten. Gleiches Muster wie INBOX_UNBEKANNT_LEAD_ID und
# RECHERCHE_LEAD_ID: die UUID kommt aus der Umgebung, die Tests biegen das
# Modulattribut um. Ein eigener Sammelkontakt, weil ein Post keinen
# Empfaenger hat — er gehoert zu keinem Kunden, und an einem Kundenlead
# wuerde er dessen Historie verfaelschen.
LINKEDIN_POST_LEAD_ID = os.environ.get("LINKEDIN_POST_LEAD_ID", "").strip()

# Gemessene LinkedIn-Grenze fuer Post-Texte: 3000 Zeichen. Ein laengerer
# Text wuerde erst beim Einfuegen auf linkedin.com auffallen — nach der
# Freigabe, also am schlechtesten Zeitpunkt (dieselbe Begruendung wie bei
# CAPTION_MAXLAENGE in medien.py).
POST_MAXLAENGE = 3000


@_gesichert
def post_entwurf_erstellen(thema: str, text: str, medien_datei: str = "") -> str:
    """LinkedIn-POST (eigenes Profil, kein Empfaenger) in die Freigabe-Queue
    legen — fuer die zwei Schienen des Hauses: Karriere-/Partner-Recruiting
    und bAV-/B2B-Sichtbarkeit. Es wird NICHTS automatisch gepostet: nach der
    Freigabe postet der Betreiber den Text VON HAND auf linkedin.com und
    quittiert mit entwurf_manuell_gesendet (LinkedIn verbietet automatisierte
    Nutzung; der Handversand ist der regelkonforme Weg).

    `thema` wird zum Betreff ("Post: <thema>") — daran erkennt die
    Freigabe-Anzeige einen Post. `medien_datei` (Dateiname aus medien_liste)
    ist ein Merkposten, welches Bild/PDF der Betreiber mit anhaengen will.
    Hoechstens 3000 Zeichen (LinkedIn-Grenze). Kein Kundenname, keine
    Kundendaten und keine Produkt-/Tarifempfehlung im Text — auch ein Post
    ist keine Beratung."""
    if not (thema or "").strip():
        return _json({"fehler": "Kein Thema angegeben."})
    if not (text or "").strip():
        return _json({"fehler": "Kein Text angegeben."})
    if len(text) > POST_MAXLAENGE:
        return _json({"fehler": (
            f"LinkedIn-Posts duerfen hoechstens {POST_MAXLAENGE} Zeichen "
            f"haben, hier sind es {len(text)}. Kuerzen — oder auf zwei "
            f"Posts aufteilen.")})
    if not LINKEDIN_POST_LEAD_ID:
        return _json({"fehler": (
            "LINKEDIN_POST_LEAD_ID ist nicht gesetzt (.env) — der "
            "Sammelkontakt 'LINKEDIN (Eigenes Profil)' fehlt. Ohne ihn "
            "entsteht kein Post-Entwurf, sonst hinge er an keinem Kontakt.")})
    sammel = _q("select id from leads where id = %s", (LINKEDIN_POST_LEAD_ID,))
    if not sammel:
        return _json({"fehler": (
            f"Der Sammelkontakt {LINKEDIN_POST_LEAD_ID} existiert nicht in "
            f"der Datenbank — LINKEDIN_POST_LEAD_ID in der .env pruefen.")})
    basis = None
    if (medien_datei or "").strip():
        basis, fehler = medien.pruefe(medien_datei)
        if fehler:
            return _json({"fehler": fehler})
    # recipient ist NOT NULL — 'eigenes-profil' sagt, wohin der Post gehoert,
    # und ist fuer den Dispatcher bedeutungslos: der fasst channel='linkedin'
    # ohnehin nie an, Posts nehmen denselben Handversand-Weg wie
    # LinkedIn-Nachrichten (freigeben -> von Hand -> manuell_gesendet).
    zeilen = _q(
        "insert into drafts (lead_id, channel, recipient, subject, body, "
        "media_ref) values (%s, 'linkedin', 'eigenes-profil', %s, %s, %s) "
        "returning id, status",
        (LINKEDIN_POST_LEAD_ID, f"Post: {thema.strip()}", text, basis))
    return _json({"draft_id": zeilen[0]["id"], "status": zeilen[0]["status"],
                  "medien_datei": basis,
                  "hinweis": ("Nicht gepostet — wartet auf Freigabe. Nach der "
                              "Freigabe von Hand posten und mit "
                              "entwurf_manuell_gesendet quittieren.")})


@_gesichert
def medien_liste() -> str:
    """Welche Unterlagen liegen zum Anhaengen bereit? Nennt Name und Groesse
    jeder Datei im Medienordner. Genau diese Namen nimmt
    entwurf_erstellen(..., medien_datei='<name>'). Dateien mit einer nicht
    versendbaren Endung tauchen nicht auf (erlaubt sind pdf, jpg, jpeg, png,
    mp3, ogg)."""
    try:
        eintraege = medien.liste()
    except OSError as e:
        return _json({"fehler": f"Medienordner nicht lesbar "
                                f"({type(e).__name__}) — liegt der Ordner "
                                f"{medien.MEDIA_VERZEICHNIS} am Container an?"})
    return _json({"anzahl": len(eintraege),
                  "dateien": [{"name": name, "groesse_bytes": groesse,
                               "groesse": _lesbare_groesse(groesse)}
                              for name, groesse in eintraege]})


def _lesbare_groesse(bytes_: int) -> str:
    """Damit der Betreiber eine Zahl hoert, die er einordnen kann."""
    if bytes_ >= 1048576:
        return f"{bytes_ / 1048576:.1f} MB".replace(".", ",")
    return f"{bytes_ / 1024:.0f} KB"


@_gesichert
def digest() -> str:
    """Zusammenfassung: offene Entwuerfe, unvollstaendige Bedarfsanalysen,
    faellige Wiedervorlagen, letzte Aktivitaeten (48 h)."""
    entwuerfe = _q("select d.id, d.channel, l.name, d.created_at from drafts d "
                   "left join leads l on l.id = d.lead_id "
                   "where d.status = 'pending' order by d.created_at desc")
    # Recherche- und Systemkontakte bleiben hier draussen (Stufe 5). Eine
    # „unvollstaendige Bedarfsanalyse" setzt ein Gespraech voraus; ein frisch
    # recherchierter Firmeneintrag hat nie eines gefuehrt. Gemessen nach der
    # ersten b2b_leads-Runde: 6 der 13 Zeilen in diesem Block waren
    # Recherche-Treffer und der Sammelkontakt — je mit 21 offenen Fragen, ganz
    # oben, weil sie die juengsten Kontakte sind. Das haette den Morgen-Digest
    # (F2) genau um die Kontakte gebracht, um die es geht. Sichtbar bleiben
    # Recherche-Kontakte ueber kontakt_suchen und die recherche-Aktivitaeten am
    # Sammelkontakt.
    unvollstaendig = _q(
        "select id, name from leads where status not in ('won','lost') "
        "and coalesce(source, '') not in ('recherche', 'system') "
        "order by updated_at desc limit 20")
    offen_je_lead = []
    for lead in unvollstaendig:
        o = json.loads(bedarf_offen(str(lead["id"])))
        if "anzahl_offen" in o and o["anzahl_offen"] > 0:
            offen_je_lead.append({"lead_id": lead["id"], "name": lead["name"],
                                  "offene_fragen": o["anzahl_offen"]})
    # Offen = wiedervorlage-Aktivitaet, faellig (faellig_am <= heute), OHNE
    # zugehoeriges Gegen-Ereignis wiedervorlage_erledigt (append-only, siehe
    # dort). LIMIT wie bei den anderen Digest-Bloecken: eine Deckelung, damit
    # eine Antwort nicht unbegrenzt waechst.
    wiedervorlagen = _q(
        "select w.id, w.lead_id, w.payload, l.name from activities w "
        "left join leads l on l.id = w.lead_id "
        "where w.type = 'wiedervorlage' "
        "and (w.payload->>'faellig_am')::date <= current_date "
        "and not exists (select 1 from activities e where "
        "e.type = 'wiedervorlage_erledigt' "
        "and e.payload->>'wiedervorlage_id' = w.id::text) "
        "order by (w.payload->>'faellig_am')::date asc limit 50")
    letzte = _q("select a.type, a.payload, a.created_at, l.name "
                "from activities a left join leads l on l.id = a.lead_id "
                "where a.created_at > now() - interval '48 hours' "
                "order by a.created_at desc limit 20")
    return _json({"anzahl_entwuerfe": len(entwuerfe),
                  "offene_entwuerfe": [
                      {"draft_id": e["id"], "kanal": e["channel"],
                       "kontakt": e["name"]} for e in entwuerfe],
                  "unvollstaendige_bedarfsanalysen": offen_je_lead,
                  "faellige_wiedervorlagen": [
                      {"aktivitaets_id": w["id"], "lead_id": w["lead_id"],
                       "kontakt": w["name"],
                       "notiz": (w["payload"] or {}).get("notiz"),
                       "faellig_am": (w["payload"] or {}).get("faellig_am")}
                      for w in wiedervorlagen],
                  "letzte_aktivitaeten": letzte})


@_gesichert
def wochenbericht() -> str:
    """Die Steuerungszahlen der letzten 7 Tage — freitags lesen (oder per
    Cron bekommen): was kam rein, was ging raus, was blieb liegen. Nur
    Lesezugriffe, versendet nichts."""
    # `seit` wird in den SQL-Text interpoliert statt gebunden. Das ist hier
    # kein Injection-Risiko, und der Grund ist strukturell, nicht
    # „vertrauenswuerdig gemeint": der String ist ein Literal in dieser
    # Funktion, und `wochenbericht()` nimmt UEBERHAUPT KEIN Argument
    # entgegen — es gibt also keinen Aufrufweg, ueber den ein Agent, ein
    # Kunde oder eine Datenbankzeile diesen Text beeinflussen koennte.
    # Interpoliert wird er nur, weil sechs Abfragen dieselbe Fenstergrenze
    # brauchen und sie genau EINMAL dastehen soll. Wird der Zeitraum je
    # parametrisierbar (z. B. `wochenbericht(tage: int)`), ist die
    # Interpolation SOFORT durch eine Bindung zu ersetzen
    # (`created_at >= now() - %s::interval`) — in allen sechs Abfragen.
    seit = "now() - interval '7 days'"
    neue = _q(f"select coalesce(source,'unbekannt') as s, count(*) as n "
              f"from leads where created_at >= {seit} group by s")
    bedarf = _q(f"select count(*) as antworten, "
                f"count(distinct lead_id) as kontakte "
                f"from activities where type='bedarf' and created_at >= {seit}")
    versand = _q(f"select channel, count(*) as n from drafts "
                 f"where sent_at >= {seit} group by channel")
    wv = _q(f"select type, count(*) as n from activities "
            f"where type in ('wiedervorlage','wiedervorlage_erledigt') "
            f"and created_at >= {seit} group by type")
    # Zwei Zahlen mit ABSICHTLICH anderem Zeitbegriff: offene Entwuerfe sind
    # ein Bestand (was liegt JETZT zur Freigabe, egal wie alt), ablaufende
    # Vertraege schauen nach vorn. Beide gehoeren in den Wochenblick, aber
    # keine von beiden ins 7-Tage-Fenster.
    offen = _q("select count(*) as n from drafts where status='pending'")
    kosten = _q(f"select coalesce(sum((payload->>'kosten_usd')::numeric),0) as k "
                f"from activities where type='recherche' "
                f"and payload ? 'kosten_usd' and created_at >= {seit}")
    ablaufend = json.loads(vertraege_ablaufend(tage=30))
    wv_map = {z["type"]: z["n"] for z in wv}
    daten = {
        "zeitraum": "letzte 7 Tage",
        "neue_leads": {z["s"]: z["n"] for z in neue},
        "bedarf": dict(bedarf[0]),
        "versand": {z["channel"]: z["n"] for z in versand},
        "wiedervorlagen": {"neu": wv_map.get("wiedervorlage", 0),
                           "erledigt": wv_map.get("wiedervorlage_erledigt", 0)},
        "entwuerfe_offen_jetzt": offen[0]["n"],
        "recherche_kosten_usd": round(float(kosten[0]["k"]), 2),
        "vertraege_ablaufend_30": ablaufend["anzahl"],
    }
    # `text` ist die eigentliche Lieferform: der Cron-Lauf soll NUR dieses
    # Feld weitergeben, damit der Betreiber einen Mehrzeiler bekommt und kein
    # JSON. Die Einzelfelder bleiben trotzdem stehen — wer nachrechnen will,
    # soll nicht den Fliesstext parsen muessen.
    zeilen = [f"Wochenbericht ({daten['zeitraum']}):",
              f"- Neue Kontakte: "
              f"{sum(daten['neue_leads'].values())} ({daten['neue_leads']})",
              f"- Bedarfsantworten: {daten['bedarf']['antworten']} "
              f"von {daten['bedarf']['kontakte']} Kontakten",
              f"- Versendet: {daten['versand'] or 'nichts'}",
              f"- Wiedervorlagen: {daten['wiedervorlagen']['neu']} neu, "
              f"{daten['wiedervorlagen']['erledigt']} erledigt",
              f"- Offene Entwuerfe jetzt: {daten['entwuerfe_offen_jetzt']}",
              f"- Recherche-Kosten: ${daten['recherche_kosten_usd']}",
              f"- Vertraege mit Ablauf in 30 Tagen: "
              f"{daten['vertraege_ablaufend_30']}"]
    return _json({**daten, "text": "\n".join(zeilen)})


# Fehlgeschlagene Entwuerfe werden nie automatisch wiederholt und sammeln sich
# deshalb an. Die Liste bleibt gedeckelt, damit ein Aufruf die Antwort nicht
# unbegrenzt aufblaeht; `anzahl_fehlgeschlagen` nennt die tatsaechliche Zahl,
# damit nichts stillschweigend verschwindet.
FEHLGESCHLAGEN_MAX = 20
FEHLER_KURZ = 120


def _zielangabe(kanal: str, empfaenger: str) -> dict:
    """Wohin ginge dieser Entwurf wirklich? — dieselbe Antwort wie im Versand.

    Nur WhatsApp wird ueber eine Nummer zugestellt. LinkedIn und E-Mail
    bekommen deshalb `zielnummer: null` ohne Warnhinweis: ein LinkedIn-Entwurf
    als „nicht zustellbar" zu kennzeichnen waere schlicht falsch, er geht ueber
    den Handversand raus.
    """
    if kanal != "whatsapp":
        return {"zielnummer": None}
    chat_id, _fehler = normalisiere_empfaenger(empfaenger)
    if chat_id is None:
        return {"zielnummer": None, "hinweis": "nicht zustellbar"}
    return {"zielnummer": chat_id}


@_gesichert
def entwuerfe_offen() -> str:
    """Alle Entwuerfe, die auf den Betreiber warten. Zwei Bloecke:

    `entwuerfe` — offene Freigaben (status='pending') sowie freigegebene
    LinkedIn-Entwuerfe, die noch auf den Handversand warten.
    `fehlgeschlagen` — Entwuerfe, deren Zustellung gescheitert ist, je mit
    Fehlergrund; sie werden NIE von selbst wiederholt und brauchen eine
    ausdrueckliche erneute Freigabe.

    Je Eintrag steht neben dem roh erfassten `empfaenger` die `zielnummer`,
    an die tatsaechlich zugestellt wuerde (null + hinweis, wenn die Nummer
    nicht zustellbar ist), der `consent`-Stand des Kontakts und
    `medien_datei` — der Anhang, der mitginge (null, wenn keiner dranhaengt).
    draft_id ist immer die vollstaendige UUID — Werkzeuge brauchen sie so.
    Vor jeder Freigabe-Entscheidung aufrufen."""
    zeilen = _q(
        "select d.id, d.channel, d.recipient, d.status, d.body, d.media_ref, "
        "       l.name, l.consent_status "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'pending' "
        "   or (d.status = 'approved' and d.channel = 'linkedin') "
        "order by d.created_at desc")
    gescheitert = _q(
        "select d.id, d.channel, d.recipient, d.error, d.media_ref, "
        "       l.name, l.consent_status "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'failed' order by d.created_at desc limit %s",
        (FEHLGESCHLAGEN_MAX,))
    anzahl = _q("select count(*) as n from drafts where status = 'failed'")
    return _json({
        "entwuerfe": [
            {"draft_id": z["id"], "kanal": z["channel"],
             "empfaenger": z["recipient"], "status": z["status"],
             "text": (z["body"] or "")[:200], "kontakt": z["name"],
             "consent": z["consent_status"], "medien_datei": z["media_ref"],
             **_zielangabe(z["channel"], z["recipient"])} for z in zeilen],
        "anzahl_fehlgeschlagen": anzahl[0]["n"],
        "fehlgeschlagen": [
            {"draft_id": z["id"], "kanal": z["channel"],
             "empfaenger": z["recipient"], "kontakt": z["name"],
             "consent": z["consent_status"], "medien_datei": z["media_ref"],
             "fehler": (z["error"] or "")[:FEHLER_KURZ],
             **_zielangabe(z["channel"], z["recipient"])} for z in gescheitert]})


def _entwurf_status_fehler(draft_id, erwarteter_status: str) -> str:
    """Baut die Fehlermeldung, wenn ein Statuswechsel am Ausgangsstatus
    scheitert: unbekannte draft_id vs. falscher tatsaechlicher Status."""
    zeilen = _q("select status from drafts where id = %s", (draft_id,))
    if not zeilen:
        return _json({"fehler": f"Kein Entwurf mit draft_id {draft_id}."})
    return _json({"fehler": f"Entwurf {draft_id} hat Status "
                            f"'{zeilen[0]['status']}', erwartet '{erwarteter_status}'."})


@_gesichert
def entwurf_freigeben(draft_id: str) -> str:
    """Entwurf freigeben (pending -> approved). Nur fuer den Betreiber. Setzt
    approved_by/approved_at und protokolliert die Freigabe. Freigibt NICHT
    fuer bereits freigegebene/abgelehnte/versendete Entwuerfe."""
    zeilen = _q(
        "update drafts set status = 'approved', approved_by = 'betreiber', "
        "approved_at = now() where id = %s and status = 'pending' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        return _entwurf_status_fehler(draft_id, "pending")
    z = zeilen[0]
    _q("insert into activities (lead_id, type, payload) values (%s, 'freigabe', %s) "
       "returning id",
       (z["lead_id"], _json({"draft_id": str(z["id"]), "kanal": z["channel"]})))
    return _json({"draft_id": z["id"], "status": "approved"})


@_gesichert
def entwurf_ablehnen(draft_id: str) -> str:
    """Entwurf ablehnen (pending -> rejected). Nur fuer den Betreiber.
    Protokolliert die Ablehnung. Lehnt NICHT bereits freigegebene/abgelehnte/
    versendete Entwuerfe ab."""
    zeilen = _q(
        "update drafts set status = 'rejected' where id = %s and status = 'pending' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        return _entwurf_status_fehler(draft_id, "pending")
    z = zeilen[0]
    _q("insert into activities (lead_id, type, payload) values (%s, 'ablehnung', %s) "
       "returning id",
       (z["lead_id"], _json({"draft_id": str(z["id"]), "kanal": z["channel"]})))
    return _json({"draft_id": z["id"], "status": "rejected"})


@_gesichert
def entwurf_manuell_gesendet(draft_id: str) -> str:
    """Quittiert einen bereits von Hand versendeten LinkedIn-Entwurf
    (approved -> sent). Versendet NICHTS selbst — nur fuer LinkedIn, WhatsApp
    versendet automatisch der Dispatcher. Nur nach tatsaechlichem
    Handversand aufrufen."""
    zeilen = _q(
        "update drafts set status = 'sent', sent_at = now() "
        "where id = %s and status = 'approved' and channel = 'linkedin' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        vorhanden = _q("select status, channel from drafts where id = %s", (draft_id,))
        if not vorhanden:
            return _json({"fehler": f"Kein Entwurf mit draft_id {draft_id}."})
        if vorhanden[0]["channel"] != "linkedin":
            return _json({"fehler": "nur für LinkedIn — WhatsApp versendet der Dispatcher"})
        return _entwurf_status_fehler(draft_id, "approved")
    z = zeilen[0]
    _q("insert into activities (lead_id, type, payload) values (%s, 'versand', %s) "
       "returning id",
       (z["lead_id"], _json({"draft_id": str(z["id"]), "kanal": z["channel"],
                             "weg": "manuell"})))
    return _json({"draft_id": z["id"], "status": "sent"})


# Praefix der Dispatcher-Claim-Marke (dispatch.py: CLAIM_PRAEFIX =
# "in Zustellung seit ..."). Kein Import von dispatch.py hier — dispatch.py
# importiert bereits server.py ("import server"), ein Ruecksimport waere ein
# Zirkelimport. server.py kennt deshalb nur das Textmuster, nicht das Modul.
_CLAIM_MARKE_PRAEFIX = "in Zustellung"


@_gesichert
def entwurf_erneut_freigeben(draft_id: str, bestaetigt: bool = False) -> str:
    """Einen an der Zustellung gescheiterten Entwurf erneut freigeben
    (failed -> approved). Nur fuer den Betreiber, nur der Retry-Weg fuer
    WhatsApp-Entwuerfe, die der Dispatcher als 'failed' markiert hat — der
    Dispatcher versucht sie danach in der naechsten Runde erneut.

    SCHUTZKANTE gegen Doppelversand: beginnt der aktuelle error-Text mit
    'in Zustellung' (die Claim-Marke des Dispatchers, gesetzt VOR dem
    eigentlichen Sendeversuch), kann ein Absturz zwischen Claim und Buchung
    bedeuten, dass die Nachricht BEREITS ZUGESTELLT wurde. Ohne
    bestaetigt=True wird der Aufruf in diesem Fall verweigert und der Status
    bleibt unveraendert; mit bestaetigt=True laeuft der Uebergang trotzdem."""
    zeilen = _q(
        "update drafts set status = 'approved', approved_by = 'betreiber', "
        "approved_at = now(), error = null "
        "where id = %s and status = 'failed' "
        "and (%s or error is null or error not like %s) "
        "returning id, lead_id, channel",
        (draft_id, bool(bestaetigt), f"{_CLAIM_MARKE_PRAEFIX}%"))
    if not zeilen:
        vorhanden = _q("select status, error from drafts where id = %s", (draft_id,))
        if not vorhanden:
            return _json({"fehler": f"Kein Entwurf mit draft_id {draft_id}."})
        status, error = vorhanden[0]["status"], vorhanden[0]["error"] or ""
        if status == "failed" and not bestaetigt and error.startswith(_CLAIM_MARKE_PRAEFIX):
            return _json({"fehler": (
                "Verweigert: dieser Entwurf traegt die Zustellungs-Marke des "
                "Dispatchers — ein Absturz zwischen Claim und Buchung kann "
                "bedeuten, dass die Nachricht BEREITS ZUGESTELLT wurde. Nur "
                "mit bestaetigt=True erneut freigeben, wenn das Risiko eines "
                f"Doppelversands ausdruecklich akzeptiert wird. error: {error}")})
        return _entwurf_status_fehler(draft_id, "failed")
    z = zeilen[0]
    _q("insert into activities (lead_id, type, payload) values (%s, 'freigabe', %s) "
       "returning id",
       (z["lead_id"], _json({"draft_id": str(z["id"]), "kanal": z["channel"],
                             "erneut": True})))
    return _json({"draft_id": z["id"], "status": "approved"})


# ---------------------------------------------------------------------------
# Recherche (Stufe 5) — Markt- und Firmendaten aus Google Maps über Apify.
#
# Der Aussenweg (HTTP, Preismodell, Normalisierung, Report-Markdown) steht in
# recherche.py; hier bleibt nur, was Datenbank oder Werkzeugschicht braucht.
# Beide Werkzeuge kosten bei jedem Aufruf echtes Geld (Free-Plan, $5 im Monat)
# — deshalb das harte `limit` und die Kostenzeile in jeder Antwort.
# ---------------------------------------------------------------------------

def _recherche_loggen(werkzeug: str, nutzlast: dict):
    """`activities`-Zeile am Sammel-Lead — oder ein Hinweis, warum nicht.

    Diese Funktion wirft NIE. Zum Zeitpunkt des Aufrufs ist der Apify-Lauf
    bezahlt und der Report geschrieben; ein fehlender Sammel-Lead oder ein
    Datenbankfehler darf dieses Ergebnis nicht in eine Fehlermeldung
    verwandeln. Er soll nur nicht stillschweigend verschwinden — deshalb der
    Hinweis in der Antwort.
    """
    if not recherche.RECHERCHE_LEAD_ID:
        return ("Nicht protokolliert: RECHERCHE_LEAD_ID ist nicht gesetzt "
                "(Sammel-Lead 'RECHERCHE (Sammelkontakt)' in .env eintragen).")
    try:
        _q("insert into activities (lead_id, type, payload) "
           "values (%s, 'recherche', %s) returning id",
           (recherche.RECHERCHE_LEAD_ID, _json({"werkzeug": werkzeug, **nutzlast})))
    except psycopg.Error as e:
        return (f"Nicht protokolliert: Datenbankfehler ({e.sqlstate}) beim "
                f"Schreiben der Recherche-Aktivität.")
    return None


def _ohne_none(objekt: dict) -> dict:
    """Hinweisfelder, die None sind, gehören nicht in die Antwort."""
    return {k: v for k, v in objekt.items() if v is not None}


@_gesichert
def marktanalyse(thema: str, region: str = "Regensburg", limit: int = 20) -> str:
    """Wettbewerber zu einem Thema in einer Region erheben und als
    Markdown-Report ablegen. Quelle sind oeffentliche Google-Maps-Firmendaten
    (Name, Adresse, Telefon, Website, Kategorie, Bewertung) — KEINE
    Personendaten.

    Beispiele fuer `thema`: "Versicherungsmakler", "Finanzberatung",
    "Steuerberater". `region` ist eine Freitextangabe wie "Regensburg" oder
    "Regensburg, Deutschland". `limit` ist die Obergrenze der Treffer;
    Vorgabe 20, mehr als 50 wird stillschweigend auf 50 gekappt — jeder
    Treffer kostet Guthaben.

    Zurueck kommen der Pfad des Reports unter /reports und eine Kurzfassung
    in fuenf Zeilen; gib die Kurzfassung wieder und nenne den Pfad, damit der
    Betreiber den Report wiederfindet. Zweimal dasselbe Thema am selben Tag
    ueberschreibt den Report (`ueberschrieben: true` sagt es).

    Dieses Werkzeug legt KEINE Kontakte an — dafuer gibt es b2b_leads."""
    ergebnis, fehler = recherche.suche(thema, region, limit)
    if fehler:
        return _json({"fehler": fehler})
    treffer = ergebnis["treffer"]
    if not treffer:
        _recherche_loggen("marktanalyse", {"thema": ergebnis["thema"],
                                           "region": ergebnis["region"],
                                           "limit": ergebnis["limit"],
                                           "treffer": 0})
        return _json({"treffer": 0, "hinweis": (
            f"Google Maps liefert zu '{ergebnis['thema']}' in "
            f"'{ergebnis['region']}' keine Treffer. Kein Report geschrieben — "
            f"anderen Suchbegriff oder groessere Region versuchen.")})
    inhalt = recherche.markt_report(ergebnis["thema"], ergebnis["region"],
                                    treffer, ergebnis["limit"],
                                    kosten=ergebnis["kosten_usd"])
    pfad, ueberschrieben, schreibfehler = None, False, None
    try:
        pfad, ueberschrieben = recherche.report_schreiben(
            recherche.report_name(ergebnis["thema"], ergebnis["region"]), inhalt)
    except (OSError, ValueError) as e:
        # Der Lauf ist bezahlt und die Zahlen stehen — sie gehen nicht
        # verloren, nur weil der Reportordner fehlt. Die Kurzfassung kommt
        # trotzdem zurueck, mit dem Grund daneben.
        schreibfehler = (f"Report konnte nicht abgelegt werden "
                         f"({type(e).__name__}: {e}) — liegt der Bind "
                         f"./reports:/reports am Container an?")
    hinweis = _recherche_loggen("marktanalyse", {
        "thema": ergebnis["thema"], "region": ergebnis["region"],
        "limit": ergebnis["limit"], "treffer": len(treffer),
        "report": pfad, "kosten_usd": ergebnis["kosten_usd"]})
    return _json(_ohne_none({
        "report": pfad, "ueberschrieben": ueberschrieben,
        "treffer": len(treffer), "kosten_usd": ergebnis["kosten_usd"],
        "kurzfassung": recherche.kurzfassung(ergebnis["thema"],
                                             ergebnis["region"], treffer),
        "fehler": schreibfehler, "protokoll": hinweis}))


@_gesichert
def b2b_leads(branche: str, region: str = "Regensburg", limit: int = 20) -> str:
    """Firmen einer Branche in einer Region recherchieren und die mit
    Telefonnummer als Kontakte anlegen (source='recherche'). Quelle sind
    oeffentliche Google-Maps-Firmendaten — KEINE Personendaten. Aufhaenger
    fuer das B2B-Gespraech ist die betriebliche Altersvorsorge.

    `limit` wie bei marktanalyse: Vorgabe 20, ueber 50 wird gekappt, jeder
    Treffer kostet Guthaben. Treffer ohne Telefonnummer werden NICHT angelegt
    (ohne Kanal kein Nutzen) und nur in der Antwort genannt. Firmen, deren
    Nummer schon im CRM steht, werden uebersprungen (Dedup wie in
    kontakt_anlegen).

    WICHTIG — diese Kontakte haben KEINE Einwilligung (consent 'unknown').
    Schlage fuer sie NIE einen WhatsApp-Entwurf vor und schreibe sie nie an;
    werbliche Kaltansprache per Messenger waere ein UWG-Verstoss. Erlaubt
    sind Textentwuerfe fuer LinkedIn oder Brief, die der Betreiber selbst von
    Hand versendet."""
    ergebnis, fehler = recherche.suche(branche, region, limit)
    if fehler:
        return _json({"fehler": fehler})
    treffer = ergebnis["treffer"]
    angelegt, dubletten, ohne_nummer, fehlgeschlagen = [], [], [], []
    for t in treffer:
        if not t["telefon"]:
            ohne_nummer.append(t["name"])
            continue
        # Ausdruecklich ueber das bestehende Werkzeug, nicht ueber ein eigenes
        # INSERT: nur so greift die Dedup-Kante aus kontakt_anlegen (gleiche
        # normalisierte Nummer -> kein zweiter Lead), und nur so gilt fuer
        # Recherche-Kontakte dieselbe Regel wie fuer alle anderen.
        antwort = json.loads(kontakt_anlegen(
            name=t["name"], phone=t["telefon"], source="recherche",
            notes=recherche.lead_notiz(t, ergebnis["thema"], ergebnis["region"])))
        if "fehler" in antwort:
            fehlgeschlagen.append(t["name"])
        elif antwort.get("angelegt"):
            # `company` fuellt kontakt_anlegen nicht — es kennt nur Personen.
            # Bei einem Firmenkontakt ist der Name die Firma, und die Spalte
            # soll das auch sagen; ein Nachtrag statt einer neuen Signatur am
            # meistgenutzten Werkzeug des Hauses. Der Nachtrag ist Kosmetik
            # und deshalb abgesichert: ein DB-Fehler hier darf nicht die
            # Schleife eines BEZAHLTEN Apify-Laufs abreissen — der Lead
            # existiert ja bereits, ihm fehlt nur die Spalte.
            try:
                _q("update leads set company = %s where id = %s returning id",
                   (t["name"], antwort["lead_id"]))
            except psycopg.Error:
                pass
            angelegt.append(t["name"])
        else:
            dubletten.append(t["name"])
    zaehler = {"treffer_gesamt": len(treffer), "angelegt": len(angelegt),
               "uebersprungen_dublette": len(dubletten),
               "ohne_nummer": len(ohne_nummer)}
    if fehlgeschlagen:
        zaehler["nicht_angelegt_fehler"] = len(fehlgeschlagen)
    hinweis = _recherche_loggen("b2b_leads", {
        "branche": ergebnis["thema"], "region": ergebnis["region"],
        "limit": ergebnis["limit"], "kosten_usd": ergebnis["kosten_usd"],
        **zaehler})
    return _json(_ohne_none({
        **zaehler, "kosten_usd": ergebnis["kosten_usd"],
        "erste_namen": angelegt[:5],
        "ohne_nummer_namen": ohne_nummer[:10],
        "protokoll": hinweis,
        "hinweis": ("Recherche-Kontakte ohne Einwilligung (consent 'unknown'): "
                    "nicht per WhatsApp anschreiben, keine Kalt-Entwuerfe "
                    "vorschlagen. Erstkontakt macht der Betreiber selbst.")}))


# Die DSGVO-Linie dieses Werkzeugs ist Konstruktion, nicht Prompt: der Text
# unten wird zurueckgegeben, BEVOR irgendetwas abgerufen wird. Ein Werkzeug,
# das die Regel nur in seinem Docstring traegt, haengt an der Tagesform des
# Modells; dieses hier kann eine Person gar nicht recherchieren.
FEHLER_NUR_FIRMENKONTAKTE = (
    "firma_anreichern arbeitet ausschliesslich fuer Firmenkontakte — dieser "
    "Kontakt hat keinen Firmeneintrag (Feld 'company' ist leer). Kundendaten "
    "kommen aus der Bedarfsanalyse, nicht aus dem Netz. Es wurde nichts "
    "abgerufen.")


@_gesichert
def firma_anreichern(lead_id: str, website: str = "") -> str:
    """Oeffentliche Firmendaten von der WEBSITE EINES FIRMENKONTAKTS lesen —
    Gespraechsvorbereitung fuer den bAV-Erstkontakt (Betriebsgroesse, Inhaber
    laut Impressum, seit wann am Markt, Leistungen).

    NUR FUER FIRMENKONTAKTE. Hat der Kontakt kein Feld `company`, bricht das
    Werkzeug ab, ohne irgendetwas abzurufen — das ist keine Einstellung,
    sondern eingebaut. Fuer Kundinnen und Kunden gibt es dieses Werkzeug
    nicht: was ueber sie bekannt ist, stammt aus dem Gespraech
    (`bedarf_speichern`, `profil_aktualisieren`), niemals aus dem Netz.

    Gelesen werden die Startseite und bis zu vier Unterseiten DERSELBEN
    Website (Impressum, Ueber uns, Kontakt, Leistungen — Team-Seiten
    ausdruecklich nicht: Beschaeftigtenlisten sind Personendaten). Der
    einzige Personenbezug, der entsteht, ist der Name der Vertretung aus dem
    Impressum — eine gesetzliche Pflichtangabe der Firma selbst. `website`
    ist optional: ohne Angabe nimmt das Werkzeug die zuletzt gespeicherte
    Adresse und sonst die „Website: …"-Zeile aus den Notizen. Wird sie
    angegeben, muss sie die Website DIESER FIRMA sein — das Werkzeug prueft
    den Kontakttyp, nicht die Zugehoerigkeit der Adresse; wer hier die Seite
    eines Dritten eintraegt, recherchiert einen Dritten, und dafuer ist das
    Werkzeug nicht da.

    Der Abruf kostet nichts (kein Fremddienst, keine Guthaben) — er dauert
    aber ein paar Sekunden. Zurueck kommen fuenf Zeilen Zusammenfassung; den
    vollstaendigen Text der gelesenen Seiten zeigt `profil_lesen` unter
    `firma`. Ein zweiter Aufruf ersetzt den gespeicherten Stand."""
    leads = _q("select id, name, company, notes, enrichment from leads "
               "where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    lead = leads[0]
    # Die Kante VOR jeder Adressermittlung und erst recht vor jedem HTTP.
    if not (lead["company"] or "").strip():
        return _json({"fehler": FEHLER_NUR_FIRMENKONTAKTE})

    vorhanden = (lead["enrichment"] or {}).get("firma")
    gespeichert = (vorhanden or {}).get("website", "") if isinstance(vorhanden, dict) else ""
    adresse = ((website or "").strip() or gespeichert
               or recherche.website_aus_notiz(lead["notes"]))
    if not adresse:
        return _json({"fehler": (
            f"Fuer '{lead['name']}' ist keine Website hinterlegt — weder als "
            f"Parameter, noch im Profil, noch als 'Website: …' in den Notizen. "
            f"Die Adresse mit firma_anreichern(lead_id, website='https://…') "
            f"uebergeben. Es wurde nichts abgerufen.")})

    daten, fehler = recherche.firma_daten(adresse)
    if fehler:
        return _json({"fehler": fehler})

    # `nicht_gelesen` wandert MIT in die Ablage: wer das Profil spaeter liest,
    # soll wissen, welche Seiten fehlten (Abweisung, Zeitbudget) — sonst
    # liest sich ein Teilergebnis wie ein vollstaendiges.
    knoten = {"website": daten["website"], "seiten": daten["seiten"],
              "hinweise": daten["hinweise"],
              "nicht_gelesen": daten["nicht_gelesen"],
              "stand": date.today().isoformat()}
    # EIN jsonb_set genuegt hier — und das ist kein Vergessen des Musters aus
    # profil_aktualisieren/bedarf_speichern, sondern sein Kern: `create_missing`
    # legt nur das LETZTE Pfadelement an, wenn dessen Elternobjekt existiert.
    # Dort ist der Pfad zweistufig ('{profil,feld}'), das Elternobjekt `profil`
    # fehlt auf frischen Kontakten, deshalb die Verschachtelung. Hier ist der
    # Pfad einstufig ('{firma}'); Elternobjekt ist die Wurzel, und die ist laut
    # db/provision.sql `not null default '{}'::jsonb`, existiert also immer.
    # Empirisch gegen sales_test geprueft, nicht abgeleitet.
    zeilen = _q(
        "update leads set enrichment = jsonb_set(enrichment, '{firma}', "
        "%s::jsonb, true), updated_at = now() where id = %s returning id",
        (_json(knoten), lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})

    nutzlast = {"website": daten["website"],
                "seiten_anzahl": daten["seiten_anzahl"],
                "kosten_usd": daten["kosten_usd"]}
    # Zwei Protokollorte, und beide haben ihren Grund: die Aktivitaet AM LEAD
    # macht in dessen Historie sichtbar, dass und wann recherchiert wurde
    # (`profil_lesen` zeigt sie) — der Sammelkontakt sammelt daneben alle
    # Recherche-Laeufe des Hauses an einer Stelle, wie bei marktanalyse und
    # b2b_leads. Der Lauf ist zu diesem Zeitpunkt getan; ein Protokollfehler
    # darf sein Ergebnis nicht in eine Fehlermeldung verwandeln.
    try:
        _q("insert into activities (lead_id, type, payload) "
           "values (%s, 'recherche', %s) returning id",
           (lead_id, _json({"werkzeug": "firma_anreichern", **nutzlast})))
    except psycopg.Error:
        pass
    hinweis = _recherche_loggen("firma_anreichern",
                                {"lead_id": str(lead_id), "name": lead["name"],
                                 **nutzlast})
    nicht_gelesen = [n["url"] for n in daten["nicht_gelesen"]]
    return _json(_ohne_none({
        "lead_id": lead["id"], "firma": lead["name"],
        "website": daten["website"], "seiten_anzahl": daten["seiten_anzahl"],
        "gelesene_seiten": [{"url": s["url"], "typ": s["typ"]}
                            for s in daten["seiten"]],
        "nicht_gelesen": nicht_gelesen or None,
        "kosten_usd": daten["kosten_usd"],
        "kurzfassung": recherche.firma_kurzfassung(lead["name"], daten),
        "protokoll": hinweis,
        "hinweis": ("Gib die fuenf Zeilen wieder. Den vollstaendigen Text der "
                    "gelesenen Seiten zeigt profil_lesen(lead_id) unter "
                    "'firma' — dort steht, was im Erstgespraech verwendbar "
                    "ist. Der Abruf kostete nichts.")}))


WERKZEUGE = (kontakt_suchen, kontakt_anlegen, kontakt_aktualisieren,
             aktivitaet_loggen, wiedervorlage_setzen, wiedervorlage_erledigt,
             vertrag_speichern, vertraege_ablaufend,
             profil_lesen, profil_aktualisieren,
             bedarf_speichern, bedarf_offen, entwurf_erstellen,
             post_entwurf_erstellen, medien_liste,
             digest, wochenbericht,
             entwuerfe_offen, entwurf_freigeben, entwurf_ablehnen,
             entwurf_manuell_gesendet, entwurf_erneut_freigeben,
             marktanalyse, b2b_leads, firma_anreichern)

for _fn in WERKZEUGE:
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
