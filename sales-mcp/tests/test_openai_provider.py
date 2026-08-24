import json
import http.client
import io
import os
import socket
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


class FakeRawResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


class FailingReadResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        raise http.client.IncompleteRead(b"partial", 12)


def assert_no_sensitive_exception_data(error, *sensitive_values):
    visited = set()

    def inspect(value):
        value_id = id(value)
        if value_id in visited:
            return
        visited.add(value_id)
        if isinstance(value, str):
            for sensitive in sensitive_values:
                assert sensitive not in value
        elif isinstance(value, bytes):
            decoded = value.decode("utf-8", errors="replace")
            for sensitive in sensitive_values:
                assert sensitive not in decoded
        elif isinstance(value, io.BytesIO):
            inspect(value.getvalue())
        elif isinstance(value, BaseException):
            inspect(value.__cause__)
            inspect(value.__context__)
            for attribute in vars(value).values():
                inspect(attribute)
        elif isinstance(value, dict):
            for key, item in value.items():
                inspect(key)
                inspect(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                inspect(item)

    inspect(error)


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
    with pytest.raises(openai_provider.OpenAIPermanentError) as caught:
        call_provider()
    assert str(caught.value) == f"OpenAI HTTP {status}"


def test_timeout_is_transient(monkeypatch):
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: (_ for _ in ()).throw(socket.timeout()))
    with pytest.raises(openai_provider.OpenAITransientError):
        call_provider()


def test_response_read_failure_is_transient(monkeypatch):
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: FailingReadResponse())
    with pytest.raises(openai_provider.OpenAITransientError):
        call_provider()


def test_http_error_does_not_retain_foreign_error_body(monkeypatch):
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses", 429, "failed", {},
        io.BytesIO(b'{"error":{"message":"Kundenkontext test-key foreign-body"}}'))
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: (_ for _ in ()).throw(error))
    with pytest.raises(openai_provider.OpenAITransientError) as caught:
        call_provider()
    assert_no_sensitive_exception_data(
        caught.value, "Kundenkontext", "test-key", "foreign-body")


def test_output_json_error_does_not_retain_customer_text(monkeypatch):
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen", lambda request, timeout: FakeResponse({
        "id": "resp_test",
        "status": "completed",
        "error": None,
        "output_text": "Kundenkontext test-key foreign-output",
        "usage": {},
    }))
    with pytest.raises(openai_provider.OpenAIPermanentError) as caught:
        call_provider()
    assert_no_sensitive_exception_data(
        caught.value, "Kundenkontext", "test-key", "foreign-output")


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_invalid_api_response_json_is_permanent(monkeypatch, body):
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: FakeRawResponse(body))
    with pytest.raises(openai_provider.OpenAIPermanentError) as caught:
        call_provider()
    assert "not-json" not in str(caught.value)


@pytest.mark.parametrize("payload", [
    {"id": "resp_test", "status": "failed", "error": None,
     "output_text": "{}", "usage": {}},
    {"id": "resp_test", "status": "incomplete", "error": None,
     "output_text": "{}", "usage": {}},
    {"id": "resp_test", "status": "completed", "error": {"message": "secret"},
     "output_text": "{}", "usage": {}},
    {"id": "resp_test", "status": "completed", "error": None,
     "output_text": "", "usage": {}},
    {"id": "resp_test", "status": "completed", "error": None,
     "output_text": "not-json", "usage": {}},
    {"id": "resp_test", "status": "completed", "error": None,
     "output_text": "[]", "usage": {}},
])
def test_invalid_completed_response_is_permanent(monkeypatch, payload):
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen",
                        lambda request, timeout: FakeResponse(payload))
    with pytest.raises(openai_provider.OpenAIPermanentError) as caught:
        call_provider()
    assert "secret" not in str(caught.value)
    assert "not-json" not in str(caught.value)


@pytest.mark.parametrize("usage, expected", [
    (None, (None, None, None)),
    ({}, (None, None, None)),
    ({"input_tokens": -1, "output_tokens": 3, "total_tokens": 2}, (None, 3, 2)),
    ({"input_tokens": True, "output_tokens": "3", "total_tokens": 2}, (None, None, 2)),
])
def test_missing_or_invalid_usage_is_exposed_as_none_metadata(monkeypatch, usage, expected):
    monkeypatch.setattr(openai_provider.urllib.request, "urlopen", lambda request, timeout: FakeResponse({
        "id": "resp_test",
        "status": "completed",
        "error": None,
        "output_text": "{}",
        "usage": usage,
    }))
    result = call_provider()
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == expected


@pytest.mark.parametrize("overrides", [
    {"api_key": ""},
    {"model": ""},
    {"model": "vendor/model"},
    {"schema_name": ""},
    {"max_output_tokens": 0},
    {"timeout_s": 0},
])
def test_invalid_request_arguments_fail_before_network_access(monkeypatch, overrides):
    def fail_if_called(request, timeout):
        pytest.fail("network access must not occur for invalid arguments")

    monkeypatch.setattr(openai_provider.urllib.request, "urlopen", fail_if_called)
    arguments = {
        "api_key": "test-key",
        "model": "gpt-5.6-luna",
        "instructions": "Systemregeln",
        "input_text": "Kundenkontext",
        "schema_name": "auto_antwort",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "max_output_tokens": 1500,
        "timeout_s": 90,
    }
    arguments.update(overrides)
    with pytest.raises(openai_provider.OpenAIPermanentError):
        openai_provider.create_structured_response(**arguments)
