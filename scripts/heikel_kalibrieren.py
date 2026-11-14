"""Kalibrierung der lokalen Heikel-Erkennung (sales-auge, Schicht A). NUR LESEND.

Aufruf (Einmal-Container aus dem Produktionsdienst, eigenes Speicherlimit):
  ssh offload-vm 'cd ~/sales-claw && docker compose run --rm --no-deps -T sales-auge \
      timeout 900 python -' < scripts/heikel_kalibrieren.py

Laedt die Bilder der Akten 3c9afada... und 54ac1821... (nur SELECT), setzt die
Wahrheit "heikel" aus der Beschreibung per Stichwort, rechnet je Bild
  d = max(cos(bild, heikel_i)) - max(cos(bild, neutral_j))
und druckt fuer Abstaende 0,00 .. 0,10 (Schritt 0,005) Treffer und Fehlalarme.
Ausgabe: NUR Zahlen - keine Beschreibungen, keine Namen, keine Bilddaten.
Selbstenthalten: importiert heikel.py NICHT (nicht im Produktionsabbild); die
Klassentexte stehen hier als Kopie und muessen mit heikel.py uebereinstimmen.
"""
import math
import re

import server
from einbetter_fastembed import FastEmbedEinbetter

KLASSEN_HEIKEL = ("a login page with a password field",
                  "a sign in with Google account chooser",
                  "a payment checkout page with credit card fields",
                  "an email inbox with a list of messages",
                  "an opened email message")
KLASSEN_NEUTRAL = ("a presentation slide", "a website", "a document in a text editor",
                   "a chat with an AI assistant", "a video call")
STICHWORT = re.compile(r"passwort|anmelde|sign in|login|checkout|zahlung|kreditkarte|"
                       r"bezahl|posteingang|inbox|e-mail-postfach|gmx", re.I)


def cos(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def main() -> None:
    zeilen = server._q(
        "select bild, beschreibung from termin_bilder "
        "where left(uid, 8) in ('3c9afada', '54ac1821') order by aufgenommen_am")
    e = FastEmbedEinbetter()
    th = [e.text_clip(t) for t in KLASSEN_HEIKEL]
    tn = [e.text_clip(t) for t in KLASSEN_NEUTRAL]
    daten = []          # (abstand, wahr)
    ohne = 0
    for z in zeilen:
        if not (z["beschreibung"] or "").strip():
            ohne += 1
            continue
        v = e.bild(bytes(z["bild"]))
        d = max(cos(v, t) for t in th) - max(cos(v, t) for t in tn)
        daten.append((d, bool(STICHWORT.search(z["beschreibung"]))))
    pos = sum(1 for _, w in daten if w)
    neg = len(daten) - pos
    print(f"bilder_gesamt={len(zeilen)} ohne_beschreibung={ohne} bewertet={len(daten)} "
          f"heikel_wahr={pos} neutral_wahr={neg}")
    if daten:
        ds = sorted(d for d, _ in daten)
        print("abstand_min=%.4f median=%.4f max=%.4f" % (ds[0], ds[len(ds) // 2], ds[-1]))
        for name, sel in (("heikel", True), ("neutral", False)):
            xs = sorted(d for d, w in daten if w is sel)
            if xs:
                print("%s: min=%.4f p25=%.4f median=%.4f p75=%.4f max=%.4f"
                      % (name, xs[0], xs[len(xs) // 4], xs[len(xs) // 2],
                         xs[(3 * len(xs)) // 4], xs[-1]))
    print("abstand;treffer;treffer_quote;fehlalarme;fehlalarm_quote")
    for i in range(0, 21):
        a = i * 0.005
        t = sum(1 for d, w in daten if w and d > a)
        f = sum(1 for d, w in daten if not w and d > a)
        print("%.3f;%d/%d;%.1f%%;%d/%d;%.1f%%" % (
            a, t, pos, 100 * t / pos if pos else 0, f, neg, 100 * f / neg if neg else 0))


main()
