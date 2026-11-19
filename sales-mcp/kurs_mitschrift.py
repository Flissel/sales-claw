"""Kursmitschrift: Konstanten, Wahl des Lernenden, Stand (Grundlage fuer das Kurs-Handbuch).

Logs: nie Namen oder Text.
"""
import base64
import io
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image

import bildschirm
import kurs_pdf
import mitschrift_bericht
import ollama
import server
import ui_termin

RUBRIK_KURSE = "Kurse"
MAX_VERSUCHE = 3
NEUVERSUCH_NACH = timedelta(hours=1)
MAX_BILDER_ABSCHNITT = 6
BILD_KANTE = 800
BILD_QUALITAET = 60
MAX_ZULETZT = 5
BESCHREIBUNG_MAX = 300
FASSUNGEN = ("felix", "lernend")
INTERN_HINWEIS = "Intern – enthält Kundendaten, nicht weitergeben"

log = logging.getLogger("kurs_mitschrift")
TZ = mitschrift_bericht.TZ

# Wie mitschrift_bericht.STAND_SQL (Alias m), zusaetzlich mit der Rubrik: ein Wechsel
# der Rubrik aendert den Stand.
KURS_STAND_SQL = ("md5(lower(coalesce(m.rubrik,'')) || '|' || "
                  + mitschrift_bericht.STAND_SQL + ")")


def ist_kurs(rubrik: str | None) -> bool:
    return (rubrik or "").casefold() == RUBRIK_KURSE.casefold()


def _uuid(wert: object) -> str | None:
    try:
        return str(uuid.UUID(str(wert)))
    except ValueError:
        return None


def vorschlaege(uid: str) -> list[dict]:
    """Moegliche Lernende: Teilnehmer (ohne Organisator), danach zuletzt gewaehlte."""
    teilnehmer = server._q(
        "select l.id, l.name from termin_teilnehmer t "
        "join leads l on l.id = coalesce(t.lead_id, "
        "  (select (array_agg(x.id))[1] from leads x where lower(x.email) = lower(t.adresse) "
        "   having count(*) = 1)) "
        "where t.uid = %s and coalesce(t.rolle, '') <> 'organisator' "
        "order by t.ctid", (uid,))
    zuletzt = server._q(
        "select l.id, l.name from termin_mitschriften m join leads l on l.id = m.kurs_lead_id "
        "where m.uid <> %s group by l.id, l.name order by max(m.geholt_am) desc limit %s",
        (uid, MAX_ZULETZT))
    aus: list[dict] = []
    gesehen: set[str] = set()
    for z in list(teilnehmer) + list(zuletzt):
        lid = str(z["id"])
        if lid not in gesehen:
            gesehen.add(lid)
            aus.append({"lead_id": lid, "name": z["name"]})
    return aus


def lernender_setzen(uid: str, lead_id: str | None) -> bool:
    """Lernenden einer Kurs-Mitschrift setzen (None = entfernen). Sonst False. Bei einem
    Wechsel geht die Sitzung zuerst aus dem Handbuch des alten Lernenden (Rueckbau); ins neue
    arbeitet sie der Taktgeber ein. Alles in einer Transaktion unter der Sperre der
    Mitschrift-Zeile (wie zuordnen/fortschreiben): ein laufender KI-Auftrag bucht danach nichts
    mehr fuer den alten Lernenden."""
    import kurs_handbuch  # zirkulaer: kurs_handbuch importiert kurs_mitschrift
    if lead_id is None:
        neu = None
    else:
        neu = _uuid(lead_id)
        if neu is None or not server._q("select 1 from leads where id = %s", (neu,)):
            return False
    dateien: list[str] = []
    with server.pool.connection() as conn:
        z = conn.execute("select rubrik from termin_mitschriften where uid = %s for update",
                         (uid,)).fetchone()
        if not z or not ist_kurs(z["rubrik"]):
            return False
        for alt in kurs_handbuch.lernende_mit_quelle(uid, conn):
            if alt != neu:
                dateien += kurs_handbuch.quelle_entfernen_in(conn, alt, uid)[1]
        conn.execute("update termin_mitschriften set kurs_lead_id = %s where uid = %s",
                     (neu, uid))
    for pfad in dateien:
        mitschrift_bericht.datei_entfernen(pfad)
    return True


def kurs_stand(uid: str) -> str | None:
    z = server._q(f"select {KURS_STAND_SQL} as s from termin_mitschriften m where m.uid = %s",
                  (uid,))
    return z[0]["s"] if z else None


# ---------- Kursmitschrift erzeugen ----------

KURS_SYSTEM = """Du bekommst das Transkript einer Online-Schulung (Segmente mit Zeit und Sprecher) und die \
Bildschirmbilder dazu (bild_id, Zeitfenster von/bis, Beschreibung). Mache daraus eine Kursmitschrift, \
mit der die Lernenden den Kurs allein nacharbeiten koennen.

Regeln:
- Sprich die Lernenden direkt an (Du). Kein Fachjargon; schwierige Begriffe in einfachen Worten erklaeren.
- Gliedere in Abschnitte mit sprechendem Titel (z. B. "Termin anlegen").
- Fasse je Bild zusammen, was gesprochen wurde, waehrend das Bild zu sehen war (Feld "erklaert"); \
"zu_sehen" beschreibt in einem Satz, was auf dem Bild zu sehen ist.
- "schritte" nur, wenn etwas vorgefuehrt wurde (z. B. "Oben rechts auf ... klicken"); sonst eine leere Liste.
- Ein Bild darfst Du weglassen, wenn es nichts beitraegt. Verwende ausschliesslich bild_id-Werte aus der \
Eingabe, erfinde keine.
- "merken": je Abschnitt 1 bis 3 Saetze, die man sich merken soll.
- "offen": Fragen der Lernenden, Stellen, an denen sie haengen blieb, und Nacharbeit fuer den Kursleiter.
- Erfinde nichts, was im Transkript nicht vorkommt.

Antworte ausschliesslich mit JSON in genau dieser Form:
{"ueberblick": "3-5 Saetze",
 "abschnitte": [{"titel": "...",
                 "bilder": [{"bild_id": "...", "zu_sehen": "1 Satz", "erklaert": "Zusammenfassung",
                             "schritte": ["...", "..."]}],
                 "merken": ["..."]}],
 "offen": ["..."]}"""


def _zeitstempel(wert) -> str | None:
    if wert is None:
        return None
    t = wert if wert.tzinfo else wert.replace(tzinfo=timezone.utc)
    return t.astimezone(TZ).strftime("%H:%M:%S")


def kurs_eingabe(uid: str) -> dict:
    """Titel, Datum, Segmente und gepruefte Bilder (mit Zeitfenster) fuer den KI-Auftrag."""
    z = server._q("select a.titel, a.thema, a.beginn, m.segmente from termin_mitschriften m "
                  "join termin_akten a on a.uid = m.uid where m.uid = %s", (uid,))
    if not z:
        raise ValueError("keine Mitschrift")
    z = z[0]
    segmente = [{"zeit": mitschrift_bericht._zeit(s.get("beginn")),
                 "sprecher": s.get("sprecher") or "?", "text": s.get("text") or ""}
                for s in mitschrift_bericht._liste(z["segmente"]) if isinstance(s, dict)]
    bilder = [{"bild_id": str(b["id"]), "von": _zeitstempel(b["aufgenommen_am"]),
               "bis": _zeitstempel(b.get("bis")),
               "beschreibung": (b.get("beschreibung") or "")[:BESCHREIBUNG_MAX]}
              for b in bildschirm.bilder(uid)]
    datum = z["beginn"].astimezone(TZ).strftime("%d.%m.%Y") if z["beginn"] else ""
    return {"titel": z["titel"] or z["thema"] or "Termin", "datum": datum,
            "segmente": segmente, "bilder": bilder}


def _text(wert) -> str:
    return wert.strip() if isinstance(wert, str) else ""


def _texte(wert) -> list[str]:
    if not isinstance(wert, list):
        return []
    return [t for t in (_text(x) for x in wert) if t]


def _ausduennen(liste: list, n: int) -> list:
    """Gleichmaessig auf hoechstens n Eintraege kuerzen."""
    if len(liste) <= n:
        return liste
    schritt = len(liste) / n
    return [liste[int(i * schritt)] for i in range(n)]


def pruefen(roh: object, bild_ids: set[str]) -> dict:
    """KI-Antwort pruefen und auf die erwartete Form bringen; ValueError, wenn unbrauchbar."""
    if not isinstance(roh, dict) or not isinstance(roh.get("abschnitte"), list) \
            or not roh["abschnitte"]:
        raise ValueError("keine Abschnitte")
    abschnitte = []
    for ab in roh["abschnitte"]:
        if not isinstance(ab, dict) or not _text(ab.get("titel")):
            continue
        bilder, gesehen = [], set()
        for b in ab.get("bilder") if isinstance(ab.get("bilder"), list) else []:
            bid = str(b.get("bild_id")) if isinstance(b, dict) else ""
            if bid not in bild_ids or bid in gesehen:
                continue
            gesehen.add(bid)
            bilder.append({"bild_id": bid, "zu_sehen": _text(b.get("zu_sehen")),
                           "erklaert": _text(b.get("erklaert")),
                           "schritte": _texte(b.get("schritte"))})
        abschnitte.append({"titel": _text(ab["titel"]),
                           "bilder": _ausduennen(bilder, MAX_BILDER_ABSCHNITT),
                           "merken": _texte(ab.get("merken"))})
    if not abschnitte:
        raise ValueError("kein Abschnitt mit Titel")
    return {"ueberblick": _text(roh.get("ueberblick")), "abschnitte": abschnitte,
            "offen": _texte(roh.get("offen"))}


def erzeugen(uid: str, jetzt: datetime) -> dict:
    """KI-Auftrag + Pruefung; speichert kurs_json und Stand. Bei Fehler Versuch zaehlen
    (nach MAX_VERSUCHE kurs_status = 'fehler') und die Ausnahme weiterreichen."""
    try:
        stand = kurs_stand(uid)
        eingabe = kurs_eingabe(uid)
        antwort = ollama.chat(KURS_SYSTEM, json.dumps(eingabe, ensure_ascii=False),
                              als_json=True)
        ergebnis = pruefen(json.loads(antwort), {b["bild_id"] for b in eingabe["bilder"]})
    except Exception as err:
        server._q("update termin_mitschriften set kurs_versuche = kurs_versuche + 1, "
                  "kurs_am = %s, kurs_status = case when kurs_versuche + 1 >= %s "
                  "then 'fehler' else kurs_status end where uid = %s returning id",
                  (jetzt, MAX_VERSUCHE, uid))
        log.warning("Kursmitschrift fehlgeschlagen uid=%s (%s)",
                    mitschrift_bericht.uid8(uid), type(err).__name__)
        raise
    server._q("update termin_mitschriften set kurs_json = %s::jsonb, kurs_stand = %s, "
              "kurs_am = %s, kurs_versuche = 0, kurs_status = null where uid = %s returning id",
              (json.dumps(ergebnis, ensure_ascii=False), stand, jetzt, uid))
    log.info("Kursmitschrift erzeugt uid=%s abschnitte=%d", mitschrift_bericht.uid8(uid),
             len(ergebnis["abschnitte"]))
    return ergebnis


# ---------- HTML (zwei Fassungen) ----------

KURS_CSS = mitschrift_bericht.CSS + """
nav.inhalt { background: var(--flaeche); border: 1px solid var(--linie); border-radius: 6px; padding: .4rem 1rem; }
.abschnitt { margin-bottom: 1.8rem; }
.bildblock { break-inside: avoid; margin: 1rem 0; }
.bildblock figure { max-width: 720px; }
.merken { background: #eef6ee; border: 1px solid #b9d9b9; border-radius: 6px; padding: .2rem 1rem; break-inside: avoid; }
.merken h3 { margin: .5rem 0 .2rem; font-size: 1rem; }"""


def _kurs_bild_uri(uid: str, bid: str) -> str | None:
    roh = bildschirm.bild_daten(uid, bid)
    if not roh:
        return None
    im = Image.open(io.BytesIO(roh)).convert("RGB")
    im.thumbnail((BILD_KANTE, BILD_KANTE))
    puffer = io.BytesIO()
    im.save(puffer, "JPEG", quality=BILD_QUALITAET, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode()


def kurs_html(uid: str, fassung: str) -> str:
    if fassung not in FASSUNGEN:
        raise ValueError("unbekannte Fassung")
    e = ui_termin._e
    z = server._q("select a.titel, a.thema, a.beginn, m.rubrik, m.kurs_json "
                  "from termin_mitschriften m join termin_akten a on a.uid = m.uid "
                  "where m.uid = %s", (uid,))
    if not z or not z[0]["kurs_json"]:
        raise ValueError("keine Kursmitschrift")
    z = z[0]
    kj = z["kurs_json"]
    kj = json.loads(kj) if isinstance(kj, str) else kj
    zeiten = {str(b["id"]): b["aufgenommen_am"] for b in bildschirm.bilder(uid)}
    titel = z["titel"] or z["thema"] or "Kurs"
    datum = z["beginn"].astimezone(TZ).strftime("%d.%m.%Y") if z["beginn"] else ""
    meta = mitschrift_bericht._verbinden(e(z["rubrik"] or ""), e(datum))

    inhalt = "".join(f'<li><a href="#a{i}">{e(a["titel"])}</a></li>'
                     for i, a in enumerate(kj["abschnitte"], 1))
    abschnitte = []
    for i, a in enumerate(kj["abschnitte"], 1):
        teile = [f'<section class="abschnitt" id="a{i}"><h2>{e(a["titel"])}</h2>']
        for b in a["bilder"]:
            uri = _kurs_bild_uri(uid, b["bild_id"])
            teil = ['<div class="bildblock">']
            if uri:
                unter = (e(zeiten[b["bild_id"]].astimezone(TZ).strftime("%H:%M"))
                         if b["bild_id"] in zeiten else "")
                teil.append(f'<figure><img src="{uri}" alt="Bildschirm">'
                            f'<figcaption>{unter}</figcaption></figure>')
            if b["zu_sehen"]:
                teil.append(f'<p><strong>Zu sehen:</strong> {e(b["zu_sehen"])}</p>')
            if b["erklaert"]:
                teil.append(f'<p><strong>Erklärt:</strong> {e(b["erklaert"])}</p>')
            if b["schritte"]:
                teil.append("<ol>" + "".join(f"<li>{e(s)}</li>" for s in b["schritte"]) + "</ol>")
            teil.append("</div>")
            teile.append("".join(teil))
        if a["merken"]:
            teile.append('<aside class="merken"><h3>Merken</h3><ul>'
                         + "".join(f"<li>{e(m)}</li>" for m in a["merken"]) + "</ul></aside>")
        teile.append("</section>")
        abschnitte.append("".join(teile))

    intern = ""
    offen = ""
    if fassung == "felix":
        intern = f'<p class="intern">{e(INTERN_HINWEIS)}</p>\n'
        liste = ("<ul>" + "".join(f"<li>{e(o)}</li>" for o in kj["offen"]) + "</ul>"
                 if kj["offen"] else '<p class="meta">Nichts offen.</p>')
        offen = f"<h2>Offen / nachfragen</h2>\n{liste}\n"
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{e(titel)}</title>\n<style>\n{KURS_CSS}\n</style></head><body>\n'
        f'{intern}<h1>{e(titel)}</h1>\n<p class="meta">{meta}</p>\n'
        f'<nav class="inhalt"><h2>Inhalt</h2><ol>{inhalt}</ol></nav>\n'
        f'<h2>Überblick</h2>\n<p>{e(kj["ueberblick"])}</p>\n'
        + "\n".join(abschnitte) + f'\n{offen}</body></html>')


# ---------- Ablage ----------

_DATEI_SPALTEN = ("kurs_pfad", "kurs_pfad_lernend", "kurs_pdf")


def ablegen(uid: str) -> str:
    """Drei Dateien im Rubrik-Ordner ablegen, dann buchen. Das PDF entsteht zuerst: schlaegt
    es fehl (PdfFehler), wird nichts geschrieben und nichts gebucht (kurs_status bleibt leer,
    ein spaeterer Aufruf versucht es erneut)."""
    z = server._q("select m.rubrik, m.kurs_json, m.kurs_pfad, m.kurs_pfad_lernend, m.kurs_pdf, "
                  "a.titel, a.thema, a.beginn from termin_mitschriften m "
                  "join termin_akten a on a.uid = m.uid where m.uid = %s", (uid,))
    if not z or not z[0]["kurs_json"]:
        raise ValueError("keine Kursmitschrift")
    z = z[0]
    rubrik = mitschrift_bericht.rubrik_normalisieren(z["rubrik"])
    if rubrik is None:
        raise ValueError("keine gueltige Rubrik")
    stamm = mitschrift_bericht.dateiname(z["titel"] or z["thema"], z["beginn"], uid)[:-len(".html")]
    rel = {"kurs_pfad": f"{rubrik}/{stamm}_kurs-intern.html",
           "kurs_pfad_lernend": f"{rubrik}/{stamm}_kurs.html",
           "kurs_pdf": f"{rubrik}/{stamm}_kurs.pdf"}
    ziel = {k: mitschrift_bericht.sicherer_pfad(r) for k, r in rel.items()}
    if any(p is None for p in ziel.values()):
        raise ValueError("Ablagepfad ungueltig")
    lernend = kurs_html(uid, "lernend")
    inhalt = {"kurs_pfad": kurs_html(uid, "felix"), "kurs_pfad_lernend": lernend,
              "kurs_pdf": kurs_pdf.pdf_aus_html(lernend)}
    neu = [k for k in _DATEI_SPALTEN if rel[k] != z[k]]
    try:
        for k in _DATEI_SPALTEN:
            kurs_pdf.schreiben(ziel[k], inhalt[k])
        gebucht = server._q(
            "update termin_mitschriften set kurs_pfad = %s, kurs_pfad_lernend = %s, "
            "kurs_pdf = %s, kurs_status = 'fertig' where uid = %s and kurs_json is not null "
            "returning kurs_status", (rel["kurs_pfad"], rel["kurs_pfad_lernend"],
                                      rel["kurs_pdf"], uid))
        if not gebucht:
            raise ValueError("Kursmitschrift nicht mehr vorhanden")
    except Exception:
        for k in neu:
            ziel[k].unlink(missing_ok=True)
        raise
    for k in _DATEI_SPALTEN:
        if z[k] and z[k] != rel[k]:
            mitschrift_bericht.datei_entfernen(z[k])
    log.info("Kursmitschrift abgelegt uid=%s", mitschrift_bericht.uid8(uid))
    return gebucht[0]["kurs_status"]


def entfernen_dateien(uid: str) -> None:
    z = server._q("select kurs_pfad, kurs_pfad_lernend, kurs_pdf from termin_mitschriften "
                  "where uid = %s", (uid,))
    if not z:
        return
    for k in _DATEI_SPALTEN:
        mitschrift_bericht.datei_entfernen(z[0][k])
    server._q("update termin_mitschriften set kurs_pfad = null, kurs_pfad_lernend = null, "
              "kurs_pdf = null, kurs_json = null, kurs_stand = null, kurs_status = null "
              "where uid = %s returning id", (uid,))


def entfernen(uid: str) -> None:
    """Kursmitschrift einer Sitzung ganz entfernen (Loeschen, Verschieben aus "Kurse",
    Neu-Auswertung): erst aus jedem Handbuch nehmen (Rueckbau; die Ausgabe erneuert der
    Taktgeber), dann Dateien und Buchung. Eine Transaktion; Dateien gehen nach dem Commit.
    Ohne Kursmitschrift: nichts zu tun (wiederholbar)."""
    with server.pool.connection() as conn:
        dateien = entfernen_in(conn, uid)
    for pfad in dateien:
        mitschrift_bericht.datei_entfernen(pfad)


def entfernen_in(conn, uid: str) -> list[str]:
    """Wie `entfernen`, in der Transaktion des Aufrufers (z. B. Verschieben: Rubrik und
    Rueckbau zusammen oder gar nicht). Rueckgabe: Dateien zum Loeschen nach dem Commit."""
    import kurs_handbuch  # zirkulaer: kurs_handbuch importiert kurs_mitschrift
    z = conn.execute("select kurs_pfad, kurs_pfad_lernend, kurs_pdf from termin_mitschriften "
                     "where uid = %s for update", (uid,)).fetchone()
    dateien: list[str] = []
    for lead_id in kurs_handbuch.lernende_mit_quelle(uid, conn):
        dateien += kurs_handbuch.quelle_entfernen_in(conn, lead_id, uid)[1]
    if z:
        dateien += [z[k] for k in _DATEI_SPALTEN if z[k]]
        conn.execute("update termin_mitschriften set kurs_pfad = null, kurs_pfad_lernend = null, "
                     "kurs_pdf = null, kurs_json = null, kurs_stand = null, kurs_status = null "
                     "where uid = %s", (uid,))
    return dateien
