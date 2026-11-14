"""Termin-Akte: je Kundentermin genau eine Zeile (Meeting-Mittelpunkt, Spec §3/§5).

Quellen sind die sales-claw-Termine (`activities`, Typ 'termin') und die
abgeglichenen Kalendertermine (`kalender_termine`) aus aktiven Quellen, deren
Details gespeichert werden duerfen. Die uid ist die Kalender-UID: dieselbe
Einladung in mehreren Kalendern und als sales-claw-Termin ergibt eine Akte.
Ist ein Termin in beiden Quellen, ist sales-claw massgebend fuer beginn, ende
und titel: sales-claw bucht den Termin und verschickt die Einladungs-Updates.

Zeiten sind intern aware UTC. Logs enthalten nur Zahlen - nie Adressen, Namen,
Titel, Links oder Passcodes. `lesen()` liefert den Passcode im Dict; das Dict
darf nirgends geloggt werden.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import kalender_sichtbarkeit
import kalender_sicht
import post_struktur
import server
import teilnehmer
import termin_link

LOG = logging.getLogger("termin_akte")

FENSTER_VOR = timedelta(days=1)
FENSTER_NACH = timedelta(days=30)
STATUS_OHNE_LINK = "kein_link"
GRUND_OHNE_LINK = "Kein Konferenz-Link im Termin"
ALLE_STATUS = ("geplant", STATUS_OHNE_LINK, "wartet_auf_einlass", "laeuft", "fertig",
               "fehlgeschlagen", "ohne_aufnahme")
# Vom System gesetzte Endgruende fuer ohne_aufnahme: nach einer Verschiebung
# gilt der Termin wieder als geplant (Final-Review I3). Ein "Nein" von Kunde
# oder Felix, kein_bot und Sperren bleiben.
SYSTEM_GRUENDE = frozenset({"Vexa nicht konfiguriert", "Termin vorbei ohne Bot"})

# Spalten, die status_setzen ausser status/status_grund setzen darf.
FELDER = frozenset({
    "herkunft", "quelle_id", "termin_activity_id", "beginn", "ende", "zeitzone",
    "titel", "thema", "beschreibung", "link", "plattform", "passcode", "einwahl",
    "kein_bot", "will_zusammenfassung", "abgesagt_am", "vexa_meeting_id",
    "vexa_plattform", "vexa_native_id", "bot_geschickt_am", "briefing_md",
    "briefing_stand", "briefing_mit_ki", "briefing_am", "hinweis_gesendet_am",
})


def _h(uid) -> str:
    return hashlib.sha256(str(uid).encode()).hexdigest()[:8]


def _utc(wert: datetime) -> datetime:
    return wert.astimezone(timezone.utc)


def _zusammenfuehren(liste: list[dict], neu: list[dict]) -> None:
    """Haengt Teilnehmer an `liste`, die dort (nach Adresse) noch fehlen."""
    vorhanden = {(t.get("adresse") or "").strip().lower() for t in liste}
    for t in neu or []:
        a = (t.get("adresse") or "").strip().lower()
        if a and a not in vorhanden:
            vorhanden.add(a)
            liste.append(t)


def _salesclaw() -> tuple[dict[str, dict], set[str], set[str]]:
    """-> (Kandidaten {uid: ...}, gesehene uids, abgesagte uids)."""
    zeilen, abgesagt = kalender_sicht.kundenzeilen(limit=5000)
    abgesagt_uids = {u for u in abgesagt if u}
    kandidaten: dict[str, dict] = {}
    gesehen: set[str] = set()
    for z in zeilen:
        p = z["payload"] or {}
        uid = str(p.get("uid") or "") or f"sc-{z['activity_id']}"
        gesehen.add(uid)
        if uid in kandidaten:
            continue
        beginn = kalender_sicht._beginn(p)
        if beginn is None:
            continue
        beginn = _utc(beginn)
        ende = beginn + timedelta(minutes=kalender_sicht._dauer(p))
        thema = str(p.get("thema") or "")
        gast = []
        if z.get("email"):
            gast.append({"adresse": z["email"], "name": z.get("name") or "",
                         "rolle": "gast", "art": "individual"})
        kandidaten[uid] = {
            "herkunft": "sales-claw", "quelle_id": None,
            "activity_id": z["activity_id"], "beginn": beginn, "ende": ende,
            "titel": thema or None, "thema": thema or None, "beschreibung": None,
            "link_texte": (str(p.get("ort") or ""),), "teilnehmer": gast}
    return kandidaten, gesehen, abgesagt_uids


def _kalender() -> tuple[dict[str, dict], set[str], set[str]]:
    """-> (Kandidaten, gesehene uids, ids pausierter Quellen)."""
    quellen = server.kalenderquellen_lesen(nur_aktive=False)
    besitzer = post_struktur.container_besitzer()
    aktiv = {q["id"]: q for q in quellen if q["aktiv"]}
    pausiert = {q["id"] for q in quellen if not q["aktiv"]}
    nutzbar = {i for i, q in aktiv.items()
               if kalender_sichtbarkeit.details_speichern(q["besitzer"], q["bereich"],
                                                          besitzer)}
    kandidaten: dict[str, dict] = {}
    gesehen: set[str] = set()
    if not aktiv:
        return kandidaten, gesehen, pausiert
    zeilen = server._q(
        "select quelle_id, uid, beginn, ende, titel, beschreibung, teilnehmer, "
        "konferenz, ort from kalender_termine "
        "where quelle_id = any(%s::uuid[]) and uid <> '' "
        # Ganztaegig, "frei" und ohne uid zaehlt nicht: wird ein Eintrag so
        # umgestellt, gilt er hier als verschwunden.
        "and not ganztaegig and not frei order by beginn, quelle_id",
        (list(aktiv),))
    for z in zeilen:
        uid = z["uid"]
        qid = str(z["quelle_id"])
        if qid not in nutzbar or aktiv[qid]["bereich"] == "privat":
            # Quelle privat oder ohne Details: ihre Termine gelten als
            # verschwunden - kuenftige Akten werden abgesagt (Final-Review).
            continue
        gesehen.add(uid)
        daten = z["teilnehmer"] if isinstance(z["teilnehmer"], dict) else {}
        liste = daten.get("liste") or []
        ok, _ = teilnehmer.ist_kundentermin(
            "kalender", aktiv[qid]["bereich"], liste, daten.get("anzahl") or 0)
        if not ok:
            continue
        k = kandidaten.get(uid)
        texte = (z["konferenz"] or "", z["ort"] or "", z["beschreibung"] or "")
        if k is None:
            kandidaten[uid] = {
                "herkunft": "kalender", "quelle_id": qid, "activity_id": None,
                "beginn": _utc(z["beginn"]), "ende": _utc(z["ende"]),
                "titel": z["titel"] or None, "thema": z["titel"] or None,
                "beschreibung": z["beschreibung"] or None,
                "link_texte": texte, "teilnehmer": list(liste)}
        else:
            _zusammenfuehren(k["teilnehmer"], liste)
            k["link_texte"] = k["link_texte"] + texte
    return kandidaten, gesehen, pausiert


def _kandidaten() -> tuple[dict[str, dict], set[str], set[str], set[str]]:
    """-> (Kandidaten, gesehene uids, abgesagte uids, ids pausierter Quellen).
    sales-claw gewinnt Herkunft, Zeit und Titel; Link und Teilnehmer ergaenzen sich."""
    sc, sc_gesehen, abgesagt = _salesclaw()
    kal, kal_gesehen, pausiert = _kalender()
    kandidaten = dict(kal)
    for uid, k in sc.items():
        if uid in kal:
            _zusammenfuehren(k["teilnehmer"], kal[uid]["teilnehmer"])
            k["link_texte"] = k["link_texte"] + kal[uid]["link_texte"]
            k["beschreibung"] = kal[uid]["beschreibung"]
            k["quelle_id"] = kal[uid]["quelle_id"]
        kandidaten[uid] = k
    gesehen = (sc_gesehen | kal_gesehen) - abgesagt
    for uid in abgesagt:
        kandidaten.pop(uid, None)
    return kandidaten, gesehen, abgesagt, pausiert


def _link(texte: tuple) -> dict:
    treffer = termin_link.erkennen(*texte) or {}
    return {"link": treffer.get("link") or None,
            "plattform": treffer.get("plattform") or None,
            "passcode": treffer.get("passcode") or None,
            "einwahl": treffer.get("einwahl") or None}


def _speichern(uid: str, k: dict, jetzt: datetime) -> tuple[bool, bool]:
    """Akte anlegen oder nachziehen -> (neu, geaendert).

    Den Status schreibt der Abgleich nur, solange die Akte geplant/kein_link
    ist (Final-Review I2) - sonst gehoert er Taktgeber und Oberflaeche. Wird
    der Termin ohne Mitschrift in die Zukunft verschoben (I3), gilt er wieder
    als offen: Hinweis neu, und ein vom System gesetztes Ende (fehlgeschlagen,
    ohne_aufnahme aus SYSTEM_GRUENDE) wird wieder geplant/kein_link. Vexa-Ids
    bleiben stehen - die raeumt `_nachloeschen` im Taktgeber ab."""
    link = _link(k["link_texte"])
    alt = server._q("select * from termin_akten where uid = %s", (uid,))
    alt = alt[0] if alt else None
    status = "geplant" if link["link"] else STATUS_OHNE_LINK
    grund = None if link["link"] else GRUND_OHNE_LINK
    geaendert = verschoben = zurueck = bot_zurueck = stand_leeren = False
    alt_status = None
    if alt is not None:
        alt_status = alt["status"]
        geaendert = (_utc(alt["beginn"]) != k["beginn"] or _utc(alt["ende"]) != k["ende"]
                     or alt["titel"] != k["titel"] or alt["link"] != link["link"]
                     or alt["abgesagt_am"] is not None)
        verschoben = (_utc(alt["beginn"]) != k["beginn"] and k["beginn"] > jetzt
                      and not server._q("select 1 from termin_mitschriften where uid = %s",
                                        (uid,)))
        zurueck = verschoben and (
            alt_status == "fehlgeschlagen"
            or (alt_status == "ohne_aufnahme" and alt["status_grund"] in SYSTEM_GRUENDE))
        bot_zurueck = verschoben and (zurueck or alt_status in ("geplant", STATUS_OHNE_LINK))
        stand_leeren = (geaendert and alt_status in ("geplant", STATUS_OHNE_LINK)) or zurueck
    offen = ("termin_akten.status in ('geplant', 'kein_link') "
             "or (%(zurueck)s and termin_akten.status = %(alt_status)s)")
    server._q(
        "insert into termin_akten (uid, herkunft, quelle_id, termin_activity_id, "
        "beginn, ende, titel, thema, beschreibung, link, plattform, passcode, "
        "einwahl, status, status_grund) "
        "values (%(uid)s, %(herkunft)s, %(quelle_id)s, %(activity_id)s, %(beginn)s, "
        "%(ende)s, %(titel)s, %(thema)s, %(beschreibung)s, %(link)s, %(plattform)s, "
        "%(passcode)s, %(einwahl)s, %(status)s, %(grund)s) "
        "on conflict (uid) do update set herkunft = case when termin_akten.herkunft = 'sales-claw' "
        "                  then termin_akten.herkunft else excluded.herkunft end, "
        "quelle_id = excluded.quelle_id, "
        "termin_activity_id = coalesce(excluded.termin_activity_id, "
        "                              termin_akten.termin_activity_id), "
        "beginn = excluded.beginn, ende = excluded.ende, titel = excluded.titel, "
        "thema = excluded.thema, beschreibung = excluded.beschreibung, "
        "link = excluded.link, plattform = excluded.plattform, "
        "passcode = excluded.passcode, einwahl = excluded.einwahl, "
        f"status = case when {offen} then excluded.status else termin_akten.status end, "
        f"status_grund = case when {offen} then excluded.status_grund "
        "                     else termin_akten.status_grund end, "
        "hinweis_gesendet_am = case when %(verschoben)s then null "
        "                           else termin_akten.hinweis_gesendet_am end, "
        "bot_geschickt_am = case when %(bot_zurueck)s and termin_akten.status = %(alt_status)s "
        "                        then null else termin_akten.bot_geschickt_am end, "
        "abgesagt_am = null, "
        "briefing_stand = case when %(stand_leeren)s then null "
        "                      else termin_akten.briefing_stand end, "
        "geaendert_am = case when %(geaendert)s then now() "
        "                    else termin_akten.geaendert_am end "
        "returning uid",
        {"uid": uid, "herkunft": k["herkunft"], "quelle_id": k["quelle_id"],
         "activity_id": k["activity_id"], "beginn": k["beginn"], "ende": k["ende"],
         "titel": k["titel"], "thema": k["thema"], "beschreibung": k["beschreibung"],
         "link": link["link"], "plattform": link["plattform"], "passcode": link["passcode"],
         "einwahl": link["einwahl"], "status": status, "grund": grund,
         "zurueck": zurueck, "alt_status": alt_status, "verschoben": verschoben,
         "bot_zurueck": bot_zurueck, "stand_leeren": stand_leeren, "geaendert": geaendert})
    return alt is None, geaendert


def abgleichen(jetzt: datetime) -> dict:
    """Akten aus sales-claw- und Kalenderterminen anlegen, nachziehen, absagen."""
    kandidaten, gesehen, abgesagt, pausiert = _kandidaten()
    von, bis = jetzt - FENSTER_VOR, jetzt + FENSTER_NACH
    neu = geaendert = 0
    for uid, k in kandidaten.items():
        if not (von <= k["beginn"] <= bis):
            continue
        try:
            ist_neu, ist_geaendert = _speichern(uid, k, jetzt)
            # Die Akte steht, bevor Teilnehmer verknuepft werden (FK auf termin_akten).
            teilnehmer.verknuepfen(uid, k["teilnehmer"], darf_anlegen=True)
        except Exception as e:  # noqa: BLE001 - eine kaputte Akte stoppt den Rest nicht
            LOG.warning("Termin-Akte uebersprungen (uid=%s): %s", _h(uid), type(e).__name__)
            continue
        neu += ist_neu
        geaendert += ist_geaendert and not ist_neu
    weg = 0
    # Keine Obergrenze (`bis`): ein Termin, der aus dem Fenster geschoben wurde,
    # steht weiter in den Quellen und gilt ueber `gesehen` nicht als abgesagt.
    for z in server._q("select uid, herkunft, quelle_id from termin_akten "
                       "where abgesagt_am is null and beginn > %s", (jetzt,)):
        uid = z["uid"]
        if uid in abgesagt:
            pass
        elif uid in gesehen:
            continue
        elif z["quelle_id"] is not None and str(z["quelle_id"]) in pausiert:
            continue   # pausierte Quelle: ihr Schweigen heisst nicht "abgesagt"
        try:
            server._q("update termin_akten set abgesagt_am = now(), geaendert_am = now() "
                      "where uid = %s returning uid", (uid,))
        except Exception as e:  # noqa: BLE001
            LOG.warning("Absage uebersprungen (uid=%s): %s", _h(uid), type(e).__name__)
            continue
        weg += 1
    LOG.info("Termin-Akten abgeglichen: neu=%d geaendert=%d abgesagt=%d", neu, geaendert, weg)
    return {"neu": neu, "geaendert": geaendert, "abgesagt": weg}


def lesen(uid: str) -> dict | None:
    """Die Akte als Dict; gesperrte Teilnehmer fehlen ganz. Enthaelt den
    Passcode - das Ergebnis nie loggen."""
    z = server._q("select * from termin_akten where uid = %s", (uid,))
    if not z:
        return None
    a = z[0]
    gesperrt: dict[str, bool] = {}

    def lead_weg(lid) -> bool:
        if not lid:
            return False
        lid = str(lid)
        if lid not in gesperrt:
            gesperrt[lid] = bool(lead_gesperrt(lid))
        return gesperrt[lid]

    tn = [{"name": t["name"], "adresse": t["adresse"], "rolle": t["rolle"],
           "lead_id": str(t["lead_id"]) if t["lead_id"] else None, "grund": t["grund"]}
          for t in server._q(
              "select name, adresse, rolle, lead_id, grund from termin_teilnehmer "
              "where uid = %s and coalesce(grund, '') <> 'gesperrt' "
              "order by (rolle = 'organisator') desc, adresse", (uid,))
          # Eine Sperre NACH dem Verknuepfen zaehlt auch: live pruefen.
          if not teilnehmer.sperrgrund(t["adresse"]) and not lead_weg(t["lead_id"])]
    mit = server._q("select id, segmente, auswertung_status, auswertung_md, auswertung_json "
                    "from termin_mitschriften where uid = %s", (uid,))
    mitschrift = None
    vorschlaege: list[dict] = []
    if mit:
        m = mit[0]
        mitschrift = {"id": str(m["id"]), "segmente": m["segmente"],
                      "auswertung_status": m["auswertung_status"],
                      "auswertung_md": m["auswertung_md"],
                      "auswertung_json": m["auswertung_json"]}
        for v in server._q(
                "select id, art, lead_id, daten, status from termin_vorschlaege "
                "where mitschrift_id = %s order by erstellt_am", (m["id"],)):
            lid = str(v["lead_id"]) if v["lead_id"] else None
            if lead_weg(lid):
                continue
            vorschlaege.append({"id": str(v["id"]), "art": v["art"], "lead_id": lid,
                                "daten": v["daten"], "status": v["status"]})
    briefing = None
    if a["briefing_md"] is not None:
        briefing = {"markdown": a["briefing_md"], "mit_ki": a["briefing_mit_ki"],
                    "am": a["briefing_am"]}
    return {
        "uid": a["uid"], "herkunft": a["herkunft"],
        "beginn": _utc(a["beginn"]), "ende": _utc(a["ende"]),
        "zeitzone": a["zeitzone"], "titel": a["titel"], "thema": a["thema"],
        "beschreibung": a["beschreibung"],
        "beitreten": {"link": a["link"], "plattform": a["plattform"],
                      "passcode": a["passcode"], "einwahl": a["einwahl"]},
        "teilnehmer": tn, "status": a["status"], "status_grund": a["status_grund"],
        "kein_bot": a["kein_bot"], "will_zusammenfassung": a["will_zusammenfassung"],
        "abgesagt": a["abgesagt_am"] is not None, "briefing": briefing,
        "mitschrift": mitschrift, "vorschlaege": vorschlaege,
        "bildschirm_auswerten": bool(a["bildschirm_auswerten"]),
        "bilder_uebersprungen": int(a.get("bilder_uebersprungen") or 0),
        # Nur gepruefte Bilder zaehlen (R11): ungepruefte sind nirgends sichtbar.
        "bilder_anzahl": int(server._q(
            "select count(*) as n from termin_bilder where uid = %s "
            "and beschreibung_status = 'fertig'", (uid,))[0]["n"])}


def status_setzen(uid: str, status: str, grund: str = "", **felder) -> None:
    unbekannt = set(felder) - FELDER
    if unbekannt:
        raise ValueError(f"Unbekannte Felder: {sorted(unbekannt)}")
    namen = sorted(felder)
    zuweisung = "".join(f", {n} = %s" for n in namen)
    server._q(
        "update termin_akten set status = %s, status_grund = %s, geaendert_am = now()"
        f"{zuweisung} where uid = %s returning uid",
        (status, grund or None, *[felder[n] for n in namen], uid))
    LOG.info("Termin-Akte Status gesetzt: %s", status)


def status_wechseln(uid: str, von: Iterable[str], nach: str, grund: str = "",
                    **felder) -> bool:
    """Bedingter Statuswechsel (Final-Review I2): schreibt nur, wenn die Akte
    noch in einem der Status `von` steht. -> True, wenn eine Zeile wechselte.
    So holt kein Taktgeber-Schritt eine Aufnahme nach einem "Nein" zurueck."""
    unbekannt = set(felder) - FELDER
    if unbekannt:
        raise ValueError(f"Unbekannte Felder: {sorted(unbekannt)}")
    namen = sorted(felder)
    zuweisung = "".join(f", {n} = %s" for n in namen)
    z = server._q(
        "update termin_akten set status = %s, status_grund = %s, geaendert_am = now()"
        f"{zuweisung} where uid = %s and status = any(%s) returning uid",
        (nach, grund or None, *[felder[n] for n in namen], uid, list(von)))
    if z:
        LOG.info("Termin-Akte Status gewechselt: %s", nach)
    return bool(z)


def felder_setzen(uid: str, **felder) -> None:
    """Nur Felder, kein Status (z. B. Vexa-Ids nach einem "Nein" sichern)."""
    unbekannt = set(felder) - FELDER
    if unbekannt or not felder:
        raise ValueError(f"Unbekannte oder keine Felder: {sorted(unbekannt)}")
    namen = sorted(felder)
    server._q(
        "update termin_akten set geaendert_am = now()"
        + "".join(f", {n} = %s" for n in namen) + " where uid = %s returning uid",
        (*[felder[n] for n in namen], uid))


def hat_gesperrte(uid: str) -> bool:
    """Steht unter den Teilnehmern jemand, der JETZT gesperrt ist? Prueft jede
    gespeicherte Adresse und jeden verknuepften Kontakt live - eine Sperre
    nach dem Verknuepfen zaehlt auch."""
    for z in server._q("select adresse, grund, lead_id from termin_teilnehmer "
                       "where uid = %s", (uid,)):
        if z["grund"] == "gesperrt" or teilnehmer.sperrgrund(z["adresse"]):
            return True
        if z["lead_id"] and teilnehmer.lead_sperrgrund(z["lead_id"]):
            return True
    return False


def akten_eines_leads(lead_id, mit_adresse: bool = False) -> list[str]:
    """uids der Akten eines Kontakts. `mit_adresse=True` (Loeschantrag,
    Auskunft - Final-Review I5) findet auch Akten, in denen die Zeile schon
    entknuepft ist (gesperrt): Abgleich ueber die E-Mail-Adresse des Leads."""
    lid = str(lead_id)
    bedingung = "t.lead_id = %s::uuid"
    werte: tuple = (lid,)
    if mit_adresse:
        bedingung += (" or (t.lead_id is null and lower(t.adresse) in ("
                      "select lower(email) from leads "
                      "where id = %s::uuid and coalesce(email, '') <> ''))")
        werte = (lid, lid)
    return [z["uid"] for z in server._q(
        "select distinct t.uid, a.beginn from termin_teilnehmer t "
        "join termin_akten a on a.uid = t.uid "
        f"where {bedingung} order by a.beginn, t.uid", werte)]


def lead_gesperrt(lead_id) -> str:
    """Grund, wenn der Kontakt JETZT gesperrt ist - sonst ''. Nur zur
    Entscheidung, nie loggen."""
    return teilnehmer.lead_sperrgrund(lead_id)


def aufnahme_beenden(uid: str, grund: str) -> None:
    """Erst Status 'ohne_aufnahme' (bedingt, I2), dann die lokale Mitschrift
    loeschen (Vorschlaege gehen per Kaskade mit, offener Entwurf wird
    abgelehnt). Vexa spricht hier niemand an (Final-Review C1): die Vexa-Ids
    bleiben stehen, der Taktgeber stoppt den Bot und loescht das Meeting
    (`termin_takt._nachloeschen`) - nur er hat VEXA_API_KEY."""
    status_wechseln(uid, ALLE_STATUS, "ohne_aufnahme", grund)
    mitschrift_entfernen(uid)


def mitschrift_entfernen(uid: str) -> None:
    """Einen noch offenen Zusammenfassungs-Entwurf ablehnen (er darf nicht
    verwaisen) und die lokale Mitschrift der Akte loeschen (Vorschlaege gehen
    per Kaskade mit)."""
    for m in server._q("select entwurf_id from termin_mitschriften where uid = %s", (uid,)):
        if m["entwurf_id"] and server._q(
                "select 1 from drafts where id = %s and status = 'pending'",
                (str(m["entwurf_id"]),)):
            server.entwurf_ablehnen(str(m["entwurf_id"]))
    server._q("delete from termin_mitschriften where uid = %s returning id", (uid,))
    bilder_entfernen(uid)  # Bilder entstehen live, auch ohne Mitschrift


def bilder_entfernen(uid: str) -> int:
    """Alle Standbilder der Akte loeschen; gibt die Anzahl zurueck."""
    return len(server._q("delete from termin_bilder where uid = %s returning id", (uid,)))


_PASSCODE_PARAMETER = ("pwd", "passcode", "pw", "password", "pass")
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
GEHEIM = "•••"


def _url_bereinigen(treffer) -> str:
    """Passcode-Parameter aus einer URL nehmen (Zoom ?pwd= ist oft ein Hash)."""
    url = treffer.group(0)
    t = urlsplit(url)
    if not t.query:
        return url
    rest = [(k, v) for k, v in parse_qsl(t.query, keep_blank_values=True)
            if k.lower() not in _PASSCODE_PARAMETER]
    return urlunsplit(t._replace(query=urlencode(rest)))


def _ohne_passcode(wert, passcode: str):
    if isinstance(wert, str):
        wert = _URL.sub(_url_bereinigen, wert)
        return wert.replace(passcode, GEHEIM) if passcode else wert
    if isinstance(wert, dict):
        return {k: _ohne_passcode(v, passcode) for k, v in wert.items()}
    if isinstance(wert, list):
        return [_ohne_passcode(v, passcode) for v in wert]
    return wert


def fuer_agenten(akte: dict) -> dict:
    """Die Akte fuer den MCP-Agenten (laeuft ueber ein Cloud-Modell): kein
    Gesprochenes und kein Kundentext aus Mitschrift, Auswertung, Briefing und
    Vorschlaegen - nur Status und Eckdaten. Dazu kein Passcode: weder Feld noch
    Link-Parameter (in jeder URL jedes Textes) noch der Passcode im Klartext."""
    passcode = (akte["beitreten"].get("passcode") or "").strip()
    m, b = akte["mitschrift"], akte["briefing"]
    akte = {
        **akte,
        "beitreten": {**akte["beitreten"]},
        "mitschrift": ({"vorhanden": True, "auswertung_status": m["auswertung_status"]}
                       if m else None),
        "briefing": {"am": b["am"], "mit_ki": b["mit_ki"]} if b else None,
        "vorschlaege": [{"id": v["id"], "art": v["art"], "status": v["status"],
                         "lead_id": v["lead_id"]} for v in akte["vorschlaege"]]}
    akte["beitreten"].pop("passcode", None)
    return _ohne_passcode(akte, passcode)
