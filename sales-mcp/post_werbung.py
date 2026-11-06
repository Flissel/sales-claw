"""Werbung ohne Modell (Spec §4): Absender-Regeln, Schutzregel, Regel-Vorschlag.

Spaeter loescht das System sichere Werbung. Darum zaehlt hier jeder Schutz: eine
Werbe-Regel greift nicht bei Betreffs, die nach Rechnung/Vertrag/Konto klingen, nicht
bei Absendern mit „nie Werbung“ und nicht bei Absendern, von denen derselbe Besitzer
schon etwas Wichtiges bekam. Alle Abfragen sind auf den Besitzer begrenzt (R13).
"""
from __future__ import annotations

import post_struktur

BLEIBT_BETREFF = (r"(?i)(rechnung|invoice|beleg|quittung|bestell|order|versand|lieferung|"
                  r"vertrag|kündig|mahnung|zahlung|payment|konto|passwort|sicherheit)")

WERBUNG = "Werbung"
MIN_SICHERE = 3           # so viele sichere Werbemails, bevor eine Regel vorgeschlagen wird
SYSTEM_NAME = "post_werbung"


def _db():
    # server erst hier: das Modul bleibt ohne Datenbank importier- und testbar.
    import server
    return server


def _muster(von: str) -> tuple[str, str] | None:
    """(Adresse, Regelmuster) fuer den Absender, None ohne Mailadresse. Die Adresse ist
    kleingeschrieben, damit dieselbe Person nicht an der Schreibweise vorbeirutscht."""
    adresse = post_struktur.absender_adresse(von)
    if not adresse:
        return None
    return adresse, post_struktur.absender_muster(adresse)


def geschuetzt(besitzer: str, von: str) -> bool:
    """Gibt es fuer diesen Absender und diesen Besitzer eine Regel „nie Werbung“?"""
    m = _muster(von)
    if m is None or not besitzer:
        return False
    return bool(_db()._q(
        "select 1 from post_regeln where art = 'nie_werbung' and feld = 'von' "
        "and besitzer = %s and lower(muster) = lower(%s) limit 1", (besitzer, m[1])))


def bleibt_immer_absender(besitzer: str, von: str) -> bool:
    """Hat dieser Besitzer von diesem Absender schon eine Mail in einem Fach, das nie
    Werbung ist (R3)? Dann gilt keine Werbe-Regel mehr fuer ihn (Spec §4)."""
    m = _muster(von)
    if m is None or not besitzer:
        return False
    return bool(_db()._q(
        "select 1 from post_mails where besitzer = %s and fach = any(%s) and von ~* %s limit 1",
        (besitzer, sorted(post_struktur.BLEIBT_IMMER), m[1])))


def regel_vorschlagen(besitzer: str, von: str) -> bool:
    """Legt die Absender-Regel „Werbung“ an, wenn der Absender >= 3 sichere Werbemails
    hat, keine einzige Mail in einem Bleibt-immer- oder Zum-Nachsehen-Fach und nicht
    geschuetzt ist. Eine schon vorhandene Regel fuer diesen Absender (auch eine
    menschliche mit anderem Fach) wird nie ueberschrieben. Rueckgabe: Regel angelegt."""
    m = _muster(von)
    if m is None or not besitzer or geschuetzt(besitzer, von):
        return False
    _, muster = m
    server = _db()
    sperr_faecher = sorted(post_struktur.BLEIBT_IMMER | {post_struktur.UNKLAR})
    zeile = server._q(
        "select count(*) filter (where werbung_sicher) as sichere, "
        "count(*) filter (where fach = any(%s)) as sperre, "
        # Bereich der juengsten sicheren Werbemail: die Regel soll dort einsortieren, wo der
        # Absender bisher landete (Firmen- oder Privatpostfach).
        "(array_agg(bereich order by eingeordnet_am desc nulls last) "
        "filter (where werbung_sicher))[1] as bereich "
        "from post_mails where besitzer = %s and von ~* %s", (sperr_faecher, besitzer, muster))[0]
    if zeile["sichere"] < MIN_SICHERE or zeile["sperre"] > 0:
        return False
    with server.pool.connection() as conn:
        # Eine Anweisung, damit zwei gleichzeitige Durchgaenge keine Doppelregel anlegen.
        angelegt = conn.execute(
            "insert into post_regeln (muster, feld, bereich, fach, sensibel, angelegt_von, "
            "besitzer, art) select %s, 'von', %s, %s, false, %s, %s, 'einordnen' "
            "where not exists (select 1 from post_regeln where feld = 'von' and art = 'einordnen' "
            "and besitzer is not distinct from %s and lower(muster) = lower(%s))",
            (muster, zeile["bereich"] or "privat", WERBUNG, SYSTEM_NAME, besitzer, besitzer, muster)).rowcount
    return angelegt > 0


def schutz_setzen(besitzer: str, von: str, conn=None) -> None:
    """Regel „nie Werbung“ anlegen; Werbe-Regeln desselben Musters und Besitzers entfallen,
    sonst fuehre eine aeltere Regel den Absender weiter als Werbung.

    Mit `conn` laeuft alles in der Transaktion des Aufrufers (Loeschfreigabe: ganz oder gar
    nicht); ohne eigene Verbindung, die sofort festgeschrieben wird."""
    m = _muster(von)
    if m is None or not besitzer:
        return
    _, muster = m

    def schreiben(c) -> None:
        c.execute(
            "delete from post_regeln where art = 'einordnen' and fach = %s and feld = 'von' "
            "and besitzer = %s and lower(muster) = lower(%s)", (WERBUNG, besitzer, muster))
        c.execute(
            "insert into post_regeln (muster, feld, sensibel, angelegt_von, besitzer, art) "
            "select %s, 'von', false, %s, %s, 'nie_werbung' where not exists ("
            "select 1 from post_regeln where art = 'nie_werbung' and feld = 'von' "
            "and besitzer = %s and lower(muster) = lower(%s))",
            (muster, SYSTEM_NAME, besitzer, besitzer, muster))

    if conn is not None:
        schreiben(conn)
        return
    with _db().pool.connection() as eigene:
        schreiben(eigene)
