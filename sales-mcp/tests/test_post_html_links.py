"""Links aus HTML-Mails bleiben erhalten (Betreiber 08.11.2026).

Mails, die nur als HTML kommen, verloren beim Abholen ihre Zieladressen:
aus <a href="https://…">Hier klicken</a> wurde nur "Hier klicken". Fuer die
Post-Sammelstelle behaelt die Umwandlung die Adresse jetzt in Klammern hinter
dem Linktext; die Mailansicht macht sie anklickbar (verlinken.py). Die
Einordnung sieht diese Klammern NICHT - ihr 4000-Zeichen-Fenster soll nicht mit
Tracking-Adressen volllaufen.
"""
import os
import sys
from email.message import EmailMessage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import post_abholen  # noqa: E402
import post_einordnung  # noqa: E402
import postfach  # noqa: E402

HTML = ('<html><style>p{color:red}</style><body><p>Termin &amp; Ablauf:&nbsp;'
        '<a href="https://meet.example.de/r?a=1&amp;b=2">Hier <b>klicken</b></a>.</p>'
        '<a href="https://x.de/">https://x.de/</a> '
        '<a href="mailto:info@x.de">Schreiben</a> '
        '<a href="javascript:alert(1)">Boese</a> '
        '<a href="https://t.de/bild"><img src="https://t.de/b.png"></a> '
        '<a href="https://y.de/a b">Leerzeichen</a> '
        '<a href="https://y.de/(klammer)">Klammer</a></body></html>')


def test_html_link_behaelt_adresse():
    text = postfach._html_zu_text(HTML, links=True)
    assert "Hier klicken (https://meet.example.de/r?a=1&b=2)" in text
    assert "Termin & Ablauf:" in text            # HTML-Kuerzel aufgeloest
    assert text.count("https://x.de/") == 1      # Text = Adresse: nicht doppelt
    assert "mailto" not in text and "Schreiben" in text
    assert "javascript" not in text and "Boese" in text
    assert "t.de/bild" not in text               # Bildlink ohne Text: nichts
    assert "y.de/a b" not in text and "Leerzeichen" in text
    assert "(klammer)" not in text and "Klammer" in text
    assert "color" not in text


def test_ohne_schalter_bleibt_alles_wie_bisher():
    # Der Posteingang des Verkaufs (postfach selbst) aendert sich nicht.
    text = postfach._html_zu_text(HTML)
    assert "https://meet" not in text and "&amp;" in text


def test_abholen_behaelt_links_aus_reinen_html_mails():
    nachricht = EmailMessage()
    nachricht["Subject"] = "Einladung"
    nachricht.set_content(HTML, subtype="html")
    assert ("Hier klicken (https://meet.example.de/r?a=1&b=2)"
            in post_abholen._text_sicher(nachricht))


def test_einordnung_sieht_die_adressen_nicht():
    text = postfach._html_zu_text(HTML, links=True)
    auftrag = post_einordnung._auftrag({"text": text, "von": "a@x.de", "betreff": "B"},
                                       {"kennung": "k", "standard_bereich": "business"})
    assert "Hier klicken" in auftrag
    assert "meet.example.de" not in auftrag
    # Ausgeschriebene Adressen im Fliesstext (auch in Textmails) bleiben.
    assert "https://x.de/" in auftrag
