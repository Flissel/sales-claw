"""Erledigt-Zustand und Liste offener Mails (Spec 2026-11-07, Z3).

Offen heisst: im Posteingang eingeordnet, vom Antwort-Abgleich geprueft, nicht
erledigt, nicht geloescht und ab dem Stichtag. Datenzugriff auf Mails nur ueber
post_struktur (sichtbar_sql / mail_lesen): nur der Besitzer sieht und aendert.
"""
import email.utils
import imaplib
import logging
from datetime import date

import post_imap
import post_struktur
import post_ziel
from post_struktur import Betrachter

LOG = logging.getLogger("sales-post.abgleich")
RECHNUNGEN = "Rechnungen"
ARTEN = ("erledigt", "bezahlt")
JE_SEITE = 50

# Absenderadresse in SQL, kleingeschrieben; Task 7 nutzt sie wieder.
ABSENDER_SQL = "lower(coalesce(substring(m.von from '<([^>]+)>'), trim(m.von)))"


def stichtag_gesetzt() -> bool:
    return post_ziel.ALTBESTAND_AB != date.max


def stichtag_sql() -> str:
    """Datumsbedingung fuer `post_mails m`: ab dem Stichtag, ohne Stichtag nie. Offen-Liste
    und Antwort-Abgleich nutzen dieselbe Bedingung. Wird bei jedem Aufruf gelesen (R4)."""
    if not stichtag_gesetzt():
        return "false"
    ab = post_ziel.ALTBESTAND_AB.isoformat()  # date, keine Nutzereingabe
    return f"m.datum >= '{ab}'"


def offen_sql() -> str:
    """WHERE-Fragment fuer `post_mails m`, ohne Parameter. Ohne Stichtag ist nichts offen."""
    return ("(m.ziel = 'posteingang' and m.status = 'eingeordnet' "
            "and m.erledigt_am is null and m.abgeglichen_am is not null "
            f"and m.geloescht_am is null and {stichtag_sql()})")


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


# --- Antwort-Abgleich (Spec Z3, Festlegung 6) ---------------------------------------
# Drei Signale: versandter Entwurf (DB), \Answered am Server, Antwort im Gesendet-Ordner.
# Das Postfach wird nur gelesen. \Answered ist so aktuell wie der letzte Abruf.

def _kandidaten_sql() -> str:
    """Wird je Aufruf gebaut: der Stichtag darf nicht beim Import einfrieren (R4)."""
    return f"""
select m.id, m.imap_uid, m.message_id, m.message_id_ersatz, m.ordner, m.ordner_uid,
       (not m.message_id_ersatz and exists (
          select 1 from drafts d where d.status = 'sent'
             and trim(both '<>' from d.antwort_auf) = m.message_id)) as entwurf_gesendet
  from post_mails m
 where m.konto_id = %(konto)s and m.besitzer = %(besitzer)s
   and m.ziel = 'posteingang' and m.status = 'eingeordnet'
   and m.erledigt_am is null and not m.abgleich_aus and m.geloescht_am is null
   and {stichtag_sql()}
 order by m.abgeglichen_am nulls first, m.datum, m.id
 limit %(n)s
"""


def _beantwortet(mail_id) -> None:
    import server
    server._q("update post_mails set erledigt_am = now(), erledigt_art = 'beantwortet', "
              "abgeglichen_am = now() where id = %s and erledigt_am is null "
              "and not abgleich_aus returning id", (mail_id,))


def _geprueft(mail_id, fehlt: bool = False) -> None:
    import server
    server._q("update post_mails set abgeglichen_am = now()"
              + (", ordner_stand = 'fehlt'" if fehlt else "")
              + " where id = %s returning id", (mail_id,))


def _imap_uid(z: dict) -> "int | None":
    """UID der Mail in ihrem Ordner; None, wenn sie sich nicht bestimmen laesst."""
    if (z["ordner"] or "INBOX") == "INBOX":
        uid = z["imap_uid"]
    else:
        uid = z["ordner_uid"]
    return int(uid) if uid is not None and int(uid) > 0 else None


def _konto_abgleichen(konto: dict, je_konto: int, verbinden, bilanz: dict) -> None:
    import server
    zeilen = server._q(_kandidaten_sql(), {"konto": konto["id"], "besitzer": konto["besitzer"],
                                           "n": max(1, int(je_konto))})
    if not zeilen:
        return
    rest = []
    for z in zeilen:                       # Signal 1: kein IMAP noetig
        if z["entwurf_gesendet"]:
            _beantwortet(z["id"])
            bilanz["geprueft"] += 1
            bilanz["beantwortet"] += 1
        else:
            rest.append(z)
    if not rest:
        return
    kasten = verbinden(konto)
    try:
        post_imap.faehigkeiten_auffrischen(kasten)
        # \Answered nur, wenn die gespeicherten INBOX-UIDs noch gelten (UIDVALIDITY gleich).
        # Andere Ordner haben keine gespeicherte Validity: dort kein Signal 2.
        try:
            live = post_imap.uidvalidity_lesen(kasten, "INBOX")
        except post_imap.Fehlt:
            live = None
        gespeichert = konto.get("uidvalidity")
        inbox_gilt = (live is not None and gespeichert is not None
                      and int(live) == int(gespeichert))
        flags: dict = {}                   # uid -> Flags (nur INBOX)
        inbox_fehlt = False
        uids = [u for u in (_imap_uid(z) for z in rest
                            if (z["ordner"] or "INBOX") == "INBOX") if u is not None]
        if inbox_gilt and uids:
            try:
                flags = post_imap.flags_lesen(kasten, "INBOX", uids)
            except post_imap.Fehlt:
                inbox_fehlt = True
        # Gesendet-Ordner einmal lesend waehlen, danach nur SEARCH je Mail.
        gesendet = post_imap.gesendet_ordner(kasten)
        sent_ok = False
        if gesendet and any(not z["message_id_ersatz"] and z["message_id"] for z in rest):
            try:
                post_imap.lesend_waehlen(kasten, gesendet)
                sent_ok = True
            except (post_imap.Fehlt, post_imap.ImapFehler, imaplib.IMAP4.error) as e:
                bilanz["sent_fehler"] += 1
                LOG.warning("Konto %s: Gesendet-Ordner nicht lesbar (%s)",
                            konto["kennung"], type(e).__name__)
        for z in rest:
            ordner, uid = z["ordner"] or "INBOX", _imap_uid(z)
            antwort = False
            if inbox_gilt and ordner == "INBOX" and uid is not None:
                if inbox_fehlt or uid not in flags:
                    _geprueft(z["id"], fehlt=True)
                    bilanz["geprueft"] += 1
                    bilanz["fehlt"] += 1
                    continue
                antwort = "\\Answered" in flags[uid]
            if not antwort and sent_ok and not z["message_id_ersatz"]:
                try:
                    antwort = post_imap.antwort_suchen(kasten, z["message_id"])
                except (post_imap.ImapFehler, imaplib.IMAP4.error) as e:
                    bilanz["sent_fehler"] += 1
                    LOG.warning("Konto %s: Gesendet-Suche abgelehnt (%s)",
                                konto["kennung"], type(e).__name__)
            if antwort:
                _beantwortet(z["id"])
                bilanz["beantwortet"] += 1
            else:
                _geprueft(z["id"])
            bilanz["geprueft"] += 1
    finally:
        try:
            kasten.logout()
        except Exception:  # noqa: BLE001 - Abmelden ist Hoeflichkeit
            pass


def abgleich(verbinden=None, je_konto: int = 50) -> dict:
    """Je aktivem Konto des Container-Besitzers hoechstens `je_konto` offene Mails auf
    Antworten pruefen. Ohne Stichtag oder Besitzer: nichts, keine Verbindung.
    Rueckgabe: {"geprueft", "beantwortet", "fehlt", "konten_fehler", "sent_fehler"}."""
    import server
    import post_konten
    bilanz = {"geprueft": 0, "beantwortet": 0, "fehlt": 0, "konten_fehler": 0,
              "sent_fehler": 0}
    besitzer = post_struktur.container_besitzer()
    if not stichtag_gesetzt() or not besitzer:
        return bilanz
    verbinden = verbinden or post_konten.verbinden
    konten = server._q("select * from post_konten where aktiv and besitzer = %s "
                       "order by kennung", (besitzer,))
    for konto in konten:
        try:
            _konto_abgleichen(konto, je_konto, verbinden, bilanz)
        except Exception as e:  # noqa: BLE001 - ein Konto haelt die anderen nicht auf
            bilanz["konten_fehler"] += 1
            LOG.warning("Konto %s: Abgleich abgebrochen (%s)", konto["kennung"],
                        type(e).__name__)
    if any(bilanz.values()):
        LOG.info("Abgleich: %d geprueft, %d beantwortet, %d fehlen, %d Kontofehler",
                 bilanz["geprueft"], bilanz["beantwortet"], bilanz["fehlt"],
                 bilanz["konten_fehler"])
    return bilanz
