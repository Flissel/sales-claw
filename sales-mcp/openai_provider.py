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


def _valid_token_count(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _validate_request(
    api_key: str,
    model: str,
    schema_name: str,
    max_output_tokens: int,
    timeout_s: float,
) -> None:
    if not api_key.strip() or not model.strip() or "/" in model:
        raise OpenAIPermanentError("OpenAI request is invalid")
    if not schema_name.strip() or max_output_tokens <= 0 or timeout_s <= 0:
        raise OpenAIPermanentError("OpenAI request is invalid")


def _read_response(request: urllib.request.Request, timeout_s: float) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code in (408, 429) or 500 <= error.code <= 599:
            raise OpenAITransientError(f"OpenAI HTTP {error.code}") from error
        raise OpenAIPermanentError(f"OpenAI HTTP {error.code}") from error
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        raise OpenAITransientError("OpenAI request failed") from error


def _parse_response(body: bytes) -> OpenAIResult:
    try:
        response = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenAIPermanentError("OpenAI response was not valid JSON") from error

    if not isinstance(response, dict):
        raise OpenAIPermanentError("OpenAI response object is invalid")
    if response.get("status") != "completed":
        raise OpenAIPermanentError("OpenAI response status is invalid")
    if response.get("error") is not None:
        raise OpenAIPermanentError("OpenAI response contains an error")

    output_text = response.get("output_text")
    if not isinstance(output_text, str) or not output_text.strip():
        raise OpenAIPermanentError("OpenAI response output is invalid")
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise OpenAIPermanentError("OpenAI response output is invalid") from error
    if not isinstance(payload, dict):
        raise OpenAIPermanentError("OpenAI response output is invalid")

    response_id = response.get("id")
    if not isinstance(response_id, str) or not response_id:
        raise OpenAIPermanentError("OpenAI response id is invalid")

    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return OpenAIResult(
        payload=payload,
        response_id=response_id,
        input_tokens=_valid_token_count(usage.get("input_tokens")),
        output_tokens=_valid_token_count(usage.get("output_tokens")),
        total_tokens=_valid_token_count(usage.get("total_tokens")),
    )


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
    _validate_request(api_key, model, schema_name, max_output_tokens, timeout_s)
    body = {
        "model": model,
        "instructions": instructions,
        "input": input_text,
        "max_output_tokens": max_output_tokens,
        "store": False,
        "text": {"format": {
            "type": "json_schema",
            "name": schema_name,
            "strict": True,
            "schema": schema,
        }},
    }
    try:
        data = json.dumps(body).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise OpenAIPermanentError("OpenAI request is invalid") from error
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return _parse_response(_read_response(request, timeout_s))
