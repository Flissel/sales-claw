"""Kalender-Sicht (Spec 2026-10-14): Kunden-, eigene, Handy-Termine und die
verbundenen Kalender eines Zeitraums an einer Stelle, dazu die Konfliktpruefung
ueber alle Arten.

Verbundene Kalender kommen aus dem Abgleich (`server.kalendertermine_lesen`)
und folgen der Sichtbarkeit Business/Privat je Betrachter (Spec 2026-11-08
§2.2). Ihre Adressen sind geheim und tauchen in keinem zurueckgegebenen Wert
auf."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import kalender
import kalender_sichtbarkeit
import post_struktur
import server
import termine_eigen

HINWEIS_HANDY = "Handy-Termine gerade nicht abrufbar"
HINWEIS_QUELLEN = "Verbundene Kalender gerade nicht abrufbar"
OHNE_KONTAKT = "(ohne Kontakt)"
STANDARD_DAUER = 60


def _zone():
    return kalender.ortszone() or timezone.utc


def kundenzeilen(limit: int = 200) -> tuple[list, dict]:
    """-> (nicht abgesagte `termin`-Aktivitaeten, neueste zuerst, mit Lead-Name;
    {uid: payload} der Absagen)."""
    zeilen = server._q(
        "select a.payload, a.created_at, l.id as lead_id, l.name "
        "from activities a left join leads l on l.id = a.lead_id "
        "where a.type = 'termin' order by a.created_at desc limit %s", (limit,))
    # Abgesagte fallen aus der Ansicht — sie stehen in ihrem eigenen Abschnitt.
    abgesagt = {str((z["payload"] or {}).get("uid") or ""): z["payload"] or {}
                for z in server._q(
                    "select payload from activities "
                    " where type = 'termin_abgesagt' order by created_at")}
    return ([z for z in zeilen
             if str((z["payload"] or {}).get("uid") or "") not in abgesagt
             or not (z["payload"] or {}).get("uid")], abgesagt)


def _beginn(payload: dict):
    try:
        return datetime.strptime(f"{payload.get('datum')} {payload.get('uhrzeit')}",
                                 "%Y-%m-%d %H:%M").replace(tzinfo=_zone())
    except (ValueError, TypeError):
        return None


def _dauer(payload: dict) -> int:
    d = payload.get("dauer_minuten")
    return d if isinstance(d, int) and not isinstance(d, bool) and d > 0 else STANDARD_DAUER


def kundentermine(von: datetime, bis: datetime) -> list[dict]:
    aus = []
    for z in kundenzeilen(limit=5000)[0]:
        p = z["payload"] or {}
        beginn = _beginn(p)
        if beginn is None:
            continue
        dauer = _dauer(p)
        if not (beginn < bis and beginn + timedelta(minutes=dauer) > von):
            continue
        uid = str(p.get("uid") or "")
        lead_id = str(z["lead_id"]) if z["lead_id"] else ""
        name = (z["name"] or "").strip()
        aus.append({
            "uid": uid, "lead_id": lead_id, "kontakt": name or OHNE_KONTAKT,
            "beginn": beginn, "dauer_minuten": dauer,
            "thema": str(p.get("thema") or ""), "ort": str(p.get("ort") or ""),
            "bearbeitbar": bool(uid and lead_id and name)})
    aus.sort(key=lambda t: t["beginn"])
    return aus


def _tage(von: datetime, bis: datetime) -> tuple[int, int]:
    jetzt = datetime.now(timezone.utc)
    return (max(0, math.ceil((jetzt - von).total_seconds() / 86400)),
            max(0, math.ceil((bis - jetzt).total_seconds() / 86400)))


def _lokal(t: datetime) -> datetime:
    return (t if t.tzinfo else t.replace(tzinfo=_zone())).astimezone(_zone())


def _sammeln(von: datetime, bis: datetime,
             betrachter: str) -> tuple[list[dict], list[str], bool]:
    """-> (rohe Ereignisse mit datetime, Hinweise, handy_luecke_oder_quellenluecke)."""
    roh, hinweise, luecke = [], [], False

    for k in kundentermine(von, bis):
        roh.append({"art": "kunde", "uid": k["uid"], "lead_id": k["lead_id"],
                    "kontakt": k["kontakt"], "titel": f"{k['thema']} – {k['kontakt']}",
                    "beginn": k["beginn"],
                    "ende": k["beginn"] + timedelta(minutes=k["dauer_minuten"]),
                    "ort": k["ort"], "bearbeitbar": k["bearbeitbar"]})

    for e in termine_eigen.im_zeitraum(von, bis):
        roh.append({"art": "eigen", "uid": e["uid"], "titel": e["titel"],
                    "beginn": e["beginn"],
                    "ende": e["beginn"] + timedelta(minutes=e["dauer_minuten"]),
                    "ort": e.get("ort") or "", "notiz": e.get("notiz") or "",
                    "geaendert_am": e["geaendert_am"], "bearbeitbar": True,
                    # NULL = noch nicht abgeglichen; "fehlgeschlagen: …" -> Oberflaeche
                    # zeigt "nicht im Handy-Kalender" auch nach dem Neuladen (Spec §1.1).
                    "kalender_stand": e.get("kalender_stand")})

    bekannt = {r["uid"] for r in roh if r["uid"]}
    zurueck, voraus = _tage(von, bis)

    # Der CalDAV-Kalender des Ladens bleibt beim Live-Abruf: er gehoert dem
    # Laden-Besitzer und ist Business, also fuer jeden voll sichtbar.
    handy, fehler = kalender.termine_lesen(zurueck, voraus)
    if fehler:
        hinweise.append(HINWEIS_HANDY)
        luecke = True
    for t in handy:
        if t.get("uid") and t["uid"] in bekannt:
            continue
        roh.append({"art": "handy", "uid": t.get("uid") or "", "titel": t["titel"],
                    "beginn": t["beginn"], "ende": t["ende"],
                    "ort": t.get("ort") or "", "bearbeitbar": False})

    try:
        termine, luecken = server.kalendertermine_lesen(von, bis, betrachter)
    except Exception:                      # noqa: BLE001 — fehlende Tabelle, DB-Ausfall
        termine, luecken = [], []
        hinweise.append(HINWEIS_QUELLEN)
        luecke = True
    for l in luecken:
        name, grund = kalender_sichtbarkeit.luecke_anzeige(l, betrachter)
        if l.get("fenster"):
            # M3: Frage ausserhalb des Abgleich-Fensters (30 zurueck/180 voraus).
            hinweise.append(f"{name} {grund}")
        else:
            hinweise.append(f"Kalender „{name}“: {grund}")
        luecke = True
    for t in termine:
        roh.append({"art": "kalender", "uid": t["uid"], "titel": t["titel"],
                    "beginn": t["beginn"], "ende": t["ende"], "ort": t["ort"],
                    "quelle_id": t["quelle_id"], "quelle": t["quelle"],
                    "besitzer": t["besitzer"], "bereich": t["bereich"],
                    "maskiert": t["maskiert"], "kalender": t["kalender"],
                    "ganztaegig": t["ganztaegig"], "frei": t["frei"],
                    "bearbeitbar": False})

    roh = [r for r in roh if _ueberlappt(r["beginn"], r["ende"], von, bis)]
    roh.sort(key=lambda r: r["beginn"])
    return roh, hinweise, luecke


def _ueberlappt(b1: datetime, e1: datetime, b2: datetime, e2: datetime) -> bool:
    """Halb-offen [b, e); ein punktueller Termin zaehlt, wenn sein Zeitpunkt im Fenster liegt."""
    if e1 <= b1:
        return b2 <= b1 < e2
    return b1 < e2 and e1 > b2


# Felder, die ein Termin aus einem verbundenen Kalender immer traegt.
KALENDER_FELDER = ("quelle_id", "quelle", "besitzer", "bereich", "maskiert",
                   "kalender", "ganztaegig", "frei")


def betrachter(name: str = "") -> str:
    """Wer den Kalender ansieht: die angemeldete Person, ohne Anmeldung der
    Laden-Besitzer (Spec 2026-11-08 §2.2)."""
    return str(name or "") or post_struktur.container_besitzer()


def ebenen(betrachter: str = "") -> list[dict]:
    """Die festen Ebenen des Ladens und jede aktive Quelle (ohne Adresse)."""
    laden = post_struktur.container_besitzer()
    feste = [{"id": art, "name": name, "besitzer": laden, "bereich": "business"}
             for art, name in (("kunde", "Kundentermine"), ("eigen", "Eigene Termine"),
                               ("handy", "Laden-Kalender"))]
    try:
        quellen = server.kalenderquellen_lesen(nur_aktive=True)
    except Exception:                      # noqa: BLE001 — die Luecke meldet _sammeln
        quellen = []
    return feste + [{"id": q["id"],
                     "name": (kalender_sichtbarkeit.privat_name(q["besitzer"])
                              if kalender_sichtbarkeit.maskiert(
                                  q["besitzer"], q["bereich"], betrachter)
                              else q["anzeigename"]),
                     "besitzer": q["besitzer"], "bereich": q["bereich"]}
                    for q in quellen]


def ereignisse(von: datetime, bis: datetime, betrachter: str) -> dict:
    roh, hinweise, _ = _sammeln(von, bis, betrachter)
    aus, zaehler = [], 0
    for r in roh:
        zaehler += 1
        if r["art"] == "kalender":
            # Je Quelle eindeutig: dieselbe UID kann in Kalendern verschiedener
            # Besitzer stehen (anwenden() fuehrt nur je Besitzer zusammen).
            kennung = f"kalender:{r['quelle_id']}:{r['uid'] or zaehler}"
        else:
            kennung = f"{r['art']}:{r['uid'] or zaehler}"
        e = {"id": kennung, "art": r["art"], "titel": r["titel"],
             "beginn": _lokal(r["beginn"]).isoformat(), "ende": _lokal(r["ende"]).isoformat(),
             "bearbeitbar": r["bearbeitbar"]}
        for feld in ("uid", "lead_id", "kontakt", "ort", "notiz", "quelle", "geaendert_am",
                     "kalender_stand"):
            if r.get(feld):
                e[feld] = r[feld]
        if r["art"] == "kalender":
            for feld in KALENDER_FELDER:
                e[feld] = r[feld]
        aus.append(e)
    return {"ereignisse": aus, "hinweise": hinweise, "ebenen": ebenen(betrachter)}


def konflikte(beginn: datetime, dauer_minuten: int, ausser_uid: str = "",
              betrachter: str = "") -> dict:
    """Ohne Betrachter gilt jeder Privat-Kalender als fremd (sichere Seite).
    „Frei" markierte Termine (Geburtstage, TRANSP:TRANSPARENT) sind kein
    Konflikt."""
    ende = beginn + timedelta(minutes=dauer_minuten)
    roh, _, luecke = _sammeln(beginn - timedelta(days=1), ende + timedelta(days=1),
                              betrachter)
    treffer = [
        {"art": r["art"], "titel": r["titel"],
         "beginn": _lokal(r["beginn"]).isoformat(), "ende": _lokal(r["ende"]).isoformat()}
        for r in roh
        if not (ausser_uid and r["uid"] == ausser_uid)
        and not r.get("frei")
        and _ueberlappt(r["beginn"], r["ende"], beginn, ende)]
    return {"konflikte": treffer, "unvollstaendig": luecke}
