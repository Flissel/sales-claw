"""Oberflaeche /newsletter/einwilligung (Betreiber 20.10.2026, A2 a+b).

Zwei saubere Wege zu mehr Newsletter-Empfaengern (opt_in):
  a) Im Gespraech fragen: die Frage geht als Entwurf in die Freigabe, das Ja
     erfasst der Betreiber mit Quelle und Wortlaut (server._newsletter_einwilligung_*).
  b) Selbst anmelden: eine Mail mit Betreff "Anmelden" an das Postfach des Ladens,
     danach Bestaetigung per Code (newsletter_anmeldung.py, laeuft in sales-mail).
     Hier stehen nur der Link und sein QR-Code fuer Webseite und Visitenkarte.
"""
import os
from urllib.parse import quote

from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import server

_HINWEIS_MAX = 300


def anmelde_link() -> str:
    """mailto:-Link fuer die Selbst-Anmeldung - oder '' ohne Absenderadresse."""
    absender = os.environ.get("EMAIL_ABSENDER", "").strip()
    return f"mailto:{absender}?subject=Anmelden" if "@" in absender else ""


def qr_svg(text: str) -> str:
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    w = QrCodeWidget(text)
    x0, y0, x1, y1 = w.getBounds()
    groesse = 240
    d = Drawing(groesse, groesse, transform=[groesse / (x1 - x0), 0, 0, groesse / (y1 - y0), 0, 0])
    d.add(w)
    return renderSVG.drawToString(d)


def _datum(wert) -> str:
    return f"{wert:%d.%m.%Y}" if wert else ""


def _weiter(hinweis: str = ""):
    ziel = "/newsletter/einwilligung"
    if hinweis:
        ziel += f"?hinweis={quote(hinweis[:_HINWEIS_MAX])}"
    return RedirectResponse(ziel, status_code=303)


def routen(ui):
    e = ui._e

    @ui._gesichert_seite
    async def seite(request):
        schreiben = ui._AKTIVE_ROLLE.get() not in ("lesen", "kalender")
        hinweis = str(request.query_params.get("hinweis") or "")[:_HINWEIS_MAX]
        teile = [f'<div class="hinweis">{e(hinweis)}</div>' if hinweis else ""]
        anzahl = server._q("select count(*) as n from leads where consent_status = 'opt_in' "
                           "and coalesce(btrim(email), '') <> ''")[0]["n"]
        teile.append(f'<p><b>{e(anzahl)}</b> Kontakte haben ausdrücklich eingewilligt und bekommen '
                     f'den Newsletter. Andere Kontakte bekommen ihn nicht.</p>')

        link = anmelde_link()
        teile.append('<h2>Selbst anmelden (Double-Opt-in)</h2><div class="karte">')
        if link:
            adresse = link[len("mailto:"):].split("?")[0]
            teile.append(
                f'<p>Wer eine Mail mit dem Betreff <b>Anmelden</b> an <b>{e(adresse)}</b> schickt, '
                f'bekommt automatisch eine Bestätigungsmail mit Code. Erst die Antwort darauf zählt '
                f'als Einwilligung. Das Postfach wird alle 10 Minuten geprüft.</p>'
                f'<p>Link für Webseite oder Signatur: <code>{e(link)}</code></p>'
                f'<p><img src="/newsletter/einwilligung/qr.svg" alt="QR-Code zur Anmeldung" '
                f'width="160" height="160"> <a href="/newsletter/einwilligung/qr.svg" '
                f'download="newsletter-anmelden.svg">QR-Code herunterladen</a> (für die Visitenkarte)</p>')
        else:
            teile.append('<p class="meta">Keine Absenderadresse (EMAIL_ABSENDER) eingerichtet – '
                         'ohne Postfach gibt es keine Anmeldung per Mail.</p>')
        teile.append('</div>')

        teile.append('<h2>Im Gespräch fragen</h2>'
                     '<p class="meta">Nur Kontakte, mit denen schon ein Gespräch läuft. „Anfragen“ '
                     'legt eine E-Mail in die Freigabe, es geht nichts von selbst raus. Sagt der '
                     'Kontakt Ja, trage es hier mit seinem Wortlaut ein.</p>')
        zeilen = []
        for k in server._newsletter_kandidaten():
            name = f'<a href="/kontakte/{e(k["id"])}">{e(k["name"])}</a>'
            stand = f'gefragt am {e(_datum(k["angefragt"]))}' if k["angefragt"] else "noch nicht gefragt"
            if k["leitfaden_antwort"]:
                stand += f' · Leitfaden: „{e(k["leitfaden_antwort"][:120])}“'
            aktion = ""
            if schreiben:
                aktion = (
                    f'<form method="post" action="/newsletter/einwilligung/anfragen" class="aktion">'
                    f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
                    f'<input type="hidden" name="lead_id" value="{e(k["id"])}">'
                    f'<button type="submit">Anfragen</button></form>'
                    f'<form method="post" action="/newsletter/einwilligung/erfassen" class="aktion">'
                    f'<input type="hidden" name="csrf" value="{ui.CSRF_TOKEN}">'
                    f'<input type="hidden" name="lead_id" value="{e(k["id"])}">'
                    f'<select name="quelle">'
                    + "".join(f'<option>{e(q)}</option>' for q in server.NEWSLETTER_QUELLEN) +
                    f'</select> <input name="wortlaut" maxlength="500" required '
                    f'placeholder="Was hat der Kontakt gesagt?" value="{e(k["leitfaden_antwort"][:500])}"> '
                    f'<button type="submit">Ja erfassen</button></form>')
            zeilen.append([name, e(k["company"]), e(k["email"]), e(_datum(k["zuletzt"])), stand, aktion])
        teile.append(ui._tabelle(["Name", "Firma", "E-Mail", "zuletzt geschrieben", "Stand", ""], zeilen)
                     if zeilen else '<p class="meta">Gerade niemand, den wir fragen können.</p>')
        return ui._seite("Newsletter-Einwilligung", "".join(teile))

    @ui._gesichert_seite
    async def qr(request):
        link = anmelde_link()
        if not link:
            return ui._fehlerseite(404, "Nicht eingerichtet", "Keine Absenderadresse (EMAIL_ABSENDER).")
        return Response(qr_svg(link), media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})

    @ui._gesichert_seite
    async def anfragen(request):
        form, lead_id, abbruch = await ui._kontakt_vorspann(request)
        if abbruch:
            return abbruch
        r = server._newsletter_einwilligung_anfragen(lead_id)
        if "fehler" in r:
            return _weiter(r["fehler"])
        return _weiter("Die Frage liegt als Entwurf in der Freigabe – es ging nichts raus.")

    @ui._gesichert_seite
    async def erfassen(request):
        form, lead_id, abbruch = await ui._kontakt_vorspann(request)
        if abbruch:
            return abbruch
        r = server._newsletter_einwilligung_erfassen(
            lead_id, str(form.get("quelle") or ""), str(form.get("wortlaut") or ""))
        if "fehler" in r:
            return _weiter(r["fehler"])
        return _weiter("Einwilligung erfasst – der Kontakt bekommt ab jetzt den Newsletter.")

    return [
        Route("/newsletter/einwilligung", seite),
        Route("/newsletter/einwilligung/qr.svg", qr),
        Route("/newsletter/einwilligung/anfragen", anfragen, methods=["POST"]),
        Route("/newsletter/einwilligung/erfassen", erfassen, methods=["POST"]),
    ]
