"""Gespeicherte Mitschrift bereinigen und neu auswerten lassen (Abnahme-Befunde 14.11.2026).

Duenner Kern fuer scripts/neu_auswerten.py: die Segmente einer Mitschrift laufen
durch mitschrift_bereinigen.bereinigen, die Auswertung wird zurueckgesetzt
(Status offen, Versuche 0, Ergebnis geleert - die alte Auswertung verweist auf
Segment-Indizes der alten Fassung), der Taktgeber wertet danach neu aus. Bleibt
nach der Bereinigung nichts, ist der Status 'leer' (wie beim Ablegen).
Offene Vorschlaege der alten Auswertung fallen weg (die neue legt eigene an),
bestaetigte und verworfene bleiben.

Nur wenn die Auswertung abgeschlossen ist (fertig, fehler, leer - sonst koennte
der Taktgeber gerade rechnen) und kein Entwurf verschickt ist (drafts.status
'sent'; 'approved' gilt als unterwegs, 'failed' als Versandversuch). Ein offener
Entwurf (pending) bleibt und wird gemeldet. Alles in EINER Transaktion.
Rueckgabe und Meldungen: nur Zaehler, nie Text oder Namen.
"""
from __future__ import annotations

import server
from mitschrift_bereinigen import bereinigen

MIN_PRAEFIX = 8
_ENTWURF_GESPERRT = ("sent", "approved", "failed")
_AUSWERTUNG_ABGESCHLOSSEN = ("fertig", "fehler", "leer")
ENTWURF_WARNUNG = "Entwurf offen – stammt aus alter Auswertung"


class NeuAuswertenFehler(Exception):
    """Abbruch mit lesbarer Meldung (ohne Inhalte)."""


def _anteile(segmente: list[dict]) -> tuple[float, float]:
    """(Anteil Sprecher '?' oder leer, Anteil Segmente mit hoechstens 2 Woertern)."""
    n = len(segmente)
    if not n:
        return 0.0, 0.0
    fragezeichen = sum(1 for s in segmente if str(s.get("sprecher") or "").strip() in ("", "?"))
    kurz = sum(1 for s in segmente if len(str(s.get("text") or "").split()) <= 2)
    return round(fragezeichen / n, 3), round(kurz / n, 3)


def neu_auswerten(uid_eingabe: str, *, betreiber: str | None = None) -> dict:
    eingabe = (uid_eingabe or "").strip()
    if not eingabe:
        raise NeuAuswertenFehler("keine uid angegeben")
    with server.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, uid, segmente, entwurf_id, auswertung_status "
                        "from termin_mitschriften where uid = %s for update", (eingabe,))
            zeilen = cur.fetchall()
            if not zeilen:
                if len(eingabe) < MIN_PRAEFIX:
                    raise NeuAuswertenFehler(
                        f"uid zu kurz: ein Praefix braucht mindestens {MIN_PRAEFIX} Zeichen")
                cur.execute("select id, uid, segmente, entwurf_id, auswertung_status "
                            "from termin_mitschriften where starts_with(uid, %s) for update",
                            (eingabe,))
                zeilen = cur.fetchall()
            if not zeilen:
                raise NeuAuswertenFehler("keine Mitschrift zu dieser uid")
            if len(zeilen) > 1:
                raise NeuAuswertenFehler(
                    f"uid-Praefix nicht eindeutig ({len(zeilen)} Treffer): volle uid angeben")
            z = zeilen[0]
            if z["auswertung_status"] not in _AUSWERTUNG_ABGESCHLOSSEN:
                raise NeuAuswertenFehler(
                    "Auswertung steht noch aus: erst nach dem Taktgeber neu auswerten")
            entwurf_offen = False
            if z["entwurf_id"] is not None:
                cur.execute("select status from drafts where id = %s", (z["entwurf_id"],))
                d = cur.fetchall()
                if not d:
                    raise NeuAuswertenFehler(
                        "verknuepfter Entwurf nicht auffindbar: Stand unklar, Abbruch")
                if d[0]["status"] in _ENTWURF_GESPERRT:
                    raise NeuAuswertenFehler(
                        "Entwurf ist schon verschickt (oder freigegeben/versucht): "
                        "keine Neu-Auswertung")
                entwurf_offen = d[0]["status"] == "pending"
            vorher = list(z["segmente"] or [])
            nachher = bereinigen(vorher, betreiber)
            cur.execute("update termin_mitschriften set segmente = %s::jsonb, "
                        "auswertung_status = %s, auswertung_versuche = 0, "
                        "auswertung_json = null, auswertung_md = null, auswertung_am = null "
                        "where id = %s",
                        (server._json(nachher), "offen" if nachher else "leer", z["id"]))
            cur.execute("delete from termin_vorschlaege where mitschrift_id = %s "
                        "and status = 'offen'", (z["id"],))
            vorschlaege_geloescht = cur.rowcount
    fv, kv = _anteile(vorher)
    fn, kn = _anteile(nachher)
    return {"segmente_vorher": len(vorher), "segmente_nachher": len(nachher),
            "fragezeichen_vorher": fv, "fragezeichen_nachher": fn,
            "kurz_vorher": kv, "kurz_nachher": kn,
            "vorschlaege_geloescht": vorschlaege_geloescht, "entwurf_offen": entwurf_offen}
