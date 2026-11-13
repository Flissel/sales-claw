"""Warteliste von vibemind.space -> Kontakte (Abgleich, seit 13.11.2026).

Die Warteliste der Website liegt in einer fremden Datenbank. Einmal am Tag
holt `deploy/warteliste-abgleich.sh` sie auf dem Wirt ab und reicht das
Dokument auf der Standardeingabe hierher. Dieses Modul gleicht es mit den
Kontakten ab:

  * Adresse noch nicht bekannt  -> neuer Kontakt, Quelle `waitinglist`,
    Notiz beginnt mit "Waitinglist".
  * Adresse schon bekannt       -> der Kontakt bleibt, wie er ist, und
    bekommt nur das Merkmal `enrichment.waitinglist`.
  * nicht mehr auf der Liste    -> der Kontakt bleibt, das Merkmal sagt
    `auf_liste: false`. Geloescht wird hier nie.

EINE RICHTUNG. Nichts geht zurueck an die Website.

KEINE FREIGABE. Ein neuer Kontakt bleibt auf `consent_status = 'unknown'`:
wer sich auf eine Warteliste setzt, hat keiner Werbung zugestimmt. Der
Abgleich ruft deshalb NICHT `kontakt_anlegen` (das bucht seit 30.10.2026
`betreiber_auftrag`), prueft aber dieselbe Verbotsliste: wer dort steht,
wird nicht angelegt.

KEIN SCHLUESSEL HIER. Den Abholschluessel kennt nur der Wirt; der Container
sieht das fertige Dokument, nie den Zugang (docker-compose reicht die .env
nicht durch, siehe dort). Ausgegeben werden nur Zahlen, keine Adressen.

ANLAGEDATUM = ANMELDEDATUM. `created_at` und `updated_at` eines neuen
Kontakts tragen den Tag der Anmeldung. Sonst stuenden nach dem ersten Lauf
einige tausend Wartelisten-Adressen als "zuletzt geaendert" vor der
laufenden Arbeit.

SCHWUND-SPERRE. Fehlt im Dokument ploetzlich ein grosser Teil der bisher
gekennzeichneten Kontakte, traegt der Lauf niemanden aus und endet mit
Exit 4 - ein halb geliefertes Dokument darf die Kennzeichnung nicht
abraeumen.

CLI (Arbeitsverzeichnis /app im Container sales-mcp, Dokument auf stdin):
  python warteliste_abgleich.py abgleichen [--trocken] [--hoechstens N]
    --trocken       rechnet nur, schreibt nichts
    --hoechstens N  legt hoechstens N neue Kontakte an (erster Lauf in Stufen)
  Ausgabe: eine Zeile JSON mit Zahlen.
  Exit 0 ok · 2 Eingabe unbrauchbar (nichts geschrieben) · 4 Schwund-Sperre
"""
import json
import re
import sys
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

Abfrage = Callable[..., list]

QUELLE = "waitinglist"
MERKMAL = "waitinglist"          # Schluessel direkt unter leads.enrichment
HERKUENFTE = ("legacy", "form")
# Dieselbe Form, die Website und Wartelisten-Tabelle verlangen.
_ADRESSE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
SCHWUND_MINDESTENS = 20
SCHWUND_ANTEIL = 0.2
_BERLIN = ZoneInfo("Europe/Berlin")


class EingabeFehler(ValueError):
    """Das Dokument ist nicht das, was die Website liefert - nichts schreiben."""


def _zeitpunkt(wert) -> Optional[str]:
    """ISO-Zeitpunkt mit Zone, in UTC normalisiert - oder None."""
    if not isinstance(wert, str) or not wert.strip():
        return None
    try:
        t = datetime.fromisoformat(wert.strip())
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return t.astimezone(timezone.utc).isoformat()


def eintraege_lesen(dokument) -> Tuple[Dict[str, dict], int]:
    """({adresse: merkmal}, anzahl_unbrauchbar) aus dem Dokument der Website.

    Erwartet `{"count": n, "rows": [{email, created_at, confirmed_at,
    source}, ...]}`. Stimmt `count` nicht mit der Zeilenzahl ueberein, ist das
    Dokument abgeschnitten -> EingabeFehler. Eine einzelne unbrauchbare Zeile
    wird gezaehlt und uebergangen; doppelte Adressen zaehlen einmal."""
    if not isinstance(dokument, dict) or not isinstance(dokument.get("rows"), list):
        raise EingabeFehler("kein Wartelisten-Dokument (rows fehlt)")
    zeilen = dokument["rows"]
    if dokument.get("count") != len(zeilen):
        raise EingabeFehler("Wartelisten-Dokument unvollstaendig (count passt nicht zu rows)")
    eintraege: Dict[str, dict] = {}
    unbrauchbar = 0
    for z in zeilen:
        if not isinstance(z, dict):
            unbrauchbar += 1
            continue
        adresse = z.get("email")
        adresse = adresse.strip().lower() if isinstance(adresse, str) else ""
        angemeldet = _zeitpunkt(z.get("created_at"))
        herkunft = z.get("source")
        bestaetigt_roh = z.get("confirmed_at")
        bestaetigt = _zeitpunkt(bestaetigt_roh)
        if (not 5 <= len(adresse) <= 255 or not _ADRESSE.match(adresse)
                or angemeldet is None or herkunft not in HERKUENFTE
                or (bestaetigt_roh is not None and bestaetigt is None)):
            unbrauchbar += 1
            continue
        if adresse in eintraege:
            continue
        eintraege[adresse] = {"auf_liste": True, "angemeldet_am": angemeldet,
                              "bestaetigt_am": bestaetigt, "herkunft": herkunft}
    return eintraege, unbrauchbar


def kontaktname(adresse: str) -> str:
    """Die Warteliste kennt keinen Namen; wie bei Mail-Kontakten
    (post_erledigt.kontakt_anlegen) steht der Teil vor dem @."""
    return adresse.split("@", 1)[0]


def notiz(merkmal: dict) -> str:
    tag = datetime.fromisoformat(merkmal["angemeldet_am"]).astimezone(_BERLIN)
    return (f"Waitinglist – auf vibemind.space eingetragen am {tag:%d.%m.%Y}. "
            "Vom Wartelisten-Abgleich angelegt; keine Werbe-Einwilligung gebucht.")


def _merkmal(enrichment) -> Optional[dict]:
    eintrag = (enrichment or {}).get(MERKMAL) if isinstance(enrichment, dict) else None
    return eintrag if isinstance(eintrag, dict) else None


def planen(eintraege: Dict[str, dict], bestand: Iterable[dict], gesperrt: Set[str],
           *, hoechstens: Optional[int] = None) -> dict:
    """Was zu tun ist - ohne Datenbank, damit es pruefbar bleibt.

    `bestand`: Kontakte als {id, email (klein, getrimmt oder None),
    enrichment}, aelteste zuerst. Bei mehreren Kontakten mit derselben Adresse
    traegt der aelteste das Merkmal (dieselbe Wahl wie
    post_erledigt.kontakt_anlegen).

    Rueckgabe: {"anlegen": [(adresse, merkmal)], "kennzeichnen": [(id,
    merkmal)], "austragen": [id], "zahlen": {...}}."""
    bestand = list(bestand)
    erster: Dict[str, dict] = {}
    for k in bestand:
        if k.get("email") and k["email"] not in erster:
            erster[k["email"]] = k

    anlegen: List[Tuple[str, dict]] = []
    kennzeichnen: List[Tuple[str, dict]] = []
    zahlen = {"auf_der_liste": len(eintraege), "angelegt": 0, "gekennzeichnet": 0,
              "aktualisiert": 0, "unveraendert": 0, "gesperrt": 0,
              "zurueckgestellt": 0, "ausgetragen": 0, "austragen_gestoppt": 0}

    for adresse in sorted(eintraege, key=lambda a: (eintraege[a]["angemeldet_am"], a)):
        neu = eintraege[adresse]
        kontakt = erster.get(adresse)
        if kontakt is not None:
            alt = _merkmal(kontakt.get("enrichment"))
            if alt is not None and all(alt.get(s) == w for s, w in neu.items()):
                zahlen["unveraendert"] += 1
            else:
                kennzeichnen.append((str(kontakt["id"]), neu))
                zahlen["gekennzeichnet" if alt is None else "aktualisiert"] += 1
        elif adresse in gesperrt:
            zahlen["gesperrt"] += 1
        elif hoechstens is not None and len(anlegen) >= hoechstens:
            zahlen["zurueckgestellt"] += 1
        else:
            anlegen.append((adresse, neu))
            zahlen["angelegt"] += 1

    traeger = {str(k["id"]) for k in erster.values()}
    markiert = [k for k in bestand
                if (_merkmal(k.get("enrichment")) or {}).get("auf_liste") is True]
    austragen = [str(k["id"]) for k in markiert
                 if not (k.get("email") in eintraege and str(k["id"]) in traeger)]
    if (len(austragen) >= SCHWUND_MINDESTENS
            and len(austragen) > SCHWUND_ANTEIL * len(markiert)):
        zahlen["austragen_gestoppt"] = len(austragen)
        austragen = []
    zahlen["ausgetragen"] = len(austragen)
    return {"anlegen": anlegen, "kennzeichnen": kennzeichnen,
            "austragen": austragen, "zahlen": zahlen}


def bestand_lesen(q: Abfrage) -> List[dict]:
    return q("select id, nullif(lower(btrim(email)), '') as email, enrichment "
             "from leads order by created_at, id")


def gesperrte_lesen(q: Abfrage, adressen: Iterable[str]) -> Set[str]:
    """Die Adressen, die auf der gemeinsamen Verbotsliste stehen - EINE
    Abfrage statt einer je Adresse; Kennung und Schema wie sperrliste.py."""
    import sperrliste
    kennungen = {}
    for a in adressen:
        k = sperrliste.kennung_email(a)
        if k:
            kennungen[k] = a
    if not kennungen:
        return set()
    zeilen = q(f"select kennung from {sperrliste.SCHEMA}.sperrliste "
               "where kennung = any(%s) and aufgehoben_am is null",
               (list(kennungen),)) or []
    return {kennungen[z["kennung"]] for z in zeilen if z["kennung"] in kennungen}


def ausfuehren(q: Abfrage, plan: dict, jetzt: datetime) -> None:
    for adresse, merkmal in plan["anlegen"]:
        q("insert into leads (name, email, source, notes, enrichment, created_at, updated_at) "
          "values (%s, %s, %s, %s, %s::jsonb, %s::timestamptz, %s::timestamptz) returning id",
          (kontaktname(adresse), adresse, QUELLE, notiz(merkmal),
           json.dumps({"art": "person", MERKMAL: merkmal}),
           merkmal["angemeldet_am"], merkmal["angemeldet_am"]))
    for lead_id, merkmal in plan["kennzeichnen"]:
        q("update leads set enrichment = coalesce(enrichment, '{}'::jsonb) "
          "|| jsonb_build_object(%s::text, %s::jsonb) where id = %s returning id",
          (MERKMAL, json.dumps(merkmal), lead_id))
    aus = json.dumps({"auf_liste": False,
                      "ausgetragen_am": jetzt.astimezone(timezone.utc).isoformat()})
    for lead_id in plan["austragen"]:
        q("update leads set enrichment = jsonb_set(enrichment, array[%s::text], "
          "(enrichment -> %s::text) || %s::jsonb) where id = %s returning id",
          (MERKMAL, MERKMAL, aus, lead_id))


def abgleichen(q: Abfrage, dokument, *, hoechstens: Optional[int] = None,
               trocken: bool = False, jetzt: Optional[datetime] = None) -> dict:
    """Ein Lauf. Gibt nur Zahlen zurueck. Wirft EingabeFehler, bevor
    irgendetwas geschrieben wurde."""
    eintraege, unbrauchbar = eintraege_lesen(dokument)
    if not eintraege:
        raise EingabeFehler("Wartelisten-Dokument ohne brauchbare Zeile")
    bestand = bestand_lesen(q)
    bekannt = {k["email"] for k in bestand if k.get("email")}
    gesperrt = gesperrte_lesen(q, (a for a in eintraege if a not in bekannt))
    plan = planen(eintraege, bestand, gesperrt, hoechstens=hoechstens)
    if not trocken:
        ausfuehren(q, plan, jetzt or datetime.now(timezone.utc))
    return {**plan["zahlen"], "unbrauchbar": unbrauchbar, "trocken": trocken}


def main(argv, eingabe=None) -> int:
    if not argv or argv[0] != "abgleichen":
        print(__doc__.split("CLI", 1)[1], file=sys.stderr)
        return 2
    trocken, hoechstens, rest = False, None, list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a == "--trocken":
            trocken = True
        elif a == "--hoechstens" and rest and rest[0].isdigit():
            hoechstens = int(rest.pop(0))
        else:
            print(f"FEHLER: unbekanntes Argument {a!r}", file=sys.stderr)
            return 2
    roh = (eingabe if eingabe is not None else sys.stdin).read()
    if not roh.strip():
        print("FEHLER: kein Dokument auf der Standardeingabe - nichts geaendert.",
              file=sys.stderr)
        return 2
    try:
        dokument = json.loads(roh)
    except ValueError:
        print("FEHLER: Dokument ist kein JSON - nichts geaendert.", file=sys.stderr)
        return 2
    import server
    try:
        zahlen = abgleichen(server._q, dokument, hoechstens=hoechstens, trocken=trocken)
    except EingabeFehler as e:
        print(f"FEHLER: {e} - nichts geaendert.", file=sys.stderr)
        return 2
    print(json.dumps(zahlen, ensure_ascii=False))
    if zahlen["austragen_gestoppt"]:
        print(f"WARNUNG: {zahlen['austragen_gestoppt']} gekennzeichnete Kontakte fehlen "
              "im Dokument - Schwund-Sperre, niemand ausgetragen.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
