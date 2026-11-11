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

import logging
from datetime import datetime, timedelta, timezone

import kalender_sichtbarkeit
import kalender_sicht
import post_struktur
import server
import teilnehmer
import termin_link
import vexa

LOG = logging.getLogger("termin_akte")

FENSTER_VOR = timedelta(days=1)
FENSTER_NACH = timedelta(days=30)
STATUS_OHNE_LINK = "kein_link"
GRUND_OHNE_LINK = "Kein Konferenz-Link im Termin"

# Spalten, die status_setzen ausser status/status_grund setzen darf.
FELDER = frozenset({
    "herkunft", "quelle_id", "termin_activity_id", "beginn", "ende", "zeitzone",
    "titel", "thema", "beschreibung", "link", "plattform", "passcode", "einwahl",
    "kein_bot", "will_zusammenfassung", "abgesagt_am", "vexa_meeting_id",
    "vexa_plattform", "vexa_native_id", "bot_geschickt_am", "briefing_md",
    "briefing_stand", "briefing_mit_ki", "briefing_am", "hinweis_gesendet_am",
})


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
        gesehen.add(uid)
        qid = str(z["quelle_id"])
        if qid not in nutzbar:
            continue
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


def _speichern(uid: str, k: dict) -> tuple[bool, bool]:
    """Akte anlegen oder nachziehen -> (neu, geaendert)."""
    link = _link(k["link_texte"])
    alt = server._q("select * from termin_akten where uid = %s", (uid,))
    alt = alt[0] if alt else None
    status = "geplant" if link["link"] else STATUS_OHNE_LINK
    grund = None if link["link"] else GRUND_OHNE_LINK
    geaendert = False
    stand_leeren = False
    if alt is not None:
        geaendert = (_utc(alt["beginn"]) != k["beginn"] or _utc(alt["ende"]) != k["ende"]
                     or alt["titel"] != k["titel"] or alt["link"] != link["link"]
                     or alt["abgesagt_am"] is not None)
        if alt["status"] in ("geplant", STATUS_OHNE_LINK):
            stand_leeren = geaendert
        else:
            status, grund = alt["status"], alt["status_grund"]
    server._q(
        "insert into termin_akten (uid, herkunft, quelle_id, termin_activity_id, "
        "beginn, ende, titel, thema, beschreibung, link, plattform, passcode, "
        "einwahl, status, status_grund) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "on conflict (uid) do update set herkunft = case when termin_akten.herkunft = 'sales-claw' "
        "                  then termin_akten.herkunft else excluded.herkunft end, "
        "quelle_id = excluded.quelle_id, "
        "termin_activity_id = coalesce(excluded.termin_activity_id, "
        "                              termin_akten.termin_activity_id), "
        "beginn = excluded.beginn, ende = excluded.ende, titel = excluded.titel, "
        "thema = excluded.thema, beschreibung = excluded.beschreibung, "
        "link = excluded.link, plattform = excluded.plattform, "
        "passcode = excluded.passcode, einwahl = excluded.einwahl, "
        "status = excluded.status, status_grund = excluded.status_grund, "
        "abgesagt_am = null, "
        "briefing_stand = case when %s then null "
        "                      else termin_akten.briefing_stand end, "
        "geaendert_am = case when %s then now() "
        "                    else termin_akten.geaendert_am end "
        "returning uid",
        (uid, k["herkunft"], k["quelle_id"], k["activity_id"], k["beginn"], k["ende"],
         k["titel"], k["thema"], k["beschreibung"], link["link"], link["plattform"],
         link["passcode"], link["einwahl"], status, grund, stand_leeren, geaendert))
    return alt is None, geaendert


def abgleichen(jetzt: datetime) -> dict:
    """Akten aus sales-claw- und Kalenderterminen anlegen, nachziehen, absagen."""
    kandidaten, gesehen, abgesagt, pausiert = _kandidaten()
    von, bis = jetzt - FENSTER_VOR, jetzt + FENSTER_NACH
    neu = geaendert = 0
    for uid, k in kandidaten.items():
        if not (von <= k["beginn"] <= bis):
            continue
        ist_neu, ist_geaendert = _speichern(uid, k)
        # Die Akte steht, bevor Teilnehmer verknuepft werden (FK auf termin_akten).
        teilnehmer.verknuepfen(uid, k["teilnehmer"], darf_anlegen=True)
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
        server._q("update termin_akten set abgesagt_am = now(), geaendert_am = now() "
                  "where uid = %s returning uid", (uid,))
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
    tn = [{"name": t["name"], "adresse": t["adresse"], "rolle": t["rolle"],
           "lead_id": str(t["lead_id"]) if t["lead_id"] else None, "grund": t["grund"]}
          for t in server._q(
              "select name, adresse, rolle, lead_id, grund from termin_teilnehmer "
              "where uid = %s and coalesce(grund, '') <> 'gesperrt' "
              "order by (rolle = 'organisator') desc, adresse", (uid,))
          # Eine Sperre NACH dem Verknuepfen zaehlt auch: live pruefen.
          if not teilnehmer.sperrgrund(t["adresse"])]
    mit = server._q("select id, segmente, auswertung_status, auswertung_md "
                    "from termin_mitschriften where uid = %s", (uid,))
    mitschrift = None
    vorschlaege: list[dict] = []
    if mit:
        m = mit[0]
        mitschrift = {"id": str(m["id"]), "segmente": m["segmente"],
                      "auswertung_status": m["auswertung_status"],
                      "auswertung_md": m["auswertung_md"]}
        gesperrt: dict[str, bool] = {}
        for v in server._q(
                "select id, art, lead_id, daten, status from termin_vorschlaege "
                "where mitschrift_id = %s order by erstellt_am", (m["id"],)):
            lid = str(v["lead_id"]) if v["lead_id"] else None
            if lid:
                if lid not in gesperrt:
                    gesperrt[lid] = bool(lead_gesperrt(lid))
                if gesperrt[lid]:
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
        "mitschrift": mitschrift, "vorschlaege": vorschlaege}


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


def hat_gesperrte(uid: str) -> bool:
    """Steht unter den Teilnehmern jemand, der JETZT gesperrt ist? Prueft jede
    gespeicherte Adresse live - eine Sperre nach dem Verknuepfen zaehlt auch."""
    for z in server._q("select adresse, grund from termin_teilnehmer where uid = %s", (uid,)):
        if z["grund"] == "gesperrt" or teilnehmer.sperrgrund(z["adresse"]):
            return True
    return False


def akten_eines_leads(lead_id) -> list[str]:
    return [z["uid"] for z in server._q(
        "select distinct t.uid, a.beginn from termin_teilnehmer t "
        "join termin_akten a on a.uid = t.uid "
        "where t.lead_id = %s::uuid order by a.beginn, t.uid", (str(lead_id),))]


def lead_gesperrt(lead_id) -> str:
    """Grund, wenn der Kontakt JETZT gesperrt ist (Sperrliste, Loeschantrag,
    Privat-Vermerk) - sonst ''. Nur zur Entscheidung, nie loggen."""
    z = server._q("select enrichment from leads where id = %s", (str(lead_id),))
    if not z:
        return ""
    if server._sperre_fuer_lead(str(lead_id)):
        return "gesperrt"
    enr = z[0]["enrichment"]
    if server._loeschantrag(enr):
        return "Loeschantrag"
    if server._privat(enr):
        return "privat"
    return ""


def aufnahme_beenden(uid: str, grund: str) -> None:
    """Bot stoppen und das Vexa-Meeting loeschen (falls eines laeuft), die lokale
    Mitschrift loeschen (Vorschlaege gehen per Kaskade mit), Status
    'ohne_aufnahme'. Scheitert Vexa, bleibt vexa_meeting_id stehen: der
    Taktgeber loescht nach."""
    z = server._q("select vexa_meeting_id, vexa_plattform, vexa_native_id "
                  "from termin_akten where uid = %s", (uid,))
    felder: dict = {}
    if z and z[0]["vexa_meeting_id"] is not None:
        a = z[0]
        try:
            if a["vexa_plattform"] and a["vexa_native_id"]:
                vexa.bot_stoppen(a["vexa_plattform"], a["vexa_native_id"])
            vexa.meeting_loeschen(int(a["vexa_meeting_id"]))
            felder["vexa_meeting_id"] = None
        except vexa.VexaFehler as e:
            LOG.warning("Vexa-Aufraeumen fehlgeschlagen (%s)", type(e).__name__)
    server._q("delete from termin_mitschriften where uid = %s returning id", (uid,))
    status_setzen(uid, "ohne_aufnahme", grund, **felder)
