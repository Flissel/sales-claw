"""sperrliste — sales-Seite der gemeinsamen Verbotsliste (F1, 03.09.2026).

compliance.sperrliste liegt in derselben Postgres wie unsere leads UND
Marketings marketing.* — Marketing schreibt Unsubscribes und Bounces hinein,
wir schreiben Widerrufe und Loeschantraege. Vor jeder ERSTANSPRACHE wird
gefragt; ein Treffer ist eine Ablehnung mit Grund, keine Warnung.

KENNUNGEN exakt wie Marketings spaces/marketing/tools/sperrliste.py bilden —
sonst sieht keine Seite die Sperre der anderen:
    email:<kleingeschrieben, getrimmt>      tel:+<ziffern, E.164 ohne Formatierung>
„(0)"-Vorwahlnull faellt weg, „00" wird „+", nationale Null wird +49
(deutscher Betrieb, dokumentierte Annahme), WhatsApp-Chat-IDs liefern ihren
Ziffernteil.

NUR STANDARDBIBLIOTHEK; der Datenbankgriff wird hereingereicht (server._q),
damit das Modul ohne Datenbank pruefbar bleibt.
"""
import re
from typing import Callable, List, Optional

Abfrage = Callable[..., list]


def kennung_email(text: Optional[str]) -> Optional[str]:
    e = (text or "").strip().lower()
    if "@" not in e or any(c.isspace() for c in e):
        return None
    return "email:" + e


def kennung_tel(text: Optional[str]) -> Optional[str]:
    t = (text or "").strip()
    if "@" in t:                      # WhatsApp-Chat-ID 4917...@c.us
        t = t.split("@", 1)[0]
    t = t.replace("(0)", "")
    plus = t.startswith("+")
    ziffern = re.sub(r"\D", "", t)
    if not ziffern:
        return None
    if ziffern.startswith("00"):
        ziffern = ziffern[2:]
    elif not plus and ziffern.startswith("0"):
        ziffern = "49" + ziffern[1:]
    if len(ziffern) < 6:
        return None
    return "tel:+" + ziffern


def kennungen(email: str = "", phone: str = "") -> List[str]:
    """E-Mail zuerst, dann Telefon — leere Eingaben liefern nichts."""
    ks = []
    for k in (kennung_email(email), kennung_tel(phone)):
        if k and k not in ks:
            ks.append(k)
    return ks


def gesperrt(q: Abfrage, email: str = "", phone: str = "") -> Optional[str]:
    """'quelle: grund' der ersten aktiven Sperre — oder None. Fragt nur, wenn es
    eine Kennung gibt."""
    ks = kennungen(email, phone)
    if not ks:
        return None
    rows = q("select kennung, quelle, grund from compliance.sperrliste "
             "where kennung = any(%s) and aufgehoben_am is null", (ks,)) or []
    if not rows:
        return None
    r = rows[0]
    return f"{r.get('quelle', '')}: {r.get('grund', '')}".strip(": ")


def sperren(q: Abfrage, email: str = "", phone: str = "", *, quelle: str, grund: str = "") -> int:
    """Sperrt jede Kennung ueber compliance.sperren (idempotent). Rueckgabe: Anzahl."""
    ks = kennungen(email, phone)
    for k in ks:
        q("select compliance.sperren(%s, %s, %s)", (k, quelle, grund))
    return len(ks)
