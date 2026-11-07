"""Erledigt-Zustand und Liste offener Mails (Spec 2026-11-07, Z3).

Offen heisst: im Posteingang eingeordnet, vom Antwort-Abgleich geprueft, nicht
erledigt, nicht geloescht und ab dem Stichtag. Datenzugriff auf Mails nur ueber
post_struktur (sichtbar_sql / mail_lesen): nur der Besitzer sieht und aendert.
"""
import email.utils
from datetime import date

import post_struktur
import post_ziel
from post_struktur import Betrachter

RECHNUNGEN = "Rechnungen"
ARTEN = ("erledigt", "bezahlt")
JE_SEITE = 50

# Absenderadresse in SQL, kleingeschrieben; Task 7 nutzt sie wieder.
ABSENDER_SQL = "lower(coalesce(substring(m.von from '<([^>]+)>'), trim(m.von)))"


def stichtag_gesetzt() -> bool:
    return post_ziel.ALTBESTAND_AB != date.max


def offen_sql() -> str:
    """WHERE-Fragment fuer `post_mails m`, ohne Parameter. Der Stichtag wird
    bei jedem Aufruf gelesen; ohne Stichtag ist nichts offen."""
    if not stichtag_gesetzt():
        return "false"
    ab = post_ziel.ALTBESTAND_AB.isoformat()  # date, keine Nutzereingabe
    return ("(m.ziel = 'posteingang' and m.status = 'eingeordnet' "
            "and m.erledigt_am is null and m.abgeglichen_am is not null "
            f"and m.geloescht_am is null and m.datum >= '{ab}')")


def mails_offen(b: Betrachter, suche: str = "",
                seite: int = 1) -> tuple[list[dict], int]:
    """(Zeilen der Seite, Gesamtzahl); am laengsten wartende Mail zuerst."""
    import server
    sicht, params = post_struktur.sichtbar_sql(b)
    teile = [offen_sql(), sicht]
    if suche and suche.strip():
        teile.append("m.suchtext @@ websearch_to_tsquery('german', %s)")
        params.append(suche)
    where = " and ".join(teile)
    gesamt = server._q(
        f"select count(*) as n from post_mails m where {where}", params)[0]["n"]
    seite = max(1, int(seite))
    zeilen = server._q(
        f"select {post_struktur._spalten()}, m.ordner_stand, m.erledigt_am, "
        "m.erledigt_art, m.bezahlt_am, m.abgleich_aus, k.kennung, "
        f"(select l.id from leads l where lower(l.email) = {ABSENDER_SQL} "
        "order by l.created_at limit 1) as lead_id "
        "from post_mails m join post_konten k on k.id = m.konto_id "
        f"where {where} order by m.datum asc, m.id limit %s offset %s",
        params + [JE_SEITE, (seite - 1) * JE_SEITE])
    return zeilen, int(gesamt)


def _eigene(b: Betrachter, mail_id: str) -> "dict | None":
    m = post_struktur.mail_lesen(b, mail_id)
    if m is None or m["besitzer"] != b.name:
        return None
    return m


def erledigen(b: Betrachter, mail_id: str, art: str) -> bool:
    import server
    if art not in ARTEN:
        return False
    m = _eigene(b, mail_id)
    if m is None:
        return False
    if art == "bezahlt" and m["fach"] != RECHNUNGEN:
        return False
    bezahlt = ", bezahlt_am = now()" if art == "bezahlt" else ""
    zeilen = server._q(
        "update post_mails set erledigt_am = now(), erledigt_art = %s"
        f"{bezahlt} where id = %s and besitzer = %s and erledigt_am is null "
        "returning id", (art, m["id"], b.name))
    return bool(zeilen)


def wieder_oeffnen(b: Betrachter, mail_id: str) -> bool:
    import server
    m = _eigene(b, mail_id)
    if m is None:
        return False
    zeilen = server._q(
        "update post_mails set erledigt_am = null, erledigt_art = null, "
        "bezahlt_am = null, abgleich_aus = true "
        "where id = %s and besitzer = %s returning id", (m["id"], b.name))
    return bool(zeilen)


def kontakt_anlegen(b: Betrachter, mail_id: str) -> "str | None":
    import server
    m = _eigene(b, mail_id)
    if m is None:
        return None
    adresse = post_struktur.absender_adresse(m["von"])
    if not adresse:
        return None
    vorhanden = server._q(
        "select id from leads where lower(email) = %s order by created_at limit 1",
        (adresse,))
    if vorhanden:
        return str(vorhanden[0]["id"])
    name = email.utils.parseaddr(m["von"] or "")[0].strip() or adresse.split("@")[0]
    neu = server._q(
        "insert into leads (name, email, source) values (%s, %s, 'email') "
        "returning id", (name, adresse))
    return str(neu[0]["id"])
