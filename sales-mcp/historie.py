"""Kontakt-Historie und Doppel-Pruefung (C3, Spec 2026-10-17)."""
from datetime import date, datetime

import psycopg

import server

FRIST_TAGE = 90
THEMA_MAX = 80
_KANAL = {"whatsapp": "WhatsApp", "email": "Mail", "linkedin": "LinkedIn", "telegram": "Telegram",
          "bluesky": "Bluesky", "mastodon": "Mastodon", "telegram_kanal": "Telegram-Kanal",
          "discord": "Discord", "devto": "dev.to", "youtube": "YouTube"}


def thema_norm(text) -> str:
    return " ".join(str(text or "").lower().split())[:THEMA_MAX]


def _lesen(was: str, sql: str, params) -> list:
    """Lesepfad der Historie: ein DB-Fehler (z. B. drafts.thema fehlt, weil
    provision.sql noch nicht eingespielt ist) laesst nur diesen Teil der
    Historie entfallen und wird als Warnung geloggt (Final Review 17.10.2026)."""
    try:
        return server._q(sql, params)
    except psycopg.Error as e:
        server._LOG.warning("Kontakt-Historie ohne %s (SQLSTATE %s): %s", was,
                            getattr(e, "sqlstate", None), str(e).splitlines()[0][:200] if str(e) else "")
        return []


def doppelt_pruefen(lead_id, thema, tage=FRIST_TAGE) -> list:
    n = thema_norm(thema)
    if not n or n == "termin":
        return []
    # Kandidaten per SQL, Themenvergleich in Python: PG lower()/\s haengen an
    # lc_ctype (Umlaute, NBSP) und wichen still von thema_norm ab.
    kandidaten = _lesen(
        "Doppel-Pruefung (thema)",
        "select id, channel, thema, status, coalesce(sent_at, created_at) as datum "
        "from drafts where lead_id = %s and status in ('pending','approved','sent') "
        "and thema is not null "
        "and coalesce(sent_at, created_at) > now() - make_interval(days => %s) "
        "order by datum desc", (str(lead_id), tage))
    return [{"draft_id": str(z["id"]), "kanal": z["channel"], "thema": z["thema"],
             "status": z["status"], "datum": z["datum"]}
            for z in kandidaten if thema_norm(z["thema"]) == n]


def doppelt_hinweis(treffer: list) -> str:
    t = treffer[0]
    d = t["datum"]
    tag = d.strftime("%d.%m.") if isinstance(d, (date, datetime)) else str(d)[8:10] + "." + str(d)[5:7] + "."
    return (f"Schon am {tag} per {_KANAL.get(t['kanal'], t['kanal'])} zum Thema {t['thema']} "
            f"angeschrieben — trotzdem anlegen? Dann trotzdem=True.")


def _akten_eintraege(lid: str, tage: int) -> list:
    """Abgeleitete Eintraege aus Termin-Akten (Meeting-Mittelpunkt): Termin,
    Mitschrift, Painpoints. Nichts davon liegt in `activities`. Akten, in
    denen dieser Kontakt gesperrt ist (grund = 'gesperrt'), und gesperrte
    Kontakte selbst liefern nichts."""
    import teilnehmer  # lokal: teilnehmer importiert server wie dieses Modul
    try:
        if teilnehmer.lead_sperrgrund(lid):
            return []
    except psycopg.Error as e:
        # Fail-closed: ohne Sperr-Pruefung keine abgeleiteten Eintraege.
        server._LOG.warning("Kontakt-Historie ohne Termin-Akten (Sperr-Pruefung scheiterte: %s)",
                            type(e).__name__)
        return []
    # Je Akte hoechstens eine Zeile, auch wenn der Kontakt ueber zwei Adressen
    # als Teilnehmer steht.
    eigene = ("select uid from termin_teilnehmer where lead_id = %s "
              "and coalesce(grund, '') <> 'gesperrt'")
    aus = []
    for z in _lesen(
            "Termin-Akten",
            "select a.titel, a.beginn, a.abgesagt_am from termin_akten a "
            f"where a.uid in ({eigene}) "
            "and a.beginn > now() - make_interval(days => %s)", (lid, tage)):
        titel = " ".join(str(z["titel"] or "Termin").split())
        text = f"Termin (abgesagt): {titel}" if z["abgesagt_am"] else f"Termin: {titel}"
        aus.append({"datum": z["beginn"], "art": "termin_akte", "kanal": "", "text": text})
    for z in _lesen(
            "Mitschriften",
            "select m.geholt_am, m.auswertung_status, m.auswertung_json, m.auswertung_am "
            f"from termin_mitschriften m where m.uid in ({eigene}) "
            "and m.geholt_am > now() - make_interval(days => %s)", (lid, tage)):
        aus.append({"datum": z["geholt_am"], "art": "mitschrift", "kanal": "",
                    "text": "Mitschrift vorhanden"})
        if z["auswertung_status"] != "fertig":
            continue
        j = z["auswertung_json"] if isinstance(z["auswertung_json"], dict) else {}
        for pp in j.get("painpoints") or []:
            zitat = " ".join(str(pp.get("zitat") or "").split()) if isinstance(pp, dict) else ""
            if zitat:
                aus.append({"datum": z["auswertung_am"] or z["geholt_am"], "art": "painpoint",
                            "kanal": "", "text": f"Painpoint: {zitat}"})
    return aus


def kontakt_historie(lead_id, tage=365, mit_mail: bool = True, mit_akten: bool = False) -> list:
    """`mit_mail=False` laesst E-Mail-Entwuerfe weg: die Oberflaeche zeigt
    Mailinhalt (Betreff, Anfang) nur dem Postfach-Besitzer.
    `mit_akten=True` nimmt Termin-Akten, Mitschrift und Painpoint-Zitate
    dazu - nur fuer Felix' eigene Seiten. Agent-Werkzeuge, Briefing und
    `letzter_kontakt` bleiben auf False: Zitate sind gesprochener Kundentext
    und gehen nie an ein Cloud-Modell."""
    lid = str(lead_id)
    aus = []
    for z in _lesen(
            "Entwuerfe (thema)",
            "select channel, subject, thema, newsletter, left(body, 60) as anfang, "
            "coalesce(sent_at, created_at) as datum from drafts where lead_id = %s "
            "and status = 'sent' and coalesce(sent_at, created_at) > now() - make_interval(days => %s)"
            + ("" if mit_mail else " and channel <> 'email'"),
            (lid, tage)):
        art = "newsletter" if z["newsletter"] else "entwurf"
        text = z["thema"] or z["subject"] or z["anfang"] or ""
        aus.append({"datum": z["datum"], "art": art, "kanal": z["channel"], "text": text})
    for z in _lesen(
            "Termine",
            "select type, payload, created_at from activities where lead_id = %s and type in "
            "('termin','termin_abgesagt','einladung_entworfen') and created_at > now() - "
            "make_interval(days => %s)", (lid, tage)):
        p = z["payload"] if isinstance(z["payload"], dict) else {}
        text = {"termin": f"Termin {p.get('datum','')} {p.get('uhrzeit','')} {p.get('thema','')}",
                "termin_abgesagt": f"Termin abgesagt {p.get('datum','')}",
                "einladung_entworfen": f"Einladung {p.get('datum','')} {p.get('uhrzeit','')}"}[z["type"]]
        aus.append({"datum": z["created_at"], "art": "termin", "kanal": "", "text": " ".join(text.split())})
    # nachricht_ausgehend bucht der Webhook fuer jede eigene WhatsApp-Nachricht —
    # vom Handy wie vom Dispatcher; er unterscheidet die beiden nicht.
    for z in _lesen(
            "Handy-Summen",
            "select date_trunc('month', created_at) as monat, count(*) as n, max(created_at) as zuletzt "
            "from activities where lead_id = %s and type = 'nachricht_ausgehend' and created_at > "
            "now() - make_interval(days => %s) group by 1", (lid, tage)):
        aus.append({"datum": z["zuletzt"], "art": "handy", "kanal": "whatsapp",
                    "text": f"{z['n']} gesendete WhatsApp-Nachrichten (Handy oder System) "
                            f"im {z['monat']:%m/%Y}"})
    if mit_akten:
        aus.extend(_akten_eintraege(lid, tage))
    aus.sort(key=lambda e: e["datum"], reverse=True)
    return aus


def zuletzt(lead_id) -> dict | None:
    return next((e for e in kontakt_historie(lead_id) if e["art"] != "handy"), None)
