"""Empfehlungslisten (C4, Spec docs/superpowers/specs/2026-10-17-
empfehlungslisten-design.md): Pole Position und Mitarbeitervorschlaege.

Kopf in der Tabelle empfehlungslisten, jede Zeile ist ein Kontakt mit
enrichment.empfehlung. Erst wird ALLES geprueft, dann geschrieben — ein
Fehler in Zeile 7 legt nichts an. Listen werden nie geloescht.
"""
import json
import uuid
from datetime import date

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
    sauber["firma"] = bool(z.get("firma"))
    return sauber, hinweise


def _anzeigename(z) -> str:
    return " ".join(t for t in (z["vorname"], z["name"]) if t)


def _empfehlung_setzen(lead_id: str, daten: dict) -> None:
    server._q("update leads set enrichment = jsonb_set(coalesce(enrichment, '{}'::jsonb), "
              "'{empfehlung}', %s::jsonb, true), updated_at = now() where id = %s returning id",
              (json.dumps(daten, ensure_ascii=False), lead_id))


def _quelle_einwilligung(kopf) -> str:
    return (f"Empfehlung: vorab gefragt von {kopf['empfohlen_von_name']} "
            f"(Liste {kopf['datum']:%d.%m.%Y})")


def _einwilligung(lead_id: str, an: bool, kopf) -> None:
    status = server._q("select consent_status from leads where id = %s", (lead_id,))[0]["consent_status"]
    if an and status not in ("opt_in", "existing_customer"):
        server.einwilligung_erfassen(lead_id, "opt_in", _quelle_einwilligung(kopf))
    elif not an and status == "opt_in":
        server.einwilligung_widerrufen(lead_id, "Empfehlung: Häkchen entfernt")


def _zeile_schreiben(kopf, z, bereiche, einwilligung, quelle, gesehen: set):
    """-> ('neu'|'verknuepft', lead_id) oder ('abgewiesen', grund)."""
    if z["chat_id"] and z["chat_id"] in gesehen:
        return "abgewiesen", "doppelt in der Liste"
    if z["chat_id"]:
        gesehen.add(z["chat_id"])
    bestehend = server._lead_mit_gleicher_nummer(z["chat_id"]) if z["chat_id"] else None
    if bestehend is not None:
        lid = str(bestehend["id"])
        e = server._q("select enrichment from leads where id = %s", (lid,))[0]["enrichment"] or {}
        if server._privat(e) or server._sammelkontakt(lid):
            return "abgewiesen", "privat markierter Kontakt — nicht verknüpft"
        art = None
        status = "verknuepft"
    else:
        r = json.loads(server.kontakt_anlegen(_anzeigename(z), phone=z["telefon"],
                                              source="empfehlung"))
        if "fehler" in r:
            return "abgewiesen", r["fehler"]
        lid, e, status = str(r["lead_id"]), {}, "neu"
        art = "firma" if z["firma"] else "person"
    if "empfehlung" not in e:
        _empfehlung_setzen(lid, {"liste_id": kopf["id"], "beruf": z["beruf"], "alter": z["alter"],
                                 "ort": z["ort"], "zeichnet_aus": z["zeichnet_aus"],
                                 "interessiert": z["interessiert"], "ergebnis": "offen",
                                 "notiz": "", "einwilligung": bool(einwilligung),
                                 "vorname": z["vorname"], "nachname": z["name"]})
    hinzu = ["bav"] if z["firma"] else list(bereiche)
    server._einordnen(lid, art if status == "neu" else None, hinzu, (), quelle=quelle)
    server._q("insert into activities (lead_id, type, payload) values (%s, 'empfehlung', %s) "
              "returning id", (lid, json.dumps({"liste_id": kopf["id"],
                                                "empfohlen_von_name": kopf["empfohlen_von_name"]},
                                               ensure_ascii=False)))
    if einwilligung:
        _einwilligung(lid, True, kopf)
    return status, lid


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
    zahl = {"neu": 0, "verknuepft": 0}
    abgewiesen, gesehen = [], set()
    for nr, z in enumerate(sauber, 1):
        status, wert = _zeile_schreiben(kopf, z, bereiche, einwilligung, quelle, gesehen)
        if status == "abgewiesen":
            abgewiesen.append({"zeile": nr, "grund": wert})
        else:
            zahl[status] += 1
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
    zeilen = []
    for m in sorted(_mitglieder(lid), key=lambda m: m["created_at"]):
        l = server._q("select name, phone, enrichment from leads where id = %s", (m["lead_id"],))
        if not l:
            continue
        e = (l[0]["enrichment"] or {}).get("empfehlung") or {}
        ergebnis, termin = wirksames_ergebnis(m["lead_id"], e.get("ergebnis") or "offen")
        zeilen.append({"lead_id": m["lead_id"], "name": l[0]["name"],
                       "vorname": e.get("vorname", ""), "nachname": e.get("nachname", ""),
                       "telefon": l[0]["phone"] or "", "beruf": e.get("beruf", ""),
                       "alter": e.get("alter"), "ort": e.get("ort", ""),
                       "zeichnet_aus": e.get("zeichnet_aus", ""),
                       "interessiert": e.get("interessiert", ""), "ergebnis": ergebnis,
                       "ergebnis_text": ERGEBNISSE.get(ergebnis, ergebnis),
                       "notiz": e.get("notiz", ""), "einwilligung": bool(e.get("einwilligung")),
                       "termin_datum": termin})
    return {"kopf": k[0], "zeilen": zeilen}


def listen() -> list:
    aus = []
    for k in server._q("select id::text as id, art, datum, empfohlen_von_name, "
                       "empfohlen_von_lead::text as empfohlen_von_lead from empfehlungslisten "
                       "order by datum desc, erstellt_am desc"):
        zs = liste(k["id"])["zeilen"]
        aus.append({**k, "anzahl": len(zs),
                    **{s: sum(1 for z in zs if z["ergebnis"] == s)
                       for s in ("offen", "termin", "abschluss")}})
    return aus


def zeile_setzen(lead_id, ergebnis=None, notiz=None, einwilligung=None, quelle="ui") -> dict:
    lid = _uuid(lead_id)
    l = server._q("select enrichment from leads where id = %s", (lid,)) if lid else []
    if not l or "empfehlung" not in (l[0]["enrichment"] or {}):
        return {"fehler": "Kein Kontakt aus einer Empfehlungsliste."}
    e = dict(l[0]["enrichment"]["empfehlung"])
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
    if einwilligung is not None and bool(einwilligung) != bool(e.get("einwilligung")):
        k = server._q("select empfohlen_von_name, datum from empfehlungslisten where id = %s",
                      (e["liste_id"],))
        if k:
            _einwilligung(lid, bool(einwilligung), k[0])
        e["einwilligung"] = bool(einwilligung)
    _empfehlung_setzen(lid, e)
    server._q("insert into activities (lead_id, type, payload, actor) values "
              "(%s, 'empfehlung_geaendert', %s, %s) returning id",
              (lid, json.dumps({k: e[k] for k in ("ergebnis", "notiz", "einwilligung")},
                               ensure_ascii=False), "human" if quelle == "ui" else "agent"))
    return {"lead_id": lid, "ergebnis": e["ergebnis"], "notiz": e["notiz"],
            "einwilligung": e["einwilligung"]}


def zeile_hinzufuegen(liste_id, zeile, quelle="ui") -> dict:
    l = liste(liste_id)
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
    status, wert = _zeile_schreiben(k, s, k["bereiche"] or [], k["einwilligung"], quelle, gesehen)
    if status == "abgewiesen":
        return {"fehler": wert}
    return {"lead_id": wert, "status": status, "hinweise": hinweise}
