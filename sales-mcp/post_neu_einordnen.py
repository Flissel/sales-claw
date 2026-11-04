"""Neu-Sortierung des Altbestands der Post-Sammelstelle (Plan Post-Einordnung v2, Task 7).

Drei Schritte, jeder einzeln aufrufbar:

  vorschau   ordnet die alten Mails (einordnung_version < 2) mit der neuen Logik
             ein und legt das Ergebnis NUR in `post_mails.vorschau` ab. Die echten
             Spalten bleiben unberuehrt: Felix sieht erst den Bericht, dann
             entscheidet er.
  bericht    nur Zahlen und Domains (nie Betreff, Text oder volle Adressen), so
             dass der Bericht ohne Bedenken im Terminal stehen darf.
  anwenden   kopiert die Vorschau in die echten Spalten. Kein Modellaufruf.

Aufruf im Container: `python -m post_neu_einordnen vorschau [--alle] | bericht | anwenden`
(siehe deploy/post-neu-einordnen.sh).

Mensch geht vor: Eine Zeile mit einordnung_quelle = 'mensch' fasst nichts davon an -
auch dann nicht, wenn Felix sie erst NACH der Vorschau korrigiert hat. Deshalb steht
die Bedingung in der WHERE-Klausel des Updates, nicht in einem vorher gelesenen Wert.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

import post_abholen
import post_einordnung
import post_katalog
import post_struktur
import server
from gateway import GatewayTransient

LOG = logging.getLogger("post_neu_einordnen")

# Bester Fall je Mail: Sortierer + Pruefer. Wie in post_abholen.eine_runde.
AUFRUFE_JE_MAIL = 2
TOP_DOMAINS = 40

# Gemeinsame Auswahl: wer ueberhaupt neu einzuordnen ist (nie ein Mensch, nie v2).
def _altbestand(t: str = "") -> str:
    """`t` = Tabellenalias mit Punkt, wo ein Join die Spaltennamen mehrdeutig macht.

    `fehler` nur, wenn das Einsortieren scheiterte: eine Mail, die schon beim Abholen
    kaputt war (post_abholen.ABHOLFEHLER), bleibt stehen - anwenden setzte sie sonst auf
    eingeordnet und loeschte die Fehlermeldung. starts_with statt LIKE: ein `%` im Text
    vertruege sich nicht mit den Platzhaltern der Abfragen, die diesen Teil einbetten."""
    abholfehler = post_abholen.ABHOLFEHLER.replace("'", "''")
    return (f"({t}status = 'eingeordnet' or ({t}status = 'fehler' "
            f"and not starts_with(coalesce({t}fehler, ''), '{abholfehler}'))) "
            f"and {t}einordnung_quelle is distinct from 'mensch' "
            f"and {t}einordnung_version < 2")


_ALTBESTAND = _altbestand()


def _vorschau_inhalt(e: post_einordnung.Einordnung, alt_sensibel: bool) -> dict:
    """Das, was in `vorschau` landet. War die Mail schon vorher sensibel, bleibt sie
    es (anwenden macht nie unsensibel) - dann darf auch kein Modell-Freitext
    gespeichert werden, selbst wenn das Modell sie diesmal harmlos fand."""
    sensibel_gesamt = alt_sensibel or e.sensibel
    begruendung = e.begruendung
    vorschlaege = e.vorschlaege
    if sensibel_gesamt:
        if not e.sensibel:
            begruendung = "vorschau:alt-sensibel"
        if vorschlaege:
            vorschlaege = {k: {f: w for f, w in v.items() if f != "begruendung"}
                           for k, v in vorschlaege.items()}
    return {"bereich": e.bereich, "fach": e.fach, "unterfach": e.unterfach,
            "sensibel": e.sensibel, "quelle": e.quelle, "begruendung": begruendung,
            "vorschlaege": vorschlaege, "aufrufe": e.aufrufe}


def _pruefer_ausfall(vorschlag: post_einordnung.Einordnung) -> post_einordnung.Einordnung:
    """Im Altbestand keine Wiederholung: wie nach drei Fehlversuchen im Betrieb
    (post_abholen._pruefer_vorschlag_speichern) - privat zum Nachsehen, der
    Sortierer-Vorschlag liegt daneben. Aufrufe: Sortierer plus der gescheiterte Pruefer."""
    sortierer = {"bereich": vorschlag.bereich, "fach": vorschlag.fach,
                 "unterfach": vorschlag.unterfach}
    if not vorschlag.sensibel:      # Freitext sensibler Mails wird nie gespeichert
        sortierer["begruendung"] = vorschlag.begruendung
    return post_einordnung.Einordnung(
        "privat", post_struktur.UNKLAR, vorschlag.sensibel, "modell",
        "pruefer:ausgefallen", None, aufrufe=vorschlag.aufrufe + 1,
        vorschlaege={"sortierer": sortierer})


# Kosten der Vorschau fuer die Tagesgrenze: `vorschau_aufrufe` ueberlebt `anwenden` (das
# die Vorschau leert) und wird am selben Tag aufaddiert, sonst verschwaenden bezahlte
# Aufrufe aus der Tagesgrenze (post_abholen.modellaufrufe_heute zaehlt sie am Tag vorschau_am).
_KOSTEN_SQL = ("vorschau_aufrufe = %s + case when vorschau_am::date = current_date "
               "then vorschau_aufrufe else 0 end, vorschau_am = now()")


def _vorschau_speichern(mail_id, inhalt: dict) -> None:
    """Speichert die Vorschau samt Kosten.
    'mensch'/Version erneut im WHERE: eine Korrektur waehrend des Modellaufrufs gewinnt."""
    server._q(
        f"update post_mails set vorschau = %s::jsonb, {_KOSTEN_SQL} "
        f"where id = %s and {_ALTBESTAND}",
        (server._json(inhalt), int(inhalt["aufrufe"]), mail_id))


def _nur_kosten_buchen(mail_id, aufrufe: int) -> None:
    """Bucht bezahlte Aufrufe OHNE Vorschau (Pruefer voruebergehend weg): die Mail bleibt
    in der Warteschlange. Ohne Altbestand-Bedingung - gekostet hat es so oder so."""
    server._q(f"update post_mails set {_KOSTEN_SQL} where id = %s", (int(aufrufe), mail_id))


def vorschau(grenze: int, alle: bool = False) -> int:
    """Ordnet bis zu `grenze` Altbestand-Mails neu ein und speichert nur die Vorschau.
    Haelt die Tagesgrenze ein (die Vorschau-Aufrufe zaehlen in modellaufrufe_heute mit).
    Rueckgabe = Zahl bearbeiteter Mails."""
    def rest() -> int:
        # Vor JEDER Mail neu gelesen: sales-post ordnet parallel ein und verbraucht
        # dieselbe Tagesgrenze; ein einmal gelesener Rest liefe daran vorbei.
        return post_abholen.TAGESGRENZE - post_abholen.modellaufrufe_heute()

    if grenze <= 0 or rest() < AUFRUFE_JE_MAIL:
        return 0
    zeilen = server._q(
        "select m.id, m.besitzer, m.von, m.betreff, m.datum, m.text, m.sensibel, "
        "k.kennung, k.standard_bereich from post_mails m "
        "left join post_konten k on k.id = m.konto_id "
        f"where {_altbestand('m.')} "
        + ("" if alle else "and m.vorschau is null ") +
        "order by m.gesehen_am, m.imap_uid limit %s", (int(grenze),))
    fertig = 0
    for zeile in zeilen:
        if rest() < AUFRUFE_JE_MAIL:
            break                  # eine weitere Mail koennte die Tagesgrenze reissen
        if post_abholen.kunde_aktiv():
            LOG.info("Vorschau pausiert: Kundenantwort hat Vorrang")
            break
        # Genau wie post_abholen.einordnen_offene gebaut. Sensible Mails haben nur
        # noch den Kopf (Text geleert) - fuer die Einordnung reicht das.
        mail = {"id": str(zeile["id"]), "besitzer": zeile["besitzer"],
                "von": zeile["von"] or "", "betreff": zeile["betreff"] or "",
                "datum": zeile["datum"].isoformat() if zeile["datum"] else "",
                "text": zeile["text"] or ""}
        konto = {"kennung": zeile["kennung"], "standard_bereich": zeile["standard_bereich"]}
        try:
            ergebnis = post_einordnung.einordnen(mail, konto)
        except post_einordnung.PrueferVoruebergehend as e:
            # Vor GatewayTransient (Unterklasse): der Sortierer hat schon gekostet.
            _nur_kosten_buchen(mail["id"], e.aufrufe)
            LOG.info("Vorschau pausiert: Pruefer voruebergehend nicht bereit")
            break
        except GatewayTransient:
            LOG.info("Vorschau pausiert: Gateway voruebergehend nicht bereit")
            break
        except post_einordnung.PrueferFehlgeschlagen as e:
            ergebnis = _pruefer_ausfall(e.vorschlag)
        except Exception as e:  # noqa: BLE001 - GatewayFehler und alles andere: eine Mail haelt die anderen nicht auf
            # Der Aufruf hat das Modell erreicht und kostet (wie in einordnen_offene).
            # Ohne gespeicherte Spur wuerde jeder Lauf dieselbe Mail erneut bezahlen:
            # darum eine Fehler-Vorschau (Zum Nachsehen), die den Aufruf festhaelt und
            # die Mail aus der Warteschlange nimmt. --alle holt sie bei Bedarf zurueck.
            LOG.warning("Mail %s: Vorschau fehlgeschlagen (%s)", mail["id"], type(e).__name__)
            _vorschau_speichern(mail["id"], {
                "bereich": "privat", "fach": post_struktur.UNKLAR, "unterfach": None,
                "sensibel": bool(zeile["sensibel"]), "quelle": "modell",
                "begruendung": "vorschau:fehler", "vorschlaege": None, "aufrufe": 1})
            fertig += 1
            continue
        _vorschau_speichern(mail["id"], _vorschau_inhalt(ergebnis, bool(zeile["sensibel"])))
        fertig += 1
    return fertig


def _endung(domain: str) -> str | None:
    """Die Katalog-Endung, die fuer diese Domain gilt (laengste zuerst, wie post_katalog.treffer)."""
    teile = domain.split(".")
    for i in range(len(teile)):
        kandidat = ".".join(teile[i:])
        if kandidat in post_katalog._NACH_ENDUNG:
            return kandidat
    return None


def bericht() -> dict:
    """Nur Zahlen und Domains. Betreff, Text und volle Adressen werden nicht einmal
    in den Rueckgabewert uebernommen."""
    zeilen = server._q(
        "select bereich, fach, von, vorschau from post_mails "
        f"where {_ALTBESTAND}")
    alt: Counter = Counter()
    neu: Counter = Counter()
    katalog: Counter = Counter()
    ohne_katalog: Counter = Counter()
    nachsehen = offen = 0
    for z in zeilen:
        v = z["vorschau"]
        if not v:
            offen += 1
            continue
        alt[(z["bereich"], z["fach"])] += 1
        neu[(v.get("bereich"), v.get("fach"), v.get("unterfach"))] += 1
        if v.get("fach") == post_struktur.UNKLAR:
            nachsehen += 1
        domain = post_katalog.domain(z["von"] or "")
        endung = _endung(domain) if domain else None
        if v.get("quelle") == "katalog" and endung:
            katalog[(endung, v.get("fach"), v.get("unterfach"))] += 1
        elif endung is None:
            ohne_katalog[domain or "(ohne Domain)"] += 1
    return {"alt": dict(alt), "neu": dict(neu), "zum_nachsehen": nachsehen, "offen": offen,
            "katalog": [(e, f, u, n) for (e, f, u), n in katalog.most_common()],
            "ohne_katalog": ohne_katalog.most_common(TOP_DOMAINS)}


def anwenden() -> int:
    """Uebernimmt die Vorschau in die echten Spalten, ohne Modellaufruf. Rueckgabe =
    Zahl der geaenderten Mails.

    `sensibel` = alt ODER neu: eine einmal sensible Mail wird nie wieder freigegeben.
    Ist das Ergebnis sensibel, werden Text/Auszug/An/Anhaenge geleert und kein
    Modell-Freitext behalten (wie post_abholen._ergebnis_speichern). In SET lesen alle
    Ausdruecke die ALTEN Spaltenwerte - darum ist `sens` ueberall dasselbe.
    `modellaufrufe` und `eingeordnet_am` bleiben, ebenso `vorschau_aufrufe`/`vorschau_am`:
    die Vorschau-Aufrufe zaehlen am Vorschau-Tag weiter (genau einmal).

    Die feste Liste gilt auch hier (wie post_abholen._ergebnis_speichern): ein Paar
    Bereich/Fach, das es nicht gibt, wird Zum Nachsehen; Zum Nachsehen liegt immer
    privat und ohne Unterfach."""
    sens = "(sensibel or coalesce((vorschau->>'sensibel')::boolean, false))"
    vs = "vorschau->'vorschlaege'"
    gueltig = ("coalesce((vorschau->>'bereich') || '|' || (vorschau->>'fach') "
               "= any(%(paare)s), false)")
    nachsehen = f"(not {gueltig} or vorschau->>'fach' = %(unklar)s)"
    paare = [f"{b}|{f}" for b, faecher in post_struktur.FAECHER.items() for f in faecher]
    zeilen = server._q(
        "update post_mails set "
        f"bereich = case when {nachsehen} then 'privat' else vorschau->>'bereich' end, "
        f"fach = case when {gueltig} then vorschau->>'fach' else %(unklar)s end, "
        f"unterfach = case when {nachsehen} then null else vorschau->>'unterfach' end, "
        f"sensibel = {sens}, "
        "einordnung_quelle = vorschau->>'quelle', "
        f"begruendung = case when {sens} and not coalesce((vorschau->>'sensibel')::boolean, false) "
        "then 'vorschau:alt-sensibel' else vorschau->>'begruendung' end, "
        f"vorschlaege = case when coalesce(jsonb_typeof({vs}), '') <> 'object' then null "
        f"when {sens} then (({vs} #- '{{sortierer,begruendung}}') #- '{{pruefer,begruendung}}') "
        f"else {vs} end, "
        "einordnung_version = 2, vorschau = null, status = 'eingeordnet', fehler = null, "
        f"text = case when {sens} then null else text end, "
        f"auszug = case when {sens} then null else auszug end, "
        f"an = case when {sens} then null else an end, "
        f"anhaenge = case when {sens} then '{{}}'::text[] else anhaenge end "
        f"where vorschau is not null and {_ALTBESTAND} returning id",
        {"paare": paare, "unklar": post_struktur.UNKLAR})
    return len(zeilen)


def _tabelle(titel: str, zeilen: list[tuple]) -> None:
    print(f"\n{titel}")
    for *schluessel, n in zeilen:
        print(f"  {n:5d}  " + " / ".join("-" if s is None else str(s) for s in schluessel))


def _bericht_drucken(b: dict) -> None:
    print(f"Offen (noch ohne Vorschau): {b['offen']}   Zum Nachsehen (neu): {b['zum_nachsehen']}")
    _tabelle("Alt (Bereich / Fach)", sorted(((*k, n) for k, n in b["alt"].items()),
                                            key=lambda t: -t[-1]))
    _tabelle("Neu (Bereich / Fach / Unterfach)", sorted(((*k, n) for k, n in b["neu"].items()),
                                                        key=lambda t: -t[-1]))
    _tabelle("Katalog-Treffer (Endung / Fach / Unterfach)",
             [(e, f, u, n) for e, f, u, n in b["katalog"]])
    _tabelle(f"Ohne Katalog, haeufigste Domains (Top {TOP_DOMAINS})",
             [(d, n) for d, n in b["ohne_katalog"]])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="post_neu_einordnen")
    sub = p.add_subparsers(dest="befehl", required=True)
    v = sub.add_parser("vorschau", help="Altbestand neu einordnen, nur als Vorschau speichern")
    v.add_argument("--alle", action="store_true", help="auch Mails mit vorhandener Vorschau")
    v.add_argument("--grenze", type=int, default=1000, help="hoechstens so viele Mails")
    sub.add_parser("bericht", help="Zahlen und Domains der Vorschau")
    sub.add_parser("anwenden", help="Vorschau in die echten Spalten uebernehmen (ohne Modell)")
    a = p.parse_args(argv)
    if a.befehl == "vorschau":
        print(f"Vorschau fuer {vorschau(a.grenze, a.alle)} Mail(s) gespeichert.")
    elif a.befehl == "anwenden":
        print(f"{anwenden()} Mail(s) uebernommen.")
        return 0              # danach ist die Vorschau leer, ein Bericht waere sinnlos
    _bericht_drucken(bericht())
    return 0


if __name__ == "__main__":
    sys.exit(main())
