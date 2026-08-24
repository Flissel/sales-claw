# Sales-Claw OpenAI Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Anthropic-Demo-Pfad vollständig durch einen fail-closed OpenAI-Responses-Pfad ersetzen und OpenClaw ohne Provider-Fallback auf OpenAI umstellen.

**Architecture:** Ein neues kleines Modul kapselt Transport, Fehlerordnung, Structured Output und metadata-only Nutzungsdaten der OpenAI Responses API. `auto.py` behält Kandidatenauswahl, Claims und Entwurfstransaktion unverändert und konsumiert nur dieses Modul. OpenClaw und Compose erhalten explizite OpenAI-Konfiguration; vorhandene Laufzeit-Volumes werden in diesem Plan nicht verändert.

**Tech Stack:** Python 3.11, `urllib.request`, OpenAI Responses API, pytest, PostgreSQL-Testschema `sales_test`, Docker Compose Config ohne Daemon, JSON/YAML-Konfiguration.

**Spec:** `docs/moegliche-erweiterungen/01-openai-modellmigration.md`

## Global Constraints

- Es gibt keinen automatischen Anthropic-, OpenRouter- oder lokalen Modell-Fallback.
- Der Auto-Responder verwendet standardmäßig `gpt-5.6-luna`; OpenClaw verwendet `openai/gpt-5.6-terra`.
- Der Auto-Responder verlangt `OPENAI_API_KEY` und `OPENAI_MODEL` explizit; fehlende Werte beenden ihn mit Exit `2` vor jedem Modellaufruf.
- Requests gehen ausschließlich per HTTPS an `https://api.openai.com/v1/responses`; `OPENAI_BASE_URL` wird nicht unterstützt.
- Jeder Request setzt `store=false`, `max_output_tokens=1500` und Structured Output mit dem bestehenden Antwortschema.
- HTTP `408`, `429` und `5xx`, Netzwerkfehler und Timeouts sind transient; andere HTTP-Fehler und unbrauchbare Antworten sind permanent.
- API-Keys, Prompttext, Kundeninhalt und fremde Fehlerrümpfe erscheinen nie in Logs oder gespeicherten Fehlermeldungen.
- Die bestehende Claim-/Entwurfstransaktion, `approved_by='auto-betrieb'` und der alleinige Versand über `sales-dispatch` bleiben unverändert.
- Tests verwenden ausschließlich Fakes und `sales_test`; kein echter OpenAI-, OpenClaw-, Docker-Daemon-, WhatsApp- oder Versandaufruf.
- Die bekannten Fremdänderungen im ursprünglichen Checkout werden nicht editiert, gestasht, zurückgesetzt oder pauschal committet. Ausführung erfolgt in einem isolierten Worktree.
- Das bestehende OpenClaw-State-Volume wird nicht mutiert. Die Repo-Konfiguration ist nur der Seed für neue Instanzen; eine spätere Laufzeitmigration bleibt ein separates Betreiber-Gate.

---

### Task 1: OpenAI-Responses-Provider implementieren

**Files:**
- Create: `sales-mcp/openai_provider.py`
- Create: `sales-mcp/tests/test_openai_provider.py`

**Interfaces:**
- Consumes: `urllib.request.urlopen`, offizielle `POST /v1/responses`-Antworten.
- Produces: `OpenAIResult`, `OpenAIPermanentError`, `OpenAITransientError` und `create_structured_response(...)` für Task 2.

- [ ] **Step 1: RED-Tests für Requestvertrag und Erfolgsantwort schreiben**

`sales-mcp/tests/test_openai_provider.py` lädt das Modul direkt aus dem bestehenden Testpfad und verwendet einen Fake-Kontextmanager:

```python
import json

import openai_provider


class FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_request_is_stateless_structured_and_openai_only(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse({
            "id": "resp_test",
            "status": "completed",
            "error": None,
            "output_text": json.dumps({"antwort": "Gern!"}),
            "usage": {"input_tokens": 12, "output_tokens": 4,
                      "total_tokens": 16},
        })

    monkeypatch.setattr(openai_provider.urllib.request, "urlopen", fake_urlopen)
    result = openai_provider.create_structured_response(
        api_key="test-key",
        model="gpt-5.6-luna",
        instructions="Systemregeln",
        input_text="Kundenkontext",
        schema_name="auto_antwort",
        schema={"type": "object", "properties": {},
                "additionalProperties": False},
        max_output_tokens=1500,
        timeout_s=90,
    )

    request, timeout = calls[0]
    body = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert timeout == 90
    assert body == {
        "model": "gpt-5.6-luna",
        "instructions": "Systemregeln",
        "input": "Kundenkontext",
        "max_output_tokens": 1500,
        "store": False,
        "text": {"format": {
            "type": "json_schema",
            "name": "auto_antwort",
            "strict": True,
            "schema": {"type": "object", "properties": {},
                       "additionalProperties": False},
        }},
    }
    assert result.payload == {"antwort": "Gern!"}
    assert (result.response_id, result.total_tokens) == ("resp_test", 16)
```

- [ ] **Step 2: Requesttest ausführen und RED belegen**

Run: `python -m pytest sales-mcp/tests/test_openai_provider.py::test_request_is_stateless_structured_and_openai_only -q`

Expected: FAIL mit `ModuleNotFoundError: No module named 'openai_provider'`.

- [ ] **Step 3: Fehlerordnungs- und Redaktions-RED-Tests ergänzen**

Die Tests erzeugen `urllib.error.HTTPError` mit einem Rumpf, der `test-key`,
`Kundenkontext` und eine fremde Fehlermeldung enthält, und prüfen:

```python
import io
import socket
import urllib.error

import pytest


def call_provider():
    return openai_provider.create_structured_response(
        api_key="test-key",
        model="gpt-5.6-luna",
        instructions="Systemregeln",
        input_text="Kundenkontext",
        schema_name="auto_antwort",
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        max_output_tokens=1500,
        timeout_s=90,
    )


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_http_statuses_are_transient(monkeypatch, status):
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses", status, "failed", {},
        io.BytesIO(b'{"error":{"code":"rate_limit","message":"Kundenkontext test-key"}}'))
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: (_ for _ in ()).throw(error))
    with pytest.raises(openai_provider.OpenAITransientError) as caught:
        call_provider()
    assert str(status) in str(caught.value)
    assert "Kundenkontext" not in str(caught.value)
    assert "test-key" not in str(caught.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_http_statuses_are_not_retried(monkeypatch, status):
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses", status, "failed", {},
        io.BytesIO(b'{"error":{"code":"invalid_request","message":"secret"}}'))
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: (_ for _ in ()).throw(error))
    with pytest.raises(openai_provider.OpenAIPermanentError):
        call_provider()


def test_timeout_is_transient(monkeypatch):
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: (_ for _ in ()).throw(socket.timeout()))
    with pytest.raises(openai_provider.OpenAITransientError):
        call_provider()
```

Weitere Fälle prüfen ungültiges JSON, `status='failed'`, `status='incomplete'`,
ein gesetztes `error`-Objekt,
leeres `output_text`, nicht-JSON `output_text`, nicht-dictionary JSON sowie
fehlende/ungültige Nutzungszahlen als permanente Fehler beziehungsweise
`None`-Metadaten.

- [ ] **Step 4: Minimalen Provider implementieren**

`sales-mcp/openai_provider.py` enthält exakt diese öffentliche Form:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import urllib.error
import urllib.request

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIPermanentError(RuntimeError):
    pass


class OpenAITransientError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAIResult:
    payload: dict[str, object]
    response_id: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


def create_structured_response(
    *,
    api_key: str,
    model: str,
    instructions: str,
    input_text: str,
    schema_name: str,
    schema: dict[str, object],
    max_output_tokens: int,
    timeout_s: float,
) -> OpenAIResult:
    """Create one stateless structured response through the official endpoint."""
```

Die Funktion validiert vor dem Netzwerkzugriff: Key und Modell nicht leer,
Modell enthält keinen `/`, `max_output_tokens > 0`, `timeout_s > 0`,
`schema_name` nicht leer. Sie baut den Request exakt wie im RED-Test. Sie liest
fremde HTTP-Rümpfe nicht in Fehlermeldungen ein; die Meldung enthält nur
`OpenAI HTTP <status>`. JSON-/Antwortfehler verwenden generische Texte ohne
Rückgabeinhalt. `output_text` wird als JSON-Dictionary geparst. Tokenwerte
werden nur übernommen, wenn `type(value) is int` und `value >= 0`, sonst `None`.

- [ ] **Step 5: Provider-Suite GREEN ausführen**

Run: `python -m pytest sales-mcp/tests/test_openai_provider.py -q`

Expected: alle Provider-Tests bestanden; kein Netzwerkzugriff.

- [ ] **Step 6: Engen Commit erstellen**

```powershell
git add -- sales-mcp/openai_provider.py sales-mcp/tests/test_openai_provider.py
git commit -m "feat: add OpenAI Responses provider"
```

---

### Task 2: Auto-Responder auf den Provider umstellen

**Files:**
- Modify: `sales-mcp/auto.py`
- Modify: `sales-mcp/tests/test_auto.py`

**Interfaces:**
- Consumes: `openai_provider.create_structured_response(...)` und die drei öffentlichen Provider-Typen aus Task 1.
- Produces: unveränderte `antwort_erzeugen(kandidat) -> dict`, `AutoFehler`, `AutoTransient`, Claim-/Draft-Verhalten für Task 3.

- [ ] **Step 1: Auto-Tests auf den neuen Providervertrag umstellen und RED erzeugen**

Der Testhelper `_modell_ok` liefert künftig ein `OpenAIResult`:

```python
def _modell_ok(monkeypatch, antwort="Gern! Passt Ihnen Donnerstag 14 Uhr?",
               beraterin=False, stopp=False, begruendung=""):
    aufrufe = []

    def _stub(**kwargs):
        aufrufe.append(kwargs)
        return auto.OpenAIResult(
            payload={"antwort": antwort,
                     "beraterin_noetig": beraterin,
                     "stopp_wunsch": stopp,
                     "begruendung": begruendung},
            response_id="resp_test",
            input_tokens=20,
            output_tokens=8,
            total_tokens=28,
        )

    monkeypatch.setattr(auto, "create_structured_response", _stub)
    return aufrufe
```

Der Kontexttest erwartet danach:

```python
aufruf = aufrufe[0]
assert aufruf["api_key"] == auto.OPENAI_API_KEY
assert aufruf["model"] == auto.OPENAI_MODEL
assert aufruf["instructions"] == auto.SYSTEM_PROMPT
assert "Baeckermeisterin" in aufruf["input_text"]
assert "Kunde: Wie sichere ich meinen Betrieb ab?" in aufruf["input_text"]
assert aufruf["schema_name"] == "auto_antwort"
assert aufruf["schema"] == auto.ANTWORT_SCHEMA
assert aufruf["max_output_tokens"] == 1500
```

Fehlertests werfen `OpenAITransientError("OpenAI HTTP 429")` beziehungsweise
`OpenAIPermanentError("OpenAI HTTP 400")`. Refusal-/Status-Tests aus der
Anthropic-Antwortform entfallen; stattdessen prüfen Tests fehlende
Pflichtfelder, falsche Boolean-Typen, leere/zu lange Antwort und eine
providerseitig permanente unbrauchbare Antwort.

- [ ] **Step 2: Gezielte Auto-Tests RED ausführen**

Run: `python -m pytest sales-mcp/tests/test_auto.py -q`

Expected: FAIL, weil `auto.OpenAIResult`, `auto.OPENAI_MODEL` und der neue
Keyword-Aufruf noch fehlen.

- [ ] **Step 3: `auto.py` minimal migrieren**

Änderungen:

```python
from openai_provider import (
    OpenAIPermanentError,
    OpenAIResult,
    OpenAITransientError,
    create_structured_response,
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "").strip()
```

`ANTHROPIC_URL`, `ANTHROPIC_API_KEY`, `AUTO_MODELL`, `_api_aufruf` und alle
Anthropic-Response-Parser werden entfernt. `ANTWORT_SCHEMA` enthält nur das
innere JSON-Schema (`type`, `properties`, `required`,
`additionalProperties`), weil der Provider `type/name/strict` ergänzt.

`antwort_erzeugen` ruft den Provider genau einmal auf:

```python
try:
    result = create_structured_response(
        api_key=OPENAI_API_KEY,
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input_text=auftrag,
        schema_name="auto_antwort",
        schema=ANTWORT_SCHEMA,
        max_output_tokens=1500,
        timeout_s=HTTP_TIMEOUT_S,
    )
except OpenAITransientError as error:
    raise AutoTransient(str(error)) from None
except OpenAIPermanentError as error:
    raise AutoFehler(str(error)) from None

LOG.info(
    "OpenAI-Antwort: response_id=%s modell=%s input_tokens=%s "
    "output_tokens=%s total_tokens=%s",
    result.response_id,
    OPENAI_MODEL,
    result.input_tokens,
    result.output_tokens,
    result.total_tokens,
)
ergebnis = result.payload
```

Danach validiert `auto.py` strikt: `antwort` ist ein nichtleerer String,
`beraterin_noetig` und `stopp_wunsch` haben exakt Typ `bool`, `begruendung` ist
String, keine unbekannten Schlüssel, Antwortlänge höchstens 4000. Fehler bleiben
`AutoFehler`; es entsteht kein Draft.

`main()` prüft zuerst `OPENAI_API_KEY`, dann `OPENAI_MODEL`, meldet nur den
fehlenden Variablennamen und gibt `2` zurück. Das Startlog nennt
`OPENAI_MODEL`, nie Schlüssel oder Prompt.

- [ ] **Step 4: Auto-Suite GREEN ausführen**

Run: `python -m pytest sales-mcp/tests/test_auto.py -q`

Expected: alle vorhandenen und migrierten Auto-Tests bestanden; die Testsuite
erzwingt weiterhin `SALES_DB_SCHEMA=sales_test`.

- [ ] **Step 5: Gemeinsame Provider-/Auto-Suite ausführen**

Run: `python -m pytest sales-mcp/tests/test_openai_provider.py sales-mcp/tests/test_auto.py -q`

Expected: alle Tests bestanden, kein Netzwerk- oder Versandaufruf.

- [ ] **Step 6: Engen Commit erstellen**

```powershell
git add -- sales-mcp/auto.py sales-mcp/tests/test_auto.py
git commit -m "feat: migrate auto replies to OpenAI"
```

---

### Task 3: OpenClaw- und Compose-Konfiguration auf OpenAI festlegen

**Files:**
- Modify: `config/openclaw.json`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `scripts/seed-env.ps1`
- Create: `scripts/tests/test_openai_model_config.py`
- Modify: `scripts/tests/test_proxmox_compose.py`

**Interfaces:**
- Consumes: `OPENAI_API_KEY`, `OPENAI_MODEL` und den migrierten `sales-auto` aus Task 2.
- Produces: OpenAI-only Seed-/Compose-Vertrag und statische Gates für Task 4.

- [ ] **Step 1: Statische RED-Vertragstests schreiben**

`scripts/tests/test_openai_model_config.py` prüft JSON, YAML und
`.env.example` ohne Secretwerte:

```python
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_openclaw_uses_openai_without_fallbacks() -> None:
    config = json.loads((ROOT / "config/openclaw.json").read_text("utf-8"))
    model = config["agents"]["defaults"]["model"]
    assert model == {"primary": "openai/gpt-5.6-terra", "fallbacks": []}
    providers = config["models"]["providers"]
    assert set(providers) == {"openai"}
    assert providers["openai"]["models"] == [
        {"id": "gpt-5.6-terra", "name": "gpt-5.6-terra"}
    ]
    serialized = json.dumps(config)
    assert "anthropic" not in serialized.lower()
    assert "openrouter" not in serialized.lower()
    assert "api_key" not in serialized.lower()


def test_compose_passes_only_openai_model_credentials() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))
    claw_env = set(compose["services"]["sales-claw"]["environment"])
    auto_env = set(compose["services"]["sales-auto"]["environment"])
    assert "OPENAI_API_KEY=${OPENAI_API_KEY:-}" in claw_env
    assert "OPENAI_API_KEY=${OPENAI_API_KEY:-}" in auto_env
    assert "OPENAI_MODEL=${OPENAI_MODEL:-gpt-5.6-luna}" in auto_env
    assert not any("ANTHROPIC" in item or "OPENROUTER" in item
                   for item in claw_env | auto_env)


def test_env_example_documents_openai_only() -> None:
    text = (ROOT / ".env.example").read_text("utf-8")
    assert text.count("OPENAI_API_KEY=") == 1
    assert "OPENAI_MODEL=gpt-5.6-luna" in text
    assert "ANTHROPIC_API_KEY" not in text
    assert "OPENROUTER_API_KEY" not in text
    assert "OPENAI_BASE_URL" in text and "NICHT" in text


def test_seed_script_recovers_only_openai_credentials() -> None:
    text = (ROOT / "scripts/seed-env.ps1").read_text("utf-8")
    assert "$cfg.env.OPENAI_API_KEY" in text
    assert "OPENAI_API_KEY=$OpenAiKey" in text
    assert "OPENAI_MODEL=gpt-5.6-luna" in text
    assert "OPENROUTER" not in text
    assert "ANTHROPIC" not in text
```

- [ ] **Step 2: Konfigurationstests RED ausführen**

Run: `python -m pytest scripts/tests/test_openai_model_config.py -q`

Expected: vier Fehler wegen Anthropic/OpenRouter, fehlender OpenAI-Variablen
und der bisherigen OpenRouter-Seed-Logik.

- [ ] **Step 3: Seed-Konfiguration und Compose minimal ändern**

`config/openclaw.json` erhält:

```json
"model": {
  "primary": "openai/gpt-5.6-terra",
  "fallbacks": []
}
```

Unter `models.providers` bleibt ausschließlich:

```json
"openai": {
  "models": [
    {"id": "gpt-5.6-terra", "name": "gpt-5.6-terra"}
  ]
}
```

`docker-compose.yml` ersetzt beim Dienst `sales-claw`
`OPENROUTER_API_KEY` durch `OPENAI_API_KEY=${OPENAI_API_KEY:-}`. Beim Dienst
`sales-auto` werden `ANTHROPIC_API_KEY` und `AUTO_MODELL` durch
`OPENAI_API_KEY=${OPENAI_API_KEY:-}` und
`OPENAI_MODEL=${OPENAI_MODEL:-gpt-5.6-luna}` ersetzt. Kommentare nennen nur
OpenAI und behalten `restart: "no"` unverändert.

`.env.example` entfernt reale Beispielpräfixe und alle Anthropic-/OpenRouter-
Variablen. Es dokumentiert ausschließlich:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-luna
# OPENAI_BASE_URL wird bewusst NICHT unterstützt.
```

`scripts/seed-env.ps1` liest nur noch `$cfg.env.OPENAI_API_KEY`, schreibt
`TZ=Europe/Berlin`, `OPENAI_API_KEY=$OpenAiKey` und
`OPENAI_MODEL=gpt-5.6-luna` nach `.env` und meldet ausschließlich das Vorhandensein
des OpenAI-Schlüssels. Die Suche nach `sk-or-v1-`, das Schreiben von
`OPENROUTER_API_KEY` und dessen Statusausgabe entfallen vollständig. Der
Schlüsselwert selbst wird weiterhin nie ausgegeben.

- [ ] **Step 4: Bestehenden Compose-Test auf OpenAI-Dummywerte aktualisieren**

In `scripts/tests/test_proxmox_compose.py` wird die Dummy-Umgebung von
`OPENROUTER_API_KEY` auf `OPENAI_API_KEY=test-only` und
`OPENAI_MODEL=gpt-5.6-luna` umgestellt. Assertions über Services, Ports,
Restart-Policies und Tailscale bleiben unverändert.

- [ ] **Step 5: Statische und daemonfreie Compose-Gates GREEN ausführen**

Run:

```powershell
python -m pytest scripts/tests/test_openai_model_config.py scripts/tests/test_proxmox_compose.py -q
```

Expected: alle Tests bestanden. `test_proxmox_compose.py` verwendet nur
`docker compose config`; kein Docker-Daemon-Zugriff.

- [ ] **Step 6: Engen Commit erstellen**

```powershell
git add -- config/openclaw.json docker-compose.yml .env.example scripts/seed-env.ps1 scripts/tests/test_openai_model_config.py scripts/tests/test_proxmox_compose.py
git commit -m "feat: configure Sales-Claw for OpenAI"
```

---

### Task 4: Betriebsdokumentation und Gesamtverifikation aktualisieren

**Files:**
- Modify: `docs/02_ARCHITECTURE.md`
- Modify: `docs/03_RUNBOOK.md`
- Modify: `docs/08_PAIRING_ANLEITUNG.md`
- Modify: `docs/moegliche-erweiterungen/01-openai-modellmigration.md`

**Interfaces:**
- Consumes: Provider-, Auto- und Konfigurationsverträge aus Tasks 1–3.
- Produces: aktueller OpenAI-only Betriebsvertrag und lokaler Abschlussbeleg.

- [ ] **Step 1: Aktuelle Betriebsabschnitte auf OpenAI umstellen**

Nur gegenwärtige Sollzustände werden geändert; klar datierte historische
Messberichte in Backup-/Disaster-Recovery-Dokumenten bleiben unverändert.

Die drei Dokumente beschreiben:

- ChatGPT-Abos und API-Abrechnung sind getrennt.
- OpenClaw: `openai/gpt-5.6-terra`, keine Fallbacks.
- Auto-Responder: `gpt-5.6-luna` über Responses API, `store=false`.
- Secrets: nur `OPENAI_API_KEY` in `.env`, niemals in JSON, Logs oder Chat.
- Fehlender Key oder Modellname beendet `sales-auto` mit Exit `2`.
- Bestehende OpenClaw-State-Volumes werden nicht durch die Repo-Datei
  überschrieben; die Umstellung einer laufenden Instanz ist ein separates
  Betreiber-Gate und wird hier nicht ausgeführt.
- Kein Smoke-Test gegen die echte API ist Teil der Implementierung.

Die Erweiterungsnotiz erhält Status `lokal implementiert, Live-Aktivierung
offen` und verweist auf diesen Plan.

- [ ] **Step 2: Veraltete aktive Konfigurationsaussagen suchen**

Run:

```powershell
rg -n "ANTHROPIC_API_KEY|anthropic/claude|openrouter/free|OPENROUTER_API_KEY" .env.example config/openclaw.json docker-compose.yml sales-mcp/auto.py sales-mcp/tests/test_auto.py docs/02_ARCHITECTURE.md docs/03_RUNBOOK.md docs/08_PAIRING_ANLEITUNG.md
```

Expected: keine Treffer in aktiven Sollzuständen. Wenn ein Dokument einen
historischen, ausdrücklich als vergangen markierten Befund bewahrt, muss die
Zeile das Datum und den historischen Charakter enthalten; andernfalls wird sie
in diesem Task korrigiert.

- [ ] **Step 3: Vollständige fokussierte Suite ausführen**

Run:

```powershell
python -m pytest sales-mcp/tests/test_openai_provider.py sales-mcp/tests/test_auto.py scripts/tests/test_openai_model_config.py scripts/tests/test_proxmox_compose.py -q
```

Expected: alle Tests bestanden; `sales_test`-Wache aktiv; kein Netzwerk- oder
Docker-Daemon-Zugriff.

- [ ] **Step 4: Syntax-, Hygiene- und Scope-Gates ausführen**

Run:

```powershell
python -m py_compile sales-mcp/openai_provider.py sales-mcp/auto.py
git diff --check
git status --short --branch
git log --oneline -5
```

Expected: Syntax und Diff sauber; nur die geplanten Pfade sind gegenüber dem
Plan-Start verändert; Tasks 1–3 besitzen je einen engen Commit.

- [ ] **Step 5: Dokumentationscommit erstellen**

```powershell
git add -- docs/02_ARCHITECTURE.md docs/03_RUNBOOK.md docs/08_PAIRING_ANLEITUNG.md docs/moegliche-erweiterungen/01-openai-modellmigration.md
git commit -m "docs: describe OpenAI-only model runtime"
```

- [ ] **Step 6: Abschlussbericht mit expliziten Nicht-Claims erstellen**

Der Bericht trennt:

- lokal verifiziert: Providervertrag, Fehlerordnung, Structured Output,
  Auto-Responder-Bridge, OpenClaw-Seed und daemonfreie Compose-Konfiguration;
- nicht ausgeführt: echter OpenAI-Aufruf, API-Key-Prüfung, Kosten-/Rate-Limit-
  Beobachtung, OpenClaw-State-Migration, Containerstart, WhatsApp-Antwort,
  Deployment und Cutover;
- nächster einzelner Betreiber-Schritt: API-Billing und Projekt-Key einrichten,
  danach in einem separat autorisierten Lauf nur einen metadata-only
  OpenAI-Preflight ohne Kundeninhalt ausführen.
