"""Vertragstests fuer den Wochenbericht (KPI) gegen sales_test.

Der Wochenbericht ist die Steuerungszahl-Sicht auf die letzten 7 Tage: was kam
rein, was ging raus, was blieb liegen. Er liest ausschliesslich — kein Versand,
kein neuer Egress-Pfad, keine Statusaenderung. Getestet wird deshalb vor allem
die ABGRENZUNG (7-Tage-Fenster) und die Zusammenfuehrung der Quellen
(leads, activities, drafts, vertraege_ablaufend).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


@pytest.fixture(autouse=True)
def leer():
    with server.pool.connection() as conn:
        conn.execute(
            "truncate sales_test.activities, sales_test.drafts, "
            "sales_test.personas, sales_test.leads cascade")


def _heute():
    """UTC, nicht date.today() — und das ist hier keine Kosmetik.

    Der Container laeuft mit TZ=Europe/Berlin, die Werkzeugschicht rechnet
    durchgehend in UTC (`datetime.now(timezone.utc).date()`, so schon in
    wiedervorlage_setzen). Zwischen 00:00 und 02:00 Berliner Zeit laufen beide
    Datumsbegriffe einen Tag auseinander — ein Test mit date.today() ist in
    genau diesem Fenster rot, sonst gruen. Gleiches Muster wie `_heute()` in
    test_vertraege.py und test_werkzeuge.py.
    """
    return datetime.now(timezone.utc).date()


def _lead():
    return server._q(
        "insert into leads (name, phone, source) values "
        "('Max Bestand', '+491701234567', 'whatsapp') returning id")[0]["id"]


def test_wochenbericht_zaehlt_die_letzten_sieben_tage():
    lead = _lead()
    server.aktivitaet_loggen(lead_id=str(lead), typ="bedarf",
                             inhalt="einkommen beantwortet")
    server._q("insert into drafts (lead_id, channel, recipient, body, status, "
              "sent_at) values (%s,'whatsapp','+491701234567','x','sent', now())",
              (lead,))
    b = json.loads(server.wochenbericht())
    assert b["neue_leads"] == {"whatsapp": 1}
    assert b["bedarf"]["antworten"] == 1
    assert b["bedarf"]["kontakte"] == 1
    assert b["versand"] == {"whatsapp": 1}
    assert b["zeitraum"] == "letzte 7 Tage"
    assert "Wochenbericht" in b["text"]


def test_alte_ereignisse_zaehlen_nicht():
    """Die Fenstergrenze ist der ganze Zweck — was aelter als 7 Tage ist,
    gehoert in keine Wochenzahl, sonst waechst jede Zeile monoton."""
    lead = _lead()
    server._q("insert into activities (lead_id, type, payload, created_at) "
              "values (%s, 'bedarf', '{}', now() - interval '8 days')", (lead,))
    server._q("insert into drafts (lead_id, channel, recipient, body, status, "
              "sent_at) values (%s,'whatsapp','+491701234567','x','sent', "
              "now() - interval '8 days')", (lead,))
    server._q("insert into leads (name, source, created_at) values "
              "('Alt Kontakt', 'whatsapp', now() - interval '8 days')")
    b = json.loads(server.wochenbericht())
    assert b["bedarf"]["antworten"] == 0
    assert b["versand"] == {}
    assert b["neue_leads"] == {"whatsapp": 1}   # nur der frische Kontakt


def test_wiedervorlagen_saldo_und_recherche_kosten():
    lead = _lead()
    server.wiedervorlage_setzen(lead_id=str(lead),
                                faellig_am=_heute().isoformat(), notiz="x")
    server._q("insert into activities (lead_id, type, payload) values "
              "(%s, 'recherche', %s)",
              (lead, json.dumps({"kosten_usd": 0.0402})))
    b = json.loads(server.wochenbericht())
    assert b["wiedervorlagen"] == {"neu": 1, "erledigt": 0}
    assert b["recherche_kosten_usd"] == 0.04


def test_ablaufende_vertraege_und_offene_entwuerfe():
    """Zwei Zahlen mit anderem Zeitbegriff als der Rest: `entwuerfe_offen_jetzt`
    ist ein Bestand (JETZT offen, egal wie alt), `vertraege_ablaufend_30`
    schaut nach VORNE. Beide duerfen nicht ins 7-Tage-Fenster geraten."""
    lead = _lead()
    server.vertrag_speichern(lead_id=str(lead), sparte="BU",
                             ablauf=(_heute() + timedelta(days=20)).isoformat())
    server.vertrag_speichern(lead_id=str(lead), sparte="KFZ",
                             ablauf=(_heute() + timedelta(days=200)).isoformat())
    server._q("insert into drafts (lead_id, channel, recipient, body, status, "
              "created_at) values (%s,'whatsapp','+491701234567','x','pending', "
              "now() - interval '30 days')", (lead,))
    b = json.loads(server.wochenbericht())
    assert b["vertraege_ablaufend_30"] == 1
    assert b["entwuerfe_offen_jetzt"] == 1


def test_leerer_bericht_bleibt_lesbar():
    """Der haeufigste Lauf am Anfang: eine leere Woche. Er darf weder werfen
    noch eine leere Zeile liefern — der Betreiber bekommt den Text per Cron."""
    b = json.loads(server.wochenbericht())
    assert b["neue_leads"] == {} and b["versand"] == {}
    assert b["bedarf"] == {"antworten": 0, "kontakte": 0}
    assert b["wiedervorlagen"] == {"neu": 0, "erledigt": 0}
    assert b["recherche_kosten_usd"] == 0.0
    assert b["entwuerfe_offen_jetzt"] == 0
    assert b["vertraege_ablaufend_30"] == 0
    assert "Neue Kontakte: 0" in b["text"]
    assert "nichts" in b["text"]


def test_signatur_ueberlebt_den_dekorator_und_werkzeug_ist_registriert():
    import inspect
    assert list(inspect.signature(server.wochenbericht).parameters) == []
    assert server.wochenbericht in server.WERKZEUGE
