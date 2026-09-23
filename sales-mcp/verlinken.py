"""Text -> HTML mit anklickbaren Adressen. Die EINE Regel dafuer im Haus.

Eigenes, abhaengigkeitsfreies Modul aus demselben Grund wie `nummern.py`:
zwei Komponenten muessen dieselbe Antwort geben, und keine darf die andere
importieren. `ui.py` zeigt Texte an, `mail_dispatch.py` verschickt sie — und
`mail_dispatch` kann `ui` nicht laden, ohne die ganze Web-Anwendung
mitzuziehen.

Die Forderung ist die des Betreibers vom 03.09.2026: „Hyperlinks werden
nicht korrekt als Hyperlinks angezeigt, sondern als Text." Erfuellt wurde sie
damals nur in der Oberflaeche. Die ausgehende Mail blieb reiner Text. Am
23.09.2026 trug eine Terminbestaetigung an einen Kunden ihren Konferenzlink
als nackte Zeichenkette. Seither benutzen beide Seiten diese Funktion.

REIHENFOLGE: erst escapen, dann verlinken, nie umgekehrt. Nur http(s) wird
zum Link; `javascript:`, `ftp:` und alles andere bleiben Text. Satzzeichen am
Ende („…siehe https://x.de.") gehoeren nicht zur Adresse.
"""
import html
import re

# Die Suche laeuft auf dem bereits ESCAPTEN Text: escapte Anfuehrungszeichen
# (&quot; &#x27;) und Klammern (&lt; &gt;) beenden eine Adresse, statt Teil
# von ihr zu werden.
URL_MUSTER = re.compile(
    r"https?://(?:(?!&quot;|&#x27;|&lt;|&gt;)[^\s<>\"'])+")
URL_SATZZEICHEN = ".,;:)!?"

_ROH_LINK = re.compile(r"https?://\S")


def enthaelt_link(text) -> bool:
    """Steht im (unescapten) Text eine http(s)-Adresse?"""
    return bool(_ROH_LINK.search(str(text or "")))


def text_html(text, attribute: str = "") -> str:
    """Escaptes HTML, in dem http(s)-Adressen `<a href>` sind.

    `attribute` wird unveraendert in jedes `<a …>` gesetzt (die Oberflaeche
    oeffnet Links in einem neuen Reiter, die Mail braucht das nicht). Es ist
    ein fester Wert des Aufrufers, nie Fremdtext.
    """
    sicher = html.escape(str(text if text is not None else ""), quote=True)

    def _link(treffer):
        url, rest = treffer.group(0), ""
        while url and url[-1] in URL_SATZZEICHEN:
            rest, url = url[-1] + rest, url[:-1]
        return f'<a href="{url}"{attribute}>{url}</a>{rest}'
    return URL_MUSTER.sub(_link, sicher)
