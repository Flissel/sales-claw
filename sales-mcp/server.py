"""sales-mcp — Werkzeugdienst des sales-claw-Prototyps.

Die deutschen Werkzeuge des Hauses über MCP (streamable-http) — wie viele
es sind, sagt das WERKZEUGE-Tupel am Dateiende, nicht dieser Satz (er stand
zweimal veraltet da, bei „zwanzig", als es 22 und dann 26 waren).
Kein Send-Werkzeug:
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
import uuid
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
# Termine (Stufe 9): ICS-Text und der optionale CalDAV-Eintrag. Wieder ein
# Modul ohne Datenbank und ohne Rückimport — und der einzige Ort, an dem
# der neue ausgehende Pfad dieser Stufe steht.
import kalender
# Und aus demselben Grund wie `nummern.py` (Anzeige und Versand dürfen nie
# zwei verschiedene Regeln benutzen): die Prüfung einer E-Mail-Adresse.
# `entwuerfe_offen` zeigt damit die Adresse an, an die sales-mail
# tatsächlich zustellen würde.
import mailadresse

SCHEMA = os.environ.get("SALES_DB_SCHEMA", "sales")
if SCHEMA not in ("sales", "sales_test"):
    raise SystemExit(f"Unzulaessiges Schema '{SCHEMA}' — erlaubt: sales, sales_test")

LEITFADEN = yaml.safe_load(
    (Path(__file__).parent / "leitfaden.yaml").read_text(encoding="utf-8"))
ALLE_FRAGEN = {f["id"]: {"frage": f["frage"], "gruppe": g["titel"]}
               for g in LEITFADEN["gruppen"] for f in g["fragen"]}

# TimeZone=UTC ist festgenagelt, nicht geerbt (Review-Befund B8): die
# Python-Schicht rechnet durchgehend datetime.now(timezone.utc), und jede
# current_date-Bedingung in digest()/wochenbericht() muss auf DERSELBEN
# Basis stehen. Bisher stimmte das nur, weil der Server-Default UTC ist und
# PGTZ nicht gesetzt war — eine Umgebungseigenschaft. Jetzt ist es eine
# Zusicherung dieser Verbindung (Test: show timezone in test_vertraege.py).
pool = ConnectionPool(
    os.environ["SALES_DB_URL"], min_size=1, max_size=4, open=True,
    kwargs={"row_factory": dict_row,
            "options": f"-c search_path={SCHEMA} -c TimeZone=UTC"})

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
        "select id, name, status, consent_status, enrichment from leads "
        "where name ilike %s or email ilike %s or phone ilike %s "
        "order by updated_at desc limit 10",
        (f"%{text}%", f"%{text}%", f"%{text}%"))
    return _json({"kontakte": [
        {"lead_id": z["id"], "name": z["name"], "status": z["status"],
         "consent": z["consent_status"],
         "whatsapp_freigabe": _whatsapp_freigegeben(z["enrichment"])}
        for z in zeilen]})


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


# ---------------------------------------------------------------------------
# Kontakt-Freigabe fuer WhatsApp (OpenClaw) — das Gate VOR dem Nachrichten-Gate.
#
# Die Freigabe je Nachricht (entwurf_freigeben) sagt, DASS dieser eine Text
# raus darf. Sie sagte bisher nichts darueber, ob der KONTAKT ueberhaupt per
# WhatsApp angeschrieben werden soll — das stand nur in den Agent-Regeln, also
# im Modellverhalten. Die Kante gehoert in die Werkzeugschicht (Projektprinzip,
# siehe kontakt_anlegen/B1): ohne ausdrueckliche Kontakt-Freigabe des
# Betreibers entsteht kein WhatsApp-Entwurf (entwurf_erstellen), und der
# Dispatcher stellt nichts zu (dispatch.verarbeite_draft prueft mit GENAU
# derselben Funktion _whatsapp_freigegeben — Anzeige, Entwurf und Versand
# duerfen nie verschiedene Regeln benutzen, siehe nummern.py).
#
# Gespeichert wird ohne DDL (die Rolle sales_app hat keins) als Schluessel
# `whatsapp_freigabe` DIREKT unter enrichment — bewusst NICHT unter
# enrichment->profil: dort schreibt profil_aktualisieren per Freitext, und
# eine Freigabe, die das Modell selbst setzen kann, waere keine. Die beiden
# Werkzeuge hier sind der einzige Schreibweg.
#
# Getrennt von consent_status: consent sagt, ob der KONTAKT einverstanden ist
# (seine Antwort, bedarf_speichern 'consent_kontakt'); whatsapp_freigabe sagt,
# ob der BETREIBER den Versandweg oeffnet. Keins ersetzt das andere, keins
# wird je aus dem anderen abgeleitet — dieselbe Trennung wie beim
# Newsletter-Status (AGENTS.md).
# ---------------------------------------------------------------------------

def _whatsapp_freigegeben(enrichment) -> bool:
    """True NUR bei ausdruecklicher, nicht entzogener Betreiber-Freigabe.

    Alles andere — fehlender Schluessel (Bestandskontakte), entzogene
    Freigabe, kaputter Wert — zaehlt als nicht freigegeben (fail-closed)."""
    eintrag = (enrichment or {}).get("whatsapp_freigabe")
    return isinstance(eintrag, dict) and eintrag.get("freigegeben") is True


def _whatsapp_freigabe_setzen(lead_id: str, freigegeben: bool) -> str:
    zeilen = _q(
        "update leads set enrichment = jsonb_set(enrichment, "
        "'{whatsapp_freigabe}', %s::jsonb, true) where id = %s "
        "returning id, name",
        (json.dumps({"freigegeben": freigegeben, "at": _jetzt(),
                     "durch": "betreiber"}), lead_id))
    if not zeilen:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    _q("insert into activities (lead_id, type, payload) values "
       "(%s, 'kontakt_freigabe', %s) returning id",
       (lead_id, _json({"kanal": "whatsapp", "freigegeben": freigegeben})))
    return _json({"lead_id": zeilen[0]["id"], "kontakt": zeilen[0]["name"],
                  "whatsapp_freigabe": freigegeben})


@_gesichert
def kontakt_freigeben(lead_id: str) -> str:
    """Kontakt fuer WhatsApp-Nachrichten (OpenClaw) freigeben. NUR auf
    ausdrueckliche Anweisung des Betreibers aufrufen — nie aus eigenem
    Antrieb, nie „damit der Entwurf durchgeht". Ohne diese Freigabe entsteht
    kein WhatsApp-Entwurf und der Dispatcher stellt nichts zu. Die Freigabe
    je Nachricht (entwurf_freigeben) bleibt zusaetzlich bestehen; E-Mail und
    LinkedIn sind nicht betroffen. Die Freigabe ersetzt KEINE Einwilligung
    des Kontakts (consent, UWG) — beide Fragen bleiben getrennt."""
    return _whatsapp_freigabe_setzen(lead_id, True)


@_gesichert
def kontakt_freigabe_entziehen(lead_id: str) -> str:
    """WhatsApp-Freigabe eines Kontakts entziehen (Betreiber-Entscheidung
    oder Kundenwunsch „keine Nachrichten mehr" — dann SOFORT aufrufen und den
    Vollzug bestaetigen). Ab sofort entsteht kein neuer WhatsApp-Entwurf;
    bereits freigegebene Entwuerfe an diesen Kontakt stellt der Dispatcher
    nicht mehr zu, sie werden mit klarem Grund fehlgeschlagen gebucht."""
    return _whatsapp_freigabe_setzen(lead_id, False)


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

    # Dubletten-Kante (Review-Befund B3) — dasselbe Gesetz wie bei
    # kontakt_anlegen: die Kante gehoert in die Werkzeugschicht, nicht ins
    # Modellverhalten. Ein gespraechiges Modell, das denselben Vertrag im
    # Verlauf erneut nennt, haengte sonst einen zweiten Array-Eintrag an und
    # legte eine ZWEITE Wiedervorlage an — und jede will einzeln erledigt
    # werden. Gleich sind zwei Vertraege, wenn Sparte, Gesellschaft und
    # Ablauf uebereinstimmen; die Notiz unterscheidet nicht (sie aendert
    # nicht, WELCHER Vertrag gemeint ist).
    def _kern(v):
        return (str(v.get("sparte", "")).strip().lower(),
                str(v.get("gesellschaft", "")).strip().lower(),
                str(v.get("ablauf", "")))
    bestand = _q("select enrichment->'vertraege' as v from leads "
                 "where id = %s", (lead_id,))
    if not bestand:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    vorhandene = bestand[0]["v"] if isinstance(bestand[0]["v"], list) else []
    if any(isinstance(v, dict) and _kern(v) == _kern(vertrag)
           for v in vorhandene):
        return _json({"vertrag": vertrag, "angelegt": False,
                      "wiedervorlage": None,
                      "hinweis": ("Identischer Vertrag (Sparte/Gesellschaft/"
                                  "Ablauf) ist bereits erfasst — nichts "
                                  "angelegt, keine zweite Wiedervorlage.")})
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
    return _json({"vertrag": vertrag, "angelegt": True,
                  "wiedervorlage": wiedervorlage,
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
    # Das Datum wird in PYTHON gefiltert, nicht per ::date im SQL: der Cast
    # wirft bei jedem nicht-datumsfoermigen `ablauf` (SQLSTATE 22007/22008),
    # und EINE solche Fremddatenzeile irgendwo in leads machte das Werkzeug
    # fuer ALLE Kontakte unbrauchbar — und riss den Wochenbericht mit
    # (Review-Befund B1; gemessen mit "nicht-datum", "31.12.2027",
    # "2027-13-45"). Ein Regex-Vorfilter reichte nicht: "2027-02-31"
    # passiert ihn und wirft trotzdem. date.fromisoformat entscheidet
    # abschliessend; Unlesbares wird uebergangen statt geworfen. Das
    # jsonb_typeof(v)='object' daneben faengt Array-Elemente, die keine
    # Objekte sind — dieselbe Fremddatenklasse, eine Ebene tiefer.
    zeilen = _q(
        "select l.id as lead_id, l.name, v->>'sparte' as sparte, "
        "       v->>'ablauf' as ablauf "
        "from leads l, jsonb_array_elements("
        "       case when jsonb_typeof(l.enrichment->'vertraege') = 'array' "
        "            then l.enrichment->'vertraege' else '[]'::jsonb end) v "
        "where jsonb_typeof(v) = 'object' "
        "  and coalesce(v->>'ablauf', '') <> ''")
    heute = datetime.now(timezone.utc).date()
    treffer = []
    for z in zeilen:
        try:
            ablauf = date.fromisoformat(z["ablauf"])
        except (TypeError, ValueError):
            continue
        if heute <= ablauf <= heute + timedelta(days=fenster):
            treffer.append(z)
    # ISO-Datumsstrings sortieren lexikografisch chronologisch.
    treffer.sort(key=lambda z: z["ablauf"])
    return _json({"anzahl": len(treffer), "fenster_tage": fenster,
                  "vertraege": treffer})


# ---------------------------------------------------------------------------
# Termine (Stufe 9, G1) — der Kalendereintrag zum vereinbarten Gespraech.
#
# Das Werkzeug HAELT FEST, worauf sich zwei Menschen muendlich geeinigt
# haben. Es lädt niemanden ein, es versendet nichts und es fragt keinen
# Kalender nach freien Zeiten: es erzeugt eine ICS-Datei in /reports, legt
# — auf Wunsch — denselben Termin in den Kalender des Betreibers und
# schreibt eine Wiedervorlage fuer den Vortag. Der Bestaetigungstext kommt
# als TEXT zurueck; ob daraus eine Nachricht wird, entscheidet der
# Betreiber ueber `entwurf_erstellen` und die Freigabe wie bei jedem
# anderen Text auch. Das Freigabe-Gate bleibt damit unberuehrt.
#
# Warum die Wiedervorlage automatisch entsteht (und die Erinnerung NICHT):
# der haeufigste Grund fuer einen geplatzten Termin ist, dass niemand mehr
# daran gedacht hat. Die Wiedervorlage taucht im Digest auf und erinnert
# den BETREIBER — die Erinnerungs-NACHRICHT an den Kunden entsteht wie
# jede andere Nachricht: als Entwurf, mit Freigabe. Eine automatische
# Kundenerinnerung waere ein zweiter Egress-Pfad am Gate vorbei.
# ---------------------------------------------------------------------------

TERMIN_DAUER_MIN = 15
TERMIN_DAUER_MAX = 480
TERMIN_DAUER_VORGABE = 60
# `thema` und `ort` landen in SUMMARY/LOCATION der ICS und im
# Bestaetigungstext. Freitext ohne Deckel waere in beiden ein Problem —
# gekappt statt abgelehnt, wie `recherche.kappe_limit`: eine zu lange
# Angabe ist ein Schaetzfehler, kein Bedienfehler.
TERMIN_TEXT_MAXLAENGE = 120
TERMIN_ERINNERUNG_TAGE = 1

WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag")


def _termin_dauer(dauer) -> int:
    """Wunsch -> erlaubte Dauer. Kappung, kein Fehler (siehe oben)."""
    try:
        return max(TERMIN_DAUER_MIN, min(int(dauer), TERMIN_DAUER_MAX))
    except (TypeError, ValueError):
        return TERMIN_DAUER_VORGABE


@_gesichert
def termin_bestaetigen(lead_id: str, datum: str, uhrzeit: str,
                       dauer_minuten: int = TERMIN_DAUER_VORGABE,
                       thema: str = "Erstgespraech", ort: str = "") -> str:
    """Einen muendlich vereinbarten Termin festhalten: Kalenderdatei (.ics)
    nach /reports, Eintrag im Kalender des Betreibers (falls konfiguriert),
    automatische Wiedervorlage „Terminerinnerung" am Vortag und ein
    fertiger, kurzer Bestaetigungstext.

    `datum` ISO (YYYY-MM-DD, nicht in der Vergangenheit), `uhrzeit` als
    HH:MM in ORTSZEIT (Europe/Berlin), `dauer_minuten` 15–480 (wird
    gekappt), `thema`/`ort` kurzer Freitext.

    Es wird NICHTS versendet: der `bestaetigungstext` ist ein Vorschlag,
    aus dem der Betreiber auf Zuruf ueber `entwurf_erstellen` eine
    Nachricht machen kann — mit Freigabe wie immer. Die ICS-Datei liegt in
    `reports\\`; soll sie an eine Nachricht, kopiert der Betreiber sie von
    Hand nach `media\\` (dort legt nur ein Mensch ab). Ein zweiter Termin
    mit demselben Kontakt am selben Tag ueberschreibt die Datei —
    `ueberschrieben: true` sagt es."""
    leads = _q("select name from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    name = leads[0]["name"]

    try:
        tag = date.fromisoformat((datum or "").strip())
    except ValueError:
        return _json({"fehler": f"Ungueltiges Datum '{datum}' — erwartet "
                                f"ISO-Format YYYY-MM-DD."})
    try:
        zeit = datetime.strptime((uhrzeit or "").strip(), "%H:%M").time()
    except ValueError:
        return _json({"fehler": f"Ungueltige Uhrzeit '{uhrzeit}' — erwartet "
                                f"HH:MM (24-Stunden-Form, z. B. 14:30)."})
    heute = datetime.now(timezone.utc).date()
    if tag < heute:
        return _json({"fehler": f"Der Termin {tag.isoformat()} liegt in der "
                                f"Vergangenheit — es wurde nichts angelegt."})

    dauer = _termin_dauer(dauer_minuten)
    thema_kurz = (thema or "").strip()[:TERMIN_TEXT_MAXLAENGE] or "Termin"
    ort_kurz = (ort or "").strip()[:TERMIN_TEXT_MAXLAENGE]
    beginn = datetime.combine(tag, zeit)
    uid = f"{uuid.uuid4()}@sales-claw"
    ics_text = kalender.ics(uid, beginn, dauer, f"{thema_kurz} — {name}",
                            ort=ort_kurz)

    # Der Kundenname geht in einen Dateinamen — also durch `slug` (Whitelist
    # [a-z0-9-]) und danach durch die Einbettungspruefung in
    # `report_schreiben`. Dasselbe zweistufige Muster wie bei der Uebergabe.
    dateiname = f"termin-{recherche.slug(name)}-{tag.isoformat()}.ics"
    pfad, ueberschrieben, schreibfehler = None, False, None
    try:
        pfad, ueberschrieben = recherche.report_schreiben(dateiname, ics_text)
    except (OSError, ValueError) as ex:
        # Wie bei der Uebergabe: der Termin ist vereinbart, und daran haengt
        # die Wiedervorlage. Ein fehlender Reportordner darf das nicht
        # kassieren — er kostet nur die Datei.
        schreibfehler = (f"Die Kalenderdatei konnte nicht abgelegt werden "
                         f"({type(ex).__name__}: {ex}) — liegt der Bind "
                         f"./reports:/reports am Container an? Termin und "
                         f"Wiedervorlage stehen trotzdem.")

    # Kalender-Eintrag (G1b). Unabhaengig von der Datei: der eine Weg darf
    # den anderen nicht mitreissen.
    zustand, grund = kalender.eintragen(uid, ics_text)
    kalender_stand = {kalender.NICHT_KONFIGURIERT: "nicht konfiguriert",
                      kalender.EINGETRAGEN: "eingetragen"}.get(
        zustand, f"fehlgeschlagen: {grund}")

    faellig = max(heute, tag - timedelta(days=TERMIN_ERINNERUNG_TAGE))
    wv_id = _wiedervorlage_anlegen(
        lead_id, faellig,
        f"Terminerinnerung: {thema_kurz} mit {name} am {tag.isoformat()} "
        f"um {zeit:%H:%M}")

    _q("insert into activities (lead_id, type, payload) values "
       "(%s, 'termin', %s) returning id",
       (lead_id, _json({"datum": tag.isoformat(), "uhrzeit": f"{zeit:%H:%M}",
                        "dauer_minuten": dauer, "thema": thema_kurz,
                        "ort": ort_kurz, "pfad": pfad, "uid": uid,
                        "kalender": kalender_stand})))

    hinweis = (f"Die Kalenderdatei liegt in reports\\{dateiname}. Zum "
               f"Mitsenden kopiert der Betreiber sie von Hand nach media\\ "
               f"und haengt sie mit entwurf_erstellen(..., medien_datei="
               f"'{dateiname}') an.")
    if zustand == kalender.NICHT_KONFIGURIERT:
        hinweis += (" Ein Kalender ist nicht konfiguriert (CALDAV_URL, "
                    "CALDAV_USER, CALDAV_PASSWORT in der .env) — es entstand "
                    "nur die Datei.")
    return _json(_ohne_none({
        "pfad": pfad, "ueberschrieben": ueberschrieben,
        "fehler": schreibfehler,
        "termin": {"datum": tag.isoformat(), "uhrzeit": f"{zeit:%H:%M}",
                   "dauer_minuten": dauer, "thema": thema_kurz,
                   "ort": ort_kurz or None},
        "kalender": kalender_stand,
        "bestaetigungstext": _bestaetigungstext(beginn, dauer, thema_kurz,
                                                ort_kurz),
        # Bleibt IMMER stehen, auch wenn sie auf heute faellt — sie ist der
        # eigentliche Zweck dieses Werkzeugs (gleiche Zusage wie bei
        # vertrag_speichern).
        "wiedervorlage": {"aktivitaets_id": wv_id,
                          "faellig_am": faellig.isoformat()},
        "hinweis": hinweis}))


def _bestaetigungstext(beginn: datetime, dauer: int, thema: str,
                       ort: str) -> str:
    """Der fertige, kurze Text fuer die Bestaetigung an den Kunden.

    Bewusst ohne Produkt-, Tarif- oder Konditionsaussage (§34d, siehe
    AGENTS.md „Verbote") und ohne jede Bedarfsangabe: er geht im Zweifel
    woertlich an den Kunden. Gesiezt, weil ungefragt niemand geduzt wird.
    """
    wochentag = WOCHENTAGE[beginn.weekday()]
    zeilen = [f"Ihr Termin steht: {wochentag}, {beginn:%d.%m.%Y} um "
              f"{beginn:%H:%M} Uhr ({thema})."]
    if ort:
        zeilen.append(f"Ort: {ort}.")
    zeilen.append(f"Eingeplant sind {dauer} Minuten. Falls etwas "
                  f"dazwischenkommt, sagen Sie einfach kurz Bescheid.")
    return " ".join(zeilen)


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
                  # Getrennt vom consent (siehe Kontakt-Freigabe oben): sagt,
                  # ob der Betreiber den WhatsApp-Versandweg geoeffnet hat.
                  "whatsapp_freigabe": _whatsapp_freigegeben(e),
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
    ohne jede Pfadangabe, Endung pdf/jpg/jpeg/png/mp3/ogg/ics, hoechstens
    15 MB. Passt etwas davon nicht, entsteht KEIN Entwurf und der Grund
    kommt als Fehlertext zurueck. Bei WhatsApp geht der Anhang zusammen mit
    dem Text in EINER Nachricht raus (der Text wird zur Bildunterschrift und
    darf deshalb hoechstens 1024 Zeichen haben); bei linkedin ist der
    Dateiname nur ein Merkposten fuer den Handversand.

    BEI E-MAIL GEHEN ANHAENGE NICHT MIT: sales-mail versendet in dieser
    Fassung reinen Text. Ein E-Mail-Entwurf MIT `medien_datei` wird beim
    Versand ausdruecklich fehlgeschlagen gebucht, statt ohne die Unterlage
    rauszugehen — freigegeben wurde eine Nachricht MIT Unterlage. Wer eine
    Datei per Mail schicken will, sendet sie von Hand und quittiert mit
    entwurf_manuell_gesendet."""
    if kanal not in ("whatsapp", "linkedin", "email"):
        return _json({"fehler": f"Unzulaessiger Kanal '{kanal}'. "
                                f"Erlaubt: whatsapp, linkedin, email"})
    leads = _q("select name, phone, email, enrichment from leads where id = %s",
               (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    # Kontakt-Freigabe VOR dem Insert (frueh sagen statt spaet scheitern,
    # dieselbe Begruendung wie bei CAPTION_MAXLAENGE): ein WhatsApp-Entwurf
    # fuer einen nicht freigegebenen Kontakt soll gar nicht erst in der
    # Freigabe-Queue auftauchen. Der Dispatcher prueft beim Zustellen erneut
    # — das hier ist die fruehe Rueckmeldung, dort ist das harte Gate.
    if kanal == "whatsapp" and not _whatsapp_freigegeben(leads[0]["enrichment"]):
        return _json({"fehler": (
            "Kontakt ist nicht fuer WhatsApp freigegeben — es entsteht kein "
            "Entwurf. Die Freigabe erteilt ausschliesslich der Betreiber "
            "(kontakt_freigeben(lead_id)); frag ihn, statt sie selbst zu "
            "setzen. E-Mail und LinkedIn stehen weiter offen.")})
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
    hinweis = "Nicht versendet — wartet in der Queue."
    if basis and kanal == "email":
        # Frueh sagen statt spaet scheitern: sales-mail bucht einen
        # E-Mail-Entwurf mit Anhang fehlgeschlagen (er ginge sonst ohne die
        # Unterlage raus, die jemand freigegeben hat). Das soll der Betreiber
        # beim Erstellen erfahren, nicht erst nach der Freigabe.
        hinweis += (f" ACHTUNG: E-Mails gehen als reiner Text raus — dieser "
                    f"Entwurf traegt den Anhang '{basis}' und wird deshalb "
                    f"beim Versand fehlschlagen. Entweder ohne Anhang neu "
                    f"erstellen — oder die Unterlage von Hand aus dem "
                    f"Mailprogramm schicken; der Entwurf bleibt dann als "
                    f"failed dokumentiert (entwurf_manuell_gesendet gilt "
                    f"NUR fuer LinkedIn).")
    return _json({"draft_id": zeilen[0]["id"], "status": zeilen[0]["status"],
                  "medien_datei": basis, "hinweis": hinweis})


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
    mp3, ogg, ics)."""
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


# ---------------------------------------------------------------------------
# Support-Posteingang (Stufe 8) — die Unbeantwortet-Sicht.
#
# Reine Lese-/Protokollschicht: `posteingang` zeigt, wer geschrieben und noch
# keine Antwort bekommen hat. Es wird NICHTS automatisch beantwortet, kein
# `drafts`-Satz angefasst und kein Versandweg geoeffnet — das Freigabe-Gate
# (Grundsatzentscheidung 1) bleibt unberuehrt. Ob und was geantwortet wird,
# entscheidet der Betreiber, und der Weg dorthin ist unveraendert
# entwurf_erstellen -> Freigabe -> Dispatcher.
# ---------------------------------------------------------------------------

# Der Sammelkontakt „Unbekannte Eingaenge" aus inbox.py — dieselbe .env-Variable,
# hier nur gelesen. Gleiches Muster wie LINKEDIN_POST_LEAD_ID: die UUID kommt
# aus der Umgebung, Tests biegen das Modulattribut um. Ohne sie funktioniert
# `posteingang` weiter, kann die Unbekannten dann aber nicht mehr nach
# Absendernummer trennen (siehe unten).
UNBEKANNT_LEAD_ID = os.environ.get("INBOX_UNBEKANNT_LEAD_ID", "").strip()

# Fenstergrenzen: unter einer Stunde ist die Sicht sinnlos, ueber einer Woche
# ist sie kein Postfach mehr, sondern eine Historie (dafuer gibt es
# profil_lesen). Gekappt statt abgelehnt, damit ein vertippter Aufruf eine
# Antwort bekommt und keine Fehlermeldung.
POSTEINGANG_STUNDEN_MIN = 1
POSTEINGANG_STUNDEN_MAX = 168
POSTEINGANG_LIMIT = 25
POSTEINGANG_TEXT_MAX = 160
# Was als Antwort zaehlt. `versand` = der Dispatcher hat zugestellt (Gate-
# Protokoll), `nachricht_ausgehend` = im Chat des Kontakts steht eine Antwort
# (vom Betreiber-Handy oder als Echo eines Versands, inbox.py `_ausgehend`).
# Beide beenden das Warten, aus unterschiedlichen Gruenden — deshalb beide.
ANTWORT_TYPEN = ("versand", "nachricht_ausgehend")


@_gesichert
def posteingang(stunden: int = 48) -> str:
    """Support-Postfach: wer hat geschrieben und noch KEINE Antwort bekommen?

    Zeigt je Kontakt die juengste Kundennachricht im Zeitfenster, sofern
    danach nichts mehr rausging. Aelteste zuerst — wer am laengsten wartet,
    steht oben. `stunden` wird auf 1..168 gekappt (Vorgabe 48). Hoechstens 25
    Eintraege; `anzahl_unbeantwortet` nennt die Gesamtzahl.

    Nachrichten von Nummern, die nicht im CRM stehen, haengen alle am
    Sammelkontakt „Unbekannte Eingaenge" — dort zaehlt JEDE Absendernummer als
    eigener Eintrag und steht als `absender` daneben, denn dort identifiziert
    die Nummer den Menschen. Will der Betreiber so jemanden aufnehmen:
    `kontakt_anlegen` mit genau dieser Nummer, dann routen kuenftige
    Nachrichten von selbst.

    Nur Lesezugriff: versendet nichts, beantwortet nichts, aendert nichts."""
    try:
        fenster = int(stunden)
    except (TypeError, ValueError):
        fenster = 48
    fenster = max(POSTEINGANG_STUNDEN_MIN, min(POSTEINGANG_STUNDEN_MAX, fenster))

    # `distinct on (lead_id, gruppe)` liefert je Gruppe die juengste
    # Kundennachricht. `gruppe` ist NULL fuer einen echten Kontakt (dort ist
    # der Lead die Person) und traegt beim Sammelkontakt die Absendernummer —
    # sonst wuerde eine Antwort an EINEN Unbekannten alle Unbekannten als
    # beantwortet gelten lassen. Aus demselben Grund prueft die
    # not-exists-Wache dort zusaetzlich, dass die ausgehende Zeile DIESE
    # Nummer meint (`empfaenger` bei nachricht_ausgehend, `chat_id` bei
    # versand).
    zeilen = _q(
        "with fenster as ("
        "  select a.lead_id, a.created_at, a.payload,"
        "         case when %(sammel)s <> '' and a.lead_id::text = %(sammel)s"
        "              then a.payload->>'absender' end as gruppe"
        "    from activities a"
        "   where a.type = 'kundenantwort'"
        "     and a.created_at > now() - make_interval(hours => %(stunden)s)),"
        " juengste as ("
        "  select distinct on (lead_id, gruppe)"
        "         lead_id, gruppe, created_at, payload"
        "    from fenster order by lead_id, gruppe, created_at desc)"
        "select j.lead_id, j.gruppe, j.created_at, j.payload,"
        "       l.name as kontakt, count(*) over () as gesamt,"
        "       extract(epoch from (now() - j.created_at)) / 3600 as wartet_h"
        "  from juengste j left join leads l on l.id = j.lead_id"
        " where not exists ("
        "        select 1 from activities b"
        "         where b.lead_id = j.lead_id"
        "           and b.type = any(%(antworten)s)"
        "           and b.created_at > j.created_at"
        "           and (j.gruppe is null"
        "                or coalesce(b.payload->>'empfaenger',"
        "                            b.payload->>'chat_id') = j.gruppe))"
        " order by j.created_at asc limit %(limit)s",
        {"sammel": UNBEKANNT_LEAD_ID, "stunden": fenster,
         "antworten": list(ANTWORT_TYPEN), "limit": POSTEINGANG_LIMIT})

    eintraege = []
    for z in zeilen:
        nutzlast = z["payload"] or {}
        text = " ".join(str(nutzlast.get("text") or "").split())
        eintrag = {"lead_id": z["lead_id"], "kontakt": z["kontakt"],
                   "text_kurz": (text[:POSTEINGANG_TEXT_MAX] + "…"
                                 if len(text) > POSTEINGANG_TEXT_MAX else text),
                   "wartet_seit": z["created_at"],
                   "wartet_stunden": round(float(z["wartet_h"]), 1)}
        # `absender` steht NUR beim Sammelkontakt: bei einem echten Kontakt
        # sagt der Name mehr als die Nummer, und die Nummer stuende dann
        # doppelt in jeder Antwortzeile.
        if z["gruppe"]:
            eintrag["absender"] = z["gruppe"]
        eintraege.append(eintrag)

    antwort = {"fenster_stunden": fenster,
               "anzahl_unbeantwortet": zeilen[0]["gesamt"] if zeilen else 0,
               "angezeigt": len(eintraege), "eintraege": eintraege}
    if any("absender" in e for e in eintraege):
        antwort["hinweis"] = (
            "Eintraege mit 'absender' kommen von Nummern, die nicht im CRM "
            "stehen. Aufnehmen geht nur auf ausdruecklichen Wunsch des "
            "Betreibers: kontakt_anlegen mit genau dieser Nummer.")
    return _json(antwort)


@_gesichert
def digest() -> str:
    """Zusammenfassung: offene Entwuerfe, unvollstaendige Bedarfsanalysen,
    faellige Wiedervorlagen, unbeantwortete Eingaenge, letzte Aktivitaeten
    (48 h)."""
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
    # Der Support-Ueberblick im Morgen-Digest (Stufe 8). Dasselbe 48-h-Fenster
    # wie „letzte Aktivitaeten", aber eine andere Frage: dort steht, was
    # passiert IST, hier, was noch AUSSTEHT. Fuenf Eintraege, nicht 25 — der
    # Digest ist eine Ansage, keine Liste; die ganze Sicht zeigt `posteingang`.
    # `.get` mit Rueckfall wie im Wochenbericht (Befund B1): eine Teilquelle
    # darf den Digest nie als Ganzes umreissen.
    posten = json.loads(posteingang(stunden=48))
    unbeantwortet = {
        "anzahl": posten.get("anzahl_unbeantwortet"),
        "eintraege": [{"lead_id": e["lead_id"], "kontakt": e["kontakt"],
                       **({"absender": e["absender"]} if "absender" in e else {}),
                       "wartet_stunden": e["wartet_stunden"]}
                      for e in posten.get("eintraege", [])[:5]],
    }
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
                  "unbeantwortete_eingaenge": unbeantwortet,
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
                # jsonb_typeof statt `?`: prueft Existenz UND Typ in einem —
                # eine handgeschriebene recherche-Zeile mit nicht-numerischem
                # kosten_usd liesse sonst ::numeric werfen und den ganzen
                # Wochenbericht zur Fehlermeldung werden (Task-2-Bedenken,
                # gleiche Haertung wie die case-Wache in vertraege_ablaufend).
                f"and jsonb_typeof(payload->'kosten_usd') = 'number' "
                f"and created_at >= {seit}")
    # .get mit Rueckfall: eine Teilquelle darf den Bericht nie als Ganzes
    # umreissen (Review-Befund B1) — liefert vertraege_ablaufend wider
    # Erwarten einen Fehler, steht hier None, und die Textzeile sagt
    # "unbekannt" statt dass ein KeyError als Traceback entweicht.
    ablaufend = json.loads(vertraege_ablaufend(tage=30)).get("anzahl")
    wv_map = {z["type"]: z["n"] for z in wv}
    alle_neuen = {z["s"]: z["n"] for z in neue}
    # digest() schliesst recherche/system aus dem Bedarfsblock aus — mit
    # gemessener Begruendung (siehe dort). Der Wochenbericht ZAEHLT sie
    # bewusst mit (ein b2b_leads-Lauf IST Wochenleistung), aber die
    # Schlagzahl, die der Betreiber liest, sind die Kontakte mit
    # Gespraechspotenzial — sonst meldete eine Recherche-Woche "20 neue
    # Kontakte", ohne dass ein Mensch geschrieben haette (Review-Befund B7:
    # keine unkommentierte Umkehr der Digest-Entscheidung).
    im_gespraech = sum(n for s, n in alle_neuen.items()
                       if s not in ("recherche", "system"))
    daten = {
        "zeitraum": "letzte 7 Tage",
        "neue_leads": alle_neuen,
        "neue_leads_im_gespraech": im_gespraech,
        "bedarf": dict(bedarf[0]),
        "versand": {z["channel"]: z["n"] for z in versand},
        "wiedervorlagen": {"neu": wv_map.get("wiedervorlage", 0),
                           "erledigt": wv_map.get("wiedervorlage_erledigt", 0)},
        "entwuerfe_offen_jetzt": offen[0]["n"],
        "recherche_kosten_usd": round(float(kosten[0]["k"]), 2),
        "vertraege_ablaufend_30": ablaufend,
    }
    # `text` ist die eigentliche Lieferform: der Cron-Lauf soll NUR dieses
    # Feld weitergeben, damit der Betreiber einen Mehrzeiler bekommt und kein
    # JSON. Die Einzelfelder bleiben trotzdem stehen — wer nachrechnen will,
    # soll nicht den Fliesstext parsen muessen.
    zeilen = [f"Wochenbericht ({daten['zeitraum']}):",
              f"- Neue Kontakte im Gespraech: {im_gespraech} "
              f"(alle Quellen: {sum(alle_neuen.values())} — {alle_neuen})",
              f"- Bedarfsantworten: {daten['bedarf']['antworten']} "
              f"von {daten['bedarf']['kontakte']} Kontakten",
              f"- Versendet: {daten['versand'] or 'nichts'}",
              f"- Wiedervorlagen: {daten['wiedervorlagen']['neu']} neu, "
              f"{daten['wiedervorlagen']['erledigt']} erledigt",
              f"- Offene Entwuerfe jetzt: {daten['entwuerfe_offen_jetzt']}",
              f"- Recherche-Kosten: ${daten['recherche_kosten_usd']}",
              f"- Vertraege mit Ablauf in 30 Tagen: "
              f"{'unbekannt' if ablaufend is None else ablaufend}"]
    return _json({**daten, "text": "\n".join(zeilen)})


# ---------------------------------------------------------------------------
# Beraterin-Uebergabe (Stufe 7) — die Naht zwischen Assistent und Beratung.
#
# Das Werkzeug STELLT ZUSAMMEN, was der Kunde selbst gesagt hat, und BEWERTET
# nichts: keine Luecken-Analyse, keine Empfehlung, kein Produktvergleich.
# Genau diese Grenze ist §34d GewO (siehe AGENTS.md „Verbote") — die
# Zusammenstellung darf der Assistent, die Einschaetzung gehoert der
# lizenzierten Beraterin. Versendet wird dabei nichts: der Text geht als
# Markdown nach /reports und als Antwort in den Chat, weitergeben tut ihn der
# Betreiber. Damit entsteht KEIN neuer Egress-Pfad (Gate-Invariante).
# ---------------------------------------------------------------------------

def _bedarf_zeile(frage_id: str, eintrag) -> str:
    """Eine Bedarfsantwort als Uebergabe-Zeile.

    `bedarf_speichern` legt pro Frage ein Objekt {"antwort": ..., "at": ...}
    ab. In der Uebergabe steht die ANTWORT, nicht das Rohobjekt — die
    Beraterin liest den Text, kein JSON. Aeltere oder von Hand gesetzte
    Eintraege koennen ein blosser String sein; die werden unveraendert
    uebernommen, statt zu werfen.
    """
    # Die Beraterin liest den FRAGETEXT aus dem Leitfaden, nicht die interne
    # frage_id ("netto" sagt einem Menschen nichts) — Review-Befund B10.
    # Unbekannte ids (alte Leitfaden-Staende) fallen auf die id zurueck.
    beschriftung = ALLE_FRAGEN.get(frage_id, {}).get("frage", frage_id)
    if isinstance(eintrag, dict):
        return f"- {beschriftung}: {eintrag.get('antwort', eintrag)}"
    return f"- {beschriftung}: {eintrag}"


@_gesichert
def uebergabe_erstellen(lead_id: str) -> str:
    """Strukturierte Uebergabe eines Kontakts an die Beraterin: Profil,
    beantworteter Bedarf, Vertraege, offene Kundenfragen, letzte
    Aktivitaeten — als Markdown nach /reports und als Volltext zurueck.

    Die Uebergabe STELLT ZUSAMMEN und BEWERTET NICHTS: keine
    Lueckenanalyse, keine Empfehlung, kein Produktvergleich — Einschaetzung
    ist §34d-Gebiet und gehoert der lizenzierten Beraterin (dieser Satz
    steht hier und nicht nur im Modulkommentar, weil DIESER Text die
    Werkzeugbeschreibung ist, die das Modell sieht). Versendet wird NICHTS —
    weitergeben tut sie der Betreiber. Eine zweite Uebergabe am selben Tag
    ueberschreibt die Datei; `ueberschrieben: true` sagt es."""
    leads = _q("select name, phone, consent_status, enrichment, notes "
               "from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    l, e = leads[0], leads[0]["enrichment"] or {}
    # Fremddaten-Wachen (Review-Befund B5): enrichment kann von aelteren
    # Staenden oder von Hand befuellt sein — ein falsch geformter Knoten
    # (String statt Objekt, Array mit Nicht-Objekten) darf die Uebergabe
    # nicht als Traceback beenden. Dieselbe Fremddatenklasse, die
    # vertraege_ablaufend bereits abfaengt — hier symmetrisch.
    profil = e.get("profil") if isinstance(e.get("profil"), dict) else {}
    bedarf = e.get("bedarf") if isinstance(e.get("bedarf"), dict) else {}
    roh_vertraege = e.get("vertraege")
    vertraege = ([v for v in roh_vertraege if isinstance(v, dict)]
                 if isinstance(roh_vertraege, list) else [])
    offene = _q("select payload, created_at from activities "
                "where lead_id = %s and type = 'offener_punkt' "
                "order by created_at", (lead_id,))
    letzte = _q("select type, payload, created_at from activities "
                "where lead_id = %s order by created_at desc limit 10",
                (lead_id,))
    heute = datetime.now(timezone.utc).date().isoformat()
    zeilen = [f"# Uebergabe: {l['name']}", "",
              f"Stand {heute} · Consent: {l['consent_status']} · "
              f"Telefon: {l['phone'] or '—'}", "", "## Profil"]
    zeilen += [f"- {k}: {v}" for k, v in profil.items()] or ["- (leer)"]
    zeilen += ["", "## Bedarfsanalyse (Angaben des Kunden)"]
    zeilen += [_bedarf_zeile(k, v) for k, v in bedarf.items()] or ["- (leer)"]
    zeilen += ["", "## Vertraege (vom Kunden genannt)"]
    # Feldnamen wie von vertrag_speichern geschrieben (sparte/gesellschaft/
    # ablauf). `gesellschaft` und `ablauf` sind dort optional und fehlen dann
    # ganz — deshalb die Vorgaben statt eines KeyError.
    zeilen += [f"- {v.get('sparte','?')} ({v.get('gesellschaft','?')}), "
               f"Ablauf {v.get('ablauf','unbekannt')}"
               for v in vertraege] or ["- (keine genannt)"]
    # "Fragen des Kunden", nicht "Beratungsbedarf": unter offener_punkt wird
    # die FRAGE protokolliert, nie eine eigene Einschaetzung — die Ueberschrift
    # soll das auch dann sagen, wenn ein Modell sich nicht daran hielt
    # (Review-Befund B11; die AGENTS-Regel steht daneben).
    zeilen += ["", "## Fragen des Kunden an die Beraterin (offene Punkte)"]
    zeilen += [f"- {(p['payload'] or {}).get('inhalt', p['payload'])}"
               for p in offene] or ["- (keine)"]
    zeilen += ["", "## Letzte Aktivitaeten"]
    zeilen += [f"- {a['created_at']:%Y-%m-%d} {a['type']}" for a in letzte] \
        or ["- (keine)"]
    zeilen += ["", "---", "Erstellt vom Assistenten. KEINE Beratung, keine "
               "Produktbewertung — reine Zusammenstellung der Kundenangaben."]
    text = "\n".join(zeilen)
    # Der Kundenname geht in einen Dateinamen — also durch `slug` (Whitelist
    # [a-z0-9-]) und danach durch die Einbettungspruefung in
    # `report_schreiben`. Dasselbe zweistufige Muster wie bei marktanalyse.
    name = f"uebergabe-{recherche.slug(l['name'])}-{heute}.md"
    pfad, ueberschrieben, schreibfehler = None, False, None
    try:
        # `ueberschrieben` wird DURCHGEREICHT (Review-Befund B6): die
        # Uebergabe ist nicht identisch rekonstruierbar (Aktivitaeten auf 10
        # gedeckelt, Profil/Bedarf ueberschreiben in-place) — ein stiller
        # Overwrite widersprach der ausdruecklichen Zusage in recherche.py.
        pfad, ueberschrieben = recherche.report_schreiben(name, text)
    except (OSError, ValueError) as ex:
        # Wie bei marktanalyse: die Zusammenstellung ist fertig und gehoert in
        # den Chat, auch wenn der Reportordner fehlt. Sie geht nicht verloren,
        # nur weil ein Bind nicht anliegt.
        schreibfehler = (f"Uebergabe konnte nicht abgelegt werden "
                         f"({type(ex).__name__}: {ex}) — liegt der Bind "
                         f"./reports:/reports am Container an? Der Text unten "
                         f"ist vollstaendig.")
    _q("insert into activities (lead_id, type, payload) values "
       "(%s, 'uebergabe', %s) returning id",
       (lead_id, _json({"pfad": pfad, "offene_punkte": len(offene)})))
    return _json(_ohne_none({"pfad": pfad, "ueberschrieben": ueberschrieben,
                             "fehler": schreibfehler, "text": text,
                             "offene_punkte_anzahl": len(offene)}))


# Fehlgeschlagene Entwuerfe werden nie automatisch wiederholt und sammeln sich
# deshalb an. Die Liste bleibt gedeckelt, damit ein Aufruf die Antwort nicht
# unbegrenzt aufblaeht; `anzahl_fehlgeschlagen` nennt die tatsaechliche Zahl,
# damit nichts stillschweigend verschwindet.
FEHLGESCHLAGEN_MAX = 20
FEHLER_KURZ = 120


def _zielangabe(kanal: str, empfaenger: str) -> dict:
    """Wohin ginge dieser Entwurf wirklich? — dieselbe Antwort wie im Versand.

    Zugestellt wird ueber zwei Wege, und beide werden hier mit GENAU der
    Funktion beurteilt, die auch versendet: WhatsApp ueber eine Nummer
    (`nummern.normalisiere_empfaenger`, sales-dispatch) und E-Mail ueber
    eine Adresse (`mailadresse.pruefe`, sales-mail). Wer freigibt, muss das
    Ziel sehen — seit Stufe 9 geht eine E-Mail automatisch raus, sie ist
    also kein Merkposten mehr.

    LinkedIn behaelt `zielnummer: null` ohne Warnhinweis: einen
    LinkedIn-Entwurf als „nicht zustellbar" zu kennzeichnen waere schlicht
    falsch, er geht ueber den Handversand raus.
    """
    if kanal == "email":
        adresse, _fehler = mailadresse.pruefe(empfaenger)
        if adresse is None:
            return {"zielnummer": None, "zieladresse": None,
                    "hinweis": "nicht zustellbar"}
        return {"zielnummer": None, "zieladresse": adresse}
    if kanal != "whatsapp":
        return {"zielnummer": None}
    chat_id, _fehler = normalisiere_empfaenger(empfaenger)
    if chat_id is None:
        return {"zielnummer": None, "hinweis": "nicht zustellbar"}
    return {"zielnummer": chat_id}


def _whatsapp_freigabe_anzeige(zeile):
    """Kontakt-Freigabe fuer die Freigabe-Anzeige: True/False bei WhatsApp
    (dieselbe Funktion, mit der der Dispatcher entscheidet), None bei den
    anderen Kanaelen — E-Mail und LinkedIn kennen dieses Gate nicht, ein
    False dort waere eine falsche Warnung."""
    if zeile["channel"] != "whatsapp":
        return None
    return _whatsapp_freigegeben(zeile["enrichment"])


@_gesichert
def entwuerfe_offen() -> str:
    """Alle Entwuerfe, die auf den Betreiber warten. Zwei Bloecke:

    `entwuerfe` — offene Freigaben (status='pending') sowie freigegebene
    LinkedIn-Entwuerfe, die noch auf den Handversand warten.
    `fehlgeschlagen` — Entwuerfe, deren Zustellung gescheitert ist, je mit
    Fehlergrund; sie werden NIE von selbst wiederholt und brauchen eine
    ausdrueckliche erneute Freigabe.

    Je Eintrag steht die Zustelladresse des Kanals: `zielnummer` bei
    WhatsApp (die Nummer, an die tatsaechlich zugestellt wuerde),
    `zieladresse` bei E-Mail (dieselbe Pruefung, mit der sales-mail
    sendet) — beide null mit Hinweis, wenn unzustellbar.

    Je Eintrag steht neben dem roh erfassten `empfaenger` die `zielnummer`,
    an die tatsaechlich zugestellt wuerde (null + hinweis, wenn die Nummer
    nicht zustellbar ist), der `consent`-Stand des Kontakts und
    `medien_datei` — der Anhang, der mitginge (null, wenn keiner dranhaengt).
    Bei WhatsApp-Entwuerfen steht zusaetzlich `whatsapp_freigabe`: hat der
    Betreiber den Kontakt fuer WhatsApp freigegeben (kontakt_freigeben)?
    Steht dort false, wird der Dispatcher NICHT zustellen — auch nicht nach
    einer Nachrichten-Freigabe. draft_id ist immer die vollstaendige UUID —
    Werkzeuge brauchen sie so. Vor jeder Freigabe-Entscheidung aufrufen."""
    zeilen = _q(
        "select d.id, d.channel, d.recipient, d.status, d.body, d.media_ref, "
        "       l.name, l.consent_status, l.enrichment "
        "from drafts d left join leads l on l.id = d.lead_id "
        "where d.status = 'pending' "
        "   or (d.status = 'approved' and d.channel = 'linkedin') "
        "order by d.created_at desc")
    gescheitert = _q(
        "select d.id, d.channel, d.recipient, d.error, d.media_ref, "
        "       l.name, l.consent_status, l.enrichment "
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
             "whatsapp_freigabe": _whatsapp_freigabe_anzeige(z),
             **_zielangabe(z["channel"], z["recipient"])} for z in zeilen],
        "anzahl_fehlgeschlagen": anzahl[0]["n"],
        "fehlgeschlagen": [
            {"draft_id": z["id"], "kanal": z["channel"],
             "empfaenger": z["recipient"], "kontakt": z["name"],
             "consent": z["consent_status"], "medien_datei": z["media_ref"],
             "whatsapp_freigabe": _whatsapp_freigabe_anzeige(z),
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
    (approved -> sent). Versendet NICHTS selbst — nur fuer LinkedIn:
    WhatsApp und E-Mail versenden die Dispatcher-Dienste automatisch. Nur
    nach tatsaechlichem Handversand aufrufen."""
    zeilen = _q(
        "update drafts set status = 'sent', sent_at = now() "
        "where id = %s and status = 'approved' and channel = 'linkedin' "
        "returning id, lead_id, channel", (draft_id,))
    if not zeilen:
        vorhanden = _q("select status, channel from drafts where id = %s", (draft_id,))
        if not vorhanden:
            return _json({"fehler": f"Kein Entwurf mit draft_id {draft_id}."})
        if vorhanden[0]["channel"] != "linkedin":
            return _json({"fehler": ("nur fuer LinkedIn — WhatsApp und "
                                     "E-Mail versenden die "
                                     "Dispatcher-Dienste")})
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
    (failed -> approved). Nur fuer den Betreiber, und nur der Retry-Weg fuer
    die automatisch zugestellten Kanaele — WhatsApp (sales-dispatch) und
    E-Mail (sales-mail). Der zustaendige Dienst versucht den Entwurf danach
    in der naechsten Runde erneut.

    SCHUTZKANTE gegen Doppelversand: beginnt der aktuelle error-Text mit
    'in Zustellung' (die Claim-Marke der Dispatcher, gesetzt VOR dem
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
             kontakt_freigeben, kontakt_freigabe_entziehen,
             aktivitaet_loggen, wiedervorlage_setzen, wiedervorlage_erledigt,
             vertrag_speichern, vertraege_ablaufend, termin_bestaetigen,
             profil_lesen, profil_aktualisieren,
             bedarf_speichern, bedarf_offen, entwurf_erstellen,
             post_entwurf_erstellen, medien_liste,
             posteingang, digest, wochenbericht, uebergabe_erstellen,
             entwuerfe_offen, entwurf_freigeben, entwurf_ablehnen,
             entwurf_manuell_gesendet, entwurf_erneut_freigeben,
             marktanalyse, b2b_leads, firma_anreichern)

for _fn in WERKZEUGE:
    mcp.tool()(_fn)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
