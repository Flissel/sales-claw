"""Schranken fuer Kundentext (Spec §7, §10.8): einziger Endpunkt und keine fremden KI-Importe."""
import ast
import io
import json
import os
import pathlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import auswertung  # noqa: E402
import briefing  # noqa: E402
import mail_dispatch  # noqa: E402
import ollama  # noqa: E402
import server  # noqa: E402
import teilnehmer  # noqa: E402
import termin_akte  # noqa: E402

JETZT = datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc)
UID = "sc-ki-1"
OLLAMA_HOST = "ollama.test.invalid:11434"
VERBOTEN = {"gateway", "openai", "anthropic", "requests", "httpx"}


@pytest.fixture(autouse=True)
def leer(monkeypatch):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.termin_akten, sales_test.activities, "
                     "sales_test.drafts, sales_test.leads cascade")
        conn.execute("truncate compliance_test.sperrliste")
    monkeypatch.setenv("POST_BESITZER", "felix")
    monkeypatch.setenv("TERMIN_TEAM_ADRESSEN", "")
    monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "")
    monkeypatch.setattr(mail_dispatch, "SMTP_USER", "")
    monkeypatch.setattr(teilnehmer.postfach, "IMAP_USER", "")
    yield


class _Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_einziger_endpunkt(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", f"http://{OLLAMA_HOST}")
    urls = []

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        urls.append(url)
        if url.endswith("/api/tags"):
            return _Antwort(b'{"models": []}')
        inhalt = json.dumps({"kurzfassung": "k", "painpoints": [], "ziele": ["z"]})
        return _Antwort(json.dumps({"message": {"role": "assistant",
                                                "content": inhalt}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    lead = str(server._q(
        "insert into leads (name, email, company, source) "
        "values ('Karla Kunde', 'kunde@firma.de', 'Firma GmbH', 'Messe') returning id")[0]["id"])
    payload = {"datum": "2099-01-10", "uhrzeit": "10:00", "thema": "Beratung", "uid": UID,
               "ort": "https://meet.google.com/abc-defg-hij"}
    server._q("insert into activities (lead_id, type, payload) values (%s, 'termin', %s::jsonb) "
              "returning id", (lead, json.dumps(payload)))
    termin_akte.abgleichen(JETZT)

    assert briefing.erstellen(UID)["mit_ki"] is True
    a = auswertung.auswerten([{"sprecher": "A", "beginn": "2026-11-12T09:00:00Z",
                               "text": "Hallo zusammen", "sprache": "de"}])
    assert a["kurzfassung"] == "k"
    assert urls
    assert {urlparse(u).netloc for u in urls} == {OLLAMA_HOST}


@pytest.mark.parametrize("modul", [briefing, auswertung, ollama])
def test_keine_fremden_ki_importe(modul):
    baum = ast.parse(pathlib.Path(modul.__file__).read_text(encoding="utf-8"))
    gefunden = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            gefunden |= {a.name.split(".")[0] for a in knoten.names}
        elif isinstance(knoten, ast.ImportFrom) and knoten.module:
            gefunden.add(knoten.module.split(".")[0])
    assert not (gefunden & VERBOTEN)
