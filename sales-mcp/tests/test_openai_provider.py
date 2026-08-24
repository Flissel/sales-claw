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


_DEFAULT_OUTPUT = object()


def wire_response(
    output_text: str = '{"antwort": "Gern!"}',
    *,
    output: object = _DEFAULT_OUTPUT,
    status: str = "completed",
    error: object | None = None,
    usage: object = ...,
) -> dict[str, object]:
    """Official raw Responses wire shape, including a reasoning output item."""
    if output is _DEFAULT_OUTPUT:
        output = [
            {
                "id": "rs_test",
                "type": "reasoning",
                "summary": [],
            },
            {
                "id": "msg_test",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            },
        ]
    if usage is ...:
        usage = {
            "input_tokens": 12,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 4,
            "output_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 16,
        }
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1787600000,
        "status": status,
        "completed_at": 1787600001,
        "error": error,
        "incomplete_details": None,
        "instructions": "Systemregeln",
        "max_output_tokens": 1500,
        "model": "gpt-5.6-luna",
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": "medium", "summary": None},
        "store": False,
        "temperature": None,
        "text": {"format": {"type": "json_schema"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": None,
        "truncation": "disabled",
        "usage": usage,
        "user": None,
        "metadata": {},
    }


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
        return FakeResponse(wire_response())

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
    monkeypatch.setattr(
        openai_provider.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(
            wire_response("Kundenkontext test-key foreign-output", usage={})
        ),
    )
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


@pytest.mark.parametrize(
    "payload",
    [
        wire_response(status="failed", usage={}),
        wire_response(status="incomplete", usage={}),
        wire_response(error={"message": "secret"}, usage={}),
        wire_response("", usage={}),
        wire_response("not-json", usage={}),
        wire_response("[]", usage={}),
    ],
)
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
    monkeypatch.setattr(
        openai_provider.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(
            wire_response("{}", usage=usage)
        ),
    )
    result = call_provider()
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == expected


def test_sdk_only_top_level_output_text_is_rejected(monkeypatch):
    monkeypatch.setattr(
        openai_provider.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(
            {
                "id": "resp_test",
                "status": "completed",
                "error": None,
                "output_text": "{}",
                "usage": {},
            }
        ),
    )

    with pytest.raises(openai_provider.OpenAIPermanentError):
        call_provider()


def test_refusal_content_is_rejected_without_retaining_refusal(monkeypatch):
    refusal = "Kundenkontext test-key foreign-refusal"
    output = [
        {"id": "rs_test", "type": "reasoning", "summary": []},
        {
            "id": "msg_test",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "refusal", "refusal": refusal}],
        },
    ]
    monkeypatch.setattr(
        openai_provider.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(wire_response(output=output)),
    )

    with pytest.raises(openai_provider.OpenAIPermanentError) as caught:
        call_provider()
    assert_no_sensitive_exception_data(
        caught.value, "Kundenkontext", "test-key", "foreign-refusal"
    )


@pytest.mark.parametrize(
    "output",
    [
        [],
        None,
        [{"id": "call_test", "type": "function_call", "name": "unknown"}],
        [
            {
                "id": "msg_test",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "reasoning_text", "text": "{}"}],
            }
        ],
        [
            {
                "id": "msg_test",
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "{}",
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ],
        [
            {
                "id": "msg_test",
                "type": "message",
                "status": "completed",
                "role": "user",
                "content": [
                    {
                        "type": "output_text",
                        "text": "{}",
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ],
    ],
    ids=[
        "empty-output",
        "non-list-output",
        "unknown-output-item",
        "unknown-content-item",
        "unfinished-message",
        "non-assistant-message",
    ],
)
def test_unknown_or_unusable_raw_output_is_rejected(monkeypatch, output):
    monkeypatch.setattr(
        openai_provider.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(wire_response(output=output)),
    )

    with pytest.raises(openai_provider.OpenAIPermanentError):
        call_provider()


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
