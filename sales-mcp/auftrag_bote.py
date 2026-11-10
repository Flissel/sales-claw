"""Der Auftrag-Bote (M8 Stufe A): macht aus fertigen Marketing-Reels Kanal-Entwuerfe und schliesst Auftraege ab.

Stufe A: nur VibeMind-Laden (Schema sales; sales_test fuer die Suite). Weitere Laeden haben noch keine
Rechte auf das Auftragsbuch; dort wartet der Bote, ohne einen Durchgang zu machen.

Je Durchgang (Takt 60 s):
1. Auftraege nach Fristende auf `abgelaufen` (auftrag.ablaufen).
2. Eigene Auftraege im Stand `erzeugt`: je Ziel-Kanal (eingabe.kanaele geschnitten mit reel_teilen.ziele) ein
   Entwurf ueber dieselben Werkzeuge wie "Auf Kanaelen teilen" der Reels-Seite, mit drafts.auftrag = Auftrag.
   Danach `wartet_freigabe`. Veroeffentlicht wird nichts: die Entwuerfe warten in /freigaben auf den Betreiber.
   Ein Kanal, der den Entwurf nicht annimmt (oder nicht mehr verbunden ist), steht einmal mit kurzem Satz in
   ergebnis.kanal_fehler; nimmt kein Kanal an, wird der Auftrag `fehler`.
3. Eigene Auftraege in `wartet_freigabe`: sind alle Entwuerfe gesendet oder verworfen, `fertig` (mit den
   Beitrags-Links) bzw. `abgebrochen`. Ein gescheiterter Versand (failed, oder "in Zustellung" seit ueber
   30 Minuten) steht einmal in ergebnis.kanal_fehler; nach 48 h wird einmal erinnert.

ergebnis.kanal_fehler = {kanal: kurzer Satz fuer den Betreiber}, je Kanal hoechstens ein Eintrag (Task 7 meldet ihn).

Hoechstens ein Entwurf je Auftrag und Kanal, auch ueber Neustarts:
- ein Kanal mit einem Entwurf dieses Auftrags wird uebersprungen;
- ein Entwurf ohne Auftrag mit derselben Reel-Datei auf demselben Kanal wird uebernommen statt neu angelegt. Das ist
  der Entwurf eines Durchgangs, der vor dem Zuordnen abbrach - oder einer, den der Betreiber auf der Reels-Seite
  selbst angelegt hat. Ist der schon gesendet (oder verworfen), schliesst er den Auftrag fuer diesen Kanal ab:
  dieselbe Datei ein zweites Mal zu posten waere ein Doppel;
- der eindeutige Index drafts_auftrag_kanal_uidx (db/provision.sql) sichert das in der Datenbank. Verliert ein
  frisch angelegter Entwurf dort gegen einen anderen, nimmt der Bote ihn sofort zurueck (rejected).
Vor dem ersten Entwurf dieselbe Eigentumspruefung wie auf der Reels-Seite (reel_teilen.fertige_reels ueber die
Marketing-API). Kein Sprachmodell.
"""
import json
import logging
import os
import re
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone

import psycopg

import auftrag_buch
from auftrag_buch import VERSAND_UNGEWISS
import freigabe_eingang as fe
import kanaele
import medien
import reel_teilen
import server

LOG = logging.getLogger("auftrag-bote")

TAKT_S = 60
ERINNERN_NACH = timedelta(hours=48)
ZUSTELLUNG_HAENGT_NACH = timedelta(minutes=30)
EINSTELLUNG_HERZSCHLAG = "auftrag_bote_herzschlag"
ERLAUBTE_SCHEMAS = ("sales", "sales_test")
_STOPP = threading.Event()

# Saetze fuer den Betreiber (ergebnis.kanal_fehler, auftrag.fehler): kurz, ohne Werkzeug-Begriffe.
VERSAND_FEHLGESCHLAGEN = "Der Versand ist fehlgeschlagen."
VERSAND_HAENGT = "Der Versand hängt seit über 30 Minuten."
NICHT_VERBUNDEN = "Der Kanal ist nicht verbunden."
UNBEKANNT_ABGELEHNT = "Kanal hat den Entwurf abgelehnt"
# Bekannte Ablehnungen der Werkzeuge (kanal_post_entwurf, post_entwurf_erstellen, medien.pruefe_anhang,
# kanaele.pruefe_entwurf) -> Satz. Erster Treffer gewinnt; der Werkzeugtext selbst wird nie gespeichert.
_ABLEHNUNGEN = (
    (("schon einen Beitrag",), "Zu diesem Thema gibt es dort schon einen Beitrag."),
    (("nicht verbunden",), NICHT_VERBUNDEN),
    (("fuer den Bot gesperrt",), "Die Reel-Datei ist in den Medien für den Bot gesperrt."),
    (("Sammelkontakt", "LINKEDIN_POST_LEAD_ID"), "Der Sammelkontakt für Beiträge fehlt."),
    (("Datenbank",), "Die Datenbank war nicht erreichbar."),
    (("Medienordner", "lesbar", "(0 Bytes)", "MB gross", "Endung", "Dateiname", "passt nicht zu einem Beitrag",
      "zu groß"), "Die Reel-Datei ließ sich nicht anhängen."),
    (("Zeichen", "Titel", "Pflicht", "nicht möglich", "höchstens"),
     "Text oder Titel passen nicht in die Grenzen des Kanals."),
)
_CLAIM_SEIT = re.compile(r"seit (\S+)")


def _laden() -> str:
    return os.environ.get("LADEN_PRAEFIX", "").strip() or "sales"


def _zeit(wert) -> datetime | None:
    try:
        z = datetime.fromisoformat(str(wert))
    except (TypeError, ValueError):
        return None
    return z if z.tzinfo else z.replace(tzinfo=timezone.utc)


def ablehnung_satz(grund: str) -> str:
    """Werkzeugtext -> kurzer Satz fuer den Betreiber (hoechstens 120 Zeichen)."""
    for muster, satz in _ABLEHNUNGEN:
        if any(m in grund for m in muster):
            return satz
    return UNBEKANNT_ABGELEHNT


def _anzeige(kanal: str) -> str:
    info = kanaele.KANAELE.get(kanal)
    return info.anzeige if info else reel_teilen.LINKEDIN.anzeige if kanal == "linkedin" else kanal


def _kanal_fehler(ergebnis: dict) -> dict:
    alt = ergebnis.get("kanal_fehler")
    return dict(alt) if isinstance(alt, dict) else {}


def _entwuerfe(q, aid: str) -> list[dict]:
    return q("select id, channel, status, error from drafts where auftrag = %s order by created_at", (aid,))


def _verwaist(q, kanal: str, datei: str):
    """Entwurf ohne Auftrag mit derselben Reel-Datei auf diesem Kanal (siehe Moduldoku)."""
    z = q("select id from drafts where auftrag is null and channel = %s and recipient = 'eigenes-profil' "
          "and media_ref = %s order by created_at limit 1", (kanal, datei))
    return str(z[0]["id"]) if z else None


def _zuordnen(q, aid: str, draft_id: str) -> bool:
    """drafts.auftrag setzen; False, wenn der Entwurf schon einen Auftrag hat oder der Kanal dieses Auftrags
    schon einen Entwurf hat (eindeutiger Index)."""
    try:
        return bool(q("update drafts set auftrag = %s where id = %s and auftrag is null returning id",
                      (aid, draft_id)))
    except psycopg.errors.UniqueViolation:
        return False


def _eigenes_reel(a: dict, datei: str) -> str | None:
    """Wie nicht_eigenes_reel auf der Reels-Seite: None, wenn `datei` ein fertiges Reel der Firma dieses
    Ladens ist (laut Marketing-API, reel_teilen.fertige_reels), sonst der Grund. Ist die Marketing-API
    nicht erreichbar, wirft das PultFehler: der Auftrag bleibt `erzeugt` und der naechste Durchgang prueft neu."""
    firma = os.environ.get("MARKETING_MANDANT", "").strip()
    if not firma or a.get("mandant") != firma:
        return "Das Reel gehört nicht zur Firma dieses Ladens."
    if not (medien.reeldatei(datei) and datei.endswith(".mp4")):
        return "Das Ergebnis nennt keine gültige Reel-Datei."
    if datei not in reel_teilen.fertige_reels(firma):
        return "Das Reel gehört nicht zur Firma dieses Ladens."
    return None


def _anlegen(info, thema: str, ergebnis: dict, datei: str) -> tuple[str | None, str]:
    """(draft_id, "") oder (None, Satz fuer den Betreiber). LinkedIn geht wie auf der Reels-Seite ueber
    post_entwurf_erstellen."""
    titel, text = reel_teilen.fassung(info, thema, ergebnis)
    if info.name == reel_teilen.LINKEDIN.name:
        roh = server.post_entwurf_erstellen(thema, text, datei)
    else:
        roh = server.kanal_post_entwurf(info.name, thema, text, titel=titel, medien_dateien=datei)
    antwort = json.loads(roh)
    if isinstance(antwort, dict) and antwort.get("draft_id"):
        return str(antwort["draft_id"]), ""
    grund = antwort.get("fehler") if isinstance(antwort, dict) else None
    return None, ablehnung_satz(str(grund or ""))


def _zuruecknehmen(q, aid: str, draft_id: str, kanal: str) -> None:
    """Ein frisch angelegter Entwurf, der sich nicht zuordnen liess, waere ein Doppel ohne Auftrag in /freigaben."""
    q("update drafts set status = 'rejected' where id = %s and auftrag is null and status = 'pending' returning id",
      (draft_id,))
    LOG.warning("Auftrag %s: Doppel-Entwurf auf %s zurueckgenommen", aid[:8], kanal)


def _erzeugt(q, a: dict, zaehler: dict) -> None:
    aid = str(a["id"])
    eingabe = a.get("eingabe") if isinstance(a.get("eingabe"), dict) else {}
    ergebnis = a.get("ergebnis") if isinstance(a.get("ergebnis"), dict) else {}
    datei = str(ergebnis.get("datei") or "")
    abgelehnt_reel = _eigenes_reel(a, datei)
    if abgelehnt_reel:
        auftrag_buch.stand_setzen(q, aid, "erzeugt", "fehler", abgelehnt_reel)
        return
    thema = str(ergebnis.get("titel") or eingabe.get("thema") or "").strip()
    nur = eingabe.get("kanaele")
    nur = [str(k) for k in nur] if isinstance(nur, list) else None
    vorhanden = {z["channel"]: str(z["id"]) for z in _entwuerfe(q, aid)}
    ziele = reel_teilen.ziele(q, nur)
    abgelehnt: dict[str, str] = {}                       # kanal -> Satz
    for kanal in nur or []:
        if kanal not in vorhanden and kanal not in {i.name for i in ziele}:
            abgelehnt[kanal] = NICHT_VERBUNDEN
    for info in ziele:
        if info.name in vorhanden:                       # Idempotenz: schon ein Entwurf dieses Auftrags
            continue
        alt = _verwaist(q, info.name, datei)
        if alt and _zuordnen(q, aid, alt):
            vorhanden[info.name] = alt
            continue
        draft_id, satz = _anlegen(info, thema, ergebnis, datei)
        if draft_id is None:
            abgelehnt[info.name] = satz
            continue
        if not _zuordnen(q, aid, draft_id):
            _zuruecknehmen(q, aid, draft_id, info.name)
            vorhanden.update({z["channel"]: str(z["id"]) for z in _entwuerfe(q, aid)})
            continue
        vorhanden[info.name] = draft_id
        zaehler["entwuerfe"] += 1
    for kanal in abgelehnt:                              # nur der Kanalname ins Log, nie ein Text
        LOG.warning("Auftrag %s: kein Entwurf auf %s", aid[:8], kanal)
    if not vorhanden:
        grund = "; ".join(f"{_anzeige(k)}: {s}" for k, s in abgelehnt.items()) or "kein verbundener Kanal nimmt Videos"
        auftrag_buch.stand_setzen(q, aid, "erzeugt", "fehler", f"Kein Kanal nahm den Entwurf an: {grund}")
        return
    teil: dict = {"entwuerfe": vorhanden}
    bisher = _kanal_fehler(ergebnis)
    neu = {k: s for k, s in abgelehnt.items() if k not in bisher and k not in vorhanden}
    if neu:
        teil["kanal_fehler"] = {**bisher, **neu}
    auftrag_buch.ergebnis_mischen(q, aid, teil)
    auftrag_buch.stand_setzen(q, aid, "erzeugt", "wartet_freigabe")


def _beitrag_link(wert: str) -> str:
    """LinkedIn liefert eine URN (urn:li:share:... / urn:li:ugcPost:...): daraus den Link auf den Beitrag bauen."""
    if re.match(r"^urn:li:(share|ugcPost):\S+$", wert):
        return f"https://www.linkedin.com/feed/update/{wert}"
    return wert


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
            beleg.setdefault(str(b["draft_id"]), _beitrag_link(str(wert)))
    return {z["channel"]: "privat" if z["channel"] == "youtube" else beleg.get(str(z["id"]), "gesendet")
            for z in gesendet}


def _wartet_seit(a: dict) -> datetime | None:
    for eintrag in reversed(a.get("verlauf") or []):
        if isinstance(eintrag, dict) and eintrag.get("stand") == "wartet_freigabe":
            return _zeit(eintrag.get("zeit"))
    return _zeit(a.get("geaendert"))


def _versand_fehler(z: dict, jetzt: datetime) -> str | None:
    """Satz fuer einen gescheiterten Versand, sonst None. Die Claim-Marke "in Zustellung seit <Zeit> ..." ist
    ein laufender Versand - erst wenn sie aelter als 30 Minuten ist, haengt er."""
    if z["status"] != "failed":
        return None
    fehler = str(z["error"] or "")
    if fehler.startswith("UNGEWISS:"):
        return VERSAND_UNGEWISS
    if not fehler.startswith(server._CLAIM_MARKE_PRAEFIX):
        return VERSAND_FEHLGESCHLAGEN
    m = _CLAIM_SEIT.search(fehler)
    seit = _zeit(m.group(1)) if m else None
    return VERSAND_HAENGT if seit is not None and jetzt - seit > ZUSTELLUNG_HAENGT_NACH else None


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
    # failed ist erst mit rejected zu Ende: der Auftrag bleibt offen, der Kanal wird einmal vermerkt.
    bisher = _kanal_fehler(ergebnis)
    neu = {}
    for z in offen:
        satz = _versand_fehler(z, jetzt)
        if satz and z["channel"] not in bisher:
            neu[z["channel"]] = satz
    if neu:
        auftrag_buch.ergebnis_mischen(q, aid, {"kanal_fehler": {**bisher, **neu}})
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
    signal.signal(signal.SIGTERM, _stopp_anfordern)
    signal.signal(signal.SIGINT, _stopp_anfordern)
    if server.SCHEMA not in ERLAUBTE_SCHEMAS:
        # Kein Exit: mit restart: unless-stopped wuerde daraus eine Neustartschleife. Einmal sagen, dann warten.
        LOG.error("Schema %s wird nicht bedient (Stufe A: nur sales oder sales_test) - der Bote wartet ohne "
                  "Durchgang.", server.SCHEMA)
        _STOPP.wait()
        return 0
    LOG.info("Start: schema=%s laden=%s takt=%ds", server.SCHEMA, _laden(), TAKT_S)
    while not _STOPP.is_set():
        durchgang(server._q)
        _STOPP.wait(TAKT_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
