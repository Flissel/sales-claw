"""Postfach an das Ziel angleichen (Spec 2026-11-06 §6, §11, §12).

Je Mail steht in post_mails das Soll (`ziel`, gepflegt von post_ziel) und der zuletzt
bekannte Ist-Stand im Postfach (`ordner`, `ordner_uid`). `ordnen` fuehrt beides fuer
eine begrenzte Zahl Mails je Konto zusammen:

  posteingang -> INBOX, zur_info -> „Zur Info“, to_review -> „To-Review“,
  loeschen    -> endgueltig loeschen, aber nur bei MODUS „voll“ UND Freigabe des
                 Jahres fuer den Besitzer (R5); sonst bleibt die Mail, wo sie ist.
  To-Review aelter als 30 Tage -> loeschen, nur bei MODUS „voll“.

Loeschen ist unumkehrbar, darum gilt im Zweifel: nichts tun und die Zeile als
`fehlt` (Mail nicht da oder eine andere unter der UID) oder `fehler` markieren.
Vor jedem Loeschen (R13): die UID muss noch dieselbe Message-ID tragen, Mails ohne
echte Message-ID werden nie geloescht, das Ziel wird frisch berechnet, und ein
Absender, den Felix bei der Freigabe herausgenommen hat, bleibt.

Kann ein Server den Schritt nicht sicher (kein MOVE/UIDPLUS, Ordner nicht anlegbar)
oder ist die INBOX neu nummeriert (UIDVALIDITY), ruht das Konto: `ordnen_aus` nennt
den Grund, andere Konten laufen weiter (Spec §11).

Protokoll: Konto-Kennung, Aktion, Zahlen, Fehlertyp. Nie Betreff, Absender, Adresse.
Das Loeschprotokoll ist die Zeile selbst: Status `geloescht`, Kopfdaten bleiben.
"""
from __future__ import annotations

import imaplib
import logging
import os

import post_imap
import post_konten
import post_struktur
import post_ziel
import server

LOG = logging.getLogger("sales-post.ordnen")

MODI = ("aus", "verschieben", "voll")
ORDNER = {post_ziel.POSTEINGANG: "INBOX", post_ziel.ZUR_INFO: "Zur Info",
          post_ziel.TO_REVIEW: "To-Review"}
TO_REVIEW_TAGE = 30


def _modus(wert: str | None) -> str:
    """Unbekannte Werte gelten als „aus“: ein Tippfehler darf nichts loeschen."""
    wert = (wert or "").strip().lower()
    if wert in MODI:
        return wert
    if wert:
        LOG.warning("POST_ORDNEN unbekannt - Ordnen bleibt aus")
    return "aus"


# aus | verschieben (alles ausser Loeschen) | voll
MODUS: str = _modus(os.environ.get("POST_ORDNEN"))


def _leere_bilanz() -> dict:
    return {"verschoben": 0, "geloescht": 0, "fehlt": 0, "fehler": 0, "konten_aus": []}


class _Ruhen(Exception):
    """Das Konto soll ruhen; der Text ist der Grund in post_konten.ordnen_aus."""


# Zeilen eines Kontos, deren Ziel nicht zum Ordner passt. Geloescht wird nur bei voll und
# nur mit Freigabe des Besitzers fuer das Jahr (UTC wie die Session, R12); ohne das bleibt
# eine Mail mit Ziel loeschen liegen (R5). Zeilen mit Stand fehlt/fehler werden nicht
# jede Runde neu versucht: was Felix im Postfach selbst bewegt hat, bildet die
# Sammelstelle nicht nach (Spec §6.3). INBOX-Zeilen mit imap_uid <= 0 sind Platzhalter:
# post_abholen hat die INBOX nach einem UIDVALIDITY-Wechsel neu nummeriert und die Mail
# (noch) nicht wiedergefunden. Sie werden uebersprungen, nicht als fehlt markiert, denn
# das Abholen holt hoechstens einen Stapel je Runde und findet sie spaeter wieder.
_OFFENE_SQL = f"""
select m.id, m.imap_uid, m.message_id, m.message_id_ersatz, m.von, m.ziel, m.ordner,
       m.ordner_uid, m.ordner_am, extract(year from m.datum)::int as jahr,
       (m.ziel = 'loeschen' or (m.ziel = 'to_review' and m.ordner = 'To-Review')) as loeschen
  from post_mails m
 where m.konto_id = %(konto)s and m.besitzer = %(besitzer)s
   and m.status = 'eingeordnet' and m.ziel is not null
   and (m.ordner_stand is null or m.ordner_stand = 'ok')
   and not (m.ordner = 'INBOX' and m.imap_uid <= 0)
   and ((m.ziel = 'posteingang' and m.ordner <> 'INBOX')
     or (m.ziel = 'zur_info' and m.ordner <> 'Zur Info')
     or (m.ziel = 'to_review' and m.ordner <> 'To-Review')
     or (%(voll)s and m.ziel = 'loeschen' and exists (
           select 1 from post_loeschfreigaben f
            where f.besitzer = m.besitzer and f.jahr = extract(year from m.datum)))
     or (%(voll)s and m.ziel = 'to_review' and m.ordner = 'To-Review'
           and m.ordner_am < now() - make_interval(days => {TO_REVIEW_TAGE})))
 order by m.datum desc nulls last, m.id
 limit %(n)s
"""


def _konten() -> list[dict]:
    return server._q("select * from post_konten where aktiv and ordnen_aus is null "
                     "order by kennung")


def _ruhen(konto: dict, grund: str) -> None:
    server._q("update post_konten set ordnen_aus = %s where id = %s returning id",
              (grund, konto["id"]))
    LOG.warning("Konto %s: Ordnen ruht (%s)", konto["kennung"], grund)


def _stand(mail_id, stand: str) -> None:
    server._q("update post_mails set ordner_stand = %s, ordner_am = now() "
              "where id = %s returning id", (stand, mail_id))


def _verschoben(z: dict, ordner: str, neue_uid: int | None) -> None:
    # Das Ziel, nach dem gehandelt wurde, wird festgehalten. Eine Handentscheidung, die
    # inzwischen kam, bleibt stehen; die naechste Runde gleicht sie an.
    server._q(
        "update post_mails set ordner = %s, ordner_uid = %s, ordner_stand = 'ok', "
        "ordner_am = now(), ziel = case when ziel_manuell then ziel else %s end "
        "where id = %s returning id", (ordner, neue_uid, z["ziel"], z["id"]))


def _geloescht(z: dict) -> None:
    # Die Zeile bleibt als Loeschprotokoll (Konto, UID, Message-ID, Absender, Betreff,
    # Fach, Ordner); nur der Inhalt geht (Spec §12).
    server._q(
        "update post_mails set status = 'geloescht', geloescht_am = now(), text = null, "
        "auszug = null, ordner_stand = 'ok', ordner_am = now(), ziel = %s "
        "where id = %s returning id", (z["ziel"], z["id"]))


def _uid_im_ordner(kasten, z: dict) -> int:
    """UID der Mail in ihrem jetzigen Ordner. In der INBOX die beim Abholen gesehene UID,
    solange ordnen die Mail nie bewegt hat; sonst die UID aus COPYUID; fehlt die, wird
    per Message-ID gesucht. Ohne echte Message-ID laesst sich nichts suchen."""
    if z["ordner_uid"] is not None:
        return int(z["ordner_uid"])
    if z["ordner"] == "INBOX" and z["ordner_am"] is None:
        return int(z["imap_uid"])
    if z["message_id_ersatz"]:
        raise post_imap.Fehlt("ohne Message-ID nicht auffindbar")
    post_imap.waehlen(kasten, z["ordner"])
    return post_imap.suchen(kasten, z["message_id"])


def _loeschen_erlaubt(konto: dict, z: dict) -> bool:
    """Letzte Pruefung direkt vor dem Loeschen, frisch aus der Datenbank (R13)."""
    erwartet = post_ziel.LOESCHEN if z["ziel"] == post_ziel.LOESCHEN else post_ziel.TO_REVIEW
    frisch = post_ziel.ziel_frisch(z["id"])
    if frisch != erwartet:
        # Seit dem Speichern geaendert (z. B. Absender geschuetzt): nicht loeschen, das
        # neue Ziel gilt ab jetzt. Dieselben Bedingungen wie in ziele_aktualisieren.
        if frisch is not None:
            server._q("update post_mails set ziel = %s where id = %s and status = 'eingeordnet' "
                      "and not ziel_manuell returning id", (frisch, z["id"]))
        LOG.info("Konto %s: Loeschen ausgelassen, Ziel geaendert", konto["kennung"])
        return False
    freigabe = None
    if z["jahr"] is not None:
        zeilen = server._q("select ausgenommen from post_loeschfreigaben "
                           "where besitzer = %s and jahr = %s", (konto["besitzer"], z["jahr"]))
        freigabe = zeilen[0] if zeilen else None
    if erwartet == post_ziel.LOESCHEN and freigabe is None:
        return False                 # ohne Freigabe nie (die Abfrage oben sollte das schon)
    if freigabe is not None:
        adresse = post_struktur.absender_adresse(z["von"])
        ausgenommen = {str(a).strip().lower() for a in (freigabe["ausgenommen"] or [])}
        if not adresse or adresse in ausgenommen:
            # Felix hat den Absender herausgenommen, die Schutzregel fehlt aber: das
            # passt nicht zusammen, also nichts tun und zum Nachsehen markieren.
            _stand(z["id"], "fehler")
            LOG.warning("Konto %s: Loeschen verweigert, Absender ausgenommen", konto["kennung"])
            return False
    return True


def _zeile_ordnen(kasten, konto: dict, z: dict, bilanz: dict, angelegt: set) -> None:
    kennung = konto["kennung"]
    if z["loeschen"]:
        if MODUS != "voll":
            return
        if z["message_id_ersatz"]:
            # Nicht pruefbar, ob die UID noch diese Mail ist: nie loeschen (R13).
            _stand(z["id"], "fehler")
            bilanz["fehler"] += 1
            LOG.info("Konto %s: Loeschen verweigert, keine Message-ID", kennung)
            return
        if not _loeschen_erlaubt(konto, z):
            return
        uid = _uid_im_ordner(kasten, z)
        post_imap.loeschen(kasten, z["ordner"], uid, konto["anbieter"],
                           message_id=z["message_id"])
        _geloescht(z)
        bilanz["geloescht"] += 1
        LOG.info("Konto %s: geloescht aus %s (uid %d)", kennung, z["ordner"], uid)
        return

    ziel_ordner = ORDNER[z["ziel"]]
    if z["message_id_ersatz"] and z["ordner"] != "INBOX":
        # Ausserhalb der INBOX gibt es keine gespeicherte UIDVALIDITY, und ohne
        # Message-ID laesst sich die UID nicht pruefen: lieber nicht raten.
        _stand(z["id"], "fehler")
        bilanz["fehler"] += 1
        LOG.info("Konto %s: Verschieben verweigert, keine Message-ID ausserhalb der INBOX",
                 kennung)
        return
    uid = _uid_im_ordner(kasten, z)
    if ziel_ordner != "INBOX" and ziel_ordner not in angelegt:
        post_imap.ordner_sicherstellen(kasten, ziel_ordner)
        angelegt.add(ziel_ordner)
    neu = post_imap.verschieben(kasten, z["ordner"], uid, ziel_ordner,
                                message_id=None if z["message_id_ersatz"] else z["message_id"])
    _verschoben(z, ziel_ordner, neu)
    bilanz["verschoben"] += 1
    LOG.info("Konto %s: verschoben %s -> %s (uid %d)", kennung, z["ordner"], ziel_ordner, uid)


def _konto_ordnen(konto: dict, je_konto: int, verbinden, bilanz: dict) -> None:
    zeilen = server._q(_OFFENE_SQL, {"konto": konto["id"], "besitzer": konto["besitzer"],
                                     "voll": MODUS == "voll", "n": max(1, int(je_konto))})
    if not zeilen:
        return                       # nichts zu tun: keine Verbindung
    kasten = verbinden(konto)
    try:
        post_imap.faehigkeiten_auffrischen(kasten)
        faehig = post_imap.faehigkeiten(kasten)
        if "MOVE" not in faehig and "UIDPLUS" not in faehig:
            raise _Ruhen("Server kann weder MOVE noch UIDPLUS")
        try:
            uidvalidity = post_imap.waehlen(kasten, "INBOX")
        except post_imap.Fehlt:
            raise RuntimeError("INBOX nicht waehlbar") from None
        if (uidvalidity is None or konto["uidvalidity"] is None
                or int(uidvalidity) != int(konto["uidvalidity"])):
            # Die gespeicherten UIDs zeigen dann womoeglich auf andere Mails.
            raise _Ruhen("UIDVALIDITY der INBOX weicht ab (Postfach neu nummeriert)")
        angelegt: set = set()
        for z in zeilen:
            try:
                _zeile_ordnen(kasten, konto, z, bilanz, angelegt)
            except post_imap.Fehlt:
                _stand(z["id"], "fehlt")
                bilanz["fehlt"] += 1
                LOG.info("Konto %s: Mail fehlt im Ordner %s", konto["kennung"], z["ordner"])
            except imaplib.IMAP4.abort:
                raise                # Verbindung weg: ganzes Konto in dieser Runde abbrechen
            except (post_imap.ImapFehler, imaplib.IMAP4.error, ValueError) as e:
                # ValueError: z. B. leere Message-ID ohne Ersatz-Markierung, die
                # post_imap.loeschen ablehnt. Betrifft nur diese Zeile, nicht das Konto.
                _stand(z["id"], "fehler")
                bilanz["fehler"] += 1
                LOG.warning("Konto %s: Befehl abgelehnt (%s)", konto["kennung"],
                            type(e).__name__)
    finally:
        try:
            kasten.logout()
        except Exception:  # noqa: BLE001 - Abmelden ist Hoeflichkeit
            pass


def ordnen(je_konto: int = 50, verbinden=None) -> dict:
    """Je aktivem, nicht ruhendem Konto hoechstens `je_konto` Mails an ihr Ziel angleichen.
    `verbinden` (Konto-Zeile -> angemeldeter Kasten) ist fuer Tests austauschbar.
    Rueckgabe: {"verschoben", "geloescht", "fehlt", "fehler", "konten_aus": [kennung]}."""
    bilanz = _leere_bilanz()
    if MODUS == "aus":
        return bilanz
    verbinden = verbinden or post_konten.verbinden
    for konto in _konten():
        try:
            _konto_ordnen(konto, je_konto, verbinden, bilanz)
        except (_Ruhen, post_imap.NichtUnterstuetzt) as e:
            _ruhen(konto, str(e))
            bilanz["konten_aus"].append(konto["kennung"])
        except Exception as e:  # noqa: BLE001 - ein Konto haelt die anderen nicht auf
            bilanz["fehler"] += 1
            LOG.warning("Konto %s: Ordnen abgebrochen (%s)", konto["kennung"], type(e).__name__)
    if any(bilanz[k] for k in ("verschoben", "geloescht", "fehlt", "fehler", "konten_aus")):
        LOG.info("Ordnen (%s): %s", MODUS, bilanz)
    return bilanz
