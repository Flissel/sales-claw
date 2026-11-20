# Origin: new file for the sales-claw pause patch on vexaai/vexa-lite v0.12.28 (Apache-2.0).
# It extends the gateway test suite of Vexa (https://github.com/Vexa-ai/vexa, Apache License 2.0)
# and follows the style of tests/test_proxy.py.
"""The edge forwards the recording pause and resume verbatim to meeting-api.

``POST /bots/{platform}/{native_meeting_id}/pause`` and ``.../resume`` are bot controls, so the
edge treats them like ``speak``: scope ``bot``, the caller's identity re-stamped as
``x-user-id``, the body (``{"at_ms": ...}``) passed through untouched, and meeting-api's verdict
(202 on success, 404/409/422/503 otherwise) returned as it is.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from gateway import ROUTE_SCOPES, create_app

from conftest import VALID_KEY, VALID_USER, FakeAuthorizer, FakeDownstream, FakeRedis

AUTH = {"x-api-key": VALID_KEY}
ROUTES = ("pause", "resume")


def _client(authorizer=None, status_code=202, body=None):
    downstream = FakeDownstream(status_code=status_code,
                                body=body if body is not None else {"status": "accepted"})
    app = create_app(authorizer or FakeAuthorizer(), downstream, FakeRedis())
    return TestClient(app), downstream


@pytest.mark.parametrize("action", ROUTES)
def test_route_is_declared_with_scope_bot(action):
    assert set(ROUTE_SCOPES[("POST", f"/bots/{{platform}}/{{native_meeting_id}}/{action}")]) == {"bot"}


@pytest.mark.parametrize("action", ROUTES)
def test_forwards_verbatim_to_meeting_api(action):
    client, downstream = _client(body={"status": f"{action}_requested", "meeting_id": 5})
    raw = b'{"at_ms": 1784000000000}' if action == "pause" else b"{}"
    r = client.post(f"/bots/jitsi/raum-1/{action}", headers={**AUTH, "content-type": "application/json"},
                    content=raw)
    assert r.status_code == 202
    assert r.json() == {"status": f"{action}_requested", "meeting_id": 5}
    assert downstream.last["method"] == "POST"
    assert downstream.last["url"].endswith(f"/bots/jitsi/raum-1/{action}")
    assert "meeting-api" in downstream.last["url"]
    assert downstream.last["content"] == raw
    headers = {k.lower(): v for k, v in downstream.last["headers"].items()}
    assert headers["x-user-id"] == str(VALID_USER["user_id"])


@pytest.mark.parametrize("status", [404, 409, 422, 503])
def test_meeting_api_verdict_is_passed_through(status):
    client, _ = _client(status_code=status, body={"detail": "x"})
    r = client.post("/bots/jitsi/raum-1/pause", headers=AUTH, json={"at_ms": 1784000000000})
    assert r.status_code == status
    assert r.json() == {"detail": "x"}


@pytest.mark.parametrize("action", ROUTES)
def test_missing_key_is_401_and_nothing_is_forwarded(action):
    client, downstream = _client()
    r = client.post(f"/bots/jitsi/raum-1/{action}", json={"at_ms": 1784000000000})
    assert r.status_code == 401
    assert downstream.last is None


@pytest.mark.parametrize("action", ROUTES)
def test_key_without_bot_scope_is_403_and_nothing_is_forwarded(action):
    tx_only = FakeAuthorizer(user={**VALID_USER, "scopes": ["tx"]})
    client, downstream = _client(authorizer=tx_only)
    r = client.post(f"/bots/jitsi/raum-1/{action}", headers=AUTH, json={"at_ms": 1784000000000})
    assert r.status_code == 403
    assert downstream.last is None


def test_pause_body_is_not_reinterpreted_by_the_edge():
    """Validation of ``at_ms`` belongs to meeting-api (422 there); the edge must not drop,
    coerce or reorder the field."""
    client, downstream = _client()
    client.post("/bots/jitsi/raum-1/pause", headers=AUTH, json={"at_ms": "nicht-int"})
    assert json.loads(downstream.last["content"]) == {"at_ms": "nicht-int"}
