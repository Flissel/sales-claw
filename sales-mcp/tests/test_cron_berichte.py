"""Drift-Test: announce-Cron-Jobs kennzeichnen ihre Berichte mit „Bericht:“."""
import json
from pathlib import Path

CRON = Path(__file__).resolve().parents[2] / "deploy" / "cron"
ZEILE = "Beginne deine Nachricht mit „Bericht:“ (genau so, dann ein Leerzeichen)."
JOBS = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(CRON.glob("*.json"))}
ANNOUNCE = {n: j for n, j in JOBS.items() if j.get("delivery", {}).get("mode") == "announce"}


def test_es_gibt_announce_jobs():
    assert set(ANNOUNCE) == {
        "abend-nachbereitung.json", "firmenkontakte-anreichern.json",
        "kalenderantworten-schnellcheck.json", "morgen-digest.json", "postfach-check.json",
    }


def test_announce_auftragstext_beginnt_mit_berichtszeile():
    for name, job in ANNOUNCE.items():
        assert job["payload"]["message"].startswith(ZEILE + "\n\n"), name


def test_no_reply_bleibt_ohne_praefix():
    for name, job in ANNOUNCE.items():
        msg = job["payload"]["message"]
        if "NO_REPLY" in msg:
            assert "NO_REPLY" in msg.split(ZEILE, 1)[1], name
            assert "„Bericht:“ NO_REPLY" not in msg and "Bericht: NO_REPLY" not in msg, name


def test_uebrige_felder_unveraendert():
    for name, job in ANNOUNCE.items():
        assert job["sessionTarget"] == "isolated", name
        assert job["delivery"]["channel"] == "whatsapp", name
        assert job["delivery"]["to"] == "${MELDE_AN}", name
        assert job["payload"]["kind"] == "agentTurn", name
        assert {"schedule", "enabled", "name", "agentId"} <= set(job), name
