"""Der Auftrag-Bote (M8 Stufe A): macht aus fertigen Marketing-Reels Kanal-Entwuerfe und schliesst Auftraege ab.

Je Durchgang (Takt 60 s):
1. Auftraege nach Fristende auf `abgelaufen` (auftrag.ablaufen).
2. Eigene Auftraege im Stand `erzeugt`: je Ziel-Kanal (eingabe.kanaele geschnitten mit reel_teilen.ziele) ein
   Entwurf ueber dieselben Werkzeuge wie "Auf Kanaelen teilen" der Reels-Seite, mit drafts.auftrag = Auftrag.
   Danach `wartet_freigabe`. Veroeffentlicht wird nichts: die Entwuerfe warten in /freigaben auf den Betreiber.
3. Eigene Auftraege in `wartet_freigabe`: sind alle Entwuerfe gesendet oder verworfen, `fertig` (mit den
   Beitrags-Links) bzw. `abgebrochen`. Ein gescheiterter Kanal wird einmal vermerkt, nach 48 h wird einmal erinnert.

Hoechstens ein Entwurf je Auftrag und Kanal, auch ueber Neustarts: ein Kanal mit einem Entwurf dieses Auftrags
wird uebersprungen, und ein Entwurf, den ein frueherer Durchgang angelegt, aber vor dem Zuordnen verloren hat
(gleiche Reel-Datei, gleicher Kanal, noch ohne Auftrag), wird uebernommen statt neu angelegt. Dazu sichert der
eindeutige Index drafts_auftrag_kanal_uidx (db/provision.sql). Kein Sprachmodell, kein Netz ausser der Datenbank.
"""
import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone

import auftrag_buch
import freigabe_eingang as fe
import medien
import reel_teilen
import server

LOG = logging.getLogger("auftrag-bote")

TAKT_S = 60
ERINNERN_NACH = timedelta(hours=48)
EINSTELLUNG_HERZSCHLAG = "auftrag_bote_herzschlag"
ERLAUBTE_SCHEMAS = ("sales", "sales_test")
GRUND_MAX = 120
_STOPP = threading.Event()


def _laden() -> str:
    return os.environ.get("LADEN_PRAEFIX", "").strip() or "sales"


def _zeit(wert) -> datetime | None:
    try:
        z = datetime.fromisoformat(str(wert))
    except (TypeError, ValueError):
        return None
    return z if z.tzinfo else z.replace(tzinfo=timezone.utc)


def _entwuerfe(q, aid: str) -> list[dict]:
    return q("select id, channel, status, error from drafts where auftrag = %s order by created_at", (aid,))


def _verwaist(q, kanal: str, datei: str):
    """Entwurf eines frueheren Durchgangs, der vor dem Zuordnen abbrach (Neustart)."""
    z = q("select id from drafts where auftrag is null and channel = %s and recipient = 'eigenes-profil' "
          "and media_ref = %s and status <> 'rejected' order by created_at limit 1", (kanal, datei))
    return str(z[0]["id"]) if z else None


def _zuordnen(q, aid: str, draft_id: str) -> bool:
    return bool(q("update drafts set auftrag = %s where id = %s and auftrag is null returning id",
                  (aid, draft_id)))


def _eigenes_reel(a: dict, datei: str) -> str | None:
    """Wie nicht_eigenes_reel auf der Reels-Seite: None, wenn das Reel der Firma dieses Ladens gehoert."""
    firma = os.environ.get("MARKETING_MANDANT", "").strip()
    if not firma or a.get("mandant") != firma:
        return "Das Reel gehört nicht zur Firma dieses Ladens."
    if not (medien.reeldatei(datei) and datei.endswith(".mp4")):
        return "Das Ergebnis nennt keine gültige Reel-Datei."
    return None


def _anlegen(info, thema: str, ergebnis: dict, datei: str) -> tuple[str | None, str]:
    """(draft_id, "") oder (None, Grund). LinkedIn geht wie auf der Reels-Seite ueber post_entwurf_erstellen."""
    titel, text = reel_teilen.fassung(info, thema, ergebnis)
    if info.name == reel_teilen.LINKEDIN.name:
        roh = server.post_entwurf_erstellen(thema, text, datei)
    else:
        roh = server.kanal_post_entwurf(info.name, thema, text, titel=titel, medien_dateien=datei)
    antwort = json.loads(roh)
    if isinstance(antwort, dict) and antwort.get("draft_id"):
        return str(antwort["draft_id"]), ""
    grund = antwort.get("fehler") if isinstance(antwort, dict) else None
    return None, str(grund or "unerwartete Antwort")[:GRUND_MAX]


def _erzeugt(q, a: dict, zaehler: dict) -> None:
    aid = str(a["id"])
    eingabe = a.get("eingabe") if isinstance(a.get("eingabe"), dict) else {}
    ergebnis = a.get("ergebnis") if isinstance(a.get("ergebnis"), dict) else {}
    datei = str(ergebnis.get("datei") or "")
    abgelehnt = _eigenes_reel(a, datei)
    if abgelehnt:
        auftrag_buch.stand_setzen(q, aid, "erzeugt", "fehler", abgelehnt)
        return
    thema = str(ergebnis.get("titel") or eingabe.get("thema") or "").strip()
    nur = eingabe.get("kanaele")
    nur = [str(k) for k in nur] if isinstance(nur, list) else None
    vorhanden = {z["channel"]: str(z["id"]) for z in _entwuerfe(q, aid)}
    gruende = []
    for info in reel_teilen.ziele(q, nur):
        if info.name in vorhanden:                       # Idempotenz: schon ein Entwurf dieses Auftrags
            continue
        alt = _verwaist(q, info.name, datei)
        if alt and _zuordnen(q, aid, alt):
            vorhanden[info.name] = alt
            continue
        draft_id, grund = _anlegen(info, thema, ergebnis, datei)
        if draft_id is None:
            gruende.append(f"{info.anzeige}: {grund}")
            continue
        _zuordnen(q, aid, draft_id)
        vorhanden[info.name] = draft_id
        zaehler["entwuerfe"] += 1
    if not vorhanden:
        grund = "; ".join(gruende) or "kein verbundener Kanal nimmt Videos"
        auftrag_buch.stand_setzen(q, aid, "erzeugt", "fehler", f"Kein Kanal nahm den Entwurf an: {grund}")
        return
    auftrag_buch.ergebnis_mischen(q, aid, {"entwuerfe": vorhanden})
    auftrag_buch.stand_setzen(q, aid, "erzeugt", "wartet_freigabe")


def _beitraege(q, gesendet: list[dict]) -> dict[str, str]:
    """Je gesendetem Kanal der Link: URL aus dem Versand-Beleg, sonst die Beitrags-Kennung (LinkedIn);
    YouTube laedt privat hoch und steht deshalb als "privat"."""
    belege = q("select payload->>'draft_id' as draft_id, payload->>'url' as url, "
               "payload->>'beitrag' as beitrag from activities where type = 'versand' "
               "and payload->>'draft_id' = any(%s) order by created_at",
               ([str(z["id"]) for z in gesendet],))
    beleg: dict[str, str] = {}
    for b in belege:
        wert = b["url"] or b["beitrag"]
        if wert:
            beleg.setdefault(str(b["draft_id"]), str(wert))
    return {z["channel"]: "privat" if z["channel"] == "youtube" else beleg.get(str(z["id"]), "gesendet")
            for z in gesendet}


def _wartet_seit(a: dict) -> datetime | None:
    for eintrag in reversed(a.get("verlauf") or []):
        if isinstance(eintrag, dict) and eintrag.get("stand") == "wartet_freigabe":
            return _zeit(eintrag.get("zeit"))
    return _zeit(a.get("geaendert"))


def _wartet(q, a: dict, jetzt: datetime, zaehler: dict) -> None:
    aid = str(a["id"])
    ergebnis = a.get("ergebnis") if isinstance(a.get("ergebnis"), dict) else {}
    entwuerfe = _entwuerfe(q, aid)
    offen = [z for z in entwuerfe if z["status"] not in ("sent", "rejected")]
    if not offen:
        gesendet = [z for z in entwuerfe if z["status"] == "sent"]
        if gesendet:
            auftrag_buch.ergebnis_mischen(q, aid, {"beitraege": _beitraege(q, gesendet)})
            fertig = auftrag_buch.stand_setzen(q, aid, "wartet_freigabe", "fertig")
        else:
            fertig = auftrag_buch.stand_setzen(q, aid, "wartet_freigabe", "abgebrochen")
        zaehler["abgeschlossen"] += 1 if fertig else 0
        return
    # failed ist erst mit rejected zu Ende; die Claim-Marke "in Zustellung seit ..." ist kein Fehler.
    gescheitert = [z["channel"] for z in offen if z["status"] == "failed"
                   and not str(z["error"] or "").startswith(server._CLAIM_MARKE_PRAEFIX)]
    alt = ergebnis.get("kanal_fehler") if isinstance(ergebnis.get("kanal_fehler"), dict) else {}
    neu = [k for k in gescheitert if k not in alt]
    if neu:
        auftrag_buch.ergebnis_mischen(q, aid, {"kanal_fehler": {**alt, **{k: "fehlgeschlagen" for k in neu}}})
    seit = _wartet_seit(a)
    if not a.get("erinnert_am") and seit is not None and jetzt - seit > ERINNERN_NACH:
        if auftrag_buch.erinnert(q, aid):
            zaehler["erinnert"] += 1


def _herzschlag(erfolg: bool, fehler: str | None, jetzt: datetime) -> None:
    """Der Herzschlag darf den Durchgang nie stoppen."""
    try:
        fe.herzschlag_schreiben(erfolg, fehler, jetzt, schluessel=EINSTELLUNG_HERZSCHLAG)
    except Exception as e:  # noqa: BLE001
        LOG.error("Herzschlag nicht geschrieben: %s", type(e).__name__)


def _einzeln(schritt, a: dict) -> str | None:
    """Ein kaputter Auftrag haelt die anderen nicht auf; nur der Typ ins Log, nie der Text."""
    try:
        schritt()
    except Exception as e:  # noqa: BLE001
        LOG.error("Auftrag %s: %s", str(a.get("id"))[:8], type(e).__name__)
        return f"Auftrag.{type(e).__name__}"
    return None


def durchgang(q, jetzt: datetime | None = None) -> dict:
    jetzt = jetzt or datetime.now(timezone.utc)
    zaehler = {"abgelaufen": 0, "entwuerfe": 0, "abgeschlossen": 0, "erinnert": 0}
    fehler = None
    try:
        zaehler["abgelaufen"] = auftrag_buch.ablaufen(q)
        laden = _laden()
        for a in auftrag_buch.eigene(q, laden, ["erzeugt"]):
            if a.get("art") == "reel":
                fehler = _einzeln(lambda: _erzeugt(q, a, zaehler), a) or fehler
        for a in auftrag_buch.eigene(q, laden, ["wartet_freigabe"]):
            if a.get("art") == "reel":
                fehler = _einzeln(lambda: _wartet(q, a, jetzt, zaehler), a) or fehler
    except Exception as e:  # noqa: BLE001
        LOG.error("Durchgang abgebrochen: %s", type(e).__name__)
        fehler = type(e).__name__
    _herzschlag(fehler is None, fehler, jetzt)
    LOG.info("Durchgang: %d abgelaufen, %d Entwuerfe, %d abgeschlossen, %d erinnert",
             zaehler["abgelaufen"], zaehler["entwuerfe"], zaehler["abgeschlossen"], zaehler["erinnert"])
    return zaehler


def _stopp_anfordern(signum, _rahmen) -> None:
    LOG.info("%s empfangen - nach diesem Durchgang ist Schluss.", signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def main() -> int:
    _logging_einrichten()
    if server.SCHEMA not in ERLAUBTE_SCHEMAS:
        LOG.error("Schema %s ist nicht erlaubt (nur sales oder sales_test) - kein Start.", server.SCHEMA)
        return 2
    signal.signal(signal.SIGTERM, _stopp_anfordern)
    signal.signal(signal.SIGINT, _stopp_anfordern)
    LOG.info("Start: schema=%s laden=%s takt=%ds", server.SCHEMA, _laden(), TAKT_S)
    while not _STOPP.is_set():
        durchgang(server._q)
        _STOPP.wait(TAKT_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
