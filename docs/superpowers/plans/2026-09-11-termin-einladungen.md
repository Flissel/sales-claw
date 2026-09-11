# Termin-Einladungen: Implementierungsplan

> **Für agentische Bearbeiter:** ERFORDERLICHE UNTER-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe
> abzuarbeiten. Die Schritte tragen Checkbox-Syntax (`- [ ]`).

**Ziel:** Ein Termin wird als Einladung verschickt, die der Empfänger annehmen, mit Grund
ablehnen oder mit einem Gegenvorschlag beantworten kann — statt still in einen fremden
Kalender geschrieben zu werden.

**Architektur:** Die bestehende Kalenderdatei bleibt unverändert (sie ist für CalDAV und
darf laut RFC 4791 kein `METHOD:` tragen). Daneben entsteht eine **zweite Fassung
derselben Buchung** für den Versand per E-Mail — mit `METHOD:REQUEST`, Veranstalter und
Teilnehmern. Der Mailversand lernt, einen Kalenderteil mitzuschicken; das Postfach lernt,
Antworten zu erkennen. Alles Ausgehende läuft weiter durch das bestehende Freigabe-Gate.

**Technik:** Python 3.12, `email.message.EmailMessage`, `smtplib`, `imaplib`, Starlette,
Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-team-terminabstimmung-design.md` (§2.3, §2.4)
— dieser Plan setzt die **Einladungs-Hälfte** um. Die Sicht-Hälfte (§2.1, §2.2) bekommt
einen eigenen Plan, sobald der Torschritt der Spec (§6, Prüfung 1) gemessen ist.

**Was dieser Plan bewusst NICHT abdeckt** (und wo es hingehört):

* §2.1/§2.2 — Kalenderquellen als Liste, personenübergreifende Überlappungsprüfung. Der
  Torschritt entscheidet über ihren Umfang, deshalb sind sie hier nicht geplant.
* §2.5 Team-Sicht im Kalender — gehört zur Sicht-Hälfte. **Der Einladungsstand** am Kontakt
  (wer hat zugesagt, wer abgesagt und warum) steckt dagegen in Aufgabe 6 dieses Plans.
* §2.6 Fähigkeiten je Quelle anzeigen — setzt die Quellenliste aus §2.1 voraus.
* §3 Einrichtung (zweiter Kalender, Freigaben) und §4 Datenschutz-Dokumente — Arbeit des
  Betreibers bzw. Dokumentenarbeit, kein Code.

## Globale Randbedingungen

- **Das Freigabe-Gate bleibt unangetastet.** Eine Einladung ist eine ausgehende Nachricht
  und läuft über `entwurf_erstellen` und die Freigabe des Betreibers. Es entsteht **kein
  zweiter Weg nach draußen**.
- **Die bestehende `kalender.ics()` wird NICHT verändert.** Sie trägt bewusst kein
  `METHOD:` (RFC 4791 §4.1; SabreDAV lehnt den PUT sonst mit HTTP 415 ab). Die
  Einladungsfassung kommt daneben, nicht an ihre Stelle.
- **Kein automatisches Zusagen.** Eingehende Einladungen und Gegenvorschläge werden dem
  Betreiber vorgelegt, nie selbst beantwortet.
- **Nur der eigene Kalender wird beschrieben.** In fremde Kalender wird nichts geschrieben.
- **Tests laufen gegen `SALES_DB_SCHEMA=sales_test`**, niemals gegen `sales`; die Variable
  wird **vor** `import server` gesetzt.
- **Anzeigetexte tragen echte Umlaute.** Ein Wächter-Test in `tests/test_darstellung.py`
  prüft die String-Literale in `ui.py`.
- **Kein JavaScript in der Oberfläche**, keine Lockerung der Content-Security-Policy.

### Testlauf (gilt für jeden „Run"-Schritt)

Die Umgebung aus der Oberflächen-Stufe wird weiterverwendet: Container `sales-testdb` im
Docker-Netz `sales-test-net`. Falls sie fehlt, so aufbauen:

```bash
docker network create sales-test-net
docker run -d --name sales-testdb --network sales-test-net \
  -e POSTGRES_PASSWORD=ci -p 55432:5432 pgvector/pgvector:pg16
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 \
  -c "create extension if not exists vector; create extension if not exists pgcrypto;"
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 < db/provision.sql
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 \
  < ../marketing/db/013b_compliance_test_schema.sql
```

Je Lauf, aus dem Wurzelverzeichnis von sales-claw:

```bash
docker build -t sales-mcp-ci ./sales-mcp
docker run --rm --network sales-test-net \
  -e SALES_DB_SCHEMA=sales_test \
  -e SALES_DB_URL="postgresql://postgres:ci@sales-testdb:5432/postgres" \
  sales-mcp-ci python -m pytest tests/<datei> -q --tb=short -p no:cacheprovider
```

Im Folgenden abgekürzt als `PYTEST tests/<datei>`.

**Nach jeder Änderung unter `sales-mcp/` das Image neu bauen** — sonst wird der alte Stand
getestet. Das ist hier die häufigste Falle.

**Ausgangswert:** `1565 passed` (Stand nach der Oberflächen-Stufe 1).

---

## Dateien

| Datei | Rolle |
|---|---|
| `sales-mcp/kalender.py` | **ändern** — `ics_einladung()` und `ics_antwort_lesen()` daneben stellen; `ics()` bleibt unberührt |
| `sales-mcp/mail_dispatch.py` | **ändern** — Kalenderteil im Versand, `anhang_nicht_unterstuetzt` fällt für `.ics` |
| `sales-mcp/postfach.py` | **ändern** — Antworten auf Einladungen erkennen |
| `sales-mcp/server.py` | **ändern** — Werkzeug `termin_einladen`, Vorlage von Antworten |
| `sales-mcp/ui.py` | **ändern** — Einladungsstand anzeigen |
| `sales-mcp/tests/test_einladung.py` | **neu** — Erzeugung und Lesen der Kalenderdaten |
| `sales-mcp/tests/test_mail_dispatch.py` | **ändern** — Versand mit Kalenderteil |
| `sales-mcp/tests/test_darstellung.py` | **ändern** — Anzeige des Einladungsstands |

---

## Aufgabe 1: Die Einladungsfassung der Kalenderdatei

Die bestehende `kalender.ics()` erzeugt eine Datei ohne `METHOD:` — richtig für CalDAV,
unbrauchbar für eine Einladung. Ein Mailprogramm zeigt erst dann „Annehmen / Ablehnen",
wenn `METHOD:REQUEST`, ein `ORGANIZER` und mindestens ein `ATTENDEE` mit `RSVP=TRUE`
vorhanden sind.

**Dateien:**
- Ändern: `sales-mcp/kalender.py`
- Neu: `sales-mcp/tests/test_einladung.py`

**Schnittstellen:**
- Verbraucht: `kalender.ics()`, `kalender._maskiere()`, `kalender._falte()`, `kalender.TZID`
- Erzeugt: `kalender.ics_einladung(uid, beginn, dauer_minuten, summary, veranstalter,
  eingeladene, ort="", beschreibung=BESCHREIBUNG, jetzt=None, folge=0) -> str`
  — `veranstalter` und jedes Element von `eingeladene` sind E-Mail-Adressen ohne
  `mailto:`-Präfix; `folge` ist die `SEQUENCE` (0 bei der ersten Einladung, +1 bei jeder
  Änderung derselben Buchung). Aufgaben 3 und 5 rufen das auf.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
"""Vertragstests der Einladungs-Kalenderdaten (Termin-Einladungen).

Eine Einladung ist NICHT dieselbe Datei wie der Kalendereintrag: RFC 4791
verbietet `METHOD:` auf einem CalDAV-Server, RFC 5546 verlangt es fuer eine
Einladung. Beide Fassungen beschreiben dieselbe Buchung unter derselben UID.
"""
import os
from datetime import datetime

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import kalender  # noqa: E402


def _zeilen(text):
    """Entfaltet die ICS-Faltung und liefert die Zeilen."""
    roh = text.replace("\r\n ", "").replace("\r\n\t", "")
    return roh.split("\r\n")


def test_einladung_traegt_method_request():
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"])
    assert "METHOD:REQUEST" in _zeilen(text)


def test_einladung_nennt_veranstalter_und_eingeladene():
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space", "kunde@beispiel.de"])
    zeilen = _zeilen(text)
    assert "ORGANIZER:mailto:felix@vibemind.space" in zeilen
    teilnehmer = [z for z in zeilen if z.startswith("ATTENDEE")]
    assert len(teilnehmer) == 2, teilnehmer
    assert all("RSVP=TRUE" in z for z in teilnehmer), teilnehmer
    assert all("PARTSTAT=NEEDS-ACTION" in z for z in teilnehmer), teilnehmer
    assert any(z.endswith(":mailto:ivan@vibemind.space") for z in teilnehmer)


def test_kalendereintrag_bleibt_ohne_method():
    """Die bestehende Fassung darf sich NICHT aendern — SabreDAV lehnt
    `METHOD:` mit HTTP 415 ab."""
    text = kalender.ics("abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch")
    assert "METHOD" not in text


def test_beide_fassungen_beschreiben_dieselbe_buchung():
    stempel = datetime(2026, 9, 11, 8, 0)
    gemeinsam = dict(uid="abc-123", beginn=datetime(2026, 10, 1, 14, 30),
                     dauer_minuten=30, summary="Erstgespräch", jetzt=stempel)
    eintrag = _zeilen(kalender.ics(**gemeinsam))
    einladung = _zeilen(kalender.ics_einladung(
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"], **gemeinsam))
    for feld in ("UID:abc-123", "DTSTART;TZID=Europe/Berlin:20261001T143000"):
        assert feld in eintrag, feld
        assert feld in einladung, feld


def test_folge_erscheint_als_sequence():
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"], folge=2)
    assert "SEQUENCE:2" in _zeilen(text)


def test_adressen_werden_geprueft():
    """Eine Zeichenkette ohne @ ist keine Adresse und darf nicht durchrutschen."""
    with pytest.raises(ValueError):
        kalender.ics_einladung(
            "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
            veranstalter="kein-at-zeichen", eingeladene=["ivan@vibemind.space"])
    with pytest.raises(ValueError):
        kalender.ics_einladung(
            "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
            veranstalter="felix@vibemind.space", eingeladene=[])
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_einladung.py`
Erwartet: FAIL mit `AttributeError: module 'kalender' has no attribute 'ics_einladung'`
(`test_kalendereintrag_bleibt_ohne_method` besteht bereits — das ist beabsichtigt, es ist
der Wächter gegen eine versehentliche Änderung der bestehenden Fassung).

- [ ] **Schritt 3: `ics_einladung` schreiben**

In `kalender.py`, direkt hinter `ics()`:

```python
def _adresse(wert: str) -> str:
    """Eine E-Mail-Adresse fuer ORGANIZER/ATTENDEE — ohne `mailto:`-Praefix.

    Geprueft wird nur das Noetigste: ein @ mit etwas davor und dahinter, und
    keine Zeichen, die eine ICS-Zeile zerlegen koennten. Eine kaputte Adresse
    hier wuerde eine Einladung erzeugen, die kein Mailprogramm zuordnen kann —
    lieber ein Fehler beim Bauen als eine stille Einladung ins Leere.
    """
    kern = (wert or "").strip()
    if kern.lower().startswith("mailto:"):
        kern = kern[7:]
    if "@" not in kern or kern.startswith("@") or kern.endswith("@"):
        raise ValueError(f"keine Adresse: {kern!r}")
    if any(z in kern for z in "\r\n,;:"):
        raise ValueError(f"unerlaubte Zeichen in Adresse: {kern!r}")
    return kern


def ics_einladung(uid: str, beginn, dauer_minuten: int, summary: str,
                  veranstalter: str = "", eingeladene=(), ort: str = "",
                  beschreibung: str = BESCHREIBUNG, jetzt=None,
                  folge: int = 0) -> str:
    """Dieselbe Buchung wie `ics()`, aber als EINLADUNG (RFC 5546).

    Unterschied zur CalDAV-Fassung, und warum es zwei gibt: RFC 4791 §4.1
    VERBIETET `METHOD:` in einem Kalenderobjekt auf einem CalDAV-Server
    (SabreDAV antwortet mit HTTP 415), RFC 5546 VERLANGT es fuer eine
    Einladung. Eine Datei kann nicht beides sein. `ics()` bleibt deshalb
    unveraendert die Fassung fuer den Kalender; diese hier geht per Mail.

    `folge` ist die SEQUENCE: 0 fuer die erste Einladung, bei jeder Aenderung
    derselben Buchung um eins hoeher. Mailprogramme erkennen daran, welche
    Fassung die neuere ist — ohne sie wuerde eine Verschiebung als Dublette
    erscheinen.
    """
    org = _adresse(veranstalter)
    gaeste = [_adresse(e) for e in eingeladene]
    if not gaeste:
        raise ValueError("eine Einladung braucht mindestens einen Eingeladenen")
    roh = ics(uid, beginn, dauer_minuten, summary, ort=ort,
              beschreibung=beschreibung, jetzt=jetzt)
    # Auf der ENTFALTETEN Fassung arbeiten: `ics()` faltet auf 75 Oktette,
    # und eine eingefuegte Zeile muss danach mitgefaltet werden.
    zeilen = roh.replace("\r\n ", "").replace("\r\n\t", "").split("\r\n")
    ergebnis = []
    for zeile in zeilen:
        if zeile == "BEGIN:VEVENT":
            ergebnis.append(zeile)
            ergebnis.append(f"ORGANIZER:mailto:{org}")
            for gast in gaeste:
                ergebnis.append(
                    "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;"
                    f"PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{gast}")
            ergebnis.append(f"SEQUENCE:{int(folge)}")
            continue
        if zeile == "CALSCALE:GREGORIAN":
            ergebnis.append(zeile)
            ergebnis.append("METHOD:REQUEST")
            continue
        ergebnis.append(zeile)
    gefaltet = [teil for z in ergebnis if z for teil in _falte(z)]
    return "\r\n".join(gefaltet) + "\r\n"
```

- [ ] **Schritt 4: Test laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_einladung.py`
Erwartet: alle PASS

Run: `PYTEST tests/test_termin.py`
Erwartet: PASS — die bestehende Fassung ist unverändert.

- [ ] **Schritt 5: Committen**

```bash
git add sales-mcp/kalender.py sales-mcp/tests/test_einladung.py
git commit -m "feat(kalender): Einladungsfassung der Kalenderdatei (METHOD:REQUEST)"
```

---

## Aufgabe 2: Der Mailversand lernt den Kalenderteil

`mail_dispatch.py:390` lehnt Anhänge ausdrücklich ab (`return "anhang_nicht_unterstuetzt"`).
Für Einladungen muss genau eine Ausnahme entstehen: eine Kalenderdatei, und zwar nicht als
beliebiger Anhang, sondern als **Alternativteil** mit `method=REQUEST`. Nur so zeigt ein
Mailprogramm die Schaltflächen zum Annehmen und Ablehnen.

**Dateien:**
- Ändern: `sales-mcp/mail_dispatch.py`
- Ändern: `sales-mcp/tests/test_mail_dispatch.py`

**Schnittstellen:**
- Verbraucht: `mail_dispatch.nachricht_bauen(adresse, betreff, rumpf) -> EmailMessage`
- Erzeugt: `mail_dispatch.nachricht_mit_einladung(adresse, betreff, rumpf, ics_text,
  methode="REQUEST") -> EmailMessage` — Aufgaben 3 und 5 rufen das auf.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

An `tests/test_mail_dispatch.py` anhängen:

```python
def test_einladung_reist_als_kalenderteil():
    """Die Einladung ist ein text/calendar-Teil mit method=REQUEST — nicht
    ein beliebiger Anhang. Nur dann bietet ein Mailprogramm 'Annehmen' an."""
    ics_text = "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nEND:VCALENDAR\r\n"
    nachricht = mail_dispatch.nachricht_mit_einladung(
        "kunde@beispiel.de", "Terminvorschlag", "Passt Ihnen der 1. Oktober?",
        ics_text)
    typen = [t.get_content_type() for t in nachricht.walk()]
    assert "text/calendar" in typen, typen
    kalenderteil = [t for t in nachricht.walk()
                    if t.get_content_type() == "text/calendar"][0]
    assert kalenderteil.get_param("method") == "REQUEST"
    assert kalenderteil.get_param("charset", "").lower() == "utf-8"
    assert "METHOD:REQUEST" in kalenderteil.get_content()


def test_einladung_traegt_auch_lesbaren_text():
    """Ein Mailprogramm ohne Kalenderunterstuetzung muss den Termin trotzdem
    lesen koennen."""
    nachricht = mail_dispatch.nachricht_mit_einladung(
        "kunde@beispiel.de", "Terminvorschlag", "Passt Ihnen der 1. Oktober?",
        "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    texte = [t.get_content() for t in nachricht.walk()
             if t.get_content_type() == "text/plain"]
    assert any("1. Oktober" in t for t in texte), texte


def test_gewoehnliche_anhaenge_bleiben_abgelehnt():
    """Die Ausnahme gilt NUR fuer Kalenderdaten — eine PDF bleibt abgelehnt."""
    assert mail_dispatch._anhang_erlaubt("einladung.ics") is True
    assert mail_dispatch._anhang_erlaubt("angebot.pdf") is False
    assert mail_dispatch._anhang_erlaubt("bild.png") is False
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_mail_dispatch.py -k einladung`
Erwartet: FAIL mit `AttributeError: module 'mail_dispatch' has no attribute
'nachricht_mit_einladung'`

- [ ] **Schritt 3: Den Kalenderteil bauen**

In `mail_dispatch.py`, hinter `nachricht_bauen`:

```python
def _anhang_erlaubt(dateiname: str) -> bool:
    """Nur Kalenderdaten duerfen an eine Mail — sonst nichts.

    Der Mailweg lehnte Anhaenge bisher vollstaendig ab
    (`anhang_nicht_unterstuetzt`). Diese eine Ausnahme entsteht, weil eine
    Einladung ohne Kalenderteil keine Einladung ist, sondern eine Textmail.
    Alles andere bleibt abgelehnt: ein PDF-Anhang waere ein neuer Weg nach
    draussen, und den gibt es hier bewusst nicht.
    """
    return (dateiname or "").lower().endswith(".ics")


def nachricht_mit_einladung(adresse: str, betreff: str, rumpf: str,
                            ics_text: str,
                            methode: str = "REQUEST") -> EmailMessage:
    """Eine Mail, die eine Kalendereinladung traegt.

    Der Kalender reist als ALTERNATIVE zum Text, nicht als Anhang daneben:
    so zeigt ein Mailprogramm die Schaltflaechen zum Annehmen und Ablehnen,
    waehrend ein Programm ohne Kalenderunterstuetzung weiterhin den lesbaren
    Text zeigt. Ein zusaetzlicher Anhang derselben Datei ist bewusst NICHT
    dabei — manche Programme zeigen die Einladung dann doppelt.
    """
    if methode not in ("REQUEST", "REPLY", "CANCEL", "COUNTER"):
        raise ValueError(f"unbekannte Methode: {methode!r}")
    nachricht = nachricht_bauen(adresse, betreff, rumpf)
    nachricht.add_alternative(
        ics_text, subtype="calendar", charset="utf-8",
        params={"method": methode, "component": "VEVENT"})
    return nachricht
```

Ist `params=` in der eingesetzten Python-Fassung an `add_alternative` nicht verfügbar, den
Teil anlegen und den Parameter danach setzen:

```python
    nachricht.add_alternative(ics_text, subtype="calendar", charset="utf-8")
    teil = nachricht.get_payload()[-1]
    teil.set_param("method", methode)
    teil.set_param("component", "VEVENT")
```

- [ ] **Schritt 4: Die Ablehnung für Kalenderdaten öffnen**

Bei `mail_dispatch.py:390` (`return "anhang_nicht_unterstuetzt"`): Die Ablehnung bleibt für
alles außer Kalenderdaten. Nutze `_anhang_erlaubt(...)`; ist die Datei eine `.ics`, wird
ihr Inhalt gelesen und über `nachricht_mit_einladung` mitgeschickt, statt den Versand
abzulehnen.

- [ ] **Schritt 5: Tests laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_mail_dispatch.py`
Erwartet: PASS (auch die bestehenden — der Versand ohne Kalenderteil muss unverändert
funktionieren)

- [ ] **Schritt 6: Committen**

```bash
git add sales-mcp/mail_dispatch.py sales-mcp/tests/test_mail_dispatch.py
git commit -m "feat(mail): Einladungen als Kalenderteil versenden"
```

---

## Aufgabe 3: Das Werkzeug `termin_einladen`

Heute hält `termin_bestaetigen` einen mündlich vereinbarten Termin fest und versendet
nichts. Für eine Einladung braucht es einen eigenen Weg: Termin vorschlagen, Einladung
bauen, **als Entwurf zur Freigabe legen**.

**Dateien:**
- Ändern: `sales-mcp/server.py`
- Neu: `sales-mcp/tests/test_termin_einladen.py`

**Schnittstellen:**
- Verbraucht: `kalender.ics_einladung(...)` (Aufgabe 1), `server.entwurf_erstellen(lead_id,
  kanal, text, betreff, medien_datei)`, `server.termin_bestaetigen(...)`
- Erzeugt: `server.termin_einladen(lead_id, datum, uhrzeit, dauer_minuten=…, thema=…,
  ort="", eingeladene="") -> str` (JSON) — `eingeladene` ist eine kommagetrennte Liste von
  Adressen; ist sie leer, wird die Adresse des Kontakts verwendet.

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
"""Vertragstests fuer `termin_einladen` — Einladung statt stillem Eintrag."""
import json
import os

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.activities, sales_test.drafts, "
                     "sales_test.leads cascade")
    yield


def _lead(name="Ivan", email="ivan@vibemind.space"):
    return str(server._q(
        "insert into leads (name, email, phone, source) values "
        "(%s, %s, '+491701234567', 'whatsapp') returning id",
        (name, email))[0]["id"])


def test_einladung_wird_entwurf_und_geht_nicht_raus():
    """Der Kern: es entsteht ein Entwurf zur Freigabe, kein Versand."""
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    assert "fehler" not in antwort, antwort
    entwuerfe = server._q(
        "select status, channel from drafts where lead_id = %s", (lead,))
    assert len(entwuerfe) == 1, entwuerfe
    assert entwuerfe[0]["status"] == "pending"
    assert entwuerfe[0]["channel"] == "email"


def test_einladung_traegt_die_kalenderdatei():
    lead = _lead()
    antwort = json.loads(server.termin_einladen(
        lead, "2026-10-01", "14:30", thema="Erstgespräch"))
    assert antwort["datei"].endswith(".ics"), antwort
    with open(antwort["pfad"], encoding="utf-8", newline="") as f:
        text = f.read()
    assert "METHOD:REQUEST" in text
    assert "ATTENDEE" in text and "ivan@vibemind.space" in text


def test_ohne_adresse_keine_einladung():
    """Ein Kontakt ohne Mailadresse kann nicht eingeladen werden — und das
    muss gesagt werden, nicht still scheitern."""
    lead = _lead(name="Ohne Mail", email=None)
    antwort = json.loads(server.termin_einladen(lead, "2026-10-01", "14:30"))
    assert "fehler" in antwort
    assert "adresse" in antwort["fehler"].lower()


def test_vergangenes_datum_wird_abgelehnt():
    lead = _lead()
    antwort = json.loads(server.termin_einladen(lead, "2020-01-01", "14:30"))
    assert "fehler" in antwort
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_termin_einladen.py`
Erwartet: FAIL mit `AttributeError: module 'server' has no attribute 'termin_einladen'`

- [ ] **Schritt 3: Die gemeinsame Zeitprüfung herausziehen**

`termin_bestaetigen` prüft Datum und Uhrzeit **inline** (`server.py:1230`–`1243`). Beide
Werkzeuge brauchen dieselbe Regel — sie zweimal zu schreiben heißt, sie zweimal zu pflegen.
Zieh sie heraus:

```python
def _termin_zeitpunkt(datum: str, uhrzeit: str):
    """Datum und Uhrzeit zu einem naiven Ortszeit-Zeitpunkt — oder ein Fehler.

    Liefert `(beginn, tag, zeit, None)` bei Erfolg und `(None, None, None,
    fehlertext)` sonst. Herausgezogen aus `termin_bestaetigen` (11.09.2026),
    damit `termin_einladen` dieselbe Regel benutzt statt einer zweiten:
    zwei Pruefungen driften auseinander, und die Abweichung faellt erst auf,
    wenn ein Termin an einem der beiden Wege durchrutscht.
    """
    try:
        tag = date.fromisoformat((datum or "").strip())
    except ValueError:
        return None, None, None, (f"Ungueltiges Datum '{datum}' — erwartet "
                                  f"ISO-Format YYYY-MM-DD.")
    try:
        zeit = datetime.strptime((uhrzeit or "").strip(), "%H:%M").time()
    except ValueError:
        return None, None, None, (f"Ungueltige Uhrzeit '{uhrzeit}' — erwartet "
                                  f"HH:MM (24-Stunden-Form, z. B. 14:30).")
    if tag < datetime.now(timezone.utc).date():
        return None, None, None, (f"Der Termin {tag.isoformat()} liegt in der "
                                  f"Vergangenheit — es wurde nichts angelegt.")
    return datetime.combine(tag, zeit), tag, zeit, None
```

`termin_bestaetigen` ruft ihn ab jetzt auf, statt selbst zu prüfen. Die Fehlertexte bleiben
wortgleich, damit die bestehenden Tests unverändert gelten.

- [ ] **Schritt 4: `termin_einladen` schreiben**

Direkt hinter `termin_bestaetigen`:

```python
def termin_einladen(lead_id: str, datum: str, uhrzeit: str,
                    dauer_minuten: int = TERMIN_DAUER_VORGABE,
                    thema: str = "Erstgespraech", ort: str = "",
                    eingeladene: str = "") -> str:
    """Einen Termin als EINLADUNG vorschlagen — der Empfaenger entscheidet.

    Anders als `termin_bestaetigen` haelt das hier keinen vereinbarten Termin
    fest, sondern schlaegt einen vor: Es entsteht eine Einladung, die als
    Entwurf zur Freigabe liegt. Der Kalendereintrag entsteht ERST, wenn
    zugesagt wurde — ein Termin im eigenen Kalender, dem niemand zugestimmt
    hat, waere eine Belegung auf Verdacht.

    `eingeladene` ist eine kommagetrennte Liste von Adressen; leer bedeutet
    die Adresse des Kontakts. Versendet wird NICHTS: der Entwurf bleibt
    'pending', bis der Betreiber ihn freigibt.
    """
    leads = _q("select id, name, email from leads where id = %s", (lead_id,))
    if not leads:
        return _json({"fehler": f"Kein Kontakt mit lead_id {lead_id}."})
    name, kontakt_mail = leads[0]["name"], (leads[0]["email"] or "").strip()

    beginn, tag, zeit, fehler = _termin_zeitpunkt(datum, uhrzeit)
    if fehler:
        return _json({"fehler": fehler})

    gaeste = [t.strip() for t in (eingeladene or "").split(",") if t.strip()]
    if not gaeste:
        if not kontakt_mail:
            return _json({"fehler": (
                f"{name} hat keine E-Mail-Adresse — ohne Adresse kann keine "
                f"Einladung verschickt werden. Entweder die Adresse am "
                f"Kontakt nachtragen oder `eingeladene` angeben.")})
        gaeste = [kontakt_mail]

    absender = (mail_dispatch.SMTP_VON or mail_dispatch.SMTP_USER or "").strip()
    if not absender:
        return _json({"fehler": (
            "Kein Absender konfiguriert (SMTP_VON/SMTP_USER) — eine Einladung "
            "braucht einen Veranstalter.")})

    dauer = _termin_dauer(dauer_minuten)
    thema_kurz = (thema or "").strip()[:TERMIN_TEXT_MAXLAENGE] or "Termin"
    ort_kurz = (ort or "").strip()[:TERMIN_TEXT_MAXLAENGE]
    uid = f"{uuid.uuid4()}@sales-claw"
    try:
        ics_text = kalender.ics_einladung(
            uid, beginn, dauer, f"{thema_kurz} — {name}",
            veranstalter=absender, eingeladene=gaeste, ort=ort_kurz)
    except ValueError as ex:
        return _json({"fehler": f"Einladung nicht baubar: {ex}"})

    dateiname = (f"einladung-{recherche.slug(name)}-{tag.isoformat()}"
                 f"-{zeit:%H%M}.ics")
    try:
        os.makedirs(medien.ERZEUGT_VERZEICHNIS, exist_ok=True)
        with open(os.path.join(medien.ERZEUGT_VERZEICHNIS, dateiname), "w",
                  encoding="utf-8", newline="\r\n") as datei:
            datei.write(ics_text)
    except OSError as ex:
        return _json({"fehler": (
            f"Die Einladung konnte nicht abgelegt werden ({type(ex).__name__}"
            f": {ex}) — ohne Datei im Medienordner ist sie nicht versendbar.")})
    pfad, _ueberschrieben = recherche.report_schreiben(dateiname, ics_text)

    text = (f"Hallo {name},\n\n"
            f"ich schlage {tag.strftime('%d.%m.%Y')} um {zeit:%H:%M} Uhr vor "
            f"({dauer} Minuten){', ' + ort_kurz if ort_kurz else ''}.\n"
            f"Die Einladung haengt an — Sie koennen direkt zusagen oder "
            f"absagen.\n\nViele Gruesse")
    roh = entwurf_erstellen(lead_id, "email", text,
                            betreff=f"Terminvorschlag: {thema_kurz}",
                            medien_datei=dateiname)
    entwurf = json.loads(roh)
    if "fehler" in entwurf:
        return roh

    _q("insert into activities (lead_id, type, payload) values "
       "(%s, 'einladung_gesendet', %s::jsonb)",
       (lead_id, json.dumps({"uid": uid, "datum": tag.isoformat(),
                             "uhrzeit": f"{zeit:%H:%M}", "folge": 0,
                             "eingeladene": gaeste, "thema": thema_kurz})))
    return _json({**entwurf, "uid": uid, "datei": dateiname, "pfad": pfad,
                  "hinweis": ("Die Einladung liegt zur Freigabe. Es ging "
                              "nichts raus, und im Kalender steht noch "
                              "nichts — das passiert erst bei der Zusage.")})
```

Heißt die Absenderkonstante in `mail_dispatch` anders, den dortigen Namen verwenden — die
Adresse **nicht** neu erfinden und nicht aus dem Kontakt ableiten.

- [ ] **Schritt 5: Tests laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_termin_einladen.py`
Erwartet: alle PASS

Run: `PYTEST tests/test_termin.py`
Erwartet: PASS — die herausgezogene Zeitprüfung darf `termin_bestaetigen` nicht verändern.

Run: `PYTEST tests/`
Erwartet: mindestens 1565 PASS

- [ ] **Schritt 6: Committen**

```bash
git add sales-mcp/server.py sales-mcp/tests/test_termin_einladen.py
git commit -m "feat(server): termin_einladen legt eine Einladung zur Freigabe vor"
```

---

## Aufgabe 4: Antworten auf Einladungen verstehen

Sagt jemand zu oder ab, kommt eine Mail mit `METHOD:REPLY` zurück. Darin steht je
Teilnehmer der Status und optional ein Kommentar — **das ist der Ablehnungsgrund.**

**Dateien:**
- Ändern: `sales-mcp/kalender.py`
- Ändern: `sales-mcp/postfach.py`
- Ändern: `sales-mcp/tests/test_einladung.py`

**Schnittstellen:**
- Erzeugt: `kalender.ics_antwort_lesen(text) -> dict | None` — liefert
  `{"uid": str, "methode": str, "teilnehmer": str, "status": str, "grund": str,
  "folge": int, "neuer_beginn": datetime | None}` oder `None`, wenn der Text keine
  Kalenderantwort ist. `status` ist einer von `ACCEPTED`, `DECLINED`, `TENTATIVE`.
  `neuer_beginn` ist nur bei `COUNTER` gesetzt (Aufgabe 5).

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

An `tests/test_einladung.py` anhängen:

```python
ANTWORT_ZUSAGE = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
    "UID:abc-123\r\nSEQUENCE:0\r\n"
    "ATTENDEE;PARTSTAT=ACCEPTED:mailto:ivan@vibemind.space\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n")

ANTWORT_ABSAGE = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REPLY\r\nBEGIN:VEVENT\r\n"
    "UID:abc-123\r\nSEQUENCE:0\r\n"
    "ATTENDEE;PARTSTAT=DECLINED:mailto:ivan@vibemind.space\r\n"
    "COMMENT:Bin an dem Tag beim Kunden in München\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n")


def test_zusage_wird_gelesen():
    ergebnis = kalender.ics_antwort_lesen(ANTWORT_ZUSAGE)
    assert ergebnis["uid"] == "abc-123"
    assert ergebnis["methode"] == "REPLY"
    assert ergebnis["status"] == "ACCEPTED"
    assert ergebnis["teilnehmer"] == "ivan@vibemind.space"
    assert ergebnis["grund"] == ""


def test_absage_traegt_den_grund():
    ergebnis = kalender.ics_antwort_lesen(ANTWORT_ABSAGE)
    assert ergebnis["status"] == "DECLINED"
    assert "beim Kunden in München" in ergebnis["grund"]


def test_kein_kalendertext_gibt_nichts():
    assert kalender.ics_antwort_lesen("Guten Tag, passt mir leider nicht.") is None
    assert kalender.ics_antwort_lesen("") is None


def test_einladung_ist_keine_antwort():
    """Eine REQUEST-Datei darf nicht als Antwort durchgehen."""
    text = kalender.ics_einladung(
        "abc-123", datetime(2026, 10, 1, 14, 30), 30, "Erstgespräch",
        veranstalter="felix@vibemind.space",
        eingeladene=["ivan@vibemind.space"])
    assert kalender.ics_antwort_lesen(text) is None
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_einladung.py -k antwort`
Erwartet: FAIL mit `AttributeError: module 'kalender' has no attribute
'ics_antwort_lesen'`

- [ ] **Schritt 3: Den Leser schreiben**

In `kalender.py`, hinter `ics_einladung`:

```python
def ics_antwort_lesen(text: str):
    """Eine Antwort auf eine Einladung lesen — oder None.

    Liefert nur bei METHOD:REPLY und METHOD:COUNTER ein Ergebnis; eine
    REQUEST-Datei ist KEINE Antwort und darf nicht als eine durchgehen
    (sonst haette eine weitergeleitete Einladung als Zusage gegolten).

    Gelesen wird auf der ENTFALTETEN Fassung: ein Grund laenger als 75
    Oktette steht sonst ueber mehrere Zeilen und wuerde abgeschnitten.
    Werte laufen durch `_entmaskiere`, sonst steht im Grund ein `\\,` statt
    eines Kommas — derselbe Fehler, der im Lesepfad schon einmal steckte.
    """
    roh = (text or "")
    if "BEGIN:VCALENDAR" not in roh:
        return None
    zeilen = roh.replace("\r\n ", "").replace("\r\n\t", "").replace(
        "\n ", "").replace("\n\t", "").replace("\r\n", "\n").split("\n")
    ergebnis = {"uid": "", "methode": "", "teilnehmer": "", "status": "",
                "grund": "", "folge": 0, "neuer_beginn": None}
    dtstart_wert, dtstart_tzid = "", ""
    for zeile in zeilen:
        name, _, wert = zeile.partition(":")
        feld = name.split(";")[0].upper()
        if feld == "METHOD":
            ergebnis["methode"] = wert.strip().upper()
        elif feld == "UID" and not ergebnis["uid"]:
            ergebnis["uid"] = _entmaskiere(wert.strip())
        elif feld == "SEQUENCE":
            try:
                ergebnis["folge"] = int(wert.strip())
            except ValueError:
                pass
        elif feld == "COMMENT" and not ergebnis["grund"]:
            ergebnis["grund"] = _entmaskiere(wert.strip())
        elif feld == "DTSTART" and not dtstart_wert:
            dtstart_wert, dtstart_tzid = wert.strip(), _tzid_aus(name)
        elif feld == "ATTENDEE" and not ergebnis["status"]:
            for teil in name.split(";")[1:]:
                schluessel, _, inhalt = teil.partition("=")
                if schluessel.upper() == "PARTSTAT":
                    ergebnis["status"] = inhalt.strip().upper()
            adresse = wert.strip()
            if adresse.lower().startswith("mailto:"):
                adresse = adresse[7:]
            ergebnis["teilnehmer"] = _entmaskiere(adresse)
    if ergebnis["methode"] not in ("REPLY", "COUNTER"):
        return None
    if ergebnis["methode"] == "COUNTER" and dtstart_wert:
        ergebnis["neuer_beginn"] = _ics_zeit(dtstart_wert, dtstart_tzid)
    return ergebnis


def _tzid_aus(feldname: str) -> str:
    """Den TZID-Parameter aus einem Feldnamen wie `DTSTART;TZID=Europe/Berlin`."""
    for teil in feldname.split(";")[1:]:
        schluessel, _, wert = teil.partition("=")
        if schluessel.upper() == "TZID":
            return wert.strip()
    return ""
```

`_ics_zeit` und `_entmaskiere` existieren bereits (aus der Oberflächen-Stufe 1). Heißt
`_ics_tzid` dort schon so wie `_tzid_aus` hier, **den vorhandenen verwenden** statt einen
zweiten zu schreiben — zwei Funktionen für dieselbe Aufgabe driften auseinander.

- [ ] **Schritt 4: Das Postfach die Antworten erkennen lassen**

In `postfach.py`: Beim Lesen einer Nachricht wird ein `text/calendar`-Teil erkannt und über
`kalender.ics_antwort_lesen` ausgewertet. Das Postfach bleibt **nur lesend** — es
beantwortet nichts. Das Ergebnis wird als Aktivität am Kontakt festgehalten, damit die
Oberfläche (Aufgabe 6) es zeigen kann.

- [ ] **Schritt 5: Tests laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_einladung.py tests/test_postfach.py`
Erwartet: PASS

- [ ] **Schritt 6: Committen**

```bash
git add sales-mcp/kalender.py sales-mcp/postfach.py sales-mcp/tests/test_einladung.py
git commit -m "feat(postfach): Zusagen und Absagen auf Einladungen verstehen"
```

---

## Aufgabe 5: Gegenvorschläge

Schlägt der Empfänger eine andere Zeit vor, kommt `METHOD:COUNTER` mit dem neuen Zeitpunkt.
**Der Bot nimmt ihn nicht an** — er legt ihn dem Betreiber vor.

**Dateien:**
- Ändern: `sales-mcp/kalender.py`
- Ändern: `sales-mcp/server.py`
- Ändern: `sales-mcp/tests/test_einladung.py`

**Schnittstellen:**
- Verbraucht: `kalender.ics_antwort_lesen` (Aufgabe 4), `server.termin_einladen`
  (Aufgabe 3)
- Erzeugt: Feld `neuer_beginn` im Ergebnis von `ics_antwort_lesen`

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
GEGENVORSCHLAG = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:COUNTER\r\nBEGIN:VEVENT\r\n"
    "UID:abc-123\r\nSEQUENCE:0\r\n"
    "DTSTART;TZID=Europe/Berlin:20261002T160000\r\n"
    "ATTENDEE;PARTSTAT=DECLINED:mailto:ivan@vibemind.space\r\n"
    "COMMENT:Donnerstag passt besser\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n")


def test_gegenvorschlag_nennt_die_neue_zeit():
    ergebnis = kalender.ics_antwort_lesen(GEGENVORSCHLAG)
    assert ergebnis["methode"] == "COUNTER"
    assert ergebnis["neuer_beginn"] == datetime(2026, 10, 2, 16, 0)
    assert "Donnerstag passt besser" in ergebnis["grund"]


def test_antwort_ohne_gegenvorschlag_hat_keine_neue_zeit():
    assert kalender.ics_antwort_lesen(ANTWORT_ABSAGE)["neuer_beginn"] is None
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_einladung.py -k gegenvorschlag`
Erwartet: FAIL — `neuer_beginn` fehlt oder ist `None`

- [ ] **Schritt 3: `DTSTART` aus der Antwort lesen**

`ics_antwort_lesen` um `neuer_beginn` erweitern: bei `METHOD:COUNTER` das `DTSTART` über
die vorhandenen `_ics_zeit`/`_ics_tzid` auswerten — **nicht** neu parsen. Bei jeder anderen
Methode bleibt das Feld `None`.

- [ ] **Schritt 4: Den Gegenvorschlag vorlegen**

Im Verarbeitungsweg aus Aufgabe 4: Bei `COUNTER` entsteht eine Wiedervorlage bzw. ein
Eintrag, der dem Betreiber die neue Zeit zeigt. Nimmt er an, ruft er `termin_einladen` mit
der neuen Zeit auf — dieselbe Kennung, `folge` um eins erhöht. **Automatisch passiert
nichts.**

- [ ] **Schritt 5: Tests laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_einladung.py tests/`
Erwartet: PASS

- [ ] **Schritt 6: Committen**

```bash
git add sales-mcp/kalender.py sales-mcp/server.py sales-mcp/tests/test_einladung.py
git commit -m "feat(termin): Gegenvorschlaege lesen und dem Betreiber vorlegen"
```

---

## Aufgabe 6: Der Einladungsstand in der Oberfläche

Der Betreiber muss sehen, was aus seinen Einladungen geworden ist: wer zugesagt hat, wer
abgesagt hat und warum, wo ein Gegenvorschlag wartet.

**Dateien:**
- Ändern: `sales-mcp/ui.py`
- Ändern: `sales-mcp/tests/test_darstellung.py`

**Schnittstellen:**
- Verbraucht: die Aktivitäten aus Aufgabe 4 und 5

- [ ] **Schritt 1: Fehlschlagenden Test schreiben**

```python
def test_einladungsstand_erscheint_am_kontakt():
    lead = _lead("Ivan")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_antwort', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-123", "status": "DECLINED",
                           "grund": "Bin beim Kunden in München",
                           "teilnehmer": "ivan@vibemind.space"})))
    seite = _get(f"/kontakte/{lead}").text
    assert "abgesagt" in seite.lower()
    assert "Bin beim Kunden in München" in seite


def test_zusage_erscheint_als_zugesagt():
    lead = _lead("Ivan")
    server._q(
        "insert into activities (lead_id, type, payload) values "
        "(%s, 'einladung_antwort', %s::jsonb)",
        (lead, json.dumps({"uid": "abc-123", "status": "ACCEPTED",
                           "grund": "", "teilnehmer": "ivan@vibemind.space"})))
    seite = _get(f"/kontakte/{lead}").text
    assert "zugesagt" in seite.lower()
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `PYTEST tests/test_darstellung.py -k einladung`
Erwartet: FAIL — die Seite zeigt den Stand nicht

- [ ] **Schritt 3: Den Stand anzeigen**

Im Kontakt-Verlauf: Die Statuswerte kommen aus der Kalenderantwort und bleiben in der
Datenbank, wie sie sind (`ACCEPTED`, `DECLINED`, `TENTATIVE`). Für die Anzeige werden sie
übersetzt — nach dem bestehenden Muster von `ZUSTAND_TEXT`:

```python
EINLADUNG_TEXT = {
    "ACCEPTED": "zugesagt",
    "DECLINED": "abgesagt",
    "TENTATIVE": "unter Vorbehalt",
    "NEEDS-ACTION": "wartet auf Antwort",
}
```

Der Grund wird über `_kurz(...)` gekürzt, der volle Text steht im `title` und läuft durch
`_e()`. Neue Anzeigetexte tragen echte Umlaute.

- [ ] **Schritt 4: Tests laufen lassen, grün bestätigen**

Run: `PYTEST tests/test_darstellung.py`
Erwartet: PASS — einschließlich des Umlaut-Wächters

Run: `PYTEST tests/`
Erwartet: mindestens 1565 PASS

- [ ] **Schritt 5: Committen**

```bash
git add sales-mcp/ui.py sales-mcp/tests/test_darstellung.py
git commit -m "feat(ui): Einladungsstand am Kontakt zeigen"
```

---

## Abschluss

- [ ] **Gesamtsuite grün**

Run: `PYTEST tests/`
Erwartet: PASS, Zahl **über** 1565.

- [ ] **Durchgang am laufenden System** (nach dem Deployment)

| Prüfung | Erwartung |
|---|---|
| Einladung an das eigene Zweitkonto | erscheint als annehmbare Einladung, nicht als Textmail mit Anhang |
| Annehmen | Zusage erscheint am Kontakt als „zugesagt" |
| Ablehnen mit Grund | Grund erscheint lesbar am Kontakt |
| Gegenvorschlag | wird vorgelegt, **nichts** passiert automatisch |
| Einladung an einen fremden Anbieter (Gmail o. ä.) | verhält sich wie eine gewöhnliche Kalendereinladung |
| Kalendereintrag im eigenen Kalender | unverändert wie vorher — die CalDAV-Fassung ist nicht angefasst |
