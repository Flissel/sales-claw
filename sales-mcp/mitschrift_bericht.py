"""Interner HTML-Bericht je Mitschrift: erzeugen und als Datei je Rubrik ablegen.

Die Datei ist die Ablage, die Datenbank fuehrt Buch (termin_mitschriften.bericht_*).
Schreiben: Datei temporaer + os.replace, dann Datenbank, dann alte Datei entfernen.
Logs: nur gekuerzte uid, Zaehler, Fehlerart; nie Titel, Namen oder Text.
"""
import base64
import hashlib
import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

import bildschirm
import server
import ui_termin

log = logging.getLogger("mitschrift_bericht")

UNSORTIERT = "Unsortiert"
# Kurs-Handbuecher (kurs_handbuch): kein Rubrikordner. Eine Rubrik kann nie so heissen,
# rubrik_normalisieren macht aus "_" ein Leerzeichen.
HANDBUCH_ORDNER = "_handbuecher"
TZ = ZoneInfo("Europe/Berlin")
MAX_JE_THEMA = 6
RUBRIK_MAX = 40
TITEL_MAX = 40

STAND_SQL = ("md5(coalesce(m.auswertung_am::text,'') || '|' || coalesce((select "
             "string_agg(b.id::text, ',' order by b.id) from termin_bilder b "
             "where b.uid = m.uid and b.beschreibung_status = 'fertig'), ''))")


def ordner() -> Path:
    return Path(os.environ.get("MITSCHRIFTEN_PFAD", "/mitschriften"))


def uid8(uid: str) -> str:
    return hashlib.sha256(str(uid).encode()).hexdigest()[:8]


def rubrik_normalisieren(name: object) -> str | None:
    """Nur Buchstaben (inkl. Umlaute/ss), Ziffern, Leerzeichen, Bindestrich; max. 40 Zeichen."""
    if not isinstance(name, str):
        return None
    s = re.sub(r"[^\w -]|_", " ", name)
    s = re.sub(r"\s+", " ", s).strip(" -")
    s = s[:RUBRIK_MAX].strip(" -")
    return s if re.search(r"[^\W_]", s) else None


def rubrik_angleichen(name: str, vorhandene: list[str]) -> str:
    for v in vorhandene:
        if v.casefold() == name.casefold():
            return v
    return name


def _titel_kurz(titel: str | None) -> str:
    s = (titel or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:TITEL_MAX].strip("-")
    return s or "termin"


def dateiname(titel: str | None, beginn: datetime | None, uid: str) -> str:
    if beginn is not None:
        b = beginn if beginn.tzinfo else beginn.replace(tzinfo=timezone.utc)
        zeit = b.astimezone(TZ).strftime("%Y-%m-%d_%H%M")
    else:
        zeit = "ohne-datum"
    return f"{zeit}_{_titel_kurz(titel)}_{uid8(uid)}.html"


def stand(uid: str) -> str | None:
    z = server._q(f"select {STAND_SQL} as s from termin_mitschriften m where m.uid = %s",
                  (uid,))
    return z[0]["s"] if z else None


def _zeit(iso) -> str:
    try:
        return (datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
                .astimezone(TZ).strftime("%H:%M:%S"))
    except ValueError:
        return ""


def _bild_uri(uid: str, bid: str) -> str | None:
    roh = bildschirm.bild_daten(uid, bid)
    if not roh:
        return None
    im = Image.open(io.BytesIO(roh)).convert("RGB")
    im.thumbnail((1000, 1000))
    puffer = io.BytesIO()
    im.save(puffer, "JPEG", quality=70, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode()


CSS = """:root { --schrift:#1d1d1f; --blass:#6b6b70; --linie:#e2e2e6; --flaeche:#f6f6f8; }
body { font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--schrift);
  background: #fff; max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 1.6rem; margin: 0 0 .2rem; } h2 { margin-top: 2.2rem; border-bottom: 1px solid var(--linie); padding-bottom: .3rem; }
.meta { color: var(--blass); font-size: .9rem; margin: .1rem 0 .6rem; }
.intern { display:inline-block; background:#fff3cd; border:1px solid #e6c65c; padding:.15rem .5rem; border-radius:4px; font-size:.85rem; }
.thema { break-inside: avoid; margin-bottom: 1.4rem; }
.bilder { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
figure { margin: 0; border: 1px solid var(--linie); border-radius: 6px; overflow: hidden; background: var(--flaeche); break-inside: avoid; }
figure img { width: 100%; display: block; }
figcaption { font-size: .8rem; color: var(--blass); padding: .4rem .55rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
td { border-top: 1px solid var(--linie); padding: .3rem .4rem; vertical-align: top; }
td.z { color: var(--blass); white-space: nowrap; font-variant-numeric: tabular-nums; }
td.s { font-weight: 600; white-space: nowrap; }
@media print { body { max-width: none; padding: 0; } h2 { break-after: avoid; } }"""


def _liste(wert) -> list:
    if isinstance(wert, str):
        try:
            wert = json.loads(wert or "[]")
        except ValueError:
            return []
    return wert if isinstance(wert, list) else []


def _verbinden(*teile: str) -> str:
    """Nur nicht leere Teile verbinden (sonst beginnt die Zeile mit ' · ')."""
    return " · ".join(t for t in teile if t)


def bericht_html(uid: str) -> str:
    e = ui_termin._e
    a = server._q("select titel, thema, beginn, plattform, bilder_uebersprungen "
                  "from termin_akten where uid = %s", (uid,))
    m = server._q("select segmente, auswertung_md, auswertung_json, auswertung_status, rubrik "
                  "from termin_mitschriften where uid = %s", (uid,))
    if not a or not m or m[0]["auswertung_status"] != "fertig":
        raise ValueError("keine fertige Auswertung")
    a, m = a[0], m[0]
    seg = [s for s in _liste(m["segmente"]) if isinstance(s, dict)]
    aj = m["auswertung_json"]
    aj = json.loads(aj) if isinstance(aj, str) else (aj or {})
    bilder = bildschirm.bilder(uid)
    nach_id = {str(b["id"]): b for b in bilder}

    themen = []
    for v in (aj.get("verlauf") if isinstance(aj, dict) else None) or []:
        if not isinstance(v, dict):
            continue
        von, bis = v.get("von"), v.get("bis")
        if not (isinstance(von, int) and isinstance(bis, int) and 0 <= von <= bis < len(seg)):
            continue
        ids = bildschirm.bilder_zu_abschnitt(seg, von, bis, bilder)
        if len(ids) > MAX_JE_THEMA:  # gleichmaessig ausduennen
            schritt = len(ids) / MAX_JE_THEMA
            ids = [ids[int(i * schritt)] for i in range(MAX_JE_THEMA)]
        karten = []
        for bid in ids:
            uri = _bild_uri(uid, bid)
            if not uri:
                continue
            b = nach_id[bid]
            unter = e(b["aufgenommen_am"].astimezone(TZ).strftime("%H:%M"))
            if b.get("beschreibung"):
                unter += " – " + e(b["beschreibung"][:220])
            karten.append(f'<figure><img src="{uri}" alt="Bildschirm">'
                          f'<figcaption>{unter}</figcaption></figure>')
        themen.append(f'<section class="thema"><h3>{e(v.get("thema") or "Thema")}</h3>'
                      f'<p class="meta">Segmente {von}–{bis}</p>'
                      + (f'<div class="bilder">{"".join(karten)}</div>' if karten else "")
                      + "</section>")

    zeilen = "".join(
        f'<tr><td class="z">{e(_zeit(s.get("beginn")))}</td>'
        f'<td class="s">{e(s.get("sprecher") or "?")}</td><td>{e(s.get("text"))}</td></tr>'
        for s in seg)
    titel = a["titel"] or a["thema"] or "Termin"
    datum = a["beginn"].astimezone(TZ).strftime("%d.%m.%Y, %H:%M") if a["beginn"] else ""
    kopf = _verbinden(e(datum), e(a["plattform"] or ""), e(m["rubrik"] or ""))
    meta = _verbinden(
        kopf, f"{len(seg)} Segmente", f"{len(bilder)} Standbilder",
        f'{int(a["bilder_uebersprungen"] or 0)} heikle Bildschirme nicht gespeichert')
    erstellt = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>Terminbericht – {e(titel)}</title>\n<style>\n{CSS}\n</style></head><body>\n'
        '<p class="intern">Intern – enthält Kundendaten, nicht weitergeben</p>\n'
        f'<h1>{e(titel)}</h1>\n'
        f'<p class="meta">{meta}</p>\n'
        f'<h2>Auswertung</h2>\n<div>{ui_termin._md(m["auswertung_md"] or "")}</div>\n'
        '<h2>Bilder je Thema</h2>\n'
        f'<p class="meta">Höchstens {MAX_JE_THEMA} Bilder je Thema, verkleinert.</p>\n'
        + ("".join(themen) or '<p class="meta">Keine Bilder.</p>') + '\n'
        '<h2>Transkript</h2>\n'
        '<p class="meta">Bereinigt; „?“ = Sprecher nicht erkannt. Zeiten in Berliner Zeit.</p>\n'
        f'<table>{zeilen}</table>\n'
        f'<p class="meta">Erstellt {erstellt} aus sales-claw.</p>\n</body></html>')


def sicherer_pfad(pfad: str) -> Path | None:
    """Aufgeloester Pfad nur, wenn er unter ordner() liegt (nie der Ordner selbst)."""
    if not pfad or not isinstance(pfad, str):
        return None
    basis = ordner().resolve()
    ziel = (basis / pfad).resolve()
    if ziel == basis or not ziel.is_relative_to(basis):
        return None
    return ziel


def datei_entfernen(pfad: str | None) -> None:
    if not pfad:
        return
    ziel = sicherer_pfad(pfad)
    if ziel is None:
        log.warning("Bericht-Pfad ausserhalb der Ablage verweigert")
        return
    try:
        ziel.unlink(missing_ok=True)
    except OSError as err:
        log.warning("Bericht-Datei nicht entfernt (%s)", type(err).__name__)


def ablegen(uid: str) -> str | None:
    z = server._q("select m.rubrik, m.bericht_pfad, a.titel, a.thema, a.beginn "
                  "from termin_mitschriften m join termin_akten a on a.uid = m.uid "
                  "where m.uid = %s", (uid,))
    if not z:
        return None
    z = z[0]
    rubrik = rubrik_normalisieren(z["rubrik"])
    if rubrik is None:
        return None
    vorher_stand = stand(uid)
    html = bericht_html(uid)
    rel = f"{rubrik}/{dateiname(z['titel'] or z['thema'], z['beginn'], uid)}"
    ziel = sicherer_pfad(rel)
    if ziel is None:
        return None
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    try:
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, ziel)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    try:
        gebucht = server._q(
            "update termin_mitschriften set bericht_pfad = %s, bericht_am = now(), "
            "bericht_stand = %s where uid = %s and auswertung_status = 'fertig' returning id",
            (rel, vorher_stand, uid))
    except Exception:
        if rel != z["bericht_pfad"]:
            ziel.unlink(missing_ok=True)
        raise
    if not gebucht:
        ziel.unlink(missing_ok=True)
        return None
    if z["bericht_pfad"] and z["bericht_pfad"] != rel:
        datei_entfernen(z["bericht_pfad"])
    log.info("Bericht abgelegt uid=%s", uid8(uid))
    return rel


def verschieben(uid: str, rubrik: str) -> str | None:
    """Von Hand in eine Rubrik legen (auch eine neue). Speichert den normalisierten,
    an vorhandene angeglichenen Namen (der Taktgeber vergleicht den Ordnernamen mit
    der gespeicherten Rubrik), setzt rubrik_manuell und legt die Datei neu ab.
    None bei ungueltigem Namen oder fehlender Mitschrift. Ein Fehler beim Ablegen
    wird weitergereicht; die Rubrik bleibt dann gespeichert (der Takt baut neu).
    Aus "Kurse" heraus: Kursmitschrift und Handbuch-Quelle gehen in derselben Transaktion
    wie der Rubrikwechsel (scheitert der Rueckbau, bleibt die Rubrik), Dateien danach."""
    import kurs_mitschrift  # zirkulaer: kurs_mitschrift importiert mitschrift_bericht
    name = rubrik_normalisieren(rubrik)
    if name is None:
        return None
    vorhandene = [z["rubrik"] for z in server._q(
        "select distinct rubrik from termin_mitschriften where rubrik is not null "
        "order by rubrik")]
    name = rubrik_angleichen(name, [UNSORTIERT] + vorhandene)
    with server.pool.connection() as conn:
        alt = conn.execute("select rubrik from termin_mitschriften where uid = %s for update",
                           (uid,)).fetchone()
        if not alt:
            return None
        dateien = kurs_mitschrift.entfernen_in(conn, uid) \
            if kurs_mitschrift.ist_kurs(alt["rubrik"]) and not kurs_mitschrift.ist_kurs(name) \
            else []
        conn.execute("update termin_mitschriften set rubrik = %s, rubrik_manuell = true "
                     "where uid = %s", (name, uid))
    for pfad in dateien:
        datei_entfernen(pfad)
    ablegen(uid)
    return name


# ---------- Abgleich Datei <-> Buchung (Taktgeber, hoechstens stuendlich) ----------

BERICHT_MUSTER = re.compile(r"^.+_[0-9a-f]{8}\.html$")
# Rest eines abgebrochenen ablegen() (Absturz zwischen Schreiben und os.replace)
TMP_MUSTER = re.compile(r"^.+_[0-9a-f]{8}\.html\.tmp$")
# Kursmitschrift im Rubrikordner (kurs_pfad / kurs_pfad_lernend / kurs_pdf)
_KURS = r".+_[0-9a-f]{8}_kurs(?:-intern\.html|\.html|\.pdf)"
KURS_MUSTER = re.compile(rf"^{_KURS}$")
# Handbuch in HANDBUCH_ORDNER (kurs_handbuch.pfad / pdf)
_HANDBUCH = r"handbuch-[0-9a-f]{8}\.(?:html|pdf)"
HANDBUCH_MUSTER = re.compile(rf"^{_HANDBUCH}$")
# Rest eines abgebrochenen kurs_pdf.schreiben() (".<name>.<pid>.tmp")
KURS_TMP_MUSTER = re.compile(rf"^\.{_KURS}\.\d+\.tmp$")
HANDBUCH_TMP_MUSTER = re.compile(rf"^\.{_HANDBUCH}\.\d+\.tmp$")
# Eben geschriebene Dateien bleiben: ablegen() schreibt erst die Datei, dann die Buchung.
SCHONFRIST_S = 600


def _beschreibbar(basis: Path) -> bool:
    return basis.is_dir() and os.access(basis, os.W_OK | os.X_OK)


def _unterordner(basis: Path) -> list[Path]:
    """Rubrikordner (ohne HANDBUCH_ORDNER)."""
    return [d for d in basis.iterdir()
            if d.is_dir() and not d.is_symlink() and not d.name.startswith(".")
            and d.name != HANDBUCH_ORDNER]


def _dateien(ordner: Path, muster: re.Pattern) -> list[Path]:
    return [f for f in ordner.iterdir()
            if muster.match(f.name) and f.is_file() and not f.is_symlink()]


def abgleichen() -> dict:
    """Waisen loeschen, Buchungen fehlender Berichte zuruecksetzen, leere Rubrikordner
    entfernen. Neu erzeugt der Taktgeber die zurueckgesetzten einzeln (einer je Runde),
    damit der Abgleich die Runde nicht aufhaelt.

    Vorsichtig: nur Dateien nach BERICHT_MUSTER/KURS_MUSTER in direkten Rubrikordnern
    und nach HANDBUCH_MUSTER in HANDBUCH_ORDNER (gebucht nur ueber kurs_handbuch); laeuft
    nicht, wenn der Ordner fehlt, nicht beschreibbar ist oder keine einzige
    erwartete Datei enthaelt (Zeichen fuer einen falsch eingehaengten Ordner).
    """
    basis = ordner()
    if not _beschreibbar(basis):
        log.warning("Abgleich uebersprungen: Ablage fehlt oder ist nicht beschreibbar")
        return {"uebersprungen": "ordner"}
    gebucht = server._q("select uid, bericht_pfad from termin_mitschriften "
                        "where bericht_pfad is not null order by uid")
    erwartet = {z["bericht_pfad"] for z in gebucht} | {z["p"] for z in server._q(
        "select p from (select kurs_pfad p from termin_mitschriften "
        "union all select kurs_pfad_lernend from termin_mitschriften "
        "union all select kurs_pdf from termin_mitschriften "
        "union all select pfad from kurs_handbuch "
        "union all select pdf from kurs_handbuch) x where p is not null")}
    dateien: dict[str, Path] = {}
    tmps: list[Path] = []
    for unter in _unterordner(basis):
        for f in _dateien(unter, BERICHT_MUSTER) + _dateien(unter, KURS_MUSTER):
            dateien[f"{unter.name}/{f.name}"] = f
        tmps += _dateien(unter, TMP_MUSTER) + _dateien(unter, KURS_TMP_MUSTER)
    hb = basis / HANDBUCH_ORDNER
    if hb.is_dir() and not hb.is_symlink():
        for f in _dateien(hb, HANDBUCH_MUSTER):
            dateien[f"{HANDBUCH_ORDNER}/{f.name}"] = f
        tmps += _dateien(hb, HANDBUCH_TMP_MUSTER)
    if not erwartet & dateien.keys():
        # ohne jede Buchung ist das normal (noch kein Bericht), sonst ein Warnzeichen
        (log.warning if erwartet else log.info)(
            "Abgleich uebersprungen: keine erwartete Datei in der Ablage (gebucht=%d)",
            len(erwartet))
        return {"uebersprungen": "keine erwartete Datei"}

    geloescht = tmp_geloescht = zurueck = entfernt = 0
    grenze = time.time() - SCHONFRIST_S
    for rel, f in dateien.items():
        if rel in erwartet:
            continue
        try:
            if f.stat().st_mtime > grenze:
                continue
            f.unlink()
            geloescht += 1
        except OSError as err:
            log.warning("Abgleich: Waise nicht entfernt (%s)", type(err).__name__)

    for f in tmps:
        try:
            if f.stat().st_mtime > grenze:
                continue
            f.unlink()
            tmp_geloescht += 1
        except OSError as err:
            log.warning("Abgleich: Temp-Datei nicht entfernt (%s)", type(err).__name__)

    for z in gebucht:
        ziel = sicherer_pfad(z["bericht_pfad"])
        if ziel is not None and ziel.is_file():
            continue
        if server._q("update termin_mitschriften set bericht_pfad = null, bericht_stand = null, "
                     "bericht_am = null where uid = %s and bericht_pfad = %s returning id",
                     (z["uid"], z["bericht_pfad"])):
            zurueck += 1

    for unter in _unterordner(basis):
        try:
            unter.rmdir()  # nur leere
            entfernt += 1
        except OSError:
            pass
    log.info("Abgleich: geloescht=%d tmp_geloescht=%d zurueckgesetzt=%d ordner_entfernt=%d",
             geloescht, tmp_geloescht, zurueck, entfernt)
    return {"geloescht": geloescht, "tmp_geloescht": tmp_geloescht, "zurueckgesetzt": zurueck, "ordner_entfernt": entfernt}
