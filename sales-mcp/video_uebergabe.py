"""Vorbereitete Video-Uebergaben aus Rowboat (Konzept-Flaeche, Spec 14).

`POST /api/auftraege/video` legt nur eine Zeile in `video_uebergabe` an (Status `offen`). Der Auftrag
entsteht erst, wenn der Betreiber auf der Werkbank-Seite "Ja, uebergeben" drueckt (`bestaetigen`); "Nein"
verwirft (`verwerfen`). Tabelle und Rechte: db/video-uebergabe.sql, je Laden-Schema.

Ablauf des Ja in EINER Transaktion: `server.pool.connection()` erreicht mit derselben Verbindung das Schema
des Ladens und das Schema `auftrag` (alle auftrag.*-Aufrufe sind voll qualifiziert). Anspruch (Update auf
`wird_uebergeben`), Pruefung, `auftrag.sales_anlegen` (in einem Sicherungspunkt, damit eine Ablehnung die
Transaktion nicht abbricht) und der Statuswechsel auf `bestaetigt` werden gemeinsam bestaetigt oder gemeinsam
zurueckgenommen. Der Anspruch haelt die Zeilensperre bis zum Ende: ein zweiter Klick wartet und findet danach
keine offene Zeile mehr. Ein haengender Anspruch kann deshalb nicht entstehen; `wird_uebergeben` ist nie
ausserhalb der Transaktion sichtbar.

Nichts vom Inhalt des Konzepts gelangt ins Log: nur Kennung (8 Zeichen), Status und Hash-Anfang.
"""
from __future__ import annotations

import json
import logging
import os
import re

import psycopg

import auftrag_buch
import server
import video_konzept
from konzept_lesen import js_trim

LOG = logging.getLogger("sales-ui")

OFFEN_MAX = 5
VERFALL = "interval '24 hours'"          # feste SQL-Konstante, kein Eingabewert

SATZ_DOPPELT = "Dieses Konzept ist schon zur Übergabe vorbereitet."
SATZ_VOLL = "Es sind schon 5 Übergaben offen. Bitte erst in Sales entscheiden."
SATZ_ABGELAUFEN = "Diese Übergabe ist abgelaufen."
SATZ_ENTSCHIEDEN = "Diese Übergabe ist schon entschieden."
SATZ_FEHLT = "Diese Übergabe gibt es nicht."
SATZ_KEINE_FIRMA = "Für diesen Laden ist keine Marketing-Firma eingetragen."
SATZ_FIRMA = "Das Konzept gehört zu einer anderen Firma als dieser Laden."
SATZ_KEIN_AUFTRAGSBUCH = "Aufträge gibt es in diesem Laden noch nicht."     # derselbe Satz wie bei der Annahme
SATZ_NICHT_EINGERICHTET = "Die Übergabe ist auf diesem Laden noch nicht eingerichtet."
SATZ_NICHT_LESBAR = "Die Übergaben sind gerade nicht lesbar."
SATZ_UNKLAR = "Ob der Auftrag angelegt wurde, ist unklar. Bitte die Werkbank-Liste prüfen."
# Fehlt die Tabelle (oder die Funktion/das Recht im Auftragsbuch), ist die Uebergabe auf diesem Laden nicht
# eingerichtet: das ist ein Ausfall, keine Ablehnung.
NICHT_EINGERICHTET = (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedFunction,
                      psycopg.errors.InsufficientPrivilege, psycopg.errors.InvalidSchemaName)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _log(status: str, kennung, sha: str) -> None:
    LOG.info("video-uebergabe status=%s id=%s hash=%s", status, str(kennung)[:8], str(sha)[:8])


def anlegen(konzept: dict, sha: str) -> tuple[str, str | None]:
    """-> (Vorgang = 8 Hex der id, None) oder ("", Fehlersatz). Zaehlen, Doppelpruefung und Einfuegen laufen
    unter einer Beratungssperre je Schema: zwei gleichzeitige Anlagen ergeben hoechstens OFFEN_MAX offene."""
    try:
        with server.pool.connection() as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", ("video_uebergabe:" + server.SCHEMA,))
            conn.execute("update video_uebergabe set status = 'abgelaufen', entschieden_am = now() "
                         f"where status = 'offen' and erstellt_am <= now() - {VERFALL}")
            if conn.execute("select 1 as x from video_uebergabe where konzept_sha = %s "
                            "and status in ('offen','wird_uebergeben')", (sha,)).fetchone():
                return "", SATZ_DOPPELT
            n = conn.execute("select count(*) as n from video_uebergabe "
                             "where status in ('offen','wird_uebergeben')").fetchone()["n"]
            if n >= OFFEN_MAX:
                return "", SATZ_VOLL
            z = conn.execute("insert into video_uebergabe (konzept, konzept_sha) values (%s::jsonb, %s) "
                             "returning id", (json.dumps(konzept, ensure_ascii=False), sha)).fetchone()
    except psycopg.errors.UniqueViolation:           # Rueckhalt: der Teil-Unique-Index auf konzept_sha
        return "", SATZ_DOPPELT
    _log("vorbereitet", z["id"], sha)
    return str(z["id"])[:8], None


def offene() -> list[dict]:
    """Offene, nicht abgelaufene Uebergaben, aelteste zuerst. `alter_s`: Alter in Sekunden nach der DB-Uhr."""
    return server._q("select u.id, u.konzept, u.konzept_sha, u.fehler, u.erstellt_am, "
                     "extract(epoch from (now() - u.erstellt_am))::int as alter_s, "
                     # schon einmal bestaetigt? (Auftragsnummer der juengsten Bestaetigung mit demselben Hash)
                     "(select b.auftrag_id from video_uebergabe b where b.konzept_sha = u.konzept_sha "
                     "and b.status = 'bestaetigt' order by b.entschieden_am desc limit 1) as frueher_auftrag "
                     "from video_uebergabe u where u.status = 'offen' "
                     f"and u.erstellt_am > now() - {VERFALL} order by u.erstellt_am")


def zustand(kennung) -> dict | None:
    """Status, Auftrag und letzter Ablehnungssatz EINER Uebergabe (ohne das Konzept) - die Ergebniszeile der Seite
    leitet sich daraus ab, nicht aus Werten im Link. None: unbekannt."""
    if not _gueltig(kennung):
        return None
    z = server._q("select status, auftrag_id, fehler from video_uebergabe where id = %s", (kennung,))
    return z[0] if z else None


def _gueltig(kennung) -> bool:
    return isinstance(kennung, str) and bool(_UUID.fullmatch(kennung))


def warum_nicht(kennung, conn=None) -> tuple[str, str]:
    """Warum sich eine Uebergabe nicht entscheiden laesst: ("fehlt"|"abgelaufen"|"entschieden", Satz)."""
    if not _gueltig(kennung):
        return "fehlt", SATZ_FEHLT
    if conn is None:
        with server.pool.connection() as eigene:
            return warum_nicht(kennung, eigene)
    z = conn.execute("select status from video_uebergabe where id = %s", (kennung,)).fetchone()
    if z is None:
        return "fehlt", SATZ_FEHLT
    if z["status"] == "offen":           # offen, aber zu alt: jetzt als abgelaufen eintragen
        conn.execute("update video_uebergabe set status = 'abgelaufen', entschieden_am = now() "
                     "where id = %s and status = 'offen'", (kennung,))
        return "abgelaufen", SATZ_ABGELAUFEN
    if z["status"] == "abgelaufen":
        return "abgelaufen", SATZ_ABGELAUFEN
    return "entschieden", SATZ_ENTSCHIEDEN


def verwerfen(kennung, von: str) -> bool:
    if not _gueltig(kennung):
        return False
    z = server._q("update video_uebergabe set status = 'verworfen', entschieden_am = now(), "
                  "entschieden_von = %s where id = %s and status = 'offen' "
                  f"and erstellt_am > now() - {VERFALL} returning id, konzept_sha", (von, kennung))
    if z:
        _log("verworfen", z[0]["id"], z[0]["konzept_sha"])
    return bool(z)


def _bestellung(kennung: str, konzept: dict):
    """Die Angaben des Auftrags aus dem gespeicherten Konzept, mit denselben Pruefungen wie bei der Annahme
    (Laden mit Auftragsbuch, gemeinsamer Pruefer, Firma) -> ((laden, mandant, eingabe), None) oder (None, Fehlersatz)."""
    if server.SCHEMA not in server._AUFTRAG_SCHEMAS:      # wie bei der Annahme; die Zeile bleibt offen, der Satz steht dabei
        return None, SATZ_KEIN_AUFTRAGSBUCH
    satz = video_konzept.pruefen(konzept)                # der gemeinsame Pruefer, dieselben Regeln wie bei der Annahme
    if satz:
        return None, satz
    thema, zielgruppe = js_trim(konzept["thema"]), js_trim(konzept["zielgruppe"])
    beschreibung = video_konzept.beschreibung_aus(konzept)
    mandant = os.environ.get("MARKETING_MANDANT", "").strip()
    if not mandant:
        return None, SATZ_KEINE_FIRMA
    firma = konzept.get("firma")
    if isinstance(firma, str) and js_trim(firma) and js_trim(firma) != mandant:
        return None, SATZ_FIRMA
    laden = os.environ.get("LADEN_PRAEFIX", "").strip() or "sales"
    sha = video_konzept.block_hash(konzept)
    eingabe = {"thema": thema, "beschreibung": beschreibung, "minuten": int(konzept["minuten"]),
               "zielgruppe": zielgruppe, "von": "rowboat", "konzept": konzept, "konzept_sha": sha,
               "uebergabe": kennung}
    return (laden, mandant, eingabe), None


def bestaetigen(kennung, von: str) -> tuple[str, dict | str]:
    """Das Ja. -> ("ok", {"auftrag": 8 Hex, "id": UUID}) | ("abgelehnt", Satz; die Uebergabe bleibt offen,
    der Satz steht in `fehler`) | ("fehlt"|"abgelaufen"|"entschieden", Satz)."""
    if not _gueltig(kennung):
        return "fehlt", SATZ_FEHLT
    with server.pool.connection() as conn:
        stoerung: list[Exception] = []

        def q(sql, params=()):
            try:
                cur = conn.execute(sql, params)
            except psycopg.errors.RaiseException:
                raise                                    # Ablehnung des Auftragsbuchs (RAISE EXCEPTION, P0001)
            except Exception as f:                       # noqa: BLE001 - Stoerung: Rechte, fehlende Funktion, Netz
                stoerung.append(f)
                raise
            return cur.fetchall() if cur.description else []

        # 1. Anspruch: nur eine offene, nicht abgelaufene Uebergabe; die Zeilensperre haelt bis zum Ende.
        z = conn.execute("update video_uebergabe set status = 'wird_uebergeben', entschieden_am = now(), "
                         "entschieden_von = %s where id = %s and status = 'offen' "
                         f"and erstellt_am > now() - {VERFALL} returning id, konzept, konzept_sha",
                         (von, kennung)).fetchone()
        if z is None:
            return warum_nicht(kennung, conn)
        konzept = z["konzept"] if isinstance(z["konzept"], dict) else {}
        # 2. Pruefungen und Auftrag (mit der Tagesgrenze) in diesem Moment; Sicherungspunkt um die Anlage.
        bestellung, satz = _bestellung(kennung, konzept)
        aid = None
        if bestellung is not None:
            try:
                with conn.transaction():
                    aid = auftrag_buch.anlegen(q, *bestellung[:2], "video", bestellung[2])
            except auftrag_buch.AuftragAbgelehnt as e:
                if stoerung:
                    # `auftrag_buch.anlegen` macht aus JEDEM Fehler einen Ablehnungssatz. Eine Stoerung (fehlende
                    # Rechte, fehlende Funktion, Verbindung) ist aber keine Ablehnung: alles zurueck, 503 an die Seite.
                    raise stoerung[0] from None
                satz = e.grund
        if satz is not None:
            conn.execute("update video_uebergabe set status = 'offen', fehler = %s, entschieden_am = null, "
                         "entschieden_von = null where id = %s", (satz, kennung))
            _log("abgelehnt", z["id"], z["konzept_sha"])
            return "abgelehnt", satz
        # 3. Statuswechsel in derselben Transaktion wie die Anlage.
        conn.execute("update video_uebergabe set status = 'bestaetigt', auftrag_id = %s::uuid, fehler = null "
                     "where id = %s", (aid, kennung))
    _log("bestaetigt", kennung, z["konzept_sha"])
    return "ok", {"auftrag": aid[:8], "id": aid}
