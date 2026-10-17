"""Empfehlungslisten (C4, Spec docs/superpowers/specs/2026-10-17-
empfehlungslisten-design.md): Pole Position und Mitarbeitervorschlaege.

Kopf in der Tabelle empfehlungslisten, jede Zeile ist ein Kontakt mit
enrichment.empfehlung. Listen werden nie geloescht.

ABWEICHUNG von Spec §4.1 ("Liste und Zeilen in einer Transaktion", Ruling I1):
die server-Helfer (kontakt_anlegen, _einordnen, einwilligung_*) committen je
Aufruf auf eigener Verbindung — eine echte Transaktion gibt es hier nicht.
Gesichert ist: ALLE Zeilen werden vor dem ersten Schreiben geprueft, ein
Pruef-Fehler (etwa in Zeile 7) legt nichts an. Ein Datenbankfehler WAEHREND
des Schreibens weist nur die betroffene Zeile ab (Grund DB_GRUND); die Liste
bleibt stehen und laesst sich per zeile_hinzufuegen heilen.

Gehoert ein verknuepfter Kontakt schon zu einer ANDEREN Liste (seine
enrichment.empfehlung nennt sie), steht er hier nur als "schon bekannt"
(fremd=True): nur lesend, ohne Einwilligungsbuchung, nicht in den Zaehlern
offen/termin/abschluss.
"""
import io
import json
import uuid
from datetime import date

import psycopg

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import formular
import server
from nummern import normalisiere_empfaenger

VORDRUCKE = {
    "pole_position": {"titel": "Pole Position",
                      "untertitel": "Konzept für den Aufbau von Empfehlungen", "max": 15},
    "mitarbeitervorschlaege": {"titel": "Mitarbeitervorschläge", "untertitel": "", "max": 25},
}
ERGEBNISSE = {"offen": "offen", "nicht_erreicht": "nicht erreicht",
              "termin": "Termin vereinbart", "kein_interesse": "kein Interesse",
              "abschluss": "Abschluss"}
TEXT_MAX = 200
NAME_MAX = 120
ZEILEN_HART_MAX = 50
DB_GRUND = "Datenbankfehler – Zeile bitte erneut hinzufügen"
FREMDE_QUELLE = "Einwilligung stammt aus anderer Quelle – nicht widerrufen"
_TEXTFELDER = ("vorname", "name", "beruf", "ort", "zeichnet_aus", "interessiert")


def _uuid(wert):
    try:
        return str(uuid.UUID(str(wert)))
    except (ValueError, TypeError):
        return None


def _zeile_pruefen(nr: int, z, art: str):
    """-> (saubere Zeile, hinweise) oder raise ValueError('Zeile n: ...')."""
    if not isinstance(z, dict):
        raise ValueError(f"Zeile {nr}: keine Zeile.")
    sauber = {}
    for f in _TEXTFELDER:
        w = z.get(f) or ""
        if not isinstance(w, str):
            raise ValueError(f"Zeile {nr}: {f} ist kein Text.")
        if len(w.strip()) > TEXT_MAX:
            raise ValueError(f"Zeile {nr}: {f} ist laenger als {TEXT_MAX} Zeichen.")
        sauber[f] = " ".join(w.split())
    if not (sauber["vorname"] or sauber["name"]):
        raise ValueError(f"Zeile {nr}: Name fehlt.")
    alter = z.get("alter")
    if alter in ("", None):
        sauber["alter"] = None
    else:
        try:
            alter = int(alter)
        except (ValueError, TypeError):
            raise ValueError(f"Zeile {nr}: Alter '{z.get('alter')}' ist keine Zahl.") from None
        if not 16 <= alter <= 99:
            raise ValueError(f"Zeile {nr}: Alter {alter} liegt nicht zwischen 16 und 99.")
        sauber["alter"] = alter
    hinweise = []
    if art == "mitarbeitervorschlaege" and sauber["alter"] is not None and sauber["alter"] < 22:
        hinweise.append(f"Zeile {nr}: Alter {sauber['alter']} — Vordruck verlangt ab 22.")
    tel = str(z.get("telefon") or "").strip()
    sauber["chat_id"] = None
    sauber["telefon"] = ""
    if tel:
        chat_id, fehler = normalisiere_empfaenger(tel)
        if chat_id is None:
            hinweise.append(f"Zeile {nr}: Telefon '{tel}' nicht lesbar — ohne Telefon angelegt, bitte prüfen.")
        else:
            sauber["chat_id"], sauber["telefon"] = chat_id, tel
    f = z.get("firma")
    # Nur ein echtes Ja zaehlt — bool("false") waere sonst True.
    sauber["firma"] = f is True or f == 1 or (
        isinstance(f, str) and f.strip().lower() in ("1", "true", "ja"))
    if sauber["firma"] and art != "pole_position":
        raise ValueError(f"Zeile {nr}: Firmenzeilen gibt es nur auf der Pole Position.")
    return sauber, hinweise


class _DbFehler(Exception):
    """Ein @_gesichert-Helfer meldete einen Datenbankfehler als {"fehler"}."""


def _ist_db_fehler(text) -> bool:
    return text == server.DB_FEHLER or str(text).startswith("Datenbankfehler")


def _anzeigename(z) -> str:
    return " ".join(t for t in (z["vorname"], z["name"]) if t)


def _empfehlung_setzen(lead_id: str, daten: dict) -> None:
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "'{empfehlung}', %s::jsonb, true), updated_at = now() where id = %s returning id",
              (json.dumps(daten, ensure_ascii=False), lead_id))


def _quelle_einwilligung(kopf) -> str:
    # Die Listen-ID am Ende macht pruefbar, dass eine Einwilligung aus GENAU
    # dieser Liste stammt (Ruling I2) — nur dann darf das Abhaken widerrufen.
    return (f"Empfehlung: vorab gefragt von {kopf['empfohlen_von_name']} "
            f"(Liste {kopf['datum']:%d.%m.%Y}) [Liste {kopf['id']}]")


def _aus_dieser_liste(lead_id: str, liste_id: str) -> bool:
    """Stammt die JUENGSTE Einwilligungsbuchung aus dieser Empfehlungsliste?"""
    z = server._q("select payload->>'quelle' as quelle from activities where lead_id = %s "
                  "and type = 'werbe_einwilligung' order by created_at desc limit 1",
                  (lead_id,))
    q = (z[0]["quelle"] or "") if z else ""
    # Exakt am Ende: der freie Name des Empfehlungsgebers steht davor und
    # koennte sonst ein fremdes Tag einschmuggeln.
    return q.startswith("Empfehlung:") and q.endswith(f"[Liste {liste_id}]")


def _widerruf_grund(liste_id: str) -> str:
    """Grund beim Abhaken — exakt und listenbezogen; nur GENAU dieser Text
    zaehlt nicht als eigene Ablehnung des Kontakts (Ruling N1)."""
    return f"Empfehlung: Häkchen entfernt [Liste {liste_id}]"


def _sperrgrund(lead_id: str, enrichment) -> str | None:
    """Loeschantrag oder Verbotsliste — dann weder verknuepfen noch einwilligen."""
    if server._loeschantrag(enrichment or {}):
        return "Löschantrag liegt vor — nicht verknüpft"
    g = server._sperre_fuer_lead(lead_id)
    if g:
        return f"steht auf der Verbotsliste ({g}) — nicht verknüpft"
    return None


def _einwilligung(lead_id: str, an: bool, kopf):
    """-> (Zeilen-Flag, Hinweis | None, Fehler | None). Bucht nur, wenn noetig
    und erlaubt; widerruft nur eine Einwilligung aus DIESER Liste (Ruling I2)."""
    l = server._q("select consent_status, enrichment from leads where id = %s", (lead_id,))[0]
    status = l["consent_status"]
    if an:
        if status in ("opt_in", "existing_customer"):
            return True, None, None
        grund = _sperrgrund(lead_id, l["enrichment"])
        if grund:
            return False, f"Einwilligung nicht gebucht: {grund}.", None
        if server._eigene_ablehnung(lead_id, _widerruf_grund(kopf["id"])):
            return False, ("Kontakt hat früher selbst widerrufen oder abgelehnt — Einwilligung "
                           "aus der Empfehlung nicht gebucht."), None
        r = json.loads(server.einwilligung_erfassen(lead_id, "opt_in", _quelle_einwilligung(kopf)))
        if "fehler" in r:
            return False, None, f"Einwilligung nicht gebucht: {r['fehler']}"
        return True, None, None
    if status != "opt_in":
        return False, None, None
    if not _aus_dieser_liste(lead_id, kopf["id"]):
        return False, FREMDE_QUELLE, None
    r = json.loads(server.einwilligung_widerrufen(lead_id, _widerruf_grund(kopf["id"])))
    if "fehler" in r:
        return True, None, f"Einwilligung nicht widerrufen: {r['fehler']}"
    return False, None, None


def _zeile_schreiben(kopf, z, bereiche, einwilligung, quelle, gesehen: set):
    """-> ('neu'|'verknuepft', lead_id, hinweise) oder ('abgewiesen', grund, [])."""
    if z["chat_id"] and z["chat_id"] in gesehen:
        return "abgewiesen", "doppelt in der Liste", []
    if z["chat_id"]:
        gesehen.add(z["chat_id"])
    try:
        return _zeile_schreiben_db(kopf, z, bereiche, einwilligung, quelle)
    except (psycopg.Error, _DbFehler):
        return "abgewiesen", DB_GRUND, []


def _zeile_schreiben_db(kopf, z, bereiche, einwilligung, quelle):
    hinweise = []
    bestehend = server._lead_mit_gleicher_nummer(z["chat_id"]) if z["chat_id"] else None
    if bestehend is not None:
        lid = str(bestehend["id"])
        e = server._q("select enrichment from leads where id = %s", (lid,))[0]["enrichment"] or {}
        if server._sammelkontakt(lid):
            return "abgewiesen", "Sammelkontakt — nicht verknüpft", []
        if server._privat(e):
            return "abgewiesen", "privat markierter Kontakt — nicht verknüpft", []
        grund = _sperrgrund(lid, e)
        if grund:
            return "abgewiesen", grund, []
        art, status = None, "verknuepft"
    else:
        r = json.loads(server.kontakt_anlegen(_anzeigename(z), phone=z["telefon"],
                                              source="empfehlung"))
        if "fehler" in r:
            if _ist_db_fehler(r["fehler"]):
                raise _DbFehler(r["fehler"])
            return "abgewiesen", r["fehler"], []
        lid, e, status = str(r["lead_id"]), {}, "neu"
        art = "firma" if z["firma"] else "person"
    eigen = "empfehlung" not in e
    flag = False
    if not eigen:
        hinweise.append("schon bekannt aus einer anderen Empfehlungsliste — dort pflegen.")
    elif einwilligung:
        flag, hinweis, fehler = _einwilligung(lid, True, kopf)
        hinweise += [t for t in (hinweis, fehler) if t]
    if eigen:
        _empfehlung_setzen(lid, {"liste_id": kopf["id"], "beruf": z["beruf"], "alter": z["alter"],
                                 "ort": z["ort"], "zeichnet_aus": z["zeichnet_aus"],
                                 "interessiert": z["interessiert"], "ergebnis": "offen",
                                 "notiz": "", "einwilligung": flag,
                                 "vorname": z["vorname"], "nachname": z["name"]})
    hinzu = ["bav"] if z["firma"] else list(bereiche)
    server._einordnen(lid, art if status == "neu" else None, hinzu, (), quelle=quelle)
    server._q("insert into activities (lead_id, type, payload) values (%s, 'empfehlung', %s) "
              "returning id", (lid, json.dumps({"liste_id": kopf["id"],
                                                "empfohlen_von_name": kopf["empfohlen_von_name"]},
                                               ensure_ascii=False)))
    return status, lid, hinweise


def liste_anlegen(art, empfohlen_von_name, datum, zeilen, empfohlen_von_lead=None,
                  berater_name=None, struktur=None, bereiche=(), einwilligung=False,
                  quelle="agent") -> dict:
    if art not in VORDRUCKE:
        return {"fehler": f"Unbekannter Vordruck '{art}' — erlaubt: {', '.join(VORDRUCKE)}."}
    name = " ".join(str(empfohlen_von_name or "").split())
    if not 1 <= len(name) <= NAME_MAX:
        return {"fehler": f"Empfehlungsgeber fehlt oder ist laenger als {NAME_MAX} Zeichen."}
    try:
        tag = date.fromisoformat(str(datum))
    except ValueError:
        return {"fehler": f"Datum '{datum}' ist kein ISO-Datum (JJJJ-MM-TT)."}
    bereiche = list(bereiche or [])
    for b in bereiche:
        if b not in server.BEREICHE:
            return {"fehler": f"Unbekannter Bereich '{b}'."}
    if art == "mitarbeitervorschlaege":
        bereiche = ["mitarbeiter"]
    if not isinstance(zeilen, list) or not zeilen:
        return {"fehler": "Die Liste hat keine Zeilen."}
    if len(zeilen) > VORDRUCKE[art]["max"]:
        return {"fehler": f"Der Vordruck fasst hoechstens {VORDRUCKE[art]['max']} Zeilen."}
    sauber, hinweise = [], []
    try:
        for nr, z in enumerate(zeilen, 1):
            s, h = _zeile_pruefen(nr, z, art)
            sauber.append(s)
            hinweise += h
    except ValueError as e:
        return {"fehler": str(e)}
    try:
        lead = _uuid(empfohlen_von_lead) if empfohlen_von_lead else None
        if lead and not server._q("select 1 from leads where id = %s", (lead,)):
            lead = None
        if berater_name is None or struktur is None:
            letzte = server._q("select berater_name, struktur from empfehlungslisten "
                               "order by erstellt_am desc limit 1")
            if berater_name is None:
                berater_name = letzte[0]["berater_name"] if letzte else ""
            if struktur is None:
                struktur = letzte[0]["struktur"] if letzte else ""
        kopf = server._q(
            "insert into empfehlungslisten (art, empfohlen_von_lead, empfohlen_von_name, datum, "
            "berater_name, struktur, bereiche, einwilligung, einwilligung_am) values "
            "(%s, %s, %s, %s, %s, %s, %s::jsonb, %s, case when %s then now() end) "
            "returning id::text as id, empfohlen_von_name, datum",
            (art, lead, name, tag, str(berater_name)[:NAME_MAX], str(struktur)[:NAME_MAX],
             json.dumps(bereiche), bool(einwilligung), bool(einwilligung)))[0]
    except psycopg.Error:
        return {"fehler": "Datenbankfehler – Liste nicht angelegt, bitte erneut versuchen."}
    zahl = {"neu": 0, "verknuepft": 0}
    abgewiesen, gesehen = [], set()
    for nr, z in enumerate(sauber, 1):
        status, wert, h = _zeile_schreiben(kopf, z, bereiche, einwilligung, quelle, gesehen)
        if status == "abgewiesen":
            abgewiesen.append({"zeile": nr, "grund": wert})
        else:
            zahl[status] += 1
            hinweise += [f"Zeile {nr}: {t}" for t in h]
    return {"liste_id": kopf["id"], **zahl, "abgewiesen": abgewiesen, "hinweise": hinweise}


def _mitglieder(liste_id: str) -> list:
    return server._q(
        "select distinct on (a.lead_id) a.lead_id::text as lead_id, a.created_at "
        "from activities a where a.type = 'empfehlung' and a.payload->>'liste_id' = %s "
        "order by a.lead_id, a.created_at", (liste_id,))


def wirksames_ergebnis(lead_id: str, gespeichert: str):
    """(ergebnis, naechster Termin ISO|None): ein nicht abgesagter Kundentermin
    macht aus offen/nicht_erreicht 'termin' — gerechnet, nicht gespeichert."""
    termine = server._q("select payload->>'uid' as uid, payload->>'datum' as datum from activities "
                        "where lead_id = %s and type = 'termin' order by payload->>'datum'",
                        (lead_id,))
    gueltig = [t["datum"] for t in termine
               if t["datum"] and not server._termin_abgesagt(lead_id, t["uid"])]
    heute = date.today().isoformat()
    kommend = [d for d in gueltig if d >= heute]
    datum = kommend[0] if kommend else (gueltig[-1] if gueltig else None)
    if gueltig and gespeichert in ("offen", "nicht_erreicht"):
        return "termin", datum
    return gespeichert, datum


def liste(liste_id) -> dict | None:
    lid = _uuid(liste_id)
    if not lid:
        return None
    k = server._q("select id::text as id, art, empfohlen_von_lead::text as empfohlen_von_lead, "
                  "empfohlen_von_name, datum, berater_name, struktur, bereiche, einwilligung, "
                  "einwilligung_am from empfehlungslisten where id = %s", (lid,))
    if not k:
        return None
    zeilen, fremde_daten = [], {}
    for m in sorted(_mitglieder(lid), key=lambda m: m["created_at"]):
        l = server._q("select name, phone, consent_status, enrichment from leads where id = %s",
                      (m["lead_id"],))
        if not l:
            continue
        roh = l[0]["enrichment"] or {}
        # Zeile entfernen = Kontakt archivieren (Spec §5); Loeschantrag und
        # privat verschwinden ebenso — aus Liste, Zaehlern und PDF.
        if server._archiviert(roh) or server._loeschantrag(roh) or server._privat(roh):
            continue
        e = roh.get("empfehlung") or {}
        # Angezeigt wird die WIRKSAME Einwilligung: Flag der Zeile UND der
        # Kontakt willigt noch ein; sonst (Widerruf, Abmeldung) "widerrufen".
        flag = bool(e.get("einwilligung"))
        wirksam = flag and l[0]["consent_status"] in server.EINWILLIGUNG_ARTEN
        heimat = _uuid(e.get("liste_id"))
        fremd = heimat != lid
        if fremd and heimat and heimat not in fremde_daten:
            d = server._q("select datum from empfehlungslisten where id = %s", (heimat,))
            fremde_daten[heimat] = d[0]["datum"] if d else None
        ergebnis, termin = wirksames_ergebnis(m["lead_id"], e.get("ergebnis") or "offen")
        zeilen.append({"lead_id": m["lead_id"], "name": l[0]["name"],
                       "vorname": e.get("vorname", ""), "nachname": e.get("nachname", ""),
                       "telefon": l[0]["phone"] or "", "beruf": e.get("beruf", ""),
                       "alter": e.get("alter"), "ort": e.get("ort", ""),
                       "zeichnet_aus": e.get("zeichnet_aus", ""),
                       "interessiert": e.get("interessiert", ""), "ergebnis": ergebnis,
                       "ergebnis_text": ERGEBNISSE.get(ergebnis, ergebnis),
                       "notiz": e.get("notiz", ""), "einwilligung": wirksam,
                       "einwilligung_widerrufen": flag and not wirksam,
                       "termin_datum": termin, "fremd": fremd,
                       "fremd_liste_id": heimat if fremd else None,
                       "fremd_liste_datum": fremde_daten.get(heimat) if fremd else None})
    return {"kopf": k[0], "zeilen": zeilen}


def listen() -> list:
    """Uebersicht. `anzahl` zaehlt ALLE Zeilen der Liste (auch "schon bekannt",
    extra ausgewiesen als `schon_bekannt`), offen/termin/abschluss nur die
    eigenen — sonst zaehlte ein Abschluss in jeder Liste, die den Kontakt nennt."""
    aus = []
    for k in server._q("select id::text as id, art, datum, empfohlen_von_name, "
                       "empfohlen_von_lead::text as empfohlen_von_lead from empfehlungslisten "
                       "order by datum desc, erstellt_am desc"):
        zs = liste(k["id"])["zeilen"]
        eigene = [z for z in zs if not z["fremd"]]
        aus.append({**k, "anzahl": len(zs), "schon_bekannt": len(zs) - len(eigene),
                    **{s: sum(1 for z in eigene if z["ergebnis"] == s)
                       for s in ("offen", "termin", "abschluss")}})
    return aus


def zeile_setzen(lead_id, ergebnis=None, notiz=None, einwilligung=None, quelle="ui",
                 liste_id=None) -> dict:
    """Ergebnis/Notiz/Einwilligung einer Zeile aendern. Mit `liste_id` wird
    abgelehnt, wenn die Zeile in dieser Liste nur "schon bekannt" ist."""
    try:
        return _zeile_setzen(lead_id, ergebnis, notiz, einwilligung, quelle, liste_id)
    except psycopg.Error:
        return {"fehler": "Datenbankfehler – nichts geändert, bitte erneut versuchen."}


def _zeile_setzen(lead_id, ergebnis, notiz, einwilligung, quelle, liste_id) -> dict:
    lid = _uuid(lead_id)
    l = server._q("select enrichment from leads where id = %s", (lid,)) if lid else []
    if not l or "empfehlung" not in (l[0]["enrichment"] or {}):
        return {"fehler": "Kein Kontakt aus einer Empfehlungsliste."}
    e = dict(l[0]["enrichment"]["empfehlung"])
    if liste_id is not None and _uuid(liste_id) != e.get("liste_id"):
        return {"fehler": "Diese Zeile ist hier nur „schon bekannt“ — ändern in der Liste, "
                          "aus der die Empfehlung stammt."}
    if ergebnis is not None:
        if ergebnis not in ERGEBNISSE:
            return {"fehler": f"Unbekanntes Ergebnis '{ergebnis}'."}
        e["ergebnis"] = ergebnis
    if notiz is not None:
        if not isinstance(notiz, str):
            return {"fehler": "Notiz ist kein Text."}
        if len(notiz.strip()) > TEXT_MAX:
            return {"fehler": f"Notiz ist laenger als {TEXT_MAX} Zeichen."}
        e["notiz"] = notiz.strip()
    hinweise = []
    if einwilligung is not None and bool(einwilligung) != bool(e.get("einwilligung")):
        k = server._q("select id::text as id, empfohlen_von_name, datum from empfehlungslisten "
                      "where id = %s", (e["liste_id"],))
        if not k:
            return {"fehler": "Die Liste dieser Zeile gibt es nicht mehr."}
        flag, hinweis, fehler = _einwilligung(lid, bool(einwilligung), k[0])
        if fehler:
            return {"fehler": fehler}
        if hinweis:
            hinweise.append(hinweis)
        e["einwilligung"] = flag
    _empfehlung_setzen(lid, e)
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'empfehlung_geaendert', %s, %s) returning id",
              (lid, json.dumps({k: e[k] for k in ("ergebnis", "notiz", "einwilligung")},
                               ensure_ascii=False), "human" if quelle == "ui" else "agent"))
    return {"lead_id": lid, "ergebnis": e["ergebnis"], "notiz": e["notiz"],
            "einwilligung": e["einwilligung"], "hinweise": hinweise}


def zeile_hinzufuegen(liste_id, zeile, einwilligung=False, quelle="ui") -> dict:
    """Eine Zeile nachtragen. Die Einwilligung der Liste gilt hier NICHT:
    gebucht wird nur mit ausdruecklichem `einwilligung=True` (wurde GENAU
    dieser Mensch vorab gefragt?) — und auch dann nur nach allen Sperr- und
    Ablehnungspruefungen."""
    try:
        l = liste(liste_id)
    except psycopg.Error:
        return {"fehler": DB_GRUND}
    if l is None:
        return {"fehler": "Diese Liste gibt es nicht."}
    if len(l["zeilen"]) >= ZEILEN_HART_MAX:
        return {"fehler": f"Eine Liste fasst hoechstens {ZEILEN_HART_MAX} Zeilen."}
    k = l["kopf"]
    try:
        s, hinweise = _zeile_pruefen(len(l["zeilen"]) + 1, zeile, k["art"])
    except ValueError as e:
        return {"fehler": str(e)}
    gesehen = {normalisiere_empfaenger(z["telefon"])[0] for z in l["zeilen"] if z["telefon"]}
    status, wert, h = _zeile_schreiben(k, s, k["bereiche"] or [], einwilligung is True, quelle,
                                       gesehen)
    if status == "abgewiesen":
        return {"fehler": wert}
    return {"lead_id": wert, "status": status, "hinweise": hinweise + h}


# --- PDF im Aufbau des Papier-Vordrucks -------------------------------------

_SPALTEN = {
    # (Ueberschrift, Breite mm, Feld) — Reihenfolge wie der Papier-Vordruck
    "pole_position": [("Name", 34, "nachname"), ("Vorname", 30, "vorname"),
                      ("Beruf", 34, "beruf"), ("Alter", 13, "alter"), ("Ort", 30, "ort"),
                      ("Telefon", 36, "telefon"), ("Termin", 24, "termin_datum"),
                      ("Ergebnis", 50, "ergebnis_text")],
    "mitarbeitervorschlaege": [("Vorname, Name", 46, "name"), ("Alter (ab 22)", 20, "alter"),
                               ("Beruf", 32, "beruf"), ("Telefon", 34, "telefon"),
                               ("Was zeichnet aus", 52, "zeichnet_aus"),
                               ("Was interessiert", 52, "interessiert"),
                               ("Termin", 24, "termin_datum")],
}
_ZEILE_H = 9 * mm
_PT = 8


def _zelle(z, feld) -> str:
    if feld == "ergebnis_text" and z.get("fremd"):
        return "schon bekannt"   # das Ergebnis steht auf der anderen Liste
    w = z.get(feld)
    if feld == "nachname" and not w and not z.get("vorname"):
        w = z.get("name")        # nur verknuepfter Kontakt: Anzeigename in die Spalte Name
    if feld == "termin_datum" and w:
        w = str(w)
        return f"{w[8:10]}.{w[5:7]}.{w[0:4]}"
    return "" if w is None else str(w)


def _passende_zeilen(text: str, breite: float, max_zeilen: int):
    """(Zeilen, pt): erst Normalgroesse, dann stufenweise bis 6 pt; passt es dann
    immer noch nicht, wird die letzte erlaubte Zeile mit '...' gekuerzt."""
    pt = float(_PT)
    while True:
        zeilen = formular._zeilen(text, breite, pt)
        if len(zeilen) <= max_zeilen:
            return zeilen, pt
        if pt <= 6:
            break
        pt = max(6.0, pt - 0.5)
    rest = " ".join(zeilen[max_zeilen - 1:])
    while rest and stringWidth(rest + "...", formular.SCHRIFT, pt) > breite:
        rest = rest[:-1]
    return zeilen[:max_zeilen - 1] + [rest.rstrip() + "..."], pt


def pdf(liste_id) -> bytes | None:
    """PDF (A4 quer) im Aufbau des Papier-Vordrucks; Folgeseite ab Vordruck-Maximum."""
    l = liste(liste_id)
    if l is None:
        return None
    k, art = l["kopf"], l["kopf"]["art"]
    vd, spalten = VORDRUCKE[art], _SPALTEN[art]
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=landscape(A4))
    breite, hoehe = landscape(A4)
    links = (breite - sum(s[1] for s in spalten) * mm) / 2
    zeilen = list(l["zeilen"])
    seiten_zeilen = []
    while zeilen or not seiten_zeilen:
        seiten_zeilen.append(zeilen[:vd["max"]])
        zeilen = zeilen[vd["max"]:]
    for seite, teil in enumerate(seiten_zeilen):
        y = hoehe - 18 * mm
        c.setFont(formular.FETT, 18)
        c.drawCentredString(breite / 2, y, formular._druckbar(vd["titel"]))
        if vd["untertitel"]:
            y -= 7 * mm
            c.setFont(formular.SCHRIFT, 12)
            c.drawCentredString(breite / 2, y, formular._druckbar(vd["untertitel"]))
        y -= 9 * mm
        c.setFont(formular.SCHRIFT, 10)
        kopf = (f"Name: {k['berater_name']}    Struktur: {k['struktur']}    "
                f"Empfohlen von: {k['empfohlen_von_name']}    Datum: {k['datum']:%d.%m.%Y}")
        c.drawString(links, y, formular._druckbar(kopf))
        y -= 8 * mm
        # Zeilenhoehe so, dass auch 25 Zeilen plus Kopfzeile auf die Seite passen
        zh = min(_ZEILE_H, (y - 10 * mm) / (vd["max"] + 1))
        mehrzeilig = zh >= 8 * mm
        x = links + 8 * mm
        c.setFont(formular.FETT, _PT)
        for titel, b, _ in spalten:
            c.rect(x, y - zh, b * mm, zh)
            c.drawString(x + 1.5 * mm, y - zh / 2 - 1 * mm, formular._druckbar(titel))
            x += b * mm
        y -= zh
        c.setFont(formular.SCHRIFT, _PT)
        for nr in range(vd["max"]):
            z = teil[nr] if nr < len(teil) else {}
            c.drawRightString(links + 6 * mm, y - zh / 2 - 1 * mm, f"{seite * vd['max'] + nr + 1}.")
            x = links + 8 * mm
            for _, b, feld in spalten:
                c.rect(x, y - zh, b * mm, zh)
                text = formular._druckbar(_zelle(z, feld)) if z else ""
                if text:
                    zeilen_txt, pt = _passende_zeilen(text, b * mm - 3 * mm,
                                                      2 if mehrzeilig else 1)
                    c.setFont(formular.SCHRIFT, pt)
                    for i, t in enumerate(zeilen_txt):
                        c.drawString(x + 1.5 * mm,
                                     y - (4 * mm if mehrzeilig else zh / 2 + 1 * mm)
                                     - i * 3.4 * mm * pt / _PT, t)
                x += b * mm
            y -= zh
        c.showPage()
    c.save()
    return puffer.getvalue()
