"""Die Suite erreicht nie den echten Kalender des Betreibers (06.11.2026).

Vorfall: Das Runbook startet die Suite mit `--env-file .env`. Damit standen
die echten CALDAV_*-Zugangsdaten im Testcontainer, und
`test_kalender_sicht.py` legte bei jedem Lauf ueber `termine_eigen.anlegen`
einen Termin "Steuer" (dazu "Fehlt im Handy", "Unbekannt") in Felix'
echten Kalender - 275 Stueck, sichtbar auf dem Handy. Die autouse-Fixture
`_kein_echter_kalender` in conftest.py nimmt die Zugangsdaten fuer jeden
Test heraus; diese Tests halten das fest.

Aussagekraeftig sind sie nur mit gesetzten Zugangsdaten, also im Container
mit der echten .env - genau dort entstand der Schaden. Die Meldungen nennen
nur Variablennamen, nie Werte: ein roter Lauf darf kein Passwort ausgeben.
"""
import kalender
import konferenz


def _gesetzt(namen, werte):
    return [name for name, wert in zip(namen, werte) if wert]


def test_suite_sieht_keine_echten_kalender_zugangsdaten():
    namen = ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASSWORT")
    assert _gesetzt(namen, kalender.konfiguration()) == []


def test_eintragen_im_test_erreicht_keinen_echten_kalender():
    zustand, _grund = kalender.eintragen("testsperre", "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    assert zustand == kalender.NICHT_KONFIGURIERT


def test_suite_sieht_keine_echten_google_meet_zugangsdaten():
    namen = ("GOOGLE_MEET_CLIENT_ID", "GOOGLE_MEET_CLIENT_SECRET",
             "GOOGLE_MEET_REFRESH_TOKEN")
    assert _gesetzt(namen, konferenz.konfiguration()[1:]) == []
