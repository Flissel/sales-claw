"""Kurs-Handbuch (B1): je Lernendem ein Nachschlagewerk aus Kapiteln, das mit jeder Kurssitzung
waechst.

Ablauf je Sitzung: `zuordnen` (ein KI-Auftrag: Abschnitte -> Kapitel, ergaenzen/neu/ersetzen),
dann je betroffenem Kapitel `fortschreiben` (ein KI-Auftrag: neue Fassung des Kapitels),
zum Schluss `ausgeben` (HTML + PDF im Ordner `_handbuecher`). Nichts wird verschickt, es gibt
keine Entwuerfe. Wiederholungen liegen beim Aufrufer (Taktgeber).

Rueckbau: `quelle_entfernen` (Sitzung geht aus dem Handbuch), `einfuegen_vorbereiten` (aeltere
Sitzung kommt nachtraeglich dazu) und `alles_entfernen` (Loeschantrag). Zurueckgerollte spaetere
Sitzungen arbeitet der Taktgeber ueber `offene_auftraege` in Datumsfolge neu ein.

Logs: nur Anzahlen, Typnamen und gekuerzte Ids, nie Titel, Namen oder Kapiteltext.
"""
import json
import logging
import re
import uuid
from datetime import datetime

import bildschirm
import kurs_mitschrift
import kurs_pdf
import mitschrift_bericht
import ollama
import server
import ui_termin

MAX_BILDER_KAPITEL = 3
ORDNER_NAME = mitschrift_bericht.HANDBUCH_ORDNER
KURZ_ZEICHEN = 400
TITEL_MAX = 200
ENTSCHEIDUNGEN = ("ergaenzen", "neu", "ersetzen")

log = logging.getLogger("kurs_handbuch")
TZ = mitschrift_bericht.TZ

ZUORDNUNG_SYSTEM = """Du pflegst das Handbuch einer Lernenden. Das Handbuch besteht aus Kapiteln; \
nach jeder Kurssitzung werden deren Abschnitte den Kapiteln zugeordnet.

Du bekommst:
- "kapitel": die vorhandenen Kapitel (kapitel_id, titel, kurz = Anfang des Kapiteltextes, \
juengste_quelle = Datum der jüngsten Sitzung, die in das Kapitel eingeflossen ist),
- "datum": das Datum der neuen Sitzung,
- "abschnitte": die Abschnitte der neuen Sitzung (abschnitt = Nummer, titel, merken, bilder).

Entscheide für jeden Abschnitt genau eine Sache:
- "ergaenzen": Der Abschnitt gehört thematisch zu einem vorhandenen Kapitel und bringt Neues dazu. \
Gib die kapitel_id an.
- "neu": Das Thema hat noch kein Kapitel. Gib einen sprechenden Titel an (z. B. "Termin anlegen").
- "ersetzen": Der Abschnitt erklärt etwas, das in einem vorhandenen Kapitel steht, jetzt anders oder \
besser, sodass der alte Teil überholt ist. Gib die kapitel_id an.

Regeln:
- Verwende nur kapitel_id-Werte aus der Eingabe, erfinde keine.
- Bevorzuge "ergaenzen" vor "neu", wenn ein vorhandenes Kapitel thematisch passt.
- Jeder Abschnitt kommt genau einmal vor; "abschnitt" ist die Nummer aus der Eingabe.
- Bei "neu" ist kapitel_id null, bei den anderen ist titel null.

Antworte ausschließlich mit JSON in genau dieser Form:
{"zuordnung": [{"abschnitt": 0, "entscheidung": "ergaenzen" | "neu" | "ersetzen", \
"kapitel_id": "..." oder null, "titel": "..." oder null}]}"""

KAPITEL_SYSTEM = """Du schreibst ein Kapitel im Handbuch einer Lernenden, mit dem sie nachschlagen \
kann, wenn sie etwas vergessen hat. Sprich sie direkt an (Du), ohne Fachjargon; schwierige Begriffe \
erklärst Du in einfachen Worten.

Du bekommst:
- "kapitel_titel" und "alter_text" (der bisherige Kapiteltext in Markdown; leer bei einem neuen Kapitel),
- "datum" der neuen Sitzung,
- "neue_abschnitte": was in der neuen Sitzung dazu erklärt wurde (abschnitt, titel, entscheidung, \
merken, bilder mit bild_id, zu_sehen, erklaert, schritte),
- "bild_ids_alt": die Bilder, die das Kapitel bisher zeigt.

Entscheidung je Abschnitt:
- "neu": Schreibe das Kapitel aus den neuen Abschnitten.
- "ergaenzen": Füge das Neue an der passenden Stelle in den alten Text ein.
- "ersetzen": Der alte Teil dazu ist überholt; ersetze genau diesen Teil durch die neue Erklärung.

Regeln:
- Alles im alten Text, was nicht ergänzt oder ersetzt wird, übernimmst Du Wort für Wort. \
Formuliere nichts um, damit die Lernende ihr Nachschlagewerk wiedererkennt.
- Schreibe in Markdown: Absätze, nummerierte Schritte (1. 2. 3.), Aufzählungen, **fett** für wichtige \
Begriffe, am Ende einen Absatz "**Merken:**" mit dem Wichtigsten. Beginne nicht mit dem Kapiteltitel \
(er wird automatisch gesetzt).
- Erfinde nichts, was in der Eingabe nicht steht. Nimm keine Fragen oder offenen Punkte auf.
- "bild_ids": die Bilder, die das Kapitel zeigen soll, höchstens 3, die aussagekräftigsten und \
jüngsten. Verwende ausschließlich bild_id-Werte aus "neue_abschnitte" oder "bild_ids_alt".

Antworte ausschließlich mit JSON in genau dieser Form:
{"text_md": "...", "bild_ids": ["..."]}"""

HANDBUCH_CSS = kurs_mitschrift.KURS_CSS + """
.kapitel { margin-bottom: 2rem; }
.quelle { color: var(--blass); font-size: .85rem; margin: -.2rem 0 .8rem; }
code { background: var(--flaeche); padding: 0 .25rem; border-radius: 3px; }"""


class Veraltet(ValueError):
    """Die Sitzung gehoert nicht mehr (so) in dieses Handbuch: Rubrik nicht mehr "Kurse",
    anderer Lernender, Kursmitschrift entfernt oder ihr Stand hat sich geaendert. Es wurde
    nichts gespeichert; kein Fehlversuch, der Aufrufer laesst die Sitzung einfach liegen."""


# ---------- Hilfen ----------

def _lead8(lead_id: str) -> str:
    return str(lead_id)[:8]


def _sitzung_sperren(conn, lead_id: str, uid: str) -> str:
    """In der Transaktion des Aufrufers: Mitschrift-Zeile sperren (`for update`, immer als
    erste Sperre) und pruefen, dass sie eine Kursmitschrift dieses Lernenden ist. Rueckgabe:
    aktueller Kurs-Stand; sonst Veraltet. Dieselbe Sperre nehmen Lernenden-Wechsel,
    Verschieben und Entfernen, daher kann kein Rueckbau zwischen Pruefen und Schreiben fallen."""
    z = conn.execute("select rubrik, kurs_lead_id, kurs_json is not null as da "
                     "from termin_mitschriften where uid = %s for update", (uid,)).fetchone()
    if not z or not z["da"] or not kurs_mitschrift.ist_kurs(z["rubrik"]) \
            or str(z["kurs_lead_id"]) != lead_id:
        raise Veraltet("Sitzung gehoert nicht mehr zu diesem Handbuch")
    return conn.execute(f"select {kurs_mitschrift.KURS_STAND_SQL} as s "
                        "from termin_mitschriften m where m.uid = %s", (uid,)).fetchone()["s"]


def _handbuch_sperren(conn, lead_id: str) -> None:
    """Ausgabe und Rueckbau eines Lernenden nacheinander (Transaktions-Sperre, auch wenn
    noch keine kurs_handbuch-Zeile existiert)."""
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"kurs_handbuch:{lead_id}",))


def _id(wert: object) -> str | None:
    """Gueltige UUID als String (klein geschrieben), sonst None."""
    try:
        return str(uuid.UUID(str(wert)))
    except (ValueError, AttributeError):
        return None


def _lead_pruefen(lead_id: str) -> str:
    lid = _id(lead_id)
    if lid is None or not server._q("select 1 from leads where id = %s", (lid,)):
        raise ValueError("Lernender nicht gefunden")
    return lid


def _json(wert) -> object:
    if isinstance(wert, str):
        return json.loads(wert)
    return wert


def _antwort(text: object) -> object:
    """KI-Antwort als JSON lesen; alles Unlesbare wird zum ValueError."""
    try:
        return json.loads(text)
    except TypeError:
        raise ValueError("keine Antwort") from None


def _text(wert) -> str:
    return wert.strip() if isinstance(wert, str) else ""


def _tag(t: datetime | None) -> str:
    return t.astimezone(TZ).strftime("%d.%m.%Y") if t else ""


def _iso_tag(t: datetime | None) -> str:
    return t.astimezone(TZ).strftime("%Y-%m-%d") if t else ""


def _sitzung(uid: str) -> tuple[datetime, dict]:
    """(Beginn, kurs_json) der Sitzung; ValueError ohne Kursmitschrift oder Beginn."""
    z = server._q("select a.beginn, m.kurs_json from termin_mitschriften m "
                  "join termin_akten a on a.uid = m.uid where m.uid = %s", (uid,))
    if not z or not z[0]["kurs_json"] or z[0]["beginn"] is None:
        raise ValueError("keine Kursmitschrift")
    kj = _json(z[0]["kurs_json"])
    if not isinstance(kj, dict) or not isinstance(kj.get("abschnitte"), list):
        raise ValueError("Kursmitschrift unbrauchbar")
    return z[0]["beginn"], kj


def _beginne(uids: list[str]) -> dict[str, datetime]:
    if not uids:
        return {}
    z = server._q("select uid, beginn from termin_akten where uid = any(%s) "
                  "and beginn is not null", (list(uids),))
    return {r["uid"]: r["beginn"] for r in z}


def _abschnitt_eingabe(index: int, a: dict) -> dict:
    return {"abschnitt": index, "titel": a["titel"], "merken": a["merken"],
            "bilder": [{"bild_id": b["bild_id"], "zu_sehen": b["zu_sehen"],
                        "erklaert": b["erklaert"], "schritte": b["schritte"]}
                       for b in a["bilder"]]}


def _kapitel_uebersicht(lead_id: str) -> list[dict]:
    z = server._q(
        "select k.id, k.titel, f.text_md, f.quellen from kurs_handbuch_kapitel k "
        "left join kurs_handbuch_fassung f on f.id = k.aktuelle_fassung "
        "where k.lead_id = %s order by k.reihenfolge, k.erstellt_am", (lead_id,))
    beginne = _beginne(sorted({u for r in z for u in (r["quellen"] or [])}))
    aus = []
    for r in z:
        jung = max((beginne[u] for u in (r["quellen"] or []) if u in beginne), default=None)
        aus.append({"kapitel_id": str(r["id"]), "titel": r["titel"],
                    "kurz": (r["text_md"] or "")[:KURZ_ZEICHEN],
                    "juengste_quelle": _iso_tag(jung)})
    return aus


# ---------- Zuordnen ----------

def _zuordnung_pruefen(roh: object, abschnitte: list[dict], eigene: set[str]) -> list[dict]:
    """KI-Zuordnung pruefen; ValueError bei allem Ungueltigen. Fehlende Abschnitte werden zu
    einem neuen Kapitel mit ihrem eigenen Titel."""
    if not isinstance(roh, dict) or not isinstance(roh.get("zuordnung"), list):
        raise ValueError("keine Zuordnung")
    je_abschnitt: dict[int, dict] = {}
    for z in roh["zuordnung"]:
        if not isinstance(z, dict):
            raise ValueError("Zuordnung unbrauchbar")
        nr = z.get("abschnitt")
        if isinstance(nr, bool) or not isinstance(nr, int) or not 0 <= nr < len(abschnitte):
            raise ValueError("ungueltiger Abschnitt")
        if nr in je_abschnitt:
            raise ValueError("Abschnitt doppelt")
        entscheidung = z.get("entscheidung")
        if entscheidung not in ENTSCHEIDUNGEN:
            raise ValueError("ungueltige Entscheidung")
        if entscheidung == "neu":
            titel = (_text(z.get("titel")) or abschnitte[nr]["titel"])[:TITEL_MAX]
            je_abschnitt[nr] = {"abschnitt": nr, "entscheidung": "neu", "kapitel_id": None,
                                "titel": titel, "erledigt": False}
        else:
            kid = _id(z.get("kapitel_id"))
            if kid is None or kid not in eigene:
                raise ValueError("Kapitel gehoert nicht zum Lernenden")
            je_abschnitt[nr] = {"abschnitt": nr, "entscheidung": entscheidung,
                                "kapitel_id": kid, "titel": None, "erledigt": False}
    for nr, a in enumerate(abschnitte):
        je_abschnitt.setdefault(nr, {"abschnitt": nr, "entscheidung": "neu", "kapitel_id": None,
                                     "titel": a["titel"][:TITEL_MAX], "erledigt": False})
    return [je_abschnitt[nr] for nr in sorted(je_abschnitt)]


def _kapitel_quellen_beginne(lead_id: str, kapitel_id: str, ausser: str) -> list[datetime]:
    """Beginn aller Sitzungen, die zu diesem Kapitel beitragen (eingearbeitet oder zugeordnet)."""
    uids: set[str] = set()
    z = server._q("select f.quellen from kurs_handbuch_kapitel k "
                  "join kurs_handbuch_fassung f on f.id = k.aktuelle_fassung where k.id = %s",
                  (kapitel_id,))
    if z:
        uids.update(z[0]["quellen"] or [])
    for q in server._q("select uid, zuordnung from kurs_handbuch_quelle "
                       "where lead_id = %s and uid <> %s", (lead_id, ausser)):
        if any(e.get("kapitel_id") == kapitel_id for e in _json(q["zuordnung"])):
            uids.add(q["uid"])
    uids.discard(ausser)
    return list(_beginne(sorted(uids)).values())


def zuordnen(lead_id: str, uid: str) -> dict:
    """Ein KI-Auftrag: Abschnitte der Sitzung `uid` den Kapiteln des Lernenden zuordnen und als
    Quelle buchen (noch nicht eingearbeitet). Ungueltige Antwort: ValueError, nichts gespeichert.
    Gehoert die Sitzung (vorher oder nach dem KI-Auftrag) nicht mehr als Kursmitschrift zu
    diesem Lernenden oder hat sich ihr Stand geaendert: Veraltet, nichts gespeichert.
    Rueckgabe: {"uid", "zuordnung": [...]}."""
    lead_id = _lead_pruefen(lead_id)
    stand = kurs_mitschrift.kurs_stand(uid)          # vor kurs_json: Neueres faellt auf
    with server.pool.connection() as conn:
        if _sitzung_sperren(conn, lead_id, uid) != stand:
            raise Veraltet("Stand geaendert")
    beginn, kj = _sitzung(uid)
    abschnitte = kj["abschnitte"]
    if not abschnitte:
        raise ValueError("keine Abschnitte")
    alt = server._q("select zuordnung from kurs_handbuch_quelle where lead_id = %s and uid = %s",
                    (lead_id, uid))
    if alt and any(e.get("erledigt") for e in _json(alt[0]["zuordnung"])):
        raise ValueError("Sitzung ist schon eingearbeitet")
    kapitel = _kapitel_uebersicht(lead_id)
    eingabe = {"kapitel": kapitel, "datum": _iso_tag(beginn),
               "abschnitte": [_abschnitt_eingabe(i, a) for i, a in enumerate(abschnitte)]}
    antwort = ollama.chat(ZUORDNUNG_SYSTEM, json.dumps(eingabe, ensure_ascii=False),
                          als_json=True)
    eintraege = _zuordnung_pruefen(_antwort(antwort), abschnitte,
                                   {k["kapitel_id"] for k in kapitel})
    for e in eintraege:
        # "ersetzen" nur durch eine Sitzung, die juenger ist als alle Quellen des Kapitels
        if e["entscheidung"] == "ersetzen" and any(
                b >= beginn for b in _kapitel_quellen_beginne(lead_id, e["kapitel_id"], uid)):
            e["entscheidung"] = "ergaenzen"
    with server.pool.connection() as conn:
        # Waehrend des KI-Auftrags kann Felix den Lernenden gewechselt, die Mitschrift
        # verschoben oder geloescht haben: erst unter Sperre pruefen, dann buchen.
        if _sitzung_sperren(conn, lead_id, uid) != stand:
            raise Veraltet("Stand geaendert")
        alt = conn.execute("select zuordnung from kurs_handbuch_quelle where lead_id = %s "
                           "and uid = %s for update", (lead_id, uid)).fetchone()
        if alt and any(e.get("erledigt") for e in _json(alt["zuordnung"])):
            raise ValueError("Sitzung ist schon eingearbeitet")
        # zugeordnete Kapitel muessen noch bestehen (ein Rueckbau kann sie waehrend des
        # KI-Auftrags geloescht haben); gesperrt nach der Quelle, wie beim Rueckbau
        ziele = sorted({e["kapitel_id"] for e in eintraege if e.get("kapitel_id")})
        if ziele and len(conn.execute(
                "select id from kurs_handbuch_kapitel where lead_id = %s "
                "and id = any(%s::uuid[]) for update", (lead_id, ziele)).fetchall()) != len(ziele):
            raise Veraltet("zugeordnetes Kapitel inzwischen geloescht")
        conn.execute(
            "insert into kurs_handbuch_quelle (lead_id, uid, beginn, stand, zuordnung, "
            "eingearbeitet_am) values (%s, %s, %s, %s, %s::jsonb, null) "
            "on conflict (lead_id, uid) do update set beginn = excluded.beginn, "
            "stand = excluded.stand, zuordnung = excluded.zuordnung, eingearbeitet_am = null",
            (lead_id, uid, beginn, stand, json.dumps(eintraege)))
    log.info("Handbuch zugeordnet lead=%s uid=%s abschnitte=%d neu=%d", _lead8(lead_id),
             mitschrift_bericht.uid8(uid), len(eintraege),
             sum(1 for e in eintraege if e["entscheidung"] == "neu"))
    return {"uid": uid, "zuordnung": eintraege}


def offene_auftraege(lead_id: str) -> list[tuple[str, str]]:
    """(uid, ziel) fuer zugeordnete, noch nicht eingearbeitete Quellen in Datumsfolge.
    ziel = kapitel_id oder "neu:<abschnitt>"; je Kapitel ein Auftrag je Sitzung. Ein "neu" mit
    kapitel_id fuellt eine leere Huelle (siehe `einfuegen_vorbereiten`)."""
    aus: list[tuple[str, str]] = []
    for q in server._q("select uid, zuordnung from kurs_handbuch_quelle "
                       "where lead_id = %s and eingearbeitet_am is null "
                       "order by beginn, uid", (lead_id,)):
        gesehen: set[str] = set()
        for e in _json(q["zuordnung"]):
            if e.get("erledigt"):
                continue
            ziel = e["kapitel_id"] if e.get("kapitel_id") else f"neu:{e['abschnitt']}"
            if ziel not in gesehen:
                gesehen.add(ziel)
                aus.append((q["uid"], ziel))
    return aus


# ---------- Fortschreiben ----------

def _auswahl_bild_ids(vorschlag: object, quellen: list[str],
                      beginne: dict[str, datetime]) -> list[str]:
    """Nur geprueft vorhandene Bilder der Quell-Sitzungen, die juengsten, hoechstens
    MAX_BILDER_KAPITEL, in zeitlicher Folge."""
    if not isinstance(vorschlag, list):
        raise ValueError("bild_ids unbrauchbar")
    bekannt: dict[str, tuple] = {}
    for u in quellen:
        for b in bildschirm.bilder(u):
            bekannt[str(b["id"])] = (beginne[u], b["aufgenommen_am"])
    ids = []
    for b in vorschlag:
        bid = _id(b)
        if bid in bekannt and bid not in ids:
            ids.append(bid)
    ids.sort(key=lambda i: bekannt[i])
    return ids[-MAX_BILDER_KAPITEL:]


def _kapitel_pruefen(roh: object) -> tuple[str, object]:
    if not isinstance(roh, dict):
        raise ValueError("keine Kapitel-Antwort")
    text = _text(roh.get("text_md"))
    if not text:
        raise ValueError("kein Kapiteltext")
    return text, roh.get("bild_ids", [])


def fortschreiben(lead_id: str, uid: str, ziel: str) -> str:
    """Ein KI-Auftrag: Kapitel `ziel` (kapitel_id oder "neu:<abschnitt>") mit den neuen Abschnitten
    der Sitzung `uid` als neue Fassung schreiben. Rueckgabe: kapitel_id. Ungueltige Antwort:
    ValueError, nichts gespeichert."""
    lead_id = _lead_pruefen(lead_id)
    q = server._q("select zuordnung from kurs_handbuch_quelle where lead_id = %s and uid = %s",
                  (lead_id, uid))
    if not q:
        raise ValueError("Sitzung ist nicht zugeordnet")
    eintraege = _json(q[0]["zuordnung"])
    beginn, kj = _sitzung(uid)
    abschnitte = kj["abschnitte"]
    kapitel = None
    if isinstance(ziel, str) and ziel.startswith("neu:"):
        try:
            nr = int(ziel[4:])
        except ValueError:
            raise ValueError("ungueltiges Ziel") from None
        auswahl = [e for e in eintraege if e["abschnitt"] == nr and e["entscheidung"] == "neu"
                   and not e.get("erledigt") and not e.get("kapitel_id")]
        titel, alter_text, alt_bilder, alt_quellen = (auswahl[0]["titel"] if auswahl else ""), \
            "", [], []
        gelesen = None
    else:
        kid = _id(ziel)
        z = server._q(
            "select k.id, k.titel, k.aktuelle_fassung, f.text_md, f.bild_ids, f.quellen "
            "from kurs_handbuch_kapitel k "
            "left join kurs_handbuch_fassung f on f.id = k.aktuelle_fassung "
            "where k.id = %s and k.lead_id = %s", (kid, lead_id)) if kid else []
        if not z:
            raise ValueError("Kapitel gehoert nicht zum Lernenden")
        kapitel = str(z[0]["id"])
        gelesen = z[0]["aktuelle_fassung"]          # Grundlage des KI-Auftrags
        auswahl = [e for e in eintraege if e.get("kapitel_id") == kapitel
                   and not e.get("erledigt")]
        titel, alter_text = z[0]["titel"], z[0]["text_md"] or ""
        alt_bilder, alt_quellen = list(z[0]["bild_ids"] or []), list(z[0]["quellen"] or [])
    if not auswahl or any(not 0 <= e["abschnitt"] < len(abschnitte) for e in auswahl):
        raise ValueError("kein offener Auftrag")

    eingabe = {"kapitel_titel": titel, "alter_text": alter_text, "bild_ids_alt": alt_bilder,
               "datum": _iso_tag(beginn),
               # "neu" in eine Huelle, die inzwischen Text hat: ergaenzen
               "neue_abschnitte": [dict(_abschnitt_eingabe(e["abschnitt"],
                                                           abschnitte[e["abschnitt"]]),
                                        entscheidung="ergaenzen"
                                        if e["entscheidung"] == "neu" and alter_text
                                        else e["entscheidung"]) for e in auswahl]}
    antwort = ollama.chat(KAPITEL_SYSTEM, json.dumps(eingabe, ensure_ascii=False),
                          als_json=True)
    text_md, vorschlag = _kapitel_pruefen(_antwort(antwort))
    quellen = sorted(set(alt_quellen) | {uid})
    beginne = _beginne(quellen)
    beginne[uid] = beginn
    quellen.sort(key=lambda u: (beginne.get(u, beginn), u))
    bild_ids = _auswahl_bild_ids(vorschlag, quellen, {u: beginne.get(u, beginn) for u in quellen})

    with server.pool.connection() as conn:
        aktuell = _sitzung_sperren(conn, lead_id, uid)     # vor der Quelle sperren
        zeile = conn.execute("select stand, zuordnung from kurs_handbuch_quelle "
                             "where lead_id = %s and uid = %s for update",
                             (lead_id, uid)).fetchone()
        if not zeile:
            raise Veraltet("Sitzung ist nicht mehr zugeordnet")
        if zeile["stand"] != aktuell:
            raise Veraltet("Stand geaendert")
        eintraege = _json(zeile["zuordnung"])
        if kapitel is None:
            # Quelle ist gesperrt: wer das Kapitel inzwischen angelegt hat, hat kapitel_id
            # gesetzt, dann ist hier nichts mehr offen
            nr = int(ziel[4:])
            offen = [e for e in eintraege if e["abschnitt"] == nr and e["entscheidung"] == "neu"
                     and not e.get("erledigt") and not e.get("kapitel_id")]
            if not offen:
                raise Veraltet("kein offener Auftrag mehr")
            kapitel = str(conn.execute(
                "insert into kurs_handbuch_kapitel (lead_id, titel, reihenfolge) values "
                "(%s, %s, (select coalesce(max(reihenfolge), 0) + 1 from "
                "kurs_handbuch_kapitel where lead_id = %s)) returning id",
                (lead_id, titel, lead_id)).fetchone()["id"])
            offen[0]["kapitel_id"] = kapitel
        else:
            # Kapitel nach der Quelle sperren (Reihenfolge wie beim Rueckbau). Hat ein
            # Rueckbau es waehrend des KI-Auftrags zurueckgesetzt oder geloescht, enthielte
            # der neue Text Inhalt einer entfernten Sitzung: dann nichts schreiben.
            k = conn.execute("select aktuelle_fassung from kurs_handbuch_kapitel "
                             "where id = %s and lead_id = %s for update",
                             (kapitel, lead_id)).fetchone()
            if not k or k["aktuelle_fassung"] != gelesen:
                raise Veraltet("Kapitel inzwischen geaendert")
            offen = [e for e in eintraege if e.get("kapitel_id") == kapitel
                     and not e.get("erledigt")]
            if sorted(e["abschnitt"] for e in offen) != sorted(e["abschnitt"] for e in auswahl):
                raise Veraltet("Auftrag inzwischen geaendert")
        fassung = conn.execute(
            "insert into kurs_handbuch_fassung (kapitel_id, text_md, bild_ids, quellen, "
            "erstellt_am) values (%s, %s, %s, %s, clock_timestamp()) returning id",
            (kapitel, text_md, bild_ids, quellen)).fetchone()["id"]
        conn.execute("update kurs_handbuch_kapitel set aktuelle_fassung = %s where id = %s",
                     (fassung, kapitel))
        for e in offen:
            e["erledigt"] = True
        fertig = all(e.get("erledigt") for e in eintraege)
        conn.execute("update kurs_handbuch_quelle set zuordnung = %s::jsonb, "
                     "eingearbeitet_am = case when %s then now() else null end "
                     "where lead_id = %s and uid = %s",
                     (json.dumps(eintraege), fertig, lead_id, uid))
    log.info("Handbuch-Kapitel fortgeschrieben lead=%s uid=%s abschnitte=%d bilder=%d",
             _lead8(lead_id), mitschrift_bericht.uid8(uid), len(offen), len(bild_ids))
    return kapitel


# ---------- HTML ----------

_FETT = re.compile(r"\*\*(.+?)\*\*")
_KURSIV = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_CODE = re.compile(r"`([^`]+)`")


def _inline(zeile: str) -> str:
    t = ui_termin._e(zeile)
    t = _CODE.sub(r"<code>\1</code>", t)
    t = _FETT.sub(r"<strong>\1</strong>", t)
    return _KURSIV.sub(r"<em>\1</em>", t)


def _md_html(text: str) -> str:
    """Kleines Markdown: Ueberschriften, Absaetze, (nummerierte) Listen, fett/kursiv/Code.
    Alles wird zuerst maskiert, es entsteht nur eigenes Markup."""
    teile: list[str] = []
    liste: tuple[str, list[str]] | None = None
    absatz: list[str] = []

    def schliessen() -> None:
        nonlocal liste
        if absatz:
            teile.append("<p>" + " ".join(_inline(z) for z in absatz) + "</p>")
            absatz.clear()
        if liste:
            teile.append(f"<{liste[0]}>" + "".join(f"<li>{_inline(i)}</li>" for i in liste[1])
                         + f"</{liste[0]}>")
            liste = None

    for zeile in text.splitlines():
        s = zeile.strip()
        if not s:
            schliessen()
        elif m := re.match(r"(#{1,6})\s+(.*)", s):
            schliessen()
            stufe = min(len(m.group(1)) + 2, 6)
            teile.append(f"<h{stufe}>{_inline(m.group(2))}</h{stufe}>")
        elif m := re.match(r"(\d+)[.)]\s+(.*)", s):
            if not liste or liste[0] != "ol":
                schliessen()
                liste = ("ol", [])
            liste[1].append(m.group(2))
        elif m := re.match(r"[-*•]\s+(.*)", s):
            if not liste or liste[0] != "ul":
                schliessen()
                liste = ("ul", [])
            liste[1].append(m.group(1))
        else:
            if liste:
                schliessen()
            absatz.append(s)
    schliessen()
    return "\n".join(teile)


def _kapitel_zeilen(lead_id: str) -> list[dict]:
    return server._q(
        "select k.id, k.titel, f.text_md, f.bild_ids, f.quellen, f.erstellt_am "
        "from kurs_handbuch_kapitel k join kurs_handbuch_fassung f on f.id = k.aktuelle_fassung "
        "where k.lead_id = %s order by k.reihenfolge, k.erstellt_am", (lead_id,))


def _bild_block(quellen: list[str], bild_ids: list[str]) -> str:
    gefunden: dict[str, tuple[str, datetime]] = {}
    for u in quellen:
        for b in bildschirm.bilder(u):
            gefunden[str(b["id"])] = (u, b["aufgenommen_am"])
    teile = []
    for bid in bild_ids:
        if bid not in gefunden:
            continue
        u, am = gefunden[bid]
        uri = kurs_mitschrift._kurs_bild_uri(u, bid)
        if uri:
            teile.append(f'<figure><img src="{uri}" alt="Bildschirm">'
                         f'<figcaption>{ui_termin._e(am.astimezone(TZ).strftime("%d.%m.%Y %H:%M"))}'
                         "</figcaption></figure>")
    return '<div class="bilder">' + "".join(teile) + "</div>" if teile else ""


def handbuch_html(lead_id: str) -> str:
    """Eigenstaendiges HTML des Handbuchs (Bilder eingebettet, druckbar). Ohne Offen-Teil."""
    e = ui_termin._e
    lead_id = _lead_pruefen(lead_id)
    name = server._q("select name from leads where id = %s", (lead_id,))[0]["name"]
    zeilen = _kapitel_zeilen(lead_id)
    beginne = _beginne(sorted({u for z in zeilen for u in z["quellen"]}))
    sitzungen = {u for z in zeilen for u in z["quellen"]}
    stand = _tag(max((z["erstellt_am"] for z in zeilen), default=None))
    n = len(sitzungen)
    kopf = (f"Stand: {stand}, {n} Sitzung" + ("" if n == 1 else "en"))
    meta = mitschrift_bericht._verbinden(f"für {e(name)}" if name else "", e(kopf))

    inhalt = "".join(f'<li><a href="#k{i}">{e(z["titel"])}</a></li>'
                     for i, z in enumerate(zeilen, 1))
    kapitel = []
    for i, z in enumerate(zeilen, 1):
        tage = sorted({beginne[u].astimezone(TZ).date() for u in z["quellen"] if u in beginne})
        woher = ("aus Sitzung" + ("" if len(tage) == 1 else "en") + " vom "
                 + ", ".join(t.strftime("%d.%m.%Y") for t in tage)) if tage else ""
        kapitel.append(
            f'<section class="kapitel" id="k{i}"><h2>{i}. {e(z["titel"])}</h2>'
            + (f'<p class="quelle">{e(woher)}</p>' if woher else "")
            + _md_html(z["text_md"])
            + _bild_block(list(z["quellen"]), list(z["bild_ids"] or []))
            + "</section>")
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>Kurs-Handbuch</title>\n<style>\n{HANDBUCH_CSS}\n</style></head><body>\n'
        f'<h1>Kurs-Handbuch</h1>\n<p class="meta">{meta}</p>\n'
        f'<nav class="inhalt"><h2>Inhalt</h2><ol>{inhalt}</ol></nav>\n'
        + "\n".join(kapitel) + "\n</body></html>")


# ---------- Ausgabe ----------

def _juengste_fassung(lead_id: str) -> datetime | None:
    z = server._q("select max(f.erstellt_am) as m from kurs_handbuch_fassung f "
                  "join kurs_handbuch_kapitel k on k.id = f.kapitel_id where k.lead_id = %s",
                  (lead_id,))
    return z[0]["m"] if z else None


# Kapitelbestand (Fassung, Titel, Reihenfolge) und Ausgabe-Zeile: aendert sich beides
# zwischen Rendern und Buchen nicht, ist die gerenderte Ausgabe noch richtig.
_ZUSTAND_SQL = (
    "select (select md5(coalesce(string_agg(k.id::text || ':' || "
    "coalesce(k.aktuelle_fassung::text, '') || ':' || k.reihenfolge || ':' || k.titel, "
    "'|' order by k.id), '')) from kurs_handbuch_kapitel k where k.lead_id = %s) as kapitel, "
    "(select row(pfad, pdf, fassungen_stand)::text from kurs_handbuch "
    "where lead_id = %s) as ausgabe")


def _noch_gleich(conn, lead_id: str, vorher: dict) -> bool:
    """Unter der Handbuch-Sperre: hat sich seit `vorher` nichts geaendert?"""
    _handbuch_sperren(conn, lead_id)
    if conn.execute(_ZUSTAND_SQL, (lead_id, lead_id)).fetchone() == vorher:
        return True
    log.info("Handbuch-Ausgabe verworfen (inzwischen geaendert) lead=%s", _lead8(lead_id))
    return False


def ausgeben(lead_id: str) -> None:
    """HTML und PDF unter `_handbuecher/` schreiben (atomar) und `kurs_handbuch` buchen. Ohne
    Kapitel: Dateien und Zeile entfernen. Das PDF entsteht zuerst: schlaegt es fehl (PdfFehler),
    wird nichts geschrieben und nichts gebucht. Geschrieben und gebucht wird unter der
    Handbuch-Sperre und nur, wenn sich Kapitel und Ausgabe-Zeile seit Beginn des Renderns
    nicht geaendert haben (sonst nichts; die Ausgabe bleibt faellig) - so schreibt keine
    Ausgabe den Inhalt einer inzwischen entfernten Sitzung zurueck."""
    lead_id = _lead_pruefen(lead_id)
    vorher = server._q(_ZUSTAND_SQL, (lead_id, lead_id))[0]
    alt = server._q("select pfad, pdf from kurs_handbuch where lead_id = %s", (lead_id,))
    zeilen = _kapitel_zeilen(lead_id)
    if not zeilen:
        if alt:
            with server.pool.connection() as conn:
                if not _noch_gleich(conn, lead_id, vorher):
                    return
                weg = conn.execute("delete from kurs_handbuch where lead_id = %s "
                                   "returning pfad, pdf", (lead_id,)).fetchall()
            for z in weg:
                mitschrift_bericht.datei_entfernen(z["pfad"])
                mitschrift_bericht.datei_entfernen(z["pdf"])
            log.info("Handbuch entfernt lead=%s", _lead8(lead_id))
        return
    rel_html = f"{ORDNER_NAME}/handbuch-{_lead8(lead_id)}.html"
    rel_pdf = f"{ORDNER_NAME}/handbuch-{_lead8(lead_id)}.pdf"
    ziel_html, ziel_pdf = (mitschrift_bericht.sicherer_pfad(r) for r in (rel_html, rel_pdf))
    if ziel_html is None or ziel_pdf is None:
        raise ValueError("Ablagepfad ungueltig")
    stand = _juengste_fassung(lead_id)       # vor dem Rendern: Neueres macht erneut faellig
    html = handbuch_html(lead_id)
    pdf = kurs_pdf.pdf_aus_html(html)
    with server.pool.connection() as conn:
        if not _noch_gleich(conn, lead_id, vorher):
            return
        kurs_pdf.schreiben(ziel_html, html)
        kurs_pdf.schreiben(ziel_pdf, pdf)
        conn.execute(
            "insert into kurs_handbuch (lead_id, pfad, pdf, stand_am, fassungen_stand) "
            "values (%s, %s, %s, now(), %s) on conflict (lead_id) do update set "
            "pfad = excluded.pfad, pdf = excluded.pdf, stand_am = excluded.stand_am, "
            "fassungen_stand = excluded.fassungen_stand",
            (lead_id, rel_html, rel_pdf, stand))
    if alt:
        for alte, neue in ((alt[0]["pfad"], rel_html), (alt[0]["pdf"], rel_pdf)):
            if alte and alte != neue:
                mitschrift_bericht.datei_entfernen(alte)
    log.info("Handbuch ausgegeben lead=%s kapitel=%d", _lead8(lead_id), len(zeilen))


def ausgabe_faellig(lead_id: str) -> bool:
    """Keine offenen Auftraege und die Ausgabe ist nicht auf dem Stand der juengsten Fassung
    (`fassungen_stand` leer = Kapitel umbenannt, umsortiert oder zurueckgerollt). Wurde die
    Ausgabe nach dem Entfernen einer Quelle zurueckgenommen (`pfad` leer), ist sie sofort
    faellig, auch mit offenen Auftraegen: ein Zwischenstand ohne die entfernte Sitzung."""
    z = server._q("select pfad, fassungen_stand from kurs_handbuch where lead_id = %s",
                  (lead_id,))
    zurueckgenommen = bool(z) and z[0]["pfad"] is None
    if not zurueckgenommen and offene_auftraege(lead_id):
        return False
    if not _kapitel_zeilen(lead_id):
        return bool(z)
    return not z or z[0]["fassungen_stand"] is None \
        or z[0]["fassungen_stand"] != _juengste_fassung(lead_id)


# ---------- Rueckbau: Quelle entfernen, aeltere Sitzung einfuegen, Loeschantrag ----------

_LERNENDE_SQL = (
    "select lead_id from kurs_handbuch_quelle where uid = %s union "
    "select k.lead_id from kurs_handbuch_fassung f join kurs_handbuch_kapitel k "
    "on k.id = f.kapitel_id where %s = any(f.quellen)")


def lernende_mit_quelle(uid: str, conn=None) -> list[str]:
    """Lernende, in deren Handbuch die Sitzung `uid` gebucht ist oder Inhalt traegt
    (mit `conn` in der Transaktion des Aufrufers)."""
    z = conn.execute(_LERNENDE_SQL, (uid, uid)).fetchall() if conn is not None \
        else server._q(_LERNENDE_SQL, (uid, uid))
    return sorted(str(r["lead_id"]) for r in z)


def _abschnitt_titel(conn, uid: str, nr: object) -> str:
    """Eigener Abschnittstitel der Sitzung `uid` (Titel, wenn ihr Abschnitt ein neues Kapitel
    bekommt, weil sein Kapitel geloescht wurde)."""
    z = conn.execute("select kurs_json from termin_mitschriften where uid = %s",
                     (uid,)).fetchone()
    try:
        titel = _text(_json(z["kurs_json"])["abschnitte"][nr]["titel"])
    except (TypeError, KeyError, IndexError, ValueError):
        titel = ""
    return (titel or "Kapitel")[:TITEL_MAX]


def _zuordnungen_oeffnen(conn, lead_id: str, geloescht: set[str],
                         verloren: dict[str, set[str]]) -> None:
    """Gespeicherte Zuordnungen nach einem Rueckbau nachziehen: Eintraege einer Quelle, deren
    Beitrag zu Kapitel K zurueckgerollt wurde, sind wieder offen; Verweise auf geloeschte
    Kapitel werden "neu" mit dem eigenen Abschnittstitel. Die Quelle gilt dann als nicht
    eingearbeitet (der Taktgeber arbeitet sie in Datumsfolge neu ein)."""
    for q in conn.execute("select uid, zuordnung from kurs_handbuch_quelle where lead_id = %s "
                          "order by beginn, uid", (lead_id,)).fetchall():
        eintraege = _json(q["zuordnung"])
        geaendert = False
        for e in eintraege:
            kid = e.get("kapitel_id")
            if kid in geloescht:
                e.update(entscheidung="neu", kapitel_id=None, erledigt=False,
                         titel=_abschnitt_titel(conn, q["uid"], e.get("abschnitt")))
                geaendert = True
            elif e.get("erledigt") and q["uid"] in verloren.get(kid, ()):
                e["erledigt"] = False
                geaendert = True
        if geaendert:
            conn.execute("update kurs_handbuch_quelle set zuordnung = %s::jsonb, "
                         "eingearbeitet_am = null where lead_id = %s and uid = %s",
                         (json.dumps(eintraege), lead_id, q["uid"]))


def _zurueckrollen(conn, lead_id: str, weg: set[str], loeschen: set[str],
                   huelle: bool) -> int:
    """In der Transaktion des Aufrufers: jedes Kapitel des Lernenden, dessen Fassungen eine
    Quelle aus `weg` tragen, auf die juengste Fassung ohne diese Quellen zuruecksetzen; alle
    Fassungen mit ihnen loeschen. Bleibt keine Fassung, wird das Kapitel geloescht - mit
    `huelle` (die Quellen werden nur neu eingearbeitet) bleibt es als leere Huelle stehen
    (Titel, Reihenfolge), die sein Schoepfer wieder fuellt. Kapitel in `loeschen` gehen ganz.
    Rueckgabe: Anzahl betroffener Kapitel."""
    fassungen = conn.execute(
        "select f.id, f.kapitel_id, f.quellen from kurs_handbuch_fassung f "
        "join kurs_handbuch_kapitel k on k.id = f.kapitel_id where k.lead_id = %s "
        "order by f.kapitel_id, f.erstellt_am, f.id", (lead_id,)).fetchall()
    je_kapitel: dict[str, list[dict]] = {str(k): [] for k in loeschen}
    for f in fassungen:
        je_kapitel.setdefault(str(f["kapitel_id"]), []).append(f)
    geloescht: set[str] = set()
    verloren: dict[str, set[str]] = {}
    for kid, liste in je_kapitel.items():
        ab = 0 if kid in loeschen else next(
            (i for i, f in enumerate(liste) if weg & set(f["quellen"])), None)
        if ab is None:
            continue
        # Fassungen sammeln Quellen auf: ab der ersten mit einer entfernten Quelle tragen alle
        # spaeteren sie auch. Wessen Beitrag dabei wegfaellt, wird fuer K wieder offen.
        bleibt = set(liste[ab - 1]["quellen"]) if ab else set()
        verloren[kid] = {u for f in liste[ab:] for u in f["quellen"]} - bleibt
        if liste[ab:]:
            conn.execute("delete from kurs_handbuch_fassung where id = any(%s)",
                         ([f["id"] for f in liste[ab:]],))
        if ab:
            conn.execute("update kurs_handbuch_kapitel set aktuelle_fassung = %s where id = %s",
                         (liste[ab - 1]["id"], kid))
        elif huelle and kid not in loeschen:
            conn.execute("update kurs_handbuch_kapitel set aktuelle_fassung = null "
                         "where id = %s", (kid,))
        else:
            conn.execute("delete from kurs_handbuch_kapitel where id = %s and lead_id = %s",
                         (kid, lead_id))
            geloescht.add(kid)
    if verloren:
        _zuordnungen_oeffnen(conn, lead_id, geloescht, verloren)
    return len(verloren)


def _ausgabe_zuruecknehmen(conn, lead_id: str, inhalt_weg: bool) -> list[str]:
    """Nach einem Rueckbau (in dessen Transaktion): die Ausgabe wird faellig
    (`fassungen_stand` leer). Ohne sichtbares Kapitel geht die Zeile; mit `inhalt_weg` (eine
    Sitzung wurde entfernt) werden die Pfade geleert, weil die Dateien ihren Inhalt tragen.
    Rueckgabe: Dateien, die der Aufrufer nach dem Commit loescht."""
    _handbuch_sperren(conn, lead_id)
    z = conn.execute("select pfad, pdf from kurs_handbuch where lead_id = %s for update",
                     (lead_id,)).fetchone()
    if not z:
        return []
    sichtbar = conn.execute("select 1 from kurs_handbuch_kapitel where lead_id = %s "
                            "and aktuelle_fassung is not null limit 1", (lead_id,)).fetchone()
    if not sichtbar:
        conn.execute("delete from kurs_handbuch where lead_id = %s", (lead_id,))
    elif inhalt_weg:
        conn.execute("update kurs_handbuch set pfad = null, pdf = null, "
                     "fassungen_stand = null where lead_id = %s", (lead_id,))
    else:
        conn.execute("update kurs_handbuch set fassungen_stand = null where lead_id = %s",
                     (lead_id,))
        return []
    return [p for p in (z["pfad"], z["pdf"]) if p]


def _gueltig(lead_id: str) -> str:
    lid = _id(lead_id)
    if lid is None:
        raise ValueError("Lernender ungueltig")
    return lid


def quelle_entfernen(lead_id: str, uid: str) -> int:
    """Sitzung `uid` aus dem Handbuch nehmen (Verschieben aus "Kurse", Loeschen, Neu-Auswertung,
    Lernenden-Wechsel). Jedes Kapitel mit einer Fassung, die `uid` traegt, geht auf die
    juengste Fassung ohne `uid` zurueck (gibt es keine, wird es geloescht, ebenso jedes von
    `uid` angelegte Kapitel); alle Fassungen mit `uid` und die Quelle werden geloescht.
    Spaetere Quellen dieser Kapitel sind wieder offen (gespeicherte Zuordnung bleibt, Verweise
    auf geloeschte Kapitel werden "neu"). Alles in einer Transaktion. Die ausgegebenen Dateien
    tragen den Inhalt und werden sofort geloescht; die Ausgabe ist faellig.
    Rueckgabe: Anzahl betroffener Kapitel."""
    lid = _gueltig(lead_id)
    with server.pool.connection() as conn:
        conn.execute("select 1 from termin_mitschriften where uid = %s for update",
                     (uid,)).fetchall()               # erste Sperre, wie zuordnen/fortschreiben
        betroffen, dateien = quelle_entfernen_in(conn, lid, uid)
    for pfad in dateien:
        mitschrift_bericht.datei_entfernen(pfad)
    return betroffen


def quelle_entfernen_in(conn, lead_id: str, uid: str) -> tuple[int, list[str]]:
    """Wie `quelle_entfernen`, in der Transaktion des Aufrufers (der die Mitschrift-Zeile schon
    gesperrt hat). Rueckgabe: (betroffene Kapitel, Dateien zum Loeschen nach dem Commit)."""
    lid = _gueltig(lead_id)
    conn.execute("select uid from kurs_handbuch_quelle where lead_id = %s for update",
                 (lid,)).fetchall()
    zeile = conn.execute("delete from kurs_handbuch_quelle where lead_id = %s and uid = %s "
                         "returning zuordnung", (lid, uid)).fetchone()
    # von `uid` angelegte Kapitel (auch Huellen, die eine aeltere Sitzung schon fuellt):
    # ihr Titel stammt aus der entfernten Sitzung
    angelegt = {e["kapitel_id"] for e in (_json(zeile["zuordnung"]) if zeile else [])
                if e.get("entscheidung") == "neu" and e.get("kapitel_id")}
    angelegt = {str(r["id"]) for r in conn.execute(
        "select id from kurs_handbuch_kapitel where lead_id = %s and id = any(%s::uuid[])",
        (lid, sorted(angelegt))).fetchall()} if angelegt else set()
    betroffen = _zurueckrollen(conn, lid, {uid}, angelegt, huelle=False)
    dateien = _ausgabe_zuruecknehmen(conn, lid, inhalt_weg=True) if betroffen else []
    if zeile or betroffen:
        log.info("Handbuch-Quelle entfernt lead=%s uid=%s kapitel=%d dateien=%d",
                 _lead8(lid), mitschrift_bericht.uid8(uid), betroffen, len(dateien))
    return betroffen, dateien


def einfuegen_vorbereiten(lead_id: str, uid: str, beginn: datetime) -> None:
    """Vor der Zuordnung einer Sitzung: sind juengere Quellen (nach Termin-Beginn) schon
    eingearbeitet, werden sie zurueckgerollt und wieder offen, damit `uid` an ihrer
    Datumsstelle eingearbeitet wird. Kapitel, die nur aus juengeren Quellen bestehen, bleiben
    als leere Huelle (Titel, Reihenfolge) und werden beim Neu-Einarbeiten wieder gefuellt."""
    lid = _gueltig(lead_id)
    with server.pool.connection() as conn:
        quellen = conn.execute("select uid, beginn from kurs_handbuch_quelle "
                               "where lead_id = %s for update", (lid,)).fetchall()
        juenger = {q["uid"] for q in quellen
                   if q["uid"] != uid and (q["beginn"], q["uid"]) > (beginn, uid)}
        betroffen = _zurueckrollen(conn, lid, juenger, set(), huelle=True) if juenger else 0
        dateien = _ausgabe_zuruecknehmen(conn, lid, inhalt_weg=False) if betroffen else []
    for pfad in dateien:
        mitschrift_bericht.datei_entfernen(pfad)
    if betroffen:
        log.info("Handbuch fuer aeltere Sitzung zurueckgerollt lead=%s uid=%s quellen=%d "
                 "kapitel=%d", _lead8(lid), mitschrift_bericht.uid8(uid), len(juenger),
                 betroffen)


def alles_entfernen(lead_id: str) -> None:
    """Loeschantrag: Handbuch des Lernenden ganz entfernen - Kapitel, Fassungen, Quellen,
    `kurs_handbuch` und die Dateien. Die Wahl als Lernender wird an allen Mitschriften
    geloest, sonst baute der Taktgeber das Handbuch wieder auf. Ungueltige Id: nichts zu tun."""
    lid = _id(lead_id)
    if lid is None:
        return
    with server.pool.connection() as conn:
        # Sperr-Reihenfolge wie ueberall: Mitschriften, Quellen, Handbuch. Ein laufendes
        # zuordnen/fortschreiben sieht danach einen anderen Lernenden und bucht nichts.
        conn.execute("update termin_mitschriften set kurs_lead_id = null "
                     "where kurs_lead_id = %s", (lid,))
        quellen = conn.execute("delete from kurs_handbuch_quelle where lead_id = %s "
                               "returning uid", (lid,)).fetchall()
        kapitel = conn.execute("delete from kurs_handbuch_kapitel where lead_id = %s "
                               "returning id", (lid,)).fetchall()
        _handbuch_sperren(conn, lid)
        zeilen = conn.execute("delete from kurs_handbuch where lead_id = %s returning pfad, pdf",
                              (lid,)).fetchall()
    for z in zeilen:
        mitschrift_bericht.datei_entfernen(z["pfad"])
        mitschrift_bericht.datei_entfernen(z["pdf"])
    if zeilen or kapitel or quellen:
        log.info("Handbuch ganz entfernt lead=%s kapitel=%d quellen=%d", _lead8(lid),
                 len(kapitel), len(quellen))
