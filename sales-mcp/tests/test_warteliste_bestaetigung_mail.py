"""Bestaetigungsmails der Warteliste gegen den echten Laden: die fertige Mail
(mail_dispatch) und die Verbotsliste (Schema compliance_test).

Lesen, Wortlaut und Versandlauf ohne Datenbank: test_warteliste_bestaetigung.py."""
import io
import json
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import pytest  # noqa: E402

import mail_dispatch  # noqa: E402
import server  # noqa: E402
import sperrliste  # noqa: E402
import warteliste_bestaetigung as wb  # noqa: E402

TOKEN = "c3" * 32
TOKEN2 = "d4" * 32


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"
    assert sperrliste.SCHEMA == "compliance_test"


@pytest.fixture(autouse=True)
def laden(monkeypatch):
    """Nie der echte Mailserver: Zugangsdaten aus dem Test, und `senden` faengt
    die fertige Nachricht ab, statt eine Verbindung zu oeffnen."""
    monkeypatch.setattr(mail_dispatch, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(mail_dispatch, "SMTP_PORT", 2525)
    monkeypatch.setattr(mail_dispatch, "SMTP_USER", "stub-user@example.org")
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "STUB-GEHEIMNIS")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "haus@example.org")
    monkeypatch.setattr(mail_dispatch, "SENDE_PAUSE_S", 0.0)
    post = []
    monkeypatch.setattr(mail_dispatch, "senden",
                        lambda nachricht, identitaet=None: post.append((nachricht, identitaet)))
    with server.pool.connection() as conn:
        conn.execute("delete from compliance_test.sperrliste where kennung like 'email:wb-%%'")
    yield post
    with server.pool.connection() as conn:
        conn.execute("delete from compliance_test.sperrliste where kennung like 'email:wb-%%'")


def _dok(*zeilen):
    return {"count": len(zeilen), "rows": [{"email": a, "token": t} for a, t in zeilen]}


def _lauf(dokument):
    aus, err = io.StringIO(), io.StringIO()
    code = wb.main(["senden"], eingabe=io.StringIO(json.dumps(dokument)), ausgabe=aus,
                   fehlerausgabe=err)
    return code, aus.getvalue(), err.getvalue()


def test_die_fertige_mail(laden):
    code, aus, err = _lauf(_dok(("wb-anna@example.org", TOKEN)))
    assert code == 0 and aus == "[]\n"
    assert json.loads(err) == {"gesendet": 1, "gesperrt": 0, "fehler": 0, "unbrauchbar": 0}
    assert len(laden) == 1
    nachricht, identitaet = laden[0]
    assert identitaet.art == "kunde" and identitaet.absender == "haus@example.org"
    assert nachricht["From"] == "haus@example.org"
    assert nachricht["To"] == "wb-anna@example.org"
    assert nachricht["Cc"] is None and nachricht["Bcc"] is None
    assert nachricht["Subject"] == wb.BETREFF
    assert nachricht["Auto-Submitted"] == "auto-generated"
    link = f"https://vibemind.space/waitlist/confirm#{TOKEN}"
    text = nachricht.get_body(preferencelist=("plain",)).get_content()
    html = nachricht.get_body(preferencelist=("html",)).get_content()
    assert link in text
    assert f'<a href="{link}">' in html


def test_wer_auf_der_verbotsliste_steht_bekommt_keine_mail(laden):
    sperrliste.sperren(server._q, email="wb-gesperrt@example.org", quelle="test", grund="Probe")
    code, aus, err = _lauf(_dok(("wb-gesperrt@example.org", TOKEN), ("wb-frei@example.org", TOKEN2)))
    assert code == 0 and aus == "[]\n"          # gesperrt wird nicht wiederholt
    assert json.loads(err) == {"gesendet": 1, "gesperrt": 1, "fehler": 0, "unbrauchbar": 0}
    assert [n["To"] for n, _ in laden] == ["wb-frei@example.org"]


def test_kein_kontakt_und_keine_buchung(laden):
    """Eine unbestaetigte Adresse ist noch niemand: der Versand legt nichts an."""
    vorher = server._q("select (select count(*) from leads) as leads, "
                       "(select count(*) from activities) as activities, "
                       "(select count(*) from drafts) as drafts")
    _lauf(_dok(("wb-neu@example.org", TOKEN)))
    nachher = server._q("select (select count(*) from leads) as leads, "
                        "(select count(*) from activities) as activities, "
                        "(select count(*) from drafts) as drafts")
    assert len(laden) == 1 and nachher == vorher


def test_ohne_brauchbares_postfach_geht_alles_zurueck(laden, monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "")
    code, aus, err = _lauf(_dok(("wb-anna@example.org", TOKEN)))
    assert code == 3 and json.loads(aus) == ["wb-anna@example.org"]
    assert laden == [] and "wb-anna@example.org" not in err


def test_versandfehler_gehen_zurueck(laden, monkeypatch):
    def scheitert(nachricht, identitaet=None):
        raise mail_dispatch.VersandFehler(f"Mailserver weist den Empfaenger zurueck: {nachricht['To']}")
    monkeypatch.setattr(mail_dispatch, "senden", scheitert)
    code, aus, err = _lauf(_dok(("wb-anna@example.org", TOKEN)))
    assert code == 3 and aus == '["wb-anna@example.org"]\n'
    assert "wb-anna@example.org" not in err and TOKEN not in err
