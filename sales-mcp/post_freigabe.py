"""Loeschfreigabe je Jahr (Spec 2026-11-06 §6.1).

Felix sieht je Jahr eine Vorschau der Werbe-Absender und gibt das Jahr mit einem Klick
frei. Ohne Freigabe wird im Altbestand nichts geloescht. Grundlage sind immer nur Mails
aus Konten des Besitzers (Join ueber post_konten, nicht nur post_mails.besitzer).
Absender werden durchgehend ueber die kleingeschriebene Adresse verglichen. Jahre gelten
in UTC (Session-Zeitzone von server._q). Keine Logs mit Betreffen oder Adressen.
"""
from __future__ import annotations

from psycopg.types.json import Jsonb

import post_struktur
import post_werbung
import post_ziel

BEISPIELE = 3
BETREFF_MAX = 80
_OHNE_BETREFF = "(kein Betreff)"

# Mails des Besitzers im Jahr, die heute auf `loeschen` stehen (nur eigene Konten).
_LOESCHBAR = ("from post_mails m join post_konten k on k.id = m.konto_id "
              "where k.besitzer = %s and m.status = 'eingeordnet' and m.ziel = 'loeschen' "
              "and extract(year from m.datum) = %s")


def _db():
    # server erst hier: das Modul bleibt ohne Datenbank importierbar.
    import server
    return server


def _adresse(wert: str) -> str:
    """Kleingeschriebene Adresse aus „Name <addr>“ oder einer blanken Adresse; leer, wenn
    keine lesbar ist."""
    return post_struktur.absender_adresse(wert or "")


def vorschau(besitzer: str, jahr: int) -> list[dict]:
    """Absender, deren Mails im Jahr geloescht wuerden: [{absender, anzahl, beispiele}],
    meiste Mails zuerst."""
    zeilen = _db()._q(
        f"select m.von, m.betreff {_LOESCHBAR} order by m.datum desc, m.id", (besitzer, jahr))
    gruppen: dict[str, dict] = {}
    for z in zeilen:
        adresse = _adresse(z["von"])
        if not adresse:
            continue          # ohne lesbare Adresse wird nie geloescht (post_ziel)
        g = gruppen.setdefault(adresse, {"absender": adresse, "anzahl": 0, "beispiele": []})
        g["anzahl"] += 1
        if len(g["beispiele"]) < BEISPIELE:
            g["beispiele"].append(((z["betreff"] or "").strip() or _OHNE_BETREFF)[:BETREFF_MAX])
    return sorted(gruppen.values(), key=lambda g: (-g["anzahl"], g["absender"]))


def loeschliste(betrachter, jahr: int, adresse: str) -> list[dict]:
    """Die einzelnen Mails eines Absenders, die im Jahr geloescht wuerden: [{datum,
    kennung, betreff}], neueste zuerst. Nur eigene Konten (wie vorschau) und zusaetzlich
    nur, was der Betrachter laut sichtbar_sql sehen darf. Eine unlesbare Adresse liefert
    eine leere Liste."""
    adresse = _adresse(adresse)
    if not adresse:
        return []
    sicht, params = post_struktur.sichtbar_sql(betrachter)
    # strpos grenzt nur vor (Gross-/Kleinschreibung, „Name <addr>“); entscheidend ist
    # der exakte Vergleich der Adresse unten, wie in vorschau.
    zeilen = _db()._q(
        f"select m.datum, m.betreff, m.von, k.kennung {_LOESCHBAR} and {sicht} "
        "and strpos(lower(m.von), %s) > 0 order by m.datum desc, m.id",
        (betrachter.name, jahr, *params, adresse))
    return [{"datum": z["datum"], "kennung": z["kennung"],
             "betreff": (z["betreff"] or "").strip() or _OHNE_BETREFF}
            for z in zeilen if _adresse(z["von"]) == adresse]


def freigeben(besitzer: str, jahr: int, gezeigt: list[str], ausgenommen: list[str]) -> int:
    """Gibt das Jahr zum Loeschen frei. Alles in einer Transaktion: Freigabezeile,
    Schutzregeln der ausgenommenen Absender, zur_info fuer deren Mails und to_review fuer
    Absender, die Felix in der Vorschau nicht gesehen hat. Ein zweiter Aufruf fuer
    dasselbe Jahr wirft ValueError und aendert nichts.

    Rueckgabe: Zahl der Mails, die jetzt geloescht werden duerfen."""
    nimm = sorted({a for a in (_adresse(x) for x in ausgenommen) if a})
    gesehen = {a for a in (_adresse(x) for x in gezeigt) if a}
    server = _db()
    with server.pool.connection() as conn:
        # Zuerst der Lock: ein laufender ziele_aktualisieren-Lauf endet vorher, ein spaeterer
        # liest diese Freigabe (sonst koennte er unter alten Freigaben `loeschen` schreiben).
        conn.execute("select pg_advisory_xact_lock(%s)", (post_ziel.FREIGABE_SPERRE,))
        # Konflikt statt Fehler: beim Doppelklick gewinnt genau ein Aufruf.
        neu = conn.execute(
            "insert into post_loeschfreigaben (besitzer, jahr, ausgenommen) values (%s, %s, %s) "
            "on conflict (besitzer, jahr) do nothing returning id",
            (besitzer, jahr, Jsonb(nimm))
        ).fetchone()
        if neu is None:
            raise ValueError("schon freigegeben")
        for adresse in nimm:
            post_werbung.schutz_setzen(besitzer, adresse, conn=conn)

        kandidaten = conn.execute(
            f"select m.id, m.von {_LOESCHBAR} and not m.ziel_manuell for update of m",
            (besitzer, jahr)).fetchall()
        zur_info, to_review = [], []
        for z in kandidaten:
            adresse = _adresse(z["von"])
            if adresse in nimm:
                zur_info.append(z["id"])
            elif adresse not in gesehen:
                to_review.append(z["id"])      # kam nach dem Laden der Vorschau dazu
        for ziel, ids in (("zur_info", zur_info), ("to_review", to_review)):
            if ids:
                conn.execute("update post_mails set ziel = %s where id = any(%s)", (ziel, ids))
        return conn.execute(f"select count(*) as n {_LOESCHBAR}", (besitzer, jahr)).fetchone()["n"]


def jahre(besitzer: str) -> list[dict]:
    """Je Jahr (neuestes zuerst): eingeordnet = alle eingeordneten Mails, offen = Werbung,
    die auf die Freigabe wartet, zu_loeschen = Werbung in freigegebenem Jahr."""
    zeilen = _db()._q(
        "select y.jahr, y.eingeordnet, "
        "case when f.id is null then y.loeschbar else 0 end as offen, "
        "case when f.id is null then 0 else y.loeschbar end as zu_loeschen, "
        "f.freigegeben_am from ("
        "  select extract(year from m.datum)::int as jahr, count(*)::int as eingeordnet, "
        "  (count(*) filter (where m.ziel = 'loeschen'))::int as loeschbar "
        "  from post_mails m join post_konten k on k.id = m.konto_id "
        "  where k.besitzer = %s and m.status = 'eingeordnet' and m.datum is not null "
        "  group by 1) y "
        "left join post_loeschfreigaben f on f.besitzer = %s and f.jahr = y.jahr "
        "order by y.jahr desc", (besitzer, besitzer))
    return [dict(z) for z in zeilen]


def konten_des_besitzers(besitzer: str) -> list[dict]:
    """Aktive Konten des Besitzers: [{kennung, ordnen_aus}] (ordnen_aus = Grund, warum das
    Konto ruht)."""
    return [dict(z) for z in _db()._q(
        "select kennung, ordnen_aus from post_konten where besitzer = %s and aktiv "
        "order by kennung", (besitzer,))]


def offene_mails(besitzer: str) -> int:
    """Mails des Besitzers, die noch Modellaufrufe brauchen: neue plus der Altbestand, der
    neu einzuordnen ist (dieselbe Auswahl wie post_neu_einordnen, nicht nachgebaut)."""
    import post_neu_einordnen   # erst hier: zieht die Abholung nach
    zeile = _db()._q(
        "select count(*) as n from post_mails m join post_konten k on k.id = m.konto_id "
        f"where k.besitzer = %s and (m.status = 'neu' or ({post_neu_einordnen._altbestand('m.')}))",
        (besitzer,))[0]
    return int(zeile["n"])
