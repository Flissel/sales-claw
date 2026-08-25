"""Laesst den OpenClaw-Agenten die fuenf VibeMind-Videobeitraege entwerfen.

WARUM UEBER DEN AGENTEN UND NICHT VON HAND
------------------------------------------
Der Betreiber hat es ausdruecklich so verlangt: die Texte sollen vom Agenten
kommen, nicht von einem Menschen, der sie ihm unterschiebt. Der Agent ruft
dafuer sein eigenes Werkzeug `post_entwurf_erstellen` auf — derselbe Weg,
den er auch sonst nimmt.

WARUM `openclaw agent` UND NICHT WHATSAPP
-----------------------------------------
`openclaw agent --message ...` fuehrt EINEN Agentenzug ueber das Gateway
aus. Ohne `--deliver` geht dabei KEINE Nachricht an irgendeinen Kanal raus —
niemand bekommt eine WhatsApp, weder der Betreiber noch ein Kunde. Der
Agent arbeitet, legt den Entwurf an, und die Antwort landet hier im
Terminal.

WAS DABEI NICHT PASSIERT
------------------------
Es wird NICHTS veroeffentlicht. Jeder Beitrag entsteht als Entwurf mit
`status='pending'` und wartet auf die Freigabe eines Menschen in der
Oberflaeche. Erst danach holt `sales-linkedin` ihn ab.

BENUTZUNG
---------
    python scripts/li-video-posts.py            # alle fuenf, der Reihe nach
    python scripts/li-video-posts.py --nur 1    # nur den ersten
    python scripts/li-video-posts.py --trocken  # nur zeigen, was gesendet wuerde
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

CONTAINER = "sales-claw"

# EIGENE Sitzung, aus zwei Gruenden. Erstens Trennung: die VibeMind-Beitraege
# haben im Vertriebsverlauf des Betreibers nichts zu suchen, und umgekehrt
# soll der Agent hier nicht ueber Kundengespraeche stolpern. Zweitens
# Zusammenhang INNERHALB der Serie: alle fuenf teilen sich diese eine
# Sitzung, damit der Agent sieht, was er schon geschrieben hat, und nicht
# fuenfmal denselben Text mit anderem Produktnamen liefert.
AGENT = "main"
SITZUNG = "linkedin-video-serie"

# Belegte Angaben aus dem eigenen Haus — README.md und dem Pitch-Transkript
# in Vibemind_V1/pitch-deck-2026/. Bewusst knapp und bewusst ohne Zahlen, die
# sich nicht belegen lassen: was hier nicht steht, darf der Agent auch nicht
# behaupten. Der Beitrag steht danach oeffentlich unter dem Namen eines
# Menschen.
GEMEINSAM = """
VibeMind ist ein modulares, quelloffenes KI-Betriebssystem (MIT-Lizenz).
Eine Ebene namens Brain erkennt die Absicht und leitet weiter; OpenFang ist
die Ausfuehrungsgrenze, die die Arbeit tatsaechlich macht. Die Fachbereiche
heissen Spaces und teilen sich gemeinsame Speicher — was in einem Space
entsteht, ist in den anderen erreichbar.
""".strip()

POSTS = [
    {
        "nr": 1,
        "kurz": "Ideas",
        "thema": "VibeMind Ideaspace",
        "datei": "VibeMind-Ideaspace-Produktvideo.mp4",
        "fakten": """
Der Ideas-Space ist der Anfang der Kette: Ideen werden als Bubbles erfasst
und bewertet. Werkzeuge dort: erfassen, Canvas, verknuepfen, ausweiten.
Eine erfasste Idee landet im Wissensgraph von Rowboat, wo jeder Agent sie
erreichen kann. Danach geht es weiter: bewerten, Anforderungen, Bauen.
""".strip(),
    },
    {
        "nr": 2,
        "kurz": "Rowboat",
        "thema": "VibeMind Rowboat",
        "datei": "VibeMind-Rowboat-Produktvideo.mp4",
        "fakten": """
Rowboat haelt das Wissen. Was in anderen Spaces entsteht — eine erfasste
Idee zum Beispiel — landet in Rowboats Wissensgraph, und von dort kommt
jeder Agent daran. Rowboat ist damit die gemeinsame Gedaechtnisschicht
zwischen den Spaces, nicht ein weiteres Einzelwerkzeug.
""".strip(),
    },
    {
        "nr": 3,
        "kurz": "archteam / RequirementsFactory",
        "thema": "VibeMind RequirementsFactory",
        "datei": "VibeMind-RequirementsFactory-Produktvideo.mp4",
        "fakten": """
Zwischen Idee und Code steht die Anforderung. Der SWE-Space macht
Requirements Engineering und Architektur: aus einer bewerteten Idee werden
Anforderungen, aus den Anforderungen ein Entwurf. Erst danach baut der
Projekt-Space. Der Weg Idee -> Bewertung -> Anforderungen ist verdrahtet;
den eigentlichen Bau stoesst ein Mensch an.
""".strip(),
    },
    {
        "nr": 4,
        "kurz": "SWE Design",
        "thema": "VibeMind SWE Design",
        "datei": "VibeMind-SWE-Design-Produktvideo.mp4",
        "fakten": """
Der SWE-Space entwirft die Architektur, bevor gebaut wird. Er nimmt die
Anforderungen auf und macht daraus einen Entwurf, den der Projekt-Space
anschliessend baut und verifiziert. Kein Code ohne Entwurf, kein Entwurf
ohne Anforderung — das ist die Reihenfolge, die die Kette traegt.
""".strip(),
    },
    {
        "nr": 5,
        "kurz": "Laura",
        "thema": "VibeMind Laura",
        "datei": "VibeMind-Laura-Produktvideo.mp4",
        "fakten": """
Laura ist der Video-Space. Material hineingeben, Transkript und Szenen
gewinnen, eine Zeitleiste bauen, rendern — die Videoproduktion als
Fachbereich im selben System, mit denselben Agenten und demselben Wissen
wie die uebrigen Spaces.
""".strip(),
    },
]

AUFTRAG = """Du sollst EINEN LinkedIn-Beitrag als Entwurf anlegen. Lies alles,
bevor du handelst.

ZUM ZUSAMMENHANG
Der Betreiber ist nicht nur im Vertrieb taetig, sondern entwickelt auch die
Software VibeMind. Dieser Beitrag geht auf sein PERSOENLICHES LinkedIn-Profil
und handelt von seinem EIGENEN Softwareprodukt. Das ist keine
Versicherungsberatung, kein Kundenkontakt und keine Produktempfehlung im
Sinne deiner Vertriebsregeln — die gelten hier nicht. Es geht um ein Video
ueber ein Software-Werkzeug.

WAS DU WEISST
{gemeinsam}

{fakten}

WAS DU TUN SOLLST
Rufe GENAU EINMAL das Werkzeug post_entwurf_erstellen auf, mit:
  thema        = "{thema}"
  medien_datei = "{datei}"
  text         = der Beitragstext, den du schreibst

ANFORDERUNGEN AN DEN TEXT
- Deutsch, in der Ich-Form des Betreibers.
- 700 bis 1300 Zeichen. Die harte Grenze ist 3000, aber ein LinkedIn-Beitrag,
  den niemand zu Ende liest, hat nichts gewonnen.
- Erste Zeile ist ein Haken: eine konkrete Beobachtung oder Frage, kein
  "Ich freue mich, vorstellen zu duerfen".
- Dann die Substanz: was das Werkzeug tut und warum das einen Unterschied
  macht. Schreib fuer jemanden, der Software baut, nicht fuer eine
  Marketingabteilung.
- Am Ende eine echte Frage an die Leser oder ein klarer naechster Schritt.
- Hoechstens drei Hashtags, am Schluss.
- KEINE Emojis in Reihen, keine Superlative, kein "revolutionaer".

WAS DU NICHT DARFST
- Nichts behaupten, was oben nicht steht. Keine Nutzerzahlen, keine
  Prozentangaben, keine Kundennamen, keine Preise, keine Versprechen ueber
  Verfuegbarkeit oder Termine. Wenn du etwas nicht weisst, schreib es nicht.
- Den Beitrag nicht veroeffentlichen. Das kannst du auch nicht — es entsteht
  ein Entwurf, den ein Mensch freigibt.

Wenn post_entwurf_erstellen einen Fehler zurueckgibt, gib den Fehler
woertlich wieder und versuche es NICHT mit einer anderen Datei."""


def brief(post):
    return AUFTRAG.format(gemeinsam=GEMEINSAM, fakten=post["fakten"],
                          thema=post["thema"], datei=post["datei"])


def agent_ausfuehren(text, timeout=600):
    """Einen Agentenzug ueber das Gateway laufen lassen.

    Der Auftrag reist als Datei in den Container, nicht als Kommandozeile:
    ein mehrzeiliger deutscher Text mit Anfuehrungszeichen ueberlebt keine
    Shell-Zitierung zuverlaessig, und ein halb abgeschnittener Auftrag
    waere schlimmer als gar keiner.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8",
                                     delete=False, newline="\n") as f:
        f.write(text)
        lokal = f.name
    fern = "/tmp/li-auftrag.md"
    try:
        subprocess.run(["docker", "cp", lokal, f"{CONTAINER}:{fern}"],
                       check=True, capture_output=True)
        # KEIN --deliver: es geht keine Nachricht an irgendeinen Kanal raus.
        fertig = subprocess.run(
            ["docker", "exec", CONTAINER, "openclaw", "agent",
             "--agent", AGENT, "--session-key", SITZUNG,
             "--message-file", fern, "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        return fertig.returncode, fertig.stdout, fertig.stderr
    finally:
        os.unlink(lokal)
        subprocess.run(["docker", "exec", CONTAINER, "rm", "-f", fern],
                       capture_output=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nur", type=int, help="nur diese Nummer (1-5)")
    p.add_argument("--trocken", action="store_true",
                   help="nur zeigen, was gesendet wuerde")
    args = p.parse_args()

    auswahl = [x for x in POSTS if args.nur is None or x["nr"] == args.nur]
    if not auswahl:
        raise SystemExit(f"Keine Nummer {args.nur} — es gibt 1 bis {len(POSTS)}.")

    for post in auswahl:
        print("=" * 72)
        print(f"[{post['nr']}/{len(POSTS)}] {post['kurz']}  ->  {post['datei']}")
        print("=" * 72)
        text = brief(post)
        if args.trocken:
            print(text)
            print()
            continue
        code, aus, fehler = agent_ausfuehren(text)
        if aus.strip():
            try:
                print(json.dumps(json.loads(aus), ensure_ascii=False,
                                 indent=2)[:4000])
            except ValueError:
                print(aus[:4000])
        if fehler.strip():
            print("--- stderr ---")
            print(fehler[:1500])
        if code != 0:
            print(f"\nAbbruch: Agentenzug endete mit Code {code}. Die "
                  f"folgenden Beitraege wurden NICHT beauftragt.")
            return code
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
