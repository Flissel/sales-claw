"""Mail-Reiter der Post-Sammelstelle (Spec 2026-10-30-post-sammelstelle-design.md
§11, §14.3) und „Postfach hinzufügen“.

- /post: Fächer mit Zahl, Liste, Suche, Stand je eigenem Konto.
- /post/mail/{id}: eine Mail; sensibel heißt nur Kopfdaten (Spec §5).
- /post/mail/{id}/korrigieren: Mensch ändert Bereich/Fach/sensibel, optional
  als Regel für den Absender (Spec §8.3).
- /post/konten: Postfach anlegen (nur Rolle `freigeben`), das Passwort wird
  sofort versiegelt und nie wieder angezeigt.

JEDE Abfrage geht durch post_struktur (sichtbar_sql, mails_suchen,
mail_lesen) - hier steht kein eigenes Sichtbarkeits-SQL, sonst gäbe es zwei
Stellen, die über private Post entscheiden. Ohne angemeldete Person ist alles
zu (fail closed, §14.3): die Anmeldewache ist ohne UI_SESSION_SECRET
durchlässig, darum prüft jede Route selbst. Wie der Rest von sales-ui ohne
JavaScript; jeder Wert aus einer Mail geht durch `ui._e`. `ui` wird
hereingereicht, nie importiert (Muster ui_editor.routen).
"""
from __future__ import annotations

import math
import urllib.parse
from datetime import timedelta

import psycopg
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse
from starlette.routing import Route

import post_struktur as ps
from post_struktur import absender_muster
import server

SEITE_GROESSE = 50
# Eine Seitenzahl jenseits davon ist keine Absicht, sondern ein Tippfehler
# oder ein Versuch, die Datenbank mit riesigen OFFSETs zu beschäftigen.
SEITE_MAX = 10_000
SUCHE_MAX = 200
FELD_MAX = 200
TEXT_MAX = 20_000          # Anzeige; gespeichert ist ohnehin gedeckelt
BEREICH_TITEL = {"privat": "Privat", "business": "Business"}
# Reiter unter /post (Spec 2026-11-06 §7); die ersten drei sind Mail-Listen.
ANSICHT_VORGABE = "aufmerksamkeit"
ANSICHT_TITEL = {"aufmerksamkeit": "Aufmerksamkeit", "zur_info": "Zur Info",
                 "to_review": "To-Review"}
JAHR_MIN, JAHR_MAX = 1990, 2100
# Ziele, die ein Mensch in der UI setzen darf (Spec §6.3). `loeschen` und
# `to_review` setzt nur die Automatik.
ZIEL_WAHL = ("posteingang", "zur_info")
# Modellaufrufe je Tag und je Mail (Sortierer + Pruefer): Grundlage der Resttage.
AUFRUFE_JE_MAIL = 2
HINWEISE = {"freigegeben": "Das Jahr ist freigegeben.",
            "schon": "Dieses Jahr war schon freigegeben. Nichts geändert."}

_STIL = """<style>
.post { display: grid; grid-template-columns: 15rem 1fr; gap: 1.2rem; }
@media (max-width: 760px) { .post { grid-template-columns: 1fr; } }
nav.faecher h3 { margin: .8rem 0 .3rem; font-size: .9rem; }
nav.faecher a { display: flex; align-items: center; gap: .4rem;
                padding: .25rem .4rem; text-decoration: none; border-radius: 6px; }
nav.faecher a.aktiv { font-weight: 700; background: var(--kopfzeile); }
nav.faecher a.unterfach { margin-left: 1.2rem; font-size: .9rem; }
.vorschlaege form { display: inline-block; margin: .3rem .5rem .3rem 0; }
.mailzeile { display: block; padding: .5rem 0; border-top: 1px solid var(--linie);
             text-decoration: none; color: inherit; }
.mailtext { white-space: pre-wrap; overflow-wrap: anywhere; }
.kontostand table { width: 100%; }
nav.reiter { display: flex; flex-wrap: wrap; gap: .4rem; margin: 0 0 1rem; }
nav.reiter a { padding: .3rem .7rem; border-radius: 6px; text-decoration: none;
               border: 1px solid var(--linie); }
nav.reiter a.aktiv { font-weight: 700; background: var(--kopfzeile); }
</style>"""


def _ganzzahl(roh, vorgabe: int, kleinste: int, groesste: int) -> int:
    """Query-Parameter -> int; Unsinn wird zur Vorgabe, nie zu einem 500
    (mails_suchen wirft bei nicht-numerischen Werten, Task-7-Hinweis)."""
    try:
        wert = int(str(roh).strip())
    except (TypeError, ValueError):
        return vorgabe
    return max(kleinste, min(wert, groesste))


def _adresse(link_basis: str, **werte) -> str:
    teile = {k: v for k, v in werte.items() if v not in ("", None, 1)}
    return link_basis + ("?" + urllib.parse.urlencode(teile) if teile else "")


def routen(ui) -> list:
    e = ui._e

    def gesperrt():
        return ui._fehlerseite(
            403, "Nur mit Anmeldung",
            "Der Mail-Reiter ist nur mit persönlicher Anmeldung offen. "
            "Nichts wurde gelesen oder geändert.")

    def betrachter(request):
        name = request.scope.get("benutzer_name")
        return ps.betrachter_laden(str(name)) if name else None

    def rolle(request) -> str:
        return str(request.scope.get("benutzer_rolle") or "")

    # --- Liste ------------------------------------------------------------

    def faecher_zahlen(b, ansicht: str = "") -> tuple[dict, dict]:
        """({(bereich, fach): anzahl}, {(bereich, fach, unterfach): anzahl})
        über die sichtbaren Mails - eine Abfrage, dieselbe Grenze wie die
        Liste (sichtbar_sql). Das Fach zählt alle seine Mails, das Unterfach
        nur die, die eines tragen."""
        wo, params = ps.sichtbar_sql(b)
        if ansicht:
            wo += " and " + ps.ziel_sql(ansicht)
        zeilen = server._q(
            f"select m.bereich, m.fach, m.unterfach, count(*) as n "
            f"from post_mails m where {wo} "
            f"group by m.bereich, m.fach, m.unterfach", params)
        faecher: dict = {}
        unter: dict = {}
        for z in zeilen:
            schluessel = (z["bereich"], z["fach"])
            faecher[schluessel] = faecher.get(schluessel, 0) + int(z["n"])
            if z["unterfach"]:
                unter[schluessel + (z["unterfach"],)] = int(z["n"])
        return faecher, unter

    def faecher_leiste(zahlen: dict, unter: dict, bereich: str, fach: str,
                       unterfach: str = "", ansicht: str = ANSICHT_VORGABE) -> str:
        markiert = ' class="aktiv"'

        def adr(**werte) -> str:
            # Die Vorgabe-Ansicht bleibt aus der Adresse heraus (alte Links gelten weiter).
            return _adresse("/post", ansicht="" if ansicht == ANSICHT_VORGABE else ansicht,
                            **werte)

        teile = ['<nav class="faecher" aria-label="Fächer">',
                 f'<a href="{e(adr())}"{markiert if not (bereich or fach) else ""}>'
                 f'Alle <span class="zaehler">{sum(zahlen.values())}</span></a>']
        for br in ps.BEREICHE:
            eigene = {f: n for (b_, f), n in zahlen.items() if b_ == br}
            if not eigene:
                continue
            teile.append(
                f'<h3><a href="{e(adr(bereich=br))}"'
                f'{markiert if bereich == br and not fach else ""}>'
                f'{e(BEREICH_TITEL[br])} <span class="zaehler">'
                f'{sum(eigene.values())}</span></a></h3>')
            # Feste Reihenfolge aus Spec §4; ein Fach außerhalb der Liste
            # (Altdaten) steht hinten, statt zu verschwinden.
            reihe = [f for f in ps.FAECHER[br] if f in eigene]
            reihe += sorted(f for f in eigene if f not in ps.FAECHER[br])
            for f in reihe:
                aktiv = (' class="aktiv"' if (bereich, fach, unterfach) == (br, f or "", "")
                         else "")
                teile.append(
                    f'<a href="{e(adr(bereich=br, fach=f or ""))}"{aktiv}>'
                    f'{e(f or "(ohne Fach)")} <span class="zaehler">{eigene[f]}</span></a>')
                # Unterfächer eingerückt darunter, nur mit mindestens einer
                # Mail, in der Reihenfolge der festen Liste.
                for u in ps.UNTERFAECHER.get(f, ()):
                    if not unter.get((br, f, u)):
                        continue
                    ua = ("aktiv " if (bereich, fach, unterfach) == (br, f, u) else "")
                    teile.append(
                        f'<a class="{ua}unterfach" href="'
                        f'{e(adr(bereich=br, fach=f, unterfach=u))}">'
                        f'{e(u)} <span class="zaehler">{unter[(br, f, u)]}</span></a>')
        offen = zahlen.get((None, None), 0)
        if offen:
            teile.append(f'<p class="meta">Noch nicht eingeordnet: {offen}</p>')
        teile.append("</nav>")
        return "".join(teile)

    def konten_sichtbar(b) -> dict:
        """Konten fürs Filtern: eigene und die, aus denen man Mails sieht."""
        wo, params = ps.sichtbar_sql(b)
        zeilen = server._q(
            "select k.id, k.kennung from post_konten k where k.besitzer = %s "
            "or exists (select 1 from post_mails m where m.konto_id = k.id "
            f"and {wo}) order by k.kennung", [b.name] + params)
        return {str(z["id"]): z["kennung"] for z in zeilen}

    def kontostand(b) -> str:
        """Stand je EIGENEM Konto. Der Besitzer sieht alle Mails seiner Konten,
        die Zahlen verraten also nichts, was er nicht ohnehin sähe."""
        zeilen = server._q(
            "select k.kennung, k.anbieter, k.altbestand_fertig, "
            "count(m.id) filter (where m.status = 'eingeordnet' "
            "  and m.fach is distinct from %s) as eingeordnet, "
            "count(m.id) filter (where m.status = 'eingeordnet' "
            "  and m.fach = %s) as unklar, "
            "count(m.id) filter (where m.status = 'neu') as neu, "
            "count(m.id) filter (where m.status = 'fehler') as fehler "
            "from post_konten k left join post_mails m on m.konto_id = k.id "
            "where k.besitzer = %s and k.aktiv "
            "group by k.id order by k.kennung", (ps.UNKLAR, ps.UNKLAR, b.name))
        if not zeilen:
            return ""
        reihen = "".join(
            f'<tr><td data-label="Konto">{e(z["kennung"])} '
            f'<span class="meta">{e(z["anbieter"])}</span></td>'
            f'<td data-label="Eingeordnet">{int(z["eingeordnet"])}</td>'
            f'<td data-label="Zum Nachsehen">{int(z["unklar"])}</td>'
            f'<td data-label="Neu">{int(z["neu"])}</td>'
            f'<td data-label="Fehler">{int(z["fehler"])}</td>'
            f'<td data-label="Altbestand">'
            f'{"fertig" if z["altbestand_fertig"] else "läuft"}</td></tr>'
            for z in zeilen)
        return ('<section class="kontostand"><h2>Stand je Konto</h2>'
                '<table><thead><tr><th>Konto</th><th>Eingeordnet</th>'
                '<th>Zum Nachsehen</th><th>Neu</th><th>Fehler</th><th>Altbestand</th>'
                f'</tr></thead><tbody>{reihen}</tbody></table>'
                '<p class="meta">Archiviert wird in Stufe 1 nichts; '
                '<a href="/post/konten">Postfach hinzufügen</a></p></section>')

    def reiterleiste(aktiv: str) -> str:
        reiter = [(k, ANSICHT_TITEL[k], "/post" if k == ANSICHT_VORGABE else f"/post?ansicht={k}")
                  for k in ANSICHT_TITEL] + [("aufraeumen", "Aufräumen", "/post/aufraeumen")]
        markiert = ' class="aktiv"'
        return ('<nav class="reiter" aria-label="Mail-Reiter">' + "".join(
            f'<a href="{e(url)}"{markiert if k == aktiv else ""}>{e(titel)}</a>'
            for k, titel, url in reiter) + '</nav>')

    def loeschdatum(m: dict) -> str:
        """To-Review: Tag, an dem die Mail geloescht wird. Die Frist laeuft nur, solange die
        Mail im Ordner To-Review liegt (post_ordnen loescht nur dort); ordner_am kann auch
        vom Verschieben in einen anderen Ordner stammen - dann steht dort kein Datum."""
        if m.get("ordner_am") is None or m.get("ordner") != "To-Review":
            return "noch nicht im Ordner"
        import post_ordnen   # TO_REVIEW_TAGE; erst hier, das Modul zieht die Abholung nach
        frist = m["ordner_am"] + timedelta(days=post_ordnen.TO_REVIEW_TAGE)
        return "wird gelöscht am " + ui._zeit(frist).split(" ")[0]

    def mail_zeile(m: dict, konten: dict, ansicht: str = "") -> str:
        marke = (' <span class="badge achtung">sensibel</span>'
                 if m["sensibel"] is not False else "")
        fach = (f'{e(BEREICH_TITEL.get(m["bereich"], m["bereich"]))} · {e(m["fach"])}'
                + (f' · {e(m["unterfach"])}' if m["unterfach"] else "")
                if m["bereich"] else "noch nicht eingeordnet")
        return (f'<a class="mailzeile" href="/post/mail/{e(m["id"])}">'
                f'<b>{e(m["betreff"] or "(ohne Betreff)")}</b>{marke}'
                f'<div class="meta">{e(m["von"])} · {e(ui._zeit(m["datum"]) if m["datum"] else "")}'
                f' · {e(konten.get(str(m["konto_id"]), ""))} · {fach}</div>'
                + (f'<div class="meta">{e(loeschdatum(m))}</div>' if ansicht == "to_review" else "")
                + '</a>')

    @ui._gesichert_seite
    async def liste(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        qp = request.query_params
        bereich = str(qp.get("bereich") or "")
        fach = str(qp.get("fach") or "")
        unterfach = str(qp.get("unterfach") or "")
        konto = str(qp.get("konto") or "")
        ansicht = str(qp.get("ansicht") or ANSICHT_VORGABE)
        if ansicht not in ANSICHT_TITEL:
            ansicht = ANSICHT_VORGABE
        such = str(qp.get("q") or "").strip()[:SUCHE_MAX]
        seite = _ganzzahl(qp.get("seite"), 1, 1, SEITE_MAX)
        # Eine Zeile mehr holen als angezeigt: so weiß die Seite, ob es eine
        # nächste gibt, ohne zweite Zählabfrage.
        mails = ps.mails_suchen(b, suche=such, bereich=bereich, fach=fach,
                                unterfach=unterfach, konto_id=konto, ziel=ansicht,
                                grenze=SEITE_GROESSE + 1,
                                versatz=(seite - 1) * SEITE_GROESSE)
        weiter = len(mails) > SEITE_GROESSE
        mails = mails[:SEITE_GROESSE]
        konten = konten_sichtbar(b)
        optionen = "".join(
            f'<option value="{e(k)}"{" selected" if k == konto else ""}>{e(n)}</option>'
            for k, n in konten.items())
        formular = (
            '<form method="get" action="/post" class="filter">'
            f'<input type="search" name="q" value="{e(such)}" '
            'placeholder="Absender, Betreff, Text" aria-label="Mails durchsuchen">'
            f'<select name="konto" aria-label="Konto"><option value="">Alle Konten</option>'
            f'{optionen}</select>'
            + (f'<input type="hidden" name="ansicht" value="{e(ansicht)}">'
               if ansicht != ANSICHT_VORGABE else "")
            + (f'<input type="hidden" name="bereich" value="{e(bereich)}">' if bereich else "")
            + (f'<input type="hidden" name="fach" value="{e(fach)}">' if fach else "")
            + (f'<input type="hidden" name="unterfach" value="{e(unterfach)}">'
               if unterfach else "")
            + '<button>Suchen</button></form>')
        if mails:
            zeilen = "".join(mail_zeile(m, konten, ansicht) for m in mails)
        else:
            zeilen = '<p class="meta">Keine Mails für diese Auswahl.</p>'
        blaettern = []
        filter_ = {"ansicht": "" if ansicht == ANSICHT_VORGABE else ansicht,
                   "bereich": bereich, "fach": fach, "unterfach": unterfach,
                   "konto": konto, "q": such}
        if seite > 1:
            blaettern.append(f'<a href="{e(_adresse("/post", **filter_, seite=seite - 1))}">'
                             '← zurück</a>')
        if weiter:
            blaettern.append(f'<a href="{e(_adresse("/post", **filter_, seite=seite + 1))}">'
                             'weiter →</a>')
        rumpf = (_STIL + reiterleiste(ansicht) + '<div class="post">'
                 + faecher_leiste(*faecher_zahlen(b, ansicht), bereich, fach, unterfach,
                                  ansicht)
                 + f'<div>{formular}<p class="meta">Seite {seite}</p>{zeilen}'
                 + (f'<p class="aktionen">{" ".join(blaettern)}</p>' if blaettern else "")
                 + kontostand(b) + '</div></div>')
        return ui._seite("Mails", rumpf)

    # --- Eine Mail --------------------------------------------------------

    def darf_korrigieren(request, b, m) -> bool:
        # Sichtbar ist m schon (mail_lesen); korrigieren darf davon nur der
        # Besitzer oder die Leitung - ein Abteilungsmitglied liest nur.
        return (rolle(request) == "freigeben"
                and (b.leitung or m["besitzer"] == b.name))

    def regel_angeboten(b, m) -> bool:
        # Den Haken nur zeigen, wo er auch wirken kann: ohne Mailadresse
        # scheiterte sonst jede Korrektur mit dem vorgewaehlten Haken.
        return darf_regel_anlegen(b, m) and bool(ps.absender_adresse(m["von"] or ""))

    def darf_regel_anlegen(b, m) -> bool:
        # R18: „für diesen Absender immer so“ nur fuer die eigene Post. Die
        # Leitung darf eine fremde Mail korrigieren, aber keine Regel fuer
        # die Post eines anderen anlegen (sie lenkte dessen kuenftige Mails).
        return bool(m["besitzer"]) and m["besitzer"] == b.name

    def einordnung_text(bereich, fach, unterfach) -> str:
        return " · ".join(t for t in (BEREICH_TITEL.get(bereich, bereich), fach,
                                      unterfach) if t)

    def vorschlag_formulare(m: dict, regel_erlaubt: bool) -> str:
        """Bei „Zum Nachsehen“ die zwei Modell-Vorschläge als Ein-Klick-
        Übernahme. Was nicht in der festen Liste steht oder selbst „Zum
        Nachsehen“ ist, bekommt keinen Knopf."""
        if m["fach"] != ps.UNKLAR or not isinstance(m.get("vorschlaege"), dict):
            return ""
        formulare = []
        for wahl, titel in (("sortierer", "Sortierer"), ("pruefer", "Prüfer")):
            v = m["vorschlaege"].get(wahl)
            if not isinstance(v, dict):
                continue
            bereich, fach = str(v.get("bereich") or ""), str(v.get("fach") or "")
            if not ps.fach_gueltig(bereich, fach) or fach == ps.UNKLAR:
                continue
            unterfach = ps.unterfach_zwingen(fach, v.get("unterfach"))
            grund = str(v.get("begruendung") or "")
            formulare.append(
                f'<form method="post" action="/post/mail/{e(m["id"])}/vorschlag">'
                f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
                f'<input type="hidden" name="wahl" value="{wahl}">'
                + ('<label><input type="checkbox" name="regel" value="ja" checked> '
                   'für diesen Absender immer so</label> ' if regel_erlaubt else '')
                + f'<button class="primaer">{e(titel)}: '
                f'{e(einordnung_text(bereich, fach, unterfach))}</button>'
                + (f'<div class="meta">{e(grund)}</div>' if grund else "")
                + '</form>')
        if not formulare:
            return ""
        return ('<section class="karte vorschlaege"><h2>Vorschläge übernehmen</h2>'
                '<p class="meta">Sortierer und Prüfer waren uneins. Ein Klick '
                'ordnet die Mail so ein.</p>' + "".join(formulare) + '</section>')

    def korrektur_formular(m: dict, regel_erlaubt: bool) -> str:
        bereiche = "".join(
            f'<option value="{br}"{" selected" if m["bereich"] == br else ""}>'
            f'{e(BEREICH_TITEL[br])}</option>' for br in ps.BEREICHE)
        gruppen = "".join(
            f'<optgroup label="{e(BEREICH_TITEL[br])}">' + "".join(
                f'<option value="{e(f)}"'
                f'{" selected" if (m["bereich"], m["fach"]) == (br, f) else ""}>'
                f'{e(f)}</option>' for f in ps.FAECHER[br]
                # „Zum Nachsehen“ liegt immer privat (Spec): unter Business
                # nicht anbieten, sonst sähe die Leitung solche Mails.
                if not (br == "business" and f == ps.UNKLAR)) + '</optgroup>'
            for br in ps.BEREICHE)
        alle_unter = tuple(dict.fromkeys(u for liste in ps.UNTERFAECHER.values()
                                         for u in liste))
        unter = '<option value="">(keins)</option>' + "".join(
            f'<option value="{e(u)}"{" selected" if m["unterfach"] == u else ""}>'
            f'{e(u)}</option>' for u in alle_unter)
        return (
            f'<form method="post" action="/post/mail/{e(m["id"])}/korrigieren" '
            'class="karte"><h2>Einordnung korrigieren</h2>'
            f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
            f'<label>Bereich <select name="bereich">{bereiche}</select></label> '
            f'<label>Fach <select name="fach">{gruppen}</select></label> '
            f'<label>Unterfach <select name="unterfach">{unter}</select></label> '
            '<label><input type="checkbox" name="sensibel" value="ja"'
            f'{" checked" if m["sensibel"] is not False else ""}> sensibel</label> '
            # Vorgewählt: die Korrektur soll lernen (Spec v2); abwählen geht.
            + ('<label><input type="checkbox" name="regel" value="ja" checked> '
               'für diesen Absender immer so (Bereich, Fach und Unterfach)</label> '
               if regel_erlaubt else '') +
            '<p class="meta">Sensibel löscht Text, Empfänger und Anhangnamen '
            'dieser Mail endgültig aus der Sammelstelle.</p>'
            '<button class="primaer">Speichern</button></form>')

    def ziel_formulare(m: dict) -> str:
        """Ein-Klick-Korrektur des Ziels (Spec §6.3). Nur die Ziele, die ein Mensch setzen
        darf, und nur das jeweils andere als das heutige."""
        if m["status"] == "geloescht":
            return ""
        namen = {"posteingang": "In den Posteingang holen",
                 "zur_info": "Nach „Zur Info“ legen"}
        knoepfe = "".join(
            f'<form method="post" action="/post/mail/{e(m["id"])}/ziel" '
            f'class="ziel-{z}">'
            f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
            f'<input type="hidden" name="ziel" value="{z}">'
            f'<button class="primaer">{e(namen[z])}</button></form>'
            for z in ZIEL_WAHL if z != m["ziel"])
        if not knoepfe:
            return ""
        hinweis = ('<p class="meta">Der Absender wird dabei als „nie Werbung“ '
                   'geschützt.</p>' if m["ziel"] == "to_review" else "")
        return ('<section class="karte"><h2>Ablage ändern</h2>' + knoepfe + hinweis
                + '</section>')

    @ui._gesichert_seite
    async def mail(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        m = ps.mail_lesen(b, request.path_params["mail_id"])
        if m is None:
            # Kein Unterschied zwischen „gibt es nicht“ und „darfst du nicht“.
            return ui._fehlerseite(404, "Mail nicht gefunden",
                                   'Diese Mail gibt es hier nicht. '
                                   '<a href="/post">Zurück zu den Mails</a>')
        konto = server._q("select kennung from post_konten where id = %s",
                          (m["konto_id"],))
        sensibel = m["sensibel"] is not False
        kopf = [("Konto", konto[0]["kennung"] if konto else ""),
                ("Von", m["von"]), ("Datum", ui._zeit(m["datum"]) if m["datum"] else ""),
                ("Einordnung", (einordnung_text(m["bereich"], m["fach"], m["unterfach"])
                                if m["bereich"] else "noch nicht eingeordnet"))]
        if not sensibel and m["an"]:
            kopf.insert(2, ("An", m["an"]))
        teile = [_STIL, '<p><a href="/post">← Alle Mails</a></p>',
                 f'<div class="karte"><h2>{e(m["betreff"] or "(ohne Betreff)")}</h2>',
                 "".join(f'<div class="meta"><b>{e(k)}:</b> {e(v)}</div>' for k, v in kopf)]
        if sensibel:
            # Spec §5: von sensiblen Mails bleiben nur Kopfdaten; Text und
            # Anhänge liefert mail_lesen gar nicht erst aus.
            teile.append('<p class="hinweis"><span class="badge achtung">sensibel</span> '
                         'Inhalt, Empfänger und Anhänge werden nicht gespeichert. '
                         'Die Mail selbst liegt im Postfach.</p></div>')
        else:
            if m["anhaenge"]:
                teile.append('<div class="meta"><b>Anhänge:</b> '
                             + ", ".join(e(a) for a in m["anhaenge"]) + "</div>")
            teile.append(f'<div class="text mailtext">{e((m["text"] or "")[:TEXT_MAX])}</div></div>')
        if darf_korrigieren(request, b, m):
            teile.append(ziel_formulare(m))
            teile.append(vorschlag_formulare(m, regel_angeboten(b, m)))
            teile.append(korrektur_formular(m, regel_angeboten(b, m)))
        return ui._seite(m["betreff"] or "Mail", "".join(teile), titel_zeigen=False)

    @ui._gesichert_seite
    async def korrigieren(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Nichts geändert. Seite neu laden.")
        m = ps.mail_lesen(b, request.path_params["mail_id"])
        if m is None or not darf_korrigieren(request, b, m):
            return ui._fehlerseite(403, "Nicht erlaubt",
                                   "Korrigieren darf nur, wem das Postfach gehört, "
                                   "oder die Leitung. Nichts geändert.")
        bereich = str(form.get("bereich") or "")
        fach = str(form.get("fach") or "")
        if not ps.fach_gueltig(bereich, fach):
            return ui._fehlerseite(400, "Ungültige Einordnung",
                                   "Dieses Fach gibt es in diesem Bereich nicht. "
                                   "Nichts geändert.")
        if fach == ps.UNKLAR:
            bereich = "privat"   # auch bei selbstgebautem Formular
        sensibel = form.get("sensibel") == "ja"
        unterfach = ps.unterfach_zwingen(fach, str(form.get("unterfach") or ""))
        fehler = speichern(b, m, bereich, fach, unterfach, sensibel,
                           form.get("regel") == "ja")
        return fehler or RedirectResponse(f"/post/mail/{m['id']}", status_code=303)

    def speichern(b, m, bereich, fach, unterfach, sensibel, regel_gewollt,
                  aufmerksamkeit=None):
        """Menschliche Einordnung festhalten (Korrektur und Vorschlag teilen
        sich das). Gibt eine Fehlerseite zurück oder None.

        `aufmerksamkeit`: Wert des übernommenen Vorschlags; ohne ihn gilt nur
        „Zum Nachsehen“ als Posteingang (Spec §5), alles andere als Zur Info."""
        muster = None
        # R18: fremde Post (Leitung korrigiert Bens Mail) wird korrigiert, aber
        # ohne Regel - auch wenn ein selbstgebautes Formular den Haken schickt.
        # Nie eine Regel nach „Zum Nachsehen“: sie hielte alle kuenftigen
        # Mails des Absenders dauerhaft ungeordnet fest.
        if regel_gewollt and fach != ps.UNKLAR and darf_regel_anlegen(b, m):
            # Dieselbe Adresse wie post_werbung (klein geschrieben): sonst ersetzte die
            # Regel eine gleichlautende Regel in anderer Schreibweise nicht.
            adresse = ps.absender_adresse(m["von"] or "")
            if not adresse:
                return ui._fehlerseite(400, "Keine Regel möglich",
                                       "Der Absender hat keine Mailadresse. "
                                       "Nichts geändert.")
            muster = absender_muster(adresse)
        if aufmerksamkeit is None or fach == ps.UNKLAR:
            aufmerksamkeit = fach == ps.UNKLAR
        # R9: wird eine Mail sensibel, verschwinden Text, Auszug, Empfänger,
        # Anhangnamen und die ursprüngliche Empfängeradresse sofort und endgültig,
        # nicht erst in der Anzeige.
        leeren = (", text = null, auszug = null, an = null, anhaenge = '{}', "
                  "urspruengliche_adresse = null" if sensibel else "")
        with server.pool.connection() as conn:
            # Begründung, Vorschau und Vorschläge sind Modell-Freitext zur
            # alten Einordnung: nach der Entscheidung des Menschen passen sie
            # nicht mehr, und bei einer jetzt sensiblen Mail dürfen sie nicht
            # überleben. Alles in einem UPDATE.
            # eingeordnet_am bleibt: es ist der Tag, an dem die Modellaufrufe der Mail
            # anfielen (Tagesgrenze). Eine Korrektur von Hand darf sie nicht auf heute ziehen.
            # werbung_sicher = false: geloescht wird nur, was Regel, Katalog oder beide
            # Modelle als Werbung erkannt haben, nie eine Handeinordnung (Spec §4).
            conn.execute(
                "update post_mails set bereich = %s, fach = %s, unterfach = %s, "
                "sensibel = %s, einordnung_quelle = 'mensch', "
                "aufmerksamkeit = %s, werbung_sicher = false, "
                "einordnung_version = 3, eingeordnet_am = coalesce(eingeordnet_am, now()), "
                "status = 'eingeordnet', fehler = null, begruendung = null, "
                f"vorschau = null, vorschlaege = null{leeren} "
                "where id = %s", (bereich, fach, unterfach, sensibel, aufmerksamkeit, m["id"]))
            if muster:
                # R13: die Regel gilt nur fuer die Post ihres Besitzers (hier
                # immer der Korrigierende selbst, R18). Sie traegt Bereich,
                # Fach und Unterfach - `sensibel` entscheiden Muster und Modell
                # weiter je Mail, darum steht hier immer false. Eine vorhandene
                # Einordnungs-Regel fuer denselben Absender wird ersetzt, sonst
                # haeuften sich widerspruechliche Regeln an; beides in dieser einen
                # Transaktion (der Block committet gemeinsam). Die Schutzregel
                # „nie Werbung“ (art nie_werbung) bleibt: sie ordnet nichts ein.
                conn.execute(
                    "delete from post_regeln where art = 'einordnen' and feld = 'von' "
                    "and lower(muster) = lower(%s) and besitzer is not distinct from %s",
                    (muster, m["besitzer"]))
                conn.execute(
                    "insert into post_regeln (muster, feld, bereich, fach, "
                    "unterfach, sensibel, angelegt_von, besitzer, art) "
                    "values (%s, 'von', %s, %s, %s, false, %s, %s, 'einordnen')",
                    (muster, bereich, fach, unterfach, b.name, m["besitzer"]))
        return None

    @ui._gesichert_seite
    async def vorschlag(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Nichts geändert. Seite neu laden.")
        m = ps.mail_lesen(b, request.path_params["mail_id"])
        if m is None or not darf_korrigieren(request, b, m):
            return ui._fehlerseite(403, "Nicht erlaubt",
                                   "Übernehmen darf nur, wem das Postfach gehört, "
                                   "oder die Leitung. Nichts geändert.")
        wahl = str(form.get("wahl") or "")
        vorschlaege = m["vorschlaege"] if isinstance(m["vorschlaege"], dict) else {}
        v = vorschlaege.get(wahl) if wahl in ("sortierer", "pruefer") else None
        # Erneut gegen die feste Liste prüfen: gespeichert ist Modell-Ausgabe,
        # und die Liste kann sich seit dem Vorschlag geändert haben.
        bereich = str(v.get("bereich") or "") if isinstance(v, dict) else ""
        fach = str(v.get("fach") or "") if isinstance(v, dict) else ""
        if not ps.fach_gueltig(bereich, fach) or fach == ps.UNKLAR:
            return ui._fehlerseite(400, "Kein gültiger Vorschlag",
                                   "Diesen Vorschlag gibt es nicht oder er passt "
                                   "nicht zur Fächerliste. Nichts geändert.")
        unterfach = ps.unterfach_zwingen(fach, v.get("unterfach"))
        # Ältere Vorschläge kennen aufmerksamkeit nicht: dann entscheidet speichern.
        aufmerksamkeit = v.get("aufmerksamkeit")
        fehler = speichern(b, m, bereich, fach, unterfach,
                           m["sensibel"] is not False, form.get("regel") == "ja",
                           aufmerksamkeit if isinstance(aufmerksamkeit, bool) else None)
        return fehler or RedirectResponse(f"/post/mail/{m['id']}", status_code=303)

    @ui._gesichert_seite
    async def ziel_setzen(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Nichts geändert. Seite neu laden.")
        m = ps.mail_lesen(b, request.path_params["mail_id"])
        if m is None or not darf_korrigieren(request, b, m):
            return ui._fehlerseite(403, "Nicht erlaubt",
                                   "Die Ablage ändern darf nur, wem das Postfach gehört, "
                                   "oder die Leitung. Nichts geändert.")
        ziel = str(form.get("ziel") or "")
        if ziel not in ZIEL_WAHL or m["status"] == "geloescht":
            return ui._fehlerseite(400, "Ungültiges Ziel",
                                   "Dieses Ziel gibt es hier nicht. Nichts geändert.")
        import post_werbung
        with server.pool.connection() as conn:
            # Eine Transaktion: eine Mail, die aus To-Review geholt wird, ohne Schutz für
            # den Absender landete beim nächsten Treffer wieder dort. `ziel_manuell` hält
            # die Automatik von der Mail fern.
            # status im WHERE: post_ordnen kann die Mail seit dem Lesen geloescht haben.
            conn.execute("update post_mails set ziel = %s, ziel_manuell = true "
                         "where id = %s and status <> 'geloescht'", (ziel, m["id"]))
            # Schutzregel nur für die eigene Post (R18): die Leitung darf eine fremde Mail
            # umlegen, aber keine Regel im Namen des Besitzers anlegen.
            if m["ziel"] == "to_review" and darf_regel_anlegen(b, m):
                post_werbung.schutz_setzen(m["besitzer"], m["von"] or "", conn=conn)
        return RedirectResponse(f"/post/mail/{m['id']}", status_code=303)

    # --- Aufräumen ----------------------------------------------------------

    def jahr_aus(request) -> int | None:
        try:
            jahr = int(str(request.path_params["jahr"]).strip())
        except ValueError:
            return None
        return jahr if JAHR_MIN <= jahr <= JAHR_MAX else None

    def jahr_fehlt():
        return ui._fehlerseite(404, "Jahr nicht gefunden",
                               'Dieses Jahr gibt es hier nicht. '
                               '<a href="/post/aufraeumen">Zurück zum Aufräumen</a>')

    @ui._gesichert_seite
    async def aufraeumen(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        import post_abholen
        import post_freigabe
        import post_ordnen
        # Immer der angemeldete Name als Besitzer: es gibt keinen Weg, einen
        # anderen anzugeben, auch nicht für die Leitung.
        jahre = post_freigabe.jahre(b.name)
        konten_ = post_freigabe.konten_des_besitzers(b.name)
        neu = post_freigabe.offene_mails(b.name)
        grenze = post_abholen.TAGESGRENZE
        heute = post_abholen.modellaufrufe_heute()
        resttage = math.ceil(neu * AUFRUFE_JE_MAIL / grenze) if grenze > 0 else 0
        hinweis = HINWEISE.get(str(request.query_params.get("hinweis") or ""), "")
        jahrzeilen = "".join(
            f'<tr><td data-label="Jahr"><a href="/post/aufraeumen/{int(j["jahr"])}">'
            f'{int(j["jahr"])}</a></td>'
            f'<td data-label="Eingeordnet">{int(j["eingeordnet"])}</td>'
            f'<td data-label="Wartet auf Freigabe">{int(j["offen"])}</td>'
            f'<td data-label="Wird gelöscht">{int(j["zu_loeschen"])}</td>'
            f'<td data-label="Freigegeben">'
            f'{e(ui._zeit(j["freigegeben_am"])) if j["freigegeben_am"] else "—"}</td></tr>'
            for j in jahre)
        jahrtabelle = (
            '<table><thead><tr><th>Jahr</th><th>Eingeordnet</th><th>Wartet auf Freigabe</th>'
            f'<th>Wird gelöscht</th><th>Freigegeben</th></tr></thead><tbody>{jahrzeilen}'
            '</tbody></table>' if jahre else '<p class="meta">Noch keine eingeordneten Mails.</p>')
        kontozeilen = "".join(
            f'<tr><td data-label="Konto">{e(k["kennung"])}</td>'
            f'<td data-label="Ordnen">'
            f'{e("ruht: " + k["ordnen_aus"]) if k["ordnen_aus"] else "aktiv"}</td></tr>'
            for k in konten_)
        kontotabelle = ('<table><thead><tr><th>Konto</th><th>Ordnen im Postfach</th></tr></thead>'
                        f'<tbody>{kontozeilen}</tbody></table>' if konten_
                        else '<p class="meta">Noch kein Postfach angebunden.</p>')
        rumpf = (_STIL + reiterleiste("aufraeumen")
                 + (f'<p class="hinweis">{e(hinweis)}</p>' if hinweis else "")
                 + '<section class="karte"><h2>Stand</h2>'
                 f'<p>Ordnungsmodus: <b>{e(post_ordnen.MODUS)}</b></p>'
                 f'<p>Modellaufrufe heute: <b>{heute} / {grenze}</b></p>'
                 f'<p>Noch einzuordnen: <b>{neu}</b> Mails, geschätzt '
                 f'<b>{resttage}</b> Tage Rest.</p></section>'
                 + f'<h2>Je Jahr</h2>{jahrtabelle}<h2>Postfächer</h2>{kontotabelle}')
        return ui._seite("Aufräumen", rumpf)

    async def freigabe_ausfuehren(request, b, jahr: int, post_freigabe):
        if rolle(request) != "freigeben":
            return ui._fehlerseite(403, "Nicht für diese Anmeldung",
                                   "Freigeben darf nur die Rolle „freigeben“. "
                                   "Nichts geändert.")
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Nichts geändert. Seite neu laden.")
        gezeigt = [str(x) for x in form.getlist("absender")]
        behalten = {str(x) for x in form.getlist("loeschen")}
        # Ausgenommen ist, was in der Vorschau stand und nicht mehr angehakt ist.
        ausgenommen = [a for a in gezeigt if a not in behalten]
        try:
            post_freigabe.freigeben(b.name, jahr, gezeigt, ausgenommen)
        except ValueError as fehler:
            if str(fehler) != "schon freigegeben":
                raise
            return RedirectResponse("/post/aufraeumen?hinweis=schon", status_code=303)
        return RedirectResponse("/post/aufraeumen?hinweis=freigegeben", status_code=303)

    @ui._gesichert_seite
    async def aufraeumen_jahr(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        jahr = jahr_aus(request)
        if jahr is None:
            return jahr_fehlt()
        import post_freigabe
        # Ein Jahr ohne eigene eingeordnete Mails gibt es hier nicht (GET wie POST).
        eintrag = next((j for j in post_freigabe.jahre(b.name) if int(j["jahr"]) == jahr), None)
        if eintrag is None:
            return jahr_fehlt()
        if request.method == "POST":
            return await freigabe_ausfuehren(request, b, jahr, post_freigabe)
        if eintrag is None:
            return jahr_fehlt()
        kopf = (f'{reiterleiste("aufraeumen")}<p><a href="/post/aufraeumen">← Aufräumen</a></p>'
                f'<h2>Jahr {jahr}</h2>')
        if eintrag["freigegeben_am"]:
            return ui._seite(f"Aufräumen {jahr}", _STIL + kopf
                             + '<p class="hinweis">Freigegeben am '
                             f'{e(ui._zeit(eintrag["freigegeben_am"]))}.</p>')
        absender = post_freigabe.vorschau(b.name, jahr)
        if not absender:
            return ui._seite(f"Aufräumen {jahr}", _STIL + kopf
                             + '<p class="meta">In diesem Jahr gibt es nichts zu löschen.</p>')
        zeilen = "".join(
            f'<tr><td data-label="Löschen">'
            f'<input type="hidden" name="absender" value="{e(a["absender"])}">'
            f'<input type="checkbox" name="loeschen" value="{e(a["absender"])}" checked '
            f'aria-label="{e(a["absender"])} löschen"></td>'
            f'<td data-label="Absender"><a href="/post/aufraeumen/{jahr}/absender?adresse='
            f'{urllib.parse.quote(a["absender"], safe="")}">{e(a["absender"])}</a></td>'
            f'<td data-label="Mails">{int(a["anzahl"])}</td>'
            f'<td data-label="Beispiele">{e(" · ".join(a["beispiele"]))}</td></tr>'
            for a in absender)
        gesamt = sum(int(a["anzahl"]) for a in absender)
        if rolle(request) == "freigeben":
            knopf = f'<button class="primaer">Jahr {jahr} löschen freigeben</button>'
        else:
            knopf = '<p class="meta">Freigeben darf nur die Rolle „freigeben“.</p>'
        formular = (
            f'<form method="post" action="/post/aufraeumen/{jahr}" class="karte">'
            f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
            f'<p>{gesamt} Mails von {len(absender)} Absendern werden gelöscht. '
            'Wer abgewählt ist, bekommt die Schutzregel „nie Werbung“ und '
            'bleibt im Postfach.</p>'
            '<table><thead><tr><th>Löschen</th><th>Absender</th><th>Mails</th>'
            f'<th>Beispiele</th></tr></thead><tbody>{zeilen}</tbody></table>{knopf}</form>')
        return ui._seite(f"Aufräumen {jahr}", _STIL + kopf + formular)

    @ui._gesichert_seite
    async def aufraeumen_absender(request):
        """Vor der Freigabe nachsehen, welche Mails eines Absenders im Jahr gelöscht
        würden (Spec §6.1). Nur lesen, nur eigene Konten, kein Formular."""
        b = betrachter(request)
        if b is None:
            return gesperrt()
        jahr = jahr_aus(request)
        if jahr is None:
            return jahr_fehlt()
        import post_freigabe
        if not any(int(j["jahr"]) == jahr for j in post_freigabe.jahre(b.name)):
            return jahr_fehlt()
        adresse = str(request.query_params.get("adresse") or "")
        mails = post_freigabe.loeschliste(b, jahr, adresse)
        zeilen = "".join(
            f'<tr><td data-label="Datum">{e(ui._zeit(m["datum"]))}</td>'
            f'<td data-label="Konto">{e(m["kennung"])}</td>'
            f'<td data-label="Betreff">{e(m["betreff"])}</td></tr>'
            for m in mails)
        tabelle = ('<table><thead><tr><th>Datum</th><th>Konto</th><th>Betreff</th></tr>'
                   f'</thead><tbody>{zeilen}</tbody></table>' if mails
                   else '<p class="meta">Keine Mails dieses Absenders zum Löschen.</p>')
        rumpf = (_STIL + reiterleiste("aufraeumen")
                 + f'<p><a href="/post/aufraeumen/{jahr}">← Jahr {jahr}</a></p>'
                 + f'<h2>{e(adresse)} · {len(mails)} Mails in {jahr}</h2>{tabelle}')
        return ui._seite(f"Aufräumen {jahr}", rumpf)

    # --- Postfach hinzufügen ---------------------------------------------

    def konten_seite(b, fehler: str = "", werte: dict | None = None,
                     status: int = 200):
        import post_konten   # erst hier: zieht cryptography nach
        werte = werte or {}
        eigene = [k for k in post_konten.aktive_konten() if k["besitzer"] == b.name]
        # Bewusst keine Spalte zugang_versiegelt: auch versiegelt hat das
        # Geheimnis auf der Seite nichts verloren.
        liste = "".join(
            f'<tr><td data-label="Kennung">{e(k["kennung"])}</td>'
            f'<td data-label="Anbieter">{e(k["anbieter"])}</td>'
            f'<td data-label="Adresse">{e(k["adresse"])}</td>'
            f'<td data-label="Altbestand">'
            f'{"fertig" if k["altbestand_fertig"] else "läuft"}</td></tr>'
            for k in eigene)
        tabelle = ('<table><thead><tr><th>Kennung</th><th>Anbieter</th>'
                   f'<th>Adresse</th><th>Altbestand</th></tr></thead><tbody>{liste}'
                   '</tbody></table>' if eigene
                   else '<p class="meta">Noch kein Postfach angebunden.</p>')
        anbieter = "".join(
            f'<option value="{a}"{" selected" if werte.get("anbieter") == a else ""}>'
            f'{"GMX" if a == "gmx" else "Gmail"}</option>'
            for a in post_konten.UI_ANBIETER)
        # business ist vorgewaehlt (bisheriges Verhalten); nach einem Fehler
        # bleibt die Wahl stehen.
        gewaehlt = werte.get("standard_bereich") or "business"
        bereiche = "".join(
            f'<option value="{b_}"{" selected" if gewaehlt == b_ else ""}>{n}</option>'
            for b_, n in (("business", "Business"), ("privat", "Privat")))
        # Das Passwortfeld bleibt IMMER leer - auch nach einem Fehler.
        formular = (
            '<form method="post" action="/post/konten" class="karte">'
            '<h2>Postfach hinzufügen</h2>'
            f'<input type="hidden" name="csrf" value="{e(ui.CSRF_TOKEN)}">'
            f'<label>Anbieter <select name="anbieter">{anbieter}</select></label> '
            f'<label>Standardbereich <select name="standard_bereich">{bereiche}'
            '</select></label> '
            '<label>Kennung <input type="text" name="kennung" required '
            f'maxlength="31" value="{e(werte.get("kennung", ""))}" '
            'placeholder="z. B. gmx-privat" autocapitalize="none" spellcheck="false"></label> '
            '<label>Adresse <input type="email" name="adresse" required '
            f'maxlength="{FELD_MAX}" value="{e(werte.get("adresse", ""))}" '
            'autocapitalize="none" spellcheck="false"></label> '
            '<label>Passwort / App-Passwort <input type="password" name="passwort" '
            'required autocomplete="off"></label> '
            '<p class="meta">Vor dem Speichern meldet sich sales-claw einmal am '
            'Postfach an. Das Passwort wird sofort versiegelt; lesen kann es nur '
            'der Abholdienst.</p><button class="primaer">Prüfen und speichern</button>'
            '</form>')
        rumpf = ((f'<p class="fehler">{e(fehler)}</p>' if fehler else "")
                 + '<p><a href="/post">← Mails</a></p>'
                 + f'<h2>Deine Postfächer</h2>{tabelle}{formular}')
        return ui._seite("Postfächer", rumpf, status=status)

    def nur_freigeben():
        return ui._fehlerseite(403, "Nicht für diese Anmeldung",
                               "Postfächer anbinden darf nur die Rolle "
                               "„freigeben“. Nichts geändert.")

    @ui._gesichert_seite
    async def konten(request):
        b = betrachter(request)
        if b is None:
            return gesperrt()
        if rolle(request) != "freigeben":
            return nur_freigeben()
        if request.method != "POST":
            return konten_seite(b)
        form = await request.form()
        if not ui._csrf_ok(form):
            return ui._fehlerseite(403, "CSRF-Token fehlt oder ist ungültig",
                                   "Nichts gespeichert. Seite neu laden.")
        werte = {"anbieter": str(form.get("anbieter") or ""),
                 "kennung": str(form.get("kennung") or "").strip()[:40],
                 "adresse": str(form.get("adresse") or "").strip()[:FELD_MAX],
                 "standard_bereich": str(form.get("standard_bereich") or "business")}
        passwort = str(form.get("passwort") or "")
        import post_konten
        try:
            # Die Probe-Anmeldung blockiert (IMAP) - nicht im Event-Loop.
            ergebnis = await run_in_threadpool(
                post_konten.konto_anlegen, b.name, werte["kennung"],
                werte["anbieter"], werte["adresse"], passwort,
                werte["standard_bereich"])
        except psycopg.Error:
            raise
        except Exception as fehler:  # noqa: BLE001 - nur der Typ, der Text koennte das Passwort tragen
            ergebnis = {"fehler": f"Postfach nicht angelegt ({type(fehler).__name__})"}
        if "fehler" in ergebnis:
            return konten_seite(b, str(ergebnis["fehler"]), werte, status=400)
        return RedirectResponse("/post/konten", status_code=303)

    return [
        Route("/post", liste),
        Route("/post/konten", konten, methods=["GET", "POST"]),
        Route("/post/aufraeumen", aufraeumen),
        Route("/post/aufraeumen/{jahr}", aufraeumen_jahr, methods=["GET", "POST"]),
        Route("/post/aufraeumen/{jahr}/absender", aufraeumen_absender),
        Route("/post/mail/{mail_id}", mail),
        Route("/post/mail/{mail_id}/korrigieren", korrigieren, methods=["POST"]),
        Route("/post/mail/{mail_id}/vorschlag", vorschlag, methods=["POST"]),
        Route("/post/mail/{mail_id}/ziel", ziel_setzen, methods=["POST"]),
    ]
